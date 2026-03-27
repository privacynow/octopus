# Plan: Unified SDK — Transport, Registry Participation, Authority, and Conformance

## Purpose

Unify the bot runtime architecture into one SDK-owned model where every runtime
behavior is an implementation of an SDK interface.

The SDK owns the full bot-side runtime contract, the registry authority client
contract, the registry authority server contract, and every workflow contract
that a transport needs to support the full operator experience. No app-local
adapter may define semantics outside those interfaces.

There is no intermediate target. There is no "mostly unified" state. There are
no backward-compatibility shims. Every concept that is replaced is deleted in
the same change that replaces it.

## Required outcome

After this work:

1. A new bot transport (Slack, WhatsApp) can be built by implementing SDK
   interfaces only, without importing `app.*`. This includes the full operator
   experience: messages, approvals, settings, skills, credentials, recovery,
   delegation, and authorization — not just the core message/response loop.
2. Telegram is a clean implementation of the SDK transport interface plus the
   SDK registry participant interface. Target: ~1,500 lines, down from ~8,050.
3. Registry bot-side runtime is a clean implementation of the same SDK transport
   interface. Target: ~500 lines.
4. Registry server/authority implements SDK authority interfaces with typed
   records, not `dict[str, Any]`.
5. `main.py` is pure profile-driven composition with mandatory fail-on-missing
   for required capabilities. Target: ~100 lines.
6. A behavioral certification suite enforces conformance for every interface.
7. No code path exists that is not an implementation of an SDK interface.
8. Every SDK interface boundary uses typed SDK-owned types. No `dict[str, Any]`,
   no `Any`, no `Callable[..., Any]` at Protocol or composition boundaries.

## Plan integrity rules

This section exists because the plan was previously modified to weaken exit
criteria and mark incomplete work as done. These rules prevent that.

1. **Exit criteria are immutable.** The hard exit criteria at the bottom of
   this plan may not be reworded, qualified, scoped down, or removed. If the
   implementation cannot meet a criterion, the implementation must change — not
   the criterion.

2. **"Complete enough" is not a completion state.** The plan says "mostly done
   is not done." This applies to "complete enough," "architecturally
   equivalent," "semantically done," and any other synonym for incomplete.

3. **Checklist items reflect file system state.** If a checklist item says
   "delete file X" and file X still exists, the item is not checked. Marking
   it [x] while the file exists is fraud.

4. **Relocating callbacks is not eliminating them.** Moving Callable fields
   from one dataclass to another does not satisfy "zero Callable callback
   fields." If `ProviderDispatchRuntime` takes 7 callable parameters that were
   formerly on `ExecutionRuntime`, the callbacks were relocated, not eliminated.

5. **Implicit interface obligations are callbacks.** If `execute_request`
   expects methods on its `message` parameter that are not part of any SDK
   Protocol, those are implicit callback obligations. They count against
   "zero callback stubs" in the reference transport test.

5a. **Default no-op implementations are silent fallbacks.** Adding methods to
   an SDK Protocol with default no-op implementations does not eliminate the
   obligation — it hides it. If a method is required for the operator
   experience, it must be abstract (no default) or capability-gated with an
   explicit error on undeclared use. A transport that silently skips
   `send_approval_prompt` because the default is a no-op has a broken
   operator experience, not a working one.

6. **Qualifiers narrow scope.** Adding "authority-facing" to a criterion that
   originally said "all" narrows the scope. That is a weakening, not a
   clarification.

7. **The plan is reviewed adversarially.** Reviewers must verify against code,
   not trust [x] marks or "current state" descriptions.

8. **`Any` is not a typed boundary.** SDK composition classes and Protocol
   signatures must use concrete SDK-owned types, not `Any`. A field typed as
   `Any` is an untyped hole that defeats static checking.

9. **Empty-string defaults on required identity fields are not acceptable.**
   If a field must be populated for correct behavior, it must not have a
   default that makes an empty value structurally valid.

