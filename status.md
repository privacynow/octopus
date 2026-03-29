# SDK-4 Execution Status

Plan source of truth: [PLAN-sdk-4.md](/Users/tinker/output/bots/telegram-agent-bot/PLAN-sdk-4.md)

Rules followed:
- The plan was not modified in this execution pass.
- Progress is recorded here only.
- Items are checked only after code changes, tests, and two-pass review against the immutable plan.
- "Mostly done" is not done.

## Phase 1: Move 5 pure files to SDK + extract time_utils

- [x] 1-pre: Move `age_seconds`, `utc_now`, `utc_now_timestamp`
- [x] 1a: `app/workflows/lifecycle_machine.py` → `octopus_sdk/workflows/lifecycle_machine.py`
- [x] 1b: `app/workflows/pending/machine.py` → `octopus_sdk/workflows/pending_machine.py`
- [x] 1c: `app/workflows/recovery/machine.py` → `octopus_sdk/workflows/recovery_machine.py`
- [x] 1d: `app/workflows/runtime_skills/setup_machine.py` → `octopus_sdk/workflows/setup_machine.py`
- [x] 1e: `app/runtime/transport_dispatcher.py` → `octopus_sdk/transport_dispatcher.py`
- [x] 1f: Verify all moved files have zero `from app.*` imports
- [x] 1g: Delete all source files from `app/`
- [x] 1h: Rewrite affected tests

## Phase 2: Define missing SDK Ports for service dependencies

- [x] 2a: `MessageTemplatePort`
- [x] 2b: `CredentialServicePort`
- [x] 2c: `SkillCatalogServicePort`
- [x] 2d: `ContentStorePort`
- [x] 2e: `SkillImportServicePort`
- [x] 2f: `CredentialValidatorPort`
- [x] 2g: `TrustTierResolverPort`
- [x] 2h: `TextFormattingPort`
- [x] 2i: `CompletionWebhookPort`
- [x] 2j: `BotConfigBase` covers all workflow-used config fields
- [x] 2k: `WorkQueuePort` covers all workflow-used queue operations
- [x] 2l: `SessionRuntimePort` covers `default_session()` and all session ops
- [x] 2m: `ProviderGuidancePort` covers guidance service operations
- [x] 2n: `SkillActivationPort` covers activation service operations
- [x] 2n2: `WorkQueuePort` and `SessionRuntimePort` structurally encode durability expectations
- [x] 2o: Remove `app.runtime.composition` dependency leaks with constructor-injected refs

## Phase 3: Refactor 14 workflow files to constructor injection, move to SDK

- [x] 3a: `pending/requests.py`
- [x] 3b: `conversation/control.py`
- [x] 3c: `conversation/settings.py`
- [x] 3d: `credentials/management.py`
- [x] 3e: `runtime_skills/catalog.py`
- [x] 3f: `runtime_skills/activation.py`
- [x] 3g: `runtime_skills/setup.py`
- [x] 3h: `runtime_skills/authoring.py`
- [x] 3i: `runtime_skills/approval.py`
- [x] 3j: `runtime_skills/importing.py`
- [x] 3k: `provider_guidance/preview.py`
- [x] 3l: `provider_guidance/management.py`
- [x] 3m: `recovery/replay.py`
- [x] 3n: `execution/finalization.py`
- [x] 3o: Delete moved backend-neutral source files from `app/workflows/`
- [x] 3p: Make `app/runtime/composition.py` construct workflows from injected app implementations
- [x] 3q: Update all other consumers
- [x] 3r: Rewrite affected tests

## Phase 3.5: Add SDK workflow composition and runtime utilities

