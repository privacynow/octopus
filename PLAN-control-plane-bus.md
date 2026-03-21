# Control-Plane Capability Architecture Plan

## Problem Statement

Registry control-plane concerns are smeared across channel, worker,
and workflow code through 11 direct `if registry_runtime is not None`
branches, dual client-construction paths, and registry-specific
factory callables on channel runtimes. This violates the port +
factory rule, creates parallel paths for the same concern, and
means every future channel (Slack, WhatsApp) would inherit the same
coupling.

## Architecture Decision Record

**Why registry-shaped ports are rejected.** A port named
`RegistryPort` or `RegistryOutbound` couples every consumer to the
existence of registries. When Slack admin or Telegram admin surfaces
arrive, they would need a different port — or the "registry" port
would grow methods unrelated to registries. The abstraction must be
capability-based: what the system needs, not which backend provides
it.

**Why control-plane capabilities are the abstraction.** The system
needs four domain operations: project conversations externally, route
tasks between agents, discover agents, and publish health. Registry
happens to implement all four today. A future Slack admin surface
might implement conversation projection and health publication but
not task routing. Capability-based ports let implementations vary
independently.

**Why the bus is first-class storage.** Workers should not make
external HTTP calls for control-plane operations. They express intent.
A processor fulfills it. The bus decouples producers (any process
role) from processors (only roles with live backends). This
eliminates the "state-backed vs runtime-backed" split that caused
the shared-worker regressions.

**Why no queue library is adopted.** No existing Python queue library
(Celery, Dramatiq, Arq, Huey, Procrastinate) satisfies SQLite +
Postgres parity without an external broker. The repo already has a
battle-tested durable storage pattern (CAS updates, state machines,
contract tests) in the work queue. The bus extends that pattern
rather than introducing new infrastructure.

## Non-Negotiables

- No non-registry orchestration code may branch on
  `registry_runtime`, `registry_id`, or registry client construction.
- No channel runtime owns registry-specific fields.
- No direct HTTP control-plane I/O from worker/channel/finalization.
- Channel registration belongs to startup composition, not runtime
  mutation.
- No "state-backed" concept in abstractions; persisted state is
  internal to control-plane implementations only.
- Every new storage seam gets SQLite + Postgres + contract tests in
  the same sequence.
- No `is_available()` booleans on ports. Typed unavailable
  results/errors instead.
- No generic control-plane port or UI path may expose
  `registry_scope`; generic seams speak in capabilities or purpose,
  not registry-specific vocabulary.
- No implicit singleton/default registry selection. Invalid or
  unqualified registry inputs fail fast instead of inventing
  `"default"` or picking the first configured registry.
- Compatibility translators are temporary migration debt, not
  architecture. If a runtime shim remains, the plan must name the
  slice that deletes it.

## Repo Rules (AGENTS.md / CLAUDE.md)

- **Port + Factory Rule**: Orchestration imports only abstract ports.
- **No parallel paths**: One path per concern.
- **Extend before inventing**: Reuse existing transport store
  patterns. Do not invent new infrastructure.
- **Registry store parity**: SQLite + Postgres + migration + contract
  test per storage slice.
- **Transport parity**: Bus follows same discipline as work queue.
- **No hand-rolled infrastructure**: Use `python-statemachine` for
  lifecycle, `pydantic` for command/reply schemas, `psycopg` for
  Postgres. Use existing CAS patterns.
- **Interfaces before implementations**: Ports defined before any
  concrete implementation lands.

## Target Architecture

### Layer 1: Capability Ports (`app/ports/`)

Four protocols, each owning one domain concern. Named by what they
do, not by which backend they talk to.

```python
# app/ports/conversation_projection.py
class ConversationProjectionPort(Protocol):
    async def bind_external_conversation(
        self, *, conversation_ref: str, title: str,
        origin_channel: str, external_id: str,
    ) -> None: ...

    async def publish_external_timeline(
        self, *, conversation_ref: str, kind: str, title: str,
        body: str = "", status: str = "", progress: int | None = None,
        metadata: dict | None = None, event_id: str | None = None,
    ) -> None: ...
```

```python
# app/ports/task_routing.py
class TaskRoutingPort(Protocol):
    async def submit_routed_task(
        self, *, request: RoutedTaskRequest, authority_ref: str,
    ) -> TaskSubmissionResult: ...

    async def report_routed_task_result(
        self, *, routed_task_id: str, authority_ref: str,
        result: RoutedTaskResult,
    ) -> TaskResultReport: ...

    async def update_routed_task_status(
        self, *, update: RoutedTaskUpdate, authority_ref: str,
    ) -> None: ...
    # Fire-and-forget: status updates are best-effort, like timeline.
    # The domain payload remains full RoutedTaskUpdate even though
    # the transport semantics are one-way. No typed result needed.
```

```python
# app/ports/agent_directory.py
class AgentDirectoryPort(Protocol):
    async def search_agents(
        self, *, query: AgentDiscoveryQuery,
    ) -> AgentSearchResult: ...

    async def resolve_target_authority(
        self, *, target_agent_id: str,
    ) -> AuthorityResolution: ...
```

**Scatter-gather semantics**: `search_agents()` is a multi-authority
operation. The adapter submits N request/reply commands (one per
authority that implements `agent_directory`), collects N replies
with a bounded timeout, and aggregates results. Each
`DiscoveredAgentRef` in the aggregated result carries the
`authority_ref` of the authority that returned it. Partial results
(some authorities timed out) are returned with a status indicating
which authorities responded.

**Typed results**:
```python
class AgentSearchResult(BaseModel):
    agents: list[DiscoveredAgentRef]
    status: str  # "complete" | "partial" | "unavailable"
    responding_authorities: list[str]
    timed_out_authorities: list[str]

class AuthorityResolution(BaseModel):
    authority_ref: str   # resolved authority, or ""
    status: str          # "resolved" | "ambiguous" | "not_found" | "unavailable"
    error: str = ""
```

```python
# app/ports/health_publication.py
class HealthPublicationPort(Protocol):
    async def publish_health(
        self, *, report: HealthReport,
    ) -> None: ...

    def connection_summary(self) -> ConnectionSummary: ...
```

```python
# Typed models (in app/ports/ or app/control_plane/requests/)
class HealthReport(BaseModel):
    connectivity_state: str
    current_capacity: int = 0
    max_capacity: int = 1
    runtime_health_json: str = ""

class ConnectionSummary(BaseModel):
    authorities: list[AuthorityStatus]

class AuthorityStatus(BaseModel):
    authority_ref: str
    connectivity_state: str
    capabilities: list[str]
```

**Key vocabulary:**
- `authority_ref` replaces `registry_id` in external-facing types.
  Consumers say "the authority that told me about this agent," not
  "the registry." Registry implementation maps `authority_ref` to
  `registry:<id>` internally.
- Return types like `TaskSubmissionResult` and `TaskResultReport`
  are typed results, not raw dicts. They include status and optional
  error information so callers handle unavailable/failed cases in
  normal control flow — no `is_available()` booleans.

### Layer 2: Services Container

```python
# app/runtime/services.py
@dataclass
class ControlPlaneServices:
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    health_publication: HealthPublicationPort

@dataclass
class BotServices:
    control_plane: ControlPlaneServices
```

`BotServices` will eventually hold non-control-plane services too
(content store, credential store). Nesting keeps the boundary
visible: `services.control_plane.conversation_projection`.

Every channel runtime gets `services: BotServices`. No nullable
fields — standalone bots get no-op implementations that return
typed "unavailable" results where applicable and silently succeed
for fire-and-forget operations.

### Layer 3: Control-Plane Bus (`app/control_plane/`)

A durable command/reply transport. First-class subsystem with same
discipline as the work queue.

#### Schema

```sql
CREATE TABLE IF NOT EXISTS control_plane_commands (
    seq               INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id        TEXT NOT NULL UNIQUE,
    capability        TEXT NOT NULL,
    operation         TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'pending',
    priority          INTEGER NOT NULL DEFAULT 0,
    correlation_id    TEXT NOT NULL DEFAULT '',
    authority_ref     TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL DEFAULT '',
    result_json       TEXT,
    error             TEXT,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    max_retries       INTEGER NOT NULL DEFAULT 3,
    created_at        TEXT NOT NULL,
    claimed_at        TEXT,
    completed_at      TEXT,
    lease_expires_at  TEXT,
    next_attempt_at   TEXT,
    CHECK (state IN ('pending', 'claimed', 'completed', 'failed',
                     'dead_letter')),
    CHECK (authority_ref != '')
);
CREATE INDEX idx_cp_state
    ON control_plane_commands (state, next_attempt_at, priority DESC, seq);
CREATE INDEX idx_cp_correlation
    ON control_plane_commands (correlation_id)
    WHERE correlation_id != '';
CREATE UNIQUE INDEX idx_cp_idempotency
    ON control_plane_commands (capability, operation, authority_ref, idempotency_key)
    WHERE idempotency_key != '';
```

**Schema notes**:
- `authority_ref` is `NOT NULL` and has a `CHECK != ''` — no
  broadcast commands. Every command targets a specific authority.
- `next_attempt_at` — durable backoff scheduling. When a command
  fails and is retried, `next_attempt_at` is set to
  `now + backoff_interval`. The poll query filters
  `WHERE next_attempt_at IS NULL OR next_attempt_at <= now`.
- Idempotency unique index is composite:
  `(capability, operation, authority_ref, idempotency_key)`.
  The same natural key can legitimately appear for different
  authorities or operations.

Both SQLite and Postgres. Postgres schema under
`app/db/migrations/postgres/`. Column uses `authority_ref`, not
`registry_id` — the bus is backend-agnostic.

#### Backend Selection

Control-plane storage follows the existing runtime backend seam.

- Extend `app/runtime_backend.py` `_Backend` to include
  `control_plane_store` alongside `session_store` and
  `transport_store`.
- Add `runtime_backend.control_plane_store()`.
- `runtime_backend.init(config)` selects the SQLite or Postgres
  control-plane store in the same place it selects the session and
  transport stores.
- `app/control_plane/bus.py` is a thin facade over
  `runtime_backend.control_plane_store()`. It does not choose a
  backend itself.
- No code outside `app/runtime_backend.py` branches on
  `database_url` or instantiates SQLite/Postgres control-plane
  stores directly.

**Deployment invariant**: all producer and processor roles must
resolve to the same selected control-plane backend configuration
via `runtime_backend.init(config)`. For SQLite this means the same
shared `data_dir`. For Postgres this means the same `database_url`
and schema.

#### State Machine

```
pending → claimed → completed
                  → failed → pending (auto-retry if retry_count < max_retries)
                           → dead_letter (retry_count >= max_retries)
                  → pending (lease expiry: lease_expires_at < now)
pending → dead_letter (processor explicitly rejects)
```

Use `python-statemachine`. CAS discipline:
`UPDATE WHERE state = 'pending'` with rowcount check.

**Lease expiry**: `lease_expires_at < now` on claimed commands →
transition back to `pending`, increment `retry_count`. The bus
poll reclaims expired leases. Default lease TTL: 30 seconds.

**Retry policy**: On failure, if `retry_count < max_retries`,
transition to `pending` and set `next_attempt_at` to
`now + backoff_seconds` where backoff = `min(2^retry_count, 60)`.
The poll query skips commands where `next_attempt_at > now`.
If `retry_count >= max_retries`, transition to `dead_letter`.
Default `max_retries`: 3.

**Lease renewal**: The runner owns lease renewal, not the
processor. When the runner dispatches a command to a processor,
it starts a background heartbeat task that calls
`bus.renew_lease(command_id)` at intervals shorter than the lease
TTL (e.g. every 10s for a 30s TTL). The heartbeat task is
cancelled when `process()` returns. If the lease expires before
the heartbeat can renew (e.g. process crashed), the runner's
`reclaim_expired()` sweep reclaims the command. The processor
never calls `renew_lease()` directly — it just does its work and
returns a `ControlReply`.

**Idempotency**: Commands may carry an `idempotency_key`. The
unique index prevents duplicate submission. Operations that are
NOT naturally idempotent (e.g. `submit_routed_task`) MUST set an
idempotency key. Operations that ARE naturally idempotent (e.g.
`bind_conversation` which is an upsert, `publish_timeline` which
deduplicates by `event_id`) MAY omit it.

#### Command/Reply Models

Use `pydantic` for ALL schemas — both the envelope and per-operation
payloads. No raw `dict` at the adapter/processor boundary.

```python
# app/control_plane/models.py
class ControlCommand(BaseModel):
    command_id: str
    capability: str
    operation: str
    payload_json: str                 # serialized pydantic request model
    authority_ref: str                # REQUIRED — no default, no empty
    priority: int = 0
    correlation_id: str = ""
    idempotency_key: str = ""
    max_retries: int = 3

    @field_validator("authority_ref")
    @classmethod
    def authority_ref_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("authority_ref must not be empty")
        return v

class ControlReply(BaseModel):
    command_id: str
    status: str                       # "completed" | "failed"
    result_json: str | None = None    # serialized pydantic result model
    error: str | None = None
```

Per-operation typed payloads (in `app/control_plane/requests/`):

```python
# app/control_plane/requests/conversation_projection.py
class BindConversationRequest(BaseModel):
    conversation_ref: str
    title: str
    origin_channel: str
    external_id: str

class PublishTimelineRequest(BaseModel):
    conversation_ref: str
    kind: str
    title: str
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict | None = None
    event_id: str | None = None

# app/control_plane/requests/task_routing.py
class SubmitRoutedTaskPayload(BaseModel):
    """Mirrors RoutedTaskRequest from app/agents/types.py.
    All fields and types match the runtime dataclass exactly.
    If the runtime type changes, this model must be updated
    in the same commit.

    Transport metadata (authority_ref, idempotency_key) belongs
    on the ControlCommand envelope, NOT in the payload. The
    payload is the domain content only."""
    routed_task_id: str
    parent_conversation_id: str = ""
    origin_agent_id: str = ""
    target_agent_id: str = ""
    title: str = ""
    instructions: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: list[str] = Field(default_factory=list)
    priority: str = "normal"
    created_at: str = ""

class ReportTaskResultPayload(BaseModel):
    """Mirrors RoutedTaskResult from app/agents/types.py.
    All fields and types match the runtime dataclass exactly.
    authority_ref is on the ControlCommand envelope, not here."""
    routed_task_id: str
    status: str             # "completed" | "failed" | "cancelled"
    summary: str = ""
    full_text: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completed_at: str = ""

class TimelineEventPayload(BaseModel):
    """Mirrors TimelineEvent from app/agents/types.py."""
    event_id: str
    conversation_id: str
    kind: str
    title: str
    body: str = ""
    status: str = ""
    progress: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""

class UpdateRoutedTaskStatusPayload(BaseModel):
    """Mirrors RoutedTaskUpdate from app/agents/types.py.
    timeline_events must be preserved; tuple → list is the only
    allowed shape change."""
    routed_task_id: str
    status: str
    summary: str = ""
    timeline_events: list[TimelineEventPayload] = Field(default_factory=list)
    progress: int | None = None
    updated_at: str = ""

# ... etc for each operation
# Rule: bus payload models mirror runtime types field-for-field.
# No lossy flattening. tuple → list is acceptable (pydantic).
# dict[str, Any] must be preserved exactly.
# Transport metadata (authority_ref, idempotency_key, correlation_id)
# belongs ONLY on the ControlCommand envelope. Payloads are domain
# content only — one source of truth for routing metadata.
```

Adapters serialize the typed request model into `payload_json`.
Processors deserialize and validate before processing. Type safety
at the boundary, flexible JSON storage underneath.

#### Command Classification

Fire-and-forget (eventual consistency, caller returns immediately):
- `conversation_projection.bind_conversation`
- `conversation_projection.publish_timeline`
- `health_publication.publish_health`
- `task_routing.update_routed_task_status`

Request/reply (correlated, bounded timeout):
- `task_routing.submit_routed_task`
- `task_routing.report_routed_task_result`
- `agent_directory.search_agents`
- `agent_directory.resolve_target_authority`

#### Bus Facade

```python
# app/control_plane/bus.py
class ControlPlaneBus:
    async def submit(self, command: ControlCommand) -> str:
        """Enqueue fire-and-forget. Returns command_id.
        Deduplicates by idempotency_key if set."""

    async def request(
        self, command: ControlCommand, *, timeout_seconds: float = 10.0,
    ) -> ControlReply:
        """Enqueue and await correlated reply.
        Raises TimeoutError if no reply within timeout."""

    async def poll_commands(
        self, *,
        allowed_pairs: set[tuple[str, str]],
        limit: int = 20,
    ) -> list[ControlCommand]:
        """Claim pending commands whose (authority_ref, capability)
        pair is in `allowed_pairs`. This is pair-aware: an authority
        that lost a capability after a scope change will NOT have
        its old commands claimed.
        Only returns commands where next_attempt_at IS NULL or
        next_attempt_at <= now (respects backoff scheduling).
        Sets lease_expires_at on claimed commands."""

    async def complete(
        self, command_id: str, *, result_json: str | None = None,
    ) -> None: ...

    async def fail(self, command_id: str, *, error: str) -> None:
        """Mark failed. Auto-retries if retry_count < max_retries."""

    async def dead_letter(self, command_id: str, *, reason: str) -> None:
        """Permanently reject. No retry."""

    async def renew_lease(self, command_id: str, *, extension_seconds: float = 30.0) -> bool:
        """Extend lease for a long-running command. Returns False if
        command is no longer claimed (already reclaimed/completed)."""

    async def reclaim_expired(self) -> int:
        """Reclaim commands where lease_expires_at < now AND state = 'claimed'.
        Increments retry_count. Sets next_attempt_at for backoff.
        Returns count reclaimed. Called periodically by runner."""

    async def reconcile_orphans(
        self, *, allowed_pairs: set[tuple[str, str]],
    ) -> int:
        """Dead-letter pending/claimed commands whose
        (authority_ref, capability) pair is NOT in allowed_pairs.

        OWNERSHIP RULE: Must be called ONLY by the process that owns
        the authoritative topology (the processor-running role). A
        producer-only/shared-worker process does not know the full
        topology and must NOT call this — it could dead-letter valid
        commands for authorities it doesn't know about.

        Handles two topology-change scenarios:
        1. Authority removed/renamed: all commands for that authority
           are dead-lettered.
        2. Authority still exists but lost a capability (scope change):
           commands for the now-invalid (authority, capability) pair
           are dead-lettered, while commands for still-valid pairs
           on the same authority are left alone.

        Returns count dead-lettered."""
```

**Targeted-only routing**: Every command on the bus has an explicit
`authority_ref`. There are no broadcast commands. Claiming is
pair-aware: `(authority_ref, capability)`. When a producer
needs to reach all authorities that implement a capability (e.g.
mirror a Telegram conversation to all channel/full registries), the
adapter expands one intent into N targeted commands at submission
time — one per relevant authority. The adapter gets the authority
set from the `ControlPlaneDirectory` (see below).

