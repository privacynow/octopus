# Control-Plane Rollout & Routed-Task Lifecycle Status

## Baseline

- Track: control-plane rollout, routed-task lifecycle correctness, and final surface cleanup
- Plan: `PLAN-control-plane-bus.md`
- Branch: `feature/multi_registry`
- Goal: keep conversation projection, task routing, delivery, recovery, and registry UI concerns on their intended seams without fake task conversations, surface-specific policy drift, or stale status/doc contracts

## Current State

- Phases 1-13 are implemented and closed.
- Phase 14 is active.
- Phase 14A landed green: bridge admission no longer fabricates bot presence for registry `channel_input` refs, while the legitimate registry conversation bind/timeline path remains intact.
- Phase 13G landed green: the status document now matches the real control-plane/remediation track, uses a present-tense current-state summary, and was verified against a final full-suite rerun.
- Registry delivery now publishes parent-conversation timeline events through the existing `ConversationProjectionPort`; dispatcher/egress creation remains reserved for real live-output and readiness concerns.
- Routed-task lifecycle is owned by the task-routing/store seam:
  - protected/degraded task states resist late in-flight status updates
  - failed routed-result delivery leaves durable degraded task state
  - routed tasks skip the generic completion webhook
  - routed-task recovery does not bind or send notices through task-ref egress
  - throttled progress updates stay on the existing Telegram progress boundary
- Registry UI shell routes visible degraded/timed-out status text through human-readable labels instead of exposing raw internal codes.
- Dead routed-result warning surface has been removed from worker/finalization code.
- Protected routed-task status coverage now spans the full shared status set across SQLite and Postgres, and rejected protected-state updates cannot append timeline rows.
- Latest verified full-suite run: `1963 passed, 23 skipped`.

## Phase Summary

- Phases 1-8 established the control-plane rollout foundation and moved the main runtime toward dispatcher-owned channel routing and control-plane-backed projection.
- Phase 9 removed the first major registry-side leaks, but later review reopened routed-task/channel-contract issues that were still structurally wrong.
- Phase 10 corrected the routed-task channel contract, authority propagation, routed-task progress ownership, residual surface-policy checks, and dead registry-state defaults.
- Phase 11 removed projected task-ref execution leakage and moved readiness checks onto the cheaper channel-seam probe.
- Phase 12 closed routed-task lifecycle correctness on the existing task-routing/store seams: durable degraded state, webhook suppression, recovery no-ops, and throttling proof.
- Phase 13 is the final cleanup track:
  - `13A` delivery projection ownership
  - `13B` registry UI human-readable degraded status
  - `13C` dead routed-result warning removal
  - `13D` full protected-status contract coverage
  - `13E` concern-neutral progress logging
  - `13F` timeline-upsert guard parity
  - `13G` status/doc closeout
- Phase 14 is the remaining ownership and hygiene cleanup track:
  - `14A` bridge fake-bot shim removal
  - `14B` bridge helper extraction and generic recovery ref resolution
  - `14C` internal version-label removal
  - `14D` behavior-first guardrail hardening
  - `14E` status/doc closeout

## Phase 14 Slice Log

- Complete: Phase 14A remediation — remove the stale fake-bot shim from bridge admission.
  Scope:
  - deleted `_egress_bot()` from `app/agents/bridge.py`
  - stopped passing `bot=` into dispatcher egress construction for registry `channel_input` admission
  - preserved the legitimate registry conversation `sync_binding()` and `publish_timeline()` side effects on registry conversation refs
  - tightened `tests/test_agents.py` so the primary behavior test now proves the dispatcher sees only the real registry egress kwargs and no fabricated `bot`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py -k 'admit_registry_delivery_queued_is_accepted or admit_registry_delivery_rejects_legacy_surface_input_kind or admit_registry_delivery_rejects_missing_registry_id'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - registry `channel_input` admission still binds and publishes timeline on the registry conversation ref
  - dispatcher egress construction for that path no longer receives a fake bot kwarg
  - legacy `surface_input` and missing-`registry_id` rejects remain intact
  - full suite status after Phase 14A: `1963 passed, 23 skipped`

## Phase 13 Slice Log

- Complete: Phase 13G closeout — rewrite the status document so it is present-tense, track-correct, and only claims behavior that is directly proven by code and tests.
  Scope:
  - replaced the stale multi-registry/bootstrap baseline header with the actual control-plane/remediation baseline
  - collapsed layered historical “current state” claims into one accurate present-tense summary
  - retained a compact phase summary and the concrete Phase 13 slice history
  - reran the full suite after the doc rewrite before closing the phase
  Tests:
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the status document now matches the actual control-plane/remediation track instead of the old multi-registry bootstrap track
  - final full suite status after Phase 13G: `1963 passed, 23 skipped`

