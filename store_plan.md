# Runtime Skills / Content System Plan

> Sealed historical artifact on 2026-03-17.
>
> The plan content below this note and above the `Replacement Plan (Active)` marker
> is preserved as a historical record of the previous planning iteration.
> It is no longer the authoritative execution plan.
> Do not mutate the sealed section except to annotate it as historical.

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
8. Modular runtime-skill use-case modules now exist for:
   - catalog reads/draft creation
   - activation/setup/clear flows
   - import/update/uninstall/diff
   - provider-guidance preview
9. Additional concern-owned inbound modules now exist for:
   - conversation settings mutations
   - conversation reset/cancel control
   - pending approval/retry decisions
   - recovery replay/discard preparation
10. Registry runtime-skill and guidance routes now go through a dedicated
    runtime-surface adapter module rather than loading/saving runtime sessions
    directly inside `registry_service/app.py`.

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

6. Adapter-owned setup workflow logic survived after the initial use-case split.
   - `telegram_handlers.py` still kicked off credential setup, cancelled setup,
     and cleared setup side effects directly.
   - Fixed by moving those decisions into `RuntimeSkillSetupUseCases`.
   - Lesson: extracting the “main” use-cases is not enough; setup/cancel side
     paths must move too.

7. Optional filter defaults can silently break shared workflow checks.
   - `foreign_setup()` used `""` instead of `None` for the optional skill filter
     and therefore suppressed real foreign-setup detection.
   - Fixed.
   - Lesson: optional workflow filters must use explicit `None` semantics, not
     sentinel strings.

8. Adapter test seams still matter after workflow extraction.
   - Handler tests intentionally patch credential validation at the Telegram
     adapter boundary.
   - Preserved by keeping validation injectable when the adapter calls the use-case.
   - Lesson: move workflow ownership out of the surface, but keep legitimate
     adapter dependency seams available for testing and rendering.

9. Naming workarounds can hide structural drift.
   - Import aliasing fixed a route/helper name collision, but it made the
     adapter boundary look like two implementations.
   - Fixed by renaming the HTTP entrypoints to explicit `api_...` adapter names
     and keeping the runtime-surface helper names canonical.
   - Lesson: local naming shortcuts can obscure whether there is truly one path.

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

Progress made:

- runtime-skill catalog/import/activation/setup flows no longer own their core
  business decisions in Telegram handlers
- Telegram still owns too much non-skill workflow orchestration and application wiring

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

1. finish refactoring Telegram into a real adapter for the remaining inbound workflows
2. refactor registry API/UI to the same shape for those workflows
3. then complete the missing lifecycle:
   - draft editing
   - revisions/history
   - submit approval
   - approve/reject
   - publish/archive
   - provider-guidance management
4. then add rich registry editing
5. then bring Telegram to full lifecycle capability parity
6. then delete the remaining old seed/store residue

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

---

# Replacement Plan (Active)

## Purpose

This is the authoritative plan going forward.

It replaces the sealed historical plan above and is explicitly shaped by:

- [AGENTS.md](/Users/tinker/output/bots/backups/telegram-agent-bot-internal-cleanup-20260316-221803/AGENTS.md)
- [CLAUDE.md](/Users/tinker/output/bots/backups/telegram-agent-bot-internal-cleanup-20260316-221803/CLAUDE.md)
- [SKILLS.md](/Users/tinker/output/bots/backups/telegram-agent-bot-internal-cleanup-20260316-221803/SKILLS.md)
- [docs/CLAUDE-global.md](/Users/tinker/output/bots/backups/telegram-agent-bot-internal-cleanup-20260316-221803/docs/CLAUDE-global.md)
- [docs/AGENTS-global.md](/Users/tinker/output/bots/backups/telegram-agent-bot-internal-cleanup-20260316-221803/docs/AGENTS-global.md)

This plan assumes:

- we keep valid work already completed
- we rebuild compromised seams cleanly
- we do not add new lifecycle features until the foundation gates pass

## Executive Summary

The current refactor made real progress, but some of it sits on incomplete
foundations. The most expensive remaining risks are:

1. the inbound use-case layer has no explicit Protocol/ABC boundary
2. [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py) still owns critical runtime-skill and credential concepts
3. the credential subsystem is still split across multiple modules
4. resolved active skills are not yet the only authority
5. [app/skill_commands.py](/Users/tinker/output/bots/telegram-agent-bot/app/skill_commands.py) remains a hidden orchestration seam

