const { test, expect } = require("@playwright/test");

function requireEnv(name) {
  const value = process.env[name] || "";
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const UI_TOKEN = requireEnv("E2E_UI_TOKEN");
const PRIMARY_LABEL = requireEnv("E2E_PRIMARY_LABEL");
const SECONDARY_LABEL = requireEnv("E2E_SECONDARY_LABEL");
const PARENT_CONVERSATION_ID = requireEnv("E2E_PARENT_CONVERSATION_ID");
const PARENT_PROMPT = requireEnv("E2E_PARENT_PROMPT");
const EXISTING_TASK_TITLE = requireEnv("E2E_EXISTING_TASK_TITLE");
const EXISTING_BASIC_TITLE = requireEnv("E2E_BASIC_CONVERSATION_TITLE");
const ORIGIN_TOKEN = requireEnv("E2E_ORIGIN_TOKEN");
const TARGET_TOKEN = requireEnv("E2E_TARGET_TOKEN");
const ORIGIN_AGENT_ID = requireEnv("E2E_ORIGIN_AGENT_ID");
const TARGET_AGENT_ID = requireEnv("E2E_TARGET_AGENT_ID");

async function fetchCsrf(page) {
  return page.evaluate(async () => {
    const response = await fetch("/v1/auth/csrf", { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`csrf ${response.status}`);
    }
    const payload = await response.json();
    return payload.token || payload.csrf_token || "";
  });
}

test("live registry ui smoke", async ({ page }) => {
  await page.goto("/ui/login");
  await page.getByLabel(/password/i).fill(UI_TOKEN);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/ui\/?$/, { timeout: 5000 });
  await expect(page.getByRole("heading", { name: /registry/i })).toBeVisible();
  await expect(page.locator(".attention-card")).toHaveCount(3);
  await expect(page.getByText("Connected agents")).toBeVisible();

  await page.goto("/ui/agents");
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(escapeRegExp(PRIMARY_LABEL)) }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(escapeRegExp(SECONDARY_LABEL)) }).first()).toBeVisible();

  await page.goto("/ui/tasks");
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await expect(page.getByText(EXISTING_TASK_TITLE).first()).toBeVisible();
  await page.getByText(EXISTING_TASK_TITLE).first().click();
  await expect(page.getByRole("link", { name: "View parent conversation" }).first()).toBeVisible();

  await page.goto(`/ui/conversations/${PARENT_CONVERSATION_ID}`);
  await expect(page.getByRole("heading", { name: "Conversation" })).toBeVisible();
  await expect(page.locator(".timeline-events")).toContainText(PARENT_PROMPT);
  await expect(page.locator(".timeline-events")).toContainText(EXISTING_TASK_TITLE);

  await page.goto("/ui/conversations");
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  await expect(page.getByText(EXISTING_BASIC_TITLE).first()).toBeVisible();
  const csrf = await fetchCsrf(page);
  const createdConversationTitle = `Live WS conversation ${Date.now()}`;
  await page.evaluate(
    async ({ title, csrfToken }) => {
      const agentsResp = await fetch("/v1/agents?limit=10", { credentials: "same-origin" });
      if (!agentsResp.ok) throw new Error(await agentsResp.text());
      const agents = await agentsResp.json();
      const target = (agents.agents || [])[0];
      if (!target) throw new Error("No agent available");
      const createResp = await fetch("/v1/conversations", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          target_agent_id: target.agent_id,
          origin_channel: "registry",
          external_conversation_ref: `ui-live-${Date.now()}`,
          title,
        }),
      });
      if (!createResp.ok) throw new Error(await createResp.text());
    },
    { title: createdConversationTitle, csrfToken: csrf },
  );
  await expect(page.getByText(createdConversationTitle).first()).toBeVisible({ timeout: 5000 });

  await page.goto("/ui/tasks");
  const liveTaskTitle = `Live WS task ${Date.now()}`;
  const liveTaskId = `live-ws-task-${Date.now()}`;
  await page.evaluate(
    async ({ taskId, title, parentId, originToken, targetToken, originAgentId, targetAgentId }) => {
      const createdAt = new Date().toISOString();
      const createResp = await fetch("/v1/agents/routed-tasks", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${originToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          routed_task_id: taskId,
          parent_conversation_id: parentId,
          origin_agent_id: originAgentId,
          target_agent_id: targetAgentId,
          title,
          instructions: "Return only the number 4.",
          created_at: createdAt,
        }),
      });
      if (!createResp.ok) throw new Error(await createResp.text());

      const resultResp = await fetch(`/v1/agents/routed-tasks/${taskId}/result`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${targetToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          status: "completed",
          summary: "4",
          full_text: "4",
          completed_at: new Date().toISOString(),
        }),
      });
      if (!resultResp.ok) throw new Error(await resultResp.text());
    },
    {
      taskId: liveTaskId,
      title: liveTaskTitle,
      parentId: PARENT_CONVERSATION_ID,
      originToken: ORIGIN_TOKEN,
      targetToken: TARGET_TOKEN,
      originAgentId: ORIGIN_AGENT_ID,
      targetAgentId: TARGET_AGENT_ID,
    },
  );
  await expect(page.getByText(liveTaskTitle).first()).toBeVisible({ timeout: 5000 });
});
