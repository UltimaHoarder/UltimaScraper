import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TaskEvidencePages } from '../../src/features/jobs/components/TaskEvidencePages';
import { getTaskDownloadErrorCount } from '../../src/features/jobs/lib/jobUtils';
import { getTaskMediaEvidence } from '../../src/api/jobs';
import type { TaskDetail } from '../../src/api/types/jobs';

vi.mock('../../src/api/jobs', () => ({ getTaskMediaEvidence: vi.fn() }));
vi.mock('../../src/api/media', () => ({
  getJobTaskResultFileUrl: (job: string, task: string, ordinal: number) => `/files/${job}/${task}/${ordinal}`,
}));

function task(selectionId = 'selection'): TaskDetail {
  return { task_id: 'task', task_type: 'download', status: 'completed', items_processed: 1000,
    result: { metrics: { failed: 123 }, output: {
      media_evidence: { selection_id: selectionId }, download_results_total: 1000,
      download_results: [{ media_id: 1, status: 'failed' }],
    } } } as unknown as TaskDetail;
}

describe('durable task reports', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the complete aggregate error count instead of counting the preview', () => {
    expect(getTaskDownloadErrorCount(task())).toBe(123);
  });

  it('loads on request and replaces the previous page while preserving exact file ordinals', async () => {
    vi.mocked(getTaskMediaEvidence)
      .mockResolvedValueOnce({ items: [{ media_id: 11, path: '/fixture/11', status: 'downloaded' }], ordinals: [0], next_cursor: 0 })
      .mockResolvedValueOnce({ items: [{ media_id: 22, path: '/fixture/22', status: 'downloaded' }], ordinals: [1], next_cursor: null });
    render(<TaskEvidencePages jobId="job" task={task()} />);
    expect(getTaskMediaEvidence).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Complete file report'));
    await screen.findByText('downloaded · media 11');
    expect(screen.getByText('Open recorded file')).toHaveAttribute('href', '/files/job/task/0');
    fireEvent.click(screen.getByText('Next page'));
    await screen.findByText('downloaded · media 22');
    expect(screen.queryByText('downloaded · media 11')).not.toBeInTheDocument();
    expect(screen.getByText('Open recorded file')).toHaveAttribute('href', '/files/job/task/1');
    expect(screen.getByText('Next page')).toBeDisabled();
  });

  it('aborts pending reads when the selected task generation changes', async () => {
    vi.mocked(getTaskMediaEvidence).mockImplementation(() => new Promise(() => {}));
    const rendered = render(<TaskEvidencePages jobId="job" task={task()} />);
    fireEvent.click(screen.getByText('Complete file report'));
    await waitFor(() => expect(getTaskMediaEvidence).toHaveBeenCalledOnce());
    const signal = vi.mocked(getTaskMediaEvidence).mock.calls[0][5];
    rendered.rerender(<TaskEvidencePages jobId="job" task={task('next')} />);
    expect(signal?.aborted).toBe(true);
  });
});
