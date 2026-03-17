# Runtime Skills / Content System Plan

## Goal

Finish the runtime-skill and provider-guidance refactor with the correct long-
term architecture:

- one durable content model
- one application/use-case layer
- no old-path compatibility shims
- no surface-owned business logic
- no confusion between runtime skills and registry routing capabilities

This plan is grounded in the code as it exists after:

- capability split
- shared lifecycle service extraction
- registry runtime-skill API/UI addition
- content-store foundation
- hard cutover of runtime skills to the content store
- confidence-suite rewrite

## Current Position

### Already complete

These are no longer future work:

1. Runtime skills and registry routing capabilities are separated.
2. Shared service seams exist for:
   - `SkillCatalogService`
   - `SkillActivationService`
   - `SkillLifecycleService`
   - `SkillImportService`
   - `ProviderGuidanceService`
   - `CapabilityService`
3. Registry exposes runtime-skill APIs under a separate namespace:
   - `/v1/catalog/skills/...`
   - `/v1/conversations/{conversation_key}/skills/...`
   - `/v1/provider-guidance/...`
4. Registry UI has an initial runtime-skill surface.
5. Content-store foundation exists with SQLite/Postgres parity.
6. Runtime skill reads are cut over to the content store.
7. Confidence suites were rewritten around the content-store model.

### Regressions/shortcuts already found during execution

These findings must shape all future work:

1. Registry artifact digest verification was lost during the cutover.
   - Fixed.
   - Lesson: migration of storage/location must preserve contract checks.

2. SQLite content-store access was not thread-safe under `asyncio.to_thread`.
   - Fixed.
   - Lesson: runtime call patterns matter as much as interface shape.

3. Old file-backed logic survived in hidden helpers after the hard cutover.
   - normalization
   - execution-context hashing
   - health/setup behavior
   - fixed
   - Lesson: “main path is migrated” is not enough; helper audits are required.

4. Some tests were still proving deleted architecture.
   - Fixed by rewriting suites instead of adding compatibility.
   - Lesson: a green suite can still be wrong.

5. Docker/Postgres harness storage pressure can cause false red.
   - Not product code, but a real verification risk.
   - Lesson: test infrastructure must preserve signal.

## Non-Negotiable Principles

- One abstraction, multiple implementations.
- No parallel paths for the same concern.
- No backward-compatibility shims that keep old runtime paths alive.
- Interfaces before implementations.
- Extend before inventing.
- The shared use-case boundary must be modular and concern-owned, not a god-service.
- Registry is the only public HTTP API.
- Registry UI, Telegram UI, and future surfaces must share the same application/use-case layer.
- Bot runtime uses shared services in-process, not registry HTTP, for runtime reads and mutations.
- Registry UI uses registry HTTP APIs for all mutations.
- Telegram remains a first-class UI surface.
- Capability parity across Telegram and registry.
- Content store is the durable source of truth.
- SQLite/Postgres parity is required in the same slice.
- Use battle-tested libraries for generic infrastructure.

## Clean Conceptual Model

There are four distinct layers. These must not be collapsed again.

### 1. Domain services

Pure business logic and durable-state rules.

Examples:

- `SkillCatalogService`
- `SkillActivationService`
- `SkillLifecycleService`
- `SkillImportService`
- `ProviderGuidanceService`
- `CapabilityService`

### 2. Application / use-case boundary

This is the canonical **inbound interaction abstraction**.

It is not one central class or mega-service. It is a set of small,
concern-owned use-case modules with typed contracts.

Examples:

- `skills_catalog_use_cases`
- `skills_activation_use_cases`
- `skills_authoring_use_cases`
- `skills_approval_use_cases`
- `provider_guidance_use_cases`
- `conversation_control_use_cases`

Those modules own typed operations such as:

- list skills
- get skill detail
- create draft
- edit draft
- submit approval
- approve/reject
- publish/archive
- install/update/uninstall
- activate/deactivate/clear
- preview provider guidance
- edit provider guidance

This boundary is the actual abstraction that all inbound surfaces must share.
Adding a new surface should require:

- a new surface adapter
- surface-specific rendering/input translation

and should **not** require redesigning the concern-owned use-case modules unless
the product capability itself changes.

### 3. Surface adapters

