/**
 * Captures the current Registry UI for docs.
 *
 * The capture flow seeds the live registry over HTTP using the current SDK/API
 * contract, then screenshots each SPA route and writes sibling *.meta.json
 * files for annotate.py.
 */
import { expect, test } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const OUT = path.join(__dirname, "..", "assets", "registry", "ui");
const BASE = "http://127.0.0.1:19987";
const ENROLL = "guide-capture-enroll-token-2026";
const UI_TOKEN = "guide-capture-ui-token-2026";

type Bot = {
  slug: string;
  display: string;
  role: string;
  provider: string;
  scope: "full" | "channel" | "coordination";
  capabilities: string[];
  tags: string[];
  state: "connected" | "degraded";
};

type SeedAgent = {
  id: string;
  token: string;
  slug: string;
  display: string;
};

type SeedConversation = {
  id: string;
  title: string;
  agentId: string;
};

const BOTS: Bot[] = [
  {
    slug: "release-coordinator",
    display: "Release Coordinator",
    role: "developer",
    provider: "codex",
    scope: "full",
    capabilities: ["python", "reviewer", "registry"],
    tags: ["release", "ops", "docs"],
    state: "connected",
  },
  {
    slug: "risk-reviewer",
    display: "Risk Reviewer",
    role: "developer",
    provider: "claude",
    scope: "full",
    capabilities: ["reviewer", "security", "policy"],
    tags: ["risk", "compliance", "docs"],
    state: "connected",
  },
  {
    slug: "support-triage",
    display: "Support Triage",
    role: "support",
    provider: "codex",
    scope: "channel",
    capabilities: ["support", "crm", "python"],
    tags: ["support", "tickets", "docs"],
    state: "connected",
  },
  {
    slug: "platform-sre",
    display: "Platform SRE",
    role: "developer",
    provider: "claude",
    scope: "coordination",
    capabilities: ["terraform", "kubernetes", "devops"],
    tags: ["sre", "infra", "docs"],
    state: "degraded",
  },
  {
    slug: "retrieval-lab",
    display: "Retrieval Lab",
    role: "developer",
    provider: "codex",
    scope: "full",
    capabilities: ["retrieval", "python", "analysis"],
    tags: ["rag", "research", "docs"],
    state: "connected",
  },
  {
    slug: "audit-lead",
    display: "Audit Lead",
    role: "developer",
    provider: "claude",
    scope: "full",
    capabilities: ["policy", "reviewer", "security"],
    tags: ["audit", "controls", "docs"],
    state: "connected",
  },
];

const seed: {
  agents: SeedAgent[];
  conversations: SeedConversation[];
  focusAgentId: string;
  focusConversationId: string;
  focusConversationTitle: string;
} = {
  agents: [],
  conversations: [],
  focusAgentId: "",
  focusConversationId: "",
  focusConversationTitle: "",
};

function iso(offsetMinutes: number): string {
  return new Date(Date.now() + offsetMinutes * 60_000).toISOString();
}

function card(bot: Bot) {
  return {
    bot_key: `bot:${bot.slug}`,
    display_name: bot.display,
    slug: bot.slug,
    role: bot.role,
    registry_scope: bot.scope,
    capabilities: bot.capabilities,
    tags: bot.tags,
    description: `Docs capture seed — ${bot.display}`,
    provider: bot.provider,
    mode: "registry",
    channel_capabilities: ["registry"],
    version: "3.0.0-docs",
  };
}

async function enrollAgent(bot: Bot): Promise<SeedAgent> {
  const enrollResp = await fetch(`${BASE}/v1/agents/enroll`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enrollment_token: ENROLL,
      agent_card: card(bot),
    }),
  });
  const enrollText = await enrollResp.text();
  expect(enrollResp.ok, enrollText).toBeTruthy();
  const enrolled = JSON.parse(enrollText);
  const token = enrolled.agent_token as string;

  const registerResp = await fetch(`${BASE}/v1/agents/register`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      agent_card: card(bot),
      connectivity_state: bot.state,
      current_capacity: bot.state === "degraded" ? 1 : 0,
      max_capacity: 6,
    }),
  });
  expect(registerResp.ok, await registerResp.text()).toBeTruthy();
  return {
    id: enrolled.agent_id as string,
    token,
    slug: bot.slug,
    display: bot.display,
  };
}

