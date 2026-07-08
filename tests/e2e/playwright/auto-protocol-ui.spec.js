const { test, expect } = require('./playwright-runtime');
const { attachErrorCapture, login } = require('./helpers/protocol-helpers');

test.use({ viewport: { width: 1440, height: 900 } });

function mockSession(index, overrides = {}) {
  const now = new Date(Date.UTC(2026, 6, 7, 12, index, 0)).toISOString();
  const sessionId = `session-${String(index).padStart(2, '0')}`;
  return {
    session_id: sessionId,
    status: 'ready',
    mode: index % 2 ? 'create' : 'revise',
    requirement_text: `Mock design ${index}`,
    target_protocol_id: `protocol-${index}`,
    source_run_id: '',
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

async function mockAgents(page, { waitFor = null } = {}) {
  await page.route('**/v1/agents**', async (route) => {
    if (waitFor) await waitFor;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        agents: [
          {
            agent_id: 'agent-m2',
            display_name: 'M2',
            slug: 'm2',
            provider: 'codex',
            connectivity_state: 'connected',
            supported_admin_operations: ['design_auto_protocol'],
          },
        ],
      }),
    });
  });
}

async function mockProtocolRunForImprove(page, { runId = 'run-improve-e2e', protocolId = 'protocol-improve-e2e' } = {}) {
  const runSummary = {
    protocol_run_id: runId,
    protocol_id: protocolId,
    status: 'blocked',
    current_stage_key: 'final_evidence',
    blocked_code: 'runtime_evidence_required',
    blocked_detail: 'Runtime evidence is incomplete.',
    updated_at: '2026-07-07T12:05:00Z',
  };
  const runDetail = {
    run: {
      ...runSummary,
      workspace_ref: 'workspace:e2e',
      run_objective: 'Improve the Auto Protocol run evidence.',
    },
    protocol: {
      protocol_id: protocolId,
      display_name: 'Improve E2E Protocol',
      lifecycle_state: 'published',
    },
    version: {
      protocol_version_id: 'version-improve-e2e',
      definition_json: {
        metadata: { display_name: 'Improve E2E Protocol' },
        stages: [{ stage_key: 'final_evidence', display_name: 'Final evidence' }],
        artifacts: [{ artifact_key: 'package', display_name: 'Package' }],
      },
    },
    stage_executions: [
      {
        protocol_stage_execution_id: 'stage-final-e2e',
        stage_key: 'final_evidence',
        display_name: 'Final evidence',
        status: 'blocked',
        failure_code: 'runtime_evidence_required',
        failure_detail: 'Runtime evidence is incomplete.',
      },
    ],
    runtime_events: [],
    transitions: [],
    artifacts: [],
  };

  await page.route('**/v1/protocol-runs**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (payload, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
    if (path === '/v1/protocol-runs/issues') {
      await json({ issues: [] });
      return;
    }
    if (path === '/v1/protocol-runs') {
      await json({ runs: [runSummary], next_cursor: null });
      return;
    }
    if (path.endsWith(`/${runId}`)) {
      await json(runDetail);
      return;
    }
    await json({ detail: { message: 'Not found', error_code: 'NOT_FOUND' } }, 404);
  });
  return runId;
}

function defaultMockSessions() {
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
  return sessions;
}

async function mockAutoProtocolSessions(page, options = {}) {
  const sessions = options.sessions || defaultMockSessions();
  const actionHandler = typeof options.actionHandler === 'function' ? options.actionHandler : null;
  const createHandler = typeof options.createHandler === 'function' ? options.createHandler : null;
  const sessionGetHandler = typeof options.sessionGetHandler === 'function' ? options.sessionGetHandler : null;

  await page.route('**/v1/protocol-auto/sessions**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (payload, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });

    if (path === '/v1/protocol-auto/sessions') {
      if (route.request().method() === 'POST' && createHandler) {
        await createHandler({ route, sessions, json });
        return;
      }
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

    const session = sessions.find((item) => String(item?.session_id || '') === sessionId);
    if (!session) {
      await json({ detail: { message: 'Not found', error_code: 'NOT_FOUND' } }, 404);
      return;
    }
    const action = parts[parts.indexOf('sessions') + 2] || '';
    if (['apply', 'publish', 'run', 'revise'].includes(action)) {
      if (actionHandler) {
        await actionHandler({ route, session, sessionId, action, json });
        return;
      }
      await json(session);
      return;
    }
    if (sessionGetHandler) {
      await sessionGetHandler({ route, session, sessionId, json });
      return;
    }
    await json(session);
  });
}

