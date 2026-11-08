import { describe, expect, it } from 'vitest';

import type { WebSocketEvent } from '../../src/hooks/useWebSocket';
import { parseLiveTransfer, taskFileCounts } from '../../src/features/jobs/lib/runbookModel';

const GB = 1024 ** 3;

function progress(extra: Record<string, unknown>): WebSocketEvent {
  return {
    event: 'download_progress',
    job_id: 'job-1',
    task_id: 'task-1',
    media_id: 584964909,
    processed_bytes: 6.3 * GB,
    expected_bytes: 42.2 * GB,
    ...extra,
  } as unknown as WebSocketEvent;
}

describe('parseLiveTransfer', () => {
  it('keeps the file and the whole task apart', () => {
    const live = parseLiveTransfer(progress({ media_processed_bytes: 0.4 * GB, media_expected_bytes: 1.2 * GB }), 'job-1');

    expect(live?.mediaId).toBe('584964909');
    expect([live?.mediaProcessedBytes, live?.mediaExpectedBytes]).toEqual([0.4 * GB, 1.2 * GB]);
    expect([live?.processedBytes, live?.expectedBytes]).toEqual([6.3 * GB, 42.2 * GB]);
  });

  it('gives no file size when the worker does not report one', () => {
    const live = parseLiveTransfer(progress({}), 'job-1');

    // Never the task's totals in their place.
    expect([live?.mediaProcessedBytes, live?.mediaExpectedBytes]).toEqual([null, null]);
  });
});

describe('active transfers', () => {
  it('reads every file in flight', () => {
    const live = parseLiveTransfer(
      progress({
        active_transfers: [
          { media_id: 1, path: '/dest/a.mp4', processed_bytes: 5, expected_bytes: 10 },
          { media_id: 2, path: null, processed_bytes: 0, expected_bytes: 20 },
        ],
      }),
      'job-1',
    );

    expect(live?.activeTransfers).toEqual([
      { mediaId: '1', path: '/dest/a.mp4', processedBytes: 5, expectedBytes: 10 },
      { mediaId: '2', path: null, processedBytes: 0, expectedBytes: 20 },
    ]);
  });

  it('is empty from a worker that does not report them', () => {
    expect(parseLiveTransfer(progress({}), 'job-1')?.activeTransfers).toEqual([]);
  });
});

describe('taskFileCounts', () => {
  it('reads a running task', () => {
    expect(
      taskFileCounts({ download_items_total: 798, downloads_completed: 142, skipped: 497, failed: 1 }),
    ).toEqual({ total: 798, downloaded: 142, skipped: 497, failed: 1 });
  });

  it('reads a finished profile task', () => {
    expect(taskFileCounts({ total_items: 2, success_count: 2, skip_count: 0, fail_count: 0 })).toEqual({
      total: 2,
      downloaded: 2,
      skipped: 0,
      failed: 0,
    });
  });

  it('has nothing to say about a task with no files', () => {
    expect(taskFileCounts({ total_items: 0 })).toBeNull();
    expect(taskFileCounts({})).toBeNull();
  });
});
