import type { SiteStatistics, SiteStatisticsSnapshot, StatisticsActivityResponse } from '../../src/api/types/statistics';

export function makeStatisticsSnapshot(overrides: Partial<SiteStatisticsSnapshot> = {}): SiteStatisticsSnapshot {
  return {
    site: 'onlyfans', bucket_date: '2026-10-11', bucket_started_at: '2026-10-11T00:00:00Z',
    bucket_ends_at: '2026-10-12T00:00:00Z', calculated_at: '2026-10-11T09:00:00Z',
    user_record_count: 240, performer_profile_count: 20, active_user_count: 180, archived_content_count: 50,
    post_count: 25, message_count: 15, story_count: 6, mass_message_count: 4,
    downloaded_media_count: 75, total_media_count: 100, sized_media_count: 80, zero_size_media_count: 20,
    image_media_count: 60, image_sized_count: 50, video_media_count: 30, video_sized_count: 25,
    audio_media_count: 5, audio_sized_count: 3, other_media_count: 5, other_sized_count: 2,
    total_known_bytes: 31_000_000, avg_media_size_bytes: 387_500,
    avg_image_size_bytes: 100_000, avg_video_size_bytes: 1_000_000,
    avg_audio_size_bytes: 300_000, avg_other_size_bytes: 50_000, size_coverage_ratio: 0.8,
    ...overrides,
  };
}

export function makeSiteStatistics(snapshot: SiteStatisticsSnapshot | null = makeStatisticsSnapshot(), overrides: Partial<SiteStatistics> = {}): SiteStatistics {
  return {
    site: snapshot?.site ?? 'onlyfans', target_bucket_date: '2026-10-11', snapshot_source: snapshot ? 'current' : 'none',
    is_current: true, is_building: false, has_snapshot: Boolean(snapshot), build_state: null,
    build_progress_ratio: null, build_processed_rows: null, build_message: null, build_error: null,
    build_updated_at: null, availability_error: null, snapshot, ...overrides,
  };
}

export function makeStatisticsActivity(overrides: Partial<StatisticsActivityResponse> = {}): StatisticsActivityResponse {
  return {
    metric: 'accounts', interval: 'day', range: '30d', date_field: 'join_date',
    start_at: '2026-10-09T00:00:00Z', end_at: '2026-10-12T00:00:00Z', calculated_at: '2026-10-11T09:00:00Z',
    sites: [{ site: 'onlyfans', available: true, availability_error: null, undated_count: 12,
      points: [{ bucket_started_at: '2026-10-09T00:00:00Z', count: 2 }, { bucket_started_at: '2026-10-11T00:00:00Z', count: 4 }] }],
    ...overrides,
  };
}
