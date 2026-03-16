# Architecture

This document explains the current system shape: the main components, the
boundaries between them, the key runtime contracts, and the rules changes must
preserve. It is architecture, not a changelog. Current implementation status
lives in [status.md](status.md). For setup and day-to-day use, start with
[README.md](../README.md).

Current shipped baseline: **Phase 20** runs in **Local Runtime**. The product
now includes the multi-agent registry surfaces while execution still stays
bot-local. The normal deployment is SQLite-backed with `BOT_DATABASE_URL`
unset. Postgres is a supported alternate backend for the same runtime contract
when `BOT_DATABASE_URL` is set. The registry service has its own backend
interface and selector: SQLite by default via `REGISTRY_DB_PATH`, or Postgres
via `REGISTRY_DATABASE_URL`. Shared Runtime is not part of the current product
surface.

If you only remember four things, remember these:

- normal provider-starting chat requests are admitted durably and executed by
  the worker
- credential-setup replies stay inline and off-queue
- one resolved execution context owns execution-scope truth for each request
- the registry is a control plane for visibility, delivery, and coordination;
  execution still happens inside each bot

Quick orientation:

- **Runtime matrix:** Local Runtime with SQLite is the default. Local Runtime
  with Postgres is supported. Shared Runtime is future work.
- **Bot backend interface and selector:** `app/runtime_backend.py` chooses the
  session and transport implementations. `storage.py` and `work_queue.py` stay
  backend-neutral.
- **Registry backend interface and selector:**
  `app/registry_service/backend.py` chooses the registry store
  implementation. `app/registry_service/store_base.py` defines the
  control-plane interface and contract.
- **Contract suites:** backend-neutral behavior is pinned by
  `tests/contracts/test_session_store_contract.py`,
  `tests/contracts/test_transport_store_contract.py`, and
  `tests/contracts/test_registry_store_contract.py`.
- **Primary E2E gate:** `tests/e2e/test_compose_flows.py` verifies the main
  Docker operator path.

Terminology used in this document:

- **component** = a concrete part of the system
- **boundary** = an ownership line between kinds of decisions
- **interface** = the API shape other code depends on
- **implementation** = a concrete SQLite, Postgres, Telegram, or provider-specific realization
- **contract** = the behavior and invariants that must remain true
- **seam** = used only when emphasizing a deliberate replacement point for testing or backend swapping

---

## System context (high-level)

```mermaid
flowchart LR
    U["Telegram user"] <--> TG["Telegram API"]
    OB["Operator browser"] <--> REG["Registry service<br/>directory, routing, UI"]
    WHK["Operator webhook endpoint"]

    subgraph BOT["Bot process"]
        TR["Transport"]
        WQ["Work queue"]
        SS["Session store"]
        EC["Execution context"]
        RF["Request flow"]
        PR["Providers<br/>Claude / Codex"]
        RD["Rendering"]
        AG["Agent runtime<br/>registry sync + poll"]
        WH["Completion webhook"]

        TR --> WQ
        WQ --> RF
        RF --> EC
        EC --> SS
        RF --> PR
        PR --> RD
        AG --> WQ
        WH --> WHK
    end

    TG <--> TR
    AG <--> REG
    PR --> CLI["Provider CLI process"]
```

The system has two authorities:

- the **bot runtime**, which owns durable admission, workflow state,
  provider execution, response rendering, and bot-local persistence
- the **registry service**, which owns bot discovery, routed delivery queues,
  shared conversation visibility, and the operator UI

The registry is a **delivery and visibility plane**, not an execution engine.
Registry mode adds coordination without changing where code actually runs.

### Runtime matrix

- **Local Runtime + SQLite**
  - default shipped path
  - bot runtime uses `sessions.db` and `transport.db`
  - registry service uses `REGISTRY_DB_PATH` unless configured otherwise
- **Local Runtime + Postgres**
  - supported alternate backend for the same contracts
  - bot runtime uses `BOT_DATABASE_URL`
  - registry service uses `REGISTRY_DATABASE_URL`
- **Shared Runtime**
  - not shipped
  - no execution authority is currently shared across bots

### Registry mode and degraded mode

Operating modes:

- `BOT_AGENT_MODE=registry`
  - bot enrolls, heartbeats, polls routed deliveries, and mirrors timeline
    state to the registry
- `BOT_AGENT_MODE=standalone`
  - explicit single-bot mode with no registry participation

Registry connectivity resolves to one truthful state:

- `connected`
  - discovery, delegation, and registry UI sync are working
- `degraded`
  - registry mode is configured, but the registry is currently unavailable
  - Telegram execution continues through the normal bot-local worker path
  - discovery and delegation are unavailable until connectivity returns
- `standalone`
  - registry participation is intentionally disabled

Operator surfaces must tell the truth about that state. `/doctor`, startup
output, logs, and the registry UI must never imply that delegation or shared
visibility are healthy when the runtime is degraded.

## Main Boundaries

The runtime is easiest to reason about as eight ownership boundaries. Each one
owns a kind of decision. Code should not skip across those ownership lines.

```mermaid
flowchart TB
    subgraph ROW1[" "]
        direction LR
        B1["1. Transport<br/>normalize inbound"]
        B2["2. Work queue<br/>journal, admit, recover"]
        B3["3. Session<br/>durable chat state"]
        B4["4. Execution context<br/>one resolved identity"]
    end

    subgraph ROW2[" "]
        direction LR
        B5["5. Request flow<br/>business rules"]
        B6["6. Provider<br/>run, preflight, progress"]
        B7["7. Capability<br/>skills, credentials, artifacts"]
        B8["8. Rendering<br/>Telegram-safe output"]
    end
```

### 1. Transport boundary

**Owner**

- normalize transport-shaped input into project-owned inbound types before
  business logic runs

**Main modules**

- `app/transport.py`
- `app/transports/`

**Owns**

- `InboundMessage`, `InboundCommand`, and `InboundCallback`
- `serialize_inbound()` / `deserialize_inbound()`
- `InboundEnvelope`, `ConversationIO`, `EditableMessageHandle`, and
  transport capability contracts
- the mapping from a `conversation_ref` to the right interaction surface

**Does not own**

- business-rule decisions
- durable queue semantics
- approval or retry logic

**Key guarantees**

- business logic should not depend on raw Telegram payload structure when a
  normalized type exists
- serialized inbound payload JSON is a stable runtime contract across the
  supported backends
- fresh plain-message admission and worker-owned outbound output already use
  the project-owned transport interfaces
- command and callback entrypoints still have some PTB-direct behavior; that
  limitation is explicit, not hidden

### 2. Work-queue boundary

**Owner**

- durable admission, claiming, idempotency, queued cancel, and crash recovery
  for provider-starting work

**Main modules**

- `app/work_queue.py`
- `app/worker.py`
- `app/workflows/transport_recovery.py`
- `app/workflows/results.py`

**Owns**

- `update_id` journaling
- work-item lifecycle (`queued`, `claimed`, `pending_recovery`, `done`,
  `failed`)
- fresh-vs-recovery dispatch routing
- stale-claim recovery and pending-recovery replay/discard/supersede
- transport-scoped user overrides and usage-log persistence

**Does not own**

- session mutation
- execution-context resolution
- provider invocation details
- rendering wording

**Key guarantees**

- duplicate `update_id` delivery is journaled idempotently, not reprocessed
- fresh provider work is admitted durably and atomically
- at most one fresh runnable provider-starting work item may exist per chat at
  a time
- queued fresh work may be cancelled before claim through the queue; claimed
  work is cancelled cooperatively through the worker-owned live registry
- `app/work_queue.py` is the backend-neutral owner across SQLite and Postgres

### 3. Session boundary

**Owner**

- durable, chat-scoped runtime state

**Main modules**

- `app/session_state.py`
- `app/storage.py`

**Owns**

- `SessionState`
- approval mode
- active skills and role
- project binding, file policy, model-profile override, compact-mode override
- pending approval / retry state
- awaiting credential setup state

**Does not own**

- authorization policy
- provider execution
- uploads and filesystem artifacts
- raw provider output

**Key guarantees**

- orchestration operates on typed session objects, not raw dicts
- project/settings mutation must flow through the typed session boundary
- changing project or file policy resets provider-local state and clears stale
  pending workflow state