async function heartbeatAgent(agent: SeedAgent, state: "connected" | "degraded", workerId: string, currentItem: string) {
  const now = new Date().toISOString();
  const resp = await fetch(`${BASE}/v1/agents/heartbeat`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${agent.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      connectivity_state: state,
      current_capacity: state === "degraded" ? 2 : 1,
      max_capacity: 6,
      runtime_health: {
        snapshot: {
          workers: [
            {
              worker_id: workerId,
              process_role: "worker",
              started_at: now,
              last_seen_at: now,
              current_item_id: currentItem,
              current_conversation_key: `registry:${agent.slug}`,
              current_kind: "message",
              items_processed: 100 + workerId.length,
              stale_recoveries_seen: state === "degraded" ? 1 : 0,
              last_error: state === "degraded" ? "slow upstream response" : "",
            },
          ],
        },
      },
    }),
  });
  expect(resp.ok, await resp.text()).toBeTruthy();
}

async function createConversation(agent: SeedAgent, title: string, externalRef: string): Promise<string> {
  const resp = await fetch(`${BASE}/v1/conversations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${agent.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      target_agent_id: agent.id,
      origin_channel: "registry",
      external_conversation_ref: externalRef,
      title,
    }),
  });
  const responseText = await resp.text();
  expect(resp.ok, responseText).toBeTruthy();
  const json = JSON.parse(responseText);
  return json.conversation_id as string;
}

function eventId(conversationId: string, suffix: string): string {
  return `${conversationId}-${suffix}`;
}

function buildTimeline(conversationId: string, actor: string, focus = false, pendingApproval = false) {
  const proposalId = eventId(conversationId, "delegation-proposal");
  const tasks = [
    {
      draft_id: `${conversationId}-draft-1`,
      title: "Check rollout checklist",
      target: "risk-reviewer",
      status: pendingApproval ? "proposed" : "submitted",
    },
    {
      draft_id: `${conversationId}-draft-2`,
      title: "Validate change window",
      target: "audit-lead",
      status: pendingApproval ? "proposed" : "submitted",
    },
  ];

  const events: Array<Record<string, unknown>> = [
    {
      event_id: eventId(conversationId, "message-user"),
      kind: "message.user",
      actor: "operator",
      content: focus
        ? "Kick off a release readiness review and call out any blocking risks."
        : `Review ${actor} status and summarize next actions.`,
      created_at: iso(-90),
      metadata: {},
    },
    {
      event_id: eventId(conversationId, "provider-request"),
      kind: "provider.request",
      actor: "",
      content: "Inspect the current state, propose next steps, and surface the most urgent blockers.",
      created_at: iso(-82),
      metadata: {
        provider: focus ? "codex" : "claude",
        model: focus ? "gpt-5.4" : "claude-sonnet-4-5",
        execution_mode: "run",
        working_dir: "/workspace/repo",
        file_policy: "edit",
        image_count: 0,
        prompt_char_count: focus ? 742 : 598,
      },
    },
    {
      event_id: eventId(conversationId, "provider-response"),
      kind: "provider.response",
      actor: "",
      content: "",
      created_at: iso(-74),
      metadata: {
        prompt_tokens: focus ? 1480 : 920,
        completion_tokens: focus ? 312 : 181,
        cost_usd: focus ? 0.0384 : 0.0187,
        provider: focus ? "codex" : "claude",
      },
    },
    {
      event_id: eventId(conversationId, "tool-execution"),
      kind: "tool.execution",
      actor: "",
      content: "exec_command completed",
      created_at: iso(-66),
      metadata: {
        tool_name: "exec_command",
        call_id: eventId(conversationId, "tool-call"),
        status: "completed",
        input_summary: focus ? "git diff --stat" : "rg release docs/",
        output_summary: focus ? "2 files changed, 34 insertions" : "3 matching guide references",
        duration_ms: focus ? 142 : 96,
        file_changes: focus
          ? [
              {
                path: "docs/manual/03-operator-registry.md",
                change_type: "modified",
                summary: "Updated dashboard and conversation notes",
              },
            ]
          : [],
      },
    },
  ];

  if (pendingApproval) {
    events.push({
      event_id: eventId(conversationId, "approval-requested"),
      kind: "approval.requested",
      actor: "operator",
      content: "Approve the final rollout checklist before continuing?",
      created_at: iso(-58),
      metadata: {
        request_kind: "retry",
        actor_key: "telegram:42",
        trust_tier: "trusted",
        expires_at: iso(45),
      },
    });
    events.push({
      event_id: eventId(conversationId, "delegation-proposed"),
      kind: "delegation.proposed",
      actor: "",
      content: "",
      created_at: iso(-49),
      metadata: { proposal_id: proposalId, tasks },
    });
  } else {
    events.push(
      {
        event_id: eventId(conversationId, "approval-requested"),
        kind: "approval.requested",
        actor: "operator",
        content: "Approve a final release checklist pass?",
        created_at: iso(-58),
        metadata: {
          request_kind: "preflight",
          actor_key: "telegram:42",
          trust_tier: "trusted",
          expires_at: iso(45),
        },
      },
      {
        event_id: eventId(conversationId, "approval-decided"),
        kind: "approval.decided",
        actor: "operator",
        content: "",
        created_at: iso(-54),
        metadata: {
          action: "approve",
          decided_by: "operator",
          decision: "approved",
        },
      },
      {
        event_id: eventId(conversationId, "delegation-submitted"),
        kind: "delegation.submitted",
        actor: "",
        content: "",
        created_at: iso(-47),
        metadata: { proposal_id: proposalId, tasks },
      },
      {
        event_id: eventId(conversationId, "delegation-completed"),
        kind: "delegation.completed",
        actor: "",
        content: "",
        created_at: iso(-39),
        metadata: {
          proposal_id: proposalId,
          tasks: tasks.map((task) => ({ ...task, status: "completed" })),
        },
      },
    );
  }

  events.push(
    {
      event_id: eventId(conversationId, "task-status"),
      kind: "task.status",
      actor: "",
      content: pendingApproval
        ? "Waiting for operator approval before continuing."
        : "Checklist verification is still running.",
      created_at: iso(-28),
      metadata: {
        routed_task_id: `${conversationId}-task-status`,
        status: pendingApproval ? "queued" : "running",
        progress: pendingApproval ? 12 : 68,
      },
    },
    {
      event_id: eventId(conversationId, "error"),
      kind: "error",
      actor: "",
      content: pendingApproval
        ? "Blocked on an operator decision."
        : "One dependency check needs a second verification pass.",
      created_at: iso(-18),
      metadata: {
        error_type: pendingApproval ? "approval" : "execution",
        message: pendingApproval
          ? "approval is still pending"
          : "one dependency check needs a second verification pass",
      },
    },
    {
      event_id: eventId(conversationId, "message-bot"),
      kind: "message.bot",
      actor,
      content: pendingApproval
        ? "Approval is pending. I will continue once the operator decides."
        : "Release review is mostly green. One dependency needs a final follow-up before launch.",
      created_at: iso(-8),
      metadata: {},
    },
  );

  return events;
}

async function publishEvents(agent: SeedAgent, conversationId: string, focus = false, pendingApproval = false) {
  const events = buildTimeline(conversationId, agent.slug, focus, pendingApproval);
  const resp = await fetch(`${BASE}/v1/conversations/${conversationId}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${agent.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ events }),
  });
  const text = await resp.text();
  expect(resp.ok, text).toBeTruthy();
  const payload = JSON.parse(text);
  expect(payload.inserted).toBe(events.length);
  expect(payload.skipped).toBe(0);
}

