import { render, screen, within } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskDetail } from '../../src/api/types/jobs';
import { JobRunbookPipeline } from '../../src/features/jobs/components/JobRunbookPipeline';
import type { WebSocketEvent } from '../../src/hooks/useWebSocket';

vi.mock('../../src/features/jobs/components/TaskEvidencePages', () => ({ TaskEvidencePages: () => null }));

const task = {
  task_id: 'task-1',
  task_type: 'download_media',
  status: 'running',
  site: 'onlyfans',
  content_type: 'Posts',
  items_processed: 639,
  items_total: 798,
  result: {
    message: 'Download in progress: 639/798',
    metrics: { download_items_total: 798, downloads_completed: 142, skipped: 497, failed: 0 },
    output: {},
  },
} as unknown as TaskDetail;

function renderPanel(liveEvent: Record<string, unknown>) {
  return render(
    <JobRunbookPipeline
      jobId="job-1"
      tasks={[task]}
      liveEvent={{ event: 'download_progress', job_id: 'job-1', task_id: 'task-1', ...liveEvent } as unknown as WebSocketEvent}
      isStreaming={false}
      isLiveJob
      canStreamTasks={false}
      streamMaxTotalTasks={0}
      emptyMessage="none"
      hasMoreTasks={false}
      isLoadingMoreTasks={false}
      onLoadMoreTasks={() => {}}
      pipelineRef={createRef<HTMLDivElement>()}
      taskStateFilter=""
      onTaskStateFilterChange={() => {}}
      taskTypeFilter=""
      onTaskTypeFilterChange={() => {}}
      taskTypeOptions={[]}
      hopUsedMin=""
      onHopUsedMinChange={() => {}}
      hopUsedMax=""
      onHopUsedMaxChange={() => {}}
      geoBlockedFilter={false}
      onGeoBlockedFilterChange={() => {}}
      errorOnlyFilter={false}
      onErrorOnlyFilterChange={() => {}}
      taskStateFilters={[]}
    />,
  );
}

describe('files in a download task', () => {
  it('shows the task counts and every file in flight with its destination', () => {
    const transfers = Array.from({ length: 8 }, (_, index) => ({
      media_id: index + 1,
      path: `/data/posts/${index + 1}.mp4`,
      processed_bytes: 50,
      expected_bytes: 100,
    }));
    renderPanel({ media_id: 1, active_transfers: transfers });

    const section = within(screen.getByRole('region', { name: /Media transfers inside/ }));
    expect(section.getByText('798 files')).toBeInTheDocument();
    expect(section.getByText('8 active')).toBeInTheDocument();
    expect(section.getByText('142 downloaded')).toBeInTheDocument();
    expect(section.getByText('497 skipped')).toBeInTheDocument();
    // Past the six a finished task's retained results are capped at.
    expect(section.getByRole('button', { name: /^8\.mp4, downloading, 50 percent/ })).toBeInTheDocument();
    expect(section.getByText('/data/posts/1.mp4')).toBeInTheDocument();
    expect(section.queryByText('Destination not published')).not.toBeInTheDocument();
    expect(section.queryByText(/more media results/)).not.toBeInTheDocument();
  });

  it('falls back to the one reported file from a worker that names no others', () => {
    renderPanel({ media_id: 9, path: '/data/posts/9.mp4', media_processed_bytes: 1, media_expected_bytes: 2 });

    const section = within(screen.getByRole('region', { name: /Media transfers inside/ }));
    expect(section.getByText('798 files')).toBeInTheDocument();
    expect(section.getByText('1 active')).toBeInTheDocument();
  });
});
