import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { JobCreator, type JobCreatorChanges } from '../../../components/jobs/JobCreator';
import { getAuthList } from '../../../api/auths';
import { getMediaProxyUrl } from '../../../api/media';
import { listProxies } from '../../../api/network';
import { getSettings } from '../../../api/settings';
import { getAllBackends, getBackendStatus } from '../../../api/system';
import {
  cancelJob,
  pauseJob,
  resumeJob,
  createJobTemplateFromJob,
  getJobDetails,
  getJobs,
  getJobRuntimeSamples,
  getJobTasks,
  prioritizeJob,
  retryJob,
  streamJobTasks,
  updateJob,
} from '../../../api/jobs';
import type { AuthListResponse } from '../../../api/types/auths';
import type {
  CreateJobRequest,
  Job,
  JobDetail,
  JobRuntimeSample,
  JobRuntimeSamplesPage,
  TaskDetail,
  TaskPageResponse,
  TaskPayload,
  UpdateJobRequest,
} from '../../../api/types/jobs';
import type { WebSocketEvent } from '../../../hooks/useWebSocket';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import {
  getNonOverlappingRefetchInterval,
  JOB_DETAILS_POLL_INTERVAL_MS,
} from '../lib/jobLiveRefresh';
import {
  calculateJobEta,
  extractInactiveAuthId,
  formatDateTime,
  formatDuration,
  getIntervalParts,
  getJobActionErrorMessage,
  getJobPreparationProgress,
  getRetryErrorMessage,
  getTaskDownloadErrorCount,
  getTemplateErrorMessage,
  resolveEffectiveJobStatus,
  streamTaskKey,
  toLocalDateTimeInput,
} from '../lib/jobUtils';
import { useJobDiagnosticsTelemetry } from '../lib/useJobDiagnosticsTelemetry';
import { JobDiagnosticsReport } from './JobDiagnosticsReport';
import { JobRunbookPipeline } from './JobRunbookPipeline';
import {
  countCategoryErrors,
  ERROR_CATEGORIES,
  failedItemReasons,
  filterFailedItemsByCategory,
  RECOVERY_CAUSES,
} from '../lib/jobRecoveryCatalog';
import { getTaskProxySummary } from '../lib/taskProxyUtils';
import './JobDetailsModal.css';
import { JobDeletionProgress } from './JobDeletionProgress';
import { copyText } from '../../../utils/clipboard';

interface TaskFailureEvidence {
  evidenceId: string;
  task: TaskDetail;
  taskType: string;
  contentType: string;
  username: string;
  site: string;
  status: string;
  messages: string[];
}

const TASK_PAGE_SIZE = 100;
const STREAM_BUFFER_LIMIT = 250;
// SSE streaming emits every task in the job. For very large jobs the flood of
// messages makes the browser unresponsive and the Pipeline tab never paints
// any rows. Above this total, fall back to REST polling only.
const STREAM_MAX_TOTAL_TASKS = 1000;
const TASK_STATE_FILTERS = [
  { value: '', label: 'All states' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'deferred', label: 'Deferred' },
];

function getHttpStatusCode(error: unknown): number | null {
  if (!error || typeof error !== 'object' || !("response" in error)) {
    return null;
  }

  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === 'number' ? response.status : null;
}

interface JobDetailsModalProps {
  job: Job;
  onClose: () => void;
  layout?: 'modal' | 'panel';
  liveEvent?: WebSocketEvent | null;
}

export function JobDetailsModal(props: JobDetailsModalProps) {
  return props.job.status === 'deleting'
    ? <JobDeletionProgress job={props.job} onClose={props.onClose} layout={props.layout} />
    : <JobExecutionDetailsModal {...props} />;
}

