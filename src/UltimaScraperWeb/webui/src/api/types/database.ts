export interface MediaItem {
  id: number;
  post_id: number | null;
  user_id: number | null;
  media_type: string | null;
  filename: string | null;
  size: number;
  downloaded: boolean;
  drm?: boolean;
  created_at: string | null;
  site: string;
}

export interface MediaBrowserResponse {
  success: boolean;
  media: MediaItem[];
  total: number;
  page: number;
  page_size: number;
  error?: string;
}

export type {
  DatabaseAnalyzeRequest,
  DatabaseAnalyzeResponse,
  DatabaseOverview,
  DatabaseOverviewResponse,
  DatabaseReindexRequest,
  DatabaseReindexResponse,
  DatabaseTableOverview,
  DatabaseVacuumRequest,
  DatabaseVacuumResponse,
} from './system';