This means `poll_commands` filters by `(authority_ref, capability)`
pairs, and every command has a non-empty `authority_ref`. Two
processors implementing the same capability each claim only
commands matching their own `(authority, capability)` pairs.

#### Control-Plane Directory

```python
# app/control_plane/directory.py
class ControlPlaneDirectory:
    """Startup-built catalog of which authorities implement which
    capabilities. Passed to adapters so they can expand intents
    into targeted commands without importing backend config."""

    def authorities_for_capability(self, capability: str) -> set[str]:
        """Return authority_refs that implement this capability."""

    def all_capabilities(self) -> set[str]: ...

    def all_authorities(self) -> set[str]: ...

    def all_pairs(self) -> set[tuple[str, str]]:
        """Return all valid (authority_ref, capability) pairs.
        Used by bus.reconcile_orphans() and poll_commands()."""
```

Built at startup from registered processors' per-authority
capability maps — NOT a cross-product:

```python
directory = ControlPlaneDirectory()
for processor in [registry_processor, ...]:
    for auth, caps in processor.authority_capabilities().items():
        for cap in caps:
            directory.register(capability=cap, authority_ref=auth)
```

This respects `registry_scope`: a `channel`-only authority
registers `conversation_projection` and `health_publication` but
NOT `task_routing` or `agent_directory`. A `coordination`-only
authority registers `task_routing` and `agent_directory` but NOT
`conversation_projection`.

Adapters receive the directory at construction. When
`BusConversationProjection.bind_external_conversation()` is called,
it queries `directory.authorities_for_capability("conversation_projection")`
and submits one targeted command per authority that supports it.

### Layer 4: Processor Runner

Generic infrastructure, separate from domain logic:

```python
# app/control_plane/processor_runner.py
class ProcessorRunner:
    """Generic claim-loop that dispatches to registered processors."""

    def register(self, processor: ControlProcessor) -> None: ...

    async def run(self, *, stop_event: asyncio.Event) -> None:
        """Poll bus, dispatch claimed commands, write results."""

    async def stop(self) -> None: ...
```

```python
# app/control_plane/processor_base.py
class ControlProcessor(Protocol):
    def authority_capabilities(self) -> dict[str, set[str]]:
        """Return {authority_ref: {capability, ...}} for each owned
        authority. Not a cross-product — each authority declares
        exactly the capabilities it supports. E.g.:
        {
            "registry:prod": {"conversation_projection", "task_routing",
                              "agent_directory", "health_publication"},
            "registry:analytics": {"conversation_projection",
                                    "health_publication"},
        }
        """
        ...

    async def process(self, command: ControlCommand) -> ControlReply: ...
```

The runner owns: claim loop (using processor's
`authority_capabilities()` for address-aware claiming), dispatch,
lease heartbeating during `process()`, retry/backoff policy,
lease expiry reclaim, dead-letter escalation. Processors own:
domain logic per capability only — they never touch the bus or
manage leases.

When a second processor arrives (Slack admin), it registers with
the same runner. The runner builds the aggregate `allowed_pairs`
set for `poll_commands` from each processor's
`authority_capabilities()` map — collecting all valid
`(authority_ref, capability)` tuples. Dispatch routes each claimed
command to the processor whose `authority_capabilities()` map
contains the command's `(authority_ref, capability)` pair.

### Layer 5: Registry Control Processor

```python
# app/agents/registry_control_processor.py
class RegistryControlProcessor:
    """The ONLY place that reads persisted registry state and builds
    registry HTTP clients for control-plane operations."""

    def __init__(self, registry_runtime: RegistryRuntime): ...

    def authority_capabilities(self) -> dict[str, set[str]]:
        # Delegates to the shared builder — single source of truth
        return registry_authority_capabilities(self._runtime.registries)

    async def process(self, command: ControlCommand) -> ControlReply:
        ...
```

**Fan-out for mirroring**: The adapter expands one mirroring intent
into N targeted commands (one per channel/full authority). Each
command has a specific `authority_ref`. The processor handles one
authority per command. One registry failure does not block others.

**Targeted commands**: Commands with a specific `authority_ref`
like `registry:prod` are routed to the matching registry connection.

**Scatter-gather for discovery**: The adapter queries the directory
for all authorities implementing `agent_directory`, submits one
targeted command per authority (each with explicit `authority_ref`),
and aggregates results. Each result carries the `authority_ref`
of the authority that returned it.

`RegistryRuntime` remains owner of enroll/register/heartbeat/poll
inbound sync. The processor may reuse the runtime's live state
internally, but that is an implementation detail.

#### Shared Authority-Capability Builder

One function is the single source of truth for the scope-to-
capability mapping. Used by both startup (to populate the
directory) and the processor (to declare its capabilities):

```python
# app/agents/registry_capabilities.py
def registry_authority_capabilities(
    registries: Sequence[RegistryConnectionConfig],
) -> dict[str, set[str]]:
    """Map each registry authority to its capabilities based on
    registry_scope. Single source of truth — no duplication."""
    result = {}
    for r in registries:
        auth = f"registry:{r.registry_id}"
        caps: set[str] = set()
        if r.registry_scope in ("channel", "full"):
            caps |= {"conversation_projection", "health_publication"}
        if r.registry_scope in ("coordination", "full"):
            caps |= {"task_routing", "agent_directory", "health_publication"}
        result[auth] = caps
    return result
```

Startup and processor both call this function. No duplicate mapping.

### Layer 6: Port Adapters

Thin adapters over the bus, one per capability. Each adapter
serializes typed `pydantic` request models into `payload_json`
on the command envelope:

```python
# app/control_plane/adapters/conversation_projection.py
class BusConversationProjection:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory): ...

    async def bind_external_conversation(
        self, *, conversation_ref: str, title: str,
        origin_channel: str, external_id: str,
    ) -> None:
        request = BindConversationRequest(
            conversation_ref=conversation_ref,
            title=title,
            origin_channel=origin_channel,
            external_id=external_id,
        )
        # Expand to one command per authority that supports this capability
        for auth in self._directory.authorities_for_capability("conversation_projection"):
            await self._bus.submit(ControlCommand(
                command_id=uuid4().hex,
                capability="conversation_projection",
                operation="bind_conversation",
                payload_json=request.model_dump_json(),
                authority_ref=auth,
            ))

    async def publish_external_timeline(
        self, *, conversation_ref: str, kind: str, title: str, **kw,
    ) -> None:
        request = PublishTimelineRequest(
            conversation_ref=conversation_ref,
            kind=kind, title=title, **kw,
        )
        for auth in self._directory.authorities_for_capability("conversation_projection"):
            await self._bus.submit(ControlCommand(
                command_id=uuid4().hex,
                capability="conversation_projection",
                operation="publish_timeline",
                payload_json=request.model_dump_json(),
                authority_ref=auth,
                idempotency_key=kw.get("event_id", ""),
            ))
```

Request/reply adapters use `bus.request()` and deserialize the
typed reply:

```python
# app/control_plane/adapters/agent_directory.py
class BusAgentDirectory:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory): ...

    async def search_agents(
        self, *, query: AgentDiscoveryQuery,
    ) -> AgentSearchResult:
        # Get all directory-capable authorities from the directory
        authorities = self._directory.authorities_for_capability("agent_directory")
        # Scatter: submit one targeted request per authority
        # Each command has explicit authority_ref — no broadcast
        # Gather: collect replies with bounded timeout
        # Aggregate: merge results, track responding/timed-out
        ...
```

All adapters receive the `ControlPlaneDirectory` at construction so
they can expand intents into targeted commands without importing
backend config.

**No-op implementations** for standalone bots (no control plane).
Semantics are per-method, not per-port:

Fire-and-forget methods (no-op silently succeeds):
- `ConversationProjectionPort.bind_external_conversation()`
- `ConversationProjectionPort.publish_external_timeline()`
- `HealthPublicationPort.publish_health()`
- `TaskRoutingPort.update_routed_task_status()`

Request/reply methods (no-op returns typed unavailable):
- `TaskRoutingPort.submit_routed_task()` →
  `TaskSubmissionResult(status="unavailable", error="no control plane")`
- `TaskRoutingPort.report_routed_task_result()` →
  `TaskResultReport(status="unavailable", error="no control plane")`
- `AgentDirectoryPort.search_agents()` →
  `AgentSearchResult(status="unavailable", agents=[], ...)`
- `AgentDirectoryPort.resolve_target_authority()` →
  `AuthorityResolution(status="unavailable", authority_ref="")`

Callers handle typed unavailable results in normal control flow
(show user a message, skip delegation) without checking a boolean.
No `is_available()`.

### Startup Composition

```python
# In main.py:

# 0. runtime_backend.init(config) has already selected the session,
#    transport, and control-plane stores for this process.

# 1. Build bus facade (all roles — no backend selection here)
bus = ControlPlaneBus(data_dir=config.data_dir)
# Facade only: delegates to runtime_backend.control_plane_store()

# 2. Build authority directory from shared builder (single source of truth)
directory = ControlPlaneDirectory()
if config.agent_registries:
    for auth, caps in registry_authority_capabilities(config.agent_registries).items():
        for cap in caps:
            directory.register(capability=cap, authority_ref=auth)

if config.agent_registries:
    cp = ControlPlaneServices(
        conversation_projection=BusConversationProjection(bus, directory),
        task_routing=BusTaskRouting(bus, directory),
        agent_directory=BusAgentDirectory(bus, directory),
        health_publication=BusHealthPublication(bus, directory),
    )
else:
    cp = ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        health_publication=NoOpHealthPublication(),
    )

# 3. Build services (all roles, never None)
services = BotServices(control_plane=cp)

# 4. Build channel dispatcher — every runtime gets services
dispatcher = ChannelDispatcher()
if config.telegram_token:
    dispatcher.register(TelegramChannelBootstrap(config, provider, services))

# 5. Register registry channels in startup (not in RegistryRuntime)
if config.agent_registries:
    register_registry_channels(config, config.agent_registries, dispatcher, services)

# 6. Build processor runner (only for roles that own sync loops)
if _runs_registry_runtime(config):
    registry_runtime = RegistryRuntime(...)
    processor = RegistryControlProcessor(registry_runtime)
    # processor.authority_capabilities() = {"registry:prod": {...}, "registry:staging": {...}}
    runner = ProcessorRunner(bus)
    runner.register(processor)
    # runner.run() polls bus with per-authority capabilities
    # runner also calls bus.reclaim_expired() periodically
    # Started as background task

# 7. Reconcile orphaned commands (processor-owning roles ONLY)
#    This is destructive — dead-letters commands for invalid pairs.
#    Must run only in the process that owns the full topology.
if _runs_registry_runtime(config):
    await bus.reconcile_orphans(allowed_pairs=directory.all_pairs())
```

Key:
- `BotServices` built for ALL roles. No nullable fields.
- Bus created for ALL roles (shared storage).
- Processor runner only for registry roles.
- Shared workers write to bus, never process commands.
- Channel registration in startup, not in `RegistryRuntime`.

## What Gets Deleted

- `TelegramRuntime.registry_runtime`
- `TelegramRuntime.registry_client_factory`
- `FinalizationContext.registry_client_factory`
- `FinalizationContext.registry_client_for_registry`
- `bind_conversation()` in bridge.py
- `bind_conversation_to_registries()` in bridge.py
- `publish_timeline_event()` in bridge.py
- `publish_timeline_to_registries()` in bridge.py
- `registry_connection_client()` in bridge.py (consumer-facing)
- `resolve_registry_connection()` in bridge.py (consumer-facing)
- private bridge bind/timeline HTTP helpers once delivery is cut to
  dispatcher/egress or control-plane
- `_default_registry_client_factory()` in state.py
- All 11 `if registry_runtime is not None` branches
- `RegistryRuntime.register_channels()` — moved to startup
- `RegistryRuntime.clients_for_mirroring()` — internal to processor
- `RegistryRuntime.runtime_for_registry()`
- `RegistryRuntime.resolve_target_registry_id()`
- `AuthorityStatus.registry_scope` from generic health publication
  models
- runtime compatibility shims for `registry_id`, `user_id`, and
  `chat_id` once the upgrade window is closed
- implicit `"default"` / first-registry fallbacks in runtime,
  delivery, bridge, and registry egress code

## Provenance Model

`authority_ref` is the opaque control-plane provenance identifier.
It is used from day one in the bus schema, command models, port
signatures, and all new external-facing types. Format examples:
- `registry:prod`
- `registry:staging`
- `slack-admin:workspace-1` (future)
- `telegram-admin:bot-42` (future)

**Slice 6D generalizes existing types**: `DiscoveredAgentRef`,
`RoutedTaskRequest`, and delivery annotations that currently use
`registry_id` are updated to `authority_ref`. The bus and ports
already use `authority_ref` from Phase 3 — Slice 6D only updates
the pre-existing types that predate this plan.

Registry processor maps `authority_ref` = `registry:<id>`
internally. Consumer code never parses `authority_ref`.

## Operability

### Retention and Cleanup

Completed and dead-lettered commands are retained for diagnostics
but purged after a configurable retention period (default: 24h).
The bus exposes:

```python
async def purge_completed(self, *, older_than_seconds: int = 86400) -> int:
async def purge_dead_letter(self, *, older_than_seconds: int = 86400) -> int:
```

Called periodically by the processor runner alongside
`reclaim_expired()`.

### Dead-Letter Inspection

Dead-lettered commands are queryable for operator diagnostics:

```python
async def list_dead_letter(self, *, limit: int = 50) -> list[ControlCommand]:
```

Surfaced in `./octopus doctor` output when dead-letter count > 0.

### Bus Health Check

The bus exposes a health summary for `./octopus doctor` and
`./octopus status`:

```python
def bus_health(self) -> dict:
    """Returns counts: pending, claimed, completed, failed,
    dead_letter. Plus oldest pending age and oldest claimed age."""
```

The `./octopus doctor` command includes bus health when registries
are configured. Alerts on: stale claimed commands (lease expired
but not reclaimed), growing dead-letter count, growing pending
backlog.

### Deployment Validation

On startup, the bus validates connectivity to the storage backend:

- **SQLite**: validate `data_dir` accessibility and that the bus
  database file is writable.
- **Postgres**: validate `database_url` connectivity, schema
  reachability, and that the `control_plane_commands` table exists.

**Shared-mode invariant**: all roles (webhook, worker, all) must
resolve to the same control-plane backend configuration via
`runtime_backend.init(config)` — not just the same filesystem
path. For Postgres this means the same `database_url` and schema.
For SQLite this means the same `data_dir` on a shared volume.

If validation fails, startup aborts with a clear error naming the
expected backend and connection details.

## Residual Drift After Phase 8

Phase 8 completed the bus/port rollout, but several non-target
architecture paths survived because they still worked during the
migration. Those are not acceptable end-state behavior and must be
removed in a dedicated remediation phase:

- Worker timeline publication still branches by surface in
  `app/channels/telegram/worker.py` instead of using one owner path.
- Registry delivery still publishes timeline events through private
  bridge helpers that construct registry clients from persisted state.
- The generic health/discovery seam still leaks `registry_scope`
  into user-facing logic.
- Runtime boundary compatibility shims still accept old
  `registry_id`, `user_id`, and `chat_id` shapes.
- Singleton/default registry fallbacks still exist in runtime,
  delivery, and registry egress code.
- Dead registry-shaped runtime API still survives because tests
  exercise it.
- Several tests still encode scaffolding behavior instead of the
  target architecture.

## Post-Phase-9 Deep Review Assessment

Phase 9 removed the first wave of rollout leftovers, but a deeper
review found one more structural problem plus a few residual policy
leaks that should be fixed as a single post-remediation track.

### Recalled Context

Earlier review rounds flagged a general risk: "special" channels
without a coherent ingress/egress contract tend to preserve old
architecture under a new name. The rollout correctly removed many
direct registry paths, but the routed-task surface was allowed to
survive because it was still in use. That was the wrong standard.
"Still in use" is not sufficient if the path is not target
architecture.

### Incorrect Decisions That Led Here

- `RegistryTaskChannel` was preserved as if it were just another
  projected conversation surface.
- `RegistryChannelEgress` was reused for both registry conversations
  and registry task refs, even though those are different concerns.
- `admit_registry_delivery(kind="routed_task")` kept task-channel
  bind/timeline side effects to avoid touching the execution/status
  path during the rollout.
- The task-routing status path was implemented and tested at the
  bus/processor/store layers, but not fully integrated into live
  execution progress.
- Tests were allowed to validate both sides of the contradiction:
  coordination-only registries enqueue no projection commands, while
  routed-task admission still expected task-channel bind/timeline
  side effects.

### Current Situation

- `RegistryTaskChannel` is registered for `coordination/full`
  registries and still advertises projected timeline support.
- `RegistryChannelEgress` only publishes through
  `ConversationProjectionPort`.
- `registry_authority_capabilities()` does NOT give
  `conversation_projection` to `coordination` registries.
- `admit_registry_delivery(kind="routed_task")` still creates a
  task-channel egress and calls `sync_binding()` /
  `publish_timeline()`.
- The real product data model for routed tasks already lives in
  routed-task creation/status/result store paths and the registry
  task detail UI.
- `TaskRoutingPort.update_routed_task_status()` exists end to end but
  execution progress still routes through conversation timeline
  callbacks.
- Two residual surface-specific string checks remain in generic-ish
  orchestration/admission code:
  - `delivery.py` special-cases `"telegram"` before retrying routed
    result delivery when no bot is present
  - `work_admission.py` auto-allows every non-Telegram surface by
    checking `channel_type != "telegram"`
- `RegistryConnectionState.registry_id = "default"` remains as a dead
  default even though the runtime now requires explicit registry
  ownership.

### Proposed Fix

- Treat routed-task lifecycle as a `TaskRoutingPort` concern, not a
  conversation-projection concern.
- Stop advertising projected timeline behavior on
  `RegistryTaskChannel`.
- Stop emitting task-channel bind/timeline side effects on routed-task
  admission.
- Carry explicit `authority_ref` through existing execution metadata
  and use it to route progress/status updates through
  `TaskRoutingPort.update_routed_task_status()`.
- Keep final routed-task completion on
  `TaskRoutingPort.report_routed_task_result()`.
- Remove remaining surface-specific string checks by reusing the
  existing dispatcher/descriptor seam instead of branching on raw
  channel-type names.
- Remove the dead default from `RegistryConnectionState`.

### Design Constraints For The Fix

- No new ports, no new channel families, no new abstraction layer.
- Do not parse registry refs in Telegram execution/workflow code to
  recover provenance; reuse canonical `authority_ref` that is already
  carried on inbound registry events.
- Do not keep both projection and task-routing active for routed
  tasks.
