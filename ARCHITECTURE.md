# Architecture

This document describes the current system shape in code: the deployment CLI,
the application/runtime, the registry service and SPA, and the shared SDK that
binds them together.

## System Map

Octopus is four cooperating systems:

| System | Owns |
|---|---|
| `./octopus` | local deployment state, lifecycle, provider auth, workspaces, local registry operations |
| Bot application | runtime composition, channels, providers, registry runtime loops, workflows, control-plane adapters |
| Registry service | agent/resource APIs, websocket realtime API, operator SPA, registry persistence/query model |
| `octopus_sdk/` | shared contracts, wire models, runtime orchestration, and protocol-based composition seams |

```mermaid
flowchart LR
    Operator["Operator"] --> CLI["./octopus"]
    Browser["Operator Browser"] --> UI["Registry SPA /ui"]
    Telegram["Telegram"] --> Bot["Bot application<br/>python -m app.main"]

    CLI --> Deploy[".deploy/ + Docker/Compose"]
    Deploy --> Bot
    Deploy --> Registry["Registry service<br/>FastAPI + websocket + SPA"]

    Bot --> Provider["Claude / Codex"]
    Bot <--> Registry
    UI --> Registry
```

### Layering

The system map above shows running systems. The layering view below is narrower:
it shows code ownership boundaries and the main dependency direction between
`app/`, `octopus_sdk/`, and the registry service.

```mermaid
flowchart TB
    CLI["./octopus"]
    UI["Registry SPA"]
    Main["app/main"]
    Telegram["Telegram transport"]
    Slack["Slack transport (later)"]
    Providers["Providers"]
    Workflows["Workflows / adapters"]
    SDK["octopus_sdk"]
    Api["Registry API"]
    Store["Registry store"]

    CLI --> Main
    UI --> Api
    Main --> Api
    Api --> Store

    Main --> Telegram
    Main --> Slack
    Main --> Providers
    Main --> Workflows

    Telegram --> Api
    Slack --> Api
    Providers --> SDK
    Workflows --> SDK
```

## Deployment And Process Model

`./octopus` is a thin shell entrypoint that delegates to the Python CLI in
`app/octopus_cli/`. It owns local deployment state under `.deploy/` and
manages containers, workspaces, provider auth, registry lifecycle, and bot
connectivity.

Important state boundaries:

| Location | Owner | Purpose |
|---|---|---|
| `.deploy/bots/<slug>/.env` | CLI/operator | deployment-time bot config |
| `.deploy/registry/.env` | CLI/operator | local registry deployment config |
| `BOT_DATA_DIR/agent/bot_identity.json` | runtime | stable local bot identity |
| `BOT_DATA_DIR/agent/registries/<registry_id>.json` | runtime | live per-registry connection state |

For local operations against a persistent `~/octopus` checkout, the repo also
ships two helper scripts under `scripts/ops/`:

- `backup_octopus_deploy.sh` copies `~/octopus/.deploy` into a timestamped
  backup directory
- `refresh_octopus_with_backup.sh` wraps the live refresh flow:
  backup `.deploy`, `git pull --ff-only`, run `./octopus clean`, restore the
  saved `.deploy`, start the registry/bots again, reconnect them, and verify
  registry health plus image freshness

These helpers are intentionally deployment-state tools; they do not replace the
`./octopus` CLI itself.

The bot runtime supports multiple registries in config, but the current CLI is
local-registry-first: local registry lifecycle and connect/disconnect are
first-class, while remote registry records are supported by runtime/config
without the same interactive CLI coverage.

### Process Axes

The application runs under three main axes:

| Config | Values | Effect |
|---|---|---|
| `BOT_AGENT_MODE` | `standalone`, `registry` | whether registry runtime/registry-connected flows participate |
| `BOT_RUNTIME_MODE` | `local`, `shared` | single-process runtime vs split shared runtime |
| `BOT_PROCESS_ROLE` | `all`, `webhook`, `worker` | which responsibilities this process owns |

The SDK still models both standalone and registry-connected runtimes, but the
shipped Telegram implementation in this repo is stricter:

- Telegram runs in `BOT_AGENT_MODE=registry`
- startup requires configured registry connections
- those connections must collectively provide full participant coverage across
  `channel` and `coordination`

`app/main.py` is now a thin runnable entrypoint. Profile validation and runtime
composition live in `app/runtime/process.py`.

## SDK Surface

`octopus_sdk/` is the shared import surface for contracts and reusable runtime
logic. Import direction is one-way:

