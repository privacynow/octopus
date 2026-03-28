# Plan: Three-Package Architecture — SDK, Registry Server, Bot

## Purpose

Separate this repository into three clean packages:

1. **`octopus_sdk/`** — the shared SDK that bot developers install. Contains
   contracts, execution engine, runtime composition, AND all backend-neutral
   workflow business logic. A developer installs this, writes their transport
   and storage, and has a working bot.
2. **`octopus_registry/`** — the registry server that operators deploy.
3. **`app/`** — our Telegram bot product.

## Problem statement

The SDK has contracts but not business logic. The registry server is entangled
with bot code. A new bot developer must clone `app/` to get workflow
implementations.

The 14 workflow implementation files in `app/workflows/` implement SDK
Protocols but import app-specific service singletons (`get_credential_service()`,
`get_content_store()`, `get_skill_catalog_service()`, etc.) instead of
receiving dependencies through constructor injection. This pattern makes them
unmovable to SDK as-is.

The fix: refactor each workflow implementation to receive its dependencies
through constructor-injected SDK Ports instead of importing app singletons.
Then the orchestration logic becomes backend-neutral and can move to SDK. The
`app/` composition code wires the constructors with our specific backends.

That is necessary but not sufficient. The target state also requires:

- SDK-owned workflow composition and minimal runtime/test utilities so an SDK
  consumer can actually use the moved workflow implementations
- a registry management protocol over the registry connection so a standalone
  registry server can manage connected bots without importing app-local runtime
  objects

## Current state (from exhaustive audit)

### Repository structure today

| Package | Files | Lines |
|---------|------:|------:|
| `octopus_sdk/` | 41 | 8,623 |
| `app/` (everything else) | 146 | 35,326 |
| `ui/` | 23 | 7,835 |
| `tests/` | 112 | ~56,178 |

### The 14 workflow files that need singleton-to-injection refactor

Each file implements an SDK Protocol but imports app singletons. The
orchestration logic is backend-neutral; only the wiring is app-specific.

| File | Lines | App singleton imports |
|------|------:|---------------------|
| `app/workflows/pending/requests.py` | 170 | `app.user_messages`, `app.config.BotConfig`, `app.runtime.composition` |
| `app/workflows/conversation/control.py` | 127 | `app.user_messages`, `app.work_queue`, `app.storage` |
| `app/workflows/conversation/settings.py` | 281 | `app.user_messages`, `app.config.BotConfig`, `app.runtime.composition` |
| `app/workflows/credentials/management.py` | 48 | `app.credential_service` |
| `app/workflows/runtime_skills/catalog.py` | 127 | `app.skill_catalog_service`, `app.skill_import_service` |
| `app/workflows/runtime_skills/activation.py` | 216 | `app.credential_service`, `app.provider_guidance_service`, `app.skill_activation_service` |
| `app/workflows/runtime_skills/setup.py` | 257 | `app.credential_service`, `app.credential_validation`, `app.skill_activation_service` |
| `app/workflows/runtime_skills/authoring.py` | 260 | `app.content_store`, `app.skill_catalog_service` |
| `app/workflows/runtime_skills/approval.py` | 130 | `app.content_store`, `app.skill_catalog_service` |
| `app/workflows/runtime_skills/importing.py` | 160 | `app.provider_guidance_service`, `app.skill_import_service` |
| `app/workflows/provider_guidance/preview.py` | 43 | `app.provider_guidance_service` |
| `app/workflows/provider_guidance/management.py` | 286 | `app.content_store` |
| `app/workflows/recovery/replay.py` | 200 | `app.user_messages`, `app.runtime.transport_dispatcher`, `app.work_queue`, `app.runtime.work_admission` |
| `app/workflows/execution/finalization.py` | 230 | `app.formatting`, `app.webhook` (conditional) |

### Deduplicated app dependencies across all 14 files

| App module | Files using it | Existing SDK Port? |
|-----------|---------------:|--------------------|
| `app.user_messages` | 4 | **NO** — needs `MessageTemplatePort` |
| `app.config.BotConfig` | 2 | YES — use `BotConfigBase` from SDK |
| `app.runtime.composition` | 2 | **NO** — circular dependency, must break |
| `app.credential_service` | 3 | **NO** — needs `CredentialServicePort` |
| `app.skill_catalog_service` | 3 | **NO** — needs `SkillCatalogServicePort` |
| `app.provider_guidance_service` | 3 | Partial — `ProviderGuidancePort` exists for preview, needs expansion or separate service port |
| `app.content_store` | 3 | **NO** — needs `ContentStorePort` |
| `app.skill_activation_service` | 2 | Partial — `SkillActivationPort` exists for session-level activation |
| `app.skill_import_service` | 2 | **NO** — needs `SkillImportServicePort` |
| `app.work_queue` | 2 | YES — `WorkQueuePort` exists |
| `app.storage` | 1 | Partial — `SessionRuntimePort` exists |
| `app.credential_validation` | 1 | **NO** — needs injectable validator |
| `app.formatting` | 1 | **NO** — utility, inline or SDK |
| `app.webhook` | 1 | Already injectable via context |
| `app.runtime.transport_dispatcher` | 1 | Moving to SDK in Phase 1 |
| `app.runtime.work_admission` | 1 | **NO** — `trust_tier_for_ref` needs injection |

### 5 pure backend-neutral files (zero app dependencies)

| File | Lines | Destination |
|------|------:|-------------|
| `app/workflows/lifecycle_machine.py` | 174 | `octopus_sdk/workflows/lifecycle_machine.py` |
| `app/workflows/pending/machine.py` | 375 | `octopus_sdk/workflows/pending_machine.py` |
| `app/workflows/recovery/machine.py` | 431 | `octopus_sdk/workflows/recovery_machine.py` |
| `app/workflows/runtime_skills/setup_machine.py` | 203 | `octopus_sdk/workflows/setup_machine.py` (needs `app.time_utils` extraction first) |
| `app/runtime/transport_dispatcher.py` | 156 | `octopus_sdk/transport_dispatcher.py` |

### TransportDispatcher consumers (7 production files + ~2 test files)

| Consumer | Line |
|----------|------|
| `app/runtime/transport_builders.py` | 16 |
| `app/channels/telegram/channel.py` | 15 |
| `app/channels/registry/channel.py` | 13 |
| `app/channels/telegram/state.py` | 23 |
| `app/runtime/work_admission.py` | 11 |
| `app/channels/registry/delivery_transport.py` | 30 |
| `app/workflows/recovery/replay.py` | 10 |

### Registry server entanglements (3 files)

| Server file | Problematic imports / missing boundary |
|-------------|----------------------------------------|
| `ingress.py` (477 lines) | 27 management operations call `_flows()` (local bot workflows), `load_runtime_session` / `save_runtime_session`, `ClaudeProvider` / `CodexProvider`, `BotConfig`, and `runtime_backend` directly. Must be rewritten to use SDK management protocol over the registry connection. |
| `auth.py` (273 lines) | `app.ratelimit` |
| `http.py` (1,472 lines) | `app.capability_service`. Also: 27 management routes are currently global (`/v1/catalog/skills`, `/v1/provider-guidance/{name}`, `/v1/conversations/{id}/skills`). Must become agent-scoped (`/v1/agents/{agent_id}/...`). |

