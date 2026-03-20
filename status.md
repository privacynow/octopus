# Multi-Registry Connections & Channel Bootstrap Status

## Baseline

- Track: multi-registry connections and channel bootstrap
- Plan: `multiregistry_plan.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace singleton registry assumptions and hardwired channel dispatch with per-connection registry runtime state, dispatcher-owned channel routing, and optional Telegram.

## Slice Log

- Complete: Slice 1 contracts and stable bot identity.
  Scope:
  - added stable runtime `bot_identity.json` persistence in `app/agents/state.py`
  - exposed `bot_identity(data_dir)` and `load_bot_identity_state(data_dir)` without changing existing registry-state behavior
  - added `app/ports/channel.py` with `ChannelDescriptor`, `Channel`, `ChannelBootstrap`, and `ChannelIngress`
  - added `app/runtime/channel_dispatcher.py` with prefix registration, conflict detection, ref-based egress routing, active channel type discovery, descriptor lookup, and ingress lifecycle hooks
  - kept all existing runtime paths intact; no live dispatch or registry behavior changed in this slice
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_channel_dispatcher.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `bot_identity()` creates a stable 32-char runtime id, persists it under `agent/bot_identity.json`, and regenerates safely from corrupt state
  - verified dispatcher routing covers positive and negative cases: telegram ref, registry task ref, unknown ref rejection, and conflicting prefix rejection
  - verified dispatcher ingress lifecycle only builds/starts `ChannelBootstrap` ingresses, not plain `Channel` instances
  Review:
  - slice 1 stays within the existing state seam instead of introducing a parallel runtime state module
  - the new dispatcher is additive and unused by production call sites so there is no slice-1 behavior drift
  - full-suite validation required running outside the sandbox because the existing socket-bind test in `tests/test_octopus_registry_network.py` cannot bind under the sandbox; the elevated rerun passed cleanly
  Verified:
  - stable local bot identity now exists as runtime state, not env/config
  - the new channel contracts and dispatcher are in place for later slices
  - full suite status after slice 1: `1777 passed, 23 skipped`
- Complete: Slice 2 registry connection config and state.
  Scope:
  - added `RegistryConnectionConfig` and `RegistryConnectionState` to the shared agent type layer
  - extended `BotConfig` with `agent_registries` while keeping the old singleton fields projected from the first configured connection
  - taught `load_config()` to parse indexed `BOT_AGENT_REGISTRY_<n>_*` variables and to synthesize a default `agent_registries` entry from the existing singleton env vars
  - added per-connection state persistence under `data/agent/registries/<id>.json` without disturbing the old `registry_state.json` path
  - updated the shared test config factory to project singleton registry inputs into `agent_registries`
  - made `app.agents` lazy-load `AgentRuntime` / `start_agent_runtime_task` so shared agent types can be imported from `config.py` without a package-init cycle
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_agents.py tests/test_config.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified singleton registry env still projects into `cfg.agent_registries` as `registry_id="default"` while preserving the old `agent_registry_url` / `agent_registry_enroll_token` fields
  - verified indexed registry env parses into multiple connection configs in order and projects the first entry back to the old singleton fields
  - verified per-connection state round-trips to `agent/registries/<id>.json`, uses private file permissions, and falls back safely from corrupt JSON
  Review:
  - the new config/state path extends the existing config and state seams instead of introducing a second config loader or second state module
  - the lazy `app.agents` package surface fixed the only slice-2 integration regression at the package boundary instead of moving the new shared dataclasses out of the planned type layer
  - old runtime consumers are still green because the singleton config fields and `registry_state.json` path remain intact for scaffolding
  Verified:
  - per-connection registry config/state now exists without changing current runtime behavior
  - the slice-2 scaffolding for later runtime migration is in place and the repo remains fully green
  - full suite status after slice 2: `1781 passed, 23 skipped`
- Complete: Slice 3 Telegram channel bootstrap.
  Scope:
  - added `app/channels/telegram/channel.py` with `TelegramChannelBootstrap` and `TelegramChannelIngress`
  - kept `app/channels/telegram/bootstrap.py` as the existing PTB application-construction seam and wrapped it instead of duplicating handler-registration logic
  - switched `main.py` from direct `build_bootstrap()` / `run_polling()` / `run_webhook()` calls to dispatcher-managed Telegram ingress startup via `ChannelDispatcher`
  - kept the legacy single-registry runtime path in `post_init` unchanged for this slice; only Telegram lifecycle moved under the dispatcher
  - hardened `ChannelDispatcher.start_all_ingresses()` / `stop_all_ingresses()` so ingress startup failures surface immediately instead of hanging behind a background task
  - removed the now-dead `run_worker_process()` helper after the dispatcher cutover and kept `KeyboardInterrupt` handling aligned across worker, webhook, and polling modes
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_telegram_channel_state.py tests/test_shared_runtime.py tests/test_handlers.py tests/test_config.py tests/test_channel_dispatcher.py tests/test_zero_import_gates.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified dispatcher registration builds exactly one Telegram ingress and routes `telegram:` refs to `TelegramChannelEgress`
  - verified the new Telegram ingress follows PTB startup/shutdown order for polling and webhook paths and skips live updater startup for worker-only processes
  - verified `main.py` now builds Telegram ingress through `ChannelDispatcher` and no longer imports or calls `build_bootstrap()` directly
  - verified ingress startup failures now raise through the dispatcher instead of silently dying in an unmanaged task
  Review:
  - slice 3 reused the existing Telegram bootstrap file as the authoritative handler-registration owner instead of cloning PTB setup into a second module
  - the dispatcher cutover stayed scoped to Telegram; registry startup is still the old `start_agent_runtime_task()` path until slice 4 as planned
  - the only cleanup beyond the plan was removing dead startup code created by the cutover and tightening the dispatcher failure path to avoid a real operability regression
  Verified:
  - Telegram now satisfies the new `ChannelBootstrap` / `ChannelIngress` contract without introducing a parallel Telegram runtime path
  - `main.py` uses dispatcher-managed Telegram ingress startup while preserving current worker and registry scaffolding behavior
  - full suite status after slice 3: `1787 passed, 23 skipped`
- Complete: Slice 4 registry runtime.
  Scope:
  - added `app/agents/registry_runtime.py` with one wrapped `AgentRuntime` per configured registry connection and one sync loop per connection
  - extended `AgentRuntime` to accept an explicit `RegistryConnectionConfig`, per-connection state loading/saving, and an optional `kind_filter` for scoped polling
  - extended `AgentRegistryClient.poll()` with an optional `kind_filter` query so scoped registry polling can be threaded through the existing client seam
  - added runtime-only per-connection state loading in `app/agents/state.py`, including legacy projection from `registry_state.json` for the default connection and dual-write back to the legacy state file for the default connection during scaffolding
  - rewired `main.py` to construct `RegistryRuntime` and start/stop it from the Telegram dispatcher lifecycle instead of calling `start_agent_runtime_task()` directly
  - kept registry egress and ref routing unchanged for this slice; registry channels are still deferred to slice 5 and the old factory still owns registry refs during the scaffolding window
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_agents_runtime.py tests/test_registry_runtime.py tests/test_config.py tests/test_telegram_channel_state.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified per-connection runtime polling annotates every delivered item with `registry_id` before it reaches the delivery handler
  - verified scoped polling uses `channel_input/channel_action` for channel connections and preserves legacy full-scope behavior without changing the old singleton runtime path
  - verified the default connection projects legacy `registry_state.json` into `registries/default.json` semantics on read and dual-writes back to the legacy file on save so old consumers stay green during scaffolding
  - verified `main.py` now starts and stops the registry runtime through Telegram lifecycle hooks instead of the old direct agent-runtime startup helper
  Review:
  - slice 4 extends the existing `AgentRuntime` path instead of forking a second registry runtime implementation, which keeps the battle-tested enrollment/heartbeat/poll loop authoritative
  - the only Telegram ingress change was making `bot_data` initialization resilient for both the real PTB application and the lightweight fake used by the channel-state tests
  - registry ref ownership and outbound routing were intentionally left on the old factory for this slice to avoid mixing the runtime cutover with the channel-registration cutover planned for slice 5
  Verified:
  - per-connection registry runtime ownership now exists without changing registry egress or ref-routing behavior ahead of schedule
  - `main.py` no longer relies on `start_agent_runtime_task()` for the live registry path
  - full suite status after slice 4: `1793 passed, 23 skipped`
- Complete: Slice 5 registry conversation and task channels.
  Scope:
  - added `app/channels/registry/refs.py` with the shared qualified registry ref format helpers:
    `registry:<id>:conversation:<external_id>` and `registry:<id>:task:<task_id>`
  - added `app/channels/registry/channel.py` with `RegistryConversationChannel` and `RegistryTaskChannel` as real dispatcher-owned `Channel` implementations
  - extended `RegistryRuntime` with `register_channels()` so channel/full connections register conversation channels and coordination/full connections register task channels
  - switched `RegistryRuntime.channel_capabilities()` from the slice-4 hardcoded fallback to `dispatcher.active_channel_types()`
  - updated `main.py` to register registry channels after constructing the registry runtime and before runtime startup
  - made `RegistryChannelEgress` connection-aware by inferring/parsing qualified registry refs, carrying `registry_id`, and resolving the correct scoped registry client
  - updated bot-local registry ref generation/admission in `app/agents/bridge.py` and `app/agents/delivery.py`:
    Telegram refs now use stable `bot_identity`, routed task refs are qualified, registry conversation refs are qualified on admission, and scoped timeline/bind calls target the correct registry connection
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_agents_runtime.py tests/test_registry_runtime.py tests/test_registry_adapter.py tests/test_config.py tests/test_channel_dispatcher.py tests/test_channel_egress_factory.py tests/test_handlers.py tests/test_handlers_delegation.py tests/test_agents_delegation_boundary.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_zero_import_gates.py::test_agents_delivery_has_no_channel_imports tests/test_agents.py::test_handle_registry_routed_result_publishes_parent_timeline_before_retry_on_startup_race tests/test_handlers.py::test_approve_delegation_from_registry_delivery tests/test_handlers.py::test_cancel_delegation_from_registry_delivery tests/test_handlers.py::test_registry_routed_task_result_report_failure_does_not_escape_worker tests/test_handlers.py::test_registry_channel_parent_resumes_through_registry_channel`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified channel-capable registry connections now contribute `"registry"` through dispatcher registration, while coordination-only task channels do not
  - verified qualified task refs and conversation refs route to registry-scoped egress without changing the old outbound factory yet
  - verified `telegram_conversation_ref()` now uses the stable runtime `bot_identity` instead of a registry-issued `agent_id`
  - verified legacy `registry:<id>`-style conversation refs already present in tests/session state still survive the scaffolding window because qualification preserves legacy `registry:` refs instead of double-wrapping them
  Review:
  - registry ref parsing/formatting was centralized in one helper module to avoid duplicating string-shape logic across bridge, runtime, egress, and tests
  - registry channels remain plain `Channel` instances, not fake `ChannelBootstrap`s; all registry polling still belongs to `RegistryRuntime`
  - the registry service still stores raw conversation IDs internally; the bot now qualifies them at admission because `registry_id` is a local bot/runtime connection label, not a server-side store field
  Verified:
  - dispatcher-owned registry channel/task routing is now in place for qualified refs
  - `channel_capabilities` is now derived from registered channels instead of `agent_mode`
  - full suite status after slice 5: `1797 passed, 23 skipped`
