export type StatisticsHistoryRange = '7d' | '30d' | '90d' | 'all';

export interface SiteStatisticsSnapshot {
  site: string;
  /** Nullable in snapshots created before archive inventory counts were added. */
  user_record_count: number | null;
  performer_profile_count: number | null;
  active_user_count?: number | null;
  archived_content_count: number | null;
  post_count?: number | null;
  message_count?: number | null;
  story_count?: number | null;
  mass_message_count?: number | null;
  downloaded_media_count: number | null;
  bucket_date: string;
  bucket_started_at: string;
  bucket_ends_at: string;
  calculated_at: string;
  total_media_count: number;
  sized_media_count: number;
  zero_size_media_count: number;
  image_media_count: number;
  image_sized_count: number;
  video_media_count: number;
  video_sized_count: number;
  audio_media_count: number;
  audio_sized_count: number;
  other_media_count: number;
  other_sized_count: number;
  total_known_bytes: number;
  avg_media_size_bytes: number;
  avg_image_size_bytes: number;
  avg_video_size_bytes: number;
  avg_audio_size_bytes: number;
  avg_other_size_bytes: number;
  size_coverage_ratio: number;
}

export interface SiteStatistics {
  site: string;
  target_bucket_date: string;
  snapshot_source: 'current' | 'latest' | 'none';
  is_current: boolean;
  is_building: boolean;
  has_snapshot: boolean;
  build_state: 'building' | 'failed' | null;
  build_progress_ratio: number | null;
  build_processed_rows: number | null;
  build_message: string | null;
  build_error: string | null;
  build_updated_at: string | null;
  availability_error: string | null;
  snapshot: SiteStatisticsSnapshot | null;
}

export interface SiteStatisticsHistory {
  site: string;
  available: boolean;
  availability_error: string | null;
  points: SiteStatisticsSnapshot[];
}

export interface StatisticsHistoryResponse {
  range: StatisticsHistoryRange;
  start_date: string | null;
  end_date: string;
  sites: SiteStatisticsHistory[];
}

export type StatisticsActivityMetric = 'accounts' | 'posts';
export type StatisticsActivityInterval = 'minute' | 'hour' | 'day' | 'month' | 'year';
export type StatisticsActivityRange = '1h' | '24h' | '7d' | '30d' | '90d' | '1y' | 'all' | 'custom';
export type StatisticsAccountDate = 'join_date' | 'created_at';

export interface StatisticsActivityResponse {
  metric: StatisticsActivityMetric;
  interval: StatisticsActivityInterval;
  range: StatisticsActivityRange;
  date_field: string;
  start_at: string;
  /** Exclusive end of the final calendar bucket, which may still be in progress. */
  end_at: string;
  calculated_at: string;
  coverage_start_at?: string | null;
  coverage_end_at?: string | null;
  /** Full range stays at the selected interval; only this window is plotted. */
  window_start_at?: string | null;
  window_end_at?: string | null;
  bucket_count?: number;
  bucket_offset?: number;
  completed_bucket_count?: number;
  sites: Array<{
    site: string;
    available: boolean;
    availability_error: string | null;
    /** Records in the archive with no source timestamp, regardless of selected range. */
    undated_count: number | null;
    total_count?: number | null;
    completed_count?: number | null;
    before_window_count?: number | null;
    /** Sparse SQL groups. Missing buckets on an available site mean zero records. */
    points: Array<{ bucket_started_at: string; count: number }>;
  }>;
}

export type SeasonalityCycle = 'hour' | 'weekday' | 'monthday' | 'month';
export interface StatisticsSeasonalityResponse {
  metric: StatisticsActivityMetric;
  cycle: SeasonalityCycle;
  date_field: string;
  start_date: string;
  end_date: string;
  calculated_at: string;
  exposures: number[];
  sites: Array<{ site: string; available: boolean; availability_error: string | null; counts: number[] }>;
}