- If existing `ChannelDescriptor` flags are insufficient for a
  surface-policy decision, extend `ChannelDescriptor` minimally in the
  same slice rather than scattering more string checks.
- Fix tests that encode the wrong architecture in the same slice as
  the code.

## Delivery Order

### Phase 1: ADR and Contract Freeze

#### Slice 1: ADR and status update

- Add ADR documenting the four decisions above.
- Update `status.md`.
- No code changes.

**Commit: "control-plane / 1: ADR — capability ports over
registry-shaped abstractions"**

### Phase 2: Capability Ports and Services (no behavior change)

#### Slice 2: Ports and services container

- Create `app/ports/conversation_projection.py`
- Create `app/ports/task_routing.py`
- Create `app/ports/agent_directory.py`
- Create `app/ports/health_publication.py`
- Create `app/runtime/services.py` with `ControlPlaneServices` and
  `BotServices`
- Create no-op implementations — typed unavailable results, no
  booleans
- Define typed result models: `TaskSubmissionResult`,
  `TaskResultReport`

Tests: protocol compliance, no-op implementations satisfy protocols.

**Commit: "control-plane / 2: capability ports and services"**

### Phase 3: Control-Plane Bus (can parallel with Phase 2)

#### Slice 3A: Bus contract and models

- Create `app/control_plane/__init__.py`
- Create `app/control_plane/models.py` — `pydantic` schemas:
  `ControlCommand`, `ControlReply` (envelope models)
- Create `app/control_plane/requests/` — `pydantic` per-operation
  payload models: `BindConversationRequest`,
  `PublishTimelineRequest`, `SubmitRoutedTaskRequest`,
  `ReportTaskResultRequest`, `SearchAgentsRequest`, etc.
- Create `app/control_plane/bus_base.py` — store contract protocol
  with address-aware poll signature
- Create `app/control_plane/machine.py` — state machine using
  `python-statemachine`: pending/claimed/completed/failed/dead_letter,
  lease expiry transition, retry count tracking

Tests: state machine transitions, lease expiry, retry exhaustion
→ dead letter, pydantic model validation.

**Commit: "control-plane / 3a: bus contract, models, and lifecycle"**

#### Slice 3B: Bus storage implementations

- Create `app/control_plane/bus.py` — `ControlPlaneBus` facade
  over `runtime_backend.control_plane_store()` (mirrors
  `app/work_queue.py` as facade over transport store)
- Extend `app/runtime_backend.py` to select and expose the
  control-plane store backend
- Create `app/control_plane/sqlite_impl.py`
- Create `app/control_plane/postgres_impl.py`
- Create Postgres migration for `control_plane_commands` table
- Create fresh-install schema for both stores

Tests: contract tests for bus (SQLite + Postgres):
- submit/poll/complete/fail lifecycle
- pair-aware claiming: (authority_ref, capability) tuples
- all commands have non-empty authority_ref (no broadcast)
- claiming is pair-aware: (authority_ref, capability) must match
- commands for known authority but revoked capability are NOT claimed
- lease expiry → reclaim to pending
- retry count increment on reclaim
- dead-letter after max_retries
- idempotency key deduplication on submit
- reply correlation for request/reply
- one-way vs request/reply behavior
- CAS invariants (concurrent claim safety)
- backend-selection parity: SQLite config uses SQLite control-plane
  store, Postgres config uses Postgres control-plane store, and no
  backend branching exists outside `app/runtime_backend.py`
- `reconcile_orphans()` dead-letters commands for removed authorities
- `reconcile_orphans()` dead-letters commands for known authority with revoked capability
- `reconcile_orphans()` leaves commands for valid (authority, capability) pairs untouched

**Commit: "control-plane / 3b: bus storage (SQLite + Postgres)"**

### Phase 4: Adapters and Processor

#### Slice 4A: Bus-backed port adapters

- Create `app/control_plane/adapters/` package
- Implement `BusConversationProjection`, `BusTaskRouting`,
  `BusAgentDirectory`, `BusHealthPublication`
- Fire-and-forget adapters serialize typed `pydantic` request models
  into `payload_json` and call `bus.submit()`
- Request/reply adapters call `bus.request()` with timeout and
  deserialize typed reply models
- `BusAgentDirectory.search_agents()` implements scatter-gather:
  submits one command per directory-capable authority, collects
  replies with bounded timeout, aggregates into `AgentSearchResult`
  with partial-success status
- Non-idempotent operations set `idempotency_key` on submit

- `BusTaskRouting.update_routed_task_status()` serializes a full
  `RoutedTaskUpdate` into `UpdateRoutedTaskStatusPayload` and
  submits it as fire-and-forget

Tests: adapter submits correct typed payload, request/reply
correlates, timeout returns typed unavailable, scatter-gather
aggregation, idempotency key set, update_routed_task_status
preserves timeline_events/progress/updated_at.

**Commit: "control-plane / 4a: bus-backed capability adapters"**

#### Slice 4B: Processor runner

- Create `app/control_plane/processor_runner.py`
- Create `app/control_plane/processor_base.py` — `ControlProcessor`
  protocol with `authority_capabilities()` per-authority map
- Generic runner:
  - Aggregates all registered processors' `authority_capabilities()`
    into a set of `(authority_ref, capability)` pairs for claiming
  - Claim loop: polls bus with `allowed_pairs`
  - Dispatch: routes each claimed command to the processor whose
    `authority_capabilities()` map contains the command's
    `(authority_ref, capability)` pair
  - Calls `bus.reclaim_expired()` periodically
  - On processor failure: calls `bus.fail()` which auto-retries
    or dead-letters based on retry_count vs max_retries
  - Clean shutdown: stop claiming, let in-progress finish

Tests: runner claims and dispatches, address-aware routing,
retry on transient failure, dead-letter after
max_retries, lease expiry reclaim, clean shutdown.

**Commit: "control-plane / 4b: processor runner"**

#### Slice 4C: Registry control processor

- Create `app/agents/registry_control_processor.py`
- Create `app/agents/registry_capabilities.py` with shared
  `registry_authority_capabilities()` builder — single source
  of truth for scope-to-capability mapping
- Processor uses the shared builder for `authority_capabilities()`
- Implements all 4 capabilities by delegating to `RegistryRuntime`
- Per-authority commands only — no broadcast handling
- Error isolation per registry
- `RegistryControlProcessor` forwards the full routed-task status
  payload, including `timeline_events`, `progress`, and `updated_at`,
  to the existing registry routed-task status path/store

Tests: processor handles each command type, fan-out works, one
registry failure doesn't block others, routed-task status update
preserves timeline_events/progress/updated_at through to registry
store.

**Commit: "control-plane / 4c: registry control processor"**

### Phase 5: Wire Services Into Runtimes

#### Slice 5: Startup composition

- Update `main.py`:
  - Build `ControlPlaneBus`
  - Build port adapters (bus-backed or no-op)
  - Build `ControlPlaneServices` and `BotServices`
  - Pass `services` to channel runtimes
  - Build processor runner, start drain loop (registry roles only)
  - Register channels in startup (not `RegistryRuntime`)
- Update `TelegramRuntime` — add `services: BotServices`
- Update `TelegramChannelBootstrap` — accept and pass services
- Keep old fields alive during scaffolding (deleted in Phase 7)
- Update test fixtures

Tests: startup produces correct services for each role. Services
never None. Processor only for registry roles.

**Commit: "control-plane / 5: wire services into startup"**

### Phase 6: Cut Consumers to Ports (sequential)

#### Slice 6A: Cut Telegram egress

- `bind()` → `services.control_plane.conversation_projection.bind_external_conversation()`
- `on_message_received()` → `publish_external_timeline()`
- `on_outcome()` → `publish_external_timeline()`
- `publish_timeline()` → `publish_external_timeline()`
- Remove `registry_runtime` field from egress
- Remove bridge imports from egress

Tests: egress through port, no registry imports, shared worker
mirroring through bus.

**Commit: "control-plane / 6a: cut telegram egress to ports"**

#### Slice 6B: Cut progress and worker timeline

- `progress_timeline_callback()` → `publish_external_timeline()`
- `_publish_timeline_event_for_runtime()` → `publish_external_timeline()`
- Remove `if registry_runtime is not None` from both

Tests: progress and worker usage/timeline through port.

**Commit: "control-plane / 6b: cut progress and worker to ports"**

#### Slice 6C: Cut finalization

- Remove `registry_client_factory` and `registry_client_for_registry`
  from `FinalizationContext`
- Add `task_routing: TaskRoutingPort`
- Routed result → `task_routing.report_routed_task_result()`
- Update worker context construction

Tests: routed result through port, shared worker through bus.

**Commit: "control-plane / 6c: cut finalization to ports"**

#### Slice 6D: Generalize provenance to authority_ref

Moved BEFORE delegation cutover because delegation uses
`DiscoveredAgentRef` which needs `authority_ref`.

- Replace `registry_id` with `authority_ref` in:
  - `DiscoveredAgentRef`
  - `RoutedTaskRequest`
  - Delivery annotations where `registry_id` is consumer-visible
- Registry processor maps `authority_ref` = `registry:<id>` internally
- Consumer code never parses `authority_ref`

Tests: provenance flows end-to-end, existing delegation tests pass
with `authority_ref`.

**Commit: "control-plane / 6d: generalize provenance to
authority_ref"**

#### Slice 6E: Cut delegation

- Discovery → `services.control_plane.agent_directory.search_agents()`
- Target resolution → `resolve_target_authority()`
- Task submission → `services.control_plane.task_routing.submit_routed_task()`
- All use `authority_ref`, not `registry_id` (generalized in 6D)
- Remove all `if runtime.registry_runtime` branches
- Remove bridge helper imports

Tests: delegation through port, correct authority_ref propagation.

**Commit: "control-plane / 6e: cut delegation to ports"**

#### Slice 6F: Cut delegation channel

- Timeline publishing → `publish_external_timeline()`
- Remove `if registry_runtime is not None` branch

**Commit: "control-plane / 6f: cut delegation channel to ports"**

### Phase 7: Cleanup

#### Slice 7A: Rationalize registry channels

Moved BEFORE grep gates so channels are already on ports when
gates are enforced.

- Registry channels accept `BotServices`, not `registry_client_factory`
- `RegistryChannelEgress` publishes via
  `services.control_plane.conversation_projection`
- No runtime-side dispatcher mutation
- Channel registration fully in startup composition

Tests: registry egress through port, channel registration in
startup only, no runtime-side dispatcher mutation.

**Commit: "control-plane / 7a: rationalize registry channels"**

#### Slice 7B: Remove leaked fields and helpers

- Delete from `TelegramRuntime`: `registry_runtime`,
  `registry_client_factory`
- Delete from `FinalizationContext`: `registry_client_factory`,
  `registry_client_for_registry`, and dead `registry_id`
- Delete consumer-facing bridge helpers
- Delete `_default_registry_client_factory()` from state.py
- Move channel registration fully to startup
- Internalize `clients_for_mirroring()` in processor

**Commit: "control-plane / 7b: delete leaked registry fields"**

#### Slice 7C: Grep gates

- Add to `test_zero_import_gates.py`:
  - No `registry_runtime` in non-registry orchestration
  - No `registry_connection_client` in channel/workflow
  - No `resolve_registry_connection` in channel/workflow
  - No `registry_client_factory` in channel/workflow
  - No `if.*registry_runtime.*is not None` in channel/workflow
  - No `bind_conversation_to_registries` (internalized)
  - No `publish_timeline_to_registries` (internalized)

**Commit: "control-plane / 7c: grep gates"**

### Phase 8: Integration and E2E Hardening

#### Slice 8: Production-shape tests

- Shared worker + 2 registries: all Telegram events mirrored
  through bus → processor → registries
- Shared worker routed task result: through bus → processor
- Local mode: bus + processor in same process
- Registry-only bot: bus + processor, no Telegram
- One registry degraded: other receives mirroring
- Coordination-only: no conversation projection commands
- Bus persistence: commands survive process restart
- Routed-task status update with timeline_events: adapter →
  bus → processor → registry store, verify timeline_events and
  progress reach the store
- Ownership-boundary tests, not unit-only monkeypatching

**Commit: "control-plane / 8: production-shape integration tests"**

### Phase 9: Post-Rollout Remediation and Scaffold Removal

This phase removes migration leftovers that survived the rollout
because they still worked. The goal is convergence on the target
architecture, not backward-compatible preservation of scaffolding.

Execution ownership note:
- If an issue was discovered after Phase 8 but technically belongs to
  an earlier slice, Phase 9 owns the fix anyway. Historical slice
  notes remain for provenance, but the remediation pass executes from
  Phase 9 only.

#### Slice 9A: Worker timeline single owner path

- `_publish_timeline_event_for_runtime()` calls
  `services.control_plane.conversation_projection.publish_external_timeline()`
  for ALL conversation refs.
- Delete the worker-side `dispatcher.channel_type_for_ref()` branch
  and registry-specific egress path from worker timeline publication.
- Drop registry-id extraction/plumbing from the finalization lambda;
  `publish_timeline_event=lambda ...` forwards only the event fields.
- Delete the dead `registry_id` field from `FinalizationContext`
  alongside the lambda/plumbing cleanup so the finalization contract
  matches the post-authority-ref architecture in the same slice.
- Keep `_resolve_registry_authority_ref()` only for explicit
  provenance handling in this slice; do not expand its role.

Tests:
- worker timeline tests assert BOTH Telegram and registry refs go
  through `ConversationProjectionPort`
- zero-import gate allows the bridge import block to be absent and
  still passes
- no bridge timeline/bind helper imports in worker code

**Commit: "control-plane / 9a: collapse worker timeline to one port path"**

#### Slice 9B: Claim-token contract completion

- Add stale-claim negative tests for `fail()`, `dead_letter()`, and
  `renew_lease()` in the control-plane store contract.
- Update runner fakes to capture and assert `claimed_at` forwarding
  through renew/complete/fail/dead-letter paths.
- If the new tests expose gaps, fix the existing bus/store/runner
  implementation in the same slice.

Tests:
- contract tests cover stale-token rejection for complete/fail/
  dead-letter/renew-lease
- runner tests prove the runner forwards `claimed_at`

**Commit: "control-plane / 9b: complete claim-token CAS coverage"**

#### Slice 9C: Registry delivery timeline convergence

- Replace direct bridge timeline publication in
  `app/agents/delivery.py` with the existing dispatcher/egress-owned
  path so delivery no longer constructs registry HTTP side effects
  through private bridge helpers.
- Delivery does NOT get `BotServices` or a new port field added just
  for this cleanup. Reuse the existing `RegistryDeliveryRuntime`
  collaborators and the dispatcher-owned egress creation seam.
- Cover all three direct timeline call sites in `delivery.py`
  (`delegated_result`, `delegation_ready` on admitted resume, and
  `delegation_ready` on duplicate resume), not just one helper call.
- Remove bridge bind/timeline helper imports from delivery code.
- Delete private bridge bind/timeline HTTP helpers once no callers
  remain; keep only pure ref/envelope helpers in `bridge.py`.
- No direct control-plane HTTP outside `RegistryControlProcessor`.

Tests:
- routed-result and delegation-ready delivery paths publish timeline
  through dispatcher/egress or control-plane-owned path
- multi-registry/shared-worker coverage proves no single-registry
  loss mode remains
- grep shows no direct bridge timeline/bind helper imports outside
  registry-owned pure helper code

**Commit: "control-plane / 9c: remove direct registry timeline side effects"**

#### Slice 9D: Generic health/discovery cleanup

- Replace `AuthorityStatus.registry_scope` with capability-based
  summary data on the generic health port.
- `connection_summary()` reports generic capability/purpose data,
  not synthetic registry vocabulary.
- Telegram `/discover` filters for coordination-capable authorities
  using capabilities, not `registry_scope`.
- Delete helper code that reconstructs synthetic `registry_scope`
  from capability sets.

Tests:
- health-publication adapter tests assert capability-based summaries
- `/discover` behavior stays correct without reading `registry_scope`
- no generic port or UI code references `registry_scope`

**Commit: "control-plane / 9d: remove registry vocabulary from generic health"**

#### Slice 9E: Close the runtime compatibility window

- Remove runtime-boundary translators that silently upconvert legacy
  `registry_id` payloads into `authority_ref`.
- Remove legacy `user_id` / `chat_id` fallback decoding once all
  canonical producers are on the normalized shape.
- Remove presenter fallback rendering of `registry_id`.
- Remove worker-side registry-ref parsing for authority synthesis if
  an upstream producer still omits `authority_ref`; fix the producer
  instead of reparsing in Telegram worker code.
- If persisted data migration is still required, do it as an explicit
  one-time migration in the same slice rather than keeping runtime
  translators alive.
- OWNERSHIP BOUNDARY: Slice 9E owns shape translation removal only.
  It removes compatibility rewrites such as:
  - `registry_id -> authority_ref`
  - `user_id -> actor_key`
  - `chat_id -> conversation_key`
  It does NOT remove singleton/default fallback behavior; that is
  owned by Slice 9F.

Tests:
- canonical payload/session fixtures use only `authority_ref`,
  `actor_key`, and `conversation_key`
- negative tests reject legacy-only shapes once the window is closed
- no shared boundary code rewrites `registry_id` into `authority_ref`

**Commit: "control-plane / 9e: delete compatibility shims"**

#### Slice 9F: Fail-fast registry refs and singleton/default fallbacks

- Remove `"default"` and first-registry fallback behavior from
  registry delivery, registry egress, bridge helpers, and
  `AgentRuntime`.
- OWNERSHIP BOUNDARY: Slice 9F owns invalid-input coercion and
  singleton/default fallback removal, not boundary shape translation.
- Require qualified registry refs and explicit registry ownership
  where registry-owned code needs them.
- Invalid or unqualified registry refs fail fast instead of being
  coerced into singleton-era defaults.
- Enumerate and remove these concrete fallback sites:
  - `app/agents/delivery.py` missing `registry_id` -> `"default"`
  - `app/channels/registry/egress.py` unqualified ref -> `"default"`
  - `app/agents/bridge.py` implicit singleton resolution when
    `registry_id` is omitted
  - `app/agents/runtime.py` first-registry / `"default"` state-id
    fallback
- Update tests and fixtures to use production-shape qualified refs
  only.

Tests:
- invalid/unqualified registry refs are rejected
- no runtime path invents `"default"` or silently picks the first
  configured registry
- registry adapter tests use qualified refs only

**Commit: "control-plane / 9f: remove singleton and default fallbacks"**

#### Slice 9G: Delete dead registry-shaped runtime API

- Delete `RegistryRuntime.runtime_for_registry()`.
- Delete `RegistryRuntime.resolve_target_registry_id()`.
- Move remaining tests to current seams:
  `RegistryControlProcessor`, `ControlPlaneDirectory`,
  `AgentDirectoryPort`, or integration tests.