- Complete: Slice 6 replace hardwired outbound dispatch.
  Scope:
  - deleted `app/channel_egress_factory.py` and removed `conversation_channel_name()` from `app/runtime/composition.py`
  - rewired Telegram worker and registry delivery resume handling to use `ChannelDispatcher.create_egress()` instead of the deleted hardwired factory
  - threaded the dispatcher through `TelegramRuntime`, `RegistryDeliveryRuntime`, `main.py`, and the shared handler test runtime so all worker-owned egress creation now goes through the dispatcher-owned prefix map
  - replaced `trust_tier_for_source()` with `trust_tier_for_ref()` in `app/runtime/work_admission.py`, using dispatcher descriptors for trusted registry channels while preserving user-based trust for Telegram/public mode
  - removed orchestration-level channel branching from execution context and worker admission by moving ref/channel lookup through dispatcher queries and descriptor capabilities
  - tightened Telegram ingress/recovery paths around the new ref-based model by persisting Telegram conversation refs on fresh inbound messages and routing recovery trust through the dispatcher-aware helper
  - extracted Telegram inbound ref/trust helpers into `app/channels/telegram/inbound_context.py` and moved the message ref-persistence helper into `app/channels/telegram/normalization.py` to stay under the ingress hard line-count gate
  - updated handler/simulator tests to use qualified registry conversation/task refs so the new no-shim dispatcher contract is exercised end to end
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_worker_workflows.py tests/test_channel_egress_factory.py tests/test_request_flow.py::test_export_uses_resolved_skills_not_raw_session tests/test_runtime_dispatch_boundary.py tests/test_handlers.py tests/test_agents.py::test_handle_registry_routed_result_publishes_parent_timeline_before_retry_on_startup_race tests/test_config.py::test_main_registry_runtime_starts_and_stops_with_dispatcher_lifecycle`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_worker_workflows.py tests/test_channel_egress_factory.py tests/test_request_flow.py::test_export_uses_resolved_skills_not_raw_session tests/test_runtime_dispatch_boundary.py tests/test_handlers.py tests/test_agents.py::test_handle_registry_routed_result_publishes_parent_timeline_before_retry_on_startup_race tests/test_runtime_composition.py tests/test_zero_import_gates.py::test_telegram_ingress_line_count_stays_below_hard_cap`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_config.py tests/test_handlers.py tests/test_worker_workflows.py tests/test_channel_egress_factory.py tests/test_runtime_dispatch_boundary.py tests/test_request_flow.py tests/test_runtime_composition.py tests/test_zero_import_gates.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_simulator_e2e.py::test_simulator_registry_message_runs_through_registry_surface_output`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `rg` returns no remaining `create_channel_egress`, `conversation_channel_name`, or `trust_tier_for_source` hits under `app/`
  - verified dispatcher-based trust preserves public Telegram behavior while still treating registry channels/tasks as trusted
  - verified registry conversation/task refs now route only when qualified (`registry:<id>:conversation:*`, `registry:<id>:task:*`), with simulator and handler coverage exercising the no-shim contract
  - verified `app/channels/telegram/ingress.py` is back under the hard line-count cap at exactly `1500` lines after moving helper logic out
  Review:
  - the slice stayed within existing seams: dispatcher for ref ownership, work admission for trust resolution, recovery workflow for replay trust, and Telegram normalization for fresh inbound ref persistence
  - no alternate outbound path remains; both worker-owned Telegram execution and routed-result resume now go through the same dispatcher contract
  - when the broader regression run exposed lingering old-format registry refs in tests/simulator, the fix was to update callers to the plan’s qualified ref format rather than reintroduce compatibility shims
  Verified:
  - hardwired outbound dispatch is gone and orchestration-level channel branching is reduced to dispatcher/descriptor queries
  - ref-based trust and execution context logic now align with the channel contract instead of string checks
  - full suite status after slice 6: `1797 passed, 23 skipped`
- Complete: Slice 7 coordination provenance.
  Scope:
  - added `DiscoveredAgentRef` with explicit `registry_id` provenance and extended `RegistryRuntime` with coordination-aware discovery fan-out, per-registry client lookup, and target-registry resolution
  - extended delegated task/session state to persist `registry_id` per child task and threaded that provenance through delegation planning, submission, and routed-result application
  - extended durable inbound transport payloads so registry-originated `InboundMessage` and `InboundAction` events persist `registry_id` instead of reconstructing it later from ref guesses
  - rewired Telegram `/discover` to use `RegistryRuntime` instead of the old singleton registry client path, with correct not-enrolled vs degraded messaging for coordination/full connections
  - rewired routed-task finalization to report results back through the explicit originating registry connection when `registry_id` is present, while keeping the singleton fallback for older direct-call seams during scaffolding
  - updated handler/runtime/presenter/session tests to exercise cross-registry provenance, registry-scoped delegation submission, explicit registry result reporting, and inbound payload round-trips
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_registry_runtime.py tests/test_handlers_delegation.py tests/test_handlers.py tests/test_execution_finalization.py tests/test_session_state.py tests/test_orchestration.py tests/test_runtime_inbound_types.py tests/test_telegram_presenters.py tests/test_agents_delegation_boundary.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_registry_runtime.py tests/test_handlers.py tests/test_handlers_delegation.py tests/test_execution_finalization.py tests/test_session_state.py tests/test_orchestration.py tests/test_runtime_inbound_types.py tests/test_transport.py tests/test_work_queue.py tests/test_telegram_presenters.py tests/test_agents_delegation_boundary.py tests/test_telegram_delegation_channel.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_zero_import_gates.py::test_telegram_ingress_line_count_stays_below_hard_cap`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified discovery now fans out across coordination/full registry connections and returns results tagged with the owning `registry_id`
  - verified delegation approval persists resolved registry provenance on each child task and routes routed-task submission through the owning registry connection instead of a singleton client
  - verified registry-originated inbound messages/actions and child-task finalization now carry/report `registry_id` explicitly through durable transport and runtime finalization paths
  - verified `app/channels/telegram/ingress.py` stays under the hard line-count gate after the slice-7 discover changes
  Review:
  - provenance now lives in the correct owners: `RegistryRuntime` for per-registry lookup, session state for per-task routing, and durable inbound payloads for worker/finalization replay
  - no new parallel discovery/delegation subsystem was introduced; existing handler, worker, and finalization seams were extended in place
  - the remaining singleton fallback is intentionally confined to direct non-runtime delegation/finalization call sites and can be removed cleanly in later cleanup slices
  Verified:
  - multi-registry discovery and delegated-task routing now preserve explicit registry provenance end to end
  - routed task results return through the originating registry connection instead of an implicit singleton
  - full suite status after slice 7: `1802 passed, 23 skipped`