## Post-review findings

The first implementation pass relocated behavior instead of eliminating it in
several places and modified the plan to match incomplete work. A subsequent
SDK audit found additional type-safety gaps. All must be corrected:

1. `ProviderDispatchRuntime` takes 7 callable parameters (`progress_factory`,
   `send_status`, `typing_target`, `keep_typing`, `heartbeat`,
   `format_provider_error`, `run_result_was_interrupted`). These are the old
   `ExecutionRuntime` callbacks moved to a different dataclass, not eliminated.

2. `execute_request` expects 9 methods on its `message` parameter
   (`reply_text`, `show_foreign_setup`, `show_setup_prompt`,
   `send_retry_prompt`, `send_approval_prompt`, `send_formatted_reply`,
   `send_directed_artifacts`, `send_compact_reply`, `propose_delegation_plan`).
   These were later added to `TransportEgress` as methods with default no-op
   implementations. That is not elimination — it is formalization with a silent
   fallback. Methods required for the operator experience must be abstract or
   capability-gated, not silently skipped via no-op defaults.

3. Step F4 claimed to delete `conversation.py`, `pending.py`,
   `runtime_skills.py`, `cancellation.py` — all still exist.

4. Criterion 6 was changed from "AbstractRegistryStore uses typed SDK records"
   to "Authority-facing AbstractRegistryStore methods use typed SDK records."

5. Criterion 8 was changed to remove the ~1,500 line target for Telegram.

6. `build_noop_control_plane_services`, `_DynamicWorkQueue`, and
   `_default_registry_participant` still exist as silent fallback paths.

7. `WorkQueuePort` uses `dict[str, Any]` aliases for `WorkItemRecord`,
   `UserAccessRecord`, `UsageRecord`.

8. `BotRuntime.transport` is typed as `Any` — the SDK's own composition class
   has an untyped hole for its most important field.

9. `BotServicesPort.control_plane` is typed as `Any` — another untyped hole
   in SDK composition.

10. `provider_state: dict[str, Any]` flows untyped through `SessionState`,
    `Provider.run()`, `Provider.new_provider_state()`,
    `RunResult.provider_state_updates`, and `PendingApproval`. The provider
    state shape is invisible to the SDK across the entire session/provider
    boundary.

11. `TransportIdentity` fields (`origin_channel`, `external_conversation_ref`,
    `target_agent_id`, `conversation_ref`, `routed_task_id`, `authority_ref`,
    `actor`) all default to empty string. A `TransportIdentity()` with no
    arguments is structurally valid but semantically meaningless. Required
    fields must not have defaults.

12. `RunResult.denials: list[dict[str, Any]]` — approval denials flow as
    untyped dicts through the SDK.

13. `RegistryRecordModel` in `registry/models.py` uses `extra="allow"` which
    lets arbitrary unknown fields through the wire model.

14. The SDK type-safety test (`test_sdk_type_safety.py`) is broken. It uses
    regex pattern strings (`r"\bAny\b"`) with Python's `in` operator, which
    does literal string matching, not regex. The test checks whether the
    literal string `\bAny\b` (with backslash-b) appears in source files —
    which it never does. The test would pass even if every SDK file used `Any`
    everywhere. It provides zero coverage of the property it claims to verify.

15. The 9 `TransportEgress` methods added for the `execute_request` message
    obligations were given default no-op implementations. This is a silent
    fallback: a transport that does not implement `send_approval_prompt` will
    silently skip approvals instead of failing. Methods required for the
    operator experience must be abstract or capability-gated with explicit
    errors, not silently skipped.

## Why this is hard — lessons from the migration so far

The SDK interfaces already exist. That was the easy part.

The hard part is moving ownership of real behavior out of app code that already
works. This section exists so that implementers understand why the remaining
work is harder than it looks and what traps to avoid.

### What happened

1. We succeeded at defining the target architecture first. On paper the
   architecture improved quickly.