The correct response is not to restart from scratch. It is to:

- freeze feature expansion
- lay the missing foundations properly
- delete the compromised seams
- then resume lifecycle work

## Non-Negotiable Global Rules

These apply to every stage and milestone.

1. One authoritative source per concept.
2. No parallel paths for the same concern.
3. No backward-compatibility shims that keep bad architecture alive.
4. Interfaces before implementations.
5. Extend before inventing.
6. Use resolved context as authority, not raw session/config reads, in business logic.
7. Adapters do parsing, persistence handoff, and rendering only. They do not own workflow logic.
8. Registry UI performs all mutations through registry APIs.
9. Telegram does not call registry HTTP for normal runtime mutations.
10. The shared inbound boundary must be modular and concern-owned, not a god-service.
11. New surfaces must require only a new adapter plus rendering/input translation.
12. Durable state owns correctness. In-memory state is optimization only.
13. Equivalent ingress paths must be audited before and after each nontrivial change.
14. Stale tests never justify escape hatches for bad architecture.

### Stale Test Rule

This is a hard rule:

- stale tests do not justify compatibility shims
- stale tests do not justify keeping old authorities alive
- stale tests do not justify adapter-owned workflow logic
- if a test encodes deleted or invalid architecture, the test must be rewritten or removed in the same slice
- only tests that prove the intended contract at the correct boundary may constrain the design

### Contract-First Rule

Before each nontrivial implementation slice, write and verify:

- contract being changed
- authoritative source
- affected entry points from `rg`
- durable and in-memory state touched
- failure paths
- invariants
- exact real-boundary tests
- adjacent regression case

If this cannot be stated clearly, the slice is not ready.

## Authoritative Domain Model

### 1. Runtime Skills

Owns:

- skill identity
- revisions
- files
- requirement schema
- provider config
- activation eligibility metadata

### 2. Provider Runtime Guidance

Owns:

- provider-specific runtime instructions
- revisions
- effective previews

### 3. Credentials

Owns:

- credential storage
- validation
- satisfaction checks
- environment materialization
- setup/clear lifecycle state transitions

### 4. Capabilities

Owns:

- registry routing/discovery traits
- capability search/override

Capabilities are not runtime skills and must never be merged back together.

## Seam Inventory

Before implementation in any milestone, each concern must have a named owner.

| Concern | Authoritative owner | Current risk to eliminate |
|---|---|---|
| Skill catalog / instructions | Content store + runtime skill services | Residual old helper coupling |
| Provider guidance | Content store + ProviderGuidanceService | Prompt/config assembly still lives in or is coupled to `app/skills.py` until Milestone 5 closes it |
| Runtime skill types | Canonical skill types module | `SkillRequirement` / `SkillMeta` still tied to `app/skills.py` |
| User credentials | Credential store + credential services/use-cases | Still fragmented and filesystem-helper-owned |
| Credential validation | Credential subsystem | Still scattered across old helpers and request flow |
| Prompt/config assembly | ProviderGuidanceService | Must not remain in `app/skills.py` |
| Codex script staging | Codex provider | Provider-specific concern is still in the wrong module until Milestone 5 moves it |
| Filesystem skill fallback | None; seeder replaces it | `app/store.py` / old fallback residue must be deleted |

## Correct Layer Model

### Layer 1. Domain types and contracts

Every shared or pluggable boundary gets a Protocol/ABC first.

Required targets:

- runtime skill type contracts
- credential type contracts
- runtime skill use-case ports
- credential use-case ports
- provider guidance use-case ports
- capability ports where needed

### Layer 2. Durable stores

- content store for runtime skills and provider guidance
- credential store
- registry store
- session store

Stores persist/query only. No workflow logic.

### Layer 3. Domain services

Concern-owned services only:

- skill catalog
- skill lifecycle
- skill import
- provider guidance
- credentials
- capabilities

### Layer 4. Application/use-case modules

This is the canonical inbound abstraction.

It must be:

- modular
- concern-owned
- typed by contracts
- independent of Telegram/FastAPI types

Minimum expected modules:

- currently existing / current-workflow modules:
- runtime skill catalog use-cases
- runtime skill activation use-cases
- runtime skill import use-cases
- runtime skill setup use-cases
- credential management use-cases
- conversation control use-cases
- conversation settings use-cases
- pending request use-cases
- recovery use-cases
- provider guidance use-cases

