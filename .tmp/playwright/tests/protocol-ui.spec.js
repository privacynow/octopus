const { test, expect } = require('@playwright/test');
const fs = require('fs');

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

async function discardDraft(page) {
  const deleteBtn = page.getByRole('button', { name: 'Delete draft' });
  if (await deleteBtn.count()) {
    await deleteBtn.click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page).toHaveURL(/\/ui\/protocols(\?.*)?$/);
  }
}

test.describe('protocol authoring live', () => {
  test('gallery blank draft uses clean URL and empty first-run fields', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await page.goto('/ui/gallery', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: 'Gallery' })).toBeVisible();
    await page.getByRole('button', { name: 'Start blank' }).click();
    await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);
    await expect(page).not.toHaveURL(/protocol_view=/);
    await expect(page.locator('.kit-workflow-canvas')).toBeVisible();

    const lifecycle = page.locator('.kit-lifecycle-header');
    await expect(lifecycle.getByLabel('Name')).toHaveValue('');
    await expect(lifecycle.getByLabel('URL slug')).toHaveValue('');
    await expect(lifecycle.getByLabel('Name')).toHaveAttribute('placeholder', /workflow/i);
    await expect(lifecycle.getByLabel('URL slug')).toHaveAttribute('placeholder', /url/i);

    await expect(page.locator('.kit-workflow-first-run')).toContainText('Add the first participant');
    await page.getByRole('button', { name: /Add participant/i }).first().click();
    await expect(page.getByTestId('workflow-lane-participant_1')).toBeVisible();
    await expect(page.locator('.kit-selector-preview-suggestions')).toBeVisible();
    await expect(page.locator('.kit-selector-preview-suggestions .quickstart-chip').first()).toBeVisible();

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('draft conflicts surface reload-first resolution and block lifecycle actions', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page, {
      ignoreConsole: [/409 \(Conflict\)/],
    });

    await login(page);
    await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'New protocol' }).click();
    await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByLabel('Name').fill(`Conflict Draft ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);

    const protocolId = protocolIdFromUrl(page.url());
    const api = page.context().request;
    const detail = await apiGetProtocol(api, protocolId);
    const serverDisplayName = `Server Truth ${Date.now()}`;
    const serverSave = await apiSaveProtocolDraft(api, protocolId, {
      slug: detail.protocol.slug,
      display_name: serverDisplayName,
      description: 'Server-side conflict edit',
      definition_json: detail.draft_definition_json,
    }, detail.protocol.draft_revision);
    expect(serverSave.status).toBe(200);

    await lifecycle.getByLabel('Name').fill('Local conflicting change');
    await lifecycle.getByLabel('Name').blur();
    await expect(page.locator('.kit-draft-chip[data-state="conflict"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.kit-validation')).toContainText('Reload');
    await expect(page.getByRole('button', { name: 'Validate' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Publish' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Reload' }).click();
    await expect(page.locator('.kit-draft-chip[data-state="saved"]')).toBeVisible({ timeout: 15000 });
    await expect(lifecycle.getByLabel('Name')).toHaveValue(serverDisplayName);

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('blank protocol authoring supports graph flow, publish, and rehearse overlay', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'New protocol' }).click();
    await expect(page).toHaveURL(/\/ui\/protocols\?protocol_id=/);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await lifecycle.getByLabel('Name').fill(`Playwright Protocol ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await expect(lifecycle.getByLabel('URL slug')).not.toHaveValue('');

    await page.getByRole('button', { name: /Add participant/i }).first().click();
    const participantPanel = page.locator('.kit-details-panel').first();
    await expect(page.locator('.kit-selector-preview-suggestions .quickstart-chip').first()).toBeVisible();
    await page.locator('.kit-selector-preview-suggestions .quickstart-chip').first().click();
    await expect(page.locator('.kit-selector-preview')).toBeVisible();
    await expect(participantPanel.getByLabel('Name')).not.toHaveValue('');
    await participantPanel.getByLabel('Key').fill('planner');
    await participantPanel.getByLabel('Key').blur();

    await page.getByRole('button', { name: /Add stage/i }).first().click();
    await page.getByTestId('workflow-node-stage_1').click();
    const stagePanel = page.locator('.kit-details-panel').first();
    await stagePanel.getByLabel('Name').fill('Plan');
    await stagePanel.getByLabel('Name').blur();
    await stagePanel.getByLabel('Key').fill('plan');
    await stagePanel.getByLabel('Key').blur();

    await page.getByRole('button', { name: /Add stage/i }).first().click();
    await page.getByTestId('workflow-node-stage_2').click();
    await stagePanel.getByLabel('Name').fill('Review');
    await stagePanel.getByLabel('Name').blur();
    await stagePanel.getByLabel('Key').fill('review');
    await stagePanel.getByLabel('Key').blur();

    await page.getByTestId('workflow-node-plan').click();
    await stagePanel.getByRole('button', { name: 'Add transition' }).click();
    await page.getByTestId('workflow-node-review').click();
    await expect(page.getByTestId('workflow-edge-plan::completed')).toBeVisible();

    await page.getByTestId('workflow-node-review').click();
    await stagePanel.getByRole('button', { name: 'Add transition' }).click();
    await page.getByTestId('workflow-node-__complete__').click();
    await expect(page.getByTestId('workflow-edge-review::completed')).toBeVisible();

    const graphMetrics = await page.locator('.kit-workflow-graph').evaluate((graph) => {
      const nodes = Array.from(graph.querySelectorAll('.kit-workflow-node-wrap')).map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          id: String(node.getAttribute('data-node-id') || ''),
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
        };
      });
      const overlaps = [];
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const horizontal = Math.min(nodes[i].right, nodes[j].right) - Math.max(nodes[i].left, nodes[j].left);
          const vertical = Math.min(nodes[i].bottom, nodes[j].bottom) - Math.max(nodes[i].top, nodes[j].top);
          if (horizontal > 6 && vertical > 6) {
            overlaps.push([nodes[i].id, nodes[j].id]);
          }
        }
      }
      return {
        width: graph.scrollWidth,
        height: graph.scrollHeight,
        overlaps,
      };
    });
    expect(graphMetrics.width).toBeGreaterThan(1200);
    expect(graphMetrics.height).toBeGreaterThan(420);
    expect(graphMetrics.overlaps).toEqual([]);
    await waitForSaved(page);

    await page.getByRole('button', { name: 'Validate' }).click();
    await expect(page.locator('.kit-validation-ok')).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: 'Publish' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });

    await page.getByRole('button', { name: 'Rehearse' }).click();
    await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
    await expect.poll(async () => page.locator('.kit-workflow-node-state').count(), { timeout: 15000 }).toBeGreaterThan(0);

    await page.getByRole('button', { name: 'Archive' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Archived' })).toBeVisible({ timeout: 15000 });

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });
});
