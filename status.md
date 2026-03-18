# Architecture Remediation Status

Last updated: 2026-03-18
Repository: `/Users/tinker/output/bots/telegram-agent-bot`
Current branch: `feature/skills`

## Scope

This file tracks execution of the **Reopened Architecture Remediation Track**
in [`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md).

Feature work remains frozen until every acceptance gate in the plan passes.

## Current State

The remediation track is in progress.

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

22. `pending commit` `Track F / F6: enforce runtime dispatch ownership`
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

## Latest Verified Test Baseline

At the end of the latest completed slice:

- full suite passed
- result: `1550 passed, 23 skipped`

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

Status: not started

Required scope:

- move Telegram rendering from:
  - `app/channels/telegram/ingress.py`
  - `app/channels/telegram/conversation.py`
  - `app/channels/telegram/runtime_skills.py`
  - `app/channels/telegram/pending.py`
  - `app/channels/telegram/guidance.py`
- into:
  - `app/channels/telegram/presenters.py`

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

Status: not started

Required scope:

- remove dead root re-exports after F5
- confirm `transport_contract.py` relocation after F5
- expand zero-import gates to `tests/`
- rename stale transport-era tests

### Track F. Orchestration and State-Machine Consolidation

Status: in progress

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

Remaining:

- none

## Acceptance Gate Checklist

These gates are copied from the active plan and tracked here with current
status.

- [ ] No app module outside Telegram ingress imports Telegram ingress.
- [ ] Telegram channel runtime state is explicit and no longer
  global-module-owned.
- [ ] `runtime/*` has no channel imports.
- [ ] `agents/*` has no channel imports.
- [ ] `access.py` has no channel imports.
- [ ] Telegram presenters own Telegram rendering.
- [ ] Registry `http.py` is a thin HTTP boundary and `ui.py` owns UI rendering.
- [x] Setup progression has one explicit machine owner.
- [x] Delegation progression has one explicit workflow/machine owner.
- [x] Pending and recovery machines live under concern-owned workflow packages.
- [x] `runtime/dispatch.py` is channel-agnostic plumbing and not a shadow
  workflow owner.
- [x] The repo-standard explicit machine style is declared and used for
  remediated durable workflows.
- [x] Lifecycle snapshot and latest-approval ownership are cleaned up.
- [ ] `workflows/__init__.py` and `transport_contract.py` no longer carry
  dead or misleading transitional ownership.
- [ ] Zero-import gates cover both `app/` and `tests/`.
- [x] Test support no longer mutates Telegram ingress globals.

## Current Slice

Next required slice:

- `Track E / E1-E4: remove stale transitional ownership and extend zero-import gates`

Completed:

- `C1` move registry UI shell rendering into `ui.py`
- `C2` move registry auth/session helpers out of `http.py`
- `D1` centralize lifecycle snapshot construction
- `D2` add explicit latest-approval store queries
- `D3` remove private cross-workflow latest-action access
- `F1` commit the orchestration inventory
- `F2` commit the repo-standard machine conventions
- `F3` extract the runtime-skill setup machine and delete the legacy setup service
- `F4` move delegation progression under `app/workflows/delegation/*`
- `F5` migrate pending and recovery to concern-owned functional machines
- `F6` separate execution workflow ownership from runtime dispatch

Remaining:

- Track E cleanup slices
- Track B Telegram presenter extraction
- final acceptance-gate audit

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
