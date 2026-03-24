# PLAN: Operational Remediation

## Context

Operational completeness (token tracking, delegation, UI controls) works end-to-end but was implemented as patches on top of Telegram-centric code. The execution workflow (`requests.py`) contains inline transport branching, ad-hoc identity resolution, event publishing logic, and delegation parsing — all of which should be channel-supplied or behind ports.

This plan remediates the patch stack into clean abstractions that any channel can implement without reading Telegram code.

## The two-identity problem

The codebase already models **provider execution identity** through `ResolvedExecutionContext` — role, skills, working dir, model, etc. Everything the LLM needs.

What's missing is **transport execution identity** — everything durable side effects need: which registry agent is acting, which channel originated this, what's the canonical conversation ref, how to publish events. Today this is derived inline from `isinstance(chat_id, int)` checks, empty-string fallbacks, and registry state file reads scattered across `requests.py`, `delegation_channel.py`, and `registry_publish.py`.

The fix: make transport identity a first-class, channel-supplied bundle — parallel to `ResolvedExecutionContext`.

## Problems

### P1: No transport identity abstraction
`execute_request` infers `origin_channel`, `external_conversation_ref`, and `target_agent_id` from `isinstance(chat_id, int)`. A new channel must fork this logic or copy it.

### P2: Event publishing is inline workflow code
`_publish_to_registry` is called at 4 points in `execute_request` with hand-built metadata. Event taxonomy, publish gating, and payload shape live in the workflow instead of behind a port.

### P3: Session identity instability
`new_provider_state()` generates a random UUID each call. Two `_load` calls for a non-persisted session produce different session_ids. Current fix is a callsite patch.

### P4: Delegated tasks have no shared context
Each routed task creates an isolated session on the target. M3 has no memory across tasks from the same parent conversation.

### P5: Delegation parsing is inline in the workflow
`<delegation>` tag parsing lives in `requests.py`. A provider that uses native tool calls for delegation can't plug in without editing the workflow.

### P6: target_agent_id="" hack
Publishing passes empty `target_agent_id` hoping an adapter callback fills it in. Fragile, violates the conversation ownership contract.

### P7: Conversation ID / ref / key normalization in wrong layer
HTTP middleware strips registry prefixes. Should be in `app/identity.py`.

### P8: Event kind migration incomplete
Usage queries changed from `'usage'` to `'provider.response'` without backward compat.

### P9: Delegation lifecycle events missing
Only `delegation.proposed` is published. No visibility into submission, completion, failure.

### P10: origin_agent_id assumes single registry
`resolve_origin_agent_id()` returns the first hit. Multi-registry gets wrong agent_id.

### P11: Capability auto-detection inaccurate
Agent card includes unverified capabilities derived from config.

### P12: prompt_weight inconsistency
`prompt_weight()` sizes the prompt without agent discovery context, underestimating when agents are injected.

## Decisions

1. **Extend `ExecutionChannelContext` into `TransportIdentity`** — `ExecutionChannelContext` already carries `conversation_ref`, `routed_task_id`, `authority_ref`. Rename it to `TransportIdentity` and add the missing transport fields (`conversation_key`, `origin_channel`, `external_conversation_ref`, `target_agent_id`, `actor`). `ExecutionChannelMetadata` stays as the channel-input type (pre-dispatch). This avoids three overlapping identity types.

2. **Introduce `ExecutionEventSink`** — an execution-layer adapter that composes `ConversationProjectionPort` + `should_publish_event` + transport identity. It is NOT a second projection API — projection is the capability, the sink is the execution-side façade. `execute_request` calls typed methods (`on_user_message`, `on_bot_reply`, `on_provider_response`, `on_error`); the sink handles gating, metadata, and projection. `execute_request` becomes pure orchestration.

3. **Deterministic session_id** — `new_provider_state()` seeded from conversation_key. No callsite patches.

4. **Delegation sessions keyed by parent relationship** — target bot uses `delegation:{origin_agent}:{parent_conversation}` as conversation_key. Shared Claude session across tasks.

5. **Pluggable delegation intent parser** — `DelegationIntentParser` protocol with default `<delegation>` XML parser. Provider or config can swap it.

6. **Bot identity on BotConfig** — `registry_agent_ids: dict[str, str]` (keyed by `registry_id`, e.g. `{"local": "0ace408e..."}`) populated at startup from enrollment state. Single writer: the enrollment pipeline writes connection state, startup reads it into config. No parallel identity source.