- [x] 3.5a: Add `octopus_sdk/composition.py`
- [x] 3.5b: Add `WorkflowComposer` with builder API
- [x] 3.5c: `WorkflowComposer.build()` returns a fully wired `WorkflowComposition`
- [x] 3.5d: Required ports fail at `.build()` time with explicit errors
- [x] 3.5e: Optional ports default to loud `NotConfiguredError`
- [x] 3.5f: Add `InMemoryWorkQueue` in `octopus_sdk/testing/work_queue.py`
- [x] 3.5g: Add `InMemorySessionStore` in `octopus_sdk/testing/sessions.py`
- [x] 3.5g2: `.build()` rejects test implementations, `.build_for_testing()` accepts them, `BotRuntime` rejects test-only composition unless explicitly overridden
- [x] 3.5h: Make `app/runtime/composition.py` a thin wrapper over `WorkflowComposer`
- [x] 3.5i: Rewrite affected tests

## Phase 4: Define registry management protocol for connected bots

- [x] 4a: Define SDK `ManagementRequest` / `ManagementResult` envelopes
- [x] 4b: Define request/result dataclasses for all 27 operations
- [x] 4c: Add `management_request` delivery kind
- [x] 4d: Add `management_result` reporting path
- [x] 4e: Define management capability advertisement
- [x] 4f: Add bot-side management executor in SDK
- [x] 4g: Add registry-side management client
- [x] 4h: Migrate management HTTP routes to agent-scoped paths
- [x] 4i: Define explicit responses for not connected / capability unavailable / timeout
- [x] 4j: Rewrite affected tests

## Phase 5: Resolve registry server entanglements

- [x] 5a-1: Rewrite `ingress.py` against the management protocol
- [x] 5a-2: Remove all `app.*` imports
- [x] 5a-3: Add capability checks before request dispatch
- [x] 5a-4: Preserve API response shapes
- [x] 5b-1: Move `app/ratelimit.py` out of `app/`
- [x] 5c-1: Move `app/capability_service.py` out of `app/`
- [x] 5c-2: Update route definitions to agent-scoped paths
- [x] 5c-3: Validate `agent_id` and connectivity before request delegation

## Phase 6: Extract registry server to `octopus_registry/`

- [x] 6a-1: Create `octopus_registry/__init__.py`
- [x] 6a-2: Move all server and store files per plan table
- [x] 6a-3: Move `ui/` to `octopus_registry/ui/`
- [x] 6a-4: Create `octopus_registry/config.py`
- [x] 6a-5: Create `octopus_registry/main.py`
- [x] 6a-6: Delete server files from `app/channels/registry/` and keep only bot transport files
- [x] 6a-7: Delete `app/registry_service/`
- [x] 6a-8: Delete root `ui/`
- [x] 6b-1: Update Dockerfiles
- [x] 6b-2: Update Docker Compose
- [x] 6b-3: Update `octopus_cli` registry references
- [x] 6c-1: Import-graph test: `octopus_registry` may not import `app`
- [x] 6c-2: Import-graph test: `app` may not import `octopus_registry`
- [x] 6c-3: Import-graph test: `octopus_sdk` imports neither
- [x] 6c-4: Verify `octopus_registry/` imports only `octopus_sdk/` + stdlib + third-party
- [x] 6c-5: Rewrite affected tests

## Phase 7: Verify bot config/entrypoint separation

- [x] 7a: Verify `app/main.py` has zero registry server startup logic
- [x] 7b: Verify `app/config.py` has zero registry server fields
- [x] 7c: Add regression test that `app/main.py` does not import `octopus_registry`

## Phase 8: Eliminate WorkerDispatchPort injection

- [x] 8a: Move claimed-item-to-workflow routing into `BotRuntime`
- [x] 8b: Eliminate `WorkerDispatchPort` from `BotRuntime`
- [x] 8c: The path from `runtime.submit(envelope)` to workflow invocation has zero `app/` imports
- [x] 8d: Rewrite affected tests

## Phase 9: SDK wiring verification test

- [x] 9a: `InMemoryWorkQueue` and `InMemorySessionStore` live in `octopus_sdk/testing/`
- [x] 9b: Test implementations are deliberately non-durable and raise on persistence-guarantee methods
- [x] 9c: `.build()` rejects test implementations and the wiring test uses `.build_for_testing()`
- [x] 9d: Wiring test composes workflows through `WorkflowComposer.build_for_testing()`
- [x] 9e: Wiring test exercises message → provider → approval → delegation → skills → recovery
- [x] 9f: Wiring test has zero `app/` imports and zero `octopus_registry/` imports
- [x] 9g: Wiring verification is a pytest in `octopus_sdk/tests/`, not a developer example/template

