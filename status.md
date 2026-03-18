# Architecture Remediation Status

Last updated: 2026-03-18
Repository: `/Users/tinker/output/bots/telegram-agent-bot`
Current branch: `feature/skills`

## Scope

This file is the current closure artifact for the architecture remediation work
defined in
[`store_plan.md`](/Users/tinker/output/bots/telegram-agent-bot/store_plan.md).

Historical pre-Phase-7 execution details live in git history. This document
tracks the final accepted ownership model and the last remediation verification
baseline.

## Current State

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

## Phase 7 Slice Log

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

## Acceptance Gates

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

## Verification Baseline

Latest focused G4 structural suite:

- `tests/test_orchestration_inventory.py`
- `tests/test_status_doc.py`
- `tests/test_zero_import_gates.py`
- `tests/test_architecture_skeleton.py`
- Result: `41 passed`

Latest full-suite remediation baseline:

- Result: `1615 passed, 23 skipped`

## Notes

- `PROMPT-phase7-remediation.md` remains an execution prompt artifact; it is
  not a runtime contract document.
- This file is intentionally concise. Historical intermediate notes and stale
  before-state inventories were removed once the final code/tests proved the
  closure state.
