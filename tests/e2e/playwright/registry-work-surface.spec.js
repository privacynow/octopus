const { test, expect } = require('./playwright-runtime');
const { login } = require('./helpers/protocol-helpers');

test.use({ viewport: { width: 1600, height: 950 } });

async function layoutMetrics(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
    };
  });
}

test('runs use inline expansion instead of the old split detail board', async ({ page }) => {
  await login(page);
  await page.goto('/ui/runs?run_id=5df4889fba7b4aa487b7952f76844ccd');
  await expect(page.locator('.protocol-runs-workbench')).toHaveCount(1);
  await expect(page.locator('.dashboard-board[data-route="protocol-runs"]')).toHaveCount(0);
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/runs-desktop.png', fullPage: false });
});

test('conversation list exposes inline context before opening the full workspace', async ({ page }) => {
  await login(page);
  await page.goto('/ui/conversations');
  await expect(page.locator('.conversation-list-route-shell')).toHaveCount(1);
  const rows = page.locator('.conversation-list-entry .list-row');
  await expect(rows.first()).toBeVisible();
  await rows.first().click();
  await expect(page.locator('.conversation-inline-detail')).toHaveCount(1);
  await expect(page.getByText('Linked runs')).toBeVisible();

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/conversations-inline-desktop.png', fullPage: false });
});

test('conversation detail keeps the workspace viewport bounded', async ({ page }) => {
  await login(page);
  await page.goto('/ui/conversations/ed29524b7a177caf34417638bc0ad3c3?view=tasks');
  await expect(page.locator('.conversation-page')).toHaveCount(1);
  await expect(page.locator('.conversation-panel')).toHaveCount(1);

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/conversation-detail-desktop.png', fullPage: false });
});
