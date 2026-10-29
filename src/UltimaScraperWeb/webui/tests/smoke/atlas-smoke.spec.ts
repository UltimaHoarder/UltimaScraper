import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

test('Atlas integrates telemetry, workers, job details, and responsive navigation', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'DATA AT SCALE.' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ultima-atlas');
  await expect(page.locator('.atlas-acquisition')).toHaveCount(0);
  await expect(page.getByText('Awaiting operations', { exact: true })).toHaveCount(0);
  const pipeline = page.getByRole('region', { name: 'Acquisition pipeline', exact: true });
  await expect(pipeline).toBeVisible();
  const placement = await pipeline.evaluate((node) => {
    const chart = document.querySelector('.system-pulse__throughput')!.getBoundingClientRect();
    const rect = node.getBoundingClientRect();
    return { below: rect.top >= chart.bottom - 1, aligned: Math.abs(rect.left - chart.left) < 1, followsChart: node.previousElementSibling?.classList.contains('system-pulse__throughput') };
  });
  expect(placement).toEqual({ below: true, aligned: true, followsChart: true });
  await expect(page.getByRole('heading', { name: 'Worker array' })).toBeVisible();
  await expect(page.locator('.atlas-worker-units button')).toHaveCount(2);
  await page.getByRole('button', { name: 'worker-1: busy', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Worker unit details' })).toContainText('job-running-1');
  await page.getByRole('button', { name: 'Close worker details' }).click();
  await expect(page.getByRole('region', { name: 'Worker unit details' })).toHaveCount(0);
  await page.getByRole('button', { name: '15 min', exact: true }).click();
  await page.getByRole('button', { name: 'Save view', exact: true }).click();
  await expect(page.getByRole('button', { name: 'View saved', exact: true })).toBeVisible();
  await page.locator('.system-pulse__job').filter({ hasText: 'Running Smoke Job' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.atlas-scene canvas')).toBeVisible();
  const scene = page.locator('.atlas-scene canvas');
  const firstFrame = await scene.screenshot();
  const cyanPixels = await page.evaluate(async (base64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${base64}`;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = img.width; canvas.height = img.height;
    const context = canvas.getContext('2d')!;
    context.drawImage(img, 0, 0);
    const pixels = context.getImageData(0, 0, img.width, img.height).data;
    let cyan = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index + 1] > 90 && pixels[index + 2] > 110 && pixels[index + 1] - pixels[index] > 35) cyan++;
    }
    return cyan;
  }, firstFrame.toString('base64'));
  expect(cyanPixels).toBeGreaterThan(50);
  await expect.poll(async () => (await scene.screenshot()).equals(firstFrame)).toBe(false);
  await page.getByRole('button', { name: 'Pause motion' }).click();
  await expect(page.getByRole('button', { name: 'Resume motion' })).toHaveAttribute('aria-pressed', 'true');
  const geometry = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('.system-pulse__panel, .system-pulse__kpis article')];
    const overlaps = nodes.some((node, index) => nodes.slice(index + 1).some((other) => {
      const a = node.getBoundingClientRect(); const b = other.getBoundingClientRect();
      return Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
    }));
    return { overflow: document.documentElement.scrollWidth > innerWidth, overlaps };
  });
  expect(geometry).toEqual({ overflow: false, overlaps: false });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('ultima-atlas-dashboard.png'), fullPage: true });
  await page.locator('.atlas-scene canvas').screenshot({ path: testInfo.outputPath('ultima-atlas-infrastructure.png') });
  await page.locator('.system-pulse__grid').screenshot({ path: testInfo.outputPath('ultima-atlas-telemetry.png') });
  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: 'Open menu' }).click();
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
    await page.getByRole('link', { name: 'Network', exact: true }).click();
  } else {
    await page.getByRole('link', { name: 'Manage proxies' }).click();
  }
  await expect(page).toHaveURL(/\/network$/);
  await page.goto('/');
  await expect(page.locator('.system-pulse')).toHaveAttribute('data-pulse-range', '15 min');
  expect(errors).toEqual([]);
});

test('Atlas retains readable telemetry with reduced motion and unavailable WebGL', async ({ page }) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args: Parameters<typeof original>) {
      if (String(args[0]).startsWith('webgl')) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await page.goto('/');
  await expect(page.locator('.atlas-scene-fallback')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'System telemetry' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'worker-1: busy', exact: true })).toBeAttached();
});
