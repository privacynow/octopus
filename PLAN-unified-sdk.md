# Plan: Unified Octopus SDK

## Problem statement

The current `registry_sdk/` package is a registry client SDK — it knows how to
talk to the registry server (enroll, publish events, discover agents, submit
tasks) but provides none of the abstractions needed to implement a new bot or
channel.

A developer who wants to build a Slack bot today must:

1. Fork the entire `app/` directory
2. Delete `app/channels/telegram/`
3. Rewrite `app/channels/slack/` from scratch
4. Wire it into the same `main.py` startup
5. Hope they copied all the right internal modules

That is not "implementing against an SDK." It is forking an application. The
channel-neutral abstractions that every bot needs — provider execution, session
management, transport identity, event sinks, delegation, identity parsing —
live inside `app/` as internal modules that happen to be structured cleanly but
are not importable, versioned, or documented as a public contract.

Meanwhile, the registry server also imports `registry_sdk/` types for
validation. Those types (events, metadata schemas, realtime envelopes) are
genuinely shared contracts. But they share the `registry_sdk` namespace with
the HTTP client, which the registry server never uses. The naming implies
"registry things" when half the types are execution/bot concerns that the
registry merely consumes.

## Current state

**`registry_sdk/` (8 modules):**

| Module | Contains | Used by |
|--------|----------|---------|
| `events.py` | `ConversationEvent`, metadata schemas, `validate_event_metadata` | Registry server, bots, event sink |
| `realtime.py` | WS envelope types, `CollectionTopic`, progress models | Registry server, SPA (conceptually) |
| `client.py` | `RegistryClient` HTTP client | Bots, CLI |
| `agents.py` | `AgentCard` | Bots |
| `tasks.py` | `RoutedTaskRequest`, `RoutedTaskResult`, `RoutedTaskUpdate` | Bots, registry server |
| `conversations.py` | `ConversationCreate` | Registry server |
| `discovery.py` | `AgentDiscoveryQuery` | Bots |
| `__init__.py` | Re-exports | All |

**Bot-runtime abstractions in `app/` (not SDK):**

| Module | Contains | Channel-specific? |
|--------|----------|--------------------|
| `app/ports/execution_events.py` | `ExecutionEventSink` protocol | No |
| `app/ports/delegation.py` | `DelegationIntentParser` protocol | No |
| `app/ports/channel.py` | `Channel`, `ChannelBootstrap`, `ChannelIngress` protocols | No |
| `app/ports/egress.py` | `ChannelEgress`, `ConversationEgress`, `ChannelCapabilities` | No |
| `app/ports/conversation_projection.py` | `ConversationProjectionPort` | No |
| `app/ports/agent_directory.py` | `AgentDirectoryPort` | No |
| `app/ports/task_routing.py` | `TaskRoutingPort` | No |
| `app/ports/health_publication.py` | `HealthPublicationPort` | No |
| `app/workflows/execution/contracts.py` | `TransportIdentity`, `ExecutionRuntime` | No |
| `app/workflows/execution/event_sink.py` | `RegistryEventSink`, `NoOpEventSink` | No |
| `app/workflows/execution/delegation_parser.py` | `XmlTagDelegationParser` | No |
| `app/workflows/execution/requests.py` | `execute_request`, `dispatch_message_request`, `request_approval` | No |
| `app/providers/base.py` | `Provider` protocol, `RunResult`, `ToolExecutionRecord` | No |
| `app/identity.py` | `parse_actor_key`, `parse_conversation_key`, `normalize_conversation_id`, `delegation_session_key` | No |
| `app/session_state.py` | `SessionState` | No |
| `app/runtime/session_runtime.py` | `load_runtime_session`, `save_runtime_session` | No |
| `app/session_defaults.py` | Default session construction | No |
| `app/config.py` | `BotConfig` (mixed channel-neutral + Telegram fields) | Partially |

## Discussion and decisions

### One SDK, not two