7. **Identity normalization in `app/identity.py`** — one function, used everywhere.

8. **Capabilities are explicit** — remove auto-detection.

9. **Sensible defaults for composition** — `delegation_parser=None` → default XML parser auto-created at execution time. `build_event_sink` with no projection → shared `NoOpEventSink` singleton. Empty `registry_agent_ids` + projection configured → fail fast at startup with clear error. A standard bot runs `execute_request` correctly with defaults; no hand-wired factories required.

## Phase 1: TransportIdentity (extend ExecutionChannelContext, per-request)

### 1.1 Rename and extend ExecutionChannelContext

`ExecutionChannelContext` already carries `conversation_ref`, `routed_task_id`, `authority_ref`, `timeline_callback`. Rename it to `TransportIdentity` and add the missing transport fields. This is an **extension**, not a new parallel type.

In `app/workflows/execution/contracts.py`:

```python
@dataclass(frozen=True)
class TransportIdentity:
    """Channel-supplied identity for durable side effects.

    Extended from the former ExecutionChannelContext. Parallel to
    ResolvedExecutionContext (provider-facing).

    Every channel builds one PER REQUEST; execute_request consumes it.

    IMPORTANT: ExecutionRuntime is long-lived (one per bot, shared across
    chats). TransportIdentity is per-execution — it MUST be a parameter to
    execute_request / dispatch_message_request, NOT a field on
    ExecutionRuntime. Two different chat_ids must never share a
    TransportIdentity instance.
    """
    # Existing fields (from ExecutionChannelContext):
    conversation_ref: str = ""     # full ref for delegation/delivery (e.g. "telegram:bot123:12345")
    routed_task_id: str = ""       # non-empty if this is a routed task execution
    authority_ref: str = ""        # registry authority for multi-registry
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None

    # New fields (transport identity for durable side effects):
    conversation_key: str = ""     # session DB key (e.g. "tg:12345", "registry:conversation:abc")
    origin_channel: str = ""       # "telegram", "registry", etc.
    external_conversation_ref: str = "" # channel-specific ref for registry create_conversation
    target_agent_id: str = ""      # this bot's agent_id on the relevant registry
    actor: str = ""                # display name of the originating user/system
```

`ExecutionChannelContext` is deleted (all references updated to `TransportIdentity`).
`ExecutionChannelMetadata` stays — it is the channel-input type (pre-dispatch), not execution-scoped.

### 1.2 ExecutionRuntime: ports and factories, not identity

`ExecutionRuntime` stays long-lived. It holds:
- **Port**: `agent_directory`
- **Per-request factories**: `build_transport_identity`, `build_event_sink` (both called once per execution. `RegistryEventSink` is new per request; `NoOpEventSink` is a shared singleton.)
- **Callbacks**: send_reply, send_approval, etc. (as today)

It does NOT hold `TransportIdentity` or `conversation_projection` directly.

**`build_channel_context` is removed.** It was the factory for the old `ExecutionChannelContext`. Since `TransportIdentity` subsumes those fields, `build_transport_identity` replaces it. There must be exactly one factory that produces the per-request identity — not two factories returning overlapping shapes.

```python
@dataclass(frozen=True)
class ExecutionRuntime:
    dispatch: RuntimeDispatchRuntime
    build_transport_identity: Callable[[Any, int | str], TransportIdentity]  # per-request factory (replaces build_channel_context)
    build_event_sink: Callable[[TransportIdentity], ExecutionEventSink]      # per-request factory (RegistryEventSink: new per call; NoOpEventSink: shared singleton)
    agent_directory: AgentDirectoryPort | None = None
    delegation_parser: DelegationIntentParser | None = None                  # Phase 4
    # ... channel callbacks (send_reply, etc.) stay as-is
```

### 1.3 execute_request builds identity at the top

```python
async def execute_request(chat_id, prompt, message, ..., *, runtime):
    transport = runtime.build_transport_identity(message, chat_id)
    event_sink = runtime.build_event_sink(transport)
    # All subsequent code uses transport.origin_channel, transport.target_agent_id, etc.
    # No isinstance(chat_id, int) anywhere.
    # event_sink is a fresh instance scoped to this request — safe for concurrent chats.
```