- Complete: Phase 13F remediation — guard routed-task timeline-event upserts behind the protected status-update guard.
  Commit:
  - `1a4729f` `phase-13 / 13f: guard timeline-event upserts behind status guard`
  Scope:
  - updated `app/registry_service/store.py` so `update_routed_task_status(...)` only upserts `timeline_events` when the guarded routed-task `UPDATE` actually affects a row
  - mirrored the same guard in `app/registry_service/store_postgres.py` so SQLite and Postgres keep identical status/timeline semantics
  - added a contract regression in `tests/contracts/test_registry_store_contract.py` proving that a rejected late `running` update cannot write timeline rows after a task reaches a protected state through `update_routed_task_result()`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/contracts/test_registry_store_contract.py -k 'status_rejection_does_not_upsert_timeline_events or routed_task_status_updates_do_not_overwrite_protected_status or routed_task_result_can_overwrite_partialfailed'`
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_integration.py -k 'routed_task_status_update_persists_timeline_events_and_progress'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - rejected routed-task status updates can no longer append timeline rows after a task reaches a protected state
  - accepted routed-task progress updates still persist timeline events and progress payloads
  - full suite status after Phase 13F: `1963 passed, 23 skipped`

- Complete: Phase 13E remediation — make progress callback logging concern-neutral.
  Commit:
  - `4ec359e` `phase-13 / 13e: concern-neutral progress callback log`
  Scope:
  - changed the Telegram progress warning text from `"Control-plane timeline callback failed"` to `"Control-plane progress callback failed"` in `app/channels/telegram/progress.py`
  - added a focused regression test proving the new wording is logged and the old wording is absent when the callback raises
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_telegram_progress_module.py -k 'logs_concern_neutral_callback_failure or throttles_routed_task_callback_and_force_bypasses or routed_task_progress_callback_updates_task_status_via_port'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - callback-failure logs now describe the progress concern accurately for both projection and task-routing callback use
  - full suite status after Phase 13E: `1961 passed, 23 skipped`

- Complete: Phase 13D remediation — parametrize protected-status contract coverage.
  Commit:
  - `806ed39` `phase-13 / 13d: parametrize protected-status contract tests`
  Scope:
  - imported the shared `PROTECTED_ROUTED_TASK_STATUSES` constant into `tests/contracts/test_registry_store_contract.py`
  - replaced the separate `completed` / `partialfailed` protection tests with one parametrized contract that covers `completed`, `failed`, `cancelled`, `timed_out`, and `partialfailed` across SQLite and Postgres
  - kept the `partialfailed` overwrite-by-result test separate so final result ownership remains explicitly proven
  Tests:
  - `./.venv/bin/python -m pytest -q tests/contracts/test_registry_store_contract.py -k 'routed_task_status_updates_do_not_overwrite_protected_status or routed_task_result_can_overwrite_partialfailed or create_routed_task_and_lookup'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - all protected routed-task statuses now resist late in-flight updates across both backends
  - the `completed` branch still proves `result_json` preservation after a late `running` update
  - full suite status after Phase 13D: `1960 passed, 23 skipped`

- Complete: Phase 13C remediation — delete the dead routed-result warning surface.
  Commit:
  - `f838f7b` `phase-13 / 13c: remove dead routed-result warning surface`
  Scope:
  - removed `routed_result_warning_text` from `FinalizationOutcome` in `app/workflows/execution/finalization.py`
  - deleted the unreachable routed-result warning send branch from `app/channels/telegram/worker.py`
  - updated finalization/worker regression tests so the oracle is now the real contract: `routed_result_status="report_failed"` plus the existing `partialfailed` fallback state, not a dead warning string
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_execution_finalization.py -k 'report_failure_emits_partialfailed_fallback'`
  - `./.venv/bin/python -m pytest -q tests/test_handlers.py -k 'registry_routed_task_result_report_failure_does_not_escape_worker'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - routed-task result-report failure is surfaced only through degraded task state on the existing task-routing seam
  - no routed-result warning send path remains in worker/finalization code
  - full suite status after Phase 13C: `1954 passed, 23 skipped`

- Complete: Phase 13B remediation — humanize routed-task degraded status in the registry UI.
  Commit:
  - `74572cd` `phase-13 / 13b: humanize task status labels in registry UI`
  Scope:
  - added a `statusLabel(...)` helper in `app/channels/registry/ui.py` so visible badge text no longer exposes raw internal values like `partialfailed`
  - kept stored/raw status values on the existing CSS/filter seams while changing only the visible render path
  - added normalized badge-class support for timed-out statuses without changing filter/storage vocabulary
  - widened static-shell regression coverage in `tests/test_registry_service.py` to prove the helper, mappings, and visible status render sites are present in the rendered HTML/JS
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_registry_service.py -k 'humanizes_visible_status_labels or partialfailed_as_failed_for_status_filter or render_shell_helper_uses_local_editors'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the registry UI shell routes visible degraded/timed-out badge text through human-readable labels
  - filter normalization still treats `partialfailed` as failed without changing the stored status value
  - full suite status after Phase 13B: `1954 passed, 23 skipped`

- Complete: Phase 13A remediation — remove delivery-side egress proxy for projection.
  Commit:
  - `2b5fb4c` `phase-13 / 13a: replace delivery egress-proxy with control-plane port`
  Scope:
  - added `services: BotServices` to `app/agents/delivery.py:RegistryDeliveryRuntime` and threaded the existing runtime services container through the delivery-runtime builder in production and test call sites
  - removed the `_egress_bot() -> object()` hack and deleted `_publish_timeline_via_dispatcher()` from `app/agents/delivery.py`
  - moved delegated-result and delegation-ready parent timeline publication onto the existing `services.control_plane.conversation_projection` seam
  - preserved live egress behavior in delivery: `dispatcher.egress_ready_for_ref(...)` and real `dispatcher.create_egress(...)` still own readiness and actual parent-conversation output
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py -k 'startup_race or channel_action_and_control_dispatch or legacy_surface_input_kind or legacy_surface_action_kind or missing_registry_id_for_registry_owned_kinds'`
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_integration.py -k 'registry_delivery_projects_parent_timeline or delegated_result'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - parent timeline projection no longer depends on fabricated bot presence or egress construction
  - startup-race behavior still retries later when real live egress is not ready
  - full suite status after Phase 13A: `1953 passed, 23 skipped`
