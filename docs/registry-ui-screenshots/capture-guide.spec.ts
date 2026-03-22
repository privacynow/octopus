/**
 * Captures the Registry UI for docs. Seeds SQLite via HTTP (+ usage rows via sqlite),
 * then screenshots every route with Playwright-generated overlay metadata for annotate.py.
 */
import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import * as fs from "fs";
import * as path from "path";

const OUT = path.join(__dirname, "..", "assets", "registry", "ui");
const BASE = "http://127.0.0.1:19987";
const ENROLL = "guide-capture-enroll-token-2026";
const REPO = path.join(__dirname, "..", "..");
const PY = path.join(REPO, ".venv", "bin", "python");
const DB_SQLITE = path.join(__dirname, ".capture-registry.sqlite3");
const SEED_USAGE = path.join(__dirname, "seed_usage_sqlite.py");

type Bot = { slug: string; display: string; caps: string[]; role: string };

const BOTS: Bot[] = [
  { slug: "acme-analytics", display: "Acme — Analytics Bot", caps: ["python", "sql", "reviewer"], role: "developer" },
  { slug: "acme-reviewer", display: "Acme — Code Review", caps: ["python", "reviewer"], role: "developer" },
  { slug: "north-support", display: "Northwind Support", caps: ["python", "support"], role: "support" },
  { slug: "gamma-lead", display: "Gamma Team Lead", caps: ["python", "coordination"], role: "developer" },
];

const seed: {
  agents: { id: string; token: string; slug: string }[];
  conversations: string[];
} = { agents: [], conversations: [] };

function card(b: Bot) {
  return {
    display_name: b.display,
    slug: b.slug,
    role: b.role,
    registry_scope: "full",
    capabilities: b.caps,
    tags: ["demo", "synthetic"],
    description: `Synthetic bot for docs: ${b.slug}`,
    provider: "demo",
    mode: "registry",
    channel_capabilities: ["registry"],
    version: "2.1.0",
  };
}

async function enrollAgent(b: Bot): Promise<{ agent_id: string; token: string }> {
  const r = await fetch(`${BASE}/v1/agents/enroll`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enrollment_token: ENROLL, agent_card: card(b) }),
  });
  expect(r.ok).toBeTruthy();
  const j = await r.json();
  const token = j.agent_token as string;
  const reg = await fetch(`${BASE}/v1/agents/register`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_card: card(b),
      connectivity_state: "connected",
      current_capacity: 1,
      max_capacity: 8,
    }),
  });
  expect(reg.ok).toBeTruthy();
  return { agent_id: j.agent_id as string, token };
}

async function publishEvents(token: string, convId: string, events: Record<string, unknown>[]) {
  const ev = await fetch(`${BASE}/v1/conversations/${convId}/events`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
  });
  expect(ev.ok).toBeTruthy();
}

async function absRect(page: import("@playwright/test").Page, selector: string) {
  const n = await page.locator(selector).first().count();
  if (n === 0) return null;
  return page.locator(selector).first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
  });
}

async function writeOverlayMeta(
  page: import("@playwright/test").Page,
  pngPath: string,
  rects: Array<{ selector: string; label: string; color?: string; pad?: number }>,
  arrows: Array<{ fromSel: string; toSel: string }> = [],
) {
  const metaPath = pngPath.replace(/\.png$/i, ".meta.json");
  const outRects: Array<{
    x: number;
    y: number;
    width: number;
    height: number;
    label?: string;
    color?: string;
  }> = [];
  for (const r of rects) {
    const box = await absRect(page, r.selector);
    if (!box) continue;
    const pad = r.pad ?? 6;
    outRects.push({
      x: Math.max(0, box.x - pad),
      y: Math.max(0, box.y - pad),
      width: box.width + 2 * pad,
      height: box.height + 2 * pad,
      label: r.label,
      color: r.color ?? "#ff9800",
    });
  }
  const arrowPixels: Array<{ x1: number; y1: number; x2: number; y2: number }> = [];
  for (const a of arrows) {
    const ra = await absRect(page, a.fromSel);
    const rb = await absRect(page, a.toSel);
    if (!ra || !rb) continue;
    const x1 = ra.x + ra.width / 2;
    const y1 = ra.y + ra.height;
    const x2 = rb.x + rb.width / 2;
    const y2 = rb.y;
    arrowPixels.push({ x1, y1, x2, y2 });
  }
  await fs.promises.writeFile(metaPath, JSON.stringify({ rects: outRects, arrows: arrowPixels }, null, 2), "utf-8");
}

