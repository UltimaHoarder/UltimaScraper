import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
}));

vi.mock('../../src/api/http', () => ({
  createHttpClient: () => ({ post: postMock }),
}));

import { analyzeMps, createMpsJob } from '../../src/api/mps';

describe('MPS API request timeouts', () => {
  beforeEach(() => {
    postMock.mockReset();
    postMock.mockResolvedValue({ data: {} });
  });

  it('does not time out long-running analysis requests', async () => {
    const request = { site: 'OnlyFans', batch_size: 1_000_000 };

    await analyzeMps(request);

    expect(postMock).toHaveBeenCalledWith('/api/v1/mps/analyze', request, {
      timeout: 0,
    });
  });

  it('does not time out long-running job creation requests', async () => {
    const request = { site: 'OnlyFans', max_profiles: 1_000_000 };

    await createMpsJob(request);

    expect(postMock).toHaveBeenCalledWith('/api/v1/mps/create-job', request, {
      timeout: 0,
    });
  });
});
