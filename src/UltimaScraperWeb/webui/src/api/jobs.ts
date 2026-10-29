import { createHttpClient, getApiBaseUrl } from './http';
import {
  streamJobTasksFromSource,
  type ActiveTaskListResponse,
  type CancelJobResponse,
  type CreateJobRequest,
  type CreateJobTemplateRequest,
  type DeleteJobsRequest,
  type DeleteJobsResponse,
  type HealthResponse,
  type InstantiateTemplateRequest,
  type Job,
  type JobDetail,
  type JobListResponse,
  type JobRuntimeSamplesPage,
  type JobTemplateResponse,
  type PrioritizeJobResponse,
  type QueueStats,
  type TaskDefinition,
  type TaskDetail,
  type TaskPageResponse,
  type TaskQueryOptions,
  type UpdateJobRequest,
} from './types/jobs';

const http = createHttpClient();

export interface TaskMediaEvidencePage {
  items: unknown[];
  ordinals: number[];
  next_cursor: number | null;
}

export async function getTaskMediaEvidence(
  jobId: string,
  taskId: string,
  selectionId: string,
  kind: 'download_results' | 'errors',
  after = -1,
  signal?: AbortSignal,
): Promise<TaskMediaEvidencePage> {
  const response = await http.get<TaskMediaEvidencePage>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/tasks/${encodeURIComponent(taskId)}/evidence/${encodeURIComponent(selectionId)}`,
    { params: { kind, after, limit: 6 }, signal },
  );
  return response.data;
}

export async function getTaskTypes(): Promise<TaskDefinition[]> {
  const response = await http.get<TaskDefinition[]>('/api/v1/tasks/types');
  return response.data;
}

export async function getJobs(
  status?: string,
  page = 1,
  pageSize = 50,
  search?: string,
  includeTasks = false,
  includeApiCommands = true,
  type?: string,
  owner?: string,
  schedule?: string,
  site?: string,
): Promise<JobListResponse> {
  const params: {
    page: number;
    page_size: number;
    status?: string;
    search?: string;
    include_tasks?: string;
    include_api_commands: boolean;
    type?: string;
    owner?: string;
    schedule?: string;
    site?: string;
  } = {
    page,
    page_size: pageSize,
    include_tasks: includeTasks ? 'true' : 'false',
    include_api_commands: includeApiCommands,
  };

  if (status && status !== 'all') {
    params.status = status;
  }
  if (search && search.trim().length > 0) {
    params.search = search.trim();
  }
  if (type && type !== 'all') {
    params.type = type;
  }
  if (owner && owner !== 'all') {
    params.owner = owner;
  }
  if (schedule && schedule !== 'all') {
    params.schedule = schedule;
  }
  if (site && site !== 'all') {
    params.site = site;
  }

  const response = await http.get<JobListResponse>('/api/v1/jobs', {
    params,
    timeout: 25000,
  });
  return response.data;
}

export async function getActiveTasks(
  limitJobs = 120,
  limitTasks = 250,
): Promise<ActiveTaskListResponse> {
  const response = await http.get<ActiveTaskListResponse>('/api/v1/jobs/active-tasks', {
    params: {
      limit_jobs: limitJobs,
      limit_tasks: limitTasks,
    },
    timeout: 25000,
  });
  return response.data;
}

export async function createJob(request: CreateJobRequest): Promise<Job> {
  const response = await http.post<Job>('/api/v1/jobs', request);
  return response.data;
}

export async function createJobTemplateFromJob(
  jobId: string,
  request: CreateJobTemplateRequest,
): Promise<JobTemplateResponse> {
  const response = await http.post<JobTemplateResponse>(
    `/api/v1/jobs/${jobId}/template`,
    request,
  );
  return response.data;
}

export async function listTemplates(): Promise<JobTemplateResponse[]> {
  const response = await http.get<JobTemplateResponse[]>('/api/v1/jobs/templates');
  return response.data;
}

export async function instantiateTemplate(
  templateId: string,
  request: InstantiateTemplateRequest,
): Promise<Job> {
  const response = await http.post<Job>(
    `/api/v1/jobs/templates/${templateId}/instantiate`,
    request,
  );
  return response.data;
}

export async function updateJob(jobId: string, request: UpdateJobRequest): Promise<Job> {
  const response = await http.patch<Job>(`/api/v1/jobs/${jobId}`, request);
  return response.data;
}

export async function retryJob(jobId: string, authId?: number): Promise<Job> {
  const body: Record<string, unknown> = {};
  if (authId !== undefined) {
    body.auth_id = authId;
  }
  const response = await http.post<Job>(`/api/v1/jobs/${jobId}/retry`, body);
  return response.data;
}

export async function prioritizeJob(jobId: string): Promise<PrioritizeJobResponse> {
  const response = await http.post<PrioritizeJobResponse>(`/api/v1/jobs/${jobId}/prioritize`);
  return response.data;
}

export async function cancelJob(jobId: string): Promise<CancelJobResponse> {
  const response = await http.post<CancelJobResponse>(`/api/v1/jobs/${jobId}/cancel`);
  return response.data;
}

export async function pauseJob(jobId: string): Promise<Job> {
  const response = await http.post<Job>(`/api/v1/jobs/${jobId}/pause`);
  return response.data;
}

export async function resumeJob(jobId: string): Promise<Job> {
  const response = await http.post<Job>(`/api/v1/jobs/${jobId}/resume`);
  return response.data;
}

export interface DeleteJobsProgress {
  completed: number;
  total: number;
  failed?: number;
  job_id?: string;
  table?: string;
  rows?: number;
  status?: Job['status'];
}

export async function deleteJobs(
  request: DeleteJobsRequest,
  onProgress?: (progress: DeleteJobsProgress) => void,
): Promise<DeleteJobsResponse> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/jobs/bulk-delete-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Job deletion failed (${response.status}).`);
  }
  if (!response.body) throw new Error('Deletion progress is unavailable. Refresh jobs before retrying.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let latest: DeleteJobsProgress = { completed: 0, total: 0 };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === 'progress') { latest = event; onProgress?.(latest); }
        if (event.type === 'cleanup' || event.type === 'state') onProgress?.({ ...latest, ...event });
        if (event.type === 'error') throw new Error(event.error);
        if (event.type === 'result') return event as DeleteJobsResponse;
      }
      if (done) throw new Error('Deletion connection ended. Cleanup may still be running; refresh jobs before retrying.');
    }
  } finally {
    reader.releaseLock();
  }
}

