import {
  getJobTaskResultFileUrl,
  getMediaFileUrl,
  getMediaProxyUrl,
} from '../../../api/media';
import type { TaskDetail } from '../../../api/types/jobs';
import type { NetworkProxy } from '../../../api/types/network';
import type { WebSocketEvent } from '../../../hooks/useWebSocket';
import { formatDuration } from './jobUtils';
import { getTaskProxySummary } from './taskProxyUtils';

export type RunbookStageId = 'prepare' | 'scrape' | 'download' | 'finish';

interface RunbookStage {
  id: RunbookStageId;
  label: string;
}

interface LiveTransfer {
  taskId: string;
  mediaId: string | null;
  path: string | null;
  url: string | null;
  status: string | null;
  contentType: string | null;
  workerId: string | null;
  processedBytes: number | null;
  expectedBytes: number | null;
  speedBps: number | null;
  completed: number | null;
  failed: number | null;
  total: number | null;
  timestamp: string | null;
}

export interface RunbookMediaEntry {
  key: string;
  resultIndex: number | null;
  mediaId: string | null;
  path: string | null;
  url: string | null;
  status: string;
  processedBytes: number | null;
  expectedBytes: number | null;
  speedBps: number | null;
  isLive: boolean;
}

export const RUNBOOK_STAGES: RunbookStage[] = [
  { id: 'prepare', label: 'Prepare' },
  { id: 'scrape', label: 'Scrape' },
  { id: 'download', label: 'Download' },
  { id: 'finish', label: 'Finish' },
];

export const ACTIVE_TASK_STATES = new Set(['claimed', 'running', 'saving_db']);
export const TERMINAL_TASK_STATES = new Set(['completed', 'failed', 'cancelled']);
function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function taskHopUsed(task: TaskDetail, networkProxies?: NetworkProxy[]): number {
  const summary = getTaskProxySummary(task, networkProxies);
  if (summary.usedHopNumber !== null) return summary.usedHopNumber;

  const result = asRecord(task.result);
  const output = asRecord(result?.output);
  const metrics = asRecord(result?.metrics);
  const attempted = output?.proxy_routes_attempted ?? metrics?.proxy_routes_attempted;
  if (Array.isArray(attempted)) {
    const attemptedIndexes = attempted
      .map((value) => asNumber(value))
      .filter((value): value is number => value !== null);
    if (attemptedIndexes.length > 0) return Math.max(...attemptedIndexes) + 1;
  }

  return summary.hasHops ? 1 : 0;
}

function hasGeoBlockedText(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  return /\bgeo(?:graphical)?[-_\s]?(?:block(?:ed|ing)?|restrict(?:ed|ion)?)\b/i.test(value);
}

export function taskIsGeoBlocked(task: TaskDetail, networkProxies?: NetworkProxy[]): boolean {
  const result = asRecord(task.result);
  const output = asRecord(result?.output);
  const metrics = asRecord(result?.metrics);
  const payload = asRecord(task.payload);
  const explicitFlags = [
    output?.geo_blocked,
    output?.geoblocked,
    metrics?.geo_blocked,
    metrics?.geoblocked,
    payload?.geo_blocked,
    payload?.geoblocked,
  ];
  if (explicitFlags.some((value) => value === true || hasGeoBlockedText(value))) return true;

  const messages = [
    task.error,
    result?.message,
    output?.message,
    output?.reason,
    output?.error,
    metrics?.message,
    metrics?.reason,
    metrics?.error,
  ];
  if (messages.some(hasGeoBlockedText)) return true;

  // Geo-diverse fallback is the persisted route-level evidence available for older tasks
  // that predate an explicit geo_blocked result flag.
  const summary = getTaskProxySummary(task, networkProxies);
  const activeCountry = summary.activeHop?.country_code;
  if (!activeCountry || summary.usedHopNumber === null || summary.usedHopNumber <= 1) return false;
  return summary.hops
    .slice(0, summary.usedHopNumber - 1)
    .some((hop) => hop.status === 'failed' && hop.country_code && hop.country_code !== activeCountry);
}

export function asString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
}

export function taskTypeStage(taskTypeValue: string): RunbookStageId {
  const taskType = taskTypeValue.toLowerCase();
  if (taskType.includes('download')) return 'download';
  if (taskType.includes('scrape')) return 'scrape';
  if (
    taskType.includes('refresh') ||
    taskType.includes('auth') ||
    taskType.includes('prepare') ||
    taskType.includes('resolve')
  ) {
    return 'prepare';
  }
  return 'finish';
}

