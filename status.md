# Control-Plane Rollout & Routed-Task Lifecycle Status

## Baseline

- Track: control-plane rollout, routed-task lifecycle correctness, and final surface cleanup
- Plan: `PLAN-control-plane-bus.md`
- Branch: `feature/multi_registry`
- Goal: keep conversation projection, task routing, delivery, recovery, and registry UI concerns on their intended seams without fake task conversations, surface-specific policy drift, or stale status/doc contracts

## Current State

- Phases 1-18 are implemented and closed. Phase 19 is active.
- Phase 19A1 landed green: Codex security-sensitive input now flows through one shared validator, invalid `CODEX_SANDBOX` values fail fast at config load, stale repo tests now match the live Codex CLI contract, and the README command-section contract was restored after the earlier docs refresh changed the tested heading.
- Registry delivery now publishes parent-conversation timeline events through the existing `ConversationProjectionPort`; dispatcher/egress creation remains reserved for real live-output and readiness concerns.
- Bridge admission and recovery/ref resolution now stay on their intended seams:
  - registry `channel_input` admission no longer fabricates bot presence
  - generic ref/text helpers live on `app/identity.py` and `app/formatting.py`
  - inbound and recovery share one data-driven ref resolver instead of Telegram-specific fallback branches
- Routed-task lifecycle is owned by the task-routing/store seam:
  - protected/degraded task states resist late in-flight status updates
  - failed routed-result delivery leaves durable degraded task state
  - routed tasks skip the generic completion webhook
  - routed-task recovery does not bind or send notices through task-ref egress
  - throttled progress updates stay on the existing Telegram progress boundary
- Registry UI shell routes visible degraded/timed-out status text through human-readable labels instead of exposing raw internal codes.
- Agent cards no longer leak the internal `phase-19-foundation` rollout marker; blank versions render through the existing registry UI fallback as `unknown`.
- Dead routed-result warning surface has been removed from worker/finalization code.
- Protected routed-task status coverage spans the full shared status set across SQLite and Postgres, rejected protected-state updates cannot append timeline rows, and the remaining bridge-cleanup seams now have narrow secondary regression checks.
- Registry ref qualification now treats already-qualified refs generically instead of hardcoding Telegram/registry prefixes, and the helper seam has direct contract coverage plus live caller regressions for registry `channel_action` and `routed_result`.
- Shared preflight and registry metadata no longer leak stale Telegram-specific wording on shared/product seams, and the registry UI conversation empty state is now channel-neutral.
- Registry bind persistence no longer invents `origin_channel="telegram"` when callers omit the field; invalid bind payloads now fail at the owning store seam and are surfaced as `422` at the raw registry HTTP edge.
- Registry binding now uses `binding_external_id_for_ref(...)`, making the helper contract explicit: registry refs yield parsed external ids and non-registry refs preserve their original qualified ref for binding.
- Raw registry agent endpoints now validate their payloads against the store contract instead of relying on happy-path callers:
  - enroll/register/heartbeat/timeline/search/routed-task/ack/status/result all fail malformed payloads with `422`
  - routed-task status/result updates now require explicit non-empty `status`
  - bind/enroll/register no longer hide stale scope/channel/capacity defaults at the owning persistence seam
- Registry store validation is now explicit and consistent across SQLite and Postgres:
  - `register()` preserves omitted capacity and card-list fields instead of resetting them
  - `enroll()` requires an explicit valid `registry_scope`
  - `ack()` rejects invalid classifications instead of coercing them
  - conversation follow-up message/action writes reject blank values
  - discovery search rejects malformed list filters and the free-text path no longer references the old `disabled_skills` name
- Registry UI shell now normalizes more of the actual data it receives:
  - real timeline/event kinds map to badge classes instead of rendering as unstyled plain text
  - diagnostic levels are normalized to the supported CSS set
  - search snippet rendering is routed through one HTML-safe helper instead of inline escape/unescape fragments
- Recovery/replay hardening now covers the sibling edge cases found during the repo-wide audit:
  - blank conversation identity resolves as a typed failure instead of slipping through replay prep
  - unexpected worker-recovery outcomes now raise instead of returning silently
  - fresh-install Postgres bootstrap is checked directly against the current registry store schema contract
- Shared inbound events no longer rely on Telegram constructor defaults:
  - durable deserialization still requires explicit canonical `source`
  - `InboundMessage` / `InboundCommand` / `InboundCallback` / `InboundAction` now require explicit source at construction time
  - Telegram-owned builders and runtime tests pass `source="telegram"` explicitly instead of inheriting it implicitly
