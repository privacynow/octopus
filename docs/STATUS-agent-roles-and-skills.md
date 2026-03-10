# Agent Roles & Skills — Implementation Status

Current as of 2026-03-10. Tracks progress against [PLAN-agent-roles-and-skills.md](PLAN-agent-roles-and-skills.md).

---

## Phase Completion Summary

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 0 | Codex delivery spike | Complete |
| Phase 1 | Instruction-only skills | Complete |
| Phase 2 | Credential-aware skills | Complete |
| Phase 3 | Provider-specific skill config | Complete |
| Phase 4 | Custom skills and ecosystem | Complete |
| Phase 5 | Skill store | Complete |

All planned implementation work through Phase 5 is done. The system is production-deployed and tested.

---

## Test Suite

Canonical full-suite runner: `./scripts/test_all.sh`

Current suite: 1,226 passing checks across 17 entrypoints.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_approvals.py` | 11 | Preflight prompt building, denial formatting. |
| `test_claude_provider.py` | 16 | Claude CLI command construction from `RunContext`. |
| `test_codex_provider.py` | 55 | Codex CLI command construction, thread invalidation, progress parsing, and modern JSON event handling. |
| `test_config.py` | 16 | Config loading, validation, `.env` parsing, and `BOT_SKILLS` validation. |
| `test_formatting.py` | 296 | Markdown-to-Telegram HTML conversion, balanced HTML splitting, table rendering, and directive extraction. |
| `test_handlers.py` | 78 | Core handler integration: happy-path routing, role/session behavior, resilience, `/help`, `/start`, and generic command flows. |
| `test_handlers_approval.py` | 53 | Approval and pending-request flows: preflight, approve/retry/skip, stale pending TTL, `/approval`, and `/cancel` for pending requests. |
| `test_handlers_codex.py` | 33 | Codex-specific handler behavior: thread invalidation, boot ID handling, retry semantics, and script staging. |
| `test_handlers_credentials.py` | 155 | Credential and setup flows: capture, validation, isolation, clear/cancel, group-setup protection, and credentialed-skill smokes. |
| `test_handlers_output.py` | 17 | Output presentation helpers: `/compact`, `/raw`, table rendering, and compact-mode summarization flows. |
| `test_handlers_store.py` | 26 | Store handler flows: install/update/uninstall, local-modification detection, prompt-size warnings, and store lifecycle smoke tests. |
| `test_high_risk.py` | 78 | Cross-cutting invariants from plan section 8.5: requester identity through approval, context hash staleness, Codex thread invalidation, credential injection, system prompt injection for both providers. |
| `test_skills.py` | 201 | Skill engine unit tests: catalog discovery, instruction loading, prompt composition, credential encryption, provider YAML parsing, context hashing, config digest, custom skill override. |
| `test_storage.py` | 26 | Session CRUD, upload path management, directory creation, session sweep. |
| `test_store.py` | 115 | Store module: discovery, search, install/uninstall, update checking, SHA-256 provenance, locally_modified persistence, session sweep, admin gate, prompt-size warning. |
| `test_summarize.py` | 15 | Raw-response ring buffer and `/raw` support primitives. |
| `tests/test_setup.sh` | 35 | Installer/setup wizard flows and config generation. |

### Handler Integration Layout

The highest-signal coverage remains in the handler integration suites. These exercise the full wiring between components: a Telegram update arrives, flows through session loading, credential checking, context building, and provider dispatch, then assertions verify both the provider call arguments and persisted session state.

- `test_handlers.py` now holds only the core non-domain-specific handler flows.
- `test_handlers_approval.py` isolates approval-specific state transitions and callback flows.
- `test_handlers_codex.py` isolates Codex-specific session and script behavior.
- `test_handlers_credentials.py` isolates the credential/setup state machine and group-setup protections.
- `test_handlers_output.py` isolates output rendering and compact/raw response behavior.
- `test_handlers_store.py` isolates store mutations and store-backed lifecycle flows.
- The split reduces the maintenance burden of a single monolithic handler file while preserving the same integration depth.

---

## Production Code

### File inventory

| File | Lines | Purpose |
|------|------:|---------|
| `app/main.py` | 77 | Entry point: config loading, provider selection, bot startup |
| `app/config.py` | 262 | Configuration loading, validation, .env parsing, BOT_SKILLS validation, BOT_ADMIN_USERS |
| `app/telegram_handlers.py` | 1,372 | All Telegram handlers: commands, message routing, approval/retry/credential flows, group chat setup safety, store commands |
| `app/skills.py` | 732 | Skill catalog, instruction loading, credential storage, context building, script staging, prompt-size checking |
| `app/storage.py` | 154 | Session CRUD, upload path management, session sweep |
| `app/store.py` | 396 | Skill store: discovery, search, install/uninstall, update checking, SHA-256 provenance |
| `app/approvals.py` | 48 | Preflight prompt building, denial formatting |
| `app/formatting.py` | 162 | Markdown-to-Telegram HTML, text splitting, SEND_FILE directives |
| `app/session_state.py` | ~120 | Typed session models: SessionState, PendingApproval, PendingRetry, AwaitingSkillSetup, ProjectBinding. Serialization via `dataclasses.asdict()`. |
| `app/execution_context.py` | ~100 | Authoritative resolved execution context: `ResolvedExecutionContext`, `resolve_execution_context()`. Single source of context hashing. |
| `app/request_flow.py` | ~210 | Pure business logic: credential satisfaction, pending validation, denial dir extraction, setup state management. No Telegram imports. |
| `app/providers/base.py` | ~70 | Provider protocol, RunResult, RunContext, PreflightContext. |
| `app/providers/claude.py` | 335 | Claude CLI provider (stream-json, session-id sessions, MCP config) |
| `app/providers/codex.py` | 309 | Codex CLI provider (exec --json, thread-id sessions, context hash invalidation) |

### Skill catalog

10 built-in skills in `skills/catalog/`:

| Skill | Type | Provider config | Credentials |
|-------|------|-----------------|-------------|
| `architecture` | Instruction-only | — | — |
| `code-review` | Instruction-only | — | — |
| `debugging` | Instruction-only | — | — |
| `devops` | Instruction-only | — | — |
| `documentation` | Instruction-only | — | — |
| `github-integration` | Tool-integrated | claude.yaml (MCP), codex.yaml (scripts) | GITHUB_TOKEN |
| `linear-integration` | Tool-integrated | claude.yaml (MCP) | LINEAR_API_KEY |
| `refactoring` | Instruction-only | — | — |
| `security` | Instruction-only | — | — |
| `testing` | Instruction-only | — | — |

---

## Detailed Progress Against Plan Steps

### Phase 1: Instruction-only skills (Steps 1–15)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 1 | PreflightContext, RunContext, PendingRequest, compute_context_hash | Done | `app/providers/base.py` |
| 2 | `app/skills.py` — catalog, instructions, build_system_prompt, context builders | Done | 714 lines |
| 3 | Built-in catalog — 8+ skill.md files | Done | 10 skills shipped (8 instruction-only + 2 tool-integrated) |
| 4 | BotConfig role/skills, load_config, validate_config, role.md, BOT_ROLE rejection of `"` / `\` | Done | `app/config.py`. BOT_SKILLS validated against catalog. |
| 5 | Session state: active_skills, role, pending_request, awaiting_skill_setup | Done | `app/storage.py` |
| 6 | Claude provider: context.system_prompt → --append-system-prompt | Done | `app/providers/claude.py` |
| 7 | Codex provider: prompt prefix, context hash thread invalidation | Done | `app/providers/codex.py` |
| 8 | execute_request builds RunContext, request_approval builds PreflightContext | Done | |
| 9 | approve_pending validates hash, uses request_user_id; retry validates hash, derives context | Done | |
| 10 | /skills command (list/add/remove/clear) | Done | Also: /skills setup, /skills create |
| 11 | /role command (view/set/clear) | Done | |
| 12 | /help and /session updates | Done | |
| 13 | setup.sh role/skill prompts | Done | |
| 14 | .env.example updates | Done | |
| 15 | Tests: §8.5 invariants, skill engine, config, context hash, providers | Done | test_skills.py, test_high_risk.py |