async function createRoutedTask(
  origin: SeedAgent,
  target: SeedAgent,
  parentConversationId: string,
  routedTaskId: string,
  title: string,
  instructions: string,
  requestedCapabilities: string[],
) {
  const resp = await fetch(`${BASE}/v1/agents/routed-tasks`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${origin.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      routed_task_id: routedTaskId,
      parent_conversation_id: parentConversationId,
      origin_agent_id: origin.id,
      target_agent_id: target.id,
      title,
      instructions,
      requested_capabilities: requestedCapabilities,
      priority: "high",
      created_at: new Date().toISOString(),
    }),
  });
  expect(resp.ok, await resp.text()).toBeTruthy();
}

async function updateTaskStatus(agentToken: string, routedTaskId: string, payload: Record<string, unknown>) {
  const resp = await fetch(`${BASE}/v1/agents/routed-tasks/${routedTaskId}/status`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${agentToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  expect(resp.ok, await resp.text()).toBeTruthy();
}

async function reportTaskResult(agentToken: string, routedTaskId: string, payload: Record<string, unknown>) {
  const resp = await fetch(`${BASE}/v1/agents/routed-tasks/${routedTaskId}/result`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${agentToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  expect(resp.ok, await resp.text()).toBeTruthy();
}

async function absRect(page: import("@playwright/test").Page, selector: string) {
  const count = await page.locator(selector).first().count();
  if (count === 0) return null;
  return page.locator(selector).first().evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return {
      x: rect.left + window.scrollX,
      y: rect.top + window.scrollY,
      width: rect.width,
      height: rect.height,
    };
  });
}

async function writeOverlayMeta(
  page: import("@playwright/test").Page,
  pngPath: string,
  rects: Array<{ selector: string; label: string; color?: string; pad?: number }>,
  arrows: Array<{ fromSel: string; toSel: string }> = [],
) {
  const metaPath = pngPath.replace(/\.png$/i, ".meta.json");
  const outRects: Array<{ x: number; y: number; width: number; height: number; label?: string; color?: string }> = [];
  for (const rect of rects) {
    const box = await absRect(page, rect.selector);
    if (!box) continue;
    const pad = rect.pad ?? 6;
    outRects.push({
      x: Math.max(0, box.x - pad),
      y: Math.max(0, box.y - pad),
      width: box.width + 2 * pad,
      height: box.height + 2 * pad,
      label: rect.label,
      color: rect.color ?? "#ff9800",
    });
  }
  const outArrows: Array<{ x1: number; y1: number; x2: number; y2: number }> = [];
  for (const arrow of arrows) {
    const from = await absRect(page, arrow.fromSel);
    const to = await absRect(page, arrow.toSel);
    if (!from || !to) continue;
    outArrows.push({
      x1: from.x + from.width / 2,
      y1: from.y + from.height,
      x2: to.x + to.width / 2,
      y2: to.y,
    });
  }
  await fs.promises.writeFile(metaPath, JSON.stringify({ rects: outRects, arrows: outArrows }, null, 2), "utf-8");
}

async function waitForViewReady(page: import("@playwright/test").Page, selector?: string) {
  await page.waitForFunction(() => {
    const content = document.getElementById("content");
    const inner = document.querySelector("#content > .content-inner");
    if (!content || !inner) return false;
    return (
      !content.classList.contains("loading-route") &&
      Number.parseFloat(getComputedStyle(inner).opacity || "1") >= 0.99
    );
  });
  if (selector) {
    await page.waitForSelector(selector);
  }
  await page.waitForTimeout(250);
}

async function seedGuidanceDraft(page: import("@playwright/test").Page) {
  const result = await page.evaluate(async () => {
    const csrfResp = await fetch("/v1/auth/csrf", { credentials: "same-origin" });
    const csrf = await csrfResp.json();
    const token = csrf.token || csrf.csrf_token || "";
    const draftResp = await fetch("/v1/provider-guidance/claude/draft", {
      method: "PUT",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
      },
      body: JSON.stringify({
        actor_key: "ui:docs-capture",
        body: [
          "Prefer direct operational guidance over long rationale.",
          "Call out risks before implementation steps.",
          "Keep release checklists ordered by blast radius.",
        ].join("\n"),
        scope_kind: "system",
        scope_key: "",
      }),
    });
    return {
      ok: draftResp.ok,
      status: draftResp.status,
      text: await draftResp.text(),
    };
  });
  expect(result.ok, `${result.status}: ${result.text}`).toBeTruthy();
}

test.beforeAll(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  for (const bot of BOTS) {
    const agent = await enrollAgent(bot);
    seed.agents.push(agent);
  }

  seed.focusAgentId = seed.agents[0]!.id;

  for (let i = 0; i < seed.agents.length; i += 1) {
    const agent = seed.agents[i]!;
    await heartbeatAgent(
      agent,
      BOTS[i]!.state,
      `worker-${agent.slug}`,
      i === 0 ? "release-checklist" : `queue-${i + 1}`,
    );
  }

  const conversationSeeds = [
    { agentIndex: 0, title: "Release readiness review", ref: "release-review", focus: true, pending: false },
    { agentIndex: 0, title: "Release approval queue", ref: "release-approval", focus: false, pending: true },
    { agentIndex: 1, title: "Policy sign-off for launch", ref: "policy-launch", focus: false, pending: false },
    { agentIndex: 2, title: "Customer escalation summary", ref: "customer-escalation", focus: false, pending: true },
    { agentIndex: 3, title: "Platform maintenance window", ref: "platform-window", focus: false, pending: false },
    { agentIndex: 4, title: "Retrieval benchmark follow-up", ref: "retrieval-benchmark", focus: false, pending: false },
    { agentIndex: 5, title: "Audit evidence bundle", ref: "audit-evidence", focus: false, pending: false },
    { agentIndex: 1, title: "Release dry run checklist", ref: "release-dry-run", focus: false, pending: false },
    { agentIndex: 4, title: "Release rollback rehearsal", ref: "release-rollback", focus: false, pending: true },
    { agentIndex: 2, title: "Support playbook refresh", ref: "support-playbook", focus: false, pending: false },
  ];

  for (const item of conversationSeeds) {
    const agent = seed.agents[item.agentIndex]!;
    const conversationId = await createConversation(agent, item.title, item.ref);
    await publishEvents(agent, conversationId, item.focus, item.pending);
    seed.conversations.push({
      id: conversationId,
      title: item.title,
      agentId: agent.id,
    });
    if (item.focus) {
      seed.focusConversationId = conversationId;
      seed.focusConversationTitle = item.title;
    }
  }

  await createRoutedTask(
    seed.agents[0]!,
    seed.agents[1]!,
    seed.conversations[0]!.id,
    "docs-risk-review",
    "Review launch checklist and call out blockers",
    "Summarize blockers and confirm whether the deployment window is safe.",
    ["reviewer", "security"],
  );
  await createRoutedTask(
    seed.agents[0]!,
    seed.agents[3]!,
    seed.conversations[1]!.id,
    "docs-release-window",
    "Validate the maintenance window",
    "Check regional overlap, pager coverage, and rollback timing.",
    ["kubernetes", "devops"],
  );
  await createRoutedTask(
    seed.agents[4]!,
    seed.agents[5]!,
    seed.conversations[4]!.id,
    "docs-audit-pass",
    "Review control evidence bundle",
    "Confirm the evidence packet is ready for the operator archive.",
    ["policy", "reviewer"],
  );
  await createRoutedTask(
    seed.agents[0]!,
    seed.agents[2]!,
    seed.conversations[3]!.id,
    "docs-customer-escalation",
    "Prepare customer escalation summary",
    "Summarize timeline, impact, and the next operator-visible step.",
    ["support", "python"],
  );

  await reportTaskResult(seed.agents[1]!.token, "docs-risk-review", {
    status: "completed",
    transition_id: "docs-risk-review-complete",
    summary: "No blocking risks. One deployment note added to the runbook.",
    full_text: "No blocking risks. One deployment note added to the runbook.",
    prompt_tokens: 241,
    completion_tokens: 88,
    cost_usd: 0.0061,
    provider: "claude",
  });
  await updateTaskStatus(seed.agents[3]!.token, "docs-release-window", {
    status: "leased",
    transition_id: "docs-release-window-leased",
    summary: "Picked up for execution.",
    timeline_events: [],
  });
  await updateTaskStatus(seed.agents[3]!.token, "docs-release-window", {
    status: "running",
    transition_id: "docs-release-window-running",
    summary: "Validating regional overlap and pager coverage.",
    progress: 54,
    timeline_events: [],
  });
  await updateTaskStatus(seed.agents[5]!.token, "docs-audit-pass", {
    status: "leased",
    transition_id: "docs-audit-pass-leased",
    summary: "Picked up for evidence review.",
    timeline_events: [],
  });
  await reportTaskResult(seed.agents[5]!.token, "docs-audit-pass", {
    status: "failed",
    transition_id: "docs-audit-pass-failed",
    summary: "One evidence attachment is still missing from the package.",
    full_text: "One evidence attachment is still missing from the package.",
    provider: "codex",
  });
});

