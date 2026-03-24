import { expect, test } from "@playwright/test";

const BASE = "http://127.0.0.1:19987";
const ENROLL = "guide-capture-enroll-token-2026";
const UI_TOKEN = "guide-capture-ui-token-2026";

const browserChannel = process.env.PW_BROWSER_CHANNEL || "";
if (browserChannel) {
  test.use({ channel: browserChannel as "chrome" });
}

function iso(offsetSeconds: number): string {
  return new Date(Date.now() + offsetSeconds * 1000).toISOString();
}

function card(slug: string, displayName: string) {
  return {
    bot_key: `bot:${slug}`,
    display_name: displayName,
    slug,
    role: "developer",
    registry_scope: "full",
    capabilities: ["python", "reviewer", "registry"],
    tags: ["playwright", "smoke"],
    description: `Smoke seed for ${displayName}`,
    provider: "codex",
    mode: "registry",
    channel_capabilities: ["registry"],
    version: "test",
  };
}

async function enrollAgent(slug: string, displayName: string) {
  const enroll = await fetch(`${BASE}/v1/agents/enroll`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enrollment_token: ENROLL,
      agent_card: card(slug, displayName),
    }),
  });
  const enrollText = await enroll.text();
  expect(enroll.ok, enrollText).toBeTruthy();
  const enrolled = JSON.parse(enrollText);
  const token = enrolled.agent_token as string;

  const register = await fetch(`${BASE}/v1/agents/register`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      agent_card: card(slug, displayName),
      connectivity_state: "connected",
      current_capacity: 0,
      max_capacity: 4,
    }),
  });
  expect(register.ok, await register.text()).toBeTruthy();

  return { agentId: enrolled.agent_id as string, token };
}

async function createConversation(token: string, agentId: string, externalRef: string, title: string) {
  const response = await fetch(`${BASE}/v1/conversations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      target_agent_id: agentId,
      origin_channel: "registry",
      external_conversation_ref: externalRef,
      title,
    }),
  });
  const responseText = await response.text();
  expect(response.ok, responseText).toBeTruthy();
  return JSON.parse(responseText);
}

function eventId(suffix: string, name: string): string {
  return `smoke-${suffix}-${name}`;
}

async function publishEvents(token: string, conversationId: string, suffix: string) {
  const events = [
    {
      event_id: eventId(suffix, "user"),
      kind: "message.user",
      actor: "operator",
      content: "Kick off a release readiness review.",
      created_at: iso(-90),
      metadata: {},
    },
    {
      event_id: eventId(suffix, "request"),
      kind: "provider.request",
      actor: "",
      content: "Review the launch checklist and identify open risk.",
      created_at: iso(-80),
      metadata: {
        provider: "codex",
        model: "gpt-5.4",
        execution_mode: "run",
        working_dir: "/workspace/repo",
        file_policy: "edit",
        image_count: 0,
        prompt_char_count: 64,
      },
    },
    {
      event_id: eventId(suffix, "response"),
      kind: "provider.response",
      actor: "",
      content: "",
      created_at: iso(-70),
      metadata: {
        prompt_tokens: 112,
        completion_tokens: 48,
        cost_usd: 0.0142,
        provider: "codex",
      },
    },
    {
      event_id: eventId(suffix, "tool"),
      kind: "tool.execution",
      actor: "",
      content: "exec_command completed",
      created_at: iso(-60),
      metadata: {
        tool_name: "exec_command",
        call_id: eventId(suffix, "tool-call"),
        status: "completed",
        input_summary: "git status",
        output_summary: "working tree clean",
        duration_ms: 83,
        file_changes: [
          {
            path: "src/app.ts",
            change_type: "modified",
            summary: "Updated release banner",
          },
        ],
      },
    },
    {
      event_id: eventId(suffix, "approval-requested"),
      kind: "approval.requested",
      actor: "operator",
      content: "Retry with production credentials?",
      created_at: iso(-50),
      metadata: {
        request_kind: "retry",
        actor_key: "telegram:42",
        trust_tier: "trusted",
        expires_at: iso(600),
      },
    },
    {
      event_id: eventId(suffix, "approval-decided"),
      kind: "approval.decided",
      actor: "operator",
      content: "",
      created_at: iso(-40),
      metadata: {
        action: "approve",
        decided_by: "operator",
        decision: "approved",
      },
    },
    {
      event_id: eventId(suffix, "delegation"),
      kind: "delegation.submitted",
      actor: "",
      content: "",
      created_at: iso(-30),
      metadata: {
        tasks: [
          { title: "Check runbook", target: "release-reviewer", status: "submitted" },
        ],
      },
    },
    {
      event_id: eventId(suffix, "task"),
      kind: "task.status",
      actor: "",
      content: "Checklist verification in progress.",
      created_at: iso(-20),
      metadata: {
        status: "running",
        progress: 68,
      },
    },
    {
      event_id: eventId(suffix, "error"),
      kind: "error",
      actor: "",
      content: "One dependency check needs a second pass.",
      created_at: iso(-10),
      metadata: {
        error_type: "execution",
        message: "One dependency check needs a second pass.",
      },
    },
    {
      event_id: eventId(suffix, "bot"),
      kind: "message.bot",
      actor: "release-bot",
      content: "Release review is mostly green. One dependency needs follow-up.",
      created_at: iso(-5),
      metadata: {},
    },
  ];
  const response = await fetch(`${BASE}/v1/conversations/${conversationId}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      events,
    }),
  });
  const responseText = await response.text();
  expect(response.ok, responseText).toBeTruthy();
  const payload = JSON.parse(responseText);
  expect(payload.inserted).toBe(events.length);
  expect(payload.skipped).toBe(0);
}