### 1.4 Channel builders supply the factory

**Telegram** (`app/channels/telegram/execution.py`):
```python
def _build_telegram_transport(message, chat_id: int | str) -> TransportIdentity:
    if isinstance(chat_id, int):
        return TransportIdentity(
            conversation_key=telegram_conversation_key(chat_id),
            origin_channel="telegram",
            external_conversation_ref=str(chat_id),
            target_agent_id=config.registry_agent_ids.get("local", ""),
            conversation_ref=telegram_conversation_ref(config, chat_id),
        )
    # Registry-originated message delivered through Telegram worker
    return TransportIdentity(
        conversation_key=parse_conversation_key(chat_id),
        origin_channel="registry",
        external_conversation_ref=str(chat_id),
        target_agent_id=config.registry_agent_ids.get("local", ""),
        conversation_ref=str(chat_id),
    )
```

The `isinstance` check moves to the **channel adapter** (where it belongs) — the one place that knows what `chat_id` means. `execute_request` never sees it.

**Exit gate**: `execute_request` has zero `isinstance` checks on `chat_id`. All transport fields come from `transport`. Two concurrent chats cannot share identity.

## Phase 2: ExecutionEventSink

### 2.1 Define the port

In `app/ports/execution_events.py`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ExecutionEventSink(Protocol):
    async def on_user_message(self, content: str, actor: str = "") -> None: ...
    async def on_bot_reply(self, content: str, actor: str = "") -> None: ...
    async def on_provider_response(self, prompt_tokens: int, completion_tokens: int, cost_usd: float, provider: str = "") -> None: ...
    async def on_error(self, error_text: str, error_type: str = "execution") -> None: ...
    async def on_delegation_proposed(self, task_count: int, targets: list[str]) -> None: ...
    async def on_delegation_submitted(self, task_count: int) -> None: ...
    async def on_delegation_completed(self, summary: str) -> None: ...
```

### 2.2 Registry-backed implementation

In `app/workflows/execution/event_sink.py`:

```python
class RegistryEventSink:
    """Publishes execution events to the registry via ConversationProjectionPort.

    Constructed per-request from TransportIdentity — never shared across chats.
    """
    def __init__(self, projection: ConversationProjectionPort, transport: TransportIdentity, config: BotConfig):
        self._projection = projection
        self._transport = transport
        self._config = config

    async def on_provider_response(self, prompt_tokens, completion_tokens, cost_usd, provider=""):
        if not should_publish_event(self._config, "provider.response"):
            return
        # create_conversation + publish_events — all in one place
        # Uses self._transport.target_agent_id, self._transport.origin_channel, etc.
        ...
```

### 2.3 NoOp implementation

For bots without registry enrollment. Stateless and thread-safe — a single shared instance is fine:
```python
class NoOpEventSink:
    async def on_user_message(self, content, actor=""): pass
    async def on_bot_reply(self, content, actor=""): pass
    # ... all no-ops
```

### 2.4 Factory on ExecutionRuntime

The runtime holds a **factory**, not a sink instance:

```python
# In build_execution_runtime (channel adapter):
_noop_sink = NoOpEventSink()  # shared, stateless

build_event_sink=(
    (lambda transport: RegistryEventSink(
        projection=runtime.services.control_plane.conversation_projection,
        transport=transport,
        config=runtime.config,
    ))
    if runtime.services.control_plane.conversation_projection
    else (lambda _transport: _noop_sink)
)
```

`execute_request` calls `runtime.build_event_sink(transport)` at the top to get a per-request sink.

### 2.5 Shared sink construction helper for non-execute_request paths

`execute_request` gets a sink from `runtime.build_event_sink(transport)`. But delegation button callbacks, delivery handlers, and other entry points also need to publish events (e.g. `delegation.submitted`). These don't have an `ExecutionRuntime` — they have config, projection port, and enough context to build a `TransportIdentity`.

Add one shared helper in `app/workflows/execution/event_sink.py`:

```python
def build_event_sink_for_context(
    transport: TransportIdentity | None,
    projection: ConversationProjectionPort | None,
    config: BotConfig,
) -> ExecutionEventSink:
    """Build an event sink from available context.

    Used by delegation handlers, delivery processors, and any path
    outside execute_request that needs to publish execution events.
    Returns NoOpEventSink if transport or projection is unavailable.
    """
    if transport is None or projection is None:
        return _NOOP_SINK
    if not should_publish_event(config, "message.user"):  # proxy for "any publishing enabled"
        return _NOOP_SINK
    return RegistryEventSink(projection=projection, transport=transport, config=config)

