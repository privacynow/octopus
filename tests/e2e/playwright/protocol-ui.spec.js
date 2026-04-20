const { test, expect } = require('./playwright-runtime');
const {
  attachErrorCapture,
  connectStep,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
  openTemplateDraft,
  protocolIdFromUrl,
  waitForSaved,
} = require('./helpers/protocol-helpers');

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

    await page.getByRole('button', { name: /\+ Add step/i }).first().click();
    const stageEditor = page.locator('.kit-stage-editor').first();
    await expect(stageEditor.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(stageEditor.getByRole('heading', { name: 'New owner role' })).toBeVisible();
    await expect(stageEditor.getByRole('heading', { name: 'Assignment' }).first()).toBeVisible();
    const strategy = stageEditor.getByLabel('Strategy', { exact: true });
    await expect(strategy).toContainText('Specific agent');
    await expect(strategy).toContainText('Required skill');
    await expect(stageEditor.locator('.kit-selector-preview-input')).toHaveCount(0);
    await expect(stageEditor.locator('.kit-selector-preview-suggestions')).toHaveCount(0);
    await strategy.selectOption('agent');
    await expect(stageEditor.getByText('Rehearsal')).toHaveCount(0);
    await stageEditor.locator('summary').filter({ hasText: 'Advanced assignment' }).click();
    await expect(stageEditor.getByLabel('Advanced strategy')).toContainText('Runtime role tag');
    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByText(/^participant_[0-9]+$/i)).toHaveCount(0);
    await expect(page.getByText(/^stage_[0-9]+$/i)).toHaveCount(0);

    await page.getByRole('button', { name: /\+ Add step/i }).first().click();
    const draftAssignmentSection = page.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'Assignment', exact: true }) }).first();
    await draftAssignmentSection.getByLabel('Strategy', { exact: true }).selectOption('skill');
    const availableSkillValues = await draftAssignmentSection.getByLabel('Choose skill', { exact: true }).locator('option').evaluateAll((options) =>
      options.map((option) => String(option.value || '')).filter(Boolean),
    );
    expect(availableSkillValues.length).toBeGreaterThan(0);
    await page.getByRole('button', { name: 'Cancel' }).click();

    const planKey = await createStep(page, {
      name: 'Plan',
      key: 'plan',
      roleName: 'Planner',
      roleKey: 'planner',
      selectorKind: 'skill',
      selectorValue: '__first__',
    });
    const details = page.locator('.kit-details-panel').first();
    const planEditor = page.locator('.kit-stage-editor-grid');
    await expect(details.getByLabel('Name')).toHaveValue('Plan');
    await expect(page.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Assignment', exact: true })).toBeVisible();
    await expect(page.locator('.kit-stage-editor')).toContainText('Planner');
    await expect(page.locator('.kit-stage-editor')).toContainText('Required skill ·');
    await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Instructions' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add route' }).first()).toBeVisible();

    const reviewKey = await createStep(page, {
      name: 'Review',
      key: 'review',
      roleName: 'Reviewer',
      roleKey: 'reviewer',
      selectorKind: 'skill',
      selectorValue: '__first__',
      stageKind: 'review',
    });

    await connectStep(page, planKey, reviewKey);
    await page.getByTestId(`workflow-outline-${planKey}`).click();
    await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();

    await connectStep(page, reviewKey, '__complete__');
    await page.getByTestId(`workflow-outline-${reviewKey}`).click();
    await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();
    await page.getByTestId('workflow-outline-review').click();
    await expect(details.getByLabel('Name')).toHaveValue('Review');

    await lifecycle.getByLabel('Name').fill(`Live Authoring ${Date.now()}`);
    await lifecycle.getByLabel('Name').blur();
    await waitForSaved(page);
    await lifecycle.getByRole('button', { name: 'Protocol' }).click();
    await lifecycle.getByRole('button', { name: 'Protocol settings' }).click();
    await expect(page.locator('.kit-details-panel').getByLabel('Description')).toBeVisible();

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

  test('software engineering template opens into one workflow canvas with inspector', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
    const protocolId = protocolIdFromUrl(page.url());
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow canvas');
    await expect(page.locator('.kit-workflow-outline')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);
    await expect(page.getByTestId('workflow-outline-segment:planning')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('workflow-outline-plan_review')).toHaveCount(0);

    await page.getByTestId('workflow-outline-segment:planning').click();
    await expect(page.locator('.kit-protocol-segment-panel')).toContainText('Planning');
    await expect(page.locator('.kit-protocol-segment-step')).toHaveCount(2);
    await expect(page.getByTestId('workflow-outline-plan_review')).toBeVisible();

    await page.getByTestId('workflow-outline-planning').click();
    await expect(page.locator('.kit-details-panel').first().getByLabel('Name')).toHaveValue('Planning');
    await expect(page.locator('.kit-stage-editor')).toContainText('Required skill · Product Definition');
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: 'Fit', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-controls').getByRole('button', { name: '100%', exact: true })).toBeVisible();
    await expect(page.locator('.kit-workflow-cy-host')).toBeVisible();
    const toolbarInsert = page.locator('.kit-workflow-toolbar-actions').getByRole('button', { name: 'Insert after Planning', exact: true });
    await expect(toolbarInsert).toBeVisible();
    await toolbarInsert.click();
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
    expect(planning?.transitions?.completed).toBe('secondary-approval');
    expect(inserted?.transitions?.completed).toBe('architecture');
    expect(inserted?.selector?.kind).toBe('agent');
    expect(inserted?.selector?.value).toBe('lift-and-shift-m1-bot');
    expect(insertedIndex).toBeGreaterThan(-1);
    expect(architectureIndex).toBeGreaterThan(insertedIndex);

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('document approval template teaches step-owned assignment without a participant detour', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Document Approval');

    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow canvas');
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);
    await expect(page.getByTestId('workflow-outline-segment:draft_document')).toBeVisible();
    await expect(page.getByText('Planner role')).toHaveCount(0);
    await expect(page.getByText('Reviewer role')).toHaveCount(0);

    await page.getByTestId('workflow-outline-segment:draft_document').click();
    await expect(page.getByTestId('workflow-outline-draft_document')).toBeVisible();
    await page.getByTestId('workflow-outline-draft_document').click();
    const details = page.locator('.kit-stage-editor').first();
    await expect(details.getByRole('heading', { name: 'Assignment' }).first()).toBeVisible();
    const strategy = details.getByLabel('Strategy', { exact: true });
    await expect(strategy).toContainText('Specific agent');
    await expect(strategy).toContainText('Required skill');
    await expect(details.getByText('Rehearsal')).toHaveCount(0);
    await expect(details).toContainText('Required skill');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template stays usable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow canvas');
    await expect(page.locator('.kit-workflow-outline')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
    const canvasOverflow = await page.locator('.kit-workflow-viewport-cy').evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }));
    expect(canvasOverflow.scrollWidth).toBeLessThanOrEqual(canvasOverflow.clientWidth + 2);

    await page.getByTestId('workflow-outline-segment:planning').click();
    await expect(page.locator('.kit-protocol-segment-panel')).toContainText('Planning');
    await page.getByTestId('workflow-outline-planning').click();
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