- future lifecycle modules, introduced only after the lifecycle schema gate:
- runtime skill authoring use-cases
- runtime skill approval use-cases

### Layer 5. Surface adapters

- Telegram inbound adapter
- Registry API adapter

Registry UI is not a peer adapter. It is a client of the registry API.

### Layer 6. Outbound transport adapters

- Telegram outbound surface
- Registry outbound surface
- future Slack outbound surface

Inbound and outbound remain separate concerns.

## What We Keep

These are valid and should be preserved:

- content-store foundation
- runtime skills vs capabilities separation
- registry runtime skill namespace
- content-store hard cutover for runtime skill reads
- content-store contract coverage
- confidence-suite rewrite where it proves the new architecture
- the existing concern-owned modules that already align with this plan

## What Must Be Rebuilt

These are no longer acceptable as-is:

- concrete-only shared use-case boundary
- credential ownership spread across modules
- `SkillRequirement` living in [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py)
- resolved active skills falling back to raw session values in business logic
- hidden orchestration in [app/skill_commands.py](/Users/tinker/output/bots/telegram-agent-bot/app/skill_commands.py)
- lingering authority in [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py)

## Execution Plan

### Milestone 0. Freeze Feature Expansion

No new lifecycle feature work lands until Milestones 1-5 pass.

Blocked features:

- draft editing
- revision/history
- submit approval
- approve/reject
- publish/archive
- provider-guidance management UI
- rich registry editor
- Telegram lifecycle parity expansion

#### Hard rules

- do not add new user-facing lifecycle behavior during this milestone
- do not “sneak in” convenience helpers that deepen the wrong seams
- do not use temporary bridges that keep old authorities alive

#### Exit criteria

- the repo and plan both clearly state that foundation work is blocking feature expansion
- any known red baseline test that proves a real durable contract bug must be resolved or explicitly reclassified before the milestone that touches that contract

### Milestone 1. Define Ports for the Inbound Boundary

Create Protocol/ABC contracts for the use-case layer before more feature work.

These contracts are required for:

- signature enforcement
- test injection seams
- preventing PTB/FastAPI types from leaking into use-case boundaries
- making Telegram and registry prove they call the same application contracts

They are not justified by “multiple interchangeable implementations of every use-case.”

#### Work

- define use-case ports for currently existing shared inbound workflows only
- ensure adapters depend on ports, not concrete implementations
- provide builders/factories for concrete wiring

This milestone does **not** define contracts for future lifecycle concerns that
do not exist yet. Authoring and approval lifecycle ports are introduced only
when the lifecycle schema is defined and those workflows are concrete.

#### Hard rules

- no single mega `UseCases` interface
- no Telegram/FastAPI/PTB types in use-case signatures
- no new concrete shared module without a port
- no adapter importing concrete implementation modules directly
- no “minimal protocol” that omits real workflow inputs/outputs just to satisfy the rule superficially

#### Watchouts

- a shared use-case layer must not become a monolith
- naming must reveal the boundary clearly

#### Exit criteria

- Telegram and registry adapter code import use-case ports/contracts
- concrete implementations are instantiated behind composition/factory code
- the contracts are complete enough to express the current shared workflows without adapter-side business branching
- future lifecycle workflows are not prematurely frozen into incomplete contracts

### Milestone 2. Establish Authoritative Runtime-Skill and Credential Types

Move authoritative types out of [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py).

#### Work

- create authoritative homes for runtime skill types
- create authoritative homes for credential-related types
- move `SkillRequirement` and related ownership out of `app/skills.py`

#### Hard rules

- no duplicate transitional dataclasses with conversion glue as a permanent seam
- no second authoritative home “for now”
- no continued import of authoritative types from `app/skills.py`

#### Watchouts

- types that seem “small” still create parallel authority if duplicated

#### Exit criteria

- `SkillRequirement` no longer lives in `app/skills.py`
- services/use-cases import the new authoritative types only
- Milestone 3 is blocked until this milestone is complete, because the credential subsystem must not re-import types from `app/skills.py`

### Milestone 3. Extract the Credential Subsystem

Create one authoritative credential domain.

Primary motivation:

The central problem is not only that credentials are fragmented. It is that
storage implementation details currently leak into use-case signatures.

After this milestone:

- use-case signatures must not accept `data_dir`
- use-case signatures must not accept `encryption_key`
- key derivation must happen once at store construction time
- callers must use an injected credential subsystem, not thread filesystem/key details through the stack

Credential boundary definition:

- the credential store owns persistence only
- the credential store owns encryption/decryption as part of persistence
- the credential service owns plaintext credential operations, validation dispatch, and environment materialization
- credential use-cases own setup/clear/satisfaction orchestration across the credential service, runtime skill requirements, and session/setup state
- handlers/routes do not own credential workflow decisions

Encryption tightening:

- Fernet remains the battle-tested authenticated-encryption library
- key derivation at credential store construction must use HKDF from `cryptography`, not raw `hashlib.sha256`
- callers and use-cases must never derive keys themselves
- the credential store factory/construction site is the only allowed place where derivation happens

Specific ownership changes required in this milestone:

- `check_credential_satisfaction` moves out of [app/request_flow.py](/Users/tinker/output/bots/telegram-agent-bot/app/request_flow.py) into credential use-cases
- `AwaitingSkillSetup` transition ownership moves into credential use-cases operating over the credential service
- `validate_credential` moves out of [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py) into a dedicated credential-validation module
- key derivation for the credential store becomes a factory concern, not a caller concern
- [app/registry_service/runtime_surface.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/runtime_surface.py) must consume the shared credential store/service and must not derive keys independently

#### Work

- add credential store port and implementation
- add credential service
- add credential use-cases
- move storage, validation, env building, and satisfaction checks into that subsystem
- move setup/clear side effects behind credential-aware use-cases
- define and use a `CredentialValidator` protocol at the credential boundary
- move the default HTTP credential validator into a dedicated credential-validation module
- construct the credential store once with HKDF-derived key material
- state explicitly whether this milestone lands:
  - full backend parity, or
  - a filesystem-backed implementation with the shared-runtime/Postgres seam explicitly named and deferred
- add contract tests for the credential seam in either case

Named contract-test scope for the credential seam:

- round-trip save then load
- per-user isolation
- per-skill deletion
- full deletion
- corrupted/tampered entry handling
- missing credential file behavior
- `list_skills` behavior without decryption

#### Hard rules

- no direct credential storage helpers imported from `app/skills.py`
- no handler-owned credential mutations
- no request-flow-specific credential logic that bypasses the subsystem
- no shadow credential API kept for compatibility
- no silent omission of parity language for the credential seam
- no independent encryption-key derivation outside credential store construction/factory wiring
- no `data_dir` or `encryption_key` parameters in credential use-case signatures after this milestone
- no raw SHA-256 key derivation for credential encryption; HKDF is the required KDF
- the credential service must not expand into unrelated runtime-skill orchestration
- if full backend parity is deferred in this milestone, the plan and implementation must name:
  - the exact deferred seam
  - the reason for deferral
  - the closure milestone
  - the blocking condition that prevents the deferred seam from surviving into later shared-runtime/lifecycle work unchecked

#### Watchouts

- `request_flow.py`, `runtime_skill_setup_use_cases.py`, `telegram_handlers.py`, and `skill_commands.py` all currently touch credentials
- this is a cross-cutting seam; partial migration is unacceptable
- `AwaitingSkillSetup` is currently written by multiple modules; that split ownership must end in this milestone
- the existing injectable validator seam in tests must be preserved via the credential validator protocol, not lost by hardwiring validation into the service
- `AwaitingSkillSetup` is session state: credential use-cases own the transition decision, adapters persist the returned session mutation

#### Exit criteria

- credentials have one authoritative storage/service/use-case path
- all credential reads/writes/validation/env building flow through that subsystem
- the credential seam has explicit contract coverage
- parity status is explicit, scoped, and tested or deliberately deferred as named debt
- any deferred credential-backend seam has an explicit closure milestone and blocking rule recorded in the same slice
- the credential service vs credential use-case boundary is implemented as defined above, not left to adapter interpretation
- `request_flow.py` no longer owns execution-path credential satisfaction logic
- `AwaitingSkillSetup` transition decisions occur through one owner: credential use-cases operating over the credential service
- registry runtime surface no longer derives credential keys independently

### Milestone 4. Make Resolved Skills Authoritative Everywhere

Resolved active skills must become the only authority in business logic.

#### Work