These translate surface-native input into canonical use-case calls.

They are **not** the use-case layer.

- Telegram UI adapter
- Registry API adapter
- future Slack adapter

Registry UI is not a sibling adapter here; it is a client of the registry API.

### 4. Outbound transport adapters

These render/send replies and surface events:

- Telegram adapter
- Registry adapter
- future Slack adapter

This is a separate concern from inbound interaction.

## Critical Clarification: API vs UI vs Adapter

The correct model is:

- **Registry API** is an adapter over the shared application/use-case layer.
- **Telegram UI** is another adapter over the same application/use-case layer.
- **Registry UI** is a client of the registry API.
- **Outbound transport adapters** are separate and do not solve inbound interaction.

This means:

- Telegram should **not** call registry HTTP for normal runtime mutations.
- Standalone bots remain viable because Telegram can call the shared use-case layer directly.
- Registry remains the only public programmatic HTTP surface.

## Clean Domain Names

### A. Runtime Skills

End-user bot skills:

- debugging
- code-review
- github-integration
- etc.

These affect:

- prompt composition
- provider config
- requirements
- helper scripts
- `/skills`

### B. Provider Runtime Guidance

Runtime provider instructions for the bot:

- Claude guidance
- Codex guidance

### C. Routing Capabilities

Registry discovery/routing traits for agents.

These are not runtime skills and must never be merged back together.

Use these names consistently:

- `skills` = runtime skills
- `capabilities` = routing/discovery traits

## Architecture Rules

### 1. Outbound transport abstraction is not inbound interaction abstraction

[app/transports/ports.py](/Users/tinker/output/bots/telegram-agent-bot/app/transports/ports.py)
and
[app/transports/telegram_adapter.py](/Users/tinker/output/bots/telegram-agent-bot/app/transports/telegram_adapter.py)
solve outbound delivery and rendering.

They do **not** solve inbound lifecycle abstraction.

Do not mistake:

- “we have a transport adapter”

for:

- “we have clean inbound surface architecture”

### 2. Registry UI, Telegram UI, and registry API must meet at the use-case layer

The application/use-case layer is the canonical inbound abstraction.

Rules:

- registry API adapts HTTP into typed use-cases
- Telegram adapts commands/callbacks/messages into typed use-cases
- registry UI performs all mutations through registry APIs
- no business workflow logic lives in handlers, routes, or browser JS
- do not collapse all inbound behavior into one monolithic orchestrator

### 3. Registry is the only public API, not the only UI

Registry owns the public HTTP/programmatic API.
Telegram remains a first-class user UI surface.
Standalone bots continue to work because Telegram talks to the use-case layer directly.

### 4. No old-path resurrection

Do not add:

- file fallback if content store is empty
- direct repo catalog reads in runtime logic
- filesystem custom/managed fallback reads
- dual-read logic
- migration shims that become permanent

### 5. Extend before inventing

Before adding a new module or abstraction:

- find the existing seam that already owns the concern
- extend it if possible
- if no seam exists, define the interface/protocol first

Do not add a concrete-only shortcut that bypasses an existing boundary.

### 6. Interfaces before implementations

Every new pluggable component must have a Protocol or ABC first.

Orchestration/use-case code imports:

- the protocol
- not the concrete implementation

### 7. No hand-rolled infrastructure

Use battle-tested libraries for generic concerns:

- `psycopg` / `psycopg_pool`
- `pydantic`
- `python-statemachine`
- `starlette` sessions
- CodeMirror 6 for web editing

Do not invent bespoke frameworks for these concerns.

## Repeated Failure Patterns To Guard Against

These come directly from the backed-up project guidance and from the recent cutover.

1. Parallel path drift.
   - command vs callback
   - Telegram vs registry
   - approval vs retry
   - normal vs recovery

2. Raw state instead of resolved state.
   - `session.active_skills` instead of resolved skills
   - raw config/session in user-visible or safety-sensitive paths

3. Test doubles not matching production shape.

4. Testing implementation instead of contracts.

5. Component isolation hiding interaction bugs.

6. Subprocess and resource leaks.

7. Decorator/wrapper swallowing behavior.

8. Leaking internals to users.

9. State-transition accounting failures.

10. Completion-owner drift.

11. Hidden stale helper reads after major cutovers.

