"""Regenerate registry UI screenshots from current UI code in one pass."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = REPO_ROOT / "docs" / "assets" / "registry"
README_SCREENSHOT = REPO_ROOT / "registry-ui-screenshot.png"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.channels.registry import ui


def _playwright_cli() -> Path:
    cache_root = Path.home() / ".npm" / "_npx"
    matches = sorted(cache_root.glob("*/node_modules/playwright/cli.js"))
    if not matches:
        raise FileNotFoundError("Could not locate cached Playwright CLI under ~/.npm/_npx")
    return matches[-1]


def _now(hour: int, minute: int, second: int) -> str:
    return f"2026-03-21T{hour:02d}:{minute:02d}:{second:02d}+00:00"


def _runtime_health_detail() -> dict:
    return {
        "report": {
            "generated_at": _now(14, 0, 10),
            "summary": {
                "status": "degraded",
                "healthy_worker_count": 1,
                "stale_worker_count": 1,
                "fresh_queued_count": 2,
                "claimed_count": 1,
                "pending_recovery_count": 1,
                "recovery_queued_count": 0,
                "oldest_claim_age_seconds": 42,
                "warning_count": 1,
                "error_count": 0,
            },
            "snapshot": {
                "queue": {
                    "fresh_queued_count": 2,
                    "claimed_count": 1,
                    "pending_recovery_count": 1,
                    "recovery_queued_count": 0,
                    "oldest_claimed_at": _now(14, 0, 0),
                },
                "workers": [
                    {
                        "worker_id": "worker-a",
                        "process_role": "worker",
                        "started_at": _now(13, 59, 0),
                        "last_seen_at": _now(14, 0, 10),
                        "current_item_id": "item-1",
                        "current_conversation_key": "conv-spec-review",
                        "current_kind": "message",
                        "items_processed": 5,
                    },
                    {
                        "worker_id": "worker-b",
                        "process_role": "worker",
                        "started_at": _now(13, 58, 0),
                        "last_seen_at": _now(13, 59, 10),
                        "items_processed": 1,
                    },
                ],
                "healthy_worker_count": 1,
                "stale_worker_count": 1,
            },
            "diagnostics": [
                {
                    "level": "warning",
                    "code": "shared.pending_recovery_backlog",
                    "message": "Shared Runtime has 1 item awaiting replay/discard.",
                }
            ],
        },
        "workers": [
            {
                "worker_id": "worker-a",
                "process_role": "worker",
                "last_seen_at": _now(14, 0, 10),
                "current_kind": "message",
                "current_item_id": "item-1",
                "items_processed": 5,
            },
            {
                "worker_id": "worker-b",
                "process_role": "worker",
                "last_seen_at": _now(13, 59, 10),
                "current_kind": "",
                "current_item_id": "",
                "items_processed": 1,
            },
        ],
        "last_mirrored_at": _now(14, 0, 10),
    }


def _snapshot_data() -> dict:
    product_agent_id = "agent-product"
    reviewer_agent_id = "agent-reviewer"
    ops_agent_id = "agent-ops"
    conversation_id = "conv-spec-review"

    bots = [
        {
            "agent_id": product_agent_id,
            "display_name": "Product Bot",
            "role": "product lead",
            "description": "Drives specs, coordination, and rollout plans.",
            "capabilities": ["planning", "python", "routing"],
            "tags": ["product", "primary"],
            "provider": "codex",
            "version": "2026.03",
            "connectivity_state": "connected",
            "last_heartbeat_at": _now(14, 0, 10),
            "runtime_health_generated_at": _now(14, 0, 10),
            "runtime_health_summary": _runtime_health_detail()["report"]["summary"],
        },
        {
            "agent_id": reviewer_agent_id,
            "display_name": "Reviewer Bot",
            "role": "reviewer",
            "description": "Reviews implementation risk and missing tests.",
            "capabilities": ["reviewer", "tests"],
            "tags": ["qa"],
            "provider": "claude",
            "version": "2026.03",
            "connectivity_state": "connected",
            "last_heartbeat_at": _now(14, 0, 12),
            "runtime_health_generated_at": "",
            "runtime_health_summary": {},
        },
        {
            "agent_id": ops_agent_id,
            "display_name": "Ops Bot",
            "role": "operations",
            "description": "Handles registry maintenance and provider rollouts.",
            "capabilities": ["operations", "approval"],
            "tags": ["ops"],
            "provider": "codex",
            "version": "2026.03",
            "connectivity_state": "degraded",
            "last_heartbeat_at": _now(14, 0, 15),
            "runtime_health_generated_at": "",
            "runtime_health_summary": {},
        },
    ]

    conversations = [
        {
            "conversation_id": conversation_id,
            "title": "Spec review for onboarding flow",
            "target_agent_id": product_agent_id,
            "target_display_name": "Product Bot",
            "status": "open",
            "created_at": _now(14, 1, 0),
            "updated_at": _now(14, 1, 40),
            "timeline_event_count": 4,
        }
    ]

    conversation_detail = dict(conversations[0])

    timeline = [
        {
            "event_id": "evt-started",
            "conversation_id": conversation_id,
            "kind": "started",
            "title": "Conversation started",
            "body": "Registry UI opened a new design-review session.",
            "created_at": _now(14, 1, 0),
        },
        {
            "event_id": "evt-progress",
            "conversation_id": conversation_id,
            "kind": "progress",
            "title": "Gathering edge cases",
            "body": "Comparing enrollment, reconnect, and scope-switch paths.",
            "created_at": _now(14, 1, 20),
        },
        {
            "event_id": "evt-usage",
            "conversation_id": conversation_id,
            "kind": "usage",
            "title": "Token usage",
            "body": "",
            "created_at": _now(14, 1, 30),
            "metadata": {
                "prompt_tokens": 280,
                "completion_tokens": 91,
                "cost_usd": 0.0348,
                "provider": "codex",
            },
        },
        {
            "event_id": "evt-delegation",
            "conversation_id": conversation_id,
            "kind": "delegation_proposed",
            "title": "Delegate API failure review",
            "body": "Ask Reviewer Bot to inspect approval and failure handling.",
            "created_at": _now(14, 1, 40),
        },
    ]

    tasks = [
        {
            "routed_task_id": "task-regression-review",
            "title": "Regression review",
            "origin_agent_id": product_agent_id,
            "origin_display_name": "Product Bot",
            "target_agent_id": reviewer_agent_id,
            "target_display_name": "Reviewer Bot",
            "parent_conversation_id": conversation_id,
            "status": "running",
            "summary": "Reviewing onboarding edge cases and fallback flows.",
            "updated_at": _now(14, 2, 10),
        },
        {
            "routed_task_id": "task-provider-rollout",
            "title": "Provider rollout check",
            "origin_agent_id": product_agent_id,
            "origin_display_name": "Product Bot",
            "target_agent_id": ops_agent_id,
            "target_display_name": "Ops Bot",
            "parent_conversation_id": conversation_id,
            "status": "partialfailed",
            "summary": "Waiting on provider policy confirmation.",
            "updated_at": _now(14, 2, 20),
        },
    ]

    runtime_skills = {
        "skills": [
            {
                "name": "code-review",
                "display_name": "Code Review",
                "description": "Review code with a focus on regressions and missing tests.",
                "source_kind": "builtin",
                "providers": ["claude", "codex"],
                "lifecycle_status": "builtin",
                "can_activate": True,
                "can_update": False,
                "can_uninstall": False,
            },
            {
                "name": "release-notes",
                "display_name": "Release Notes",
                "description": "Registry-authored release notes helper.",
                "source_kind": "custom",
                "providers": ["claude"],
                "lifecycle_status": "published",
                "can_activate": True,
                "can_update": True,
                "can_uninstall": True,
            },
        ],
        "detail": {
            "name": "release-notes",
            "display_name": "Release Notes",
            "description": "Registry-authored release notes helper.",
            "body": "Summarize release notes with impact, rollout risk, and verification notes.",
            "source_kind": "custom",
            "has_custom_override": True,
            "providers": ["claude"],
            "requirement_keys": [],
            "can_activate": True,
            "can_update": True,
            "can_uninstall": True,
            "lifecycle_status": "published",
        },
        "lifecycle": {
            "name": "release-notes",
            "display_name": "Release Notes",
            "description": "Registry-authored release notes helper.",
            "visibility": "private",
            "body": "Summarize release notes with impact, rollout risk, and verification notes.",
            "lifecycle_status": "published",
            "active_revision_id": "skill-release-notes@3",
            "published_revision_id": "skill-release-notes@3",
            "runtime_available": True,
            "revisions": [
                {
                    "revision_id": "skill-release-notes@1",
                    "version_label": "draft",
                    "status": "draft",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 55, 0),
                },
                {
                    "revision_id": "skill-release-notes@2",
                    "version_label": "review",
                    "status": "approved",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 57, 0),
                },
                {
                    "revision_id": "skill-release-notes@3",
                    "version_label": "published",
                    "status": "published",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 59, 0),
                },
            ],
            "approvals": [
                {
                    "action": "submitted",
                    "actor": "reg:ui",
                    "note": "registry-docs:submit",
                    "created_at": _now(13, 56, 0),
                },
                {
                    "action": "approved",
                    "actor": "reg:ui",
                    "note": "registry-docs:approve",
                    "created_at": _now(13, 58, 0),
                },
                {
                    "action": "published",
                    "actor": "reg:ui",
                    "note": "registry-docs:publish",
                    "created_at": _now(14, 0, 0),
                },
            ],
        },
        "preview": {
            "provider": "claude",
            "effective_guidance": "Prefer concise registry updates and highlight rollout risk.",
            "system_prompt": "Active runtime skills: Release Notes.\nSummarize release notes with impact, rollout risk, and verification notes.",
            "capability_summary": "release notes, rollout risk, verification",
            "provider_config": {"provider": "claude"},
            "prompt_weight": 188,
        },
    }

    provider_guidance = {
        "detail": {
            "provider": "claude",
            "scope_kind": "system",
            "scope_key": "",
            "body": "# Claude Registry Guidance\n\nPrefer concise registry updates.\n\n- Call out blocked delegated tasks.\n- Mention active runtime skills.",
            "lifecycle_status": "published",
            "active_revision_id": "guidance-claude@3",
            "published_revision_id": "guidance-claude@3",
            "runtime_available": True,
            "revisions": [
                {
                    "revision_id": "guidance-claude@1",
                    "version_label": "draft",
                    "status": "draft",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 54, 0),
                },
                {
                    "revision_id": "guidance-claude@2",
                    "version_label": "review",
                    "status": "approved",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 56, 30),
                },
                {
                    "revision_id": "guidance-claude@3",
                    "version_label": "published",
                    "status": "published",
                    "created_by": "reg:ui",
                    "created_at": _now(13, 59, 30),
                },
            ],
            "approvals": [
                {
                    "action": "submitted",
                    "actor": "reg:ui",
                    "note": "registry-docs:submit",
                    "created_at": _now(13, 55, 0),
                },
                {
                    "action": "approved",
                    "actor": "reg:ui",
                    "note": "registry-docs:approve",
                    "created_at": _now(13, 58, 0),
                },
                {
                    "action": "published",
                    "actor": "reg:ui",
                    "note": "registry-docs:publish",
                    "created_at": _now(14, 0, 0),
                },
            ],
        },
        "preview": {
            "provider": "claude",
            "effective_guidance": "Prefer concise registry updates.\n\n- Call out blocked delegated tasks.\n- Mention active runtime skills.",
            "system_prompt": "Provider guidance active for claude.",
            "capability_summary": "concise updates, delegation awareness, runtime skills",
            "provider_config": {"provider": "claude"},
            "prompt_weight": 144,
        },
    }

    capabilities = [
        {
            "capability_name": "approval",
            "declared_by_agents": ["Ops Bot"],
            "enabled": True,
        },
        {
            "capability_name": "planning",
            "declared_by_agents": ["Product Bot"],
            "enabled": True,
        },
        {
            "capability_name": "reviewer",
            "declared_by_agents": ["Reviewer Bot"],
            "enabled": True,
        },
        {
            "capability_name": "routing",
            "declared_by_agents": ["Product Bot"],
            "enabled": False,
        },
        {
            "capability_name": "tests",
            "declared_by_agents": ["Reviewer Bot"],
            "enabled": True,
        },
    ]

    return {
        "ids": {
            "product_agent_id": product_agent_id,
            "conversation_id": conversation_id,
            "running_task_id": "task-regression-review",
        },
        "bootstrap": {
            "bots": bots,
            "conversations": conversations,
            "tasks": tasks,
        },
        "usage": {
            "daily_total": {
                "prompt_tokens": 280,
                "completion_tokens": 91,
                "cost_usd": 0.0348,
            },
            "by_conversation": [
                {
                    "conversation_id": conversation_id,
                    "prompt_tokens": 280,
                    "completion_tokens": 91,
                    "cost_usd": 0.0348,
                }
            ],
        },
        "bot_health": {
            product_agent_id: _runtime_health_detail(),
        },
        "conversation_detail": conversation_detail,
        "conversation_timeline": timeline,
        "conversation_skill_state": {
            "conversation_key": conversation_id,
            "active_skills": ["code-review"],
            "active_skill_details": [
                {
                    "name": "code-review",
                    "display_name": "Code Review",
                }
            ],
        },
        "runtime_skills": runtime_skills,
        "provider_guidance": provider_guidance,
        "capabilities": capabilities,
    }


def _snapshot_prelude(snapshot_name: str, data: dict) -> str:
    payload = json.dumps(data)
    snapshot = json.dumps(snapshot_name)
    return f"""
