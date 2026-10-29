import type { Job, JobDetail, TaskDetail, TaskStats, TaskSummary } from '../../../api/types/jobs';

export type JobPreparationPhase = 'queued' | 'materializing' | 'finalizing';

interface JobPreparationSource {
  status?: string | null;
  materialization_status?: string | null;
  materialized_tasks?: number | null;
  materialization_total?: number | null;
  task_stats?: TaskStats;
}

export interface JobPreparationProgress {
  phase: JobPreparationPhase;
  label: 'Queued' | 'Materializing' | 'Finalizing';
  completed: number;
  total: number;
  percent: number;
}

export function isJobRunningStatus(status?: string | null): boolean {
  const norm = String(status || '').trim().toLowerCase();
  return (
    norm === 'running' ||
    norm === 'in_progress' ||
    norm === 'pending' ||
    norm === 'preparing' ||
    norm === 'paused' ||
    norm === 'deleting' ||
    norm === 'wrapping_up'
  );
}

export function resolveEffectiveJobStatus(
  status?: string | null,
  taskStats?: Partial<TaskStats>,
  overallProgress?: number,
): string {
  const normalized = String(status || '').toLowerCase();
  // Do not mark a completed run as overall FAILED if tasks hit the terminal threshold or retry policy
  if (
    normalized === 'failed' &&
    overallProgress !== undefined &&
    overallProgress >= 100
  ) {
    const total = taskStats?.total ?? 0;
    const completed = taskStats?.completed ?? 0;
    const failed = taskStats?.failed ?? 0;
    if (completed > 0 && (total === 0 || (completed + failed) >= total)) {
      const failureRate = (completed + failed) > 0 ? failed / (completed + failed) : 0;
      if (failureRate < 0.5) {
        return 'completed';
      }
    }
  }
  return normalized;
}

export function getJobPreparationProgress(
  job: JobPreparationSource,
): JobPreparationProgress | null {
  const status = String(job.status ?? '').toLowerCase();
  const phase = String(job.materialization_status ?? '').toLowerCase();
  if (
    !['pending', 'running'].includes(status) ||
    !['queued', 'materializing', 'finalizing'].includes(phase)
  ) {
    return null;
  }

  const normalizedPhase = phase as JobPreparationPhase;
  const total = Math.max(
    0,
    job.materialization_total ?? job.task_stats?.total ?? 0,
  );
  const preparedTasks = job.task_stats
    ? job.task_stats.ready +
      job.task_stats.blocked +
      job.task_stats.inflight +
      job.task_stats.deferred +
      job.task_stats.completed +
      job.task_stats.failed
    : 0;
  const completed = Math.min(
    total,
    Math.max(
      0,
      normalizedPhase === 'finalizing'
        ? preparedTasks
        : (job.materialized_tasks ?? 0),
    ),
  );
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const label =
    normalizedPhase === 'queued'
      ? 'Queued'
      : normalizedPhase === 'finalizing'
        ? 'Finalizing'
        : 'Materializing';

  return { phase: normalizedPhase, label, completed, total, percent };
}

function parseInactiveAuthId(message?: string | null): number | null {
  if (!message) return null;
  const match = /auth\s+(\d+)\s+not found in site api/i.exec(message);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : null;
}

export function extractInactiveAuthId(details?: JobDetail, tasks?: TaskDetail[]): number | null {
  const fromResult = parseInactiveAuthId(details?.result_error || details?.result_message);
  if (fromResult !== null) return fromResult;
  for (const task of tasks ?? []) {
    const fromTask = parseInactiveAuthId(task.error);
    if (fromTask !== null) return fromTask;
  }
  return null;
}

export function getJobActionErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') return fallback;
  const maybeError = error as {
    message?: string;
    response?: { data?: { detail?: string; message?: string; error?: string } };
  };
  const detail =
    maybeError.response?.data?.detail ??
    maybeError.response?.data?.message ??
    maybeError.response?.data?.error;
  return detail || maybeError.message || fallback;
}

