import type { ActiveTaskDetail, Job } from '../../../api/types/jobs';

export interface JobCompletionSample {
  timestamp: number;
  completedTasks: number;
  runCount: number;
  rate: number;
}

export function buildJobCompletionSamples(
  jobs: Job[],
  updatedAt: number,
  previousSamples: Record<string, JobCompletionSample>,
): Record<string, JobCompletionSample> {
  const samples: Record<string, JobCompletionSample> = {};
  for (const job of jobs) {
    const completedTasks = Number.isFinite(job.completed_tasks)
      ? Math.max(0, job.completed_tasks)
      : 0;
    const runCount = job.run_count ?? 0;
    const previous = previousSamples[job.job_id];
    const elapsed = previous ? (updatedAt - previous.timestamp) / 1000 : 0;
    const reset = previous && (
      completedTasks < previous.completedTasks || runCount !== previous.runCount
    );

    // Keep the baseline across rapid event-driven refreshes so their completed
    // work is included once enough time has elapsed to measure a rate.
    if (previous && !reset && elapsed < 0.75) {
      samples[job.job_id] = previous;
      continue;
    }

    samples[job.job_id] = {
      timestamp: updatedAt,
      completedTasks,
      runCount,
      rate: previous && !reset && elapsed > 0
        ? (completedTasks - previous.completedTasks) / elapsed
        : 0,
    };
  }
  return samples;
}

export interface TaskWithSpeed extends ActiveTaskDetail {
  speed?: number;
  scraped_speed?: number;
  saved_speed?: number;
  lastUpdated?: number;
  scraped_processed?: number;
  scraped_total?: number | null;
  saved_processed?: number;
  saved_total?: number | null;
  worker_id?: string | null;
  current_file?: string;
}

export interface StageSpeedSample {
  lastUpdated: number;
  scrapedProcessed: number;
  savedProcessed: number;
  itemsProcessed: number;
  scrapedSpeed: number;
  savedSpeed: number;
  itemsSpeed: number;
}

export interface ActiveTaskState {
  activeTasks: TaskWithSpeed[];
  stageSpeedSamples: Record<string, StageSpeedSample>;
}

function generateTaskKey(
  jobId: string,
  taskType: string,
  taskId?: string | null,
  username?: string | null
): string {
  if (taskId) {
    return `${jobId}:${taskId}`;
  }
  return `${jobId}:${taskType}:${(username ?? 'unknown').toLowerCase()}`;
}

function normalizeTaskStatus(
  status?: string | null
): 'pending' | 'running' | 'completed' | 'failed' {
  const normalized = (status ?? 'running').toLowerCase();
  if (normalized === 'pending' || normalized === 'claimed') return 'pending';
  if (normalized === 'completed' || normalized === 'success' || normalized === 'db_saved') {
    return 'completed';
  }
  if (normalized === 'failed' || normalized === 'cancelled' || normalized === 'error') {
    return 'failed';
  }
  return 'running';
}

function isSubscriptionScrapeTask(
  task: Pick<ActiveTaskDetail, 'task_type' | 'content_type'>
): boolean {
  return (
    task.task_type.toLowerCase() === 'scrape' &&
    (task.content_type ?? '').toLowerCase() === 'subscriptions'
  );
}

