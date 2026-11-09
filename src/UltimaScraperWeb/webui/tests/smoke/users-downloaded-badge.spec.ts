import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

function creator(id: number, username: string, downloadedAt: string | null) {
  return { id, user_id: id, site: 'onlyfans', username, name: `Creator ${id}`, avatar_url: null, header_url: null,
    description: null, sex: null, gender: null, price: 5, post_count: 1, image_count: 0, video_count: 1, media_count: 1,
    favorite: false, is_active: true, is_subscribed: false, is_pending_order: false, downloaded_at: downloadedAt,
    last_checked_at: null };
}

test('the users page marks creators that have been downloaded', async ({ page }, testInfo) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.route('**/api/v1/users/?*', route => route.fulfill({ json: { success: true, total: 2, active: 2,
    inactive: 0, free: 0, paid: 2, avg_price: 5, has_more: false,
    users: [creator(1, 'saved_creator', '2026-11-08T19:15:56+00:00'), creator(2, 'never_saved', null)] } }));

  await page.goto('/users?site=onlyfans');
  await expect(page.getByRole('link', { name: '@saved_creator', exact: true }).first()).toBeVisible();
  await expect(page.getByText('Downloaded', { exact: false }).filter({ visible: true })).toHaveCount(1);

  if (process.env.CAPTURE_THEME_SHOTS === '1') {
    await page.screenshot({ path: testInfo.outputPath('users-downloaded-badge.png'), fullPage: true });
  }
});
