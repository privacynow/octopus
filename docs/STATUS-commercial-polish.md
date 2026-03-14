# Commercial Polish — Implementation Status

Current as of 2026-03-13. Tracks progress against [PLAN-commercial-polish.md](PLAN-commercial-polish.md).

> **Latest change (2026-03-13):** **Milestone E (Bucket E) — in progress.** Partial work landed: README dev_up/doctor wording, lib_env.sh and script consolidation, dead progress_liveness removed, model-profile source unified in cmd_session and settings callback, two test fixes (recovery_already_handled oracle, provider_status env message in lib). **Milestone E is not complete.** It remains open until: (1) **Compose E2E** has actually been run and any failures fixed or blockers documented; (2) the **structural simplification pass** over telegram_handlers, user_messages, execution_context, and operator scripts is done (dead code, stale branches, duplicate owners, obsolete compatibility); (3) the **test ownership/rationalization pass** over test_handlers, test_workitem_integration, test_request_flow, test_handlers_approval and handler_support is done (ownership audit, moves/merges/deletes where justified, no “no tests moved” without a real audit). Do not mark E complete or say “Next: Phase 13” until all of that is done and verified. **Compose E2E:** In this session the E2E run was not executed (invocation aborted). The operator must run E2E_COMPOSE=1 pytest tests/e2e/test_compose_flows.py where Docker is available before marking E complete.
>
> **Structural simplification (same day):** telegram_handlers: removed 7 unused imports (build_setup_state, RunContext, PreflightContext, summarize, AwaitingSkillSetup, check_credentials, load_user_credentials) and dead helper _project_working_dir. user_messages: added settings_compact_on_label, settings_compact_off_label, admin_required, no_sessions_found, no_conversation_to_export, no_projects_configured, approval_usage, policy_usage; handlers updated to use them (duplicate compact label and admin/sessions/export/projects/usage copy centralized). **Test ownership audit:** test_handlers (handler UX), test_handlers_approval (approval/retry), test_request_flow (trust/context/validate_pending), test_workitem_integration (claim/recovery/worker); ownership aligned, no moves. Added test_settings_and_admin_messages_bucket_e. Verification: handlers, approval, request_flow, workitem, user_messages, operator_scripts passed.
>
> **Prior (2026-03-13):** **Bucket D follow-up — public /settings model text and keyboard unified.** Public `/settings` was showing resolved effective model in the text but the selected model button from raw session/default, so when default was restricted (e.g. balanced) and public only had fast, the screen could show "Model profile: fast" with the fast button unchecked. **Fix:** (1) Added `_settings_model_profile_state(session, cfg, trust_tier, effective_model)` in `telegram_handlers.py` returning `(available_profiles, current_profile_for_display)` so public users get current from effective model over public profiles only. (2) `cmd_settings` now uses that single source for both the "Model profile:" line and the inline keyboard checkmark. (3) `cmd_model` uses the same helper so `/model` and `/settings` stay aligned. (4) **Test:** `test_public_settings_model_text_and_button_agree_when_default_restricted` — default_model_profile="balanced", public_model_profiles={"fast"} → reply text shows "Model profile:" and "fast", only setting_model:fast button, and that button is checked. Handler suite 75 passed. Bucket D complete; next: **Bucket E**.
>
> **Prior (2026-03-13):** **Bucket D — restriction / trust / profile clarity done.** (1) **Resolved context as display authority:** `/settings` and `/session` already used `_resolve_context`; public `/settings` model display now derived from resolved effective model (profile name from public set or "(default)"); public `/session` appends `trust_settings_managed_public()` so project/file-policy are clearly operator-managed. (2) **`/model`:** Public "current" profile label is the profile matching `resolve_effective_model` from public set, or "(default)". (3) **Shared wording:** No new user_messages; existing `trust_settings_managed_public`, `trust_file_policy_public`, `trust_project_public` used. (4) **Command/callback parity:** Callbacks already used same trust checks and messages; no divergence. (5) **Tests:** `test_public_settings_shows_managed_and_no_project_policy_buttons`, `test_public_session_shows_resolved_and_managed_message`, `test_public_model_shows_only_public_profiles`, `test_settings_callback_policy_denial_public`, `test_settings_callback_project_denial_public`; trusted `test_settings_command_shows_current_values` unchanged. Full handler suite 74 passed. Next: **Bucket E — final hardening and truthfulness**, then Phase 13.
>
> **Prior (2026-03-13):** **Bucket C follow-up — Option 2: adjacent cancellation strings centralized.** (1) **queue_busy()** fixed: "Yours is queued and will run next" (no "try again"). (2) **Option 2:** Credential cancellation copy moved to user_messages: `credential_setup_cancelled()`, `credential_setup_another_user_in_progress()`, `credential_clear_cancelled()`. Handlers: cmd_cancel (own setup + another user's setup), _execute_clear_credentials (setup_cleared line), handle_clear_cred_callback (clear_cred_cancel). **Tests:** test_credential_cancellation_messages; test_cancel_setup and test_cancel_admin_foreign_setup pin credential_setup_cancelled(); test_cancel_foreign_setup_shows_another_user_message pins credential_setup_another_user_in_progress(); test_clear_credentials_cancel pins credential_clear_cancelled(). Status claim now matches implementation.
>
> **Prior:** **Bucket C — no-op / already-handled / busy / wrong-user clarity.** User-facing dead-end and “you can’t do that now” messages are centralized and clarified. **Seams:** (1) `app/user_messages.py` — wording improved: `recovery_discarded_confirm` "Request skipped."; `retry_skip_confirmation` "Retry skipped. Nothing to run again."; `queue_busy` "Another request is already running. Yours is queued and will run next."; `callback_wrong_user` "This button is only for the person who started the request."; added `nothing_to_cancel()` and `cancel_pending_request()`. (2) `app/telegram_handlers.py` — cmd_cancel uses `_msg.nothing_to_cancel()` and `_msg.cancel_pending_request()`; recovery/retry/approval/clear_cred paths already used user_messages. (3) **Tests:** test_user_messages (queue_busy, callback_wrong_user, nothing_to_cancel, cancel_pending_request); test_cancel_nothing_to_cancel; test_clear_credentials_cross_user_rejected pins callback_wrong_user(); test_recovery_double_click pins recovery_already_handled(); test_recovery_discard_callback_finalizes_item pins recovery_discarded_edit(); test_cancel_pending pins cancel_pending_request(). No workflow or FSM changes. Next: Bucket D.
>
> **Prior:** **Bucket B follow-up — Trust- and admin-aware help.** `/start` and `/help` reflect current user's usable command surface; public no /project or /policy; non-admin no /admin sessions.
>
> **Prior:** **Bucket B — Command/help/discoverability done.** Main user path discoverable in-bot and truthful in docs; HELP_TEMPLATE added /project; help/start/README parity; tests for settings/project/session and registration.
>
> **Prior:** **Compose E2E harness isolation fixed and verified.** The E2E suite no longer publishes a host Postgres port, uses a unique Compose project per run/worker, generates a per-run override with a temporary `.env.bot` and unique bot image tag, captures full logs on failure and teardown, and tears down only its own project with `down -v --remove-orphans`. Verified with real runs: `E2E_COMPOSE=1 .venv/bin/python -m pytest -q tests/e2e/test_compose_flows.py -n 0` and `-n 4` both passed (`5 passed, 1 skipped`).
>
> **Prior:** **Roadmap correction after Phase 12.** The future roadmap is no longer “Postgres queue next for everyone.” The next numbered phase is now **Phase 13 — Storage backend abstraction and Local Runtime mode**, with SQLite as the planned default backend for both Docker and host deployments. Shared-runtime Postgres queue work has been moved to the end of the roadmap as a later capability tier. Docs updated to distinguish: (1) **shipped today** = Postgres-only runtime from Phase 12, and (2) **planned next** = backend-neutral product/core plus Local Runtime first, Shared Runtime later.
>
> **Prior:** **Milestone D follow-up.** Stale/invalidated pending message fixed: `approval_context_changed()` now describes execution-context change truthfully ("This request can't continue because the chat context changed…"), not only settings/project. Retry callback wording fully centralized: `retry_skip_confirmation()` ("Retry skipped.") and `retry_nothing_pending()` ("No retry is waiting.") in `user_messages.py`; handlers use them. Tests: user_messages pins context-changed wording (no "settings or project" only); test_retry_skip asserts retry-skip edit text; test_retry_allow_no_pending asserts no-retry wording; test_stale_context_hash and test_validate_pending_detects_real_context_change assert "context" in reply. 200 passed.
>
> **Prior:** **Milestone D complete.** Progress, recovery, approval, and trust clarity. User-facing copy centralized in `app/user_messages.py`. Progress: provider-neutral labels. Recovery: interruption notice, Run again/Skip, already-handled/blocked/discarded. Approval/retry: plan review, approve/reject, expired/context-changed, permission/retry prompt. Trust: not authorized, public-mode restrictions, settings managed. Tests: test_user_messages.py; handler/approval/request_flow/progress updated; all pass.
>
> **Prior:** **Milestone C follow-up.** `/settings` now respects public-user execution-context: display built from `_resolve_context` only (no trusted project/path leak); project and file-policy controls omitted for public users; optional line "Project selection and file policy are managed by the operator in public mode." `/settings` added to `HELP_TEMPLATE` so `/help` and `/start` expose it. Tests: public `/settings` trust-boundary (no leak), public keyboard restriction (no `setting_project:*`/`setting_policy:*`), trusted regression (project/policy/model/compact/approval), help/start discoverability; existing Milestone C tests unchanged.
>
> **Prior:** **Milestone C complete.** `/settings` as discoverability surface (current project, model, policy, compact, approval + inline controls). `/project` default shows inline project selection and clear. `handle_settings_callback` extended with `setting_project:<name>` and `setting_project:clear`; same mutation/invalidation as commands. Public user denied project callback. Tests: settings view, project default keyboard, project use/clear/clears-pending callbacks, compact does not reset provider state, project callback public denied.
>
> **Prior:** **dev_up.sh DB lifecycle:** Uses **db-update** as the branch selector; runs **db-bootstrap** only when update reports the explicit "Schema or schema_migrations table missing" condition. All other failures (connectivity, auth, drift, newer-than-supported schema) surface clearly and exit non-zero; doctor is post-action validation only. **tests/test_dev_up_contract.sh** pins update-success, missing-schema→bootstrap, other-failure→no bootstrap, and **guided_start.sh** propagation of dev_up failure.
>
> **Prior (2026-03-13):** Tooling independent of bot config: **bot** service under profile **bot** so `docker compose up -d postgres` and db-* tooling work without `.env.bot`. Bot start: **docker compose --profile bot --env-file .env.bot up -d bot**. **Provider-tagged images** (`telegram-agent-bot:claude`, `telegram-agent-bot:codex`); build via `./scripts/build_bot_image.sh` (docker build, no compose build); **provider_login.sh** checks `docker image inspect` and fails with rebuild message if image missing. **guided_start.sh** single-pass: runs provider_login if needed, then starts bot (no “rerun script”). README front door: clone, `.env.bot`, **./scripts/guided_start.sh**. E2E: **test_compose_postgres_up_without_env_bot**; shell contract: image-inspect guard, --profile bot in compose args.
>
> **Prior (2026-03-13):** Provider login as first-class Docker workflow: **bot-home** volume at `/home/bot` persists provider auth; **entrypoint** chowns bot-home to uid 1000 then runs as bot (gosu). **provider_login.sh** runs in-container login (codex `--login` / claude `/login`) using same image and volume, then verifies provider health; **provider_status.sh** runs `--doctor`; **provider_logout.sh** clears provider auth in bot-home. Startup validates provider auth (runtime health) and fails with “Run ./scripts/provider_login.sh” when missing. README Quick Start includes provider login; Troubleshooting and scripts table updated. ARCHITECTURE documents bot-home and provider-login ownership. Prior: supported path = real provider image; stub test-only.
>
> **Prior (2026-03-12):** Post-Phase-12 execution program was made explicit in the roadmap. This historical note predates the later roadmap correction that moved shared-runtime queue authority to the end of the plan; the gate itself remains, but now leads into Milestone E and then **Phase 13 — storage backend abstraction and Local Runtime mode** rather than immediate queue-authority work.
> **Schema policy (corrected):** Transport schema is versioned; migration/upgrade path is deferred, not rejected as product direction. No "fresh-schema-only" or "delete DB and restart" product policy. Current build expects current schema/layout; unsupported schema/layout fails fast with a neutral error (`Unsupported transport.db schema/layout for this build`). Bootstrap: brand-new DB (no tables) gets `_CREATE_SQL` + schema_version; existing DB is validated only (tables, columns, `idx_one_claimed_per_chat`, meta schema_version) and is not mutated before validation.
> **Transport repository shape:** Single claim path `_claim_queued_item`; single insert path `_insert_initial_work_item`. All mutators use `_write_tx(conn)`; nested use raises `RuntimeError("nested transport transaction")`. Impossible machine rejections are fatal: `_apply_transport_event` and `_insert_initial_work_item` raise `TransportStateCorruption` on workflow rejection; `_claim_queued_item` returns None only for `other_claimed_for_chat`, else raises; `mark_pending_recovery`, `discard_recovery`, `supersede_pending_recovery`, `reclaim_for_replay` raise on invalid_transition (recover_stale_claims allows guard_failed as “not stale, skip”). Chat integrity: `_assert_no_invalid_rows_for_chat(conn, chat_id)` is called in `has_queued_or_claimed`, `get_latest_pending_recovery`, `reclaim_for_replay`, `supersede_pending_recovery`. Strict helpers: `_apply_claim_event` for claim-style transitions (exact CAS, reread); reclaim_for_replay uses it; supersede_pending_recovery applies _apply_transport_event per item in one transaction; recover_stale_claims uses exact source predicate (id, state, worker_id, claimed_at) and reread classification.
> **Transaction and invariant fixes:** One transaction wrapper for all mutating entry points; rollback on any exception. `_assert_no_invalid_rows_for_chat()` enforces at most one claimed per chat. Current schema includes `idx_one_claimed_per_chat`. Tests: rollback on non-IntegrityError, two-claimed raises, fresh schema index, meta/schema_version validation (unsupported layout/mismatch raise neutral error).
> **Phase 11 sealed.** Phase 12 complete (Postgres runtime cutover). Next after Milestone E: **Phase 13 (storage backend abstraction and Local Runtime mode).**
>
> **Prior:** Phase 11 second workflow (pending approval/retry machine, invalidation in machine, 39 machine tests).
>
> **Prior:** Phase 11 transport regression tests (stale claim/complete, dispatch corruption, meta no schema_version).
>
> **Prior:** Enqueue/preclaim derived from machine; preclaim test.
>
> **Prior:** Claim paths exact CAS in `claim_next`/`claim_next_any`; regression test for stale complete vs later claim.
>
> **Prior:** Test isolation, parallel default, portable fd test.
> **Priority 4 (test isolation):** One authoritative reset path
> (`reset_handler_test_runtime()`), close-all for session and transport DB
> caches, conftest autouse fixture, isolation regression tests. Direct
> `_bot_instance` writes removed (use `set_bot_instance()`). Full suite passes
> under `-n 2`, `-n 4`, `-n 8`. **Default pytest:** `pyproject.toml` addopts
> set to `-v -n 4` so `pytest` runs with 4 workers by default. **Portable fd
> test:** `test_db_no_fd_leak_on_schema_error` now uses `/proc/{pid}/fd` on
> Linux and `/dev/fd` on macOS; skips on unsupported platforms. Full suite
> (all 787 tests) runs on macOS without exclusions.
>
> Prior: Fresh command ownership race fix — Priority 2.
> `record_and_enqueue()` now creates work items as `claimed` (handler-owned)
> instead of `queued` when the inline handler is active. The background
> worker can no longer steal fresh commands and send false "interrupted by
> a restart" recovery notices. `claim_for_update()` recognizes pre-claimed
> items. `complete_work_item()` guards against overwriting terminal states.
> Per-chat serialization preserved (falls back to `queued` when chat is busy).
> 9 new integration tests covering the exact bug scenarios from production.
> 787 pytest + 36 bash tests.
>
> Prior: Priority 3c (raw provider event regression fixtures). Checked-in
> Codex and Claude NDJSON traces in tests/fixtures/progress/; regression
> tests feed them through mapping/render and assert event types and
> user-visible output. Priority 3 (test coverage gaps) complete.
>
> Prior: Priority 3a/3b (test coverage gaps). Heartbeat vs provider liveness
> test and rate-limit + semantic event test in test_progress.py (real
> TelegramProgress, burst with suppression asserted).
>
> Prior: Test-suite ownership refactor — Priority 1.
> Deleted 5 overflow files (test_high_risk, test_edge_callbacks,
> test_edge_sessions, test_edge_providers, test_edge_formatting).
> 20 weak duplicate tests removed, unique tests strengthened and moved
> to owner suites. Created test_execution_context.py and
> test_request_flow.py as missing owner suites.
>
> Prior: All build phases shipped.
> Phases A–I, IIa/b, III (all sub-items including Layer 2 progress
> contract and expand/collapse), IV, Ext (webhook), restart recovery
> hardening — all shipped and tested.
>
> Historical note (superseded by the roadmap correction above): remaining work
> previously followed the older linear Phase 11-19 sequence in
> [PLAN-commercial-polish.md](PLAN-commercial-polish.md), with Postgres queue
> authority immediately after the Postgres cutover. The current roadmap no
> longer uses that ordering.
>
> Prior: Progress UX Layer 2, user-intent-owned replay, restart recovery
> hardening, supersede_recovery guard, ReclaimBlocked exception.
>
> Prior: Claude resume timeout fix, work-item claim fix, mid-flight
> mutation serialization, preflight model parity, export trust
> enforcement, project extra_dirs contract.
>
> Restart recovery (three items, all resolved):
> - Item 1 (fixed): worker_dispatch infinite replay loop — historical.
> - Item 2 (fixed): Claude resume state poisoning — historical.
> - Item 3 (fixed): User-intent-owned replay. New `pending_recovery`
>   work-item state. worker_dispatch sends recovery notice with inline
>   keyboard instead of auto-replaying. Fresh messages supersede pending
>   recovery (only `handle_message`, not commands or callbacks — guarded
>   by `supersede_recovery` parameter on `_chat_lock`). Double-click on
>   buttons is idempotent. Replay goes through `_chat_lock` with
>   `worker_item`; interruption during replay leaves item claimed for
>   next-boot re-recovery. `reclaim_for_replay` enforces per-chat
>   single-claimed invariant; raises `ReclaimBlocked` when blocked by
>   another claim (distinct from returning None when item is gone).
>   Failed recovery-notice delivery re-raises so `worker_loop` marks
>   item failed, not done.
>   `RunResult.resume_failed` field provides typed evidence from the provider.
>   Claude provider parses stderr for session-not-found/invalid-session
>   markers and sets `resume_failed=True` only when the resume target is
>   dead. Generic errors during a healthy resumed session do not trigger
>   reset. Codex retains its existing thread_id clear on any resume error.
>   False-positive test confirms generic errors preserve session state.
>   **Integration test confirmed:** the real Claude CLI does NOT emit
>   classifiable stderr on a dead session — it either hangs (env-dependent)
>   or exits rc=1 with empty stderr. The timeout path now sets
>   `resume_failed=True` when `is_resume` is true, which is the primary
>   recovery mechanism. The stderr classifier remains as defense in depth
>   in case a future CLI version emits structured errors.
>
> Resource and correctness: subprocess leak fix in summarize.py, regex
> backreference injection fix in skills.py, cancelled tasks now awaited in
> finally blocks, first content update bypasses rate limiter after
> content_started (heartbeat/progress race fix).
>
> Approval wording: all user-facing "Preflight" replaced with neutral terms.
> Tests rewritten with _StickyReplyMessage so edit_text updates on the
> status message are visible in assertions. Positive assertions prove
> "Approval required." and "Approval check failed:" are observed.
>
> Test improvements: mock.patch replaces module global mutation, sys.executable
> replaces hardcoded python3. Engineering standards updated with pre-merge
> gate checklist, bug decomposition rules, completion-owner rules.
>
> Correctness fixes (latest):
> - **Work-item claim (High):** `_chat_lock` now takes `update_id` and uses
>   `claim_for_update()` to claim the specific item for the current update.
>   Stale recovered items are no longer silently marked done when a fresh
>   update acquires the lock first. Worker_loop still uses `claim_next`.
> - **Worker/live-handler race (High):** When `claim_next_any` claims an item
>   in the worker loop (outside the in-memory lock), a live handler that
>   acquires the lock first now raises `ClaimBlocked` instead of running
>   unserialized. The handler's work item stays queued for the worker to
>   pick up. Both decorators (`_command_handler`, `_callback_handler`) and
>   `handle_message` catch `ClaimBlocked`. `_callback_handler` answers the
>   query before returning so Telegram's callback spinner is dismissed.
>   Worker path uses `worker_item` parameter to skip re-claiming.
> - **Mid-flight /project /policy (High):** `/project use|clear` and
>   `/policy inspect|edit` now serialize with `_chat_lock`, preventing
>   provider_state mutation while a request is in-flight.
> - **Preflight model parity (Medium):** `PreflightContext` now carries
>   `effective_model`. Approval preflight uses the same model as execution.
> - **Export trust enforcement (Medium):** `/export` uses resolved execution
>   context for the header, not raw `session.active_skills`. Public users
>   no longer see trusted-only skills in export output.
> - **Project extra_dirs (Low):** `resolve_execution_context` now folds
>   `project_binding.extra_dirs` into `base_extra_dirs`, honoring the
>   allowed-roots contract.
>
> Work-item claiming and callback update_id threading now covered by real
> integration tests (`test_workitem_integration.py`) exercising real SQLite,
> real asyncio locks, and real handler code — only faking Telegram transport
> and provider subprocess. Redundant fake-based unit tests removed from
> `test_invariants.py`. 736 tests passing.

---

## Current Snapshot

- Phases 1-10 are sealed as shipped.
- The next numbered roadmap phase is **Phase 13 — storage backend abstraction and Local Runtime mode**.
- Immediate execution focus is the pre-Phase-13 gate:
  - turnkey Docker runtime
  - config/onboarding simplification
  - user-facing settings and `/project` polish
  - progress/recovery/trust clarity
  - usability hardening
- Phase 12 is complete: the **shipped runtime today** uses Postgres and
  requires `BOT_DATABASE_URL` at startup.
- The roadmap direction after Phase 12 is now:
  - **Local Runtime first**: backend-neutral product/core plus SQLite as the
    planned default backend for both Docker and host deployments
  - **Shared Runtime last**: Postgres queue authority and multi-process scale
- Dockerized app + Postgres is the primary supported operational model.
- Compose is the canonical shape for Postgres, DB tooling, and the app runtime.
- The **supported bot image** is a **real provider-enabled image** (includes the chosen Claude or Codex CLI). Built via repo-owned script from `BOT_PROVIDER` (e.g. `./scripts/build_bot_image.sh`); operators do not choose Docker targets manually. The stub-provider image (`Dockerfile.runnable`) exists only for **test/dev smoke** (e.g. E2E when real provider is not available) and is not the supported runtime.
- Zero-to-running: clone → start Postgres → DB bootstrap → DB doctor → create `.env.bot` → build bot image for your provider → `docker compose run --rm --env-file .env.bot bot`. README presents one Docker-first path; build complexity lives in the build script and deeper docs.
- Host-run remains available as a secondary fallback/debug path.
- DB bootstrap, DB update, and DB doctor are explicit repo-owned workflows; app
  startup is validate-only.
- Postgres integration suites use a harness-started test-only Docker container
  per pytest-xdist worker and never touch `BOT_DATABASE_URL`, dev, staging, or
  production databases.
- The primary docs are now `README.md`, `ARCHITECTURE.md`,
  `PLAN-commercial-polish.md`, and `STATUS-commercial-polish.md`.
- `transport idempotency` is shipped in Phase 9.
- `content dedup` is intentionally unshipped and remains future work in
  Phase 15.

---

## Linear Roadmap Status

| Phase | Scope | Status | Note |
|------:|-------|--------|------|
| 1 | Core Telegram loop | Done | Core request/response, file flow, and session commands shipped. |
| 2 | Safety, approvals, and rate limiting | Done | Approval, retry, `/cancel`, `/doctor`, and rate limiting shipped. |
| 3 | Roles and instruction-only skills | Done | Roles and instruction-only capability surfacing shipped. |
| 4 | Credentialed and provider-specific skills | Done | Credential capture, encrypted storage, and provider-specific setup shipped. |
| 5 | Skill store and capability distribution | Done | Managed store, registry install/search, and digest verification shipped. |
| 6 | Output, compact mode, and progress UX | Done | Compact/raw/export, expand/collapse, summary-first, and normalized progress shipped. |
| 7 | Durable session state and execution context | Done | Typed session state and authoritative resolved execution context shipped. |
| 8 | Public trust, model profiles, and settings UX | Done | Mixed trust, model profiles, and inline settings UX shipped. |
| 9 | Durable transport, transport idempotency, webhook mode, and restart recovery | Done | Durable queue, webhook path, replay/discard recovery, and polling conflict detection shipped. |
| 10 | Structural hardening, invariants, and test ownership | Done | Invariant coverage, test ownership refactor, and runtime isolation hardening shipped. |
| 11 | Workflow ownership extraction | Done | Transport/recovery and pending approval/retry are now library-owned workflow families. Transport uses one claim path, one insert path, `_apply_claim_event`, one transaction wrapper, fatal impossible rejections, and chat-integrity checks; pending invalidation flows through `PendingRequestMachine`. Phase 11 sealed. |
| 12 | Postgres runtime cutover | Done | M1–M9 complete. Current shipped runtime is Postgres-only; BOT_DATABASE_URL required; E2E layer and zero-to-running docs in place. |
| 13 | Storage backend abstraction and Local Runtime mode | Planned | Next numbered phase after Milestone E. Restore a first-class Local Runtime mode with SQLite as the default backend for Docker and host, behind backend-neutral storage/runtime contracts. |
| 14 | Product polish on local foundations | Planned | Continue product polish on top of Local Runtime and backend-neutral contracts. |
| 15 | Behavior extensions | Planned | Demand-gated `content dedup` and richer project/policy scope without coupling product work to Shared Runtime queue authority. |
| 16 | Registry trust and governance | Planned | Publisher signing and organizational trust policy on top of digest verification. |
| 17 | Usage accounting, quotas, and billing | Planned | Usage recording, quota enforcement, and billing before Shared Runtime queue work. |
| 18 | Shared Runtime: Postgres queue authority in webhook mode | Planned | Advanced deployment capability: persist-first webhook ingress and app-owned Postgres queue authority. |
| 19 | Shared Runtime: multi-process scale and durability confidence | Planned | Multi-process workers, leases, recovery metrics, crash confidence, and shared-runtime durability. |

Detailed workstream sections below are preserved as historical implementation
record. The authoritative roadmap ordering is the Phase 1-19 table above.

---

## Current Execution Focus

The next numbered roadmap phase is still Phase 13, but execution should not
start there yet. The required gate is the pre-Phase-13 program defined in
[PLAN-commercial-polish.md](PLAN-commercial-polish.md).

| Milestone | Status | Scope |
|---|---|---|
| **Docker-first productization track (A1–A4)** | **Done** | Clean zero-to-running path, one `.env.bot` path, config/doctor/startup messages. **Supported** path uses **real** provider-enabled image (build script from BOT_PROVIDER); stub image is test/dev-only. |
| A. Turnkey Docker runtime | Done (track) | Real provider-enabled image build (Dockerfile.bot + build script); Compose E2E for bootstrap/doctor/update; tests prove provider in image and execution path where possible. |
| B. Config and onboarding simplification (Docker scope) | Done (track) | One primary `.env.bot` path; config/startup/DB CLI messages reference `.env.bot` and build script. |
| C. User-facing settings and `/project` polish | Done | `/settings` discoverability surface; `/project` default with inline keyboard; `setting_project:*` callbacks in `handle_settings_callback`; project/policy/compact/model/approval parity; tests for settings view, project callbacks, public denial, compact-no-reset. Follow-up: `/settings` uses resolved context only (public-safe display), no project/policy buttons for public users; `/settings` in `HELP_TEMPLATE`; tests for public trust-boundary, keyboard restriction, help/start discoverability. |
| D. Progress, recovery, and trust clarity | Done | Centralized user-facing copy in `app/user_messages.py`. Progress: provider-neutral wording. Recovery: interruption notice, Run again/Skip, already-handled/blocked/discarded messages. Approval/retry: plan review, approve/reject, expired/context-changed, permission/retry prompt. Trust: not authorized, public-mode restrictions, settings managed. Tests: test_user_messages.py; handler/approval/request_flow/progress tests updated; existing behavior tests intact. |
| E. Usability hardening before Phase 13 | In progress | Full scope per PLAN: Docker/operator path, command/help/discoverability, no-op and restriction clarity, config/doctor/startup tests, Compose E2E, handler flows. **Landed so far:** README command-table correctness (no /retry, /clear), dev_up discoverability (guided_start hint); tests: test_readme_commands.py, test_dev_up_contract.sh. Milestone remains **open** until the full usability-hardening scope and required test envelope in the plan are satisfied. |

**Milestone E note:** Do not mark E complete until the broad end-to-end hardening pass (Docker path, onboarding, `/doctor`, startup, main Telegram journey) and the plan’s required verification (config/doctor/startup tests, Compose E2E, persistence/integration suites, user-visible handler flows) are done. The two fixes already in tree are useful but do not by themselves satisfy the gate.

Phase 13 should not start until the full gate in the plan is satisfied (including C, D, E as applicable). Shared-runtime queue authority is no longer the immediate next step; it is deferred to Phase 18.

### Milestone E — Usability audit (Step 1)

Bounded audit of Docker/operator and Telegram surfaces. Classifications: **discoverability**, **misleading wording**, **wrong/no-op state**, **path drift**, **stale docs**, **operator trap**.

**Docker/operator path**

| Surface | Finding | Classification |
|--------|---------|-----------------|
| First run | guided_start 4-step flow and README Quick Start align. dev_up ends with “To run the bot” + guided_start hint. | — |
| Provider login | provider_login.sh requires .env.bot, checks image, clear “build first” message. | — |
| Provider status | Script prints “Provider auth and runtime only (no DB/Telegram checks)”; comment says “For full app health use … app.main --doctor”. Operator may still treat provider_status success as “all good”. | **operator trap** |
| Provider logout | Clear; “Done. Run ./scripts/provider_login.sh to authenticate again.” | — |
| Update after pull | README: db-update, build, up -d bot; guided_start rebuilds when rev/files changed. | — |
| Doctor | Three distinct things: (1) db_doctor = Postgres/schema only, (2) provider_status = provider auth only, (3) app --doctor / in-chat /doctor = full. README and provider_status mention full doctor but distinction could be clearer. | **discoverability** / **operator trap** |
| Stale image / rebuild | guided_start rev + mtime; build_bot_image suggests guided_start. | — |
| Missing image / provider auth / DB | Scripts and startup fail with clear messages (build image, provider_login, rerun dev_up). | — |

**Telegram path**

| Surface | Finding | Classification |
|--------|---------|-----------------|
| /start, /help | HELP_TEMPLATE includes /settings, /session, /approve, /reject, /cancel, /doctor. Command table (README) fixed (no /retry, /clear). | — |
| /settings, /session | In HELP_TEMPLATE. /project only reachable via “view and change chat settings” (no separate /project line in main command list). | **discoverability** |
| Approval / retry / recovery | Centralized copy in user_messages; buttons in-context. No explicit “retry” or “Run again/Skip” in main help text. | **discoverability** (minor) |
| Already-handled / no-op / busy / wrong-user | recovery_already_handled, retry_nothing_pending, queue_busy, callback_wrong_user centralized; handlers use them. | — |
| Public restriction | trust_* and settings_managed_public centralized. | — |

**Step 2 — Execution plan (Bucket A → E)**

| Bucket | Scope | Owner seam | Tests required |
|--------|--------|------------|----------------|
| **A** | guided_start, dev_up, provider_login/status/logout, README, doctor vs provider-health | Scripts + README operator section; provider_status vs app --doctor wording | Shell/operator contract; config/doctor/startup; Compose E2E for touched flows |
| **B** | /start, /help, /settings, /project, /session | HELP_TEMPLATE + cmd_start/cmd_help; README command table | Handler tests start/help; discoverability parity; README command checks if touched |
| **C** | retry, recovery, queue busy, wrong user, nothing pending, already-handled, skip/discard/replay no-op | user_messages + callback/handler paths | Handler/callback tests on user-visible text; adjacent regression |
| **D** | public restrictions, unavailable profile/settings, trust wording | user_messages + _public_guard / resolve paths | request_flow/handler tests; public-mode regression; trusted parity |
| **E** | Final pass: Docker path + Telegram journey, docs/status alignment | All touched seams | config/doctor/startup; Compose E2E; persistence/integration touched; handler flows; then mark E done |

**Current:** Bucket C done. Next: Bucket D (restriction / trust / profile clarity).

**Bucket C completed:** No-op / already-handled / busy / wrong-user clarity. **Centralized in user_messages.py (and used by handlers):** recovery discard confirmation, retry skip confirmation, queue busy ("Yours is queued and will run next"), wrong-user callback, nothing_to_cancel, cancel_pending_request; credential_setup_cancelled, credential_setup_another_user_in_progress, credential_clear_cancelled (Option 2 follow-up). cmd_cancel, handle_clear_cred_callback, and _execute_clear_credentials use these. **Tests:** user_messages (queue_busy, callback_wrong_user, nothing_to_cancel, cancel_pending_request, credential_cancellation_messages); handler tests pin credential_setup_cancelled(), credential_setup_another_user_in_progress(), credential_clear_cancelled(); test_cancel_foreign_setup_shows_another_user_message; test_clear_credentials_cancel; test_cancel_setup, test_cancel_admin_foreign_setup. Invariants unchanged. No new FSM or workflow.

**Bucket B completed:** Command/help/discoverability, then follow-up for trust- and admin-aware help. Main user path discoverable from `/start` and `/help`; README command table matches real surface; `/project` visible for trusted users only. **Seams:** Static HELP_TEMPLATE replaced by `_help_command_lines(user)` and `_build_main_help(user)`; cmd_start and cmd_help both call `_build_main_help(event.user)`. Public users do not see `/project` or `/policy`; non-admin users do not see `/admin sessions`; trusted/admin see full relevant set. **Tests:** `test_help_and_start_include_settings` (trusted: settings, project, session; no /retry, no standalone /clear); `test_help_and_start_public_user_excludes_project_and_policy`; `test_help_and_start_non_admin_excludes_admin_sessions`; `test_help_and_start_admin_sees_admin_sessions_and_trusted_commands`; README and registration parity tests unchanged. No new FSM or help framework.

**Bucket A completed:** Provider vs full-doctor distinction hardened. **Seams:** (1) `scripts/provider_status.sh` — on success now prints one line: "For full app health (DB, config, Telegram) run: docker compose … bot python -m app.main --doctor". (2) README Building section — explicit "provider_status checks only provider auth and runtime (no DB or Telegram); it is **not** full app health." (3) Compose E2E harness is now isolated and parallel-safe: no host Postgres port publication, unique Compose project per run/worker, generated temp `.env.bot`, unique bot image tag, full log capture, and project-scoped teardown with `down -v --remove-orphans`. **Tests:** `tests/test_operator_scripts.py` (provider_status reminds full doctor, requires .env.bot); `tests/test_dev_up_contract.sh`; `tests/test_readme_commands.py`; doctor handler tests; `tests/test_db_postgres.py` doctor slice; and real Compose E2E runs via `E2E_COMPOSE=1 .venv/bin/python -m pytest -q tests/e2e/test_compose_flows.py -n 0` and `-n 4` (`5 passed, 1 skipped` in both modes).

---

## Docker-first productization track (complete)

Executed 2026-03-13. Scope: Docker/runtime only; no user-facing polish, no Phase 13 work.

| Milestone | Delivered |
|-----------|-----------|
| **A1. Supported runnable image** | **Real** provider-enabled image: `Dockerfile.bot` (base + provider install via `scripts/install_provider_claude.sh`, `scripts/install_provider_codex.sh`). `./scripts/build_bot_image.sh` selects target from `BOT_PROVIDER`. Stub image (`Dockerfile.runnable`) and `bot-stub` Compose service (profile `stub`) for **test/dev-only** (E2E_USE_STUB_IMAGE=1). |
| **A2. Clean zero-to-running path** | Flow: clone → Postgres → bootstrap → doctor → `.env.bot` → **./scripts/build_bot_image.sh** → start bot container. One README path; build complexity in script and deeper docs. E2E: bootstrap/doctor/update; `test_compose_bot_image_has_provider` (real image has provider binary); `test_compose_bot_startup_validates_schema` (real image); `test_compose_bot_stub_smoke` (test-only). |
| **A3. Docker config and onboarding simplification** | One `.env.bot` path. Config errors mention `.env.bot` and `./scripts/build_bot_image.sh`. DB CLI message for missing `BOT_DATABASE_URL` points to Docker vs host-run. |
| **A4. Docker usability hardening** | Stabilization; docs truthful (supported = real provider image; stub = test-only). |

Artifacts: `Dockerfile.bot`, `scripts/build_bot_image.sh`, `scripts/install_provider_claude.sh`, `scripts/install_provider_codex.sh`; `Dockerfile.runnable` and `bot-stub` (profile stub) for test/dev-only; E2E and config tests.

---

## Open Items

### ~~1. Claude resume failure detection depends on unverified stderr format~~ (resolved)

**Resolution:** Integration test (`test_claude_cli_bogus_resume_no_classifiable_error`)
confirmed the real Claude CLI does NOT emit classifiable stderr for a
dead session. Depending on environment, it either hangs silently or
exits rc=1 with empty stderr/stdout.

**Fix:** `ClaudeProvider.run()` now sets `resume_failed=True` on the
timeout path when `is_resume` is true. This is the primary recovery
mechanism — the handler resets session state and the next request
starts a fresh session. The stderr classifier (`_is_resume_failure`)
remains as defense in depth for a future CLI version that emits
structured errors.

**Tests added:**
- `test_claude_timeout_during_resume_sets_resume_failed` — provider unit
- `test_claude_timeout_during_fresh_session_no_resume_failed` — false-positive guard
- `test_claude_cli_bogus_resume_no_classifiable_error` — integration against real CLI

---

## Test Suite

Canonical full-suite runner: `./scripts/test_all.sh` (runs `pytest` + `test_setup.sh`)

Framework: **pytest** with pytest-asyncio (auto mode). Config in `pyproject.toml`.
Default: **4 workers** (`addopts = "-v -n 4"`). Full suite runs on Linux and
macOS (fd leak test portable: `/proc` on Linux, `/dev/fd` on macOS).

Current suite: **827 pytest tests** + 36 bash tests across 31 files.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_approvals.py` | 6 | Preflight prompt building, denial formatting. |
| `test_claude_provider.py` | 17 | Claude CLI command construction, API ping health check, file_policy inspect system prompt injection, effective_model override, fallback, run/preflight command threading, retry extra_dirs forwarding, preflight hardening, error state contract. |
| `test_codex_provider.py` | 42 | Codex CLI command construction, thread invalidation, progress event mapping, health check with real flags, file_policy sandbox override (inspect→read-only, edit→default), effective_model override, fallback, resume command threading, preflight safety (no full-auto/dangerous in safe_mode), extra_dirs/uploads isolation, runtime extra_dirs merge. |
| `test_config.py` | 31 | Config loading, validation, `.env` parsing, rate limit and admin config, BOT_SKILLS validation, webhook mode validation, `main()` mode selection (poll/webhook), `load_config` webhook env var parsing, data_dir writability, extra_dirs validation, bad timeout error, config isolation across instances. |
| `test_execution_context.py` | 53 | Execution context contracts: context hash round-trip (7 combos × approval + retry), stale detection (3 change types), inspect sandbox integrity (5 provider_config combos), ResolvedContext path parity, hash field sensitivity (8 fields), typed session round-trip (approval/retry/no-pending), handler-vs-direct builder equivalence, execution config digest, extra_dirs forwarding, model profile resolution (4), project+model cross-invalidation. |
| `test_formatting.py` | 47 | Markdown-to-Telegram HTML conversion, balanced HTML splitting, table rendering, directive extraction, deeply nested markdown, extremely long single-line, empty code blocks, unicode/emoji mix, trim_text empty/boundary. |
| `test_handlers.py` | 58 | Core handler integration: happy-path routing, session lifecycle, `/role`, `/new`, `/help`, `/start`, `/doctor` warnings and resilience (admin fallback, stale sessions, prompt size, missing data_dir, corrupt DB, schema version mismatch), SEND_FILE/SEND_IMAGE directive delivery, per-chat project bindings (`/project list/use/clear`, switch invalidation, context hash), file policy (`/policy inspect/edit`, session display, provider context threading, context hash), model profiles (`/model` command, inline keyboard settings callbacks, session display), empty message ignored, codex thread display, message after /new fresh session, provider empty response. |
| `test_handlers_admin.py` | 7 | `/admin sessions` summary and detail views, access gating, stale skill filtering. |
| `test_handlers_approval.py` | 17 | Approval and pending-request flows: preflight, approve/retry/skip, stale pending TTL, callback answer verification, button structure validation, markup removal after callbacks, project-active retry, approval after session reset, retry callback without pending, role change invalidates pending. |
| `test_handler_runtime_isolation.py` | 3 | Priority 4: reset clears all handler globals and DB caches; clean runtime has no leaked state; caches empty after teardown. |
| `test_handlers_codex.py` | 12 | Codex-specific handler behavior: thread invalidation, boot ID, retry semantics, script staging. |
| `test_handlers_credentials.py` | 40 | Credential and setup flows: capture, validation, isolation, clear/cancel, group-setup protection, clear-credentials confirmation ownership, callback answer/markup verification, button structure validation, malformed validate spec resilience. |
| `test_handlers_export.py` | 4 | `/export` command: no history, document generation, access gating. |
| `test_handlers_output.py` | 15 | Output presentation: `/compact`, `/raw`, table rendering, blockquote compact mode, button-path threshold (long response forces expand button), expand callback (full response via new messages for long text, in-place edit with Collapse button for short text), collapse callback (restores compact with Show full button), expand→collapse round trip, rotated-buffer expand fallback, summary-first prompt injection at execution context boundary (compact on/off), summary extraction. |
| `test_handlers_ratelimit.py` | 6 | Rate limiting integration: blocking, admin exemption (explicit vs implicit), per-user isolation. |
| `test_handlers_store.py` | 13 | Store handler flows: admin install/uninstall, update propagation, prompt-size warnings, ref lifecycle, callback flows (skill_add confirm/cancel, skill_update confirm/cancel/non-admin alert, unauthorized alert), markup removal verification. |
| `test_invariants.py` | 70 | Cross-cutting invariant tests (genuinely span multiple boundaries): registry digest residue, async boundary, update-ID idempotency (4: message, decorated command, non-decorated command, callback), _chat_lock queued feedback (3), contended callback single-answer (3: approval, settings, clear-cred), same-chat overlapping update completion, shutdown-interrupted runs stay claimed for recovery, all signals (rc<0) treated as interrupted (4), provider error feedback (2), global error handler (3), decorator exceptions mark work items failed (2), summarizer subprocess killed on timeout, callback None-event completes work item, provider-neutral progress wording (5), Claude/Codex thinking capitalization (2), Codex thread ID suppression (3), Codex compaction wording, heartbeat (5: idle firing, stops on content, clean cancellation, respects recent progress, content_started signals), approval initial status neutral. Temporarily houses: doctor warnings, progress wording/heartbeat, recovery/resume, error handlers (pending future migration). |
| `test_progress.py` | 49 | Progress event contract tests: render() output for all 9 event types, no-internals-leak checks, Codex _map_event type mapping (thinking, command start/finish, tool start/finish, draft reply, suppressed internals), end-to-end raw-event→render pipeline, tool_activity truncation, empty-text fallback, Claude _consume_stream integration (text delta, tool activity, denial, content_started signal, no-internals parity). Heartbeat vs provider liveness (no overwrite). Rate-limit + semantic event preservation (TelegramProgress, burst, suppression asserted). Raw fixture regression (Priority 3c): Codex and Claude NDJSON traces through mapping/render. |
| `test_ratelimit.py` | 8 | RateLimiter unit tests: sliding window, per-minute/per-hour, user isolation, clear, expiry. |
| `test_registry.py` | 8 | Skill registry: index parsing (valid/bad version/non-JSON), search, artifact download/extraction, store integration (digest match/mismatch). |
| `test_request_flow.py` | 49 | Request flow contracts: public trust enforcement (7), is_public_user/is_allowed predicates (3+2), public command gating (7 commands + trusted pass-through), rate-limit defaults (2), mixed trust ingress (2), execution-path trust enforcement (5), trust-tier-aware pending validation (2), classify_pending_validation (ok/expired/context_changed), credential satisfaction with resolved skills (2), model command/callback parity (4), extra_dirs_from_denials, compact+public cross-feature (6), export resolved skills, polling conflict detection (3), prompt weight in /doctor with resolved context (2). |
| `test_pending_request_workflow_machine.py` | 39 | Pending approval/retry workflow: allowed/forbidden transitions, guards (validation_ok, is_expired, is_context_stale), dispositions (executed, rejected, expired, invalidated, cancelled), handler-path classification→disposition, unknown event/state. |
| `test_skills.py` | 44 | Skill engine: catalog, instruction loading, prompt composition, credential encryption, context hashing, role shaping, provider config digest, YAML parsing resilience. |
| `test_sqlite_integration.py` | 9 | SQLite session backend integration: handler→SQLite round-trip, JSON-to-SQLite migration under handler load, `cmd_doctor` stale scan from SQLite, `delete_session`, `close_db`/reopen lifecycle, multi-chat independence, cross-chat prompt size scan, no-JSON-artifact verification, fd leak regression on schema error (portable: Linux /proc, macOS /dev/fd). |
| `test_storage.py` | 14 | Session CRUD (SQLite-backed), upload paths, directory creation, path resolution, `list_sessions()`, JSON-to-SQLite migration with corrupt file handling, provider mismatch state reset, upload isolation (per-chat dir enforcement, cross-chat denial, shared-root denial), upload isolation in provider commands. |
| `test_store.py` | 21 | Store module: discovery, search, content hashing, install/uninstall via refs and objects, ref round-trip, update detection, custom override detection, diff, GC, startup recovery, schema guard, pinned refs. |
| `test_store_e2e.py` | 26 | End-to-end user flows through handlers: install→add→message→prompt, update propagation, uninstall pruning, /skills info across all tiers, three-tier resolution, custom override shadowing, /admin sessions stale filtering, provider compatibility output, source label edge cases, normalization persistence, --doctor schema check. |
| `test_summarize.py` | 21 | Ring buffer (full prompt, kind field, rotation at 50, slot-based retrieval), export formatting, summarization. |
| `test_transport.py` | 30 | Inbound transport normalization: user/command/callback/message normalization, frozen dataclasses (tuples not lists), bot-mention stripping, None-user safety for all handler types, behavioral integration (empty-content skip, caption-to-provider), handler integration proving normalized types flow through. |
| `test_work_queue.py` | 37 | Durable transport layer: update journal idempotency, payload storage/update, enqueue/claim lifecycle, per-chat serialization, cross-chat concurrency, completion states, has_queued_or_claimed lifecycle, stale claim recovery (different worker, expired, fresh), purge old/recent/active, serialization round-trip (message/command/callback), one-work-item-per-update constraint, claim_next_any (empty/single/busy-chat/cross-chat/payload join), worker loop (process/failure/bad-payload/per-chat-ordering), handler payload storage, crash recovery with payload integrity, interrupted worker items left claimed for recovery. |
| `test_workitem_integration.py` | 31 | Real integration tests for work-item claim serialization and recovery: fresh message does not consume stale recovered item, concurrent messages each claim own item, claim_for_update blocked by existing claimed item, approval callback does not consume stale item, /project switch serializes with in-flight request, preflight and execution use same model, live command blocked by worker-claimed item, live message blocked by worker-claimed item, blocked item processable after worker completes, live callback blocked by worker and query answered, worker_dispatch sends recovery notice (not auto-replay), recovery discard callback finalizes item, recovery replay callback executes original, fresh message supersedes pending_recovery, double-click on recovery buttons is idempotent, failed notice delivery marks item failed via worker_loop, multiple pending_recovery items each addressable by update_id, discard race after replay answers already-handled, replay reclaim blocked by existing claimed item (ReclaimBlocked), blocked replay informs user "in progress", command does not supersede pending_recovery, reclaim distinguishes gone from blocked, fresh command item created as claimed (handler-owned), worker cannot steal handler-owned item, no false recovery for /compact, no false recovery for /doctor, no false recovery for /session, handler crash leaves item recoverable, claim_for_update recognizes pre-claimed items, complete_work_item state guard (no terminal overwrite), per-chat serialization preserved with pre-claimed items. Real SQLite, real asyncio locks, real handler code — only fakes are Telegram transport and provider subprocess. |
| `test_setup.sh` | 36 | Installer/setup wizard flows, provider-pruned config generation. |

---

## Historical Workstream: Phase 3 — Trust & Cost Control

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

## Historical Workstream: Phase 4 — Operational Hardening

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

## Historical Workstream: Phase 5 — Transport & Webhook Foundation

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

## Historical Workstream: Phase 6 — Session & Execution Context

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
- 9 integration tests in `test_sqlite_integration.py` exercise real handler→SQLite round-trips, including portable fd leak regression on schema errors (Linux/macOS).

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

## Historical Workstream: Phase 7 — Ecosystem & Extensibility

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

## Historical Workstream: Phase 8 — Edge Case Testing and Coverage Hardening

### What shipped

**8.1 Edge case testing** (originally `test_edge_callbacks.py`, `test_edge_sessions.py`, `test_edge_providers.py`, `test_edge_formatting.py` — all deleted in ownership refactor)
- 29 original tests across 4 domains. 20 weak duplicates deleted, unique tests strengthened and moved to owner suites:
  - **Callbacks (2 unique → `test_handlers_approval.py`)**: approve after session reset, retry without pending. 2 duplicates deleted.
  - **Sessions (4 unique → `test_handlers.py`, `test_handlers_approval.py`)**: empty message ignored, codex thread display, message after /new, role change invalidates pending (strengthened). 3 duplicates deleted.
  - **Providers (1 unique → `test_handlers.py`)**: provider empty response. 6 duplicates deleted.
  - **Formatting (5 unique → `test_formatting.py`)**: deeply nested markdown, long single-line, empty code blocks, unicode/emoji mix, trim_text empty. 7 duplicates deleted.

| Item | Status | Notes |
|------|--------|-------|
| 8.1 Edge case testing | Done | Tests folded into owner suites; overflow files deleted. |

---

## Historical Remaining-Work Record (Superseded)

All build phases (A–IV) and the single-worker webhook foundation are shipped.
The active remaining-work structure is now the Phase 11-19 roadmap in
[PLAN-commercial-polish.md](PLAN-commercial-polish.md). This section is
retained only as historical execution record:

1. **Test-suite ownership refactor** — DONE. Overflow files deleted (20 weak
   duplicates removed), owner suites created (test_execution_context,
   test_request_flow). Ownership and layering now live in
   `docs/ARCHITECTURE.md`.
2. **Fresh command ownership race** — DONE. `record_and_enqueue()` creates
   items as `claimed` (handler-owned). Worker cannot steal fresh commands.
   `claim_for_update()` recognizes pre-claimed items. `complete_work_item()`
   guards terminal states. 9 integration tests. See `dont_make_false_claims.md`.
3. **Test coverage gaps** (Priority 3) — DONE. 3a: heartbeat vs provider
   liveness. 3b: rate-limit + semantic event preservation (TelegramProgress,
   burst, suppression asserted). 3c: raw provider event regression fixtures
   (tests/fixtures/progress/codex_trace.ndjson, claude_trace.ndjson);
   regression tests in test_progress.py feed traces through mapping/render.
4. **Test isolation and safe parallelization** (Priority 4) — DONE. Audit
   matrix in PLAN. Authoritative reset path in tests/support/handler_support
   (`reset_handler_test_runtime()`); close_all_db / close_all_transport_db;
   conftest autouse fixture; test_handler_runtime_isolation.py; direct
   _bot_instance writes removed (set_bot_instance). Full suite passes under
   `-n 2`, `-n 4`, `-n 8`. Default pytest: `-n 4` in pyproject.toml. Portable
   fd leak test (test_sqlite_integration): Linux + macOS; full suite runs on
   macOS without exclusions.
5. **Small feature gaps** (low effort): `/project` inline keyboard.
   Content-based dedup is demand-gated (only if operators report double-sends).
6. **Architectural hardening** (high effort, conditional): III.7 workflow
   state-machine extraction, verbose/debug progress mode.
7. **Product extensions** (future): multi-worker webhook, usage tracking,
   registry signing, policy/project expansion.

---

## Historical Extension Record: Multi-Worker Webhook Architecture

Historical mapping: this record now corresponds primarily to planned Phases
13-15 in the linear roadmap.

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
| `_db()` leaks file descriptors on schema/corruption errors | Medium | `sqlite3.connect()` opens a connection, but if schema version check or `executescript` raises, the connection is never cached in `_db_connections` or closed. Repeated calls (e.g. `/doctor` retries) accumulate open fds (4→45 after 20 calls). | Wrapped `_db()` initialization in `try/except` that calls `conn.close()` before re-raising. Connection only cached after successful init. Regression test uses portable fd count (Linux `/proc/{pid}/fd`, macOS `/dev/fd`; skips elsewhere). |
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

## Historical Deferred Record (Superseded)

Historical mapping: this record now corresponds primarily to planned Phase 19.

| Item | Notes |
|------|-------|
| Usage tracking & quotas | Needs token-cost mapping, billing integration. Intentionally deferred. |

---

## Historical Workstream: Phase 9 — Structural Refactoring & Invariant Coverage

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
| Shutdown-killed provider showed confusing error to user | Medium-high | rc=-15 from SIGTERM fell through to normal error path: saved partial provider_state, displayed "Claude error (rc=-15)" | `_run_result_was_interrupted` catches all signals (rc < 0), raises `LeaveClaimed` before session save or error display |
| Only SIGTERM/SIGKILL treated as interrupted | Medium | `_run_result_was_interrupted` only checked rc=-15/-9; SIGINT (-2), SIGABRT (-6) etc. still surfaced as provider errors | Changed to `returncode < 0` — any signal is treated as interrupted |
| No global error handler | Medium | Unhandled exceptions (e.g. stale callback `BadRequest`) logged full tracebacks with "No error handlers registered" and user got no feedback | Added `_global_error_handler`: suppresses stale callback queries, logs other exceptions, notifies user |
| Long provider errors shown raw in Telegram | Medium | `execute_request` passed raw error text (up to 3000 chars) directly to user with only `html.escape` | Added `_format_provider_error`: tries haiku summarization for long errors, falls back to head+tail truncation, handles empty output |
| Error summarizer subprocess leaked on timeout | Medium | `_format_provider_error` spawned `claude -p` but `except Exception: pass` never killed or reaped the child on timeout | Added `proc.kill()` + `await proc.wait()` in exception handler when `proc.returncode is None` |
| Decorator exceptions marked work items as "done" | Medium | Both `_command_handler` and `_callback_handler` used `finally: _complete_pending_work_item(uid)` which defaults to `state="done"` | Changed to `except`/`else`: exceptions pass `state="failed"`, clean exits pass `state="done"` |
| Callback with no effective_user leaked queued work item | Medium | `_callback_handler` returned on `event is None` without calling `_complete_pending_work_item` | Added `_complete_pending_work_item(uid)` to the `event is None` branch |

---

## Progress UX Normalization (Layer 1)

Phase III.5 + III.5a from PLAN. Provider-neutral progress wording, heartbeat
for idle states, internal detail suppression.

### What shipped

- **Neutral initial status**: `Working...` / `Resuming...` instead of
  `Starting claude...` / `Starting codex...`
- **Neutral timeout**: `Request timed out after N seconds.` instead of
  `claude timed out...`
- **Neutral terminal status**: `Completed.` instead of `Done.`
- **Neutral approval timeout**: `Approval request timed out.` instead of
  `Preflight approval timed out.`
- **Codex thread/session ID suppression**: `_map_event` returns `None`
  for `thread_started`, `session_meta`, and `session_configured` events.
  Thread IDs go to debug log only.
- **Codex compaction wording**: `Still working — this may take a moment...`
  instead of `Still working — possible context compaction…`
- **Claude thinking capitalized**: `Thinking...` (ASCII dots) instead of
  `thinking…` (unicode ellipsis)
- **Heartbeat task**: shows `Still working... (Ns)` during idle non-content
  states. First beat at 5s, then every 10s. Driven by `asyncio.Event`
  (`content_started`) — providers set it on first real text, heartbeat
  stops firing. Same lifecycle pattern as `keep_typing()`.
- **Neutral approval status**: `Preparing approval...` instead of
  `Preparing preflight approval plan…` (internal "preflight" terminology
  no longer shown to users).
- **FakeProgress consolidated**: single shared definition in
  `tests/support/handler_support.py`, removed duplicates from
  `test_codex_provider.py` and `test_invariants.py`.

### Design decisions

- **No wrapper class**: heartbeat is a sibling background task, not a
  `LiveProgressSink` wrapper. Keeps the `ProgressSink` protocol unchanged.
- **State flag over string matching**: `content_started` is an
  `asyncio.Event`, not a heuristic over `progress.last_text`. Providers
  set it explicitly when first real text arrives.
- **Tapering cadence**: 5s first beat, 10s subsequent. Alive without noisy.
- **`getattr` for backward compatibility**: providers check
  `getattr(progress, "content_started", None)` so they work with any
  `ProgressSink` (including `FakeProgress` in tests).
- **Heartbeat respects recent progress**: heartbeat checks
  `progress.last_update` before firing — if a tool/command update was
  pushed recently, heartbeat waits for the full silence interval before
  overwriting. Prevents heartbeat from replacing fresh tool status.
- **Codex content_started on any visible text**: fires on
  commentary/draft text too (not just final), since draft previews are
  visible to users.
- **Content-first rate-limit bypass**: `TelegramProgress` bypasses the
  rate limiter for the first non-forced update after `content_started`
  is set. Prevents stale tool/heartbeat message remaining on screen
  when the first text update arrives within the rate-limit window.
- **Heartbeat/typing tasks awaited on cancel**: `finally` blocks now
  `await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)`
  so background tasks are fully cleaned up before execution continues.

---

## Restart Recovery and Resume Hardening

### What shipped

**User-intent-owned replay** (`app/work_queue.py`, `app/telegram_handlers.py`, `app/worker.py`)
- `PendingRecovery` exception and `pending_recovery` work-item state.
- `mark_pending_recovery()` transitions claimed → pending_recovery.
- `get_pending_recovery_for_update()` and `get_latest_pending_recovery()` find pending_recovery items (by update or latest in chat).
- `supersede_pending_recovery()` finalizes all pending_recovery as superseded.
- `discard_recovery()` returns bool for race-safe discard.
- `reclaim_for_replay()` with per-chat single-claimed invariant; raises `ReclaimBlocked` when blocked (distinct from returning None when item is gone).
- `worker_dispatch` sends recovery notice with inline keyboard instead of auto-replaying.
- `handle_recovery_callback` processes Replay/Discard buttons, bypasses `_callback_handler`.
- `_chat_lock` supersession gated by `supersede_recovery` parameter — only `handle_message` passes True.
- `worker_loop` catches `PendingRecovery` and skips completion.
- `purge_old` includes `pending_recovery` in deletion.

### Bugs found and fixed

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| Failed recovery-notice delivery moves item to pending_recovery | High | `mark_pending_recovery` ran before `send_message` could fail; exception skipped by `PendingRecovery` catch | Moved `mark_pending_recovery` after send; failed send re-raises so `worker_loop` marks failed |
| Multiple pending_recovery items only newest found | High | `get_pending_recovery` used `LIMIT 1` ignoring update_id from button | Added `update_id` parameter; callback passes specific update_id from button data |
| Discard ignores discard_recovery return value | Medium | Handler discarded without checking race; two concurrent discards could both succeed | Check `discard_recovery` bool; false → "already handled" |
| reclaim_for_replay bypasses per-chat claimed invariant | High | New state-transition helper didn't audit existing invariants on work_items table | Added `BEGIN IMMEDIATE` transaction with claimed check; mirrors `claim_for_update` guard |
| Failed notice delivery marks item done (not failed) | High | Returning normally from worker_dispatch caused worker_loop to mark done | Changed to re-raise; worker_loop's except branch marks failed |
| `_chat_lock` supersedes pending_recovery for all handlers | High | Supersession code ran for every claimed item, not just fresh messages | Added `supersede_recovery` parameter; only `handle_message` passes True |
| Blocked replay path says "already handled" | Medium | `reclaim_for_replay` returned None for both gone and blocked | Added `ReclaimBlocked` exception; handler shows "in progress — try again" for blocked, "already handled" for gone |

---

## Historical Next-Steps Record (Superseded)

Historical mapping: the active roadmap is the Phase 11-19 sequence in
[PLAN-commercial-polish.md](PLAN-commercial-polish.md). The material below is
retained as shipped planning history.

### ~~Near-term: progress UX Layer 2~~ (shipped)

PLAN III.5 Layer 2 — unified progress contract. `app/progress.py`
defines a `ProgressEvent` dataclass family (Thinking, CommandStart,
CommandFinish, ToolStart, ToolFinish, ContentDelta, DraftReply,
Denial, Liveness) and a single `render()` function that owns all
user-facing HTML wording. Both providers now emit events through
`_map_event` (Codex) or inline event construction (Claude) and
delegate rendering to `render_progress()`. No provider builds HTML
strings directly — including the Codex resume-compaction timeout
path, which now emits `Liveness(...)` through the shared renderer.
40 contract tests in `test_progress.py`.

### Plan complete — remaining deferred items

All phases (A–I, IIa/b, III including all sub-items, IV, Ext) and all
hardening work (restart recovery, resume hardening, resolved context
enforcement) are shipped and tested.

**III.7 — Workflow state-machine extraction:** Deferred per plan's
conditional go/no-go rule. Only justified if durable-state bugs continue
to dominate review time. See PLAN III.7 for scope, approach, and tests.

**Product extensions** (per PLAN, legitimate but not blocking):

- Policy and project expansion (richer scoping, granular file policies)
- Registry trust expansion (publisher governance, organizational trust)
- Confidence extensions (concurrency tests, streaming integration,
  real provider smoke tests)
- Usage accounting and billing
