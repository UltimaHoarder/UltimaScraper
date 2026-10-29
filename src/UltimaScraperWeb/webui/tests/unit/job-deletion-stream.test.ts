import { afterEach, describe, expect, it, vi } from 'vitest';
import { deleteJobs } from '../../src/api/jobs';

afterEach(() => vi.unstubAllGlobals());

function mockStream(parts: string[]) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(new TextEncoder().encode(part));
      controller.close();
    },
  }), { status: 200 })));
}

describe('job deletion stream', () => {
  it('decodes split records and reports actual cleanup before completion', async () => {
    mockStream([
      '{"type":"pro',
      'gress","completed":0,"total":1}\n{"type":"cleanup","rows":25000,"table":"execution_outbox"}\n',
      '{"type":"progress","completed":1,"total":1}\n',
      '{"type":"result","requested":1,"deleted":1,"failed":0,"failures":[]}\n',
    ]);
    const progress = vi.fn();
    expect(await deleteJobs({ job_ids: ['a'] }, progress)).toMatchObject({ deleted: 1 });
    expect(progress).toHaveBeenNthCalledWith(2, expect.objectContaining({ completed: 0, rows: 25000 }));
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ completed: 1, total: 1 }));
  });

  it('does not report success when the connection ends before a result', async () => {
    mockStream(['{"type":"progress","completed":0,"total":1}\n']);
    await expect(deleteJobs({ job_ids: ['a'] })).rejects.toThrow('Cleanup may still be running');
  });
});
