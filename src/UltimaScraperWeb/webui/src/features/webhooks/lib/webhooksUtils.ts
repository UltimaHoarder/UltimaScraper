import type { WebhookMessage, WebhookMessageCategory } from '../../../hooks/useWebhookStream';

export type CategoryFilter = 'all' | WebhookMessageCategory;
export type SiteKey = 'onlyfans' | 'fansly';

export const categoryLabels: Record<CategoryFilter, string> = {
  all: 'All',
  backend: 'Backend',
  usapi: 'Sites (USAPI)',
  system: 'System',
};

export const siteLabels: Record<SiteKey, string> = {
  onlyfans: 'OnlyFans',
  fansly: 'Fansly',
};

function isChatMessageEvent(message: WebhookMessage): boolean {
  if (!message || !message.payload || typeof message.payload !== 'object') {
    return false;
  }
  if ('api2_chat_message' in message.payload) {
    return true;
  }
  if ('message' in message.payload && typeof message.payload.message === 'string') {
    return true;
  }
  return Boolean(
    message.payload.source_id && String(message.payload.source_id).includes(':ws:'),
  );
}

export function filterWebhookMessages(
  messages: WebhookMessage[],
  categoryFilter: CategoryFilter,
  showAllEvents: boolean,
  filterText: string,
) {
  let filtered =
    categoryFilter === 'all'
      ? messages
      : messages.filter((message) => message.category === categoryFilter);

  if (!showAllEvents) {
    filtered = filtered.filter((message) => {
      const isWebhookEvent =
        message.event === 'subscription_processing' ||
        message.event === 'scrape_progress' ||
        message.event === 'download_progress' ||
        message.event === 'chat_message' ||
        message.event === 'webhook' ||
        message.event === 'webhook_message' ||
        message.event === 'websocket_message' ||
        message.event === 'subscription_added' ||
        Boolean(message.eventType) ||
        isChatMessageEvent(message);
      return isWebhookEvent;
    });
  }

  if (!filterText.trim()) {
    return filtered;
  }

  const lower = filterText.toLowerCase();
  return filtered.filter((message) => {
    const raw = JSON.stringify(message.payload).toLowerCase();
    return (
      message.event.toLowerCase().includes(lower) ||
      (message.eventType?.toLowerCase().includes(lower) ?? false) ||
      raw.includes(lower)
    );
  });
}