## Phase 10: Final verification

- [x] 10a: Import graph: `octopus_sdk/` imports neither `app/` nor `octopus_registry/`
- [x] 10b: Import graph: `octopus_registry/` imports only `octopus_sdk/`
- [x] 10c: Import graph: `app/` does not import `octopus_registry/`
- [x] 10d: All import-graph regression tests pass
- [x] 10e: Full test suite passes
- [x] 10f: SDK wiring verification test passes
- [x] 10g: `app/` does not import `octopus_sdk.testing`
- [x] 10h: `octopus_registry/` does not import `octopus_sdk.testing`
- [x] 10i: `octopus_sdk/testing` is not re-exported from `octopus_sdk/__init__.py` or any other convenience surface
- [x] 10j: Adversarial review of all exit criteria

## Phase 11: Fix delegation protocol transport identity

- [x] 11a: Add `origin_conversation_key: str` to `PendingDelegation`
- [x] 11b: Add `origin_transport_ref: str = ""` to `RoutedTaskRequest`
- [x] 11c: Update `build_delegation_plan()` to accept and store transport conversation key
- [x] 11d: Update `propose_participant_delegation()` and callers to pass transport conversation key
- [x] 11e: Update routed task submission path to propagate `origin_transport_ref`
- [x] 11f: Update routed task creation in both registry stores to persist transport ref and return it in `routed_result` delivery payload
- [x] 11g: Verify transport-originated delegation path preserves `external_conversation_ref`, and make proposal payload/metadata carry explicit `origin_transport_ref` so approval is self-describing with conversation-row fallback only
- [x] 11h: Routed-result handler resolves parent session key from explicit transport identity first
- [x] 11i: Resume message targets the original transport ref for egress and `conversation_ref`
- [x] 11j: Completion message decision is based on originating transport ref, not `parent_conversation_id.startswith("registry:")`
- [x] 11k: Add delegation round-trip checks to SDK wiring verification test
- [x] 11l: Add Telegram-originated round-trip integration coverage
- [x] 11m: Add equivalent non-Telegram transport round-trip coverage
- [x] 11n: Audit management protocol for the same identity-loss class and fix conversation-scoped registry ingress requests to use transport-derived conversation keys
- [x] 11o: Extend wiring verification so delegation identity is proven through the round-trip, not bypassed by stubs
- [x] 11p: Verify Phase 8 runtime path does not strip routed-result transport identity; `RegistryDeliveryTransport` handles `routed_result` directly and tests lock the handler behavior

## Phase 12A: Direct-assignment transport identity parity

- [x] 12A-1: Add `origin_transport_ref: str = ""` to `DirectAssignmentRequest` and `DirectAssignActionPayload` in `octopus_sdk/registry/models.py`
- [x] 12A-2: `submit_participant_direct_assignment()` in `octopus_sdk/workflows/delegation.py` populates `origin_transport_ref` from the caller transport identity
- [x] 12A-3: Registry store `direct_assign` action handlers persist `origin_transport_ref` on the routed task and include it in the `routed_result` delivery payload
- [x] 12A-4: Delivery handler `resolve_delegation_parent_identity()` prefers `origin_transport_ref` from the delivery payload over the bare `external_conversation_ref` fallback
- [x] 12A-5: `ensure_conversation_id()` callers in `octopus_sdk/workflows/delegation.py` pass qualified transport refs as `external_conversation_ref`
- [x] 12A-6: Direct-assign round-trip coverage proves Telegram M1 → M2 → result → M1 resume with `origin_transport_ref` preserved and no raw-ref failure

## Phase 12B: Recipient-side routed-task conversation projection