test.beforeAll(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  for (const b of BOTS) {
    const { agent_id, token } = await enrollAgent(b);
    seed.agents.push({ id: agent_id, token, slug: b.slug });
  }

  const origin = seed.agents[0]!;
  const target = seed.agents[1]!;

  // Each bot: two conversations (self-targeted) with rich timelines
  const titles = [
    ["Sprint planning — Q1", "acme-plan-q1"],
    ["Customer ticket #4412", "nw-ticket-4412"],
    ["Security review checklist", "gamma-sec-1"],
    ["On-call handoff", "gamma-handoff"],
  ];
  let t = 0;
  for (let i = 0; i < seed.agents.length; i++) {
    const ag = seed.agents[i]!;
    for (let j = 0; j < 2; j++) {
      const [title, ref] = titles[t % titles.length]!;
      t++;
      const cr = await fetch(`${BASE}/v1/conversations`, {
        method: "POST",
        headers: { Authorization: `Bearer ${ag.token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          target_agent_id: ag.id,
          title: `${title} (${ag.slug})`,
          origin_channel: j === 0 ? "registry-ui" : "telegram",
          external_conversation_ref: `${ref}-${i}-${j}-${Date.now()}`,
        }),
      });
      expect(cr.ok).toBeTruthy();
      const conv = await cr.json();
      const cid = conv.conversation_id as string;
      seed.conversations.push(cid);

      await publishEvents(ag.token, cid, [
        {
          event_id: `e-${cid}-1`,
          kind: "message.user",
          actor: "operator",
          content: "Status check: are we green for deploy?",
          metadata: { attachments: [] },
        },
        {
          event_id: `e-${cid}-2`,
          kind: "message.bot",
          actor: ag.slug,
          content: "**Summary:** tests pass; one flaky integration test on CI.",
          metadata: { attachments: [] },
        },
        {
          event_id: `e-${cid}-3`,
          kind: "provider.response",
          actor: "",
          content: "",
          metadata: { prompt_tokens: 800, completion_tokens: 120, cost_usd: 0.002, tool_calls: [] },
        },
        {
          event_id: `e-${cid}-4`,
          kind: "approval.decided",
          actor: "operator",
          content: "",
          metadata: { action: "approve_deploy", decided_by: "operator", decision: "approved" },
        },
        {
          event_id: `e-${cid}-5`,
          kind: "task.status",
          actor: "",
          content: "",
          metadata: { status: "running", progress: 65 },
        },
        {
          event_id: `e-${cid}-6`,
          kind: "error",
          actor: "",
          content: "Transient timeout talking to tool server",
          metadata: { error_type: "execution", message: "timeout" },
        },
      ]);
    }
  }

  const parentConv = seed.conversations[0]!;

  const tasks = [
    {
      id: "rt-spec-review",
      title: "Review API specification",
      instructions: "List blocking issues only.",
    },
    {
      id: "rt-load-test",
      title: "Run load test on staging",
      instructions: "Capture p95 latency.",
    },
    {
      id: "rt-docs-sync",
      title: "Sync public docs with release",
      instructions: "Verify changelog links.",
    },
  ];
  for (const tk of tasks) {
    const rt = await fetch(`${BASE}/v1/agents/routed-tasks`, {
      method: "POST",
      headers: { Authorization: `Bearer ${origin.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        routed_task_id: tk.id,
        parent_conversation_id: parentConv,
        origin_agent_id: origin.id,
        target_agent_id: target.id,
        title: tk.title,
        instructions: tk.instructions,
        requested_capabilities: ["reviewer"],
        priority: "high",
        created_at: new Date().toISOString(),
      }),
    });
    expect(rt.ok).toBeTruthy();
  }

  await fetch(`${BASE}/v1/agents/routed-tasks/rt-load-test/status`, {
    method: "POST",
    headers: { Authorization: `Bearer ${target.token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      status: "running",
      summary: "Executing k6 scenario …",
      timeline_events: [],
    }),
  });

  const iso = new Date().toISOString();
  await fetch(`${BASE}/v1/agents/heartbeat`, {
    method: "POST",
    headers: { Authorization: `Bearer ${origin.token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      connectivity_state: "connected",
      current_capacity: 2,
      max_capacity: 8,
      runtime_health: {
        snapshot: {
          workers: [
            {
              worker_id: "worker-a1",
              process_role: "worker",
              started_at: iso,
              last_seen_at: iso,
              current_item_id: "queue-42",
              current_conversation_key: "tg:demo",
              current_kind: "message",
              items_processed: 128,
              stale_recoveries_seen: 0,
              last_error: "",
            },
            {
              worker_id: "worker-a2",
              process_role: "worker",
              started_at: iso,
              last_seen_at: iso,
              current_item_id: "idle",
              current_conversation_key: "",
              current_kind: "",
              items_processed: 64,
              stale_recoveries_seen: 1,
              last_error: "",
            },
          ],
        },
      },
    }),
  });

  // Usage rows (kind=usage) — not in SDK publish path
  execFileSync(PY, [SEED_USAGE, DB_SQLITE, ...seed.conversations.slice(0, 6)], {
    stdio: "inherit",
  });
});