- Complete: Slice 8 Telegram mirroring fan-out.
  Scope:
  - added `bind_conversation_to_registries()` and `publish_timeline_to_registries()` in `app/agents/bridge.py` so Telegram-originated mirroring fans out through `RegistryRuntime.clients_for_mirroring()` instead of the old singleton registry client path
  - rewired `TelegramChannelEgress` binding, input mirroring, outcome mirroring, and generic timeline publication to use registry-runtime fan-out when available while preserving the existing single-registry fallback for non-runtime seams
  - threaded `registry_runtime` through Telegram egress construction and worker finalization so usage/timeline events for Telegram refs fan out to channel/full connections, while registry refs stay single-registry and scoped by `registry_id`
  - rewired Telegram progress and delegation-plan timeline publication to the same fan-out helpers so Telegram mirroring uses one consistent path instead of mixing runtime fan-out with singleton bridge calls
  - added direct tests for partial-failure isolation, coordination-only skipping, Telegram egress fan-out, progress/delegation fan-out, and worker timeline routing
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_agents.py tests/test_registry_runtime.py tests/test_telegram_channel_egress.py tests/test_telegram_progress_module.py tests/test_telegram_delegation_channel.py tests/test_telegram_worker_timeline.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_handlers.py tests/test_execution_finalization.py tests/test_telegram_channel_state.py tests/test_workitem_integration.py tests/test_agents.py tests/test_registry_runtime.py tests/test_telegram_channel_egress.py tests/test_telegram_progress_module.py tests/test_telegram_delegation_channel.py tests/test_telegram_worker_timeline.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_zero_import_gates.py::test_worker_dispatch_no_longer_contains_inline_execution_workflow_logic tests/test_telegram_worker_timeline.py tests/test_telegram_channel_egress.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `RegistryRuntime.clients_for_mirroring()` returns only channel/full connections, so coordination-only registries receive no Telegram mirrors
  - verified Telegram-originated binding, progress, delegation, message, outcome, and usage timeline publication now route through the same registry-runtime fan-out seam when the runtime is available
  - verified the worker keeps registry conversation/task timeline publication single-scoped and ref-aware instead of incorrectly fanning registry refs out to every mirroring target
  - verified the slice still satisfies the no-inline-worker-logic gate by removing the old literal singleton timeline call from `worker.py`
  Review:
  - the slice extends the existing registry-runtime ownership boundary instead of introducing a second mirroring helper object or teaching the dispatcher about registry clients
  - Telegram mirroring now has a single authoritative fan-out path; the remaining singleton helper is intentionally confined to registry-scoped publication and non-runtime fallbacks until the later cleanup slices remove those old seams
  - `app/channels/telegram/progress.py` already had a local transient-network hardening change in flight; it was included in this slice because the file had to be touched for fan-out and the user explicitly approved committing it
  Verified:
  - Telegram mirrors now fan out to every channel/full registry connection with partial-failure isolation and coordination-only skipping
  - Telegram progress, delegation, and finalization timeline events no longer leave a mixed singleton/fan-out path behind
  - full suite status after slice 8: `1811 passed, 23 skipped`
- Complete: Slice 9 registry service scope enforcement (both stores).
  Scope:
  - added `registry_scope` as a first-class persisted agent field in both SQLite and Postgres registry stores, with SQLite auto-migration, a new Postgres migration (`0012_registry_scope.sql`), and the runtime enrollment card now sending the configured scope at enroll time
  - added shared `RegistryScopeError`, `require_registry_scope()`, and delivery-kind filtering helpers in `store_base.py` so scope enforcement semantics are defined once and reused by both store implementations
  - enforced `registry_scope` on protected agent operations: channel-only scopes can publish timeline and bind conversations, coordination-only scopes can perform discovery and routed-task/result work, and poll now filters queued deliveries by allowed kind for the authenticated scope
  - updated the FastAPI registry endpoints to translate scope failures into explicit `403` responses with `error_code=registry_scope_not_permitted` instead of generic authorization failures
  - extended the backend-neutral registry store contract tests and service API tests to cover persisted scope, scope rejection, and channel/coordination delivery filtering across both SQLite and Postgres
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/contracts/test_registry_store_contract.py tests/test_registry_service.py tests/test_agents.py tests/test_registry_runtime.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_registry.py tests/test_registry_service.py tests/contracts/test_registry_store_contract.py tests/test_agents.py tests/test_registry_runtime.py tests/test_handlers.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified channel-only agents now receive `403` on discovery and coordination-only agents receive `403` on channel timeline/bind endpoints with the new structured scope error payload
  - verified store contract tests pass for both SQLite and Postgres with `registry_scope` persisted, `assert_agent_scope()` enforced, and poll filtering returning only the delivery kinds allowed for each scope
  - verified the SQLite legacy-migration test now upgrades older registry databases to schema version `6`, including the new `registry_scope` column, while preserving the earlier channel-vocabulary and token-hashing migrations
  Review:
  - scope enforcement stays registry-specific; `role` remains persona metadata and was not overloaded
  - the parity work landed through shared helpers plus both concrete stores and a migration file, which keeps SQLite/Postgres behavior aligned instead of letting one drift ahead
  - the slice deliberately avoids inventing a second auth layer or queue path; enforcement happens where the existing registry token and delivery/store seams already exist
  Verified:
  - registry service scope enforcement now exists end to end across HTTP, SQLite, Postgres, and runtime enrollment
  - coordination-only connections no longer receive channel deliveries, and channel-only connections cannot access coordination endpoints
  - full suite status after slice 9: `1821 passed, 23 skipped`