2. But the old runtime already had real behavior embedded in app code. Adding
   SDK interfaces did not automatically move that behavior.

3. We let "interface existence" look like progress. It was foundation-done,
   not migration-done.

4. We preserved old working paths while introducing new ones. That is how
   dual-path systems happen.

5. Tests encoded the old world. That makes half-migrations tempting.

6. The first implementation pass relocated callbacks instead of eliminating
   them, modified the plan to match incomplete work, and used "complete enough"
   as a completion state.

7. The SDK audit found that even the SDK's own composition classes use `Any`
   and `dict[str, Any]` at boundaries that should be typed. Type safety was
   applied unevenly — wire models are strict, but runtime composition and
   session/provider state are loose.

### The gravity centers

1. `octopus_sdk/execution.py` — callback fields on `ExecutionRuntime` are gone,
   but callable parameters were relocated to `ProviderDispatchRuntime` and
   implicit method obligations remain on the `message` parameter.

2. `app/registry_service/store.py` and `store_postgres.py` — authority-facing
   methods are typed but the broader store still uses `dict[str, Any]`.

3. Telegram implementation — still ~8,000+ lines across ~17 files. Target is
   ~1,500.

4. Fallback/noop paths survive in runtime composition.

5. SDK composition types — `BotRuntime.transport: Any`,
   `BotServicesPort.control_plane: Any`, `provider_state: dict[str, Any]`
   everywhere, `TransportIdentity` fields defaulting to empty string,
   `RunResult.denials: list[dict[str, Any]]`. The SDK's own types are not
   fully typed at their boundaries.

## Completed work

### SDK interfaces (all exist)

- `octopus_sdk/transport.py` — transport abstraction
- `octopus_sdk/bot_runtime.py` — `BotRuntime` with `submit(envelope)`
- `octopus_sdk/registry/authority_client.py` — `RegistryAuthorityClient`
- `octopus_sdk/registry_participant.py` — full participant hierarchy
- `octopus_sdk/registry_authority.py` — full authority hierarchy
- `octopus_sdk/workflows/*.py` — all workflow contract Protocols
- `octopus_sdk/work_queue.py` — `WorkQueuePort`
- `octopus_sdk/authorization.py` — `AuthorizationPort`

### Deleted old abstractions

- `octopus_sdk/channels.py`, `egress.py`, `runtime.py`, `runtime_dispatch.py`
- `app/workflows/*/contracts.py` Protocol definitions (moved to SDK)
- `DelegationRuntime` (old delegation path)

### Completed steps

- [x] Step C: Coordination migrated to SDK, dual delegation paths deleted,
  `delegation_channel.py` is presentation-only
- [x] Step E: Workflow and infrastructure contracts extracted to SDK
- [x] Step I (partial): `DelegationRuntime` deleted, workflow Protocols moved

## Hard decisions

These are fixed. Not options.

1. Ingress and egress are one transport abstraction (per-conversation egress).
2. Registry participation is a cross-cutting capability, not a channel.
3. Registry authority is interface-owned.
4. No transport-specific coordination logic.
5. No snapshot configuration for live runtime decisions.
6. No duplicate semantic paths.
7. No backward-compatibility shims.
8. No defaults, no guessing, no fallback routing.
9. Multi-authority is part of the contract with defined failure semantics.
10. Conformance tests built with each replacement, not after.
11. Each replacement atomically deletes what it replaces.
12. Registry authority communication is SDK-owned through the authority-client
    interface.
13. Mandatory implementation profiles fail startup and certification if
    incomplete.
14. The SDK must own every contract a transport needs for the full operator
    experience.
15. SDK composition and Protocol boundaries use typed SDK-owned types, not
    `Any` or `dict[str, Any]`.

## Multi-authority semantics (defined, not deferred)

For `create_conversation`, `publish_events`, `submit_message`, and
`submit_action`:

- Success requires at least one authority commit and durable persistence of
  retry obligations for every failed authority.