export function taskStage(task: TaskDetail): RunbookStageId {
  return taskTypeStage(String(task.task_type || ''));
}

export function taskTypeLabel(taskType: string): string {
  return taskType.replace(/_/g, ' ');
}

export function taskTitle(task: TaskDetail): string {
  const label = taskTypeLabel(task.task_type || 'task');
  const contentType = task.content_type?.replace(/([a-z])([A-Z])/g, '$1 $2').trim();
  const normalized = label.toLowerCase();

  if (contentType && normalized.includes('download')) return `Download ${contentType}`;
  if (contentType && normalized.includes('scrape')) return `Scrape ${contentType}`;
  return label;
}

export function taskWorker(task: TaskDetail): string {
  const result = asRecord(task.result);
  const metrics = asRecord(result?.metrics);
  const payload = asRecord(task.payload);
  return (
    asString(task.worker_id) ??
    asString(result?.worker_id) ??
    asString(metrics?.worker_id) ??
    asString(payload?.worker_id) ??
    'unclaimed'
  );
}

export function taskAttempt(task: TaskDetail): { current: number; maximum: number } {
  const result = asRecord(task.result);
  const payload = asRecord(task.payload);
  return {
    current: Math.max(1, asNumber(result?.attempt ?? payload?.attempt) ?? 1),
    maximum: Math.max(1, asNumber(result?.max_attempts ?? payload?.max_attempts) ?? 3),
  };
}

export function taskAuthId(task: TaskDetail): number | null {
  const payload = asRecord(task.payload);
  return asNumber(payload?.auth_id);
}

export function taskProgressPercent(task: TaskDetail): number {
  const rawProgress = asNumber(task.progress);
  if (rawProgress !== null && rawProgress > 0) {
    const normalized = rawProgress <= 1 ? rawProgress * 100 : rawProgress;
    return Math.min(100, Math.max(0, Math.round(normalized)));
  }
  if (task.items_total && task.items_total > 0) {
    return Math.min(100, Math.max(0, Math.round((task.items_processed / task.items_total) * 100)));
  }
  return String(task.status).toLowerCase() === 'completed' ? 100 : 0;
}

export function taskDuration(task: TaskDetail): string {
  if (!task.started_at) return 'Waiting';
  const start = new Date(task.started_at).getTime();
  const end = task.completed_at ? new Date(task.completed_at).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 'In progress';
  return formatDuration(Math.max(0, Math.round((end - start) / 1000)));
}

export function taskMessage(task: TaskDetail): string {
  const result = asRecord(task.result);
  const message = asString(result?.message);
  if (task.error) return task.error;
  if (message) return message;

  switch (String(task.status || '').toLowerCase()) {
    case 'completed':
      return 'Task completed successfully.';
    case 'failed':
      return 'Task failed without additional error details.';
    case 'saving_db':
      return 'Saving this task result to the database.';
    case 'running':
    case 'claimed':
      return 'Live task telemetry will update here as work progresses.';
    case 'blocked':
    case 'deferred':
      return 'Waiting for an upstream requirement before this task can continue.';
    default:
      return 'Waiting for a worker to claim this task.';
  }
}

export function resultMetrics(task: TaskDetail | null): Record<string, unknown> {
  const result = asRecord(task?.result);
  return asRecord(result?.metrics) ?? {};
}

export function downloadResults(task: TaskDetail | null): Array<Record<string, unknown>> {
  const result = asRecord(task?.result);
  const output = asRecord(result?.output);
  const rawResults = output?.download_results;
  if (!Array.isArray(rawResults)) return [];
  return rawResults.map(asRecord).filter((entry): entry is Record<string, unknown> => !!entry);
}

export function dependencyIds(task: TaskDetail): string[] {
  const payload = asRecord(task.payload);
  const raw = payload?.depends_on ?? payload?.dependencies;
  if (Array.isArray(raw)) {
    return raw.map((value) => String(value)).filter(Boolean);
  }
  const single = asString(raw);
  return single ? [single] : [];
}

export function formatTransferBytes(value: number | null): string {
  if (value === null || value < 0) return '—';
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = value / 1024;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  return `${amount >= 100 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`;
}

export function formatRate(value: number | null): string {
  return value !== null && value > 0 ? `${formatTransferBytes(value)}/s` : '—';
}