A `bot_sdk` that depends on `registry_sdk` creates import indirection and
forces every bot to install two packages. Since the registry server also needs
event types from the same package, the cleanest boundary is one package with
clear submodule organization. The registry server imports contract submodules;
bots import contract + runtime submodules; channel implementations import the
channel protocol submodule.

### SDK owns contracts and reusable implementations; app/ owns wiring

The SDK provides:
- All shared types and protocols (events, identity, transport, providers, channels, sessions)
- Default implementations where there is exactly one correct implementation (NoOpEventSink, XmlTagDelegationParser, RegistryEventSink, RegistryClient)
- Identity helpers that every consumer needs
- Core execution orchestration (`execute_request`, `dispatch_message_request`, `request_approval`)
- A public bot runtime facade for building and running bots from SDK contracts

The SDK does NOT provide:
- Application wiring (`main.py`, startup, signal handling, Docker integration)
- The control plane bus (internal fan-out mechanism, not a public contract)
- `octopus_cli` (deployment tool)
- Telegram-specific channel implementation
- Registry HTTP server implementation
- Store implementations (SQLite, Postgres)

### Outcome bar: the SDK must be sufficient for a new transport

The goal is not merely "shared types moved into a new package." The goal is:

- A new transport can be implemented against `octopus_sdk` without importing
  `app.*`
- The transport can execute provider work, publish events, manage sessions,
  participate in delegation, and connect to registries through SDK contracts
- Telegram and registry channels prove the SDK is complete by consuming the
  same public surface

If a transport still needs to read `app/main.py` or import `app/workflows/*`
to run, the migration is incomplete.

### Import direction is one-way

`app/` imports `octopus_sdk`. `octopus_sdk` never imports `app`. This is
enforced by the import graph check in the verification plan. Shared types live
where they semantically belong — `TransportIdentity` is not a registry type,
so it cannot stay in app-local workflow code.

### Registry types nest under `octopus_sdk.registry`

Registry-specific models (agents, conversations, tasks, discovery) and the
registry HTTP client live under `octopus_sdk.registry.*`. This makes "registry
is one capability, not the whole SDK" explicit in the import path. Shared
contracts that both the registry server and bots consume (events, realtime)
stay at the top level.

### Channel protocol is SDK surface

`Channel`, `ChannelBootstrap`, `ChannelIngress`, `ChannelEgress`,
`ChannelCapabilities`, `ChannelDescriptor` are the contracts a Slack developer
implements. They must be in the SDK, not buried in `app/ports/`.

### ExecutionRuntime is SDK surface

`ExecutionRuntime` defines what a channel adapter wires: `build_transport_identity`,
`build_event_sink`, `delegation_parser`, provider callbacks, send callbacks.
The Slack developer creates an `ExecutionRuntime` with Slack-specific factories.
This must be importable from the SDK.

### Bot runtime facade is SDK surface

A public `octopus_sdk.runtime` module provides a builder that composes
provider, config, channels, transport identity, event sink, session/runtime
services, and registry connectivity hooks. This is the supported "build a bot"
entrypoint — a Slack developer should not need to read `app/main.py` to
understand wiring.

### BotConfig splits into base and channel-specific

`BotConfig` today has ~40 fields. About 25 are channel-neutral (provider,
skills, approval_mode, registries, capabilities, timeout, etc.). About 15 are
Telegram-specific (telegram_token, telegram_bot_id, telegram_username, etc.).
The SDK defines a base config. The Telegram app extends it. The SDK cannot
require Telegram token fields to build non-Telegram bots.

### No backwards compatibility shims

When types move from `app/` to `octopus_sdk/`, all imports update in the same
change. No `app.ports.channel` re-exporting from `octopus_sdk.channels`.
No dual import paths. Temporary branch-local shims are acceptable only during
migration and must be removed before merge.

### Provider implementations stay in app/

The `Provider` protocol goes in the SDK. `ClaudeProvider` and `CodexProvider`
stay in `app/providers/` because they are specific implementations with
subprocess management, streaming JSON parsing, and provider-specific quirks.
A Slack bot might use the same providers or bring its own.

