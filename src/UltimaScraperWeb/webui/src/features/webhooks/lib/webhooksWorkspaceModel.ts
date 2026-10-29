import type { WebhookInfo, WatchedUserInfo } from '../../../api/types/webhooks';
import type { WebhookMessage } from '../../../hooks/useWebhookStream';
import type { CategoryFilter, SiteKey } from './webhooksUtils';

export interface WebhookRoute extends WebhookInfo { id: string; site: SiteKey; kind: string }

export interface WebhooksWorkspaceModel {
  isPreview?: boolean;
  routes: WebhookRoute[];
  hookCountLabel?: string;
  selectedRoute?: WebhookRoute;
  setSelectedRouteId: (id: string) => void;
  messages: WebhookMessage[];
  filteredMessages: WebhookMessage[];
  selectedMessage?: WebhookMessage;
  setSelectedMessageId: (id: string) => void;
  category: CategoryFilter;
  setCategory: (category: CategoryFilter) => void;
  query: string;
  setQuery: (query: string) => void;
  showAll: boolean;
  setShowAll: (value: boolean) => void;
  clearMessages: () => void;
  resetFilters?: () => void;
  users: WatchedUserInfo[];
  totalUsers?: number;
  filteredUsers: WatchedUserInfo[];
  paused: boolean;
  connected: boolean;
  watchSite: string;
  setWatchSite: (site: string) => void;
  watchQuery: string;
  setWatchQuery: (query: string) => void;
  addQuery: string;
  setAddQuery: (query: string) => void;
  addSite: string;
  setAddSite: (site: string) => void;
  candidates: WatchedUserInfo[];
  watch: (person: WatchedUserInfo) => void;
  unwatch: (person: WatchedUserInfo) => void;
  togglePaused: () => void;
  addPending?: boolean;
  removePending?: boolean;
  pausePending?: boolean;
  watchStatusUnavailable?: boolean;
  watchListLoading?: boolean;
  searchLoading?: boolean;
  searchError?: string;
  updatesPaused?: boolean;
  toggleUpdates?: () => void;
  hasMoreUsers?: boolean;
  loadMoreUsers?: () => void;
}