### Missing SDK/runtime pieces

The current tree still lacks several target-state pieces this plan must create:

- `WorkflowComposer` in the SDK with builder pattern. Workflow assembly still
  lives in `app/runtime/composition.py`.
- SDK test/runtime utilities `InMemoryWorkQueue` and `InMemorySessionStore`.
- SDK-defined `ManagementRequest` / `ManagementResult` envelope models and
  per-operation request/result dataclasses for 27 management operations.
- `management_request` / `management_result` delivery kinds in the existing
  poll/ack delivery system.
- Bot-side management executor in SDK that routes `management_request`
  deliveries to `WorkflowComposer`-built workflows.
- Registry-side management client that enqueues requests and awaits results.
- Capability advertisement mechanism — bot declares which management domains
  it supports at registration time.
- Agent-scoped management HTTP routes (`/v1/agents/{agent_id}/...`) replacing
  current global management routes.

### Bot-only verification baseline

`app/main.py` is already bot-only — zero registry server logic. `app/config.py`
has zero registry server fields (`REGISTRY_PORT`, `REGISTRY_UI_TOKEN`,
`REGISTRY_BIND_HOST` are absent). This becomes verification/locking work later
in Phase 7, not a package split.

## Lessons and rules

From PLAN-sdk-3:

1. Exit criteria are immutable.
2. "Complete enough" is not a completion state.
3. Checklist items reflect file system state.
4. Each replacement atomically deletes what it replaces.
5. Tests are rewritten in the same change.
6. The plan is reviewed adversarially.
7. Do not modify exit criteria to match the implementation.

From this plan:

8. The exit test is a RUNNING bot, not a type-checking stub.
9. "Backend-neutral" = zero `from app.*` imports. Operates entirely through
   injected SDK Ports.
10. Replacing singleton imports with constructor injection is the prerequisite
    for moving workflow logic to SDK. Moving a file that imports `app/` into
    the SDK is not moving it to the SDK.
11. Three packages means three packages.
12. `telegram_shared_dispatch.py` is Telegram transport code, not worker
    dispatch injection. It is NOT deleted as part of WorkerDispatchPort
    elimination.

## Target boundary

The target architecture is:

- **`octopus_sdk/`** = shared contracts, shared business logic, workflow
  composition, and test/runtime utilities
- **`octopus_registry/`** = management plane. Enrollment, status, UI, store,
  and agent-scoped management API for connected bots
- **`app/`** = Telegram bot product. No management API or UI of its own

The registry server must be deployable on its own. When no bots are connected,
enrollment, health, status, and UI still work, and management endpoints fail
explicitly as unavailable.

When a bot connects, the registry server manages that bot through an
SDK-defined management protocol over the registry connection. The registry
server does not import Telegram code and does not receive live Python objects
from the bot process.

`app/channels/registry/` remains the bot-side transport/client path to the
registry management plane. `octopus_registry/` is the server side of that
management plane.

### Two tiers of registry endpoints

**Global endpoints** — registry-owned data. No bot connection required.
Enrollment, agent listing, conversations, tasks, status, health.
These already exist and work standalone. No change needed.

Examples: `/v1/agents`, `/v1/conversations`, `/v1/agents/enroll`,
`/v1/agents/{id}/status`

**Agent-scoped management endpoints** — bot-specific operations. Require a
connected bot with the relevant capability advertised.

Examples: `/v1/agents/{agent_id}/catalog/skills`,
`/v1/agents/{agent_id}/guidance/{name}`,
`/v1/agents/{agent_id}/conversations/{id}/skills`

Current global management endpoints (`/v1/catalog/skills`,
`/v1/provider-guidance/{name}`, `/v1/conversations/{id}/skills`) become
agent-scoped. This eliminates hidden single-bot assumptions and makes the
registry genuinely multi-bot capable.

### Management protocol transport

Management requests use the existing poll/ack delivery system. The registry
enqueues a `management_request` delivery for the target agent. The bot polls,
receives the request, executes the operation against its locally composed
workflows, and reports the result back. No new listener or bind required on
the bot side.

This matches the existing `routed_task` / `routed_result` pattern and works
when the bot is behind NAT.

## Execution plan

### Phase 1: Move 5 pure files to SDK + extract time_utils

These files have zero app dependencies. Direct moves.

**Prerequisite:**
- [ ] 1-pre: Move `age_seconds`, `utc_now`, `utc_now_timestamp` (~20 lines)
  from `app/time_utils` to `octopus_sdk/time_utils.py`. Update consumers.

**Moves (4 FSMs + 1 dispatcher = 5 files, 1,339 lines):**

- [ ] 1a: `app/workflows/lifecycle_machine.py` (174) → `octopus_sdk/workflows/lifecycle_machine.py`
- [ ] 1b: `app/workflows/pending/machine.py` (375) → `octopus_sdk/workflows/pending_machine.py`
- [ ] 1c: `app/workflows/recovery/machine.py` (431) → `octopus_sdk/workflows/recovery_machine.py`
- [ ] 1d: `app/workflows/runtime_skills/setup_machine.py` (203) → `octopus_sdk/workflows/setup_machine.py` (after 1-pre)
- [ ] 1e: `app/runtime/transport_dispatcher.py` (156) → `octopus_sdk/transport_dispatcher.py`

**Consumer import updates (7 production + ~2 test files):**