test("capture all registry UI surfaces", async ({ page }) => {
  await page.goto("/ui/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await page.screenshot({ path: path.join(OUT, "00-login.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "00-login.png"), [
    { selector: ".login-container", label: "Operator sign-in for the registry UI", color: "#2196f3", pad: 10 },
    { selector: "#login-password", label: "Password = REGISTRY_UI_TOKEN", color: "#ff9800", pad: 8 },
    { selector: "button[type='submit']", label: "Creates an operator session cookie", color: "#4caf50", pad: 8 },
  ]);

  await page.getByLabel("Password").fill(UI_TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/ui");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await waitForViewReady(page, ".dashboard-shell");

  await page.screenshot({ path: path.join(OUT, "01-dashboard.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "01-dashboard.png"), [
    { selector: "#sidebar", label: "Primary navigation", color: "#ff9800", pad: 6 },
    { selector: ".summary-rail", label: "Summary rail for open conversations, running work, follow-up, and agent health", color: "#2196f3", pad: 8 },
    { selector: '[data-key="needs-attention"]', label: "Needs-attention queue for approvals, failed work, and unhealthy agents", color: "#4caf50", pad: 8 },
    { selector: ".dashboard-work-grid", label: "Direct jump lists for conversations, tasks, and agents", color: "#9c27b0", pad: 8 },
  ]);

  await page.goto("/ui/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await waitForViewReady(page, ".approval-card");
  await page.screenshot({ path: path.join(OUT, "01b-approvals.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "01b-approvals.png"), [
    { selector: ".approval-card:nth-of-type(1)", label: "Pending request with clear decision actions", color: "#2196f3", pad: 8 },
    { selector: ".approval-actions", label: "Approve, reject, or open the full conversation", color: "#4caf50", pad: 8 },
  ]);

  await page.goto("/ui/agents");
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  await waitForViewReady(page, "#agent-list-content .list-row");
  await page.screenshot({ path: path.join(OUT, "02-agents.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "02-agents.png"), [
    { selector: ".route-controls", label: "Server-side search plus segmented connectivity filters", color: "#ff9800", pad: 6 },
    { selector: "#agent-list-content .list-row-shell:nth-child(1)", label: "Agent row with connectivity context", color: "#2196f3", pad: 6 },
    { selector: "#agent-list-content .list-row-action", label: "Direct Open action to reuse or start a conversation", color: "#4caf50", pad: 6 },
  ]);

  await page.goto(`/ui/agents/${seed.focusAgentId}`);
  await waitForViewReady(page, '.agent-detail-grid [data-key="overview"]');
  await page.screenshot({ path: path.join(OUT, "03-agent-detail.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "03-agent-detail.png"), [
    { selector: ".workspace-header", label: "Compact header with direct Open conversation action", color: "#ff9800", pad: 6 },
    { selector: '.agent-detail-grid [data-key="overview"]', label: "Registry identity, scope, version, and heartbeat", color: "#2196f3", pad: 8 },
    { selector: '.agent-detail-grid [data-key="workers"]', label: "Worker state published by runtime heartbeat", color: "#9c27b0", pad: 8 },
    { selector: '.agent-detail-grid [data-key="conversations"]', label: "Inline conversations for this agent", color: "#4caf50", pad: 8 },
  ]);

  await page.goto(`/ui/agents/${seed.focusAgentId}/conversations`);
  await waitForViewReady(page, '.agent-detail-grid [data-key="conversations"]');
  await page.screenshot({ path: path.join(OUT, "04-agent-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "04-agent-conversations.png"), [
    { selector: '.agent-detail-grid [data-key="conversations"]', label: "Compatibility route that lands on the same inline conversations workspace", color: "#2196f3", pad: 8 },
  ]);

  await page.goto("/ui/conversations");
  await waitForViewReady(page, ".quickstart-shell");
  await page.screenshot({ path: path.join(OUT, "05-conversations.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "05-conversations.png"), [
    { selector: ".quickstart-shell", label: "Connected-agent quick start plus overflow path to the full agent roster", color: "#4caf50", pad: 6 },
    { selector: ".route-controls", label: "Server-backed search and segmented status filter", color: "#ff9800", pad: 6 },
    { selector: ".list-container .list-row:nth-of-type(1)", label: "Conversation row → conversation workspace", color: "#2196f3", pad: 6 },
  ]);

  await page.locator(".search-input").first().fill("Release");
  await page.waitForTimeout(700);
  await waitForViewReady(page, ".list-container .list-row");
  await page.screenshot({ path: path.join(OUT, "05b-conversations-filtered.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "05b-conversations-filtered.png"), [
    { selector: ".search-input", label: "Debounced server-side conversation search", color: "#ff9800", pad: 6 },
    { selector: ".list-container .list-row:nth-of-type(1)", label: "Filtered results from the registry conversation index", color: "#2196f3", pad: 6 },
  ]);

  await page.goto(`/ui/conversations/${seed.focusConversationId}`);
  await waitForViewReady(page, ".conversation-shell");
  await page.screenshot({ path: path.join(OUT, "06-conversation-detail.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "06-conversation-detail.png"), [
    { selector: ".conversation-meta", label: "Compact operator-facing header with With / Assigned to / Started in, status, activity shortcut, and Copy ref action", color: "#ff9800", pad: 6 },
    { selector: ".conversation-toolbar", label: "Conversation, Tasks, and Full activity views", color: "#4caf50", pad: 6 },
    { selector: ".chat-timeline", label: "Conversation view with messages, approvals, delegation milestones, and task status updates", color: "#2196f3", pad: 8 },
    { selector: ".compose-box", label: "Shared composer for normal replies and leading-@ direct routing", color: "#9c27b0", pad: 6 },
  ]);

  await page.goto("/ui/tasks");
  await waitForViewReady(page, ".task-item");
  await page.locator(".task-item-row").first().click();
  await page.screenshot({ path: path.join(OUT, "07-tasks.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "07-tasks.png"), [
    { selector: ".summary-rail", label: "Summary rail for pending, running, and follow-up work", color: "#ff9800", pad: 6 },
    { selector: ".segmented-control", label: "Segmented task status filter", color: "#4caf50", pad: 6 },
    { selector: ".task-item:nth-of-type(1)", label: "Expandable task row with origin, target, and parent conversation actions", color: "#2196f3", pad: 8 },
  ]);

  await page.goto("/ui/capabilities");
  await waitForViewReady(page, "#cap-list .settings-row, #cap-list .empty-state");
  await page.screenshot({ path: path.join(OUT, "08-capabilities.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "08-capabilities.png"), [
    { selector: "#cap-list", label: "Global capability overrides declared by active agents", color: "#2196f3", pad: 8 },
  ]);

  await page.goto("/ui/skills");
  await waitForViewReady(page, ".card, .empty-state");
  await page.screenshot({ path: path.join(OUT, "09-skills.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "09-skills.png"), [
    { selector: ".search-input", label: "Client-side search across the skill catalog", color: "#ff9800", pad: 6 },
    { selector: ".card:nth-of-type(1)", label: "Catalog row with install or uninstall action", color: "#2196f3", pad: 6 },
  ]);

  await page.goto("/ui/usage");
  await waitForViewReady(page, "#usage-table table, #usage-table .empty-state");
  await page.screenshot({ path: path.join(OUT, "10-usage.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "10-usage.png"), [
    { selector: ".segmented-control", label: "Date-range shortcuts map to /v1/usage", color: "#ff9800", pad: 6 },
    { selector: ".summary-rail", label: "Prompt, completion, and cost summary", color: "#2196f3", pad: 6 },
    { selector: "#usage-table", label: "Per-conversation usage rollups, including delegated child usage when reported", color: "#4caf50", pad: 6 },
  ]);

  await seedGuidanceDraft(page);
  await page.goto("/ui/guidance");
  await waitForViewReady(page, ".guidance-textarea");
  await page.screenshot({ path: path.join(OUT, "11-guidance.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "11-guidance.png"), [
    { selector: ".filter-bar", label: "Provider selector", color: "#ff9800", pad: 6 },
    { selector: ".card:first-of-type", label: "Lifecycle status for the selected provider guidance", color: "#2196f3", pad: 8 },
    { selector: ".guidance-textarea", label: "Draft system prompt body", color: "#4caf50", pad: 8 },
    { selector: ".card-actions", label: "Preview and lifecycle actions", color: "#9c27b0", pad: 8 },
  ]);

  await page.goto(`/ui/agents/${seed.focusAgentId}`);
  await waitForViewReady(page, ".agent-detail-grid");
  await page.screenshot({ path: path.join(OUT, "12-agent-detail-deep-link.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "12-agent-detail-deep-link.png"), [
    { selector: "#content", label: "Direct deep link to /ui/agents/{agent_id}", color: "#4caf50", pad: 6 },
  ]);

  await page.goto(`/ui/conversations/${seed.focusConversationId}`);
  await waitForViewReady(page, ".conversation-page");
  await page.screenshot({ path: path.join(OUT, "13-conversation-deep-link.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "13-conversation-deep-link.png"), [
    { selector: ".conversation-page", label: "Direct deep link to /ui/conversations/{conversation_id}", color: "#4caf50", pad: 6 },
  ]);
});

test("capture mobile registry docs views", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ui/login");
  await page.getByLabel("Password").fill(UI_TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/ui");
  await waitForViewReady(page, ".dashboard-shell");

  await page.screenshot({ path: path.join(OUT, "14-mobile-dashboard.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "14-mobile-dashboard.png"), [
    { selector: "#hamburger", label: "Sidebar drawer trigger on mobile", color: "#ff9800", pad: 6 },
    { selector: ".summary-rail", label: "Summary cards collapse into a single vertical rail", color: "#2196f3", pad: 8 },
    { selector: ".dashboard-work-grid", label: "Attention sections stack into one reading column", color: "#4caf50", pad: 8 },
  ]);

  await page.goto("/ui/approvals");
  await waitForViewReady(page, ".approval-card");
  await page.screenshot({ path: path.join(OUT, "15-mobile-approvals.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "15-mobile-approvals.png"), [
    { selector: ".approval-card:nth-of-type(1)", label: "Approval cards remain action-first on small screens", color: "#2196f3", pad: 8 },
    { selector: ".approval-actions", label: "Open, approve, and reject stay reachable without extra drill-in", color: "#4caf50", pad: 8 },
  ]);

  await page.goto(`/ui/conversations/${seed.focusConversationId}`);
  await waitForViewReady(page, ".conversation-shell");
  await page.screenshot({ path: path.join(OUT, "16-mobile-conversation.png"), fullPage: true });
  await writeOverlayMeta(page, path.join(OUT, "16-mobile-conversation.png"), [
    { selector: ".conversation-meta", label: "Header metadata stacks into one readable mobile block with action shortcuts preserved", color: "#ff9800", pad: 6 },
    { selector: ".conversation-toolbar", label: "Conversation, Tasks, and Full activity remain in one segmented control", color: "#4caf50", pad: 6 },
    { selector: ".compose-box", label: "Composer stays inside the conversation workspace", color: "#2196f3", pad: 8 },
  ]);
});
