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

  const plannerKey = await createParticipant(page, { name: 'Planner', key: 'planner' });
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-participant-page.png', fullPage: true });

  const planKey = await createStep(page, { name: 'Plan', key: 'plan', ownerParticipant: plannerKey });
  const reviewerKey = await createParticipant(page, { name: 'Reviewer', key: 'reviewer' });
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
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-page.png', fullPage: true });
  await page.locator('.kit-workflow-process').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-focus.png',
  });

  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-page.png', fullPage: true });
  await page.locator('.kit-protocol-detail').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-detail.png',
  });

  await page.getByRole('button', { name: 'Visual map' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Visual map');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-page.png', fullPage: true });
  await page.locator('.kit-workflow-shell').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph.png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Back to phases' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-process-page.png', fullPage: true });
  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-protocol-detail-title')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-focus-page.png', fullPage: true });

  await discardDraft(page);

  await openTemplateDraft(page, 'Document Approval');
  await expect(page.getByTestId('workflow-step-draft_document')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-page.png', fullPage: true });
  await page.getByRole('button', { name: 'Author' }).first().click();
  await expect(page.locator('.kit-details-panel').first().getByText('Assignment rule')).toBeVisible();
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-document-approval-participant-page.png', fullPage: true });

  await discardDraft(page);
});