function JobExecutionDetailsModal({
  job,
  onClose,
  layout = 'modal',
  liveEvent = null,
}: JobDetailsModalProps) {
  'use no memo';

  const isPanel = layout === 'panel';
  const queryClient = useQueryClient();
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const { data: details, isLoading, error } = useQuery<JobDetail>({
    queryKey: ['jobDetails', job.job_id],
    queryFn: () => getJobDetails(job.job_id, false),
    refetchInterval: (query) => {
      const liveStatus = String(
        (query.state.data as JobDetail | undefined)?.status || job.status
      ).toLowerCase();
      const isTerminal =
        liveStatus === 'completed' ||
        liveStatus === 'failed' ||
        liveStatus === 'cancelled' ||
        liveStatus === 'canceled' ||
        liveStatus === 'stopped';
      const isLiveStatus = !isTerminal;
      return getNonOverlappingRefetchInterval(
        query,
        JOB_DETAILS_POLL_INTERVAL_MS,
        isLiveStatus,
      );
    },
    refetchIntervalInBackground: false,
    retry: 0,
  });
  const detailStatusCode = getHttpStatusCode(error);
  const isMissingJob = detailStatusCode === 404;
  const hasRetainedJobDetails = details !== undefined;
  const canRenderJobDetails = !error || hasRetainedJobDetails;
  const rawStatus = String(details?.status || job.status || '').toLowerCase();
  const rawStats = details?.task_stats ?? job.task_stats;
  const initialTotal = rawStats?.total ?? job.task_count ?? 0;
  const initialTerminal = rawStats ? rawStats.completed + rawStats.failed : ((job.completed_tasks || 0) + (job.failed_tasks || 0));
  const initialProgress = initialTotal > 0 ? Math.min(100, Math.round((initialTerminal / initialTotal) * 100)) : 0;
  const terminalJobError =
    details?.result_error?.trim() ||
    details?.materialization_error?.trim() ||
    job.materialization_error?.trim() ||
    null;
  const liveStatus = terminalJobError
    ? 'failed'
    : resolveEffectiveJobStatus(rawStatus, rawStats, initialProgress);
  const isTerminalStatus =
    liveStatus === 'completed' ||
    liveStatus === 'failed' ||
    liveStatus === 'cancelled' ||
    liveStatus === 'canceled' ||
    liveStatus === 'stopped';
  const isLiveJob = !isTerminalStatus && !details?.completed_at;
  const totalTaskCount =
    details?.task_stats?.total ?? job.task_stats?.total ?? 0;
  // SSE streams every task in the job, which blocks the UI for huge jobs.
  // Gate the stream so large jobs fall back to REST polling only.
  const canStreamTasks = totalTaskCount > 0 && totalTaskCount <= STREAM_MAX_TOTAL_TASKS;

  const [streamedTasks, setStreamedTasks] = useState<TaskDetail[]>([]);
  const [taskItems, setTaskItems] = useState<TaskDetail[]>([]);
  const [taskCursor, setTaskCursor] = useState<string | null>(null);
  const [hasMoreTasks, setHasMoreTasks] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingMoreTasks, setIsLoadingMoreTasks] = useState(false);
  const [selectedAuthId, setSelectedAuthId] = useState<number | ''>('');
  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'pipeline' | 'diagnostics' | 'errors' | 'config'>('pipeline');
  const [preservedModalSize, setPreservedModalSize] = useState<{ width: number; height: number } | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const runtimeSampleCursorRef = useRef<{
    jobId: string;
    afterId: string | undefined;
  }>({ jobId: job.job_id, afterId: undefined });
  const [runtimeSamplePageCursor, setRuntimeSamplePageCursor] = useState<{
    jobId: string;
    afterId: string | undefined;
  }>({ jobId: job.job_id, afterId: undefined });
  const [runtimeSampleState, setRuntimeSampleState] = useState<{
    jobId: string;
    samples: JobRuntimeSample[];
  }>(() => ({ jobId: job.job_id, samples: [] }));
  const runtimeSamples = runtimeSampleState.jobId === job.job_id
    ? runtimeSampleState.samples
    : [];
  const runtimeSamplePageCursorId = runtimeSamplePageCursor.jobId === job.job_id
    ? runtimeSamplePageCursor.afterId
    : undefined;
  useEffect(() => {
    if (runtimeSampleCursorRef.current.jobId === job.job_id) return;
    runtimeSampleCursorRef.current = { jobId: job.job_id, afterId: undefined };
    setRuntimeSamplePageCursor({ jobId: job.job_id, afterId: undefined });
    setRuntimeSampleState({ jobId: job.job_id, samples: [] });
  }, [job.job_id]);
  const runtimeSamplesQuery = useQuery<
    JobRuntimeSamplesPage & { requestedAfter: string | undefined }
  >({
    queryKey: ['jobRuntimeSamples', job.job_id, runtimeSamplePageCursorId],
    // Samples are owned by runtimeSampleState; release consumed page copies.
    gcTime: 0,
    queryFn: async ({ signal }) => {
      const requestedAfter = runtimeSampleCursorRef.current.jobId === job.job_id
        ? runtimeSampleCursorRef.current.afterId
        : undefined;
      return {
        ...(await getJobRuntimeSamples(job.job_id, requestedAfter, signal)),
        requestedAfter,
      };
    },
    enabled: activeTab === 'diagnostics',
    refetchInterval: (query) => {
      const page = query.state.data as
        | (JobRuntimeSamplesPage & { requestedAfter: string | undefined })
        | undefined;
      if (page?.has_more) return false;
      return isLiveJob ? 1_000 : false;
    },
    refetchIntervalInBackground: false,
    retry: 0,
  });
  useEffect(() => {
    const page = runtimeSamplesQuery.data;
    if (!page) return;
    const activeAfterId = runtimeSampleCursorRef.current.jobId === job.job_id
      ? runtimeSampleCursorRef.current.afterId
      : undefined;
    if (page.requestedAfter !== activeAfterId) return;

    if (page.next_after_id && page.samples.length > 0) {
      runtimeSampleCursorRef.current = {
        jobId: job.job_id,
        afterId: page.next_after_id,
      };
    }
    if (
      page.has_more &&
      page.samples.length > 0 &&
      page.next_after_id &&
      page.next_after_id !== page.requestedAfter
    ) {
      setRuntimeSamplePageCursor({
        jobId: job.job_id,
        afterId: page.next_after_id,
      });
    }
    setRuntimeSampleState((current) => {
      const state = current.jobId === job.job_id
        ? current
        : { jobId: job.job_id, samples: [] };
      const knownCursors = new Set(state.samples.map((sample) => sample.cursor));
      const appended = page.samples.filter((sample) => {
        if (knownCursors.has(sample.cursor)) return false;
        knownCursors.add(sample.cursor);
        return true;
      });
      if (appended.length === 0 && current.jobId === job.job_id) return current;
      return { ...state, samples: [...state.samples, ...appended] };
    });
  }, [job.job_id, runtimeSamplesQuery.data]);
  const [selectedBaselineJobId, setSelectedBaselineJobId] = useState<string | null>(null);
  const { data: baselineJobDetail } = useQuery<JobDetail>({
    queryKey: ['baselineJobDetail', selectedBaselineJobId],
    queryFn: () => getJobDetails(selectedBaselineJobId!, false),
    enabled: Boolean(selectedBaselineJobId),
    staleTime: 60_000,
  });
  const { data: historicalJobs } = useQuery<Job[]>({
    queryKey: ['historicalJobsForDiagnostics', job.site, job.job_name],
    queryFn: async () => {
      const pageSize = 200;
      const jobs: Job[] = [];
      let page = 1;
      let total = Number.POSITIVE_INFINITY;

      while (jobs.length < total) {
        const response = await getJobs(
          undefined,
          page,
          pageSize,
          undefined,
          false,
          false,
          undefined,
          undefined,
          undefined,
          job.site || undefined,
        );
        jobs.push(...response.jobs);
        total = response.total;
        if (response.jobs.length < pageSize) break;
        page += 1;
      }

      return jobs;
    },
    enabled: activeTab === 'diagnostics',
    staleTime: 60_000,
  });
  const [errorTab, setErrorTab] = useState<string>('all');
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [diagnosticCopyState, setDiagnosticCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const [taskStateFilter, setTaskStateFilter] = useState('');
  const [taskTypeFilter, setTaskTypeFilter] = useState('');
  const [hopUsedMin, setHopUsedMin] = useState('');
  const [hopUsedMax, setHopUsedMax] = useState('');
  const [geoBlockedFilter, setGeoBlockedFilter] = useState(false);
  const [errorOnlyFilter, setErrorOnlyFilter] = useState(false);
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  const pipelineRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<(() => void) | null>(null);
  const streamedTaskMapRef = useRef<Map<string, TaskDetail>>(new Map());

  const changeTab = (nextTab: 'pipeline' | 'diagnostics' | 'errors' | 'config') => {
    if (nextTab === 'pipeline') {
      setPreservedModalSize(null);
    } else if (activeTab === 'pipeline' && !isPanel) {
      const { width, height } = modalRef.current?.getBoundingClientRect() ?? { width: 0, height: 0 };
      if (width > 0 && height > 0) setPreservedModalSize({ width, height });
    }
    setActiveTab(nextTab);
  };

  useEffect(() => {
    if (!isLiveJob) return;
    const interval = window.setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);
    return () => window.clearInterval(interval);
  }, [isLiveJob]);

  const { data: taskPage, isLoading: isLoadingTaskPage } = useQuery<TaskPageResponse>({
    queryKey: ['jobTaskPage', job.job_id, taskStateFilter, taskTypeFilter, errorOnlyFilter],
    queryFn: () =>
      getJobTasks(job.job_id, {
        limit: TASK_PAGE_SIZE,
        state: taskStateFilter || undefined,
        task_type: taskTypeFilter || undefined,
        error_only: errorOnlyFilter || undefined,
      }),
    staleTime: 0,
    refetchInterval: (query) =>
      getNonOverlappingRefetchInterval(
        query,
        JOB_DETAILS_POLL_INTERVAL_MS,
        isLiveJob,
      ),
    refetchIntervalInBackground: false,
    retry: 0,
  });

  useEffect(() => {
    const pipeline = pipelineRef.current;
    if (pipeline) {
      if (typeof pipeline.scrollTo === 'function') {
        pipeline.scrollTo({ top: 0 });
      } else {
        pipeline.scrollTop = 0;
      }
    }
    setTaskItems([]);
    setTaskCursor(null);
    setHasMoreTasks(false);
    streamedTaskMapRef.current.clear();
    setStreamedTasks([]);
  }, [job.job_id, taskStateFilter, taskTypeFilter, errorOnlyFilter]);

  useEffect(() => {
    setSelectedEvidenceId(null);
  }, [errorTab, job.job_id]);

  useEffect(() => {
    setTaskItems(taskPage?.tasks ?? []);
    setTaskCursor(taskPage?.next_cursor ?? null);
    setHasMoreTasks(taskPage?.has_more ?? false);
  }, [taskPage]);

  useEffect(() => {
    streamedTaskMapRef.current.clear();
    setStreamedTasks([]);
    setIsStreaming(false);

    if (streamRef.current) {
      streamRef.current();
    }

    const shouldStream = activeTab === 'pipeline' && isLiveJob && canStreamTasks;
    if (!shouldStream) {
      streamRef.current = null;
      return () => undefined;
    }

    setIsStreaming(true);
    const stopStream = streamJobTasks(
      job.job_id,
      (task) => {
        const key = streamTaskKey(task);
        const map = streamedTaskMapRef.current;

        if (map.has(key)) {
          map.delete(key);
        }
        map.set(key, task);

        while (map.size > STREAM_BUFFER_LIMIT) {
          const oldest = map.keys().next().value as string | undefined;
          if (!oldest) break;
          map.delete(oldest);
        }

        setStreamedTasks(Array.from(map.values()));
      },
      () => {
        setIsStreaming(false);
        void queryClient.invalidateQueries({ queryKey: ['jobTaskPage', job.job_id] });
        void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
      },
      () => {
        setIsStreaming(false);
        void queryClient.invalidateQueries({ queryKey: ['jobTaskPage', job.job_id] });
      },
      {
        limit: STREAM_BUFFER_LIMIT,
        state: taskStateFilter || undefined,
        task_type: taskTypeFilter || undefined,
        error_only: errorOnlyFilter || undefined,
      },
    );

    streamRef.current = stopStream;
    const streamedTaskMap = streamedTaskMapRef.current;

    return () => {
      streamedTaskMap.clear();
      stopStream();
      if (streamRef.current === stopStream) {
        streamRef.current = null;
      }
    };
  }, [activeTab, canStreamTasks, errorOnlyFilter, isLiveJob, job.job_id, queryClient, taskStateFilter, taskTypeFilter]);

  const tasksToUse = useMemo(
    () => (streamedTasks.length > 0 ? streamedTasks : taskItems),
    [streamedTasks, taskItems]
  );

  const { data: networkProxies } = useQuery({
    queryKey: ['networkProxies'],
    queryFn: listProxies,
    staleTime: 30000,
  });

  const { data: backendStatus } = useQuery({
    queryKey: ['system', 'backend'],
    queryFn: getBackendStatus,
    staleTime: 30000,
  });

  const { data: clusterBackends } = useQuery({
    queryKey: ['system', 'all-backends'],
    queryFn: getAllBackends,
    staleTime: 30000,
    enabled: Boolean(backendStatus?.distributed_mode),
  });

  const { data: settingsData } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 60000,
  });

  const workerPoolSize = useMemo(() => {
    if (clusterBackends?.backends && clusterBackends.backends.length > 0) {
      const activeBackends = clusterBackends.backends.filter((b) => {
        const s = (b.status || '').toLowerCase();
        return s === 'online' || s === 'active' || s === 'busy' || s === 'idle';
      });

      if (activeBackends.length > 0) {
        const clusterTotal = activeBackends.reduce((sum, b) => {
          const isLocal =
            (backendStatus?.backend_id && b.backend_id === backendStatus.backend_id) ||
            (clusterBackends.local_backend_id && b.backend_id === clusterBackends.local_backend_id);
          const localOverride = isLocal
            ? settingsData?.worker_pool?.size || backendStatus?.max_workers
            : undefined;
          const workers = localOverride || b.max_workers || b.workers?.length || b.active_workers || 0;
          return sum + workers;
        }, 0);
        if (clusterTotal > 0) return clusterTotal;
      }
    }
    if (settingsData?.worker_pool?.size && settingsData.worker_pool.size > 0) {
      return settingsData.worker_pool.size;
    }
    if (backendStatus?.max_workers && backendStatus.max_workers > 0) {
      return backendStatus.max_workers;
    }
    if (backendStatus) {
      const localTotal = backendStatus.worker_count || backendStatus.workers?.length;
      if (localTotal && localTotal > 0) return localTotal;
    }
    if (backendStatus?.active_workers && backendStatus.active_workers > 0) {
      return backendStatus.active_workers;
    }
    return 32;
  }, [clusterBackends, backendStatus, settingsData]);

  const diagnosticsTelemetry = useJobDiagnosticsTelemetry(
    job,
    details,
    tasksToUse,
    networkProxies,
    isLiveJob,
    workerPoolSize,
    details?.task_stats_observed_at_ms ?? undefined,
    runtimeSamples,
  );
  const identityTask = tasksToUse.find((task) => task.username) ?? tasksToUse[0] ?? null;
  const summaryIdentityTask = job.tasks?.find((task) => task.username) ?? job.tasks?.[0] ?? null;
  const runbookUsername = identityTask?.username || summaryIdentityTask?.username || null;
  const runbookSite = String(
    details?.site || identityTask?.site || summaryIdentityTask?.site || '',
  ).toLowerCase();
  const runbookSiteLabel =
    runbookSite === 'onlyfans'
      ? 'OnlyFans'
      : runbookSite
        ? runbookSite.charAt(0).toUpperCase() + runbookSite.slice(1)
        : 'Job';
  const runbookOperation =
    job.job_name
      .replace(/@[\w.-]+/g, '')
      .replace(/\([^)]*\)/g, '')
      .trim() ||
    details?.job_type?.replace(/_/g, ' ') ||
    'execution';
  const runbookTitle = runbookUsername ? `@${runbookUsername}` : (job.job_name || `Job ${job.job_id}`);

  const loadMoreTasks = async () => {
    if (!taskCursor || isLoadingMoreTasks) return;
    setIsLoadingMoreTasks(true);
    try {
      const nextPage = await getJobTasks(job.job_id, {
        cursor: taskCursor,
        limit: TASK_PAGE_SIZE,
        state: taskStateFilter || undefined,
        task_type: taskTypeFilter || undefined,
        error_only: errorOnlyFilter || undefined,
      });
      setTaskItems((current) => [...current, ...nextPage.tasks]);
      setTaskCursor(nextPage.next_cursor);
      setHasMoreTasks(nextPage.has_more);
    } finally {
      setIsLoadingMoreTasks(false);
    }
  };

  const inactiveAuthId = useMemo(
    () => extractInactiveAuthId(details, tasksToUse),
    [details, tasksToUse]
  );
  const site = details?.site ? details.site.toLowerCase() : null;
  const shouldShowRetry = job.status === 'failed' && inactiveAuthId !== null && !!site;

  const argsPayload = useMemo(() => {
    if (!details?.args || typeof details.args !== 'object') return null;
    return details.args as Record<string, unknown>;
  }, [details]);

  const initialTasks = useMemo<TaskPayload[]>(() => {
    if (!Array.isArray(tasksToUse)) return [];
    const parsed: TaskPayload[] = [];
    for (const task of tasksToUse) {
      if (!task || typeof task !== 'object') continue;
      if (typeof task.task_type !== 'string') continue;
      const params =
        task.payload && typeof task.payload === 'object'
          ? (task.payload as Record<string, unknown>)
          : {};
      parsed.push({ task_type: task.task_type, params });
    }
    return parsed;
  }, [tasksToUse]);

  const initialSchedule = useMemo(() => {
    const rawSchedule = argsPayload?.schedule;
    const schedule =
      rawSchedule && typeof rawSchedule === 'object'
        ? (rawSchedule as Record<string, unknown>)
        : null;
    const scheduledFor =
      typeof schedule?.scheduled_for === 'string' ? schedule.scheduled_for : job.scheduled_for ?? '';
    const cron = typeof schedule?.cron === 'string' ? schedule.cron : job.cron ?? '';
    const intervalSeconds =
      typeof schedule?.interval_seconds === 'number'
        ? schedule.interval_seconds
        : job.interval_seconds ?? null;
    const intervalParts = getIntervalParts(intervalSeconds);
    const startImmediately =
      typeof schedule?.start_immediately === 'boolean' ? schedule.start_immediately : true;
    const scheduleEnabled = Boolean(scheduledFor || cron || intervalSeconds);
    const scheduleType: 'once' | 'cron' | 'interval' = scheduledFor
      ? 'once'
      : cron
        ? 'cron'
        : 'interval';

    return {
      enabled: scheduleEnabled,
      type: scheduleType,
      at: scheduledFor ? toLocalDateTimeInput(scheduledFor) : '',
      intervalValue: intervalParts?.value ?? 1,
      intervalUnit: intervalParts?.unit ?? 'hours',
      cron,
      startImmediately,
    };
  }, [argsPayload, job]);

  const {
    data: activeAuths,
    isLoading: isAuthLoading,
    error: authError,
  } = useQuery<AuthListResponse>({
    queryKey: ['auths', 'active', site],
    queryFn: () => getAuthList(site ?? undefined, true),
    enabled: shouldShowRetry && !!site,
  });
  const retryAuths = activeAuths?.auths ?? [];
  const effectiveSelectedAuthId: number | '' =
    selectedAuthId === '' ? (retryAuths[0]?.user_id ?? '') : selectedAuthId;
  const hasSelectedRetryAuth = typeof effectiveSelectedAuthId === 'number';

  const retryMutation = useMutation({
    mutationFn: (authId: number) => retryJob(job.job_id, authId),
    onSuccess: () => {
      onClose();
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
    },
  });

  const retryAnyMutation = useMutation({
    mutationFn: () => retryJob(job.job_id),
    onSuccess: () => {
      onClose();
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
    },
  });

  const prioritizeMutation = useMutation({
    mutationFn: () => prioritizeJob(job.job_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
    },
  });

  const cancelJobMutation = useMutation({
    mutationFn: () => cancelJob(job.job_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
      onClose();
    },
    onError: (mutationError) => {
      const message = getJobActionErrorMessage(mutationError, 'Failed to cancel job.');
      if (message.toLowerCase().includes('already cancelled')) {
        void queryClient.invalidateQueries({ queryKey: ['jobs'] });
        void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
        onClose();
      }
    },
  });

  const pauseResumeMutation = useMutation({
    mutationFn: () => liveStatus === 'paused' ? resumeJob(job.job_id) : pauseJob(job.job_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
    },
  });

  const saveTemplateMutation = useMutation({
    mutationFn: (templateName: string) =>
      createJobTemplateFromJob(job.job_id, {
        name: templateName,
        created_by: 'webui',
      }),
    onSuccess: (template) => {
      setTemplateMessage(`Template "${template.name}" saved.`);
    },
    onError: (mutationError) => {
      setTemplateMessage(getTemplateErrorMessage(mutationError));
    },
  });

  const handleEditSubmit = async (payload: CreateJobRequest, changes: JobCreatorChanges) => {
    const updatePayload: UpdateJobRequest = {
      job_name: payload.job_name,
    };
    if (changes.tasksChanged) updatePayload.tasks = payload.tasks;
    if (changes.scheduleChanged) updatePayload.schedule = payload.schedule ?? {};
    return updateJob(job.job_id, updatePayload);
  };

  const effectiveStartedAt =
    details?.started_at ??
    (job as unknown as { started_at?: string | null }).started_at ??
    details?.last_ran_at ??
    job.last_ran_at ??
    details?.created_at ??
    job.created_at ??
    null;

  const duration =
    effectiveStartedAt && details?.completed_at
      ? Math.round(
          (new Date(details.completed_at).getTime() - new Date(effectiveStartedAt).getTime()) / 1000
        )
      : null;

  const totalDownloadErrors = useMemo(
    () => tasksToUse.reduce((sum, task) => sum + getTaskDownloadErrorCount(task), 0),
    [tasksToUse]
  );
  const aggregateTaskStats = details?.task_stats ?? job.task_stats;
  const materializationStatus =
    details?.materialization_status ?? job.materialization_status ?? null;
  const materializedTasks =
    details?.materialized_tasks ?? job.materialized_tasks ?? 0;
  const materializationTotal =
    details?.materialization_total ??
    job.materialization_total ??
    aggregateTaskStats?.total ??
    job.task_count ??
    0;
  const preparation = getJobPreparationProgress({
    status: liveStatus,
    materialization_status: materializationStatus,
    materialized_tasks: materializedTasks,
    materialization_total: materializationTotal,
    task_stats: aggregateTaskStats,
  });
  const hasTaskFilters = Boolean(
    taskStateFilter ||
      taskTypeFilter ||
      hopUsedMin ||
      hopUsedMax ||
      geoBlockedFilter ||
      errorOnlyFilter,
  );
  const loadedTasksCoverJob =
    !hasTaskFilters &&
    (aggregateTaskStats?.total ?? 0) > 0 &&
    tasksToUse.length >= (aggregateTaskStats?.total ?? 0);
  const loadedTerminalTaskCount = tasksToUse.filter((task) =>
    ['completed', 'failed', 'cancelled'].includes(task.status),
  ).length;
  const terminalTaskCount = loadedTasksCoverJob
    ? loadedTerminalTaskCount
    : aggregateTaskStats
      ? aggregateTaskStats.completed + aggregateTaskStats.failed
      : loadedTerminalTaskCount;
  const executionProgress = (aggregateTaskStats?.total ?? tasksToUse.length) > 0
    ? Math.min(100, (terminalTaskCount / (aggregateTaskStats?.total ?? tasksToUse.length)) * 100)
    : 0;
  const overallProgress = preparation
    ? preparation.percent
    : (aggregateTaskStats?.total ?? tasksToUse.length) > 0
      ? Math.min(
          100,
          Math.round(
            (terminalTaskCount / (aggregateTaskStats?.total ?? tasksToUse.length)) * 100,
          ),
        )
      : 0;

  const effectiveLiveStatus = liveStatus;

  const jobEta = useMemo(
    () =>
      calculateJobEta({
        status: liveStatus,
        startedAt: effectiveStartedAt,
        completedAt: details?.completed_at ?? null,
        progressPercent: executionProgress,
        itemsProcessed: terminalTaskCount,
        itemsTotal: aggregateTaskStats?.total ?? null,
        currentTime,
      }),
    [
      aggregateTaskStats?.total,
      currentTime,
      details?.completed_at,
      effectiveStartedAt,
      liveStatus,
      executionProgress,
      terminalTaskCount,
    ],
  );
  const taskHistoryUnavailable =
    !hasTaskFilters && !isLiveJob && (aggregateTaskStats?.total ?? 0) > 0 && tasksToUse.length === 0;
  const emptyTaskMessage = preparation
    ? preparation.phase === 'queued'
      ? `Waiting to prepare ${preparation.total.toLocaleString()} task records...`
      : preparation.phase === 'finalizing'
        ? `Finalizing ${preparation.completed.toLocaleString()} of ${preparation.total.toLocaleString()} task records for execution...`
        : `Materializing ${preparation.completed.toLocaleString()} of ${preparation.total.toLocaleString()} task records...`
    : isStreaming || isLoadingTaskPage
      ? 'Loading tasks...'
    : hasTaskFilters
      ? 'No matching tasks'
      : isMissingJob
        ? 'This job is no longer available. Its live state was removed and no retained history record exists.'
        : taskHistoryUnavailable
          ? 'Task history is no longer available for this job.'
          : 'No tasks';
  const taskTypeOptions = useMemo(() => {
    const taskTypes = new Set<string>();
    const typeCounts = aggregateTaskStats?.task_type_counts ?? {};
    for (const taskType of Object.keys(typeCounts)) {
      taskTypes.add(taskType);
    }
    for (const task of taskItems) {
      if (task.task_type) {
        taskTypes.add(task.task_type);
      }
    }
    for (const task of streamedTasks) {
      if (task.task_type) {
        taskTypes.add(task.task_type);
      }
    }
    return Array.from(taskTypes).sort();
  }, [aggregateTaskStats?.task_type_counts, streamedTasks, taskItems]);

  const taskFailureItems = useMemo(() => {
    const items: TaskFailureEvidence[] = [];

    for (const [taskIndex, task] of tasksToUse.entries()) {
      const normalizedStatus = String(task.status || '').toLowerCase();
      const result =
        task.result && typeof task.result === 'object'
          ? (task.result as Record<string, unknown>)
          : null;

      const messages: string[] = [];
      const seen = new Set<string>();
      const pushMessage = (value: unknown) => {
        if (value === null || value === undefined) return;
        const text = String(value).trim();
        if (!text || seen.has(text)) return;
        seen.add(text);
        messages.push(text);
      };

      if (task.error) pushMessage(task.error);
      if (typeof result?.message === 'string' && normalizedStatus === 'failed') {
        pushMessage(result.message);
      }
      if (Array.isArray(result?.errors)) {
        for (const entry of result.errors) {
          pushMessage(entry);
        }
      }
      if (!messages.length && normalizedStatus === 'failed') {
        pushMessage('Task failed without error details.');
      }
      if (!messages.length) continue;

      items.push({
        evidenceId: `task:${task.task_id ?? taskIndex}`,
        task,
        taskType: String(task.task_type || 'task').replace('_', ' '),
        contentType: String(task.content_type || 'All'),
        username: String(task.username || 'Unknown'),
        site: String(task.site || 'Unknown'),
        status: task.status || 'failed',
        messages,
      });
    }

    return items;
  }, [tasksToUse]);

  const totalTaskErrors = useMemo(
    () => taskFailureItems.reduce((sum, item) => sum + Math.max(1, item.messages.length), 0),
    [taskFailureItems]
  );

  const allErrors = useMemo(() => {
    const breakdown: Record<string, number> = {};
    const failedItems: Array<Record<string, unknown>> = [];

    for (const [taskIndex, task] of tasksToUse.entries()) {
      const result = task.result;
      if (!result || typeof result !== 'object') continue;
      const output = (result as { output?: unknown }).output;
      if (!output || typeof output !== 'object') continue;

      const failureBreakdown = (output as { failure_breakdown?: unknown }).failure_breakdown;
      if (failureBreakdown && typeof failureBreakdown === 'object') {
        for (const [key, value] of Object.entries(failureBreakdown as Record<string, unknown>)) {
          // Existing files are successful deduplication skips, not recovery errors.
          if (key === 'already_exists') continue;
          const count = typeof value === 'number' ? value : Number(value);
          if (Number.isFinite(count) && count > 0) {
            breakdown[key] = (breakdown[key] ?? 0) + count;
          }
        }
      }

      const downloadResults = (output as { download_results?: unknown }).download_results;
      if (!Array.isArray(downloadResults)) continue;

      for (const [downloadIndex, entry] of downloadResults.entries()) {
        if (!entry || typeof entry !== 'object') continue;
        const recoveryErrors = Array.isArray(entry.errors)
          ? entry.errors.filter((errorEntry: unknown) =>
              !errorEntry || typeof errorEntry !== 'object' ||
              !('reason' in errorEntry) || errorEntry.reason !== 'already_exists'
            )
          : [];
        const taskPayload =
          task.payload && typeof task.payload === 'object'
            ? (task.payload as Record<string, unknown>)
            : null;
        const rawTaskAuthId = taskPayload?.auth_id;
        const taskAuthId =
          typeof rawTaskAuthId === 'number'
            ? rawTaskAuthId
            : typeof rawTaskAuthId === 'string' && rawTaskAuthId.trim()
              ? Number(rawTaskAuthId)
              : null;
        if (
          (entry.status === 'failed' || entry.status === 'skipped') &&
          recoveryErrors.length > 0
        ) {
          failedItems.push({
            ...entry,
            errors: recoveryErrors,
            _evidenceId: `media:${task.task_id ?? taskIndex}:${String(entry.content_id ?? 'unknown')}:${String(entry.media_id ?? downloadIndex)}:${downloadIndex}`,
            _taskId: task.task_id,
            _taskUsername: task.username || 'Unknown',
            _taskContentType: task.content_type || 'All',
            _taskSite: task.site || details?.site || 'onlyfans',
            _taskAuthId: Number.isFinite(taskAuthId) ? taskAuthId : null,
          });
        }
      }
    }

    return { breakdown, failedItems };
  }, [details?.site, tasksToUse]);

  const totalDownloadErrorEvents = Math.max(
    totalDownloadErrors,
    Object.values(allErrors.breakdown).reduce(
      (sum, value) => sum + Number(value || 0),
      0
    )
  );
  const totalErrorCount = totalDownloadErrorEvents + totalTaskErrors;

  const getFilteredFailedItems = (category: string) =>
    filterFailedItemsByCategory(allErrors.failedItems, category);

  const hasDownloadErrors =
    allErrors.failedItems.length > 0 || Object.keys(allErrors.breakdown).length > 0;
  const hasTaskErrors = taskFailureItems.length > 0;
  const getRecoveryGroupCount = (category: string): number => {
    if (category === 'all') return totalErrorCount;
    if (category === 'task_issues') return totalTaskErrors;
    return Math.max(
      countCategoryErrors(allErrors.breakdown, category),
      getFilteredFailedItems(category).length,
    );
  };
  const availableRecoveryGroups = [
    'all',
    ...(hasTaskErrors ? ['task_issues'] : []),
    ...Object.keys(ERROR_CATEGORIES).filter(
      (category) => getRecoveryGroupCount(category) > 0
    ),
    ...(getRecoveryGroupCount('other') > 0 ? ['other'] : []),
  ];
  const selectedRecoveryCause = RECOVERY_CAUSES[errorTab] ?? RECOVERY_CAUSES.other;
  const selectedTaskFailureItems =
    errorTab === 'all' || errorTab === 'task_issues' ? taskFailureItems : [];
  const selectedDownloadFailureItems =
    errorTab === 'task_issues' ? [] : getFilteredFailedItems(errorTab);
  const selectedEvidenceCount =
    selectedTaskFailureItems.length + selectedDownloadFailureItems.length;
  const totalEvidenceCount = taskFailureItems.length + allErrors.failedItems.length;
  const selectedCauseCount = getRecoveryGroupCount(errorTab);
  const retryFailedTaskCount =
    aggregateTaskStats?.failed ??
    tasksToUse.filter((task) => String(task.status).toLowerCase() === 'failed').length;
  const retryScopeLabel =
    retryFailedTaskCount > 0
      ? `${retryFailedTaskCount} failed ${retryFailedTaskCount === 1 ? 'task' : 'tasks'}`
      : 'All available tasks';
  const retryScopeDetail =
    retryFailedTaskCount > 0
      ? `The backend will clone the ${retryFailedTaskCount} failed ${retryFailedTaskCount === 1 ? 'task' : 'tasks'} into a new job.`
      : 'No failed task state is recorded, so the backend will clone every available task into a new job.';
  const knownTaskCount = aggregateTaskStats?.total ?? tasksToUse.length;
  const loadedTaskLabel = knownTaskCount > 0
    ? `${tasksToUse.length} / ${knownTaskCount}`
    : String(tasksToUse.length);

  const copyRecoverySummary = async () => {
    const reasonCodes = Array.from(
      new Set(selectedDownloadFailureItems.flatMap((item) => failedItemReasons(item)))
    );
    const taskTypes = Array.from(
      new Set(selectedTaskFailureItems.map((item) => item.taskType))
    );
    const summary = [
      `Job: ${job.job_id}`,
      `Status: ${liveStatus || 'unknown'}`,
      `Recovery view: ${selectedRecoveryCause.label} (${selectedRecoveryCause.code})`,
      `Recorded errors: ${selectedCauseCount}`,
      `Loaded evidence records: ${selectedEvidenceCount}`,
      `Retry scope: ${retryScopeLabel}`,
      reasonCodes.length ? `Reason codes: ${reasonCodes.join(', ')}` : null,
      taskTypes.length ? `Task types: ${taskTypes.join(', ')}` : null,
    ]
      .filter((line): line is string => Boolean(line))
      .join('\n');

    try {
      await copyText(summary);
      setDiagnosticCopyState('copied');
    } catch {
      setDiagnosticCopyState('error');
    }
  };

  const scheduleDescription = useMemo(() => {
    if (!initialSchedule.enabled) return null;
    if (initialSchedule.type === 'once' && initialSchedule.at) {
      return `Once at ${new Date(initialSchedule.at).toLocaleString()}`;
    }
    if (initialSchedule.type === 'interval') {
      return `Every ${initialSchedule.intervalValue} ${initialSchedule.intervalUnit}`;
    }
    if (initialSchedule.type === 'cron' && initialSchedule.cron) {
      return `Cron: ${initialSchedule.cron}`;
    }
    return null;
  }, [initialSchedule]);

  const renderErrorBadges = (item: Record<string, unknown>) => {
    const errors = Array.isArray(item.errors) ? item.errors : [];
    if (errors.length > 0) {
      return errors.map((errorEntry: { reason?: string }, index: number) => (
        <span key={index} className="jdm-error-badge">
          {String(errorEntry.reason || 'unknown')}
        </span>
      ));
    }
    if (item.reason) {
      return <span className="jdm-error-badge">{String(item.reason)}</span>;
    }
    return null;
  };

  const renderErrorMessages = (item: Record<string, unknown>) => {
    const errors = Array.isArray(item.errors) ? item.errors : [];
    if (errors.length > 0) {
      return (
        <span className="jdm-error-messages">
          {errors.map((errorEntry: { reason?: string; message?: string }, index: number) => (
            <span key={index} className="jdm-error-msg">
              <strong>{String(errorEntry.reason || 'error')}:</strong>{' '}
              {String(errorEntry.message || 'Unknown error')}
            </span>
          ))}
        </span>
      );
    }
    if (item.error_message) {
      return <span className="jdm-error-msg">{String(item.error_message)}</span>;
    }
    return null;
  };

  const renderEvidenceInspector = ({
    title,
    description,
    fields,
    messages,
    rawRecord,
    sourceLink,
  }: {
    title: string;
    description: string;
    fields: Array<{ label: string; value: unknown }>;
    messages: string[];
    rawRecord: Record<string, unknown>;
    sourceLink?: { href: string; rawUrl: string } | null;
  }) => {
    const visibleFields = fields.filter(
      ({ value }) => value !== null && value !== undefined && value !== ''
    );

    return (
      <section
        id="jdm-recovery-evidence-inspector"
        className="jdm-evidence-inspector"
        role="region"
        aria-label="Selected affected evidence"
      >
        <header className="jdm-evidence-inspector-header">
          <div>
            <span>Selected evidence</span>
            <h5>{title}</h5>
            <p>{description}</p>
          </div>
          <button
            type="button"
            className="jdm-evidence-inspector-close"
            aria-label="Close affected evidence"
            onClick={() => setSelectedEvidenceId(null)}
          >
            Close
          </button>
        </header>

        <dl className="jdm-evidence-fields">
          {visibleFields.map(({ label, value }) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>

        {sourceLink ? (
          <a
            className="jdm-evidence-source-action"
            href={sourceLink.href}
            target="_blank"
            rel="noopener noreferrer"
            title={sourceLink.rawUrl}
          >
            Open affected source media
            <span aria-hidden="true">↗</span>
          </a>
        ) : null}

        {messages.length > 0 ? (
          <div className="jdm-evidence-failures">
            <span>Recorded failure</span>
            {messages.map((message, index) => (
              <p key={`${message}-${index}`}>{message}</p>
            ))}
          </div>
        ) : null}

        <details className="jdm-evidence-raw">
          <summary>Raw evidence record</summary>
          <pre>{JSON.stringify(rawRecord, null, 2)}</pre>
        </details>
      </section>
    );
  };

  const resultError =
    details?.result_error ??
    details?.materialization_error ??
    job.materialization_error ??
    null;
  const resultMessage = details?.result_message ?? null;
  const isSuccessResultMessage = (message: string | null): boolean =>
    Boolean(message && /^(Scraped|Downloaded)\s+\d+/i.test(message));
  const actualResultError =
    resultError && !isSuccessResultMessage(resultError) ? resultError : null;
  const showResultError = Boolean(actualResultError) || details?.result_success === false;
  const showResultSuccess =
    Boolean(resultMessage) &&
    (details?.result_success === true ||
      (liveStatus === 'completed' && details?.result_success !== false));

  const runbookNotices = (
    <>
      {showResultError && actualResultError ? (
        <div className="jdm-alert jdm-alert-error">
          <pre className="jdm-alert-code">{actualResultError}</pre>
        </div>
      ) : null}
      {showResultSuccess && resultMessage ? (
        <div
          className={`jdm-alert ${totalDownloadErrors > 0 ? 'jdm-alert-warn' : 'jdm-alert-ok'}`}
        >
          <pre className="jdm-alert-code">{resultMessage}</pre>
        </div>
      ) : null}

      {shouldShowRetry ? (
        <div className="jdm-retry-section">
          <h4>Retry with active auth</h4>
          <p className="jdm-retry-hint">
            Job failed because auth {inactiveAuthId} is inactive.
          </p>
          {isAuthLoading ? <span>Loading auths...</span> : null}
          {authError ? <span className="error-message">Failed to load auths</span> : null}
          {!isAuthLoading && !authError ? (
            <div className="jdm-retry-controls">
              <select
                className="jdm-retry-select"
                value={effectiveSelectedAuthId}
                onChange={(event) =>
                  setSelectedAuthId(event.target.value === '' ? '' : Number(event.target.value))
                }
              >
                {retryAuths.length ? (
                  retryAuths.map((auth) => (
                    <option key={`${auth.site}-${auth.user_id}`} value={auth.user_id}>
                      {auth.username || `Auth ${auth.user_id}`} (ID {auth.user_id})
                    </option>
                  ))
                ) : (
                  <option value="">No active auths</option>
                )}
              </select>
              <button
                className="btn btn-primary"
                disabled={!hasSelectedRetryAuth || !retryAuths.length || retryMutation.isPending}
                onClick={() => {
                  if (hasSelectedRetryAuth) retryMutation.mutate(effectiveSelectedAuthId);
                }}
              >
                {retryMutation.isPending ? 'Retrying...' : 'Retry'}
              </button>
            </div>
          ) : null}
          {retryMutation.isError ? (
            <div className="error-message">{getRetryErrorMessage(retryMutation.error)}</div>
          ) : null}
        </div>
      ) : null}
    </>
  );

  const runbookActions = (
    <>
      {isLiveJob && liveStatus !== 'paused' ? (
        <button
          className="btn btn-secondary"
          title={prioritizeMutation.isSuccess ? 'Prioritized!' : 'Process this job next'}
          disabled={prioritizeMutation.isPending || prioritizeMutation.isSuccess}
          onClick={() => prioritizeMutation.mutate()}
        >
          {prioritizeMutation.isPending
            ? 'Prioritizing...'
            : prioritizeMutation.isSuccess
              ? 'Prioritized'
              : 'Prioritize'}
        </button>
      ) : null}
      {!shouldShowRetry ? (
        <button
          className="btn btn-primary"
          onClick={() => retryAnyMutation.mutate()}
          disabled={retryAnyMutation.isPending}
        >
          {retryAnyMutation.isPending ? 'Retrying...' : 'Retry Job'}
        </button>
      ) : null}
      {isLiveJob ? (
        <button
          className="btn btn-danger"
          onClick={() => setShowCancelConfirm(true)}
          disabled={cancelJobMutation.isPending}
        >
          {cancelJobMutation.isPending ? 'Cancelling...' : 'Cancel Job'}
        </button>
      ) : null}
      {retryAnyMutation.isError ? (
        <span className="jdm-footer-hint error-message">
          {getRetryErrorMessage(retryAnyMutation.error)}
        </span>
      ) : null}
      {cancelJobMutation.isError ? (
        <span className="jdm-footer-hint error-message">
          {getJobActionErrorMessage(cancelJobMutation.error, 'Failed to cancel job.')}
        </span>
      ) : null}
    </>
  );

  const pauseResumeAction = isLiveJob && (details?.execution_engine || job.execution_engine) === 'ledger' ? (
    <>
      <button
        className="btn btn-secondary"
        title={liveStatus === 'paused' ? 'Allow queued tasks to start' : 'Stop starting tasks; running tasks may finish'}
        disabled={pauseResumeMutation.isPending}
        onClick={() => pauseResumeMutation.mutate()}
      >
        {pauseResumeMutation.isPending ? 'Updating...' : liveStatus === 'paused' ? 'Resume Job' : 'Pause Job'}
      </button>
      {pauseResumeMutation.isError && (
        <span role="alert" className="error-message">
          {getJobActionErrorMessage(pauseResumeMutation.error, 'Failed to update job.')}
        </span>
      )}
    </>
  ) : null;

  const content = (
    <div
      role={isPanel ? 'region' : 'dialog'}
      aria-modal={isPanel ? undefined : true}
      aria-label={`Job details: ${job.job_name || job.job_id}`}
      ref={modalRef}
      style={preservedModalSize && !isPanel ? {
        width: `${preservedModalSize.width}px`,
        height: `${preservedModalSize.height}px`,
      } : undefined}
      className={
        isPanel
          ? 'jdm-modal jdm-runbook-modal jdm-surface jdm-surface-panel'
          : 'modal-content jdm-modal jdm-runbook-modal'
      }
      onClick={isPanel ? undefined : (event) => event.stopPropagation()}
    >
          <div className="jdm-header jdm-runbook-header">
            <div
              className="jdm-runbook-overall-progress"
              style={{ '--jdm-runbook-progress': `${overallProgress}%` } as CSSProperties}
              role="progressbar"
              aria-label={
                preparation
                  ? preparation.phase === 'finalizing'
                    ? 'Job task finalization'
                    : 'Job task materialization'
                  : 'Job task completion'
              }
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={overallProgress}
            >
              <span>
                <strong>{overallProgress}%</strong>
                <small>
                  {preparation
                    ? preparation.phase === 'finalizing'
                      ? 'prepared'
                      : 'materialized'
                    : 'complete'}
                </small>
              </span>
            </div>
            <div className="jdm-header-top">
              <div className="jdm-header-left">
                <span className="jdm-runbook-kicker">
                  {runbookSiteLabel} · {runbookOperation}
                </span>
                <h2 className="jdm-title">{runbookTitle}</h2>
                <div className="jdm-subtitle">
                  <span className="jdm-id">{job.job_id.slice(0, 8)}</span>
                  <span>{diagnosticsTelemetry.completedTasksCount.toLocaleString()} / {diagnosticsTelemetry.totalTasksCount.toLocaleString()} completed</span>
                  {details?.run_count ? <span>Run #{details.run_count}</span> : null}
                  {duration !== null && <span>{formatDuration(duration)}</span>}
                  {effectiveStartedAt && details?.completed_at && (
                    <span>
                      {new Date(effectiveStartedAt).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                      {' → '}
                      {new Date(details.completed_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  )}
                  {!details?.completed_at && (
                    <>
                      {effectiveStartedAt && liveStatus !== 'pending' && liveStatus !== 'queued' && (
                        <span>
                          Started{' '}
                          {new Date(effectiveStartedAt).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      )}
                      {jobEta.elapsedSeconds !== null && (
                        <span className="jdm-elapsed-time">
                          Elapsed {jobEta.formattedElapsed}
                        </span>
                      )}
                      {jobEta.formattedRemaining && (
                        <span className="jdm-eta-time">
                          ETA ~{jobEta.formattedRemaining}
                          {jobEta.formattedCompletionTime
                            ? ` (${jobEta.formattedCompletionTime})`
                            : ''}
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>
              <div className="jdm-header-right">
                <div className="jdm-status-badges">
                  <span className={`jdm-status job-status-${effectiveLiveStatus || 'unknown'}`}>
                    {preparation ? preparation.label.toLowerCase() : effectiveLiveStatus || 'unknown'}
                  </span>
                  {effectiveLiveStatus === 'completed' && (totalDownloadErrors > 0 || (aggregateTaskStats?.failed ?? 0) > 0) && (
                    <span className="jdm-status jdm-status-errors">
                      {totalDownloadErrors || aggregateTaskStats?.failed} {(totalDownloadErrors || aggregateTaskStats?.failed) === 1 ? 'Error' : 'Errors'}
                    </span>
                  )}
                </div>
                {isPanel ? (
                  <button className="jdm-panel-close" onClick={onClose}>
                    Clear
                  </button>
                ) : (
                  <button className="modal-close" aria-label="Close job details" onClick={onClose}>
                    ×
                  </button>
                )}
              </div>
            </div>
            <div className="jdm-tabs" role="tablist" aria-label="Job detail view">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'pipeline'}
                className={`jdm-tab ${activeTab === 'pipeline' ? 'active' : ''}`}
                onClick={() => changeTab('pipeline')}
              >
                Pipeline
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'diagnostics'}
                className={`jdm-tab ${activeTab === 'diagnostics' ? 'active' : ''}`}
                onClick={() => changeTab('diagnostics')}
              >
                Diagnostics
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'errors'}
                className={`jdm-tab ${activeTab === 'errors' ? 'active' : ''}`}
                onClick={() => changeTab('errors')}
              >
                Errors{totalErrorCount > 0 ? ` (${totalErrorCount})` : ''}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'config'}
                className={`jdm-tab ${activeTab === 'config' ? 'active' : ''}`}
                onClick={() => changeTab('config')}
              >
                Config
              </button>
            </div>
          </div>

          <div className={`jdm-body ${activeTab === 'pipeline' ? 'jdm-body-runbook' : ''}`}>
            {isLoading && (
              <div className="jdm-loading" role="status">
                <span className="loading-spinner" aria-hidden="true" />
                <span>Loading job details...</span>
              </div>
            )}
            {error && !hasRetainedJobDetails && (!isMissingJob || activeTab !== 'pipeline') && (
              <div className="error-message">
                {isMissingJob
                  ? 'Job details are no longer available. Showing retained task history only.'
                  : 'Failed to load job details'}
              </div>
            )}

            {error && hasRetainedJobDetails && !isMissingJob && (
              <div className="error-message">
                Live refresh failed. Showing the last loaded job details.
              </div>
            )}

            {activeTab === 'pipeline' && !isLoading && (canRenderJobDetails || isMissingJob) && (
              <>
                {isMissingJob ? (
                  <div className="error-message">
                    Job details are no longer available. Showing retained task history only.
                  </div>
                ) : null}
                <JobRunbookPipeline
                  jobId={job.job_id}
                  tasks={tasksToUse}
                  taskStats={aggregateTaskStats}
                  networkProxies={networkProxies}
                  workerId={details?.worker_id}
                  liveEvent={liveEvent}
                  isStreaming={isStreaming}
                  isLiveJob={isLiveJob}
                  jobEta={jobEta}
                  canStreamTasks={canStreamTasks}
                  streamMaxTotalTasks={STREAM_MAX_TOTAL_TASKS}
                  emptyMessage={emptyTaskMessage}
                  hasMoreTasks={hasMoreTasks}
                  isLoadingMoreTasks={isLoadingMoreTasks}
                  onLoadMoreTasks={() => {
                    void loadMoreTasks();
                  }}
                  pipelineRef={pipelineRef}
                  taskStateFilter={taskStateFilter}
                  onTaskStateFilterChange={setTaskStateFilter}
                  taskTypeFilter={taskTypeFilter}
                  onTaskTypeFilterChange={setTaskTypeFilter}
                  taskTypeOptions={taskTypeOptions}
                  hopUsedMin={hopUsedMin}
                  onHopUsedMinChange={setHopUsedMin}
                  hopUsedMax={hopUsedMax}
                  onHopUsedMaxChange={setHopUsedMax}
                  geoBlockedFilter={geoBlockedFilter}
                  onGeoBlockedFilterChange={setGeoBlockedFilter}
                  errorOnlyFilter={errorOnlyFilter}
                  onErrorOnlyFilterChange={setErrorOnlyFilter}
                  taskStateFilters={TASK_STATE_FILTERS}
                  notices={runbookNotices}
                  actions={<>{pauseResumeAction}{runbookActions}</>}
                />
              </>
            )}

            {activeTab === 'diagnostics' && !isLoading && canRenderJobDetails && (
              <JobDiagnosticsReport
                telemetry={diagnosticsTelemetry}
                isLiveJob={isLiveJob}
                jobEta={jobEta}
                workerPoolSize={workerPoolSize}
                jobName={job.job_name || details?.job_name}
                jobId={job.job_id}
                site={job.site || details?.site}
                historicalJobs={historicalJobs}
                currentJob={details || job}
                chartNow={currentTime}
                baselineJobDetail={baselineJobDetail}
                onBaselineJobChange={setSelectedBaselineJobId}
              />
            )}

            {activeTab === 'errors' && !isLoading && canRenderJobDetails && (
              <div className="jdm-errors jdm-recovery-console" aria-label="Recovery console">
                {!hasTaskErrors && !hasDownloadErrors ? (
                  <div className="jdm-empty">
                    {isLoadingTaskPage ? 'Loading error evidence...' : 'No errors'}
                  </div>
                ) : (
                  <>
                    <header className="jdm-recovery-heading">
                      <div>
                        <span>Triage by recorded cause</span>
                        <h3>Recovery console</h3>
                        <p>
                          Group real task and download evidence, inspect the recovery boundary,
                          then create a backend-scoped retry job.
                        </p>
                      </div>
                      <div className="jdm-recovery-vitals" aria-label="Loaded error summary">
                        <span><small>Recorded errors</small><strong>{totalErrorCount}</strong></span>
                        <span><small>Evidence records</small><strong>{totalEvidenceCount}</strong></span>
                        <span><small>Loaded tasks</small><strong>{loadedTaskLabel}</strong></span>
                      </div>
                      <button
                        type="button"
                        className="jdm-recovery-copy"
                        title="Copies job IDs, counts, task types, and reason codes. URLs and error messages are omitted."
                        onClick={() => void copyRecoverySummary()}
                      >
                        {diagnosticCopyState === 'copied'
                          ? 'Summary copied'
                          : diagnosticCopyState === 'error'
                            ? 'Copy unavailable'
                            : 'Copy summary'}
                      </button>
                    </header>

                    {hasTaskFilters && (
                      <div className="jdm-recovery-filter-notice">
                        <span>Error evidence is limited by the Pipeline task filters.</span>
                        <button
                          type="button"
                          onClick={() => {
                            setTaskStateFilter('');
                            setTaskTypeFilter('');
                            setErrorOnlyFilter(false);
                          }}
                        >
                          Clear filters
                        </button>
                      </div>
                    )}

                    <div className="jdm-recovery-layout">
                      <aside className="jdm-recovery-causes" aria-label="Recovery cause groups">
                        <div className="jdm-recovery-section-label">
                          <span>Cause groups</span>
                          <b>{Math.max(0, availableRecoveryGroups.length - 1)}</b>
                        </div>
                        <div role="tablist" aria-label="Recovery cause selection">
                          {availableRecoveryGroups.map((category) => {
                            const cause = RECOVERY_CAUSES[category] ?? RECOVERY_CAUSES.other;
                            const count = getRecoveryGroupCount(category);
                            return (
                              <button
                                key={category}
                                type="button"
                                role="tab"
                                aria-selected={errorTab === category}
                                aria-controls="jdm-recovery-cause-panel"
                                className={`jdm-recovery-cause ${errorTab === category ? 'is-selected' : ''}`}
                                onClick={() => {
                                  setErrorTab(category);
                                  setDiagnosticCopyState('idle');
                                }}
                              >
                                <i className={`is-${cause.tone}`} aria-hidden="true" />
                                <span>
                                  <strong>{cause.label}</strong>
                                  <small>{cause.code}</small>
                                </span>
                                <b>{count}</b>
                              </button>
                            );
                          })}
                        </div>
                      </aside>

                      <main
                        id="jdm-recovery-cause-panel"
                        className="jdm-recovery-detail"
                        role="tabpanel"
                        aria-label={`${selectedRecoveryCause.label} recovery evidence`}
                        tabIndex={0}
                      >
                        <header className="jdm-recovery-cause-header">
                          <div>
                            <span className={`jdm-recovery-tone is-${selectedRecoveryCause.tone}`}>
                              {selectedRecoveryCause.posture}
                            </span>
                            <code>{selectedRecoveryCause.code}</code>
                          </div>
                          <span>
                            <b>{selectedCauseCount}</b> recorded · <b>{selectedEvidenceCount}</b>{' '}
                            loaded evidence
                          </span>
                        </header>

                        <section className="jdm-recovery-diagnosis">
                          <span>What the records show</span>
                          <h4>{selectedRecoveryCause.label}</h4>
                          <p>{selectedRecoveryCause.signal}</p>
                        </section>

                        <div className="jdm-recovery-impact-grid">
                          <section>
                            <span>Operational impact</span>
                            <p>{selectedRecoveryCause.impact}</p>
                          </section>
                          <section>
                            <span>Recovery boundary</span>
                            <p>{selectedRecoveryCause.boundary}</p>
                          </section>
                        </div>

                        <section className="jdm-recovery-evidence">
                          <div className="jdm-recovery-evidence-heading">
                            <span>Affected evidence</span>
                            <small>{selectedEvidenceCount} loaded records</small>
                          </div>

                          {!selectedTaskFailureItems.length &&
                          !selectedDownloadFailureItems.length ? (
                            <p className="jdm-recovery-empty-evidence">
                              This cause has a recorded count but no item-level evidence in the
                              loaded task history.
                            </p>
                          ) : null}

                          {selectedTaskFailureItems.map((item) => {
                            const isSelected = selectedEvidenceId === item.evidenceId;
                            const taskResult =
                              item.task.result && typeof item.task.result === 'object'
                                ? item.task.result
                                : null;

                            return (
                              <article
                                key={item.evidenceId}
                                className={`jdm-error-item${isSelected ? ' is-selected' : ''}`}
                              >
                                <button
                                  type="button"
                                  className="jdm-evidence-select"
                                  aria-expanded={isSelected}
                                  aria-controls={
                                    isSelected ? 'jdm-recovery-evidence-inspector' : undefined
                                  }
                                  aria-label={`Inspect ${item.taskType} ${item.contentType} task evidence`}
                                  onClick={() =>
                                    setSelectedEvidenceId((current) =>
                                      current === item.evidenceId ? null : item.evidenceId
                                    )
                                  }
                                >
                                  <span className="jdm-error-item-header">
                                    <span className="jdm-error-item-id">
                                      {item.taskType} · {item.contentType} · {item.username} · {item.site}
                                    </span>
                                    <span className="jdm-error-item-badges">
                                      <span className="jdm-error-badge">{item.status}</span>
                                    </span>
                                  </span>
                                  <span className="jdm-error-messages">
                                    {item.messages.map((message, messageIndex) => (
                                      <span key={messageIndex} className="jdm-error-msg">
                                        {message}
                                      </span>
                                    ))}
                                  </span>
                                  <span className="jdm-evidence-open-hint">
                                    {isSelected ? 'Hide evidence' : 'Inspect evidence'}
                                    <span aria-hidden="true">{isSelected ? '−' : '+'}</span>
                                  </span>
                                </button>

                                {isSelected
                                  ? (() => {
                                      const proxySummary = getTaskProxySummary(item.task, networkProxies);
                                      return renderEvidenceInspector({
                                        title: `${item.taskType} task`,
                                        description:
                                          'This is the task record that reported the failure and supplied the messages shown above.',
                                        fields: [
                                          { label: 'Task ID', value: item.task.task_id },
                                          { label: 'Task type', value: item.task.task_type },
                                          { label: 'Content type', value: item.contentType },
                                          { label: 'Account', value: item.username },
                                          { label: 'Site', value: item.site },
                                          { label: 'State', value: item.status },
                                          {
                                            label: 'Progress',
                                            value: `${Math.round((item.task.progress || 0) * 100)}%`,
                                          },
                                          {
                                            label: 'Items',
                                            value:
                                              item.task.items_total == null
                                                ? item.task.items_processed
                                                : `${item.task.items_processed} / ${item.task.items_total}`,
                                          },
                                          {
                                            label: 'Proxy route',
                                            value: proxySummary.hasHops ? proxySummary.summaryText : null,
                                          },
                                          {
                                            label: 'Configured route order',
                                            value:
                                              proxySummary.hasHops && proxySummary.hopCount > 1
                                                ? proxySummary.hops
                                                    .map(
                                                      (h) =>
                                                        `Hop ${h.hop_number} (${h.role_label}): ${h.is_direct ? 'Direct' : h.masked_url} [${h.status}]`,
                                                    )
                                                    .join(' → ')
                                                : null,
                                          },
                                          { label: 'Started', value: item.task.started_at },
                                          { label: 'Completed', value: item.task.completed_at },
                                        ],
                                        messages: item.messages,
                                        rawRecord: {
                                          task_id: item.task.task_id,
                                          task_type: item.task.task_type,
                                          status: item.task.status,
                                          site: item.task.site,
                                          username: item.task.username,
                                          content_type: item.task.content_type,
                                          proxy_url: item.task.proxy_url ?? null,
                                          proxy_routes: item.task.proxy_routes ?? null,
                                          proxy_hop_used: item.task.proxy_hop_used ?? null,
                                          error: item.task.error,
                                          result_message: taskResult?.message ?? null,
                                          result_errors: taskResult?.errors ?? null,
                                        },
                                      });
                                    })()
                                  : null}
                              </article>
                            );
                          })}

                          {selectedDownloadFailureItems.slice(0, 50).map((entry, index) => {
                            const rawUrl = entry.url != null ? String(entry.url) : null;
                            const entrySite =
                              typeof entry._taskSite === 'string' && entry._taskSite
                                ? String(entry._taskSite).toLowerCase()
                                : (site ?? 'onlyfans');
                            const entryAuthId =
                              typeof entry._taskAuthId === 'number'
                                ? entry._taskAuthId
                                : null;
                            const proxiedUrl = getMediaProxyUrl(rawUrl, entrySite, entryAuthId);
                            const linkUrl = proxiedUrl ?? rawUrl;
                            const evidenceId = String(
                              entry._evidenceId ??
                                `media:${String(entry.content_id ?? 'unknown')}:${String(entry.media_id ?? index)}:${index}`
                            );
                            const isSelected = selectedEvidenceId === evidenceId;
                            const evidenceMessages = Array.isArray(entry.errors)
                              ? entry.errors.map((errorEntry) => {
                                  if (!errorEntry || typeof errorEntry !== 'object') {
                                    return String(errorEntry);
                                  }
                                  const reason =
                                    'reason' in errorEntry
                                      ? String(errorEntry.reason || 'error')
                                      : 'error';
                                  const message =
                                    'message' in errorEntry
                                      ? String(errorEntry.message || 'Unknown error')
                                      : 'Unknown error';
                                  return `${reason}: ${message}`;
                                })
                              : entry.error_message != null
                                ? [String(entry.error_message)]
                                : [];
                            const rawEvidenceRecord = Object.fromEntries(
                              Object.entries(entry).filter(([key]) => !key.startsWith('_'))
                            );

                            return (
                              <article
                                key={evidenceId}
                                className={`jdm-error-item${isSelected ? ' is-selected' : ''}`}
                              >
                                <button
                                  type="button"
                                  className="jdm-evidence-select"
                                  aria-expanded={isSelected}
                                  aria-controls={
                                    isSelected ? 'jdm-recovery-evidence-inspector' : undefined
                                  }
                                  aria-label={`Inspect ${String(entry._taskContentType ?? 'content')} ${String(entry.content_id ?? 'unknown')} media ${String(entry.media_id ?? 'unknown')} evidence`}
                                  onClick={() =>
                                    setSelectedEvidenceId((current) =>
                                      current === evidenceId ? null : evidenceId
                                    )
                                  }
                                >
                                  <span className="jdm-error-item-header">
                                    <span className="jdm-error-item-id">
                                      {String(entry._taskContentType ?? 'Content')}{' '}
                                      {String(entry.content_id ?? '?')} · Media{' '}
                                      {String(entry.media_id ?? '?')}
                                    </span>
                                    <span className="jdm-error-item-badges">
                                      {renderErrorBadges(entry)}
                                    </span>
                                  </span>
                                  {entry.path != null || entry.filepath != null ? (
                                    <span className="jdm-error-item-path">
                                      {String(entry.path ?? entry.filepath)}
                                    </span>
                                  ) : null}
                                  {renderErrorMessages(entry)}
                                  <span className="jdm-evidence-open-hint">
                                    {isSelected ? 'Hide evidence' : 'Inspect evidence'}
                                    <span aria-hidden="true">{isSelected ? '−' : '+'}</span>
                                  </span>
                                </button>
                                {entry.url != null && (
                                  <div className="jdm-error-item-url">
                                    <a
                                      href={linkUrl ?? String(entry.url)}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      title={String(entry.url)}
                                    >
                                      {String(entry.url).length > 100
                                        ? `${String(entry.url).slice(0, 100)}...`
                                        : String(entry.url)}
                                    </a>
                                  </div>
                                )}
                                {isSelected
                                  ? renderEvidenceInspector({
                                      title: `${String(entry._taskContentType ?? 'Content')} ${String(entry.content_id ?? '?')} · Media ${String(entry.media_id ?? '?')}`,
                                      description:
                                        'This is the download-result row attached to the failed task. The values below identify the exact media and destination affected.',
                                      fields: [
                                        { label: 'Content ID', value: entry.content_id },
                                        { label: 'Media ID', value: entry.media_id },
                                        { label: 'Result state', value: entry.status },
                                        { label: 'Content type', value: entry._taskContentType },
                                        { label: 'Account', value: entry._taskUsername },
                                        { label: 'Site', value: entrySite },
                                        { label: 'Task ID', value: entry._taskId },
                                        { label: 'Auth ID', value: entryAuthId },
                                        {
                                          label: 'Destination',
                                          value: entry.path ?? entry.filepath,
                                        },
                                        { label: 'Bytes written', value: entry.bytes_written },
                                        {
                                          label: 'Expected bytes',
                                          value:
                                            entry.expected_bytes ??
                                            entry.total_bytes ??
                                            entry.expected_size,
                                        },
                                        { label: 'Error type', value: entry.error_type },
                                      ],
                                      messages: evidenceMessages,
                                      rawRecord: rawEvidenceRecord,
                                      sourceLink:
                                        rawUrl && linkUrl
                                          ? { href: linkUrl, rawUrl }
                                          : null,
                                    })
                                  : null}
                              </article>
                            );
                          })}

                          {selectedDownloadFailureItems.length > 50 && (
                            <div className="jdm-error-more">
                              +{selectedDownloadFailureItems.length - 50} more loaded records
                            </div>
                          )}

                          {hasMoreTasks && (
                            <button
                              type="button"
                              className="jdm-recovery-load-more"
                              disabled={isLoadingMoreTasks}
                              onClick={() => void loadMoreTasks()}
                            >
                              {isLoadingMoreTasks ? 'Loading more evidence...' : 'Load more task evidence'}
                            </button>
                          )}
                        </section>
                      </main>

                      <aside className="jdm-recovery-plan" aria-label="Recovery plan">
                        <div className="jdm-recovery-section-label">
                          <span>Recovery plan</span>
                        </div>
                        <div className={`jdm-recovery-posture is-${selectedRecoveryCause.tone}`}>
                          <strong>{selectedRecoveryCause.posture}</strong>
                          <small>recorded-cause posture</small>
                        </div>
                        <ol>
                          <li className="is-complete">
                            <i>✓</i>
                            <span>
                              <b>Inspect retained evidence</b>
                              <small>{selectedEvidenceCount} loaded records in this view.</small>
                            </span>
                          </li>
                          <li>
                            <i>2</i>
                            <span>
                              <b>Resolve prerequisite</b>
                              <small>{selectedRecoveryCause.prerequisite}</small>
                            </span>
                          </li>
                          <li>
                            <i>3</i>
                            <span>
                              <b>Create backend retry</b>
                              <small>{retryScopeDetail}</small>
                            </span>
                          </li>
                          <li>
                            <i>4</i>
                            <span>
                              <b>Verify the new job</b>
                              <small>Confirm the cloned tasks complete without the selected cause.</small>
                            </span>
                          </li>
                        </ol>
                        <dl>
                          <div><dt>Retry scope</dt><dd>{retryScopeLabel}</dd></div>
                          <div><dt>Creates</dt><dd>New pending job</dd></div>
                          <div><dt>Current job</dt><dd>Superseded</dd></div>
                        </dl>

                        {shouldShowRetry && (
                          <div className="jdm-recovery-auth">
                            <label htmlFor={`jdm-retry-auth-${job.job_id}`}>Replacement auth</label>
                            <small>Auth {inactiveAuthId} is inactive. Choose an active auth for the cloned tasks.</small>
                            {isAuthLoading ? <span>Loading active auths...</span> : null}
                            {authError ? <span className="error-message">Failed to load auths</span> : null}
                            {!isAuthLoading && !authError ? (
                              <select
                                id={`jdm-retry-auth-${job.job_id}`}
                                className="jdm-retry-select"
                                value={effectiveSelectedAuthId}
                                onChange={(event) =>
                                  setSelectedAuthId(
                                    event.target.value === '' ? '' : Number(event.target.value)
                                  )
                                }
                              >
                                {retryAuths.length ? (
                                  retryAuths.map((auth) => (
                                    <option key={`${auth.site}-${auth.user_id}`} value={auth.user_id}>
                                      {auth.username || `Auth ${auth.user_id}`} (ID {auth.user_id})
                                    </option>
                                  ))
                                ) : (
                                  <option value="">No active auths</option>
                                )}
                              </select>
                            ) : null}
                          </div>
                        )}

                        <div className="jdm-recovery-commit">
                          <small className="jdm-recovery-action-note">
                            This action supersedes the current job. It does not retry only the selected error group.
                          </small>
                          <button
                            type="button"
                            className="btn btn-primary jdm-recovery-action"
                            disabled={
                              retryAnyMutation.isPending ||
                              retryMutation.isPending ||
                              (shouldShowRetry && (!hasSelectedRetryAuth || !retryAuths.length))
                            }
                            onClick={() => {
                              if (shouldShowRetry) {
                                if (hasSelectedRetryAuth) {
                                  retryMutation.mutate(effectiveSelectedAuthId);
                                }
                                return;
                              }
                              retryAnyMutation.mutate();
                            }}
                          >
                            {retryAnyMutation.isPending || retryMutation.isPending
                              ? 'Creating retry...'
                              : shouldShowRetry
                                ? 'Create retry with auth'
                                : 'Create retry job'}
                          </button>
                          {shouldShowRetry && retryMutation.isError ? (
                            <div className="error-message">
                              {getRetryErrorMessage(retryMutation.error)}
                            </div>
                          ) : null}
                          {!shouldShowRetry && retryAnyMutation.isError ? (
                            <div className="error-message">
                              {getRetryErrorMessage(retryAnyMutation.error)}
                            </div>
                          ) : null}
                        </div>
                      </aside>
                    </div>
                  </>
                )}
              </div>
            )}

            {activeTab === 'config' && !isLoading && canRenderJobDetails && (
              <div className="jdm-config">
                <div className="jdm-config-grid">
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Job ID</span>
                    <span className="jdm-config-value font-mono">{job.job_id}</span>
                  </div>
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Owner</span>
                    <span className="jdm-config-value">{job.created_by || 'Unknown'}</span>
                  </div>
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Created</span>
                    <span className="jdm-config-value">
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Runs</span>
                    <span className="jdm-config-value">{details?.run_count ?? 0}</span>
                  </div>
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Last Ran</span>
                    <span className="jdm-config-value">
                      {formatDateTime(details?.last_ran_at) || '—'}
                    </span>
                  </div>
                  <div className="jdm-config-kv">
                    <span className="jdm-config-label">Schedule</span>
                    <span className="jdm-config-value">{scheduleDescription || 'None (manual)'}</span>
                  </div>
                  {details?.started_at && (
                    <div className="jdm-config-kv">
                      <span className="jdm-config-label">Started</span>
                      <span className="jdm-config-value">
                        {new Date(details.started_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {details?.completed_at && (
                    <div className="jdm-config-kv">
                      <span className="jdm-config-label">Completed</span>
                      <span className="jdm-config-value">
                        {new Date(details.completed_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {duration !== null && (
                    <div className="jdm-config-kv">
                      <span className="jdm-config-label">Duration</span>
                      <span className="jdm-config-value">{formatDuration(duration)}</span>
                    </div>
                  )}
                  {!details?.completed_at && jobEta.elapsedSeconds !== null && (
                    <div className="jdm-config-kv">
                      <span className="jdm-config-label">Elapsed</span>
                      <span className="jdm-config-value">{jobEta.formattedElapsed}</span>
                    </div>
                  )}
                  {!details?.completed_at && jobEta.formattedRemaining && (
                    <div className="jdm-config-kv">
                      <span className="jdm-config-label">Estimated Completion (ETA)</span>
                      <span className="jdm-config-value">
                        ~{jobEta.formattedRemaining}
                        {jobEta.formattedCompletionTime
                          ? ` (${jobEta.formattedCompletionTime})`
                          : ''}
                      </span>
                    </div>
                  )}
                </div>
                <div className="jdm-config-actions">
                  <button
                    className="btn btn-secondary"
                    onClick={() => setIsEditOpen(true)}
                    disabled={isLoading || !!error}
                  >
                    Edit Job
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      const suggestedName = job.job_name || `Job ${job.job_id}`;
                      const templateName = window.prompt('Template name', suggestedName);
                      if (!templateName) return;
                      const trimmed = templateName.trim();
                      if (!trimmed) {
                        setTemplateMessage('Template name is required.');
                        return;
                      }
                      setTemplateMessage(null);
                      saveTemplateMutation.mutate(trimmed);
                    }}
                    disabled={saveTemplateMutation.isPending}
                  >
                    {saveTemplateMutation.isPending ? 'Saving...' : 'Save as Template'}
                  </button>
                  {templateMessage && (
                    <span
                      className={`template-message ${saveTemplateMutation.isError ? 'template-message-error' : 'template-message-success'}`}
                    >
                      {templateMessage}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className={`jdm-footer jdm-footer-runbook ${activeTab === 'pipeline' || activeTab === 'diagnostics' ? 'is-hidden' : ''}`}>
            {pauseResumeAction}
            {activeTab === 'config' && !shouldShowRetry && (
              <button
                className="btn btn-primary"
                onClick={() => retryAnyMutation.mutate()}
                disabled={retryAnyMutation.isPending}
              >
                {retryAnyMutation.isPending ? 'Retrying...' : 'Retry Job'}
              </button>
            )}
            {activeTab !== 'pipeline' && activeTab !== 'diagnostics' && isLiveJob && (
              <button
                className="btn btn-danger"
                onClick={() => setShowCancelConfirm(true)}
                disabled={cancelJobMutation.isPending}
              >
                {cancelJobMutation.isPending ? 'Cancelling...' : 'Cancel Job'}
              </button>
            )}
            {activeTab !== 'errors' && retryAnyMutation.isError && (
              <span className="jdm-footer-hint error-message">
                {getRetryErrorMessage(retryAnyMutation.error)}
              </span>
            )}
            {cancelJobMutation.isError && (
              <span className="jdm-footer-hint error-message">
                {getJobActionErrorMessage(cancelJobMutation.error, 'Failed to cancel job.')}
              </span>
            )}
            <div className="jdm-footer-spacer" />
            <button className="btn btn-secondary" onClick={onClose}>
              {isPanel ? 'Clear selection' : 'Close'}
            </button>
          </div>
          <ConfirmDialog
            isOpen={showCancelConfirm}
            title="Cancel job?"
            description={`Stop ${job.job_name || job.job_id} immediately. Running tasks will be interrupted and the queue entry will move to cancelled state.`}
            confirmLabel="Cancel job"
            isPending={cancelJobMutation.isPending}
            onClose={() => setShowCancelConfirm(false)}
            onConfirm={() => {
              cancelJobMutation.mutate();
              setShowCancelConfirm(false);
            }}
          />
    </div>
  );

  return (
    <>
      {isPanel ? content : <div className="modal-overlay" onClick={onClose}>{content}</div>}

      {isEditOpen && (
        <div className="modal-overlay" onClick={() => setIsEditOpen(false)}>
          <div
            className="modal-content job-details-modal job-edit-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <JobCreator
              mode="edit"
              submitLabel="Save Changes"
              initialJobName={job.job_name || details?.job_name || ''}
              initialTasks={initialTasks}
              initialSchedule={initialSchedule}
              onSubmit={handleEditSubmit}
              onJobCreated={() => {
                setIsEditOpen(false);
                queryClient.invalidateQueries({ queryKey: ['jobs'] });
                queryClient.invalidateQueries({ queryKey: ['jobDetails', job.job_id] });
              }}
              onCancel={() => setIsEditOpen(false)}
            />
          </div>
        </div>
      )}
    </>
  );
}
