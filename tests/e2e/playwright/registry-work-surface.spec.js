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

async function expectDetailBelowRow(row, detail) {
  const rowBox = await row.boundingBox();
  const detailBox = await detail.boundingBox();
  expect(rowBox).toBeTruthy();
  expect(detailBox).toBeTruthy();
  expect(detailBox.y).toBeGreaterThan(rowBox.y + rowBox.height - 2);
  expect(Math.abs(detailBox.x - rowBox.x)).toBeLessThan(4);
  expect(detailBox.width).toBeGreaterThan(rowBox.width * 0.9);
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

function routedTaskIdFromConversation(conversation) {
  const externalRef = String(conversation?.external_conversation_ref || '').trim();
  return String(conversation?.conversation_type || '') === 'task_thread' && externalRef.startsWith('routed-task:')
    ? externalRef.slice('routed-task:'.length).trim()
    : '';
}

async function findTaskThreadWithProtocolRun(page) {
  const listResponse = await page.request.get('/v1/conversations?type=task_thread&include_generated=1&limit=100');
  expect(listResponse.ok()).toBeTruthy();
  const payload = await listResponse.json();
  const conversations = Array.isArray(payload?.conversations) ? payload.conversations : (Array.isArray(payload) ? payload : []);

  for (const conversation of conversations) {
    const taskId = routedTaskIdFromConversation(conversation);
    if (!taskId) continue;
    const taskResponse = await page.request.get(`/v1/tasks/${encodeURIComponent(taskId)}`);
    if (!taskResponse.ok()) continue;
    const task = await taskResponse.json();
    const runId = String(task?.protocol_run_id || '').trim();
    if (runId) {
      return { conversation, task, runId };
    }
  }

  return null;
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
  await expect(page.locator('.nav-group')).toHaveText(['Work', 'Build', 'Operations']);
  await expect(page.getByRole('link', { name: 'Agents', exact: true })).toBeVisible();
  await expect(page.locator('.nav-links').getByText('Team', { exact: true })).toHaveCount(0);

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

test('generated visibility controls use an obvious shared filter toggle', async ({ page }) => {
  await login(page);

  const routes = [
    ['/ui/conversations', 'Show generated/audit work', 'Generated/audit: hidden'],
    ['/ui/agents', 'Show generated/audit agents', 'Generated/audit: hidden'],
    ['/ui/runs', 'Show generated/audit runs', 'Generated/audit: hidden'],
    ['/ui/usage', 'Show generated/audit usage', 'Generated/audit: hidden'],
    ['/ui/protocols', 'Show generated drafts', 'Generated drafts: hidden'],
  ];

  for (const [route, accessibleName, visibleLabel] of routes) {
    await page.goto(route);
    const toggle = page.getByRole('button', { name: accessibleName, exact: true });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveClass(/filter-toggle-link/);
    await expect(toggle).toHaveText(visibleLabel);
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    const box = await toggle.boundingBox();
    expect(box?.width || 0).toBeGreaterThan(0);
    expect(box?.width || 0).toBeLessThan(360);
  }
});

test('skills defaults to a human assignment catalog before bot management', async ({ page }) => {
  await login(page);
  await page.goto('/ui/skills');

  await expect(page.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible();
  await expect(page.getByText('Skill catalog', { exact: true })).toBeVisible();
  await expect(page.getByText('Available skills', { exact: true })).toBeVisible();
  await expect(page.getByText('Architecture', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('*', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Rehearsal', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Meta Protocol Composer \d{10,}/)).toHaveCount(0);
  await expect(page.getByText('No connected bot advertises skill management.', { exact: true })).toHaveCount(0);

  const architectureRow = page.locator('.list-row').filter({ hasText: 'Architecture' }).first();
  await expect(architectureRow).toBeVisible();
  await architectureRow.click();
  await expect(architectureRow).toHaveClass(/is-selected/);
  await expect(architectureRow).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.dashboard-board-stacked')).toHaveCount(1);
  await expect(page.locator('.editor-shell')).toBeHidden();
  await expect(page.locator('.skill-inline-detail')).toHaveCount(1);
  await expectDetailBelowRow(architectureRow, page.locator('.skill-inline-detail').first());
  await expect(page.getByRole('heading', { name: 'Architecture', exact: true })).toBeVisible();
  await expect(page.getByText('Assignment slug')).toBeVisible();
  await expect(page.getByText('Instructions preview')).toBeVisible();
  await expect(page.getByText('Use this in a protocol stage by choosing Assignment, then Existing skill.')).toBeVisible();
  await architectureRow.click();
  await expect(page.locator('.skill-inline-detail')).toHaveCount(0);
});

test('agents use inline details and share the skills workspace', async ({ page }) => {
  await login(page);
  await page.goto('/ui/agents');

  await expect(page.getByRole('heading', { name: 'Agents', exact: true })).toBeVisible();
  const agentRow = page.locator('.kit-agents-list-row').filter({ hasText: 'M1' }).first();
  await expect(agentRow).toBeVisible();
  await expect(agentRow.getByRole('button', { name: 'Details', exact: true })).toBeVisible();

  await agentRow.getByRole('button', { name: 'Details', exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/agents\?agent_id=/);
  await expect(agentRow).toHaveClass(/is-selected/);
  await expect(agentRow).toHaveAttribute('aria-expanded', 'true');
  await expect(agentRow.locator('.agent-inline-detail')).toHaveCount(1);
  await expect(agentRow.locator('.agent-inline-detail')).toContainText('Open agent workspace');
  await expect(agentRow.locator('.agent-inline-detail')).toContainText('Open skills');

  const agentWorkspaceHref = await agentRow.getByRole('link', { name: 'Open agent workspace', exact: true }).getAttribute('href');
  expect(agentWorkspaceHref).toMatch(/\/ui\/agents\//);
  await agentRow.getByRole('button', { name: 'Hide details', exact: true }).click();
  await expect(page.locator('.agent-inline-detail')).toHaveCount(0);

  await page.goto(agentWorkspaceHref);
  await expect(page.getByRole('heading', { name: 'M1', exact: true })).toBeVisible();
  await expect(page.locator('.skills-drawer-dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Open Skills workspace', exact: true }).click();
  await expect(page).toHaveURL(/\/ui\/skills\?agent_id=/);
  await expect(page.locator('.skills-drawer-dialog')).toHaveCount(0);
  await expect(page.locator('.dashboard-board-stacked')).toHaveCount(1);
  await expect(page.locator('.editor-shell')).toBeHidden();

  const architectureSkill = page.locator('.list-row').filter({ hasText: 'Architecture' }).first();
  await architectureSkill.click();
  await expect(architectureSkill).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.skill-inline-detail')).toHaveCount(1);
  await expectDetailBelowRow(architectureSkill, page.locator('.skill-inline-detail').first());
  await expect(page.getByText('Instructions preview')).toBeVisible();
  await architectureSkill.click();
  await expect(page.locator('.skill-inline-detail')).toHaveCount(0);
});

test('runs use inline expansion instead of the old split detail board', async ({ page }) => {
  await login(page);
  const { id, detail } = await findRunWithLineage(page);
  await page.goto(`/ui/runs?run_id=${id}`);
  await expect(page.locator('.protocol-runs-workbench')).toHaveCount(1);
  await expect(page.locator('.dashboard-board[data-route="protocol-runs"]')).toHaveCount(0);
  await expect(page.locator('.kit-runs-inline-detail')).toHaveCount(1);
  await expect(page.locator('.protocol-runs-workbench .pagination')).toHaveCount(0);
  await expect(page.getByRole('tablist', { name: 'Run evidence section' })).toHaveCount(1);
  await expect(page.locator('.protocol-lineage-card')).toHaveCount(0);
  await expect(page.getByText(/^Current step:/)).toBeVisible();
  await expect(page.getByText(/Open Stages for task, decision, and output evidence/)).toBeVisible();
  await expect(page.getByText(/output[s]? available/)).toBeVisible();

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
  await expect(page.getByRole('tablist', { name: 'Run artifact stage evidence' })).toHaveCount(1);
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

  await page.goto(`/ui/runs?run_id=${selected.protocol_run_id}&include_generated=1`);
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
  const linked = await findTaskThreadWithProtocolRun(page);
  await page.goto(linked
    ? `/ui/conversations?type=task_thread&include_generated=1&conversation_id=${encodeURIComponent(linked.conversation.conversation_id)}`
    : '/ui/conversations?type=task_thread&include_generated=1');
  await expect(page.locator('.conversation-list-route-shell')).toHaveCount(1);
  const rows = page.locator('.conversation-list-entry .list-row');
  await expect(rows.first()).toBeVisible();
  const targetRow = linked
    ? rows.filter({ hasText: String(linked.conversation.title || linked.task.title || '').trim() }).first()
    : rows.first();
  if (!linked) {
    await targetRow.click();
  }
  await expect(page.locator('.conversation-inline-detail')).toHaveCount(1);
  await expect(page.getByText('Linked runs')).toBeVisible();
  if (linked) {
    await expect(page.getByRole('link', { name: new RegExp(linked.runId.slice(0, 8)) })).toBeVisible();
  }
  await expect(targetRow).toHaveAttribute('aria-expanded', 'true');
  await targetRow.click();
  await expect(page.locator('.conversation-inline-detail')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('conversation_id')).toBeFalsy();

  const metrics = await layoutMetrics(page);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
  await page.screenshot({ path: '.tmp/visual-registry/conversations-inline-desktop.png', fullPage: false });
});

test('conversation pagination is visible and addressable', async ({ page }) => {
  await login(page);
  const listResponse = await page.request.get('/v1/conversations?limit=26');
  expect(listResponse.ok()).toBeTruthy();
  const payload = await listResponse.json();
  test.skip(!payload.has_more, 'Need more than one page of conversations to verify pagination.');

  await page.goto('/ui/conversations?include_generated=1');
  const pagination = page.locator('.conversation-list-route-shell .pagination');
  await expect(pagination).toBeVisible();
  await expect(pagination).toContainText('Page 1');

  await pagination.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(pagination).toContainText('Page 2');
  expect(Number(new URL(page.url()).searchParams.get('cursor'))).toBeGreaterThan(0);
  await expect(pagination.getByRole('button', { name: 'Previous', exact: true })).toBeEnabled();

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('.conversation-list-route-shell .pagination')).toContainText('Page 2');
  await page.locator('.conversation-list-route-shell .pagination').getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(page.locator('.conversation-list-route-shell .pagination')).toContainText('Page 1');
  expect(new URL(page.url()).searchParams.get('cursor')).toBeFalsy();
});

test('tasks keep one inline detail open at a time', async ({ page }) => {
  await login(page);
  const { id } = await findRunWithLineage(page);
  await page.goto(`/ui/tasks?protocol_run_id=${encodeURIComponent(id)}`);
  const rows = page.locator('.task-item-row');
  const rowCount = await rows.count();
  test.skip(rowCount < 2, 'Need at least two tasks to verify single-detail expansion.');
  await expect(rows.first()).toBeVisible();

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
