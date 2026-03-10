# Commercial Polish — Implementation Status

Current as of 2026-03-09. Tracks progress against [PLAN-commercial-polish.md](PLAN-commercial-polish.md).

---

## Phase Completion Summary

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 | Activation & self-service | Done |
| Phase 2 | Output quality | Done |
| Phase 3 | Trust & cost control | Done |
| Phase 4 | Operational hardening | Done |
| Phase 5 | Transport & webhook foundation | In progress (5.1 done, 5.2 next) |
| Phase 6 | Session & execution context | In progress (6.1 done, 6.2 next) |
| Phase 7 | Ecosystem & extensibility | Not started |
| Phase 8 | Edge case testing & coverage hardening | Not started |

---

## Test Suite

Canonical full-suite runner: `./scripts/test_all.sh` (runs `pytest` + `test_setup.sh`)

Framework: **pytest** with pytest-asyncio (auto mode). Config in `pyproject.toml`.

Current suite: **416 pytest tests** + 35 bash tests across 24 entrypoints.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_approvals.py` | 6 | Preflight prompt building, denial formatting. |
| `test_claude_provider.py` | 8 | Claude CLI command construction, API ping health check. |
| `test_codex_provider.py` | 29 | Codex CLI command construction, thread invalidation, progress parsing, health check with real flags. |
| `test_config.py` | 14 | Config loading, validation, `.env` parsing, rate limit and admin config, BOT_SKILLS validation. |
| `test_formatting.py` | 42 | Markdown-to-Telegram HTML conversion, balanced HTML splitting, table rendering, directive extraction. |
| `test_handlers.py` | 24 | Core handler integration: happy-path routing, session lifecycle, `/role`, `/new`, `/help`, `/start`, `/doctor` warnings and resilience (admin fallback, stale sessions, prompt size, missing data_dir, corrupt DB, schema version mismatch), SEND_FILE/SEND_IMAGE directive delivery. |
| `test_handlers_admin.py` | 7 | `/admin sessions` summary and detail views, access gating, stale skill filtering. |
| `test_handlers_approval.py` | 12 | Approval and pending-request flows: preflight, approve/retry/skip, stale pending TTL, callback answer verification, button structure validation, markup removal after callbacks. |
| `test_handlers_codex.py` | 11 | Codex-specific handler behavior: thread invalidation, boot ID, retry semantics, script staging. |
| `test_handlers_credentials.py` | 40 | Credential and setup flows: capture, validation, isolation, clear/cancel, group-setup protection, clear-credentials confirmation ownership, callback answer/markup verification, button structure validation, malformed validate spec resilience. |
| `test_handlers_export.py` | 4 | `/export` command: no history, document generation, access gating. |
| `test_handlers_output.py` | 6 | Output presentation: `/compact`, `/raw`, table rendering, summarization flows. |
| `test_handlers_ratelimit.py` | 6 | Rate limiting integration: blocking, admin exemption (explicit vs implicit), per-user isolation. |
| `test_handlers_store.py` | 13 | Store handler flows: admin install/uninstall, update propagation, prompt-size warnings, ref lifecycle, callback flows (skill_add confirm/cancel, skill_update confirm/cancel/non-admin alert, unauthorized alert), markup removal verification. |
| `test_high_risk.py` | 29 | Cross-cutting invariants: requester identity, context hash staleness, credential injection, system prompt injection. |
| `test_ratelimit.py` | 8 | RateLimiter unit tests: sliding window, per-minute/per-hour, user isolation, clear, expiry. |
| `test_skills.py` | 43 | Skill engine: catalog, instruction loading, prompt composition, credential encryption, context hashing, role shaping, provider config digest, YAML parsing resilience. |
| `test_sqlite_integration.py` | 8 | SQLite session backend integration: handler→SQLite round-trip, JSON-to-SQLite migration under handler load, `cmd_doctor` stale scan from SQLite, `delete_session`, `close_db`/reopen lifecycle, multi-chat independence, cross-chat prompt size scan, no-JSON-artifact verification. |
| `test_storage.py` | 11 | Session CRUD (SQLite-backed), upload paths, directory creation, path resolution, `list_sessions()`, JSON-to-SQLite migration with corrupt file handling. |
| `test_store.py` | 21 | Store module: discovery, search, content hashing, install/uninstall via refs and objects, ref round-trip, update detection, custom override detection, diff, GC, startup recovery, schema guard, pinned refs. |
| `test_store_e2e.py` | 26 | End-to-end user flows through handlers: install→add→message→prompt, update propagation, uninstall pruning, /skills info across all tiers, three-tier resolution, custom override shadowing, /admin sessions stale filtering, provider compatibility output, source label edge cases, normalization persistence, --doctor schema check. |
| `test_summarize.py` | 18 | Ring buffer (full prompt, kind field, rotation at 50), export formatting, summarization. |
| `test_transport.py` | 30 | Inbound transport normalization: user/command/callback/message normalization, frozen dataclasses (tuples not lists), bot-mention stripping, None-user safety for all handler types, behavioral integration (empty-content skip, caption-to-provider), handler integration proving normalized types flow through. |
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

| Item | Status | Notes |
|------|--------|-------|
| 5.1 Thin inbound transport normalization | Done | All handlers normalized. New `app/transport.py` module. |
| 5.2 Webhook mode | Not started | Deferred until after 6.1 SQLite — lands on transactional storage. First cut remains single-process. |

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
- 8 integration tests in `test_sqlite_integration.py` exercise real handler→SQLite round-trips.

| Item | Status | Notes |
|------|--------|-------|
| 6.1 SQLite session backend | Done | WAL mode, schema versioning, JSON migration, indexed query columns. |
| 6.2 Per-chat project model | Not started | Optional named project bindings layered on top of the current working-dir model. |
| 6.3 File policy | Not started | `inspect|edit` persisted in session/project/provider context. |

---

## Phase 7 — Ecosystem & Extensibility

| Item | Status | Notes |
|------|--------|-------|
| 7.1 Third-party skill registry | Not started | Lands after phases 5 and 6 on top of the 4.1 managed store foundation. |

---

## Planned Next Sequence

Execution from the current state is:

1. ~~**5.1** — add thin inbound transport normalization~~ Done.
2. ~~**6.1** — move chat sessions from JSON blobs to SQLite~~ Done.
3. **5.2** — add webhook mode on top of SQLite + normalized inbound path
4. **6.2** — add optional per-chat project bindings
5. **6.3** — add file policy (`inspect|edit`)
6. **7.1** — add the third-party registry on top of the 4.1 store model
7. **8.1** — edge case testing and coverage hardening

`5.1` and `6.1` are complete. `5.2` is next — webhook ingress writes to
SQLite from the start. `6.2` and `6.3` use the `project_id` and `file_policy`
columns already present in the schema. `8.1` runs last as a systematic sweep.

The deferred item `3.2` (usage tracking / billing hooks) remains intentionally out of sequence.

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

---

## Architecture Cleanup

Seven code smells identified and fixed in a single pass. All tests pass after each change.

| Smell | Fix | Files changed |
|-------|-----|---------------|
| Duplicated doctor logic between CLI `--doctor` and chat `/doctor` | Extracted `app/doctor.py` with `collect_doctor_report()` returning `DoctorReport(errors, warnings)`. Both paths delegate to it. | `app/doctor.py` (new), `app/main.py`, `app/telegram_handlers.py` |
| Session-scan queries (`scan_stale_sessions`, `check_prompt_size_cross_chat`) lived in `telegram_handlers.py` | Moved to `app/doctor.py` as pure functions taking explicit parameters | `app/doctor.py`, `app/telegram_handlers.py` |
| Every command handler repeated `normalize_command → is_allowed` boilerplate | `@_command_handler` and `@_callback_handler` decorators. 16 command handlers and 4 callback handlers converted. | `app/telegram_handlers.py` |
| `cmd_skills` was a 370-line monolith with 13 subcommands | Extracted `app/skill_commands.py` (374 lines) with one function per subcommand. `cmd_skills` is now a 30-line dispatcher. | `app/skill_commands.py` (new), `app/telegram_handlers.py` (−330 lines) |
| Custom test runner with manual assertion helpers | Migrated all 23 test files to **pytest** with pytest-asyncio (auto mode). Removed `Checks` class, `run_test()` registration, `sys.path.insert` hacks, and per-file `__main__` runners. Deleted `tests/support/assertions.py`. | `pyproject.toml` (new), all 23 test files, `scripts/test_all.sh`, `tests/support/handler_support.py` |
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

## What's Not Yet Implemented

| Item | Status | Notes |
|------|--------|-------|
| 3.2 Usage tracking & quotas | Deferred | Needs token-cost mapping, billing integration |
| 5.2 Webhook mode | Not started | Next execution item. `BOT_MODE=poll\|webhook`, webhook server, `/health` endpoint, single-process only in first cut. |
| 6.2 Per-chat project model | Not started | Named project bindings per chat, with provider/pending invalidation on switch. |
| 6.3 File policy | Not started | `inspect|edit` surfaced in session/provider context. |
| 7.1 Third-party skill registry | Not started | Planned after phases 5 and 6. Uses the managed store foundation from 4.1 |
| 8.1 Edge case testing | Not started | Systematic boundary/error/interaction testing across callbacks, files, providers, skills, sessions, formatting. |