### Existing channels must prove the SDK works

After extraction, both Telegram and registry channel implementations must
import all contracts from the SDK — not from `app/ports/` or `app/workflows/`.
If either channel still needs an `app`-internal import for a contract type,
that type hasn't been promoted yet.

## Target SDK structure

```
octopus_sdk/
    __init__.py

    # --- Shared contracts (used by registry server + bots + UI) ---
    events.py               # ConversationEvent, metadata schemas, validate_event_metadata
    realtime.py             # WS envelope types, CollectionTopic, progress models

    # --- Registry subpackage (client + models) ---
    registry/
        __init__.py
        client.py           # RegistryClient
        models.py           # AgentCard, RoutedTaskRequest, RoutedTaskResult,
                            # RoutedTaskUpdate, ConversationCreate,
                            # AgentDiscoveryQuery, ConversationProgressUpdate

    # --- Identity (used by registry server + bots) ---
    identity.py             # parse_actor_key, parse_conversation_key,
                            # normalize_conversation_id, delegation_session_key,
                            # telegram_actor_key, telegram_conversation_key,
                            # conversation_key_for_ref, registry_id_from_authority_ref

    # --- Channel contracts (implemented by Telegram, Slack, etc.) ---
    channels.py             # Channel, ChannelBootstrap, ChannelIngress, ChannelDescriptor
    egress.py               # ChannelEgress, ConversationEgress, ChannelCapabilities,
                            # EditableHandle

    # --- Execution contracts + orchestration ---
    execution.py            # TransportIdentity, ExecutionRuntime,
                            # execute_request, dispatch_message_request, request_approval

    # --- Provider protocol ---
    providers.py            # Provider protocol, RunResult, ToolExecutionRecord

    # --- Execution event sink (protocol + implementations) ---
    execution_events.py     # ExecutionEventSink protocol
    event_sink.py           # RegistryEventSink, NoOpEventSink, build_event_sink_for_context

    # --- Delegation (protocol + default implementation) ---
    delegation.py           # DelegationIntentParser protocol, XmlTagDelegationParser

    # --- Port protocols (used by runtime composition) ---
    conversation_projection.py  # ConversationProjectionPort, NoOpConversationProjection
    agent_directory.py          # AgentDirectoryPort, AgentSearchResult, AuthorityResolution
    task_routing.py             # TaskRoutingPort, TaskSubmissionResult, TaskResultReport
    health_publication.py       # HealthPublicationPort, HealthReport, AuthorityStatus

    # --- Session management ---
    sessions.py             # SessionState, defaults, provider-state factory types,
                            # session IO/service protocols used by runtime

    # --- Bot configuration (channel-neutral base) ---
    config.py               # BotConfigBase — provider, skills, approval_mode, registries,
                            # capabilities, timeout, data_dir, registry_agent_ids, etc.
                            # RegistryConnectionConfig, PublishLevel helpers

    # --- Bot runtime facade ---
    runtime.py              # Public bot builder: composes provider, config, channels,
                            # transport identity, event sink, session services,
                            # registry connectivity hooks. The supported "build a bot"
                            # entrypoint.
```

## What moves where

