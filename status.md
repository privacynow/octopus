# Architecture Remediation Status

Last updated: 2026-03-18
Repository: `/Users/tinker/output/bots/telegram-agent-bot`
Current branch: `feature/skills`

## Scope

This file tracks execution of the **Reopened Architecture Remediation Track**
in [`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md).

Feature work remains frozen until every acceptance gate in the plan passes.

Historical pre-closure execution notes are preserved below as an audit log,
including intermediate mistakes, reopened gates, and before-state inventories.
The authoritative current closure summary is appended at the end under:

- `## Current Authoritative Status`

## Current State

The remediation track is reopened and not complete.

Post-closure audit originally found four remaining gaps that blocked the
acceptance gates in
[`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md):

1. `G1` has now closed the singleton-runtime gap:
   - Telegram runtime and cancellation ownership are explicit runtime objects,
     not installed module singletons.
2. `G2` has now closed the bootstrap/routing ownership gap:
   - `app/channels/telegram/bootstrap.py` now owns PTB application
     construction and handler registration.
   - `app/channels/telegram/ingress.py` is the live Telegram dispatch owner.
   - `app/channels/telegram/routing.py` is deleted.
3. `G3` has now closed the Telegram harness/test-boundary gap:
   - test setup runs through the real Telegram application builder
   - test support no longer depends on deleted routing or singleton seams
   - structural gates now lock the final Telegram test boundary
4. `status.md` and `docs/orchestration_inventory.md` still need their final
   post-remediation truth pass so they match the actual code ownership and
   test seam state.

Phase 8 is now active.

- Completed Phase 8 slices:
  - `9b8b611` `Phase 8 / H1: extract session_io from ingress`
    - Telegram session/key helpers now live in
      `app/channels/telegram/session_io.py`
    - `app/channels/telegram/ingress.py` no longer defines `_load`, `_save`,
      `_conversation_key`, `_actor_key`, `_event_key`, or `_telegram_chat_id`
    - focused structural gates for the extracted module are in place
    - verified against the full suite: `1620 passed, 23 skipped`
  - `8c12f44` `Phase 8 / H1: extract progress from ingress`
    - Telegram progress lifecycle now lives in
      `app/channels/telegram/progress.py`
    - `app/channels/telegram/ingress.py` no longer defines `TelegramProgress`,
      `_progress_timeline_callback`, `keep_typing`, or `_heartbeat`
    - `tests/test_progress.py`, `tests/test_invariants.py`, and
      `tests/test_runtime_dispatch_boundary.py` now use the extracted public
      progress module owner
    - focused suite: `173 passed`
    - verified against the full suite: `1624 passed, 23 skipped`
  - `62b7569` `Phase 8 / H1: extract delegation channel from ingress`
    - Telegram delegation proposal publication and callback parsing/approval
      flow now live in `app/channels/telegram/delegation_channel.py`
    - no new `surface`-named Telegram owner was introduced in this slice;
      channel-oriented naming is retained
    - `app/channels/telegram/ingress.py` no longer defines delegation proposal,
      callback parsing, or callback-approve/cancel helpers
    - focused suite: `90 passed`
    - verified against the full suite: `1628 passed, 23 skipped`
  - `9594e84` `Phase 8 / H1: extract execution from ingress`
    - Telegram execution, approval, context resolution, send helpers, and
      runtime builders now live in `app/channels/telegram/execution.py`
    - `app/channels/telegram/ingress.py` no longer defines execution/runtime
      builder helpers, prompt-size helpers, context-resolution helpers, or the
      extracted send/approval helpers
    - execution-focused suites: `300 passed`
    - verified against the full suite: `1632 passed, 23 skipped`
  - `ac9fa9e` `Phase 8 / H1: extract worker from ingress`
    - Telegram worker dispatch and action execution now live in
      `app/channels/telegram/worker.py`
    - `app/channels/telegram/bootstrap.py` now wires
      `telegram_worker.worker_dispatch` directly
    - `app/channels/telegram/ingress.py` no longer defines worker dispatch,
      worker action execution, cancel polling, or completion webhook helpers
    - worker-focused suites: `376 passed`
    - verified against the full suite: `1634 passed, 23 skipped`
- Remaining verified-but-uncommitted Phase 8 work in this branch state:
  - `c2b3f33` `Phase 8 / H1: extract shared-mode dispatch from ingress`
    - Telegram shared-runtime command/callback persistence now lives in
      `app/channels/telegram/shared_mode_dispatch.py`
    - this owner is channel-specific, not a repo-wide shared layer
    - `app/channels/telegram/bootstrap.py` now wires shared-mode handlers
      directly from the extracted module
    - `app/channels/telegram/ingress.py` no longer defines shared dispatch,
      shared action-envelope helpers, or worker-owned shared action builders
    - ingress line count after the slice: `1574`
    - shared-runtime and structural suites: `222 passed`
    - verified against the full suite: `1636 passed, 23 skipped`
  - `Phase 8 / H1 final ingress cleanup` is complete in the current branch
    state:
    - concern-owned command routing for `/skills` and `/guidance` now lives in
      `app/channels/telegram/runtime_skills.py` and
      `app/channels/telegram/guidance.py`
    - `app/channels/telegram/ingress.py` is now below the Phase 8 threshold at
      `1483` lines
    - focused suites: `282 passed`
    - verified against the full suite: `1639 passed, 23 skipped`
- Remaining Phase 8 work is still pending:
  - H2 presenter rendering blind-spot closure
  - H3 Telegram test-boundary hardening
  - H4 documentation and structural gate tightening

Feature work remains frozen.

Historical execution log follows below. Some older entries reference the
pre-audit `ingress.py`/`routing.py` closure state and are preserved as history,
not as the current authoritative shape.

Completed slices:

1. `00379be` `Freeze architecture remediation track`
   - Reopened the remediation track in `store_plan.md`.
   - Added Tracks A-F, sequencing, hard rules, and acceptance gates.

2. `bc68795` `Track A / A3: normalize access boundary`
   - `app/access.py` no longer imports Telegram normalization.
   - Access helpers now require `InboundUser`.
   - Telegram normalization happens at the channel edge.

3. `8ed47b0` `Track A / A4: move trust tier routing to work admission`
   - `trust_tier_for_source` moved out of `app/runtime/composition.py`.
   - Callers now use `app/runtime/work_admission.py`.

4. `5bd3a8f` `Track A / A1: extract telegram channel state`
   - Added explicit Telegram channel state and cancellation owners:
     - `app/channels/telegram/state.py`
     - `app/channels/telegram/cancellation.py`
   - Removed Telegram ingress-owned `_config`, `_provider`, `_bot_instance`,
     `_boot_id`, `_LIVE_CANCEL`, `_cfg()`, and `_prov()` as the previous state
     hub.
   - Test support moved off ingress globals.

5. `23fe4dc` `Track A / A2: detach telegram conversation slice from ingress`
   - `app/channels/telegram/conversation.py` no longer imports Telegram ingress.
   - Conversation handling now runs through explicit injected runtime
     collaborators from `app/channels/telegram/ingress.py`.

6. `26ed78c` `Track A / A2: detach telegram runtime skill slice from ingress`
   - `app/channels/telegram/runtime_skills.py` no longer imports Telegram ingress.
   - Runtime-skill channel logic now runs through explicit
     `TelegramRuntimeSkillsRuntime` injection and stable owners for
     auth/identity/session/work-queue helpers.
   - ingress now passes explicit runtime-skills collaborators instead of
     being imported as the hidden owner.

7. `1213a6e` `Track A / A2: detach telegram pending slice from ingress`
   - `app/channels/telegram/pending.py` no longer imports Telegram ingress.
   - Pending approval / retry / recovery handling now runs through explicit
     `TelegramPendingRuntime` injection.
   - ingress now passes pending/recovery collaborators explicitly instead of
     being imported as the hidden owner.

8. `4e672a3` `Track A / A2: detach runtime dispatch slice from ingress`
   - `app/runtime/dispatch.py` no longer imports Telegram channel modules.
   - Request execution and approval plumbing now run through explicit
     `RuntimeDispatchRuntime` injection from Telegram ingress.
   - `RequestExecutionOutcome` ownership moved into the runtime boundary
     instead of being defined inside Telegram ingress.
   - Added focused positive and negative tests for the dispatch boundary and
     the new import-direction gate.

9. `531856c` `Track A / A2: detach agents delivery slice from ingress`
   - `app/agents/delivery.py` no longer imports Telegram ingress or Telegram
     channel state.
   - Registry delivery handling now runs through explicit
     `RegistryDeliveryRuntime` injection for provider/session defaults and bot
     access when a Telegram parent conversation actually needs egress.
   - Main/runtime and test call sites now pass the explicit delivery runtime,
     and a negative gate now proves the agents delivery module has no channel
     imports.

10. `2f8a303` `Track A / A2: detach agents delegation slice from ingress`
   - `app/agents/delegation.py` no longer imports Telegram ingress or Telegram
     channel state.
   - Delegation approve/cancel flows now run through explicit
     `DelegationRuntime` injection from Telegram ingress.
   - Added direct delegation-boundary tests and a negative gate proving the
     delegation module has no channel imports.

11. `8a6b656` `Track A / A5: finish test support migration and global-state cleanup`
   - Test support now has explicit positive and negative coverage proving
     `setup_globals()` installs Telegram channel state through the new state
     owner rather than restoring deleted ingress globals.
   - Added a guard that `tests/support/handler_support.py` does not mutate
     legacy ingress globals or call deleted ingress global accessors.

12. `57fd205` `Track C / C1: move registry UI shell rendering into ui.py`
   - The large `/ui` shell HTML/CSS/JS block now lives in
     `app/channels/registry/ui.py` instead of `app/channels/registry/http.py`.
   - Added a focused shell-render helper test and a structural guard proving
     `http.py` stays below the line-count threshold and no longer embeds the
     large UI shell markup.

13. `31db8ed` `Track C / C2: move registry auth and session helpers out of http`
   - Added `app/channels/registry/auth.py` as the registry channel owner for:
     - `RegistrySettings`
     - session middleware configuration
     - bearer-token auth helpers
     - UI-session validation/login/logout helpers
   - `app/channels/registry/http.py` now imports these helpers instead of
     defining them inline.
   - Added focused positive coverage for the new auth owner and a negative
     structural guard proving `http.py` no longer defines the displaced auth
     and session helpers.

14. `eb071e7` `Track D / D1: centralize lifecycle snapshot construction`
   - Added `build_lifecycle_snapshot(...)` to
     `app/workflows/lifecycle_machine.py` as the single owner of lifecycle
     snapshot construction.
   - Runtime-skill authoring, runtime-skill approval, and provider-guidance
     management now consume the shared builder instead of maintaining local
     `_snapshot()` helpers.
   - Added focused positive helper coverage and a negative structural guard
     proving the duplicate runtime-skill `_snapshot()` helpers are gone.

15. `c19abfd` `Track D / D2: add explicit latest-approval store queries`
   - Added explicit content-store contract methods for latest approval lookup:
     - `get_latest_skill_approval_action(...)`
     - `get_latest_provider_guidance_approval_action(...)`
   - Implemented both methods in SQLite and Postgres with explicit
     `ORDER BY ... DESC LIMIT 1` queries instead of relying on workflow-level
     Python scans.
   - Added parameterized contract coverage for:
     - newest matching action is returned
     - missing revisions return an empty string

16. `ce3b6ef` `Track D / D3: remove private cross-workflow latest-action access`
   - Runtime-skill authoring now uses the explicit store query directly for
     lifecycle snapshot construction.
   - Runtime-skill approval no longer reaches into authoring’s private helper;
     it consumes the explicit store contract instead.
   - Provider-guidance management now also consumes the explicit latest-approval
     store query instead of scanning approval history in-process.
   - Added a structural guard proving the removed private/helper paths no longer
     exist in the workflow modules.

17. `2ee0b77` `Track F / F1: commit orchestration inventory`
   - Added `docs/orchestration_inventory.md` as the committed inventory of the
     durable and semi-durable orchestration concerns named by the plan.
   - Classified lifecycle, pending approval/retry, transport recovery,
     credential/setup progression, delegation progression, and request
     execution/preflight using the fixed F1 vocabulary.
   - Added guard tests proving the inventory names the required live modules and
     does not leave placeholder or unclassified entries behind.

18. `f274448` `Track F / F2: commit machine conventions standard`
   - Added `docs/machine_conventions.md` as the repo-standard functional
     decision-machine contract for future machine migrations.
   - Declared the standard shape:
     - snapshot
     - action
     - decision
     - effects
     - atomic application at the store/session boundary
   - Explicitly marked existing `python-statemachine` machines as
     migration-state only and disallowed any third machine style.
   - Added guard tests proving the standard document includes the required
     shape, migration-state rule, and anti-drift constraints.

19. `3ce052e` `Track F / F3: extract the runtime-skill setup machine`
   - Added `app/workflows/runtime_skills/setup_machine.py` as the single
     setup-transition owner for:
     - start
     - foreign-setup inspection
     - cancel
     - advance
     - clear-on-credential-removal
   - Deleted `app/skill_lifecycle_service.py`.
   - Reduced `app/credential_flow.py` to rendering helpers only.
   - Moved `apply_cleared_credentials(...)` onto the runtime-skill setup port.
   - Updated activation and setup workflows to consume the machine and apply
     its effects at the workflow boundary.
   - Added positive and negative coverage proving:
     - stale foreign setup can be replaced
     - active foreign setup blocks new setup
     - the legacy service path is gone
     - `app/workflows/runtime_skills/setup.py` is the only app owner writing
       `session.awaiting_skill_setup`

20. `128bf67` `Track F / F4: move delegation into concern-owned workflows`
   - Added the real delegation workflow package:
     - `app/workflows/delegation/contracts.py`
     - `app/workflows/delegation/machine.py`
     - `app/workflows/delegation/coordination.py`
   - Deleted `app/agents/orchestration.py`.
   - Moved plan creation, task progression, routed-result application,
     resume-readiness, completion-summary building, and post-resume clearing
     into the workflow package.
   - Reduced `app/agents/delegation.py` and `app/agents/delivery.py` to thin
     bridge adapters over the workflow package.
   - Moved Telegram ingress delegation plan creation/finalize-resume behavior
     to the workflow owner.
   - Added:
     - delegation machine tests
     - updated workflow tests
     - negative gates proving the deleted owner path is gone and `app/agents/*`
       no longer edits delegation status strings directly

21. `845aed3` `Track F / F5: migrate pending and recovery to concern-owned functional machines`
   - Before-state inventory captured before editing:
     - `app/workflows/pending_request.py`
       - still owns the pending approval/retry machine
       - still uses `python-statemachine`
       - still exports:
         - `PendingRequestMachine`
         - `PendingRequestWorkflowModel`
         - `PendingRequestDisposition`
         - `PendingRequestTransitionResult`
         - `run_pending_request_event(...)`
     - `app/workflows/transport_recovery.py`
       - still owns the transport/recovery machine
       - still uses `python-statemachine`
       - still exports:
         - `TransportRecoveryMachine`
         - `TransportWorkflowModel`
         - `TRANSPORT_STATES`
         - `run_transport_event(...)`
     - `app/workflows/results.py`
       - still holds transport/recovery transition result types and domain
         exceptions under a root transitional owner
     - `app/transport_contract.py`
       - still sits at app root
       - still imports `TRANSPORT_STATES` from the root transport workflow
   - Current caller inventory captured by `rg` before editing:
     - pending owner:
       - `app/workflows/pending/requests.py`
       - `tests/test_pending_request_workflow_machine.py`
       - `app/workflows/__init__.py`
     - recovery/result owner:
       - `app/work_queue_sqlite_impl.py`
       - `app/work_queue_postgres_impl.py`
       - `app/worker.py`
       - `app/workflows/recovery/replay.py`
       - `app/channels/telegram/ingress.py`
       - `tests/test_transport_workflow_machine.py`
       - `tests/test_work_queue.py`
       - `tests/test_contracts/test_transport_store_contract.py`
       - `tests/support/handler_support.py`
       - `app/workflows/__init__.py`
     - transport contract owner:
       - `app/work_queue.py`
       - `app/work_queue_sqlite.py`
       - `app/work_queue_postgres.py`
       - `app/work_queue_sqlite_impl.py`
       - `app/work_queue_postgres_impl.py`
       - `tests/contracts/test_transport_store_contract.py`
   - Contract tests that currently define the accepted behavior:
     - `tests/test_pending_request_workflow_machine.py`
     - `tests/test_transport_workflow_machine.py`
     - `tests/test_work_queue.py`
     - `tests/contracts/test_transport_store_contract.py`
     - `tests/test_workitem_integration.py`
     - `tests/test_invariants.py`
   - Required after-state for F5:
     - `app/workflows/pending/machine.py` becomes the only pending machine owner
     - `app/workflows/recovery/machine.py` becomes the only recovery machine owner
     - `app/workflows/recovery/results.py` owns recovery result and exception types
     - `app/workflows/recovery/transport_contract.py` owns recovery contract types
     - old root paths are deleted, not aliased
     - no production pending/recovery path remains on `python-statemachine`
   - Completed implementation in the current worktree:
     - added:
       - `app/workflows/pending/machine.py`
       - `app/workflows/recovery/machine.py`
       - `app/workflows/recovery/results.py`
       - `app/workflows/recovery/transport_contract.py`
     - deleted:
       - `app/workflows/pending_request.py`
       - `app/workflows/transport_recovery.py`
       - `app/workflows/results.py`
       - `app/transport_contract.py`
     - updated app callers:
       - `app/workflows/pending/requests.py`
       - `app/workflows/recovery/replay.py`
       - `app/workflows/__init__.py`
       - `app/work_queue.py`
       - `app/work_queue_sqlite.py`
       - `app/work_queue_postgres.py`
       - `app/work_queue_sqlite_impl.py`
       - `app/work_queue_postgres_impl.py`
       - `app/channels/telegram/ingress.py`
       - `app/worker.py`
     - updated machine and boundary tests:
       - `tests/test_pending_request_workflow_machine.py`
       - `tests/test_transport_workflow_machine.py`
       - `tests/test_work_queue.py`
       - `tests/contracts/test_transport_store_contract.py`
       - `tests/support/handler_support.py`
       - `tests/test_architecture_skeleton.py`
       - `tests/test_zero_import_gates.py`
     - updated machine/inventory docs:
       - `docs/machine_conventions.md`
       - `docs/orchestration_inventory.md`
   - Verification completed before commit:
     - focused F5 suite:
       - `254 passed`
     - full suite:
       - `1547 passed, 23 skipped`

22. `c5bbcdc` `Track F / F6: enforce runtime dispatch ownership`
   - Before-state inventory captured before editing:
     - `app/runtime/dispatch.py`
       - still owned:
         - `RequestExecutionOutcome`
         - `check_prompt_size_cross_chat(...)`
         - `prompt_weight(...)`
         - `check_credential_satisfaction(...)`
         - `execute_request(...)`
         - `request_approval(...)`
       - still mixed:
         - runtime provider-call plumbing
         - request/preflight workflow decisions
         - session mutation
         - progress/reply branching
         - Telegram-specific keyboard construction
   - Required after-state for F6:
     - `app/runtime/dispatch.py` remains only provider-run plumbing
     - execution/preflight orchestration moves to a concern-owned workflow
       package under `app/workflows/execution/*`
     - Telegram-specific rendering and prompt/keyboard decisions leave
       `app/runtime/dispatch.py` in the same slice
     - `runtime/*` remains free of channel imports and Telegram-library
       rendering objects
   - Completed implementation in the current worktree:
     - `app/runtime/dispatch.py` now owns only:
       - `RuntimeDispatchRuntime`
       - `ProviderDispatchOutcome`
       - `run_provider_request(...)`
       - `run_provider_preflight(...)`
     - added concern-owned execution workflow package:
       - `app/workflows/execution/__init__.py`
       - `app/workflows/execution/contracts.py`
       - `app/workflows/execution/requests.py`
     - moved execution/preflight ownership out of runtime and into
       `app/workflows/execution/requests.py`:
       - `RequestExecutionOutcome`
       - `check_prompt_size_cross_chat(...)`
       - `prompt_weight(...)`
       - `check_credential_satisfaction(...)`
       - `execute_request(...)`
       - `request_approval(...)`
     - updated ingress to consume the execution workflow owner and provide
       explicit execution runtime collaborators instead of treating
       `app/runtime/dispatch.py` as a mixed workflow/runtime module
     - updated focused boundary tests:
       - `tests/test_runtime_dispatch_boundary.py`
       - `tests/test_architecture_skeleton.py`
       - `tests/test_zero_import_gates.py`
   - Verification completed before commit:
     - focused F6 suite:
       - `66 passed`
     - full suite:
       - `1550 passed, 23 skipped`

23. `7a39e96` `Track E / E1-E4: finalize dead ownership cleanup and test gates`
   - Before-state inventory captured before editing:
     - `app/workflows/__init__.py`
       - already reduced to a package docstring
       - needed an explicit structural guard so it cannot regress into root
         transitional re-exports
     - `app/workflows/recovery/transport_contract.py`
       - already owned the recovery transport contract
       - needed explicit positive coverage so the cleaned owner and deleted
         root path are both locked in
     - `tests/test_zero_import_gates.py`
       - still scanned only `app/`
       - did not yet scan `tests/` for forbidden deleted-module references
     - stale transport-era test filenames still present:
       - `tests/test_transports_factory.py`
       - `tests/test_transports_telegram.py`
   - Completed implementation in the current worktree:
     - expanded `tests/test_zero_import_gates.py` to:
       - scan both `app/` and `tests/` for deleted legacy module references
       - assert `app/workflows/__init__.py` stays free of transitional
         re-exports and temporary language
       - assert the concern-owned recovery transport-contract file exists
       - assert the stale transport-era test filenames are gone
     - deleted stale transport-era test files:
       - `tests/test_transports_factory.py`
       - `tests/test_transports_telegram.py`
     - added channel-owned replacements:
       - `tests/test_channel_egress_factory.py`
       - `tests/test_telegram_channel_egress.py`
   - Verification completed before commit:
     - focused Track E suite:
       - `24 passed`
     - full suite:
       - `1554 passed, 23 skipped`

24. `602f5c1` `Track B / B1: centralize Telegram reply-markup builders`
   - Before-state inventory captured before editing:
     - `app/channels/telegram/ingress.py`
       - still built retry/approval/delegation/expand-collapse keyboards inline
       - still carried dead `_settings_*_buttons()` helpers with no callers
     - `app/channels/telegram/conversation.py`
       - still built all settings keyboards inline
     - `app/channels/telegram/runtime_skills.py`
       - still built the skill-add confirmation keyboard inline
       - still built the clear-credentials confirmation keyboard inline
     - `app/channels/telegram/presenters.py`
       - still only owned `extract_summary(...)`
   - Completed implementation in the current worktree:
     - `app/channels/telegram/presenters.py` now owns:
       - shared `TelegramRenderedMessage`
       - approval/retry prompt rendering
       - delegation/expand-collapse reply-markup builders
       - conversation settings reply-markup builders
       - runtime-skill confirmation reply-markup builders
     - removed `InlineKeyboardButton` / `InlineKeyboardMarkup` construction from:
       - `app/channels/telegram/ingress.py`
       - `app/channels/telegram/conversation.py`
       - `app/channels/telegram/runtime_skills.py`
     - deleted dead inline settings-button helpers from Telegram ingress
     - added focused presenter unit/regression coverage in:
       - `tests/test_telegram_presenters.py`
       - `tests/test_zero_import_gates.py`
     - rewrote stale settings-button tests to assert the presenter owner
       instead of deleted ingress internals
   - Verification completed before commit:
     - focused Track B1 suite:
       - `314 passed`
     - full suite:
       - `1562 passed, 23 skipped`

## Latest Verified Test Baseline

At the end of the latest completed slice:

- full suite passed
- result: `1632 passed, 23 skipped`

This baseline must be re-established after every subsequent slice before
committing.

## Track Progress

### Track A. Fix the Inbound Context Problem

Status: complete

Completed:

- `A3` remove Telegram normalization from `app/access.py`
- `A4` move `trust_tier_for_source`
- `A1` extract explicit Telegram state/cancellation owners
- `A2` conversation concern slice
- `A2` runtime skills concern slice
- `A2` pending concern slice
- `A2` runtime dispatch concern slice
- `A2` agents delivery concern slice
- `A2` agents delegation concern slice
- `A5` finish test support migration and remove any remaining global-state test coupling

Remaining:
- none

### Track B. Build the Telegram Presenter Layer

Status: complete

Required scope:

- move Telegram rendering from:
  - `app/channels/telegram/ingress.py`
  - `app/channels/telegram/conversation.py`
  - `app/channels/telegram/runtime_skills.py`
  - `app/channels/telegram/pending.py`
  - `app/channels/telegram/guidance.py`
- into:
  - `app/channels/telegram/presenters.py`

Completed and committed:

- `B1` centralized the scoped Telegram reply-markup builders in
  `app/channels/telegram/presenters.py`
- `B2a` moved provider-guidance Telegram rendering into presenters
- `B2b` moved runtime-skill Telegram rendering into presenters
- `B2c1` moved conversation and pending Telegram rendering into presenters
- `B2c2a` moved ingress request/setup/compact/delegation/raw/welcome rendering
  into presenters
- `B2c2b` moved the remaining ingress help/session/discover/admin/reporting
  rendering into presenters

Remaining:

- none

### Track C. Decompose Registry HTTP and UI

Status: complete

Completed:

- `C1` move large `/ui` shell HTML/CSS/JS rendering into `app/channels/registry/ui.py`
- `C2` move displaced registry auth/session helpers to `app/channels/registry/auth.py`

Verified outcomes:

- `app/channels/registry/http.py` is reduced to route registration,
  request parsing/validation, HTTP-boundary auth/session checks, ingress calls,
  and response mapping
- `app/channels/registry/ui.py` owns the large registry browser shell rendering
- `app/channels/registry/auth.py` owns reusable registry auth/session helpers

Remaining:

- none

### Track D. Lifecycle and Workflow Hygiene Cleanup

Status: complete

Required scope:

- deduplicate lifecycle snapshot construction
- add explicit latest-approval store methods
- remove private cross-class lifecycle helper access

Completed:

- `D1` move shared lifecycle snapshot construction into `app/workflows/lifecycle_machine.py`
- `D2` add explicit latest-approval store methods with SQLite/Postgres parity
- `D3` remove private cross-class latest-action helper access

Remaining:

- none

### Track E. Dead Code, Naming, and Test-Gate Cleanup

Status: complete

Required scope:

- remove dead root re-exports after F5
- confirm `transport_contract.py` relocation after F5
- expand zero-import gates to `tests/`
- rename stale transport-era tests

Completed in the current worktree:

- `E1` locked down `app/workflows/__init__.py` as a clean package root with
  focused structural guards
- `E2` locked down `app/workflows/recovery/transport_contract.py` as the
  concern-owned recovery transport contract
- `E3` expanded zero-import gates to scan both `app/` and `tests/`
- `E4` deleted stale transport-era test file names and replaced them with
  channel-owned test file names

Verified outcome:

- focused Track E suite passed: `24 passed`
- full suite passed: `1554 passed, 23 skipped`

### Track F. Orchestration and State-Machine Consolidation

Status: complete

Required scope:

- `F1` committed orchestration inventory
- `F2` repo-standard functional decision-machine conventions
- `F3` runtime skill setup machine
- `F4` delegation machine/workflow
- `F5` pending/recovery migration off `python-statemachine`
- `F6` dispatch ownership cleanup

Completed:

- `F1` committed orchestration inventory in `docs/orchestration_inventory.md`
- `F2` committed the repo-standard functional decision-machine conventions
- `F3` runtime-skill setup machine with deleted legacy setup service
- `F4` delegation workflow/machine with thin bridge adapters in `app/agents/*`
- `F5` pending/recovery migration off `python-statemachine`
- `F6` dispatch ownership cleanup

Remaining:

- none

## Acceptance Gate Checklist

These gates are copied from the active plan and tracked here with current
status.

- [x] No app module outside Telegram ingress imports Telegram ingress.
- [x] Telegram channel runtime state is explicit and no longer
  global-module-owned.
- [x] `runtime/*` has no channel imports.
- [x] `agents/*` has no channel imports.
- [x] `access.py` has no channel imports.
- [x] Telegram presenters own Telegram rendering.
- [x] Registry `http.py` is a thin HTTP boundary and `ui.py` owns UI rendering.
- [x] Setup progression has one explicit machine owner.
- [x] Delegation progression has one explicit workflow/machine owner.
- [x] Pending and recovery machines live under concern-owned workflow packages.
- [x] `runtime/dispatch.py` is channel-agnostic plumbing and not a shadow
  workflow owner.
- [x] The repo-standard explicit machine style is declared and used for
  remediated durable workflows.
- [x] Lifecycle snapshot and latest-approval ownership are cleaned up.
- [x] `workflows/__init__.py` and `transport_contract.py` no longer carry
  dead or misleading transitional ownership.
- [x] Zero-import gates cover both `app/` and `tests/`.
- [x] Test support no longer mutates Telegram ingress globals.

## Current Slice

Active slice:

- `G4` repair documentation and final structural gates

Just completed:

- `bf86331` `Phase 7 / G1: replace singleton Telegram runtime ownership`
  - replaced singleton Telegram runtime ownership with explicit
  bootstrap-owned runtime
  - `app/channels/telegram/state.py` now defines the explicit
    `TelegramRuntime` owner and `build_telegram_runtime(...)`
  - `app/channels/telegram/cancellation.py` now defines only the explicit
    cancellation registry type
  - `app/channels/telegram/bootstrap.py` now constructs the runtime, PTB
    application, and bound worker dispatch instead of re-exporting routing
  - `app/main.py` now consumes the bootstrap result rather than peeking
    installed singleton state
  - `app/channels/telegram/routing.py` now receives runtime explicitly through
    bootstrap/context wiring instead of singleton install/get helpers
  - `tests/support/handler_support.py` now constructs and injects an explicit
    Telegram runtime instead of restoring singleton state
  - focused G1 suites passed
  - full suite passed: `1608 passed, 23 skipped`

Before-state for `G4`:

- `4166599` `Phase 7 / G2: restore Telegram bootstrap and ingress ownership`
  - `app/channels/telegram/bootstrap.py` now owns PTB application
    construction and handler registration directly
  - `app/channels/telegram/ingress.py` is now the live Telegram ingress owner
    for normalized event translation, shared dispatch, and worker dispatch
  - `app/channels/telegram/routing.py` is deleted with no compatibility alias
  - app and test imports were rewritten off the deleted routing module
  - focused G2 suites passed
  - full suite passed: `1608 passed, 23 skipped`

- `complete in current worktree` `Phase 7 / G3: finish Telegram test-boundary migration`
  - `tests/support/handler_support.py` now runs test setup through the real
    Telegram application builder instead of constructing an out-of-band runtime
    shape
  - Telegram harness tests still use explicit runtime state, but the runtime is
    now wired through the same bootstrap application path production uses
  - zero-import gates now explicitly lock out routing references and legacy
    singleton accessors from the Telegram harness
  - focused G3 suites passed
  - full suite passed: `1608 passed, 23 skipped`

Current documentation/gate inventory for `G4`:

- production boundary is now:
  - `app/channels/telegram/bootstrap.py`
  - `app/channels/telegram/ingress.py`
- docs still needing the final truth pass:
  - `status.md`
  - `docs/orchestration_inventory.md`
- structural gates still to add/finish under G4:
  - bootstrap is not a re-export shim
  - final bootstrap/ingress ownership split is asserted positively
  - documentation names only live owners and live paths

Required after-state for `G4`:

- `status.md` truthfully reflects the current committed architecture and gates
- `docs/orchestration_inventory.md` names only the actual current owners
- structural gates catch the regressions that escaped the first closure:
  - singleton Telegram runtime authority
  - deleted routing imports
  - stale documentation ownership
  - bootstrap regressing back into a shim

Committed Track B slices after `B1`:

25. `f13dbd1` `Track B / B2a: move provider-guidance Telegram rendering into presenters`
   - `app/channels/telegram/guidance.py` now applies named presenter functions
     for preview, history, and lifecycle mutation output.
   - Focused verification passed: `46 passed`
   - Full suite passed: `1567 passed, 23 skipped`

26. `cb6b191` `Track B / B2b: move runtime-skill Telegram rendering into presenters`
   - `app/channels/telegram/runtime_skills.py` now applies presenter output
     for catalog, setup, lifecycle, import/update/diff, and clear-credential
     flows.
   - Focused verification passed: `96 passed`
   - Full suite passed: `1573 passed, 23 skipped`

27. `6e6de74` `Track B / B2c1: move telegram conversation and pending presenters`
   - `app/channels/telegram/conversation.py` and
     `app/channels/telegram/pending.py` now apply presenter output instead of
     owning inline status and callback text.
   - Focused verification passed: `103 passed`
   - Full suite passed: `1583 passed, 23 skipped`

28. `0057e1c` `Track B / B2c2a: move ingress request rendering into presenters`
   - `app/channels/telegram/ingress.py` now applies presenter output for setup,
     formatted replies, compact/full replies, delegation plans, `/raw`, and
     welcome output.
   - Focused verification passed: `118 passed`
   - Full suite passed: `1592 passed, 23 skipped`

29. `65843b1` `Track B / B2c2b: move ingress help rendering into presenters`
   - `app/channels/telegram/presenters.py` now owns the remaining help/session/
     discover/admin/access/usage rendering that previously lived in the
     Telegram entrypoint owner.
   - Focused verification passed: `277 passed`
   - Full suite passed: `1603 passed, 23 skipped`

Worktree now in progress for final acceptance closure:

30. `complete in current worktree` `Final acceptance audit and closure`
   - deleted the old Telegram entrypoint path:
     - `app/channels/telegram/ingress.py`
   - moved the Telegram routing owner to:
     - `app/channels/telegram/routing.py`
   - kept Telegram boot wiring under:
     - `app/channels/telegram/bootstrap.py`
   - moved the concrete outbound egress factory out of `runtime/*` and into:
     - `app/channel_egress_factory.py`
   - `app/runtime/composition.py` is now channel-agnostic and no longer
     imports concrete channel packages
   - app and test imports were rewritten away from the deleted Telegram
     ingress path
   - structural tests now prove:
     - the old Telegram ingress path is gone
     - `runtime/*`, `agents/*`, and `access.py` have no channel imports
     - the Telegram routing owner remains presenter-owned for rendering
   - focused closure verification passed:
     - `246 passed`
   - final full-suite verification passed:
     - `1605 passed, 23 skipped`

## Remaining Work

- Phase 7. Closure Correction Stage
  - `G4` repair status/inventory docs and strengthen structural gates to catch
    the regressions that escaped the previous closure

Acceptance remains blocked until the reopened Phase 7 gates pass.
     - negative structural guards proving inline rendering is gone from both
       channel modules
   - focused verification passed:
     - `204 passed`
   - full suite passed:
     - `1579 passed, 23 skipped`

Before-state for `Track B / B2c2`:

- files expected after `B2c1`:
  - `app/channels/telegram/ingress.py`
  - `app/channels/telegram/presenters.py`
  - `tests/test_telegram_presenters.py`
  - `tests/test_handlers_output.py`
  - `tests/test_request_flow.py`
  - `tests/test_zero_import_gates.py`
- current caller and owner inventory:
  - `ingress.py` will still own compact/full-answer rendering, setup prompts,
    delegation-plan formatting, and help/session/discover/admin text
- after-state required by this slice:
  - remaining Telegram ingress rendering lives in
    `app/channels/telegram/presenters.py`
  - `ingress.py` becomes orchestration plus PTB wiring only
  - focused regression coverage proves ingress uses presenters for the remaining
    rendered outputs
  - negative structural guards prove the removed inline formatting is gone

Before-state for `Track B / B2c2a`:

- files that will change:
  - `app/channels/telegram/ingress.py`
  - `app/channels/telegram/presenters.py`
  - `tests/test_telegram_presenters.py`
  - `tests/test_handlers_output.py`
  - `tests/test_request_flow.py`
  - `tests/test_zero_import_gates.py`
- current caller and owner inventory:
  - `ingress.py` still owns setup prompts and foreign-setup notices
  - `ingress.py` still owns compact/full-answer formatting and chunking
  - `ingress.py` still owns delegation-plan message formatting
  - `ingress.py` still owns welcome/path-error/raw command output text
- after-state required by this slice:
  - these request/setup/delegation/compact rendering paths move to presenters
  - ingress becomes orchestration only for these flows
  - focused regression coverage proves ingress calls presenters for them
  - negative structural guards prove the moved inline formatting is gone

Before-state for `Track B / B2c2b`:

- files expected after `B2c2a`:
  - `app/channels/telegram/ingress.py`
  - `app/channels/telegram/presenters.py`
  - `tests/test_telegram_presenters.py`
  - `tests/test_handlers.py`
  - `tests/test_handlers_output.py`
  - `tests/test_zero_import_gates.py`
- current caller and owner inventory:
  - `ingress.py` will still own help/session/discover/admin/reporting text
- after-state required by this slice:
  - remaining help/session/discover/admin/reporting rendering moves to
    `presenters.py`
  - `ingress.py` becomes orchestration and PTB wiring only
  - final acceptance audit follows immediately after this slice

Next required slice:

- `Track B / B2c2b: move ingress help/session/discover/admin/reporting rendering into presenters.py`

Completed in `Track B / B2c1`:

- `app/channels/telegram/conversation.py` no longer imports
  `app.credential_flow` or owns inline HTML formatting
- `app/channels/telegram/pending.py` no longer owns `ParseMode` or recovery
  reply formatting
- remaining Telegram rendering debt is now isolated to `app/channels/telegram/ingress.py`

Completed in `F6`:

- `app/runtime/dispatch.py` now contains only channel-agnostic provider-call
  plumbing
- `app/workflows/execution/*` now owns request/preflight workflow logic
- Telegram ingress now consumes explicit execution runtime collaborators instead
  of treating runtime dispatch as a workflow owner
- focused verification passed:
  - `66 passed`
- full suite passed:
  - `1550 passed, 23 skipped`

## Working Rules

For every remaining slice:

1. update this file before and after the slice
2. inventory callers with `rg`
3. make the change
4. update all imports/callers
5. delete old ownership paths when replaced
6. write positive and negative tests
7. run the full test suite
8. commit one logical slice

No compatibility shims.
No partial ownership moves.
No feature work.

## Current Authoritative Status

Last updated: 2026-03-18
Repository: `/Users/tinker/output/bots/telegram-agent-bot`
Current branch: `feature/skills`

### Scope

This section is the current closure artifact for the architecture remediation
work defined in
[`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md).

Historical pre-Phase-7 execution details remain above as audit history. This
section tracks the final accepted ownership model and the last remediation
verification baseline.

### Current State

Phase 7 closure correction is complete.

Tracks A through F had already landed. Phase 7 reopened the remediation after a
post-closure audit found four escaped regressions:

1. Telegram runtime state still had singleton/module-global authority.
2. Telegram bootstrap and ingress ownership were still collapsed into a renamed
   monolith.
3. Telegram-heavy tests still depended on transitional routing/runtime seams.
4. `status.md` and `docs/orchestration_inventory.md` no longer matched the real
   code ownership.

Those regressions are now closed. The current live Telegram boundary is:

- `app/channels/telegram/bootstrap.py`
- `app/channels/telegram/ingress.py`

The current committed orchestration inventory lives in:

- `docs/orchestration_inventory.md`

The repo-standard explicit machine contract lives in:

- `docs/machine_conventions.md`

Feature work may resume.

### Phase 7 Slice Log

1. `bf86331` `Phase 7 / G1: replace singleton Telegram runtime ownership`
   - replaced singleton runtime/cancellation ownership with explicit
     bootstrap-owned `TelegramRuntime`
   - removed singleton install/get/reset helpers and deleted module-global
     Telegram runtime authority
   - moved Telegram-heavy test setup to explicit runtime construction

2. `4166599` `Phase 7 / G2: restore Telegram bootstrap and ingress ownership`
   - made `app/channels/telegram/bootstrap.py` the real PTB application and
     route-registration owner
   - restored `app/channels/telegram/ingress.py` as the live normalized-event
     and worker-dispatch owner
   - deleted `app/channels/telegram/routing.py`

3. `0c01b70` `Phase 7 / G3: finish Telegram test-boundary migration`
   - rewrote Telegram-heavy test setup around explicit runtime/bootstrap wiring
   - removed direct dependence on deleted routing and singleton seams
   - tightened Telegram test-boundary structural gates

4. `78051ae` `Phase 7 / G4: repair documentation and structural gates`
   - updated `docs/orchestration_inventory.md` to reflect the actual current
     delegation and execution owners
   - added final Telegram bootstrap/ingress split gates
   - tightened documentation-owner checks so the escaped closure regressions are
     covered by tests

### Acceptance Gates

These mirror the authoritative
`Architecture Remediation Acceptance Gates` in
[`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md).

- [x] No app module outside Telegram ingress imports Telegram ingress.
- [x] Telegram channel runtime state is explicit and instance-owned, not
  singleton or global-module-owned.
- [x] `runtime/*` has no channel imports.
- [x] `agents/*` has no channel imports.
- [x] `access.py` has no channel imports.
- [x] Telegram presenters own Telegram rendering.
- [x] Registry `http.py` is a thin HTTP boundary and `ui.py` owns UI rendering.
- [x] Setup progression has one explicit machine owner.
- [x] Delegation progression has one explicit workflow/machine owner.
- [x] Pending and recovery machines live under concern-owned workflow packages.
- [x] `runtime/dispatch.py` has explicit non-channel ownership and is not a
  shadow workflow owner.
- [x] The repo-standard explicit machine style is declared and used for
  remediated durable workflows.
- [x] Lifecycle snapshot and latest-approval ownership are cleaned up.
- [x] `workflows/__init__.py` and `transport_contract.py` no longer carry dead
  or misleading transitional ownership.
- [x] Zero-import gates cover both `app/` and `tests/`.
- [x] Test support no longer mutates Telegram ingress globals.
- [x] Telegram bootstrap owns PTB application construction and route
  registration; Telegram ingress owns normalized event translation and dispatch
  only.
- [x] Telegram-heavy tests exercise the Telegram boundary through explicit
  runtime setup rather than routing-module internals or singleton mutable
  state.
- [x] `status.md` and `docs/orchestration_inventory.md` reflect the actual
  current code ownership and were updated only after code/tests proved the
  state.

### Verification Baseline

Latest focused G4 structural suite:

- `tests/test_orchestration_inventory.py`
- `tests/test_status_doc.py`
- `tests/test_zero_import_gates.py`
- `tests/test_architecture_skeleton.py`
- Result: `42 passed`

Latest full-suite remediation baseline:

- Result: `1616 passed, 23 skipped`

### Notes

- `PROMPT-phase7-remediation.md` remains an execution prompt artifact; it is
  not a runtime contract document.
- The historical log above is preserved intentionally, even where it records
  intermediate false starts, reopened gates, and stale before-state notes.