const __REGISTRY_DOC_DATA__ = {payload};
const __REGISTRY_DOC_SNAPSHOT__ = {snapshot};
window.setInterval = () => 0;
window.clearInterval = () => {{}};
window.fetch = async function(input, options = {{}}) {{
  const url = typeof input === "string" ? input : String(input?.url || "");
  const method = String(options.method || "GET").toUpperCase();
  const bodyText = typeof options.body === "string" ? options.body : "";
  let body = {{}};
  if (bodyText) {{
    try {{
      body = JSON.parse(bodyText);
    }} catch (_error) {{
      body = {{}};
    }}
  }}
  const jsonResponse = payload => new Response(JSON.stringify(payload), {{
    status: 200,
    headers: {{ "Content-Type": "application/json" }},
  }});
  if (url.endsWith("/v1/ui/bootstrap")) return jsonResponse(__REGISTRY_DOC_DATA__.bootstrap);
  if (url.endsWith("/v1/ui/usage")) return jsonResponse(__REGISTRY_DOC_DATA__.usage);
  if (url.endsWith("/v1/ui/capabilities")) return jsonResponse(__REGISTRY_DOC_DATA__.capabilities);
  if (url.endsWith("/v1/catalog/skills")) return jsonResponse({{ skills: __REGISTRY_DOC_DATA__.runtime_skills.skills }});
  if (url.endsWith("/v1/catalog/skills/release-notes")) return jsonResponse(__REGISTRY_DOC_DATA__.runtime_skills.detail);
  if (url.endsWith("/v1/catalog/skills/release-notes/lifecycle")) return jsonResponse(__REGISTRY_DOC_DATA__.runtime_skills.lifecycle);
  if (url.endsWith("/v1/provider-guidance/claude")) return jsonResponse(__REGISTRY_DOC_DATA__.provider_guidance.detail);
  if (url.endsWith("/v1/provider-guidance/claude/preview")) {{
    if (Array.isArray(body.active_skills) && body.active_skills.includes("release-notes")) {{
      return jsonResponse(__REGISTRY_DOC_DATA__.runtime_skills.preview);
    }}
    return jsonResponse(__REGISTRY_DOC_DATA__.provider_guidance.preview);
  }}
  const botHealthMatch = url.match(/\\/v1\\/ui\\/bots\\/([^/]+)\\/health$/);
  if (botHealthMatch) return jsonResponse(__REGISTRY_DOC_DATA__.bot_health[botHealthMatch[1]] || {{}});
  const conversationMatch = url.match(/\\/v1\\/ui\\/conversations\\/([^/]+)$/);
  if (conversationMatch) return jsonResponse(__REGISTRY_DOC_DATA__.conversation_detail);
  const timelineMatch = url.match(/\\/v1\\/ui\\/conversations\\/([^/]+)\\/timeline$/);
  if (timelineMatch) return jsonResponse({{ events: __REGISTRY_DOC_DATA__.conversation_timeline }});
  const skillStateMatch = url.match(/\\/v1\\/conversations\\/([^/]+)\\/skills$/);
  if (skillStateMatch) return jsonResponse(__REGISTRY_DOC_DATA__.conversation_skill_state);
  throw new Error(`Unexpected fetch: ${{method}} ${{url}}`);
}};