| Consumer | Old | New |
|----------|-----|-----|
| `app/workflows/runtime_skills/authoring.py` | `app.workflows.lifecycle_machine` | `octopus_sdk.workflows.lifecycle_machine` |
| `app/workflows/runtime_skills/approval.py` | `app.workflows.lifecycle_machine` | `octopus_sdk.workflows.lifecycle_machine` |
| `app/workflows/provider_guidance/management.py` | `app.workflows.lifecycle_machine` | `octopus_sdk.workflows.lifecycle_machine` |
| `app/workflows/pending/requests.py` | `app.workflows.pending.machine` | `octopus_sdk.workflows.pending_machine` |
| `app/workflows/runtime_skills/setup.py` | `app.workflows.runtime_skills.setup_machine` | `octopus_sdk.workflows.setup_machine` |
| `app/runtime/transport_builders.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/channels/telegram/channel.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/channels/registry/channel.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/channels/telegram/state.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/runtime/work_admission.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/channels/registry/delivery_transport.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |
| `app/workflows/recovery/replay.py` | `app.runtime.transport_dispatcher` | `octopus_sdk.transport_dispatcher` |

- [ ] 1f: Verify all moved files have zero `from app.*` imports
- [ ] 1g: Delete all source files from `app/`
- [ ] 1h: Rewrite affected tests

**Exit gate:**
- 5 files in SDK, sources deleted
- 12 consumer imports updated
- Zero `app/` imports in moved files

### Phase 2: Define missing SDK Ports for service dependencies

Before the 14 workflow files can be refactored, SDK Ports must exist for
every app service they depend on.

**New SDK Ports to define:**

- [ ] 2a: `MessageTemplatePort` — user-facing string templates. Methods
  for every string the 4 workflow files currently get from `app.user_messages`.
  Location: `octopus_sdk/messages.py`
- [ ] 2b: `CredentialServicePort` — credential load/store/list/clear.
  Location: expand existing `octopus_sdk/workflows/credentials.py` or new file
- [ ] 2c: `SkillCatalogServicePort` — skill catalog CRUD operations.
  Location: expand `octopus_sdk/workflows/skills.py`
- [ ] 2d: `ContentStorePort` — content storage for skill files and guidance.
  Location: `octopus_sdk/content_store.py`
- [ ] 2e: `SkillImportServicePort` — skill import/update/diff.
  Location: expand `octopus_sdk/workflows/skills.py`
- [ ] 2f: `CredentialValidatorPort` — credential validation callable.
  Location: expand `octopus_sdk/workflows/credentials.py`
- [ ] 2g: `TrustTierResolverPort` — trust tier for conversation ref.
  Location: `octopus_sdk/authorization.py`
- [ ] 2h: `TextFormattingPort` — `summarize_text` and similar.
  Location: expand `octopus_sdk/formatting.py`
- [ ] 2i: `CompletionWebhookPort` — fire webhook on completion.
  Location: `octopus_sdk/webhooks.py`

**Existing SDK Ports to verify are sufficient:**

- [ ] 2j: `BotConfigBase` covers all config fields the workflows use
- [ ] 2k: `WorkQueuePort` covers all work queue operations the workflows use
- [ ] 2l: `SessionRuntimePort` covers `default_session()` and all session ops
- [ ] 2m: `ProviderGuidancePort` covers guidance service operations
- [ ] 2n: `SkillActivationPort` covers activation service operations
- [ ] 2n2: `WorkQueuePort` and `SessionRuntimePort` encode durability
  expectations in their method surface, not just documentation. Methods like
  `recover_after_crash`, `list_incomplete_sessions`, `replay_unacked` (or
  equivalents) must exist so that `octopus_sdk/testing/` implementations can
  raise `NotImplementedError` on them. If these methods do not exist today,
  add them in this phase — the fence in Phase 9 only works if the ports
  structurally distinguish durable from non-durable implementations

**Break the composition circular dependency:**

- [ ] 2o: The 2 files that import `app.runtime.composition` use it to reach
  sibling workflows (e.g., `composition.workflows().runtime_skills.setup`).
  Replace with constructor-injected workflow references. The workflow receives
  its sibling workflows through its constructor, not by importing the
  composition module.

**Exit gate:**
- Every app singleton dependency has a corresponding SDK Port
- No new Port imports from `app/`
- Composition circular dependency is breakable

### Phase 3: Refactor 14 workflow files to constructor injection, move to SDK

Depends on Phase 2 (all Ports exist).

For each of the 14 files:
1. Replace every `app.*` singleton import with a constructor parameter typed
   to an SDK Port
2. Verify zero `from app.*` imports remain
3. Move the file to `octopus_sdk/workflows/`
4. Delete the `app/` source
5. Update `app/runtime/composition.py` to inject the app implementations
   when constructing each workflow
6. Rewrite affected tests

**The pattern for each file:**

Before (in `app/`):
```python
from app.credential_service import get_credential_service
class CredentialManagementUseCases(CredentialManagementPort):
    def clear(self, session, ...):
        svc = get_credential_service()  # app singleton
        svc.clear(...)
```

After (in SDK):
```python
class CredentialManagementUseCases(CredentialManagementPort):
    def __init__(self, credential_service: CredentialServicePort):
        self._credential_service = credential_service
    def clear(self, session, ...):
        self._credential_service.clear(...)
