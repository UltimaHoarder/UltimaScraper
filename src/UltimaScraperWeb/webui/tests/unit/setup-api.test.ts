import { expect, it, vi } from 'vitest';

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../../src/api/http', () => ({ createHttpClient: () => ({ post }) }));
import { applyStartupMigration } from '../../src/api/setup';

it('waits for the migration transaction result beyond the default request timeout', async () => {
  const result = { success: true, message: 'Migration applied successfully.', output: [] };
  post.mockResolvedValue({ data: result });
  await expect(applyStartupMigration({ preview_id: 'reviewed' })).resolves.toEqual(result);
  expect(post).toHaveBeenCalledWith('/api/v1/setup/migrations/apply', { preview_id: 'reviewed' }, { timeout: 0 });
});
