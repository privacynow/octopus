const { test, expect } = require('./playwright-runtime');
const {
  connectStep,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
  openTemplateDraft,
  waitForSaved,
} = require('./helpers/protocol-helpers');

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

  await page.getByRole('button', { name: /\+ Add step/i }).first().click();
  const participantEditor = page.locator('.kit-stage-editor').first();
  await participantEditor.getByLabel('Name').fill('Plan');
  await participantEditor.getByLabel('Role name').fill('Planner');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-step-create-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Cancel' }).click();

  const planKey = await createStep(page, {
    name: 'Plan',
    key: 'plan',
    roleName: 'Planner',
    roleKey: 'planner',
    selectorKind: 'skill',
    selectorValue: 'planning',
  });
  const reviewKey = await createStep(page, {
    name: 'Review',
    key: 'review',
    roleName: 'Reviewer',
    roleKey: 'reviewer',
    selectorKind: 'skill',
    selectorValue: 'review',
    stageKind: 'review',
  });

  await connectStep(page, planKey, reviewKey);
  await connectStep(page, reviewKey, '__complete__');
  await page.getByTestId(`workflow-outline-${planKey}`).click();
  await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();
  await page.getByTestId(`workflow-outline-${reviewKey}`).click();
  await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();

  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-page.png', fullPage: true });
  await page.locator('.kit-authoring-details-column').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-focus.png',
  });

  await discardDraft(page);

  await openTemplateDraft(page, 'Software Engineering');
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow canvas');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-page.png', fullPage: true });
  await page.locator('.kit-workflow-shell-scene').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-focus.png',
  });

  await page.getByTestId('workflow-outline-segment:planning').click();
  await expect(page.locator('.kit-protocol-segment-panel')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-page.png', fullPage: true });
  await page.locator('.kit-authoring-details-column').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-detail.png',
  });

  await page.getByTestId('workflow-outline-planning').click();
  await expect(page.locator('.kit-stage-editor')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-page.png', fullPage: true });
  await page.locator('.kit-workflow-viewport-cy').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph.png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow canvas');
  await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-process-page.png' });
  await page.getByTestId('workflow-outline-segment:planning').click();
  await expect(page.locator('.kit-protocol-segment-panel')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-focus-page.png' });

  await discardDraft(page);

  await openTemplateDraft(page, 'Document Approval');
  await expect(page.getByTestId('workflow-outline-segment:draft_document')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-page.png', fullPage: true });
  await page.getByTestId('workflow-outline-segment:draft_document').click();
  await expect(page.getByTestId('workflow-outline-draft_document')).toBeVisible();
  await page.getByTestId('workflow-outline-draft_document').click();
  await expect(page.locator('.kit-stage-editor').first().getByRole('heading', { name: 'Assignment' }).first()).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-participant-page.png', fullPage: true });

  await discardDraft(page);
});
