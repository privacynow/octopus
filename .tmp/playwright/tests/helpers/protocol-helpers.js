const fs = require('fs');
const { expect } = require('@playwright/test');

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
  await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);
  await expect(page.locator('.kit-protocol-detail, .kit-workflow-canvas')).toBeVisible();
}

async function createRole(page, { name, key = '', selectorValue = '' }) {
  await page.getByRole('button', { name: /\+ Add role/i }).first().click();
  const details = page.locator('.kit-details-panel').first();
  await expect(details).toBeVisible();
  await details.getByLabel('Name').fill(name);
  if (key) {
    await details.getByLabel('Key').fill(key);
  }
  if (selectorValue) {
    await details.getByLabel('Rule value').fill(selectorValue);
  }
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    const button = Array.from(document.querySelectorAll('.kit-details-panel button'))
      .find((node) => String(node.textContent || '').trim() === 'Create role');
    if (!button) {
      throw new Error('Create role button not found');
    }
    button.click();
  });
  const laneKey = key || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  await expect(page.locator('.kit-details-panel').first().getByLabel('Name')).toHaveValue(name);
  return laneKey;
}

async function createStep(page, { name, key = '', ownerRole = '', stageKind = '' }) {
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
  if (ownerRole) {
    await stageEditor.getByLabel('Owning role').selectOption(ownerRole);
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
  const node = page.getByTestId(`workflow-node-${stageKey}`);
  await expect(node).toBeVisible();
  return stageKey;
}

async function connectStep(page, sourceStageKey, targetNodeId) {
  await page.getByTestId(`workflow-step-${sourceStageKey}`).click();
  const addRoute = page.getByRole('button', { name: 'Add route' }).first();
  await expect(addRoute).toBeVisible();
  await addRoute.click();
  const routePanel = page.locator('.kit-details-panel').first();
  await expect(routePanel).toBeVisible();
  await routePanel.locator('select').last().selectOption(targetNodeId);
  await page.getByRole('button', { name: 'Create route' }).click();
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
  createRole,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
  protocolIdFromUrl,
  waitForSaved,
};