```

Wiring (stays in `app/`):
```python
credential_mgmt = CredentialManagementUseCases(
    credential_service=get_credential_service(),
)
```

**Checklist (14 files):**

- [ ] 3a: `pending/requests.py` (170 lines) — inject `MessageTemplatePort`, `BotConfigBase`, sibling workflow refs
- [ ] 3b: `conversation/control.py` (127 lines) — inject `MessageTemplatePort`, `WorkQueuePort`, `SessionRuntimePort`
- [ ] 3c: `conversation/settings.py` (281 lines) — inject `MessageTemplatePort`, `BotConfigBase`, sibling workflow refs
- [ ] 3d: `credentials/management.py` (48 lines) — inject `CredentialServicePort`
- [ ] 3e: `runtime_skills/catalog.py` (127 lines) — inject `SkillCatalogServicePort`, `SkillImportServicePort`
- [ ] 3f: `runtime_skills/activation.py` (216 lines) — inject `CredentialServicePort`, `ProviderGuidancePort`, `SkillActivationPort`
- [ ] 3g: `runtime_skills/setup.py` (257 lines) — inject `CredentialServicePort`, `CredentialValidatorPort`, `SkillActivationPort`
- [ ] 3h: `runtime_skills/authoring.py` (260 lines) — inject `ContentStorePort`, `SkillCatalogServicePort`
- [ ] 3i: `runtime_skills/approval.py` (130 lines) — inject `ContentStorePort`, `SkillCatalogServicePort`
- [ ] 3j: `runtime_skills/importing.py` (160 lines) — inject `ProviderGuidancePort`, `SkillImportServicePort`
- [ ] 3k: `provider_guidance/preview.py` (43 lines) — inject `ProviderGuidancePort`
- [ ] 3l: `provider_guidance/management.py` (286 lines) — inject `ContentStorePort`
- [ ] 3m: `recovery/replay.py` (200 lines) — inject `MessageTemplatePort`, `TransportDispatcher`, `WorkQueuePort`, `TrustTierResolverPort`
- [ ] 3n: `execution/finalization.py` (230 lines) — inject `TextFormattingPort`, `CompletionWebhookPort`

**For each move:**
- [ ] 3o: Delete the `app/workflows/*/` source file
- [ ] 3p: Update `app/runtime/composition.py` to construct each workflow with
  injected app implementations
- [ ] 3q: Update all other consumers
- [ ] 3r: Rewrite affected tests

**Exit gate:**
- All 14 workflow implementations live in `octopus_sdk/workflows/`
- All 14 `app/workflows/*/` source files deleted (except `*/telegram.py`
  transport-specific files which stay)
- Zero `from app.*` imports in any SDK workflow file
- `app/runtime/composition.py` wires constructors with app implementations
- `app/workflows/` contains only Telegram-specific handlers and `__init__` files

### Phase 3.5: Add SDK workflow composition and runtime utilities

Depends on Phase 3 (SDK workflow implementations exist).

The SDK must provide a real composition surface and minimal runtime/test
utilities. A bot developer should not reverse-engineer `app/runtime/composition.py`
to use the SDK.

- [ ] 3.5a: Add `octopus_sdk/composition.py`
- [ ] 3.5b: Add `WorkflowComposer` with builder-style API
  (`with_credentials(...)`, `with_content_store(...)`, etc.)
- [ ] 3.5c: `WorkflowComposer.build()` returns a fully wired
  `WorkflowComposition`
- [ ] 3.5d: Required ports fail at `.build()` time with explicit errors.
  Required: `MessageTemplatePort`, `SessionRuntimePort`, `WorkQueuePort`,
  `BotConfigBase`
- [ ] 3.5e: Optional ports default to loud `NotConfiguredError`
  implementations that raise on any method call — not silent no-ops, not
  empty returns. Optional: `CredentialServicePort`, `SkillCatalogServicePort`,
  `ContentStorePort`, `SkillImportServicePort`, `ProviderGuidancePort`,
  `SkillActivationPort`, `CredentialValidatorPort`, `TextFormattingPort`,
  `CompletionWebhookPort`, `TrustTierResolverPort`
- [ ] 3.5f: Add `InMemoryWorkQueue` in `octopus_sdk/testing/work_queue.py`.
  Deliberately non-durable: raises `NotImplementedError` on methods that
  imply persistence guarantees (`recover_after_crash`,
  `list_incomplete_sessions`, etc.). Suitable for wiring verification only.
- [ ] 3.5g: Add `InMemorySessionStore` in `octopus_sdk/testing/sessions.py`.
  Same constraint: non-durable, raises on persistence-guarantee methods.
- [ ] 3.5g2: `WorkflowComposer` has two build methods: `.build()` for
  production and `.build_for_testing()` for test/verification use.
  `.build()` rejects `octopus_sdk.testing.*` implementations — it does not
  auto-detect and warn, it refuses. `.build_for_testing()` accepts them and
  marks the composition as test-only. `BotRuntime` refuses to start with a
  test-only composition unless an explicit override is provided. This makes
  the intent visible at the call site, not buried in implementation types.
- [ ] 3.5h: Make `app/runtime/composition.py` a thin wrapper around
  `WorkflowComposer`
- [ ] 3.5i: Rewrite affected tests

**Exit gate:**
- SDK provides `WorkflowComposer`
- SDK provides in-memory work queue and session utilities
- `app/runtime/composition.py` owns wiring only, not workflow business logic
- Optional-capability defaults fail loudly, not silently

### Phase 4: Define registry management protocol for connected bots

Depends on Phases 2, 3, and 3.5.

The registry server is the management plane. The bot has no management API of
its own. Therefore registry management operations must cross the registry
connection through an SDK-defined protocol; local constructor injection is not
enough across a process boundary.

#### Operation inventory (27 operations, 4 tiers)

**Tier B: Pure workflow operations (19 ops)**
Need only composed workflows. No session, no provider, no config.

| Domain | Operations |
|--------|-----------|
| Skill catalog | `list_catalog_skills`, `search_catalog_skills`, `catalog_skill_detail`, `diff_catalog_skill` |
| Skill lifecycle | `catalog_skill_lifecycle_detail`, `edit_catalog_skill_draft`, `submit_catalog_skill`, `approve_catalog_skill`, `reject_catalog_skill`, `publish_catalog_skill`, `archive_catalog_skill` |
| Provider guidance | `preview_provider_guidance`, `provider_guidance_detail`, `edit_provider_guidance_draft`, `submit_provider_guidance`, `approve_provider_guidance`, `reject_provider_guidance`, `publish_provider_guidance`, `archive_provider_guidance` |

**Tier C: Workflow + provider operations (2 ops)**
Need composed workflows + provider context for prompt size validation.

| Operations |
|-----------|
| `install_catalog_skill`, `update_catalog_skill` |

**Tier D: Workflow + config operations (1 op)**
Needs composed workflows + config (default_skills guard).

| Operations |
|-----------|
| `uninstall_catalog_skill` |

**Tier E: Session-backed operations (4 ops)**
Need store + config + provider + session load/save. Session is local to bot.

| Operations |
|-----------|
| `conversation_skill_state` (read), `activate_conversation_skill` (read/write), `deactivate_conversation_skill` (read/write), `clear_conversation_skills` (read/write) |

All session management stays bot-side. The protocol is request/response — the
registry sends "activate skill X for conversation Y" and the bot handles
session load, workflow execution, session save, and returns the result. The
registry never touches sessions directly.

#### Transport mechanism

Management requests use the existing poll/ack delivery system. New delivery
kind: `management_request`. Bot polls, receives request, executes against
locally composed workflows, reports result via `management_result`.

This matches the existing `routed_task` / `routed_result` pattern. No new
listener or bind required on the bot side. Works behind NAT.

#### Agent-scoped endpoints

Current global management endpoints become agent-scoped:

| Current | Target |
|---------|--------|
| `GET /v1/catalog/skills` | `GET /v1/agents/{agent_id}/catalog/skills` |
| `GET /v1/catalog/skills/search` | `GET /v1/agents/{agent_id}/catalog/skills/search` |
| `GET /v1/catalog/skills/{name}` | `GET /v1/agents/{agent_id}/catalog/skills/{name}` |
| `PUT /v1/catalog/skills/{name}/draft` | `PUT /v1/agents/{agent_id}/catalog/skills/{name}/draft` |
| `POST /v1/catalog/skills/{name}/submit` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/submit` |
| `POST /v1/catalog/skills/{name}/approve` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/approve` |
| `POST /v1/catalog/skills/{name}/reject` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/reject` |
| `POST /v1/catalog/skills/{name}/publish` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/publish` |
| `POST /v1/catalog/skills/{name}/archive` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/archive` |
| `POST /v1/catalog/skills/{name}/install` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/install` |
| `POST /v1/catalog/skills/{name}/uninstall` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/uninstall` |
| `POST /v1/catalog/skills/{name}/update` | `POST /v1/agents/{agent_id}/catalog/skills/{name}/update` |
| `GET /v1/catalog/skills/{name}/diff` | `GET /v1/agents/{agent_id}/catalog/skills/{name}/diff` |
| `GET /v1/catalog/skills/{name}/lifecycle` | `GET /v1/agents/{agent_id}/catalog/skills/{name}/lifecycle` |
| `GET /v1/conversations/{id}/skills` | `GET /v1/agents/{agent_id}/conversations/{id}/skills` |
| `POST /v1/conversations/{id}/skills/{name}/activate` | `POST /v1/agents/{agent_id}/conversations/{id}/skills/{name}/activate` |
| `POST /v1/conversations/{id}/skills/{name}/deactivate` | `POST /v1/agents/{agent_id}/conversations/{id}/skills/{name}/deactivate` |
| `POST /v1/conversations/{id}/skills/clear` | `POST /v1/agents/{agent_id}/conversations/{id}/skills/clear` |
| `GET /v1/provider-guidance/{name}` | `GET /v1/agents/{agent_id}/guidance/{name}` |
| `PUT /v1/provider-guidance/{name}/draft` | `PUT /v1/agents/{agent_id}/guidance/{name}/draft` |
| `POST /v1/provider-guidance/{name}/submit` | `POST /v1/agents/{agent_id}/guidance/{name}/submit` |
| `POST /v1/provider-guidance/{name}/approve` | `POST /v1/agents/{agent_id}/guidance/{name}/approve` |
| `POST /v1/provider-guidance/{name}/reject` | `POST /v1/agents/{agent_id}/guidance/{name}/reject` |
| `POST /v1/provider-guidance/{name}/publish` | `POST /v1/agents/{agent_id}/guidance/{name}/publish` |
| `POST /v1/provider-guidance/{name}/archive` | `POST /v1/agents/{agent_id}/guidance/{name}/archive` |
| `POST /v1/provider-guidance/{name}/preview` | `POST /v1/agents/{agent_id}/guidance/{name}/preview` |

Global endpoints (`/v1/agents`, `/v1/conversations`, `/v1/tasks`, enrollment,
heartbeat, poll/ack) remain unchanged — they are registry-owned data.

#### Checklist

- [ ] 4a: Define SDK `ManagementRequest` / `ManagementResult` envelope models
  with discriminated `operation` field. Location: `octopus_sdk/registry/management.py`