- Shared workflow/doc surfaces no longer keep the stale Telegram-first framing in generic ownership/docstrings.
- Codex provider/runtime hardening is now underway:
  - sandbox values are validated against the current CLI contract (`read-only`, `workspace-write`, `danger-full-access`)
  - skill-provided Codex `config_overrides` are restricted to the audited allowlisted key set instead of being appended raw to argv
  - invalid override entries are rejected with warnings instead of silently weakening execution
- Accepted limitation: the registry UI shell regressions still prove static HTML/JS shell wiring, not browser-rendered DOM behavior. That limitation is now explicit and is not being overclaimed as runtime UI proof.
- Latest verified full-suite run: `2047 passed, 23 skipped`.

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
- Phase 14 closed the remaining ownership and hygiene cleanup track:
  - `14A` bridge fake-bot shim removal
  - `14B` bridge helper extraction and generic recovery ref resolution
  - `14C` internal version-label removal
  - `14D` behavior-first guardrail hardening
  - `14E` status/doc closeout
- Phase 15 is the invariant-first seam closure track:
  - `15A` generic ref qualification and contract tests
  - `15B` stale channel-name removal from shared prompts and API title
  - `15C` invariant closeout sweep and status/doc update
- Phase 16 is the boundary validation and helper-contract cleanup track:
  - `16A` bind/origin-channel invariant closure
  - `16B` external-id helper contract clarification
  - `16C` closeout
- Phase 17 is the shared inbound provenance closure track:
  - `17A` shared inbound provenance invariant closure
  - `17B` closeout and constructor-default audit
- Phase 18 is the registry-boundary and audit-closeout track:
  - `18A` registry HTTP/store contract hardening
  - `18B` UI/recovery/schema parity sweep
  - `18C` explicit inbound-source enforcement and closeout
- Phase 19 is the final remediation track:
  - Track A security hardening
  - Track B durability and data-integrity hardening
  - Track C resource-lifecycle cleanup
  - Track D delegation correctness
  - Track E error-handling and polish

## Phase 19 Slice Log

- Complete: Phase 19A1 remediation — codify the current Codex sandbox/override contract in one shared validator before execution reaches the provider argv builder.
  Scope:
  - added `app/providers/codex_security.py` as the shared Codex security seam for sandbox validation and allowlisted `config_overrides`
  - updated `app/config.py` so invalid `CODEX_SANDBOX` values fail fast at config load/provider-health load, and `validate_config(...)` now flags invalid Codex sandbox settings on direct config objects
  - updated `app/providers/codex.py` so invalid provider-config sandbox overrides are rejected with warnings and invalid `config_overrides` entries are filtered instead of being appended raw to argv
  - refreshed the stale Codex-contract tests to use the live CLI sandbox values and the repo’s actual allowlisted override key (`sandbox_permissions`)
  - restored the README commands-section heading required by the existing README contract tests after the earlier doc refresh renamed it
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_codex_provider.py tests/test_execution_context.py tests/test_config.py tests/test_skills.py -k 'codex or inspect_mode or sandbox or config_overrides or build_provider_config or placeholder_resolution'`
  - `./.venv/bin/python -m pytest -q tests/test_readme_commands.py`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - Codex sandbox values are now validated against the live CLI contract instead of accepting stale repo-only strings like `off` / `networking`
  - the only current skill-owned Codex override key in the repo (`sandbox_permissions`) still flows through, while unsafe/non-allowlisted entries are rejected before argv construction
  - config-load failure is now explicit at the owner seam, not deferred until provider execution
  - full suite status after Phase 19A1: `2047 passed, 23 skipped`

## Phase 18 Slice Log

- Complete: Phase 18C closeout — remove the last shared inbound constructor default, neutralize the remaining shared Telegram-first doc wording, and only then close the audit pass.
  Scope:
  - changed `app/runtime/inbound_types.py` so inbound event constructors require explicit non-empty `source` instead of silently defaulting to `"telegram"`
  - updated Telegram-owned builders and constructor-heavy runtime/worker tests to pass `source="telegram"` explicitly
  - added direct constructor contract coverage in `tests/test_runtime_inbound_types.py`
  - neutralized the remaining shared-workflow/shared-module docstrings that were still describing generic seams as Telegram-specific
  - kept the accepted static-shell UI-test limitation explicit because the repo still does not carry a browser test harness
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_runtime_inbound_types.py tests/test_work_queue.py tests/test_transport.py tests/test_handlers.py tests/test_worker_workflows.py tests/test_invariants.py tests/test_telegram_guidance.py tests/test_telegram_runtime_skills.py tests/test_workitem_integration.py`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - shared inbound event construction no longer hides missing provenance behind a Telegram default
  - Telegram-owned builders remain explicit and green after the constructor contract tightens
  - shared doc surfaces no longer encode stale Telegram-first ownership language
  - final full suite status after Phase 18C: `2040 passed, 23 skipped`