- Verify no app callers remain before deletion.

Tests:
- grep proves no production callers remain
- replacement tests cover the current control-plane behavior rather
  than dead runtime API

**Commit: "control-plane / 9g: delete dead registry runtime API"**

#### Slice 9H: Final test-hygiene and guardrail cleanup

- Remove tests that codify scaffolding behavior instead of target
  architecture.
- Tighten grep gates so they forbid leaked bad patterns but never
  require an old import/helper to exist.
- Ensure guardrails reflect the final design:
  no worker surface split, no bridge direct side effects, no
  generic `registry_scope`, no default registry fallbacks.
- Clean low-noise post-rollout leftovers discovered during review
  only if they remain after the structural slices land
  (for example stale log wording like "Registry timeline callback"
  on generic control-plane paths, or redundant post-migration
  cleanup like unnecessary `dict(json.loads(...))` wrappers).

Tests:
- full suite
- zero-import gates and contract tests reflect the final architecture

**Commit: "control-plane / 9h: align tests with final architecture"**

### Phase 10: Routed-Task Surface Correction and Final Surface Boundary Cleanup

This phase fixes the routed-task/channel mismatch discovered after
Phase 9 and removes the last surface-specific policy leaks that are
still outside the target architecture.

#### Slice 10A: Correct the routed-task channel contract

- `RegistryTaskChannel` stops advertising projected conversation
  timeline support. It remains a dispatcher-owned ref surface, but it
  is not a conversation-projection channel.
- `admit_registry_delivery(kind="routed_task")` keeps work admission
  but deletes task-channel `sync_binding()` and `publish_timeline()`
  side effects.
- Update tests that currently assert routed-task bind/timeline egress
  during admission.
- Do not add a task-specific egress abstraction; remove the fake
  projected behavior instead.
- This slice is primarily a contract correction. The main behavioral
  change comes in Slice 10C when routed-task progress is wired to
  `TaskRoutingPort`; do not expect `supports_timeline=False` by itself
  to create new routed-task progress behavior.
- `RegistryTaskChannel` may still reuse `RegistryChannelEgress` as an
  existing dispatcher seam, but task-ref egress projection methods are
  no longer part of valid runtime behavior after this slice. If a
  later code path still calls `bind()` / `sync_binding()` /
  `publish_timeline()` on a task-ref egress, that is a bug and tests
  should fail.

Tests:
- `RegistryTaskChannel.descriptor.supports_timeline is False`
- routed-task admission still admits work successfully
- routed-task admission no longer binds or publishes timeline through
  registry channel egress
- coordination-only registries still enqueue no projection commands
- routed-task execution still completes successfully in the interim
  state where progress callback remains absent before Slice 10C lands
- tests do not expect product-visible routed-task progress from this
  slice alone; that behavior belongs to Slice 10C

**Commit: "control-plane / 10a: correct routed-task channel contract"**

#### Slice 10B: Carry explicit routed-task provenance through execution

- Extend the existing execution metadata/context types to carry
  `authority_ref` explicitly.
- Populate `authority_ref` from canonical inbound event provenance;
  do not reparse registry refs in Telegram execution/workflow code.
- Keep the change on existing seams:
  `ExecutionChannelMetadata`, `ExecutionChannelContext`,
  Telegram execution/runtime builders, and worker call sites.

Tests:
- execution metadata/context preserves canonical `authority_ref`
- routed-task execution paths receive explicit provenance without
  parsing `registry:{id}:task:{id}` refs
- grep proves no new registry-ref parsing was added to Telegram
  execution/workflow code

**Commit: "control-plane / 10b: thread routed-task authority through execution"**

#### Slice 10C: Route routed-task progress through TaskRoutingPort

- Replace routed-task execution progress publication through
  `ConversationProjectionPort` with
  `TaskRoutingPort.update_routed_task_status()`.
- Keep projected conversation timeline callbacks for real projected
  conversation surfaces only.
- `ExecutionChannelContext` chooses progress callback by concern:
  projected conversation => conversation projection,
  routed task + `authority_ref` => task-routing status update.
- The current single `timeline_callback_factory(conversation_ref,
  routed_task_id)` seam is not sufficient once `authority_ref` is
  required. Fix this explicitly in the same slice:
  - either split the collaborator seam into
    `build_conversation_progress_callback(conversation_ref, routed_task_id)`
    and
    `build_routed_task_progress_callback(routed_task_id, authority_ref)`
  - or extend the existing factory signature so `authority_ref` is an
    explicit input and the context builder can select by concern
- Prefer the split-factory approach because it keeps conversation
  projection and routed-task status concerns separate without
  overloading one callback builder.
- Add a dedicated routed-task progress callback alongside
  `progress_timeline_callback()` in `app/channels/telegram/progress.py`
  rather than overloading the conversation-projection callback.
- Preserve the existing callback shape
  `Callable[[html_text: str, force: bool], Awaitable[None]]` by
  wrapping it into a `RoutedTaskUpdate` inside the callback factory.
- The wrapper must convert callback input to routed-task status
  updates explicitly:
  - `routed_task_id` from the execution context
  - `authority_ref` from the execution context
  - `status="running"` (or the existing in-flight status constant used
    by the task surface)
  - `summary` from plain-text/summarized progress text
  - `timeline_events=()` unless the slice also has the canonical
    parent-conversation provenance needed to write timeline rows
    intentionally
  - `progress=None` unless the runtime already has a true numeric
    progress value; do NOT infer numeric progress from markup
  - `updated_at` set explicitly by the callback
- Reuse existing text-cleaning/summarization patterns; do not invent a
  second progress-text parsing system.
- Preserve throttling. Routed-task status callbacks must not flood the
  bus/registry with every token-level update. Keep an interval policy
  equivalent to the current progress publication cadence and let
  `force=True` bypass the throttle only when the existing progress
  lifecycle already would.
- `finalize_execution()` continues to report final routed-task result
  through `report_routed_task_result()`.
- Do not let routed-task usage/progress silently target a no-op
  projection path; either skip task-ref usage projection or route it
  through the routed-task status concern in the same slice.

Tests:
- routed-task execution progress updates registry task status through
  `TaskRoutingPort`
- projected conversation execution still publishes through
  `ConversationProjectionPort`
- routed-task final result reporting still works
- no routed-task execution path depends on projected task-channel
  timeline support
- callback tests cover html_text/force -> `RoutedTaskUpdate` mapping
- throttling tests prove routed-task progress updates do not enqueue
  on every raw progress tick

**Commit: "control-plane / 10c: move routed-task progress to task routing"**

#### Slice 10D: Remove residual surface-specific string checks

- Replace the hardcoded `"telegram"` check in `app/agents/delivery.py`
  with a runtime readiness query on the existing dispatcher seam.
- This check is about whether the current process can build a
  functional egress for a ref right now, not a static channel
  capability. Do NOT try to solve it with a static
  `ChannelDescriptor` field.
- Extend `ChannelDispatcher` minimally with a runtime readiness/helper
  query if needed, reusing the existing channel/build-egress seam
  rather than inventing a new policy object.
- Replace the hardcoded non-Telegram auto-allow check in
  `app/runtime/work_admission.py` with descriptor-owned admission
  policy using existing channel metadata where possible.
- Do not create a new policy subsystem for this cleanup.
- For work admission specifically, if current `ChannelDescriptor`
  fields are insufficient, extend that existing contract minimally in
  the same slice and delete the raw string check in the same commit.
  This is a static admission-policy concern and does belong on the
  descriptor if the existing fields are not enough.

Tests:
- routed-result delivery retry behavior stays correct without raw
  channel-type string checks
- work admission no longer auto-allows by `channel_type != "telegram"`
- new non-Telegram user-facing channels do not inherit implicit
  allow-all behavior accidentally
- grep proves the targeted raw string checks are gone
- readiness tests prove delivery retry uses dispatcher/runtime
  readiness rather than a static raw channel-type name check

**Commit: "control-plane / 10d: replace raw surface checks with descriptor policy"**

#### Slice 10E: Remove the last dead defaults and finalize guardrails

- Delete `RegistryConnectionState.registry_id = "default"` and
  require explicit registry ownership in all constructor paths.
- Clean any low-noise follow-up fallout from slices 10A-10D, but only
  if it remains after the structural changes land.
- Update status, grep gates, and any stale tests so they describe the
  final architecture rather than the pre-Phase-10 compromise.

Tests:
- `RegistryConnectionState` is constructed only with explicit
  `registry_id`
- full suite
- zero-import/grep gates reflect the post-Phase-10 architecture

**Commit: "control-plane / 10e: remove dead defaults and finalize guardrails"**

### Phase 11: Routed-Task Execution Surface Completion and Readiness Refinement

Phase 10 corrected routed-task admission and progress callback selection,
but a deeper review found that routed-task execution still leaks through
projected task-ref egress behavior during the actual worker/provider/finalization
lifecycle. This phase closes that remaining execution-side drift and cleans
up the last low-noise routed-task/runtime seams that were left behind because
they still worked.

#### Slice 11A: Remove projected task-ref side effects from routed-task execution

- Routed-task execution must not emit conversation-projection side effects on
  `registry:{id}:task:{task_id}` refs during normal worker execution.
- Close the remaining execution-time projection path:
  - no routed-task `bind()` side effects at worker start
  - no routed-task `on_outcome()` projected result side effects
  - no routed-task warning text sent back onto the task ref when result
    reporting fails
  - no routed-task usage audit event projected onto the task ref
- Reuse existing seams; do not add a new port, channel family, or
  task-specific architecture layer.
- It is acceptable to make task-ref registry egress behavior inert for
  projection-only methods if that is the smallest clean fix on the existing
  seam, but do not reintroduce a parallel task-delivery surface.
- Keep conversation-surface behavior unchanged.
- Routed-task execution is non-interactive. If the execution path returns
  `None` because it hit an interactive-only branch (for example a credential
  setup prompt or other message-only pause), synthesize a routed-task failure
  outcome in the same slice rather than silently ending the task without a
  final report.
- Update `status.md` in the same slice so it no longer claims the routed-task
  surface cleanup is complete before this behavior lands.

Tests:
- routed-task execution on a full-scope registry does NOT emit projected
  `started`, `bot_message`, `completed`, `failed`, or `usage` events on the
  task ref
- routed-task execution still reports final result through
  `TaskRoutingPort.report_routed_task_result()`
- routed-task report-failure warning does not publish onto the task ref
- routed-task execution that cannot continue through an interactive-only path
  returns a failure result instead of silently ending with no report
- projected registry conversation execution still emits its normal
  bind/result/usage side effects

**Commit: "control-plane / 11a: remove routed-task execution projection drift"**

#### Slice 11B: Make routed-task terminal state owned by final result, not progress text

- Routed-task terminal state must come from the execution outcome reported
  through `TaskRoutingPort.report_routed_task_result()`, not from matching
  user-facing progress strings.
- Remove brittle status inference from `app/channels/telegram/progress.py`
  that derives routed-task terminal status by matching formatted text like
  `"Completed."` or timeout/cancel labels.
- Keep routed-task progress updates for genuine in-flight progress only.
- Prefer source-of-truth ownership over text parsing:
  - in-flight progress => `update_routed_task_status(status="running", ...)`
  - terminal success/failure/cancel/timeout/delegation outcome =>
    `report_routed_task_result(...)`
- If needed, suppress terminal routed-task progress callbacks at the execution
  source (`execute_request()` / provider result handling) instead of inferring
  terminal state downstream from rendered text.
- Do not weaken conversation-surface progress behavior to solve this.

Tests:
- routed-task progress callback no longer infers terminal status from
  user-facing progress text
- routed-task execution still produces in-flight status updates
- terminal routed-task status in the registry store is driven by the final
  routed-task result report, not by a terminal progress-text callback
- no test encodes `"Completed."` / timeout / cancel strings as the source of
  truth for routed-task state

**Commit: "control-plane / 11b: move routed-task terminal state to final result"**

#### Slice 11C: Cheap dispatcher readiness checks on the channel seam

- `ChannelDispatcher.egress_ready_for_ref()` must stop constructing and
  discarding a full egress object just to answer a readiness question.
- Reuse the existing channel seam:
  - extend `Channel` minimally with an egress-readiness/precondition method
    if needed
  - let channels answer readiness from their own construction prerequisites
    instead of hardcoding surface logic in shared code
- The current delivery use case is runtime readiness for parent-conversation
  egress during routed-result handling. Solve that concern without inventing a
  new policy subsystem.
- A default implementation may still fall back to the existing build path
  temporarily, but Telegram should use a cheap readiness check rather than
  constructing a full egress object for every routed-result probe.
- Keep the existing delivery behavior unchanged: `retry_later` still means the
  process cannot currently build a live parent egress.

Tests:
- dispatcher readiness tests prove Telegram readiness no longer requires
  constructing a full egress instance
- routed-result delivery retry behavior is unchanged
- shared delivery code still does not branch on raw surface-name strings

**Commit: "control-plane / 11c: make egress readiness a cheap channel query"**

### Phase 12: Routed-Task Lifecycle Correctness and Durable Degraded-State Recovery

Phase 11 removed the last projected task-ref execution side effects, but a
deeper lifecycle review found three correctness gaps still open:
- late fire-and-forget routed-task progress updates can overwrite degraded or
  terminal routed-task state in the registry store
- routed-task result-report failure is still silent at the durable task-state
  level
- routed-task completion still leaks through non-task surfaces like the generic
  completion webhook and recovery egress callbacks

This phase finishes the routed-task lifecycle model without adding any new
channel-specific escape hatches or parallel delivery paths.

#### Design Decisions For Phase 12

- No direct Telegram `bot.send_message(...)` or any other channel-specific
  cross-cutting notification fix for routed-task result-report failure.
- Routed-task lifecycle correction stays on the existing task-routing/store/UI
  seam. If origin-user notification ever becomes a product requirement, it must
  be implemented later as a generic origin-delivery concern, not a Telegram
  patch in worker/finalization code.
- Protected routed-task end/degraded states are explicit product vocabulary,
  not inferred from `result_json IS NULL`. A later successful
  `update_routed_task_result()` remains authoritative and may overwrite prior
  degraded state.
- Use existing degraded vocabulary for result-delivery failure:
  `partialfailed`, not `failed`, because the execution itself succeeded.
- Because `partialfailed` is only partially represented in the current registry
  UI/filter surface, the same slice that adopts it must add explicit UI/test
  coverage so the degraded state is visible and does not become a hidden
  internal code.

#### Slice 12A: Guard terminal and degraded routed-task states in both stores

- Add one shared canonical protected-status set on the existing registry-store
  seam (`store_base.py` or the narrowest equivalent shared module). Do not
  duplicate ad hoc SQL status lists across SQLite and Postgres.
- `update_routed_task_status()` in both:
  - `app/registry_service/store.py`
  - `app/registry_service/store_postgres.py`
  must not overwrite routed tasks already in protected states.
- Protected states for this phase:
  - `completed`
  - `failed`
  - `cancelled`
  - `timed_out`
  - `partialfailed`
- `update_routed_task_result()` remains authoritative and may overwrite prior
  degraded state such as `partialfailed`.
- Do not reframe terminal ownership around `result_json IS NULL`; that leaves
  degraded fallback state unprotected.

Tests:
- contract test proves a late `running` status update cannot overwrite
  `completed`
- contract test proves a late `running` status update cannot overwrite
  `partialfailed`
- contract test proves a later successful `update_routed_task_result()` can
  still overwrite `partialfailed`
- SQLite + Postgres in the same contract suite

**Commit: "routed-task / 12a: guard terminal and degraded task states"**

#### Slice 12B: Persist degraded routed-task state when result delivery fails

- In `app/workflows/execution/finalization.py`, when
  `report_routed_task_result()` fails or times out:
  - keep `routed_result_status = "report_failed"`
  - submit a fire-and-forget `update_routed_task_status()` through the existing
    `TaskRoutingPort`
  - use `status = "partialfailed"`
  - write a summary that clearly states execution completed but result delivery
    to the requesting conversation failed
- Do not add any direct Telegram send, raw bot call, or other channel-specific
  notification path.
- Do not publish the warning back onto the routed-task ref through egress.
- This slice owns durable degraded task state only. It does NOT add a new
  origin-user notification feature.
- In the same slice, add the small routed-task UI/test coverage needed so
  `partialfailed` is treated as an intentional visible degraded state rather
  than a hidden badge-only leftover.

Tests:
- finalization test proves report failure triggers fallback
  `update_routed_task_status(status="partialfailed", ...)`
- integration test proves failed result report reaches the registry store
  through the bus as `partialfailed`
- UI/test coverage proves `partialfailed` renders intelligibly on the routed
  task surface
- worker/finalization regression test proves no direct Telegram/raw channel
  notification path was introduced

**Commit: "routed-task / 12b: persist degraded state on result delivery failure"**

#### Slice 12C: Skip generic completion webhook for routed tasks

- In `app/workflows/execution/finalization.py`, the generic completion webhook
  must not fire when `context.routed_task_id` is present.
- Routed-task completion is owned by task routing, not by the generic
  `conversation_completed` webhook contract.

Tests:
- routed-task finalization does not schedule the completion webhook
- non-routed completion webhook behavior stays unchanged

**Commit: "routed-task / 12c: skip completion webhook for routed tasks"**

#### Slice 12D: Suppress routed-task recovery egress callbacks

- In `app/channels/telegram/worker.py`, recovery dispatch for routed tasks must
  not pass either:
  - `bind_egress`
  - `send_notice`
  through the task-ref egress seam.
- Use explicit no-op async callbacks for routed tasks on both recovery hooks.
- This slice is broader than just skipping `bind()`. Recovery notices on task
  refs are already structurally inert, so both callbacks must be closed.
- Routed-task recovery is not a first-class surfaced workflow today. Do not
  invent one here.

Tests:
- routed-task recovery does not call `bind()`
- routed-task recovery does not call `send_recovery_notice()`
- non-routed recovery still calls both callbacks normally
- routed-task recovery dispatch still returns a valid outcome and does not
  crash

**Commit: "routed-task / 12d: suppress routed-task recovery egress"**

#### Slice 12E: Prove routed-task progress throttling at the real callback boundary

- Add a routed-task throttling proof at the integration point where
  `TelegramProgress.update()` invokes the callback.
- The test must prove:
  - rapid non-forced progress updates do not invoke the routed-task progress
    callback one-for-one
  - `force=True` still bypasses throttling
  - routed-task progress remains in-flight only and does not infer terminal
    state from user-facing text

Tests:
- rapid burst of routed-task progress updates is throttled
- forced update bypasses the interval gate
- callback mapping tests still prove routed-task progress emits
  `status="running"` for user-facing terminal-ish labels

**Commit: "routed-task / 12e: prove routed-task progress throttling"**

#### Slice 12F: Status, guardrails, and final closeout