### Phase 2: Credential-aware skills (Steps 15–24)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 15 | requires.yaml parsing | Done | `_parse_requires_yaml()` with yaml.safe_load, resilient to malformed YAML |
| 16 | Per-user credential storage with Fernet encryption | Done | `credentials/<user_id>.json`, key derived from TELEGRAM_BOT_TOKEN |
| 17 | awaiting_skill_setup in session state | Done | Survives bot restarts via restore whitelist |
| 18 | Credential check on /skills add | Done | Defers activation until creds satisfied |
| 19 | Conversational credential input with user_id match | Done | §8.1 routing order enforced |
| 20 | Secret message deletion | Done | Best-effort, logged on failure |
| 21 | Per-request credential check in execute_request and request_approval | Done | Shared `_check_credential_satisfaction()` helper |
| 22 | HTTP validation for credentials | Done | `validate_credential()` with httpx |
| 23 | /skills setup command | Done | Re-enters all credentials |
| 24 | Tests: credential flow, isolation, deletion, encryption, env injection | Done | |

### Phase 3: Provider-specific skill config (Steps 25–33)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 25 | claude.yaml parsing — MCP servers, allowed/disallowed tools | Done | |
| 26 | codex.yaml parsing — scripts, sandbox, config_overrides | Done | |
| 27 | ${VAR} placeholder resolution in build_provider_config | Done | `_resolve_placeholders()` recursive |
| 28 | Claude provider: provider_config → --mcp-config, --allowedTools, --disallowedTools | Done | |
| 29 | Codex provider: provider_config → script staging, --add-dir, sandbox settings | Done | |
| 30 | Codex script lifecycle: sync on run, clean on /new | Done | `stage_codex_scripts()`, `cleanup_codex_scripts()` |
| 31 | capability_summary for PreflightContext | Done | `build_capability_summary()` |
| 32 | Tool-integrated built-in skills | Done | github-integration, linear-integration |
| 33 | Tests: MCP config, placeholders, capability_summary, script staging | Done | |