- Complete: Phase 18B remediation — close the repo-wide audit findings around UI rendering, recovery edge handling, migration parity, and fixture clarity.
  Scope:
  - expanded `app/channels/registry/ui.py` badge-class handling for real timeline kinds, normalized diagnostic CSS classes, and routed search snippet rendering through a single helper
  - hardened `app/workflows/recovery/replay.py` and `app/channels/telegram/worker.py` so missing conversation identity and unexpected recovery outcomes fail explicitly instead of slipping through
  - added a fresh-install Postgres bootstrap parity check in `tests/test_db_postgres.py`
  - clarified the registry processor/runtime fixture intent in `tests/test_control_plane_integration.py` and `tests/support/handler_support.py`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_registry_service.py tests/test_worker_workflows.py tests/test_db_postgres.py tests/test_control_plane_integration.py`
  Verified:
  - registry UI shell handles the actual event-kind/diagnostic/snippet shapes produced by the store more consistently
  - recovery/replay failure paths now fail loudly on malformed identity or impossible dispatch outcomes
  - Postgres fresh-install bootstrap still matches the current registry store contract

- Complete: Phase 18A remediation — harden the raw registry HTTP/store boundary instead of relying on control-plane happy-path callers.
  Scope:
  - added explicit payload validators in `app/registry_service/store_base.py` for bind/register/heartbeat/timeline/search/routed-task/ack/status/result/message/action seams
  - updated both registry store backends so stale defaults no longer hide bad inputs:
    - `register()` preserves omitted capacity/card-list fields
    - `enroll()` requires explicit valid `registry_scope`
    - routed-task status/result updates require explicit non-empty `status`
    - `ack()` rejects invalid classifications
    - UI follow-up message/action writes reject blank inputs
  - updated `app/channels/registry/http.py` so malformed raw payloads return `422` instead of surfacing as `500` or silently mutating store state
  - fixed the discovery free-text search path to use the current disabled-capability shape
  Tests:
  - `./.venv/bin/python -m pytest -q tests/contracts/test_registry_store_contract.py tests/test_registry_service.py tests/test_registry_skills.py`
  Verified:
  - malformed raw registry requests now fail at the owning boundary instead of corrupting state through store defaults
  - SQLite and Postgres now enforce the same agent-facing payload rules on these seams

## Phase 17 Slice Log

- Complete: Phase 17B closeout — rerun the provenance/default audit, keep the accepted limitations honest, and only then close the phase.
  Scope:
  - reran the shared-default audit after removing the deserializer fallback and confirmed the remaining `source="telegram"` defaults in `app/runtime/inbound_types.py` are constructor conveniences used by Telegram-owned builders, not owner-boundary persistence/deserialization fallbacks
  - updated the plan/status documents only after the focused tests and final full-suite rerun were green
  - kept the accepted static-shell UI-test limitation explicit instead of overstating it as browser-rendered proof
  Tests:
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - no owner-boundary inbound provenance fallback remains after the deserializer fix
  - the constructor-default audit did not uncover another shared persistence/runtime seam bug in this area
  - final full suite status after Phase 17B: `2001 passed, 23 skipped`

- Complete: Phase 17A remediation — close the shared inbound provenance invariant at the deserializer seam instead of relying on caller discipline.
  Scope:
  - updated `app/runtime/inbound_types.py` so `deserialize_inbound(...)` requires explicit canonical `source` instead of defaulting missing provenance to `"telegram"`
  - kept the existing registry `authority_ref` validation on the explicit-provenance path and added a code comment documenting why the Telegram fallback was structurally wrong
  - added direct contract tests in `tests/test_runtime_inbound_types.py` for missing and blank `source`
  - added a live worker regression in `tests/test_work_queue.py` proving malformed queued payloads missing `source` fail as `deserialize_error` instead of dispatching
  - updated the small set of manual canonical payload fixtures in `tests/test_shared_runtime.py`, `tests/test_handlers.py`, and `tests/test_simulator_e2e.py` so they now carry explicit `source="telegram"`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_runtime_inbound_types.py tests/test_work_queue.py -k 'deserialize_inbound or worker_loop_handles_bad_payload or worker_loop_rejects_payload_missing_canonical_source or worker_loop_notifies_on_deserialize_failure'`
  - `./.venv/bin/python -m pytest -q tests/test_shared_runtime.py -k 'shared_cancel_records_action_and_sets_durable_flag or worker_loop_heartbeat_tracks_current_item'`
  - `./.venv/bin/python -m pytest -q tests/test_handlers.py -k 'registry_channel_action_recovery_replay_executes_request'`
  - `./.venv/bin/python -m pytest -q tests/test_simulator_e2e.py -k 'recover'`
  Verified:
  - shared inbound deserialization now rejects missing or blank canonical provenance instead of silently classifying malformed payloads as Telegram
  - worker-loop and recovery/shared-runtime paths stay green once canonical payload fixtures carry explicit `source`
  - focused seam and live-path coverage passed before the final closeout rerun

