const { test, expect } = require('./playwright-runtime');
const { attachErrorCapture, login } = require('./helpers/protocol-helpers');

test.use({ viewport: { width: 1440, height: 900 } });

async function firstRunId(page) {
  const response = await page.request.get('/v1/protocol-runs?limit=50');
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const runs = Array.isArray(payload?.runs) ? payload.runs : (Array.isArray(payload) ? payload : []);
  const run = runs.find((item) => String(item?.protocol_run_id || item?.id || '').trim());
  if (!run) {
    throw new Error('Expected at least one protocol run for the Auto Protocol improve dialog check.');
  }
  return String(run.protocol_run_id || run.id);
}

function mockSession(index, overrides = {}) {
  const now = new Date(Date.UTC(2026, 6, 7, 12, index, 0)).toISOString();
  const sessionId = `session-${String(index).padStart(2, '0')}`;
  return {
    session_id: sessionId,
    status: 'ready',
    mode: index % 2 ? 'create' : 'revise',
    requirement_text: `Mock design ${index}`,
    target_protocol_id: `protocol-${index}`,
    planner_policy: index % 2 ? 'auto_select' : 'specific_agent',
    planner_task_id: `auto-task-${index}`,
    updated_at: now,
    draft_definition_json: {
      metadata: { auto_protocol: { primary_artifact: { artifact_key: 'package' } } },
      stages: [{ stage_key: 'produce_outcome', display_name: 'Produce outcome' }],
    },
    plan: {
      protocol_name: `Mock Auto Design ${index}`,
      stages: [{ stage_key: 'produce_outcome', display_name: 'Produce outcome', stage_kind: 'work' }],
      artifacts: [{ artifact_key: 'package', display_name: 'Package' }],
      primary_artifact: { artifact_key: 'package', display_name: 'Package' },
    },
    analysis: {
      goal: `Mock planner goal ${index}`,
      work_packages: [{ package_key: 'package', display_name: 'Package', rationale: 'Build the outcome.' }],
    },
    validation: { ok: true },
    unresolved_decisions: [],
    warnings: [],
    planner_state: {
      planner_status: 'completed',
      selected_agent_display_name: index % 2 ? 'M1' : 'M2',
      queued_at: now,
      started_at: now,
      last_progress_at: now,
      progress_summary: `Completed design ${index}`,
      queue_position: 0,
    },
    ...overrides,
  };
}

async function mockAutoProtocolSessions(page) {
  const sessions = Array.from({ length: 25 }, (_value, index) => mockSession(index));
  sessions[2] = mockSession(2, {
    status: 'planning',
    requirement_text: 'Active queue design',
    plan: { protocol_name: 'Active Queue Design' },
    draft_definition_json: {},
    validation: { ok: false },
    planner_state: {
      planner_status: 'running',
      selected_agent_display_name: 'M2',
      queued_at: '2026-07-07T12:00:00Z',
      started_at: '2026-07-07T12:01:00Z',
      last_progress_at: '2026-07-07T12:02:00Z',
      timeout_at: '2026-07-07T14:00:00Z',
      progress_summary: 'Analyzing product goals and verification scope.',
      queue_position: 1,
    },
  });
  const byId = new Map(sessions.map((session) => [session.session_id, session]));

  await page.route('**/v1/protocol-auto/sessions**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (payload, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });

    if (path === '/v1/protocol-auto/sessions') {
      const limit = Math.max(1, Number(url.searchParams.get('limit') || 24));
      const cursor = Math.max(0, Number(url.searchParams.get('cursor') || 0));
      const statusFilter = String(url.searchParams.get('status') || '').trim();
      const filtered = statusFilter
        ? sessions.filter((session) => String(session.status || '') === statusFilter)
        : sessions;
      const pageItems = filtered.slice(cursor, cursor + limit);
      const nextCursor = cursor + limit < filtered.length ? cursor + limit : null;
      await json({ items: pageItems, next_cursor: nextCursor });
      return;
    }

    const parts = path.split('/').filter(Boolean);
    const sessionId = decodeURIComponent(parts[parts.indexOf('sessions') + 1] || '');
    if (path.endsWith('/events')) {
      await json({
        items: [
          {
            event_id: `event-${sessionId}`,
            event_kind: 'planner_progress',
            created_at: '2026-07-07T12:02:00Z',
            actor_ref: 'M2',
          },
        ],
      });
      return;
    }

    const session = byId.get(sessionId);
    if (!session) {
      await json({ detail: { message: 'Not found', error_code: 'NOT_FOUND' } }, 404);
      return;
    }
    await json(session);
  });
}

test('improve-run dialog opens and unavailable actions are not actionable', async ({ page }) => {
  await login(page);
  const runId = await firstRunId(page);
  await page.goto(`/ui/runs?run_id=${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded' });

  const capture = attachErrorCapture(page);
  await expect(page.getByRole('button', { name: 'Improve this run', exact: true })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Improve this run', exact: true }).click();

  const dialog = page.locator('.confirm-dialog.protocol-auto-modal').filter({ hasText: 'Improve this run' }).first();
  await expect(dialog).toBeVisible({ timeout: 15000 });
  await expect(dialog.getByText('Candidate lessons from this run')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Generate improvement', exact: true })).toBeVisible();

  const unavailableActions = ['Apply draft', 'Publish', 'Publish & Run', 'View in queue'];
  for (const label of unavailableActions) {
    const button = dialog.locator('button').filter({ hasText: label }).first();
    await expect(button).toHaveCount(1);
    await expect(button).toBeHidden();
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute('aria-hidden', 'true');
    await expect.poll(() => button.evaluate((element) => element.tabIndex)).toBe(-1);
  }

  await dialog.getByRole('button', { name: 'Generate improvement', exact: true }).click();
  await expect(dialog.getByText('Describe what should improve.')).toBeVisible();
  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});

test('design-session queue shows active work and does not loop pagination', async ({ page }) => {
  await login(page);
  await mockAutoProtocolSessions(page);
  const capture = attachErrorCapture(page);

  await page.goto('/ui/design-sessions?session_id=session-02', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Auto Protocol designs', exact: true })).toBeVisible();
  await expect(page.locator('[data-auto-protocol-session-id="session-02"]')).toHaveClass(/selected/);
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Active Queue Design');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Analyzing product goals and verification scope.');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Planner agent');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('M2');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Queue position');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('2');

  const next = page.getByRole('button', { name: 'Next', exact: true });
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page).toHaveURL(/cursor=24/);
  await expect(page.locator('[data-auto-protocol-session-id="session-24"]')).toBeVisible();
  await expect(next).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeEnabled();

  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});