### Phase 4: Custom skills and ecosystem (Steps 34–39)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 34 | Custom skill discovery from ~/.config/telegram-agent-bot/skills/ | Done | |
| 35 | Override logic (custom > built-in) | Done | `_skill_dir()` checks custom first |
| 36 | /skills create scaffolds custom skill | Done | |
| 37 | (custom) tag in /skills list | Done | |
| 38 | /doctor validates active skills | Done | Checks catalog presence + credential satisfaction |
| 39 | Tests: custom override, scaffold | Done | test_skills.py Phase 4 |

### Phase 5: Skill store (Steps 40–51)

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 40 | `app/store.py` — store discovery, search, skill_info | Done | `list_store_skills()`, `search()`, `skill_info()` |
| 41 | SHA-256 content hashing for update detection | Done | `_hash_directory()` — deterministic, excludes `_store.json` |
| 42 | `_store.json` provenance manifest — read/write/round-trip | Done | `StoreManifest` dataclass, `read_manifest()`, `_write_manifest()` |
| 43 | `install()` — copy from store to custom dir, SHA-256 verification | Done | Post-copy hash verification with rollback on mismatch |
| 44 | `uninstall()` — config guard, session sweep, directory removal | Done | Refuses if skill in `BOT_SKILLS`; sweeps `active_skills` across all sessions |
| 45 | `check_updates()` — compare installed vs store, detect local modifications | Done | Persists `locally_modified: true` to `_store.json` on first detection |
| 46 | `update_skill()` / `update_all()` — re-install from store | Done | Warns on local modification overwrite |
| 47 | `BOT_ADMIN_USERS` config, `is_admin()` gate | Done | Fallback to `BOT_ALLOWED_USERS` when unset |
| 48 | Handler subcommands: search, info, install, uninstall, updates, update | Done | All admin-gated mutations; browse commands open to all users |
| 49 | `(store)` tag in `/skills list` | Done | `is_store_installed()` check |
| 50 | Prompt-size warning — 8,000 char threshold, cross-chat checking | Done | `check_prompt_size()`, `_check_prompt_size_cross_chat()` on `/skills add`, `/skills update`, `/skills update all` |
| 51 | `sweep_skill_from_sessions()` in `app/storage.py` | Done | Atomic file writes, returns count of modified sessions |

---

## Production Bugs Found and Fixed During Testing