window.addEventListener("load", () => {{
  const hideStatus = () => {{
    const refresh = document.getElementById("refresh-indicator");
    const updated = document.getElementById("last-updated");
    const status = document.getElementById("ui-status");
    if (refresh) refresh.style.visibility = "hidden";
    if (updated) updated.style.visibility = "hidden";
    if (status) status.style.visibility = "hidden";
  }};
  const ready = async predicate => {{
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {{
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 30));
    }}
    throw new Error(`Timed out waiting for snapshot ${{__REGISTRY_DOC_SNAPSHOT__}}`);
  }};
  const markReady = () => {{
    hideStatus();
    document.body.setAttribute("data-snapshot-ready", __REGISTRY_DOC_SNAPSHOT__);
  }};
  (async () => {{
    await ready(() => {{
      const bots = document.getElementById("bots");
      const conversations = document.getElementById("conversations");
      const tasks = document.getElementById("tasks");
      const skills = document.getElementById("runtime-skills");
      const capabilities = document.getElementById("capabilities");
      const guidance = document.getElementById("provider-guidance-detail");
      return Boolean(
        bots &&
        conversations &&
        tasks &&
        skills &&
        capabilities &&
        guidance &&
        !bots.textContent.includes("Loading") &&
        !conversations.textContent.includes("Loading") &&
        !tasks.textContent.includes("Loading") &&
        !skills.textContent.includes("Loading") &&
        !capabilities.textContent.includes("Loading") &&
        !guidance.classList.contains("hidden")
      );
    }});
    if (__REGISTRY_DOC_SNAPSHOT__ === "dashboard") {{
      window.scrollTo(0, 0);
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "bot-detail") {{
      await window.loadBotDetail(__REGISTRY_DOC_DATA__.ids.product_agent_id);
      await ready(() => document.getElementById("detail-panel-title")?.textContent === "Bot Detail");
      window.scrollTo(0, 0);
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "task-detail") {{
      const task = (__REGISTRY_DOC_DATA__.bootstrap.tasks || []).find(item => item.routed_task_id === __REGISTRY_DOC_DATA__.ids.running_task_id);
      window.renderTaskDetail(task);
      await ready(() => document.getElementById("detail-panel-title")?.textContent === "Routed Task Detail");
      window.scrollTo(0, 0);
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "conversation-detail") {{
      await window.loadConversationDetail(__REGISTRY_DOC_DATA__.ids.conversation_id);
      await ready(() => document.getElementById("detail-panel-title")?.textContent === "Conversation Detail");
      window.scrollTo(0, 0);
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "runtime-skills") {{
      await window.loadRuntimeSkillDetail("release-notes");
      await window.previewRuntimeSkill("claude", "release-notes");
      await ready(() => document.getElementById("runtime-skill-detail")?.textContent.includes("Prompt Preview"));
      document.querySelectorAll("section.skills-panel")[0]?.scrollIntoView({{ block: "start" }});
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "provider-guidance") {{
      document.querySelectorAll("section.skills-panel")[1]?.scrollIntoView({{ block: "start" }});
      markReady();
      return;
    }}
    if (__REGISTRY_DOC_SNAPSHOT__ === "capabilities") {{
      document.querySelectorAll("section.skills-panel")[2]?.scrollIntoView({{ block: "start" }});
      markReady();
      return;
    }}
    throw new Error(`Unknown snapshot: ${{__REGISTRY_DOC_SNAPSHOT__}}`);
  }})().catch(error => {{
    const banner = document.createElement("div");
    banner.id = "snapshot-error";
    banner.textContent = error.message || String(error);
    banner.style.position = "fixed";
    banner.style.top = "0";
    banner.style.left = "0";
    banner.style.right = "0";
    banner.style.padding = "8px 12px";
    banner.style.background = "#ef4444";
    banner.style.color = "#fff";
    banner.style.zIndex = "9999";
    document.body.appendChild(banner);
  }});
}});
"""


def _shell_snapshot(snapshot_name: str, data: dict) -> str:
    html = ui.render_shell_html(
        title_text="Agent Registry",
        heading_text="Agent Registry",
        logout_link='<a href="/ui/logout" class="nav-link">Logout</a>',
        csrf_token="snapshot-csrf",
    )
    html = html.replace(
        "</head>",
        """
    <style>
      #refresh-indicator,
      #last-updated,
      #ui-status {
        visibility: hidden !important;
      }
    </style>
  </head>""",
    )
    injection = f"<script>{_snapshot_prelude(snapshot_name, data)}</script>\n    <script>"
    return html.replace("<script>", injection, 1)


def _write_snapshot_pages(temp_dir: Path, data: dict) -> dict[str, Path]:
    pages = {
        "login": temp_dir / "login.html",
        "dashboard": temp_dir / "dashboard.html",
        "bot-detail": temp_dir / "bot-detail.html",
        "task-detail": temp_dir / "task-detail.html",
        "conversation-detail": temp_dir / "conversation-detail.html",
        "runtime-skills": temp_dir / "runtime-skills.html",
        "provider-guidance": temp_dir / "provider-guidance.html",
        "capabilities": temp_dir / "capabilities.html",
    }
    pages["login"].write_text(ui.render_login_html("Agent Registry"), encoding="utf-8")
    for name, path in pages.items():
        if name == "login":
            continue
        path.write_text(_shell_snapshot(name, data), encoding="utf-8")
    return pages


def _screenshot(page_path: Path, output_path: Path, *, selector: str, viewport: str = "1600,1240", full_page: bool = False) -> None:
    command = [
        "node",
        str(_playwright_cli()),
        "screenshot",
        "--browser",
        "chromium",
        "--color-scheme",
        "dark",
        "--lang",
        "en-US",
        "--timezone",
        "UTC",
        "--viewport-size",
        viewport,
        "--wait-for-selector",
        selector,
        "--wait-for-timeout",
        "250",
    ]
    if full_page:
        command.append("--full-page")
    command.extend([page_path.as_uri(), str(output_path)])
    subprocess.run(command, check=True, cwd=REPO_ROOT)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = _snapshot_data()
    with tempfile.TemporaryDirectory(prefix="registry-doc-assets-") as tmp_dir:
        temp_dir = Path(tmp_dir)
        pages = _write_snapshot_pages(temp_dir, data)

        _screenshot(
            pages["login"],
            ASSET_DIR / "03-registry-login.png",
            selector="form.card",
            viewport="1280,980",
        )
        _screenshot(
            pages["dashboard"],
            ASSET_DIR / "05-registry-dashboard.png",
            selector='body[data-snapshot-ready="dashboard"]',
            viewport="1600,1240",
        )
        shutil.copyfile(ASSET_DIR / "05-registry-dashboard.png", README_SCREENSHOT)
        _screenshot(
            pages["dashboard"],
            ASSET_DIR / "00-full-dashboard.png",
            selector='body[data-snapshot-ready="dashboard"]',
            viewport="1600,1240",
            full_page=True,
        )
        _screenshot(
            pages["bot-detail"],
            ASSET_DIR / "10-agent-detail.png",
            selector='body[data-snapshot-ready="bot-detail"]',
            viewport="1600,1240",
        )
        _screenshot(
            pages["task-detail"],
            ASSET_DIR / "12-routed-task-detail.png",
            selector='body[data-snapshot-ready="task-detail"]',
            viewport="1600,1240",
        )
        _screenshot(
            pages["conversation-detail"],
            ASSET_DIR / "13-conversation-detail.png",
            selector='body[data-snapshot-ready="conversation-detail"]',
            viewport="1600,1500",
        )
        _screenshot(
            pages["runtime-skills"],
            ASSET_DIR / "runtime-skills-tab.png",
            selector='body[data-snapshot-ready="runtime-skills"]',
            viewport="1600,1200",
        )
        _screenshot(
            pages["provider-guidance"],
            ASSET_DIR / "guidance-tab.png",
            selector='body[data-snapshot-ready="provider-guidance"]',
            viewport="1600,1200",
        )
        _screenshot(
            pages["capabilities"],
            ASSET_DIR / "capabilities-tab.png",
            selector='body[data-snapshot-ready="capabilities"]',
            viewport="1600,1000",
        )


if __name__ == "__main__":
    main()
