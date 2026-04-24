const fs = require('fs');
const { expect } = require('../playwright-runtime');

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

function protocolIdFromUrl(urlText) {
  const url = new URL(urlText);
  const value = String(url.searchParams.get('protocol_id') || '').trim();
  if (!value) {
    throw new Error(`protocol_id missing from URL: ${urlText}`);
  }
  return value;
}

function attachErrorCapture(page, { ignoreConsole = [] } = {}) {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (ignoreConsole.some((pattern) => pattern.test(text))) return;
    consoleErrors.push(text);
  });
  page.on('pageerror', (err) => {
    pageErrors.push(String(err));
  });
  return { consoleErrors, pageErrors };
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

async function firstExecutionReadyAgent(page, { preferredProvider = 'codex' } = {}) {
  return page.evaluate(async ({ preferredProviderName }) => {
    const response = await fetch('/v1/agents?state=connected&limit=100', { credentials: 'same-origin' });
    const payload = await response.json();
    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const normalized = agents.map((agent) => {
      const tags = Array.isArray(agent?.tags) ? agent.tags : [];
      const workspaceTag = tags.find((tag) => String(tag || '').startsWith('workspace:'));
      return {
        agentId: String(agent?.agent_id || ''),
        slug: String(agent?.slug || ''),
        provider: String(agent?.provider || '').trim().toLowerCase(),
        connectivityState: String(agent?.connectivity_state || '').trim().toLowerCase(),
        executionState: String(agent?.execution_state || 'healthy').trim().toLowerCase(),
        workspaceRef: workspaceTag ? String(workspaceTag).split(':').slice(1).join(':').trim() : '',
      };
    }).filter((agent) => agent.agentId && agent.slug);
    const connected = normalized.filter((agent) => agent.connectivityState === 'connected');
    const executionReady = connected.filter((agent) => !['faulted', 'degraded'].includes(agent.executionState));
    const preferred = executionReady.filter((agent) => agent.provider === String(preferredProviderName || '').trim().toLowerCase());
    return preferred[0] || executionReady[0] || connected[0] || normalized[0] || {
      agentId: '',
      slug: '',
      provider: '',
      connectivityState: '',
      executionState: '',
      workspaceRef: '',
    };
  }, { preferredProviderName: preferredProvider });
}

async function apiCsrf(api) {
  const resp = await api.get('/v1/auth/csrf');
  expect(resp.ok()).toBeTruthy();
  const payload = await resp.json();
  return String(payload.csrf_token || payload.token || '').trim();
}

