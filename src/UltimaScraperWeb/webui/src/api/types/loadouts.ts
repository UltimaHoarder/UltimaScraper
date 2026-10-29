export type SearchLoadoutType = 'users' | 'subscriptions' | 'content';

export interface SearchLoadoutItem {
  name: string;
  type: SearchLoadoutType;
  identifier: string;
  description: string;
  site: string;
  filters: Record<string, unknown>;
  is_default: boolean;
  updated_at: string | null;
}

export interface SearchLoadoutsResponse {
  success: boolean;
  type: SearchLoadoutType;
  default_name: string | null;
  loadouts: SearchLoadoutItem[];
  error?: string | null;
}

export interface SearchLoadoutMutationResponse {
  success: boolean;
  type: SearchLoadoutType;
  name: string;
  default_name: string | null;
  error?: string | null;
}

export interface SearchLoadoutUpsertRequest {
  identifier?: string;
  description?: string;
  site?: string;
  filters?: Record<string, unknown>;
  set_as_default?: boolean;
}