test("capture all registry UI surfaces", async ({ page }) => {
  const uiToken = "guide-capture-ui-token-2026";
  const firstAgentId = seed.agents[0]!.id;

  await page.goto("/ui/login");
  await page.screenshot({ path: path.join(OUT, "00-login.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "00-login.png"), [
    { selector: "form", label: "Password = REGISTRY_UI_TOKEN", color: "#2196f3", pad: 10 },
    { selector: 'input[type="password"]', label: "Operator credential", color: "#ff9800", pad: 8 },
  ]);

  await page.locator('input[type="password"]').fill(uiToken);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL("**/ui**", { timeout: 15000 });

  await page.goto(BASE + "/ui");
  await page.waitForSelector("#agent-list-content .card", { timeout: 20000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "01-agents.png"), fullPage: true });
  await writeOverlayMeta(
    page,
    path.join(OUT, "01-agents.png"),
    [
      { selector: "#sidebar", label: "Primary navigation (7 areas)", color: "#ff9800", pad: 4 },
      { selector: "#agent-list-content .card:nth-child(1)", label: "Agent row → detail", color: "#2196f3", pad: 6 },
      { selector: "#agent-list-content .card:nth-child(2)", label: "Another enrolled bot", color: "#4caf50", pad: 6 },
    ],
    [{ fromSel: ".page-header h2", toSel: "#agent-list-content .card:nth-child(1)" }],
  );

  await page.locator("#agent-list-content .card").first().click();
  await page.waitForSelector("#agent-detail-content .data-table", { timeout: 20000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "02-agent-detail.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "02-agent-detail.png"), [
    { selector: ".page-header", label: "Display name & connectivity badge", color: "#ff9800", pad: 6 },
    { selector: "#agent-detail-content .card:first-of-type .data-table", label: "Identity, scope, capabilities", color: "#2196f3", pad: 6 },
    { selector: "#agent-detail-content .card:nth-of-type(2) .data-table", label: "Worker processes (heartbeat)", color: "#9c27b0", pad: 4 },
    { selector: "#agent-detail-content .card:last-of-type", label: "Conversations → (scoped list)", color: "#4caf50", pad: 6 },
  ]);

  await page.locator("#agent-detail-content .card").filter({ hasText: /Conversations/ }).click();
  await page.waitForSelector("#agent-convos .card, #agent-convos .empty-state", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "03-agent-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "03-agent-conversations.png"), [
    { selector: "#agent-convos", label: "Conversations where this agent is involved", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(BASE + "/ui/conversations");
  await page.waitForSelector("#convo-list .card", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "04-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "04-conversations.png"), [
    { selector: "#convo-search", label: "Type 3+ chars to search (FTS)", color: "#ff9800", pad: 4 },
    { selector: "#convo-list", label: "All conversations across agents", color: "#2196f3", pad: 6 },
  ]);

  await page.locator("#convo-search").fill("Acme");
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, "04b-conversations-filtered.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "04b-conversations-filtered.png"), [
    { selector: "#convo-search", label: "Filtered list (search debounced)", color: "#ff9800", pad: 4 },
    { selector: "#convo-list", label: "Matches title / FTS snippet", color: "#2196f3", pad: 6 },
  ]);

  await page.locator("#convo-search").fill("");
  await page.waitForTimeout(400);
  await page.locator("#convo-list .card").first().click();
  await page.waitForSelector("#convo-timeline", { timeout: 20000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "05-conversation-detail.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "05-conversation-detail.png"), [
    { selector: "#convo-meta", label: "Title · channel · status", color: "#ff9800", pad: 6 },
    { selector: "#convo-timeline", label: "Timeline: bubbles + event cards", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(BASE + "/ui/tasks");
  await page.waitForSelector("#task-list table, #task-list .empty-state", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "06-tasks.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "06-tasks.png"), [
    { selector: "#task-list table", label: "Routed tasks — click row → parent conversation", color: "#2196f3", pad: 8 },
  ]);

  await page.goto(BASE + "/ui/capabilities");
  await page.waitForSelector("#cap-list .card, #cap-list .empty-state", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "07-capabilities.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "07-capabilities.png"), [
    { selector: "#cap-list", label: "Declared by agents + optional overrides", color: "#2196f3", pad: 8 },
  ]);

  await page.goto(BASE + "/ui/skills");
  await page.waitForSelector("#skill-list", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "08-skills.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "08-skills.png"), [
    { selector: "#skill-list", label: "Catalog entries from registry store", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(BASE + "/ui/usage");
  await page.waitForSelector("#usage-content", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "09-usage.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "09-usage.png"), [
    { selector: "#usage-content table, #usage-content .empty-state", label: "Aggregated from usage events (seeded in capture)", color: "#2196f3", pad: 8 },
  ]);

  // Deep-link sanity: second agent by URL
  await page.goto(`${BASE}/ui/agents/${firstAgentId}`);
  await page.waitForSelector("#agent-detail-content", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "10-agent-detail-deep-link.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "10-agent-detail-deep-link.png"), [
    { selector: "#content", label: "Same view via /ui/agents/{id} (bookmarkable)", color: "#4caf50", pad: 6 },
  ]);

  const firstConvId = seed.conversations[0]!;
  await page.goto(`${BASE}/ui/conversations/${firstConvId}`);
  await page.waitForSelector("#convo-timeline, #convo-meta", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "11-conversation-deep-link.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "11-conversation-deep-link.png"), [
    { selector: "#convo-meta", label: "Loaded by URL /ui/conversations/{id}", color: "#4caf50", pad: 6 },
    { selector: "#convo-timeline", label: "Same timeline as row navigation", color: "#2196f3", pad: 6 },
  ]);
});