- `app/` may import `octopus_sdk/`
- `octopus_sdk/` must not import `app/`

### Registry Contracts

| Module | Owns |
|---|---|
| `octopus_sdk.registry.client` | async registry HTTP client |
| `octopus_sdk.registry.models` | agent enrollment, discovery, conversation create, routed-task, and timeline wire models |
| `octopus_sdk.events` | stored conversation event contracts and metadata schemas |
| `octopus_sdk.realtime` | websocket envelopes, collection invalidation topics, and progress payloads |

The registry server and bot runtime both consume these contracts. The registry
server does not define its own private wire types for these surfaces.

### Unified Transport, Runtime, Participant, And Authority Contracts

| Module | Owns |
|---|---|
| `octopus_sdk.transport` | unified bot-side transport contract: `TransportDescriptor`, `TransportImplementation`, `TransportEgress`, `BotRuntimeHandle` |
| `octopus_sdk.inbound_types` | canonical `InboundEnvelope` taxonomy for normalized inbound work |
| `octopus_sdk.bot_runtime` | provider-dispatch runtime collaborators and typed runtime support ports |
| `octopus_sdk.identity` | actor/conversation key parsing, Telegram ref helpers, stable bot identity helpers |
| `octopus_sdk.registry_participant` | bot-side registry participation: enrollment, discovery, mirroring, coordination, and health |
| `octopus_sdk.registry.authority_client` | bot-to-registry authority client contract |
| `octopus_sdk.registry_authority` | server-side registry authority contracts |
| `octopus_sdk.conversation_projection` | shared conversation projection port used by participant/runtime code |
| `octopus_sdk.task_routing` | routed-task submission/status/result port |
| `octopus_sdk.agent_directory` | discovery and authority-resolution port |
| `octopus_sdk.health_publication` | live runtime health publication port |
| `octopus_sdk.task_protocol` | routed-task lifecycle states, transitions, and idempotent transition validation |
| `octopus_sdk.providers` | provider protocol and execution result/tool models |

The architecture is intentionally split into three first-class SDK surfaces:

- **primary transport**
  - how a bot talks to users
  - ingress, egress, binding, refs, identity, lifecycle
- **registry participant**
  - how a bot joins the shared control plane
  - enrollment, discovery, mirroring, typed coordination, task flow, health
- **registry authority**
  - the server-side control plane implementation
  - conversations, tasks, directory, health, mirroring, enrollment, delivery

The registry server and bot runtime both consume SDK-owned contracts. The
registry server does not define a second private wire model for participant
flows, and transport implementations do not define their own coordination
contract outside the SDK.

Current ref families remain:

| Ref kind | Format |
|---|---|
| Telegram conversation | `telegram:<bot_id>:<chat_id>` |
| Registry conversation | `registry:<registry_id>:conversation:<conversation_id>` |
| Registry task | `registry:<registry_id>:task:<routed_task_id>` |

Unknown or malformed refs fail fast.

### Structured Coordination And Task Protocol

The current coordination model has two explicit lanes:

- **content lane**
  - user/operator messages
  - provider reasoning
  - bot replies
- **coordination lane**
  - typed conversation actions
  - delegation proposals and approvals
  - routed-task submission, status, and result updates

The coordination lane is no longer based on provider-emitted XML. Registry and
Telegram coordination go through typed SDK and registry contracts.

Current typed action family in `octopus_sdk.registry.models`:

- `approve`
- `reject`
- `cancel_conversation`
- `retry_allow`
- `retry_skip`
- `recovery_discard`
- `recovery_replay`
- `direct_assign`
- `delegate_tasks`
- `approve_delegation`
- `cancel_delegation`
- `cancel_task`
- `retry_task`

Current routed-task lifecycle in `octopus_sdk.task_protocol`:

- `queued`
- `leased`
- `running`
- `completed`
- `failed`
- `cancelled`
- `timed_out`

Every routed-task transition carries a `transition_id`, and registry stores use
that together with the current task snapshot to enforce transition legality and
idempotency.

### Example: Adding A Slack Transport

Slack is not implemented in this repo today, but the current SDK is structured
so a new transport can be added without importing `app.main`.