- trust tier is resolved per request, not stored here as the source of truth

### 4. Execution-context boundary

**Owner**

- one authoritative resolved execution identity per request

**Main module**

- `app/execution_context.py`

**Owns**

- resolved working directory, allowed roots, extra dirs, file policy,
  project scope, skill set, and effective model
- the context hash used for pending validation and Codex thread reuse
- public/open execution-scope restrictions

**Does not own**

- queue admission
- provider subprocess logic
- transport rendering

**Key guarantees**

- downstream code reads execution-scope fields from
  `ResolvedExecutionContext`, never raw `session.*` or `config.*`
- approval validity, retry validity, provider thread invalidation, and
  `/session` all agree on the same resolved identity
- effective model selection resolves here, not inside providers

### 5. Request-flow boundary

**Owner**

- business-rule orchestration independent of Telegram transport details

**Main modules**

- `app/request_flow.py`
- `app/approvals.py`
- `app/workflows/pending_request.py`

**Owns**

- credential satisfaction checks
- pending approval and retry freshness classification
- denial formatting and retry permission scope
- transition legality for pending approval / retry workflow

**Does not own**

- transport normalization
- direct Telegram I/O
- provider-local subprocess details

**Key guarantees**

- credential checks use resolved active skills, not raw session state
- `classify_pending_validation()` is the authoritative freshness classifier
- `PendingRequestMachine` owns transition legality; handlers select events and
  render outcomes, but do not define the workflow rules

### 6. Provider boundary

**Owner**

- provider protocol, subprocess execution, progress mapping, and provider-local
  state updates

**Main modules**

- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`

**Owns**

- `Provider` protocol
- `PreflightContext`, `RunContext`, `RunResult`, and `ProgressSink`
- health probes and provider CLI invocation
- mapping raw CLI events to shared progress events

**Does not own**

- session or project resolution
- approval decisions
- skill discovery
- final HTML wording

**Key guarantees**

- providers receive only provider-facing contexts
- providers emit `ProgressEvent` instances rather than Telegram HTML
- reported token/cost fields in `RunResult` are best-effort and may remain zero
  when a CLI does not expose usage metadata

### 7. Capability boundary

**Owner**

- skills, credentials, managed artifact store, and registry-delivered content

**Main modules**

- `app/skills.py`
- `app/store.py`
- `app/registry.py`
- `app/skill_commands.py`

**Owns**

- skill resolution order
- immutable managed-skill object store and refs
- digest verification for downloaded artifacts
- per-user credential loading at execution time

**Does not own**

- provider invocation
- session persistence
- transport delivery

**Key guarantees**

- skill resolution is deterministic: custom > managed > built-in
- managed objects are immutable and content-addressed
- credentials are loaded only for the request user at execution time

### 8. Rendering boundary

**Owner**

- adaptation from model output to Telegram-safe user-visible output

**Main modules**

- `app/formatting.py`
- `app/summarize.py`
- `app/progress.py`

**Owns**

- shared progress-event rendering
- Markdown-to-Telegram HTML conversion
- compact mode and progressive disclosure
- raw-response ring buffer and `/raw` export behavior

**Does not own**

- provider command construction
- session or queue mutation
- access-control decisions

**Key guarantees**

- providers never build final display HTML directly
- compact/full response presentation is a rendering concern
- long responses use progressive disclosure against one stable ring-buffer slot
  format

## Main Runtime Flows

This section is the main narrative path through the system. The rest of the
document should elaborate these flows, not restate them from scratch.

### Normal request

```mermaid
flowchart LR
    U["Telegram update"]
    T["Transport normalize"]
    A["Access / trust tier"]
    Q["Journal + admit fresh work"]
    W["Worker claim"]
    X["Resolve execution context"]
    R["Request flow<br/>credential and pending rules"]
    P["Provider run / preflight"]
    O["Render + send output"]
    S["Persist session and queue state"]

    U --> T --> A --> Q --> W --> X --> R --> P --> O --> S