- [x] 12B-1: Existing SDK delivery/conversation models were sufficient; the registry store now creates or ensures recipient-side routed-task projections without introducing an app-owned protocol
- [x] 12B-2: Routed-task delivery payloads require and carry a valid `external_conversation_ref`; recipient execution no longer runs with a blank routed-task external ref
- [x] 12B-3: Registry UI/store queries expose incoming delegated work under the recipient bot conversation/task view
- [x] 12B-4: Recipient execution mirror events are written against the recipient-side task thread, not only the requester parent conversation
- [x] 12B-5: Store/service/agent tests cover recipient projection visibility, routed-task event mirroring, and result visibility on the recipient thread

## Phase 12C: Deferred recipient notification

- [x] 12C-1: Define a `DeferredNotification` model in the SDK
- [x] 12C-2: Routed-task completion/failure creates deferred notifications through the SDK execution-finalization path using `DeferredNotificationPort`
- [x] 12C-3: Define a `DeferredNotificationPort` in the SDK and integrate the bot runtime flush path
- [x] 12C-4: Implement the port in `app/` using durable storage-backed adapters
- [x] 12C-5: Deferred notification delivery is actor-keyed rather than transport-keyed, so the next authorized interaction on any transport can flush it
- [x] 12C-6: Notifications have TTL and stale entries expire before display
- [x] 12C-7: Wiring/runtime tests cover completion → deferred enqueue → next interaction flush → consume-once behavior

## Phase 12D: Composition type-safety fixes

- [x] 12D-1: `WorkflowComposition.trust_tier_resolver` is typed as `TrustTierResolverPort | None`, not bare `Callable`
- [x] 12D-2: `WorkflowComposition` required fields `messages`, `config`, and `sessions` have no `| None` defaults
- [x] 12D-3: The defensive `if self.workflows.messages is not None` guard is removed from BotRuntime required-port flow
- [x] 12D-4: `_reject_test_implementations` covers all managed ports including `messages` and `config`
- [x] 12D-5: `_UnavailablePort` documents the `hasattr()` behavior explicitly; no fake `__hasattr__` path was added
- [x] 12D-6: Full test suite passes after the composition tightening

## Phase 12E: Poll cursor correctness and registry reconnect safety

- [x] 12E-1: Re-enrollment resets `poll_cursor` to `0` in bot-local registry state
- [x] 12E-2: Identity/auth failure clears local registry state, re-enrolls, and restarts polling from cursor `0`
- [x] 12E-3: Cursor never advances past unacked deliveries; `retry_later` does not move the durable cursor past the skipped item
- [x] 12E-4: Registry exposes `registry_epoch`; bots persist it and reset cursor when the epoch changes
- [x] 12E-5: Tests cover fresh-registry rebuild with stale local state, re-enrollment, cursor reset, and successful replay from `0`
- [x] 12E-6: Tests cover crash-before-ack behavior: delivery is seen again, acked, and only then advances the cursor

## Phase 12F: Remaining test and type gaps from adversarial review

- [x] 12F-1: `origin_transport_ref` is validated at SDK submission time and rejects raw numeric/unqualified refs
- [x] 12F-2: Full direct-assign round-trip integration coverage proves parent transport resume with preserved `origin_transport_ref`
- [x] 12F-3: `WorkflowComposition.deferred_notifications` is structurally non-None through composition/build paths
- [x] 12F-4: Full end-to-end deferred-notification integration coverage proves enqueue → next interaction flush → consume-once

## Phase 12G: SDK-owned delegation continuation path

- [x] 12G-1: Define `DelegationContinuationPort` in the SDK
- [x] 12G-2: Implement the continuation path in the SDK, not `app/`
- [x] 12G-3: Wire continuation through `BotRuntime`
- [x] 12G-4: Rewrite `routed_result` handling to call continuation instead of fabricating an inbound message
- [x] 12G-5: Remove dead delegation-resume re-entry paths; `admission_class` remains only for approval/retry replay
- [x] 12G-6: Completion message and resumed provider response use the same parent transport egress
- [x] 12G-7: Automated restrictive-auth round-trip coverage proves continuation avoids fresh-message admission
- [ ] 12G-8: Manual live acceptance test — operator sends delegation from M1 Telegram chat → M2 completes → M1 Telegram chat receives the resumed reply in the same thread