## Phase 16 Slice Log

- Complete: Phase 16C closeout — rerun the seam sweep, keep the accepted limitations honest, and only then close the phase.
  Scope:
  - reran the targeted sweep for hidden `origin_channel="telegram"` defaults and verified no production or test code still contains the old store fallback
  - reran the helper-name sweep and verified no production or test code still references `registry_ref_external_id(...)`
  - confirmed the only remaining older-name hits are historical status notes documenting the 16B rename
  - closed the phase only after a final full-suite rerun
  Tests:
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the bind/origin-channel invariant remains closed across both store backends and the raw registry HTTP edge
  - the external-id helper contract/name cleanup is fully propagated through production code and tests
  - the accepted static-shell UI-test limitation remains documented accurately and is not being overclaimed
  - final full suite status after Phase 16C: `1998 passed, 23 skipped`

- Complete: Phase 16B remediation — make the registry external-id helper contract honest without changing the runtime behavior current binding flows depend on.
  Scope:
  - renamed `registry_ref_external_id(...)` to `binding_external_id_for_ref(...)` in `app/channels/registry/refs.py`
  - updated `app/channels/registry/channel.py`, `app/channels/registry/egress.py`, and `app/agents/bridge.py` to use the renamed helper
  - expanded `tests/test_registry_refs.py` so the contract is explicit for registry conversation refs, registry task refs, and non-registry qualified refs
  - added a live-path regression in `tests/test_agents.py` proving registry `channel_input` delivery preserves a qualified non-registry ref as the binding external id
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_registry_refs.py`
  - `./.venv/bin/python -m pytest -q tests/test_agents.py -k 'preserves_external_id_for_qualified_non_registry_ref or admit_registry_delivery_queued_is_accepted'`
  - `./.venv/bin/python -m pytest -q tests/test_registry_adapter.py`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the helper name now matches the actual contract instead of implying registry-only extraction semantics
  - current registry binding flows still preserve qualified non-registry refs unchanged where that behavior is required
  - no production code references to the old helper name remain
  - full suite status after Phase 16B: `1998 passed, 23 skipped`

- Complete: Phase 16A remediation — close the bind/origin-channel invariant at the owning store seam instead of letting caller discipline hide a bad default.
  Scope:
  - added `validated_bind_conversation_payload(...)` to `app/registry_service/store_base.py`
  - removed the hidden `origin_channel="telegram"` fallback from both `app/registry_service/store.py` and `app/registry_service/store_postgres.py`
  - updated `app/channels/registry/http.py` so invalid bind payloads surface as `422` instead of server errors
  - added direct negative contract tests in `tests/contracts/test_registry_store_contract.py` proving missing and blank `origin_channel` payloads are rejected without creating conversation rows
  - added an API regression in `tests/test_registry_service.py` proving the raw registry bind endpoint now returns `422` for missing `origin_channel` and does not create a conversation
  Tests:
  - `./.venv/bin/python -m pytest -q tests/contracts/test_registry_store_contract.py -k 'bind_conversation'`
  - `./.venv/bin/python -m pytest -q tests/test_registry_service.py -k 'bind_conversation'`
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_integration.py::test_registry_only_bot_projects_without_telegram_runtime`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the bind persistence seam no longer invents a Telegram origin when callers omit `origin_channel`
  - invalid bind payloads now fail at the owning store seam and map to `422` at the raw HTTP edge
  - explicit valid `origin_channel` values still project through the real control-plane bind path into the registry store
  - full suite status after Phase 16A: `1996 passed, 23 skipped`