- Reopen `status.md` so it accurately states that Phase 11 overclaimed
  completion and Phase 12 is the active remediation track until 12A-12E land.
- After the code slices are green, update `status.md` again to reflect the
  actual final state.
- Prefer contract and integration tests over grep gates for store semantics.
- Run the full suite after the slice and close the track only if every prior
  slice is green.

Tests:
- full suite
- any narrow regression tests needed to keep:
  - no routed-task webhook
  - no routed-task recovery bind/notice
  - no direct channel-specific notification workaround
  - degraded routed-task state protected from late progress updates

**Commit: "routed-task / 12f: update status and close lifecycle remediation"**

## Hard Rules

1. **Ports named by domain, not backend.** `ConversationProjectionPort`,
   not `RegistryPort`.
2. **No `if registry_runtime is not None` in channel/workflow code.**
3. **No registry client construction outside registry-owned code.**
4. **`BotServices` never None.** No-op for standalone. No booleans.
   Typed unavailable results.
5. **Bus is first-class.** SQLite + Postgres + state machine +
   `pydantic` schemas + contract tests.
6. **Only processor makes control-plane HTTP.** Workers enqueue.
7. **Channel runtimes hold `services`, not registry fields.**
8. **`RegistryRuntime` does not mutate dispatcher.** Startup owns
   channel registration.
9. **Each slice leaves repo green.** Old fields alive during
   scaffolding.
10. **Fire-and-forget is eventual.** Request/reply has bounded
    timeout (10s default).
11. **`authority_ref` in external-facing types**, not `registry_id`.
    Registry maps internally.
12. **Processor runner is generic.** Domain logic in processors,
    infrastructure in runner. Second processor (Slack admin) plugs
    into same runner.
13. **No `is_available()` booleans on ports.** No-op semantics are
    per-method: fire-and-forget methods silently succeed, while
    request/reply methods return typed unavailable results with
    status/error fields.
14. **Pair-aware bus claiming.** `poll_commands` and
    `reconcile_orphans` operate on `(authority_ref, capability)`
    pairs. An authority that lost a capability after a scope change
    will not have its old commands claimed or left pending.
15. **Typed `pydantic` payloads per operation.** No raw `dict` at
    the adapter/processor boundary. Every operation has a typed
    request model. Request/reply operations also have a typed
    reply/result model. Fire-and-forget operations use only the
    `ControlReply` envelope acknowledgement and omit a typed result
    payload.
16. **Idempotency for non-idempotent operations.** `submit_routed_task`
    and similar MUST set an `idempotency_key`. Naturally idempotent
    operations (bind, timeline publish) MAY omit it.
17. **Lease expiry and retry limits.** Claimed commands that expire
    return to pending. Failed commands retry up to `max_retries`
    then dead-letter. No stranded commands.
18. **Scatter-gather for directory search.** `search_agents` fans
    out to all directory-capable authorities, aggregates results
    with partial-success status.
19. **Shared control-plane backend across all roles.** All producer
    and processor roles must resolve to the same backend configuration
    via `runtime_backend.init(config)`.
20. **Single source of truth for authority-capability mapping.**
    `registry_authority_capabilities()` in
    `app/agents/registry_capabilities.py`. Used by both startup
    and processor. No duplicate scope-to-capability logic.
21. **Bus payloads are domain content only.** Transport metadata
    (`authority_ref`, `idempotency_key`, `correlation_id`) belongs
    on the `ControlCommand` envelope, not in the payload. Payloads
    mirror runtime types field-for-field with no lossy flattening.
    If a runtime type changes, the payload model updates in the
    same commit.
22. **Orphan reconciliation at startup, processor-owning role only.**
    `bus.reconcile_orphans()` dead-letters commands for invalid
    `(authority, capability)` pairs. Only the process that owns
    the authoritative topology may call this. Producer-only/shared-
    worker processes must NOT reconcile — they don't know the full
    topology.
23. **No registry vocabulary in generic seams.** Generic ports,
    summaries, and UI paths may depend on capabilities/purpose, not
    on `registry_scope`.
24. **No implicit registry selection.** Runtime code must not invent
    `"default"` or silently pick the first configured registry to
    satisfy malformed inputs.
25. **Tests must guard the target architecture.** Do not preserve a
    migration seam by writing tests that require it to exist.
26. **No half-contract channels.** A registered channel must not
    advertise binding, input, or timeline capabilities that its
    scoped services cannot actually fulfill.
27. **Routed-task lifecycle belongs to task routing.** Routed-task
    progress/status/result updates are not conversation-projection
    concerns.
28. **No raw surface-name policy checks in shared orchestration,
    admission, or delivery code.** Those paths must use
    dispatcher/descriptor seams instead of branching on string
    literals like `"telegram"` when existing metadata can own the
    policy. Channel-local rendering/UX code inside
    `app/channels/<surface>/...` is not the target of this rule.
29. **No fake defaults in registry-owned state.** Registry state must
    require explicit registry ownership; dead `"default"` placeholders
    do not survive as silent constructor defaults.
30. **Routed-task execution is not a projected conversation surface.**
    Execution on `registry:{id}:task:{task_id}` refs must not rely on
    bind/result/usage/warning projection side effects to communicate
    task lifecycle.
31. **Terminal routed-task state belongs to the final result path.**
    In-flight progress may update task status, but terminal success,
    failure, cancellation, and timeout are owned by
    `report_routed_task_result()`, not by matching rendered progress
    strings.
32. **Dispatcher readiness probes stay on the channel seam.** Shared
    code may ask whether a ref is egress-ready, but it must not hardcode
    surface checks or pay the cost of constructing/discarding full
    egress objects when the owning channel can answer readiness from
    cheaper preconditions.
33. **No fake bot objects for projection.** Delivery code must not
    fabricate bot presence to build an egress for projection-only
    purposes. Projection goes through `ConversationProjectionPort`.
34. **Dead contract surfaces are deleted, not preserved.** If a field,
    method, or branch is unreachable in the target architecture, delete
    it. Do not keep it "for later."
35. **Store guards are atomic.** If a guarded status update is rejected
    (task already terminal), no side effects — including timeline-event
    upserts — should land from that command.
36. **Protected-status tests cover the full shared constant.** Do not
    test only the statuses that triggered a specific bug. Parametrize
    over `PROTECTED_ROUTED_TASK_STATUSES`.
37. **Status docs are present-tense and proven.** `status.md` must
    reflect the current state, not historical narration. Do not claim
    product polish that tests do not prove.
38. **`bridge.py` is a registry-delivery admission module only.** It
    must not export generic utilities to channel, workflow, or
    orchestration code. Relocate shared helpers to their owning
    modules (`app/identity.py`, `app/formatting.py`).
39. **No internal rollout markers in user-visible fields.** Agent
    version, display labels, and UI-rendered metadata must not contain
    internal phase/migration labels.
40. **Behavior tests are primary proof.** Grep/source-shape checks
    are secondary verification only. Do not add broad token-scan
    suites when a behavior test can prove the real contract.

## Exit Gates

### Capability Ports
- [ ] `ConversationProjectionPort` in `app/ports/`
- [ ] `TaskRoutingPort` in `app/ports/`
- [ ] `AgentDirectoryPort` in `app/ports/`
- [ ] `HealthPublicationPort` in `app/ports/`
- [ ] No-op implementations with typed unavailable results
- [ ] `ControlPlaneServices` nested in `BotServices`
- [ ] `BotServices` never None, no nullable fields

### Control-Plane Bus
- [ ] `control_plane_commands` table — SQLite + Postgres
- [ ] Postgres migration
- [ ] `pydantic` schemas for command/reply AND per-operation payloads
- [ ] `python-statemachine` lifecycle with lease expiry + dead letter
- [ ] CAS discipline on all transitions
- [ ] `ControlPlaneBus` facade: submit/request/poll/complete/fail/dead_letter/reclaim_expired
- [ ] Pair-aware claiming: `poll_commands(allowed_pairs={(auth, cap), ...})`
- [ ] Idempotency key deduplication on submit
- [ ] Lease expiry reclaim (claimed → pending when expired)
- [ ] Retry count tracking, dead-letter after max_retries
- [ ] Contract tests for both stores covering all invariants
- [ ] Fire-and-forget returns immediately
- [ ] Request/reply correlates and times out
- [ ] All roles share same selected control-plane backend configuration
- [ ] `reconcile_orphans()` dead-letters commands for invalid (authority, capability) pairs
- [ ] Startup calls reconcile after directory is built
- [ ] `ControlCommand.authority_ref` required and validated non-empty

### Processor
- [ ] `ControlProcessor` protocol with `authority_capabilities()` per-authority map
- [ ] `ProcessorRunner`: generic claim loop with address-aware dispatch
- [ ] Runner handles lease renewal, retry/backoff, dead-letter escalation
- [ ] Runner calls `reclaim_expired()` periodically
- [ ] `RegistryControlProcessor`: per-authority capabilities respecting `registry_scope`
- [ ] Handles per-authority commands, error isolation per registry
- [ ] Scatter-gather for discovery across directory-capable authorities
- [ ] Runner only for registry roles
- [ ] No-op processor for standalone

### Consumer Migration
- [ ] Telegram egress through ports
- [ ] Progress timeline through port
- [ ] Worker timeline/usage through port
- [ ] Worker timeline publication has one owner path: `ConversationProjectionPort`
- [ ] Worker does not branch on channel type to publish timeline events
- [ ] Finalization through `TaskRoutingPort`
- [ ] Routed-task execution progress flows through `TaskRoutingPort.update_routed_task_status()`
- [ ] Routed-task execution metadata/context carries explicit `authority_ref`
- [ ] Routed-task execution does not emit projected task-ref bind/result/usage/warning side effects
- [ ] Routed-task execution does not silently end on interactive-only branches; blocked tasks report failure
- [ ] Delegation through `AgentDirectoryPort` + `TaskRoutingPort`
- [ ] Delegation channel through `ConversationProjectionPort`
- [ ] Zero `if registry_runtime is not None` in channel/workflow

### Provenance
- [ ] `authority_ref` replaces `registry_id` in external types
- [ ] `DiscoveredAgentRef.authority_ref`
- [ ] Bus commands use `authority_ref`
- [ ] Consumer code never parses authority_ref

### Cleanup
- [ ] `TelegramRuntime.registry_runtime` deleted
- [ ] `TelegramRuntime.registry_client_factory` deleted
- [ ] `FinalizationContext` registry factories and dead `registry_id` field deleted
- [ ] Bridge consumer-facing helpers deleted/internalized
- [ ] No direct bridge timeline/bind helper imports outside pure registry helper code
- [ ] Direct registry timeline side effects removed from delivery/orchestration code
- [ ] `RegistryTaskChannel` does not advertise projected timeline support
- [ ] `admit_registry_delivery(kind="routed_task")` does not emit task-channel bind/timeline side effects
- [ ] Channel registration in startup only
- [ ] Registry egress through port
- [ ] `RegistryRuntime.runtime_for_registry()` deleted
- [ ] `RegistryRuntime.resolve_target_registry_id()` deleted
- [ ] Compatibility shims for `registry_id`, `user_id`, and `chat_id` removed once migration window closes
- [ ] No implicit `"default"` / first-registry fallbacks remain in runtime, delivery, bridge, or registry egress
- [ ] `RegistryConnectionState` no longer defaults `registry_id` to `"default"`
- [ ] Grep gates enforcing boundary
- [ ] Full suite passes after every slice

### Operability
- [ ] Completed commands purged after retention period
- [ ] Dead-lettered commands queryable
- [ ] `./octopus doctor` shows bus health (pending/claimed/dead counts)
- [ ] Startup validates control-plane backend connectivity (SQLite: data_dir writable; Postgres: database_url reachable, schema exists)
- [ ] `ControlPlaneDirectory` built from config at startup

### Genericity
- [ ] Generic health/discovery seams do not expose `registry_scope`
- [ ] `/discover` filters authorities by capabilities, not registry vocabulary
- [ ] Delivery/admission code does not branch on raw surface-name strings when descriptor policy can own the decision

### Test Hygiene
- [ ] Zero-import gates allow dead imports to disappear; they do not require scaffolding to exist
- [ ] Worker timeline tests assert the final single-path design
- [ ] Stale claim-token negatives cover complete/fail/dead-letter/renew-lease
- [ ] Tests do not construct registry egress with unqualified refs
- [ ] Tests do not encode routed-task projection behavior that the target architecture rejects
- [ ] Tests do not derive routed-task terminal state from formatted progress strings

### Production Shape
- [ ] Shared worker + 2 registries mirrors all events
- [ ] Shared worker routed task results correct
- [ ] One degraded registry doesn't block others
- [ ] Bus commands survive process restart
- [ ] Coordination-only: no projection commands
- [ ] Registry-only bot works without Telegram
- [ ] Local mode works (bus + processor same process)
- [ ] No broadcast commands on bus — all targeted via authority_ref
- [ ] Adapter-side expansion via directory for multi-authority intents
- [ ] Coordination-only routed tasks update task status/result without relying on conversation projection
- [ ] Full-scope routed tasks also avoid task-ref projection during execution/finalization

### Phase 13: Final Surface and Contract Cleanup
- [ ] `_egress_bot()` deleted from delivery.py
- [ ] `_publish_timeline_via_dispatcher()` deleted from delivery.py
- [ ] `RegistryDeliveryRuntime` has `services: BotServices`
- [ ] Delivery timeline projection uses `ConversationProjectionPort` directly
- [ ] `runtime.bot` preserved only for live egress (lines 173, 258, 303)
- [ ] `partialfailed` renders as "Delivery failed" in registry UI
- [ ] `timed_out` renders as "Timed out" in registry UI
- [ ] Generic underscored statuses humanized by fallback
- [ ] `routed_result_warning_text` removed from `FinalizationOutcome`
- [ ] Dead worker send branch for routed-result warning removed
- [ ] All 5 `PROTECTED_ROUTED_TASK_STATUSES` have parametrized contract tests (both backends)
- [ ] `completed` case includes `result_json` preservation check
- [ ] Progress callback log says "progress callback" not "timeline callback"
- [ ] Timeline-event upserts gated behind rowcount in both stores
- [ ] Contract test proves: rejected status update → no new timeline rows
- [ ] `status.md` is present-tense and does not overclaim
- [ ] Full suite passes after every slice

## Implementation Prompt

Implement the control-plane capability architecture for
`telegram-agent-bot` according to this plan. Read the plan fully
before starting.

### Before Writing Code, Read

**Architecture rules:**
- `AGENTS.md`
- `CLAUDE.md`
- `SKILLS.md`
- `multiregistry_plan.md`

**Existing port patterns:**
- `app/ports/egress.py`
- `app/ports/channel.py`

**Current control-plane leakage (every file listed must be read):**
- `app/channels/telegram/egress.py`
- `app/channels/telegram/progress.py`
- `app/channels/telegram/delegation_channel.py`
- `app/channels/telegram/worker.py`
- `app/channels/telegram/state.py`
- `app/workflows/execution/finalization.py`
- `app/agents/delegation.py`
- `app/agents/bridge.py`
- `app/agents/delivery.py`
- `app/agents/registry_runtime.py`
- `app/agents/runtime.py`
- `app/channels/registry/egress.py`
- `app/channels/registry/channel.py`
- `app/session_state.py`
- `app/runtime/inbound_types.py`
- `app/runtime/work_admission.py`
- `app/workflows/delegation/coordination.py`
- `app/channels/telegram/presenters.py`
- `app/channels/telegram/execution.py`
- `app/workflows/execution/context.py`
- `app/workflows/execution/contracts.py`
- `app/main.py`

**Existing transport patterns to follow:**
- `app/work_queue.py` — facade
- `app/work_queue_sqlite_impl.py` — SQLite CAS
- `app/work_queue_postgres_impl.py` — Postgres CAS
- `app/workflows/recovery/machine.py` — state machine
- `tests/contracts/test_transport_store_contract.py` — contract tests
- `tests/contracts/test_control_plane_store_contract.py`
- `tests/test_control_plane_processor_runner.py`
- `tests/test_telegram_worker_timeline.py`
- `tests/test_zero_import_gates.py`
- `tests/test_registry_adapter.py`

**Registry runtime (processor wraps):**
- `app/agents/registry_runtime.py`
- `app/agents/client.py`

### Hard Rules

1. Ports by domain, not backend. No `RegistryPort`.
2. No `if registry_runtime is not None` in channel/workflow.
3. No registry client construction outside registry-owned code.
4. `BotServices` never None. No-op semantics are per-method:
   fire-and-forget methods silently succeed, request/reply methods
   return typed unavailable. `TaskRoutingPort` has both kinds.
5. Bus: SQLite + Postgres + `pydantic` + `python-statemachine` +
   contract tests. All roles share storage.
6. Only processor makes control-plane HTTP. Workers enqueue.
7. `services` on channel runtimes, not registry fields.
8. Startup owns channel registration.
9. Each slice green. Old fields alive during scaffolding.
10. Fire-and-forget eventual. Request/reply bounded timeout.
11. `authority_ref` from day one. Not `registry_id`.
12. Pair-aware claiming: `(authority_ref, capability)` pairs, not flat sets.
13. Typed `pydantic` request payload per operation. Request/reply
    operations also have typed result payloads. Fire-and-forget
    operations use envelope acknowledgement only.
14. Idempotency keys for non-idempotent operations.
15. Lease expiry + retry + dead-letter. No stranded commands.
16. Scatter-gather for directory with partial-success status.
17. Generic runner, domain processors.
18. Single source of truth for authority-capability mapping.
19. Bus payloads are domain content only. Transport metadata on
    envelope. Payloads mirror runtime types — no lossy flattening.
20. Orphan reconciliation at startup, processor-owning role ONLY.
21. `ControlCommand.authority_ref` required, validated non-empty.
22. No generic seam may expose `registry_scope`.
23. No implicit `"default"` or first-registry fallbacks.
24. Tests must enforce final architecture, not scaffolding windows.
25. Registered channels must not claim capabilities their scoped
    services cannot fulfill.
26. Routed-task lifecycle is task-routing, not conversation
    projection.
27. Do not branch on raw surface-name strings in shared
    orchestration/admission when dispatcher descriptors can own the
    policy.
28. Thread explicit `authority_ref` through existing execution
    metadata/context instead of reparsing task refs.
29. Do not patch routed-task lifecycle failures with direct
    channel-specific sends. Origin-user notification, if ever added,
    must be a generic delivery concern, not a raw Telegram or
    surface-specific workaround.

### Execution Rules

- Follow phases exactly.
- Phase 2 and Phase 3 can be parallel.
- No consumer cutover before ports and bus contracts exist.
- No cleanup deletion before shared-worker tests exist.
- Phase 9 executes strictly in order; do not jump ahead to deletion
  slices before the worker, delivery, and genericity fixes land.
- Phase 10 executes strictly in order. Fix the routed-task surface
  model before replacing residual surface-name string checks.