- change [app/execution_context.py](/Users/tinker/output/bots/telegram-agent-bot/app/execution_context.py) so effective active skills are resolved centrally
- remove `resolved if present else session.active_skills` business-logic fallbacks
- normalize unresolved/invalid skills at the authoritative boundary

#### Hard rules

- no business logic path may read raw `session.active_skills` except persistence/mutation code
- no user-visible or safety-sensitive path may use raw skill lists
- no duplicate resolution logic in handlers/services/use-cases

#### Watchouts

- raw vs resolved state drift is one of the core historical bug classes

#### Exit criteria

- resolved skill lists are the only active-skill authority in request/preflight/display/validation logic
- any raw session usage is clearly persistence-only

### Milestone 5. Dismantle `app/skills.py` as an Authority

After the previous milestones, remove central authority from [app/skills.py](/Users/tinker/output/bots/telegram-agent-bot/app/skills.py).

#### Work

- move any remaining authoritative responsibilities to proper modules
- delete dead or bypassed logic
- keep only narrowly justified implementation helpers, if any remain
- move prompt/config assembly ownership explicitly into [app/provider_guidance_service.py](/Users/tinker/output/bots/telegram-agent-bot/app/provider_guidance_service.py)
- move Codex script staging/cleanup ownership explicitly into the Codex provider layer
- retire [app/store.py](/Users/tinker/output/bots/telegram-agent-bot/app/store.py) as a named deletion target, not an implicit side effect

#### Hard rules

- `app/skills.py` may not remain a hidden dependency root
- no “utility graveyard” that new code starts importing from again
- no compatibility wrapper that preserves the old authority shape
- no module under `app/` may import from `app/skills.py` after this milestone completes

#### Watchouts

- small helper retention often becomes a new stealth parallel path

#### Exit criteria

- `app/skills.py` is no longer central to runtime-skill or credential architecture
- zero modules under `app/` import from `app/skills.py`
- `app/store.py` is removed or reduced to zero live architectural responsibility, with no filesystem fallback path left
- prompt/config assembly is owned by `ProviderGuidanceService`, not `app/skills.py`

### Milestone 6. Refactor Current Inbound Workflows In Per-Workflow Lockstep

Do not refactor Telegram fully and registry later. That creates a temporary parallel-path drift window that this plan explicitly forbids.

The required sequencing is per workflow, across both surfaces in the same slice.

Current workflow slices covered by this milestone:

- skill catalog reads/detail/search
- skill activation
- skill deactivation/clear
- skill setup
- skill import/update/uninstall/diff
- conversation settings mutations
- conversation control/cancel
- pending approval/retry actions
- recovery replay/discard
- provider-guidance preview

This list is the complete scope of Milestone 6.
Any workflow addition requires explicit re-scoping in the plan before implementation.

For each workflow:

- Telegram adapter must route through the shared contracts
- registry API adapter must route through the same shared contracts
- only then move to the next workflow

This milestone covers current workflows only. Lifecycle workflows introduced in
Milestone 8 follow the same lockstep rule and are completed in Milestone 9.

Treat both Telegram-facing modules as adapter code:

- [app/telegram_handlers.py](/Users/tinker/output/bots/telegram-agent-bot/app/telegram_handlers.py)
- [app/skill_commands.py](/Users/tinker/output/bots/telegram-agent-bot/app/skill_commands.py)

#### Work

- surface parsing only
- call use-case ports
- persist returned state changes
- render returned outcomes

#### Hard rules

- no workflow branching in `skill_commands.py`
- no domain branching in Telegram handlers outside provider execution paths that genuinely belong there
- no handler-local lifecycle state machines
- no adapter-specific fallbacks that bypass shared use-cases
- no “Telegram first, registry later” sequencing for a shared workflow
- no workflow may be added to this milestone’s scope implicitly during implementation; any addition must be named and re-scoped explicitly first

#### Watchouts

- `skill_commands.py` is currently a hidden orchestration seam and must be treated as such

#### Exit criteria

- zero workflow branching remains in `app/skill_commands.py` for workflows covered by this milestone
- zero domain branching remains in `app/telegram_handlers.py` for workflows covered by this milestone when a use-case port exists
- for each workflow slice covered by this milestone, Telegram and registry route through the same use-case contracts before the next workflow begins

#### Additional registry requirements for every workflow slice