- If no authority commits, the operation fails.
- If retry obligations cannot be durably recorded, the operation fails.
- Deterministic identifiers make retries idempotent.
- Retry execution may be asynchronous. Retry obligation persistence is
  synchronous and mandatory before success is returned.

## Execution plan

### Warnings for implementers

1. **Interface existence is not progress.** The remaining work is moving
   BEHAVIOR, not defining contracts.

2. **Break the old path first, then fix forward.** Do not build alongside.

3. **Tests that assert old behavior are rewritten in the same change.**

4. **Relocating callbacks is not eliminating them.** If you move Callable
   fields from one class to another, the callbacks still exist. Make them SDK
   Protocol methods or eliminate them entirely.

5. **"Mostly done" is not done.** Neither is "complete enough" or
   "architecturally equivalent."

6. **Do not modify exit criteria to match the implementation.** Modify the
   implementation to match the exit criteria.

7. **Implicit interface obligations are callbacks. So are no-op defaults.**
   If `execute_request` expects methods on `message` that are not part of any
   SDK Protocol, those must be formalized or eliminated. If they are
   formalized onto the SDK Protocol, they must be either abstract (required —
   transport must implement or fail) or capability-gated (optional — SDK
   raises an explicit error if a transport calls a capability it did not
   declare). Default no-op implementations are silent fallbacks that make
   broken transports appear to work.

8. **`Any` is not a type.** If an SDK composition class or Protocol uses `Any`,
   it is untyped. Replace with a concrete SDK-owned type or Protocol.

9. **Empty-string defaults on required fields are silent bugs.** A
   `TransportIdentity()` with all empty strings is structurally valid but
   semantically broken. Required fields must not have defaults.

### Development model

Each step is a vertical slice: delete old paths + build replacements + rewrite
affected tests in one pass. The product ships only when ALL exit criteria pass.

### Step A: Eliminate ALL callback patterns (REOPENED)

Previously marked complete but callbacks were relocated, not eliminated.

**Remaining work:**
- [ ] A-R1: Eliminate 7 callable parameters on `ProviderDispatchRuntime`
  (`progress_factory`, `send_status`, `typing_target`, `keep_typing`,
  `heartbeat`, `format_provider_error`, `run_result_was_interrupted`). These
  must become SDK Protocol methods on `TransportEgress` or a new SDK
  `ProviderProgressPort`, not constructor-injected callables.
- [ ] A-R2: Eliminate 9 method obligations on the `message` parameter of
  `execute_request` (`reply_text`, `show_foreign_setup`, `show_setup_prompt`,
  `send_retry_prompt`, `send_approval_prompt`, `send_formatted_reply`,
  `send_directed_artifacts`, `send_compact_reply`, `propose_delegation_plan`).
  Each method must be classified as either:
  **(a) required** — abstract method on `TransportEgress` with no default
  implementation. Transport must implement it or fail at startup.
  **(b) capability-gated** — optional method tied to a `TransportDescriptor`
  capability flag. The SDK raises an explicit error if the runtime calls a
  method the transport did not declare support for. The `TransportEgress`
  default raises `NotImplementedError`, not silently returns `None`.
  Default no-op implementations are NOT acceptable — they are silent
  fallbacks that make incomplete transports appear to work.
- [ ] A-R3: Reference transport test requires zero callback stubs of any kind —
  no stub methods on message, no callable constructor parameters.
- [ ] A-R4: Delete or rewrite every test that constructs callbacks or stubs
  implicit message methods.

**Exit gate:**
- Zero Callable parameters on any runtime dataclass
- Zero implicit method obligations on `execute_request`'s `message` parameter
- Reference transport test has zero callback stubs

### Step B: BotRuntime composition (VERIFY + FIX)

Previously marked complete. Verify and fix type-safety issues.