_NOOP_SINK = NoOpEventSink()  # module-level singleton
```

This is the **single construction point** for sinks outside `execute_request`. Delegation handlers, delivery processors, and future entry points all use it. No re-implementing sink wiring per call site.

### 2.6 Remove _publish_to_registry from execute_request

Replace 4 inline publish calls with:
```python
await event_sink.on_user_message(prompt, actor=str(request_user_id))
# ... later:
await event_sink.on_provider_response(result.prompt_tokens, ...)
```

**Exit gate**: `_publish_to_registry` is not imported or called from `requests.py`. All execution-originated event publishing goes through the sink or `build_event_sink_for_context`. No other construction path exists.

## Phase 3: Session identity stability

### 3.1 Deterministic session_id

`new_provider_state()` on Provider protocol accepts optional `conversation_key`:

```python
def new_provider_state(self, conversation_key: str = "") -> dict[str, Any]:
    sid = str(uuid5(NAMESPACE_URL, conversation_key)) if conversation_key else str(uuid4())
    return {"session_id": sid, "started": False}
```

`load_runtime_session` passes `conversation_key` to `provider_state_factory`.

### 3.2 Remove callsite workaround

Delete `if not session.provider_state.get("started"): _save(...)` from `execute_request`.

**Exit gate**: Same conversation_key always produces same initial session_id. Double-load is harmless.

## Phase 4: Delegation architecture

### 4.1 DelegationIntentParser protocol

In `app/ports/delegation.py`:

```python
@runtime_checkable
class DelegationIntentParser(Protocol):
    def parse(self, response_text: str, available_agents: list[dict[str, str]]) -> list[dict[str, str]]: ...
```

Default implementation: `XmlTagDelegationParser` (the current `<delegation>` logic, extracted from `requests.py`).

### 4.2 Shared delegation sessions on target

In `app/identity.py`:
```python
def delegation_session_key(origin_agent_id: str, parent_conversation_id: str) -> str:
    return f"delegation:{origin_agent_id}:{parent_conversation_id}"
```

`app/agents/delivery.py` uses this when processing routed tasks instead of per-task conversation_key.

### 4.3 Delegation lifecycle events via EventSink

`handle_delegation_approve` in `app/agents/delegation.py` takes an optional `ExecutionEventSink` and publishes `delegation.submitted`, `delegation.completed`, etc. No channel-specific event publishing. When called from `execute_request`, the sink is the same per-request instance built from the current `TransportIdentity`. When called from other paths (e.g. Telegram button callback, delivery handler), the caller uses `build_event_sink_for_context(transport, projection, config)` from §2.5 — the single shared construction point. If transport context is unavailable, the helper returns `NoOpEventSink` and events are silently skipped.

### 4.4 Move delegation event publishing from Telegram channel to shared handler

`publish_delegation_proposed_event` moves from `delegation_channel.py` to `app/agents/delegation.py`, using the event sink.

**Exit gate**: `requests.py` calls `runtime.delegation_parser.parse(...)`. No inline regex. Delegation events published from shared code, not Telegram-specific.

## Phase 5: Bot identity on BotConfig

### 5.1 registry_agent_ids on BotConfig

```python
@dataclass(frozen=True)
class BotConfig:
    ...
    registry_agent_ids: dict[str, str] = field(default_factory=dict)
```

Populated at startup after enrollment, cached for the lifetime of the process.

### 5.2 Replace all ad-hoc resolution

- `resolve_origin_agent_id()` reads from `config.registry_agent_ids`
- `_agent_id_for_authority` callback reads from `config.registry_agent_ids`
- `TransportIdentity.target_agent_id` set from `config.registry_agent_ids` at construction

### 5.3 Multi-registry support

`resolve_origin_agent_id(config, registry_id)` scoped to target registry.

**Exit gate**: No code reads registry state files ad-hoc. All agent_id goes through BotConfig.

## Phase 6: Identity normalization + event kind compat

### 6.1 normalize_conversation_id in app/identity.py

```python
def normalize_conversation_id(raw: str) -> str:
    parts = raw.split(":")
    if len(parts) >= 4 and parts[-2] == "conversation":
        return parts[-1]
    return raw