async function mockProtocolCatalog(page, { records = [] } = {}) {
  await page.route('**/v1/protocols**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/v1/protocols') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(records),
      });
      return;
    }
    const parts = url.pathname.split('/').filter(Boolean);
    const protocolId = decodeURIComponent(parts[parts.indexOf('protocols') + 1] || '');
    const record = records.find((item) => String(item.protocol_id || '') === protocolId);
    if (!record) {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { message: 'Not found', error_code: 'NOT_FOUND' } }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        protocol: record,
        draft_definition_json: {
          metadata: {
            slug: record.slug,
            display_name: record.display_name,
            description: record.description,
          },
          participants: [],
          artifacts: [],
          stages: [],
          policies: {},
        },
        versions: [],
        validation: { ok: true },
      }),
    });
  });
  await page.route('**/v1/protocol-auto/sessions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], next_cursor: null }),
    });
  });
  await page.route('**/v1/protocol-authoring/options', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });
  await page.route('**/v1/protocol-templates', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
}

function visibleReadySessions() {
  return [
    mockSession(1, { session_id: 'session-01', requirement_text: 'Ready design one', target_protocol_id: 'protocol-01' }),
    mockSession(2, { session_id: 'session-02', requirement_text: 'Ready design two', target_protocol_id: 'protocol-02' }),
  ];
}

test('protocol catalog cards clamp long descriptions without overlap', async ({ page }) => {
  await login(page);
  const longDescription = [
    'This generated protocol description is intentionally enormous.',
    'It includes a full pasted specification, repeated invariant clauses, provider caveats, API notes, persistence warnings, and user workflow details.',
    'LongUnbrokenIdentifierThatUsedToBleedAcrossCatalogColumnsAndCoverNeighboringCards'.repeat(12),
    ' '.repeat(1),
    'Every catalog card must remain a bounded summary while the full description stays available in the detail view.',
  ].join(' ');
  await mockProtocolCatalog(page, {
    records: [
      {
        protocol_id: 'proto-alpha',
        slug: 'long-description-alpha',
        display_name: 'Long Generated Protocol',
        description: longDescription.repeat(6),
        lifecycle_state: 'draft',
        updated_at: '2026-07-07T12:00:00Z',
      },
      {
        protocol_id: 'proto-beta',
        slug: 'neighbor-beta',
        display_name: 'Readable Neighbor Protocol',
        description: 'Neighbor card should remain readable and clickable.',
        lifecycle_state: 'published',
        current_version_id: 'version-beta',
        updated_at: '2026-07-07T12:01:00Z',
      },
      {
        protocol_id: 'proto-gamma',
        slug: 'neighbor-gamma',
        display_name: 'Second Neighbor Protocol',
        description: 'Another adjacent card that must not be covered.',
        lifecycle_state: 'published',
        current_version_id: 'version-gamma',
        updated_at: '2026-07-07T12:02:00Z',
      },
    ],
  });
  const capture = attachErrorCapture(page);

  await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
  const cards = page.locator('.kit-authored-catalog .kit-catalog-card');
  await expect(cards).toHaveCount(3);
  await expect(cards.filter({ hasText: 'Readable Neighbor Protocol' })).toBeVisible();
  await cards.filter({ hasText: 'Readable Neighbor Protocol' }).click();
  await expect(page).toHaveURL(/protocol_id=proto-beta/);
  await page.goBack({ waitUntil: 'domcontentloaded' });
  await expect(cards).toHaveCount(3);

  const layout = await cards.evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect();
    const body = node.querySelector('.kit-catalog-card-body');
    const bodyRect = body ? body.getBoundingClientRect() : null;
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
      bodyHeight: bodyRect ? bodyRect.height : 0,
    };
  }));
  expect(layout.length).toBe(3);
  for (let i = 0; i < layout.length; i += 1) {
    expect(layout[i].width).toBeGreaterThan(240);
    expect(layout[i].height).toBeLessThan(260);
    expect(layout[i].bodyHeight).toBeLessThan(105);
    for (let j = i + 1; j < layout.length; j += 1) {
      const a = layout[i];
      const b = layout[j];
      const separated = a.right <= b.left + 1
        || b.right <= a.left + 1
        || a.bottom <= b.top + 1
        || b.bottom <= a.top + 1;
      expect(separated).toBeTruthy();
    }
  }

  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});