- [ ] 4b: Define SDK request/result dataclasses for each of the 27 operations,
  grouped by domain (skill catalog, skill lifecycle, provider guidance,
  conversation skills)
- [ ] 4c: Add `management_request` delivery kind to the existing delivery
  system alongside `channel_input`, `routed_task`, etc.
- [ ] 4d: Add `management_result` reporting path (mirrors `routed_result`)
- [ ] 4e: Define capability advertisement — bot advertises supported management
  domains (`skill_catalog`, `skill_lifecycle`, `provider_guidance`,
  `conversation_skills`) at connection/registration time. Maps directly to
  which optional ports were wired in `WorkflowComposer`
- [ ] 4f: Add bot-side management executor in SDK that receives a
  `ManagementRequest`, routes to the correct workflow method on the
  `WorkflowComposer`-built composition, and returns a `ManagementResult`.
  For Tier E (session-backed) operations, the executor handles session
  load/save locally
- [ ] 4g: Add registry-side management client that enqueues
  `management_request` deliveries for the target agent and awaits
  `management_result`. Used by HTTP handlers and UI
- [ ] 4h: Migrate current global management HTTP routes to agent-scoped
  (`/v1/agents/{agent_id}/...`). Update UI to include agent selector and
  per-agent management views
- [ ] 4i: Define explicit responses for: agent not connected, agent connected
  but capability not advertised, agent connected and capable but request
  timed out
- [ ] 4j: Rewrite affected tests

**Exit gate:**
- All 27 management operations use `management_request` / `management_result`
  over the poll/ack delivery system
- All management HTTP endpoints are agent-scoped
  (`/v1/agents/{agent_id}/...`)
- No management endpoint depends on local bot-runtime objects
- Capability advertisement determines which management features are available
  per agent
- Standalone registry: management endpoints return explicit "agent not
  connected" or "capability not available" responses
- UI shows per-agent management with agent selector

### Phase 5: Resolve registry server entanglements

Depends on Phase 4 (management protocol exists).

**5a: Rewrite `ingress.py` against the management protocol**

After Phase 4, `ingress.py` no longer calls `_flows()` or loads sessions
locally. It becomes the registry-side adapter that translates HTTP handler
calls into `ManagementRequest` envelopes, sends them to the target agent
through the management client, and returns `ManagementResult` payloads.

This is a rewrite, not a move. The current 477-line file that imports
`app.config`, `app.providers.*`, `app.runtime.composition`,
`app.runtime.session_runtime`, and `app.runtime_backend` is replaced by a
~200-line adapter that imports only `octopus_sdk.registry.management` types.

- [ ] 5a-1: Rewrite `ingress.py` to use the registry-side management client
  from Phase 4g. Each function becomes: build `ManagementRequest` → send to
  agent → return `ManagementResult` payload
- [ ] 5a-2: Remove all `app.*` imports
- [ ] 5a-3: Add capability checks — if the target agent does not advertise the
  required capability, return explicit error before sending the request
- [ ] 5a-4: All 27 operations produce the same API responses as before (same
  JSON shape to avoid breaking the UI)

**5b: Fix `auth.py`**
- [ ] 5b-1: Move `app/ratelimit.py` (~65 lines) to `octopus_registry/` or
  extract as shared utility

**5c: Fix `http.py`**
- [ ] 5c-1: Move `app/capability_service.py` (~90 lines) to
  `octopus_registry/` or inline
- [ ] 5c-2: Update route definitions to agent-scoped paths per Phase 4h table
- [ ] 5c-3: Each agent-scoped route resolves `agent_id` from path, validates
  agent exists and is connected, then delegates to rewritten `ingress.py`

**Exit gate:**
- All registry-server files have zero `app.*` imports
- `ingress.py` operates through SDK management protocol, not local bot objects
- `http.py` routes are agent-scoped
- API response shapes preserved (UI compatibility)

### Phase 6: Extract registry server to `octopus_registry/`

Depends on Phase 5 (entanglements resolved).

**6a: Create package and move files**

| Source | Destination |
|--------|-------------|
| `app/channels/registry/http.py` | `octopus_registry/server.py` |
| `app/channels/registry/ws.py` | `octopus_registry/ws.py` |
| `app/channels/registry/auth.py` | `octopus_registry/auth.py` |
| `app/channels/registry/presenters.py` | `octopus_registry/presenters.py` |
| `app/channels/registry/ingress.py` | `octopus_registry/ingress.py` |
| `app/registry_service/store_base.py` | `octopus_registry/store_base.py` |
| `app/registry_service/store.py` | `octopus_registry/store.py` |
| `app/registry_service/store_postgres.py` | `octopus_registry/store_postgres.py` |
| `app/registry_service/authority.py` | `octopus_registry/authority.py` |
| `app/registry_service/backend.py` | `octopus_registry/backend.py` |
| `ui/` | `octopus_registry/ui/` |

- [ ] 6a-1: Create `octopus_registry/__init__.py`
- [ ] 6a-2: Move all server + store files per table
- [ ] 6a-3: Move `ui/` to `octopus_registry/ui/`
- [ ] 6a-4: Create `octopus_registry/config.py` (registry-specific config)
- [ ] 6a-5: Create `octopus_registry/main.py` (registry entrypoint)
- [ ] 6a-6: Delete `app/channels/registry/` server files (keep bot transport:
  `channel.py`, `egress.py`, `delivery_transport.py`, `refs.py`)
- [ ] 6a-7: Delete `app/registry_service/`
- [ ] 6a-8: Delete `ui/` at repo root

**6b: Update deployment**
- [ ] 6b-1: Update Dockerfiles
- [ ] 6b-2: Update Docker Compose
- [ ] 6b-3: Update `octopus_cli` registry references

**6c: Lock boundaries**
- [ ] 6c-1: Import-graph test: `octopus_registry` may not import `app`
- [ ] 6c-2: Import-graph test: `app` may not import `octopus_registry`
- [ ] 6c-3: Import-graph test: `octopus_sdk` imports neither
- [ ] 6c-4: Verify `octopus_registry/` imports only `octopus_sdk/` + stdlib + third-party
- [ ] 6c-5: Rewrite affected tests

**Exit gate:**
- `octopus_registry/` exists with server, store, UI, config, entrypoint
- `app/registry_service/` does not exist
- `ui/` at repo root does not exist
- Import-graph tests pass for all 3 boundaries

### Phase 7: Verify bot config/entrypoint separation

`app/main.py` is already bot-only. `app/config.py` has no registry server
fields. This phase verifies and locks that state.

- [ ] 7a: Verify `app/main.py` has zero registry server startup logic
- [ ] 7b: Verify `app/config.py` has zero registry server fields
- [ ] 7c: Add regression test that `app/main.py` does not import
  `octopus_registry`

**Exit gate:**
- Bot entrypoint and config confirmed bot-only
- Regression test locks it

### Phase 8: Eliminate WorkerDispatchPort injection

Depends on Phase 3 (workflow implementations are SDK-owned).

`BotRuntime._run_worker_loop()` can now dispatch to SDK workflows directly.

