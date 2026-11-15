import { expect, test, type Page } from '@playwright/test';

import { installApiMocks, seedConfiguredApp } from './helpers';

const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

async function mockConsolidation(page: Page, scanning: boolean) {
  const calls = { previews: [] as string[], inFlight: 0, maxInFlight: 0, failCarlaOnce: true, runPolls: -1, previewTargets: [] as (string | null)[], runBody: null as unknown };
  const performers = [
    { relative_path: 'OnlyFans/A/alice_example', folders: [
      { root: '/mnt/UltimaDrive/DHS', path: '/mnt/UltimaDrive/DHS/OnlyFans/A/alice_example', priority: 1, files: 1204, bytes: 2_500_000_000 },
      { root: '/mnt/UltimaDrive2/DHS', path: '/mnt/UltimaDrive2/DHS/OnlyFans/A/alice_example', priority: 2, files: 88, bytes: 2_100_000_000 },
    ] },
    { relative_path: 'OnlyFans/B/bella_example', folders: [
      { root: '/mnt/UltimaDrive/DHS', path: '/x', priority: 1 },
      { root: '/mnt/UltimaDrive3/DHS', path: '/y', priority: 3 },
      { root: '/mnt/UltimaDrive2/DHS', path: '/z', priority: 2 },
    ] },
    { relative_path: 'OnlyFans/C/carla_example_with_a_rather_long_folder_name', folders: [
      { root: '/mnt/UltimaDrive/DHS', path: '/x', priority: 1 },
      // An empty copy: nothing to move.
      { root: '/mnt/UltimaDrive2/DHS', path: '/z', priority: 2, files: 0, bytes: 0 },
    ] },
  ];
  // Drive2 is nearly full: 3 GB free, 1 GB of it kept in reserve. Drive3 has 0.5 GB.
  const space: Record<string, { free_bytes: number; reserve_bytes: number }> = {
    '/mnt/UltimaDrive/DHS': { free_bytes: 50_000_000_000, reserve_bytes: 10_000_000_000 },
    '/mnt/UltimaDrive2/DHS': { free_bytes: 3_000_000_000, reserve_bytes: 1_000_000_000 },
    '/mnt/UltimaDrive3/DHS': { free_bytes: 500_000_000, reserve_bytes: 0 },
  };
  await page.route('**/api/v1/consolidation/split**', (route) => route.fulfill(json({
    site_name: 'OnlyFans', scanning, paused: false, roots_total: 4, roots_done: 1,
    current_root: scanning ? '/mnt/UltimaDrive2/DHS' : null, scanned_at: 1794600000, performers,
  })));
  await page.route('**/api/v1/consolidation/run', (route) => {
    calls.runPolls = 0;
    calls.runBody = route.request().postDataJSON();
    return route.fulfill(json({}));
  });
  await page.route('**/api/v1/consolidation/status', (route) => route.fulfill(json({
    // Once started, the run shows as running for two polls, then finished.
    running: calls.runPolls >= 0 && calls.runPolls++ < 2, total: 1, done: 0, current: 'OnlyFans/A/alice_example', finished_at: 1794500000, performers: [
      { relative_path: 'OnlyFans/D/dana_example', moved: 312, moved_bytes: 9_400_000_000, duplicates: 4, conflict_count: 1, conflicts: ['OnlyFans/D/dana_example/Posts/Images/a.jpg'], failed_count: 0 },
      { relative_path: 'OnlyFans/E/erin_example', error: 'Target drive ran out of space' },
    ],
  })));
  await page.route('**/api/v1/consolidation/preview', async (route) => {
    const { relative_path, target_root } = route.request().postDataJSON() as {
      relative_path: string;
      target_root: string | null;
    };
    calls.previewTargets.push(target_root);
    const performer = performers.find((p) => p.relative_path === relative_path)!;
    const folders = performer.folders.map((f) => ({
      ...f, files: f.files ?? 40, bytes: f.bytes ?? 900_000_000, ...space[f.root],
    }));
    calls.previews.push(relative_path);
    calls.inFlight += 1;
    calls.maxInFlight = Math.max(calls.maxInFlight, calls.inFlight);
    await new Promise((resolve) => setTimeout(resolve, 150));
    calls.inFlight -= 1;
    if (relative_path.includes('carla') && calls.failCarlaOnce) {
      calls.failCarlaOnce = false;
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Drive not mounted' }) });
      return;
    }
    // bella fits on no drive by itself; the others go to Drive unless one is chosen.
    const root = target_root ?? (relative_path.includes('bella') ? null : '/mnt/UltimaDrive/DHS');
    const total = folders.reduce((sum, f) => sum + f.bytes, 0);
    const needed = root ? total - folders.find((f) => f.root === root)!.bytes : 0;
    const fits = root !== null && needed <= space[root].free_bytes;
    await route.fulfill(json({
      relative_path, folders,
      target_root: fits ? root : null,
      reason: fits ? '' : 'short of space',
      needed_bytes: fits ? needed : 0,
      into_reserve: fits && needed > space[root].free_bytes - space[root].reserve_bytes,
      no_space: !fits,
      move_files: needed > 0 ? 88 : 0,
      move_bytes: needed, duplicates: 3, conflicts: ['x'], recent: 0, too_long: 0,
    }));
  });
  return calls;
}

