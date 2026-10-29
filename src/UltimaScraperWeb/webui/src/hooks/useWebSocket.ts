/**
 * WebSocket hook for real-time event updates
 *
 * Features:
 * - One shared connection per URL and tab; every hook registers on it
 * - Topic subscriptions: the server sends a connection only what its hooks ask for
 * - Automatic reconnection on disconnect, with a resync event so views refetch
 * - Ping/heartbeat to keep connection alive (especially on mobile)
 * - Visibility change handler to reconnect when tab becomes visible
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { backendUrl } from '../api/http';

interface WebSocketChatMessage {
  fromUser?: {
    id?: number;
  };
  user_id?: number;
  userId?: number;
}

export interface WebSocketEvent {
  type: string;
  event?: string;
  data?: unknown;
  site?: string;
  auth_id?: number;
  chat_user_id?: number;
  api2_chat_message?: WebSocketChatMessage;
  new_message?: WebSocketChatMessage;
  [key: string]: unknown;
}

/**
 * Server topics: 'jobs' (job-level changes, per-task activity coalesced into
 * job_changed), `job:<id>` (every event for one job), 'logs', 'chats',
 * 'system' and 'api_hooks' (per-call API hooks).
 */
export type EventTopic = 'jobs' | 'logs' | 'chats' | 'system' | 'api_hooks' | 'favourites' | 'profiles' | `job:${string}`;

/** Sent to every hook after a reconnect: events may have been missed, refetch state. */
export const RESYNC_EVENT: WebSocketEvent = { type: 'resync', event: 'job_resync' };

export interface UseWebSocketOptions {
  url: string;
  /** Topics this hook needs; defaults to job-level changes and system events. */
  topics?: EventTopic[];
  onMessage?: (event: WebSocketEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnect?: boolean;
  reconnectInterval?: number;
  reconnectAttempts?: number;
  /** Ping interval in ms to keep connection alive (default: 25000ms) */
  pingInterval?: number;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: WebSocketEvent | null;
  lastActivity: number;
  send: (data: unknown) => void;
  reconnect: () => void;
}

const DEFAULT_TOPICS: EventTopic[] = ['jobs', 'system'];
// Keep the connection briefly when the last hook unmounts (page navigation).
const IDLE_CLOSE_MS = 2000;

interface Listener {
  topics: EventTopic[];
  message: (event: WebSocketEvent) => void;
  open: () => void;
  close: () => void;
  error: (error: Event) => void;
}

interface SocketSettings {
  reconnect: boolean;
  reconnectInterval: number;
  reconnectAttempts: number;
  pingInterval: number;
}

class SharedSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private reconnectCount = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private subscribed = '';
  private opened = false;
  lastPong = Date.now();
  connected = false;

  private url: string;
  private settings: SocketSettings;

  constructor(url: string, settings: SocketSettings) {
    this.url = url;
    this.settings = settings;
  }

  add(listener: Listener): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
    this.listeners.add(listener);
    if (this.connected) {
      listener.open();
      this.subscribe();
    } else {
      this.connect();
    }
  }

  remove(listener: Listener): void {
    this.listeners.delete(listener);
    if (this.listeners.size === 0) {
      this.idleTimer = setTimeout(() => this.shutdown(), IDLE_CLOSE_MS);
    } else {
      this.subscribe();
    }
  }

  /** Re-send the union of topics after a hook's topics change. */
  subscribe(): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const topics = [...new Set([...this.listeners].flatMap((listener) => listener.topics))].sort();
    const key = topics.join('|');
    if (key === this.subscribed) return;
    this.subscribed = key;
    this.ws.send(JSON.stringify({ type: 'subscribe', topics }));
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn('[WebSocket] Cannot send, not connected');
    }
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    let ws: WebSocket;
    try {
      ws = new WebSocket(backendUrl(this.url));
    } catch (error) {
      console.error('[WebSocket] Failed to create WebSocket:', error);
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      const reconnected = this.opened;
      this.opened = true;
      this.connected = true;
      this.reconnectCount = 0;
      this.lastPong = Date.now();
      this.subscribed = '';
      this.subscribe();
      for (const listener of [...this.listeners]) {
        listener.open();
        // Events published while disconnected are not replayed: refetch instead.
        if (reconnected) listener.message(RESYNC_EVENT);
      }
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.ping(), this.settings.pingInterval);
    };

    ws.onmessage = (message) => {
      if (this.ws !== ws) return;
      this.lastPong = Date.now();
      let data: WebSocketEvent;
      try {
        data = JSON.parse(message.data) as WebSocketEvent;
      } catch (error) {
        console.error('[WebSocket] Failed to parse message:', error);
        return;
      }
      if (data.type === 'pong' || data.type === 'subscribed') return;
      for (const listener of [...this.listeners]) listener.message(data);
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (!this.listeners.size) ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      this.connected = false;
      this.subscribed = '';
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = null;
      for (const listener of [...this.listeners]) listener.close();
      const { reconnect, reconnectAttempts, reconnectInterval } = this.settings;
      if (this.listeners.size && reconnect && this.reconnectCount < reconnectAttempts) {
        this.reconnectCount += 1;
        this.reconnectTimer = setTimeout(() => this.connect(), reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      if (this.ws !== ws) return;
      for (const listener of [...this.listeners]) listener.error(error);
    };
  }

  private ping(): void {
    const ws = this.ws;
    if (ws?.readyState !== WebSocket.OPEN) return;
    // No pong or message for two intervals: the connection is dead.
    if (Date.now() - this.lastPong > this.settings.pingInterval * 2) {
      ws.close();
      return;
    }
    try {
      ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
    } catch (error) {
      console.warn('[WebSocket] Ping failed:', error);
    }
  }

  /** Reconnect if disconnected or stale; used on visibility, network and manual reconnect. */
  revive(force = false): void {
    if (!this.listeners.size) return;
    const stale = Date.now() - this.lastPong > this.settings.pingInterval * 2;
    if (force || !this.ws || this.ws.readyState !== WebSocket.OPEN || stale) {
      this.reconnectCount = 0;
      if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.close();
      else this.connect();
    } else {
      this.ping();
    }
  }

  /** Close now, rather than after the idle delay, if nothing listens. */
  closeIfUnused(): void {
    if (this.listeners.size) return;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.shutdown();
  }

  private shutdown(): void {
    this.idleTimer = null;
    if (this.listeners.size) return;
    sockets.delete(this.url);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      ws.close();
    }
  }
}