export function fileName(value: string | null): string | null {
  if (!value) return null;
  const withoutQuery = value.split('?')[0];
  const segments = withoutQuery.split(/[\\/]/).filter(Boolean);
  const raw = segments.at(-1) ?? null;
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export function mediaKind(path: string | null): 'video' | 'audio' | 'image' | 'file' {
  const extension = (path?.split('.').at(-1) ?? '').toLowerCase();
  if (['mp4', 'mkv', 'mov', 'webm', 'm4v'].includes(extension)) return 'video';
  if (['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg'].includes(extension)) return 'audio';
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif'].includes(extension)) return 'image';
  return 'file';
}

export function mediaGlyph(kind: ReturnType<typeof mediaKind>): string {
  if (kind === 'video') return '▶';
  if (kind === 'audio') return '≋';
  if (kind === 'image') return '◇';
  return '□';
}

export function normalizedMediaState(status: string, isLive: boolean): string {
  const normalized = status.toLowerCase();
  if (
    normalized.includes('complete') ||
    normalized.includes('downloaded') ||
    normalized.includes('success')
  ) return 'complete';
  if (isLive || normalized.includes('progress') || normalized.includes('downloading')) return 'downloading';
  if (normalized.includes('queue') || normalized.includes('pending')) return 'queued';
  if (normalized.includes('fail') || normalized.includes('error') || normalized.includes('retry')) return 'retrying';
  if (normalized.includes('skip')) return 'skipped';
  return 'complete';
}

export function mediaProgress(entry: RunbookMediaEntry): number {
  if (entry.processedBytes !== null && entry.expectedBytes !== null && entry.expectedBytes > 0) {
    return Math.min(100, Math.max(0, Math.round((entry.processedBytes / entry.expectedBytes) * 100)));
  }
  return normalizedMediaState(entry.status, entry.isLive) === 'complete' ? 100 : 0;
}

export function mediaPreviewUrls(
  entry: RunbookMediaEntry,
  task: TaskDetail,
  jobId: string,
): string[] {
  const site = task.site?.toLowerCase() || 'onlyfans';
  const candidates: Array<string | null> = [];
  if (entry.isLive && entry.url) {
    candidates.push(getMediaProxyUrl(entry.url, site, taskAuthId(task)));
  } else {
    if (entry.resultIndex !== null && task.task_id) {
      candidates.push(getJobTaskResultFileUrl(jobId, task.task_id, entry.resultIndex));
    }

    const isProfileTask = String(task.content_type || '').toLowerCase() === 'profile';
    if (isProfileTask && entry.url) {
      candidates.push(getMediaProxyUrl(entry.url, site, taskAuthId(task)));
    }

    const numericMediaId = entry.mediaId ? Number(entry.mediaId) : Number.NaN;
    if (Number.isFinite(numericMediaId)) {
      candidates.push(getMediaFileUrl(site, numericMediaId));
    }

    if (!isProfileTask && entry.url) {
      candidates.push(getMediaProxyUrl(entry.url, site, taskAuthId(task)));
    }
  }

  return [...new Set(candidates.filter((candidate): candidate is string => Boolean(candidate)))];
}

export function parseLiveTransfer(event: WebSocketEvent | null | undefined, jobId: string): LiveTransfer | null {
  if (!event) return null;
  const eventJobId = asString(event.job_id ?? event.id);
  if (eventJobId !== jobId) return null;

  const eventName = asString(event.event) ?? asString(event.type);
  const transportType = asString(event.type);
  const isDownloadEvent =
    eventName === 'download_progress' ||
    transportType === 'download_status' ||
    Boolean(eventName?.startsWith('download_'));
  if (!isDownloadEvent) return null;

  const taskId = asString(event.task_id);
  if (!taskId) return null;

  return {
    taskId,
    mediaId: event.media_id == null ? null : String(event.media_id),
    path: asString(event.path),
    url: asString(event.url),
    status: asString(event.status) ?? eventName,
    contentType: asString(event.content_type),
    workerId: asString(event.worker_id),
    processedBytes: asNumber(event.processed_bytes ?? event.total_bytes),
    expectedBytes: asNumber(event.expected_bytes),
    speedBps: asNumber(event.speed_bps),
    completed: asNumber(event.completed),
    failed: asNumber(event.failed),
    total: asNumber(event.total),
    timestamp: asString(event.timestamp),
  };
}

export function taskStatusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === 'completed') return 'complete';
  if (ACTIVE_TASK_STATES.has(normalized)) return 'live';
  if (normalized === 'failed' || normalized === 'cancelled') return 'failed';
  if (normalized === 'blocked' || normalized === 'deferred') return 'blocked';
  return 'queued';
}
