export interface UserInfo {
  id: number;
  user_id: number;
  username: string;
  name: string | null;
  sex: number | null;
  gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  ai_assisted?: boolean | null;
  verified?: boolean | null;
  description: string | null;
  avatar_url: string | null;
  header_url: string | null;
  price: number;
  post_count: number;
  media_count: number;
  image_count: number;
  video_count: number;
  favorite: boolean;
  is_active: boolean;
  is_subscribed: boolean;
  is_pending_order: boolean;
  site: string;
  downloaded_at: string | null;
  last_checked_at: string | null;
}

export interface UsersListResponse {
  success: boolean;
  users: UserInfo[];
  total: number | null;
  active: number | null;
  inactive: number | null;
  avg_price: number | null;
  free: number | null;
  paid: number | null;
  has_more?: boolean | null;
  error?: string;
}

export interface UsersListQuery {
  site?: string;
  search?: string;
  searchDescription?: string;
  activeOnly?: boolean;
  favoriteOnly?: boolean;
  sex?: number[];
  gender?: number[];
  profileType?: number[];
  sexualContent?: number[];
  subscribedOnly?: boolean;
  excludeSubscribed?: boolean;
  minPrice?: string;
  maxPrice?: string;
  minPostCount?: string;
  maxPostCount?: string;
  minImageCount?: string;
  maxImageCount?: string;
  minVideoCount?: string;
  maxVideoCount?: string;
  performerOnly?: boolean;
  excludePerformers?: boolean;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
  includeStats?: boolean;
  statsOnly?: boolean;
}

export interface UsernameDirectoryMatch {
  root: string;
  path: string;
}

export interface UsernameDirectorySearchResponse {
  success: boolean;
  username: string;
  site: string;
  user_directory_format: string;
  matches: UsernameDirectoryMatch[];
  checked_patterns: string[];
  usernames_searched: string[];
  resolved_user_id: number | null;
}

export interface WatchToggleResponse {
  user_id: number;
  watched: boolean;
  message: string;
}

export interface IgnoreToggleResponse {
  user_id: number;
  ignored: boolean;
  message: string;
}

export interface UserProfileMediaInfo {
  id: number;
  avatar_url: string | null;
  header_url: string | null;
  created_at: string | null;
}

export interface SocialInfo {
  site: string;
  identifier: string;
}

export interface DetailedUserInfo {
  id: number;
  user_id: number;
  username: string;
  name: string | null;
  description: string | null;
  avatar_url: string | null;
  header_url: string | null;
  price: number;
  post_count: number;
  media_count: number;
  image_count: number;
  video_count: number;
  audio_count: number;
  stream_count: number;
  archived_post_count: number;
  subscribers_count: number;
  favourited_count: number;
  favourites_count: number;
  size: number;
  display_size: number;
  estimated_size: number | null;
  size_source: 'actual' | 'estimated' | 'unknown';
  statistics_bucket_date: string | null;
  location: string | null;
  website: string | null;
  sex: number | null;
  gender: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  promotion: boolean;
  is_active: boolean;
  is_subscribed: boolean;
  subscription_expires_at: string | null;
  balance: number;
  spend: boolean;
  performer: boolean;
  favorite: boolean;
  site: string;
  join_date: string | null;
  downloaded_at: string | null;
  first_downloaded_at: string | null;
  last_checked_at: string | null;
  created_at: string | null;
  profile_media_history: UserProfileMediaInfo[];
  socials: SocialInfo[];
}

export interface DetailedUserResponse {
  success: boolean;
  user: DetailedUserInfo | null;
  error?: string | null;
  is_stale?: boolean;
  is_refreshing?: boolean;
  refresh_error?: string | null;
}

export interface UserProfileRefreshResponse {
  accepted: boolean;
  is_refreshing: boolean;
  error?: string | null;
}

export interface HistoUserInfoItem {
  id: number;
  user_id: number;
  name: string | null;
  username: string | null;
  about: string | null;
  header: string | null;
  avatar: string | null;
  post_count: number;
  media_count: number;
  image_count: number;
  video_count: number;
  audio_count: number;
  price: number;
  fans_count: number;
  following_count: number;
  subscriber_count: number;
  archived_post_count: number;
  private_archived_post_count: number;
  created_at: string | null;
  site: string;
}

export interface HistoUserInfoResponse {
  success: boolean;
  snapshots: HistoUserInfoItem[];
  total: number;
  error?: string | null;
}

export interface UserAliasItem {
  id: number;
  user_id: number;
  username: string;
  created_at: string | null;
  site: string;
}

export interface UserAliasResponse {
  success: boolean;
  aliases: UserAliasItem[];
  total: number;
  error?: string | null;
}

export interface UserAliasDeleteResponse {
  success: boolean;
  alias_id: number | null;
  error?: string | null;
}

export interface UserUpdateRequest {
  username?: string | null;
  name?: string | null;
  alias?: string | null;
  description?: string | null;
  sex?: number | null;
  gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  favorite?: boolean | null;
  ai_assisted?: boolean | null;
  verified?: boolean | null;
}

export interface UserUpdateResponse {
  success: boolean;
  user_id: number | null;
  site: string | null;
  username: string | null;
  name: string | null;
  alias: string | null;
  description: string | null;
  sex: number | null;
  gender: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  favorite: boolean | null;
  ai_assisted?: boolean | null;
  verified?: boolean | null;
  error?: string | null;
}

export interface EligibleAuth {
  auth_id: number;
  auth_username: string | null;
  is_active: boolean;
}

export interface EligibleAuthsResponse {
  auths: EligibleAuth[];
  error?: string | null;
}

export interface UserBrowserItem {
  id: number;
  username: string | null;
  name: string | null;
  active: boolean;
  performer: boolean;
  favorite: boolean;
  post_count: number;
  media_count: number;
  image_count: number;
  video_count: number;
  price: number;
  site: string;
}

export interface UserBrowserResponse {
  success: boolean;
  users: UserBrowserItem[];
  total: number;
  page: number;
  page_size: number;
  error?: string;
}

export interface UserIdentifierCandidate {
  user_id: number;
  username: string;
  active: boolean;
  last_checked_at: string | null;
  matched_by: Array<'user_id' | 'username' | 'alias'>;
}

export interface UserIdentifierResolutionResponse {
  success: boolean;
  status: 'resolved' | 'ambiguous' | 'not_found' | 'unavailable';
  user_id: number | null;
  username: string | null;
  candidates: UserIdentifierCandidate[];
  total: number;
  page: number;
  page_size: number;
  error?: string | null;
}