```

Execution order in plain language:

1. normalize the inbound update
2. authorize the user and resolve trust tier
3. handle credential-setup replies inline when setup state owns the next
   message
4. otherwise journal the update and atomically admit or reject fresh work
5. return promptly from the handler; the worker later claims runnable work
6. load typed session state in the worker-owned path
7. resolve the authoritative execution context
8. apply business rules using the resolved context
9. build provider-facing context and invoke the provider
10. render transport-safe output, persist session and delivery state, save raw
    response history, and deliver any directed artifacts

### Approval and retry

Approval and retry are the same workflow family: persist pending state, then
validate that state against the current execution identity before executing.

```mermaid
flowchart TD
    M["Incoming request<br/>approval_mode = on"]
    C["Resolve execution context"]
    PF["Provider preflight"]
    PA["Persist PendingApproval"]
    UX["User approves / rejects / retries"]
    V["classify_pending_validation()<br/>PendingRequestMachine"]
    EX["Execute request"]
    CL["Clear pending and show user-facing message"]

    M --> C --> PF --> PA --> UX --> V
    V --> EX
    V --> CL
```

Rules that must stay true:

- pending freshness is classified in one place
- stored `trust_tier` must be used when recomputing pending validity
- retry adds denial-derived permission scope; it does not invent a second
  workflow system

### Registry and delegation

Registry mode adds coordination, not remote execution.

```mermaid
flowchart LR
    ORIG["Origin bot"]
    REG["Registry service"]
    TGT["Target bot"]

    ORIG -->|"enroll / heartbeat / timeline"| REG
    ORIG -->|"submit routed task"| REG
    REG -->|"poll routed_task delivery"| TGT
    TGT -->|"execute locally through its own worker path"| TGT
    TGT -->|"publish result + timeline"| REG
    REG -->|"deliver routed_result"| ORIG
```

Delegation flow in practice:

- discovery finds candidate specialist bots in the registry
- the origin bot proposes a delegation plan and persists `PendingDelegation`
- user approval or cancellation is handled at the origin surface
- approved child tasks are submitted through the registry
- target bots execute child tasks locally through their own normal worker path
- routed results are delivered back to the origin bot and merged into the
  parent conversation

### Recovery summary

Transport recovery is specialized enough to live mostly in the appendix, but
the narrative contract is simple:

- stale claimed items are requeued as `dispatch_mode='recovery'`
- recovery work must surface replay/discard decisions to the user before
  pretending execution succeeded
- replay/discard/supersede are explicit workflow outcomes, not implicit
  cleanup

## State and Storage Model

The system has four durable state families: bot-local transport state,
bot-local session state, filesystem artifacts, and registry control-plane
state.

```mermaid
flowchart LR
    subgraph BOT["Bot local runtime"]
        TS["Transport store<br/>updates, work_items,<br/>user_access, usage_log"]
        SS["Session store<br/>SessionState and pending state"]
        FS["Filesystem<br/>uploads, raw history,<br/>managed store, credentials"]
        RS["registry_state.json<br/>runtime connectivity state"]
    end

    subgraph REG["Registry service"]
        RG["Registry store<br/>agents, deliveries,<br/>conversations, timeline_events,<br/>skills_override"]
    end

    TS --- SS
    SS --- FS
    BOT -->|"timeline / poll / routed deliveries"| REG
