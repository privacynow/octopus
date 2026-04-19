const { test, expect } = require('./playwright-runtime');
const {
  connectStep,
  createParticipant,
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

  await page.getByRole('button', { name: /\+ Add participant/i }).first().click();
  const participantEditor = page.locator('.kit-stage-editor').first();
  await participantEditor.getByLabel('Name').fill('Planner');
  await participantEditor.getByLabel('Key').fill('planner');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-participant-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Cancel' }).click();

  const plannerKey = await createParticipant(page, { name: 'Planner', key: 'planner', selectorKind: 'skill', selectorValue: 'planning' });

  const planKey = await createStep(page, { name: 'Plan', key: 'plan', ownerParticipant: plannerKey });
  const reviewerKey = await createParticipant(page, { name: 'Reviewer', key: 'reviewer', selectorKind: 'skill', selectorValue: 'review' });
  const reviewKey = await createStep(page, {
    name: 'Review',
    key: 'review',
    ownerParticipant: reviewerKey,
    stageKind: 'review',
  });

  await connectStep(page, planKey, reviewKey);
  await connectStep(page, reviewKey, '__complete__');
  await page.getByTestId(`workflow-step-${planKey}`).click();
  await expect(page.getByTestId('stage-route-plan::completed')).toBeVisible();
  await page.getByTestId(`workflow-step-${reviewKey}`).click();
  await expect(page.getByTestId('stage-route-review::accept')).toBeVisible();

  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-page.png', fullPage: true });
  await page.locator('.kit-protocol-detail').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-detail-focus.png',
  });

  await discardDraft(page);

  await openTemplateDraft(page, 'Software Engineering');
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow overview');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-page.png', fullPage: true });
  await page.locator('.kit-workflow-overview').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-focus.png',
  });

  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-page.png', fullPage: true });
  await page.locator('.kit-protocol-detail').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-detail.png',
  });

  await page.getByRole('button', { name: 'Topology' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Topology');
  const topologyToolbar = page.locator('.kit-workflow-toolbar');
  await expect(topologyToolbar.getByRole('button', { name: 'Focus', exact: true })).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-page.png', fullPage: true });
  await page.locator('.kit-workflow-viewport').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph.png',
  });
  await topologyToolbar.getByRole('button', { name: 'Full graph', exact: true }).click();
  await page.locator('.kit-workflow-viewport').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph-expanded.png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow overview');
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('desktop only');
  await expect(page.getByRole('button', { name: 'Topology' })).toHaveCount(0);
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-process-page.png', fullPage: true });
  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-focus-page.png', fullPage: true });

  await discardDraft(page);

  await openTemplateDraft(page, 'Document Approval');
  await expect(page.getByTestId('workflow-step-draft_document')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Author' }).first().click();
  await expect(page.locator('.kit-stage-editor').first().getByRole('heading', { name: 'Assignment rule' }).first()).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-participant-page.png', fullPage: true });

  await discardDraft(page);
});