test("ui overhaul smoke flow", async ({ page }) => {
  const suffix = `${Date.now()}`;
  const primaryDisplay = `Release Coordinator ${suffix}`;
  const reviewerDisplay = `Risk Reviewer ${suffix}`;
  const conversationTitle = `UI overhaul smoke thread ${suffix}`;
  const primary = await enrollAgent(`release-bot-${suffix}`, primaryDisplay);
  await enrollAgent(`reviewer-bot-${suffix}`, reviewerDisplay);
  const conversation = await createConversation(primary.token, primary.agentId, `ui-overhaul-${suffix}`, conversationTitle);
  await publishEvents(primary.token, conversation.conversation_id as string, suffix);

  await page.goto("/ui/login");
  await page.getByLabel("Password").fill(UI_TOKEN);
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page).toHaveURL(/\/ui\/?$/);
  await expect(page.getByRole("heading", { name: "Registry Dashboard" })).toBeVisible();
  await expect(page.getByText("Connected Agents")).toBeVisible();
  await expect(page.locator(".stat-card-label", { hasText: "Pending Approvals" })).toBeVisible();

  await page.locator(".nav-links").getByRole("link", { name: /Agents/ }).click();
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  await expect(page.getByText(primaryDisplay)).toBeVisible();

  await page.locator(".nav-links").getByRole("link", { name: /Conversations/ }).click();
  await expect(page.getByRole("heading", { name: "Conversations" })).toBeVisible();
  await page.getByText(conversationTitle).click();

  await expect(page.getByRole("heading", { name: "Conversation" })).toBeVisible();
  await expect(page.getByText("provider · request")).toBeVisible();
  await expect(page.getByText("provider · response")).toBeVisible();
  await expect(page.getByText("tool · execution")).toBeVisible();
  await expect(page.getByText("approval · requested")).toBeVisible();
  await expect(page.getByText("approval · decided")).toBeVisible();
  await expect(page.getByText("delegation · submitted")).toBeVisible();
  await expect(page.getByText("task · status")).toBeVisible();
  await expect(page.getByText("Kick off a release readiness review.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Messages only" })).toBeVisible();
});