test('improve-run dialog opens and unavailable actions are not actionable', async ({ page }) => {
  await login(page);
  let releaseAgents;
  const agentsReady = new Promise((resolve) => {
    releaseAgents = resolve;
  });
  await mockAgents(page, { waitFor: agentsReady });
  const runId = await mockProtocolRunForImprove(page);
  await page.goto(`/ui/runs?run_id=${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded' });

  const capture = attachErrorCapture(page);
  await expect(page.getByRole('button', { name: 'Improve this run', exact: true })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Improve this run', exact: true }).click();

  const dialog = page.locator('.confirm-dialog.protocol-auto-modal').filter({ hasText: 'Improve this run' }).first();
  await expect(dialog).toBeVisible({ timeout: 15000 });
  await expect(dialog.getByText('Candidate lessons from this run')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Generate improvement', exact: true })).toBeVisible();
  const plannerSelect = dialog.getByLabel('Planner agent');
  await expect(plannerSelect).toBeVisible();
  await expect(plannerSelect).toBeDisabled();
  releaseAgents();
  await expect.poll(() => plannerSelect.locator('option').evaluateAll((options) => options.map((option) => option.textContent || ''))).toContain('M2');
  await expect(plannerSelect).toBeEnabled();

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

test('improve-run dialog rejects remembered sessions from another run', async ({ page }) => {
  await login(page);
  await mockAgents(page);
  const protocolId = 'protocol-shared-improve-e2e';
  const runId = await mockProtocolRunForImprove(page, { runId: 'run-improve-b-e2e', protocolId });
  let rememberedFetches = 0;
  const rememberedSession = mockSession(11, {
    session_id: 'session-run-a',
    status: 'planning',
    mode: 'revise',
    target_protocol_id: protocolId,
    source_run_id: 'run-improve-a-e2e',
    requirement_text: 'Run A remembered planning session',
    plan: { protocol_name: 'Run A remembered planner' },
    draft_definition_json: {},
    validation: { ok: false },
    planner_state: {
      planner_status: 'running',
      selected_agent_display_name: 'M2',
      queued_at: '2026-07-07T12:11:00Z',
      started_at: '2026-07-07T12:12:00Z',
      last_progress_at: '2026-07-07T12:13:00Z',
      progress_summary: 'Run A planner is active.',
      queue_position: 0,
    },
  });
  await mockAutoProtocolSessions(page, {
    sessions: [rememberedSession],
    sessionGetHandler: async ({ sessionId, json, session }) => {
      if (sessionId === 'session-run-a') rememberedFetches += 1;
      await json(session);
    },
  });
  const capture = attachErrorCapture(page);
  await page.evaluate(([key, value]) => window.localStorage.setItem(key, value), [
    'octopus.protocolAuto.activeSessionId',
    'session-run-a',
  ]);

  await page.goto(`/ui/runs?run_id=${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: 'Improve this run', exact: true })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Improve this run', exact: true }).click();

  const dialog = page.locator('.confirm-dialog.protocol-auto-modal').filter({ hasText: 'Improve this run' }).first();
  await expect(dialog).toBeVisible({ timeout: 15000 });
  await expect.poll(() => rememberedFetches).toBe(1);
  await expect(dialog.getByRole('button', { name: 'Generate improvement', exact: true })).toBeVisible();
  await expect(dialog.getByPlaceholder(/make the runtime start/i)).toBeVisible();
  await expect(dialog.getByText('Run A planner is active.')).toHaveCount(0);
  await expect(dialog.getByText('Run A remembered planner')).toHaveCount(0);
  const queueButton = dialog.locator('button').filter({ hasText: 'View in queue' }).first();
  await expect(queueButton).toBeHidden();
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
  await expect(page.locator('.protocol-auto-session-detail .kit-details-row').filter({ hasText: 'Queue position' })).toHaveCount(0);

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

test('queue action deterministic errors render once without retry', async ({ page }) => {
  await login(page);
  await mockAutoProtocolSessions(page, {
    sessions: visibleReadySessions(),
    actionHandler: async ({ action, json }) => {
      if (action === 'apply') {
        await json({
          detail: {
            message: 'Operator authoring role is required.',
            error_code: 'PROTOCOL_AUTO_APPLY_ROLE_REQUIRED',
          },
        }, 403);
        return;
      }
      await json({});
    },
  });
  const capture = attachErrorCapture(page, { ignoreConsole: [/403 \(Forbidden\)/] });

  await page.goto('/ui/design-sessions?session_id=session-01', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-auto-protocol-session-id="session-01"]')).toHaveClass(/selected/);
  await page.getByRole('button', { name: 'Apply draft', exact: true }).click();

  const detail = page.locator('.protocol-auto-session-detail');
  const errorCard = detail.locator('.protocol-auto-error');
  await expect(errorCard).toHaveCount(1);
  await expect(errorCard).toContainText('PROTOCOL_AUTO_APPLY_ROLE_REQUIRED');
  await expect(errorCard).toContainText('Operator authoring role is required.');
  await expect(errorCard.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0);
  await expect(detail.getByText('Operator authoring role is required.')).toHaveCount(1);

  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});

test('queue action planning refresh updates stale detail without mutating', async ({ page }) => {
  await login(page);
  let actionRefresh = false;
  let mutationAttempts = 0;
  const ready = mockSession(1, {
    session_id: 'session-01',
    requirement_text: 'Ready design before stale refresh',
    target_protocol_id: 'protocol-01',
  });
  const planning = {
    ...ready,
    status: 'planning',
    draft_definition_json: {},
    validation: { ok: false },
    planner_state: {
      planner_status: 'running',
      selected_agent_display_name: 'M2',
      queued_at: '2026-07-07T12:00:00Z',
      started_at: '2026-07-07T12:01:00Z',
      last_progress_at: '2026-07-07T12:03:00Z',
      progress_summary: 'Still designing after refresh.',
    },
  };
  await mockAutoProtocolSessions(page, {
    sessions: [ready],
    sessionGetHandler: async ({ json, session }) => {
      await json(actionRefresh ? planning : session);
    },
    actionHandler: async ({ json }) => {
      mutationAttempts += 1;
      await json({ detail: { message: 'Mutation should not have run.', error_code: 'UNEXPECTED_MUTATION' } }, 500);
    },
  });
  const capture = attachErrorCapture(page);

  await page.goto('/ui/design-sessions?session_id=session-01', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Ready design before stale refresh');
  actionRefresh = true;
  await page.getByRole('button', { name: 'Apply draft', exact: true }).click();

  const detail = page.locator('.protocol-auto-session-detail');
  await expect(detail.locator('.protocol-auto-error')).toContainText('PROTOCOL_AUTO_PLANNING');
  await expect(detail).toContainText('Still designing after refresh.');
  await expect(detail.getByRole('button', { name: 'Apply draft', exact: true })).toBeDisabled();
  expect(mutationAttempts).toBe(0);
  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});

test('retryable queue errors allow one in-flight retry', async ({ page }) => {
  await login(page);
  let applyAttempts = 0;
  let retryReleased = false;
  let releaseRetry;
  const retryStarted = new Promise((resolve) => {
    releaseRetry = () => {
      retryReleased = true;
      resolve();
    };
  });
  await mockAutoProtocolSessions(page, {
    sessions: visibleReadySessions(),
    actionHandler: async ({ action, json }) => {
      if (action !== 'apply') {
        await json({});
        return;
      }
      applyAttempts += 1;
      if (applyAttempts === 1) {
        await json({ detail: { message: 'Transient planner action failure.', error_code: 'TEMPORARY_FAILURE' } }, 500);
        return;
      }
      await retryStarted;
      await json({ detail: { message: 'Retry should not complete in this assertion.', error_code: 'TEMPORARY_FAILURE' } }, 500);
    },
  });

  await page.goto('/ui/design-sessions?session_id=session-01', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Apply draft', exact: true }).click();
  const retry = page.locator('.protocol-auto-session-detail .protocol-auto-error').getByRole('button', { name: 'Retry', exact: true });
  await expect(retry).toBeVisible();

  await retry.click();
  await expect.poll(() => applyAttempts).toBe(2);
  const apply = page.getByRole('button', { name: 'Apply draft', exact: true });
  await expect(apply).toBeDisabled();
  await apply.click({ force: true });
  await page.waitForTimeout(100);
  expect(applyAttempts).toBe(2);
  releaseRetry();
  await expect(retry).toBeVisible();
  await expect(apply).toBeEnabled();
  expect(retryReleased).toBe(true);
});

test('planning sessions remain visible after closing a generation dialog', async ({ page }) => {
  await login(page);
  const sessions = visibleReadySessions();
  await mockAutoProtocolSessions(page, {
    sessions,
    actionHandler: async ({ json }) => {
      await json({});
    },
    createHandler: async ({ sessions: currentSessions, json }) => {
      const created = mockSession(9, {
        session_id: 'session-created',
        status: 'planning',
        requirement_text: 'New visible planning session',
        target_protocol_id: '',
        draft_definition_json: {},
        validation: { ok: false },
        planner_state: {
          planner_status: 'queued',
          queued_at: '2026-07-07T12:09:00Z',
          progress_summary: 'Queued for planner assignment.',
          queue_position: 0,
        },
      });
      currentSessions.unshift(created);
      await json(created);
    },
  });
  const capture = attachErrorCapture(page);

  await page.goto('/ui/design-sessions', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New Auto Protocol', exact: true }).click();
  const dialog = page.locator('.confirm-dialog.protocol-auto-modal').filter({ hasText: 'Auto protocol' }).first();
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder(/Describe the outcome you want/i).fill('Build a planning session that stays visible.');
  await dialog.getByRole('button', { name: 'Generate protocol', exact: true }).click();
  await expect(dialog.getByText('Queued for planner assignment.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();

  await expect(page.locator('[data-auto-protocol-session-id="session-created"]')).toBeVisible();
  await page.locator('[data-auto-protocol-session-id="session-created"]').click();
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('New visible planning session');
  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});

test('concurrent planning sessions stay independently selectable', async ({ page }) => {
  await login(page);
  const sessions = defaultMockSessions();
  sessions[3] = mockSession(3, {
    status: 'planning',
    requirement_text: 'Second active queue design',
    plan: { protocol_name: 'Second Active Queue Design' },
    draft_definition_json: {},
    validation: { ok: false },
    planner_state: {
      planner_status: 'running',
      selected_agent_display_name: 'M3',
      queued_at: '2026-07-07T12:03:00Z',
      started_at: '2026-07-07T12:04:00Z',
      last_progress_at: '2026-07-07T12:05:00Z',
      progress_summary: 'Drafting the second design.',
      queue_position: 0,
    },
  });
  await mockAutoProtocolSessions(page, { sessions });
  const capture = attachErrorCapture(page);

  await page.goto('/ui/design-sessions?session_id=session-02', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Active Queue Design');
  await page.locator('[data-auto-protocol-session-id="session-03"]').click();
  await expect(page).toHaveURL(/session_id=session-03/);
  await expect(page.locator('[data-auto-protocol-session-id="session-03"]')).toHaveClass(/selected/);
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Second Active Queue Design');
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Drafting the second design.');
  await page.locator('[data-auto-protocol-session-id="session-02"]').click();
  await expect(page.locator('.protocol-auto-session-detail')).toContainText('Active Queue Design');

  expect(capture.pageErrors).toEqual([]);
  expect(capture.consoleErrors).toEqual([]);
});