- [app/registry_service/app.py](/Users/tinker/output/bots/telegram-agent-bot/app/registry_service/app.py) must remain a thin HTTP adapter
- registry UI mutations must continue to flow only through registry APIs
- no route-local lifecycle branching may be introduced while matching Telegram parity

### Milestone 7. Lifecycle Schema Gate

Before implementing missing lifecycle behavior, land the durable schema first.

#### Work

- add required lifecycle schema changes
- add versioned SQLite migrations
- add versioned Postgres migrations
- add contract tests for the new durable states

Expected lifecycle schema concerns:

- revision status fields such as `draft`, `review`, `published`, `archived`
- approval records / decision history
- any additional publish pointer or revision-state metadata needed by the lifecycle

#### Hard rules

- no lifecycle implementation before schema exists
- no migration shortcuts that violate migration-fidelity rules
- no SQLite-only lifecycle schema changes without explicit scoped debt language

#### Exit criteria

- lifecycle schema is landed with backend parity expectations stated and tested

### Milestone 8. Lifecycle Implementation

After Milestones 1-7 are done, add the missing lifecycle:

- draft edit
- revision/history
- submit approval
- approve/reject
- publish/archive
- provider-guidance management

#### Hard rules

- no lifecycle feature may be added on top of an unresolved foundational gap
- every new lifecycle use-case must land with contracts and both surface adapters
- no lifecycle implementation before the schema gate is complete
- no lifecycle state transition may land without explicit durable-state hardening:
  - state machine/transition inventory
  - interruption path
  - duplicate/replay path
  - rejection path
  - partial failure / incomplete publish path
  - completion-owner definition for every transition

#### Exit criteria

- lifecycle behavior is owned by use-cases, not adapters
- lifecycle durable-state transitions are explicitly hardened against interruption, replay, rejection, and partial completion paths

### Milestone 9. Surface Capability Parity For Lifecycle Workflows

Bring Telegram and registry to the same capability set for lifecycle workflows added in Milestone 8.

#### Hard rules

- parity means same operations and invariants
- presentation may differ
- Telegram cannot be “left for later”
- Milestone 9 follows the same per-workflow lockstep discipline as Milestone 6; it is not a Telegram-first or registry-first catch-up phase

#### Exit criteria

- Telegram and registry support the same lifecycle operations added in Milestone 8
- no lifecycle workflow remains registry-only or Telegram-only at milestone completion

### Milestone 10. Rich Registry Editor

Only after lifecycle contracts are correct.

#### Work

- add a battle-tested editor, preferably CodeMirror 6

#### Hard rules

- do not let UI richness hide API/use-case shortcomings
- do not add editor-driven server shortcuts that bypass lifecycle contracts

#### Exit criteria

- rich editing exists as a UI enhancement over the correct API/use-case boundary

## Required Audits At Every Milestone

Each milestone must explicitly audit:

1. equivalent ingress paths
2. raw vs resolved state usage
3. completion ownership where background/recovery state is touched
4. durable state vs in-memory state authority
5. test boundary correctness
6. adjacent regression risk
7. whether a known pre-existing failing test needs to be fixed or formally reclassified before touching that contract

## Hard “Do Not” List

Do not:

- keep old helpers alive because tests still call them
- preserve bad architecture for stale tests
- add a temporary second authority “until later”
- put workflow logic in handlers, routes, or UI code
- centralize all inbound behavior into one mega orchestrator
- use aliasing or naming tricks that obscure whether one or two paths exist
- add new lifecycle features before the foundation gates pass

## Milestone Acceptance Gates

Feature work may resume only when all of the following are true:

- use-case ports exist
- authoritative type ownership is fixed
- credentials have one authoritative subsystem
- resolved active skills are authoritative everywhere
- `app/skills.py` is no longer a central authority
- `skill_commands.py` is a real adapter seam, not hidden orchestration
- Telegram and registry API both depend on the same contract-defined use-case boundary

## Success Criteria

This replacement plan is complete only when:

- runtime skills, provider guidance, credentials, and capabilities each have one owner
- no parallel old/new runtime paths exist
- Telegram and registry API are both thin adapters over contract-defined concern-owned use-cases
- registry UI performs all mutations through registry APIs
- stale tests no longer influence architectural decisions
- `app/skills.py` is no longer a hidden authority
- resolved context is the only authority in business logic where applicable
- new surfaces can be added by writing adapters, not reworking the architecture