- Phase 11 executes strictly in order. Remove execution-time task-ref
  projection drift before polishing terminal-state ownership and
  readiness efficiency.
- Phase 12 executes strictly in order. Protect degraded/terminal task
  state before adding fallback result-delivery handling, then close
  webhook/recovery leaks before final throttling proof and status
  closeout.
- Phase 13: 13A first (structural fix), then 13B/13C/13E parallel-safe,
  then 13D → 13F sequential (both touch store contract tests), then
  13G last (status closeout).
- Phase 14: strictly sequential. 14A → 14B → 14C → 14D → 14E.
  14B depends on 14A (bridge clean before relocation). 14D depends
  on 14B/14C (behavior tests after code shape is correct).
- Run full suite after every slice.
- After each slice: check for duplicate paths, grep for leaks,
  verify no consumer imports concrete registry classes.
- If a fix requires adding another helper in `bridge.py`, stop
  and fix the abstraction instead.

### Phase 10 Execution Prompt

Implement the post-Phase-9 routed-task surface correction exactly as
described in this plan.

Problem to fix:
- Registry routed tasks are still partially modeled as projected
  conversations. That is wrong. Conversation projection belongs to
  registry conversation surfaces. Routed-task lifecycle belongs to
  `TaskRoutingPort` and the routed-task store/UI.
- `RegistryTaskChannel` still advertises projected timeline support
  even though coordination-only registries do not have
  `conversation_projection`.
- `admit_registry_delivery(kind="routed_task")` still emits task-
  channel bind/timeline side effects.
- Routed-task execution progress is not yet integrated with
  `TaskRoutingPort.update_routed_task_status()`.
- Residual raw `"telegram"` checks remain in delivery/admission code.

Required outcomes:
- `RegistryTaskChannel` no longer claims projected timeline support.
- routed-task admission keeps work admission but does not bind or
  publish timeline through task-channel egress.
- routed-task execution progress/status uses
  `TaskRoutingPort.update_routed_task_status()`.
- routed-task completion stays on
  `TaskRoutingPort.report_routed_task_result()`.
- execution metadata/context carries explicit `authority_ref` from
  canonical inbound provenance; no registry-ref reparsing in Telegram
  execution/workflow code.
- residual surface-specific policy checks move onto the existing
  dispatcher seam (runtime readiness) or existing descriptor seam
  (static admission policy), depending on the concern.
- `RegistryConnectionState` stops defaulting `registry_id` to
  `"default"`.

Implementation guidance:
- Extend existing types before inventing anything:
  `ExecutionChannelMetadata`, `ExecutionChannelContext`,
  Telegram execution builders, worker call sites, and existing
  descriptor policy seams.
- Keep the fix concern-based:
  projected conversation progress => `ConversationProjectionPort`
  routed-task progress => `TaskRoutingPort`
- Do not add a new port, channel family, abstraction layer, or
  compatibility shim.
- For routed-task progress, fix the existing callback-builder seam
  explicitly. The context builder must have enough inputs to choose by
  concern once `authority_ref` is threaded through:
  - preferred: add
    `build_conversation_progress_callback(conversation_ref, routed_task_id)`
    and
    `build_routed_task_progress_callback(routed_task_id, authority_ref)`
  - acceptable alternative: extend the existing factory signature to
    accept `authority_ref`
  Keep the callback signature stable at the final call site and
  convert `(html_text, force)` into a `RoutedTaskUpdate` inside the
  routed-task wrapper. Reuse existing text-cleaning/summarization
  patterns and preserve throttling.
- Treat readiness and policy separately:
  - runtime egress readiness belongs on the dispatcher seam
  - static admission policy may use `ChannelDescriptor` if an
    additional minimal field is needed
- If a test currently encodes the wrong architecture, change the test
  in the same slice as the code.

Testing requirements:
- Positive:
  - routed-task admission still admits work items successfully
  - routed-task execution still completes successfully after Slice
    10A and before Slice 10C lands
  - routed-task execution progress updates registry task status
  - routed-task final result reporting still works
  - projected conversation execution still publishes through
    `ConversationProjectionPort`
  - coordination-only registries still enqueue no projection
    commands
- Negative:
  - routed-task admission does not bind/publish via task-channel
    egress
  - `RegistryTaskChannel` does not advertise projected timeline
    support
  - no new registry-ref parsing appears in Telegram
    execution/workflow code
  - no residual targeted raw `"telegram"` string checks remain in
    shared delivery/admission policy code

Process rules:
- Follow slices 10A-10E in order.
- Update `status.md` after every slice.
- Run focused tests for each slice, then the full suite.
- Review each slice against the target architecture before moving on.

### Phase 11 Execution Prompt

Implement the post-Phase-10 routed-task execution cleanup exactly as
described in this plan.

Problem to fix:
- Routed-task admission and callback wiring were corrected, but routed-task
  execution still leaks through projected task-ref egress behavior during the
  worker/provider/finalization lifecycle.
- Full-scope routed tasks still emit projected task-surface side effects such
  as bind/start/completed/usage/warning events on `registry:{id}:task:{id}`.
- Routed-task terminal state is still partially inferred from rendered progress
  text instead of being owned by the final routed-task result path.
- `ChannelDispatcher.egress_ready_for_ref()` still constructs/discards full
  egress objects for a readiness probe.

Required outcomes:
- Routed-task execution no longer emits projected task-ref bind/result/usage/
  warning side effects.
- Routed-task executions that hit an interactive-only branch do not silently
  stop; they report failure through the existing routed-task result path.
- Routed-task in-flight progress still updates task status, but terminal state
  is owned by `report_routed_task_result()`, not by string-matching progress
  labels.
- Dispatcher readiness checks stay on the existing channel seam and use the
  cheapest correct channel-owned precondition check available.

Implementation guidance:
- Extend existing seams before inventing anything:
  `RegistryChannelEgress`, worker dispatch/finalization call sites,
  execution request/result handling, `Channel`, and `ChannelDispatcher`.
- Do not add a new port, a task-only channel family, or a new policy
  subsystem.
- If you need a routed-task-specific behavioral distinction, keep it as a
  small branch on the existing task-ref/channel seam rather than a second
  execution path.
- Prefer making routed-task terminal ownership explicit at the execution
  source over inferring it downstream from user-facing message text.
- If you discover an interactive-only branch that cannot make sense for a
  routed task, fail it cleanly and report the failure rather than pausing it
  behind a silent message path.

Testing requirements:
- Positive:
  - routed-task execution still runs and reports result through task routing
  - in-flight routed-task progress still updates task status
  - projected registry conversation execution still behaves normally
  - routed-result delivery retry behavior stays correct
- Negative:
  - no projected `started` / `bot_message` / `completed` / `failed` / `usage`
    events are emitted on task refs during routed-task execution
  - routed-task report-failure warnings do not publish to task refs
  - routed-task terminal status is not sourced from rendered progress labels
  - dispatcher readiness no longer has to construct/discard a full Telegram
    egress object

Process rules:
- Follow slices 11A-11C in order.
- Update `status.md` after every slice.
- Run focused tests for each slice, then the full suite.
- Review each slice against the target architecture before moving on.

### Phase 12 Execution Prompt

Implement the post-Phase-11 routed-task lifecycle remediation exactly as
described in this plan.

Problem to fix:
- late fire-and-forget routed-task progress updates can regress degraded or
  terminal routed-task state in the registry store
- routed-task result-report failure does not leave durable degraded task state
- the generic completion webhook still fires for routed tasks
- routed-task recovery still passes task-ref egress callbacks that are wrong or
  inert on the task surface
- no test yet proves routed-task progress inherits throttling at the real
  callback boundary

Required outcomes:
- protected routed-task end/degraded states cannot be overwritten by late
  `update_routed_task_status()` calls
- result-delivery failure is surfaced durably on the task itself through
  existing task-routing/store/UI seams
- no direct Telegram or other channel-specific cross-cutting notification path
  is introduced
- routed tasks do not fire the generic completion webhook
- routed-task recovery does not call task-ref bind/notice egress callbacks
- routed-task progress throttling is proven at the real callback boundary

Implementation guidance:
- Extend existing seams only:
  `store_base.py`, `store.py`, `store_postgres.py`,
  `finalization.py`, `worker.py`, existing routed-task UI/test paths, and the
  current Telegram progress tests.
- Do not add a new delivery subsystem, new task status type system, or any raw
  surface-specific send path.
- Use existing degraded vocabulary: `partialfailed`.
- Because `partialfailed` is only partially surfaced today, the slice that
  adopts it must add the minimal UI/test coverage needed for it to be a real
  visible state.
- `update_routed_task_result()` remains authoritative and may overwrite prior
  degraded state.
- Prefer contract/integration tests over grep-only enforcement for store
  semantics.

Testing requirements:
- Positive:
  - later successful `update_routed_task_result()` can overwrite prior
    `partialfailed`
  - failed result report leaves durable `partialfailed` state with explanatory
    summary
  - non-routed completion webhooks still fire
  - non-routed recovery still binds and sends recovery notice
  - forced routed-task progress updates still invoke the callback immediately
- Negative:
  - late `running` progress cannot overwrite `completed`
  - late `running` progress cannot overwrite `partialfailed`
  - no direct Telegram/raw channel notification path appears for result-report
    failure
  - routed-task webhook does not fire
  - routed-task recovery does not call bind/notice egress hooks
  - non-forced rapid routed-task progress does not invoke the callback
    one-for-one

Process rules:
- Follow slices 12A-12F in order.
- Update `status.md` after every slice.
- Run focused tests for each slice, then the full suite.
- Review each slice against the target architecture before moving on.

### Phase 13: Final Surface and Contract Cleanup

This phase removes the last structural hacks, dead contract
surfaces, and under-covered invariants that survived earlier phases
because they "technically worked." The recurring pattern across the
entire rollout was: a structurally wrong path gets removed, a narrower
replacement lands and passes tests, but one residual seam remains
because it was already there and technically functional. Tests then
normalize that compromise instead of forcing the final product
contract. Phase 13 closes those gaps.

#### Architecture and Product Vision

The target end-state is:

- **Delivery projection uses the control-plane port directly.**
  Registry delivery code publishes parent-conversation timeline
  events through `ConversationProjectionPort`, not through a
  fabricated channel egress constructed with a dummy bot object. The
  `_egress_bot() → object()` hack and the
  `_publish_timeline_via_dispatcher()` proxy are deleted.

- **Degraded task state is productized.** Operators see
  human-readable labels, not raw internal status codes. `partialfailed`
  renders as "Delivery failed" in the registry UI. Generic statuses
  with underscores are humanized. Raw status values are preserved only
  for CSS class mapping and filter logic.

- **Dead contract surfaces are removed, not preserved.** Code should
  not suggest a user-visible path exists when the architecture
  deliberately does not use it. `routed_result_warning_text` is
  deleted.

- **Store invariants are fully covered.** The protected-status
  contract is tested across all five members of the shared constant,
  not just the two that were immediately in play for a specific bug.
  Timeline-event upserts respect the terminal-state guard.

- **Logs are concern-neutral.** Callback failure messages describe
  the concern accurately, not the implementation that was there
  before the refactor.

- **Status documentation is honest.** `status.md` reflects the
  present state, not a historical narration that overclaims closure.

#### Slice 13A: Remove delivery-side egress proxy for projection

**Problem**: `_publish_timeline_via_dispatcher()` in
`app/agents/delivery.py` fabricates bot presence with `_egress_bot()`
→ `object()` and builds a channel egress just to call
`publish_timeline()`. This abuses egress construction as a projection
adapter. The control-plane port should be used directly.

**Fix**:
- Add `services: BotServices` to `RegistryDeliveryRuntime`.
- Thread real services from startup in `main.py` through the existing
  `build_registry_delivery_runtime()`.
- Replace `_publish_timeline_via_dispatcher()` with a direct helper
  that calls
  `services.control_plane.conversation_projection.publish_external_timeline()`.
- Delete `_egress_bot()` and `_publish_timeline_via_dispatcher()`.
- Update only the real projection-only call sites:
  - delegated-result parent timeline
  - delegation-ready after admitted resume
  - delegation-ready after duplicate resume

**Preserve** (do not touch):
- `runtime.bot` for real live egress paths (lines 173, 258, 303
  in delivery.py — readiness checks, delegation completion messages,
  conversation resume egress).
- `runtime.dispatcher` for real live egress paths.
- `dispatcher.egress_ready_for_ref(...)` as a runtime-readiness
  check.
- `dispatcher.create_egress(...)` only where actual output/resume
  is needed.

Tests:
- parent timeline publication uses `ConversationProjectionPort`
  directly
- startup-race still returns `retry_later` when egress not ready
- real live egress creation still exists only for actual output paths
- no fake bot `object()` is used for projection-only behavior

**Commit: "phase-13 / 13a: replace delivery egress-proxy with
control-plane port"**

#### Slice 13B: Humanize routed-task degraded status in registry UI

**Problem**: `app/channels/registry/ui.py` renders raw `partialfailed`
as badge text. The CSS class mapping exists, but the text is the raw
internal code.

**Fix**: Add a JS display-label helper that handles null/empty input
and normalizes underscored statuses:

```javascript
function statusLabel(status) {
  if (!status) return "Open";
  const labels = {
    partialfailed: "Delivery failed",
    timed_out: "Timed out",
  };
  return labels[status]
    || status.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase());
}
```

Guard against falsy input — current render sites use
`item.status || "open"` and this helper must not throw on
`null`/`undefined`/`""`. The fallback handles underscored statuses
generically (`timed_out` → "Timed out"). Explicit mappings override
where the generic humanization is unclear.

Apply `statusLabel(item.status)` at every visible badge/status text
render site in place of the raw `escapeHtml(item.status || "open")`
pattern. Keep raw status values for CSS class mapping
(`getBadgeClass`) and filter logic — those are internal concerns.

Also verify `getBadgeClass` handles `timed_out` correctly. The
current badge-class lookup normalizes keys by stripping non-letter
characters, so `timed_out` becomes `timedout`. If `timedout` has
no badge-class mapping, either add the normalized key
(`timedout: "badge-failed"`) or adjust the normalization so
underscored keys match. Do not add a `timed_out` key verbatim —
it will not match the normalized lookup.

Tests (the current registry UI test seam inspects static rendered
HTML/JS source, not browser-executed output — phrase all assertions
as source-level verification, not runtime-behavior claims):
- rendered HTML/JS contains the `statusLabel` helper with the
  explicit `partialfailed` → "Delivery failed" mapping
- rendered HTML/JS contains the `timed_out` → "Timed out" mapping
- rendered HTML/JS contains the empty/falsy guard returning "Open"
- badge-text render sites call `statusLabel(...)` instead of raw
  `escapeHtml(item.status || "open")`
- `getBadgeClass` map contains a key that matches the normalized
  form of `timed_out` (i.e. `timedout`)
- existing filter tests pass unchanged

**Commit: "phase-13 / 13b: humanize task status labels in
registry UI"**

#### Slice 13C: Delete dead routed-result warning surface

**Problem**: `routed_result_warning_text` on `FinalizationOutcome` is
set when result-report fails for routed tasks, but the worker
suppresses it with `not is_routed_task`. For non-routed tasks, the
result-report path is never entered. The field is dead contract surface
that suggests a user-visible warning path exists when the architecture
deliberately does not use it.

**Fix**:
- Remove `routed_result_warning_text` from `FinalizationOutcome`.
- Remove all assignments to it in `finalize_execution()`.
- Remove the unreachable worker send branch at worker.py line 484.
- Update tests to assert the real contract:
  - `routed_result_status == "report_failed"`
  - fallback `partialfailed` status is emitted via the control-plane
    port
  - no user-visible routed-result warning send path exists.
- Prefer behavior tests, not a grep gate as primary proof.

Tests:
- finalization test: result-report failure → `report_failed` +
  `partialfailed` fallback — no warning text assertion
- worker test: no dead send branch for routed-result warning

**Commit: "phase-13 / 13c: remove dead routed-result warning
surface"**

#### Slice 13D: Parametrize protected-status contract coverage

**Problem**: `PROTECTED_ROUTED_TASK_STATUSES` has 5 statuses
(`completed`, `failed`, `cancelled`, `timed_out`, `partialfailed`)
but contract tests prove only 2.

**Fix**: Parametrize the contract test over the full shared constant:

```python
@pytest.mark.parametrize("protected_status",
                         PROTECTED_ROUTED_TASK_STATUSES)
def test_routed_task_status_updates_cannot_overwrite_protected(
    store, protected_status,
):
    ...
    assert task["status"] == protected_status
```

Generates 5 test cases × 2 backends = 10 parametrized cases.

- The `completed` case is special: it must be established via
  `update_routed_task_result()` (not `update_routed_task_status()`)
  because that is the only path that writes `result_json`. The
  parametrized test must branch for `completed` to use the result
  path, then assert both status protection AND `result_json`
  preservation after the late `running` update. All other protected
  statuses are established via `update_routed_task_status()`.
- Keep `test_routed_task_result_can_overwrite_partialfailed` as a
  separate test — that covers result-write authority, not the
  protected set.
- Delete the now-subsumed
  `test_routed_task_status_updates_do_not_overwrite_partialfailed`.

Tests:
- all 5 protected statuses across both backends
- late `running` cannot overwrite any protected status
- `completed` case includes `result_json` preservation
- later result write can still repair `partialfailed`

**Commit: "phase-13 / 13d: parametrize protected-status contract
tests"**

#### Slice 13E: Concern-neutral progress callback log

**Problem**: `app/channels/telegram/progress.py` line 61 says
`"Control-plane timeline callback failed"` even when the callback is
routed-task status publication via `TaskRoutingPort`.

**Fix**: Change to `"Control-plane progress callback failed"`.
One-line string change.

Tests:
- suite only, unless there is nearby log-assert coverage that
  needs updating

**Commit: "phase-13 / 13e: concern-neutral progress callback log"**

#### Slice 13F: Guard timeline-event upserts behind status guard

**Problem**: Both stores upsert `timeline_events` unconditionally
after the guarded `UPDATE routed_tasks SET status = ? ... AND
status NOT IN (protected)`. If the status update was rejected
(task already terminal), timeline events from a late progress
update still land. This is inconsistent — a rejected status
update should not produce timeline side effects.

**Fix**: Capture the guarded `UPDATE` cursor. Only upsert
`timeline_events` when the update affected a row:

```python
# SQLite
cursor = conn.execute(...)
if cursor.rowcount > 0:
    for event in payload.get("timeline_events", []):
        self._upsert_timeline_event(...)

# Postgres (psycopg cursor supports .rowcount)
cur.execute(...)
if cur.rowcount > 0:
    for event in payload.get("timeline_events", []):
        self._upsert_timeline_event(...)
```

Both stores. Same logic.

