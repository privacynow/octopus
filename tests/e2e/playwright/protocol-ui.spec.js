const { test, expect } = require('./playwright-runtime');
const {
  assertStandardAuthoringSurface,
  attachErrorCapture,
  connectStep,
  createStep,
  discardDraft,
  expectSelectedStep,
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

async function waitForRunStatus(page, runId, status, timeout = 60000) {
  await expect.poll(async () => {
    const detail = await getRunDetail(page, runId);
    return String(detail.run?.status || '');
  }, { timeout }).toBe(status);
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

async function firstConnectedAgent(page) {
  return page.evaluate(async () => {
    const response = await fetch('/v1/agents?state=connected&limit=100', { credentials: 'same-origin' });
    const payload = await response.json();
    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const first = agents.find((agent) => String(agent.connectivity_state || '').toLowerCase() === 'connected');
    return {
      agentId: String(first?.agent_id || ''),
      slug: String(first?.slug || ''),
    };
  });
}

async function firstSkillLifecycleAgent(page) {
  return page.evaluate(async () => {
    const response = await fetch('/v1/agents?limit=100', { credentials: 'same-origin' });
    const payload = await response.json();
    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const first = agents.find((agent) => {
      const state = String(agent.connectivity_state || '').trim().toLowerCase();
      const capabilities = Array.isArray(agent.management_capabilities) ? agent.management_capabilities : [];
      return ['connected', 'degraded'].includes(state) && capabilities.includes('skill_lifecycle');
    });
    return {
      agentId: String(first?.agent_id || ''),
      slug: String(first?.slug || ''),
      displayName: String(first?.display_name || first?.slug || '').trim(),
    };
  });
}

async function createAndPublishCustomSkill(page, {
  agentId,
  skillName,
  description,
  body,
} = {}) {
  await page.goto('/ui/skills', { waitUntil: 'domcontentloaded' });
  const agentSelect = page.getByLabel('Managed bot', { exact: true });
  await expect.poll(async () => agentSelect.locator('option').evaluateAll((options) =>
    options.map((option) => String(option.value || '')).filter(Boolean),
  )).toContain(agentId);
  await agentSelect.selectOption(agentId);
  await page.getByRole('button', { name: 'New custom skill', exact: true }).click();
  await page.getByPlaceholder('skill-slug').fill(skillName);
  await page.getByPlaceholder('Short description').first().fill(description);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect.poll(() => page.url(), { timeout: 20000 }).toContain(`skill=${encodeURIComponent(skillName)}`);
  await page.getByPlaceholder('Display name').fill(
      skillName
      .split('-')
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' '),
  );
  await page.getByPlaceholder('Short description').last().fill(description);
  await page.getByPlaceholder('Draft instructions').fill(body);
  await page.getByRole('tab', { name: 'Review', exact: true }).click();
  const reviewPanel = page.locator('.editor-panel').filter({ hasText: 'Instructions preview' }).first();
  await expect(page.getByRole('button', { name: 'Submit', exact: true })).toBeEnabled({ timeout: 60000 });
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  await expect(reviewPanel).toContainText('Lifecycle');
  await expect(reviewPanel).toContainText('review', { timeout: 30000 });
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(reviewPanel).toContainText('approved', { timeout: 30000 });
  await expect(reviewPanel).toContainText('Publish this approved draft when you are ready', { timeout: 30000 });
  await expect(page.getByRole('button', { name: 'Publish', exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.locator('.editor-panel').filter({ hasText: 'Runtime available' }).first()).toContainText('Yes', { timeout: 30000 });
}

async function openProtocolSettings(page) {
  const lifecycle = page.locator('.kit-lifecycle-header');
  await lifecycle.getByRole('button', { name: 'Protocol' }).click();
  await lifecycle.getByRole('button', { name: 'Protocol settings' }).click();
  await expect(page.locator('.kit-protocol-inline-card').getByLabel('Description')).toBeVisible();
}

async function addArtifact(page, { name, path, kind = 'workspace_file' }) {
  const catalog = page.locator('.kit-protocol-inline-card').filter({ has: page.getByRole('heading', { name: 'Workflow files and outputs', exact: true }) }).first();
  const beforeCount = await page.locator('[data-testid^="workflow-artifact-"]').count();
  const artifactKey = `artifact_${beforeCount + 1}`;
  await catalog.getByRole('button', { name: 'Add artifact', exact: true }).click();
  const artifactNode = page.getByTestId(`workflow-artifact-${artifactKey}`);
  await expect(artifactNode).toBeVisible();
  await artifactNode.click();
  await expect(artifactNode).toHaveClass(/is-selected/);
  let editor = page.locator('.kit-protocol-inline-editor .kit-stage-editor').first();
  await expect(editor.getByRole('heading', { name: 'Artifact basics', exact: true })).toBeVisible();
  await expect(editor).toContainText('datasets, code, documents, PDFs, and reports');
  await editor.getByLabel('Name', { exact: true }).fill(name);
  await editor.getByLabel('Name', { exact: true }).blur();
  await page.waitForTimeout(600);
  await waitForSaved(page);
  editor = page.locator('.kit-protocol-inline-editor .kit-stage-editor').first();
  await editor.getByLabel('What it represents', { exact: true }).selectOption(kind);
  await page.waitForTimeout(600);
  await waitForSaved(page);
  editor = page.locator('.kit-protocol-inline-editor .kit-stage-editor').first();
  await editor.getByLabel('Workspace path', { exact: true }).fill(path);
  await editor.getByLabel('Workspace path', { exact: true }).blur();
  await page.waitForTimeout(600);
  await waitForSaved(page);
}

async function configureStepArtifacts(page, stageKey, { reads = [], writes = [] } = {}) {
  await selectStep(page, stageKey);
  const artifactLabelPattern = (label) => new RegExp(
    String(label || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  );
  async function artifactRows() {
    const editor = page.locator('.kit-stage-editor').last();
    const artifactsSection = editor.locator('.kit-stage-editor-section').filter({
      has: page.getByRole('heading', { name: 'Inputs and outputs', exact: true }),
    }).first();
    const summary = artifactsSection.locator('summary').first();
    if (await summary.count()) {
      const expanded = await summary.evaluate((node) => node.closest('details')?.open === true);
      if (!expanded) {
        await summary.click();
        await expect.poll(async () => summary.evaluate((node) => node.closest('details')?.open === true)).toBe(true);
      }
    }
    const readsRow = artifactsSection.locator('.kit-details-row').filter({ hasText: 'Needs from earlier steps' }).first();
    const writesRow = artifactsSection.locator('.kit-details-row').filter({ hasText: 'Produces for later steps' }).first();
    await expect(readsRow).toBeVisible();
    await expect(writesRow).toBeVisible();
    return { readsRow, writesRow };
  }
  for (const label of reads) {
    const { readsRow } = await artifactRows();
    await readsRow.getByLabel(artifactLabelPattern(label)).check();
    await page.waitForTimeout(600);
    await waitForSaved(page);
    await expectSelectedStep(page, stageKey);
  }
  for (const label of writes) {
    const { writesRow } = await artifactRows();
    await writesRow.getByLabel(artifactLabelPattern(label)).check();
    await page.waitForTimeout(600);
    await waitForSaved(page);
    await expectSelectedStep(page, stageKey);
  }
}

async function createProtocolRun(page, payload) {
  const response = await apiJson(page, 'POST', '/v1/protocol-runs', payload);
  expect(response.ok).toBe(true);
  return response.payload;
}

test.describe('protocol authoring live', () => {
  test('blank draft uses step-first authoring with inline role creation', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openBlankDraft(page);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await expect(lifecycle.getByLabel('Name')).toHaveValue('');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start the workflow');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start with the first step');
    await expect(page.getByRole('button', { name: 'Define shared files', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open skills catalog', exact: true })).toBeVisible();
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
    await assertStandardAuthoringSurface(stageEditor, { expectDelete: false });
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
    await page.getByRole('button', { name: 'Protocol settings', exact: true }).click();
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
    await page.getByRole('button', { name: 'Done', exact: true }).first().click();
    await expect(page.locator('.kit-protocol-inline-editor > .kit-stage-editor')).toHaveCount(0);

    await selectStep(page, 'planning');
    await expect(page.locator('.kit-stage-editor').last().getByLabel('Name').first()).toHaveValue('Planning');
    await expect(page.getByRole('button', { name: 'Show workflow map', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).not.toBeVisible();
    await page.getByRole('button', { name: 'Show workflow map', exact: true }).click();
    await expect(page.locator('.kit-protocol-stage-stack')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Hide workflow map', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Back to workflow', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: 'Fit', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: '100%', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).toBeVisible();
    const mapWidth = await page.locator('.kit-authoring-map-panel .kit-workflow-viewport-cy').evaluate((element) => element.getBoundingClientRect().width);
    expect(mapWidth).toBeGreaterThan(700);
    await page.getByRole('button', { name: 'Back to workflow', exact: true }).click();
    await expectSelectedStep(page, 'planning');
    await expect(page.locator('.kit-protocol-stage-stack')).toBeVisible();

    await openProtocolSettings(page);
    await expect(page.locator('.kit-protocol-stage-stack')).toHaveCount(0);
    await page.getByRole('button', { name: 'Back to workflow', exact: true }).click();
    await expectSelectedStep(page, 'planning');

    const assignment = page.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'Assignment', exact: true }) }).first();
    await expect.poll(async () => assignment.getByLabel('Required skill', { exact: true }).locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    )).toContain('product-definition');
    await assignment.getByLabel('Required skill', { exact: true }).selectOption('architecture');
    await expect(assignment.getByText('Matching agents', { exact: true })).toBeVisible();
    const pinAgentPillGroup = assignment.locator('.kit-selector-pill-group[aria-label="Pin matching agent (optional)"]');
    const pinAgentSelect = assignment.locator('select[aria-label="Pin matching agent (optional)"]');
    if (await pinAgentPillGroup.count()) {
      await expect(pinAgentSelect).toHaveCount(0);
      const pinAgentPills = pinAgentPillGroup.locator('.quickstart-chip');
      const pillLabels = (await pinAgentPills.allTextContents()).map((label) => String(label || '').trim()).filter(Boolean);
      const firstAgentLabel = pillLabels.find((label) => label !== 'Dynamic') || '';
      expect(firstAgentLabel).toBeTruthy();
      const firstAgentPill = pinAgentPills.filter({ hasText: firstAgentLabel }).first();
      await firstAgentPill.click();
      await expect(firstAgentPill).toHaveAttribute('aria-pressed', 'true');
    } else {
      const matchingAgentValues = await pinAgentSelect.locator('option').evaluateAll((options) =>
        options.map((option) => String(option.value || '')).filter(Boolean),
      );
      expect(matchingAgentValues.length).toBeGreaterThan(0);
      await pinAgentSelect.selectOption(matchingAgentValues[0]);
      await expect(pinAgentSelect).toHaveValue(matchingAgentValues[0]);
    }
    await expect(assignment.getByLabel('Required skill', { exact: true })).toHaveValue('architecture');
    await assignment.getByRole('tab', { name: 'Specific agent', exact: true }).click();
    const agentControl = assignment.getByLabel('Agent', { exact: true });
    const initialPinnedAgentValue = await agentControl.inputValue();
    expect(initialPinnedAgentValue).toBeTruthy();
    await expect(assignment.getByText('Optional skill requirement')).toBeVisible();
    await expect(assignment).toContainText('(leave agent-only)');
    const availableAgentValues = await agentControl.locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    const alternateAgent = availableAgentValues.find((value) => value !== initialPinnedAgentValue) || '';
    if (alternateAgent) {
      await agentControl.selectOption(alternateAgent);
      await expect(agentControl).toHaveValue(alternateAgent);
    } else {
      await expect(agentControl).toHaveValue(initialPinnedAgentValue);
    }
    const optionalSkillControl = assignment.getByLabel('Limit to one of this agent\'s skills (optional)', { exact: true });
    const availableAgentSkills = await optionalSkillControl.locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    if (availableAgentSkills.length) {
      const alternateSkill = availableAgentSkills.find((value) => value !== 'architecture') || availableAgentSkills[0];
      await optionalSkillControl.selectOption(alternateSkill);
      await expect(assignment.getByRole('tab', { name: 'By skill', exact: true })).toHaveAttribute('aria-selected', 'true');
      await expect(assignment.getByLabel('Required skill', { exact: true })).toHaveValue(alternateSkill);
      const nextPinAgentPillGroup = assignment.locator('.kit-selector-pill-group[aria-label="Pin matching agent (optional)"]');
      const nextPinAgentSelect = assignment.locator('select[aria-label="Pin matching agent (optional)"]');
      if (await nextPinAgentPillGroup.count()) {
        await expect(nextPinAgentSelect).toHaveCount(0);
        await expect(nextPinAgentPillGroup.locator('.quickstart-chip[aria-pressed="true"]')).toHaveCount(1);
      } else {
        await expect(nextPinAgentSelect).toHaveValue(alternateAgent || initialPinnedAgentValue);
      }
      await expect(assignment.getByText('Matching agents', { exact: true })).toBeVisible();
    } else {
      await expect(assignment.getByText('Optional skill requirement')).toBeVisible();
    }
    const connectedAgent = await firstConnectedAgent(page);
    expect(connectedAgent.slug).toBeTruthy();
    await selectStep(page, 'plan_review');
    const reviewEntry = page.locator('.kit-protocol-segment-entry').filter({ has: page.getByTestId('workflow-stage-plan_review') }).first();
    await reviewEntry.getByRole('button', { name: 'Add below', exact: true }).click();
    await createStep(page, {
      name: 'Secondary Approval',
      key: 'secondary-approval',
      roleName: 'Secondary Approver',
      roleKey: 'secondary-approver',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
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
    const secondaryEditor = page.locator('.kit-stage-editor').last();
    await assertStandardAuthoringSurface(secondaryEditor);
    await secondaryEditor.getByRole('button', { name: 'Delete step', exact: true }).click();
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

  test('software engineering artifact edits keep architecture selected', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering', { expectedStageKeys: SOFTWARE_ENGINEERING_STAGE_KEYS });
    await page.getByRole('button', { name: 'Protocol settings', exact: true }).click();

    await addArtifact(page, {
      name: 'Architecture notes',
      path: 'docs/architecture-notes.md',
      kind: 'workspace_file',
    });
    await addArtifact(page, {
      name: 'Architecture review notes',
      path: 'docs/architecture-review.md',
      kind: 'workspace_file',
    });

    await selectStep(page, 'architecture');
    const selectedEntry = page.locator('.kit-protocol-segment-entry').filter({
      has: page.locator('[data-testid="workflow-stage-architecture"].is-selected'),
    }).first();
    const stageEditor = selectedEntry.locator('.kit-stage-editor').first();
    const artifactsSection = stageEditor.locator('.kit-stage-editor-section').filter({
      has: page.getByRole('heading', { name: 'Inputs and outputs', exact: true }),
    }).first();
    const summary = artifactsSection.locator('summary').first();
    if (await summary.count()) {
      const expanded = await summary.evaluate((node) => node.closest('details')?.open === true);
      if (!expanded) {
        await summary.click();
        await expect.poll(async () => summary.evaluate((node) => node.closest('details')?.open === true)).toBe(true);
      }
    }

    const readsRow = artifactsSection.locator('.kit-details-row').filter({ hasText: 'Needs from earlier steps' }).first();
    const writesRow = artifactsSection.locator('.kit-details-row').filter({ hasText: 'Produces for later steps' }).first();
    await artifactsSection.getByRole('button', { name: 'Edit workflow files and outputs', exact: true }).click();
    await expectSelectedStep(page, 'architecture');
    const localArtifactCatalog = artifactsSection.locator('.kit-protocol-inline-card').filter({
      has: page.getByRole('heading', { name: 'Workflow files and outputs', exact: true }),
    }).first();
    await expect(localArtifactCatalog).toBeVisible();
    await expect(page.locator('.kit-authoring-secondary-surface')).toHaveCount(0);
    await localArtifactCatalog.getByTestId('workflow-artifact-artifact_1').click();
    await expect(localArtifactCatalog.locator('.kit-stage-editor').first()).toContainText('Architecture notes');
    await localArtifactCatalog.getByRole('button', { name: 'Back to step', exact: true }).click();
    await expect(localArtifactCatalog).toHaveCount(0);
    await expectSelectedStep(page, 'architecture');

    await readsRow.getByLabel(/Architecture review notes/).check();
    await page.waitForTimeout(600);
    await waitForSaved(page);
    await expectSelectedStep(page, 'architecture');

    await writesRow.getByLabel(/Architecture notes/).check();
    await page.waitForTimeout(600);
    await waitForSaved(page);
    await expectSelectedStep(page, 'architecture');

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expectSelectedStep(page, 'architecture');

    const reloadedEntry = page.locator('.kit-protocol-segment-entry').filter({
      has: page.locator('[data-testid="workflow-stage-architecture"].is-selected'),
    }).first();
    const reloadedStageEditor = reloadedEntry.locator('.kit-stage-editor').first();
    const reloadedArtifactsSection = reloadedStageEditor.locator('.kit-stage-editor-section').filter({
      has: page.getByRole('heading', { name: 'Inputs and outputs', exact: true }),
    }).first();
    const reloadedSummary = reloadedArtifactsSection.locator('summary').first();
    if (await reloadedSummary.count()) {
      const expanded = await reloadedSummary.evaluate((node) => node.closest('details')?.open === true);
      if (!expanded) {
        await reloadedSummary.click();
        await expect.poll(async () => reloadedSummary.evaluate((node) => node.closest('details')?.open === true)).toBe(true);
      }
    }
    const reloadedReadsRow = reloadedArtifactsSection.locator('.kit-details-row').filter({ hasText: 'Needs from earlier steps' }).first();
    const reloadedWritesRow = reloadedArtifactsSection.locator('.kit-details-row').filter({ hasText: 'Produces for later steps' }).first();
    await expect(reloadedReadsRow.getByLabel(/Architecture review notes/)).toBeChecked();
    await expect(reloadedWritesRow.getByLabel(/Architecture notes/)).toBeChecked();

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
    await assertStandardAuthoringSurface(details);
    await expect(details).toContainText('Current assignment:');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('data analysis workflow can be authored, rehearsed, and executed through the standard UI', async ({ page }) => {
    test.setTimeout(240_000);
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openBlankDraft(page);
    const connectedAgent = await firstConnectedAgent(page);
    expect(connectedAgent.agentId).toBeTruthy();
    expect(connectedAgent.slug).toBeTruthy();

    await openProtocolSettings(page);
    for (const artifact of [
      { name: 'Source data', path: 'workspace/source-data.csv' },
      { name: 'Filtered data', path: 'workspace/filtered-data.csv' },
      { name: 'Analytics summary', path: 'workspace/analytics-summary.json' },
      { name: 'PDF report', path: 'workspace/report.pdf' },
      { name: 'Published report', path: 'workspace/published-report.json' },
    ]) {
      await addArtifact(page, artifact);
    }

    const loadKey = await createStep(page, {
      name: 'Load data',
      key: 'load-data',
      roleName: 'Data loader',
      roleKey: 'data-loader',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
      instructions: [
        'Create workspace/source-data.csv in the workspace.',
        'Write a small CSV with columns department,region,amount and at least four rows.',
        'Use realistic sample values so the next step can filter them.',
      ].join(' '),
    });
    const filterKey = await createStep(page, {
      name: 'Filter rows',
      key: 'filter-rows',
      roleName: 'Data filter',
      roleKey: 'data-filter',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
      instructions: [
        'Read workspace/source-data.csv and create workspace/filtered-data.csv.',
        'Keep only rows where region is west.',
        'Preserve the CSV header and write the filtered result for the next stage.',
      ].join(' '),
    });
    const analyzeKey = await createStep(page, {
      name: 'Run analytics',
      key: 'run-analytics',
      roleName: 'Data analyst',
      roleKey: 'data-analyst',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
      instructions: [
        'Read workspace/filtered-data.csv and create workspace/analytics-summary.json.',
        'Include row_count, total_amount, and average_amount in valid JSON.',
      ].join(' '),
    });
    const renderKey = await createStep(page, {
      name: 'Render report',
      key: 'render-report',
      roleName: 'Report renderer',
      roleKey: 'report-renderer',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
      instructions: [
        'Read workspace/analytics-summary.json and create workspace/report.pdf.',
        'It may be plain text content saved at that path.',
        'Summarize the analytics in a concise report body.',
      ].join(' '),
    });
    const publishKey = await createStep(page, {
      name: 'Publish report',
      key: 'publish-report',
      roleName: 'Report publisher',
      roleKey: 'report-publisher',
      selectorKind: 'agent',
      selectorValue: connectedAgent.slug,
      instructions: [
        'Read workspace/report.pdf and create workspace/published-report.json.',
        'Store a small JSON object with status, published_at, and report_path.',
      ].join(' '),
    });

    await connectStep(page, loadKey, filterKey);
    await connectStep(page, filterKey, analyzeKey);
    await connectStep(page, analyzeKey, renderKey);
    await connectStep(page, renderKey, publishKey);
    await connectStep(page, publishKey, '__complete__');

    await configureStepArtifacts(page, loadKey, { writes: ['Source data'] });
    await configureStepArtifacts(page, filterKey, { reads: ['Source data'], writes: ['Filtered data'] });
    await configureStepArtifacts(page, analyzeKey, { reads: ['Filtered data'], writes: ['Analytics summary'] });
    await configureStepArtifacts(page, renderKey, { reads: ['Analytics summary'], writes: ['PDF report'] });
    await configureStepArtifacts(page, publishKey, { reads: ['PDF report'], writes: ['Published report'] });

    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByLabel('Name').fill(`Data Analysis ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await lifecycle.getByRole('button', { name: 'Validate', exact: true }).click();
    await lifecycle.getByRole('button', { name: 'Publish', exact: true }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });
    const protocolId = protocolIdFromUrl(page.url());

    const scenarioIds = [];
    for (const payload of [
      {
        protocol_id: protocolId,
        stage_key: loadKey,
        participant_key: 'data-loader',
        display_name: 'Load data complete',
        decision: 'completed',
        decision_summary: 'Source data loaded.',
        response_text: 'Loaded the source CSV into the workspace for downstream processing.',
      },
      {
        protocol_id: protocolId,
        stage_key: filterKey,
        participant_key: 'data-filter',
        display_name: 'Filter rows complete',
        decision: 'completed',
        decision_summary: 'Rows filtered.',
        response_text: 'Filtered the dataset by the requested parameters and produced the filtered CSV.',
      },
      {
        protocol_id: protocolId,
        stage_key: analyzeKey,
        participant_key: 'data-analyst',
        display_name: 'Analytics complete',
        decision: 'completed',
        decision_summary: 'Analytics computed.',
        response_text: 'Computed the requested analytics and stored a structured summary.',
      },
      {
        protocol_id: protocolId,
        stage_key: renderKey,
        participant_key: 'report-renderer',
        display_name: 'Render report complete',
        decision: 'completed',
        decision_summary: 'PDF rendered.',
        response_text: 'Rendered the analytics summary into the templated PDF report.',
      },
      {
        protocol_id: protocolId,
        stage_key: publishKey,
        participant_key: 'report-publisher',
        display_name: 'Publish report complete',
        decision: 'completed',
        decision_summary: 'Report published.',
        response_text: 'Published the final report and recorded the publication result.',
      },
    ]) {
      const scenario = await createProtocolScenario(page, payload);
      scenarioIds.push(String(scenario.protocol_scenario_id || ''));
    }

    try {
      await page.getByRole('button', { name: 'Rehearse' }).click();
      await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
      const rehearsalRunId = await waitForLatestRehearsalRunId(page, protocolId);
      const rehearsalSequence = [
        [loadKey, 'Load data complete', filterKey],
        [filterKey, 'Filter rows complete', analyzeKey],
        [analyzeKey, 'Analytics complete', renderKey],
        [renderKey, 'Render report complete', publishKey],
        [publishKey, 'Publish report complete', 'completed'],
      ];
      for (const [stageKey, scenarioName, nextState] of rehearsalSequence) {
        await waitForRunStage(page, rehearsalRunId, stageKey);
        const session = page.locator('.kit-rehearsal-session').first();
        await expect(session).toContainText(stageKey);
        await applyScenarioAndSubmit(session, scenarioName);
        if (nextState === 'completed') {
          await waitForRunStatus(page, rehearsalRunId, 'completed');
        } else {
          await waitForRunStage(page, rehearsalRunId, nextState);
        }
      }

      const created = await createProtocolRun(page, {
        protocol_id: protocolId,
        entry_agent_id: connectedAgent.agentId,
        entry_authority_ref: 'protocol-ui-spec',
        workspace_ref: 'default',
        problem_statement: 'Process sample CSV data, compute basic west-region analytics, render a report, and publish the result.',
      });
      const runId = String(created.run?.protocol_run_id || '');
      expect(runId).toBeTruthy();
      await waitForRunStatus(page, runId, 'completed', 300000);
      const finalDetail = await getRunDetail(page, runId);
      expect(String(finalDetail.run?.status || '')).toBe('completed');
      expect(finalDetail.stage_executions.some((item) => String(item.stage_key || '') === publishKey)).toBe(true);
    } finally {
      for (const scenarioId of scenarioIds.reverse()) {
        if (scenarioId) {
          await deleteProtocolScenario(page, scenarioId);
        }
      }
    }

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('meta assistant flow composes a custom skill and a protocol through UI and APIs', async ({ page }) => {
    test.setTimeout(300_000);
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    const connectedAgent = await firstConnectedAgent(page);
    expect(connectedAgent.agentId).toBeTruthy();
    const lifecycleAgent = await firstSkillLifecycleAgent(page);
    expect(lifecycleAgent.agentId).toBeTruthy();

    const skillName = `meta-protocol-composer-${Date.now()}`;
    await createAndPublishCustomSkill(page, {
      agentId: lifecycleAgent.agentId,
      skillName,
      description: 'Guides a bot through assembling a protocol-driven assistant from a business goal.',
      body: [
        'Gather the business goal, identify missing capabilities, and outline the next protocol to create.',
        'Prefer concise workflow structure over long narrative text.',
        'When asked, propose the minimum viable stages, artifacts, and review loop.',
      ].join(' '),
    });

    await openBlankDraft(page);
    const composeKey = await createStep(page, {
      name: 'Compose assistant protocol',
      key: 'compose-assistant-protocol',
      roleName: 'Protocol composer',
      roleKey: 'protocol-composer',
      selectorKind: 'skill',
      selectorValue: '__first__',
      instructions: [
        `Use the published custom skill ${skillName} as one building block when outlining a new assistant workflow.`,
        'Return a concise protocol outline with the purpose, the minimum required stages, and the completion rule.',
        'End the response with PROTOCOL_SUMMARY: completed.',
      ].join(' '),
    });
    await connectStep(page, composeKey, '__complete__');
    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByLabel('Name').fill(`Meta Protocol Assistant ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await lifecycle.getByRole('button', { name: 'Validate', exact: true }).click();
    await lifecycle.getByRole('button', { name: 'Publish', exact: true }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });
    const protocolId = protocolIdFromUrl(page.url());

    const scenario = await createProtocolScenario(page, {
      protocol_id: protocolId,
      stage_key: composeKey,
      participant_key: 'protocol-composer',
      display_name: 'Compose assistant complete',
      decision: 'completed',
      decision_summary: 'Assistant protocol drafted.',
      response_text: `Drafted a concise assistant protocol outline using ${skillName} as part of the composition plan.`,
    });

    try {
      await page.getByRole('button', { name: 'Rehearse' }).click();
      await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
      const rehearsalRunId = await waitForLatestRehearsalRunId(page, protocolId);
      const session = page.locator(`.kit-rehearsal-session[data-stage-key="${composeKey}"]`).first();
      await expect(session).toBeVisible({ timeout: 20000 });
      await applyScenarioAndSubmit(session, 'Compose assistant complete');
      await waitForRunStatus(page, rehearsalRunId, 'completed');

      const created = await createProtocolRun(page, {
        protocol_id: protocolId,
        entry_agent_id: connectedAgent.agentId,
        entry_authority_ref: 'meta-assistant-ui',
        problem_statement: `Create a protocol-driven assistant outline using the published custom skill ${skillName}.`,
      });
      const runId = String(created?.run?.protocol_run_id || '');
      expect(runId).toBeTruthy();
      await waitForRunStatus(page, runId, 'completed', 180000);
      const finalDetail = await getRunDetail(page, runId);
      expect(String(finalDetail.run?.status || '')).toBe('completed');
      expect(finalDetail.stage_executions.some((item) => String(item.stage_key || '') === composeKey)).toBe(true);
    } finally {
      if (scenario?.protocol_scenario_id) {
        await deleteProtocolScenario(page, String(scenario.protocol_scenario_id || ''));
      }
    }

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
      height: element.getBoundingClientRect().height,
    }));
    expect(canvasOverflow.scrollWidth).toBeLessThanOrEqual(canvasOverflow.clientWidth + 2);
    expect(canvasOverflow.height).toBeGreaterThan(420);

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
