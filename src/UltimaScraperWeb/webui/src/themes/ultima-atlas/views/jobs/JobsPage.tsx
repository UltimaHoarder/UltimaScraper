// Canonical jobs ledger for the WebUI. Queue behavior, API contracts, and
// recovery actions live in one implementation so registered themes cannot drift.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getWebSocketBaseUrl } from '../../../../api/http';
import { cancelJob, deleteJobs, getJobs, pauseJob, prioritizeJob, resumeJob, retryJob } from '../../../../api/jobs';
import type { DeleteJobsRequest, JobListResponse } from '../../../../api/types/jobs';
import { JobCreator } from '../../../../components/jobs/JobCreator';
import { JobDetailsModal } from '../../../../features/jobs/components/JobDetailsModal';
import { JobsOperationsLedger } from '../../../../features/jobs/components/JobsOperationsLedger';
import {
  getNonOverlappingRefetchInterval,
  isJobLifecycleRefreshEvent,
  JOBS_LIST_POLL_INTERVAL_MS,
} from '../../../../features/jobs/lib/jobLiveRefresh';
import { getJobActionErrorMessage } from '../../../../features/jobs/lib/jobUtils';
import { ConfirmDialog } from '../../../../shared/ui/ConfirmDialog';
import { ToastPortal, type ToastPortalState } from '../../../../shared/ui/ToastPortal';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import { OperationsNotice } from '../../../../shared/ui/operations/OperationsChrome';
import { isTypingTarget } from '../../../../shared/lib/keyboard';
import { useWebSocket, type WebSocketEvent } from '../../../../hooks/useWebSocket';
import './JobsPage.css';

interface JobsPageProps {
  showCreator?: boolean;
}

type JobEventType =
  | 'task_claimed'
  | 'task_started'
  | 'task_progress'
  | 'task_completed'
  | 'task_failed'
  | 'job_created'
  | 'job_started'
  | 'job_claimed'
  | 'job_tasks_routed'
  | 'job_materialized'
  | 'job_progress'
  | 'job_completed'
  | 'job_failed'
  | 'job_cancelled'
  | 'download_progress'
  | 'scrape_progress';

interface JobEvent {
  event?: JobEventType | string;
  type?: string;
  job_id?: string;
  id?: string;
}

const JOB_QUERY_REFRESH_COALESCE_MS = 500;

