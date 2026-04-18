const { test, expect } = require('@playwright/test');
const {
  connectStep,
  createRole,
  createStep,
  discardDraft,
  login,
  openBlankDraft,
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

  const plannerKey = await createRole(page, { name: 'Planner', key: 'planner' });
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-role-page.png', fullPage: true });

  const planKey = await createStep(page, { name: 'Plan', key: 'plan', ownerRole: plannerKey });
  const reviewerKey = await createRole(page, { name: 'Reviewer', key: 'reviewer' });
  const reviewKey = await createStep(page, {
    name: 'Review',
    key: 'review',
    ownerRole: reviewerKey,
    stageKind: 'review',
  });

  await connectStep(page, planKey, reviewKey);
  await connectStep(page, reviewKey, '__complete__');
  await expect(page.getByTestId('workflow-edge-plan::completed')).toBeVisible();
  await expect(page.getByTestId('workflow-edge-review::accept')).toBeVisible();

  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-graph-page.png', fullPage: true });
  await page.locator('.kit-workflow-shell').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-graph-focus.png',
  });

  await discardDraft(page);

  await page.goto('/ui/gallery', { waitUntil: 'domcontentloaded' });
  const templateCard = page.locator('.protocol-template-card').filter({ hasText: 'Software Engineering' }).first();
  await expect(templateCard).toBeVisible();
  await templateCard.getByRole('button', { name: 'Use template' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-page.png', fullPage: true });
  await page.locator('.kit-workflow-process').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-overview-focus.png',
  });

  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-page.png', fullPage: true });
  await page.locator('.kit-workflow-shell').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-focus-graph.png',
  });

  await page.getByRole('button', { name: 'All steps' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('All steps');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-page.png', fullPage: true });
  await page.locator('.kit-workflow-shell').screenshot({
    path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-full-graph.png',
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Back to phases' }).click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Workflow phases');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-process-page.png', fullPage: true });
  await page.getByTestId('workflow-node-segment:planning').click();
  await expect(page.locator('.kit-workflow-viewbar')).toContainText('Planning');
  await page.screenshot({ path: '/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright/protocol-mobile-focus-page.png', fullPage: true });

  await discardDraft(page);
});
