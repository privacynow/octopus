const { test, expect } = require('@playwright/test');
const fs = require('fs');

function registryUiToken() {
  const direct = String(process.env.REGISTRY_UI_TOKEN || '').trim();
  if (direct) return direct;
  const envPath = '/Users/tinker/octopus/.deploy/registry/.env';
  const text = fs.readFileSync(envPath, 'utf8');
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith('REGISTRY_UI_TOKEN=')) {
      return line.slice('REGISTRY_UI_TOKEN='.length).trim();
    }
  }
  return '';
}

async function login(page) {
  const password = registryUiToken();
  if (!password) {
    throw new Error('REGISTRY_UI_TOKEN is required for live UI login tests');
  }
  await page.goto('/ui/login', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(/\/ui\/?$/);
}

test.describe('protocol routes live', () => {
  test('dashboard protocol links land on the correct owner routes', async ({ page }) => {
    await login(page);
    await page.goto('/ui/', { waitUntil: 'domcontentloaded' });

    await page.getByRole('link', { name: 'Published protocols' }).click();
    await page.waitForURL(/\/ui\/protocols(\?.*)?$/);
    await expect(page.getByRole('heading', { name: 'Protocols' })).toBeVisible();

    await page.goto('/ui/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('link', { name: 'Active protocol runs' }).click();
    await page.waitForURL(/\/ui\/protocol-runs(\?.*)?$/);
    await expect(page.getByRole('heading', { name: 'Protocol runs' })).toBeVisible();
  });

  test('protocols nav opens authoring only and runs live on their own route', async ({ page }) => {
    const consoleErrors = [];
    const pageErrors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => {
      pageErrors.push(String(err));
    });

    await login(page);
    await page.getByRole('link', { name: 'Protocols' }).click();
    await page.waitForURL(/\/ui\/protocols(\?.*)?$/);

    await expect(page.getByRole('heading', { name: 'Protocols' })).toBeVisible();
    await expect(page.getByText('Run launcher')).toHaveCount(0);
    await expect(page.getByText(/^Protocol runs$/)).toHaveCount(0);
    await expect(page.getByText(/^Protocol issues$/)).toHaveCount(0);

    await page.getByRole('button', { name: 'New protocol' }).click();
    await expect(page.getByText('Blank protocol')).toBeVisible();
    await expect(page.getByText('Import JSON or YAML')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start blank' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use template' }).first()).toBeVisible();

    await page.getByRole('button', { name: 'Start blank' }).click();
    await expect(page.getByText('Workflow summary')).toBeVisible();
    await expect(page.getByText('Protocol basics')).toBeVisible();
    await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);
    await expect(page.getByText('Advanced raw editor')).toHaveCount(0);

    const authorColumns = page.locator('.protocol-author-board > .dashboard-column');
    const listBox = await authorColumns.nth(0).boundingBox();
    const editorBox = await authorColumns.nth(1).boundingBox();
    expect(listBox).toBeTruthy();
    expect(editorBox).toBeTruthy();
    expect(editorBox.y).toBeGreaterThan(listBox.y);

    await page.getByRole('tab', { name: /^Advanced$/ }).click();
    await expect(page.getByText('Advanced raw editor')).toBeVisible();

    await page.getByRole('button', { name: 'Discard draft' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByText('Blank protocol')).toBeVisible();
    await expect(page).toHaveURL(/\/ui\/protocols(\?.*)?$/);

    const protocolRow = page.getByRole('button', { name: /software engineering/i }).first();
    await expect(protocolRow).toBeVisible();
    await protocolRow.click();
    await expect(protocolRow).toHaveClass(/is-selected/);
    await expect(page.getByText('Workflow summary')).toBeVisible();
    await expect(page.getByText('Workflow map')).toBeVisible();
    await expect(page.getByText('Stage details')).toHaveCount(0);
    await expect(page.getByText('Advanced raw editor')).toHaveCount(0);

    await page.getByRole('tab', { name: /^Stages/ }).click();
    await expect(page.getByText('Workflow stages')).toBeVisible();
    await expect(page.getByText('Stage details')).toBeVisible();
    await page.getByRole('button', { name: /Planning/ }).first().click();
    await expect(page.getByText('Stage details')).toBeVisible();

    await page.goto('/ui/protocol-runs', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Protocol runs' })).toBeVisible();
    await expect(page.locator('.editor-section-title').filter({ hasText: /^Runs$/ }).first()).toBeVisible();
    await expect(page.locator('.editor-section-title').filter({ hasText: /^Run detail$/ }).first()).toBeVisible();
    await expect(page.getByText('Structured editor')).toHaveCount(0);

    const runRows = page.locator('.protocol-panel .list-row').first();
    if (await runRows.count()) {
      await runRows.click();
      await expect(page).toHaveURL(/\/ui\/protocol-runs\?run_id=/);
    }

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });
});
