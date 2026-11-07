import { describe, expect, it } from 'vitest';

import type { WebSocketEvent } from '../../src/hooks/useWebSocket';
import { parseLiveTransfer } from '../../src/features/jobs/lib/runbookModel';

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