```

### 6.2 Remove HTTP middleware

HTTP layer calls `identity.normalize_conversation_id` via FastAPI dependency. No middleware.

### 6.3 Dual-query for event kinds (one-time registry store update)

This is a **one-time** backward-compat change to the registry store, not a per-bot or per-channel change. After this, new channels do not touch the store.

```sql
WHERE kind IN ('usage', 'provider.response')
```

In both SQLite and Postgres stores. Documented deprecation.

**Exit gate**: `normalize_conversation_id` lives only in `app/identity.py`. HTTP layer imports it; no middleware or private copies. Usage page shows both old and new events.

## Phase 7: Prompt sizing + capabilities

### 7.1 prompt_weight consistency

`prompt_weight()` accepts the same parameters as `system_prompt()`, including `available_agents`. Or: introduce `effective_prompt_for_sizing()` that returns the actual prompt text and its length.

### 7.2 Capabilities explicit only

Revert `_effective_capabilities()`. Agent card uses `config.agent_capabilities` directly.

**Exit gate**: `prompt_weight` and `system_prompt` always see the same inputs.

## Phase 8: Cleanup

- Remove debug session_id logging
- Fix import ordering (stdlib before local)
- Remove defensive `delegation_submitted` status filter from egress
- Remove `_publish_to_registry` import from `requests.py` (moved to event sink)
- Remove `_resolve_origin_agent_id` from `delegation_channel.py` (moved to `app/agents/delegation.py`)

## Implementation sequence

The recommended vertical slice: **(5) config-backed agent IDs → (1) per-request TransportIdentity → (2) event sink → slim requests.py**, then session stability, delegation, and cleanup in dependency order.

| Order | Phase | Size | Depends on |
|-------|-------|------|------------|
| 1 | Phase 5 (bot identity on config) | Small | Nothing |
| 2 | Phase 3 (session stability) | Small | Nothing |
| 3 | Phase 6 (normalization + event compat) | Small | Nothing |
| 4 | Phase 1 (TransportIdentity) | Medium | Phase 5 |
| 5 | Phase 2 (ExecutionEventSink) | Medium | Phases 1, 5 |
| 6 | Phase 4 (delegation architecture) | Medium | Phases 1, 2, 3 |
| 7 | Phase 7 (prompt sizing + capabilities) | Small | Phase 4 |
| 8 | Phase 8 (cleanup) | Small | All above |

Phases 3, 5, 6 are independent foundations. Phase 1 + 2 are the core refactor. Phase 4 is the delegation vertical. Phase 8 is sweep.

## Tests (minimum per phase)

| Phase | Tests |
|-------|-------|
| Phase 1 | Unit: `TransportIdentity` builders for Telegram + registry delivery metadata. Regression: two concurrent `chat_id`s with shared runtime share no `TransportIdentity` bleed. |
| Phase 2 | Unit: `RegistryEventSink` emits correct kinds + metadata; respects `should_publish_event`. Unit: `NoOpEventSink` is silent. Config matrix: `BOT_REGISTRY_PUBLISH_LEVEL=minimal` → no `provider.response` emitted. |
| Phase 3 | Unit: same `conversation_key` → same `session_id` across multiple `new_provider_state` calls. |
| Phase 4 | Unit: `DelegationIntentParser` + slug resolution. Unit: `delegation_session_key` produces stable keys. Integration: two consecutive delegations share one session on target. Unit: stub parser proves the hook works without editing `requests.py`. |
| Phase 5 | Unit: `registry_agent_ids` populated from enrollment state. Smoke: minimal `ExecutionRuntime` with NoOp sink + empty `registry_agent_ids` runs `execute_request` without crash. |
| Phase 6 | Integration: usage API aggregates both legacy `usage` and `provider.response` rows. Contract parity: SQLite and Postgres stores return same results for same input. |
| Phase 7 | Unit: `prompt_weight` matches `system_prompt` output length when `available_agents` provided. |

## Channel SDK surface (what a new channel implements)

After this plan, a new channel needs:

1. **`build_transport_identity()` factory** — return a `TransportIdentity` from channel-specific message metadata. Register as the `build_transport_identity` callable on `ExecutionRuntime`.
2. **Channel egress callbacks** — `send_formatted_reply`, `send_approval_prompt`, etc. (already required)
3. **Register ports at startup** — `ConversationProjectionPort`, `AgentDirectoryPort`, `TaskRoutingPort` (already required via bus)

Everything else is automatic:
- Event publishing → `ExecutionEventSink` constructed per-request from `TransportIdentity` + projection port via the `build_event_sink` factory on `ExecutionRuntime`
- Delegation → shared `handle_delegation_approve` + `DelegationIntentParser`
- Session management → `conversation_key` from `TransportIdentity`, deterministic session_id
- Identity normalization → `app/identity.py` functions

No copying from `requests.py`. No `isinstance(chat_id, int)`.

## Files changed

| File | Changes |
|------|---------|
| `app/workflows/execution/contracts.py` | Rename `ExecutionChannelContext` → `TransportIdentity` (extend with transport fields); add factories to `ExecutionRuntime`; delete `ExecutionChannelContext` |
| `app/ports/execution_events.py` | NEW — `ExecutionEventSink` protocol |
| `app/ports/delegation.py` | NEW — `DelegationIntentParser` protocol |
| `app/workflows/execution/event_sink.py` | NEW — `RegistryEventSink`, `NoOpEventSink`, `build_event_sink_for_context` |
| `app/workflows/execution/delegation_parser.py` | NEW — `XmlTagDelegationParser` (extracted from requests.py) |
| `app/workflows/execution/requests.py` | Consume TransportIdentity, EventSink, DelegationParser; remove inline branching/publishing/parsing |
| `app/workflows/execution/registry_publish.py` | DELETE — replaced by EventSink. Non-execution callers (e.g. `delegation_channel.py`) updated to use the sink or inlined. |
| `app/providers/claude.py` | Deterministic `new_provider_state` |
| `app/providers/base.py` | Provider protocol: `new_provider_state(conversation_key)` |
| `app/runtime/session_runtime.py` | Pass conversation_key to provider_state_factory |
| `app/config.py` | Add `registry_agent_ids` |
| `app/identity.py` | Add `normalize_conversation_id`, `delegation_session_key` |
| `app/agents/runtime.py` | Populate registry_agent_ids; revert capability auto-detection |
| `app/agents/delegation.py` | Accept EventSink; publish lifecycle events; multi-registry origin_agent_id |
| `app/agents/delivery.py` | Delegation session key from parent relationship |
| `app/channels/telegram/execution.py` | Build TransportIdentity; build EventSink; simplify |
| `app/channels/telegram/delegation_channel.py` | Remove event publishing (moved to shared handler) |
| `app/channels/registry/http.py` | Replace middleware with identity.normalize calls |
| `app/channels/registry/egress.py` | Remove defensive status filter |
| `app/registry_service/store.py` | Dual-query for usage kinds |
| `app/registry_service/store_postgres.py` | Same |
| `app/provider_guidance_service.py` | prompt_weight accepts available_agents |

## Non-goals

- No new persistence seams or tables
- No new channel types (but the surface is now defined for one)
- No changes to the bus model
- No provider-native delegation tools (keep parser pluggable first; provider hooks come later)
- No migration scripts (dual-query handles old data)
- No changes to `ResolvedExecutionContext` (provider identity is already the right seam for LLM identity)
- No big `ExecutionRuntime` restructure beyond adding factories — callbacks stay as-is this pass
- **New channels must not require registry schema, SDK model, or existing bot changes.** Only new bot/channel implementations and deployment config. `origin_channel` and `external_conversation_ref` are the extension points — no channel-specific columns, event kinds, or SDK fields.

---

## Remaining work (post-initial implementation)

### Phase 9: Test performance (do first — unblocks all verification)

**Problem:** Full suite is 465s (7.7min). `test_handlers.py` alone is 389s. 13 tests take 25-50s each due to bus timeouts from `RegistryEventSink` publishing through an unprocessed control plane bus.

**Root cause:** Tests that configure `agent_registries` get a real `ConversationProjectionPort` backed by the bus. The event sink publishes through it, each call times out at 5s. Multiple publish calls per test × 5s = 25-50s per test.

**Fix:**
1. Add `registry_publish_level: "off"` to all `test_handlers.py` test configs that use `agent_registries` but don't assert on event publishing. This makes `build_event_sink_for_context` return `NoOpEventSink`.
2. For the 2 tests that specifically test delegation event publishing (`test_delegation_proposed_event_published`, `test_worker_dispatch_skips_completion_webhook_for_delegation_proposed`): mock the projection port to return immediately instead of going through the bus.
3. `test_invariants.py::test_format_provider_error_kills_subprocess_on_timeout` (15s) — inherent subprocess timeout test, leave as-is.

**Exit gate:** Full suite under 60s. No test takes >5s except explicit timeout tests.

### Phase 10: Fix worker-to-execution actor handoff

**Problem:** Worker passes normalized `actor_key` into `dispatch_message_request`, but `execute_request` ignores it — uses `transport.actor` instead. In the worker path, `transport.actor` is built from `message.from_user` on the channel egress object (not the original inbound message), so it's empty. This means:
- Credential/setup ownership checks run without the real actor
- Registry events lose actor attribution

**Fix:**
1. `execution_channel_metadata` must accept `actor_key` as an explicit parameter (not derive it from message.from_user when the message is a channel egress)
2. Worker passes the already-normalized `actor_key` through to `execution_channel_metadata` → `TransportIdentity.actor`
3. `execute_request` uses `transport.actor` for everything (already does after our changes)

**Test:**
- Unit: worker-originated execution has correct `transport.actor`
- Unit: `FakeMessage` in test harness sets `from_user` with an id so `transport.actor` is non-empty

**Exit gate:** `transport.actor` is never empty in any execution path. Tests pin the handoff.

### Phase 11: Fix remaining test failures (15 failures from profiling run)

**Failures by category:**

1. **Delegation tests (6 failures):** `handle_delegation_approve/cancel` signature changed to `conversation_key` but test helpers still pass `chat_id`. Fix: update test helpers to pass `_conversation_key(chat_id)`.

2. **Registry service tests (4 failures):** `CODEX_SANDBOX` config validation error — test config passes invalid value `'seatbelt'`. Fix: update test config or use valid sandbox value.

3. **Skills tests (2 failures):** Same `CODEX_SANDBOX` config issue.

4. **Delegation boundary tests (3 failures):** `actor_key` rename broke assertions on `pending_delegation` field names. Fix: update assertions.

**Exit gate:** 0 failures, 0 errors in full suite.

### Phase 12: Update test_operational_units.py

Add tests for:
- Deterministic session_id: same conversation_key → same uuid5 session_id
- `ExecutionRuntime` shape: `build_transport_identity` and `build_event_sink` are required fields, no `build_channel_context`
- Authority-scoped agent_id: `agent_id_for_registry` returns correct value per registry
- Worker actor handoff: `transport.actor` populated from normalized actor_key
- `delegation_session_key`: multiple tasks from same parent share key

### Resolved items (verified correct, no action needed)

- **`target_agent_id=""` fallback** in `execution.py:329` — legitimate "no registries configured" case. The mirrored projection adapter overrides per-authority on fan-out in production.
- **`str(chat_id)` as `external_conversation_ref`** in `execution.py:350` — Telegram adapter converting chat_id to string for the transport field. Correct.
- **`_conversation_key(chat_id)` and `isinstance(chat_id, int)` in `channels/telegram/`** — Telegram boundary code that correctly uses `telegram_conversation_key`. The plan's scope was the workflow layer (`requests.py`), not rewriting every Telegram channel internal. Channel-level type dispatch is legitimate at the transport boundary.
- **`_actor_key(event.user.id)` calls in Telegram channel code** — boundary normalizations. Correct pattern: normalize raw Telegram IDs at the channel boundary, thread only `actor_key` strings into shared code.
- **First-hit `target_agent_id` fallback in Telegram execution** — less concerning now because the mirrored projection adapter is wired with per-authority `agent_id_for_authority` in production, so it can override on fan-out.

### Full test suite verification

The 263 core tests pass but the full ~1800 tests haven't been verified since the `actor_key` rename. Phase 11 covers fixing the 15 known failures from the profiling run plus any additional failures from the rename. Some tests may still reference old field names (`request_user_id`, `user_id` on `AwaitingSkillSetup`) or pass wrong types.

### Execution sequence

1. **Phase 9** (test performance) — unblocks fast iteration
2. **Phase 10** (actor handoff) — fixes the remaining P1 correctness bug
3. **Phase 11** (test failures) — achieves 0 failures in full suite
4. **Phase 12** (unit tests) — pins the contracts