12. Surface-specific logic leaking into orchestration/use-case layers.

13. Half-migrated contract changes.

14. False “queueing” that is really rejection.

15. Recovery path re-entering itself and creating loops.

## Current Risks Still Open

### 1. `app/telegram_handlers.py` is still too much of the system

This is the biggest remaining architecture problem.

It currently mixes:

- Telegram command parsing
- callback routing
- request orchestration
- lifecycle/UI branching
- worker action dispatch
- app wiring
- surface decisions
- domain decisions

That means it is **not** a clean transport implementation.
It is a Telegram-shaped orchestration monolith.

This must be refactored until it is structurally correct, not merely smaller.

### 2. Registry API and UI are better, but still too concentrated

[app/registry_service/app.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/app.py)
currently mixes:

- HTTP routes
- HTML shell
- browser JS
- runtime-surface bridging
- some lifecycle shaping

This is directionally better than Telegram, but still too monolithic.

### 3. Seed assets still leak through old repo layout

[app/content_seed.py](/Users/tinker/output/bots/telegram-agent-bot/app/content_seed.py)
still reads via top-level repo skill paths through
[app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py)
`CATALOG_DIR`.

This is acceptable only as a temporary seed-input mechanism.

### 4. Dead file-store code still exists

[app/store.py](/Users/tinker/output/bots/telegram-agent-bot/app/store.py) still
contains historical bundled-store/file-store logic that no longer owns runtime
truth.

That code should be deleted, not bypassed forever.

### 5. Lifecycle completion is still partial

The current system supports content-store-backed read/install/update/uninstall/diff,
but not the full intended lifecycle:

- create draft
- edit draft
- revisions/history
- submit approval
- approve/reject
- publish/archive
- provider-guidance editing lifecycle

### 6. Surface parity is not yet real

Telegram remains first-class in principle, but not yet in actual lifecycle capability.

Registry currently has richer support than Telegram for the new lifecycle.
That is only acceptable as an in-progress state.

## Stage Plan

### Stage 1. Define and land the real use-case layer

#### Goal

Make the shared inbound interaction abstraction explicit, modular, and
concern-owned.

#### Required work

- define the canonical typed use-cases/commands for runtime-skill and provider-guidance lifecycle
- make it clear which operations belong there
- ensure both Telegram and registry API are adapters to this layer
- split the use-case boundary by concern instead of centralizing all behavior
  in one orchestrator

#### Watchouts

- do not confuse service methods with full use-cases if the workflow spans multiple services
- do not let HTTP or PTB types leak into use-case inputs
- do not let browser JS become a second workflow engine
- do not build a single mega-service that every inbound action must pass through

#### Success criteria

- one explicit inbound interaction abstraction exists
- Telegram and registry API both map into it
- the abstraction is composed of small concern-owned use-case modules, not one monolith

### Stage 2. Refactor Telegram into a true surface adapter

#### Goal

Turn [app/telegram_handlers.py](/Users/tinker/output/bots/telegram-agent-bot/app/telegram_handlers.py)
into a proper Telegram adapter over shared use-cases.

#### Required work

- pull workflow/business logic out of Telegram handlers
- leave:
  - PTB edge parsing
  - Telegram-specific rendering
  - adapter glue
- move shared lifecycle branching into the use-case layer

#### Watchouts

- do not move PTB types into domain code
- do not keep “just one more special case” in `telegram_handlers.py`
- audit command, callback, approval, retry, admin, CLI-equivalent, and recovery parity

#### Success criteria

- `telegram_handlers.py` is no longer the place where domain workflows live

### Stage 3. Refactor registry API/UI into the same shape

#### Goal

Make the registry API a clean adapter over the use-case layer, and the registry UI a client of those APIs.

#### Required work

- thin API routes
- move HTML/JS concerns out of overly concentrated route modules where reasonable
- ensure browser UI performs mutations only through the registry APIs

#### Watchouts

- do not add server-side UI-only shortcuts that bypass the API
- do not put business rules in browser JS
- keep API validation and lifecycle semantics authoritative on the server

#### Success criteria

- registry API is a thin adapter
- registry UI is an API client, not a bypass

### Stage 4. Complete runtime-skill and provider-guidance lifecycle

#### Goal

Support the full content lifecycle.