- Complete: Slice 10 Telegram optionality.
  Scope:
  - updated `validate_config()` so startup now requires at least one ingress-capable channel instead of always requiring `TELEGRAM_BOT_TOKEN`
  - added `build_worker_bundle()` in `app/channels/telegram/bootstrap.py` so registry-only processes can reuse the existing Telegram worker/runtime collaborators without constructing PTB ingress
  - rewired `main.py` to register Telegram only when a token is configured and to start registry-only processes through `run_dispatcher_process(..., startup=..., shutdown=...)`
  - kept the existing Telegram lifecycle path intact by preserving `post_init` / `post_shutdown` ownership when Telegram ingress is present, while using the same background-runtime helpers for the no-Telegram path
  - added config and startup tests covering channel-capable registry-only bots, coordination-only/no-channel rejection, and registry-only process startup without Telegram bootstrap
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_config.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_config.py tests/test_registry_runtime.py tests/test_telegram_channel_state.py tests/test_handlers.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified registry-only startup uses `build_worker_bundle()` and `RegistryRuntime` without constructing `TelegramChannelBootstrap`
  - verified no-channel bots are rejected while channel/full registry connections satisfy the ingress requirement without a Telegram token
  - verified Telegram-present startup still goes through the existing dispatcher-owned Telegram ingress path and only builds ingresses once
  Review:
  - the slice extends existing seams instead of inventing a registry-only runtime framework: dispatcher still owns ingress lifecycle, Telegram bootstrap still owns PTB app construction, and the shared background-runtime helpers own worker/registry startup for both paths
  - `build_worker_bundle()` factors reusable worker/runtime construction out of `build_bootstrap()` so registry-only mode does not duplicate Telegram execution setup
  - registry-only support intentionally stops at the plan boundary here; credential-store requirements and other non-channel runtime concerns remain unchanged and were not broadened into speculative config rules
  Verified:
  - Telegram is now optional for bots that have at least one channel-capable registry connection
  - coordination-only/no-channel bots still fail fast at config validation
  - full suite status after slice 10: `1824 passed, 23 skipped`
- Complete: Slice 11 Octopus CLI multi-registry support.
  Scope:
  - added shell helpers for parsing, counting, clearing, and writing registry connections so `./octopus` can manage indexed `BOT_AGENT_REGISTRY_<n>_*` env entries instead of a singleton registry pair
  - updated `./octopus` registry connect/setup flows to capture `registry_scope`, derive stable local registry connection ids, write indexed env vars, verify enrollment against per-connection state files, and support adding or removing additional registry connections
  - updated CLI status output to show every configured registry connection with id, scope, connectivity state, and URL, while preserving the existing top-level bot/provider/local-registry summary
  - kept `cmd_doctor` on the existing doctor output seam and added coverage proving per-connection health lines survive operator formatting
  - centralized run/doctor env sanitization in `scripts/app/env-setup.sh`, including indexed registry vars, so parent-shell overrides do not corrupt the new multi-registry env model
  - fixed two slice-11 integration issues during review: replaced `mapfile` with portable bash loops for macOS shell compatibility, and updated the “unused local registry” check to inspect all configured registry connections instead of only the primary one
  Tests:
  - `bash -n octopus scripts/lib/bot.sh scripts/lib/state.sh scripts/app/env-setup.sh scripts/app/run.sh scripts/app/doctor.sh`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_full_mode.py tests/test_octopus_cli_contracts.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_full_mode.py tests/test_octopus_first_bot_flow.py tests/test_octopus_cli_contracts.py tests/test_octopus_provider_auth.py tests/test_octopus_registry_network.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified first-bot, add-bot, connect, switch, and add-second-registry flows now write indexed registry vars with explicit scope and without introducing `BOT_ID` into env
  - verified `cmd_status` can display multiple registry connections for a single bot and that `cmd_doctor` preserves per-connection health lines after operator formatting
  - verified the new shell helpers still read the old singleton registry keys during the scaffolding window, while all active write paths now emit indexed registry entries
  Review:
  - the slice extends the existing `./octopus` env/state helpers instead of creating a second registry-config path; all CLI registry writes now go through the same shell helper seam
  - registry-connectivity display stays a CLI concern and reads runtime state via the existing compose/runtime boundary rather than inventing a separate host-side state cache
  - the indexed-env unsetting in `env-setup.sh` was necessary to keep the runtime boot path consistent with the new CLI write model and to avoid parent-shell override regressions
  Verified:
  - Octopus now understands multi-registry bot envs, captures per-connection scope, and can append additional registry connections
  - CLI status/doctor output now reflects the multi-registry runtime model instead of a single-registry shortcut
  - full suite status after slice 11: `1828 passed, 23 skipped`

# Octopus CLI Implementation Status

## Baseline

- Track: `./octopus` unified CLI
- Plan: `PLAN-octopus-cli.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace the legacy startup scripts and env shim with a single `./octopus` entrypoint and `.deploy/`-based state model.

## Slice Log

- Complete: Slice 1 split the legacy env shim into focused libraries.
  Scope:
  - created `scripts/lib/bot.sh`, `scripts/lib/docker.sh`, `scripts/lib/provider.sh`, `scripts/lib/ui.sh`, `scripts/lib/state.sh`, and `scripts/lib/registry.sh`
  - moved all existing legacy env helper functions into the focused libraries
  - kept a temporary compatibility shim for the slice
  - rewired `start_instance.sh`, `stop_instance.sh`, `logs_instance.sh`, `provider_login.sh`, and `provider_status.sh` to source focused libraries directly
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/docker.sh scripts/lib/provider.sh scripts/lib/ui.sh scripts/lib/state.sh scripts/lib/registry.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh`
  - `.venv/bin/python -m pytest -q -n 4 tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - the low-level helpers still printed the expected missing-config guidance before the legacy shim was removed
  - provider status still surfaced the expected missing-config guidance before the legacy shim was removed
  Verified:
  - the library split landed without changing current startup/provider behavior
  - the temporary shim preserves the existing operator-script test contract while callers move to the focused libraries
  - full suite remained green after the refactor
- Complete: Slice 2 introduce `.deploy/` state layout and slug-based wrappers.
  Scope:
  - add `scripts/lib/state.sh` queries and `.deploy/` directory helpers
  - add `normalize_slug()` to `scripts/lib/bot.sh`
  - rewrite `bot_compose()` around `.deploy/bots/<slug>/.env`
  - add `registry_compose()` and `provider_compose()`
  - update `start_instance.sh`, `stop_instance.sh`, and `logs_instance.sh` to prefer slug-based `.deploy` bots while keeping the old instance fallback for this slice only
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/state.sh scripts/lib/docker.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - created a temporary `.deploy/bots/slice2-test/.env` and verified `start_instance.sh` / `stop_instance.sh` resolved the slug-based bot path
  - confirmed ordinary bot commands no longer require registry env interpolation just to parse the compose file
  Verified:
  - `.deploy/` is now the canonical state root for the new wrappers
  - slug-based low-level bot scripts work while the old instance fallback remains available for this transitional slice
  - the compose wrappers now inject temporary registry placeholders for non-registry bot/profile commands, avoiding unrelated compose parse failures
- Complete: Slice 3 shared provider auth volume.
  Scope:
  - populated `scripts/lib/provider.sh` with shared auth directory helpers, authoritative auth checks, and `.authed` hint updates
  - rewired provider login/status scripts to use `provider_compose()` and shared `.deploy/provider-auth/<provider>/` bind mounts
  - changed the bot and provider compose services to mount provider auth at `/home/bot/.provider-auth` and persist bot data only at `/home/bot/data`
  - updated `docker-entrypoint.sh` to create provider-auth symlinks before privilege drop and to chown only `/home/bot/data`
  - aligned provider logout cleanup with the auth paths actually used by the current images
  Probe:
  - built both provider images and verified live auth paths before finalizing the mount model
  - Claude currently writes auth/state under `/home/bot/.claude` and `/home/bot/.claude.json`
  - Codex currently writes auth/state under `/home/bot/.codex`
  - `.config/...` paths were not observed in this build, so they were not carried into the new shared-auth layout
  Tests:
  - `bash -n scripts/lib/provider.sh scripts/lib/docker.sh scripts/docker/docker-entrypoint.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh scripts/provider/provider_logout.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_provider_auth.py tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - rebuilt both provider images and verified the runtime entrypoint now exposes `/home/bot/.claude`, `/home/bot/.claude.json`, and `/home/bot/.codex` as symlinks into `/home/bot/.provider-auth`
  - verified two separate bot slugs can mount the same Claude auth directory without forcing a second login flow
  - confirmed host-side files under `.deploy/provider-auth/claude/` remained owned by the host user instead of being mutated by container startup
  Verified:
  - provider auth is now shared per provider, not per bot
  - the authoritative auth decision path is container-backed, while `.authed` remains only a cache for fast status UX
  - the new entrypoint behavior avoids chowning host-mounted auth state while preserving writable bot data under `/home/bot/data`
