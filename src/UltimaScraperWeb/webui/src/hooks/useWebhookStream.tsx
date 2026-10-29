import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getWebSocketBaseUrl } from '../api/http';
import { useWebSocket, type WebSocketEvent } from './useWebSocket';

export type WebhookMessageCategory = 'backend' | 'usapi' | 'system';

export type WebhookMessage = {
  id: string;
  payloadId?: string;
  receivedAt: string;
  event: string;
  eventType?: string;
  payload: WebSocketEvent;
  category: WebhookMessageCategory;
};

type WebhookStreamContextValue = {
  messages: WebhookMessage[];
  isConnected: boolean;
  lastActivity: number;
  clearMessages: () => void;
  /** Subscribe to per-call API hooks until the returned function is called. */
  watch: () => () => void;
};

const WebhookStreamContext = createContext<WebhookStreamContextValue | null>(null);

/**
 * Detect the category of a webhook message based on its content.
 * - backend: Job/task events from the backend system (job_started, task_completed, etc.)
 * - usapi: Events from site APIs (chat messages, subscription updates, websocket events)
 * - system: System-level events (queue_depth, system_health, heartbeat)
 */
function detectCategory(event: WebSocketEvent, eventName: string): WebhookMessageCategory {
  // System events
  if (
    eventName === 'queue_depth' ||
    eventName === 'system_health' ||
    eventName === 'heartbeat' ||
    event.type === 'queue_depth' ||
    event.type === 'system_health'
  ) {
    return 'system';
  }

  // USAPI/Site events - chat messages, websocket streams, subscription events from sites
  if (
    'api2_chat_message' in event ||
    eventName === 'api2_chat_message' ||
    eventName === 'chat_message' ||
    eventName === 'websocket_message' ||
    eventName === 'subscription_added' ||
    eventName === 'subscription_removed' ||
    eventName === 'message_received' ||
    eventName === 'story_update' ||
    eventName === 'post_update' ||
    eventName === 'stream_event' ||
    (event.source_id && String(event.source_id).includes(':ws:')) ||
    event.channel === 'ultimascraper:websocket:stream'
  ) {
    return 'usapi';
  }

  // Backend job/task events
  if (
    eventName.includes('job_') ||
    eventName.includes('task_') ||
    eventName.startsWith('JOB_') ||
    eventName.startsWith('TASK_') ||
    event.job_id ||
    event.task_id ||
    eventName === 'scrape_progress' ||
    eventName === 'download_progress' ||
    eventName === 'subscription_processing'
  ) {
    return 'backend';
  }

  // Default to backend for unrecognized events
  return 'backend';
}

export const MAX_MESSAGES = 10_000;
const MAX_STRING_LENGTH = 2000;
const MAX_OBJECT_KEYS = 40;
const MAX_ARRAY_ITEMS = 40;
const MAX_DEPTH = 4;
const FLUSH_INTERVAL_MS = 250; // Batch WS events and flush at most every 250ms

function truncateString(value: string): string {
  if (value.length <= MAX_STRING_LENGTH) return value;
  const extra = value.length - MAX_STRING_LENGTH;
  return `${value.slice(0, MAX_STRING_LENGTH)}... [truncated ${extra} chars]`;
}

function compactPayload(value: unknown, depth = 0): unknown {
  if (
    value === null ||
    value === undefined ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }

  if (typeof value === 'string') {
    return truncateString(value);
  }

  if (typeof value !== 'object') {
    return String(value);
  }

  if (depth >= MAX_DEPTH) {
    return '[truncated-depth]';
  }

  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_ARRAY_ITEMS).map((item) => compactPayload(item, depth + 1));
    if (value.length > MAX_ARRAY_ITEMS) {
      items.push(`[+${value.length - MAX_ARRAY_ITEMS} more items]`);
    }
    return items;
  }

  const entries = Object.entries(value as Record<string, unknown>);
  const compacted: Record<string, unknown> = {};
  for (const [key, item] of entries.slice(0, MAX_OBJECT_KEYS)) {
    compacted[key] = compactPayload(item, depth + 1);
  }
  if (entries.length > MAX_OBJECT_KEYS) {
    compacted.__truncated_keys__ = entries.length - MAX_OBJECT_KEYS;
  }
  return compacted;
}