| Current location | Target location | Notes |
|-----------------|----------------|-------|
| `registry_sdk/events.py` | `octopus_sdk/events.py` | Rename package |
| `registry_sdk/realtime.py` | `octopus_sdk/realtime.py` | Rename package |
| `registry_sdk/client.py` | `octopus_sdk/registry/client.py` | Nest under registry subpackage |
| `registry_sdk/agents.py` | `octopus_sdk/registry/models.py` | Consolidate registry models |
| `registry_sdk/tasks.py` | `octopus_sdk/registry/models.py` | Consolidate registry models |
| `registry_sdk/conversations.py` | `octopus_sdk/registry/models.py` | Consolidate registry models |
| `registry_sdk/discovery.py` | `octopus_sdk/registry/models.py` | Consolidate registry models |
| `app/identity.py` | `octopus_sdk/identity.py` | Move entirely |
| `app/ports/channel.py` | `octopus_sdk/channels.py` | Move |
| `app/ports/egress.py` | `octopus_sdk/egress.py` | Move |
| `app/ports/execution_events.py` | `octopus_sdk/execution_events.py` | Move |
| `app/ports/delegation.py` + `delegation_parser.py` | `octopus_sdk/delegation.py` | Merge protocol + default impl |
| `app/ports/conversation_projection.py` | `octopus_sdk/conversation_projection.py` | Move (port only, not bus adapter) |
| `app/ports/agent_directory.py` | `octopus_sdk/agent_directory.py` | Move |
| `app/ports/task_routing.py` | `octopus_sdk/task_routing.py` | Move |
| `app/ports/health_publication.py` | `octopus_sdk/health_publication.py` | Move |
| `app/workflows/execution/contracts.py` | `octopus_sdk/execution.py` | TransportIdentity + ExecutionRuntime |
| `app/workflows/execution/requests.py` | `octopus_sdk/execution.py` | execute_request + dispatch + approval |
| `app/workflows/execution/event_sink.py` | `octopus_sdk/event_sink.py` | RegistryEventSink + NoOpEventSink |
| `app/workflows/execution/delegation_parser.py` | `octopus_sdk/delegation.py` | Merge with protocol |
| `app/providers/base.py` | `octopus_sdk/providers.py` | Provider protocol + RunResult + ToolExecutionRecord |
| `app/session_state.py` | `octopus_sdk/sessions.py` | SessionState |
| `app/session_defaults.py` | `octopus_sdk/sessions.py` | Default construction |
| `app/runtime/session_runtime.py` | `octopus_sdk/sessions.py` (partial) | Only channel-neutral session APIs move; storage-backed helpers may need refactor behind SDK session protocols |
| `app/config.py` (partial) | `octopus_sdk/config.py` | Channel-neutral BotConfigBase only |
| `app/main.py` + `app/runtime/` (partial) | `octopus_sdk/runtime.py` | Public bot builder facade |

## What stays in app/

| Module | Why |
|--------|-----|
| `app/config.py` | Telegram-specific fields, env parsing, load_config() — extends BotConfigBase |
| `app/main.py` | Application entry point — uses SDK runtime facade for wiring |
| `app/providers/claude.py` | Claude-specific subprocess management |
| `app/providers/codex.py` | Codex-specific subprocess management |
| `app/channels/telegram/*` | Telegram channel implementation (imports SDK contracts) |
| `app/channels/registry/*` | Registry HTTP server + channel (imports SDK contracts) |
| `app/control_plane/*` | Bus, adapters, processor runner (internal mechanism) |
| `app/agents/*` | Agent runtime, delegation handlers, delivery, bridge |
| `app/storage*.py` | SQLite/Postgres session store implementations behind SDK session protocols |
| `app/registry_service/*` | Registry store implementations |
| `app/workflows/*` (non-execution) | Conversation, pending, skills workflows |
| `app/runtime/*` | Composition, services, health (app-level wiring) |
| `app/octopus_cli/*` | Deployment CLI |
| `app/work_queue*.py` | Work queue implementations |

## What the Slack developer experience looks like after this