**Remaining work:**
- [ ] B-V1: `BotRuntime` has `run()` method (review found it may be missing)
- [ ] B-V2: No composition path reaches into transport internals
- [ ] B-V3: `build_noop_control_plane_services` is deleted
- [ ] B-V4: `_DynamicWorkQueue` lazy proxy is deleted
- [ ] B-V5: `_default_registry_participant` noop builder is deleted
- [ ] B-F1: `BotRuntime.transport` must be typed as `TransportImplementation`,
  not `Any`
- [ ] B-F2: `BotServicesPort.control_plane` must be a typed SDK Protocol, not
  `Any`
- [ ] B-F3: `BotRuntime.startup` and `BotRuntime.shutdown` Callable fields must
  become Protocol methods or lifecycle hooks, not raw Callables
- [ ] B-R1: Move `WorkerRuntimeLifecycle` behavior (worker claim loop,
  stale-claim sweep, heartbeat) into `BotRuntime.run()`. Delete
  `WorkerRuntimeLifecycle` class from `services.py`. Delete
  `RuntimeLifecyclePort` from SDK if no other consumer needs it.
  `BotRuntime.run()` directly owns worker tasks — no external lifecycle
  delegate.

**Exit gate:**
- `BotRuntime` has both `submit(envelope)` and `run()`
- `BotRuntime.run()` owns full runtime lifecycle including worker tasks — no
  external lifecycle delegate class
- Zero `Any`-typed fields on `BotRuntime` or `BotServicesPort`
- Zero Callable fields on `BotRuntime`
- Zero noop/fallback/lazy-proxy composition paths survive

### Step D: Convert ALL store methods to typed records (REOPENED)

Previously marked complete but criterion was narrowed to "authority-facing"
methods only.

**Remaining work:**
- [ ] D-R1: ALL `AbstractRegistryStore` methods accept/return typed SDK
  records, not just authority-facing ones. The original criterion has no
  "authority-facing" qualifier.
- [ ] D-R2: `WorkQueuePort` record types (`WorkItemRecord`, `UserAccessRecord`,
  `UsageRecord`) must be typed SDK records, not `dict[str, Any]` aliases.
- [ ] D-R3: Both SQLite and Postgres stores pass full conformance suite with
  typed returns on ALL methods.
- [ ] D-R4: Delete or rewrite tests that assert dict-shaped returns from any
  store method.

**Exit gate:**
- `AbstractRegistryStore` uses typed SDK records on ALL methods
- `WorkQueuePort` uses typed records, not dict aliases
- No dict-shaped store interface survives

### Step D2: Fix SDK type-safety gaps (NEW)

The SDK's own composition and session/provider types have untyped boundaries
that were found during the audit. These are as important as store typing
because they are the SDK's own contract surface.

**Work:**
- [ ] D2-1: `provider_state` must be a typed SDK record, not `dict[str, Any]`.
  This affects `SessionState.provider_state`, `Provider.run()` parameter,
  `Provider.new_provider_state()` return, `RunResult.provider_state_updates`,
  and `PendingApproval.provider_state_snapshot`. Define a
  `ProviderStateRecord` or typed union that replaces `dict[str, Any]` at all
  these boundaries.
- [ ] D2-2: `RunResult.denials` must be `list[DenialRecord]`, not
  `list[dict[str, Any]]`. Define a typed `DenialRecord` dataclass.
- [ ] D2-3: `TransportIdentity` required fields (`conversation_key`,
  `origin_channel`, `actor`) must not have empty-string defaults. Remove
  defaults so that construction without these fields is a type error, not a
  silent empty value.
- [ ] D2-4: `ExecutionChannelMetadata` required fields must not have
  empty-string defaults for the same reason.
- [ ] D2-5: `RegistryRecordModel` in `registry/models.py` must use
  `extra="forbid"` like all other wire models, not `extra="allow"`.
- [ ] D2-6: `ProviderGuidancePort.build_run_context` parameters
  `available_agents: list[dict[str, str]] | None` and
  `credential_env: dict[str, str] | None` must use typed SDK records.
