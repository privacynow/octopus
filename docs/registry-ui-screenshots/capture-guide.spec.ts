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

/** DOM hooks for the vanilla SPA (no capture-only ids on list views). */
const UI = {
  /** All conversations + tasks: header, `.filter-bar`, list pane, pagination. */
  filterListPane: "#content .filter-bar + div",
  convoSearch: "#content .filter-bar input.search-input",
  /** Skills: no filter-bar — search input sits directly under `.page-header`. */
  skillListPane: "#content .page-header + input.search-input + div",
};
const ENROLL = "guide-capture-enroll-token-2026";
const REPO = path.join(__dirname, "..", "..");
const PY = path.join(REPO, ".venv", "bin", "python");
const DB_SQLITE = path.join(__dirname, ".capture-registry.sqlite3");
const SEED_USAGE = path.join(__dirname, "seed_usage_sqlite.py");

type Bot = { slug: string; display: string; caps: string[]; role: string; tags?: string[] };

/** Rich synthetic fleet for documentation screenshots (lists, badges, search). */
const BOTS: Bot[] = [
  {
    slug: "acme-analytics",
    display: "Acme — Analytics & BI",
    caps: ["python", "sql", "reviewer"],
    role: "developer",
    tags: ["acme", "warehouse", "docs-seed"],
  },
  {
    slug: "acme-reviewer",
    display: "Acme — Code Review",
    caps: ["python", "reviewer", "security"],
    role: "developer",
    tags: ["acme", "quality", "docs-seed"],
  },
  {
    slug: "north-support",
    display: "Northwind — L2 Support",
    caps: ["python", "support", "crm"],
    role: "support",
    tags: ["northwind", "customer", "docs-seed"],
  },
  {
    slug: "gamma-lead",
    display: "Gamma — Platform Lead",
    caps: ["python", "coordination", "terraform"],
    role: "developer",
    tags: ["gamma", "sre", "docs-seed"],
  },
  {
    slug: "contoso-research",
    display: "Contoso — Research Assistant",
    caps: ["python", "retrieval", "reviewer"],
    role: "developer",
    tags: ["contoso", "rag", "docs-seed"],
  },
  {
    slug: "fabrikam-devops",
    display: "Fabrikam — Release Bot",
    caps: ["python", "devops", "kubernetes"],
    role: "developer",
    tags: ["fabrikam", "cicd", "docs-seed"],
  },
  {
    slug: "tailspin-oncall",
    display: "Tailspin — On-call Triage",
    caps: ["python", "support", "pager"],
    role: "support",
    tags: ["tailspin", "incident", "docs-seed"],
  },
  {
    slug: "wingtip-compliance",
    display: "Wingtip — Compliance Review",
    caps: ["python", "reviewer", "policy"],
    role: "developer",
    tags: ["wingtip", "audit", "docs-seed"],
  },
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
    tags: b.tags ?? ["demo", "docs-seed"],
    description: `Docs capture seed — ${b.display} (${b.slug})`,
    provider: "demo",
    mode: "registry",
    channel_capabilities: ["registry"],
    version: "2.4.0",
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

/** Varied chat copy so timelines look distinct in screenshots. */
function buildTimeline(slug: string, convId: string, variant: number): Record<string, unknown>[] {
  const themes = [
    {
      u: "Delta risk for tomorrow's cutover — are we green?",
      b: "**Risk:** low. Redis failover exercised on staging; rollback tested.",
    },
    {
      u: "Customer asked for SLA proof on ticket #4412.",
      b: "**SLA:** 99.2% last 30d. P99 latency 412ms. Attached runbook link in thread.",
    },
    {
      u: "Run the security checklist before we tag v2.4.0.",
      b: "**Checklist:** 12/12 pass. Container scan clean; SBOM attached to release.",
    },
    {
      u: "Handoff: anything queued for the weekend on-call?",
      b: "**Queue:** 2 low-priority items; paging policy unchanged. Runbook `/runbooks/weekend`.",
    },
    {
      u: "Compare embedding providers for the RAG pilot (cost vs latency).",
      b: "**Summary:** Provider A wins on cost; B wins p95. Recommend A for batch, B for interactive.",
    },
    {
      u: "Pipeline failed after the helm chart bump — root cause?",
      b: "**RC:** invalid `imagePullSecret` in values.yaml line 88. Patch drafted in branch `fix/pull-441`.",
    },
    {
      u: "Page fired: checkout errors spiking in eu-west.",
      b: "**Triage:** CDN misroute 7% traffic; mitigation applied 14:02 UTC. Monitoring stable.",
    },
    {
      u: "Need sign-off on data retention policy draft §4.2.",
      b: "**Review:** compliant with SOC2 sample; suggest redacting vendor names in appendix.",
    },
  ];
  const th = themes[variant % themes.length]!;
  return [
    {
      event_id: `e-${convId}-u`,
      kind: "message.user",
      actor: "operator",
      content: th.u,
      metadata: { attachments: [] },
    },
    {
      event_id: `e-${convId}-b`,
      kind: "message.bot",
      actor: slug,
      content: th.b,
      metadata: { attachments: [] },
    },
    {
      event_id: `e-${convId}-p`,
      kind: "provider.response",
      actor: "",
      content: "",
      metadata: { prompt_tokens: 900 + variant * 50, completion_tokens: 140 + variant * 10, cost_usd: 0.002 + variant * 0.0002, tool_calls: [] },
    },
    {
      event_id: `e-${convId}-a`,
      kind: "approval.decided",
      actor: "operator",
      content: "",
      metadata: { action: "approve_change", decided_by: "operator", decision: "approved" },
    },
    {
      event_id: `e-${convId}-t`,
      kind: "task.status",
      actor: "",
      content: "",
      metadata: { status: variant % 2 === 0 ? "running" : "queued", progress: 35 + variant },
    },
    {
      event_id: `e-${convId}-e`,
      kind: "error",
      actor: "",
      content: variant % 3 === 0 ? "Rate limit from upstream API (429) — backing off" : "Transient timeout talking to tool server",
      metadata: { error_type: "execution", message: "retryable" },
    },
  ];
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

  const target = seed.agents[1]!;

  // Each bot: three conversations with distinct titles and timeline variants
  const blueprints: [string, string][] = [
    ["Sprint planning — Q1 roadmap", "plan-q1"],
    ["Customer ticket #4412 — checkout timeout", "nw-4412"],
    ["Security review — container hardening", "sec-harden"],
    ["On-call handoff — weekend queue", "handoff-wknd"],
    ["RAG pilot — embedding evaluation", "rag-pilot"],
    ["Release train — helm chart rollback drill", "rel-helm"],
    ["Incident — eu-west latency spike", "inc-euw"],
    ["Compliance — data retention §4.2", "comp-42"],
    ["Postmortem — cache stampede", "pm-stampede"],
    ["Cost review — LLM spend by team", "cost-llm"],
    ["DR exercise — regional failover", "dr-failover"],
    ["Design doc — workflow engine v3", "wf-v3"],
    ["Backlog grooming — bot capabilities", "bl-cap"],
    ["Partner API — webhook signatures", "api-wh"],
    ["Migration — Postgres cutover window", "pg-cut"],
    ["Metrics — SLO burn rate alerts", "slo-burn"],
    ["Docs — operator manual screenshots", "docs-cap"],
    ["Experiment — tool-use sandbox", "exp-sbx"],
    ["ChatOps — /deploy dry-run", "chatops-dry"],
    ["Audit trail — privileged commands", "audit-priv"],
    ["Training set — red-team prompts", "train-red"],
    ["Staging — synthetic load profile", "stg-load"],
    ["Prod freeze — holiday checklist", "freeze-hol"],
    ["Retro — registry adoption", "retro-reg"],
    ["Weekly report — agent utilization", "wk-util"],
  ];

  let bp = 0;
  for (let i = 0; i < seed.agents.length; i++) {
    const ag = seed.agents[i]!;
    for (let j = 0; j < 3; j++) {
      const [title, ref] = blueprints[bp % blueprints.length]!;
      bp++;
      const channels = ["registry-ui", "telegram", "slack"] as const;
      const cr = await fetch(`${BASE}/v1/conversations`, {
        method: "POST",
        headers: { Authorization: `Bearer ${ag.token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          target_agent_id: ag.id,
          title: `${title} · ${ag.slug}`,
          origin_channel: channels[j % channels.length],
          external_conversation_ref: `${ref}-${i}-${j}-${Date.now()}`,
        }),
      });
      expect(cr.ok).toBeTruthy();
      const conv = await cr.json();
      const cid = conv.conversation_id as string;
      seed.conversations.push(cid);
      await publishEvents(ag.token, cid, buildTimeline(ag.slug, cid, bp + i + j));
    }
  }

  type TaskSeed = {
    id: string;
    title: string;
    instructions: string;
    parentIdx: number;
    originIdx: number;
    targetIdx: number;
    caps: string[];
  };

  const tasks: TaskSeed[] = [
    {
      id: "rt-spec-review",
      title: "Review OpenAPI specification (checkout service)",
      instructions: "List blocking issues; note breaking changes.",
      parentIdx: 0,
      originIdx: 0,
      targetIdx: 1,
      caps: ["reviewer", "python"],
    },
    {
      id: "rt-load-test",
      title: "Run k6 load test on staging (checkout)",
      instructions: "Capture p95/p99; attach Grafana snapshot.",
      parentIdx: 1,
      originIdx: 0,
      targetIdx: 1,
      caps: ["devops", "python"],
    },
    {
      id: "rt-docs-sync",
      title: "Sync public docs with release v2.4.0",
      instructions: "Verify changelog links and version strings.",
      parentIdx: 2,
      originIdx: 1,
      targetIdx: 0,
      caps: ["reviewer"],
    },
    {
      id: "rt-incident-triage",
      title: "Triage P1 — payment webhook failures",
      instructions: "Correlate with deploy window T-45m.",
      parentIdx: 3,
      originIdx: 2,
      targetIdx: 3,
      caps: ["support", "python"],
    },
    {
      id: "rt-compliance-audit",
      title: "SOC2 evidence — access log sample",
      instructions: "Export last 30d admin actions (redacted).",
      parentIdx: 4,
      originIdx: 4,
      targetIdx: 7,
      caps: ["policy", "reviewer"],
    },
    {
      id: "rt-helm-diff",
      title: "Helm diff — redis chart 18.x → 19.x",
      instructions: "Flag securityContext changes.",
      parentIdx: 5,
      originIdx: 5,
      targetIdx: 3,
      caps: ["kubernetes", "reviewer"],
    },
    {
      id: "rt-rag-eval",
      title: "Benchmark retrieval — legal corpus subset",
      instructions: "nDCG@10 vs baseline; cost per query.",
      parentIdx: 6,
      originIdx: 4,
      targetIdx: 4,
      caps: ["retrieval", "python"],
    },
  ];

  for (const tk of tasks) {
    const o = seed.agents[tk.originIdx]!;
    const t = seed.agents[tk.targetIdx]!;
    const parent = seed.conversations[tk.parentIdx]!;
    const rt = await fetch(`${BASE}/v1/agents/routed-tasks`, {
      method: "POST",
      headers: { Authorization: `Bearer ${o.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        routed_task_id: tk.id,
        parent_conversation_id: parent,
        origin_agent_id: o.id,
        target_agent_id: t.id,
        title: tk.title,
        instructions: tk.instructions,
        requested_capabilities: tk.caps,
        priority: "high",
        created_at: new Date().toISOString(),
      }),
    });
    expect(rt.ok).toBeTruthy();
  }

  const postStatus = (taskId: string, token: string, body: Record<string, unknown>) =>
    fetch(`${BASE}/v1/agents/routed-tasks/${taskId}/status`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  await postStatus("rt-load-test", target.token, {
    status: "running",
    summary: "k6: 1.2k RPS sustained; collecting p95 …",
    timeline_events: [],
  });
  await postStatus("rt-spec-review", target.token, {
    status: "completed",
    summary: "Approved — no blocking issues; nits in comments.",
    timeline_events: [],
  });
  await postStatus("rt-incident-triage", seed.agents[3]!.token, {
    status: "failed",
    summary: "Root cause inconclusive — need DB slow-query log.",
    timeline_events: [],
  });
  await postStatus("rt-helm-diff", seed.agents[3]!.token, {
    status: "running",
    summary: "Rendering manifests for redis 19.1.2 …",
    timeline_events: [],
  });
  await postStatus("rt-compliance-audit", seed.agents[7]!.token, {
    status: "completed",
    summary: "Evidence bundle uploaded to secure share.",
    timeline_events: [],
  });

  const iso = new Date().toISOString();
  const workerStories = [
    [
      {
        worker_id: "worker-ledger",
        process_role: "worker",
        started_at: iso,
        last_seen_at: iso,
        current_item_id: "queue-checkout-42",
        current_conversation_key: "tg:acme-prod",
        current_kind: "message",
        items_processed: 1840,
        stale_recoveries_seen: 0,
        last_error: "",
      },
      {
        worker_id: "worker-batch",
        process_role: "worker",
        started_at: iso,
        last_seen_at: iso,
        current_item_id: "idle",
        current_conversation_key: "",
        current_kind: "",
        items_processed: 622,
        stale_recoveries_seen: 2,
        last_error: "",
      },
    ],
    [
      {
        worker_id: "reviewer-1",
        process_role: "worker",
        started_at: iso,
        last_seen_at: iso,
        current_item_id: "pr-8841-diff",
        current_conversation_key: "registry-ui:review",
        current_kind: "tool",
        items_processed: 412,
        stale_recoveries_seen: 0,
        last_error: "",
      },
    ],
    [
      {
        worker_id: "support-router",
        process_role: "worker",
        started_at: iso,
        last_seen_at: iso,
        current_item_id: "ticket-4412",
        current_conversation_key: "slack:northwind",
        current_kind: "message",
        items_processed: 901,
        stale_recoveries_seen: 0,
        last_error: "",
      },
    ],
  ];

  for (let idx = 0; idx < seed.agents.length; idx++) {
    const ag = seed.agents[idx]!;
    const workers = workerStories[idx % workerStories.length]!;
    await fetch(`${BASE}/v1/agents/heartbeat`, {
      method: "POST",
      headers: { Authorization: `Bearer ${ag.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        connectivity_state: "connected",
        current_capacity: idx === 0 ? 2 : 1,
        max_capacity: 8,
        runtime_health: { snapshot: { workers } },
      }),
    });
  }

  // Usage rows (kind=usage) — not in SDK publish path; one per conversation for a full table
  execFileSync(PY, [SEED_USAGE, DB_SQLITE, ...seed.conversations], {
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
    { selector: "#agent-convos-section", label: "Conversations (inline, paginated)", color: "#4caf50", pad: 6 },
  ]);

  await page.goto(`${BASE}/ui/agents/${firstAgentId}/conversations`);
  await page.waitForSelector("#agent-convos .card, #agent-convos .empty-state", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "03-agent-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "03-agent-conversations.png"), [
    { selector: "#agent-convos", label: "Conversations where this agent is involved", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(BASE + "/ui/conversations");
  await page.waitForSelector(`${UI.filterListPane} .card.clickable, ${UI.filterListPane} .empty-state`, {
    timeout: 20000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "04-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "04-conversations.png"), [
    { selector: UI.convoSearch, label: "Type 3+ chars to search (FTS)", color: "#ff9800", pad: 4 },
    { selector: UI.filterListPane, label: "All conversations across agents", color: "#2196f3", pad: 6 },
  ]);

  await page.locator(UI.convoSearch).fill("Acme");
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, "04b-conversations-filtered.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "04b-conversations-filtered.png"), [
    { selector: UI.convoSearch, label: "Filtered list (search debounced)", color: "#ff9800", pad: 4 },
    { selector: UI.filterListPane, label: "Matches title / FTS snippet", color: "#2196f3", pad: 6 },
  ]);

  await page.locator(UI.convoSearch).fill("");
  await page.waitForTimeout(400);
  await page.locator(`${UI.filterListPane} .card.clickable`).first().click();
  await page.waitForSelector("#convo-timeline", { timeout: 20000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "05-conversation-detail.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "05-conversation-detail.png"), [
    { selector: "#convo-meta", label: "Title · channel · status", color: "#ff9800", pad: 6 },
    { selector: "#convo-timeline", label: "Timeline: bubbles + event cards", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(BASE + "/ui/tasks");
  await page.waitForSelector(`${UI.filterListPane} table.data-table, ${UI.filterListPane} .empty-state`, {
    timeout: 20000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "06-tasks.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "06-tasks.png"), [
    {
      selector: `${UI.filterListPane} table.data-table`,
      label: "Routed tasks — click row → parent conversation",
      color: "#2196f3",
      pad: 8,
    },
  ]);

  await page.goto(BASE + "/ui/capabilities");
  await page.waitForSelector("#cap-list .card, #cap-list .empty-state", { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "07-capabilities.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "07-capabilities.png"), [
    { selector: "#cap-list", label: "Declared by agents + optional overrides", color: "#2196f3", pad: 8 },
  ]);

  await page.goto(BASE + "/ui/skills");
  await page.waitForSelector(`${UI.skillListPane} .card, ${UI.skillListPane} .empty-state`, { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "08-skills.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "08-skills.png"), [
    { selector: UI.skillListPane, label: "Catalog entries from registry store", color: "#ff9800", pad: 8 },
  ]);

  await page.goto(BASE + "/ui/usage");
  await page.waitForFunction(
    () => {
      const summary = document.querySelector("#usage-summary .summary-card");
      const table = document.querySelector("#usage-table table");
      const empty = document.querySelector("#usage-table .empty-state");
      return !!(summary && (table || empty));
    },
    null,
    { timeout: 20000 },
  );
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "09-usage.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "09-usage.png"), [
    {
      selector: "#usage-table table, #usage-table .empty-state",
      label: "Aggregated from usage events (seeded in capture)",
      color: "#2196f3",
      pad: 8,
    },
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