```

### Durable authorities

**Bot runtime**

- **transport store**
  - journaled updates
  - work-item state machine
  - queued-cancel and recovery state
  - user-access overrides
  - per-run usage history
- **session store**
  - typed chat-scoped session state
  - pending approval / retry / setup state
  - project / model / policy / compact-mode preferences
- **filesystem**
  - uploads per chat
  - raw-response ring buffer
  - managed skill objects and refs
  - encrypted credentials
  - staged helper scripts and artifacts

**Registry service**

- enrolled bot directory
- delivery queues for routed tasks and surface actions
- shared conversations and timeline events
- global skills overrides
- UI-facing search, export, and usage-summary views

### Backend interfaces and implementations

Bot runtime backends:

- selected by `app/runtime_backend.py`
- SQLite default when `BOT_DATABASE_URL` is unset
- Postgres alternate when `BOT_DATABASE_URL` is set
- `app/storage.py` and `app/work_queue.py` are the backend-neutral facades

Registry backends:

- selected by `app/registry_service/backend.py`
- SQLite default via `REGISTRY_DB_PATH`
- Postgres alternate via `REGISTRY_DATABASE_URL`
- `app/registry_service/store_base.py` defines the backend-neutral contract

### Why this split exists

- transport state and session state have different lifecycles and failure
  modes
- files and artifacts benefit from filesystem semantics and direct provider
  access
- registry state is a control-plane concern and must stay separate from
  bot-local execution authority
- the split lets the bot keep executing locally even when registry
  connectivity degrades

### Response history and progressive disclosure

The raw-response ring buffer is the single source of truth for `/raw` and
expand/collapse flows.

- `save_raw()` stores prompt + raw text in numbered slots
- `load_raw()` and `load_raw_by_slot()` resolve the latest or specific slot
- slots rotate FIFO; expired slots return “no longer available”
- rendered compact/full variants are derived views, not separate durable state

## Access and Safety Model

### User authorization

Only allowed users may interact. When open mode is enabled, users resolve to
`trusted` or `public`.

Authorization applies two layers in order:

1. a DB override fetched at the handler / transport boundary
2. the config baseline evaluated by `app/access.py`

```mermaid
flowchart TD
    REQ["Inbound request"]
    FETCH["fetch DB override<br/>via work_queue.get_user_access()"]
    OVR{"override?"}
    BLK["blocked -> deny"]
    ALW["allowed -> allow"]
    CFG["access.is_allowed_user()<br/>config baseline"]
    DENY["deny"]
    OK["allow"]

    REQ --> FETCH --> OVR
    OVR -->|"blocked"| BLK
    OVR -->|"allowed"| ALW
    OVR -->|"none"| CFG
    CFG -->|"match"| OK
    CFG -->|"no match"| DENY