## Phase 15 Slice Log

- Complete: Phase 15C closeout — rerun the invariant sweep, record the accepted limitations honestly, and only then close the phase.
  Scope:
  - reran the targeted grep sweep for stale `Telegram bridge` / `Telegram Agent Registry` strings, hardcoded ref-qualification prefix lists, and rollout-marker hits after 15A-15B
  - verified the only remaining hardcoded prefix check is the intentional `parse_registry_ref()` parser guard and the only remaining `phase-19-foundation` hits are negative assertions in tests
  - rewrote the status document current state so Phase 15 is presented as closed invariant-first seam closure instead of an active cleanup track
  - recorded the accepted limitation on registry UI shell tests explicitly: they prove static HTML/JS shell wiring, not browser-rendered DOM behavior
  Tests:
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - no stale `Telegram bridge` or `Telegram Agent Registry` strings remain in production code
  - no rollout-marker hits remain in production code
  - the accepted static-shell UI-test limitation is now documented instead of being overclaimed
  - final full suite status after Phase 15C: `1991 passed, 23 skipped`

- Complete: Phase 15B remediation — remove stale channel-specific wording from shared prompts and remaining generic registry surfaces.
  Scope:
  - changed `app/approvals.py:build_preflight_prompt()` from `Telegram bridge` wording to neutral bot/provider wording
  - changed the FastAPI registry app title in `app/channels/registry/http.py` from `Telegram Agent Registry` to `Agent Registry`
  - removed the stale Telegram-specific conversation empty-state copy from `app/channels/registry/ui.py`
  - added a direct approval-prompt regression in `tests/test_approvals.py`, an `/openapi.json` title check in `tests/test_registry_service.py`, and a registry UI shell regression proving the empty-state copy is now channel-neutral
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_approvals.py tests/test_registry_service.py -k 'preflight_prompt or openapi_title_is_channel_neutral or conversation_empty_state_is_channel_neutral or bot_detail_version_falls_back_to_unknown or humanizes_visible_status_labels'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - shared preflight text no longer describes the system as a Telegram bridge
  - registry API metadata now matches the generic `Agent Registry` product naming already used on the UI shell/login surfaces
  - the remaining stale Telegram-specific copy found during the shared/product sweep was fixed in the same slice rather than deferred
  - full suite status after Phase 15B: `1991 passed, 23 skipped`

- Complete: Phase 15A remediation — close the ref-qualification invariant at the owning seam instead of only at caller paths.
  Scope:
  - changed `app/channels/registry/refs.py:qualify_registry_conversation_ref()` to preserve any already-qualified ref generically via `":" in conversation_ref` instead of a hardcoded Telegram/registry prefix list
  - added a dedicated helper contract suite in `tests/test_registry_refs.py` covering bare ids, empty input, Telegram refs, registry conversation refs, registry task refs, future-surface refs, `parse_registry_ref()`, and the external-id helper contract
  - added live caller regressions in `tests/test_agents.py` proving qualified future-surface refs remain unchanged through both registry `channel_action` and registry `routed_result` handling
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_registry_refs.py tests/test_agents.py -k 'registry_ref or preserves_already_qualified_future_surface_ref or handle_registry_channel_action_and_control_dispatch or routed_result_publishes_parent_timeline_before_retry_on_startup_race'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - already-qualified refs now pass through unchanged at the owning helper seam, not just for Telegram and registry
  - the direct helper contract is now tested independently of callers
  - registry `channel_action` and `routed_result` callers preserve qualified future-surface refs without rewrapping them
  - full suite status after Phase 15A: `1988 passed, 23 skipped`

## Phase 14 Slice Log

- Complete: Phase 14E closeout — rewrite the status document for the true final Phase 14 state and verify it against a final full-suite rerun.
  Scope:
  - collapsed the “Phase 14 is active” wording into a closed-phase current-state summary
  - rewrote the top-level current-state bullets to describe the final bridge/recovery/version/guardrail outcomes instead of listing in-progress slice landings
  - updated the phase summary so Phase 14 is presented as closed ownership and hygiene cleanup rather than a remaining track
  - reran the full suite after the doc closeout before marking the phase complete
  Tests:
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the status document now matches the real final state of the control-plane, routed-task, and ownership-cleanup rollout
  - final full suite status after Phase 14E: `1972 passed, 23 skipped`

