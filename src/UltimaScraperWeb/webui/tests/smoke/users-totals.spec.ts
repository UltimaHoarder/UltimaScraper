import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

test('user pages and pagination survive a slow or failed exact total', async ({ page }) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  let totalsRequests = 0;
  const offsets: number[] = [];
  await page.route('**/api/v1/users/?*', async route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('stats_only') === 'true') {
      totalsRequests++;
      if (totalsRequests === 1) {
        await waiting;
        return route.fulfill({ json: { success: false, users: [], error: 'statement timeout' } });
      }
      return route.fulfill({ json: { success: true, users: [], total: 150, active: 150,
        inactive: 0, free: 0, paid: 150, avg_price: 5 } });
    }
    expect(params.get('include_stats')).toBe('false');
    const offset = Number(params.get('offset') || 0);
    offsets.push(offset);
    const users = Array.from({ length: offset === 0 ? 100 : 50 }, (_, index) => {
      const id = offset + index + 1;
      return { id, user_id: id, site: 'onlyfans', username: `count_test_${id}`, name: `Creator ${id}`,
        avatar_url: null, header_url: null, description: null, sex: null, gender: null, price: 5,
        post_count: 1, image_count: 0, video_count: 1, media_count: 1, favorite: false, is_active: true,
        is_subscribed: false, is_pending_order: false, downloaded_at: null, last_checked_at: null };
    });
    return route.fulfill({ json: { success: true, users, total: null, active: null,
      inactive: null, avg_price: null, free: null, paid: null, has_more: offset === 0 } });
  });
  await page.goto('/users?site=onlyfans');
  await expect(page.getByRole('link', { name: '@count_test_1', exact: true }).first()).toBeVisible();
  await expect(page.getByText('Loading totals…')).toBeVisible();
  expect(totalsRequests).toBe(1);
  release();
  await expect(page.getByText('Totals unavailable')).toBeVisible();
  await expect(page.getByRole('link', { name: '@count_test_1', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText('150 Creators in Roster')).toBeVisible();
  const loadMore = page.getByRole('button', { name: 'Load More (100)', exact: true });
  if (await loadMore.count()) await loadMore.evaluate(button => (button as HTMLButtonElement).click());
  await expect.poll(() => offsets.includes(100)).toBe(true);
  await expect(page.getByRole('link', { name: '@count_test_150', exact: true }).first()).toBeVisible();
  expect(totalsRequests).toBe(2);
  await expect(page.getByText('All users loaded')).toBeVisible();
});
