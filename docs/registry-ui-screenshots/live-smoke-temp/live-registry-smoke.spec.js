const { test, expect } = require('@playwright/test');

const UI_TOKEN = 'KOmefo_IAYI9tkKgr14jn84g_jTXCeIz';
const M1_TOKEN = 'bMGQPEQUlBuEdTVu_-AfKokn1NW52Vv8oYQhzxNVcMo';
const M2_TOKEN = 'nP8yITtWWItKTkHDrN0LUij5VAaxnvXXLkEuWBQSMKc';
const PARENT_CONVERSATION_ID = 'e809252bfce17e7914aaa65224d8b1de';
const M1_AGENT_ID = '469e60611b2340298e69ecf48feb20f3';
const M2_AGENT_ID = '5a677c7e5edd44e2b55feea801af4800';

test('live deployed registry UI smoke', async ({ page }) => {
  await page.goto('/ui/login');
  await page.getByLabel('Password').fill(UI_TOKEN);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/ui\/?$/, { timeout: 5000 });
  await expect(page.getByRole('heading', { name: /Registry/ })).toBeVisible();
  await expect(page.locator('.attention-card')).toHaveCount(3);
  await expect(page.getByText('Connected agents')).toBeVisible();

  await page.goto('/ui/agents');
  await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible();
  await expect(page.getByRole('link', { name: /M1/ }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: /M2/ }).first()).toBeVisible();

  await page.goto('/ui/tasks');
  await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible();
  await expect(page.getByText('Manual routed task').first()).toBeVisible();
  await expect(page.getByText('Compute 2 + 2').first()).toBeVisible();
  await page.getByText('Manual routed task').first().click();
  await expect(page.getByRole('link', { name: 'View parent conversation' }).first()).toBeVisible();

  await page.goto(`/ui/conversations/${PARENT_CONVERSATION_ID}`);
  await expect(page.getByRole('heading', { name: 'Conversation' })).toBeVisible();
  await expect(page.getByText('Delegate this task to M2 through the registry.')).toBeVisible();
  await expect(page.locator('.timeline-events')).toContainText('Manual routed task');
  await expect(page.locator('.timeline-events')).toContainText('4');

  await page.goto('/ui/conversations');
  await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible();
  const createdTitle = `Live WS convo ${Date.now()}`;
  await page.evaluate(async ({ title }) => {
    const csrfResp = await fetch('/v1/auth/csrf', { credentials: 'same-origin' });
    const csrf = await csrfResp.json();
    const agentsResp = await fetch('/v1/agents?limit=10', { credentials: 'same-origin' });
    if (!agentsResp.ok) throw new Error(await agentsResp.text());
    const agents = await agentsResp.json();
    const target = (agents.agents || []).find((item) => item.display_name === 'M1') || (agents.agents || [])[0];
    if (!target) throw new Error('No agent available for live conversation test');
    const createResp = await fetch('/v1/conversations', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf.token || csrf.csrf_token || '',
      },
      body: JSON.stringify({
        target_agent_id: target.agent_id,
        origin_channel: 'registry',
        external_conversation_ref: 'ui-' + Date.now(),
        title,
      }),
    });
    if (!createResp.ok) throw new Error(await createResp.text());
  }, { title: createdTitle });
  await expect(page.getByText(createdTitle).first()).toBeVisible({ timeout: 5000 });

  await page.goto('/ui/tasks');
  const liveTaskTitle = `Live WS task ${Date.now()}`;
  const liveTaskId = `live-ws-task-${Date.now()}`;
  await page.evaluate(async ({ taskId, title, parentId, m1, m2, originAgentId, targetAgentId }) => {
    const createResp = await fetch('/v1/agents/routed-tasks', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${m1}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        routed_task_id: taskId,
        parent_conversation_id: parentId,
        origin_agent_id: originAgentId,
        target_agent_id: targetAgentId,
        title,
        instructions: 'Return only 4.',
        created_at: new Date().toISOString(),
      }),
    });
    if (!createResp.ok) throw new Error(await createResp.text());
    const resultResp = await fetch(`/v1/agents/routed-tasks/${taskId}/result`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${m2}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        status: 'completed',
        summary: '4',
        full_text: '4',
        completed_at: new Date().toISOString(),
      }),
    });
    if (!resultResp.ok) throw new Error(await resultResp.text());
  }, {
    taskId: liveTaskId,
    title: liveTaskTitle,
    parentId: PARENT_CONVERSATION_ID,
    m1: M1_TOKEN,
    m2: M2_TOKEN,
    originAgentId: M1_AGENT_ID,
    targetAgentId: M2_AGENT_ID,
  });
  await expect(page.getByText(liveTaskTitle).first()).toBeVisible({ timeout: 5000 });
});