```

`app/access.py` must stay a pure policy module. It must not import storage,
SQLite, Postgres, or backend selectors.

### Admin authorization

Admin access is narrower than general allowed-user access. Admin-only surfaces
manage store-backed skills and broader state inspection.

### Approval mode

Approval mode determines whether execution requires preflight plan review
before the provider is invoked.

### File, project, and model scope

Allowed roots and working scope derive from the resolved execution context:

- resolved working directory
- resolved extra dirs
- per-chat upload dir
- denial-derived retry dirs

Those roots must be computed from `ResolvedExecutionContext`, not from raw
config or raw session fields scattered across handlers.

### Public-trust enforcement

Two layers enforce public/trusted behavior:

- **execution scope**
  - forced inspect policy
  - forced public working dir
  - stripped extra dirs
  - stripped skills
  - disabled project binding
- **command availability**
  - disabled skill management for public users
  - restricted project and `/send` behavior
  - restricted model-profile surface

The execution-scope layer is stronger. Once the context is resolved, those
restrictions flow through provider context, pending validation, allowed roots,
artifact delivery, and rendering automatically.

## Stable Contracts

This section is intentionally normative. These are the surfaces the rest of
the document exists to explain.

### Interfaces That Must Stay Stable

The following contracts should change only deliberately:

- `SessionState`
- `PendingApproval` / `PendingRetry` (including stored `trust_tier`)
- `ResolvedExecutionContext`
- `PreflightContext` / `RunContext`
- `Provider` protocol and `RunResult`
- `ProgressEvent` family and `render()` contract
- serialized inbound payload JSON shape used by the durable work queue
- `check_credential_satisfaction` signature (resolved active skills)
- pending-validation contract built on `classify_pending_validation()`
- work-item state machine and `TransportRecoveryMachine` events / guards
- transport delivery semantics (`update_id` handling, fresh-admission rules,
  queued-cancel rules, recovery routing)
- managed store layout (`objects/`, `refs/`, `custom/`)
- registry store contract in `app/registry_service/store_base.py`
- ring-buffer slot format used by expand/collapse callback data

Changing these should trigger both code review and invariant-test updates.

### Execution Order Constraints

If you rework the runtime, preserve this order:

1. normalize transport
2. journal updates and enforce transport idempotency
3. handle credential-setup replies inline and off-queue when setup state owns
   the next message
4. atomically admit or reject fresh provider-starting work
5. claim runnable work from the worker-owned execution lane
6. load typed session state
7. resolve trust tier and authoritative execution context
8. apply business rules using the resolved context
9. build provider-facing context from the resolved context
10. invoke provider and map raw events to shared progress events
11. persist session and durable delivery state
12. render transport-safe output, save raw history, and deliver artifacts

The single most important architectural rule: once
`resolve_execution_context()` produces a `ResolvedExecutionContext`, all
downstream execution-scope reads come from that object. Never from raw
`session.*` or `config.*` for working directory, file policy, active skills,
extra dirs, project binding, or effective model.

### Backend parity and contract testing

The codebase has three backend-neutral persistence interfaces:

- **session store**
  - facade: `app/storage.py`
  - backends: `storage_sqlite.py`, `storage_postgres.py`
  - contract suite: `tests/contracts/test_session_store_contract.py`
- **transport store**
  - facade: `app/work_queue.py`
  - backends: `work_queue_sqlite.py`, `work_queue_postgres.py`
  - contract suite: `tests/contracts/test_transport_store_contract.py`
- **registry store**
  - contract: `app/registry_service/store_base.py`
  - backends: `RegistrySQLiteStore`, `RegistryPostgresStore`
  - contract suite: `tests/contracts/test_registry_store_contract.py`

New persistence behavior belongs behind these interfaces. New facade or
contract methods must land with both backend implementations and matching
contract-test coverage in the same change.

## Reference Appendix

The sections below are reference material. They are useful, but they are not
the primary reading path.

### Key Data Types

**SessionState**

- typed runtime representation of a chat session
- owns provider-local state, approval mode, active skills, project binding,
  model/profile overrides, compact mode, and pending/setup workflow state

**PendingApproval / PendingRetry**

- carry original requester identity, prompt, image list, context hash,
  creation time, and stored `trust_tier`
- `PendingRetry` additionally carries denial records used to derive retry
  permission scope

**ResolvedExecutionContext**

- single authoritative execution identity
- source of context hash, provider-facing working dir, effective model, file
  policy, allowed roots, and public/trusted execution-scope restrictions

**Provider contexts**

- `PreflightContext`: provider-facing planning input
- `RunContext`: provider-facing execution input
- intentionally narrower than session state

**RunResult**

- provider result carrying text, status flags, provider-state updates, denial
  records, and best-effort reported token/cost fields

**ProgressEvent**

- frozen event family rendered by the shared `progress.py` renderer

### Transport and simulator architecture

The current transport architecture deliberately separates three concerns:

1. inbound normalization
2. durable admission and worker execution
3. handler-owned Telegram UI behavior

That means the simulator is best understood as a **handler-level runtime
harness**, not a transport-port simulator.

Current simulator contract (`tests/support/conversation_simulator.py`):

- runs the real queue and worker loop
- injects via `handle_message()` / `cmd_*` directly
- exposes one ordered text-output log
- does not include markup-only edits
- does not yet inject callbacks as a first-class simulator surface
- does not yet drive ingress by delivering `InboundEnvelope` end-to-end

The remaining gap is explicit:

- unify more handler-owned outbound messaging behind `ConversationIO`
- add first-class callback injection to the simulator
- optionally move from direct handler injection to transport-level delivery
  without making PTB internals the main contract

### Transport workflow detail

`TransportRecoveryMachine` owns transition legality. Repository/store code owns
SQL, compare-and-update, races, and repository-only outcomes such as
`already_handled`.

```mermaid
stateDiagram-v2
    queued --> claimed: claim_inline / claim_worker
    claimed --> done: complete
    claimed --> failed: fail
    claimed --> pending_recovery: move_to_pending_recovery
    claimed --> queued: recover_stale_claim
    pending_recovery --> claimed: reclaim_for_replay
    pending_recovery --> done: discard_recovery
    pending_recovery --> done: supersede_recovery