- Complete: Slice 4 shared Docker network with registry alias.
  Scope:
  - added an external `octopus-net` default network to the main compose file
  - introduced the local registry network alias `registry` so bot containers can use `http://registry:8787`
  - populated `scripts/lib/registry.sh` with port selection and local-registry bootstrap helpers
  - moved registry secrets and port state to `.deploy/registry/.env`
  - rewired `scripts/registry/start.sh` and `scripts/registry/stop.sh` around the new wrappers
  - cleaned up generated Docker names so the local registry now comes up as `octopus-registry-service-1` instead of `octopus-registry-registry-1`
  - renamed the shared provider helper project to `octopus-auth-<provider>` to avoid another duplicated generated container name
  Tests:
  - `bash -n scripts/lib/state.sh scripts/lib/registry.sh scripts/lib/docker.sh scripts/registry/start.sh scripts/registry/stop.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_registry_network.py tests/test_operator_scripts.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - started the local registry via `./scripts/registry/start.sh` and verified a bot container could reach `http://registry:8787/healthz` over the shared network alias
  - verified the cleaned-up generated registry container name was `octopus-registry-service-1`
  - confirmed start/stop now remove renamed-service orphans instead of leaving stale registry containers behind
  Cleanup:
  - pruned unused Docker builder cache, dangling images, and stopped containers after the slice to keep local disk usage under control
  Verified:
  - the local registry network path is now real end-to-end, not just file-declared
  - the registry lifecycle uses `.deploy/registry/.env` as the only local registry config source
  - the singleton registry naming is cleaner and no longer repeats `registry` in generated container or volume names
- Complete: Slice 5 early Telegram token validation.
  Scope:
  - added `telegram_token_format_valid()` to `scripts/lib/bot.sh` for a fast format gate before any network work
  - added `validate_telegram_token()` to `scripts/lib/bot.sh` using a Python `urllib` helper fed by stdin instead of putting the token in command args
  - updated the helper contract to return the Telegram identity triple: `id`, `username`, and `first_name`
  Tests:
  - `bash -n scripts/lib/bot.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_token_validation.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified the helper can be faked in tests to return a valid identity triple without exposing the token in the child `python3` argv
  - verified rejected-token paths return nonzero and produce no helper output
  - verified a live `ps` scan during validation did not show the test token string in process args
  Verified:
  - Telegram token validation now happens with a dedicated helper that is safe to call before any Docker or provider work
  - the identity fields needed by later `./octopus` flows are now available from a single `getMe` call
  - the token-leak constraint is covered by both positive and negative tests, not just by code inspection
- Complete: Slice 6 first-bot `./octopus` flow.
  Scope:
  - added the root `./octopus` entrypoint and made it sourceable for shell-level contract tests
  - implemented the first-bot quick setup flow with Telegram identity validation, provider choice, provider auth bootstrap, env-file creation, doctor checks, token-repair loop, and background startup verification
  - persisted both Octopus-facing identity fields (`BOT_TELEGRAM_ID`, `BOT_TELEGRAM_USERNAME`, `BOT_DISPLAY_NAME`, `BOT_SLUG`) and current runtime-facing fields (`BOT_INSTANCE`, `BOT_AGENT_SLUG`, `BOT_AGENT_DISPLAY_NAME`)
  - added duplicate-bot detection keyed by `BOT_TELEGRAM_ID` so the same Telegram bot is not silently re-added as a second local deployment
  - added reusable state helpers for Telegram identity lookups ahead of the later management slices
  Tests:
  - `bash -n octopus scripts/lib/state.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_first_bot_flow.py tests/test_octopus_token_validation.py`
  - `.venv/bin/python -m pytest -q tests/contracts/test_transport_store_contract.py -k 'test_get_usage_since_filters_by_time and postgres' -n 0`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - ran a stubbed first-bot bootstrap simulation under Bash and verified the flow prints `This token belongs to <name> (@<username>).` with no naming prompt
  - verified the generated `.deploy/bots/example-bot/.env` contained the Telegram identity fields plus the current runtime fields needed by `app.config`
  - verified the success box references the new `./octopus` command surface
  Notes:
  - one unrelated postgres contract test was timing-sensitive on the first parallel full-suite pass; the isolated rerun passed immediately and the subsequent full-suite rerun was green
  Verified:
  - the first-run contract is now token-driven instead of asking the user to name the bot a second time
  - the first-bot flow preserves the token-repair and doctor-check behavior from the old guided path while moving state into `.deploy/bots/<slug>/.env`
  - Telegram identity is now the authoritative source for first-bot local identity, while the duplicate guard prevents accidental double deployment of the same Telegram bot
- Complete: Slice 7 multi-bot management.
  Scope:
  - implemented `./octopus status`, `./octopus start`, `./octopus stop`, `./octopus logs`, and `./octopus doctor`
  - added bot selection helpers with single-bot auto-selection and multi-bot interactive choice prompts
  - added the top-level state-aware main menu plus the first management submenu shell
  - switched status and management output to identity-aware labels using `BOT_DISPLAY_NAME` and `BOT_TELEGRAM_USERNAME`
  - kept “Add a bot” on the same token-driven bootstrap path as first-run so additional bots do not reintroduce a naming prompt
  - fixed a portability bug in env parsing where non-POSIX `\\s` handling in shell readers could corrupt values like `standalone`
  Tests:
  - `bash -n octopus scripts/lib/bot.sh scripts/app/start_instance.sh scripts/provider/build_bot_image.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified `cmd_status` prints the expected no-bots guidance when `.deploy/bots/` is empty
  - verified a single configured bot is auto-selected for `start`, `stop`, `logs`, and `doctor`
  - verified the manage menu header shows the human-facing bot identity instead of the raw slug
  Verified:
  - the public `./octopus` surface now supports day-2 bot operations instead of only first-run bootstrap
  - multi-bot selection works without regressing the single-bot “don’t ask unnecessary questions” rule
  - the shared env-reader fix closed a real bug in active scripts, not just in the new CLI path
- Complete: Slice 8 registry connect and switch flows.
  Scope:
  - implemented local and remote registry connection flows for standalone bots
  - implemented local→remote, remote→local, and disconnect flows for already-registered bots
  - upgraded “Add a bot” to support creating a new bot directly in registry mode while keeping Telegram identity as the only naming source
  - added `./octopus registry` local-registry status/start/stop/logs management
  - added state-based enrollment verification using the bot’s persisted `registry_state.json`, with doctor output and filtered logs only as fallback diagnostics
  - cleared persisted registry runtime state before registry target changes so stale `agent_id` / `agent_token` values are not reused against the wrong registry
  Tests:
  - `bash -n octopus scripts/lib/bot.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py tests/test_octopus_registry_network.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified a standalone bot env can be rewritten into local-registry mode with the expected `BOT_AGENT_REGISTRY_URL` / `BOT_AGENT_REGISTRY_ENROLL_TOKEN` values
  - verified disconnect removes registry keys instead of leaving empty stubs behind
  - verified non-HTTPS remote registry URLs are rejected before any config change is written
  Verified:
  - registry attachment is now bot-scoped, not a global checkout switch
  - success messages stay context-aware and only print the localhost UI URL for local registry flows
  - registry switching now accounts for persisted runtime identity, preventing a subtle stale-token bug during re-enrollment
- Complete: Slice 9 full mode, guided edit, and advanced options.
  Scope:
  - implemented `./octopus --full` and full-mode setup paths for both first-bot and add-bot creation
  - extended bot env creation to persist full-mode settings such as role, tags, description, skills, allowed users, working directory, timeout, and completion webhook URL
  - made display name editable in the guided settings menu while keeping the Telegram-derived slug immutable
  - added guided edit flows for display name, role, tags, allowed users, timeout, and full-config editor handoff
  - split generic restart behavior from registry-target restarts so ordinary config edits do not wipe persisted registry identity
  - added the first advanced menu with full-setup entry and webhook-mode configuration
  Tests:
  - `bash -n octopus tests/test_octopus_full_mode.py`
  - `.venv/bin/python -m pytest -q tests/test_octopus_full_mode.py tests/test_octopus_registry_management.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified full-mode env generation writes both bot-local settings and registry settings when full setup chooses registry mode
  - verified display-name edits update both `BOT_DISPLAY_NAME` and `BOT_AGENT_DISPLAY_NAME`
  - verified clearing allowed users through the guided menu restores `BOT_ALLOW_OPEN=1` instead of preserving stale restrictions
  Verified:
  - full mode now extends the same Telegram-identity-first bootstrap path instead of reintroducing a naming prompt
  - guided edit behavior matches the product split: display name is editable, slug is not
  - advanced config paths no longer depend on raw env editing as the primary user experience
