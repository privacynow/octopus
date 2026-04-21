const { test, expect } = require('./playwright-runtime');
const {
  attachErrorCapture,
  connectStep,
  createStep,
  discardDraft,
  login,
  outlineStepNode,
  openBlankDraft,
  openTemplateDraft,
  protocolIdFromUrl,
  selectStep,
  waitForSaved,
} = require('./helpers/protocol-helpers');

const SOFTWARE_ENGINEERING_STAGE_KEYS = [
  'planning',
  'plan_review',
  'architecture',
  'architecture_review',
  'implementation',
  'implementation_review',
  'acceptance',
];

const DOCUMENT_APPROVAL_STAGE_KEYS = [
  'draft_document',
  'review_document',
  'approve_document',
];

async function apiJson(page, method, path, body = undefined) {
  return page.evaluate(async ({ httpMethod, requestPath, requestBody }) => {
    async function csrfToken() {
      const response = await fetch('/v1/auth/csrf', { credentials: 'same-origin' });
      const payload = await response.json();
      return String(payload.csrf_token || payload.token || '');
    }
    const headers = {};
    if (requestBody !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    if (!['GET', 'HEAD'].includes(httpMethod)) {
      headers['X-CSRF-Token'] = await csrfToken();
    }
    const response = await fetch(requestPath, {
      method: httpMethod,
      credentials: 'same-origin',
      headers,
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (error) {
      payload = { raw: text, parse_error: String(error || '') };
    }
    return {
      ok: response.ok,
      status: response.status,
      payload,
    };
  }, { httpMethod: method, requestPath: path, requestBody: body });
}

async function createProtocolScenario(page, payload) {
  const response = await apiJson(page, 'POST', '/v1/protocol-scenarios', payload);
  expect(response.ok).toBe(true);
  return response.payload;
}

async function deleteProtocolScenario(page, scenarioId) {
  const response = await apiJson(page, 'DELETE', `/v1/protocol-scenarios/${encodeURIComponent(scenarioId)}`);
  expect(response.ok).toBe(true);
}

async function getRunDetail(page, runId) {
  const response = await apiJson(page, 'GET', `/v1/protocol-runs/${encodeURIComponent(runId)}`);
  expect(response.ok).toBe(true);
  return response.payload;
}

async function waitForRunStage(page, runId, stageKey) {
  await expect.poll(async () => {
    const detail = await getRunDetail(page, runId);
    return String(detail.run?.current_stage_key || '');
  }, { timeout: 30000 }).toBe(stageKey);
}

async function waitForRunStatus(page, runId, status) {
  await expect.poll(async () => {
    const detail = await getRunDetail(page, runId);
    return String(detail.run?.status || '');
  }, { timeout: 60000 }).toBe(status);
}

async function applyScenarioAndSubmit(session, scenarioName) {
  await session.getByRole('button', { name: scenarioName, exact: true }).click();
  await expect(session.getByRole('textbox')).not.toHaveValue('');
  await session.getByRole('button', { name: 'Submit response', exact: true }).click();
}

async function waitForLatestRehearsalRunId(page, protocolId) {
  const expectedProtocolId = String(protocolId || '');
  await expect.poll(async () => {
    const response = await apiJson(page, 'GET', '/v1/protocol-runs?limit=10&status=running');
    const runs = Array.isArray(response.payload?.runs) ? response.payload.runs : [];
    return String(runs.find((item) => item.is_rehearsal && String(item.protocol_id || '') === expectedProtocolId)?.protocol_run_id || '');
  }, { timeout: 15000 }).not.toBe('');
  const response = await apiJson(page, 'GET', '/v1/protocol-runs?limit=10&status=running');
  const runs = Array.isArray(response.payload?.runs) ? response.payload.runs : [];
  return String(runs.find((item) => item.is_rehearsal && String(item.protocol_id || '') === expectedProtocolId)?.protocol_run_id || '');
}

test.describe('protocol authoring live', () => {
  test('blank draft uses step-first authoring with inline role creation', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openBlankDraft(page);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await expect(lifecycle.getByLabel('Name')).toHaveValue('');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start the workflow');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start by adding the first step.');
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);

    await page.getByRole('button', { name: /(\+ )?Add (first )?step/i }).first().click();
    const stageEditor = page.locator('.kit-stage-editor').last();
    await expect(stageEditor.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(stageEditor.getByRole('heading', { name: 'New owner role' })).toBeVisible();
    const assignmentHeading = stageEditor.getByRole('heading', { name: 'Assignment' }).first();
    await assignmentHeading.scrollIntoViewIfNeeded();
    await expect(assignmentHeading).toBeVisible();
    await expect(stageEditor.getByRole('tab', { name: 'By skill', exact: true })).toBeVisible();
    await expect(stageEditor.getByRole('tab', { name: 'Specific agent', exact: true })).toBeVisible();
    await expect(stageEditor.getByLabel('Required skill', { exact: true })).toBeVisible();
    await expect(stageEditor.getByLabel('Pin matching agent (optional)', { exact: true })).toBeVisible();
    await expect(stageEditor.locator('.kit-selector-preview-input')).toHaveCount(0);
    await expect(stageEditor.locator('.kit-selector-preview-suggestions')).toHaveCount(0);
    await expect(stageEditor.getByText('Rehearsal')).toHaveCount(0);
    const advancedAssignment = stageEditor.locator('summary').filter({ hasText: 'Custom runtime selector' });
    if (await advancedAssignment.count()) {
      await advancedAssignment.click();
      await expect(stageEditor.getByLabel('Custom selector type')).toContainText('Runtime role tag');
    }
    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByText(/^participant_[0-9]+$/i)).toHaveCount(0);
    await expect(page.getByText(/^stage_[0-9]+$/i)).toHaveCount(0);

    await page.getByRole('button', { name: /(\+ )?Add (first )?step/i }).first().click();
    const draftStageEditor = page.locator('.kit-stage-editor').last();
    await expect(draftStageEditor.getByLabel('Required skill', { exact: true }).first()).toBeVisible();
    const availableSkillValues = await draftStageEditor.getByLabel('Required skill', { exact: true }).first().locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    if (!availableSkillValues.length) {
      await expect(draftStageEditor).toContainText('No available routing skills were loaded from the registry.');
    }
    await page.getByRole('button', { name: 'Cancel' }).click();

    const defaultAssignmentKind = availableSkillValues.length ? 'skill' : 'agent';

    const planKey = await createStep(page, {
      name: 'Plan',
      key: 'plan',
      roleName: 'Planner',
      roleKey: 'planner',
      selectorKind: defaultAssignmentKind,
      selectorValue: '__first__',
    });
    const planEditor = page.locator('.kit-stage-editor-grid');
    await expect(page.locator('.kit-stage-editor').last().getByLabel('Name').first()).toHaveValue('Plan');
    await expect(page.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Assignment', exact: true })).toBeVisible();
    await expect(page.locator('.kit-stage-editor')).toContainText('Planner');
    await expect(page.locator('.kit-stage-editor')).toContainText('Current assignment:');
    await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Instructions' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add branch or finish' }).first()).toBeVisible();

    const reviewKey = await createStep(page, {
      name: 'Review',
      key: 'review',
      roleName: 'Reviewer',
      roleKey: 'reviewer',
      selectorKind: defaultAssignmentKind,
      selectorValue: '__first__',
      stageKind: 'review',
    });

    await connectStep(page, planKey, reviewKey);
    await selectStep(page, planKey);
    await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();

    await connectStep(page, reviewKey, '__complete__');
    await selectStep(page, reviewKey);
    await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();
    await selectStep(page, 'review');
    await expect(page.locator('.kit-stage-editor').last().getByLabel('Name').first()).toHaveValue('Review');

    await lifecycle.getByLabel('Name').fill(`Live Authoring ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await lifecycle.getByRole('button', { name: 'Protocol' }).click();
    await lifecycle.getByRole('button', { name: 'Protocol settings' }).click();
    await expect(page.locator('.kit-protocol-inline-card').getByLabel('Description')).toBeVisible();

    await page.getByRole('button', { name: 'Validate' }).click();
    await page.getByRole('button', { name: 'Publish' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });

    await page.getByRole('button', { name: 'Rehearse' }).click();
    await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.kit-workflow-toolbar')).toContainText('Rehearsal is active');

    await lifecycle.getByRole('button', { name: 'Protocol' }).click();
    await expect(lifecycle.getByRole('button', { name: 'Protocol settings' })).toBeVisible();
    await page.getByRole('button', { name: 'Archive' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Archived' })).toBeVisible({ timeout: 15000 });

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template opens into one progressive workflow editor', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering', { expectedStageKeys: SOFTWARE_ENGINEERING_STAGE_KEYS });
    const protocolId = protocolIdFromUrl(page.url());
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
    await expect(page.locator('.kit-authoring-primary-column')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Show workflow map', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);
    await expect(page.getByTestId('workflow-stage-planning')).toBeVisible({ timeout: 15000 });

    await page.getByTestId('workflow-stage-planning').click();
    const planningEditor = page.locator('.kit-stage-editor').last();
    await expect(planningEditor.getByLabel('Name').first()).toHaveValue('Planning');
    await expect(page.getByTestId('workflow-stage-plan_review')).toBeVisible();

    await selectStep(page, 'planning');
    await expect(page.locator('.kit-stage-editor').last().getByLabel('Name').first()).toHaveValue('Planning');
    await expect(page.getByRole('button', { name: 'Show workflow map', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).not.toBeVisible();
    await page.getByRole('button', { name: 'Show workflow map', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Hide workflow map', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: 'Fit', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: '100%', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).toBeVisible();
    const assignment = page.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'Assignment', exact: true }) }).first();
    await expect.poll(async () => assignment.getByLabel('Required skill', { exact: true }).locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    )).toContain('product-definition');
    await assignment.getByLabel('Required skill', { exact: true }).selectOption('architecture');
    await expect(assignment.getByText('Matching agents', { exact: true })).toBeVisible();
    const pinAgentControl = assignment.getByLabel('Pin matching agent (optional)', { exact: true });
    const matchingAgentValues = await pinAgentControl.locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    expect(matchingAgentValues.length).toBeGreaterThan(0);
    await pinAgentControl.selectOption(matchingAgentValues[0]);
    await expect(assignment.getByLabel('Required skill', { exact: true })).toHaveValue('architecture');
    await expect(pinAgentControl).toHaveValue(matchingAgentValues[0]);
    await assignment.getByRole('tab', { name: 'Specific agent', exact: true }).click();
    await expect(assignment.getByLabel('Agent', { exact: true })).toHaveValue(matchingAgentValues[0]);
    await expect(assignment.getByText('Optional skill requirement')).toBeVisible();
    await expect(assignment).toContainText('(leave agent-only)');
    await assignment.getByLabel('Agent', { exact: true }).selectOption('lift-and-shift-m2-bot');
    await expect(assignment.getByLabel('Agent', { exact: true })).toHaveValue('lift-and-shift-m2-bot');
    const optionalSkillControl = assignment.getByLabel('Limit to one of this agent\'s skills (optional)', { exact: true });
    const availableAgentSkills = await optionalSkillControl.locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    if (availableAgentSkills.length) {
      await optionalSkillControl.selectOption(availableAgentSkills[0]);
      await expect(optionalSkillControl).toHaveValue(availableAgentSkills[0]);
    }
    await expect(assignment.getByText('Optional skill requirement')).toBeVisible();
    expect(await assignment.locator('.quickstart-chip').count()).toBeGreaterThan(0);
    await selectStep(page, 'plan_review');
    const reviewEntry = page.locator('.kit-protocol-segment-entry').filter({ has: page.getByTestId('workflow-stage-plan_review') }).first();
    await reviewEntry.getByRole('button', { name: 'Add below', exact: true }).click();
    await createStep(page, {
      name: 'Secondary Approval',
      key: 'secondary-approval',
      roleName: 'Secondary Approver',
      roleKey: 'secondary-approver',
      selectorKind: 'agent',
      selectorValue: 'lift-and-shift-m1-bot',
      openEditor: false,
    });
    await waitForSaved(page);

    const detail = await page.evaluate(async (id) => {
      const response = await fetch(`/v1/protocols/${encodeURIComponent(id)}`, { credentials: 'same-origin' });
      if (!response.ok) {
        throw new Error(`protocol fetch failed: ${response.status}`);
      }
      return response.json();
    }, protocolId);
    const draftDocument = detail.draft_definition_json || detail.draft_document || {};
    const stages = Array.isArray(draftDocument.stages) ? draftDocument.stages : [];
    const planning = stages.find((item) => String(item.stage_key || '') === 'planning');
    const inserted = stages.find((item) => String(item.stage_key || '') === 'secondary-approval');
    const insertedIndex = stages.findIndex((item) => String(item.stage_key || '') === 'secondary-approval');
    const architectureIndex = stages.findIndex((item) => String(item.stage_key || '') === 'architecture');
    expect(planning?.transitions?.completed).toBe('plan_review');
    expect(stages.find((item) => String(item.stage_key || '') === 'plan_review')?.transitions?.accept).toBe('secondary-approval');
    expect(inserted?.transitions?.completed).toBe('architecture');
    expect(inserted?.selector?.kind).toBe('agent');
    expect(inserted?.selector?.value).toBe('lift-and-shift-m1-bot');
    expect(insertedIndex).toBeGreaterThan(-1);
    expect(architectureIndex).toBeGreaterThan(insertedIndex);

    await selectStep(page, 'secondary-approval');
    const advancedSection = page.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'Advanced', exact: true }) }).first();
    await advancedSection.locator('summary').click();
    await advancedSection.getByRole('button', { name: 'Delete step', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await waitForSaved(page);

    const afterDelete = await page.evaluate(async (id) => {
      const response = await fetch(`/v1/protocols/${encodeURIComponent(id)}`, { credentials: 'same-origin' });
      if (!response.ok) {
        throw new Error(`protocol fetch failed: ${response.status}`);
      }
      return response.json();
    }, protocolId);
    const afterDeleteStages = Array.isArray(afterDelete.draft_definition_json?.stages)
      ? afterDelete.draft_definition_json.stages
      : Array.isArray(afterDelete.draft_document?.stages)
        ? afterDelete.draft_document.stages
        : [];
    expect(afterDeleteStages.some((item) => String(item.stage_key || '') === 'secondary-approval')).toBe(false);
    expect(afterDeleteStages.find((item) => String(item.stage_key || '') === 'plan_review')?.transitions?.accept).toBe('architecture');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('document approval template teaches step-owned assignment without a participant detour', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Document Approval', { expectedStageKeys: DOCUMENT_APPROVAL_STAGE_KEYS });

    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);
    await expect(page.getByTestId('workflow-stage-draft_document')).toBeVisible();
    await expect(page.getByText('Planner role')).toHaveCount(0);
    await expect(page.getByText('Reviewer role')).toHaveCount(0);

    await page.getByTestId('workflow-stage-draft_document').click();
    await expect(await outlineStepNode(page, 'draft_document')).toBeVisible();
    await selectStep(page, 'draft_document');
    const details = page.locator('.kit-stage-editor').last();
    const documentAssignmentHeading = details.getByRole('heading', { name: 'Assignment' }).first();
    await documentAssignmentHeading.scrollIntoViewIfNeeded();
    await expect(documentAssignmentHeading).toBeVisible();
    await expect(details.getByRole('tab', { name: 'By skill', exact: true })).toBeVisible();
    await expect(details.getByRole('tab', { name: 'Specific agent', exact: true })).toBeVisible();
    await expect(details.getByLabel('Required skill', { exact: true })).toBeVisible();
    await expect(details.getByLabel('Pin matching agent (optional)', { exact: true })).toBeVisible();
    await expect(details.getByText('Rehearsal')).toHaveCount(0);
    await expect(details).toContainText('Current assignment:');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering rehearsal proves revise loops and completion visually', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);
    await login(page);
    await openTemplateDraft(page, 'Software Engineering', { expectedStageKeys: SOFTWARE_ENGINEERING_STAGE_KEYS });
    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByRole('button', { name: 'Publish' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });
    const protocolId = protocolIdFromUrl(page.url());

    const scenarioIds = [];
    for (const payload of [
      {
        protocol_id: protocolId,
        stage_key: 'planning',
        participant_key: 'planner',
        display_name: 'Planning pass 1',
        decision: 'completed',
        decision_summary: 'Planning completed.',
        response_text: 'Plan the audit logging change, include failure handling, rollout, and tests.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'planning',
        participant_key: 'planner',
        display_name: 'Planning pass 2',
        decision: 'completed',
        decision_summary: 'Planning revised.',
        response_text: 'Plan updated with rollback handling, log format, and explicit test coverage.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'plan_review',
        participant_key: 'plan_reviewer',
        display_name: 'Plan review revise',
        decision: 'revise',
        decision_summary: 'Missing rollback and failure details.',
        response_text: 'Send the plan back. It does not explain rollback handling or failure-mode coverage.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'plan_review',
        participant_key: 'plan_reviewer',
        display_name: 'Plan review accept',
        decision: 'accept',
        decision_summary: 'Plan accepted.',
        response_text: 'The revised plan is coherent and ready for architecture.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'architecture',
        participant_key: 'architect',
        display_name: 'Architecture pass',
        decision: 'completed',
        decision_summary: 'Architecture completed.',
        response_text: 'Architecture updated with API boundaries, log schema, persistence, and observability.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'architecture_review',
        participant_key: 'architecture_reviewer',
        display_name: 'Architecture review accept',
        decision: 'accept',
        decision_summary: 'Architecture accepted.',
        response_text: 'Architecture is coherent, safe, and maintainable.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'implementation',
        participant_key: 'implementer',
        display_name: 'Implementation pass 1',
        decision: 'completed',
        decision_summary: 'Implementation pass 1 completed.',
        response_text: 'Implementation updated, but coverage gaps remain in failure-path tests.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'implementation',
        participant_key: 'implementer',
        display_name: 'Implementation pass 2',
        decision: 'completed',
        decision_summary: 'Implementation revised.',
        response_text: 'Implementation updated with failure-path tests and status summary.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'implementation_review',
        participant_key: 'implementation_reviewer',
        display_name: 'Implementation review revise',
        decision: 'revise',
        decision_summary: 'Add failure-path tests.',
        response_text: 'Send this back until the failure-path tests are covered.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'implementation_review',
        participant_key: 'implementation_reviewer',
        display_name: 'Implementation review accept',
        decision: 'accept',
        decision_summary: 'Implementation accepted.',
        response_text: 'Implementation now matches the plan and includes the necessary tests.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'acceptance',
        participant_key: 'acceptance',
        display_name: 'Acceptance pass',
        decision: 'accept',
        decision_summary: 'Run accepted.',
        response_text: 'The change is ready to complete.',
      },
    ]) {
      const scenario = await createProtocolScenario(page, payload);
      scenarioIds.push(String(scenario.protocol_scenario_id || ''));
    }

    try {
      await page.getByRole('button', { name: 'Rehearse' }).click();
      await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
      const runId = await waitForLatestRehearsalRunId(page, protocolId);

      const sequence = [
        ['planning', 'Planning pass 1', 'plan_review'],
        ['plan_review', 'Plan review revise', 'planning'],
        ['planning', 'Planning pass 2', 'plan_review'],
        ['plan_review', 'Plan review accept', 'architecture'],
        ['architecture', 'Architecture pass', 'architecture_review'],
        ['architecture_review', 'Architecture review accept', 'implementation'],
        ['implementation', 'Implementation pass 1', 'implementation_review'],
        ['implementation_review', 'Implementation review revise', 'implementation'],
        ['implementation', 'Implementation pass 2', 'implementation_review'],
        ['implementation_review', 'Implementation review accept', 'acceptance'],
      ];

      for (const [stageKey, scenarioName, nextStage] of sequence) {
        const session = page.locator(`.kit-rehearsal-session[data-stage-key="${stageKey}"]`).first();
        await expect(session).toBeVisible({ timeout: 20000 });
        await applyScenarioAndSubmit(session, scenarioName);
        await waitForRunStage(page, runId, nextStage);
      }

      const acceptance = page.locator('.kit-rehearsal-session[data-stage-key="acceptance"]').first();
      await expect(acceptance).toBeVisible({ timeout: 20000 });
      await applyScenarioAndSubmit(acceptance, 'Acceptance pass');
      await waitForRunStatus(page, runId, 'completed');

      const finalDetail = await getRunDetail(page, runId);
      expect(String(finalDetail.run?.status || '')).toBe('completed');
      expect(finalDetail.stage_executions.some((item) => String(item.stage_key || '') === 'plan_review' && String(item.decision || '') === 'revise')).toBe(true);
      expect(finalDetail.stage_executions.some((item) => String(item.stage_key || '') === 'implementation_review' && String(item.decision || '') === 'revise')).toBe(true);
    } finally {
      for (const scenarioId of scenarioIds.filter(Boolean)) {
        await deleteProtocolScenario(page, scenarioId);
      }
    }

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('document approval rehearsal proves revise then approve visually', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);
    await login(page);
    await openTemplateDraft(page, 'Document Approval', { expectedStageKeys: DOCUMENT_APPROVAL_STAGE_KEYS });
    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByRole('button', { name: 'Publish' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });
    const protocolId = protocolIdFromUrl(page.url());

    const scenarioIds = [];
    for (const payload of [
      {
        protocol_id: protocolId,
        stage_key: 'draft_document',
        participant_key: 'author',
        display_name: 'Draft v1',
        decision: 'completed',
        decision_summary: 'Draft completed.',
        response_text: 'Drafted the quarterly risk summary without an executive summary section.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'draft_document',
        participant_key: 'author',
        display_name: 'Draft v2',
        decision: 'completed',
        decision_summary: 'Draft revised.',
        response_text: 'Added an executive summary and clarified the outstanding risk items.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'review_document',
        participant_key: 'reviewer',
        display_name: 'Review revise',
        decision: 'revise',
        decision_summary: 'Missing executive summary.',
        response_text: 'Send this back until it includes an executive summary.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'review_document',
        participant_key: 'reviewer',
        display_name: 'Review accept',
        decision: 'accept',
        decision_summary: 'Review accepted.',
        response_text: 'The revised document is ready for approval.',
      },
      {
        protocol_id: protocolId,
        stage_key: 'approve_document',
        participant_key: 'approver',
        display_name: 'Approve accept',
        decision: 'accept',
        decision_summary: 'Document approved.',
        response_text: 'Approve the document and finish the workflow.',
      },
    ]) {
      const scenario = await createProtocolScenario(page, payload);
      scenarioIds.push(String(scenario.protocol_scenario_id || ''));
    }

    try {
      await page.getByRole('button', { name: 'Rehearse' }).click();
      await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
      const runId = await waitForLatestRehearsalRunId(page, protocolId);

      const sequence = [
        ['draft_document', 'Draft v1', 'review_document'],
        ['review_document', 'Review revise', 'draft_document'],
        ['draft_document', 'Draft v2', 'review_document'],
        ['review_document', 'Review accept', 'approve_document'],
      ];
      for (const [stageKey, scenarioName, nextStage] of sequence) {
        const session = page.locator(`.kit-rehearsal-session[data-stage-key="${stageKey}"]`).first();
        await expect(session).toBeVisible({ timeout: 20000 });
        await applyScenarioAndSubmit(session, scenarioName);
        await waitForRunStage(page, runId, nextStage);
      }

      const approval = page.locator('.kit-rehearsal-session[data-stage-key="approve_document"]').first();
      await expect(approval).toBeVisible({ timeout: 20000 });
      await applyScenarioAndSubmit(approval, 'Approve accept');
      await waitForRunStatus(page, runId, 'completed');

      const finalDetail = await getRunDetail(page, runId);
      expect(String(finalDetail.run?.status || '')).toBe('completed');
      expect(finalDetail.stage_executions.some((item) => String(item.stage_key || '') === 'review_document' && String(item.decision || '') === 'revise')).toBe(true);
    } finally {
      for (const scenarioId of scenarioIds.filter(Boolean)) {
        await deleteProtocolScenario(page, scenarioId);
      }
    }

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template stays usable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering', { expectedStageKeys: SOFTWARE_ENGINEERING_STAGE_KEYS });
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
    await expect(page.locator('.kit-authoring-primary-column')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Show workflow map', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Show workflow map', exact: true }).click();
    const canvasOverflow = await page.locator('.kit-workflow-viewport-cy').evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }));
    expect(canvasOverflow.scrollWidth).toBeLessThanOrEqual(canvasOverflow.clientWidth + 2);

    await page.getByTestId('workflow-stage-planning').click();
    await expect(page.locator('.kit-stage-editor').last().getByLabel('Name').first()).toHaveValue('Planning');
    await selectStep(page, 'planning');
    await expect(page.locator('.kit-stage-editor-grid')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
    await expect(page.locator('.kit-workflow-cy-host')).toBeVisible();

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('draft conflict shell stays available for blank drafts', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);
    await login(page);
    await openBlankDraft(page);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByLabel('Name').fill(`Conflict Draft ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });
});
