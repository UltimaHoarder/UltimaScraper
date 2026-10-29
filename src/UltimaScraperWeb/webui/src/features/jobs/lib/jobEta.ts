import { formatDuration } from './jobUtils';

export type JobEtaStatus = 'pending' | 'running' | 'wrapping_up' | 'completed' | 'stopped';

export interface JobEtaInput {
  status?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  progressPercent?: number | null;
  itemsProcessed?: number | null;
  itemsTotal?: number | null;
  currentTime?: number;
  smoothedTargetMs?: number | null;
}

export interface JobEtaResult {
  status: JobEtaStatus;
  elapsedSeconds: number | null;
  remainingSeconds: number | null;
  formattedElapsed: string | null;
  formattedRemaining: string | null;
  completionDate: Date | null;
  formattedCompletionTime: string | null;
  label: string;
  tooltip: string;
}

/**
 * Calculates live ETA, elapsed duration, and completion timestamp for a job.
 */
export function calculateJobEta({
  status,
  startedAt,
  completedAt,
  progressPercent,
  itemsProcessed,
  itemsTotal,
  currentTime = Date.now(),
  smoothedTargetMs = null,
}: JobEtaInput): JobEtaResult {
  const normStatus = String(status || '').toLowerCase();

  // If job is finished
  if (completedAt || normStatus === 'completed') {
    const startMs = startedAt ? new Date(startedAt).getTime() : NaN;
    const endMs = completedAt ? new Date(completedAt).getTime() : currentTime;
    const elapsed = !Number.isNaN(startMs)
      ? Math.max(0, Math.round((endMs - startMs) / 1000))
      : null;
    return {
      status: 'completed',
      elapsedSeconds: elapsed,
      remainingSeconds: 0,
      formattedElapsed: elapsed !== null ? formatDuration(elapsed) : null,
      formattedRemaining: 'Done',
      completionDate: new Date(endMs),
      formattedCompletionTime: new Date(endMs).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
      label: elapsed !== null ? `Completed in ${formatDuration(elapsed)}` : 'Completed',
      tooltip: elapsed !== null ? `Job finished in ${formatDuration(elapsed)}` : 'Job completed',
    };
  }

  // If stopped / failed / cancelled
  if (
    normStatus === 'failed' ||
    normStatus === 'cancelled' ||
    normStatus === 'canceled'
  ) {
    const startMs = startedAt ? new Date(startedAt).getTime() : NaN;
    const elapsed = !Number.isNaN(startMs)
      ? Math.max(0, Math.round((currentTime - startMs) / 1000))
      : null;
    return {
      status: 'stopped',
      elapsedSeconds: elapsed,
      remainingSeconds: 0,
      formattedElapsed: elapsed !== null ? formatDuration(elapsed) : null,
      formattedRemaining: normStatus === 'failed' ? 'Failed' : 'Cancelled',
      completionDate: null,
      formattedCompletionTime: null,
      label: elapsed !== null ? `Stopped after ${formatDuration(elapsed)}` : 'Stopped',
      tooltip: elapsed !== null ? `Job stopped after ${formatDuration(elapsed)}` : 'Job stopped',
    };
  }

  // If pending or queued
  if (normStatus === 'pending' || normStatus === 'queued') {
    return {
      status: 'pending',
      elapsedSeconds: null,
      remainingSeconds: null,
      formattedElapsed: null,
      formattedRemaining: 'Queued',
      completionDate: null,
      formattedCompletionTime: null,
      label: 'Queued',
      tooltip: 'Job is queued waiting to run',
    };
  }

  // If claimed
  if (normStatus === 'claimed') {
    return {
      status: 'pending',
      elapsedSeconds: null,
      remainingSeconds: null,
      formattedElapsed: null,
      formattedRemaining: 'Starting...',
      completionDate: null,
      formattedCompletionTime: null,
      label: 'Starting...',
      tooltip: 'Job has been claimed by a worker and is starting',
    };
  }

  // If live/running, but no start timestamp available or invalid
  const startMs = startedAt ? new Date(startedAt).getTime() : NaN;
  if (Number.isNaN(startMs)) {
    return {
      status: 'running',
      elapsedSeconds: null,
      remainingSeconds: null,
      formattedElapsed: null,
      formattedRemaining: 'Estimating...',
      completionDate: null,
      formattedCompletionTime: null,
      label: 'Estimating ETA...',
      tooltip: 'Calculating estimated completion time...',
    };
  }

  // Job is live/running with a valid start time
  const elapsed = Math.max(0, Math.floor((currentTime - startMs) / 1000));
  const effectiveElapsed = Math.max(1, elapsed);
  const progress =
    typeof progressPercent === 'number' && Number.isFinite(progressPercent)
      ? progressPercent
      : 0;

  if (progress >= 100) {
    return {
      status: 'wrapping_up',
      elapsedSeconds: elapsed,
      remainingSeconds: 0,
      formattedElapsed: formatDuration(elapsed),
      formattedRemaining: '< 5s',
      completionDate: new Date(currentTime),
      formattedCompletionTime: 'Soon',
      label: 'Wrapping up',
      tooltip: 'Tasks completed, finalizing job results',
    };
  }

  let remainingSec: number | null = null;

  // Use smoothed target timestamp if provided
  if (smoothedTargetMs !== null && smoothedTargetMs !== undefined) {
    const diffMs = smoothedTargetMs - currentTime;
    remainingSec = Math.max(0, Math.round(diffMs / 1000));
  } else if (progress > 0) {
    remainingSec = Math.max(
      0,
      Math.round((effectiveElapsed * (100 - progress)) / progress),
    );
  } else if (
    itemsTotal &&
    itemsProcessed &&
    itemsTotal > itemsProcessed &&
    itemsProcessed > 0
  ) {
    const p = itemsProcessed / itemsTotal;
    remainingSec = Math.max(0, Math.round((effectiveElapsed * (1 - p)) / p));
  }

  if (remainingSec === null) {
    return {
      status: 'running',
      elapsedSeconds: elapsed,
      remainingSeconds: null,
      formattedElapsed: formatDuration(elapsed),
      formattedRemaining: 'Estimating...',
      completionDate: null,
      formattedCompletionTime: null,
      label: 'Calculating ETA...',
      tooltip: 'Calculating estimated completion time...',
    };
  }

  const completionDate = new Date(currentTime + remainingSec * 1000);
  const formattedCompletionTime = completionDate.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
  const formattedRemaining =
    remainingSec === 0 ? '< 5s' : formatDuration(remainingSec);

  return {
    status: 'running',
    elapsedSeconds: elapsed,
    remainingSeconds: remainingSec,
    formattedElapsed: formatDuration(elapsed),
    formattedRemaining,
    completionDate,
    formattedCompletionTime,
    label: `Est. finish ${formattedCompletionTime}`,
    tooltip: `Estimated completion at ${formattedCompletionTime} (~${formattedRemaining} left)`,
  };
}