- Complete: Slice 10 removed the legacy startup surface and updated docs/tests.
  Scope:
  - deleted the legacy guided startup script, shared-runtime startup script, and temporary env shim
  - removed all remaining flat-env and old-script fallback logic from active shell helpers and provider scripts
  - tightened the low-level helper scripts to operate only on `.deploy/bots/<slug>/.env`
  - aligned the compose files, config loader, registry UI copy, and helper scripts with the `./octopus` + `.deploy/` contract
  - rewrote the README around `./octopus` as the only primary operator command
  - removed obsolete legacy-surface tests and updated the remaining docs/doctor/config tests to the new paths and wording
  Tests:
  - `bash -n scripts/lib/bot.sh scripts/lib/docker.sh scripts/app/start_instance.sh scripts/app/stop_instance.sh scripts/app/logs_instance.sh scripts/provider/build_bot_image.sh scripts/provider/provider_login.sh scripts/provider/provider_status.sh scripts/provider/provider_logout.sh scripts/app/dev_up.sh scripts/db/dev_up_postgres.sh octopus`
  - `.venv/bin/python -m pytest -q tests/test_readme_operator.py tests/test_startup_diagnostics.py tests/test_config.py tests/test_doctor.py tests/test_octopus_registry_network.py tests/test_octopus_provider_auth.py tests/test_octopus_management.py tests/test_octopus_registry_management.py tests/test_octopus_full_mode.py tests/test_octopus_first_bot_flow.py`
  - `.venv/bin/python -m pytest -q tests/test_readme_commands.py tests/test_readme_operator.py tests/e2e/test_compose_flows_probe.py`
  - `.venv/bin/python -m pytest -q tests/contracts/test_transport_store_contract.py -k 'test_get_usage_since_filters_by_time and postgres' -n 0`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - repo-wide grep for the removed startup surface and flat env paths returned zero matches
  - verified the cleaned README still covers first-time setup, daily commands, and registry UI with `./octopus`
  - verified the provider and helper scripts no longer depend on hidden flat env files
  Verified:
  - the repo no longer ships or references the removed startup surface
  - the active shell/config/docs path is now coherent around `.deploy/` and `./octopus`
  - the cleanup did not leave stale breakage behind; the full suite passed after the regressions were fixed
- Complete: Slice 11 added final CLI contract coverage and reran the full suite.
  Scope:
  - added `tests/test_octopus_cli_contracts.py` for slug normalization, state queries, menu routing, compose-wrapper contracts, provider-auth marker behavior, and the repo-wide no-legacy-surface assertion
  - expanded README contract coverage so the shipped docs retain both the `./octopus` operator surface and the user-facing Telegram command list
  - fixed a real shell bug in `provider_is_authed()` where the old `! ...; $?` pattern masked provider failures and could leave `.authed` markers stale
  - cleaned `.gitignore` to drop old flat-env patterns and legacy comments so the repo-level zero-reference check is truthful
  Tests:
  - `bash -n octopus scripts/lib/state.sh scripts/lib/bot.sh scripts/lib/docker.sh scripts/lib/provider.sh scripts/lib/registry.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_cli_contracts.py tests/test_octopus_token_validation.py tests/test_octopus_provider_auth.py tests/test_octopus_registry_network.py tests/test_octopus_management.py tests/test_octopus_first_bot_flow.py tests/test_readme_commands.py tests/test_readme_operator.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - verified the repo-wide banned-surface scan stays clean without excluding shipped source files
  - verified the compose-wrapper tests capture the actual argument ordering after the `.deploy/` cleanup
  - verified the authoritative provider-auth check now sets and clears `.authed` markers correctly
  Verified:
  - the final CLI contract now has direct tests for the remaining slice-11 acceptance gaps instead of relying on incidental coverage
  - the new tests found and drove out one real provider-auth bug before the final pass
  - final suite status: `1769 passed, 23 skipped`
- Follow-up: plan/example alignment after final rollout review.
  Scope:
  - updated the plan’s provider-auth path sections to match the slice-3 probe (`.claude`, `.claude.json`, `.codex`) instead of the earlier `.config/...` assumptions
  - documented the `BOT_DATA_DIR` fallback in Python config as a residual risk for host/debug runs, while noting the compose path sets `/home/bot/data` correctly
  - deleted the legacy root env artifacts and replaced the tracked reference template with `.deploy/bots/.env.example`
  - rewired `scripts/host/setup_instance.sh` to use the new tracked example path
  Tests:
  - `bash -n scripts/host/setup_instance.sh`
  - `.venv/bin/python -m pytest -q tests/test_octopus_cli_contracts.py tests/test_octopus_provider_auth.py tests/test_readme_operator.py tests/test_readme_commands.py`
  - `.venv/bin/python -m pytest -q -n 4`
  Verified:
  - the written plan now matches the probed implementation for provider auth
  - the repo no longer carries the legacy root env artifacts
  - full suite status after the follow-up remained `1769 passed, 23 skipped`
- Complete: Slice 12 removed the remaining singleton registry scaffolding.
  Scope:
  - deleted the singleton registry config fields from `BotConfig` and removed the internal projection back from `agent_registries[0]`
  - removed the legacy single-file registry runtime state path and collapsed runtime persistence onto `data/agent/registries/<id>.json`
  - deleted the singleton bridge helper and moved registry client/state lookup to per-connection resolution
  - updated runtime health, delegation, registry egress, and CLI state checks to operate on explicit registry connections only
  - finished the final consumer cleanup in tests, E2E flows, and CLI helpers so the repo no longer references the removed singleton paths
  - tightened the Telegram worker timeline mirroring check to use dispatcher channel resolution instead of hardcoded prefix branching
  Tests:
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_config.py tests/test_agents.py tests/test_agents_runtime.py tests/test_registry_runtime.py tests/test_doctor.py tests/test_handlers_delegation.py tests/test_agents_delegation_boundary.py tests/test_registry_adapter.py tests/test_channel_egress_factory.py tests/test_worker_workflows.py tests/test_simulator_e2e.py`
  - `./.venv/bin/python -m pytest -q -n 0 tests/test_telegram_worker_timeline.py tests/test_handlers.py -k "registry_routed_task_executes_and_reports_result or registry_routed_task_result_report_failure_does_not_escape_worker or registry_channel_parent_resumes_through_registry_channel or publish_timeline_event_for_runtime_fans_out_telegram_refs or publish_timeline_event_for_runtime_keeps_registry_refs_single_scoped"`
  - `./.venv/bin/python -m pytest -q -n 4`
  Direct checks:
  - repo-wide grep across `app/`, `tests/`, `scripts/`, and `octopus` returned zero matches for `registry_state.json`, `agent_registry_url`, `conversation_channel_name`, and `create_channel_egress`
  - verified the broader singleton audit also returned zero matches for the removed singleton config/state helper names across shipped code
  - verified the full suite stayed green after the final bridge and dispatcher cleanup
  Verified:
  - registry runtime/config/state ownership is now per connection only; there is no residual singleton registry path in active code
  - the final-slice cleanup removed more code than it added, which reduced duplication instead of hiding it behind compatibility helpers
  - final suite status: `1827 passed, 23 skipped`