- [ ] 8a: Move claimed-item-to-workflow routing into `BotRuntime`
- [ ] 8b: Eliminate `WorkerDispatchPort` from `BotRuntime`
- [ ] 8c: The path from `runtime.submit(envelope)` to workflow invocation has
  zero `app/` imports
- [ ] 8d: Rewrite affected tests

**Note:** `app/runtime/telegram_shared_dispatch.py` is Telegram-specific
command/callback routing. It is NOT part of this phase. It stays in `app/`
as Telegram transport code.

**Exit gate:**
- `BotRuntime` has no `WorkerDispatchPort` or equivalent injection
- Dispatch is SDK-native

### Phase 9: SDK wiring verification test

Depends on Phases 3.5 and 8.

This phase creates a **test** that proves SDK wiring is correct. It uses
test-only in-memory implementations from `octopus_sdk/testing/`. These
implementations exist exclusively for this purpose — they are NOT production
defaults, NOT developer templates, and NOT a shortcut to "certification."

**Fence off test utilities:**

- [ ] 9a: `InMemoryWorkQueue` and `InMemorySessionStore` live in
  `octopus_sdk/testing/` — a package that is clearly test infrastructure,
  not runtime code
- [ ] 9b: Test implementations are deliberately minimal — they do NOT
  implement durability, concurrency safety, or restart recovery. They
  raise `NotImplementedError` on any method that implies persistence
  guarantees (e.g., `recover_after_crash`, `list_incomplete_sessions`)
- [ ] 9c: `.build()` rejects test implementations. The wiring test must
  use `.build_for_testing()` — making the test-only intent explicit at
  the call site

**The wiring test itself:**

- [ ] 9d: Test composes workflows through
  `WorkflowComposer...build_for_testing()` with test implementations
- [ ] 9e: Test exercises: message → provider → approval → delegation →
  skills → recovery — proving the SDK workflow implementations are
  correctly wired through injected Ports
- [ ] 9f: Zero `app/` imports. Zero `octopus_registry/` imports.
- [ ] 9g: This is a pytest in `octopus_sdk/tests/`, not an example or
  template. It is not referenced in developer documentation as "how to
  build a bot"

**Exit gate:**
- Full workflow lifecycle exercised through SDK business logic
- Zero `app/` and `octopus_registry/` imports
- Test utilities are fenced in `octopus_sdk/testing/` and unsuitable for
  production use by design
- Test mode is detectable and loudly warns

### Phase 10: Final verification

- [ ] 10a: Import graph: `octopus_sdk/` imports neither `app/` nor `octopus_registry/`
- [ ] 10b: Import graph: `octopus_registry/` imports only `octopus_sdk/`
- [ ] 10c: Import graph: `app/` does not import `octopus_registry/`
- [ ] 10d: All import-graph regression tests pass
- [ ] 10e: Full test suite passes
- [ ] 10f: SDK wiring verification test passes
- [ ] 10g: `app/` does not import `octopus_sdk.testing` (production code
  must not depend on test utilities)
- [ ] 10h: `octopus_registry/` does not import `octopus_sdk.testing`
- [ ] 10i: `octopus_sdk/testing` is not re-exported from `octopus_sdk/__init__.py`
  or any other convenience surface. It must be an explicit, deliberate import.
- [ ] 10j: Adversarial review of all exit criteria

### Phase 11: Fix delegation protocol transport identity

Phases 1-10 are complete. This phase fixes a structural bug in the
delegation protocol: the originating transport conversation key is lost
during the delegation round-trip. This affects any transport (Telegram,
Slack, any future transport) — it is not a Telegram-specific bug.

A Slack developer using the SDK would hit the same bug. This must be
fixed as an SDK protocol change, not as a transport-specific workaround.

#### The bug

When a bot running on any transport delegates to another bot via the registry:

1. The `PendingDelegation` is saved in the parent session under the transport
   conversation key (e.g., `telegram:12345` or `slack:workspace:channel`)
2. `_coordination_conversation_id()` creates a registry conversation and
   returns a UUID. This UUID is stored as `PendingDelegation.conversation_ref`
3. `RoutedTaskRequest.parent_conversation_id` carries the registry UUID
4. When the child result returns, `delivery_transport.py` derives the parent
   conversation key from `parent_conversation_id` via
   `conversation_key_for_ref()` → produces `registry:conversation:<uuid>`
5. Session lookup under `registry:conversation:<uuid>` finds nothing — the
   session with `PendingDelegation` is stored under the transport key
6. `apply_runtime_delegation_result()` returns `matched=False`, result dropped

The original transport conversation key is not carried through the
delegation protocol. It is lost when `_coordination_conversation_id()`
converts the transport ref to a registry UUID.

#### What already exists

The registry store populates `parent_external_conversation_ref` in the
delivery payload (from `conversations.external_conversation_ref`). The
delivery handler reads this field but uses it only for egress routing and
`TransportIdentity` — NOT for session key lookup.

The completion message at `delivery_transport.py` is suppressed when
`parent_conversation_id.startswith("registry:")`. Since qualified parent refs
always start with `"registry:"`, transport-originated delegations never send
the completion summary.

#### What must change (SDK protocol, not transport-specific patch)

The delegation protocol must carry the originating transport identity
explicitly, end-to-end. This is a data model change in SDK types, a
delivery handler change, and a registry store change. Every transport
benefits — no transport-specific code needed.

**SDK data model:**

- [ ] 11a: Add `origin_conversation_key: str` to `PendingDelegation` in
  `octopus_sdk/sessions.py`. Set when `build_delegation_plan()` /
  `propose_participant_delegation()` creates the pending delegation.
  Value: the transport session key (e.g., `telegram:12345`). The session
  carries its own transport identity — not dependent on registry lookups.

- [ ] 11b: Add `origin_transport_ref: str = ""` to `RoutedTaskRequest` in
  `octopus_sdk/registry/models.py`. Populated with the originating
  transport ref when submitting the task. The protocol is self-describing —
  the registry doesn't need to reverse-lookup the transport ref from its
  conversations table.

- [ ] 11c: Update `build_delegation_plan()` in
  `octopus_sdk/workflows/delegation.py` to accept and store the transport
  conversation key. The caller (execution engine, transport adapter) must
  provide it.

- [ ] 11d: Update `propose_participant_delegation()` and all callers to
  pass the transport conversation key through to `build_delegation_plan()`.
  Trace all call sites — Telegram execution, registry channel, any other
  transport that calls into the delegation flow.

- [ ] 11e: Update routed task submission (SDK `TaskRoutingPort` and
  control plane adapter) to populate `origin_transport_ref` from the
  `PendingDelegation.origin_conversation_key`. The registry store receives
  the transport ref on the wire, not by lookup.

**Registry store:**

- [ ] 11f: Update routed task creation in the registry store (both SQLite
  and Postgres) to persist `origin_transport_ref` from `RoutedTaskRequest`.
  Include it in the `routed_result` delivery payload as
  `parent_transport_ref` (or equivalent explicit field).

- [ ] 11g: Verify `ensure_conversation_id()` correctly populates
  `external_conversation_ref` on the conversation row for
  transport-originated delegations. Fix if needed — this is the existing
  path that the delivery payload relies on as a fallback.

**Delivery handler (`app/channels/registry/delivery_transport.py`):**

