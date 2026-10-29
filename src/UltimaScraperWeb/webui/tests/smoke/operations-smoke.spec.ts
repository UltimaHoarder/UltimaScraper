import { expect, test, type Page } from '@playwright/test';

import { installApiMocks, seedConfiguredApp } from './helpers';

async function openChatThread(page: Page) {
  const mobileOpenChatsButton = page.getByRole('button', { name: /Open chats/i });
  if (await mobileOpenChatsButton.isVisible().catch(() => false)) {
    await mobileOpenChatsButton.click();
  }

  const chatItem = page.locator('.chat-item').first();
  await expect(chatItem).toBeVisible();
  await chatItem.click();
}

test.describe('operational smoke flows', () => {
  test('operates the jobs queue through the Operations ledger', async ({ page }, testInfo) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/jobs');
    await expect(page.getByRole('heading', { name: 'Operations ledger' })).toBeVisible();
    await expect(page.getByRole('table', { name: 'Jobs operations ledger' })).toBeVisible();
    await expect(page.getByText('Running Smoke Job')).toBeVisible();
    await expect(page.getByText('Failed Smoke Job')).toBeVisible();

    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('operations-ledger.png'), fullPage: true });
    }

    await page.getByRole('button', { name: 'Columns 14' }).click();
    await page.getByRole('group', { name: 'Visible columns' }).getByLabel('Owner').uncheck();
    await expect(page.getByRole('columnheader', { name: 'Owner' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Columns 13' }).click();

    await page.getByRole('checkbox', { name: 'Select Failed Smoke Job' }).check();
    await page.getByRole('button', { name: 'Retry failed (1)' }).click();
    await expect(page.getByText('1 retry queued.')).toBeVisible();

    await page.getByRole('button', { name: /New job/i }).click();
    await expect(page.getByText('Job builder', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Back to ledger' }).click();
    await expect(page.getByRole('heading', { name: 'Operations ledger' })).toBeVisible();
  });

  test('browses orders and confirms order deletion', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/orders');
    // The page header; the orders table has its own "Orders" heading.
    await expect(page.getByRole('heading', { name: 'Orders', exact: true }).first()).toBeVisible();

    const orderRow = page.locator('.orders-row').first();
    await expect(orderRow).toBeVisible();
    await orderRow.focus();
    await orderRow.press('Enter');
    await expect(page.getByRole('button', { name: 'Delete Order' })).toBeVisible();

    const deleteOrderButton = page.getByRole('button', { name: 'Delete Order' });
    await deleteOrderButton.focus();
    await deleteOrderButton.press('Enter');
    await expect(page.getByText('Delete order?')).toBeVisible();
    await page.locator('.confirm-dialog').getByRole('button', { name: 'Delete order' }).click();

    await expect(page.getByText('Order deleted')).toBeVisible();
    await expect(page.getByText('No matching orders')).toBeVisible();
  });

  test('opens chats, sends a message, and confirms PPV unlock flow', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/chats');
    await expect(page.getByRole('heading', { name: 'Chats', exact: true })).toBeVisible();

    await openChatThread(page);
    await expect(page.locator('.header-username')).toHaveText('@alice');

    const messageInput = page.getByPlaceholder('Type a message...');
    await messageInput.fill('Smoke test reply');
    await messageInput.press('Enter');
    await expect(page.getByText('Smoke test reply')).toBeVisible();

    await page.getByRole('button', { name: /UNLOCK FOR \$5\.00/i }).click();
    await expect(page.getByText('Unlock PPV')).toBeVisible();
    await page.getByRole('button', { name: 'Buy' }).click();
    await expect(page.getByText('Unlock PPV')).not.toBeVisible();
  });

  test('runs proxy analyzer basics', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/network');
    await expect(page.getByRole('heading', { name: 'Network', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Analyze baseline' }).click();
    await page.getByRole('button', { name: /Start Analysis/i }).click();
    await expect(page.getByText(/Analysis complete!/)).toBeVisible();
    await page.getByRole('button', { name: 'Apply recommendation' }).click();
    await expect(page.getByText(/Updated Network \(direct\)|Updated http:\/\/proxy1\.example:8080/)).toBeVisible();
  });

  test('bulk-edits connection capacity across selected proxies', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/network');
    await expect(page.getByRole('heading', { name: 'Network', exact: true })).toBeVisible();

    const secondProxyCard = page.locator('.network-proxy').filter({ hasText: 'http://proxy2.example:8080' });
    await secondProxyCard.getByRole('button', { name: 'Test' }).click();
    await expect(secondProxyCard.getByText('London, England, United Kingdom')).toBeVisible();

    await page.getByRole('checkbox', { name: 'Select proxy http://proxy1.example:8080' }).check();
    await page.getByRole('checkbox', { name: 'Select proxy http://proxy2.example:8080' }).check();
    await expect(page.getByRole('toolbar', { name: 'Floating selection actions' })).toBeVisible();
    await page.getByRole('button', { name: '⚡ TEST (2)' }).first().click();
    await expect(page.getByText('Bulk Connectivity Test Complete')).toBeVisible();
    await page.getByRole('button', { name: 'EDIT CONNECTIONS (2)' }).first().click();

    await expect(page.getByRole('heading', { name: 'Edit Connections — 2 Proxies' })).toBeVisible();
    await page.getByPlaceholder(/Mixed values/).fill('64');
    await page.getByRole('button', { name: 'Apply to 2 Proxies' }).click();

    await expect(page.getByText('Bulk Edit Applied')).toBeVisible();
    await expect(page.getByText('Updated max_connections=64 on 2 proxies')).toBeVisible();
  });
});
