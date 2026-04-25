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

function orderedStageExecutions(detail) {
  const stageDefinitions = detail.version?.definition_json?.stages || [];
  const stageOrder = new Map(stageDefinitions.map((stage, index) => [String(stage.stage_key || ''), index]));
  return [...(detail.stage_executions || [])].sort((left, right) => {
    const leftOrder = stageOrder.has(String(left.stage_key || ''))
      ? stageOrder.get(String(left.stage_key || ''))
      : Number.MAX_SAFE_INTEGER;
    const rightOrder = stageOrder.has(String(right.stage_key || ''))
      ? stageOrder.get(String(right.stage_key || ''))
      : Number.MAX_SAFE_INTEGER;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    const leftAttempt = Number(left.attempt || 0);
    const rightAttempt = Number(right.attempt || 0);
    if (leftAttempt !== rightAttempt) return leftAttempt - rightAttempt;
    return String(left.started_at || '').localeCompare(String(right.started_at || ''));
  });
}

test('main navigation swaps content immediately and keeps internal work queues out of default nav', async ({ page }) => {
  await login(page);

  await page.goto('/ui/approvals', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Approvals', exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Protocols', exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/protocols/);
  await expect(page.getByRole('heading', { name: 'Protocols', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Approvals', exact: true })).toHaveCount(0);

  await page.getByRole('link', { name: 'Runs', exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/runs/);
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Tasks', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Approvals', exact: true })).toHaveCount(0);
});

test('capabilities defaults to a human assignment catalog before bot management', async ({ page }) => {
  await login(page);
  await page.goto('/ui/skills');

  await expect(page.getByRole('heading', { name: 'Capabilities', exact: true })).toBeVisible();
  await expect(page.getByText('Capability catalog', { exact: true })).toBeVisible();
  await expect(page.getByText('Available capabilities', { exact: true })).toBeVisible();
  await expect(page.getByText('Architecture', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Meta Protocol Composer \d{10,}/)).toHaveCount(0);
  await expect(page.getByText('No connected bot advertises capability management.', { exact: true })).toHaveCount(0);
});

test('runs use inline expansion instead of the old split detail board', async ({ page }) => {
  await login(page);
  const { id, detail } = await findRunWithLineage(page);
  await page.goto(`/ui/runs?run_id=${id}`);
  await expect(page.locator('.protocol-runs-workbench')).toHaveCount(1);
  await expect(page.locator('.dashboard-board[data-route="protocol-runs"]')).toHaveCount(0);
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);
  await expect(page.getByRole('tablist', { name: 'Run evidence section' })).toHaveCount(1);
  await expect(page.locator('.protocol-lineage-card')).toHaveCount(1);

  const sectionTabs = page.getByRole('tablist', { name: 'Run evidence section' }).getByRole('tab');
  await expect(sectionTabs).toHaveCount(4);
  await sectionTabs.filter({ hasText: 'Stages' }).click();
  await expect(page.getByRole('tablist', { name: 'Execution stage' })).toHaveCount(0);
  await expect(page.getByRole('tablist', { name: 'Run stage evidence' })).toHaveCount(1);
  await expect(page.locator('.protocol-lineage-card')).toHaveCount(1);

  const orderedStages = orderedStageExecutions(detail);
  const stageDefinitions = new Map(
    (detail.version?.definition_json?.stages || []).map((stage) => [String(stage.stage_key || ''), stage]),
  );
  const firstStage = orderedStages[0] || {};
  const lastStage = orderedStages[orderedStages.length - 1] || {};
  const firstDefinition = stageDefinitions.get(String(firstStage.stage_key || '')) || {};
  const lastDefinition = stageDefinitions.get(String(lastStage.stage_key || '')) || {};
  const stageTabs = page.getByRole('tablist', { name: 'Run stage evidence' }).getByRole('tab');
  await expect(stageTabs).toHaveCount(detail.stage_executions.length);
  await stageTabs.first().click();
  await expect(page.locator('.protocol-lineage-title').first()).toContainText(firstDefinition.display_name || firstStage.stage_key || '');
  await stageTabs.last().click();
  await expect(page.locator('.protocol-lineage-title').first()).toContainText(lastDefinition.display_name || lastStage.stage_key || '');

  await sectionTabs.filter({ hasText: 'Artifacts' }).click();
  await expect(page.locator('.artifact-list-row').first()).toBeVisible();
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
  const participant = (detail.participants || []).find((item) =>
    item.resolution_outcome && String(item.resolution_outcome || '') !== String(item.state || 'queued'));
  test.skip(!participant, 'Need a run participant whose resolved outcome differs from raw state.');

  await page.goto(`/ui/runs?run_id=${id}`);
  const sectionTabs = page.getByRole('tablist', { name: 'Run evidence section' }).getByRole('tab');
  await sectionTabs.filter({ hasText: 'Audit' }).click();
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
