/** Download-failure reasons grouped into the recovery categories shown in job details. */
export const ERROR_CATEGORIES: Record<string, string[]> = {
  url_expired: ['url_expired', 'url_expired_runtime', 'no_url'],
  ip_mismatch: ['ip_mismatch'],
  download_error: ['download_error', 'network_error'],
  content_issues: ['content_expired', 'content_deleted_runtime'],
  data_issues: ['size_mismatch', 'disk_full'],
};

export type RecoveryTone = 'critical' | 'warning' | 'review';

export interface RecoveryCauseDefinition {
  label: string;
  code: string;
  tone: RecoveryTone;
  posture: string;
  signal: string;
  impact: string;
  boundary: string;
  prerequisite: string;
}

export const RECOVERY_CAUSES: Record<string, RecoveryCauseDefinition> = {
  all: {
    label: 'All failures',
    code: 'JOB_FAILURE_SET',
    tone: 'review',
    posture: 'Inspect',
    signal:
      'This view combines every task issue and download failure found in the loaded task history. Select a cause group to narrow the evidence.',
    impact:
      'The job contains recorded failures, but their retry boundaries may differ by cause.',
    boundary:
      'Review each cause before creating a retry. The backend retries failed tasks when any exist; otherwise it retries every available task.',
    prerequisite: 'Review each recorded cause and confirm the resulting retry scope.',
  },
  task_issues: {
    label: 'Task issues',
    code: 'TASK_FAILURE',
    tone: 'critical',
    posture: 'Inspect',
    signal:
      'One or more tasks returned an explicit failure state or error message. The task messages below are the source evidence.',
    impact:
      'The affected task did not complete cleanly, so dependent work may not have run.',
    boundary:
      'Resolve the condition reported by the task, then retry the failed-task scope shown in the recovery plan.',
    prerequisite: 'Resolve the task error shown in the evidence list.',
  },
  url_expired: {
    label: 'Signed URL expired',
    code: 'URL_EXPIRED',
    tone: 'critical',
    posture: 'Refresh first',
    signal:
      'A download result reported an expired or missing source URL. Item-level messages below retain the backend detail.',
    impact:
      'Affected media did not produce a successful download result; other recorded outputs are unchanged.',
    boundary:
      'Refresh source metadata or otherwise restore a usable media URL before creating a retry job.',
    prerequisite: 'Refresh the affected source URLs.',
  },
  ip_mismatch: {
    label: 'Route identity changed',
    code: 'IP_MISMATCH',
    tone: 'critical',
    posture: 'Route fix',
    signal:
      'A request reported that its network route no longer matched the route used by the authenticated session.',
    impact:
      'The provider rejected affected requests before their downloads could complete.',
    boundary:
      'Restore a matching auth and route pairing before retrying the affected task scope.',
    prerequisite: 'Restore the authenticated route identity.',
  },
  download_error: {
    label: 'Transfer failure',
    code: 'DOWNLOAD_ERROR',
    tone: 'warning',
    posture: 'Retryable',
    signal:
      'The worker recorded a download or network error while transferring media.',
    impact:
      'Affected media remains incomplete or absent at the recorded destination.',
    boundary:
      'Confirm network and destination health, then create a retry job for the backend-selected task scope.',
    prerequisite: 'Confirm network and destination availability.',
  },
  content_issues: {
    label: 'Source content unavailable',
    code: 'CONTENT_UNAVAILABLE',
    tone: 'warning',
    posture: 'Review first',
    signal:
      'The source reported that affected content expired or was deleted during the run.',
    impact:
      'The source may no longer expose these items; existing local files are not evidence that a retry will succeed.',
    boundary:
      'Check source availability before retrying. Do not assume deleted content can be recovered by replaying the job.',
    prerequisite: 'Confirm that the source content is available again.',
  },
  data_issues: {
    label: 'Storage or data guard',
    code: 'DATA_GUARD',
    tone: 'critical',
    posture: 'Blocked',
    signal:
      'The worker reported a size mismatch or insufficient destination capacity.',
    impact:
      'Affected output is not considered a successful download and may require storage remediation.',
    boundary:
      'Resolve capacity or integrity checks before retrying; a replay does not repair the underlying storage condition.',
    prerequisite: 'Resolve the reported storage or integrity condition.',
  },
  other: {
    label: 'Unclassified',
    code: 'UNCLASSIFIED',
    tone: 'review',
    posture: 'Inspect',
    signal:
      'The backend recorded a reason that is not mapped to a known recovery category.',
    impact:
      'Automatic recovery guidance would be speculative without inspecting the raw evidence.',
    boundary:
      'Review the recorded reason and message before creating a retry job.',
    prerequisite: 'Classify the raw error and resolve its prerequisite.',
  },
};

const CATEGORIZED_REASONS = new Set(Object.values(ERROR_CATEGORIES).flat());

function categoryMatches(category: string, reason: string): boolean {
  if (category === 'other') return !CATEGORIZED_REASONS.has(reason);
  return (ERROR_CATEGORIES[category] ?? []).includes(reason);
}

/** Total recorded download errors for a recovery category ('all', 'other' or a named group). */
export function countCategoryErrors(breakdown: Record<string, unknown>, category: string): number {
  return Object.entries(breakdown)
    .filter(([reason]) => category === 'all' || categoryMatches(category, reason))
    .reduce((sum, [, value]) => sum + Number(value || 0), 0);
}

export function failedItemReasons(item: Record<string, unknown>): string[] {
  if (!Array.isArray(item.errors)) return [];
  const reasons: string[] = [];
  for (const errorEntry of item.errors) {
    if (errorEntry && typeof errorEntry === 'object' && 'reason' in errorEntry) {
      reasons.push(String(errorEntry.reason));
    }
  }
  return reasons;
}

export function filterFailedItemsByCategory(
  failedItems: Array<Record<string, unknown>>,
  category: string,
): Array<Record<string, unknown>> {
  if (category === 'all') return failedItems;
  return failedItems.filter((item) =>
    failedItemReasons(item).some((reason) => categoryMatches(category, reason)),
  );
}