async function apiGetProtocol(api, protocolId) {
  const resp = await api.get(`/v1/protocols/${encodeURIComponent(protocolId)}`);
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

async function apiSaveProtocolDraft(api, protocolId, body, revision) {
  const csrf = await apiCsrf(api);
  const resp = await api.put(`/v1/protocols/${encodeURIComponent(protocolId)}/draft`, {
    headers: {
      'X-CSRF-Token': csrf,
      'If-Match': String(revision),
      'Content-Type': 'application/json',
    },
    data: JSON.stringify(body),
    failOnStatusCode: false,
  });
  const payload = await resp.json();
  return { status: resp.status(), payload };
}

async function assertStandardAuthoringSurface(stageEditor, { expectDelete = true } = {}) {
  await expect(stageEditor.locator('summary').filter({ hasText: 'Custom runtime selector' })).toHaveCount(0);
  await expect(stageEditor.getByRole('heading', { name: 'Advanced', exact: true })).toHaveCount(0);
  await expect(stageEditor.getByLabel('Custom selector type')).toHaveCount(0);
  await expect(stageEditor.getByLabel('Stage key')).toHaveCount(0);
  await expect(stageEditor.getByLabel('Max rounds')).toHaveCount(0);
  await expect(stageEditor.getByLabel('Timeout seconds')).toHaveCount(0);
  const stageSurface = stageEditor.locator('xpath=ancestor-or-self::*[contains(concat(" ", normalize-space(@class), " "), " kit-protocol-segment-entry ")][1]');
  if (expectDelete) {
    if (await stageSurface.count()) {
      await expect(stageSurface.getByRole('button', { name: 'Delete step', exact: true })).toBeVisible();
    } else {
      await expect(stageEditor.getByRole('button', { name: 'Delete step', exact: true })).toBeVisible();
    }
  } else {
    await expect(stageEditor.getByRole('button', { name: 'Delete step', exact: true })).toHaveCount(0);
  }
}

async function waitForSaved(page) {
  await expect(page.locator('.kit-draft-chip[data-state="saved"]')).toBeVisible({ timeout: 15000 });
}

async function openStagePanel(page, stageEditorShell, {
  tab,
  heading = tab,
} = {}) {
  const panelKeyByLabel = {
    Basics: 'basics',
    'Step basics': 'basics',
    Assignment: 'assignment',
    Routing: 'routing',
    Instructions: 'instructions',
    'Files & outputs': 'artifacts',
    'Inputs and outputs': 'artifacts',
    Advanced: 'advanced',
  };
  const panelTab = stageEditorShell.getByRole('tab', { name: tab, exact: true });
  if (await panelTab.count()) {
    await expect(panelTab).toBeVisible();
    const isActive = await panelTab.evaluate((element) => element.classList.contains('active'));
    if (!isActive) {
      await panelTab.click();
    }
  }
  const panelKey = panelKeyByLabel[String(heading || tab || '').trim()] || panelKeyByLabel[String(tab || '').trim()] || '';
  if (panelKey) {
    const workspace = stageEditorShell.locator(`.kit-stage-editor-grid[data-panel="${panelKey}"]`).first();
    if (await workspace.count()) {
      await expect(workspace).toBeVisible();
      return workspace;
    }
  }
  const section = stageEditorShell.locator('.kit-stage-editor-section').filter({
    has: page.getByRole('heading', { name: heading, exact: true }),
  }).first();
  await expect(section).toBeVisible();
  return section;
}

async function setSelectValue(control, value) {
  const targetValue = String(value || '');
  await expect(control).toBeVisible();
  const options = await control.locator('option').evaluateAll((nodes) =>
    nodes.map((node) => String(node.value || '')),
  );
  if (!options.includes(targetValue)) {
    throw new Error(`Select value "${targetValue}" is not available. Options: ${options.join(', ')}`);
  }
  await control.evaluate((element, nextValue) => {
    const select = /** @type {HTMLSelectElement} */ (element);
    select.value = String(nextValue || '');
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }, targetValue);
}

async function openBlankDraft(page) {
  await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New protocol' }).click();
  await expect(page).toHaveURL(/\/ui\/protocols\?.*protocol_id=/);
  await expect(page.locator('.kit-authoring-primary-column')).toBeVisible();
}

async function openConversationForAgentFromUi(page, agentId) {
  await page.goto(`/ui/agents/${encodeURIComponent(String(agentId || '').trim())}`, { waitUntil: 'domcontentloaded' });
  const openConversation = page.getByRole('button', { name: 'Open conversation', exact: true });
  await expect(openConversation).toBeVisible({ timeout: 15000 });
  await openConversation.click();
  await expect(page).toHaveURL(/\/ui\/conversations\//, { timeout: 15000 });
  await expect(page.locator('.conversation-page')).toBeVisible({ timeout: 15000 });
}

async function openTemplateDraft(page, templateName, { expectedStageKeys = [], retry = true } = {}) {
  await page.goto('/ui/gallery', { waitUntil: 'domcontentloaded' });
  const templateCard = page.locator('.protocol-template-card').filter({ hasText: templateName }).first();
  await expect(templateCard).toBeVisible();
  await templateCard.getByRole('button', { name: 'Use template' }).click();
  await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);
  if (expectedStageKeys.length) {
    await expect(page.locator('[data-testid^="workflow-stage-"]').first()).toBeVisible({ timeout: 15000 });
    const actualStageKeys = await page.locator('[data-testid^="workflow-stage-"]').evaluateAll((nodes) =>
      Array.from(new Set(nodes
        .map((node) => String(node.getAttribute('data-testid') || '').replace('workflow-stage-', ''))
        .filter(Boolean))),
    );
    const expected = [...expectedStageKeys].sort();
    const actual = [...actualStageKeys].sort();
    const matches = expected.length === actual.length && expected.every((value, index) => value === actual[index]);
    if (!matches && retry) {
      await discardDraft(page);
      await openTemplateDraft(page, templateName, { expectedStageKeys, retry: false });
    }
  }
}

async function createStep(page, {
  name,
  key = '',
  ownerRole = '',
  roleName = '',
  roleKey = '',
  selectorKind = 'skill',
  selectorValue = '',
  stageKind = '',
  instructions = '',
  openEditor = true,
} = {}) {
  if (openEditor) {
    const activeStage = page
      .locator('.kit-protocol-segment-entry')
      .filter({ has: page.locator('.kit-protocol-segment-step.is-selected') })
      .first();
    const inlineAdd = page
      .locator('.kit-protocol-segment-entry')
      .filter({ has: page.locator('.kit-protocol-segment-step.is-selected') })
      .locator('[data-testid^="workflow-insert-after-"]')
      .first();
    if (await inlineAdd.count() && await inlineAdd.isVisible().catch(() => false)) {
      await inlineAdd.click();
    } else {
      const addStep = page.getByRole('button', { name: /(\+ )?Add (first )?step/i }).first();
      if (await addStep.count() && await addStep.isVisible().catch(() => false)) {
        await addStep.click();
      } else if (await activeStage.count()) {
        await activeStage.getByRole('button', { name: /Add step below/i }).first().click();
      } else {
        await page.getByRole('button', { name: /Add step below/i }).first().click();
      }
    }
  }
  const stageEditorShell = page
    .locator('.kit-stage-editor')
    .filter({ has: page.getByRole('button', { name: 'Create step', exact: true }) })
    .last();
  await expect(stageEditorShell).toBeVisible();
  const stepBasics = await openStagePanel(page, stageEditorShell, {
    tab: 'Basics',
    heading: 'Step basics',
  });
  const stepNameControl = stepBasics.locator('input, textarea').first();
  await expect(stepNameControl).toBeVisible();
  await stepNameControl.fill(name);
  const ownerRoleSelect = stepBasics.getByLabel('Owner role').first();
  if (ownerRole) {
    await setSelectValue(ownerRoleSelect, ownerRole);
  } else {
    const roleNameControl = stepBasics.getByLabel('Role name').first();
    await expect(roleNameControl).toBeVisible();
    await roleNameControl.fill(roleName || `${name} role`);
    if (roleKey) {
      await stepBasics.getByLabel('Role key').first().fill(roleKey);
    }
  }
  if (stageKind) {
    await setSelectValue(stepBasics.getByLabel('Stage type').first(), stageKind);
  }
  if (!selectorValue) {
    throw new Error(`selectorValue is required when creating step ${key || name}`);
  }
  const assignmentSection = await openStagePanel(page, stageEditorShell, {
    tab: 'Assignment',
    heading: 'Assignment',
  });
  const valueLabel = selectorKind === 'agent'
    ? 'Agent'
    : selectorKind === 'skill'
      ? 'Required skill'
      : 'Choose runtime role tag';
  if (selectorKind === 'agent' || selectorKind === 'skill') {
    const modeLabel = selectorKind === 'agent' ? 'Specific agent' : 'By skill';
    const modeTab = assignmentSection.getByRole('tab', { name: modeLabel, exact: true });
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await modeTab.click();
      const valueCount = await assignmentSection.getByLabel(valueLabel, { exact: true }).count();
      if (valueCount) {
        break;
      }
      await page.waitForTimeout(100);
    }
  } else {
    const advanced = assignmentSection.locator('summary').filter({ hasText: 'Custom runtime selector' }).first();
    if (await advanced.count()) {
      await advanced.click();
    }
  }
  const valueControl = assignmentSection.getByLabel(valueLabel, { exact: true }).first();
  await expect(valueControl).toBeVisible();
  const valueTag = await valueControl.evaluate((element) => element.tagName.toLowerCase());
  if (valueTag === 'select') {
    let targetValue = selectorValue;
    if (selectorValue === '__first__') {
      targetValue = await valueControl.locator('option').evaluateAll((options) =>
        options.map((option) => String(option.value || '')).find((value) => value),
      );
      if (!targetValue) {
        throw new Error(`No selectable ${selectorKind} option is available for ${key || name}`);
      }
    }
    await setSelectValue(valueControl, targetValue);
  } else {
    await valueControl.fill(selectorValue);
    await valueControl.blur();
  }
  await page.waitForTimeout(150);
  if (instructions) {
    const instructionsSection = await openStagePanel(page, stageEditorShell, {
      tab: 'Instructions',
      heading: 'Instructions',
    });
    await instructionsSection.getByLabel('Instructions').fill(instructions);
  }
  await stageEditorShell.getByRole('button', { name: 'Create step', exact: true }).click();
  const stageKey = key || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const node = await outlineStepNode(page, stageKey);
  await expect(node).toBeVisible();
  await waitForSaved(page);
  return stageKey;
}