const sockets = new Map<string, SharedSocket>();
let windowHandlersInstalled = false;

function sharedSocket(url: string, settings: SocketSettings): SharedSocket {
  let socket = sockets.get(url);
  if (!socket) {
    socket = new SharedSocket(url, settings);
    sockets.set(url, socket);
  }
  if (!windowHandlersInstalled && typeof window !== 'undefined') {
    windowHandlersInstalled = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') for (const s of sockets.values()) s.revive();
    });
    window.addEventListener('online', () => {
      for (const s of sockets.values()) s.revive(true);
    });
  }
  return socket;
}

/**
 * Close every socket nothing listens to any more, without the idle delay.
 * Switching backends unmounts the old one's listeners; its sockets go at once.
 */
export function closeUnusedSockets(): void {
  for (const socket of [...sockets.values()]) socket.closeIfUnused();
}

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    topics = DEFAULT_TOPICS,
    onMessage,
    onOpen,
    onClose,
    onError,
    reconnect = true,
    reconnectInterval = 3000,
    reconnectAttempts = 10,
    pingInterval = 25000, // Default 25s ping to keep connection alive
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketEvent | null>(null);
  const [lastActivity, setLastActivity] = useState<number>(() => Date.now());
  const socketRef = useRef<SharedSocket | null>(null);
  const listenerRef = useRef<Listener | null>(null);
  const pendingMessageRef = useRef<WebSocketEvent | null>(null);
  const activityFlushRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  const topicsKey = [...topics].sort().join('|');

  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
  }, [onMessage, onOpen, onClose, onError]);

  useEffect(() => {
    let mounted = true;
    const socket = sharedSocket(url, { reconnect, reconnectInterval, reconnectAttempts, pingInterval });
    const listener: Listener = {
      topics: topicsKey ? (topicsKey.split('|') as EventTopic[]) : [],
      message: (event) => {
        if (!mounted) return;
        pendingMessageRef.current = event;
        onMessageRef.current?.(event);
        // Keep the public snapshot at most once per second; callbacks still
        // receive every event without rendering the entire page per message.
        if (!activityFlushRef.current) {
          activityFlushRef.current = setTimeout(() => {
            activityFlushRef.current = null;
            if (!mounted) return;
            setLastActivity(Date.now());
            setLastMessage(pendingMessageRef.current);
            pendingMessageRef.current = null;
          }, 1000);
        }
      },
      open: () => {
        if (!mounted) return;
        setIsConnected(true);
        onOpenRef.current?.();
      },
      close: () => {
        if (!mounted) return;
        setIsConnected(false);
        onCloseRef.current?.();
      },
      error: (error) => {
        if (mounted) onErrorRef.current?.(error);
      },
    };
    socketRef.current = socket;
    listenerRef.current = listener;
    socket.add(listener);
    return () => {
      mounted = false;
      if (activityFlushRef.current) clearTimeout(activityFlushRef.current);
      activityFlushRef.current = null;
      pendingMessageRef.current = null;
      socket.remove(listener);
    };
  }, [url, reconnect, reconnectInterval, reconnectAttempts, pingInterval, topicsKey]);

  const send = useCallback((data: unknown) => {
    socketRef.current?.send(data);
  }, []);

  const manualReconnect = useCallback(() => {
    socketRef.current?.revive(true);
  }, []);

  return {
    isConnected,
    lastMessage,
    lastActivity,
    send,
    reconnect: manualReconnect,
  };
}