for (const scanning of [false, true]) {
  test(`split performers tool ${scanning ? 'shows scan progress' : 'previews and selects performers'}`, async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);
    const calls = await mockConsolidation(page, scanning);
    await page.goto('/tools');
    await page.getByRole('button', { name: /Split Performers/ }).click();
    await expect(page.getByRole('heading', { name: 'Split Performers' })).toBeVisible();
    if (!scanning) {
      // Every performer is previewed on its own, one at a time; there is no Preview button.
      await expect(page.getByRole('button', { name: /^Preview/ })).toHaveCount(0);
      // Short of space everywhere is an error, in red.
      const bellaNote = page.getByRole('listitem').filter({ hasText: 'bella_example' }).first().locator('.split-row__plan[role="alert"]');
      await expect(bellaNote).toHaveText('Not enough free space on any drive holding this performer.');
      await expect(bellaNote).toHaveClass(/is-error/);
      const carla = page.getByRole('listitem').filter({ hasText: 'carla_example' });
      await expect(carla.getByText(/Preview failed/)).toBeVisible();
      await expect(page.getByText('Previewed').locator('..').getByText('2 / 3')).toBeVisible();
      expect(calls.maxInFlight).toBe(1);

      await carla.getByRole('button', { name: 'Retry' }).click();
      await expect(carla.getByText('TARGET')).toBeVisible();
      await expect(carla.getByRole('button', { name: 'Retry' })).toHaveCount(0);
      expect(calls.previews).toHaveLength(4);
      // Nothing to move with a valid target: ticked without being asked.
      const carlaTick = page.getByRole('checkbox', {
        name: 'Select OnlyFans/C/carla_example_with_a_rather_long_folder_name',
      });
      await expect(carlaTick).toBeChecked();
      // alice has 88 files to move, so she waits for a choice.
      await expect(page.getByRole('checkbox', { name: 'Select OnlyFans/A/alice_example' })).not.toBeChecked();
      await carlaTick.uncheck();

      await expect(page.getByRole('checkbox', { name: 'Select OnlyFans/B/bella_example' })).toBeDisabled();

      // Picking another drive previews against it and is sent with the run.
      const alice = page.getByRole('listitem').filter({ hasText: 'alice_example' }).first();

      // Clicking a drive's path copies the performer's full folder there, without choosing it.
      await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
      const folder = '/mnt/UltimaDrive2/DHS/OnlyFans/A/alice_example';
      const copyButton = alice.getByRole('button', { name: `Copy ${folder}` });
      const widthBefore = (await copyButton.boundingBox())!.width;
      await copyButton.click();
      await expect(copyButton).toHaveText(/Copied/);
      // The chip keeps its size, so nothing beside it shifts.
      expect((await copyButton.boundingBox())!.width).toBe(widthBefore);
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(folder);
      await expect(
        alice.getByRole('button', { name: 'Move OnlyFans/A/alice_example to /mnt/UltimaDrive2/DHS' }),
      ).toHaveAttribute('aria-pressed', 'false');

      // A valid chosen drive ticks the performer; going back to the best drive unticks it.
      const aliceTick = page.getByRole('checkbox', { name: 'Select OnlyFans/A/alice_example' });
      const drive2 = alice.getByRole('button', { name: 'Move OnlyFans/A/alice_example to /mnt/UltimaDrive2/DHS' });
      await drive2.click();
      await expect(drive2).toHaveAttribute('aria-pressed', 'true');
      await expect(drive2.getByText('chosen')).toBeVisible();
      await expect(aliceTick).toBeChecked();
      expect(calls.previewTargets.at(-1)).toBe('/mnt/UltimaDrive2/DHS');
      await alice.getByRole('button', { name: 'Use best drive' }).click();
      await expect(alice.getByRole('button', { name: /to \/mnt\/UltimaDrive\/DHS$/ }).getByText('target')).toBeVisible();
      await expect(aliceTick).not.toBeChecked();
      expect(calls.previewTargets.at(-1)).toBeNull();
      await drive2.click();
      await expect(drive2.getByText('chosen')).toBeVisible();
      await expect(aliceTick).toBeChecked();

      // 2.5 GB fits in Drive2's 3 GB only by using its reserve: a warning, in amber.
      const aliceWarning = alice.locator('.split-row__plan.is-warning');
      await expect(aliceWarning).toHaveText(/^Uses .+ of the .+ reserve on \/mnt\/UltimaDrive2\/DHS\.$/);
      const drive2Usage = page.getByRole('list', { name: 'Space on target drives' }).getByRole('listitem');
      await expect(drive2Usage).toHaveClass(/is-warning/);
      await expect(drive2Usage).toContainText('Uses some of its');

      // A chosen drive without the free space is refused, in red, and never ticked.
      const bella = page.getByRole('listitem').filter({ hasText: 'bella_example' }).first();
      const bellaTick = page.getByRole('checkbox', { name: 'Select OnlyFans/B/bella_example' });
      await bella.getByRole('button', { name: 'Move OnlyFans/B/bella_example to /mnt/UltimaDrive3/DHS' }).click();
      await expect(bellaNote).toHaveText(/^Not enough space on \/mnt\/UltimaDrive3\/DHS: needs .+, .+ free\.$/);
      await expect(bellaNote).toHaveClass(/is-error/);
      await expect(bellaTick).not.toBeChecked();

      // Drive2 takes bella alone, but not beside alice: it stays unticked, and can't be ticked.
      await bella.getByRole('button', { name: 'Move OnlyFans/B/bella_example to /mnt/UltimaDrive2/DHS' }).click();
      await expect(bellaNote).toHaveText(
        /^Not enough space on \/mnt\/UltimaDrive2\/DHS with the other ticked performers: needs .+, .+ left\.$/,
      );
      await expect(bellaNote).toHaveClass(/is-error/);
      await expect(bellaTick).not.toBeChecked();
      await expect(bellaTick).toBeDisabled();
      await bella.getByRole('button', { name: 'Use best drive' }).click();
      await expect(bellaNote).toHaveText('Not enough free space on any drive holding this performer.');
      await expect(page.getByRole('button', { name: 'Consolidate 1 selected' })).toBeEnabled();

      await page.locator('.split-results summary').click();
      await page.screenshot({ path: test.info().outputPath('split.png'), fullPage: true });

      // A finished run moved files, so every performer is previewed again.
      await page.getByRole('button', { name: 'Consolidate 1 selected' }).click();
      await expect(page.getByText('Consolidating 1 of 1')).toBeVisible();
      expect(calls.runBody).toMatchObject({
        relative_paths: ['OnlyFans/A/alice_example'],
        targets: { 'OnlyFans/A/alice_example': '/mnt/UltimaDrive2/DHS' },
      });
      await expect.poll(() => calls.previews.length, { timeout: 15_000 }).toBe(13);
      await expect(page.getByRole('checkbox', { name: 'Select OnlyFans/A/alice_example' })).not.toBeChecked();
      expect(calls.maxInFlight).toBe(1);
    } else {
      await expect(page.getByText('Scanning drive 2 of 4')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Pause scan' })).toBeVisible();
      await expect(page.getByText('Previews when the scan or run finishes.')).toHaveCount(3);
      expect(calls.previews).toHaveLength(0);
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
