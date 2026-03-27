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
const DELEGATION_CONVERSATION_TITLE = requireEnv("E2E_DELEGATION_CONVERSATION_TITLE");
const DELEGATION_CONVERSATION_ID = requireEnv("E2E_DELEGATION_CONVERSATION_ID");
const ORIGIN_TOKEN = requireEnv("E2E_ORIGIN_TOKEN");
const TARGET_TOKEN = requireEnv("E2E_TARGET_TOKEN");
const ORIGIN_AGENT_ID = requireEnv("E2E_ORIGIN_AGENT_ID");
const TARGET_AGENT_ID = requireEnv("E2E_TARGET_AGENT_ID");

async function signIn(page) {
  await page.goto("/ui/login");
  await page.getByLabel(/password/i).fill(UI_TOKEN);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/ui\/?$/, { timeout: 5000 });
}

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
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Open conversations").first()).toBeVisible();
  await expect(page.getByText("Agents").first()).toBeVisible();
  await expect(page.getByText("Nothing urgent right now.")).toHaveCount(0);

  await page.goto("/ui/agents");
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  const agentFilterTabs = page.getByRole("tablist", { name: "Agent state filter" });
  await agentFilterTabs.getByRole("tab", { name: "All" }).focus();
  await agentFilterTabs.getByRole("tab", { name: "All" }).press("ArrowRight");
  await expect(agentFilterTabs.getByRole("tab", { name: "Connected", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(agentFilterTabs.getByRole("tab", { name: "Connected", exact: true })).toHaveAttribute("tabindex", "0");
  await agentFilterTabs.getByRole("tab", { name: "Connected", exact: true }).press("End");
  await expect(agentFilterTabs.getByRole("tab", { name: "Offline" })).toHaveAttribute("aria-selected", "true");
  await expect(agentFilterTabs.getByRole("tab", { name: "Offline" })).toHaveAttribute("tabindex", "0");
  await agentFilterTabs.getByRole("tab", { name: "Offline" }).press("Home");
  await expect(agentFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  await expect(agentFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("tabindex", "0");
  await expect(page.getByRole("link", { name: new RegExp(escapeRegExp(PRIMARY_LABEL)) }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(escapeRegExp(SECONDARY_LABEL)) }).first()).toBeVisible();
  const openConversationButtons = page.locator(".list-row-action");
  await expect(openConversationButtons).toHaveCount(2);
  await Promise.all([
    page.waitForURL(/\/ui\/conversations\//, { timeout: 5000 }),
    openConversationButtons.nth(1).click(),
  ]);
  await expect(page).toHaveURL(/\/ui\/conversations\//, { timeout: 5000 });
  await expect(page.locator(".conversation-meta")).toContainText(`With ${SECONDARY_LABEL}`);
  await expect(page.locator(".conversation-meta")).toContainText("Started in registry");
  await expect(page.locator(".conversation-meta")).toContainText("Activity (");
  await expect(page.locator(".conversation-meta")).not.toContainText("Agent");
  await expect(page.locator(".conversation-meta")).not.toContainText("Source");
  await expect(page.locator(".conversation-meta")).not.toContainText("Events");

  await page.goto("/ui/tasks");
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  const taskFilterTabs = page.getByRole("tablist", { name: "Task status filter" });
  await taskFilterTabs.getByRole("tab", { name: "All" }).focus();
  await taskFilterTabs.getByRole("tab", { name: "All" }).press("ArrowRight");
  await expect(taskFilterTabs.getByRole("tab", { name: "Queued", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(taskFilterTabs.getByRole("tab", { name: "Queued", exact: true })).toHaveAttribute("tabindex", "0");
  await taskFilterTabs.getByRole("tab", { name: "Queued", exact: true }).press("End");
  await expect(taskFilterTabs.getByRole("tab", { name: "Cancelled" })).toHaveAttribute("aria-selected", "true");
  await expect(taskFilterTabs.getByRole("tab", { name: "Cancelled" })).toHaveAttribute("tabindex", "0");
  await taskFilterTabs.getByRole("tab", { name: "Cancelled" }).press("Home");
  await expect(taskFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  await expect(taskFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("tabindex", "0");
  await expect(page.getByText(EXISTING_TASK_TITLE).first()).toBeVisible();
  const existingTaskItem = page.locator(".task-item").filter({ hasText: EXISTING_TASK_TITLE }).first();
  await existingTaskItem.locator(".task-item-row").click();
  await expect(existingTaskItem.getByRole("link", { name: /open conversation/i })).toBeVisible();
  await expect(existingTaskItem).not.toContainText(PARENT_CONVERSATION_ID);
  await expect(existingTaskItem).not.toContainText(TARGET_AGENT_ID);

  await page.goto(`/ui/conversations/${PARENT_CONVERSATION_ID}`);
  await expect(page.getByRole("tablist", { name: "Conversation timeline view" })).toBeVisible();
  await expect(page.locator(".timeline-events")).toContainText(PARENT_PROMPT);
  await expect(page.locator(".compose-hint")).toBeHidden();
  await expect(page.getByLabel("Message text")).toBeInViewport();
  await expect(page.locator(".chat-timeline")).toBeVisible();
  await expect(page.locator(".conversation-task-view")).toHaveAttribute("hidden", "");

  const liveUiTaskTitle = `Live UI direct ${Date.now()}`;
  const targetSelector = await page.evaluate(async ({ targetAgentId }) => {
    const response = await fetch("/v1/agents?limit=20", { credentials: "same-origin" });
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    const match = (payload.agents || []).find((agent) => agent.agent_id === targetAgentId);
    if (!match || !match.slug) throw new Error(`No slug for ${targetAgentId}`);
    const displayName = String(match.display_name || "").trim();
    const selectorValue = displayName && !/\s/.test(displayName) ? displayName : match.slug;
    return {
      selectorValue,
      selectorKind: displayName && !/\s/.test(displayName) ? "display_name" : "slug",
      slug: match.slug,
    };
  }, { targetAgentId: TARGET_AGENT_ID });

  await page.getByLabel("Message text").fill("@");
  await expect(page.locator(".compose-hint")).toContainText(/choose an agent, capability, or role/i);
  await expect(page.locator(".compose-suggestions")).toContainText(`@${targetSelector.selectorValue}`);
  await expect(
    page.locator(".compose-suggestion strong").filter({ hasText: new RegExp(`^@${escapeRegExp(targetSelector.selectorValue)}$`) })
  ).toHaveCount(1);
  await page.getByLabel("Message text").fill(`@${targetSelector.selectorValue} ${liveUiTaskTitle}`);
  await expect(page.getByText(new RegExp(`Routing directly to @${escapeRegExp(targetSelector.selectorValue)}`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Assign" })).toBeVisible();
  await page.getByRole("button", { name: "Assign" }).click();
  await expect(page.locator(".timeline-events")).toContainText(liveUiTaskTitle, { timeout: 5000 });
  await expect(page.locator(".timeline-events")).toContainText("Task submitted", { timeout: 5000 });
  await expect(page.locator(".conversation-meta")).toContainText(`Assigned to ${targetSelector.selectorValue}`, { timeout: 5000 });
  await expect(page.locator(".timeline-events")).toContainText(`Assigned to ${targetSelector.selectorValue}`, { timeout: 5000 });
  await expect(page.locator(".timeline-events")).not.toContainText(`${liveUiTaskTitle}${TARGET_AGENT_ID}`);

  await page.getByRole("tab", { name: "Tasks" }).click();
  await expect(page.locator(".conversation-task-view")).not.toHaveAttribute("hidden", "");
  await expect(page.locator(".chat-timeline")).toHaveAttribute("hidden", "");
  await expect(
    page.locator(".conversation-task-card-title").filter({ hasText: liveUiTaskTitle })
  ).toHaveCount(1);
  await page.getByRole("tab", { name: "Full activity" }).click();
  await expect(page.locator(".chat-timeline")).not.toHaveAttribute("hidden", "");
  await expect(page.locator(".conversation-task-view")).toHaveAttribute("hidden", "");
  await expect(page.locator(".timeline-events")).toContainText("Task submitted");

  await page.goto("/ui/conversations");
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  const conversationFilterTabs = page.getByRole("tablist", { name: "Conversation status filter" });
  await conversationFilterTabs.getByRole("tab", { name: "All" }).focus();
  await conversationFilterTabs.getByRole("tab", { name: "All" }).press("ArrowRight");
  await expect(conversationFilterTabs.getByRole("tab", { name: "Open", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(conversationFilterTabs.getByRole("tab", { name: "Open", exact: true })).toHaveAttribute("tabindex", "0");
  await conversationFilterTabs.getByRole("tab", { name: "Open", exact: true }).press("End");
  await expect(conversationFilterTabs.getByRole("tab", { name: "Needs follow-up" })).toHaveAttribute("aria-selected", "true");
  await expect(conversationFilterTabs.getByRole("tab", { name: "Needs follow-up" })).toHaveAttribute("tabindex", "0");
  await conversationFilterTabs.getByRole("tab", { name: "Needs follow-up" }).press("Home");
  await expect(conversationFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  await expect(conversationFilterTabs.getByRole("tab", { name: "All" })).toHaveAttribute("tabindex", "0");
  await expect(page.locator(".quickstart-chip")).toHaveCount(2);
  await Promise.all([
    page.waitForURL(/\/ui\/conversations\//, { timeout: 5000 }),
    page.locator(".quickstart-chip").nth(0).click(),
  ]);
  await expect(page).toHaveURL(/\/ui\/conversations\//, { timeout: 5000 });
  await expect(page.locator(".conversation-meta")).toBeVisible();

  await page.goto("/ui/conversations");
  await expect(page.getByText(EXISTING_BASIC_TITLE).first()).toBeVisible();
  await expect(page.getByText(DELEGATION_CONVERSATION_TITLE).first()).toBeVisible();
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
  const liveTaskResult = `Delegated answer ${Date.now()} = 4`;
  await page.evaluate(
    async ({ taskId, title, parentId, originToken, targetToken, originAgentId, targetAgentId, taskResult }) => {
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
          transition_id: `${taskId}-complete`,
          summary: taskResult,
          full_text: taskResult,
          prompt_tokens: 17,
          completion_tokens: 9,
          cost_usd: 0.21,
          provider: "codex",
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
      taskResult: liveTaskResult,
    },
  );
  await expect(page.getByText(liveTaskTitle).first()).toBeVisible({ timeout: 5000 });
  const liveTaskItem = page.locator(".task-item").filter({ hasText: liveTaskTitle }).first();
  await expect(liveTaskItem).toContainText(liveTaskResult);
  await expect(liveTaskItem).not.toContainText(PARENT_CONVERSATION_ID);
  await expect(liveTaskItem).not.toContainText(TARGET_AGENT_ID);

  await page.goto(`/ui/conversations/${PARENT_CONVERSATION_ID}`);
  await expect(page.locator(".timeline-events")).toContainText(liveTaskResult, { timeout: 5000 });
  await expect(page.locator(".timeline-events")).not.toContainText(TARGET_AGENT_ID);

  await page.goto("/ui/usage");
  await expect(page.getByRole("heading", { name: "Usage" })).toBeVisible();
  const usageTabs = page.getByRole("tablist", { name: "Usage date range" });
  await usageTabs.getByRole("tab", { name: "7 days" }).focus();
  await usageTabs.getByRole("tab", { name: "7 days" }).press("End");
  await expect(usageTabs.getByRole("tab", { name: "30 days" })).toHaveAttribute("aria-selected", "true");
  await expect(usageTabs.getByRole("tab", { name: "30 days" })).toHaveAttribute("tabindex", "0");
  await usageTabs.getByRole("tab", { name: "30 days" }).press("Home");
  await expect(usageTabs.getByRole("tab", { name: "Today" })).toHaveAttribute("aria-selected", "true");
  await expect(usageTabs.getByRole("tab", { name: "Today" })).toHaveAttribute("tabindex", "0");
  const usageRow = page
    .locator("#usage-table tbody tr")
    .filter({ has: page.locator(`a[href=\"/ui/conversations/${PARENT_CONVERSATION_ID}\"]`) })
    .first();
  await expect(usageRow).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => {
    const value = (await usageRow.locator("td").nth(1).textContent()) || "0";
    return Number(value.replace(/,/g, "").trim());
  }).toBeGreaterThan(0);
});

test.describe("mobile dark ui smoke", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    colorScheme: "dark",
  });

  test("mobile dark segmented controls and conversation layout", async ({ page }) => {
    await signIn(page);
    await expect.poll(async () => {
      return page.evaluate(() => document.documentElement.getAttribute("data-theme"));
    }).toBe("dark");

    await page.goto("/ui/conversations");
    await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
    const mobileConversationTabs = page.getByRole("tablist", { name: "Conversation status filter" });
    const mobileActiveTab = mobileConversationTabs.getByRole("tab", { name: "All" });
    const [tablistBox, activeBox] = await Promise.all([
      mobileConversationTabs.boundingBox(),
      mobileActiveTab.boundingBox(),
    ]);
    expect(tablistBox).toBeTruthy();
    expect(activeBox).toBeTruthy();
    expect(activeBox.x).toBeGreaterThanOrEqual(tablistBox.x - 1);
    expect(activeBox.x + activeBox.width).toBeLessThanOrEqual(tablistBox.x + tablistBox.width + 1);
    expect(activeBox.y).toBeGreaterThanOrEqual(tablistBox.y - 1);
    expect(activeBox.y + activeBox.height).toBeLessThanOrEqual(tablistBox.y + tablistBox.height + 1);

    await page.goto(`/ui/conversations/${PARENT_CONVERSATION_ID}`);
    await expect(page.getByRole("tablist", { name: "Conversation timeline view" })).toBeVisible();
    await expect(page.getByLabel("Message text")).toBeInViewport();
    await page.getByRole("tab", { name: "Full activity" }).click();
    await expect(page.locator(".timeline-events")).toContainText("Agent started work");
  });
});
