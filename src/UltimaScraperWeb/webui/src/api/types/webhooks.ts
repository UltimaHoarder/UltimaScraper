export interface WebhookInfo {
  active: boolean;
  url: string | null;
  hide_info: string[];
}

export interface WebhooksInfo {
  auth: WebhookInfo;
  download: WebhookInfo;
}

export interface WebhookSitesResponse {
  onlyfans: WebhooksInfo;
  fansly: WebhooksInfo;
}

export interface WebhooksResponse {
  sites: WebhookSitesResponse;
  configuration?: WebhookConfiguration;
}

export type WebhookSite = 'onlyfans' | 'fansly';
export type WebhookHook = 'auth' | 'download' | 'chat_message' | 'subscriber' | 'post_published' | 'post_updated' | 'stream_started' | 'comment' | 'price_changed' | 'online' | 'site_message';

export interface WebhookHookDefinition {
  id: WebhookHook;
  label: string;
  description: string;
  sites: WebhookSite[];
  group: 'Account' | 'Downloads' | 'Site messages';
}

export interface WebhookDestination {
  id: string;
  name: string;
  url: string;
  format: 'json' | 'discord';
}

export interface WebhookRule {
  id: string;
  name: string;
  hooks: WebhookHook[];
  destination_ids: string[];
  active: boolean;
  hide_info: string[];
}

export interface SiteWebhookRouting {
  destinations: WebhookDestination[];
  rules: WebhookRule[];
}

export interface WebhookConfiguration {
  version: number | null;
  catalog: WebhookHookDefinition[];
  sites: Record<WebhookSite, SiteWebhookRouting>;
}

export interface WatchedUserInfo {
  id: number;
  username: string | null;
  site: string;
  watched: boolean;
  downloaded_at: string | null;
  created_at: string | null;
}

export interface WatchListResponse {
  users: WatchedUserInfo[];
  total: number;
}

export interface WatchStatsResponse {
  total_watched: number;
  by_site: Record<string, number>;
  paused: boolean;
}

export interface WatchPauseResponse {
  paused: boolean;
  message: string;
}