```python
from octopus_sdk.channels import ChannelBootstrap, ChannelIngress, ChannelDescriptor
from octopus_sdk.egress import ChannelEgress, ChannelCapabilities
from octopus_sdk.execution import TransportIdentity, execute_request
from octopus_sdk.event_sink import RegistryEventSink, NoOpEventSink
from octopus_sdk.providers import Provider, RunResult
from octopus_sdk.identity import parse_actor_key, parse_conversation_key
from octopus_sdk.config import BotConfigBase
from octopus_sdk.sessions import load_runtime_session, save_runtime_session
from octopus_sdk.runtime import BotRuntimeBuilder
from octopus_sdk.registry.client import RegistryClient


class SlackChannel(ChannelBootstrap):
    @property
    def channel_id(self) -> str:
        return "slack"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return ChannelDescriptor(
            channel_type="slack",
            display_name="Slack",
            supports_multiple=True,
            requires_polling=False,
            supports_timeline=True,
        )

    def ref_prefix(self) -> str:
        return "slack:"

    def build_egress(self, *, conversation_ref, config, **kw):
        return SlackEgress(conversation_ref, config)

    def build_ingress(self, *, config, delivery_handler):
        return SlackIngress(config, delivery_handler)


class SlackEgress(ChannelEgress):
    # Implement send_text, send_photo, send_document, send_action
    ...


# Build and run the bot using the SDK runtime facade
bot = (
    BotRuntimeBuilder()
    .with_config(my_config)
    .with_provider(my_provider)
    .with_channel(SlackChannel())
    .with_registry(registry_url="http://registry:8787", enroll_token="...")
    .build()
)
await bot.run()
```

The Slack developer:
- Implements `SlackChannel` (ingress + egress)
- Uses `BotRuntimeBuilder` to compose execution, events, sessions, registry
- Gets execution, events, delegation, sessions, providers from SDK imports
- Does NOT fork `app/`, does NOT copy internal modules
- Does NOT read `app/main.py` to understand wiring

## Implementation phases

### Phase 1: Freeze target API and create SDK skeleton

- Define the final `octopus_sdk` module map and all public exports
- Create `octopus_sdk/` directory with `__init__.py` and submodule stubs
- Create `octopus_sdk/registry/` subpackage with `__init__.py`
- Do not move code yet — define the namespace first

**Exit gate:** `octopus_sdk/` directory exists with target module files (can be empty). Import structure is documented.

### Phase 2: Move registry contracts into unified SDK

- Move `registry_sdk/events.py` → `octopus_sdk/events.py`
- Move `registry_sdk/realtime.py` → `octopus_sdk/realtime.py`
- Consolidate `registry_sdk/agents.py`, `registry_sdk/tasks.py`, `registry_sdk/conversations.py`, `registry_sdk/discovery.py` → `octopus_sdk/registry/models.py`
- Move `registry_sdk/client.py` → `octopus_sdk/registry/client.py`
- Update all `from registry_sdk` imports in `app/` to `from octopus_sdk` / `from octopus_sdk.registry`
- Delete `registry_sdk/` directory
- Update `Dockerfile`, `Dockerfile.bot`, `Dockerfile.runnable` COPY lines
- Run full test suite

**Exit gate:** Zero `registry_sdk` imports anywhere. `octopus_sdk.events`, `octopus_sdk.registry.client`, `octopus_sdk.registry.models` all work.

### Phase 3: Move identity helpers

- Move `app/identity.py` → `octopus_sdk/identity.py`
- Update all `from app.identity` imports to `from octopus_sdk.identity`
- The SDK now owns all identity parsing

**Exit gate:** `app/identity.py` does not exist. All identity imports from `octopus_sdk.identity`.

### Phase 4: Move port protocols

- Move `app/ports/channel.py` → `octopus_sdk/channels.py`
- Move `app/ports/egress.py` → `octopus_sdk/egress.py`
- Move `app/ports/execution_events.py` → `octopus_sdk/execution_events.py`
- Move `app/ports/delegation.py` + `app/workflows/execution/delegation_parser.py` → `octopus_sdk/delegation.py`
- Move `app/ports/conversation_projection.py` → `octopus_sdk/conversation_projection.py`
- Move `app/ports/agent_directory.py` → `octopus_sdk/agent_directory.py`
- Move `app/ports/task_routing.py` → `octopus_sdk/task_routing.py`
- Move `app/ports/health_publication.py` → `octopus_sdk/health_publication.py`
- Delete `app/ports/` directory
- Update all imports

**Exit gate:** `app/ports/` contains no protocol definitions. All port imports from `octopus_sdk.*`.

### Phase 5: Move execution contracts, orchestration, and event sink