These bugs were discovered by writing handler-level integration tests against the production code. Each bug got both a production fix and a regression test.

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| Scripts dir not in RunContext | High | `build_run_context()` called before `stage_codex_scripts()` | Moved staging before context building |
| /skills add early activation | High | Skill added to active_skills before credential check | Check creds first, only activate after satisfaction |
| Cross-provider config digest invalidation | Medium | `get_provider_config_digest()` hashed both claude.yaml and codex.yaml | Added `provider_name` parameter for scoped hashing |
| Role double-wrapping | Medium | `build_system_prompt("You are a senior architect")` → "You are a You are a ..." | Case-insensitive sentence detection |
| MCP args scalar vs list | Medium | claude.yaml had `args: -y @...` (scalar string) instead of list | Fixed to YAML list syntax |
| Setup not cancelled on /skills remove | Medium | `awaiting_skill_setup` left intact after skill removal | Clear in both /skills remove and /skills clear |
| Stale scripts not cleaned | Medium | Re-staging didn't remove old files from skill directory | `shutil.rmtree` before re-staging |
| Malformed skills crash bot | Medium | No try/except in `_load_skill_md`, `load_provider_yaml`, `_parse_requires_yaml` | Added error handling; `_skill_dir()` validates parseability |
| BOT_SKILLS not validated | Low-medium | `validate_config()` didn't check skill names against catalog | Added catalog check |
| httpx missing from requirements | Low | `validate_credential()` imports httpx but it wasn't declared | Added to requirements.txt |
| Group chat credential setup overwrite | High | Single `awaiting_skill_setup` slot could be overwritten or cancelled by another user, causing first user's secret to fall through to provider | All setup writers check for existing setup by different user and refuse to overwrite. Destructive paths that would cancel a different user's setup are rejected instead of being partially applied. |
| Catalog name vs directory name divergence | Medium | `load_catalog()` used frontmatter `name` as key but `_skill_dir()` resolves by directory name | Catalog now uses directory name as canonical key |
| Non-numeric expect_status crashes | Medium-low | `int(spec.get("expect_status"))` with non-numeric value raises ValueError | Wrapped in try/except, returns user-facing error |
| Approval mode not propagating from .env | Medium | `load_session()` always restored `approval_mode` from saved session, ignoring config changes | Added `approval_mode_explicit` flag — only restore from session when user explicitly ran `/approval` |
| `/skills update all` skips prompt-size guardrail | Medium | The `all` branch only formatted results; the single-skill branch had the check | Added `_check_prompt_size_cross_chat()` call per updated skill in the `all` branch |
| `_store.json` `locally_modified` never persisted | Low | `check_updates()` detected modifications transiently in memory but never wrote back to manifest | Added `_write_manifest()` call in `check_updates()` when modification first detected |

---

## Architecture Notes

### Error handling philosophy

Malformed skill files are handled at two levels:

1. **`_skill_dir()`** (the resolution gate): Validates that `skill.md` is parseable before returning a directory. If parsing fails, the skill is invisible to the entire runtime — credential checks, provider config loading, and execution all skip it.

2. **Individual parsers**: `_load_skill_md()` raises `ValueError`, `_parse_requires_yaml()` returns `[]`, `load_provider_yaml()` returns `{}`. Each caller decides how to handle the failure.

This means a malformed custom skill in `~/.config/telegram-agent-bot/skills/` will not crash the bot, block messages, or appear in `/skills list`. It is logged as a warning during catalog discovery.

### Credential isolation

Credentials are per-user, not per-chat. The `request_user_id` field in `PendingApproval` / `PendingRetry` (typed models in `app/session_state.py`) ensures that when Alice requests and Bob approves, Alice's credentials (not Bob's) are injected into the provider subprocess. This is tested in scenario 27 (cross-user credential isolation).

### Group chat credential setup safety

The session has a single `awaiting_skill_setup` slot per chat. In a group chat, multiple users share the same session. Protection is applied at both write and destructive paths:

- **Write paths** (`_check_credential_satisfaction`, `/skills add`, `/skills setup`): Check for an existing setup belonging to a different user and refuse to overwrite it.
- **Destructive paths** (`/skills remove`, `/skills clear`, `/new`): Check setup ownership before mutating chat state. Only the setup owner can cancel their own setup; another user's destructive command is rejected with a wait message.