#### Required work

- create draft
- edit draft
- revisions/history
- submit approval
- approve/reject
- publish/archive
- provider-guidance lifecycle with the same rigor

#### Watchouts

- do not put approval logic in surface code
- keep built-in/imported immutable
- custom shared visibility remains approval-gated
- use resolved state, not raw session/config state

#### Success criteria

- services/use-cases fully own lifecycle behavior

### Stage 5. Add rich registry editing

#### Goal

Give registry UI rich editing without creating another logic path.

#### Required work

- CodeMirror 6 integration
- skill draft editing
- provider-guidance editing
- diff/history UI
- approval UI

#### Watchouts

- UI richness must not become UI-owned business logic
- keep the same mutation semantics as Telegram/API

#### Success criteria

- registry UI is richer in presentation, not richer in capability

### Stage 6. Bring Telegram to capability parity

#### Goal

Telegram supports the same lifecycle operations as registry/API through chat-native UX.

#### Required work

- guided draft editing
- revision/history flow
- approval/publish/archive flow
- provider-guidance flow if in scope
- attachment/import support alongside guided editing

#### Watchouts

- do not accept “registry can do it, Telegram can’t” as architecture
- parity means operations and outcomes, not identical controls
- do not reintroduce file-based authoring because chat UX is harder

#### Success criteria

- Telegram and registry expose the same lifecycle capability set

### Stage 7. Remove remaining old seed/store residue

#### Goal

Delete dead architecture and move seed assets into the final app-owned location.

#### Required work

- move seed assets under `app/`
- stop seeding through top-level repo catalog paths
- delete dead file-store/bundled-store code in
  [app/store.py](/Users/tinker/output/bots/telegram-agent-bot/app/store.py)
- remove stale helpers and docs that still imply the old model

#### Watchouts

- do not leave dead code “for now”
- do not leave old terminology that implies filesystem runtime truth
- do not leave tests touching deleted concepts

#### Success criteria

- no live or seed-time dependency on top-level runtime skill directories
- no dead file-store lifecycle code in normal runtime modules

## Cross-Stage Audit Checklist

At the end of every stage, explicitly audit for:

1. Hidden old-path reads
   - repo file helpers
   - filesystem custom/managed helpers
   - stale digest/hash helpers

2. Surface logic drift
   - Telegram path doing one thing
   - registry path doing another

3. Naming drift
   - runtime skill
   - capability
   - provider guidance

4. Service/use-case ownership drift
   - business logic sliding back into handlers, routes, or browser JS

5. Contract blast radius
   - every consumer of changed statuses, return types, or state transitions updated together

6. Resource and process cleanup
   - subprocesses killed and awaited
   - DB handles closed
   - no leaked descriptors on error paths

7. User-facing language discipline
   - no provider names
   - no internal IDs
   - no implementation terminology

8. Test relevance
   - are tests still proving the current architecture, or a deleted one?

## Durable Workflow Rules

These remain mandatory for any queue/recovery/runtime-state changes in adjacent work:

- queueing is a first-class runtime contract, not a polite rejection
- stale-claim detection is age-based, not worker-based
- transport contract changes require full blast-radius audit
- durable queue changes require FSM and invariant review first
- recovered claimed work is replay-notice only, never auto-rerun
- completion ownership must be explicit whenever semantics change

## Immediate Next Slice

The next implementation slice should be:

1. define the explicit use-case layer
2. refactor Telegram into a real adapter over it
3. refactor registry API/UI to the same shape
4. then complete lifecycle and parity work
5. then delete the remaining old seed/store residue

## Acceptance Criteria For This Plan

This plan is satisfied only when:

- runtime skills, provider guidance, and capabilities are cleanly separated
- registry UI uses registry APIs for all mutations
- registry API and Telegram are both adapters over the same use-case layer
- the shared use-case boundary is modular and concern-owned, not a monolithic orchestrator
- no parallel old/new content paths exist
- `telegram_handlers.py` is no longer a domain-orchestration monolith
- registry route/UI modules are no longer excessively concentrated
- Telegram and registry both implement the same lifecycle capabilities
- content store is the sole durable source of runtime skill/guidance truth
- seed inputs live under `app/`, not as top-level runtime clutter
- dead file-store code is removed, not merely bypassed
