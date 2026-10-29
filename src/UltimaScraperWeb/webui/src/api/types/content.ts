export interface ContentMediaInfo {
  id: number;
  category: string;
  preview: boolean;
  duration?: number;
  thumb_url?: string | null;
  fallback_thumb_url?: string | null;
  local_url?: string | null;
}

export interface ContentLibraryItem {
  favorite?: boolean;
  id: number;
  user_id: number;
  username: string | null;
  content_type: string;
  text: string | null;
  price: number;
  paid: boolean | null;
  deleted: boolean;
  archived: boolean;
  media_count: number;
  media: ContentMediaInfo[];
  expires_at: string | null;
  created_at: string | null;
  site: string;
}

export interface ContentLibraryResponse {
  success: boolean;
  content: ContentLibraryItem[];
  total: number;
  total_is_exact?: boolean;
  page: number;
  page_size: number;
  has_more?: boolean;
  error?: string;
}

export interface BrowseContentLibraryOptions {
  site?: string;
  contentType?: string;
  userId?: number;
  excludeUserIds?: number[];
  search?: string;
  sortBy?: string;
  order?: string;
  includeFlags?: string[];
  excludeFlags?: string[];
  page?: number;
  pageSize?: number;
  includeTotal?: boolean;
  signal?: AbortSignal;
}