export function buildActiveTaskState(
  polledTasks: ActiveTaskDetail[],
  updatedAt: number,
  previousSamples: Record<string, StageSpeedSample>
): ActiveTaskState {
  const result: TaskWithSpeed[] = [];
  const nextStageSpeedSamples: Record<string, StageSpeedSample> = {};

  for (const task of polledTasks) {
    const jobIdLower = task.job_id.toLowerCase();
    if (
      jobIdLower === 'api' ||
      jobIdLower.startsWith('api-') ||
      jobIdLower.startsWith('test-') ||
      task.task_type === 'api_command'
    ) {
      continue;
    }

    const key = generateTaskKey(task.job_id, task.task_type, task.task_id, task.username);
    const normalizedStatus = normalizeTaskStatus(task.status);
    const isScrape = task.task_type.toLowerCase() === 'scrape';
    const isSubscriptionScrape = isSubscriptionScrapeTask(task);
    const usesScrapeStages = isScrape && !isSubscriptionScrape;
    const total = task.items_total ?? null;
    const processedCounter = Math.max(task.items_processed ?? 0, 0);
    const scrapedCounter = Math.max(task.items_scraped ?? 0, 0);
    const savedCounter = Math.max(task.items_saved ?? 0, 0);

    const speedSample = previousSamples[key];
    const sampleInvalid =
      speedSample != null &&
      ((usesScrapeStages &&
        (scrapedCounter < speedSample.scrapedProcessed ||
          savedCounter < speedSample.savedProcessed)) ||
        (!usesScrapeStages && processedCounter < speedSample.itemsProcessed));
    const baselineSample = sampleInvalid ? undefined : speedSample;

    let scrapedSpeed = baselineSample?.scrapedSpeed ?? 0;
    let savedSpeed = baselineSample?.savedSpeed ?? 0;
    let itemsSpeed = baselineSample?.itemsSpeed ?? 0;

    if (baselineSample) {
      const timeDelta = (updatedAt - baselineSample.lastUpdated) / 1000;
      const minSampleSeconds = 0.75;
      if (timeDelta >= minSampleSeconds) {
        if (usesScrapeStages) {
          const scrapedDelta = Math.max(0, scrapedCounter - baselineSample.scrapedProcessed);
          const savedDelta = Math.max(0, savedCounter - baselineSample.savedProcessed);
          const instantScrapedSpeed = scrapedDelta / timeDelta;
          const instantSavedSpeed = savedDelta / timeDelta;
          scrapedSpeed = baselineSample.scrapedSpeed * 0.65 + instantScrapedSpeed * 0.35;
          savedSpeed = baselineSample.savedSpeed * 0.65 + instantSavedSpeed * 0.35;
        } else {
          const processedDelta = Math.max(0, processedCounter - baselineSample.itemsProcessed);
          const instantItemsSpeed = processedDelta / timeDelta;
          itemsSpeed = baselineSample.itemsSpeed * 0.65 + instantItemsSpeed * 0.35;
        }
      }
    }

    if (normalizedStatus === 'running') {
      nextStageSpeedSamples[key] = {
        lastUpdated: updatedAt,
        scrapedProcessed: scrapedCounter,
        savedProcessed: savedCounter,
        itemsProcessed: processedCounter,
        scrapedSpeed,
        savedSpeed,
        itemsSpeed,
      };
    }

    let activeProcessed = task.items_processed;
    let activeProgress = task.progress ?? 0;
    if (usesScrapeStages) {
      const stage: 'scraped' | 'saved' = savedCounter > 0 ? 'saved' : 'scraped';
      activeProcessed = stage === 'saved' ? savedCounter : scrapedCounter;
      if (total != null && total > 0) {
        activeProgress = Math.min(activeProcessed / total, 1);
      }
    }

    result.push({
      ...task,
      status: normalizedStatus,
      items_processed: activeProcessed,
      progress: activeProgress,
      items_scraped: scrapedCounter,
      items_saved: savedCounter,
      scraped_processed: scrapedCounter,
      scraped_total: isScrape ? total : null,
      saved_processed: savedCounter,
      saved_total: isScrape ? total : null,
      scraped_speed: usesScrapeStages ? scrapedSpeed : 0,
      saved_speed: usesScrapeStages ? savedSpeed : 0,
      speed: usesScrapeStages ? (savedSpeed > 0 ? savedSpeed : scrapedSpeed) : itemsSpeed,
      lastUpdated: updatedAt,
    });
  }

  return {
    activeTasks: result,
    stageSpeedSamples: nextStageSpeedSamples,
  };
}

export function formatBytesPerSecond(bytesPerSecond: number): string {
  if (bytesPerSecond < 1024) return `${bytesPerSecond.toFixed(0)} B/s`;
  const kb = bytesPerSecond / 1024;
  if (kb < 1024) return `${kb.toFixed(kb >= 100 ? 0 : kb >= 10 ? 1 : 2)} KB/s`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(mb >= 100 ? 0 : mb >= 10 ? 1 : 2)} MB/s`;
  const gb = mb / 1024;
  return `${gb.toFixed(gb >= 100 ? 0 : gb >= 10 ? 1 : 2)} GB/s`;
}