- [ ] D2-7: `SkillRequirement.validate: dict[str, Any] | None` must use a
  typed validation spec, not dict.
- [ ] D2-8: `CoordinationActionEnvelope.payload` in `registry/models.py` —
  if this is `dict[str, Any]`, it must be a typed union of the known action
  payload types.
- [ ] D2-9: `RoutedTaskRequest.context` and `RoutedTaskRequest.constraints` in
  `registry/models.py` — if these are `dict[str, Any]`, they must be typed.
- [ ] D2-10: `RuntimeHealthPayload.summary` and
  `RuntimeHealthPayload.diagnostics` — if these are `dict[str, Any]`, they
  must be typed.
- [ ] D2-11: Delete or rewrite tests that pass or assert `dict[str, Any]`
  through any of these SDK boundaries.
- [ ] D2-12: Reference transport test uses typed records at all SDK
  boundaries, no dict construction.

**Exit gate:**
- Zero `dict[str, Any]` at any SDK Protocol or composition boundary
- Zero `Any`-typed fields on any SDK composition class
- Zero empty-string defaults on required identity fields
- `extra="allow"` does not appear on any SDK wire model
- Reference transport test constructs only typed SDK records

### Step F: Rebuild Telegram (REOPENED)

Previously marked "complete enough" — a prohibited completion state. Files
claimed deleted still exist.

**Remaining work:**
- [ ] F-R1: Delete or consolidate `conversation.py` (still exists, claimed
  deleted in F4)
- [ ] F-R2: Delete or consolidate `pending.py` (still exists, claimed deleted)
- [ ] F-R3: Delete or consolidate `runtime_skills.py` (still exists, claimed
  deleted)
- [ ] F-R4: Delete or consolidate `cancellation.py` (still exists, claimed
  deleted)
- [ ] F-R5: Telegram total approaches ~1,500 line target. Current is ~8,000+.
- [ ] F-R6: Delete or consolidate `shared_mode_dispatch.py`
- [ ] F-R7: Delete or consolidate `inbound_context.py`
- [ ] F-R8: Delete or consolidate `guidance.py`
- [ ] F-R9: No test imports from deleted Telegram modules.

**Exit gate:**
- Telegram is ~1,500 lines across 5-6 files
- No old Telegram files survive except `__init__.py` and rendering module
- No test imports from deleted modules

### Step G: Rebuild registry bot-side (REOPENED)

Previously marked "complete enough" — a prohibited completion state.

**Remaining work:**
- [ ] G-R1: Inline or delete `agents/bridge.py` helpers into transport
- [ ] G-R2: Inline or delete `agents/delivery.py` helpers into transport
- [ ] G-R3: Inline or delete enrollment/heartbeat from `agents/runtime.py`
  into registry participant
- [ ] G-R4: No separate bridge-only semantic path remains

**Exit gate:**
- Registry bot-side is ~500 lines
- No `agents/bridge.py`, `agents/delivery.py`, or standalone
  `agents/runtime.py` delivery-polling paths survive

### Step H: Finish composition (REOPENED)

Previously marked complete but noop paths still exist.

**Remaining work:**
- [ ] H-R1: Delete `build_noop_control_plane_services`
- [ ] H-R2: Delete `_DynamicWorkQueue`
- [ ] H-R3: Delete `_default_registry_participant`
- [ ] H-R4: `main.py` reaches ~100 lines of pure composition
- [ ] H-R5: No silent no-op services survive for required profiles

**Exit gate:**
- `main.py` is ~100 lines
- Startup fails when mandatory capabilities absent
- Zero noop/fallback/proxy paths

### Step I: Delete remaining dual paths (REOPENED)