- Move `TransportIdentity` and `ExecutionRuntime` from `app/workflows/execution/contracts.py` → `octopus_sdk/execution.py`
- Move `execute_request`, `dispatch_message_request`, `request_approval` from `app/workflows/execution/requests.py` → `octopus_sdk/execution.py`
- Move `RegistryEventSink`, `NoOpEventSink`, `build_event_sink_for_context` from `app/workflows/execution/event_sink.py` → `octopus_sdk/event_sink.py`
- Update runtime callers so execution entrypoints come from the SDK, not `app/workflows/execution/`
- Delete emptied source files before merge; temporary branch-local wrappers are allowed only while imports are being switched
- Update all imports

**Exit gate:** `TransportIdentity`, `ExecutionRuntime`, `execute_request`, `RegistryEventSink`, `NoOpEventSink` importable from `octopus_sdk.*`. No execution contract types remain in `app/workflows/execution/`.

### Phase 6: Move provider protocol and session management

- Move `Provider`, `RunResult`, `ToolExecutionRecord` from `app/providers/base.py` → `octopus_sdk/providers.py`
- Move `SessionState` from `app/session_state.py` → `octopus_sdk/sessions.py`
- Move session defaults from `app/session_defaults.py` → `octopus_sdk/sessions.py`
- Extract a session IO/service protocol into `octopus_sdk/sessions.py` if needed so runtime code can depend on the SDK instead of concrete app storage helpers
- Update SQLite/Postgres-backed session implementations in `app/storage*.py` to implement the SDK session protocol
- Move only the channel-neutral session APIs from `app/runtime/session_runtime.py`; do not strand `octopus_sdk` with imports back into `app`
- Delete emptied source files before merge
- Update all imports

**Exit gate:** Provider protocol and session state/service contracts importable from `octopus_sdk.providers` and `octopus_sdk.sessions`. `octopus_sdk` does not import `app.storage` or `app.config`.

### Phase 7: Extract channel-neutral BotConfigBase

- Define `BotConfigBase` in `octopus_sdk/config.py` with only channel-neutral fields
- Have `app/config.py`'s `BotConfig` inherit from `BotConfigBase`
- Move `RegistryConnectionConfig`, `PublishLevel` helpers, `should_publish_event` to SDK config
- Update imports where only base config is needed

**Exit gate:** A bot that doesn't use Telegram can configure itself with `BotConfigBase` from the SDK. `BotConfig` in `app/config.py` extends `BotConfigBase`.

### Phase 8: Build public bot runtime facade

- Create `octopus_sdk/runtime.py` with `BotRuntimeBuilder`
- Extract the reusable composition logic from `app/main.py`, `app/runtime/services.py`, and the execution wiring around `execute_request`
- The builder composes: provider, config, channels, transport identity factory, event sink factory, session services, registry connectivity hooks
- The builder must be sufficient for a non-Telegram transport to start and run without importing `app.main`
- `app/main.py` becomes a thin consumer of `BotRuntimeBuilder` with Telegram-specific wiring

**Exit gate:** `BotRuntimeBuilder` can produce a running bot with stub channel + provider. `app/main.py` uses it. A transport author no longer needs `app.main` to understand or reproduce wiring.

### Phase 9: Refactor Telegram to be a pure SDK consumer

- Update `app/channels/telegram/*` so all channel-neutral imports come from `octopus_sdk.*`
- No `app.ports.*` imports remain in Telegram code
- No `app.workflows.execution.contracts` imports remain in Telegram code
- Telegram only owns: ingress, egress, presentation, bootstrap, Telegram-specific config

**Exit gate:** `grep -r "from app.ports\|from app.workflows.execution.contracts\|from app.workflows.execution.event_sink" app/channels/telegram/` returns zero hits.

### Phase 10: Refactor registry channel to the same SDK surface

- Update `app/channels/registry/*` so all channel-neutral imports come from `octopus_sdk.*`
- Registry HTTP server and channel prove the same SDK contracts work for both channel types

**Exit gate:** `grep -r "from app.ports\|from app.workflows.execution.contracts" app/channels/registry/` returns zero hits.