async function outlineStepNode(page, stageKey) {
  const stageNode = page.getByTestId(`workflow-stage-${stageKey}`);
  await expect(stageNode).toHaveCount(1, { timeout: 15000 });
  return stageNode.first();
}

async function selectStep(page, stageKey) {
  const node = await outlineStepNode(page, stageKey);
  await node.scrollIntoViewIfNeeded();
  await expect(node).toBeVisible();
  const alreadySelected = await node.evaluate((element) => element.classList.contains('is-selected'));
  const onStagePanel = new RegExp(`stage_key=${stageKey}(?:&|$)`).test(page.url());
  if (!alreadySelected || !onStagePanel) {
    await node.click();
  }
  await expectSelectedStep(page, stageKey);
}

async function expectSelectedStep(page, stageKey) {
  const node = await outlineStepNode(page, stageKey);
  await expect(node).toHaveClass(/is-selected/);
  await expect(page).toHaveURL(new RegExp(`stage_key=${stageKey}`));
  const selectedEntry = page.locator('.kit-protocol-segment-entry').filter({
    has: page.locator(`[data-testid="workflow-stage-${stageKey}"].is-selected`),
  }).first();
  await expect(selectedEntry.locator('.kit-stage-editor').first()).toBeVisible();
}

async function ensureDetailsOpen(section) {
  const summary = section.locator('summary').first();
  if (!(await summary.count())) return;
  const expanded = await summary.evaluate((node) => node.closest('details')?.open === true);
  if (expanded) return;
  await summary.click();
  await expect.poll(async () => summary.evaluate((node) => node.closest('details')?.open === true)).toBe(true);
}

