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
    const stageEditor = page.locator('.kit-stage-editor').last();
    await expect(stageEditor.getByRole('heading', { name: 'Step basics' })).toBeVisible();
    await expect(stageEditor.getByRole('heading', { name: 'New owner role' })).toBeVisible();
    const assignmentHeading = stageEditor.getByRole('heading', { name: 'Assignment' }).first();
    await assignmentHeading.scrollIntoViewIfNeeded();
    await expect(assignmentHeading).toBeVisible();
    await expect(stageEditor.getByLabel('Required skill', { exact: true })).toBeVisible();
    await expect(stageEditor.getByLabel('Pinned agent', { exact: true })).toBeVisible();
    await expect(stageEditor.locator('.kit-selector-preview-input')).toHaveCount(0);
    await expect(stageEditor.locator('.kit-selector-preview-suggestions')).toHaveCount(0);
    await expect(stageEditor.getByText('Rehearsal')).toHaveCount(0);
    const advancedAssignment = stageEditor.locator('summary').filter({ hasText: 'Runtime role tag or custom selector' });
    if (await advancedAssignment.count()) {
      await advancedAssignment.click();
      await expect(stageEditor.getByLabel('Advanced strategy')).toContainText('Runtime role tag');
    }
    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByText(/^participant_[0-9]+$/i)).toHaveCount(0);
    await expect(page.getByText(/^stage_[0-9]+$/i)).toHaveCount(0);

    await page.getByRole('button', { name: /\+ Add step/i }).first().click();
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
    const details = page.locator('.kit-details-panel').first();
    const planEditor = page.locator('.kit-stage-editor-grid');
    await expect(details.getByLabel('Name')).toHaveValue('Plan');
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

  test('software engineering template opens into one progressive workflow editor', async ({ page }) => {
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
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
    await expect(page.locator('.kit-stage-editor').first()).toContainText('Planning');
    await expect(page.getByTestId('workflow-stage-plan_review')).toBeVisible();

    await selectStep(page, 'planning');
    await expect(page.locator('.kit-details-panel').first().getByLabel('Name')).toHaveValue('Planning');
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
    await expect(assignment.getByText('Agents with this skill')).toBeVisible();
    await expect(assignment.locator('.quickstart-chip').filter({ hasText: 'M1' }).first()).toBeVisible();
    await assignment.locator('.quickstart-chip').filter({ hasText: 'M1' }).first().click();
    await expect(assignment.getByLabel('Required skill', { exact: true })).toHaveValue('architecture');
    await expect(assignment.getByLabel('Pinned agent', { exact: true })).toHaveValue('lift-and-shift-m1-bot');
    await assignment.getByLabel('Pinned agent', { exact: true }).selectOption('lift-and-shift-m2-bot');
    await expect(assignment.getByText('Skills advertised by this agent')).toBeVisible();
    await expect(assignment).toContainText('Available here:');
    await expect(assignment.locator('.quickstart-chip').filter({ hasText: 'Architecture' }).first()).toBeVisible();
    await assignment.locator('.quickstart-chip').filter({ hasText: 'Architecture' }).first().click();
    await expect(assignment.getByLabel('Required skill', { exact: true })).toHaveValue('architecture');
    await expect(assignment.getByLabel('Pinned agent', { exact: true })).toHaveValue('lift-and-shift-m2-bot');
    await expect(assignment.getByText('Agents with this skill')).toBeVisible();
    await expect(assignment.getByText('Skills advertised by this agent')).toBeVisible();
    expect(await assignment.locator('.quickstart-chip').count()).toBeGreaterThan(0);
    const planningEntry = page.locator('.kit-protocol-segment-entry').filter({ has: page.getByTestId('workflow-stage-plan_review') }).first();
    await planningEntry.getByRole('button', { name: 'Add below', exact: true }).click();
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
    await openTemplateDraft(page, 'Document Approval');

    await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
    await expect(page.getByRole('button', { name: /\+ Add participant/i })).toHaveCount(0);
    await expect(page.getByTestId('workflow-stage-draft_document')).toBeVisible();
    await expect(page.getByText('Planner role')).toHaveCount(0);
    await expect(page.getByText('Reviewer role')).toHaveCount(0);

    await page.getByTestId('workflow-stage-draft_document').click();
    await expect(await outlineStepNode(page, 'draft_document')).toBeVisible();
    await selectStep(page, 'draft_document');
    const details = page.locator('.kit-stage-editor').first();
    const documentAssignmentHeading = details.getByRole('heading', { name: 'Assignment' }).first();
    await documentAssignmentHeading.scrollIntoViewIfNeeded();
    await expect(documentAssignmentHeading).toBeVisible();
    await expect(details.getByLabel('Required skill', { exact: true })).toBeVisible();
    await expect(details.getByLabel('Pinned agent', { exact: true })).toBeVisible();
    await expect(details.getByText('Rehearsal')).toHaveCount(0);
    await expect(details).toContainText('Current assignment:');

    await discardDraft(page);
    expect(pageErrors, `page errors: ${pageErrors.join('\n')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join('\n')}`).toEqual([]);
  });

  test('software engineering template stays usable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { consoleErrors, pageErrors } = attachErrorCapture(page);

    await login(page);
    await openTemplateDraft(page, 'Software Engineering');
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
    await expect(page.locator('.kit-stage-editor').first()).toContainText('Planning');
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
