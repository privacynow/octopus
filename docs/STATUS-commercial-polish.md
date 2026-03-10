# Commercial Polish — Implementation Status

Current as of 2026-03-10. Tracks progress against [PLAN-commercial-polish.md](PLAN-commercial-polish.md).

> **Latest change (2026-03-10):** Multi-worker webhook architecture extension
> complete. Durable transport layer (`transport.db`) with update journal, work items,
> atomic claiming, stale recovery, and async worker loop. Serialized inbound event
> payloads stored for crash-recovery replay. 659 tests passing.

---

## Phase Completion Summary

| PLAN Phase | Scope | Status |
|------------|-------|--------|
| A | Core Telegram product loop | Done |
| B | Safety and trust controls | Done |
| C | Skills and credentials | Done |
| D | Output quality and mobile usability | Done |
| E | Durable runtime and execution context | Done |
| F | Managed capability distribution | Done |
| G | Registry and ecosystem | Done |
| H | Hardening and invariants | Done |
| I | Public trust profile | Done |
| IIa | Model profiles — state and plumbing | Done |
| IIb | Inline-keyboard UX for session settings | Done |
| III | Compact defaults and perceived latency | Done |
| IV | Update delivery and burst safety | Done |
| — | Resolved execution context enforcement hardening | Done |
| Ext | Multi-worker webhook architecture | Done |

---

## Test Suite

Canonical full-suite runner: `./scripts/test_all.sh` (runs `pytest` + `test_setup.sh`)

Framework: **pytest** with pytest-asyncio (auto mode). Config in `pyproject.toml`.