```

Runtime invariants:

- `work_items.state` must be one of `queued`, `claimed`, `pending_recovery`,
  `done`, `failed`
- `dispatch_mode` must be `fresh` or `recovery`
- `claimed` rows must have `worker_id` and `claimed_at`
- at most one `claimed` row may exist per chat
- at most one fresh runnable (`queued` or `claimed`) row may exist per chat
- stale claims must requeue as `dispatch_mode='recovery'`
- queued fresh cancel must terminate the item visibly as cancelled; it must not
  silently disappear

### Testing Architecture

The suite is organized around contracts, not just features.

**Four-layer model**

1. **Pure or owner suites**
   - workflow machines, execution context, request-flow rules, providers,
     formatting, progress, and other backend-neutral contracts
2. **In-process integration**
   - real handlers, real request flow, fake Telegram doubles, fake providers,
     and real local persistence
3. **Postgres bootstrap and repository integration**
   - real Postgres, real schema bootstrap/update/doctor, real pooling
4. **E2E**
   - Compose-based operator-path validation in
     `tests/e2e/test_compose_flows.py`

**Postgres harness rules**

- Docker is required
- each pytest-xdist worker gets an isolated Postgres test DB
- schema is applied once per worker
- runtime tables are truncated between tests
- the harness never mutates dev, staging, or production databases

### Health, admin, and provider notes

**doctor.py**

- shared health orchestration for Telegram `/doctor` and CLI entry points
- covers config validation, provider health, managed-store health, stale
  session scanning, public-mode diagnostics, and transport diagnostics

**Admin views**

- reporting surfaces over current durable state such as `/admin sessions` and
  stale pending/setup visibility

**Provider notes**

- Claude is session-oriented and maps `stream-json` events inline
- Codex is thread-oriented and thread reuse depends on context hash plus boot
  ID
- providers own subprocess invocation and progress mapping, not session
  persistence or approval logic

## Deployment and dependencies

The bot’s Python dependencies live in **`requirements.txt`**. The normal
runtime path is Docker, and the same dependency set also supports host-side
debugging and tests.

- **Current runtime contract:** Local Runtime is the supported deployment mode.
  Leave `BOT_DATABASE_URL` unset for SQLite (default), or set it to a Postgres
  DSN to use Postgres as the bot-runtime backend for the same product/runtime
  contract. The app validates backend compatibility at startup.
- **Registry control-plane backend:** the registry service is separate from the
  bot runtime. Use `REGISTRY_DB_PATH` for the default SQLite control-plane
  store, or `REGISTRY_DATABASE_URL` for the Postgres control-plane store.
- **Optional Postgres workflows:** explicit repo-owned DB commands
  (`scripts/db/db_bootstrap.sh`, `scripts/db/db_update.sh`,
  `scripts/db/db_doctor.sh`) prepare and verify Postgres before the app starts
  when a Postgres DSN is configured. `./scripts/db/dev_up_postgres.sh` remains
  the fast local operator path for standing up the alternate Postgres backend.
- **Environment identity:** each bot environment has its own database, config,
  Telegram token, and app instance identity. Side-by-side dev/staging
  environments use separate databases regardless of backend choice.
- **Responsibilities are explicit:**
  1. infrastructure provides the runtime substrate for the selected mode
  2. repo-owned DB/runtime commands apply schema and validate compatibility
  3. the app validates and runs; it does not create the DB, role, or schema at
     startup
- **Primary operational model:** Dockerized bot is the main operator path.
  `./scripts/app/guided_start.sh` is the main zero-to-running path for SQLite
  Local Runtime. The canonical Compose entrypoints live under
  `infra/compose/docker-compose.yml` and `infra/compose/docker-compose.e2e.yml`.
- **Supported bot image:** the supported Docker path uses a real
  provider-enabled image built from `infra/docker/Dockerfile.bot`.
  `./scripts/provider/build_bot_image.sh` selects the provider-specific target
  from `BOT_PROVIDER`. A stub-provider image exists only for test/dev smoke.
- **Provider authentication contract:** provider auth state is not baked into
  the image. Login runs inside the same bot image, persists in a dedicated
  Docker volume mounted at `/home/bot`, and startup plus `/doctor` validate
  runtime/auth health before treating the bot as ready.
- **Host-run bot:** still supported as a secondary fallback/debug path with the
  same Local Runtime contract above the storage boundary.
- **Later environments:** staging and production may still choose Local Runtime
  while Shared Runtime remains future work.

See [README.md](../README.md) for the operator path, and [status.md](status.md)
for current shipped-state truth.
