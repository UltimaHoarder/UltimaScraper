import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

test('content-tab video opens and loads in the lightbox', async ({ page }) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.route('**/api/v1/database/content**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        total: 1,
        page: 1,
        page_size: 20,
        content: [{
          id: 1,
          user_id: 123,
          username: 'onlyfans',
          content_type: 'post',
          text: 'Video smoke test',
          price: 0,
          paid: true,
          deleted: false,
          archived: false,
          media_count: 1,
          media: [{
            id: 1,
            category: 'video',
            preview: false,
            duration: 1.2,
            thumb_url: null,
            local_url: null,
          }],
          expires_at: null,
          created_at: '2026-08-06T00:00:00Z',
          site: 'onlyfans',
        }],
      }),
    });
  });
  await page.route('**/api/v1/media/stream/onlyfans/1**', async (route) => {
    const fixture = path.join(
      process.cwd(),
      'node_modules/@videojs/vhs-utils/test/fixtures/formats/mp4/avc1.4d401e,aac.mp4',
    );
    await route.fulfill({
      status: 200,
      contentType: 'video/mp4',
      body: fs.readFileSync(fixture),
    });
  });

  await page.goto('/users/123?site=onlyfans&source=content&tab=content');
  await page.locator('.content-card-media-item').click();

  await expect(page.locator('.cc-lightbox-overlay')).toBeVisible();
  await expect(page.locator('.cc-lightbox-media[data-media-category="video"]')).toBeVisible();
  await expect(page.locator('.cc-lightbox-media .video-js')).toBeVisible();
  await expect.poll(
    async () => page.locator('.cc-lightbox-media .vjs-tech').evaluate(
      (video: HTMLVideoElement) => video.currentSrc,
    ),
  ).toContain('/api/v1/media/stream/onlyfans/1');
  await expect(page.locator('.cc-lightbox-media .video-js')).not.toHaveClass(/vjs-error/);
});
