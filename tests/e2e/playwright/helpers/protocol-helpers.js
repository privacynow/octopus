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

async function waitForSaved(page) {
  await expect(page.locator('.kit-draft-chip[data-state="saved"]')).toBeVisible({ timeout: 15000 });
}

async function openBlankDraft(page) {
  await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New protocol' }).click();
  await expect(page).toHaveURL(/\/ui\/protocols\?.*protocol_id=/);
  await expect(page.locator('.kit-authoring-primary-column')).toBeVisible();
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
  openEditor = true,
} = {}) {
  if (openEditor) {
    const inlineAdd = page
      .locator('.kit-protocol-segment-entry')
      .filter({ has: page.locator('.kit-protocol-segment-step.is-selected') })
      .getByRole('button', { name: 'Add below', exact: true })
      .first();
    if (await inlineAdd.count() && await inlineAdd.isVisible().catch(() => false)) {
      await inlineAdd.click();
    } else {
      const addStep = page.getByRole('button', { name: /(\+ )?Add (first )?step/i }).first();
      if (await addStep.count() && await addStep.isVisible().catch(() => false)) {
        await addStep.click();
      } else {
        await page.getByRole('button', { name: 'Add below', exact: true }).first().click();
      }
    }
  }
  const stageEditorShell = page
    .locator('.kit-stage-editor')
    .filter({ has: page.getByRole('button', { name: 'Create step', exact: true }) })
    .last();
  await expect(stageEditorShell).toBeVisible();
  const stageEditor = stageEditorShell.locator('.kit-stage-editor-grid');
  const stepBasics = stageEditorShell
    .locator('.kit-stage-editor-section')
    .filter({ has: page.getByRole('heading', { name: 'Step basics', exact: true }) })
    .first();
  await stepBasics.getByLabel('Name').first().fill(name);
  const ownerRoleSelect = stepBasics.getByLabel('Owner role').first();
  if (ownerRole) {
    await ownerRoleSelect.selectOption(ownerRole);
  } else {
    const roleSection = stageEditorShell
      .locator('.kit-stage-editor-section')
      .filter({ has: page.getByRole('heading', { name: 'New owner role', exact: true }) })
      .first();
    const roleNameControl = roleSection.getByLabel('Role name').first();
    await expect(roleNameControl).toBeVisible();
    await roleNameControl.fill(roleName || `${name} role`);
    if (roleKey) {
      await roleSection.getByLabel('Role key').first().fill(roleKey);
    }
  }
  if (stageKind) {
    await stepBasics.getByLabel('Stage type').first().selectOption(stageKind);
  }
  if (!selectorValue) {
    throw new Error(`selectorValue is required when creating step ${key || name}`);
  }
  const valueLabel = selectorKind === 'agent' ? 'Pinned agent' : selectorKind === 'skill' ? 'Required skill' : 'Choose runtime role tag';
  const assignmentSection = stageEditorShell
    .locator('.kit-stage-editor-section')
    .filter({ has: page.getByRole('heading', { name: 'Assignment', exact: true }) })
    .first();
  const valueControl = assignmentSection.getByLabel(valueLabel, { exact: true }).first();
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
    await valueControl.selectOption(targetValue);
  } else {
    await valueControl.fill(selectorValue);
    await valueControl.blur();
  }
  await page.waitForTimeout(150);
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
  if (!alreadySelected) {
    await node.click();
  }
}

async function connectStep(page, sourceStageKey, targetNodeId) {
  await selectStep(page, sourceStageKey);
  await expect(page).toHaveURL(new RegExp(`stage_key=${sourceStageKey}`));
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
  attachErrorCapture,
  connectStep,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
  openTemplateDraft,
  outlineStepNode,
  protocolIdFromUrl,
  selectStep,
  waitForSaved,
};
