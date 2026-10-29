interface QueryWithFetchStatus {
  state: {
    fetchStatus: 'idle' | 'fetching' | 'paused';
  };
}

export const JOBS_LIST_POLL_INTERVAL_MS = 3_000;
export const JOB_DETAILS_POLL_INTERVAL_MS = 1_000;

const JOB_LIFECYCLE_REFRESH_EVENTS = new Set([
  'job_created',
  'job_started',
  'job_claimed',
  'job_tasks_routed',
  'job_materialized',
  'job_completed',
  'job_failed',
  'job_cancelled',
  'job_prioritized',
  'job_updated',
  'job_paused',
  'job_resumed',
]);

/**
 * Progress and task events can arrive many times per second. The jobs page
 * already polls live state, so only bounded job lifecycle transitions should
 * request an immediate refresh.
 */
export function isJobLifecycleRefreshEvent(eventName: string): boolean {
  return JOB_LIFECYCLE_REFRESH_EVENTS.has(eventName);
}

/**
 * TanStack Query's numeric interval may cancel and restart an existing
 * refetch. Disable the interval while a request is in flight so polling waits
 * a full interval after each response instead of creating overlapping reads.
 */
export function getNonOverlappingRefetchInterval(
  query: QueryWithFetchStatus,
  intervalMs: number,
  enabled = true,
): number | false {
  return enabled && query.state.fetchStatus === 'idle' ? intervalMs : false;
}