This prevents both the original secret-leak scenario and a partial-reset bug where a preserved setup could later resurrect a skill after `/skills clear` or `/new`. To avoid wedging a shared chat if the setup owner disappears, setups auto-expire after 10 minutes (`_SETUP_TIMEOUT_SECONDS`), allowing other users to recover. Tested in scenarios 42–50.

### Skill identity

The canonical skill identifier is the **directory name**, not the frontmatter `name` field. `_skill_dir()` resolves by directory name, and `load_catalog()` uses directory name as the catalog key. The frontmatter `name` field is display metadata only — it populates `display_name` if `display_name` is not set, but does not affect resolution. This prevents a class of bugs where a skill appears in `/skills list` but is invisible to the runtime.

### Context hash

Context hashing is centralized in `ResolvedExecutionContext.context_hash` (`app/execution_context.py`). The hash covers: role, active_skills, skill file digests, provider config digest (scoped to the active provider), base extra_dirs, project_id, file_policy, and working_dir. It does NOT cover denial-approved dirs (those are ephemeral). The hash is used for:

- Codex thread invalidation (hash change → clear thread_id)
- Pending request staleness (hash mismatch → reject retry/approval)

All paths — execute, preflight, approve, retry, /session display — use `resolve_execution_context()` as the single builder. The old `compute_context_hash()` function in `base.py` is a backward-compat wrapper.

### Test infrastructure

Handler tests use a single event loop with explicit `shutdown_default_executor()` to avoid ThreadPoolExecutor hangs from `cmd_doctor`'s `run_in_executor()`. Tests use `FakeProvider` (records all calls) and minimal Telegram stand-ins (`FakeMessage`, `FakeChat`, `FakeUpdate`). Malformed-skill tests use temporary `CUSTOM_DIR` overrides, matching the pattern in `test_skills.py`.

---

### Skill store design

The store uses a local `skills/store/` directory within the repo as a curated catalog. Skills are installed by copying to `~/.config/telegram-agent-bot/skills/` (the existing custom skills directory). A `_store.json` manifest in each installed skill directory distinguishes store-installed skills from user-created custom skills and tracks provenance.

**Install/update flow**: Copy from store → write `_store.json` with SHA-256 hash → verify hash post-copy. Updates overwrite local modifications with a warning. The `locally_modified` flag is persisted to `_store.json` the first time `check_updates()` detects a content mismatch, and reset to `false` after a successful update.

**Uninstall flow**: Config guard (refuse if skill in `BOT_SKILLS`) → session sweep (remove from `active_skills` in all saved sessions) → delete directory. Session sweep uses atomic writes to prevent corruption.

**Admin gating**: `BOT_ADMIN_USERS` config (falls back to `BOT_ALLOWED_USERS`). Instance-global mutations (install, uninstall, update) require admin. Browse commands (search, info, updates) are open to all users. Per-chat activation (`/skills add`) is also open to all users.

**Prompt-size safety**: `check_prompt_size()` warns when the composed system prompt exceeds 8,000 characters. `_check_prompt_size_cross_chat()` scans all session files to find chats where an updated skill is active and would push them over threshold. Runs on `/skills add`, `/skills update <name>`, and `/skills update all`.

**Future**: The local store directory is a stepping stone. The upgrade path is to a proper skill store service with onboarding, access control, and payment — the `_store.json` provenance manifest and SHA-256 verification are designed to generalize to that model.

See [OPS-skill-store.md](OPS-skill-store.md) for the full operations guide.

---

## What's Not Covered

### Not yet tested

- **Concurrent handler execution**: `CHAT_LOCKS` serialization under actual concurrent message delivery. Tests run handlers sequentially.
- **File upload/attachment path**: `download_attachments()` and the attachment flow through to provider. Would require mocking Telegram file download API.
- **Streaming progress updates**: `TelegramProgress` throttling and edit_text behavior during long provider runs.
- **Provider subprocess integration**: Real Claude/Codex CLI invocation. Tests mock at the Provider.run() boundary.

### Not yet implemented

- **Skill conflict detection**: Plan explicitly decided not to detect (§Q5). Documented as intentional.