A realistic Slack implementation would use [Bolt for Python](https://docs.slack.dev/tools/bolt-python/)
as the Slack-facing library. Slack documents Bolt as its Python framework for
building Slack apps, supports framework adapters for production HTTP handling,
and also supports [Socket Mode](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode)
when Slack should deliver events over a websocket instead of an inbound HTTP
endpoint.

The resulting runtime shape would look like this:

```mermaid
flowchart TB
    Slack["Slack"]

    subgraph Bot["Slack bot process"]
        direction TB
        Bolt["Bolt for Python"]
        Transport["Slack transport<br/>octopus_sdk.transport"]
        Runtime["Bot runtime<br/>octopus_sdk.bot_runtime"]
        Participant["Registry participant<br/>octopus_sdk.registry_participant"]
    end

    Provider["Claude / Codex"]
    Registry["Registry service"]

    Slack <--> Bolt
    Bolt <--> Transport
    Transport <--> Runtime
    Runtime <--> Provider
    Runtime <--> Participant
    Participant <--> Registry
```

The transport split would look like this:

- Slack/Bolt owns Slack auth, event delivery, signatures or Socket Mode, and Slack API calls
- `octopus_sdk.transport` owns the transport contract: descriptor, lifecycle, refs, identity, and egress
- `octopus_sdk.inbound_types` owns the normalized inbound envelope contract
- `octopus_sdk.bot_runtime` owns provider-dispatch collaborators and execution plumbing
- `octopus_sdk.registry_participant` owns optional registry participation for discovery, mirroring, and typed coordination

In practice a Slack transport would:

1. implement `TransportImplementation` around Bolt listeners and Slack API egress
2. normalize Slack events into canonical `InboundEnvelope` values
3. define a stable Slack ref family and identity resolver
4. provide bot-runtime collaborator implementations for session, guidance, and artifact handling
5. optionally compose the full `RegistryParticipantImplementation` to join the shared registry control plane

Once implemented, the runtime behavior would look like this:

```mermaid
sequenceDiagram
    participant S as Slack
    participant Bolt as Bolt
    participant Transport as Slack transport
    participant Runtime as SDK runtime
    participant Participant as Registry participant
    participant Provider as Provider
    participant Registry as Registry service

    Note over Bolt,Participant: Slack bot process
    S->>Bolt: events / commands
    Bolt->>Transport: normalize inbound
    Transport->>Runtime: identity + input
    Runtime->>Provider: run / preflight
    Runtime->>Transport: reply / actions / artifacts
    Transport->>Bolt: outbound requests
    Bolt->>S: messages / files / updates
    Runtime->>Participant: publish, search, route
    Participant->>Registry: authority client calls
```

That keeps Slack-specific code in `app/channels/slack/` while reusing the SDK
for transport behavior, provider dispatch, approvals, event publication,
session state, and registry connectivity.

## Application Systems

The repo's runnable application lives under `app/` and composes the SDK with
concrete implementations.

### Composition Root

`app/main.py` is now a thin launcher. `app/runtime/process.py` performs the
current startup sequence:

1. load config
2. validate the required implementation profile
3. construct provider
4. initialize content and credential stores
5. create shared control-plane and participant services
6. register primary transports and registry delivery transport
7. start dispatcher-managed ingress plus worker/runtime components for the selected mode

### Main Subsystems

| Subsystem | Package | Owns |
|---|---|---|
| Telegram transport | `app/channels/telegram` | Telegram transport implementation, presenters, Telegram ingress normalization, and Telegram-specific rendering |
| Registry channels/service | `app/channels/registry` | registry HTTP routes, websocket manager, SPA egress, registry conversation/task transport implementations, registry delivery transport |
| Agent runtime | `app/agents` | registry enrollment/state loops, delivery handling, delegation helpers, registry authority clients |
| Runtime composition | `app/runtime` | profile validation, shared service composition, participant runtime, dispatcher, admission, runtime health |
| Providers | `app/providers` | Codex and Claude implementations over the SDK provider protocol |
| Workflows | `app/workflows` | approvals, recovery, guidance, runtime skills, conversation/settings workflows |
| Control plane | `app/control_plane` | bus, adapters, processor runner, authority directory |
| Registry persistence | `app/registry_service` | typed authority facade plus agent/event/task/approval/guidance/query stores |

### Telegram As An SDK Consumer

Telegram is the reference implementation of the unified model in this repo:

- `app/channels/telegram/channel.py` implements the primary transport contract
- `app/runtime/registry_participant.py` provides the full registry participant surface
- `app/runtime/process.py` composes both into the shipped Telegram runtime profile
- Telegram-specific presentation code stays in transport/presenter modules rather than owning registry policy

### Registry Bot-Side As An SDK Consumer

Registry conversation/task channels in `app/channels/registry/channel.py` and
the registry delivery transport in `app/channels/registry/delivery_transport.py`
also consume the same SDK transport and participant contracts. They build
registry-scoped egress and route projection/routing/health through bus-backed
services from `app/runtime/services.py`.

## Registry Service And Operator UI

The registry service spans:

- `app/channels/registry/`
- `app/registry_service/`
- `ui/`

### API Surfaces

| Surface | Purpose |
|---|---|
| Agent API | enroll/register/heartbeat/delivery/search/task flows for bots and processor/runtime code |
| Resource API | `/v1/summary`, `/v1/agents`, `/v1/conversations`, `/v1/tasks`, `/v1/approvals`, `/v1/capabilities`, `/v1/usage`, skill catalog, guidance |
| Realtime API | `WS /v1/ws` for typed `event`, `heartbeat`, `progress`, and `invalidate` envelopes |
| Operator SPA | browser UI under `/ui` |

Important current behavior:

- list endpoints use cursor/limit/has_more pagination
- agent list supports server-side `q` and `state`
- conversation list supports server-side `q` and `status`
- task list supports server-side `status`
- usage is derived from provider response events, and delegated child usage can
  roll into the parent conversation when routed-task results carry usage data
- conversation detail can submit typed actions through `POST /v1/conversations/{id}/actions`
- direct operator routing and delegated coordination share the same action
  surface and backend state model

### Realtime Model

The websocket manager in `app/channels/registry/ws.py` uses typed SDK
envelopes from `octopus_sdk.realtime` and pushes explicit topics, not wildcard
subscriptions.

Current topic families:

- `conversation:<id>`
- `agent:<id>`
- collection topics such as `summary`, `agents`, `conversations`, `tasks`, `approvals`, `usage`

Current realtime envelope types:

- `event`
- `heartbeat`
- `progress`
- `invalidate`

The SPA is a vanilla JS application in `ui/` and subscribes to explicit topics
through `ui/js/ws.js`. Dashboard and list refreshes are driven by invalidation
topics; conversation detail also renders progress updates.

### SPA Shell And Route Model

The registry UI is a route-driven operator console:

- one left rail / drawer shell
- one main work surface per route
- shared summary rails, segmented controls, list rows, task cards, and compact
  metadata rows across desktop and mobile

Core browser routes today:

| Route | Main purpose |
|---|---|
| `/ui` | dashboard summary + attention lists |
| `/ui/approvals` | pending approval queue |
| `/ui/agents` | agent roster with direct open-conversation actions |
| `/ui/agents/{id}` | agent overview, workers, inline conversations |
| `/ui/conversations` | quick start plus active thread roster |
| `/ui/conversations/{id}` | conversation workspace with Conversation / Tasks / Full activity |
| `/ui/tasks` | routed-task queue |
| `/ui/usage` | per-conversation usage rollups |

Important SPA primitives:

- `ui/js/helpers/ui.js`
  - `UI.reconcileChildren(...)` wraps `morphdom` for keyed DOM reconciliation
  - `UI.bindSegmentedControlKeyboard(...)` centralizes arrow-key navigation for
    segmented controls
- `Fuse.js` is used for `@target` suggestion ranking in conversation detail
- theme state is owned in `ui/js/app.js` and applies to both light and dark
  modes without a separate mobile app

The current component split matches operator jobs rather than raw resource
types:

- dashboard: summary + immediate follow-up
- conversations: start/reopen work and inspect active threads
- conversation detail: human conversation, routed work, and diagnostics in one
  workspace
- tasks: cross-conversation routed-task queue
- agents: health and direct entry into work
- usage: cost/token accounting tied back to conversations

Conversation detail in `ui/js/components/conversation-detail.js` is also the
main operator entrypoint for structured coordination today:

- normal conversation messages still go through `POST /v1/conversations/{id}/messages`
- a leading selector such as `@m2`, `@cap:review`, or `@role:reviewer` routes
  through typed `direct_assign` actions from the same main composer
- the default `Conversation` tab stays human-first while still surfacing
  delegation milestones and terminal task status events
- the conversation header uses operator-facing metadata (`With`, `Assigned to`,
  `Started in`) while demoting raw refs into a copy action and turning event
  counts into an `Activity (n)` action
- the `Tasks` tab renders routed work as first-class task objects with task
  actions
- `Full activity` keeps the full stored event stream for diagnostics

## Main Interaction Flows

### Telegram Request Execution

This is the normal inbound execution path for a Telegram-originated request.

```mermaid
sequenceDiagram
    participant U as User
    participant T as Telegram
    participant X as Runtime
    participant P as Provider
    participant S as Event sink
    participant O as Outbound

    U->>T: message
    T->>X: normalized work
    X->>P: run / preflight
    X->>S: publish events
    X->>O: reply / actions / progress
```

### Registry Projection

This is how execution events become stored registry conversation activity.

```mermaid
sequenceDiagram
    participant X as Runtime
    participant S as Registry sink
    participant P as Projection port
    participant B as Bus
    participant R as Registry

    X->>S: publish lifecycle
    S->>P: create / publish
    P->>B: control command
    B->>R: apply projection
```

### Delegation And Routed Tasks

This is how one bot delegates work to another through the registry now.

```mermaid
sequenceDiagram
    participant O as Origin bot
    participant X as SDK execution
    participant P as Projection
    participant R as Registry
    participant G as Target bot

    O->>X: provider result with coordination_intent
    X->>P: submit typed action
    P->>R: direct_assign / delegate_tasks / approve_delegation
    R->>G: deliver task
    G->>R: status / result
    R->>O: deliver result
```

Parent conversations also receive mirrored `task.status` events so delegated
work is visible in the registry UI, while the conversation `Tasks` tab queries
the routed-task store directly for a cleaner operational view.

## Identity And Persistence

### Stable And Live Identity

Stable local bot identity is stored at:

- `BOT_DATA_DIR/agent/bot_identity.json`

Per-registry runtime connection state is stored at:

- `BOT_DATA_DIR/agent/registries/<registry_id>.json`

Important rule:

- `BotConfig.registry_agent_ids` is a startup read model
- live per-registry identity comes from runtime registry state in `app/agents/state.py`
- projection and delegation paths must use the live runtime state, not the startup snapshot

### Actor And Conversation Identity

`actor_key` and conversation keys are the shared identity vocabulary across
channels. Key helpers live in `octopus_sdk.identity`, including:

- `telegram_actor_key(...)`
- `parse_actor_key(...)`
- `parse_conversation_key(...)`
- `conversation_key_for_ref(...)`
- `delegation_session_key(...)`
- stable bot identity helpers such as `bot_identity(...)` and `telegram_conversation_ref(...)`

### Persistence Seams

| Seam | Backends | Owns |
|---|---|---|
| local agent state | JSON files | stable bot identity and per-registry connection state |
| session storage | SQLite / Postgres | session, approval, retry, and delegation state |
| work queue / transport | SQLite / Postgres | queued work, claims, recovery, usage |
| control-plane bus | SQLite / Postgres | commands, replies, leases |
| content store | SQLite / Postgres | built-in/runtime content and guidance |
| credential store | SQLite / Postgres | encrypted skill credentials |
| registry store | SQLite / Postgres | agents, conversations, deliveries, events, routed tasks, approvals, skills, guidance |

Current defaults:

- bot runtime uses SQLite by default and Postgres when `BOT_DATABASE_URL` is set
- registry uses SQLite by default and Postgres when `REGISTRY_DATABASE_URL` is set
- SQLite and Postgres are kept aligned by shared tests and contract coverage

## Architecture Rules

1. `./octopus` owns `.deploy/`; runtime-owned identity/state lives under `BOT_DATA_DIR/agent/`.
2. `octopus_sdk` is the shared contract/runtime layer; it must not import `app/`.
3. `app/main.py` is the application composition root for this repo's runnable bot.
4. Channels own ref formats, ingress, and egress behavior.
5. `octopus_sdk.execution` owns channel-neutral execution orchestration; transport implementations supply adapters and callbacks.
6. `octopus_sdk.runtime` is protocol-based composition, not a builder API.
7. Structured coordination goes through typed SDK and registry contracts, not provider-emitted XML.
8. Projection, routing, discovery, and health publication go through SDK ports.
9. Routed-task lifecycle legality and idempotency are enforced through `octopus_sdk.task_protocol`.
10. Stored registry events use contracts from `octopus_sdk.events`.
11. Websocket realtime uses contracts from `octopus_sdk.realtime` and explicit topic subscriptions.
12. Live per-registry agent identity comes from runtime registry state, not from the startup-only `BotConfig.registry_agent_ids` snapshot.
13. SQLite and Postgres backends must remain behaviorally aligned.