function positiveIntegerParam(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function pageSizeParam(value: string | null): number {
  const parsed = positiveIntegerParam(value, 50);
  return [25, 50, 100, 200].includes(parsed) ? parsed : 50;
}

const LEDGER_STATUSES = new Set([
  'all',
  'running',
  'pending',
  'failed',
  'completed',
  'cancelled',
]);

type DeleteTarget =
  | { kind: 'selected'; jobIds: string[] }
  | { kind: 'older'; hours: number };

function deleteTargetRequest(target: DeleteTarget): DeleteJobsRequest {
  return target.kind === 'selected'
    ? { job_ids: target.jobIds }
    : { older_than_hours: target.hours };
}

function deleteTargetLabel(target: DeleteTarget): string {
  if (target.kind === 'selected') {
    return `${target.jobIds.length} selected ${target.jobIds.length === 1 ? 'job' : 'jobs'}`;
  }
  if (target.hours === 24) return 'jobs older than 24 hours';
  return `jobs older than ${target.hours / 24} days`;
}

export function JobsPage({ showCreator = false }: JobsPageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [isCreatorOpen, setIsCreatorOpen] = useState(
    () => showCreator || searchParams.get('creator') === '1'
  );
  const [selectedJobId, setSelectedJobId] = useState<string | null>(
    () => searchParams.get('job') || null
  );
  const [statusFilter, setStatusFilter] = useState<string>(
    () => {
      const requestedStatus = searchParams.get('status') || 'all';
      return LEDGER_STATUSES.has(requestedStatus) ? requestedStatus : 'all';
    }
  );
  const [ownerFilter, setOwnerFilter] = useState<string>(() => searchParams.get('owner') || 'all');
  const [typeFilter, setTypeFilter] = useState<string>(() => searchParams.get('type') || 'all');
  const [scheduleFilter, setScheduleFilter] = useState<'all' | 'scheduled' | 'manual'>(() => {
    const raw = searchParams.get('schedule');
    return raw === 'scheduled' || raw === 'manual' ? raw : 'all';
  });
  const [showApiCommands, setShowApiCommands] = useState(false);
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('q') || '');
  const [queueNotice, setQueueNotice] = useState<ToastPortalState | null>(null);
  const [page, setPage] = useState(() => positiveIntegerParam(searchParams.get('page'), 1));
  const [pageSize, setPageSize] = useState(() => pageSizeParam(searchParams.get('rows')));
  const [cancelTargetJobIds, setCancelTargetJobIds] = useState<string[]>([]);
  const [deleteProgress, setDeleteProgress] = useState<{ completed: number; total: number; failed: number; rows?: number; table?: string }>({ completed: 0, total: 0, failed: 0 });
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [latestDownloadEvents, setLatestDownloadEvents] = useState<Record<string, WebSocketEvent>>({});
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRefreshJobIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (queueNotice?.type !== 'success') return;
    const timer = window.setTimeout(() => setQueueNotice(null), 8_000);
    return () => window.clearTimeout(timer);
  }, [queueNotice]);

  const statusQueryFilter = statusFilter === 'all' ? undefined : statusFilter;
  const trimmedSearchQuery = searchQuery.trim();

  const refreshJobs = useCallback(() => {
    return queryClient.invalidateQueries(
      { queryKey: ['jobs'], refetchType: 'active' },
      { cancelRefetch: false },
    );
  }, [queryClient]);

  const scheduleJobQueryRefresh = useCallback(
    (jobId: string) => {
      pendingRefreshJobIdsRef.current.add(jobId);
      if (refreshTimerRef.current) return;

      refreshTimerRef.current = setTimeout(() => {
        refreshTimerRef.current = null;
        const jobIds = [...pendingRefreshJobIdsRef.current];
        pendingRefreshJobIdsRef.current.clear();

        void refreshJobs();
        for (const pendingJobId of jobIds) {
          void queryClient.invalidateQueries(
            { queryKey: ['jobDetails', pendingJobId], refetchType: 'active' },
            { cancelRefetch: false },
          );
          void queryClient.invalidateQueries(
            { queryKey: ['jobTaskPage', pendingJobId], refetchType: 'active' },
            { cancelRefetch: false },
          );
        }
      }, JOB_QUERY_REFRESH_COALESCE_MS);
    },
    [queryClient, refreshJobs],
  );

  useEffect(() => {
    const pendingRefreshJobIds = pendingRefreshJobIdsRef.current;
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      pendingRefreshJobIds.clear();
    };
  }, []);

  const handleWebSocketMessage = useCallback(
    (wsEvent: WebSocketEvent) => {
      const event = wsEvent as unknown as JobEvent;
      const eventName = (event.event ?? event.type ?? '').toString();
      if (eventName === 'job_resync') {
        // Reconnected: events may have been missed while offline.
        void refreshJobs();
        return;
      }
      const jobId = event.job_id ?? event.id;
      if (!eventName || !jobId) return;

      const jobIdLower = jobId.toLowerCase();
      if (jobIdLower === 'api' || jobIdLower.startsWith('test-') || jobIdLower.startsWith('api-')) {
        return;
      }
      const transportType = String(event.type ?? '');
      if (
        eventName === 'download_progress' ||
        transportType === 'download_status' ||
        eventName.startsWith('download_')
      ) {
        if (jobId === selectedJobId) {
          setLatestDownloadEvents({ [jobId]: wsEvent });
        }
      }
      if (!isJobLifecycleRefreshEvent(eventName)) return;

      scheduleJobQueryRefresh(jobId);
    },
    [refreshJobs, scheduleJobQueryRefresh, selectedJobId]
  );

  useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    // Job-level changes, plus every event (live progress) for the selected job.
    topics: selectedJobId ? ['jobs', `job:${selectedJobId}`] : ['jobs'],
    onMessage: handleWebSocketMessage,
  });

  const typeQueryFilter = !typeFilter || typeFilter === 'all' ? undefined : typeFilter;
  const ownerQueryFilter = !ownerFilter || ownerFilter === 'all' ? undefined : ownerFilter;
  const scheduleQueryFilter = !scheduleFilter || scheduleFilter === 'all' ? undefined : scheduleFilter;

  const { data, isLoading, isFetching } = useQuery({
    queryKey: [
      'jobs',
      statusQueryFilter,
      page,
      pageSize,
      trimmedSearchQuery,
      showApiCommands,
      typeQueryFilter,
      ownerQueryFilter,
      scheduleQueryFilter,
    ],
    queryFn: () =>
      getJobs(
        statusQueryFilter,
        page,
        pageSize,
        trimmedSearchQuery || undefined,
        false,
        showApiCommands,
        typeQueryFilter,
        ownerQueryFilter,
        scheduleQueryFilter,
      ),
    refetchInterval: (query) =>
      getNonOverlappingRefetchInterval(query, JOBS_LIST_POLL_INTERVAL_MS),
    refetchIntervalInBackground: false,
    retry: 0,
  });

  const jobs = useMemo(() => data?.jobs ?? [], [data?.jobs]);
  const resolvedSelectedJobId = useMemo(() => {
    if (!selectedJobId) return null;
    return jobs.some((job) => job.job_id === selectedJobId) ? selectedJobId : null;
  }, [jobs, selectedJobId]);

  useEffect(() => {
    const nextParams = new URLSearchParams(searchParams);
    if (statusFilter !== 'all') nextParams.set('status', statusFilter);
    else nextParams.delete('status');
    if (ownerFilter !== 'all') nextParams.set('owner', ownerFilter);
    else nextParams.delete('owner');
    if (typeFilter !== 'all') nextParams.set('type', typeFilter);
    else nextParams.delete('type');
    if (scheduleFilter !== 'all') nextParams.set('schedule', scheduleFilter);
    else nextParams.delete('schedule');
    if (trimmedSearchQuery) nextParams.set('q', trimmedSearchQuery);
    else nextParams.delete('q');
    if (page > 1) nextParams.set('page', String(page));
    else nextParams.delete('page');
    if (pageSize !== 50) nextParams.set('rows', String(pageSize));
    else nextParams.delete('rows');
    if (resolvedSelectedJobId) nextParams.set('job', resolvedSelectedJobId);
    else nextParams.delete('job');
    if (isCreatorOpen && !showCreator) nextParams.set('creator', '1');
    else nextParams.delete('creator');

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [
    isCreatorOpen,
    ownerFilter,
    page,
    pageSize,
    resolvedSelectedJobId,
    scheduleFilter,
    searchParams,
    setSearchParams,
    showCreator,
    statusFilter,
    trimmedSearchQuery,
    typeFilter,
  ]);

  const cancelJobMutation = useMutation({
    mutationFn: async (jobIds: string[]) => {
      const results = await Promise.allSettled(jobIds.map((jobId) => cancelJob(jobId)));
      return {
        attempted: jobIds.length,
        succeeded: results.filter((result) => result.status === 'fulfilled').length,
        failures: results
          .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
          .map((result) => result.reason as unknown),
      };
    },
    onSuccess: (result) => {
      const failed = result.attempted - result.succeeded;
      setQueueNotice({
        type: failed > 0 ? (result.succeeded > 0 ? 'warning' : 'error') : 'success',
        message: failed > 0
          ? `Cancellation requested for ${result.succeeded} ${result.succeeded === 1 ? 'job' : 'jobs'}; ${failed} failed. ${getJobActionErrorMessage(result.failures[0], 'Review the failed queue entries and try again.')}`
          : `Cancellation requested for ${result.succeeded} ${result.succeeded === 1 ? 'job' : 'jobs'}.`,
      });
      void refreshJobs();
    },
  });

  const prioritizeJobMutation = useMutation({
    mutationFn: async (jobIds: string[]) => {
      const results = await Promise.allSettled(jobIds.map((jobId) => prioritizeJob(jobId)));
      return {
        attempted: jobIds.length,
        succeeded: results.filter((result) => result.status === 'fulfilled').length,
        failures: results
          .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
          .map((result) => result.reason as unknown),
      };
    },
    onSuccess: (result) => {
      const failed = result.attempted - result.succeeded;
      setQueueNotice({
        type: failed > 0 ? (result.succeeded > 0 ? 'warning' : 'error') : 'success',
        message: failed > 0
          ? `${result.succeeded} ${result.succeeded === 1 ? 'job' : 'jobs'} moved to the front; ${failed} failed. ${getJobActionErrorMessage(result.failures[0], 'Review the failed queue entries and try again.')}`
          : `${result.succeeded} ${result.succeeded === 1 ? 'job' : 'jobs'} moved to the front of the queue.`,
      });
      void refreshJobs();
    },
  });

  const retryJobsMutation = useMutation({
    mutationFn: async (jobIds: string[]) => {
      const results = await Promise.allSettled(jobIds.map((jobId) => retryJob(jobId)));
      return {
        attempted: jobIds.length,
        succeeded: results.filter((result) => result.status === 'fulfilled').length,
        failures: results
          .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
          .map((result) => result.reason as unknown),
      };
    },
    onSuccess: (result) => {
      const failed = result.attempted - result.succeeded;
      setQueueNotice({
        type: failed > 0 ? (result.succeeded > 0 ? 'warning' : 'error') : 'success',
        message: failed > 0
          ? `${result.succeeded} ${result.succeeded === 1 ? 'retry' : 'retries'} queued; ${failed} failed. ${getJobActionErrorMessage(result.failures[0], 'Review the failed queue entries and try again.')}`
          : `${result.succeeded} ${result.succeeded === 1 ? 'retry' : 'retries'} queued.`,
      });
      void refreshJobs();
    },
  });

  const pauseResumeJobMutation = useMutation({
    mutationFn: ({ jobId, action }: { jobId: string; action: 'pause' | 'resume' }) =>
      action === 'pause' ? pauseJob(jobId) : resumeJob(jobId),
    onSuccess: (_job, { action }) => {
      setQueueNotice({ type: 'success', message: action === 'pause' ? 'Job paused.' : 'Job resumed.' });
      void refreshJobs();
    },
    onError: (error, { action }) => {
      setQueueNotice({
        type: 'error',
        message: getJobActionErrorMessage(error, `Failed to ${action} job.`),
      });
    },
  });

  const deleteJobsMutation = useMutation({
    mutationFn: (target: DeleteTarget) => {
      setDeleteProgress({ completed: 0, total: 0, failed: 0 });
      return deleteJobs(deleteTargetRequest(target), (progress) => {
        setDeleteProgress({ ...progress, failed: progress.failed ?? 0 });
        if (progress.status && progress.job_id) {
          queryClient.setQueriesData<JobListResponse>({ queryKey: ['jobs'] }, (cached) =>
            cached ? { ...cached, jobs: cached.jobs.map((job) => job.job_id === progress.job_id
              ? { ...job, status: progress.status! } : job) } : cached);
          scheduleJobQueryRefresh(progress.job_id);
        }
      });
    },
    onSuccess: (result) => {
      setDeleteTarget(null);
      setQueueNotice({
        type: result.failed > 0 ? (result.deleted + (result.queued ?? 0) > 0 ? 'warning' : 'error') : 'success',
        message: result.failed > 0
          ? `Deletion queued for ${result.queued ?? 0} jobs; ${result.failed} could not be queued. ${getJobActionErrorMessage({ message: result.failures[0]?.error }, 'Review the failed jobs and try again.')}`
          : result.queued
            ? `Deletion queued for ${result.queued} jobs. Track cleanup on the jobs page.`
            : `Deleted ${result.deleted} jobs.`,
      });
      void refreshJobs();
    },
    onError: (error) => {
      setQueueNotice({ type: 'error', message: getJobActionErrorMessage(error, 'Job deletion failed.') });
    },
  });

  const handleJobCreated = useCallback(
    () => {
      setIsCreatorOpen(false);
      void refreshJobs();
      navigate('/jobs');
    },
    [navigate, refreshJobs]
  );

  const activeSelectedJob = useMemo(() => {
    if (!resolvedSelectedJobId) return null;
    return jobs.find((job) => job.job_id === resolvedSelectedJobId) ?? null;
  }, [jobs, resolvedSelectedJobId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.altKey ||
        isTypingTarget(event.target)
      ) {
        return;
      }

      if (event.key === 'Escape') {
        if (isCreatorOpen) {
          event.preventDefault();
          setIsCreatorOpen(false);
          return;
        }

        if (resolvedSelectedJobId) {
          event.preventDefault();
          setSelectedJobId(null);
        }
        return;
      }

      if (
        event.key.toLowerCase() === 'n' &&
        !event.ctrlKey &&
        !event.metaKey
      ) {
        event.preventDefault();
        setIsCreatorOpen(true);
        return;
      }

      if (
        isCreatorOpen ||
        resolvedSelectedJobId ||
        (event.key !== 'ArrowDown' && event.key !== 'ArrowUp')
      ) {
        return;
      }

      if (!jobs.length) {
        return;
      }

      event.preventDefault();
      const currentIndex = resolvedSelectedJobId
        ? jobs.findIndex((job) => job.job_id === resolvedSelectedJobId)
        : -1;

      const nextIndex =
        event.key === 'ArrowDown'
          ? Math.min(currentIndex + 1, jobs.length - 1)
          : currentIndex === -1
            ? jobs.length - 1
            : Math.max(currentIndex - 1, 0);

      setSelectedJobId(jobs[nextIndex]?.job_id ?? null);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isCreatorOpen, jobs, resolvedSelectedJobId]);

  const total = data?.total ?? 0;
  const isMutating =
    cancelJobMutation.isPending || prioritizeJobMutation.isPending || retryJobsMutation.isPending
    || pauseResumeJobMutation.isPending || deleteJobsMutation.isPending;

  return (
    <div className="jobs-page operations-ledger-page">
      <ToastPortal toast={queueNotice} onDismiss={() => setQueueNotice(null)} />
      {isCreatorOpen ? (
        <>
          <WorkspacePageHeader
            eyebrow="Jobs"
            title="Create job"
            subtitle="Compose tasks, schedules, or templates for the live queue."
            icon="◇"
          />
          <OperationsNotice
            tone="info"
            title="Job builder"
            actions={
              <button className="ops-action ops-action-secondary" onClick={() => setIsCreatorOpen(false)}>
                Back to ledger
              </button>
            }
          >
            Compose tasks, schedules, or templates here. Creating a job returns you to the live queue automatically.
          </OperationsNotice>
          <div className="creator-section">
            <JobCreator onJobCreated={handleJobCreated} onCancel={() => setIsCreatorOpen(false)} />
          </div>
        </>
      ) : (
        <>
          <JobsOperationsLedger
            jobs={jobs}
            showApiCommands={showApiCommands}
            onShowApiCommandsChange={(value) => {
              setShowApiCommands(value);
              setPage(1);
            }}
            total={total}
            page={page}
            pageSize={pageSize}
            searchQuery={searchQuery}
            statusFilter={statusFilter}
            selectedJobId={resolvedSelectedJobId}
            isLoading={isLoading}
            isFetching={isFetching && !isLoading}
            isMutating={isMutating}
            onSearchChange={(value) => {
              setSearchQuery(value);
              setPage(1);
            }}
            onStatusFilterChange={(value) => {
              setStatusFilter(value);
              setPage(1);
            }}
            ownerFilter={ownerFilter}
            onOwnerFilterChange={(value) => {
              setOwnerFilter(value);
              setPage(1);
            }}
            typeFilter={typeFilter}
            onTypeFilterChange={(value) => {
              setTypeFilter(value);
              setPage(1);
            }}
            scheduleFilter={scheduleFilter}
            onScheduleFilterChange={(value) => {
              setScheduleFilter(value);
              setPage(1);
            }}
            availableTypes={data?.available_types}
            availableOwners={data?.available_owners}
            onPageChange={setPage}
            onPageSizeChange={(value) => {
              setPageSize(value);
              setPage(1);
            }}
            onJobClick={(job) => setSelectedJobId(job.job_id)}
            onPrioritizeJobs={(jobIds) => prioritizeJobMutation.mutate(jobIds)}
            onRetryJobs={(jobIds) => retryJobsMutation.mutate(jobIds)}
            onPauseResumeJob={(jobId, action) => pauseResumeJobMutation.mutate({ jobId, action })}
            onRequestCancelJobs={setCancelTargetJobIds}
            onRequestDeleteJobs={(jobIds) => setDeleteTarget({ kind: 'selected', jobIds })}
            onRequestDeleteOlderThan={(hours) => setDeleteTarget({ kind: 'older', hours })}
            onNewJob={() => setIsCreatorOpen(true)}
            onNotice={(message) => setQueueNotice({ type: 'success', message })}
          />

          {activeSelectedJob ? (
            <JobDetailsModal
              key={activeSelectedJob.job_id}
              job={activeSelectedJob}
              liveEvent={latestDownloadEvents[activeSelectedJob.job_id] ?? null}
              onClose={() => setSelectedJobId(null)}
            />
          ) : null}
        </>
      )}

      <ConfirmDialog
        isOpen={cancelTargetJobIds.length > 0}
        title={cancelTargetJobIds.length === 1 ? 'Cancel job?' : `Cancel ${cancelTargetJobIds.length} jobs?`}
        description={
          cancelTargetJobIds.length === 1
            ? `Stop job ${cancelTargetJobIds[0]} immediately. Running tasks will be interrupted and the queue entry will move to cancelled state.`
            : cancelTargetJobIds.length > 1
              ? `Stop ${cancelTargetJobIds.length} selected jobs immediately. Running tasks will be interrupted and each queue entry will move to cancelled state.`
            : ''
        }
        confirmLabel={cancelTargetJobIds.length === 1 ? 'Cancel job' : 'Cancel jobs'}
        isPending={cancelJobMutation.isPending}
        onClose={() => setCancelTargetJobIds([])}
        onConfirm={() => {
          if (cancelTargetJobIds.length === 0) return;
          cancelJobMutation.mutate(cancelTargetJobIds);
          setCancelTargetJobIds([]);
        }}
      />

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title={deleteTarget ? `Delete ${deleteTargetLabel(deleteTarget)}?` : 'Delete jobs?'}
        description={
          deleteTarget?.kind === 'selected'
            ? 'This permanently removes the selected jobs and their task history. Any pending, running, staging, or materializing work is cancelled first.'
            : 'This permanently removes every matching job and its task history. Any pending, running, staging, or materializing work is cancelled first.'
        }
        confirmLabel="Delete jobs"
        isPending={deleteJobsMutation.isPending}
        progress={deleteProgress}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteJobsMutation.mutate(deleteTarget);
        }}
      />

    </div>
  );
}