function buildWebhookMessage(event: WebSocketEvent): WebhookMessage | null {
  if (!event || typeof event !== 'object') return null;
  if (event.type === 'log' || event.type === 'ack' || event.type === 'pong') return null;

  const eventName =
    (event.event as string | undefined) ||
    (event.type as string | undefined) ||
    ('api2_chat_message' in event ? 'api2_chat_message' : undefined) ||
    'message';
  const eventType = (event.event_type as string | undefined) || undefined;
  const timestamp =
    (event.timestamp as string | undefined) ||
    (event.stored_at as string | undefined) ||
    new Date().toISOString();

  const payloadId = (event.id as string) || (event.job_id as string) || (event.task_id as string);
  const category = detectCategory(event, eventName);

  return {
    id: `${eventName}-${timestamp}-${Math.random().toString(36).slice(2, 8)}`,
    payloadId,
    receivedAt: timestamp,
    event: eventName,
    eventType,
    payload: compactPayload(event) as WebSocketEvent,
    category,
  };
}

export function WebhookStreamProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<WebhookMessage[]>([]);
  // Per-call API hooks are subscribed only while a webhooks view is mounted;
  // workers stop publishing them when nobody watches.
  const [watchers, setWatchers] = useState(0);
  const watch = useCallback(() => {
    setWatchers((count) => count + 1);
    return () => setWatchers((count) => count - 1);
  }, []);
  const pendingRef = useRef<WebhookMessage[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Flush pending messages into state in a single batch
  const flushPending = useCallback(() => {
    flushTimerRef.current = null;
    const batch = pendingRef.current;
    if (batch.length === 0) return;
    pendingRef.current = [];

    setMessages((prev) => {
      // Build a set of existing payloadIds for O(1) dedup
      const existingIds = new Set<string>();
      for (const m of prev) {
        if (m.payloadId) existingIds.add(m.payloadId);
      }

      const newMessages: WebhookMessage[] = [];
      for (const msg of batch) {
        if (msg.payloadId && existingIds.has(msg.payloadId)) continue;
        if (msg.payloadId) existingIds.add(msg.payloadId);
        newMessages.push(msg);
      }

      if (newMessages.length === 0) return prev;

      // Prepend new messages and cap at MAX_MESSAGES
      const merged = [...newMessages, ...prev];
      return merged.length > MAX_MESSAGES ? merged.slice(0, MAX_MESSAGES) : merged;
    });
  }, []);

  const handleWebSocketMessage = useCallback((wsEvent: WebSocketEvent) => {
    const message = buildWebhookMessage(wsEvent);
    if (!message) return;

    // Skip high-frequency progress events from the webhook store entirely —
    // they are only useful on the DashboardPage which has its own handler.
    const evt = message.event;
    if (evt === 'scrape_progress' || evt === 'download_progress' || evt === 'task_progress') {
      return;
    }

    pendingRef.current.push(message);

    // Schedule a flush if one isn't already pending
    if (!flushTimerRef.current) {
      flushTimerRef.current = setTimeout(flushPending, FLUSH_INTERVAL_MS);
    }
  }, [flushPending]);

  const { isConnected, lastActivity } = useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    topics: watchers > 0 ? ['jobs', 'system', 'api_hooks'] : ['jobs', 'system'],
    onMessage: handleWebSocketMessage,
  });

  const clearMessages = useCallback(() => {
    setMessages([]);
    pendingRef.current = [];
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      pendingRef.current = [];
    };
  }, []);

  const value = useMemo(
    () => ({
      messages,
      isConnected,
      lastActivity,
      clearMessages,
      watch,
    }),
    [messages, isConnected, lastActivity, clearMessages, watch]
  );

  return (
    <WebhookStreamContext.Provider value={value}>
      {children}
    </WebhookStreamContext.Provider>
  );
}

export function useWebhookStream(): WebhookStreamContextValue {
  const context = useContext(WebhookStreamContext);
  if (!context) {
    throw new Error('useWebhookStream must be used within a WebhookStreamProvider');
  }
  const { watch } = context;
  useEffect(() => watch(), [watch]);
  return context;
}