export async function getQueueStats(): Promise<QueueStats> {
  const response = await http.get<QueueStats>('/api/v1/admin/queue-stats', {
    timeout: 15000,
  });
  return response.data;
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await http.get<HealthResponse>('/api/v1/admin/health', {
    timeout: 10000,
  });
  return response.data;
}

export async function getJobDetails(
  jobId: string,
  includeTasks = false,
): Promise<JobDetail> {
  const response = await http.get<JobDetail>(`/api/v1/jobs/${jobId}`, {
    params: { include_tasks: includeTasks },
  });
  return response.data;
}

export async function getJobRuntimeSamples(
  jobId: string,
  afterId?: string,
  signal?: AbortSignal,
): Promise<JobRuntimeSamplesPage> {
  const response = await http.get<JobRuntimeSamplesPage>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/runtime-samples`,
    {
      params: { after_id: afterId, limit: 10_000 },
      signal,
    },
  );
  return response.data;
}

export async function getJobTasks(
  jobId: string,
  options: TaskQueryOptions = {},
): Promise<TaskPageResponse> {
  const response = await http.get<TaskPageResponse>(`/api/v1/jobs/${jobId}/tasks`, {
    params: {
      cursor: options.cursor,
      offset: options.offset ?? 0,
      limit: options.limit ?? 100,
      state: options.state,
      task_type: options.task_type,
      error_only: options.error_only ? 'true' : undefined,
    },
  });
  return response.data;
}

export function streamJobTasks(
  jobId: string,
  onTask: (task: TaskDetail) => void,
  onDone?: () => void,
  onError?: (err: Event) => void,
  options: TaskQueryOptions = {},
  baseUrl: string = getApiBaseUrl(),
): () => void {
  return streamJobTasksFromSource(jobId, onTask, onDone, onError, options, baseUrl);
}