### Phase 11: Reference transport proof

- Add a minimal test transport (`tests/support/stub_channel.py` or similar) that uses only SDK imports
- Implement: `StubChannel(ChannelBootstrap)`, `StubEgress(ChannelEgress)`, transport identity builder
- Integration test: create a bot through `BotRuntimeBuilder` with stub channel + fake provider, call `execute_request`, verify reply flows through
- This proves the SDK is sufficient without `app`-internal imports

**Exit gate:** Test channel imports zero types from `app.*`. Integration test passes.

### Phase 12: Remove old paths

- Delete `registry_sdk/` if still present
- Delete `app/ports/` if still present
- Delete moved protocol definitions from `app/workflows/execution/` (contracts.py, event_sink.py, delegation_parser.py)
- Delete `app/session_state.py`, `app/session_defaults.py`, `app/identity.py` if still present
- Remove any temporary aliasing used during migration

**Exit gate:** `grep -r "registry_sdk\|from app.ports\|from app.identity import\|from app.session_state" app/ tests/` returns zero hits (except test assertions that verify absence).

### Phase 13: Documentation

- Update `ARCHITECTURE.md` to reflect SDK structure
- Update `README.md` SDK section
- Add `octopus_sdk/README.md` with developer guide: "How to build a new channel"
- Update relevant manual/integration docs
- Ensure `Dockerfile*` COPY lines include `octopus_sdk/`

**Exit gate:** ARCHITECTURE.md describes the unified SDK. README references it. Developer guide exists.

### Phase 14: Verification

- Full test suite passes
- Import graph check: `octopus_sdk` does not import from `app`
- SDK import smoke tests: all public names importable
- Execution/runtime smoke test: a stub transport can build and run through `octopus_sdk.runtime` without touching `app.main`
- Telegram build/runtime tests pass with SDK imports only
- Registry server/runtime tests pass with SDK imports only
- Stub channel integration test passes with SDK imports only
- No duplicate protocol/type definitions remain under `app/`

**Exit gate:** All verification checks pass. SDK is independently importable without `app/` on the path.

## Architectural principles applied

1. **No parallel constructs** — `registry_sdk/` is deleted, not kept alongside `octopus_sdk/`. `app/ports/` is deleted, not kept alongside SDK ports.
2. **One import path per type** — no re-exports, no aliases, no backward-compat shims.
3. **Import direction is one-way** — `app/` imports `octopus_sdk`; `octopus_sdk` never imports `app`. Enforced by import graph check.
4. **SDK owns contracts, app/ owns wiring** — protocols, types, default implementations, and execution orchestration in SDK; application startup, bus, stores, CLI in app/.
5. **New channel = SDK imports + channel code** — no forking app/, no copying internal modules.
6. **Existing code moves, not rewrites** — same implementations, new package location. The one new abstraction is `BotRuntimeBuilder` (runtime facade).
7. **If a contract is promoted, all implementations adopt it** — Telegram, registry channel, runtime services, registry server, tests, and docs all switch to SDK imports in the same migration.
8. **No compatibility layer at merge time** — temporary branch-local shims acceptable during migration, removed before merge.
9. **Outcome over relocation** — a move is only complete when an external-style transport can use the SDK without `app` imports.

## Key architectural rules

- SDK import direction is one-way: app imports SDK; SDK does not import app.
- Shared types live where they semantically belong. `TransportIdentity` is not a registry type, so it cannot stay in app-local workflow code.
- Registry-only models and bot-runtime models share one package but different submodules.
- Telegram and registry channels must import SDK contracts, not private app copies.
- No duplicate protocol definitions after extraction.

## Non-goals

- No new channel implementations in this plan (Slack, WhatsApp, etc.)
- No changes to the control plane bus or registry server logic
- No PyPI packaging (the SDK is a local package for now; packaging is a future concern)
- No intended user-facing runtime behavior changes; internal composition may change as long as behavior remains equivalent and tests prove parity