Tests: contract test (both backends):
1. Set task to protected state via `update_routed_task_result`
2. Send `update_routed_task_status` with `status="running"` and
   `timeline_events=[{event_data}]`
3. Assert task status is still `"completed"` (unchanged)
4. Assert no new timeline rows were written for this task

Both assertions required — that is the full invariant.

**Commit: "phase-13 / 13f: guard timeline-event upserts behind
status guard"**

#### Slice 13G: Rewrite status doc and close out honestly

**Problem**: `status.md` still carries the recurring rollout mistake
pattern: stale baseline headers, "Current State" mixing old
in-progress bullets with later closeout bullets, overclaiming the UI
side of `partialfailed`.

**Fix**:
- Rewrite the baseline header to the actual plan/track.
- Make "Current State" present-tense only.
- Move older phase narration into slice log/history.
- Only claim what is directly proven by code and tests:
  - delivery projection ownership fixed
  - product-visible degraded status fixed
  - dead warning surface removed
  - protected-state contract fully covered
  - status/timeline guard parity closed
- Do not overclaim anything not directly proven.

Tests:
- full suite

**Commit: "phase-13 / 13g: update status and close final cleanup"**

### Phase 13 Parallelization

- **13A must be first** — it is the structural fix.
- **13B, 13C, and 13E are parallel-safe** after 13A — they touch
  disjoint files (UI, finalization/worker, progress log).
- **13D and 13F must be sequential** (13D before 13F) — both
  change `test_registry_store_contract.py` and `13F` also changes
  the same store seam that `13D` validates.
- **13G must be last** — it closes docs only after everything is
  green.

Recommended execution:
13A → (13B, 13C, 13E in any order) → 13D → 13F → 13G.

### Phase 13 Execution Prompt

Implement the Phase 13 final surface and contract cleanup for
`telegram-agent-bot` exactly as described in this plan.

#### Problem to Fix

Six residual issues survived earlier phases because the plumbing
technically worked even though the architecture was wrong:

1. Registry delivery fabricates a dummy bot to build egress as a
   projection proxy — the control-plane port should be used directly.
2. `partialfailed` renders verbatim in the registry UI badge text.
3. `routed_result_warning_text` is dead contract surface — set for
   routed tasks but unreachable in the worker.
4. Protected-status contract tests cover only 2 of 5 statuses.
5. Progress callback failure log says "timeline" when it may be
   task-routing.
6. Timeline-event upserts still land even when the status-update
   guard rejects the command.

#### Required Outcomes

- `_egress_bot()` and `_publish_timeline_via_dispatcher()` deleted.
- `RegistryDeliveryRuntime` gains `services: BotServices`.
- Delivery timeline publication goes through
  `ConversationProjectionPort` directly.
- `runtime.bot` preserved only for real live egress (readiness
  checks, resume, delegation completion).
- `partialfailed` renders as "Delivery failed" in the registry UI.
- `timed_out` renders as "Timed out". Generic underscored statuses
  humanized by fallback.
- `routed_result_warning_text` deleted from `FinalizationOutcome`
  and all assignments/consumers.
- All 5 protected statuses have parametrized contract tests across
  both backends. `completed` case preserves `result_json` assertion.
- Progress callback log is concern-neutral.
- Timeline-event upserts gated behind rowcount check in both stores.
- `status.md` rewritten honestly.

#### Before Writing Code, Read

**Architecture rules:**
- `AGENTS.md`
- `CLAUDE.md`

**Files that change (read every line):**
- `app/agents/delivery.py` — egress proxy removal, services addition
- `app/agents/delivery.py` lines 173, 258, 303 — live egress to
  preserve
- `app/channels/registry/ui.py` — badge text rendering, status label
- `app/workflows/execution/finalization.py` — dead warning removal
- `app/channels/telegram/worker.py` — dead send branch removal
- `app/channels/telegram/progress.py` — log message
- `app/registry_service/store.py` — timeline upsert guard
- `app/registry_service/store_postgres.py` — timeline upsert guard
- `app/registry_service/store_base.py` — protected status constant
- `app/main.py` — services threading to delivery runtime builder

**Files affected by `RegistryDeliveryRuntime` signature change
(13A — add `services: BotServices`):**
- `app/agents/delivery.py` — dataclass definition + builder
- `app/main.py` — `build_registry_delivery_runtime()` call site
- `tests/test_control_plane_integration.py` — integration test
  builder call sites
- `tests/support/handler_support.py` — test fixture builder

**Test files that change:**
- `tests/test_agents.py` — delivery projection tests
- `tests/test_execution_finalization.py` — warning removal, fallback
- `tests/test_handlers.py` — worker branch removal
- `tests/contracts/test_registry_store_contract.py` — parametrize,
  timeline guard
- `tests/test_registry_service.py` — UI label test
- `tests/test_control_plane_integration.py` — delivery runtime
  signature
- `tests/support/handler_support.py` — delivery runtime fixture

**Existing patterns to follow:**
- `app/runtime/services.py` — services threading pattern
- `tests/contracts/test_control_plane_store_contract.py` — contract
  test parametrization pattern

#### Hard Rules (Phase 13 specific)

1. No fake bot objects for projection. Projection goes through the
   control-plane port.
2. No grep gates as primary proof for deleted surfaces. Behavior
   tests are the contract.
3. No dead contract fields preserved "for later." If it is
   unreachable, delete it.
4. Protected-status tests must cover the full shared constant, not
   just the statuses that triggered a specific bug.
5. Store guards must be atomic: if the status update is rejected,
   no side effects (including timeline events) should land.
6. Status docs must be present-tense and proven, not historical
   narration that overclaims.
7. Live egress paths in delivery (readiness, resume, delegation
   completion) must NOT be touched by the projection cleanup.

#### Testing Requirements

Positive:
- parent timeline publication reaches the registry store through
  `ConversationProjectionPort` → bus → processor
- startup-race delivery returns `retry_later` when egress not ready
- rendered HTML/JS shell contains source-level proof that visible
  badge text is routed through `statusLabel(...)` and maps
  `partialfailed` to "Delivery failed"
- result-report failure produces `partialfailed` fallback
- all 5 protected statuses resist late `running` overwrites
- `update_routed_task_result()` can overwrite `partialfailed`
- non-routed webhooks still fire
- non-routed recovery still binds and sends notice

Negative (behavior tests are the primary proof; source-shape checks
below are secondary direct verification, not the contract):
- no timeline rows written when status update is rejected
  (contract test — primary proof)
- no raw `partialfailed` in visible UI text (string-level
  verification in rendered HTML/JS — primary proof)

Secondary source-shape verification (confirm deletion landed, but
do not rely on these as the architectural contract):
- no `_egress_bot` or `_publish_timeline_via_dispatcher` in codebase
- no `routed_result_warning_text` in production code

Process:
- Follow slices 13A-13G in order. 13B/13C/13E are parallel-safe
  after 13A. 13D before 13F (both touch store contract tests).
  13G last.
- Run focused tests per slice.
- Run full suite after each slice.
- After each slice: check for duplicate paths, verify no new
  architectural hacks were introduced.
- If a fix requires adding another helper in `bridge.py`, stop and
  fix the abstraction instead.
- Update `status.md` only in 13G, after all prior slices are green.


### Phase 14: Ownership and Hygiene Cleanup

This phase fixes the remaining whole-rollout residuals found with
hindsight: stale fake-bot shim in bridge.py, generic helper
ownership drift back into the bridge module, shared recovery logic
still branching on a concrete surface shape, user-visible internal
rollout label, and test hygiene still relying too much on
source-shape proof.

**Architecture Decisions**:
- Keep the Phase 13 delivery fix intact: projection-only parent
  timeline publication stays on `ConversationProjectionPort`.
- Do not invent a new helper bucket or new infrastructure.
- Move generic ref/text helpers onto existing shared seams:
  Telegram/ref identity helpers in `app/identity.py`, generic text
  summarization in `app/formatting.py`.
- Recovery ref resolution must be data-shape driven:
  `conversation_ref` if present → `chat_id` → numeric
  `conversation_key` → raw `conversation_key`. No
  `event.source == "telegram"` branching in shared recovery code.
- Do not invent a new version subsystem. If no real existing version
  source can be reused cleanly, use a neutral empty value and let
  the existing UI fallback render `unknown`.
- Behavior tests are primary proof. Grep/source-shape checks are
  narrow and secondary only.

**What Not To Do**:
- Do not add a new port.
- Do not create a new generic `utils.py` or helper bucket.
- Do not leave bridge re-exports for moved helpers.
- Do not reintroduce raw surface-name branching in shared
  orchestration.
- Do not add a version env var/config/build system.
- Do not add more broad grep gates instead of behavior tests.
- Do not reopen the Phase 13 delivery projection fix.

#### Slice 14A: Remove stale fake-bot shim from bridge admission

**Problem**: `_egress_bot()` in `app/agents/bridge.py` returns
`object()` when no bot exists. `admit_registry_delivery()` passes
this fabricated bot into `dispatcher.create_egress()`. The registry
channel's `build_egress` ignores `bot` entirely. This is the same
architecture hack removed from `delivery.py` in Phase 13A,
surviving on a second ingress path.

**Fix**:
- Delete `_egress_bot()` from `bridge.py`.
- In `admit_registry_delivery(kind == "channel_input")`, stop
  passing `bot=` into `dispatcher.create_egress()` for registry
  conversation refs. The registry channel does not need it.
- Keep the registry conversation `sync_binding()` and
  `publish_timeline()` behavior — that is the channel-owned
  conversation surface and is legitimate for `channel_input` refs
  (not task refs, which were removed in Phase 10A).
- Do not touch the routed-task admission branch in this slice.

Tests:
- Positive: registry `channel_input` admission still binds and
  publishes timeline on the registry conversation ref
- Negative: dispatcher test fails if `bot` is passed in kwargs for
  registry channel-input egress construction
- Negative: legacy `surface_input`/`surface_action` kinds remain
  rejected
- Run focused tests, then full suite

**Commit: "phase-14 / 14a: remove bridge fake-bot shim"**

#### Slice 14B: Shrink bridge.py to registry-owned concerns and make recovery ref resolution generic

**Problem**: `bridge.py` exports `telegram_conversation_ref()`,
`summarize_text()`, and `conversation_key_for_ref()` to 7+ consumer
files across channels and workflows, making it a cross-cutting
utility bucket. The zero-import gate explicitly excludes it, hiding
the drift. Separately, `_event_conversation_ref()` in
`app/workflows/recovery/replay.py` branches on
`source != "telegram"` and calls `telegram_conversation_ref()`
directly — surface-specific logic in shared workflow code.

**Fix**:
- Move `telegram_conversation_ref()` to `app/identity.py`.
- Move `conversation_key_for_ref()` to `app/identity.py`.
- Move `summarize_text()` to `app/formatting.py`.
- Update all non-registry import sites so Telegram and workflow
  code stop importing from `app.agents.bridge`:
  - `app/channels/telegram/execution.py`
  - `app/channels/telegram/inbound_context.py`
  - `app/channels/telegram/normalization.py`
  - `app/channels/telegram/worker.py`
  - `app/channels/telegram/delegation_channel.py`
  - `app/channels/registry/ingress.py`
  - `app/workflows/execution/finalization.py`
  - `app/workflows/recovery/replay.py`
  - `app/agents/delivery.py`
- Add one shared data-driven ref-resolution helper on the existing
  identity/ref seam. Priority chain: `conversation_ref` first →
  `chat_id` → numeric `conversation_key` → raw `conversation_key`.
  No source-string branching.
- Rework `app/workflows/recovery/replay.py` to use that generic
  helper instead of importing `telegram_conversation_ref` and
  branching on `event.source`.
- Reuse the same helper from
  `app/channels/telegram/inbound_context.py` so ingress and
  recovery do not carry parallel ref-resolution logic.
- Do not leave bridge re-exports behind. Delete the bridge-owned
  copies once imports are updated.
- After relocation, `bridge.py` should contain only:
  - `qualify_registry_parent_ref()`
  - `build_registry_message_delivery()`
  - `build_registry_action_envelope()`
  - `admit_registry_delivery()`

Tests:
- Positive: recovery action prep works for current events with
  canonical `conversation_ref`
- Positive: legacy Telegram-shaped recovery payloads without
  `conversation_ref` still resolve correctly from numeric
  `conversation_key` or `chat_id`
- Positive: non-Telegram payloads resolve from explicit ref/key
  without surface-name branch
- Negative: non-registry Telegram/workflow modules no longer import
  generic helpers from `app.agents.bridge`
- Run focused tests on recovery, Telegram inbound/ref helpers, and
  touched handler flows, then full suite

**Commit: "phase-14 / 14b: extract generic helpers from bridge"**

#### Slice 14C: Remove internal rollout label from product surface

**Problem**: `AgentRuntime.requested_card()` hardcodes
`version="phase-19-foundation"` in `app/agents/runtime.py`. The
registry UI renders `bot.version` directly. Operators see an
internal migration label.

**Fix**:
- Replace `version="phase-19-foundation"` with a neutral value.
  Prefer `""` unless there is already a clean existing real version
  source in repo code that can be reused without adding new
  config/env/build machinery.
- Keep the existing UI fallback in `app/channels/registry/ui.py`
  that renders `unknown` when `bot.version` is empty.
- Do not invent `BOT_VERSION`, a new config field, or a version
  subsystem in this slice.

Tests:
- Positive: requested card no longer emits `phase-19-foundation`
- Positive: blank version still renders as `unknown` on registry
  detail surface
- Secondary direct check only: no `phase-19-foundation` marker
  remains in production code after the runtime field is fixed
- Run focused tests, then full suite

**Commit: "phase-14 / 14c: remove internal agent version label"**

#### Slice 14D: Rebalance guardrails toward behavior-level proof

**Problem**: Some guardrails still prove source shape more than
real behavior. The zero-import gate excludes `bridge.py` entirely,
hiding exactly the stale seams this phase fixes. Static HTML/JS
source checks are used as sole proof of user-visible behavior.

**Fix**:
- Keep the new behavior tests from 14A-14C as the primary
  guardrails.
- If adding source-shape checks, keep them narrow and secondary:
  - no `_egress_bot(` in `bridge.py`
  - no non-registry Telegram/workflow modules importing
    `telegram_conversation_ref`, `conversation_key_for_ref`, or
    `summarize_text` from `app.agents.bridge`
- Do not add another broad token-scan suite.
- Do not treat static HTML/JS source checks as the only proof of
  user-visible behavior if a behavior seam already exists.

Tests:
- Bridge admission behavior test is primary oracle for shim removal
- Recovery behavior tests are primary oracle for surface-neutral
  ref resolution
- Requested-card/UI tests are primary oracle for version leak fix
- Any new grep checks are only secondary
- Run focused tests, then full suite

**Commit: "phase-14 / 14d: harden behavior-level guardrails"**

#### Slice 14E: Status and closeout

- After each completed slice, update `status.md` with the real
  completed work and actual test results.
- After 14D, update the current state and slice log for Phase 14.
- Do not mark the phase complete until the final full-suite rerun
  is green.

Tests:
- full suite

**Commit: "phase-14 / 14e: update status and close ownership
cleanup"**

### Phase 14 Sequencing

Strictly sequential: 14A → 14B → 14C → 14D → 14E.

- 14A removes the live stale shim first.
- 14B fixes the deeper ownership drift and shared recovery
  fallback. Depends on 14A (bridge clean before relocation).
- 14C closes the user-visible internal label leak.
- 14D hardens the test oracles after the code shape is correct.
  Depends on 14B/14C.
- 14E closes docs only after the runtime/test state is green.

### Phase 14 Exit Gates

- `_egress_bot()` deleted from `app/agents/bridge.py`
- Registry `channel_input` admission does not pass `bot` in egress
  kwargs
- Registry `channel_input` admission still produces bind/timeline
  side effects on registry conversation refs
- Non-registry Telegram/workflow code no longer imports generic
  helpers from `app.agents.bridge`
- `summarize_text()` relocated to `app/formatting.py`
- `telegram_conversation_ref()` relocated to `app/identity.py`
- `conversation_key_for_ref()` relocated to `app/identity.py`
- No bridge re-exports left behind for moved helpers
- Shared recovery ref resolution does not branch on raw `source`
- One data-driven ref-resolution helper is used by both recovery and
  inbound/ref resolution code
- `AgentRuntime.requested_card().version` has no internal rollout
  marker
- Registry UI falls back to `unknown` for blank bot version
- Behavior tests prove the bridge, recovery, and version contracts
- Any new grep/source checks are narrow and secondary only
- Full suite passes after every slice and at final closeout

### Phase 14 Execution Prompt

Implement Phase 14: bridge ownership and guardrail cleanup for
`telegram-agent-bot`.

#### Before Writing Code, Read

- `PLAN-control-plane-bus.md`
- `status.md`
- `CLAUDE.md` (backup)
- `AGENTS.md` (backup)
- `SKILLS.md` (backup)
- `app/agents/bridge.py`
- `app/identity.py`
- `app/formatting.py`
- `app/workflows/recovery/replay.py`
- `app/channels/telegram/inbound_context.py`
- `app/channels/telegram/normalization.py`
- `app/channels/telegram/execution.py`
- `app/channels/telegram/worker.py`
- `app/channels/telegram/delegation_channel.py`
- `app/channels/registry/ingress.py`
- `app/workflows/execution/finalization.py`
- `app/agents/delivery.py`
- `app/agents/runtime.py`
- `app/channels/registry/ui.py`
- `tests/test_agents.py`
- `tests/test_worker_workflows.py`
- `tests/test_workitem_integration.py`
- `tests/test_zero_import_gates.py`
- `tests/test_registry_service.py`

#### Problem to Fix

The main rollout is complete, but residual seams repeat the same
earlier mistake pattern:
- `bridge.py` still fabricates bot presence for registry
  `channel_input` admission even though registry egress does not
  require a bot
- generic helpers still live in `bridge.py` and are imported by
  Telegram and workflow code
- shared recovery code still contains Telegram-specific ref
  reconstruction logic
- `AgentRuntime` still leaks an internal rollout marker as bot
  version
- some guardrails still prove source shape more than real behavior

#### Required Outcomes

- Delete `_egress_bot()` from `bridge.py`.
- Registry `channel_input` admission must not pass a fabricated
  bot into `dispatcher.create_egress()`.
- Keep `channel_input` bind/timeline behavior for registry
  conversation refs; do not rework this into a new direct-port
  path.
- Move `telegram_conversation_ref()` and
  `conversation_key_for_ref()` onto the existing identity/ref seam.
- Move `summarize_text()` onto an existing shared text-formatting
  seam.
- Remove non-registry Telegram/workflow imports from
  `app.agents.bridge`.
- Replace shared recovery source-string branching with a
  data-driven ref-resolution helper based on
  `conversation_ref`/`chat_id`/`conversation_key`.
