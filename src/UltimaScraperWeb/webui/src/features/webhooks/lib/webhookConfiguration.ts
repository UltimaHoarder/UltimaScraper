import type { SiteWebhookRouting, WebhookConfiguration, WebhookHookDefinition, WebhooksResponse, WebhookSite } from '../../../api/types/webhooks';

// Older backends can display a draft while the editable API is being activated.
export const webhookHookCatalog: WebhookHookDefinition[] = [
  { id: 'auth', label: 'Auth', description: 'Accounts added, updated, or removed.', sites: ['onlyfans', 'fansly'], group: 'Account' },
  { id: 'download', label: 'Download', description: 'Completed or failed download batches.', sites: ['onlyfans', 'fansly'], group: 'Downloads' },
  { id: 'chat_message', label: 'Chat messages', description: 'Incoming API chat messages.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'subscriber', label: 'New subscribers', description: 'New subscriptions, including trial subscribers.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'post_published', label: 'Published posts', description: 'Notifications when a post is published.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'post_updated', label: 'Updated posts', description: 'Notifications when a post changes.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'stream_started', label: 'Live streams', description: 'New stream notifications.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'comment', label: 'Comments', description: 'New comment notifications.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'price_changed', label: 'Price changes', description: 'Subscription price changes.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'online', label: 'Online activity', description: 'User online notifications.', sites: ['onlyfans'], group: 'Site messages' },
  { id: 'site_message', label: 'All site messages', description: 'All incoming site notifications except connection keepalives.', sites: ['onlyfans'], group: 'Site messages' },
];

export function webhookConfiguration(data: WebhooksResponse): WebhookConfiguration {
  if (data.configuration) return data.configuration;
  const sites = {} as Record<WebhookSite, SiteWebhookRouting>;
  for (const site of ['onlyfans', 'fansly'] as const) {
    const routing: SiteWebhookRouting = { destinations: [], rules: [] };
    for (const hook of ['auth', 'download'] as const) {
      const legacy = data.sites[site][hook];
      if (!legacy.url) continue;
      let destination = routing.destinations.find((item) => item.url === legacy.url);
      if (!destination) {
        destination = { id: `legacy-${hook}`, name: `${hook === 'auth' ? 'Auth' : 'Download'} destination`, url: legacy.url, format: 'discord' };
        routing.destinations.push(destination);
      }
      routing.rules.push({ id: `legacy-${hook}`, name: hook === 'auth' ? 'Auth' : 'Download', hooks: [hook], destination_ids: [destination.id], active: legacy.active, hide_info: legacy.hide_info });
    }
    sites[site] = routing;
  }
  return { version: null, catalog: webhookHookCatalog, sites };
}

export function routingError(routing: SiteWebhookRouting): string | null {
  for (const destination of routing.destinations) {
    if (!destination.name.trim()) return 'Give each destination a name.';
    try {
      const url = new URL(destination.url);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash) throw new Error();
    } catch { return `Enter a valid HTTP or HTTPS URL for ${destination.name}.`; }
  }
  if (new Set(routing.destinations.map((item) => item.url.trim())).size !== routing.destinations.length) return 'This destination URL is already configured.';
  for (const rule of routing.rules) {
    if (!rule.name.trim()) return 'Give each routing rule a name.';
    if (!rule.hooks.length) return `Choose at least one hook for ${rule.name}.`;
    if (!rule.destination_ids.length) return `Choose at least one destination for ${rule.name}.`;
  }
  return null;
}