## Phase 12H: Recipient task thread UI presentation

- [x] 12H-1: Add `conversation_type` to SQLite, Postgres, and Postgres migration SQL
- [x] 12H-2: Recipient routed-task projection is stored with `conversation_type="task_thread"`
- [x] 12H-3: Store list/get serialization returns `conversation_type`
- [x] 12H-4: Conversation list renders task threads with a distinct badge/visual treatment
- [x] 12H-5: Agent detail conversation list renders task threads distinctly
- [x] 12H-6: Conversation list filter exists for `All` / `Conversations` / `Task threads`
- [x] 12H-7: Store/service/UI contract tests prove typed recipient projections, filtering, and distinct rendering markers
- [x] 12H-8: Remove `conversation_type` from ON CONFLICT SET clause in `_ensure_conversation_in_tx` in BOTH `store.py` and `store_postgres.py`
- [x] 12H-9: Fix 4 callers (`store.py:1636`, `store.py:1836`, `store_postgres.py:1467`, `store_postgres.py:1686`) to pass `conversation_type="task_thread"` explicitly
- [x] 12H-10: Test: task thread type survives status and completion updates in both store backends

## Phase 12I: Two-shell route transitions

- [x] 12I-1: `router.js` `_render()` is sync again
- [x] 12I-2: All 11 route components reverted to sync shell rendering
- [x] 12I-3: Two-shell overlay CSS exists for concurrent outgoing/incoming route shells
- [x] 12I-4: Router mounts new shell alongside old shell and crossfades instead of single-buffer replacement
- [x] 12I-5: Old-route cleanup runs after shell removal, not before mount
- [x] 12I-6: 404 path uses the same two-shell swap machinery
- [x] 12I-7: Rapid navigation uses render sequence guards and stale-shell cleanup
- [x] 12I-8: `loading-route` dim and `.route-enter`/`.route-enter-active` are removed
- [x] 12I-9: First page load mounts directly with no crossfade
- [ ] 12I-10: Manual visual test — dashboard → tasks → conversations → agent detail shows no blank frame, no skeleton flash, no dim

## Phase 12J: Approval/retry replay `admission_class`

- [x] 12J-1: `admission_class` remains correctly scoped to approval and retry replay paths after 12G
- [x] 12J-2: Replay coverage proves restrictive auth does not break retry replay execution

## Hard exit criteria