- [ ] 11h: Routed-result handler: resolve parent session key using
  `parent_transport_ref` from the delivery payload (the explicit protocol
  field from 11f). Fall back to `parent_external_conversation_ref` (the
  store-lookup field). Fall back to `conversation_key_for_ref(parent_conversation_id)`
  only as last resort for registry-originated delegations.

- [ ] 11i: Resume message: target the transport ref for egress routing and
  `conversation_ref`, not the registry-qualified `parent_conversation_id`.

- [ ] 11j: Completion message: determine whether to send based on the
  transport ref type, not on `parent_conversation_id.startswith("registry:")`.
  If the originating transport is Telegram, send the completion to
  Telegram. If Slack, send to Slack. If registry-originated, handle
  accordingly.

**SDK wiring verification test:**

- [ ] 11k: Add delegation round-trip to the SDK wiring verification test
  in `octopus_sdk/tests/`. The test stub transport must verify that
  `origin_conversation_key` survives the full delegation cycle:
  propose → approve → submit → child execute → result → parent resume.
  The parent session must be found under the original transport key, not
  under a registry-derived key.

**Cross-transport integration test:**

- [ ] 11l: Add cross-transport round-trip integration test (can use the
  test harness, not a live deployment): Telegram transport → registry
  delegation → target bot → result → parent Telegram resume. Verify:
  - `apply_runtime_delegation_result()` finds the correct session
  - Completion message is sent to the Telegram chat
  - Resume prompt lands in the original Telegram chat
  - No conversation key mismatch warnings in logs

- [ ] 11m: Add equivalent test for a stub non-Telegram transport to prove
  the fix is transport-neutral, not Telegram-specific.

**Completed-work revisit (items from Phases 1-10 affected by this gap):**

- [ ] 11n: Phase 4 management protocol: verify that `management_request` /
  `management_result` delivery does NOT have the same identity-loss bug.
  Management requests target a specific agent, not a conversation — but if
  management result delivery uses `conversation_key_for_ref()` anywhere,
  it could have the same mismatch. Audit and confirm clean or fix.

- [ ] 11o: Phase 9 wiring verification test (9e): the existing delegation
  exercise in the wiring test uses stub transport. Verify the stub
  transport sets `origin_conversation_key` on `PendingDelegation` and that
  the delegation round-trip resolves using that key, not a registry-derived
  key. If the current test passes without this (because stubs bypass the
  registry), the test is not catching the bug — extend it.

- [ ] 11p: Phase 8 `BotRuntime` dispatch: verify that the
  `routed_result` dispatch path in `BotRuntime._run_worker_loop()` passes
  the transport ref through to the delegation result handler. If dispatch
  strips or ignores transport identity fields, the fix won't survive the
  runtime.

**Exit gate:**
- Delegation results from any transport are delivered to the correct parent
  session using the originating transport conversation key
- Resume and completion messages target the original transport chat
- `PendingDelegation.origin_conversation_key` carries the transport key
- `RoutedTaskRequest.origin_transport_ref` carries the transport ref on
  the wire
- The registry store persists and returns the transport ref in the delivery
  payload without relying on `conversations.external_conversation_ref`
  reverse-lookup as the primary mechanism
- SDK wiring verification test catches the identity-loss bug
- Cross-transport integration tests pass for Telegram and for a generic
  stub transport
- Management protocol delivery (Phase 4) is confirmed clean of the same bug
- No conversation key mismatch in any delegation round-trip path

## Hard exit criteria

These are immutable.

1. Three packages exist: `octopus_sdk/`, `octopus_registry/`, `app/`.
2. `octopus_sdk/` imports neither `app/` nor `octopus_registry/`.
3. `octopus_registry/` imports only `octopus_sdk/`. Zero `app/` imports.
4. `app/` does not import `octopus_registry/`.
5. Import-graph regression tests lock all three boundaries.
6. Registry server (enrollment, status, UI, management API) is deployable from
   `octopus_registry/` + `octopus_sdk/`.
7. Standalone registry behavior is explicit: when no bot is connected,
   management endpoints return "agent not connected." When a bot is connected
   but does not advertise a capability, endpoints return "capability not
   available." No silent success. No reach into bot code.
8. When a bot is connected, registry management operations execute through
   `management_request` / `management_result` over the existing poll/ack
   delivery system. No new listener or bind on the bot side.
9. All 27 management HTTP endpoints are agent-scoped
   (`/v1/agents/{agent_id}/...`). No global management endpoints that assume
   a single connected bot.
10. Bot deployable from `app/` + `octopus_sdk/`.
11. All 14 workflow Protocol implementations live in `octopus_sdk/workflows/`
    with zero `from app.*` imports. They receive dependencies through
    constructor-injected SDK Ports.
12. All 4 backend-neutral FSMs live in `octopus_sdk/workflows/`.
13. `TransportDispatcher` lives in `octopus_sdk/`.
14. `WorkflowComposer` exists in the SDK and assembles all workflow
    implementations from injected Ports through a builder API.
15. SDK provides `InMemoryWorkQueue` and `InMemorySessionStore` in
    `octopus_sdk/testing/` — test-only, deliberately non-durable, raises
    `NotImplementedError` on persistence-guarantee methods. NOT runtime
    defaults. NOT developer templates.
16. `WorkflowComposer` required ports (`MessageTemplatePort`,
    `SessionRuntimePort`, `WorkQueuePort`, `BotConfigBase`) fail at
    `.build()` time if not provided. Optional ports fail loudly with
    `NotConfiguredError` on any method call. No silent no-ops.
    `.build()` rejects `octopus_sdk.testing.*` implementations.
    `.build_for_testing()` accepts them and marks the composition as
    test-only. `BotRuntime` refuses to start with a test-only composition
    unless explicitly overridden.
17. Bots advertise management capabilities (`skill_catalog`,
    `skill_lifecycle`, `provider_guidance`, `conversation_skills`) at
    registration time based on which optional ports were wired in
    `WorkflowComposer`.
18. Bot-side management executor in SDK handles `management_request`
    deliveries: routes to correct workflow, handles session load/save locally
    for Tier E operations, returns `ManagementResult`.
19. `ingress.py` in `octopus_registry/` is rewritten against the management
    protocol. Zero `app.*` imports. Translates HTTP calls to
    `ManagementRequest` envelopes.
20. `app/registry_service/` does not exist.
21. `ui/` at repo root does not exist.
22. `app/workflows/` contains only Telegram-specific handlers and `__init__`
    files. Zero backend-neutral orchestration logic.
23. `BotRuntime` has no `WorkerDispatchPort` or equivalent injection.
24. The SDK wiring verification test exercises full workflow lifecycle using
    real SDK implementations, `WorkflowComposer`, and test utilities from
    `octopus_sdk/testing/` with zero `app/` and `octopus_registry/` imports.
    It is a pytest, not a developer template or example.
25. `app/` does not import `octopus_sdk.testing`. Production code must not
    depend on test utilities.
26. `octopus_registry/` does not import `octopus_sdk.testing`.
27. `octopus_sdk/testing` is not re-exported from `octopus_sdk/__init__.py`
    or any other convenience surface.
28. `WorkQueuePort` and `SessionRuntimePort` encode durability expectations
    in their method surface (not just docs) so that test implementations
    can structurally fail on durability operations.