- Remove `version="phase-19-foundation"` from
  `AgentRuntime.requested_card()`.
- If no real existing version source can be reused cleanly, use
  `""` and rely on the existing UI fallback to show `unknown`.
- Add behavior-first tests for all of the above.
- Treat any grep/source-shape checks as secondary only.

#### Hard Rules (Phase 14)

1. `bridge.py` is a registry-delivery admission module, not a
   utility bucket.
2. No fake bot `object()` anywhere.
3. Shared workflow code must not branch on channel source strings.
4. No internal rollout markers in user-visible fields.
5. Behavior tests are primary proof. Grep/source-shape checks are
   secondary.
6. Do not add a new module, port, version system, or helper bucket.
7. Extend existing seams: `app/identity.py`, `app/formatting.py`.
8. Do not leave bridge re-export shims behind.

#### Execution Order

14A → 14B → 14C → 14D → 14E. Strictly sequential.

#### Testing Requirements

After each slice:
- write/update meaningful positive and negative tests
- run focused tests for touched seams
- run the full suite
- review deeply
- update `status.md`
- commit

Required behavior tests:
- registry `channel_input` admission still binds/publishes timeline
  but does not pass `bot` in dispatcher egress kwargs
- recovery replay prep works for: current events with canonical
  `conversation_ref`; legacy Telegram events with numeric
  `conversation_key`/`chat_id`; non-Telegram events with raw
  `conversation_key`
- `requested_card()` no longer emits `phase-19-foundation`
- registry detail surface falls back to `unknown` for blank version

Any new grep/source checks must be narrow:
- no `_egress_bot` in bridge
- no Telegram/workflow imports of generic helpers from
  `app.agents.bridge`

## Phase 15: Invariant-First Seam Closure

### Why This Phase Exists

Phases 1-14 fixed paths. Phase 15 closes invariants.

The recurring failure mode across earlier phases was:

1. find one bad path
2. fix that path
3. add tests around that path
4. declare the slice done
5. later discover the same assumption in a sibling helper, a
   second ingress path, a fallback branch, a UI seam, or a test
   that only proved source shape

Phase 15 does not treat "main path is green" as closure. A slice is
closed only when the invariant is stated, the owning seam has a
direct contract test, sibling paths are audited, and product/status
language does not overclaim what is actually proven.

### Phase 15 Process Rules

Every slice in this phase must follow this structure:

1. state the invariant in one sentence
2. enumerate every seam that can violate it:
   helpers, builders, ingress paths, delivery paths, recovery paths,
   UI/product surfaces, tests, docs/status claims
3. search for the smell, not just the symbol:
   fake objects, hardcoded prefixes, raw `source == "telegram"`,
   rollout markers, static assertions for dynamic behavior
4. add one contract test at the ownership seam
5. add narrow caller-level regression tests on live paths
6. do a "same bug, different file" pass before closing
7. treat grep/source-shape checks as secondary tripwires only

### Phase 15 Architecture Decisions

- No new infrastructure, ports, modules, or abstractions
- Extend existing seams only:
  - `app/channels/registry/refs.py`
  - `app/approvals.py`
  - `app/channels/registry/http.py`
- Behavior tests are primary proof
- Source-shape checks are secondary only
- Product-visible text must not contain stale channel-specific names,
  internal rollout markers, or internal vocabulary
- The existing static HTML/JS shell checks for registry UI remain a
  known limitation. Do not add a JS runner or browser harness in this
  phase.

### Invariant 1: Already-qualified conversation refs pass through unchanged

**Statement**: Any conversation ref already qualified by a channel
(contains `:`) must not be re-wrapped by registry qualification.
Only bare unqualified IDs may be wrapped as
`registry:{registry_id}:conversation:{id}`.

**Owning seam**:
- `qualify_registry_conversation_ref()` in
  `app/channels/registry/refs.py`

**Every place that can violate it**:
- `qualify_registry_conversation_ref()` itself
- `qualify_registry_parent_ref()` in `app/agents/bridge.py`
- `admit_registry_delivery(kind="channel_input")` in
  `app/agents/bridge.py`
- `handle_registry_delivery(kind="channel_action")` in
  `app/agents/delivery.py`
- `handle_registry_delivery(kind="routed_result")` in
  `app/agents/delivery.py`
- any helper or test that encodes a hardcoded
  `telegram:` / `registry:` pass-through list

**Fix**:
- Replace the hardcoded prefix list in
  `qualify_registry_conversation_ref()` with this rule:
  - empty -> `""`
  - valid registry ref -> passthrough
  - any ref containing `:` -> passthrough
  - otherwise -> wrap as registry conversation ref
- Preferred shape:

```python
def qualify_registry_conversation_ref(registry_id: str, conversation_ref: str) -> str:
    if not conversation_ref:
        return ""
    if parse_registry_ref(conversation_ref) is not None:
        return conversation_ref
    if ":" in conversation_ref:
        return conversation_ref
    return registry_conversation_ref(registry_id, conversation_ref)
```

**Contract notes**:
- This helper now treats `:` as the generic "already-qualified"
  marker.
- Bare external conversation IDs are assumed not to contain `:`.
  If the product ever needs opaque bare IDs containing `:`, that
  must become an explicit payload distinction between bare external
  IDs and channel-qualified refs, not more heuristics in this helper.

**Contract tests**:
- Add a dedicated ref-helper contract test file:
  - `tests/test_registry_refs.py`
- Required tests:
  - bare id -> qualified registry conversation ref
  - empty -> empty
  - qualified Telegram ref -> passthrough
  - qualified registry conversation ref -> passthrough
  - qualified registry task ref -> passthrough
  - qualified future-surface ref such as `slack:eng:C0123ABC` ->
    passthrough
  - another qualified future-surface ref such as
    `whatsapp:biz:+1234567890` -> passthrough
  - `parse_registry_ref()` handles conversation refs correctly
  - `parse_registry_ref()` handles task refs correctly
  - `parse_registry_ref()` returns `None` for non-registry refs and
    bare ids
  - `binding_external_id_for_ref()` returns parsed external ids and
    passes through unknown refs unchanged

**Caller regression tests**:
- In `tests/test_agents.py`, add a `channel_action` case proving a
  qualified future-surface ref such as `slack:eng:12345` reaches the
  registry semantic-action path unchanged
- In `tests/test_agents.py`, add a `routed_result` case proving a
  qualified future-surface parent ref reaches the dispatcher
  readiness/handling path unchanged

**Same bug, different file pass**:
- After the code change, grep for hardcoded
  `startswith("telegram:")` and `startswith("registry:")` in
  qualification/normalization helpers and remove any stale
  pass-through lists that should follow the same generic rule

**Commit**:
- `phase-15 / 15a: generic ref qualification and contract tests`

### Invariant 2: Shared execution/data-shaping code does not embed stale channel names

**Statement**: Prompt text, API metadata, and shared data-shaping
helpers must not embed concrete channel names like "Telegram" unless
the code is owned by a Telegram-local surface seam under
`app/channels/telegram/`.

**Owning seams**:
- `build_preflight_prompt()` in `app/approvals.py`
- FastAPI app title in `app/channels/registry/http.py`

**Every place that can violate it**:
- `build_preflight_prompt()` in `app/approvals.py`
- shared execution call site in `app/workflows/execution/requests.py`
- registry API app metadata in `app/channels/registry/http.py`
- any shared/generic module outside `app/channels/telegram/` still
  containing stale `Telegram` branding or wording

**Fix**:
- Change the preflight prompt in `app/approvals.py` from
  `"a Telegram bridge that runs {provider_name} CLI"` to neutral
  wording such as:
  - `"a bot that runs {provider_name} CLI"`
- Change the registry FastAPI app title from
  `"Telegram Agent Registry"` to `"Agent Registry"`
- Keep Telegram-local wording untouched inside
  `app/channels/telegram/` unless it is itself stale or internal

**Contract / behavior tests**:
- In `tests/test_approvals.py`:
  - prompt still includes the required sections
  - prompt still includes the provider name
  - prompt includes user request
  - prompt does not contain `Telegram` or `telegram`
- In `tests/test_registry_service.py`:
  - assert `/openapi.json` reports `info.title == "Agent Registry"`

**Same bug, different file pass**:
- Grep `app/` excluding `app/channels/telegram/` for
  `[Tt]elegram`
- Fix any small stale shared/product references found in the same
  slice
- Also grep `app/` and adjacent product surfaces for
  `phase-` / `foundation` rollout markers and remove any residual
  production hits found in this sweep

**Commit**:
- `phase-15 / 15b: remove stale channel names from shared prompts and api title`

### Invariant 3: Helper seams get direct contract tests, not only incidental caller coverage

**Statement**: Any helper enforcing a data invariant must have a
direct contract test at the owning seam, not only incidental exercise
through callers.

**Application in Phase 15**:
- `qualify_registry_conversation_ref()` -> direct contract tests in
  `tests/test_registry_refs.py`
- `parse_registry_ref()` -> direct contract tests in
  `tests/test_registry_refs.py`

**Already acknowledged limitation**:
- Registry UI shell tests in `tests/test_registry_service.py`
  inspect static HTML/JS source. They do not prove browser-executed
  DOM behavior.
- Accept that limitation in this phase. Do not add a JS test runner
  or browser automation.
- Do not overclaim those static tests as proof of rendered DOM
  behavior in status/docs.

### Slice 15C: Closeout and process guard

- Update `status.md` only after 15A and 15B are complete and the
  full suite rerun is green
- Add a short closeout note to the status log describing this phase
  as invariant closure, not path cleanup
- Re-run the repo sweep for:
  - hardcoded qualification prefix lists
  - stale `Telegram` wording outside Telegram-local code
  - `phase-` / `foundation` markers in production code
- Record accepted limitations honestly:
  - registry UI shell tests are still static-shell checks, not
    browser-rendered DOM checks

**Commit**:
- `phase-15 / 15c: close invariant sweep and update status`

### Phase 15 Sequencing

Strictly sequential: 15A → 15B → 15C.

- 15A closes the ref-qualification invariant and adds contract
  tests at the owning seam plus live caller regressions
- 15B removes stale channel names from shared prompts and product
  metadata
- 15C closes the sweep only after code, tests, and status all match
  the real runtime state

### Phase 15 Exit Gates

- `qualify_registry_conversation_ref()` uses the generic
  already-qualified rule, not a hardcoded prefix list
- Contract tests prove:
  - bare id -> qualified registry conversation ref
  - empty -> empty
  - qualified Telegram ref -> passthrough
  - qualified registry conversation ref -> passthrough
  - qualified registry task ref -> passthrough
  - qualified future-surface refs -> passthrough
- Contract tests for `parse_registry_ref()` cover conversation,
  task, non-registry, and bare-id inputs
- Caller regression tests prove qualified future-surface refs stay
  unchanged through `channel_action` and `routed_result` registry
  delivery paths
- `build_preflight_prompt()` contains no `Telegram` wording
- Registry API title is `Agent Registry`
- Grep sweep confirms no stale `Telegram` wording remains in shared
  code outside `app/channels/telegram/`, aside from intentionally
  product-owned documentation/comments that still accurately describe
  Telegram-local seams
- No `phase-` / `foundation` rollout markers remain in production
  code
- Behavior tests remain the primary proof
- Full suite passes after every slice and at final closeout

### What Not To Do (Phase 15)

- Do not add new infrastructure, modules, or abstractions
- Do not add a JS runner or browser automation for registry UI
  checks in this phase
- Do not add broad grep-gate suites; keep source-shape checks narrow
  and secondary only
- Do not reopen unrelated cleanup tracks
- Do not mark the phase complete if the helper contract is only
  incidentally exercised through callers

### Phase 15 Execution Prompt

Implement Phase 15: invariant-first seam closure for
`telegram-agent-bot`.

#### Before Writing Code, Read

- `PLAN-control-plane-bus.md`
- `status.md`
- `CLAUDE.md` (backup)
- `AGENTS.md` (backup)
- `SKILLS.md` (backup)
- `app/channels/registry/refs.py`
- `app/agents/bridge.py`
- `app/agents/delivery.py`
- `app/approvals.py`
- `app/channels/registry/http.py`
- `app/workflows/execution/requests.py`
- `tests/test_agents.py`
- `tests/test_registry_service.py`
- `tests/test_approvals.py`

#### Problem to Fix

Three invariants remain incompletely closed:

1. already-qualified refs are handled by a hardcoded known-surface
   list instead of a generic ownership rule
2. shared prompts and API metadata still embed stale Telegram
   language outside Telegram-local seams
3. the helper seam with the highest future-regression risk still has
   no dedicated contract test

#### Required Outcomes

- `qualify_registry_conversation_ref()` follows the generic
  already-qualified rule
- dedicated contract tests exist for
  `qualify_registry_conversation_ref()` and `parse_registry_ref()`
- live caller regression tests prove qualified future-surface refs
  remain unchanged through registry `channel_action` and
  `routed_result` handling
- `build_preflight_prompt()` contains no Telegram-specific wording
- registry API title is `Agent Registry`
- small stale Telegram references found in shared/generic code
  during the required grep sweep are fixed in the same phase
- no internal rollout markers survive in production code

#### Hard Rules (Phase 15)

1. Fix the invariant, not just the caller path.
2. Add one contract test at the owning seam.
3. Add live caller regression tests after the contract test.
4. Grep/source-shape checks are secondary only.
5. Do not add infrastructure for browser-rendered UI tests.
6. Do not overclaim static HTML/JS shell checks as DOM/runtime proof.
7. Do not leave a hardcoded surface-prefix pass-through list behind
   in a helper seam.

#### Execution Order

15A → 15B → 15C. Strictly sequential.

#### Testing Requirements

After each slice:
- write/update meaningful positive and negative tests
- run focused tests for touched seams
- run the full suite
- review deeply
- update `status.md`
- commit

Required tests:
- direct contract tests for registry ref helpers
- caller regressions for qualified future-surface refs on live
  registry delivery paths
- prompt test proving shared preflight no longer says `Telegram`
- registry API metadata test proving title is `Agent Registry`

Accepted limitation:
- registry UI shell tests remain static HTML/JS source checks in
  this phase; do not expand scope into browser-executed testing

## Phase 16: Boundary Validation and Helper-Contract Cleanup

### Why This Phase Exists

Phase 15 closed the ref-qualification invariant, but one store-boundary
default and one misleading helper contract survived review:

1. the registry bind persistence seam still defaulted missing
   `origin_channel` to `"telegram"` even though the owning
   control-plane contract requires it explicitly
2. `binding_external_id_for_ref()` has behavior that is correct for
   current registry binding flows but its name overpromises what it
   extracts for non-registry refs

This phase stays intentionally small. It closes those two seams without
opening new infrastructure or another broad cleanup track.

### Phase 16 Process Rules

Every slice in this phase must:

1. fix the owning seam, not just a caller
2. add one direct contract test where the invariant lives
3. add one live-path regression where the seam is exercised in runtime
4. keep SQLite/Postgres parity intact in the same commit
5. keep source-shape checks secondary to behavior and contract tests

### Phase 16 Architecture Decisions

- No new infrastructure, ports, or helper buckets
- Extend existing seams only:
  - `app/registry_service/store_base.py`
  - `app/registry_service/store.py`
  - `app/registry_service/store_postgres.py`
  - `app/channels/registry/http.py`
  - `app/channels/registry/refs.py`
- Validate missing bind fields at the store seam and map them cleanly
  at the raw registry HTTP edge
- Make the external-id helper contract honest by naming/documenting the
  actual behavior, not by inventing a second parallel helper

### Slice 16A: Close the bind/origin-channel invariant

**Statement**: `bind_conversation()` must not invent an
`origin_channel`. Missing or blank `origin_channel` is invalid input and
must not persist as `"telegram"` or any other implicit surface.

**Owning seams**:
- `bind_conversation()` in `app/registry_service/store.py`
- `bind_conversation()` in `app/registry_service/store_postgres.py`
- shared validation helper in `app/registry_service/store_base.py`
- raw agent HTTP bind route in `app/channels/registry/http.py`

**Fix**:
- add one shared `validated_bind_conversation_payload(...)` helper in
  `store_base.py`
- require non-empty `conversation_id` and `origin_channel`
- remove the `"telegram"` fallback from both stores
- keep title optional
- map `ValueError` from the raw registry HTTP bind endpoint to
  `HTTP 422` instead of a server error

**Contract tests**:
- direct negative store-contract coverage for:
  - missing `origin_channel`
  - blank `origin_channel`
- assert no conversation row is created on failure

**Live-path regression tests**:
- a registry HTTP bind test proving missing `origin_channel` returns
  `422` and no conversation appears in the UI listing
- keep one control-plane integration bind path green to verify the
  valid explicit-channel path still reaches the registry store

**Commit**:
- `phase-16 / 16a: close bind origin-channel invariant`

### Slice 16B: Make the external-id helper contract honest

**Statement**: The helper currently named
`binding_external_id_for_ref()` does not extract only "registry external
ids"; for non-registry refs it returns the original ref unchanged. That
behavior is correct for current registry binding flows, but the name is
misleading.

**Owning seam**:
- helper in `app/channels/registry/refs.py`

**Callers to update**:
- `app/channels/registry/channel.py`
- `app/channels/registry/egress.py`
- `app/agents/bridge.py`
- direct helper tests in `tests/test_registry_refs.py`

**Fix**:
- rename the helper to reflect the actual contract, e.g.
  `binding_external_id_for_ref()` or equivalent
- keep the current behavior:
  - registry ref -> parsed external id
  - non-registry ref -> original ref
- update direct helper tests so the behavior and the name now match

**Contract tests**:
- registry conversation ref -> parsed external id
- registry task ref -> parsed external id
- non-registry qualified ref -> original ref unchanged

**Live-path regression tests**:
- keep existing registry delivery / registry egress tests green where
  non-registry qualified refs are preserved through binding

**Commit**:
- `phase-16 / 16b: clarify registry external-id helper contract`

### Slice 16C: Closeout

- update `status.md` only after 16A and 16B are green
- re-run the sweep for:
  - implicit `"telegram"` store defaults
  - stale references to the old helper name
- re-run the full suite
- record the accepted UI static-shell limitation honestly; do not
  overclaim it as browser-rendered proof

**Commit**:
- `phase-16 / 16c: close boundary validation cleanup`

### Phase 16 Sequencing

Strictly sequential: 16A → 16B → 16C.

### Phase 16 Exit Gates

- `bind_conversation()` no longer defaults `origin_channel` to
  `"telegram"` in either backend
- missing or blank `origin_channel` is rejected directly at the store
  seam
- the raw registry HTTP bind endpoint returns `422` for invalid bind
  payloads instead of persisting an implicit surface or surfacing a
  server error
- direct contract tests cover invalid bind payloads
- the external-id helper name matches its actual behavior
- no stale references to the old helper name remain
- full suite passes after every slice and at final closeout
