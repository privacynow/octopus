const { test, expect } = require('./playwright-runtime');
const {
  connectStep,
  createStep,
  discardDraft,
  login,
  outlineStepNode,
  openBlankDraft,
  openTemplateDraft,
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

test('capture protocol authoring states', async ({ page }) => {
  await login(page);

  await page.goto('/ui/protocols', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Protocols', exact: true })).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-list-page.png', fullPage: true });

  await openBlankDraft(page);
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-blank-page.png', fullPage: true });

  const lifecycle = page.locator('.kit-lifecycle-header');
  await lifecycle.getByLabel('Name').fill(`Visual Review ${Date.now()}`);
  await lifecycle.getByLabel('Name').blur();
  await waitForSaved(page);

  await page.getByRole('button', { name: /Add( first)? step/i }).first().click();
  const participantEditor = page.locator('.kit-stage-editor').first();
  const stepBasics = participantEditor.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'Step basics', exact: true }) }).first();
  const newRole = participantEditor.locator('.kit-stage-editor-section').filter({ has: page.getByRole('heading', { name: 'New owner role', exact: true }) }).first();
  await stepBasics.getByLabel('Name').fill('Plan');
  await newRole.getByLabel('Role name').fill('Planner');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-step-create-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Cancel' }).click();

  const planKey = await createStep(page, {
    name: 'Plan',
    key: 'plan',
    roleName: 'Planner',
    roleKey: 'planner',
    selectorKind: 'skill',
    selectorValue: '__first__',
  });
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
  await connectStep(page, reviewKey, '__complete__');
  await selectStep(page, planKey);
  await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();
  await selectStep(page, reviewKey);
  await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();

  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-page.png', fullPage: true });
  await page.locator('.kit-authoring-primary-column').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-focus.png',
  });

  await discardDraft(page);

  await openTemplateDraft(page, 'Software Engineering', { expectedStageKeys: SOFTWARE_ENGINEERING_STAGE_KEYS });
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-page.png', fullPage: true });
  await page.locator('.kit-authoring-primary-column').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-focus.png',
  });

  await page.getByTestId('workflow-stage-planning').click();
  await expect(page.locator('.kit-stage-editor').getByLabel('Name').first()).toHaveValue('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-page.png', fullPage: true });
  await page.locator('.kit-authoring-primary-column').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-detail.png',
  });

  await selectStep(page, 'planning');
  await expect(page.locator('.kit-stage-editor')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Show workflow map', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Hide workflow map', exact: true })).toBeVisible();
  await page.locator('.kit-workflow-canvas').first().screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph.png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow stages');
  await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-process-page.png' });
  await selectStep(page, 'planning');
  await expect(page.locator('.kit-stage-editor').getByLabel('Name').first()).toHaveValue('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-focus-page.png' });

  await discardDraft(page);

  await openTemplateDraft(page, 'Document Approval', { expectedStageKeys: DOCUMENT_APPROVAL_STAGE_KEYS });
  await expect(page.getByTestId('workflow-stage-draft_document')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-page.png', fullPage: true });
  await page.getByTestId('workflow-stage-draft_document').click();
  await expect(await outlineStepNode(page, 'draft_document')).toBeVisible();
  await selectStep(page, 'draft_document');
  await expect(page.locator('.kit-stage-editor').first().getByRole('heading', { name: 'Assignment' }).first()).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-participant-page.png', fullPage: true });

  await discardDraft(page);
});