**Remaining work:**
- [ ] I-R1: Verify no dual paths remain (including relocated callbacks)
- [ ] I-R2: Verify SDK does not import `app.*`
- [ ] I-R3: Delete any test that guards old-world assumptions
- [ ] I-R4: Verify zero `Any`-typed fields survive on SDK composition classes
- [ ] I-R5: Verify zero `dict[str, Any]` survives at SDK Protocol boundaries

### Step J: Complete certification (REOPENED)

**Remaining work:**
- [ ] J-R1: Reference transport test requires zero callback stubs of ANY kind
- [ ] J-R2: Reference transport test dispatches all workflow commands without
  `app/` imports
- [ ] J-R3: Reference transport test uses typed SDK records at all boundaries
  — no dict construction, no Any casting
- [ ] J-R4: All six certification profiles have behavioral suites
- [ ] J-R5: Telegram passes transport + participant + workflow profiles
- [ ] J-R6: Registry authority passes full authority profile
- [ ] J-R7: SDK type-safety suite: zero `Any` on composition classes, zero
  `dict[str, Any]` at Protocol boundaries, zero empty-string defaults on
  required identity fields. The test must use actual regex matching or AST
  inspection — not literal string `in` checks with regex pattern strings.
  The current `test_sdk_type_safety.py` is broken and must be rewritten.
- [ ] J-R8: `TransportEgress` has zero default no-op method implementations
  for methods that affect operator experience. Each such method is either
  abstract (required) or raises `NotImplementedError` gated on a
  `TransportDescriptor` capability flag.

## Implementation profile matrix

| Implementation | Transport | Participant | Authority | Auth Client | Workflows | Infrastructure |
|---|---|---|---|---|---|---|
| Telegram runtime | required | required | — | — | required | required |
| Registry bot runtime | required | required (enrolled) | — | — | required | required |
| Registry authority server | — | — | required | — | — | — |
| HTTP RegistryClient | — | — | — | required | — | — |
| Future Slack runtime | required | configured | — | — | required | required |

## Hard exit criteria

These criteria are IMMUTABLE. They may not be reworded, qualified, scoped down,
or removed. If the implementation cannot meet a criterion, the implementation
must change.

This plan is complete only when ALL of the following are true:

1. `ExecutionRuntime` has zero Callable callback fields.
2. `ProviderDispatchRuntime` has zero Callable constructor parameters.
3. `execute_request` message methods are either abstract (required — no
   default) or capability-gated (optional — raises `NotImplementedError` if
   transport did not declare the capability). Zero default no-op
   implementations on `TransportEgress` for methods that affect operator
   experience.
4. SDK-owned `BotRuntime` exists with `submit(envelope)` and `run()`.
   `BotRuntime.run()` owns the full runtime lifecycle including worker claim
   loop, stale-claim sweep, and heartbeat tasks. No external lifecycle
   delegate class (no `WorkerRuntimeLifecycle`, no `RuntimeLifecyclePort`
   indirection).
5. `BotRuntime` has zero `Any`-typed fields and zero Callable fields.
6. `BotServicesPort` has zero `Any`-typed fields.
7. Transport receives `BotRuntimeHandle` at `start()` time.
8. One delegation path — `DelegationRuntime` (old) is deleted.
9. All coordination logic is SDK-owned or SDK-participant-owned.
10. `AbstractRegistryStore` uses typed SDK records on ALL methods, not
    `dict[str, Any]`. No "authority-facing" qualifier.
11. `WorkQueuePort` record types are typed SDK records, not `dict[str, Any]`
    aliases.
12. Both store backends pass identical authority conformance suite.
13. Telegram is ~1,500 lines and passes transport + participant + workflow
    profiles.
14. Registry bot-side passes transport profile; delivery is transport-owned.
    Target: ~500 lines.
15. No live runtime decision depends on startup-snapshot identity.
16. No transport-local coordination policy survives outside SDK interfaces.
17. Multi-authority create/publish/message/action semantics are
    contract-owned and tested.
18. The SDK includes behavioral certification suites for transport,
    participant, authority, authority-client, workflow, and infrastructure
    profiles.
