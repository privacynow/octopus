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

async function findRunWithLineage(page) {
  const listResponse = await page.request.get('/v1/protocol-runs?limit=50');
  expect(listResponse.ok()).toBeTruthy();
  const payload = await listResponse.json();
  const runs = Array.isArray(payload?.runs) ? payload.runs : (Array.isArray(payload) ? payload : []);

  for (const run of runs) {
    const runId = run.protocol_run_id || run.id;
    if (!runId) continue;
    const detailResponse = await page.request.get(`/v1/protocol-runs/${runId}`);
    if (!detailResponse.ok()) continue;
    const detail = await detailResponse.json();
    if ((detail.stage_executions || []).length > 1) {
      return { id: runId, detail };
    }
  }

  throw new Error('Expected at least one protocol run with multiple stage executions.');
}

function statusLabel(status) {
  return String(status || '').replace(/^\w/, (char) => char.toUpperCase());
}

test('runs use inline expansion instead of the old split detail board', async ({ page }) => {
  await login(page);
  const { id, detail } = await findRunWithLineage(page);
  await page.goto(`/ui/runs?run_id=${id}`);
  await expect(page.locator('.protocol-runs-workbench')).toHaveCount(1);
  await expect(page.locator('.dashboard-board[data-route="protocol-runs"]')).toHaveCount(0);
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);
  await expect(page.getByRole('tablist', { name: 'Run detail section' })).toHaveCount(1);
  await expect(page.locator('.protocol-lineage-card')).toHaveCount(0);

  const sectionTabs = page.getByRole('tablist', { name: 'Run detail section' }).getByRole('tab');
  await expect(sectionTabs).toHaveCount(5);
  await sectionTabs.filter({ hasText: 'Execution' }).click();
  await expect(page.locator('.protocol-lineage-card')).toHaveCount(1);

  const stageTabs = page.getByRole('tablist', { name: 'Execution stage' }).getByRole('tab');
  await expect(stageTabs).toHaveCount(detail.stage_executions.length);
  const targetStage = detail.stage_executions[1];
  const stageDefinitions = new Map(
    (detail.version?.definition_json?.stages || []).map((stage) => [String(stage.stage_key || ''), stage]),
  );
  const targetDefinition = stageDefinitions.get(String(targetStage.stage_key || '')) || {};
  await stageTabs.nth(1).click();
  await expect(stageTabs.nth(1)).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.protocol-lineage-title')).toHaveText(
    `${targetDefinition.display_name || targetStage.stage_key || 'Stage'} · ${targetStage.status}`,
  );
  await expect(page.locator('.kit-runs-list-row[aria-expanded="true"]')).toHaveCount(1);
  await page.locator('.kit-runs-list-row[aria-expanded="true"]').click();
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(0);
  expect(page.url()).not.toContain('run_id=');

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/runs-desktop.png', fullPage: false });
});

test('runs clear stale selection when the status filter changes', async ({ page }) => {
  await login(page);
  const listResponse = await page.request.get('/v1/protocol-runs?limit=50');
  expect(listResponse.ok()).toBeTruthy();
  const payload = await listResponse.json();
  const runs = Array.isArray(payload?.runs) ? payload.runs : [];
  const selected = runs.find((run) => run.protocol_run_id && run.status);
  expect(selected).toBeTruthy();
  const target = runs.find((run) => run.protocol_run_id && run.status && run.status !== selected.status);
  test.skip(!target, 'Need at least two run statuses to verify stale selection clearing.');

  await page.goto(`/ui/runs?run_id=${selected.protocol_run_id}`);
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);
  await page.locator('.kit-runs-filter-chip').filter({ hasText: statusLabel(target.status) }).click();
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('run_id')).toBeFalsy();
  expect(new URL(page.url()).searchParams.get('status')).toBe(target.status);

  await page.locator('.kit-runs-list-row').first().click();
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);
  await expect(page.locator('.kit-runs-list-row[aria-expanded="true"]')).toHaveCount(1);
  expect(new URL(page.url()).searchParams.get('run_id')).toBeTruthy();
});

test('run participants prefer resolved outcomes over raw running state', async ({ page }) => {
  await login(page);
  const { id, detail } = await findRunWithLineage(page);
  const participant = (detail.participants || []).find((item) => item.resolution_outcome);
  test.skip(!participant, 'Need a run participant with a resolved outcome.');

  await page.goto(`/ui/runs?run_id=${id}`);
  const sectionTabs = page.getByRole('tablist', { name: 'Run detail section' }).getByRole('tab');
  await sectionTabs.filter({ hasText: 'Participants' }).click();
  const displayName = participant.display_name || participant.participant_key;
  await expect(page.getByText(`${displayName} · ${participant.resolution_outcome}`)).toBeVisible();
  await expect(page.getByText(`${displayName} · ${participant.state || 'running'}`)).toHaveCount(0);
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
  await expect(rows.first()).toHaveAttribute('aria-expanded', 'true');
  await rows.first().click();
  await expect(page.locator('.conversation-inline-detail')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('conversation_id')).toBeFalsy();

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/conversations-inline-desktop.png', fullPage: false });
});

test('tasks keep one inline detail open at a time', async ({ page }) => {
  await login(page);
  await page.goto('/ui/tasks');
  const rows = page.locator('.task-item-row');
  await expect(rows.first()).toBeVisible();
  const rowCount = await rows.count();
  test.skip(rowCount < 2, 'Need at least two tasks to verify single-detail expansion.');

  await rows.nth(0).click();
  await expect(rows.nth(0)).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.task-item-row[aria-expanded="true"]')).toHaveCount(1);

  await rows.nth(1).click();
  await expect(rows.nth(0)).toHaveAttribute('aria-expanded', 'false');
  await expect(rows.nth(1)).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.task-item-row[aria-expanded="true"]')).toHaveCount(1);

  await rows.nth(1).click();
  await expect(page.locator('.task-item-row[aria-expanded="true"]')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('task_id')).toBeFalsy();
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
