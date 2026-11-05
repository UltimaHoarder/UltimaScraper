import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

const TARGET_VIEWPORTS = [
  { width: 1053, expectedCols: 2 },
  { width: 1280, expectedCols: 2 },
  { width: 1440, expectedCols: 2 },
  { width: 1920, expectedCols: 4 },
  { width: 2560, expectedCols: 5 },
  { width: 3840, expectedCols: 10 },
  { width: 5120, expectedCols: 10 },
];

const ALLOWED_COLUMNS = new Set([1, 2, 4, 5, 10]);

test('Users card grid uses responsive column counts that divide 100 evenly (1, 2, 4, 5, 10)', async ({ page }, testInfo) => {
  // Desktop loads the page at seven widths, up to 5120px, so it needs more than the default time.
  test.slow(testInfo.project.name === 'desktop', 'loads the Users page at seven viewport widths');
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);

  await page.route('**/api/v1/users/?*', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('stats_only') === 'true') {
      return route.fulfill({ json: { success: true, users: [], total: 100, active: 100, inactive: 0, free: 0, paid: 100, avg_price: 5 } });
    }
    const users = Array.from({ length: 100 }, (_, i) => ({
      id: i + 1,
      user_id: i + 1,
      site: 'onlyfans',
      username: `user_${i + 1}`,
      name: `User ${i + 1}`,
      avatar_url: null,
      header_url: null,
      description: null,
      price: 5,
      post_count: 10,
      image_count: 5,
      video_count: 5,
      media_count: 10,
      favorite: false,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: null,
    }));
    return route.fulfill({ json: { success: true, users, total: 100, has_more: false } });
  });

  const viewports = testInfo.project.name === 'desktop'
    ? TARGET_VIEWPORTS
    : [{ width: page.viewportSize()?.width ?? 412, expectedCols: (page.viewportSize()?.width ?? 412) < 656 ? 1 : 2 }];

  for (const { width, expectedCols } of viewports) {
    if (testInfo.project.name === 'desktop') {
      await page.setViewportSize({ width, height: 960 });
    }
    await page.goto('/users?site=onlyfans');
    await expect(page.locator('.users-grid .user-card').first()).toBeVisible();

    const info = await page.evaluate(() => {
      const grid = document.querySelector('.users-grid');
      if (!grid) return null;
      const computed = getComputedStyle(grid);
      const cols = computed.gridTemplateColumns.trim().split(/\s+/).filter(Boolean);
      const cards = Array.from(grid.querySelectorAll('.user-card'));
      const firstCardRect = cards[0]?.getBoundingClientRect();
      const containerRect = grid.closest('.user-card-grid-container')?.getBoundingClientRect() || grid.getBoundingClientRect();
      return {
        columnCount: cols.length,
        cardWidth: firstCardRect?.width ?? 0,
        containerWidth: containerRect.width,
        cardCount: cards.length,
      };
    });

    console.log(`[Users ${testInfo.project.name}] Viewport ${width}px -> Container: ${info?.containerWidth?.toFixed(1)}px, Cols: ${info?.columnCount}, CardWidth: ${info?.cardWidth?.toFixed(1)}px`);
    expect(info).not.toBeNull();
    expect(ALLOWED_COLUMNS.has(info!.columnCount)).toBe(true);
    expect(info!.columnCount).toBe(expectedCols);
    if (info!.containerWidth >= 656) {
      expect(info!.cardWidth).toBeGreaterThanOrEqual(320);
    }

    // Verify 100 users fill whole rows with 0 leftover cards in incomplete rows
    expect(100 % info!.columnCount).toBe(0);
    const completeRows = 100 / info!.columnCount;
    expect(Number.isInteger(completeRows)).toBe(true);
  }
});

