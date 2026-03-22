/**
 * Captures the Registry UI for docs. Seeds SQLite via HTTP, then screenshots every route.
 * Run: cd docs/registry-ui-screenshots && npm install && npx playwright install chromium && npm run capture
 */
import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const OUT = path.join(__dirname, "..", "assets", "registry", "ui");
const BASE = "http://127.0.0.1:19987";
const ENROLL = "guide-capture-enroll-token-2026";

const seed: { agentA: string; agentB: string; convId: string } = {
  agentA: "",
  agentB: "",
  convId: "",
};

function card(slug: string) {
  return {
    display_name: slug,
    slug,
    role: "developer",
    registry_scope: "full",
    capabilities: ["python"],
    tags: [],
    description: `${slug} demo`,
    provider: "demo",
    mode: "registry",
    channel_capabilities: ["registry"],
    version: "1.0.0",
  };
}

async function enrollAgent(slug: string): Promise<{ agent_id: string; token: string }> {
  const r = await fetch(`${BASE}/v1/agents/enroll`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enrollment_token: ENROLL, agent_card: card(slug) }),
  });
  expect(r.ok).toBeTruthy();
  const j = await r.json();
  const token = j.agent_token as string;
  const reg = await fetch(`${BASE}/v1/agents/register`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_card: card(slug),
      connectivity_state: "connected",
      current_capacity: 0,
      max_capacity: 4,
    }),
  });
  expect(reg.ok).toBeTruthy();
  return { agent_id: j.agent_id as string, token };
}

test.beforeAll(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  const origin = await enrollAgent("origin-bot");
  const target = await enrollAgent("target-bot");
  seed.agentA = origin.agent_id;
  seed.agentB = target.agent_id;

  // Agent tokens may only create conversations targeting themselves (enforced in HTTP).
  const cr = await fetch(`${BASE}/v1/conversations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${origin.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      target_agent_id: origin.agent_id,
      title: "Demo: planning session",
      origin_channel: "registry-ui",
      external_conversation_ref: "demo-ext-1",
    }),
  });
  expect(cr.ok).toBeTruthy();
  const conv = await cr.json();
  seed.convId = conv.conversation_id as string;

  const ev = await fetch(`${BASE}/v1/conversations/${seed.convId}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${origin.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      events: [
        {
          event_id: "evt-demo-1",
          kind: "message.user",
          actor: "operator",
          content: "Can you summarize the risks?",
          metadata: { attachments: [] },
        },
        {
          event_id: "evt-demo-2",
          kind: "message.bot",
          actor: "target-bot",
          content: "Here are the top three risks…",
          metadata: { attachments: [] },
        },
        {
          event_id: "evt-demo-3",
          kind: "task.status",
          actor: "",
          content: "",
          metadata: { status: "running", progress: 40 },
        },
      ],
    }),
  });
  expect(ev.ok).toBeTruthy();

  const rt = await fetch(`${BASE}/v1/agents/routed-tasks`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${origin.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      routed_task_id: "demo-routed-task-1",
      parent_conversation_id: seed.convId,
      origin_agent_id: origin.agent_id,
      target_agent_id: target.agent_id,
      title: "Review specification",
      instructions: "Read the attached spec and list blockers.",
      requested_capabilities: ["reviewer"],
      priority: "normal",
      created_at: new Date().toISOString(),
    }),
  });
  expect(rt.ok).toBeTruthy();
});

test("capture all registry UI surfaces", async ({ page }) => {
  const uiToken = "guide-capture-ui-token-2026";

  await page.goto("/ui/login");
  await page.screenshot({ path: path.join(OUT, "00-login.png"), fullPage: true });
  await page.locator('input[type="password"]').fill(uiToken);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL("**/ui**", { timeout: 15000 });

  await page.goto(BASE + "/ui");
  await page.waitForSelector("#agent-list-content .card", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "01-agents.png"), fullPage: true });

  await page.locator("#agent-list-content .card").first().click();
  await page.waitForSelector("#agent-detail-content .card-title", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "02-agent-detail.png"), fullPage: true });

  await page.locator("#agent-detail-content .card").filter({ hasText: /Conversations/ }).click();
  await page.waitForSelector("#agent-convos", { timeout: 15000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "03-agent-conversations.png"), fullPage: true });

  await page.goto(BASE + "/ui/conversations");
  await page.waitForSelector("#convo-list .card, #convo-list .empty-state", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "04-conversations.png"), fullPage: true });

  await page.locator("#convo-list .card").first().click();
  await page.waitForSelector("#convo-timeline, #convo-meta", { timeout: 15000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "05-conversation-detail.png"), fullPage: true });

  await page.goto(BASE + "/ui/tasks");
  await page.waitForSelector("#task-list", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "06-tasks.png"), fullPage: true });

  await page.goto(BASE + "/ui/capabilities");
  await page.waitForSelector("#cap-list", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "07-capabilities.png"), fullPage: true });

  await page.goto(BASE + "/ui/skills");
  await page.waitForSelector("#skill-list", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "08-skills.png"), fullPage: true });

  await page.goto(BASE + "/ui/usage");
  await page.waitForSelector("#usage-content", { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "09-usage.png"), fullPage: true });
});
