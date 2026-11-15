import { createHttpClient } from './http';

const http = createHttpClient();
// Listing a performer's files on network drives can take minutes.
const SLOW_REQUEST_MS = 10 * 60 * 1000;

export interface ConsolidationFolder {
  root: string;
  path: string;
  priority: number;
  files?: number | null;
  bytes?: number | null;
  /** Free space less what running downloads expect to write; null when unreadable. */
  free_bytes?: number | null;
  /** Free space the drive keeps for downloads; consolidation may use it, with a warning. */
  reserve_bytes?: number | null;
  /** Bytes that would move here if this drive were the target; duplicates need none. */
  needed_bytes?: number | null;
}

export interface SplitPerformer {
  relative_path: string;
  folders: ConsolidationFolder[];
}

export interface SplitScan {
  site_name: string;
  scanning: boolean;
  paused?: boolean;
  started_at?: number;
  scanned_at?: number | null;
  cancelled_at?: number;
  interrupted?: boolean;
  roots_total?: number;
  roots_done?: number;
  current_root?: string | null;
  error?: string;
  performers: SplitPerformer[];
}

export interface ConsolidationPreview {
  relative_path: string;
  folders: ConsolidationFolder[];
  target_root: string | null;
  reason: string;
  /** Bytes the target drive gains. */
  needed_bytes: number;
  /** The move fits only by using some of the target drive's reserve. */
  into_reserve: boolean;
  /** Refused because no drive (or the chosen one) has the free space at all. */
  no_space: boolean;
  move_files: number;
  move_bytes: number;
  duplicates: number;
  conflicts: string[];
  recent: number;
  too_long: number;
}

export interface ConsolidationRunEntry {
  relative_path: string;
  target_root?: string;
  moved?: number;
  moved_bytes?: number;
  duplicates?: number;
  conflicts?: string[];
  conflict_count?: number;
  skipped?: number;
  failed?: string[];
  failed_count?: number;
  error?: string;
}

export interface ConsolidationStatus {
  running?: boolean;
  total?: number;
  done?: number;
  current?: string | null;
  started_at?: number;
  finished_at?: number | null;
  performers?: ConsolidationRunEntry[];
}

export async function startSplitScan(siteName = 'OnlyFans'): Promise<void> {
  await http.post('/api/v1/consolidation/scan', undefined, { params: { site_name: siteName } });
}

export type ScanCommand = 'pause' | 'resume' | 'cancel';

export async function commandSplitScan(command: ScanCommand, siteName = 'OnlyFans'): Promise<void> {
  await http.post(`/api/v1/consolidation/scan/${command}`, undefined, { params: { site_name: siteName } });
}

export async function getSplitScan(siteName = 'OnlyFans'): Promise<SplitScan> {
  const response = await http.get<SplitScan>('/api/v1/consolidation/split', { params: { site_name: siteName } });
  return response.data;
}

/** `targetRoot` picks a drive already holding the performer; otherwise the best one is used. */
export async function previewConsolidation(
  relativePath: string,
  targetRoot?: string | null,
  siteName = 'OnlyFans',
): Promise<ConsolidationPreview> {
  const response = await http.post<ConsolidationPreview>('/api/v1/consolidation/preview', {
    site_name: siteName,
    relative_path: relativePath,
    target_root: targetRoot ?? null,
  }, { timeout: SLOW_REQUEST_MS });
  return response.data;
}

/** `targets` maps a performer to the drive chosen for it. */
export async function startConsolidation(
  relativePaths: string[],
  targets: Record<string, string> = {},
  siteName = 'OnlyFans',
): Promise<void> {
  await http.post('/api/v1/consolidation/run', { site_name: siteName, relative_paths: relativePaths, targets });
}

export async function getConsolidationStatus(): Promise<ConsolidationStatus> {
  const response = await http.get<ConsolidationStatus>('/api/v1/consolidation/status');
  return response.data;
}