- [x] 1. Three packages exist: `octopus_sdk/`, `octopus_registry/`, `app/`.
- [x] 2. `octopus_sdk/` imports neither `app/` nor `octopus_registry/`.
- [x] 3. `octopus_registry/` imports only `octopus_sdk/`. Zero `app/` imports.
- [x] 4. `app/` does not import `octopus_registry/`.
- [x] 5. Import-graph regression tests lock all three boundaries.
- [x] 6. Registry server is deployable from `octopus_registry/` + `octopus_sdk/`.
- [x] 7. Standalone registry behavior is explicit.
- [x] 8. Management operations via `management_request` / `management_result` over poll/ack.
- [x] 9. All 27 management HTTP endpoints are agent-scoped.
- [x] 10. Bot is deployable from `app/` + `octopus_sdk/`.
- [x] 11. All 14 workflow implementations in SDK with zero `app.*` imports.
- [x] 12. All 4 backend-neutral FSMs in SDK.
- [x] 13. `TransportDispatcher` in SDK.
- [x] 14. `WorkflowComposer` in SDK with builder API.
- [x] 15. `InMemoryWorkQueue` and `InMemorySessionStore` in `octopus_sdk/testing/`, test-only, non-durable.
- [x] 16. `WorkflowComposer` required ports fail at build, test implementations rejected by `.build()`.
- [x] 17. Capability advertisement at registration.
- [x] 18. Bot-side management executor in SDK.
- [x] 19. `octopus_registry/ingress.py` rewritten, zero `app.*` imports.
- [x] 20. `app/registry_service/` does not exist.
- [x] 21. `ui/` at repo root does not exist.
- [x] 22. `app/workflows/` contains only Telegram-specific handlers.
- [x] 23. `BotRuntime` has no `WorkerDispatchPort`.
- [x] 24. SDK wiring verification test exercises full lifecycle, zero `app/` imports.
- [x] 25. `app/` does not import `octopus_sdk.testing`.
- [x] 26. `octopus_registry/` does not import `octopus_sdk.testing`.
- [x] 27. `octopus_sdk/testing` not re-exported.
- [x] 28. Durability expectations encoded in port method surface.
- [x] 29. `PendingDelegation` stores `origin_conversation_key`.
- [x] 30. `RoutedTaskRequest` carries `origin_transport_ref`.
- [x] 31. Delegation result handler uses transport identity for session resolution and resume.
- [x] 32. Cross-transport delegation round-trip tests pass.
- [x] 33. `DirectAssignmentRequest` carries `origin_transport_ref`.
- [x] 34. Recipient bots have visible task projections in registry.
- [x] 35. Deferred notifications exist as SDK capability.
- [x] 36. Composition type safety (trust_tier_resolver, required fields, reject test implementations).
- [x] 37. Poll cursor correctness and rebuild detection.
- [x] 38. `origin_transport_ref` validated at SDK submission.
- [x] 39. Full direct-assign round-trip test passes.
- [x] 40. `deferred_notifications` not None through any construction path.
- [x] 41. Full deferred notification integration test passes.
- [x] 42. Resume envelope transport matches parent transport.
- [x] 43. Recipient task threads visually distinguishable, filters exist.
- [ ] 44. Route transitions use two-shell crossfade. Old view stays visible until new view fades in. No blank frame, no skeleton flash, no dim. Components are sync. Cleanup runs after old shell removal.
- [x] 45. Delegation resume uses SDK-owned continuation path (`DelegationContinuationPort`), not `InboundMessage` re-entry through `admit_message`. No synthetic actor, no `bot=None` blocker, no mixed registry/Telegram identity. `admission_class` remains only for approval/retry replays.
- [x] 46. `conversation_type` NOT overwritten by ON CONFLICT upserts. Task thread type survives status and completion updates.
- [x] 47. `app/runtime/composition.py` is thin wrapper over `WorkflowComposer`.
- [x] 48. Every moved file deleted from source.
- [x] 49. No exit criterion was weakened, qualified, or removed in this execution pass.

## Review log

- [x] Review pass 1: audited rewritten 12G/12H/12I/12J plan sections against current code paths
- [x] Review pass 2: found fresh-message delegation resume and async-pre-render route swaps still violated the rewritten late phases
- [x] Review pass 3: implemented SDK continuation path, re-audited routed-result handling, then rewrote router/components back to sync two-shell rendering
- [x] Review pass 4: reran focused slices and full suite after the second rewrite; updated status only after the final whole-tree audit

## Current verification

- Delegation/UI focused slices:
  - `10 passed` (`tests/test_registry_ui_contract.py`, `octopus_sdk/tests/test_wiring_verification.py`, `tests/test_agents.py` routed-result/delegation slice)
  - `13 passed` (`tests/test_handlers.py` routed-result/delegation slice, `tests/test_request_flow.py` delegation slice, `tests/test_runtime_inbound_types.py`)
  - `12 passed` (post-contract pass after adding `DelegationContinuationPort`)
- Current full suite: `2168 passed, 1 skipped`
- Remaining manual/live items only: `12G-8`, `12I-10`
- Exit criterion 44 is still open pending manual browser confirmation

## Remaining work summary

Remaining manual acceptance:
1. `12G-8`: Telegram M1 → M2 → M1 resumed reply visible in the human Telegram chat
2. `12I-10`: visual confirmation that dashboard → tasks → conversations → agent detail uses the two-shell transition with no blank frame or skeleton flash