# Control-Plane Capability Architecture Status

## Baseline

- Track: control-plane capability architecture
- Plan: `PLAN-control-plane-bus.md`
- Baseline branch: `feature/multi_registry`
- Baseline goal: replace registry-shaped control-plane coupling with capability ports, a durable control-plane bus, and startup-owned composition through `BotServices`.

## Slice Log

- Complete: Slice 1 ADR and contract freeze.
  Scope:
  - added `docs/adr/0001-control-plane-capability-architecture.md` documenting the architecture decision for capability ports, the durable control-plane bus, the channel-neutral services container, and the internal-only status of persisted registry state
  - added `docs/adr/README.md` so the repo has an explicit ADR index instead of a one-off markdown file
  - initialized this control-plane slice log in `status.md` without changing runtime code
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_zero_import_gates.py`
  Review:
  - slice 1 is documentation-only and intentionally does not change runtime behavior
  Verified:
  - the architecture decision now exists outside the implementation plan and status log
  - baseline sanity after the doc-only slice: `65 passed`
- Complete: Slice 2 capability ports and services.
  Scope:
  - added shared capability-port contracts in `app/ports/conversation_projection.py`, `app/ports/task_routing.py`, `app/ports/agent_directory.py`, and `app/ports/health_publication.py`
  - added typed no-op implementations for each capability so standalone/no-control-plane paths have one contract-shaped fallback instead of ad hoc `None` checks
  - added `app/runtime/services.py` with `ControlPlaneServices` nested under `BotServices`
  - kept the slice additive only: no runtime wiring or consumer migration landed yet
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_ports.py`
  - `./.venv/bin/python -m pytest -q tests/test_zero_import_gates.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the new contracts reuse the existing shared-port seam under `app/ports/` instead of inventing a parallel workflow-local contract package
  - no-op behavior is defined per method, which matches the plan and avoids the earlier mistake of treating whole ports as purely request/reply or purely fire-and-forget
  - the result models stay minimal and typed; the extra `TaskResultReport.details` field was removed during review because it was not part of the plan or current contract need
  Verified:
  - shared control-plane contracts now exist independently of any concrete registry runtime wiring
  - standalone/no-control-plane behavior is explicit and typed instead of implicit `None` handling
  - full suite status after slice 2: `1832 passed, 23 skipped`
- Complete: Slice 3A bus contract, models, and lifecycle.
  Scope:
  - added the `app/control_plane/` package with typed envelope models in `models.py` and the store protocol in `bus_base.py`
  - added typed per-operation payload models under `app/control_plane/requests/`, including the full routed-task status/result payload shapes and a shared `TimelineEventPayload`
  - added `app/control_plane/machine.py` with a `python-statemachine`-backed lifecycle helper covering claim, completion, claimed-failure, retry, lease-expiry reclaim, and dead-letter transitions
  - kept the slice contract-only: no storage implementation, runtime backend wiring, or consumer migration landed yet
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_machine.py tests/test_control_plane_models.py`
  - `./.venv/bin/python -m compileall app/control_plane tests/test_control_plane_machine.py tests/test_control_plane_models.py`
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_ports.py tests/test_control_plane_machine.py tests/test_control_plane_models.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the new bus contract follows the existing transport pattern: a dedicated store protocol in its own file, typed facade envelopes, and no backend selection logic outside `runtime_backend`
  - request payload models mirror the current domain dataclasses without lossy flattening; tuple-valued runtime collections become lists only where pydantic serialization requires it
  - the reply envelope was hardened during review so failed replies cannot accidentally carry a result payload, which keeps request/reply semantics unambiguous before storage lands
  Verified:
  - the control-plane bus now has typed command/reply contracts and validated payload models without introducing persistence or runtime wiring ahead of schedule
  - lifecycle invariants for retry budget and lease-expiry reclaim are now explicit and tested instead of being deferred to store-specific SQL
  - full suite status after slice 3A: `1844 passed, 23 skipped`
- Complete: Slice 3B bus storage and runtime backend seam.
  Scope:
  - added `app/control_plane/bus.py` as the async facade over `runtime_backend.control_plane_store()`
  - added SQLite and Postgres control-plane store implementations in `app/control_plane/sqlite_impl.py` and `app/control_plane/postgres_impl.py`, including submit/request primitives, pair-aware claiming, lease renewal, expiry reclaim, retry backoff, idempotency, and orphan reconciliation
  - extended `app/runtime_backend.py` so backend selection now owns `control_plane_store` alongside the existing session and transport stores
  - added Postgres migration `app/db/migrations/postgres/0013_control_plane_commands.sql` and updated the Postgres test truncation helper to reset the new runtime table between tests
  - added backend-neutral contract coverage in `tests/contracts/test_control_plane_store_contract.py`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/contracts/test_control_plane_store_contract.py`
  - `./.venv/bin/python -m compileall app/control_plane app/runtime_backend.py tests/contracts/test_control_plane_store_contract.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the storage slice extends the existing runtime-backend seam instead of introducing a second backend-selection path; `database_url` branching remains centralized in `app/runtime_backend.py`
  - the new control-plane store follows the existing transport-store pattern: backend-neutral protocol, SQLite/Postgres implementations, migration-backed Postgres schema, and contract tests running through the selected backend
  - the initial implementation review found an idempotency race under concurrent submit; both backends were hardened to query-and-return the existing command after a unique-conflict rollback so dedup remains stable under contention
  Verified:
  - the bus now has durable SQLite/Postgres persistence with pair-aware claiming and backend-selection parity
  - runtime backend reset/init owns the control-plane store lifecycle just like session and transport
  - full suite status after slice 3B: `1860 passed, 23 skipped`
- Complete: Slice 4A bus-backed capability adapters.
  Scope:
  - added `app/control_plane/directory.py` with the startup-built `ControlPlaneDirectory` used by adapters for capability-to-authority expansion
  - added bus-backed capability adapters in `app/control_plane/adapters/` for conversation projection, task routing, agent directory, and health publication
  - implemented targeted fan-out for conversation projection and health publication by expanding one capability-port call into one `ControlCommand` per registered authority
  - implemented request/reply task routing adapters with typed timeout and failure fallback handling, plus fire-and-forget routed-task status submission that preserves the full `RoutedTaskUpdate` payload shape
  - implemented agent-directory scatter/gather over targeted authority requests with aggregated `partial` / `unavailable` status handling
  - added focused adapter coverage in `tests/test_control_plane_adapters.py`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_ports.py tests/test_control_plane_models.py tests/test_control_plane_adapters.py`
  - `./.venv/bin/python -m compileall app/control_plane/adapters app/control_plane/directory.py tests/test_control_plane_adapters.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the adapters stay thin and intent-shaped: all routing knowledge comes from `ControlPlaneDirectory`, while command persistence and retry semantics remain in the bus/store layer
  - targeted fan-out is now explicit and per-authority, which avoids reintroducing the old broadcast ambiguity the plan was written to eliminate
  - routed-task status updates keep the full domain payload shape instead of collapsing timeline/progress fields into a narrower transport-only shape
  - the adapter review caught one stray internal deletion in `BusTaskRouting` before commit; it was removed rather than worked around
  Verified:
  - capability-port consumers now have one bus-backed path for projection, routing, directory lookups, and health publication without touching registry runtime/client seams
  - positive and negative adapter paths are covered: multi-authority fan-out, request success, request timeout, targeted unavailability, and directory partial aggregation
  - full suite status after slice 4A: `1868 passed, 23 skipped`