test('Subscriptions card grid uses responsive column counts that divide 100 evenly (1, 2, 4, 5, 10)', async ({ page }, testInfo) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);

  const viewports = testInfo.project.name === 'desktop'
    ? TARGET_VIEWPORTS
    : [{ width: page.viewportSize()?.width ?? 412, expectedCols: (page.viewportSize()?.width ?? 412) < 656 ? 1 : 2 }];

  for (const { width, expectedCols } of viewports) {
    if (testInfo.project.name === 'desktop') {
      await page.setViewportSize({ width, height: 960 });
    }
    await page.goto('/subscriptions');
    await expect(page.locator('.subscriptions-grid .user-card').first()).toBeVisible();

    const info = await page.evaluate(() => {
      const grid = document.querySelector('.subscriptions-grid');
      if (!grid) return null;
      const computed = getComputedStyle(grid);
      const cols = computed.gridTemplateColumns.trim().split(/\s+/).filter(Boolean);
      const firstCard = grid.querySelector('.user-card');
      const cardRect = firstCard?.getBoundingClientRect();
      const containerRect = grid.closest('.user-card-grid-container')?.getBoundingClientRect() || grid.getBoundingClientRect();
      return {
        columnCount: cols.length,
        cardWidth: cardRect?.width ?? 0,
        containerWidth: containerRect.width,
      };
    });

    console.log(`[Subscriptions ${testInfo.project.name}] Viewport ${width}px -> Container: ${info?.containerWidth?.toFixed(1)}px, Cols: ${info?.columnCount}, CardWidth: ${info?.cardWidth?.toFixed(1)}px`);
    expect(info).not.toBeNull();
    expect(ALLOWED_COLUMNS.has(info!.columnCount)).toBe(true);
    expect(info!.columnCount).toBe(expectedCols);
    if (info!.containerWidth >= 656) {
      expect(info!.cardWidth).toBeGreaterThanOrEqual(320);
    }
    expect(100 % info!.columnCount).toBe(0);
  }
});

test('Favourites creators card grid uses responsive column counts dividing 100 evenly', async ({ page }, testInfo) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);

  await page.route('**/api/v1/favourites**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/status')) {
      return route.fulfill({ json: { enabled: true } });
    }
    if (url.pathname.endsWith('/counts')) {
      return route.fulfill({ json: { total: 100, by_type: { user: 100, post: 0, story: 0, message: 0 } } });
    }
    const items = Array.from({ length: 100 }, (_, i) => ({
      id: i + 1,
      site: 'onlyfans',
      entity_type: 'user',
      entity_id: i + 1,
      created_at: '2026-10-13T00:00:00Z',
      created_at_source: 'user_downloaded_at',
      availability: 'available',
      entity: {
        id: i + 1,
        user_id: i + 1,
        site: 'onlyfans',
        username: `creator_${i + 1}`,
        name: `Creator ${i + 1}`,
        description: null,
        sex: null,
        gender: null,
        price: 5,
        post_count: 10,
        image_count: 5,
        video_count: 5,
        media_count: 10,
        favorite: true,
        is_active: true,
        is_subscribed: false,
        is_pending_order: false,
        downloaded_at: null,
        last_checked_at: null,
      },
    }));
    return route.fulfill({ json: { items, has_more: false, next_cursor: null } });
  });

  const viewports = testInfo.project.name === 'desktop'
    ? TARGET_VIEWPORTS
    : [{ width: page.viewportSize()?.width ?? 412, expectedCols: (page.viewportSize()?.width ?? 412) < 656 ? 1 : 2 }];

  for (const { width, expectedCols } of viewports) {
    if (testInfo.project.name === 'desktop') {
      await page.setViewportSize({ width, height: 960 });
    }
    await page.goto('/favourites');
    await expect(page.locator('.favourites-users-grid .user-card').first()).toBeVisible();

    const info = await page.evaluate(() => {
      const grid = document.querySelector('.favourites-users-grid');
      if (!grid) return null;
      const computed = getComputedStyle(grid);
      const cols = computed.gridTemplateColumns.trim().split(/\s+/).filter(Boolean);
      const firstCard = grid.querySelector('.user-card');
      const cardRect = firstCard?.getBoundingClientRect();
      const containerRect = grid.closest('.user-card-grid-container')?.getBoundingClientRect() || grid.getBoundingClientRect();
      return {
        columnCount: cols.length,
        cardWidth: cardRect?.width ?? 0,
        containerWidth: containerRect.width,
      };
    });

    console.log(`[Favourites ${testInfo.project.name}] Viewport ${width}px -> Container: ${info?.containerWidth?.toFixed(1)}px, Cols: ${info?.columnCount}, CardWidth: ${info?.cardWidth?.toFixed(1)}px`);
    expect(info).not.toBeNull();
    expect(ALLOWED_COLUMNS.has(info!.columnCount)).toBe(true);
    expect(info!.columnCount).toBe(expectedCols);
    if (info!.containerWidth >= 656) {
      expect(info!.cardWidth).toBeGreaterThanOrEqual(320);
    }
    expect(100 % info!.columnCount).toBe(0);
  }
});
