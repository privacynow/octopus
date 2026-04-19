const { test, expect } = require('./playwright-runtime');
const {
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
} = require('./helpers/protocol-helpers');

test.describe('protocol authoring live', () => {
  test('blank draft uses participant-first and step-first authoring flows', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openBlankDraft(page);

    const lifecycle = page.locator('.kit-lifecycle-header');
    await expect(lifecycle.getByLabel('Name')).toHaveValue('');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start the workflow');
    await expect(page.locator('.kit-workflow-first-run')).toContainText('Start by adding the first participant');

    await page.getByRole('button', { name: /\+ Add participant/i }).first().click();
    const participantEditor = page.locator('.kit-stage-editor').first();
    await expect(participantEditor.getByRole('heading', { name: 'Participant' })).toBeVisible();
    await expect(participantEditor.getByRole('heading', { name: 'Assignment rule' }).first()).toBeVisible();
    const strategy = participantEditor.getByLabel('Strategy');
    await expect(strategy).toContainText('Specific agent');
    await expect(strategy).toContainText('Required skill');
    await expect(strategy).not.toContainText('Runtime role tag');
    await expect(participantEditor.locator('.kit-selector-preview-input')).toHaveCount(0);
    await expect(participantEditor.locator('.kit-selector-preview-suggestions')).toHaveCount(0);
    await strategy.selectOption('agent');
    const agentPicker = participantEditor.getByLabel('Choose agent');
    await expect(agentPicker).toBeVisible();
    await expect(participantEditor.getByText('Rehearsal')).toHaveCount(0);
    await participantEditor.locator('summary').filter({ hasText: 'Advanced assignment' }).click();
    await expect(participantEditor.getByLabel('Advanced strategy')).toContainText('Runtime role tag');
    await page.getByRole('button', { name: 'Cancel' }).click();

    const plannerKey = await createParticipant(page, { name: 'Planner', key: 'planner' });
    await expect(page.getByText(/^participant_[0-9]+$/i)).toHaveCount(0);
    await expect(page.getByText(/^stage_[0-9]+$/i)).toHaveCount(0);

    const planKey = await createStep(page, { name: 'Plan', key: 'plan', ownerParticipant: plannerKey });
    const details = page.locator('.kit-details-panel').first();
    const stageEditor = page.locator('.kit-stage-editor-grid');
    await expect(details.getByLabel('Name')).toHaveValue('Plan');
    await expect(page.locator('.kit-stage-editor-section')).toHaveCount(5);
    await expect(page.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Instructions' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add route' }).first()).toBeVisible();

    const reviewerKey = await createParticipant(page, { name: 'Reviewer', key: 'reviewer' });
    const reviewKey = await createStep(page, {
      name: 'Review',
      key: 'review',
      ownerParticipant: reviewerKey,
      stageKind: 'review',
    });

    await connectStep(page, planKey, reviewKey);
    await page.getByTestId(`workflow-step-${planKey}`).click();
    await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();

    await connectStep(page, reviewKey, '__complete__');
    await page.getByTestId(`workflow-step-${reviewKey}`).click();
    await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel transition' })).toHaveCount(0);
    await page.getByTestId('workflow-step-review').click();
    await expect(details.getByLabel('Name')).toHaveValue('Review');

    await lifecycle.getByLabel('Name').fill(`Live Authoring ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await lifecycle.getByRole('button', { name: 'Protocol' }).click();
    await expect(lifecycle.getByLabel('URL slug')).not.toHaveValue('');

    await page.getByRole('button', { name: 'Validate' }).click();
    await page.getByRole('button', { name: 'Publish' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Published' })).toBeVisible({ timeout: 15000 });

    await page.getByRole('button', { name: 'Rehearse' }).click();
    await expect(page.locator('.kit-rehearsal-panel')).toBeVisible({ timeout: 15000 });
    await expect.poll(async () => page.locator('.kit-workflow-node-state').count(), { timeout: 15000 }).toBeGreaterThan(0);

    await lifecycle.getByRole('button', { name: 'Protocol' }).click();
    await page.getByRole('button', { name: 'Archive' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.kit-lifecycle-chip').filter({ hasText: 'Archived' })).toBeVisible({ timeout: 15000 });

    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template uses process view first and focuses local flow', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
    await expect(page.getByTestId('workflow-node-segment:planning')).toBeVisible({ timeout: 15000 });

    await page.getByTestId('workflow-node-segment:planning').click();
    await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
    await expect(page.getByRole('button', { name: 'Back to phases' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Visual map' })).toBeVisible();
    await expect(page.getByTestId('workflow-step-planning')).toBeVisible();
    await expect(page.getByTestId('workflow-step-plan_review')).toBeVisible();
    await expect(page.locator('.kit-details-panel').first().getByLabel('Name')).toHaveValue('Planning');

    await page.getByRole('button', { name: 'Visual map' }).click();
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Visual map');
    await expect(page.getByRole('button', { name: 'Fit' })).toBeVisible();
    await expect(page.getByRole('button', { name: '100%' })).toBeVisible();
    const labelOverlaps = await page.evaluate(() => {
      const edgeLabels = [...document.querySelectorAll('.kit-workflow-edge-label')].map((element) => ({
        id: element.getAttribute('data-testid') || element.textContent || 'edge-label',
        rect: element.getBoundingClientRect(),
      }));
      const nodes = [...document.querySelectorAll('.kit-workflow-node')].map((element) => ({
        id: element.getAttribute('data-testid') || element.getAttribute('data-node-id') || 'node',
        rect: element.getBoundingClientRect(),
      }));
      return edgeLabels.flatMap((label) =>
        nodes
          .filter((node) =>
            label.rect.left < node.rect.right
            && label.rect.right > node.rect.left
            && label.rect.top < node.rect.bottom
            && label.rect.bottom > node.rect.top)
          .map((node) => `${label.id}:${node.id}`));
    });
    expect(labelOverlaps).toEqual([]);

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('document approval template teaches participants and assignment rules without software ontology', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Document Approval');

    await expect(page.locator('.kit-protocol-detail-title')).toContainText('Draft Document');
    await expect(page.locator('.kit-workflow-viewbar')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toBeVisible();
    await expect(page.getByTestId('workflow-step-draft_document')).toBeVisible();
    await expect(page.getByText('Planner role')).toHaveCount(0);
    await expect(page.getByText('Reviewer role')).toHaveCount(0);

    await page.getByRole('button', { name: 'Author' }).first().click();
    const details = page.locator('.kit-stage-editor').first();
    await expect(details.getByRole('heading', { name: 'Participant' })).toBeVisible();
    await expect(details.getByRole('heading', { name: 'Assignment rule' }).first()).toBeVisible();
    const strategy = details.getByLabel('Strategy');
    await expect(strategy).toContainText('Specific agent');
    await expect(strategy).toContainText('Required skill');
    await expect(strategy).not.toContainText('Runtime role tag');
    await expect(details.getByText('Rehearsal')).toHaveCount(0);

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template stays usable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
    await expect(page.locator('.kit-workflow-process')).toBeVisible();
    const processOverflow = await page.locator('.kit-workflow-process').evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }));
    expect(processOverflow.scrollWidth).toBeLessThanOrEqual(processOverflow.clientWidth + 2);

    await page.getByTestId('workflow-node-segment:planning').click();
    await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
    await expect(page.locator('.kit-protocol-step-list')).toBeVisible();
    await page.getByTestId('workflow-step-planning').click();
    await expect(page.locator('.kit-stage-editor-grid')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Back to phases' })).toBeVisible();
    const compactOverlap = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('.kit-protocol-step-card')].map((element) => ({
        top: element.getBoundingClientRect().top,
        bottom: element.getBoundingClientRect().bottom,
      }));
      return cards.some((card, index) => index > 0 && card.top < cards[index - 1].bottom - 2);
    });
    expect(compactOverlap).toBeFalsy();

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('draft conflicts block lifecycle actions until reload or overwrite', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page, {
      ignoreConsole: [/409 \(Conflict\)/],
    });

    await login(page);
    await openBlankDraft(page);

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
    await expect(page.locator('.kit-validation')).toContainText('Overwrite');
    await expect(page.getByRole('button', { name: 'Validate' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Publish' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Rehearse' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Delete draft' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Reload' }).click();
    await expect(page.locator('.kit-draft-chip[data-state="saved"]')).toBeVisible({ timeout: 15000 });
    await expect(lifecycle.getByLabel('Name')).toHaveValue(serverDisplayName);

    const reloaded = await apiGetProtocol(api, protocolId);
    const newerServerName = `Server Truth Again ${Date.now()}`;
    const secondSave = await apiSaveProtocolDraft(api, protocolId, {
      slug: reloaded.protocol.slug,
      display_name: newerServerName,
      description: 'Second server-side conflict edit',
      definition_json: reloaded.draft_definition_json,
    }, reloaded.protocol.draft_revision);
    expect(secondSave.status).toBe(200);

    await lifecycle.getByLabel('Name').fill('Overwrite local change');
    await lifecycle.getByLabel('Name').blur();
    await expect(page.locator('.kit-draft-chip[data-state="conflict"]')).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: 'Overwrite' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.kit-draft-chip[data-state="saved"]')).toBeVisible({ timeout: 15000 });
    await expect(lifecycle.getByLabel('Name')).toHaveValue('Overwrite local change');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });
});
