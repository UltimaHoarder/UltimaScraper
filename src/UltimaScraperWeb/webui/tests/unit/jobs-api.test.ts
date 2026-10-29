import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
}));

vi.mock('../../src/api/http', () => ({
  createHttpClient: () => ({ get: getMock }),
}));

import { getJobs } from '../../src/api/jobs';

describe('jobs API filters', () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockResolvedValue({ data: { jobs: [], total: 0, page: 1, page_size: 200 } });
  });

  it('sends the site as a filter rather than a search term', async () => {
    await getJobs(undefined, 1, 200, undefined, false, false, undefined, undefined, undefined, 'OnlyFans');

    expect(getMock).toHaveBeenCalledWith('/api/v1/jobs', {
      params: {
        page: 1,
        page_size: 200,
        include_tasks: 'false',
        include_api_commands: false,
        site: 'OnlyFans',
      },
      timeout: 25000,
    });
  });
});
