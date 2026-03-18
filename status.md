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

8. `this commit` `Track A / A2: detach runtime dispatch slice from ingress`
   - `app/runtime/dispatch.py` no longer imports Telegram channel modules.
   - Request execution and approval plumbing now run through explicit
     `RuntimeDispatchRuntime` injection from Telegram ingress.
   - `RequestExecutionOutcome` ownership moved into the runtime boundary
     instead of being defined inside Telegram ingress.
   - Added focused positive and negative tests for the dispatch boundary and
     the new import-direction gate.

## Latest Verified Test Baseline

At the end of the latest completed slice:

- full suite passed
- result: `1505 passed, 23 skipped`

This baseline must be re-established after every subsequent slice before
committing.

## Track Progress

### Track A. Fix the Inbound Context Problem

Status: in progress

Completed:

- `A3` remove Telegram normalization from `app/access.py`
- `A4` move `trust_tier_for_source`
- `A1` extract explicit Telegram state/cancellation owners
- `A2` conversation concern slice
- `A2` runtime skills concern slice
- `A2` pending concern slice
- `A2` runtime dispatch concern slice

Remaining:

- `A2` agents delivery concern slice
- `A2` agents delegation concern slice
- `A5` finish test support migration and remove any remaining global-state test coupling

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

Status: not started

Required scope:

- move large HTML/CSS/JS blocks out of `app/channels/registry/http.py`
- expand `app/channels/registry/ui.py`
- keep `http.py` as a thin HTTP boundary
- move displaced non-boundary auth/session logic to `app/channels/registry/auth.py`

### Track D. Lifecycle and Workflow Hygiene Cleanup

Status: not started

Required scope:

- deduplicate lifecycle snapshot construction
- add explicit latest-approval store methods
- remove private cross-class lifecycle helper access

### Track E. Dead Code, Naming, and Test-Gate Cleanup

Status: not started

Required scope:

- remove dead root re-exports after F5
- confirm `transport_contract.py` relocation after F5
- expand zero-import gates to `tests/`
- rename stale transport-era tests

### Track F. Orchestration and State-Machine Consolidation

Status: not started

Required scope:

- `F1` committed orchestration inventory
- `F2` repo-standard functional decision-machine conventions
- `F3` runtime skill setup machine
- `F4` delegation machine/workflow
- `F5` pending/recovery migration off `python-statemachine`
- `F6` dispatch ownership cleanup

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
- [ ] Setup progression has one explicit machine owner.
- [ ] Delegation progression has one explicit workflow/machine owner.
- [ ] Pending and recovery machines live under concern-owned workflow packages.
- [ ] `runtime/dispatch.py` is channel-agnostic plumbing and not a shadow
  workflow owner.
- [ ] The repo-standard explicit machine style is declared and used for
  remediated durable workflows.
- [ ] Lifecycle snapshot and latest-approval ownership are cleaned up.
- [ ] `workflows/__init__.py` and `transport_contract.py` no longer carry
  dead or misleading transitional ownership.
- [ ] Zero-import gates cover both `app/` and `tests/`.
- [ ] Test support no longer mutates Telegram ingress globals.

## Current Slice

Next required slice:

- `Track A / A2: detach agents delivery slice from Telegram ingress`

Before-state:

- `app/agents/delivery.py` still imports Telegram ingress-owned collaborators
  and still violates the agents layer boundary.

After-state required:

- `app/agents/delivery.py` becomes a thin bridge over explicit injected
  collaborators or shared workflow/runtime owners.
- `agents/*` no longer import Telegram ingress and move toward zero channel
  imports entirely.
- negative gate tests prove the old back-import pattern is gone.

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