- Complete: Phase 14D remediation — rebalance guardrails toward behavior-level proof.
  Scope:
  - added a narrow zero-import/source-shape check in `tests/test_zero_import_gates.py` proving `app/agents/bridge.py` no longer contains the `_egress_bot(...)` shim
  - added an explicit targeted guard proving the cleaned Telegram/workflow modules no longer import `app.agents.bridge`
  - kept the existing 14A-14C behavior tests as the primary oracles and used the new source-shape checks only as focused backstops
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_zero_import_gates.py tests/test_agents.py tests/test_worker_workflows.py tests/test_registry_service.py -k 'bridge_module_has_no_fake_bot_helper or selected_telegram_and_workflow_modules_no_longer_import_bridge_helpers or admit_registry_delivery_queued_is_accepted or recovery_prepare_action or event_conversation_ref_uses_chat_id_when_no_ref_or_key_is_present or requested_card_uses_neutral_version_when_no_product_version_is_defined or registry_ui_shell_bot_detail_version_falls_back_to_unknown'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - the removed bridge shim and removed Telegram/workflow bridge-helper imports now have narrow direct regression checks
  - behavior-level tests from 14A-14C remain the primary proof of the bridge, recovery, and version contracts
  - full suite status after Phase 14D: `1972 passed, 23 skipped`

- Complete: Phase 14C remediation — remove the internal rollout label from the product surface.
  Scope:
  - changed `AgentRuntime.requested_card()` in `app/agents/runtime.py` to emit a neutral blank version instead of `phase-19-foundation`
  - added focused agent-runtime tests proving the requested card stays neutral and the old internal rollout marker is absent from production runtime code
  - added a registry UI shell regression proving the bot-detail render path still falls back to `unknown` when `bot.version` is blank
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_registry_service.py -k 'requested_card_uses_neutral_version_when_no_product_version_is_defined or agent_runtime_source_has_no_internal_rollout_version_marker or requested_card_uses_agent_capabilities_without_default_skill_fallback or registry_ui_shell_bot_detail_version_falls_back_to_unknown'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - operator-facing bot detail no longer depends on an internal rollout label to populate the version field
  - blank requested-card versions render through the existing registry UI fallback as `unknown`
  - full suite status after Phase 14C: `1970 passed, 23 skipped`

- Complete: Phase 14B remediation — extract generic helpers from bridge and make recovery ref resolution data-driven.
  Scope:
  - moved `telegram_conversation_ref()` and `conversation_key_for_ref()` into `app/identity.py`
  - moved `summarize_text()` into `app/formatting.py`
  - added `resolve_event_conversation_ref(...)` on the identity seam and reused it from both `app/channels/telegram/inbound_context.py` and `app/workflows/recovery/replay.py`
  - removed the stale `bot` parameter from `admit_registry_delivery()` and updated delivery/runtime callers accordingly
  - updated Telegram, workflow, registry-ingress, and test imports so non-registry code no longer depends on generic helper exports from `app.agents.bridge`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_worker_workflows.py -k 'event_conversation_ref or recovery_prepare_action or worker_recovery_for_routed_task_skips_bind_and_notice or worker_recovery_for_conversation_still_binds_and_sends_notice or admit_worker_message'`
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_handlers.py tests/test_control_plane_integration.py tests/test_runtime_dispatch_boundary.py tests/test_channel_egress_factory.py tests/test_handlers_delegation.py tests/test_request_flow.py tests/test_simulator_e2e.py -k 'telegram_conversation_ref or conversation_key_for_ref or registry_channel_action_recovery_replay_executes_request or registry_channel_action_recovery_discard_discards_pending_recovery or handle_registry_routed_result_publishes_parent_timeline_before_retry_on_startup_race or execution_runtime_uses_injected_timeline_and_delegation_callbacks or workflow_context_builder_resolves_registry_conversation_metadata or channel_builds_telegram or channel_builds_registry or dispatch_runtime_uses_injected_collaborators'`
  - `./.venv/bin/python -m pytest -q`
  Verified:
  - bridge now owns only registry-delivery admission helpers; generic ref/text helpers moved to the shared seams that already owned those concerns
  - shared recovery no longer branches on raw `source == "telegram"` to reconstruct refs
  - inbound and recovery ref resolution now share the same explicit-priority chain: `conversation_ref` → `chat_id` → numeric `conversation_key` → raw `conversation_key`
  - full suite status after Phase 14B: `1967 passed, 23 skipped`

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