Current suite: **659 pytest tests** + 35 bash tests across 31 entrypoints.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_approvals.py` | 6 | Preflight prompt building, denial formatting. |
| `test_claude_provider.py` | 13 | Claude CLI command construction, API ping health check, file_policy inspect system prompt injection, effective_model override, fallback, and run/preflight command threading. |
| `test_codex_provider.py` | 36 | Codex CLI command construction, thread invalidation, progress parsing, health check with real flags, file_policy sandbox override (inspect→read-only, edit→default), effective_model override, fallback, and resume command threading. |
| `test_config.py` | 23 | Config loading, validation, `.env` parsing, rate limit and admin config, BOT_SKILLS validation, webhook mode validation, `main()` mode selection (poll/webhook), `load_config` webhook env var parsing. |
| `test_formatting.py` | 42 | Markdown-to-Telegram HTML conversion, balanced HTML splitting, table rendering, directive extraction. |
| `test_handlers.py` | 51 | Core handler integration: happy-path routing, session lifecycle, `/role`, `/new`, `/help`, `/start`, `/doctor` warnings and resilience (admin fallback, stale sessions, prompt size, missing data_dir, corrupt DB, schema version mismatch), SEND_FILE/SEND_IMAGE directive delivery, per-chat project bindings (`/project list/use/clear`, switch invalidation, context hash), file policy (`/policy inspect/edit`, session display, provider context threading, context hash), model profiles (`/model` command, inline keyboard settings callbacks, session display). |
| `test_handlers_admin.py` | 7 | `/admin sessions` summary and detail views, access gating, stale skill filtering. |
| `test_handlers_approval.py` | 14 | Approval and pending-request flows: preflight, approve/retry/skip, stale pending TTL, callback answer verification, button structure validation, markup removal after callbacks, project-active retry. |
| `test_handlers_codex.py` | 11 | Codex-specific handler behavior: thread invalidation, boot ID, retry semantics, script staging. |
| `test_handlers_credentials.py` | 40 | Credential and setup flows: capture, validation, isolation, clear/cancel, group-setup protection, clear-credentials confirmation ownership, callback answer/markup verification, button structure validation, malformed validate spec resilience. |
| `test_handlers_export.py` | 4 | `/export` command: no history, document generation, access gating. |
| `test_handlers_output.py` | 8 | Output presentation: `/compact`, `/raw`, table rendering, blockquote compact mode, expand/collapse, summary extraction. |
| `test_handlers_ratelimit.py` | 6 | Rate limiting integration: blocking, admin exemption (explicit vs implicit), per-user isolation. |
| `test_handlers_store.py` | 13 | Store handler flows: admin install/uninstall, update propagation, prompt-size warnings, ref lifecycle, callback flows (skill_add confirm/cancel, skill_update confirm/cancel/non-admin alert, unauthorized alert), markup removal verification. |
| `test_high_risk.py` | 29 | Cross-cutting invariants: requester identity, context hash staleness, credential injection, system prompt injection. |
| `test_invariants.py` | 115 | Contract-shaped invariant tests: context hash round-trip (7 combos × approval + retry), stale detection (3 change types), inspect sandbox integrity (5 provider_config combos), registry digest residue, execution context consistency, async boundary, hash completeness (8 fields), typed session round-trip (approval/retry/no-pending), handler-vs-direct builder equivalence, model profile resolution (4), public trust enforcement (7), is_public_user predicate (3), public command gating (7 commands + trusted pass-through), doctor public mode warnings (3), rate-limit defaults (2), update-ID idempotency across all entry points (4: message, decorated command, non-decorated command, callback), mixed ingress (2), execution-path trust enforcement (5), trust-tier-aware pending validation (2), credential check with resolved skills (2), model command/callback parity (4), cross-feature invariants (6: public+model escalation, inspect+model, compact+public, project+policy+approval+model), polling conflict detection (3), prompt weight in /doctor with resolved context (2), _chat_lock queued feedback (3), contended callback single-answer (3: approval, settings, clear-cred). |
| `test_ratelimit.py` | 8 | RateLimiter unit tests: sliding window, per-minute/per-hour, user isolation, clear, expiry. |
| `test_registry.py` | 8 | Skill registry: index parsing (valid/bad version/non-JSON), search, artifact download/extraction, store integration (digest match/mismatch). |
| `test_skills.py` | 43 | Skill engine: catalog, instruction loading, prompt composition, credential encryption, context hashing, role shaping, provider config digest, YAML parsing resilience. |
| `test_sqlite_integration.py` | 9 | SQLite session backend integration: handler→SQLite round-trip, JSON-to-SQLite migration under handler load, `cmd_doctor` stale scan from SQLite, `delete_session`, `close_db`/reopen lifecycle, multi-chat independence, cross-chat prompt size scan, no-JSON-artifact verification, fd leak regression on schema error. |
| `test_storage.py` | 11 | Session CRUD (SQLite-backed), upload paths, directory creation, path resolution, `list_sessions()`, JSON-to-SQLite migration with corrupt file handling. |
| `test_store.py` | 21 | Store module: discovery, search, content hashing, install/uninstall via refs and objects, ref round-trip, update detection, custom override detection, diff, GC, startup recovery, schema guard, pinned refs. |
| `test_store_e2e.py` | 26 | End-to-end user flows through handlers: install→add→message→prompt, update propagation, uninstall pruning, /skills info across all tiers, three-tier resolution, custom override shadowing, /admin sessions stale filtering, provider compatibility output, source label edge cases, normalization persistence, --doctor schema check. |
| `test_summarize.py` | 21 | Ring buffer (full prompt, kind field, rotation at 50, slot-based retrieval), export formatting, summarization. |
| `test_edge_callbacks.py` | 4 | Edge cases: approval double-click, approve after session reset, cross-user approval in shared chat, retry without pending. |
| `test_edge_formatting.py` | 11 | Edge cases: deeply nested markdown, long lines, empty code blocks, unicode/emoji, HTML entities, split_html boundaries, inconsistent table columns, trim_text edge cases. |
| `test_edge_providers.py` | 7 | Edge cases: provider timeout, empty response, error returncode, state persistence, codex thread_id persistence/resume, full approval flow. |
| `test_edge_sessions.py` | 7 | Edge cases: message after /new reset, role change with pending, /compact toggle, /session info, codex thread display, /cancel clears pending, empty message ignored. |
| `test_transport.py` | 30 | Inbound transport normalization: user/command/callback/message normalization, frozen dataclasses (tuples not lists), bot-mention stripping, None-user safety for all handler types, behavioral integration (empty-content skip, caption-to-provider), handler integration proving normalized types flow through. |
| `test_work_queue.py` | 32 | Durable transport layer: update journal idempotency, payload storage/update, enqueue/claim lifecycle, per-chat serialization, cross-chat concurrency, completion states, has_queued_or_claimed lifecycle, stale claim recovery (different worker, expired, fresh), purge old/recent/active, serialization round-trip (message/command/callback), one-work-item-per-update constraint, claim_next_any (empty/single/busy-chat/cross-chat/payload join), worker loop (process/failure/bad-payload/per-chat-ordering), handler payload storage, crash recovery with payload integrity. |
| `test_setup.sh` | 35 | Installer/setup wizard flows, provider-pruned config generation. |

---

## Phase 3 — Trust & Cost Control

### What shipped

**3.1 Rate limiting** (`app/ratelimit.py`)
- Sliding-window limiter with `BOT_RATE_LIMIT_PER_MINUTE` / `BOT_RATE_LIMIT_PER_HOUR` config.
- Admins exempt only when `BOT_ADMIN_USERS` is explicitly set (not fallback).
- Integrated in `handle_message` before any provider work.

**3.3 Admin safety posture**
- `admin_users_explicit: bool` in BotConfig distinguishes explicit config from fallback.
- `/doctor` warns when `BOT_ADMIN_USERS` not set and multiple allowed users exist.
- Rate limiter respects the explicit/fallback distinction.

**3.4 Proactive prompt size warnings**
- `estimate_prompt_size()` in `app/skills.py` projects prompt size before activation.
- Inline keyboard confirmation when projected size exceeds threshold.
- `handle_skill_add_callback` processes confirm/cancel.

**3.5 Runtime health checks**
- Provider health split into cheap sync `check_health()` (binary in PATH) and async `check_runtime_health()` (version check, API ping via `asyncio.create_subprocess_exec`).
- Claude: API ping via `claude -p --model <model> --max-turns 1`.
- Codex: API ping via `codex exec --ephemeral` mirroring real execution flags (sandbox, skip-git-repo-check, model, profile, working dir).
- `/doctor` calls both: sync check inline, async probes awaited directly in the event loop.
- `--doctor` (CLI) delegates to `collect_doctor_report()` in `app/doctor.py`.
- Age-gated stale session scan: pending requests >1h, credential setup >10m.

**3.2 Usage tracking** — Deferred. Requires token-cost mapping and billing integration.

---

## Phase 4 — Operational Hardening

### What shipped

**4.1 Managed immutable skill-store foundation** (`app/store.py`, `app/skills.py`, `app/main.py`, `app/telegram_handlers.py`)
- Content-addressed immutable objects under `managed/objects/<sha256>/`.
- Atomic logical refs under `managed/refs/<name>.json` (write `.tmp` + `os.rename`).
- Cross-instance `fcntl.flock` on `managed/.lock` for all mutations; read-only operations do not lock.
- Conservative GC at startup: removes unreferenced objects older than 1 hour, cleans stale tmp dirs and ref temps.
- Schema version guard via `managed/version.json`; refuses to operate if schema > known.
- Three-tier skill resolution: `custom/<name>` > managed ref→object > `catalog/<name>`.
- `_resolve_skill()` returns `(path, tier)` so source labels always match actual resolution.
- `skill_info_resolved()` reads metadata, body, source, and skill_dir from the resolved tier.
- `/skills info` shows content from the resolved tier (not drifted store copy), provider compatibility, and correct source label.
- `/skills list` shows `(managed)`, `(custom)`, and `[custom override]` tags.
- Session self-healing via `normalize_active_skills()` in `_load()` — all command paths get normalization, not just messages.
- `/admin sessions` and `_check_prompt_size_cross_chat` filter stale active_skills via `filter_resolvable_skills()`.
- `--doctor` checks managed store schema compatibility via `ensure_managed_dirs()` + `check_schema()`.
- Idempotent object creation, pinned ref support, `update_all` skips pinned.
- Clean break from old `_store.json` / mutable directory model — no migration.

**4.2 Locally modified skill protection**
- Under the 4.1 immutable model, managed skills cannot be edited in place.
- "Local modifications" only occur when a custom skill in `custom/<name>` shadows a managed ref.
- `/skills diff <name>` compares custom override vs managed object, or managed object vs store source (update preview).
- `/skills update <name>` updates the managed ref; if a custom override exists, the message notes it remains active.
- Batch update via `/skills update all` skips pinned refs.

**4.3 Configuration template per provider**
- `setup.sh` prunes codex-specific config lines when provider is claude (and vice versa).
- `.env.example` remains the full reference; generated configs are clean.

**4.4 Admin session visibility** (`app/storage.py`, `app/telegram_handlers.py`)
- `list_sessions()` in storage.py queries SQLite, returns sorted summary dicts.
- `/admin sessions` — summary view: total sessions, pending approvals, top skills by usage.
- `/admin sessions <chat_id>` — detail view: provider, approval mode, skills, timestamps.
- Admin-gated via `is_admin()`.
- Active skills filtered through `filter_resolvable_skills()` to exclude stale refs.

**4.5 Conversation export**
- Ring buffer upgraded: full prompt storage (no truncation), `kind` field (`request`/`approval`/`system`), capacity 10 → 50.
- Approval plan turns now captured in ring buffer.
- `export_chat_history()` in `app/summarize.py` formats entries with kind labels.
- `/export` sends session metadata header + history as downloadable `.txt` document.
- Header documents scope honestly: only successful model responses and approval plans are captured; denied, timed-out, or failed requests are not.
- `/help` updated to list `/export` and `/admin sessions`.

### Design decisions

**Immutable store vs mutable directories**: The old model copied store skills into `custom/` with a `_store.json` manifest, making provenance tracking fragile and crash recovery hard. The new model separates concerns: immutable content-addressed objects hold skill content, lightweight JSON refs provide the name→digest mapping with provenance metadata, and custom skills remain in their own editable directory. Install/update become atomic ref swaps; uninstall removes the ref and lets GC handle the orphaned object.

**Session normalization placement**: `normalize_active_skills()` runs inside `_load()` rather than only in `handle_message()`. This ensures every code path — `/skills`, `/skills list`, `/skills add`, `/admin sessions` — sees consistent state. Stale skills are pruned and persisted on first load after they become unresolvable.

**Resolution tier tracking**: `_resolve_skill()` returns `(path, tier)` as a pair so that downstream code (e.g. `/skills info` source labels) uses the tier that actually resolved, not a re-derived guess from directory/ref existence. This prevents mislabeling when stray empty dirs or malformed skill.md files exist.

**Ring buffer vs append-only log**: The `/export` feature reuses the existing ring buffer rather than building a separate conversation log. The ring buffer stores the last 50 turns with full prompts, which covers most practical export needs.

**Admin session listing**: Returns all sessions sorted by `updated_at`. No pagination — bounded by number of rows in SQLite. Detail view shows per-session metadata without loading provider state internals.

---

## Phase 5 — Transport & Webhook Foundation

### What shipped

**5.1 Thin inbound transport normalization** (`app/transport.py`, `app/telegram_handlers.py`)
- New `app/transport.py` module with frozen inbound event dataclasses: `InboundUser`, `InboundMessage`, `InboundCommand`, `InboundCallback`, `InboundAttachment`.
- Normalization functions: `normalize_user()`, `normalize_message()`, `normalize_command()`, `normalize_callback()`.
- All command handlers, the message handler, and all callback handlers now normalize inbound data before processing.
- `is_allowed()` and `is_admin()` accept both raw Telegram user objects and `InboundUser` via `_to_inbound_user()` coercion.
- Attachment download logic moved to `transport.download_attachments()`.
- The old `Attachment` dataclass is replaced by `InboundAttachment` (aliased for internal compatibility).
- All existing tests pass without modification, proving the normalization is transparent.
- 30 tests in `test_transport.py` covering: user/command/callback/message normalization, frozen dataclasses (tuples not lists), bot-mention stripping, None-user safety for all handler types, behavioral integration (empty-content skip, caption-to-provider), handler integration proving `InboundUser` flows through `is_allowed`.
- `handle_message` calls `normalize_message()` directly for text/attachment/empty-content extraction — single inbound seam, no duplicated logic.
- 3 bugs found and fixed during review:
  - Updates with no `effective_user` crashed normalization instead of returning cleanly
  - `handle_message` bypassed `normalize_message()`, duplicating text/attachment extraction (fixed: now calls normalize_message directly)
  - `InboundCommand.args` and `InboundMessage.attachments` used mutable lists despite frozen dataclass claim
- Post-review cleanup: removed dead code (`serialize_pending_request`, `clear_pending_request`, `sweep_skill_from_sessions`), removed unused imports, moved 9 misplaced tests from catch-all `test_handlers.py` to proper specialized suites, fixed test runner bug in `test_transport.py` that masked exceptions.

**5.2 Webhook mode** (`app/main.py`, `app/config.py`)
- `BOT_MODE=poll|webhook` config with `BOT_WEBHOOK_URL`, `BOT_WEBHOOK_LISTEN`, `BOT_WEBHOOK_PORT`, `BOT_WEBHOOK_SECRET`.
- Uses `python-telegram-bot`'s built-in `run_webhook()` — no separate web framework needed.
- `requirements.txt` updated to `python-telegram-bot[webhooks]>=21.0` (adds tornado).
- Webhook and polling share the same `build_application()` — identical handler registration, same normalized inbound path from 5.1.
- `validate_config()` enforces `BOT_WEBHOOK_URL` is required when `BOT_MODE=webhook`, rejects invalid mode values.
- Empty `BOT_WEBHOOK_SECRET` passes `secret_token=None` (no verification); non-empty value enables Telegram's `X-Telegram-Bot-Api-Secret-Token` header check.
- Single-process only — current in-memory per-chat locks remain the concurrency guard.
- 9 new tests: config validation (invalid mode, missing URL, valid webhook, poll mode), `load_config` env var parsing, `main()` mode selection (poll calls `run_polling`, webhook calls `run_webhook` with correct args, empty secret → None).

| Item | Status | Notes |
|------|--------|-------|
| 5.1 Thin inbound transport normalization | Done | All handlers normalized. New `app/transport.py` module. |
| 5.2 Webhook mode | Done | `BOT_MODE=webhook` uses `run_webhook()`. Single-process, same handler path as polling. |

---

## Phase 6 — Session & Execution Context

### What shipped

**6.1 SQLite session backend** (`app/storage.py`, `app/telegram_handlers.py`)
- SQLite with WAL mode replaces per-chat JSON session files.
- Schema carries `project_id` and `file_policy` columns from day one (for 6.2/6.3).
- `_db()` manages connection pool (one per data_dir), creates schema on first use.
- `_upsert()` extracts indexed columns (`provider`, `has_pending`, `has_setup`, `project_id`, `file_policy`) from session dict for query efficiency.
- One-time JSON-to-SQLite migration: on first DB open, imports `sessions/*.json` and removes files/directory. Corrupt files are cleaned up.
- Schema version guard: refuses to open if DB schema is newer than code supports.
- Same API surface: `load_session()`, `save_session()`, `list_sessions()`, `default_session()`.
- New: `session_exists()`, `delete_session()`, `close_db()`.
- All handler-side session scans (`cmd_doctor` stale scan, `_check_prompt_size_cross_chat`) converted from JSON glob to `list_sessions()` / `load_session()`.
- DB connection cleanup via `fresh_data_dir()` context manager prevents leaked connections.
- `_db()` closes the connection on initialization errors (schema mismatch, corruption) before re-raising, preventing fd leaks on repeated failures.
- 9 integration tests in `test_sqlite_integration.py` exercise real handler→SQLite round-trips, including fd leak regression on schema errors.

**6.2 Per-chat project model** (`app/config.py`, `app/telegram_handlers.py`, `app/providers/base.py`, `app/providers/claude.py`, `app/providers/codex.py`, `app/skills.py`)
- `BOT_PROJECTS=name1:/path1,name2:/path2` config with validation (duplicate names, non-existent dirs).
- `/project` command: `list`, `use <name>`, `clear`, or show current binding.
- Project switch resets provider state, clears pending requests, invalidates context hash.
- `PreflightContext.working_dir` and `RunContext` pass project working directory to providers.
- Provider subprocess `cwd` overridable: `cwd = working_dir or str(self.config.working_dir)`.
- `compute_context_hash()` includes `project_id` — stale Codex threads invalidated on project switch.
- `_allowed_roots()` scopes file access to project dirs when a project is bound.
- `cmd_session` shows active project in working directory display.
- `project_id` persisted in both SQLite column (indexed) and JSON `data` blob; restored on session load.
- 9 new tests: list (empty/populated), use (valid/invalid), clear, switch invalidation, context hash, session display.

**6.3 File policy** (`app/providers/base.py`, `app/providers/codex.py`, `app/providers/claude.py`, `app/skills.py`, `app/telegram_handlers.py`)
- `/policy inspect|edit` command to set per-chat file access policy.
- `file_policy` field on `PreflightContext`/`RunContext`, threaded through skills builders and providers.
- Codex: `file_policy=inspect` overrides sandbox to `read-only` on new exec.
- Claude: `file_policy=inspect` appends a read-only system prompt instruction.
- `compute_context_hash()` includes `file_policy` — stale Codex threads invalidated on policy change.
- `/session` shows active file policy.
- Policy switch resets provider state and clears pending requests (same pattern as project switch).
- `file_policy` persisted in SQLite `file_policy` column and JSON blob; restored on session load.
- 12 new tests: handler tests (default, set inspect/edit, same-value noop, invalid arg, session display, provider context threading, context hash), Codex sandbox override, Claude system prompt.

| Item | Status | Notes |
|------|--------|-------|
| 6.1 SQLite session backend | Done | WAL mode, schema versioning, JSON migration, indexed query columns. |
| 6.2 Per-chat project model | Done | Named project bindings per chat, provider/pending invalidation on switch, project-scoped file access. |
| 6.3 File policy | Done | `inspect|edit` per-chat, Codex sandbox override, Claude system prompt enforcement, context hash invalidation. |

---

## Phase 7 — Ecosystem & Extensibility

### What shipped

**7.1 Third-party skill registry** (`app/registry.py`, `app/store.py`, `app/skill_commands.py`, `app/config.py`)
- New `app/registry.py` module: fetch JSON index, search, download `.tar.gz` artifacts, extract with path traversal protection.
- Registry index format: `{"version": 1, "skills": {"name": {...metadata, digest, artifact_url}}}`.
- `install_from_registry()` in `app/store.py`: downloads artifact, verifies SHA-256 digest matches registry entry, creates immutable object, writes ref with `source="registry"` and publisher/version metadata.
- Digest mismatch rejects the install — no ref created for tampered artifacts.
- `/skills search` falls back to registry when `BOT_REGISTRY_URL` is configured; results deduplicated against bundled store.
- `/skills install` falls back to registry when skill not found in bundled store.
- `BOT_REGISTRY_URL` config field (empty = disabled).
- Uses `httpx` (sync client) — consistent with the rest of the codebase.
- 8 tests with real HTTP servers: index parsing (valid, bad version, non-JSON), search, artifact download (valid, missing skill.md), store integration (digest match, digest mismatch).

| Item | Status | Notes |
|------|--------|-------|
| 7.1 Third-party skill registry | Done | Remote index, artifact download, digest verification, managed store integration. |

---

## Phase 8 — Edge Case Testing and Coverage Hardening

### What shipped

**8.1 Edge case testing** (`tests/test_edge_callbacks.py`, `tests/test_edge_sessions.py`, `tests/test_edge_providers.py`, `tests/test_edge_formatting.py`)
- 29 new tests across 4 domains exercising boundary conditions and error paths.
- **Callbacks (4)**: approval double-click idempotency, approve after session reset (stale pending), cross-user approval in shared chat, retry callback without pending request.
- **Sessions (7)**: message after `/new` uses fresh state, role change with pending approval, `/compact` toggle persistence, `/session` displays provider info, codex thread display, `/cancel` clears pending, empty message ignored.
- **Providers (7)**: timeout handling, empty response, error returncode, provider state persistence, codex thread_id persistence and resume, full approval-to-execution flow.
- **Formatting (11)**: deeply nested markdown, extremely long single-line, empty code blocks, code block with language tag, unicode/emoji mix, HTML entity escaping, split_html single chunk, split_html content preservation, inconsistent table columns, trim_text empty/boundary.

| Item | Status | Notes |
|------|--------|-------|
| 8.1 Edge case testing | Done | 29 tests across callbacks, sessions, providers, formatting. |

---

## Planned Next Sequence

All build phases (A–IV) and the multi-worker webhook architecture extension
are complete. Usage tracking/billing (deferred) is the only planned item not
yet shipped.

---

## Extension: Multi-Worker Webhook Architecture

### What shipped

**Durable transport layer** (`app/work_queue.py`, `transport.db`)
- Separate SQLite WAL-mode database for transport state (not session state).
- `updates` table: durable `update_id` journal with chat_id, user_id, kind, serialized payload, received timestamp.
- `work_items` table: lifecycle states `queued → claimed → done|failed`, worker_id lease, timestamps.
- `record_update()` — idempotent insert, replaces in-memory `_seen_update_ids` set.
- `enqueue_work_item()` — creates a queued work item linked to an update.
- `claim_next(chat_id, worker_id)` — atomic `BEGIN IMMEDIATE` claim with per-chat serialization (no two items for same chat claimed simultaneously).
- `claim_next_any(worker_id)` — cross-chat atomic claim for worker loop (skips chats with in-flight items).
- `complete_work_item()` — marks done or failed with error detail.
- `update_payload()` — stores serialized event after async normalization.
- `recover_stale_claims(current_worker_id)` — requeues items held by dead workers or past max_age (called at startup).
- `purge_old(older_than_hours)` — deletes completed items and orphaned updates older than threshold.
- `has_queued_or_claimed(chat_id)` — query for durable contention check.
- Schema versioning via `meta` table with forward-compatibility guard.

**Serialized inbound event storage** (`app/transport.py`)
- `serialize_inbound()` / `deserialize_inbound()` for `InboundMessage`, `InboundCommand`, `InboundCallback`.
- All handler paths store serialized payloads at dedup time (commands, callbacks) or after normalization (messages with async attachment download).
- Payloads survive crashes: a recovered work item carries enough data to reconstruct the original event.

**Handler integration** (`app/telegram_handlers.py`)
- `_dedup_update()` replaces in-memory `_seen_update_ids` with `record_update()` + `enqueue_work_item()`.
- `_command_handler` and `_callback_handler` decorators: normalize → serialize → dedup → dispatch → complete.
- `_chat_lock` context manager: claims work item on lock entry, completes on exit (done/failed).
- `_pending_work_items` dict tracks current work item per chat for handlers that don't use `_chat_lock`.
- `_complete_pending_work_item()` helper for early returns (auth, rate limit, normalization failures).
- In-memory `CHAT_LOCKS` kept as fast-path contention signal; durable claims are the authority.

**Async worker loop** (`app/worker.py`)
- Background asyncio task that polls the durable queue for claimable items.
- Claims items atomically via `claim_next_any()`, deserializes payloads, dispatches to handler.
- Handles dispatch failures (marks failed with error), deserialization failures (marks failed).
- Respects per-chat serialization (skips chats with in-flight items).
- Configurable poll interval and batch size.
- Clean shutdown via `asyncio.Event`.
- Started via `post_init` hook, stopped via `post_shutdown` hook on the Application.

**Startup and shutdown** (`app/main.py`)
- Startup: `recover_stale_claims()` requeues orphaned items, `purge_old()` cleans retention.
- Worker task started after application init, stopped before connection close.
- `close_transport_db()` called in both `finally` blocks.

### Design decisions

**Separate transport.db**: Transport data (updates, work items) has a different lifecycle and retention policy than session state. Separate databases allow independent backup, purging, and schema evolution.

**In-memory locks as fast path**: `CHAT_LOCKS` (asyncio.Lock) provides sub-millisecond contention detection for the common single-worker case. The durable `claim_next` is the authority for crash recovery and future multi-worker. Both agree in steady state.

**Inline processing + background drain**: In single-worker mode, the inline handler path (dedup → claim inside lock → process → complete) handles most items. The background worker loop drains orphaned items from crash recovery. In future multi-worker mode, the worker loop becomes the primary processing path.

**Payload storage timing**: Commands and callbacks serialize at dedup time (normalization is sync). Messages serialize after normalization completes (attachment download is async). The `update_payload()` function updates the stored payload after the fact.

### Bugs found and fixed

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| `/skills info` showed drifted store content, not installed version | Medium-high | Handler always called `store_skill_info()` which reads from `STORE_DIR` | Added `skill_info_resolved()` using `_resolve_skill()` three-tier resolution |
| Session normalization only on message path | Medium | `normalize_active_skills()` only called in `handle_message()` | Moved into `_load()` so all command paths get normalization |
| `/admin sessions` showed stale active_skills | Medium | `list_sessions()` reads raw JSON, bypasses `_load()` normalization | Added `filter_resolvable_skills()` call in admin handler |
| `_check_prompt_size_cross_chat` used stale skills | Medium | Reads raw session JSON directly | Added `filter_resolvable_skills()` call before checking |
| `/skills info` lost provider compatibility output | Medium-low | Rewrite dropped `Providers: Claude, Codex` line | Restored by checking `claude.yaml`/`codex.yaml` in resolved skill_dir |
| `/skills info` source label mislabeled with stray custom dir | Low | Source derived from dir/ref existence, not actual resolution tier | `_resolve_skill()` returns tier; `skill_info_resolved()` uses it directly |
| `--doctor` didn't check managed store schema | Low-medium | `run_doctor()` only ran config + provider health | Added `ensure_managed_dirs()` + `check_schema()` to doctor path |
| Rate limiter ineffective for implicit admins | High | Admin fallback made all users admin-exempt from rate limiting | Added `admin_users_explicit` flag; rate limiter only exempts when explicitly configured |
| Codex health check fails in valid environments | Medium | Ping command didn't use real execution flags | Mirror `--sandbox`, `--skip-git-repo-check`, `--model`, `--profile`, `-C working_dir` |
| Normalization crashes on updates with no `effective_user` | Medium | `normalize_user()` dereferences `tg_user.id` unconditionally; handlers normalize before auth | `normalize_user` returns None for None input; all handlers guard `event is None` before accessing fields |
| `handle_message` bypasses shared normalization path | Low-medium | Handler manually extracted text/attachments instead of calling `normalize_message()` | `handle_message` now calls `normalize_message()` directly; `_download_attachments` wrapper removed; behavioral tests verify empty-content and caption paths |
| `InboundCommand.args` and `InboundMessage.attachments` were mutable lists | Low | `field(default_factory=list)` on frozen dataclass allows content mutation | Changed to `tuple` fields; tests verify `append()` raises `AttributeError` |
| `/doctor` stale scan counts fresh sessions | Medium | No age threshold — any pending request was flagged | Added `_STALE_PENDING_SECONDS = 3600`, `_STALE_SETUP_SECONDS = 600` |
| `/doctor` false positive for explicit admin with equal user sets | Low | Warning triggered when admin set == allowed set regardless of explicit config | Check `admin_users_explicit` flag, not set equality |
| `cmd_doctor` stale scan still read JSON files after SQLite migration | Medium | Stale session scan at `cmd_doctor` globbed `sessions/*.json` instead of querying SQLite | Converted to `list_sessions()` + `load_session()` |
| `_check_prompt_size_cross_chat` still read JSON files after SQLite migration | Medium | Cross-chat prompt size scan globbed `sessions/*.json` | Converted to `list_sessions()` + `load_session()` |
| `test_store_e2e.py` read session from JSON file path | Low | `normalization persists pruned state` test read `sessions/1001.json` directly | Changed to `load_session()` from SQLite |
| Leaked SQLite connections in test runners | Low | Tests created temp dirs with `ensure_data_dirs` but never called `close_db`, accumulating stale connections | Added `fresh_data_dir()` context manager; closes DB before temp dir deletion |
| `cmd_doctor` `run_in_executor` hangs in some environments | Medium | Sequential `run_in_executor()` calls within a single event loop deadlock on some platforms | Removed `run_in_executor`; split health checks into cheap sync + async subprocess probes |
| Provider health checks block the event loop | Medium | `check_health()` ran `subprocess.run()` with 10–30s timeouts, blocking the bot for all users | Split into sync `check_health()` (PATH lookup only) and async `check_runtime_health()` (async subprocess) |
| `check_runtime_health` leaks subprocesses on timeout | Medium-high | `asyncio.wait_for` timeout on `proc.communicate()` never killed or reaped the subprocess, causing orphaned CLI processes and loop-teardown warnings | Added `proc.kill()` + `await proc.wait()` on all timeout paths in both providers |
| Doctor runs expensive runtime probe after cheap check fails | Low-medium | Both `/doctor` and `--doctor` always called `check_runtime_health()` even when `check_health()` already found errors (e.g. binary missing) | Short-circuit: skip runtime probes when cheap precheck has failures |
| `_callback_handler` decorator erased handler-specific callback feedback | Medium | Decorator eagerly called `query.answer()` before handler ran, swallowing per-handler alerts (foreign-user rejection in clear-cred, non-admin rejection in skill-update) | Removed blanket `query.answer()` from decorator; each handler controls its own answer semantics. Restored lost alerts. |
| `FakeCallbackQuery` discarded answer payload | Medium | Test harness `answer()` only set `answered=True`, discarding `text` and `show_alert` — made callback feedback regression structurally undetectable | `FakeCallbackQuery.answer()` now captures `answer_text` and `answer_show_alert`. Added `send_callback()` test helper. 23 new callback feedback assertions. |
| `edit_message_reply_markup()` silently discarded on both fakes | High | 17 production calls to remove buttons after callback click — zero test coverage. Buttons failing to disappear would pass all tests. | Both `FakeMessage` and `FakeCallbackQuery` now record the call. `has_markup_removal()` helper. 10 callback paths assert markup removal. |
| `FakeCallbackQuery.answer()` overwrote on double-call | Medium | If a handler called `query.answer()` twice, the first call's payload (e.g., an alert) would be silently overwritten by the second | Changed to `answers` list with backward-compat properties. All callback tests assert `len(query.answers) == 1`. |
| Keyboard button callback_data never validated in tests | Medium | Tests checked `"reply_markup" in reply` (key exists) but never verified button content. Wrong callback_data values would route to wrong handler undetected. | Added `get_callback_data_values()` helper. Tests verify exact callback_data for approval, retry, credential-clear buttons. |
| `SEND_FILE`/`SEND_IMAGE` directive delivery untested | Medium | Full handler path from provider response → directive extraction → `reply_document`/`reply_photo` had zero integration coverage | Added end-to-end tests: provider returns directive text, handler delivers file/image to chat. |
| `--doctor` crashes when data_dir doesn't exist | Medium | `collect_doctor_report()` unconditionally scanned sessions via SQLite, which fails before first bot startup when `data_dir` hasn't been created yet | Added `config.data_dir.is_dir()` guard before stale session scan. Regression test covers the path. |
| Doctor runs expensive runtime probe before cheap store check | Low-medium | Managed store schema check (`ensure_managed_dirs` + `check_schema`) ran after the expensive subprocess runtime probe, so a trivially detectable schema error still incurred a slow API ping | Reordered: config validation → provider PATH check → managed store schema → runtime probe (only if no errors). |
| `/doctor` and `--doctor` crash on corrupt session database | Medium | `scan_stale_sessions()` calls `list_sessions()` → `_db()` → SQLite open, which throws `DatabaseError` on junk/corrupt `sessions.db`. The health command — the one tool meant to diagnose problems — crashed instead of reporting them. | Wrapped stale session scan in `collect_doctor_report` with `sqlite3.DatabaseError`/`OperationalError` handler. Reports corruption as an error in the health report. |
| Telegram `/doctor` crashes on corrupt DB before reaching health checks | Medium | `cmd_doctor` calls `_load()` which hits SQLite before `collect_doctor_report`. Corrupt DB raised unhandled `DatabaseError`, user saw nothing. | `cmd_doctor` wraps `_load()` in `DatabaseError`/`OperationalError` handler; on failure, passes `session=None` to `collect_doctor_report` which still runs all non-session checks. |
| `/doctor` crashes on newer session DB schema version | Medium | `storage._db()` raises `RuntimeError` when `schema_version > supported`, but both `collect_doctor_report` and `cmd_doctor` only caught `sqlite3` exceptions. Downgrading the bot with an existing DB crashed the health command. | Added `RuntimeError` to exception handlers in both `collect_doctor_report` (stale session scan) and `cmd_doctor` (`_load()` wrapper). Regression tests for both CLI and Telegram paths. |
| `_db()` leaks file descriptors on schema/corruption errors | Medium | `sqlite3.connect()` opens a connection, but if schema version check or `executescript` raises, the connection is never cached in `_db_connections` or closed. Repeated calls (e.g. `/doctor` retries) accumulate open fds (4→45 after 20 calls). | Wrapped `_db()` initialization in `try/except` that calls `conn.close()` before re-raising. Connection only cached after successful init. Regression test measures fd count via `/proc/{pid}/fd`. |
| `bootstrap.sh` installs dev deps in production setup | Low-medium | `scripts/bootstrap.sh` unconditionally installed `requirements-dev.txt` (pytest, xdist). `setup.sh` calls bootstrap, so operator installs got test tooling. | Dev deps only installed when `BOT_SETUP_RUNNING` is unset (standalone bootstrap, not setup.sh). |
| `test_all.sh` runs bash tests even with pytest filters | Low-medium | `test_all.sh` forwarded args to pytest then always ran `tests/test_setup.sh`. So `-k doctor` or `-x` only filtered pytest; bash suite ran in full regardless. | Bash tests only run when no arguments are passed (full suite run). |

---

## Architecture Cleanup

Seven code smells identified and fixed in a single pass. All tests pass after each change.

| Smell | Fix | Files changed |
|-------|-----|---------------|
| Duplicated doctor logic between CLI `--doctor` and chat `/doctor` | Extracted `app/doctor.py` with `collect_doctor_report()` returning `DoctorReport(errors, warnings)`. Both paths delegate to it. | `app/doctor.py` (new), `app/main.py`, `app/telegram_handlers.py` |
| Session-scan queries (`scan_stale_sessions`, `check_prompt_size_cross_chat`) lived in `telegram_handlers.py` | Moved to `app/doctor.py` as pure functions taking explicit parameters | `app/doctor.py`, `app/telegram_handlers.py` |
| Every command handler repeated `normalize_command → is_allowed` boilerplate | `@_command_handler` and `@_callback_handler` decorators. 16 command handlers and 4 callback handlers converted. | `app/telegram_handlers.py` |
| `cmd_skills` was a 370-line monolith with 13 subcommands | Extracted `app/skill_commands.py` (374 lines) with one function per subcommand. `cmd_skills` is now a 30-line dispatcher. | `app/skill_commands.py` (new), `app/telegram_handlers.py` (−330 lines) |
| Custom test runner with manual assertion helpers | Migrated all 23 test files to **pytest** with pytest-asyncio (auto mode). Removed `Checks` class, `run_test()` registration, `sys.path.insert` hacks, and per-file `__main__` runners. Deleted `tests/support/assertions.py`. `test_all.sh` skips bash tests when pytest filters are active. `bootstrap.sh` only installs dev deps when run standalone (not from `setup.sh`). | `pyproject.toml` (new), all 23 test files, `scripts/test_all.sh`, `scripts/bootstrap.sh`, `tests/support/handler_support.py` |
| Dead `session_file()` / `_SessionPath` compatibility shim in storage | Deleted (~15 lines). No callers after SQLite migration. | `app/storage.py` |
| `store._object_dir()` was private but accessed from `skills.py`; `store._parse_skill_md()` duplicated frontmatter parsing | Renamed to `store.object_dir()` (public API). `_parse_skill_md()` delegates to `skills._load_skill_md()`. Removed duplicate `import frontmatter`. | `app/store.py`, `app/skills.py`, 2 test files |

Net result: `telegram_handlers.py` reduced from 2,015 to 1,685 lines. Two new focused modules (`doctor.py`, `skill_commands.py`). All 23 test files migrated to pytest with pytest-asyncio; custom `Checks` runner deleted.

---

## Test Harness Audit

Systematic audit of `FakeCallbackQuery`, `FakeMessage`, `FakeChat`, and other test fakes to find silent data discards — places where fakes accept production calls but throw away the data, making regressions structurally undetectable.

### Blind spots found and fixed

| Blind spot | Severity | What was invisible | Fix |
|-----------|----------|-------------------|-----|
| `edit_message_reply_markup()` silently no-oped on both `FakeMessage` and `FakeCallbackQuery` | High | Buttons not disappearing after callback click (17 production call sites, 0 tests) | Both fakes now record the call in `replies`. Added `has_markup_removal()` helper. 10 callback paths now assert markup removal. |
| `FakeCallbackQuery.answer()` stored only latest call, not history | Medium | Double `query.answer()` regression would overwrite first (meaningful alert) with second (blank ack) | Changed to `answers` list. Properties provide backward compat. All 10 callback tests now assert `len(query.answers) == 1`. |
| Keyboard button callback_data never validated | Medium | Wrong `callback_data` values on buttons (routing to wrong handler) would pass tests | Added `get_callback_data_values()` helper. Tests now verify exact callback_data for approval, retry, and credential-clear buttons. |
| `send_message(reply_markup=)` captured but never asserted | Medium | Approval and permission-retry buttons could vanish from chat without test failure | Approval flow tests now verify button presence and callback_data in `sent_messages`. |
| `SEND_FILE` / `SEND_IMAGE` directive path untested end-to-end | Medium | Provider returning file/image directives could silently stop delivering files | Added integration tests: provider returns directive → handler calls `reply_document`/`reply_photo` with real files in allowed roots. |
| `reply_photo()` never exercised in integration | Medium | Image-sending feature had zero handler-level test coverage | Covered by new `SEND_IMAGE` directive test. |

### Confirmed non-issues

| Fake method | Status | Notes |
|-------------|--------|-------|
| `FakeChat.send_action()` | Correct no-op | Typing indicators are fire-and-forget |
| `FakeMessage.delete()` | Well tested | 10+ credential tests verify `.deleted` |
| `FakeMessage.edit_text()` | Well tested | Heavily used across callback tests |
| `FakeCallbackQuery.edit_message_text()` | Well tested | Verified in approval and credential tests |
| `FakeMessage.reply_document()` | Partially tested | Export path covered; directive path now covered |

---

## Deferred

| Item | Notes |
|------|-------|
| Usage tracking & quotas | Needs token-cost mapping, billing integration. Intentionally deferred. |

---

## Phase 9 — Structural Refactoring & Invariant Coverage

Root cause analysis identified that the codebase optimized for feature delivery but not for invariant coverage across cross-cutting changes. A new field added to the execution identity (e.g. `working_dir`, `file_policy`) required updates in 3–5 independent call sites; missing one caused silent approval/retry failures. The fix is structural: one authoritative context builder, typed session models, contract-shaped tests.

### What shipped

**9.1 Typed session models** (`app/session_state.py`)
- `SessionState`, `PendingApproval`, `PendingRetry`, `AwaitingSkillSetup`, `ProjectBinding` dataclasses.
- `PendingApproval` and `PendingRetry` are separate types — no more single `PendingRequest` bag with optional `denials`.
- Serialization uses `dataclasses.asdict()` — no hand-rolled field copying.
- `session_from_dict()` reconstructs typed session state from the storage dict at the runtime boundary.
- Storage layer (`storage.py`) updated: `default_session()` uses `pending_approval`/`pending_retry` keys, `_upsert()` checks both for indexed `has_pending` column, `load_session()` merges new field names.

**9.2 Authoritative execution context** (`app/execution_context.py`)
- `ResolvedExecutionContext` (frozen dataclass) — single authoritative snapshot of execution identity.
- `context_hash` property — the ONLY place context hashes are computed. Adding a field to the hash means adding it to this one object.
- `resolve_execution_context(session, config, provider_name)` — the ONLY builder. All paths (execute, preflight, approve, retry, /session display, thread invalidation) use this.
- `_resolve_context()` in handlers is now a thin adapter that delegates to the authoritative builder.

**9.3 Object-based context hashing**
- `compute_context_hash()` and `PendingRequest` deleted from `base.py` — no backward-compat baggage.
- `ResolvedExecutionContext.context_hash` is the sole hash computation path.
- All tests updated to use `ResolvedExecutionContext` directly.

**9.4 Library standardization**
- `.env` parsing: replaced hand-rolled parser in `config.py` with `python-dotenv` (`dotenv_values()`). Handles escapes, multiline values, export prefixes.
- HTTP client: replaced `urllib.request` in `registry.py` with `httpx` (sync client). `httpx` was already a dependency; now used consistently across the codebase.
- Serialization: `session_to_dict()` uses `dataclasses.asdict()` instead of hand-rolled field-by-field copying.

**9.5 Invariant test suite** (`tests/test_invariants.py`)
- 37 contract-shaped tests across 10 invariant categories:
  1. Approval hash round-trip (7 parametrized combos of project/policy/role)
  2. Retry hash round-trip (7 parametrized combos)
  3. Stale detection (3 parametrized: role/policy/project change)
  4. Inspect mode sandbox integrity (5 parametrized provider_config combos)
  5. Registry integrity (digest mismatch leaves no residue)
  6. Execution context consistency (all paths produce same hash)
  7. Async boundary (slow registry doesn't block event loop)
  8. Hash completeness (8 parametrized — every field affects hash)
  9. Typed session round-trip (approval, retry, no-pending)
  10. Handler-vs-direct builder equivalence

**9.6 Typed session boundary enforced**
- `_load()` returns `SessionState`, `_save()` accepts `SessionState`.
- Zero raw dict access (`session.get()`, `session["key"]`) in `telegram_handlers.py` or `skill_commands.py`.
- `normalize_active_skills()` in `skills.py` operates on `SessionState` attributes.
- Legacy `pending_request` migration deleted from `session_from_dict()`.
- Legacy `pending_request` check deleted from `storage._upsert()`.

**9.7 Orchestration extracted** (`app/request_flow.py`)
- Pure business logic with no Telegram imports: `build_setup_state`, `format_credential_prompt`, `foreign_setup_message`, `foreign_skill_setup`, `check_credential_satisfaction`, `pending_expired`, `validate_pending`, `extra_dirs_from_denials`, `current_context_hash`.
- `CredentialCheckResult` typed return replaces inline message-sending in credential check.
- `validate_pending()` encapsulates expiry + stale-context checks.
- Handlers import from `request_flow` and handle transport (messages, buttons, progress).
- `skill_commands.py` imports directly from `request_flow` instead of `telegram_handlers` private functions.

### Completion

All steps complete:

| Step | Description | Status |
|------|-------------|--------|
| 9.1 Typed session models | Done | `app/session_state.py` |
| 9.2 Authoritative execution context | Done | `app/execution_context.py` |
| 9.3 Object-based context hashing | Done | No backward-compat baggage |
| 9.4 Library standardization | Done | `python-dotenv`, `httpx` everywhere |
| 9.5 Invariant test suite | Done | 37 tests, 10 invariant categories |
| 9.6 Typed session boundary | Done | `_load` returns `SessionState`, zero raw dict access |
| 9.7 Orchestration extracted | Done | `app/request_flow.py` — pure business logic |

### Bugs found and fixed

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| `_current_context_hash()` missing `working_dir` | High | Added `working_dir` to hash but missed one of three call sites | Refactored to single `_resolve_context()` → `resolve_execution_context()` chain |
| Sandbox override not authoritative for inspect mode | High | Provider config `sandbox` could override `file_policy=inspect` read-only | Inspect mode check runs first; provider config sandbox only applies when not in inspect mode |
| Registry blocking event loop | Medium | `fetch_index()` and `install_from_registry()` used blocking `urllib.request` | Wrapped in `asyncio.to_thread()` at call sites; now uses `httpx` sync client |
| Digest mismatch leaves orphan objects | Medium | `install_from_registry()` created object before verifying digest | Verify digest in staging dir before `_create_object()` |

---

## Resolved Execution Context Enforcement Hardening

Root cause analysis of 5 contract violations where downstream code read raw
`session.*` or `config.*` instead of the resolved execution context. All
violations follow the same pattern: a function was written before the resolved
context existed, or was updated to accept the context but callers weren't
updated.

### What shipped

**Pending validation with trust tier** (`app/request_flow.py`)
- `current_context_hash()` now accepts `trust_tier` parameter.
- `validate_pending()` reads `trust_tier` from the stored `PendingApproval`/`PendingRetry` object and passes it through, so the hash is recomputed with the same identity shape that created it.
- Before: public user creates pending → hash uses public context. Approver clicks approve → hash recomputed as trusted. Hash mismatch → false "Context changed" error.
- `PendingApproval` and `PendingRetry` now carry a `trust_tier` field (default `"trusted"` for backward compat with existing stored sessions).

**Credential satisfaction with resolved skills** (`app/request_flow.py`, `app/telegram_handlers.py`)
- `check_credential_satisfaction()` now accepts `active_skills` as an explicit parameter instead of reading `session.active_skills`.
- `_check_credential_satisfaction()` in handlers passes `resolved.active_skills`.
- Public users have empty resolved skills → no credential prompts, no skill credential setup.
- Before: public user in a chat with `github-integration` active would be prompted to paste a GitHub token.

**Allowed roots from resolved context** (`app/telegram_handlers.py`)
- `_allowed_roots()` now accepts `ResolvedExecutionContext` instead of `SessionState`.
- Uses `resolved.working_dir` and `resolved.base_extra_dirs` for root computation.
- `send_directed_artifacts()` passes the resolved context.
- `/send` command builds resolved context before computing allowed roots.
- Before: project-bound chats used config default roots for file access; public users used operator roots.

**Mixed trusted/public ingress** (`app/telegram_handlers.py`)
- `is_allowed()` now admits all users when `allow_open=True`, regardless of whether explicit allow-lists exist.
- Trust-tier enforcement happens downstream in `resolve_execution_context`, not at the ingress gate.
- Before: `allow_open=True` with explicit `allowed_user_ids` rejected strangers entirely.

**Model command/callback parity** (`app/telegram_handlers.py`)
- `/model <profile>` now uses the same trust-tier profile filtering as `setting_model:<profile>` callbacks.
- Public users can switch to profiles in `public_model_profiles` via both surfaces.
- Before: `/model fast` was blocked by `_public_guard()` while the callback path allowed it.

### Bugs found and fixed

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| Public approval immediately fails with "Context changed" | High | `validate_pending` recomputed hash as trusted, not matching stored public hash | Read `trust_tier` from pending object; pass to `current_context_hash` |
| Public users prompted for skill credentials | Medium-high | `check_credential_satisfaction` read raw `session.active_skills` | Accept resolved `active_skills` list; public users pass `[]` |
| Project-bound directed sends use wrong roots | Medium-high | `send_directed_artifacts` called `_allowed_roots` without resolved context | Pass `ResolvedExecutionContext` to `_allowed_roots` |
| `/send` used session instead of resolved context for roots | Medium | `_allowed_roots` received `SessionState` after signature changed | Build resolved context in `/send` handler |
| Mixed open+allowed mode rejected strangers at ingress | Medium-high | `is_allowed` required empty allow-lists for `allow_open` to work | Admit all users when `allow_open=True`; tier enforcement downstream |
| `/model fast` blocked for public but callback allowed it | Medium | `/model` used blanket `_public_guard`; callback used profile filtering | Both surfaces use same trust-tier profile filtering |
| `/session` showed operator working dir for public users | Medium | Display fell back to `cfg.working_dir` when no project bound | Use `resolved.working_dir` directly |
| Unauthorized callback test assumed open mode rejects strangers | Low | Test used `allow_open=True` config but expected stranger rejection | Changed to `allow_open=False` for authorization test |
| `/start` and `/help` bypassed update_id dedup | Low-medium | These handlers inline normalize/auth instead of using `@_command_handler` decorator | Added `_dedup_update()` call at top of both handlers |
| Polling conflict detection was config heuristic only | Medium-high | `/doctor` only checked if both poll and webhook URL were set | Added real `getUpdates` HTTP 409 probe via `httpx.AsyncClient` |
| Prompt weight not shown in `/doctor` | Medium | `/session` showed character estimate but `/doctor` did not | Added `prompt_weight_chars` to `DoctorReport`; rendered in `/doctor` output |
| Commands and callbacks had no busy/queued feedback | Medium | Only `handle_message` checked `lock.locked()` before queuing | Added lock check with visible feedback to `_command_handler` and `_callback_handler` decorators |
| Cross-feature invariant matrix incomplete | Medium | Only 2 of 4 PLAN-specified combos tested | Added: compact+public+long reply, project+file_policy+approval+model change |
| Plan overstated first-progress and prompt-weight criteria | Low-medium | Plan said "1 second" and "token count" but implementation uses immediate messages and char estimates | Updated PLAN to match what was built: immediate pre-invocation messages, char-based prompt size |
| Polling probe false-warns from running bot | Medium-high | `/doctor` ran `getUpdates` probe while the bot was running — self-409 in poll mode, webhook conflict in webhook mode | Renamed to `caller_is_bot`; Telegram `/doctor` always passes `True`, CLI `--doctor` passes `False` (only safe caller) |
| Queued feedback fired for non-blocking handlers | Medium | Decorator checked `lock.locked()` before handler ran, so `/session` and other lock-free commands showed "queued" then responded immediately | Moved feedback to `_chat_lock` context manager; only handlers that actually block send feedback |
| `/doctor` prompt weight used raw session, not resolved context | Medium | `collect_doctor_report` computed prompt weight from `session["active_skills"]`, ignoring public trust tier stripping | Moved computation to `cmd_doctor` handler using `_resolve_context` with trust tier |
| Commands used bare `CHAT_LOCKS` bypassing queued feedback | Medium | 12 command/callback handlers used `async with CHAT_LOCKS[chat_id]` directly instead of `_chat_lock`, so queued feedback never appeared | Converted all 12 sites to `_chat_lock` with appropriate `message=`/`query=` parameter |
| `handle_callback` answered before entering lock | Medium | `query.answer()` consumed the callback answer slot before `_chat_lock` could send queued feedback | Moved `query.answer()` inside `_chat_lock` for `handle_callback`, `handle_settings_callback`, and `handle_skill_add_callback` |
| Contended callbacks answered twice | Medium | `_chat_lock` sent queued feedback via `query.answer()`, then the handler called `query.answer()` again after acquiring the lock | `_chat_lock` now yields `sent_feedback` boolean; handlers skip their own `query.answer()` when `True`. 3 contention tests added. |
| `handle_clear_cred_callback` answered before entering lock | Medium | `query.answer()` called before `_execute_clear_credentials` entered `_chat_lock`, so queued feedback was ineffective under contention | Confirm branches defer `query.answer()` to `_execute_clear_credentials`, which passes `query=` to `_chat_lock` and answers after lock acquisition (skipped when queued feedback already sent). Cancel branch answers immediately (no lock needed). |