export function getRetryErrorMessage(error: unknown): string {
  return getJobActionErrorMessage(error, 'Failed to retry job.');
}

export function getTemplateErrorMessage(error: unknown): string {
  return getJobActionErrorMessage(error, 'Failed to save template.');
}

export function formatDateTime(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function timeAgo(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const now = Date.now();
  const diffMs = now - parsed.getTime();
  if (diffMs < 0) return 'in the future';
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return parsed.toLocaleDateString();
}

export function getScheduleLabel(job: Job): string | null {
  if (job.interval_seconds) {
    const secs = job.interval_seconds;
    if (secs % 86400 === 0) return `every ${secs / 86400}d`;
    if (secs % 3600 === 0) return `every ${secs / 3600}h`;
    return `every ${Math.round(secs / 60)}m`;
  }
  if (job.cron) return `cron: ${job.cron}`;
  if (job.scheduled_for) return `at ${new Date(job.scheduled_for).toLocaleString()}`;
  return null;
}

export function taskTypeLabel(taskType: string): string {
  return taskType.replace(/_/g, ' ');
}

export function toLocalDateTimeInput(value?: string | null): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  const adjusted = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return adjusted.toISOString().slice(0, 16);
}

export function getIntervalParts(
  intervalSeconds?: number | null
): { value: number; unit: 'minutes' | 'hours' | 'days' } | null {
  if (!intervalSeconds || intervalSeconds <= 0) return null;
  if (intervalSeconds % 86400 === 0) return { value: intervalSeconds / 86400, unit: 'days' };
  if (intervalSeconds % 3600 === 0) return { value: intervalSeconds / 3600, unit: 'hours' };
  return { value: Math.max(1, Math.round(intervalSeconds / 60)), unit: 'minutes' };
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remainMins = mins % 60;
  return remainMins > 0 ? `${hrs}h ${remainMins}m` : `${hrs}h`;
}

function positiveNumber(value: unknown): number | null {
  return typeof value === 'number' && value > 0 ? value : null;
}

export function computeJobDurationSeconds(job?: Job | JobDetail | null): number {
  if (!job) return 1;

  const explicitDuration =
    positiveNumber(job.duration_seconds) ?? positiveNumber(job.metadata?.duration_seconds);
  if (explicitDuration !== null) {
    return Math.max(1, Math.round(explicitDuration));
  }

  const started = job.started_at || job.created_at || '';
  const finished =
    job.completed_at || job.last_ran_at || job.last_activity_at || job.updated_at || '';

  const startMs = started ? new Date(started).getTime() : 0;
  const endMs = finished ? new Date(finished).getTime() : startMs;
  return startMs > 0 && endMs > startMs ? Math.max(1, Math.round((endMs - startMs) / 1000)) : 1;
}

export function streamTaskKey(task: TaskDetail): string {
  if (task.task_id) return `task:${task.task_id}`;
  return [
    'fallback',
    task.task_type,
    task.site ?? 'unknown-site',
    task.username ?? 'unknown-user',
    task.content_type ?? 'all',
  ].join('|');
}

export function getTaskDownloadErrorCount(task: TaskSummary | TaskDetail): number {
  const result =
    'result' in task && task.result && typeof task.result === 'object' ? task.result : null;
  if (!result || typeof result !== 'object') return 0;
  const metrics = (result as { metrics?: { failed?: unknown } }).metrics;
  if (typeof metrics?.failed === 'number' && Number.isFinite(metrics.failed)) {
    return Math.max(0, metrics.failed);
  }
  const output = (result as { output?: unknown }).output;
  if (!output || typeof output !== 'object') return 0;
  const downloadResults = (output as { download_results?: unknown }).download_results;
  if (!Array.isArray(downloadResults)) return 0;
  return downloadResults.filter((entry) => entry?.status === 'failed').length;
}

export * from './jobEta';