- Complete: Slice 4B processor runner.
  Scope:
  - added `app/control_plane/processor_base.py` with the generic `ControlProcessor` protocol and its per-authority capability map contract
  - added `app/control_plane/processor_runner.py` with a generic claim loop over the control-plane bus, bounded in-flight claiming, pair-aware processor dispatch, runner-owned lease heartbeating, periodic expired-lease reclaim, and clean shutdown handling
  - made duplicate `(authority_ref, capability)` ownership a registration error so control-plane routing cannot silently drift into ambiguous processor selection
  - added slice coverage in `tests/test_control_plane_processor_runner.py` for pair-aware dispatch, transient retry recovery, retry exhaustion/dead-letter behavior, expired-lease reclaim, lease renewal, and clean shutdown
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_processor_runner.py`
  - `./.venv/bin/python -m compileall app/control_plane/processor_base.py app/control_plane/processor_runner.py tests/test_control_plane_processor_runner.py`
  - `./.venv/bin/python -m pytest -q tests/test_control_plane_ports.py tests/test_control_plane_models.py tests/test_control_plane_adapters.py tests/test_control_plane_processor_runner.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the runner stays generic infrastructure: it owns claiming, shutdown, lease renewal, and retry handoff, while processors remain pure domain handlers that never touch the bus directly
  - in-flight bounding was kept in the runner rather than each processor so shutdown semantics and lease ownership stay centralized instead of becoming per-processor policy
  - the reclaim/retry review found the correct behavior was already in the store layer; the test was fixed to zero backoff explicitly instead of weakening store semantics for convenience
  Verified:
  - command execution now has one generic processor loop that honors per-authority capability ownership and keeps leases alive while handlers run
  - positive and negative runner paths are covered: routing by pair, transient failure retry, dead-letter on exhausted retries, reclaim of expired claims, lease heartbeats, and stop-with-inflight semantics
  - full suite status after slice 4B: `1876 passed, 23 skipped`
- Complete: Slice 4C registry control processor.
  Scope:
  - added `app/agents/registry_capabilities.py` with the shared `registry_authority_capabilities()` builder plus `registry:` authority ref helpers
  - added `app/agents/registry_control_processor.py` as the registry-backed `ControlProcessor` implementation for conversation projection, task routing, agent directory, and health publication
  - added a public `registries` property on `RegistryRuntime` so startup and processor slices can share the same configured connection set without reaching into private fields
  - kept registry HTTP ownership on existing seams: the processor reuses `RegistryRuntime.client_for_registry()` and existing `AgentRegistryClient` methods instead of creating a second registry-I/O path
  - added focused processor coverage in `tests/test_registry_control_processor.py`
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_registry_control_processor.py`
  - `./.venv/bin/python -m compileall app/agents/registry_capabilities.py app/agents/registry_control_processor.py app/agents/registry_runtime.py tests/test_registry_control_processor.py`
  - `./.venv/bin/python -m pytest -q tests/test_registry_runtime.py tests/test_registry_control_processor.py tests/test_control_plane_processor_runner.py tests/test_control_plane_adapters.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - scope-to-capability ownership now has one shared builder; the processor does not re-encode `registry_scope` locally, which avoids the drift problem called out in the plan review
  - the processor translates only real registry request failures (`RegistryClientError`) into failed replies and leaves ordinary coding errors visible, so retry semantics stay correct without hiding defects
  - routed-task status processing preserves timeline events, progress, and `updated_at` all the way into the existing client/store path instead of flattening the payload
  Verified:
  - registry now has a concrete control-plane processor that can execute every planned capability over existing runtime/client seams
  - positive and negative processor paths are covered: scope mapping, projection, routing, discovery, authority resolution, health publication, and isolated registry request failure handling
  - full suite status after slice 4C: `1880 passed, 23 skipped`
- Complete: Slice 5 startup composition.
  Scope:
  - wired `app/main.py` to build one `ControlPlaneBus`, derive a startup `ControlPlaneDirectory` from `registry_authority_capabilities()`, and construct bus-backed or no-op `BotServices` before any channel runtime is built
  - threaded `services` through `TelegramRuntime`, `build_worker_bundle()`, `build_bootstrap()`, and `TelegramChannelBootstrap` so every Telegram runtime now owns `BotServices` even before consumer cutovers land
  - moved registry channel registration into startup composition with `register_registry_channels(...)` instead of mutating the dispatcher from `RegistryRuntime`
  - added startup-owned `ProcessorRunner` wiring so registry-owning roles reconcile orphaned commands and run the control-plane processor loop, while non-owning roles still receive bus-backed services but do not start processors
  - updated the shared handler fixture to build runtimes with the same services/channel-registration composition shape as startup
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_config.py tests/test_telegram_channel_state.py tests/test_telegram_runtime_skills.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the slice reused the existing startup composition root and `runtime_backend` seam instead of introducing a second topology/bootstrap abstraction just to carry services
  - `BotServices` injection is now startup-owned and runtime-local; consumers still keep their legacy fields during scaffolding, which matches the plan and avoids mixing composition with consumer cutover
  - registry channel registration is now explicit startup work, which removes one runtime-owned dispatcher mutation path without yet forcing registry channel egress onto the new control-plane ports ahead of schedule
  Verified:
  - startup now produces non-null `BotServices` for polling, webhook, worker-only, and registry-only roles
  - the control-plane processor loop starts only for registry-owning roles, while shared worker roles with registries still receive services and channel registration without starting a processor
  - the shared test fixture now follows the same startup-owned services/channel-registration model as production composition
  - full suite status after slice 5: `1881 passed, 23 skipped`
- Complete: Slice 6A cut Telegram egress to ports.
  Scope:
  - rewired `app/channels/telegram/egress.py` so binding, input mirroring, outcome mirroring, and generic timeline publication all go through `services.control_plane.conversation_projection`
  - removed Telegram egress imports of bridge mirroring helpers and removed its direct `registry_runtime` branch/state
  - updated `TelegramChannelBootstrap.build_egress()` to inject the startup-owned `BotServices` into every Telegram egress instance created by the dispatcher
  - preserved the surrounding worker/delivery call shapes during scaffolding: dispatcher callers can still pass old kwargs, but Telegram egress now ignores the registry-runtime detail entirely
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_telegram_channel_egress.py tests/test_telegram_channel_state.py tests/test_telegram_worker_timeline.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the slice removes one full parallel path instead of adding another adapter layer: Telegram egress no longer imports or branches on bridge/runtime control-plane helpers at all
  - the services injection point stays at the channel bootstrap, which keeps the control-plane dependency startup-owned and avoids smuggling a new runtime-specific collaborator through worker callsites ahead of schedule
  - timeline publication now forwards `event_id` when present, which keeps the new port path compatible with the existing idempotent timeline model instead of silently dropping dedupe metadata
  Verified:
  - Telegram egress now depends only on the conversation-projection capability port for bind/input/outcome/timeline projection
  - positive and negative egress paths are covered: normal projection, missing-conversation bind skip, disabled input mirroring skip, outcome projection, and timeline event-id forwarding
  - full suite status after slice 6A: `1885 passed, 23 skipped`
- Complete: Slice 6B cut progress and worker timeline to ports.
  Scope:
  - rewired `app/channels/telegram/progress.py` so `progress_timeline_callback()` publishes through `runtime.services.control_plane.conversation_projection` instead of bridge/runtime mirroring helpers
  - rewired `app/channels/telegram/worker.py::_publish_timeline_event_for_runtime()` so Telegram refs project through the same conversation-projection port even when no live `registry_runtime` is present
  - kept registry refs on the existing single-scoped timeline path for now, which matches the plan’s slice boundary and avoids pulling finalization/registry cleanup forward
  Tests:
  - `./.venv/bin/python -m pytest -q tests/test_telegram_progress_module.py tests/test_telegram_worker_timeline.py tests/test_telegram_execution_module.py`
  - `./.venv/bin/python -m pytest -q -n 4`
  Review:
  - the slice removes the remaining Telegram timeline branch on live runtime presence; Telegram projection now depends on the same startup-owned capability port in egress, progress, and worker timeline paths
  - the worker helper still routes registry refs through the existing single-scoped publication seam, which keeps the ref-sensitive behavior intact until the later registry cleanup slices own that contract migration
  - no new control-plane abstraction or helper was introduced; the change stays within the existing runtime/services boundary and the existing ref-type split in worker timeline publication
  Verified:
  - Telegram progress and worker-owned usage/timeline publication no longer require `runtime.registry_runtime` to mirror externally
  - positive and negative paths are covered: progress projection, progress without live runtime, Telegram-ref worker projection through the port, and registry-ref worker publication staying single-scoped
  - full suite status after slice 6B: `1885 passed, 23 skipped`