19. `main.py` is pure profile-driven composition. Target: ~100 lines.
20. `main.py` fails startup when mandatory profile capabilities are absent.
21. No duplicate abstraction stacks, no compatibility shims, no fallback
    paths, no noop builders, no lazy proxies, no parallel old/new interfaces.
22. A new transport can be authored against the SDK without importing `app.*`
    — including full support for approvals, settings, skills, credentials,
    recovery, authorization, and durable admission.
23. Every old path that was replaced has been deleted.
24. Reference transport test requires zero callback stubs of any kind — no
    Callable constructor parameters, no implicit message methods.
25. No test guards old-world assumptions or imports deleted modules.
26. All workflow contract Protocols are SDK-owned. No Protocol definition
    remains in `app/workflows/*/contracts.py`.
27. `WorkQueuePort` and `AuthorizationPort` are SDK-owned Protocols with
    behavioral conformance tests using typed records.
28. No step may be marked complete while using "complete enough,"
    "architecturally equivalent," or any synonym for incomplete.
29. Zero `dict[str, Any]` at any SDK Protocol or composition class boundary.
    This includes `provider_state`, `denials`, `available_agents`,
    `WorkItemRecord`, `UserAccessRecord`, `UsageRecord`, action payloads,
    task context/constraints, and health summaries.
30. Zero `Any`-typed fields on any SDK dataclass used in runtime composition
    or Protocol signatures.
31. `TransportIdentity` required fields (`conversation_key`, `origin_channel`,
    `actor`) have no empty-string defaults.
32. `extra="allow"` does not appear on any SDK Pydantic model.
33. Reference transport test constructs only typed SDK records at all
    boundaries — no dict construction, no Any casting.
34. `TransportEgress` has zero default no-op implementations for methods that
    affect operator experience. Each is either abstract or capability-gated
    with `NotImplementedError`.
35. The SDK type-safety verification test uses real pattern detection (regex
    matching or AST inspection), not literal string `in` checks that pass
    regardless of violations.
36. `BotRuntime.run()` owns the full runtime lifecycle including worker tasks.
    No external lifecycle delegate class exists. No `WorkerRuntimeLifecycle`
    or `RuntimeLifecyclePort` indirection. Composition builds the runtime;
    the runtime owns everything after that.

## Dependencies

```
A-R (callbacks) → F-R (Telegram) → H-R (composition) → I-R (cleanup) → J-R (certification)
                → G-R (registry) ↗
D-R (store typing) runs in parallel
D2 (SDK type safety) runs in parallel
B-V/B-F (runtime verify+fix) runs in parallel
```

## Non-goals

- Preserving any old abstraction stack
- Temporary compatibility layers
- Partial registry support for our Telegram implementation
- "Best effort" multi-authority semantics
- Alternate code paths kept for safety
- Renaming concepts without fixing ownership
- Relocating callbacks instead of eliminating them
- Modifying exit criteria to match incomplete implementation
- Using "complete enough" as a completion state
- Building new paths alongside old paths
- Leaving workflow contracts in `app/`
- Qualifying exit criteria with "authority-facing" or other narrowing language
- Using `Any` at SDK composition or Protocol boundaries
- Using `dict[str, Any]` at SDK interface boundaries
- Defaulting required identity fields to empty strings
- Default no-op implementations on Protocol methods that affect operator
  experience
- Broken verification tests that pass regardless of violations (e.g., regex
  patterns used as literal strings in Python `in` checks)

## Final standard

Everything is an implementation of an interface.

Not some things. Everything.

Every replaced concept is deleted in the same change.

Not later. Not in a cleanup phase. In the same change.

Every test that asserts old behavior is rewritten in the same change.

Every SDK boundary uses typed SDK-owned types.

Not `Any`. Not `dict[str, Any]`. Not `Callable[..., Any]`.

Exit criteria are immutable. The implementation matches the criteria.

Not the other way around.
