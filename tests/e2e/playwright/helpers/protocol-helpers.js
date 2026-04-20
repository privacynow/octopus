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
  await expect(page.locator('.kit-workflow-canvas')).toBeVisible();
}

async function openTemplateDraft(page, templateName) {
  await page.goto('/ui/gallery', { waitUntil: 'domcontentloaded' });
  const templateCard = page.locator('.protocol-template-card').filter({ hasText: templateName }).first();
  await expect(templateCard).toBeVisible();
  await templateCard.getByRole('button', { name: 'Use template' }).click();
  await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);
}

async function createParticipant(page, { name, key = '', selectorKind = 'skill', selectorValue = '' }) {
  const participantKey = key || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!selectorValue) {
    throw new Error(`selectorValue is required when creating participant ${participantKey}`);
  }
  const protocolId = protocolIdFromUrl(page.url());
  const api = page.context().request;
  const draftPending = await page.locator('.kit-draft-chip[data-state="editing"], .kit-draft-chip[data-state="saving"]').count();
  if (draftPending) {
    await waitForSaved(page);
  }
  const detail = await apiGetProtocol(api, protocolId);
  const definition = JSON.parse(JSON.stringify(detail.draft_definition_json || {}));
  definition.participants = Array.isArray(definition.participants) ? definition.participants : [];
  definition.participants.push({
    participant_key: participantKey,
    display_name: name,
    selector: {
      kind: selectorKind,
      value: selectorValue,
    },
    instructions: '',
  });
  const save = await apiSaveProtocolDraft(api, protocolId, {
    slug: detail.protocol.slug,
    display_name: detail.protocol.display_name,
    description: detail.protocol.description,
    definition_json: definition,
  }, detail.protocol.draft_revision);
  expect(save.status).toBe(200);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('.kit-lifecycle-header')).toBeVisible();
  await expect(page.locator('.kit-workflow-canvas')).toBeVisible();
  return participantKey;
}

async function createStep(page, { name, key = '', ownerParticipant = '', stageKind = '' }) {
  await page.getByRole('button', { name: /\+ Add step/i }).first().click();
  const stageEditor = page.locator('.kit-stage-editor-grid');
  await expect(stageEditor).toBeVisible();
  await stageEditor.getByLabel('Name').fill(name);
  if (key) {
    await page.locator('details.kit-stage-editor-section.is-collapsible').first().evaluate((element) => {
      element.open = true;
    });
    await stageEditor.getByLabel('Key').fill(key);
  }
  if (ownerParticipant) {
    await stageEditor.getByLabel('Owning participant').selectOption(ownerParticipant);
  }
  if (stageKind) {
    await stageEditor.getByLabel('Stage type').selectOption(stageKind);
  }
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('.kit-details-panel button'))
      .find((node) => String(node.textContent || '').trim() === 'Create step');
    if (!button) {
      throw new Error('Create step button not found');
    }
    button.click();
  });
  const stageKey = key || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const node = page.getByTestId(`workflow-outline-${stageKey}`);
  await expect(node).toBeVisible();
  return stageKey;
}

async function connectStep(page, sourceStageKey, targetNodeId) {
  let stageNode = page.getByTestId(`workflow-outline-${sourceStageKey}`);
  if (!(await stageNode.count())) {
    const segmentNode = page.getByTestId(`workflow-outline-segment:${sourceStageKey}`);
    if (await segmentNode.count()) {
      await segmentNode.click();
      stageNode = page.getByTestId(`workflow-outline-${sourceStageKey}`);
    }
  }
  if (!(await stageNode.count())) {
    throw new Error(`workflow outline step missing for ${sourceStageKey}`);
  }
  await stageNode.click();
  await expect(page).toHaveURL(new RegExp(`stage_key=${sourceStageKey}`));
  const routingAdd = page.locator('.kit-stage-routing').getByRole('button', { name: 'Add route' }).first();
  const toolbarAdd = page.locator('.kit-workflow-toolbar').getByRole('button', { name: 'Add route' }).first();
  if (await routingAdd.count()) {
    await routingAdd.click();
  } else {
    await toolbarAdd.click();
  }
  const createRoute = page.getByRole('button', { name: 'Create route' });
  await expect(createRoute).toBeVisible();
  const routePanel = page.locator('.kit-details-panel').filter({ has: createRoute }).first();
  await expect(routePanel).toBeVisible();
  await routePanel.getByLabel('Next step').selectOption(targetNodeId);
  await createRoute.click();
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
  createParticipant,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
  openTemplateDraft,
  protocolIdFromUrl,
  waitForSaved,
};