29. `PendingDelegation` stores `origin_conversation_key` — the transport
    conversation key that the delegation was initiated from. The round-trip
    identity is self-contained in the session, not dependent on registry
    store lookups.
30. `RoutedTaskRequest` carries `origin_transport_ref` — the transport
    ref alongside `parent_conversation_id`. The protocol is self-describing.
31. Delegation result handler resolves the parent session using the transport
    conversation key (from `parent_external_conversation_ref` or
    `PendingDelegation.origin_conversation_key`), not from
    `conversation_key_for_ref(parent_conversation_id)`. Resume and
    completion messages target the original transport chat.
32. Cross-transport delegation round-trip test passes: Telegram → registry
    delegation → target bot → result → parent Telegram resume.
33. `app/runtime/composition.py` is a thin app-specific wrapper over
    `WorkflowComposer`. It does not own business logic.
34. Every file moved from `app/` is deleted in the same change.
35. No exit criterion has been weakened, qualified, or removed.

## Dependencies

```
Phases 1–10: COMPLETE (see status.md)
Phase 11 (delegation protocol transport identity) — new work, builds on completed architecture
```

- Phases 1-10 are complete
- Phase 11 depends on the completed architecture (especially Phase 4
  management protocol and Phase 8 BotRuntime dispatch) but does not
  invalidate any completed phase — it extends the SDK protocol
- Phase 11 items 11n-11p revisit completed phases to verify they are
  not affected by the same identity-loss pattern

## Developer prompt

```text
Separate the Octopus codebase into three packages as defined in PLAN-sdk-4.md.

Read the ENTIRE plan first, especially the inventory tables, missing SDK pieces,
and the target-boundary section.

The architecture is:
- octopus_sdk = contracts, business logic, workflow composition, test/runtime utilities
- octopus_registry = management plane
- app = Telegram bot product with no management API of its own

Phases 1-10 are COMPLETE. The three-package architecture is in place.

Phase 11 is the remaining work. It fixes a structural bug in the SDK
delegation protocol: the originating transport conversation key is lost
during the delegation round-trip. This affects ANY transport, not just
Telegram. A Slack developer using the SDK would hit the same bug.

The fix is an SDK protocol change — add origin_conversation_key to
PendingDelegation, add origin_transport_ref to RoutedTaskRequest, fix the
delivery handler to resolve the parent session using the transport key,
update the registry store to persist and return the transport ref in the
delivery payload. Also revisit Phase 4 management protocol, Phase 8
BotRuntime dispatch, and Phase 9 wiring test to verify they are not
affected by the same identity-loss pattern.

Phase 11 checklist has 16 items (11a through 11p):
- 11a-11e: SDK data model changes (PendingDelegation, RoutedTaskRequest,
  build_delegation_plan, all callers, task submission)
- 11f-11g: Registry store changes (persist transport ref, verify
  ensure_conversation_id)
- 11h-11j: Delivery handler changes (session lookup, resume target,
  completion suppression)
- 11k-11m: Tests (SDK wiring verification, cross-transport integration,
  generic stub transport)
- 11n-11p: Revisit completed phases (management protocol, wiring test,
  BotRuntime dispatch)

For reference, the completed architecture phases were:

Phase 2 — Define the missing SDK Ports for service dependencies.

Phase 3 — Refactor and move the 14 workflow implementations to SDK.

Phase 3.5 — Add WorkflowComposer and SDK in-memory runtime/test utilities.
Use a builder pattern. Required ports fail at build time. Optional capabilities
fail loudly when not configured. No silent no-ops.

Phase 4 — Define the registry management protocol. 27 operations across 4
tiers (19 pure workflow, 2 workflow+provider, 1 workflow+config, 4
session-backed). Use management_request/management_result over existing
poll/ack delivery. All management endpoints become agent-scoped
(/v1/agents/{agent_id}/...). Bots advertise management capabilities at
registration. Session management stays bot-side.

Phase 5 — Rewrite ingress.py against the management protocol (this is a
rewrite, not a move). Migrate http.py routes to agent-scoped. Fix auth.py
and http.py remaining entanglements.

Phase 6 — Extract the registry server to octopus_registry/.

Phase 7 — Verify bot config/entrypoint remain bot-only.

Phase 8 — Eliminate WorkerDispatchPort. BotRuntime dispatches to SDK
workflows natively. Do NOT delete telegram_shared_dispatch.py — that is
Telegram transport code, not worker dispatch.

Phase 9 — SDK wiring verification test. Uses real SDK workflow implementations
and test-only utilities from octopus_sdk/testing/. This is a pytest, not a
developer template. Test utilities are deliberately non-durable and raise on
persistence-guarantee methods. Compositions with test implementations are
marked test_mode=True.

Phase 10 — Verify exit criteria 1-28 and 33-35. (Criteria 29-32 are Phase 11.)

Phase 11 — Fix delegation protocol transport identity. 16 items (11a-11p).
Exit criteria 29-32. This is not a Telegram-specific patch — it is an SDK
protocol change that makes delegation round-trip identity explicit for any
transport. Revisit Phase 4, 8, and 9 deliverables for the same identity-loss
pattern.

Non-negotiables:
- Three packages with locked import boundaries
- Constructor injection, not singleton imports, in SDK workflow code
- Registry management uses management_request/management_result over poll/ack
- All management endpoints are agent-scoped (/v1/agents/{agent_id}/...)
- Session management stays bot-side — protocol is request/response
- Standalone registry operation must be explicit, not magical
- WorkflowComposer required ports fail at build, optional ports raise NotConfiguredError
- Test utilities in octopus_sdk/testing/ are NOT production defaults
- app/ and octopus_registry/ must not import octopus_sdk.testing
- Each moved file deleted from source in same change
- telegram_shared_dispatch.py is Telegram transport code, stays in app/
- Delegation protocol carries transport identity explicitly on the wire — no
  reverse-lookups from registry store, no transport-specific patches
- Delegation fixes must be transport-neutral — a Slack developer must not hit
  the same bug
- Exit criteria are immutable
- Do not modify this plan
```

## Final standard

Three packages. Three clean boundaries. Three independent deployables.

The SDK contains contracts, business logic, and composition. A developer
installs it, writes their transport and storage/port implementations, and
has a working bot. They don't clone `app/`. They don't clone
`octopus_registry/`. Test utilities exist in `octopus_sdk/testing/` for
wiring verification only — they are not production defaults and not
developer templates.

Every workflow implementation in the SDK receives its dependencies through
constructor-injected Ports. No singleton imports. No `from app.*`.

The registry server is the management plane. It deploys standalone. It manages
whichever bots connect — Telegram, Slack, or any future transport. Management
endpoints are agent-scoped. Management operations cross the connection through
`management_request` / `management_result` over the existing poll/ack delivery
system. The bot has no management server of its own.

When no bot is connected, the registry says so explicitly. When a bot connects
but doesn't support a capability, the registry says that explicitly too. No
hidden single-bot assumptions. No silent failures.

The delegation protocol carries the originating transport identity
explicitly — `PendingDelegation.origin_conversation_key` and
`RoutedTaskRequest.origin_transport_ref`. Delegation results are delivered to
the correct parent session regardless of which transport initiated the
delegation. No registry store reverse-lookups. No transport-specific patches.

The registry server is its own package. The bot is its own package. The SDK
is the shared contract.

Exit criteria are immutable.