async function openProtocolSettings(page) {
  const lifecycle = page.locator('.kit-lifecycle-header');
  await lifecycle.getByRole('button', { name: 'Protocol' }).click();
  await lifecycle.getByRole('button', { name: 'Protocol settings' }).click();
  await expect(page.locator('.kit-protocol-inline-card').getByLabel('Description')).toBeVisible();
}

async function openWorkflowMap(page) {
  const button = page.getByRole('button', { name: 'Show workflow map', exact: true });
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.locator('.kit-authoring-secondary-surface .kit-workflow-canvas')).toBeVisible();
}

async function backToWorkflow(page) {
  const surface = page.locator('.kit-authoring-secondary-surface').first();
  if (!(await surface.count())) return;
  const button = surface.getByRole('button', { name: 'Back to workflow', exact: true }).first();
  if (!(await button.count())) return;
  await button.click();
  await expect(surface).toHaveCount(0);
}

async function connectStep(page, sourceStageKey, targetNodeId) {
  await selectStep(page, sourceStageKey);
  await expect(page).toHaveURL(new RegExp(`stage_key=${sourceStageKey}`));
  const stageEditor = page.locator('.kit-stage-editor').last();
  const routingSection = await openStagePanel(page, stageEditor, {
    tab: 'Routing',
    heading: 'Routing',
  });
  const branchAdd = page.locator('.kit-stage-routing').getByRole('button', { name: 'Add branch or finish' }).first();
  await expect(branchAdd).toBeVisible();
  await branchAdd.click();
  const saveBranch = page.getByRole('button', { name: 'Save branch' });
  await expect(saveBranch).toBeVisible();
  const routePanel = page.locator('.kit-details-panel').filter({ has: saveBranch }).first();
  await expect(routePanel).toBeVisible();
  await routePanel.getByLabel('Go to').selectOption(targetNodeId);
  await saveBranch.click();
}

async function discardDraft(page) {
  const deleteBtn = page.getByRole('button', { name: 'Delete draft' });
  if (await deleteBtn.count()) {
    await deleteBtn.click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page).toHaveURL(/\/ui\/protocols(\?.*)?$/);
  }
}

module.exports = {
  apiGetProtocol,
  apiSaveProtocolDraft,
  assertStandardAuthoringSurface,
  attachErrorCapture,
  backToWorkflow,
  connectStep,
  createStep,
  discardDraft,
  ensureDetailsOpen,
  firstExecutionReadyAgent,
  login,
  openBlankDraft,
  openConversationForAgentFromUi,
  openStagePanel,
  openProtocolSettings,
  openTemplateDraft,
  openWorkflowMap,
  outlineStepNode,
  protocolIdFromUrl,
  expectSelectedStep,
  setSelectValue,
  selectStep,
  waitForSaved,
};
