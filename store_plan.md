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
- feature expansion stays frozen until the architecture and lifecycle gates pass

## Executive Summary

The lifecycle remediation track is complete, but the architecture recovery is
not actually accepted complete.

What is now true:

1. the repo shape follows the `channels/`, `workflows/`, `ports/`, and `runtime/` model
2. lifecycle schema, lifecycle workflows, Telegram parity, registry parity, and registry rich editing are landed and revalidated
3. lifecycle transitions now use an explicit machine plus atomic durable transition application
4. the registry browser UI mutates through registry HTTP ingress rather than a server-side shortcut path

What is not yet true:

1. Telegram ingress is still the real mutable runtime state hub for the Telegram channel
2. `runtime/dispatch.py` and parts of `app/agents/*` still depend on Telegram channel internals
3. registry HTTP/UI decomposition is still incomplete
4. the Telegram presenter layer is still largely absent
5. some ownership and naming cleanup promised by the target architecture is still incomplete
6. test support still couples a large part of the suite to Telegram ingress module globals

The earlier feature unfreeze was premature.

Feature expansion is now re-frozen until the architecture remediation track
defined below is complete.

## Current Plan State

As of 2026-03-17:

- Milestones 1-13 are accepted complete
- Milestones 11R-13R are accepted complete
- lifecycle hardening is accepted complete
- channel/workflow/runtime package migration is only partially accepted complete
- a new architecture remediation track is now open

### Feature Freeze Status

The earlier unfreeze was a mistake.

Feature expansion is frozen again because the current package layout still
contains unresolved ownership violations:

- Telegram ingress still owns mutable channel runtime state through module globals
- runtime and agents still reach back into Telegram ingress
- registry HTTP still embeds large UI/template programs
- Telegram presentation is still scattered across ingress and satellite modules
- tests still depend on Telegram ingress globals through `setup_globals`

Allowed work during this freeze:

- architecture remediation defined in this plan
- test rewrites needed to remove architecture coupling
- naming, ownership, and boundary cleanup that moves the repo toward the
  declared channel/workflow/runtime model

Blocked work during this freeze:

- new feature work
- new channel features
- lifecycle expansion
- UI expansion not required by the remediation track
- convenience shims that preserve the broken seams

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
11. New channels must require only a new channel package plus rendering/input translation.
12. Durable state owns correctness. In-memory state is optimization only.
13. Equivalent ingress paths must be audited before and after each nontrivial change.
14. Stale tests never justify escape hatches for bad architecture.
15. `contracts.py` is workflow-local; `ports/` is only for cross-workflow or infrastructure boundaries.
16. Shared inbound/admission types must not live under a channel package.
17. Existing code and existing package names are raw material only; they do not get to constrain the target architecture.
18. No module may import a sibling or parent channel entrypoint to obtain runtime state or helper access.
19. No module-level mutable globals may be used as a shared service locator for channel state.
20. Tests must construct or inject explicit context objects; they must not mutate channel module globals as setup.
21. `runtime/*` must not import channel packages for business orchestration.
22. `agents/*` must not import channel packages for business orchestration.
23. `access.py` and other shared/domain helpers may accept only normalized shared types, never raw channel-native objects.
24. `presenters.py` owns channel-specific rendering; `ingress.py` and `http.py` do not build UI strings or markup inline except for trivial literals.
25. `http.py` is a thin HTTP boundary; `ui.py` owns HTML/CSS/JS page construction.
26. No workflow may reach into another workflow implementation’s private helpers.
27. Do not rely on implicit ordering contracts when the store can provide an explicit query.
28. Temporary re-exports, aliases, or naming bridges must have an explicit removal step in the same track or they are not allowed.

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
| Provider guidance | Content store + ProviderGuidanceService | Prompt/config assembly must stay with ProviderGuidanceService and not drift back into generic helpers during the channel refactor |
| Runtime skill types | Canonical skill types module | Type ownership must not drift back into convenience modules during package moves |
| User credentials | Credential store + credential services/use-cases | Still fragmented and filesystem-helper-owned |
| Credential validation | Credential subsystem | Still scattered across old helpers and request flow |
| Prompt/config assembly | ProviderGuidanceService | Must not drift into channels or runtime composition |
| Codex script staging | Codex provider | Must not drift into channels or workflow packages |
| Filesystem skill fallback | None; seeder replaces it | Deleted; must not be reintroduced via convenience paths |

## Authoritative Structural Model

The clean-room target architecture is:

```text
app/
  channels/
    telegram/
      ingress.py
      egress.py
      presenters.py
      bootstrap.py
      normalization.py

    registry/
      ingress.py
      egress.py
      presenters.py
      bootstrap.py
      http.py
      ui.py

  workflows/
    runtime_skills/
      catalog.py
      activation.py
      importing.py
      setup.py
      setup_machine.py
      contracts.py
    credentials/
      management.py
      contracts.py
    conversation/
      control.py
      settings.py
      contracts.py
    pending/
      machine.py
      requests.py
      contracts.py
    recovery/
      machine.py
      replay.py
      results.py
      transport_contract.py
      contracts.py
    delegation/
      machine.py
      coordination.py
      contracts.py
    provider_guidance/
      preview.py
      contracts.py

  ports/
    egress.py
    content_store.py
    credential_store.py
    registry_store.py

  runtime/
    composition.py
    inbound_types.py
    session_runtime.py
    work_admission.py
    dispatch.py
```

### Layer 1. Domain types and contracts

Every shared or pluggable boundary gets a Protocol/ABC first.

Required targets:

- runtime skill type contracts
- credential type contracts
- workflow contracts beside each workflow package
- egress port contracts
- store ports

### Contracts vs `ports/` Rule

Use `contracts.py` when the types or protocols are owned by one workflow and
exist to express that workflow boundary:

- typed requests
- typed outcomes
- narrow workflow-local protocols

Use `ports/` only when the boundary is shared across workflows or is
infrastructure-level:

- egress
- content store
- credential store
- registry store
- any future cross-channel registry/composition seam that is truly justified

Do **not** put workflow-local contracts in `ports/` just because multiple
channels call the workflow. Multiple callers do not make a workflow contract an
infrastructure port.

### Shared inbound/admission types

Normalized inbound types such as message/command/callback/action plus admitted
envelope shapes are not workflow contracts and are not channel-local.

They must live under `runtime/*`, with the expected home being:

- `runtime/inbound_types.py` for normalized shared inbound shapes
- `runtime/work_admission.py` for admitted-envelope and queue-admission logic

They must not live in `channels/telegram/normalization.py` or any other
channel-scoped module because workflows and runtime dispatch consume them across
channels.

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

### Layer 4. Workflows

This is the canonical inbound business boundary.

It must be:

- modular
- concern-owned
- typed by contracts
- independent of Telegram/FastAPI/browser types

Current workflow packages:

- `workflows/runtime_skills/catalog.py`
- `workflows/runtime_skills/activation.py`
- `workflows/runtime_skills/importing.py`
- `workflows/runtime_skills/setup.py`
- `workflows/credentials/management.py`
- `workflows/conversation/control.py`
- `workflows/conversation/settings.py`
- `workflows/pending/requests.py`
- `workflows/recovery/replay.py`
- `workflows/delegation/coordination.py`
- `workflows/provider_guidance/preview.py`

Future lifecycle workflow packages, introduced only after the lifecycle schema gate:

- `workflows/runtime_skills/authoring.py`
- `workflows/runtime_skills/approval.py`

The existing [app/workflows](/Users/tinker/output/bots/telegram-agent-bot/app/workflows)
package already contains transport/pending state-machine code. It is not a
reason to avoid the `workflows/` name. It is the package that will be absorbed
and repurposed into the target concern-owned namespace.

Hard rule:

- do not create a parallel `workflows_v2` or similar package
- absorb or relocate the current `app/workflows/*` contents into the target
  ownership model in-place
- if the existing `app/workflows/*` contents do not fit the target ownership
  model cleanly, rewrite or relocate them; do not distort the target model to
  preserve legacy file shapes

### Layer 5. Channels

Channels are the external boundary.

Each channel has separate ingress and egress.

- Telegram is one channel
- Registry is one channel
- future Slack/Signal/etc are additional channels

Registry is not split into separate top-level peers such as `registry_api` and `registry`.
Registry browser UI is a client of registry HTTP ingress, but server-side registry remains
one channel with both ingress and egress.

### Layer 6. Runtime composition

`runtime/*` owns:

- channel enablement from config
- shared inbound/admission types
- channel bootstrapping
- egress factory wiring
- work admission
- dispatch/runtime execution

This is wiring only, not business workflow logic.

`runtime/session_runtime.py` scope:

- session load/save helpers
- resolved session/context preparation
- persistence-only mutation handoff helpers
- no business workflow decisions

`runtime/dispatch.py` scope:

- queue-claim to provider-run orchestration
- progress/timeline plumbing
- cancellation/interrupt handoff
- provider execution dispatch
- no channel parsing
- no workflow state-machine ownership
- no workflow-local branching that belongs in `workflows/*`

## Orchestration Classification Rule

The repo currently has multiple orchestration forms. That is tolerated only as
an intermediate state, not as an accepted end-state.

Authoritative rule:

- durable transition systems use one explicit machine style
- one-shot orchestration may remain procedural
- `runtime/*`, `agents/*`, services, and channels must not become shadow
  business-orchestration layers

### Durable transition systems

These require an explicit machine with:

- transition inventory
- one owner
- replay/idempotency semantics
- explicit effects
- tests for interruption and duplicate handling where applicable

Current and expected durable transition systems:

- lifecycle transitions
- pending approval/retry
- transport recovery
- credential/setup progression (`awaiting_skill_setup`)
- delegation progression

### Procedural workflows

These may remain procedural because they are request/response orchestration,
not durable transition systems:

- catalog reads
- provider-guidance preview
- import/update/diff
- credential listing/clear
- most conversation setting changes

### Standard machine style

The target standard for explicit machines in this repo is:

- pure functional machine
- snapshot + action in
- decision + effects out
- atomic application at the session/store boundary

Reason:

- it expresses replay and repair directly
- it avoids callback-driven mutable machine models
- it matches the lifecycle hardening shape already accepted in this plan

Existing `python-statemachine` machines are accepted only as migration-state
implementations until they are consolidated into the standard style.

## What We Keep

These are valid and should be preserved:

- content-store foundation
- credential-store foundation
- runtime skills vs capabilities separation
- registry runtime skill namespace
- content-store hard cutover for runtime skill reads
- content-store and credential-store contract coverage
- confidence-suite rewrite where it proves the new architecture
- the existing concern-owned modules that already align with this plan

## What Must Be Rebuilt

These are no longer acceptable as-is:

- the `transports/` top-level concept
- the split between “transport” and large ingress monoliths
- `telegram_handlers.py` as the effective Telegram channel implementation
- `registry_service/app.py` as combined HTTP, UI, ingress, and workflow bridge
- concrete-only shared workflow boundary rooted in legacy top-level modules
- generic inbound action shapes drifting into workflow APIs
- hidden orchestration in `skill_commands.py`
- any reintroduction of deleted legacy authorities through convenience imports or aliases
- Telegram ingress as a mutable global state hub
- `runtime/dispatch.py` as Telegram-shaped orchestration hiding under `runtime/`
- `app/agents/*` depending on Telegram channel internals
- registry HTTP routes mixed with large inline UI/template programs
- a Telegram channel with no real presenter layer
- tests that require mutating Telegram ingress globals to construct runtime state

## Execution Plan

### Milestone 0. Freeze Feature Expansion

No new lifecycle feature work lands until the channel/workflow architecture track
reaches Milestone 8.

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
- do not let legacy tests or current file layout dictate package boundaries

#### Exit criteria

- the repo and plan both clearly state that structural refactor work is blocking feature expansion
- any known red baseline test that proves a real durable contract bug must be resolved or explicitly reclassified before the milestone that touches that contract

### Milestone 1. Land the Package Skeleton and Dependency Rules

Create the target package structure first, without preserving old names as architecture.

#### Work

- create `app/channels/`
- create `app/workflows/`
- create `app/ports/`
- create `app/runtime/`
- add package-level docs or module comments that state dependency direction
- add import-lint or equivalent guardrails if practical

#### Hard rules

- do not create placeholder packages that immediately import old monoliths wholesale
- do not keep `transports/` as the conceptual owner once `channels/` exists
- do not let `channels/*` import each other directly for workflow logic
- do not let `workflows/*` import channel code
- do not create a second workflows package; absorb the existing `app/workflows/`
  package in-place
- do not preserve an existing file or package layout if it conflicts with the
  target channel/workflow/runtime boundary

#### Implementation guidance

- create the new packages empty or with minimal `__init__.py` only
- keep behavior unchanged in this milestone
- record the allowed dependency direction explicitly:
  - `channels/*` -> `workflows/*`, `ports/*`, `runtime/*` helpers where justified
  - `workflows/*` -> `ports/*`, domain services, stores
  - `runtime/*` -> composition/wiring only
- define the explicit rule for what belongs in `contracts.py` vs `ports/`
- name `runtime/inbound_types.py` as the shared home for normalized inbound types
- treat existing code as migration input only, not as a source of architecture truth

#### Exit criteria

- the target package map exists
- dependency direction is documented and enforceable
- no behavior changed

### Milestone 2. Move Egress to `ports/egress.py` and `channels/*/egress.py`

Egress is the least ambiguous seam and should move first.

#### Work

- move outbound contracts from `app/transports/ports.py` to `app/ports/egress.py`
- move Telegram outbound implementation to `app/channels/telegram/egress.py`
- move registry outbound implementation to `app/channels/registry/egress.py`
- replace `app/transports/factory.py` with channel-aware egress construction in `app/runtime/composition.py`

#### Hard rules

- do not keep `transports/ports.py` as an alias or second authority
- do not leave channel egress construction split between old and new factories
- do not move ingress logic into egress packages

#### Implementation guidance

- port names may change if they are legacy-shaped, but keep the contract narrow
- if `InteractionSurface` is too rendering-specific or misnamed, rename it during this move
- update imports directly to the new path; do not add compatibility exports
- preserve tests that prove egress contract behavior; rewrite any that prove old module ownership

#### Exit criteria

- all outbound code uses `app/ports/egress.py`
- all concrete egress implementations live under `app/channels/*/egress.py`
- `app/transports/` no longer owns architecture and is on a straight deletion path

### Milestone 3. Move Current Use-Case Ports into Local Workflow Contracts

Replace the old shared “use-case factory” shape with local workflow contracts.

#### Work

- create `contracts.py` beside each current workflow package
- move request/outcome dataclasses and narrow protocols there
- replace old `*_port.py` sprawl with workflow-local contracts where practical
- remove the conceptual center of gravity from `app/inbound_use_case_factory.py`

#### Hard rules

- no generic `use_cases` or `actions` sink
- no single mega workflow registry contract
- no stringly `action, params` workflow APIs
- do not define future lifecycle workflow contracts until the lifecycle schema exists

#### Implementation guidance

- one workflow package owns one concern and its contracts
- examples:
  - `workflows/runtime_skills/contracts.py`
  - `workflows/conversation/contracts.py`
  - `workflows/pending/contracts.py`
- generic queue envelopes remain generic only at admission/runtime layers, never as workflow public APIs

#### Exit criteria

- workflow contracts live beside their workflows
- no workflow depends on old top-level port clutter as its conceptual home
- the workflow boundary remains concern-owned and typed

### Milestone 4. Replace `inbound_use_case_factory.py` with `runtime/composition.py`

Composition must own channel wiring, not an old use-case factory.

#### Work

- create `app/runtime/composition.py`
- move concrete workflow instantiation there
- make channels depend on composition, not on direct concrete imports

#### Hard rules

- no new service locator
- no one mega composition object that becomes hidden business logic
- composition wires dependencies only; it does not make workflow decisions
- do not introduce `ports/channel_registry.py` for only two known channels unless
  a concrete third-channel or dynamic-registration need appears first

#### Implementation guidance

- composition may expose narrow getters/builders grouped by concern or channel
- composition may wire:
  - workflow implementations
  - egress factories
  - channel bootstraps
- for the known Telegram and registry channels, direct composition wiring is
  preferred over a premature registry abstraction
- delete `app/inbound_use_case_factory.py` at milestone completion; do not leave it as an alias

#### Exit criteria

- channels get workflow implementations through composition
- old shared use-case factory is deleted
- composition owns wiring only
- no premature channel-registry abstraction was introduced without a justified
  third-channel need

### Milestone 5. Refactor Registry Into One Channel

Registry must be one channel with ingress and egress, not a split legacy shape.

#### Work

- create `app/channels/registry/ingress.py`
- create `app/channels/registry/egress.py`
- create `app/channels/registry/presenters.py`
- create `app/channels/registry/http.py`
- create `app/channels/registry/ui.py`
- move route registration and request validation into `http.py`
- move HTML shell/static/UI-serving concerns into `ui.py`
- move workflow translation into `ingress.py`
- move timeline/result publication into `egress.py`

#### Hard rules

- no separate top-level `registry_api` architecture
- browser UI must use registry HTTP ingress for all mutations
- no workflow logic in `http.py`
- no workflow logic in `ui.py`
- no continued dependence on `registry_service/runtime_surface.py` after migration

#### Implementation guidance

- `http.py` should be thin: validate, call ingress, map response
- `ingress.py` should translate registry-native requests into typed workflow calls
- `presenters.py` should shape workflow outcomes into HTTP JSON, action lists, and UI hints
- `egress.py` should own timeline/result publication and any registry-native output behavior
- `ui.py` may serve HTML/JS/static assets only
- delete or absorb `app/registry_service/runtime_surface.py` at the end of the milestone

#### Exit criteria

- registry server-side code is one channel with ingress and egress
- browser UI uses registry HTTP ingress only
- `app/registry_service/app.py` no longer owns workflow translation directly
- `app/registry_service/runtime_surface.py` is deleted

### Milestone 6. Refactor Telegram Into One Channel

Telegram must become one channel with ingress and egress, not egress plus a giant ingress monolith.

#### Work

- create `app/channels/telegram/ingress.py`
- create `app/channels/telegram/egress.py`
- create `app/channels/telegram/presenters.py`
- create `app/channels/telegram/bootstrap.py`
- create `app/channels/telegram/normalization.py`
- move PTB wiring/registration into `bootstrap.py`
- move update normalization into `normalization.py`
- move workflow translation into `ingress.py`
- move rendering into `presenters.py`

#### Hard rules

- no domain workflow logic remains in `telegram_handlers.py`
- no workflow branching remains in `skill_commands.py`
- no handler-local state machines
- no “Telegram first, registry later” for shared workflows
- no hidden reuse of old monolith helpers after the new owner lands

#### Implementation guidance

- treat the already extracted Telegram modules as migration raw material only
- merge or rewrite them if that yields a cleaner channel package
- `bootstrap.py` owns PTB app construction and route registration only
- `ingress.py` owns translation from normalized Telegram input into typed workflow calls
- `presenters.py` owns Telegram-specific rendering, keyboards, and message formatting
- `normalization.py` owns Telegram-native update parsing and attachment download entrypoints
- delete `app/telegram_handlers.py` and `app/skill_commands.py` at the end of the milestone; do not leave namespace shims

#### Exit criteria

- Telegram is one channel with ingress and egress
- `telegram_handlers.py` is deleted
- `skill_commands.py` is deleted
- all Telegram workflow entry paths route through the new channel package

### Milestone 7. Move Current Workflows Under `app/workflows/` In Per-Workflow Lockstep

This is the sequencing-critical milestone.

The required sequencing is per workflow, across both channels in the same slice.

Current workflow slices covered by this milestone:

- skill catalog reads/detail/search
- skill activation
- skill deactivation/clear
- skill setup
- skill import/update/uninstall/diff
- credential management
- conversation settings mutations
- conversation control/cancel
- pending approval/retry actions
- recovery replay/discard
- provider-guidance preview

This list is the complete scope of Milestone 7.
Any workflow addition requires explicit re-scoping in the plan before implementation.

For each workflow:

- move/rename the workflow module under `app/workflows/...`
- move/rename its local contracts beside it
- migrate Telegram ingress to the new workflow path
- migrate registry ingress to the same workflow path
- delete the old implementation path completely
- only then move to the next workflow

#### Hard rules

- no “Telegram first, registry later” sequencing for a shared workflow
- no workflow may be added implicitly during implementation
- no old/new workflow path may coexist past the end of a workflow slice
- no generic action router may be introduced as a shortcut

#### Implementation guidance

- examples:
  - `app/runtime_skill_catalog_use_cases.py` -> `app/workflows/runtime_skills/catalog.py`
  - `app/conversation_control_use_cases.py` -> `app/workflows/conversation/control.py`
  - `app/provider_guidance_use_cases.py` -> `app/workflows/provider_guidance/preview.py`
- rewrite rather than mechanically move files if the old shape is wrong
- preserve concern ownership; do not create a shared dumping ground in `workflows/`

#### Exit criteria

- current workflows live under `app/workflows/`
- Telegram and registry both call the same workflow modules for each covered slice
- no old workflow module path remains live for the covered slices

### Milestone 8. Move Runtime Admission and Request Execution Into `runtime/*`

`runtime/*` must own composition, admission, and dispatch, not channels.

#### Work

- move shared admitted-envelope and queue logic into `app/runtime/work_admission.py`
- move request execution orchestration into `app/runtime/dispatch.py`
- move session/runtime composition helpers into `app/runtime/session_runtime.py`
- remove business/runtime orchestration from channel ingress packages

#### Hard rules

- channels do not own queue semantics
- channels do not own generic runtime dispatch
- workflows do not own channel admission concerns
- generic inbound envelopes remain runtime/admission types only
- `runtime/session_runtime.py` must not become a hidden business-logic sink
- `runtime/dispatch.py` must not become a replacement monolith for channel or workflow logic

#### Implementation guidance

- `request_runtime.py` should either move here or be split by concern and deleted
- `app/transport.py` should be split into channel normalization and runtime admission types; do not keep it as a grab bag
- `app/transports/types.py` should either disappear or move under runtime with clearer naming
- `runtime/session_runtime.py` owns only session/context preparation and persistence-only helpers
- `runtime/dispatch.py` owns only queue/admission-to-provider execution plumbing

#### Exit criteria

- runtime composition/admission/dispatch live under `app/runtime/`
- channels are thinner because generic runtime work moved out
- no old transport/admission grab-bag remains as an architecture center

### Milestone 9. Delete Legacy Entry Paths and Enforce Zero-Import Gates

Once the new owners exist, the old ones must die.

#### Work

- delete `app/transports/`
- delete `app/inbound_use_case_factory.py`
- delete `app/telegram_handlers.py`
- delete `app/skill_commands.py`
- delete or absorb old top-level `*_use_cases.py` modules replaced by `app/workflows/*`
- delete or absorb old registry service routing/runtime bridge modules replaced by `app/channels/registry/*`

#### Hard rules

- no compatibility exports
- no alias modules
- no “temporary” re-export packages
- no tests preserved by keeping dead paths alive

#### Exit criteria

- zero imports from deleted legacy modules
- the new architecture is the only architecture

### Milestone 10. Lifecycle Schema Gate (Complete)

This milestone is the renamed continuation of the former lifecycle-schema work
that used to sit earlier in the plan. It is intentionally deferred until the
channel/workflow/runtime architecture track is complete.

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

#### Completion notes

- lifecycle schema landed with backend parity and versioned migrations
- runtime-vs-published resolution semantics were split explicitly
- durable approval history is now part of the content model

#### Exit criteria

- lifecycle schema is landed with backend parity expectations stated and tested

### Milestone 11. Lifecycle Implementation (Complete)

This milestone is the renamed continuation of the former lifecycle implementation
work.

This milestone added the missing lifecycle behavior:

- draft edit
- revision/history
- submit approval
- approve/reject
- publish/archive
- provider-guidance management

#### Hard rules

- no lifecycle feature may be added on top of an unresolved structural gap
- every new lifecycle workflow must land with local contracts and both channels
- no lifecycle implementation before the schema gate is complete
- no lifecycle state transition may land without explicit durable-state hardening:
  - state machine/transition inventory
  - interruption path
  - duplicate/replay path
  - rejection path
  - partial failure / incomplete publish path
  - completion-owner definition for every transition

#### Completion notes

- lifecycle behavior now lives in workflow modules, not channels
- runtime-skill authoring/approval and provider-guidance management are real workflow owners
- lifecycle transitions were implemented only after the schema gate landed

#### Exit criteria

- lifecycle behavior is owned by workflow modules, not channels
- lifecycle durable-state transitions are explicitly hardened against interruption, replay, rejection, and partial completion paths

### Milestone 12. Channel Capability Parity For Lifecycle Workflows (Complete)

This milestone is the renamed continuation of the former parity milestone for
lifecycle workflows.

Bring Telegram and registry to the same capability set for lifecycle workflows added in Milestone 11.

#### Hard rules

- parity means same operations and invariants
- presentation may differ
- Telegram cannot be “left for later”
- this milestone follows the same per-workflow lockstep discipline as Milestone 7

#### Completion notes

- Telegram and registry both support the lifecycle operations added in Milestone 11
- lifecycle workflow parity now exists at the channel layer, with different presentation but shared workflow ownership

#### Exit criteria

- Telegram and registry support the same lifecycle operations added in Milestone 11
- no lifecycle workflow remains registry-only or Telegram-only at milestone completion

### Milestone 13. Rich Registry Editor (Complete)

This milestone is the renamed continuation of the former rich-editor work.

Only after lifecycle contracts are correct.

#### Work

- add a battle-tested editor, preferably CodeMirror 6

#### Hard rules

- do not let UI richness hide channel/workflow shortcomings
- do not add editor-driven server shortcuts that bypass workflow contracts

#### Completion notes

- the registry channel UI now provides rich editing over the correct HTTP-ingress/workflow boundary
- lifecycle mutation and draft editing remain routed through registry HTTP ingress
- the editor is a UI enhancement rather than a server-side shortcut

#### Exit criteria

- rich editing exists as a UI enhancement over the correct registry channel ingress/workflow boundary

## Reopened Lifecycle Remediation Track

Review after the first Milestone 13 landing found that Milestone 11 did not
meet this plan’s own hardening gate. The remediation track below is now part of
the authoritative plan and must be completed before lifecycle-dependent feature
work resumes.

### Milestone 11R. Lifecycle Hardening (Complete)

This milestone reopens Milestone 11 at the workflow/store boundary.

#### Required work

- define an explicit lifecycle state machine / transition inventory
- define one completion owner for each lifecycle transition
- replace multi-step lifecycle durable writes with atomic store operations
- make duplicate/replay calls idempotent or explicitly rejected with a stable result
- make retry after interrupted partial transitions repair durable state instead of creating split state
- add tests for:
  - interruption repair
  - duplicate/replay submit
  - duplicate/replay approve
  - rejection transition
  - partial publish repair
  - partial archive repair

#### Hard rules

- string status checks in workflow code are not enough by themselves; the lifecycle machine must be explicit
- no lifecycle transition may span multiple independent store commits
- approval history ordering assumptions must be explicit at the contract boundary
- retry after partial durable mutation must converge to one correct durable end state

#### Completion notes

- lifecycle transitions now run through an explicit lifecycle machine
- multi-step durable transitions now apply atomically at the content-store boundary
- duplicate/replay submit/approve/archive paths now have stable results
- interrupted partial publish/archive/reject transitions are repairable on retry

#### Exit criteria

- lifecycle transitions are explicitly modeled and owned
- multi-step lifecycle transitions are atomic at the store boundary
- duplicate/replay calls have stable behavior
- interrupted partial lifecycle transitions are repairable on retry

### Milestone 12R. Channel Revalidation Over Hardened Lifecycle (Complete)

This milestone reopens Milestone 12 after Milestone 11R.

#### Required work

- re-run Telegram and registry lifecycle flows against the hardened workflow layer
- update channel messages/status handling where hardened lifecycle outcomes introduce explicit replay/idempotent results
- add parity tests for the hardened outcomes, not just the happy path

#### Hard rules

- channel parity must be proven against the hardened lifecycle semantics, not assumed from the earlier structural landing
- no channel may paper over lifecycle replay/repair results with a fake success path

#### Completion notes

- Telegram and registry now prove replay/idempotent lifecycle behavior through channel tests
- channel parity is revalidated against the hardened workflow semantics rather than the original happy path

#### Exit criteria

- Telegram and registry expose the same hardened lifecycle semantics
- parity tests cover at least one replay/idempotent lifecycle path in both channels

### Milestone 13R. Registry Editor Revalidation (Complete)

This milestone reopens Milestone 13 after Milestone 12R.

#### Required work

- revalidate the registry editor against hardened lifecycle semantics
- ensure the editor works through the same repaired HTTP ingress/workflow path
- add UI tests for lifecycle draft/edit/submit/publish flows that exercise the hardened path

#### Hard rules

- editor richness must not mask lifecycle repair gaps
- the browser UI must continue to mutate only through registry HTTP ingress

#### Completion notes

- the registry editor remains on the same HTTP-ingress/workflow boundary after hardening
- registry tests now prove the editor shell still targets the hardened lifecycle routes

#### Exit criteria

- the rich editor is accepted on top of the hardened lifecycle behavior
- registry editor tests cover the repaired lifecycle path, not just the original happy path

## Reopened Architecture Remediation Track

Deep review after the lifecycle remediation confirmed that the package migration
landed the target directory shape but did not fully land the target ownership
model.

This track is now authoritative and blocks feature expansion.

### Root Problem Summary

The deepest unresolved issue is the inbound context problem:

- [app/channels/telegram/ingress.py](/Users/tinker/output/bots/telegram-agent-bot/app/channels/telegram/ingress.py)
  still owns module-level mutable state
- multiple channel, runtime, and agent modules import it at runtime to reach
  back into that state
- test support still mutates those globals directly

That one seam causes most of the remaining violations:

- reverse dependencies from `runtime/*` into a channel package
- reverse dependencies from `agents/*` into a channel package
- Telegram satellite modules that are not truly independent
- tests coupled to implementation internals rather than the channel boundary

The other open faults are grouped below by root cause.

### Open Issue Inventory

#### 1. Inbound context and dependency-direction faults

- Telegram ingress owns `_config`, `_provider`, `_boot_id`, `_rate_limiter`,
  and `_bot_instance`
- Telegram ingress also owns `_LIVE_CANCEL`, which is mutable per-conversation
  async cancellation state and must be treated as runtime concurrency state,
  not startup configuration
- six app modules still import Telegram ingress as a back-door dependency
- `runtime/dispatch.py` is not channel-agnostic
- `app/agents/delivery.py` and `app/agents/delegation.py` are not channel-agnostic
- `access.py` imports Telegram normalization
- `trust_tier_for_source` lives in `runtime/composition.py` instead of the
  inbound/admission boundary
- `setup_globals` in test support still mutates Telegram ingress globals
- large Telegram-heavy suites, including 139 ingress references in
  `test_handlers.py` alone, are coupled to the module-global pattern

#### 2. Registry channel decomposition faults

- `channels/registry/http.py` still mixes:
  - route handlers
  - auth/session behavior
  - large inline HTML/CSS/JS template programs
- `channels/registry/ui.py` exists but does not own the UI layer yet

#### 3. Telegram presentation faults

- `channels/telegram/presenters.py` is effectively empty
- Telegram rendering remains spread across:
  - `ingress.py`
  - `conversation.py`
  - `runtime_skills.py`
  - `pending.py`
  - `guidance.py`

#### 4. Workflow/lifecycle hygiene faults

- `_snapshot()` is duplicated in runtime-skill lifecycle workflows
- approval workflow reaches into a private helper on authoring
- latest-approval lookup relies on implicit ordering and Python scanning rather
  than an explicit store query

#### 5. Dead code, naming, and gate faults

- `workflows/__init__.py` re-exports have no callers
- `transport_contract.py` is still stranded at `app/` root under a legacy name
- zero-import gate scans `app/` only, not `tests/`
- stale test names still refer to deleted `transports` ownership

#### 6. Orchestration and state-machine consolidation faults

- the repo still contains multiple orchestration styles:
  - library-backed class machines
  - functional decision machines
  - procedural workflow orchestration
  - out-of-band orchestration in `runtime/*` and `agents/*`
- `awaiting_skill_setup` progression is still split across workflow and service
  ownership instead of one explicit machine
- `app/credential_flow.py` is still a third setup-logic locus alongside the
  workflow and service layers
- delegation progression is still outside `app/workflows/*`
- pending/recovery machine files still live in transitional top-level modules
- `runtime/dispatch.py` still risks acting as a shadow workflow owner

## Architecture Remediation Rules

These rules are specific to this reopened track and are stricter than the
global rules above.

1. Do not decompose a large module by creating satellites that import back into
   it for state, helpers, or service access.
2. Any extracted module must be executable from explicit inputs plus injected
   collaborators. If it still needs `import ... as th`, the extraction is not
   accepted.
3. Replace module-global mutable channel state with a typed context object
   before further decomposition of that channel.
4. `runtime/*` may depend on shared types, stores, ports, and workflows only.
   It may not depend on a concrete channel package.
5. `agents/*` may depend on shared types, stores, runtime admission, and
   workflows only. It may not depend on a concrete channel package.
6. Channel normalization happens at the channel edge. Shared helpers such as
   `access.py` must consume normalized shared types only.
7. Route modules and ingress modules translate, validate, persist, and delegate.
   They do not render large UI programs and they do not own business workflow
   branches.
8. Presenter extraction is not optional cleanup. A channel does not satisfy the
   architecture until its rendering lives in its presenter layer.
9. Tests must follow the same architectural boundary as production code. If
   production moves from globals to explicit context, tests must do the same in
   the same slice.
10. No private cross-workflow method access is allowed. Shared logic either
    moves to a shared helper/module or becomes an explicit store/domain API.
11. Do not accept “temporary” re-exports or naming bridges without a same-track
    removal step and a zero-import test.
12. Preserve behavior by tests, not by keeping the wrong owner alive.
13. Durable transition systems must not be implemented as ad hoc conditionals
    spread across workflows, services, runtime, and agents.
14. New and remediated durable transition systems must use the repo-standard
    functional machine style unless a narrower exception is explicitly planned.
15. Existing library-backed machines are migration targets, not an accepted
    second long-term machine standard.

## Track A. Fix the Inbound Context Problem

Root cause: Telegram ingress owns module-level mutable runtime state, and six
other modules plus the test harness reach back into it.

### A1. Extract `TelegramChannelState` and explicit Telegram runtime registries

Create a dedicated context object under:

- `app/channels/telegram/state.py`
  or
- `app/channels/telegram/context.py`

`TelegramChannelState` owns startup-initialized Telegram channel state currently
held in module globals, including:

- `config`
- `provider`
- `boot_id`
- `rate_limiter`
- `bot_instance`
- any Telegram-specific helper dependencies that are currently read through
  `_cfg()` / `_prov()` and related globals

A separate explicit mutable runtime registry object must own concurrency maps
such as:

- `_LIVE_CANCEL`
- any similar per-conversation async runtime registries discovered during A1

Expected home:

- `app/channels/telegram/cancellation.py`

This module owns Telegram-specific mutable per-conversation async runtime
registries and exposes explicit access/manipulation helpers for them.

Helpers that already have a correct owner do not move onto the context object:

- session load/save helpers stay in `runtime/session_runtime.py`
- chat/conversation key helpers stay in `identity.py`
- upload-dir helpers stay with their current correct owner or move to
  `runtime/*` if they are truly shared
- boot wiring stays in bootstrap/startup code

#### Hard rules

- no module-level mutable globals remain as the authoritative Telegram state
- no module may read channel runtime state through `import ...ingress as th`
- the context object must be explicit and typed
- mutable per-conversation async registries must be explicit and typed; they
  do not hide as anonymous module globals
- startup/bootstrap is the only place allowed to construct or mutate the live
  startup channel state object

#### Implementation guidance

- keep the context object small and explicit; do not turn it into a giant bag
  of random helpers
- prefer injected collaborators over context methods when a dependency is not
  truly Telegram-owned
- if a helper already has a correct home, keep it there; the context object may
  reference it but does not become its new owner
- if a helper belongs in `runtime/*` or `workflows/*`, move it there instead of
  hiding it on the context object
- `ingress.py` becomes a thin PTB wiring layer that holds a context reference
  and passes it down

#### Required tests

- add focused tests for context construction and access
- add focused tests for the explicit mutable runtime registry that replaces
  `_LIVE_CANCEL`
- replace any test that currently relies on `_th._config` / `_th._provider`
  mutation with explicit context setup

#### Exit criteria

- Telegram startup state is owned by one explicit context object
- mutable async channel runtime registries have explicit owners under
  `channels/telegram/cancellation.py`
- `_cfg()` / `_prov()` style global accessors are deleted
- `ingress.py` no longer acts as a service locator

### A2. Remove back-imports into Telegram ingress

Update these modules to accept explicit context or injected collaborators:

- `app/channels/telegram/conversation.py`
- `app/channels/telegram/runtime_skills.py`
- `app/channels/telegram/pending.py`
- `app/runtime/dispatch.py`
- `app/agents/delivery.py`
- `app/agents/delegation.py`

#### Hard rules

- no `import app.channels.telegram.ingress as th` outside `ingress.py`
- `runtime/*` and `agents/*` must not gain new channel imports while this is
  being fixed
- do not replace one hidden global with another hidden singleton

#### Implementation guidance

- update one concern slice at a time:
  - conversation
  - runtime skills
  - pending
  - runtime dispatch
  - agents
- delete compatibility helper wrappers in the same slice once callers are moved
- if a function needs too many context fields, that is a signal to split the
  function or move shared logic to the correct layer

#### Required tests

- add a zero-import gate proving no app module outside `channels/telegram/ingress.py`
  imports Telegram ingress
- add focused regression tests for `runtime/dispatch.py` and `app/agents/*`
  showing they can run with injected collaborators/context rather than hidden
  ingress state

#### Exit criteria

- no file outside `ingress.py` imports Telegram ingress
- `runtime/*` has no channel import
- `agents/*` has no channel import
- `ingress.py` contains PTB registration, normalization, event dispatch
  handoff, and context passing only; it does not own business logic,
  rendering, or shared helper/state accessors

### A3. Fix `access.py` import direction

`access.py` must accept only `InboundUser` and other shared types.

#### Required work

- remove the import of Telegram normalization from `access.py`
- normalize Telegram-native objects at the Telegram channel edge before calling
  access/trust helpers
- update the existing call sites accordingly

#### Hard rules

- shared helpers do not coerce channel-native objects
- normalization belongs to the channel edge only

#### Required tests

- add focused access tests over `InboundUser`
- update channel tests to normalize before calling access helpers

#### Exit criteria

- `access.py` has no import from `app/channels`
- `access.py` accepts normalized shared types only

### A4. Move `trust_tier_for_source`

The source-sensitive trust decision is an inbound/admission concern.

#### Required work

- move `trust_tier_for_source` out of `runtime/composition.py`
- expected home:
  - `runtime/work_admission.py`
  or
  - a nearby inbound identity/admission helper module
- update all call sites

#### Exit criteria

- `runtime/composition.py` no longer owns inbound trust routing

### A5. Update `setup_globals` and the Telegram-heavy tests

The test harness must stop mutating ingress globals.

#### Required work

- change `tests/support/handler_support.py` so `setup_globals` constructs or
  injects the new Telegram channel context instead of mutating module globals
- update the large Telegram suites to use that explicit setup path
- audit the very large `test_handlers.py` and related Telegram tests to ensure
  they exercise the channel boundary rather than module-global internals

#### Hard rules

- tests do not get a “special exception” to keep global state alive
- if a test is only proving the global pattern, rewrite or delete it

#### Required tests

- add one focused test proving the setup helper no longer mutates ingress globals
- keep behavioral coverage while removing implementation coupling

#### Exit criteria

- `setup_globals` does not mutate Telegram ingress globals
- Telegram tests construct explicit context/state instead of depending on module globals

## Track B. Build the Telegram Presenter Layer

Root cause: Telegram rendering still lives in ingress and satellite modules
instead of `presenters.py`.

### B1. Extract message and keyboard builders

Move all Telegram-specific rendering into:

- `app/channels/telegram/presenters.py`

Including:

- `InlineKeyboardMarkup` construction
- `InlineKeyboardButton` construction
- HTML message bodies
- edit-vs-send rendering choices where the decision is presentation-specific
- credential/setup prompt formatting
- approval/recovery/pending formatting
- provider-guidance rendering now living in `guidance.py`

### B2. Extract workflow-outcome presenters

Each workflow outcome rendered by Telegram must have a named presenter
function:

- runtime skill outcomes
- conversation-control outcomes
- pending approval/retry outcomes
- recovery outcomes
- provider-guidance lifecycle outcomes

#### Hard rules

- no new inline Telegram markup outside `presenters.py`
- `ingress.py`, `conversation.py`, `runtime_skills.py`, and `pending.py` may
  orchestrate calls, but they do not build channel markup directly
- `guidance.py` follows the same rule
- presentation decisions must not drift into workflow modules

#### Required tests

- add focused presenter tests for Telegram analogous to registry presenter tests
- add at least one regression test per major workflow family proving the
  channel module calls a presenter instead of formatting inline

#### Exit criteria

- `presenters.py` is the authoritative home for Telegram rendering
- no `InlineKeyboardMarkup` or `InlineKeyboardButton` creation remains outside
  `presenters.py`

## Track C. Decompose Registry HTTP and UI

Root cause: `channels/registry/http.py` still combines route handling,
auth/session logic, and a large inline UI program.

### C1. Move UI/template programs into `ui.py`

Move all large HTML/CSS/JS page-building content into:

- `app/channels/registry/ui.py`

Where useful, split further into:

- template helpers
- page builders
- editor asset helpers

### C2. Reduce `http.py` to a thin HTTP boundary

`http.py` should contain:

- route registration
- request parsing and validation
- auth/session checks that truly belong to the HTTP boundary
- calls into registry ingress/workflows
- response mapping

It should not contain:

- large template strings
- embedded editor programs
- page markup construction

Auth/session logic that does not belong in the HTTP boundary moves to:

- `app/channels/registry/auth.py`

That module becomes the registry channel owner for:

- session lookup helpers
- auth policy helpers
- non-route request authentication/authorization helpers shared by registry
  ingress and HTTP routes

`http.py` may call into `auth.py`, but it does not remain the owner of that
logic.

#### Hard rules

- `http.py` contains no long inline HTML/CSS/JS blocks
- browser UI remains a client of registry HTTP ingress only
- do not move workflow logic into `ui.py`; `ui.py` owns rendering only
- auth/session logic that is not intrinsically HTTP-bound moves to
  `channels/registry/auth.py`

#### Required tests

- add focused tests for UI render helpers in `ui.py`
- keep registry HTTP tests proving route behavior unchanged
- add one guard test that fails if:
  - `http.py` contains a multiline literal with markers such as `<!DOCTYPE`,
    `<html`, `<style`, `<script`, or `<textarea>`
  - or `http.py` remains above the agreed line-count threshold after extraction
    (target: fewer than 1800 lines)

#### Exit criteria

- `ui.py` owns the registry UI rendering layer
- `http.py` is a thin HTTP boundary with no embedded UI program
- registry auth/session ownership is explicit and no longer muddled inside
  `http.py`

## Track D. Lifecycle and Workflow Hygiene Cleanup

Root cause: the lifecycle hardening fixed correctness, but some ownership and
maintainability problems remain.

### D1. Extract lifecycle snapshot construction

Move duplicated `_snapshot()` logic to one explicit shared helper, expected
home:

- `app/workflows/lifecycle_machine.py`

Expose something like:

- `build_lifecycle_snapshot(track, latest_action) -> LifecycleSnapshot`

### D2. Add explicit latest-approval store methods

Add explicit store methods for latest approval lookup for both:

- runtime skills
- provider guidance

The method must express ordering explicitly in the store boundary rather than
relying on Python scans over ordered lists.

### D3. Remove private cross-workflow access

After D2:

- remove `_latest_action_for_revision` from authoring
- stop approval from calling a private helper on authoring

#### Hard rules

- shared lifecycle helper logic exists in one place only
- approval workflow does not reach into authoring internals
- hidden ordering contracts are not allowed at the call site

#### Required tests

- add store tests for explicit latest-approval queries
- update lifecycle workflow tests to prove both authoring and approval consume
  the shared helper/store method rather than duplicated logic

#### Exit criteria

- snapshot logic exists in one place
- no private cross-class workflow access remains
- latest-approval lookup is explicit at the store boundary

## Track E. Dead Code, Naming, and Test-Gate Cleanup

Root cause: dead re-exports, legacy naming, incomplete gates, and stale test
names still muddy the architecture.

### E1. Resolve `workflows/__init__.py`

Do not leave dead re-exports in place.

Guidance:

- F5 resolves the machine file relocation for pending/recovery
- E1 should not perform a separate intermediate relocation of those same files
- after F5 lands, remove the dead root re-exports and the misleading
  “temporary” language
- if F5 has not landed yet, E1 may only remove dead re-exports that already
  have no callers; it must not introduce a second move of the same files

### E2. Relocate `transport_contract.py`

Move it under the recovery concern package:

- `app/workflows/recovery/transport_contract.py`

Update imports and tests in the same slice.

Do not create a new `app/work_queue/` package in this remediation track.

### E3. Expand zero-import gates to `tests/`

Add a second forbidden-import scan over the test tree.

### E4. Audit and clean stale transport test names

`test_transports_factory.py` and `test_transports_telegram.py` are not dead,
but their names still encode the deleted architecture.

Required action:

- either rename them to match the current `channels/*` ownership
- or merge/delete them if they are duplicate coverage

#### Hard rules

- no “temporary” language without an active same-track removal step
- zero-import gates must cover both production code and tests
- test names must reflect the live architecture

#### Required tests

- update zero-import-gate coverage
- add/adjust tests to prove the relocated transport/work-queue contract module
  still behaves the same

#### Exit criteria

- no dead re-exports remain
- `transport_contract.py` no longer sits at app root under a legacy name
- zero-import gates scan both `app/` and `tests/`
- no test file name encodes a deleted top-level architecture without justification

## Track F. Orchestration and State-Machine Consolidation

Root cause: the repo still has multiple durable orchestration styles and still
leaks transition ownership outside `app/workflows/*`.

This track makes the earlier orchestration analysis explicit and turns it into
required work rather than background guidance.

### F1. Inventory and classify every orchestration owner

Before moving code, produce an explicit inventory for the current durable and
semi-durable flows:

- lifecycle
- pending approval/retry
- transport recovery
- credential/setup progression, explicitly including:
  - `app/workflows/runtime_skills/setup.py`
  - `app/skill_lifecycle_service.py`
  - `app/credential_flow.py`
- delegation progression
- request execution / preflight

Each concern must be classified as exactly one of:

- explicit machine required
- procedural workflow acceptable
- misplaced orchestration that must move

#### Hard rules

- do not assume a module belongs in `runtime/*` or `agents/*` just because it
  currently lives there
- do not tolerate “mixed ownership” where one concern is partly in workflows
  and partly in services or runtime

#### Required output

The inventory must be committed in:

- `docs/orchestration_inventory.md`

That document becomes the gating reference for F2-F6.

#### Exit criteria

- each major orchestration concern has a written owner and type classification
- there is no unclassified durable transition system left in the repo

### F2. Standardize on one explicit machine style

The standard machine style for this repo is the functional decision-machine
shape already used by lifecycle:

- snapshot
- action
- decision
- effects
- atomic application at the store/session boundary

#### Required work

- define shared conventions for machine modules:
  - snapshot type
  - action type
  - decision/effects type
  - stable statuses for idempotent replay
- treat existing `python-statemachine` machines as migration-state only

#### Hard rules

- do not introduce a third explicit machine style
- do not add new callback-driven mutable machines
- do not keep two machine standards as a permanent compromise

#### Required tests

- add machine-focused tests for any newly migrated machine module
- prove replay/idempotent behavior where the concern is durable

#### Exit criteria

- the repo has one declared explicit-machine standard
- any remaining non-standard machine is explicitly tracked as not-yet-migrated

### F3. Extract a real runtime-skill setup machine

`awaiting_skill_setup` is a durable conversational progression and must have
one explicit machine owner.

#### Required work

- move setup progression into:
  - `app/workflows/runtime_skills/setup_machine.py`
- define:
  - states
  - actions
  - effects on `session.awaiting_skill_setup`
  - activation-ready transition
  - foreign-setup and cancellation semantics
- absorb or replace the setup helper logic currently living in:
  - `app/credential_flow.py`
- make `runtime_skills/setup.py` a consumer of that machine, not a second
  state owner
- remove setup-transition ownership from `skill_lifecycle_service.py`

#### Hard rules

- `awaiting_skill_setup` writes have one owner only
- no split ownership between workflow and service
- `credential_flow.py` must not survive as a parallel setup-state helper path
- no ad hoc mutation of `session.awaiting_skill_setup` outside the machine
  application boundary

#### Required tests

- setup machine tests for:
  - start
  - next requirement
  - ready/completion
  - cancel
  - foreign setup
  - clear-after-credential-removal

#### Exit criteria

- setup progression has one explicit machine owner
- service/workflow split no longer duplicates setup transition ownership
- `credential_flow.py` no longer owns parallel setup-state logic

### F4. Move delegation into `app/workflows/*`

Delegation progression is durable workflow state and must stop living as a
half-workflow under `app/agents/*`.

#### Required work

- create a real delegation workflow package:
  - `app/workflows/delegation/contracts.py`
  - `app/workflows/delegation/machine.py`
  - `app/workflows/delegation/coordination.py`
- implement `delegation/machine.py` using the repo-standard functional
  decision-machine style defined in F2
- move plan approval/cancel/result-application/resume-readiness logic there
- make `agents/delivery.py` and `agents/delegation.py` thin transport/bridge
  adapters over that workflow package
- define the explicit state inventory for both:
  - parent delegation plan state
  - child task progression state

Expected parent delegation plan states include:

- `proposed`
- `submitted`
- `completed`
- `partial_failed`
- `cancelled`

Expected child-task progression states include the currently live active values:

- `proposed`
- `queued`
- `leased`
- `running`
- `submitted`
- `completed`
- `failed`

#### Hard rules

- `app/agents/*` may bridge agent I/O, but they do not own delegation state
  transitions
- delegation statuses are explicit machine outcomes, not scattered string edits
- delegation does not introduce a second long-term machine style; it uses the
  F2 functional decision-machine standard

#### Required tests

- machine tests for:
  - proposed -> submitted
  - proposed -> queued -> leased -> running -> completed
  - cancel before send
  - routed result application
  - all tasks complete
  - partial failure
  - ready-to-resume

#### Exit criteria

- delegation transition ownership lives in `app/workflows/delegation/*`
- `app/agents/*` no longer edits delegation status strings directly
- delegation machine uses the repo-standard functional decision-machine style

### F5. Migrate pending and transport recovery to the repo-standard machine style

The current root files:

- `app/workflows/pending_request.py`
- `app/workflows/transport_recovery.py`
- `app/workflows/results.py`

are transitional residue.

#### Required work

- replace the current `python-statemachine` implementations with functional
  decision machines that use the repo-standard shape
- move pending machine code under:
  - `app/workflows/pending/machine.py`
- move transport recovery machine code under:
  - `app/workflows/recovery/machine.py`
- move supporting recovery result types under the same concern-owned package
- move `transport_contract.py` under:
  - `app/workflows/recovery/transport_contract.py`
- update imports and zero-import gates accordingly

This milestone also resolves the machine-file location part of E1.

#### Hard rules

- no root-level “temporary” machine modules remain after this slice
- machine code lives with the workflow concern that owns it
- pending and recovery do not remain on `python-statemachine` as a permanent
  second standard

#### Required tests

- keep the current pending/recovery machine contract tests
- add migration-equivalence tests proving the new functional machines preserve
  the accepted transition semantics
- add zero-import coverage for the old root module paths once callers are moved

#### Exit criteria

- pending and recovery machine modules live under their concern packages
- no callers import the old root machine modules
- pending and recovery use the repo-standard functional machine style
- no production pending/recovery logic depends on `python-statemachine`

### F6. Enforce `runtime/dispatch.py` as pure runtime plumbing

`runtime/dispatch.py` must be explicitly classified rather than left as a
catch-all orchestrator.

#### Required work

- make `runtime/dispatch.py` pure channel-agnostic execution plumbing
- if any business decision or durable transition logic remains after Track A,
  move that logic to a dedicated concern-owned workflow package such as
  `app/workflows/execution/*` in the same slice
- if any logic is inherently Telegram-specific rendering or callback behavior,
  move it back under the Telegram channel in the same slice

The required invariant after the decision:

- `runtime/dispatch.py` does not own durable business transitions
- `runtime/dispatch.py` does not depend on channel packages
- if some logic is inherently Telegram-specific, it moves out of runtime

#### Hard rules

- do not keep channel-shaped orchestration under `runtime/*`
- do not let the “runtime” name justify a hidden business workflow

#### Required tests

- focused execution/preflight tests at the chosen boundary
- import-boundary tests proving `runtime/*` no longer imports channel packages

#### Exit criteria

- execution/preflight ownership is explicit
- `runtime/dispatch.py` is no longer a shadow workflow owner
- `runtime/dispatch.py` remains only if it is channel-agnostic plumbing
- any workflow-local decision logic formerly hidden there has a concern-owned
  workflow home

## Required Sequencing

The tracks above are not all equal-risk.

### Phase 1. Freeze and boundary rules

- reopen the feature freeze
- land the stricter architecture rules and this remediation track in the plan

### Phase 2. Track A first

Do Track A before major Telegram decomposition work.

Reason:

- presenter extraction and runtime cleanup are unstable until Telegram state is
  explicit rather than global
- test coupling must be fixed at the same seam

Recommended slice order inside Track A:

1. A3 fix `access.py` direction and A4 move `trust_tier_for_source`
2. A1 extract context/state object plus explicit runtime registries
3. A2 remove back-imports one concern at a time
4. A5 rewrite setup/test support

### Phase 3. Tracks C, D, and F1-F2 may run after A1

After the context object exists:

- Track C is mostly independent and can proceed
- Track D is independent and low-risk
- Track F inventory and machine-standard work can proceed without waiting for
  full Telegram cleanup

### Phase 4. Track F3-F6 before final unfreeze

The orchestration consolidation track must be resolved before the freeze lifts.

Recommended order:

1. F1 inventory/classification
2. F2 machine-standard decision
3. F3 setup machine
4. F4 delegation workflow
5. F5 pending/recovery package consolidation
6. F6 dispatch ownership decision and cleanup

### Phase 5. Track B after A2 is substantially done

Presenter extraction is easier and cleaner once the Telegram modules no longer
reach back into ingress for state and helpers.

### Phase 6. Track E throughout, but finish it last

Dead-code cleanup and gate expansion should accompany the relevant slices, with
final cleanup at the end of the remediation track.

## Architecture Remediation Acceptance Gates

Feature expansion may resume only when all of the following are true:

- no app module outside Telegram ingress imports Telegram ingress
- Telegram channel runtime state is explicit and instance-owned, not singleton or global-module-owned
- `runtime/*` has no channel imports
- `agents/*` has no channel imports
- `access.py` has no channel imports
- Telegram presenters own Telegram rendering
- registry `http.py` is a thin HTTP boundary and `ui.py` owns UI rendering
- setup progression has one explicit machine owner
- delegation progression has one explicit workflow/machine owner
- pending and recovery machines live under concern-owned workflow packages
- `runtime/dispatch.py` has explicit non-channel ownership and is not a shadow workflow owner
- the repo-standard explicit machine style is declared and used for remediated durable workflows
- lifecycle snapshot and latest-approval ownership are cleaned up
- `workflows/__init__.py` and `transport_contract.py` no longer carry dead or
  misleading transitional ownership
- zero-import gates cover both `app/` and `tests/`
- test support no longer mutates Telegram ingress globals
- Telegram bootstrap owns PTB application construction and route registration;
  Telegram ingress owns normalized event translation and dispatch only
- Telegram-heavy tests exercise the Telegram boundary through explicit runtime
  setup rather than routing-module internals or singleton mutable state
- `status.md` and `docs/orchestration_inventory.md` reflect the actual current
  code ownership and are updated only after code/tests prove the state
- `ingress.py` is ≤ 1500 lines and contains only event translation, handler
  dispatch, and thin coordination
- no extracted Telegram channel module imports `app.channels.telegram.ingress`
- no Telegram channel file except `presenters.py` creates
  `InlineKeyboardMarkup` or `InlineKeyboardButton`
- no test file calls private ingress helpers (with documented exceptions for
  PTB callback contracts that have no public entry point)
- no test file monkeypatches module-level ingress functions for stubbing
- zero-import gates for singleton helpers cover both `app/` and `tests/`
- ingress line-count gate prevents growth above 1500 lines

## Phase 7. Closure Correction Stage

The prior closure overstated completion. The following remaining work is
required before the acceptance gates above can be considered satisfied.

### G1. Replace singleton Telegram runtime ownership with bootstrap-owned runtime

The current `app/channels/telegram/state.py` and
`app/channels/telegram/cancellation.py` still own singleton mutable state via
module globals. That is a renamed global-state seam, not the explicit context
boundary Track A required.

#### Required work

- replace singleton-installed Telegram channel state with an explicit
  bootstrap-owned runtime object
- the runtime object must own:
  - startup state (`config`, `provider`, `boot_id`, `rate_limiter`, `bot`)
  - mutable in-memory registries that are genuinely Telegram-runtime scoped
    such as live cancellation and chat-lock maps
- this runtime object is the runtime boundary that the restored
  `app/channels/telegram/ingress.py` owner in G2 must consume; do not create a
  second ingress-local runtime authority later
- pass that runtime explicitly to Telegram ingress and worker dispatch owners
- delete singleton accessors and reset helpers from:
  - `app/channels/telegram/state.py`
  - `app/channels/telegram/cancellation.py`
- update `app/main.py`, Telegram channel code, and tests to use the explicit
  runtime object rather than installed globals

#### Hard rules

- no module-level singleton may remain as the authoritative Telegram runtime
  owner
- if a helper only exists to read a singleton runtime, the helper must be
  deleted or moved behind an explicit runtime object
- test fixtures must construct runtime objects the same way production bootstrap
  does; tests do not get an alternate global seam

#### Required tests

- positive tests proving bootstrap/runtime construction produces the expected
  Telegram runtime shape
- negative tests proving singleton install/get/reset helpers are gone
- update Telegram runtime isolation tests so they assert over explicit runtime
  instances rather than module singletons

#### Exit criteria

- no authoritative Telegram runtime or cancellation singleton remains
- Telegram runtime is passed explicitly from bootstrap to ingress/worker paths
- tests no longer depend on singleton install/reset helpers

### G2. Restore the Telegram bootstrap and ingress ownership split

The current `app/channels/telegram/bootstrap.py` is a re-export shim and
`app/channels/telegram/routing.py` remains a monolithic owner for PTB wiring,
worker dispatch, ingress translation, and residual orchestration.

#### Required work

- make `app/channels/telegram/bootstrap.py` the real owner of:
  - PTB application construction
  - handler registration
  - runtime installation/wiring
- restore a true ingress owner at:
  - `app/channels/telegram/ingress.py`
- move normalized Telegram event translation and dispatch there
- delete `app/channels/telegram/routing.py`
- update all app and test imports to the final owners

#### Hard rules

- `bootstrap.py` must not be a re-export shim
- `ingress.py` must not become a mega orchestrator
- no compatibility alias or re-export module may remain for `routing.py`
- worker dispatch must run through the real ingress owner, not a legacy alias

#### Required tests

- positive tests for bootstrap application construction through
  `app/channels/telegram/bootstrap.py`
- positive tests for ingress message/callback/worker dispatch behavior through
  `app/channels/telegram/ingress.py`
- negative tests proving `app/channels/telegram/routing.py` is gone
- updated zero-import gates proving no app module outside Telegram ingress
  imports Telegram ingress, and no tests import deleted Telegram routing paths

#### Exit criteria

- `bootstrap.py` owns PTB app construction and route registration
- `ingress.py` owns normalized Telegram event translation and dispatch only
- `routing.py` no longer exists

### G3. Finish the Telegram test-boundary migration

The current Telegram-heavy tests still import routing internals directly and
mutate or inspect runtime internals such as pending-work registries and context
variables. That keeps the old implementation seam alive in tests.

#### Required work

- rewrite `tests/support/handler_support.py` around explicit Telegram runtime
  construction and boundary helpers
- update Telegram-heavy suites to import and exercise the final bootstrap and
  ingress owners, not deleted or transitional internal modules
- remove direct test mutation/assertion of internal registries such as:
  - `_pending_work_items`
  - `CHAT_LOCKS`
  - `_current_update_id`
- where runtime state must be asserted, assert through explicit runtime objects
  or public boundary behavior

#### Hard rules

- tests must not preserve architecture that production code no longer uses
- tests must not reach into module-private mutable state to prove a contract
- if a test only passes by importing a deleted/transitional owner, rewrite it
  or delete it

#### Required tests

- update handler/runtime isolation tests to assert explicit runtime ownership
- update presenter tests so they target final ingress/bootstrap owners
- strengthen zero-import gates to block test imports of deleted or transitional
  Telegram entrypoint paths

#### Exit criteria

- Telegram-heavy tests run through the same explicit runtime boundary as
  production
- no test imports deleted/transitional Telegram routing owners
- test support no longer mutates or resets Telegram module internals

### G4. Repair documentation and final structural gates

`status.md` and `docs/orchestration_inventory.md` must reflect the actual
current ownership model. Structural gates must verify the final architecture,
not only deleted historical paths.

#### Required work

- update `status.md` to reflect the reopened state and final closure truthfully
- update `docs/orchestration_inventory.md` to reflect the actual current owners
  after G1-G3
- specifically correct stale entries such as:
  - any Telegram entrypoint ownership references that still point at deleted or
    transitional owners instead of the final bootstrap/ingress split
  - delegation ownership entries that still name deleted `app/agents/*`
    owners instead of `app/workflows/delegation/*`
  - request-execution ownership entries that still describe
    `app/runtime/dispatch.py` as a mixed workflow owner after F6 cleanup
- expand zero-import/structure tests so they check the final Telegram owners
  and the absence of singleton authority

#### Required tests

- structural tests for:
  - no singleton Telegram runtime authority
  - no deleted/transitional Telegram entrypoint imports in app or tests
  - final bootstrap/ingress ownership split

#### Exit criteria

- status and inventory docs match the actual code
- structural gates fail on the regressions that escaped the previous closure

## Phase 8. Ingress Decomposition and Test-Boundary Hardening

Phase 7 closed the singleton/routing regressions, but a post-Phase-7 audit found
that the Telegram ingress owner is still oversized, the test suite still reaches
into ingress private helpers, and the presenter gate has a gap in egress.py.
Feature work remains frozen until Phase 8 gates pass.

### Findings That Motivated Phase 8

1. **Ingress is still a shadow mega-owner.** `app/channels/telegram/ingress.py`
   is 3,009 lines with 127 definitions. The G2 exit criterion said "ingress owns
   normalized event translation and dispatch only" and the G2 guidance said
   "if ingress.py exceeds ~1500 lines after the split, further decompose." It is
   double that threshold. Specifically, ingress still owns:
   - `TelegramProgress` class (lines 815-870): progress display lifecycle
   - `keep_typing` / `_heartbeat` (lines 1276-1314): typing animation and
     heartbeat orchestration
   - `_load` / `_save` session wrappers (lines 1317-1335): session I/O helpers
   - `execute_request` / `request_approval` / `approve_pending` / `reject_pending`
     / `retry_skip_pending` / `retry_allow_pending` (lines 1340-1428): full
     execution and approval orchestration
   - `_propose_delegation_plan` / `_publish_delegation_proposed_event` /
     `_handle_delegation_approve` / `_handle_delegation_cancel` (lines 1209-1461):
     delegation proposal publishing and channel callback flow
   - `worker_dispatch` (lines 2635-2858): 224-line worker dispatch with inline
     recovery, usage recording, timeline publication, and routed-task result
     reporting
   - `_execute_worker_action` (lines 2554-2632): worker action execution with
     inline runtime-skill dispatch
   - `_shared_command_dispatch` / `_shared_callback_dispatch` (lines 2937-3008):
     shared-mode dispatch routing
   - `_global_error_handler` (lines 2989-3009): PTB error handler

2. **Tests certify implementation details instead of the public boundary.**
   Multiple test files reach into ingress private helpers:
   - `test_agents.py:509` monkeypatches `ingress._execute_worker_action`
   - `test_telegram_presenters.py:474,488,514,548` calls private ingress helpers
     `_send_approval_prompt`, `_show_setup_prompt`, `_send_compact_reply`,
     `_propose_delegation_plan`
   - `test_execution_context.py:796` calls private `ingress._load` / `_save`
   - `test_invariants.py:1041,1113` exercises private `_global_error_handler`
     and monkeypatches `_load`
   - `test_handlers_credentials.py` monkeypatches `ingress.validate_credential`
     at runtime (lines 61, 99, 132, 153, 178, 197)
   - `handler_support.py:16` imports live ingress directly (legitimate for
     `handle_message` / `worker_dispatch`, but still a coupling surface)

3. **Egress.py creates Telegram markup outside presenters.**
   `app/channels/telegram/egress.py:150-153` constructs `InlineKeyboardMarkup` /
   `InlineKeyboardButton` in `send_recovery_notice()`. The gate test
   `test_telegram_reply_markup_builders_live_only_in_presenters` checks only
   5 files and does not include `egress.py`.

4. **status.md has contradictory lede.** Line 22 says "The remediation track is
   reopened and not complete" while the authoritative section at line 910 says
   "Phase 7 closure correction is complete" and line 935 says "Feature work may
   resume."

5. **Stale module docstring.** `ingress.py:1` says it owns "progress display, and
   PTB wiring" — PTB wiring is now in bootstrap.py, and progress display should
   move out in this phase.

6. **Zero-import gates have an asymmetry.** Singleton helper checks cover `app/`
   but not `tests/`.

### H1. Decompose ingress.py below the ~1500-line threshold

#### Problem

`ingress.py` at 3,009 lines is double the G2 guidance threshold. It owns
normalized event translation (its legitimate job) plus execution orchestration,
delegation proposal publishing and channel callback flow, progress display,
session I/O, and worker dispatch post-processing (not its job).

#### Required work

Split `ingress.py` into concern-owned modules within `app/channels/telegram/`.
The split must produce modules that do not import back into `ingress.py` for
state — they receive explicit collaborators.

Decomposition target:

| Responsibility group | Target file | Approx lines |
|---|---|---|
| `TelegramProgress`, `keep_typing`, `_heartbeat`, `_progress_timeline_callback` | `progress.py` | ~120 |
| `execute_request`, `request_approval`, `approve_pending`, `reject_pending`, `retry_skip_pending`, `retry_allow_pending`, `_resolve_context`, `_resolve_project`, `_allowed_roots`, `_check_prompt_size_cross_chat`, `_execution_surface_context`, plus all `_*_runtime()` adapter builders | `execution.py` | ~400 |
| `_propose_delegation_plan`, `_publish_delegation_proposed_event`, `_handle_delegation_approve`, `_handle_delegation_cancel`, `_delegation_keyboard`, `_DelegationCallbackEditableHandle`, `_DelegationCallbackSurface`, `_parse_delegation_callback` | `delegation_channel.py` | ~130 |
| `worker_dispatch`, `_execute_worker_action`, `_run_with_cancel_watch`, `_poll_cancel_requested`, `_build_action_surface`, `_action_target_message_id`, `_maybe_fire_webhook` | `worker.py` | ~350 |
| `_load`, `_save`, `_conversation_key`, `_actor_key`, `_event_key`, `_telegram_chat_id` | `session_io.py` | ~40 |
| `_shared_command_dispatch`, `_shared_callback_dispatch`, `_shared_inline_command_handler`, `_enqueue_shared_action`, `_shared_action_envelope`, `_record_shared_action`, `_shared_cancel_command`, `_action_requires_public_guard` | `shared_mode_dispatch.py` | ~120 |
| `_global_error_handler` | stays in `ingress.py` (registered by bootstrap) or moves to bootstrap | ~25 |

After the split, `ingress.py` retains:
- Command handlers (`cmd_*`)
- Callback handlers (`handle_*`)
- `handle_message`
- Decorators (`_command_handler`, `_callback_handler`)
- Dedup/locking helpers (`_dedup_update`, `_complete_pending_work_item`)
- Access checks (`is_allowed`, `is_admin`, `is_public_user`, `_trust_tier`,
  `_public_guard`)
- `build_user_prompt`, `send_formatted_reply`, `send_path_to_chat`,
  `send_directed_artifacts`, `_edit_or_reply_text`

Estimated `ingress.py` after split: ~1300-1500 lines.

#### Hard rules

- No extracted module may import `app.channels.telegram.ingress`. Each receives
  its collaborators explicitly (runtime, session, message, config) as function
  parameters.
- `ingress.py` may import from the new modules. The new modules may not import
  from each other except through shared types (e.g., `TelegramRuntime` from
  `state.py`, presenter functions from `presenters.py`).
- No re-export shims. If `worker_dispatch` moves to `worker.py`, bootstrap must
  import it from `worker.py` (or ingress re-exports it as a public name — but
  ingress calls it, it does not just pass it through).
- `worker_dispatch` must remain callable from `bootstrap.py` via the
  `TelegramBootstrap.worker_dispatch` partial. Update the partial target if the
  function moves.
- Do not create empty package directories. These are sibling modules under
  `app/channels/telegram/`, not sub-packages.

#### Required tests

- Positive: each extracted module's public functions work when called with
  explicit runtime/session/config inputs.
- Negative: no extracted module imports `app.channels.telegram.ingress`.
  Add a zero-import gate for each new module (pattern: read file text, assert
  `"app.channels.telegram.ingress"` not in text).
- Negative: `ingress.py` does not define `TelegramProgress`, `worker_dispatch`,
  `_load`, `_save`, `_propose_delegation_plan`, or `execute_request` after
  the split (these belong to extracted modules).
- Gate: `ingress.py` is below 1500 lines.

#### Exit criteria

- `ingress.py` is ≤1500 lines and contains only normalized event translation,
  handler dispatch, and thin coordination calls to extracted modules.
- Each extracted module runs from explicit inputs and does not import ingress.
- `bootstrap.py` wires `worker_dispatch` from its new location.

### H2. Move recovery notice markup from egress into presenters

#### Problem

`egress.py:150-153` constructs `InlineKeyboardMarkup` / `InlineKeyboardButton`
for recovery notices. The plan gate says "Telegram presenters own Telegram
rendering." The gate test checks 5 files but not `egress.py`.

#### Required work

1. Add a presenter function to `presenters.py`:
   `recovery_notice_markup(update_id, run_again_label, skip_label) -> InlineKeyboardMarkup`
2. `egress.py` calls `presenters.recovery_notice_markup(...)` instead of
   constructing keyboard objects directly.
3. Remove `InlineKeyboardButton` and `InlineKeyboardMarkup` imports from
   `egress.py`.
4. Add `egress.py` to the scoped paths in
   `test_telegram_reply_markup_builders_live_only_in_presenters`.

#### Required tests

- Positive: presenter produces expected keyboard shape.
- Negative: `egress.py` no longer imports `InlineKeyboardButton` or
  `InlineKeyboardMarkup`.
- Gate: update existing gate to include `egress.py`.

#### Exit criteria

- Zero `InlineKeyboardMarkup` / `InlineKeyboardButton` construction in any
  Telegram channel file except `presenters.py`.

### H3. Harden test-boundary discipline

#### Problem

Multiple test files reach into ingress private helpers directly. This certifies
implementation details and creates coupling that masks architecture regressions.

#### Required work

For each test file that calls a private ingress helper, fix the coupling:

**`test_telegram_presenters.py`** (lines 474, 488, 514, 548):
These tests call `_send_approval_prompt`, `_show_setup_prompt`,
`_send_compact_reply`, `_propose_delegation_plan` to verify that ingress
delegates to presenters. After H1 moves these functions to extracted modules
(`execution.py`, `delegation_channel.py`), the tests should:
- Either call the extracted module's public function directly (if the function
  becomes public in the new module), OR
- Test the presenter function itself (verify the presenter produces the expected
  markup) rather than testing that ingress calls the presenter.
The second approach is better: test the contract at the boundary (presenter input
→ markup output), not the wiring (ingress calls presenter).

**`test_agents.py:509`**:
Monkeypatches `ingress._execute_worker_action`. After H1 moves this to
`worker.py`, the test should monkeypatch the new module's function. But better:
test the agent delivery path through the public `worker_dispatch` entry point
with a fake provider, rather than stubbing out internals.

**`test_execution_context.py:796`**:
Calls `ingress._load` / `_save` directly. After H1 moves these to
`session_io.py`, the test should call the new module. But better: test execution
context resolution through the public execution entry point.

**`test_invariants.py:1041,1113`**:
Calls `_global_error_handler` directly and monkeypatches `_load`. The error
handler test is acceptable — it tests a PTB callback contract that has no
higher-level public entry point. The `_load` monkeypatch (line 1113) should
be replaced with a store-level fake that makes `_load` fail naturally, rather
than patching the function.

**`test_handlers_credentials.py`**:
Monkeypatches `ingress.validate_credential` 6 times. This should be replaced
with a dependency-injected validator or a store-level credential stub that makes
the real validator produce the desired result.

**`handler_support.py:16`**:
Imports `ingress as _th` and calls `_th.handle_message` and
`_th.worker_dispatch`. This is legitimate (these are the public ingress entry
points). No change required, but after H1, `worker_dispatch` may move to
`worker.py`, so the import should track the final owner.

#### Hard rules

- No test may call a function that starts with `_` from another module unless
  that function is the PTB callback contract being tested (like
  `_global_error_handler`) and there is no public entry point.
- Monkeypatching a module attribute to stub out a private function is not
  acceptable when the function can be replaced by injecting a collaborator or
  using a store-level fake.
- "The test was working" is not a reason to preserve implementation coupling.

#### Required tests

- Gate: add a zero-import gate that scans all test files for calls to known
  private ingress helpers (`_load`, `_save`, `_execute_worker_action`,
  `_propose_delegation_plan`, `_send_approval_prompt`, `_show_setup_prompt`,
  `_send_compact_reply`). These must not appear in test code after H3.
  Exception: `_global_error_handler` is allowed in `test_invariants.py` only.
- Gate: add a zero-import gate asserting that no test file monkeypatches
  `ingress.validate_credential` — the real validator must be tested through
  store-level fakes.

#### Exit criteria

- No test file calls a private ingress helper (with the documented exception).
- No test file monkeypatches module-level ingress functions for stubbing.
- All Telegram-heavy tests exercise the channel through public entry points
  or through the extracted module's public functions.

### H4. Repair documentation and tighten gates

#### Required work

1. **Fix status.md lede**: Replace line 22 ("The remediation track is reopened
   and not complete") with a truthful current-state summary that points the
   reader to the authoritative section. Lines 40-48 that say "Feature work
   remains frozen" should also be updated to reflect the actual current state
   after Phase 8.

2. **Fix ingress.py docstring**: Line 1 says ingress owns "progress display, and
   PTB wiring." After H1 moves progress to `progress.py` and PTB wiring is in
   `bootstrap.py`, update the docstring to match the actual ownership.

3. **Add singleton-helper gate for tests/**: Create
   `test_deleted_telegram_singleton_helpers_are_gone_from_test_code` that scans
   `tests/` the same way the existing app-side gate scans `app/`.

4. **Add extracted-module back-import gates**: For each module created in H1,
   add a gate asserting it does not import `app.channels.telegram.ingress`.

5. **Add ingress line-count gate**: Assert `ingress.py` is below 1500 lines.
   This prevents future growth back toward the monolith threshold.

6. **Update orchestration_inventory.md** if any worker dispatch or execution
   ownership entries changed due to H1.

#### Required tests

- Gate: singleton helpers absent from `tests/`.
- Gate: no extracted Telegram module imports ingress.
- Gate: `ingress.py` ≤ 1500 lines.
- Gate: `egress.py` has no `InlineKeyboardMarkup` or `InlineKeyboardButton`.

#### Exit criteria

- Documentation matches the code.
- Structural gates enforce the final Telegram decomposition.
- The ingress line-count gate prevents regression.

### Phase 8 Sequencing

1. **H1** first — the decomposition creates the new module targets.
2. **H2** can proceed in parallel with H1.
3. **H3** after H1 — test rewrites depend on knowing the final module locations.
4. **H4** last — documentation and gates codify the final state.

### Phase 8 Acceptance Gates

All existing Architecture Remediation Acceptance Gates must continue to hold,
plus the following new gates:

- `ingress.py` is ≤ 1500 lines and contains only event translation, handler
  dispatch, and thin coordination
- No extracted Telegram channel module imports `app.channels.telegram.ingress`
- No Telegram channel file except `presenters.py` creates
  `InlineKeyboardMarkup` or `InlineKeyboardButton`
- No test file calls private ingress helpers (with documented exceptions)
- No test file monkeypatches module-level ingress functions for stubbing
- `status.md` lede reflects the actual current state
- Zero-import gates for singleton helpers cover both `app/` and `tests/`
- Ingress line-count gate prevents growth above 1500 lines

### Phase 8 Failure Patterns

These are the specific patterns that caused Phase 8 to be necessary. Check for
them on every change.

1. **Renaming a monolith instead of decomposing it.** Phase 7 replaced
   `routing.py` with `ingress.py` but left the same 3,000-line scope. If you
   split `ingress.py` and create a 1,500-line `worker.py` that does the same
   mixed-concern work, you have moved lines, not decomposed.

2. **Extracted modules importing back into the parent.** If `execution.py`
   imports from `ingress.py`, the extraction did not create independence. Each
   extracted module must accept its inputs as explicit function parameters.

3. **Tests that validate wiring instead of contracts.** "Ingress calls the
   presenter" is a wiring test. "The presenter produces correct markup given
   this input" is a contract test. Write the second kind. The wiring is
   implicitly tested by any integration test that exercises the full path.

4. **Preserving test coupling because it was already there.** If a test only
   works by monkeypatching `ingress._load`, and you move `_load` to
   `session_io.py` and update the monkeypatch target, you have preserved the
   coupling at the new location. Replace the monkeypatch with a store-level
   fake or dependency injection.

5. **Gate tests that check a specific list of files instead of a pattern.** The
   existing presenter gate checks 5 hardcoded files and missed `egress.py`.
   Prefer gates that scan a directory glob and assert a property (e.g., "no .py
   file in `app/channels/telegram/` except `presenters.py` imports
   `InlineKeyboardButton`").

## Post-Audit Findings (F1–F10)

Post-Phase-8 deep audit found 10 remaining issues. These must be resolved
before the architecture remediation track is accepted as complete.

### F1. Extract post-execution finalization from worker.py

`worker_dispatch()` at `worker.py:260-439` handles 7 workflow concerns inline
in channel ingress code: recovery path handling (300-316), duplicated access
control (301-303, 318-320), approval mode branching (328-361), delegation
finalization (366-374), routed task result reporting (375-401), usage recording
(402-418), timeline publishing (419-437). The Hard Do Not List says "do not put
workflow logic in channel ingress."

Required work:

1. Create `app/workflows/execution/finalization.py` owning post-execution
   orchestration: delegation finalization, routed task result reporting, usage
   recording, timeline publishing, webhook firing. It must not import from
   `app/channels/`. It receives channel-specific callbacks as typed Callable
   parameters on a `FinalizationContext` dataclass.

2. Move approval mode branching into `app/workflows/execution/requests.py`.
   The workflow function accepts `approval_mode: str` and decides internally.
   Channel code must not read `session.approval_mode`.

3. Move access control to `app/runtime/work_admission.py`. Create or extend a
   function that performs the admission check and returns a typed result.
   `worker_dispatch` calls it once.

4. Move recovery dispatch to `app/workflows/recovery/`. The recovery path at
   lines 300-316 transitions durable state — that belongs in the recovery
   workflow.

5. Extract shared channel egress construction. Lines 283-298 and 160-175
   duplicate the `telegram_conversation_ref` → `create_channel_egress` pattern.

6. Document completion ownership explicitly at the top of `worker_dispatch`:
   who marks done (caller on normal return), who marks failed (lines X,Y), who
   marks pending_recovery (line Z), what happens on exception after execution.

7. Make usage recording failure handling explicit. Either document that failure
   is non-blocking, or transition the work item to a specific state on failure.

Hard rules:
- `app/workflows/execution/finalization.py` must not import from `app/channels/`
- `worker.py` must not read `session.approval_mode` or call
  `finalize_resumed_delegation`
- `worker.py` must not call `work_queue.record_usage` or
  `publish_timeline_event` directly
- `worker.py` must not gate on `source == "registry"` for workflow decisions

Exit criteria:
- `worker_dispatch` becomes: normalize → admit → build egress → delegate to
  execution workflow → delegate to finalization workflow → return
- No inline business logic, source-gated branches, or raw session reads

### F2. Move execution_channel_context and format_provider_error out of channel layer

`execution.py:302-335` `execution_channel_context()` constructs
`ExecutionChannelContext` (a workflow contract) by inspecting message
capabilities — workflow-layer state resolution in the channel layer.
`execution.py:73-113` `format_provider_error()` spawns a subprocess with a
hardcoded model and is injected into the non-Telegram `RuntimeDispatchRuntime`.

Required work:

1. Move `execution_channel_context` logic into
   `app/workflows/execution/requests.py` or a new
   `app/workflows/execution/context.py`. The channel extracts raw metadata and
   passes it to the workflow.

2. Move `format_provider_error` to `app/formatting.py` or `app/summarize.py`.
   Make the model name configurable. Remove HTML escaping — let the channel
   escape for its own format.

3. Remove the 7 pure passthroughs from execution.py (`execute_request`,
   `request_approval`, `approve_pending`, `reject_pending`,
   `retry_skip_pending`, `retry_allow_pending`,
   `check_prompt_size_cross_chat`). Callers should build the typed runtime
   directly and call the workflow function.

Hard rules:
- No workflow contract type may be constructed in channel code based on
  business logic
- `format_provider_error` must not HTML-escape — that is the channel's job
- `RuntimeDispatchRuntime.format_provider_error` receives a plain-text formatter

### F3. Reduce sibling coupling between extracted Telegram modules

The plan at line 3044 says extracted modules may import from each other "only
through shared types." But `execution.py` imports behavioral functions from 6
siblings, `worker.py` from 5, `shared_mode_dispatch.py` from 5.

Required work:

1. After F1/F2, re-examine the import graph.
2. Runtime builders should receive behavioral collaborators as Callable
   parameters, not as direct imports from siblings.
3. Routing imports (worker.py dispatching to conversation/pending/runtime_skills
   handler functions) are acceptable.
4. Add a gate test enforcing sibling import discipline.

Hard rules:
- No extracted module calls a function defined in another extracted sibling
  unless it is a routing dispatch target or a shared type/helper
- Runtime builders receive behavioral collaborators as parameters

### F4. Eliminate duplicated dispatch logic between ingress.py and shared_mode_dispatch.py

`shared_mode_dispatch.py:360-437` `_shared_skills_inline_handler` (80 lines)
duplicates skills dispatch from ingress → `runtime_skills.handle_skills_command`.
`shared_mode_dispatch.py:440-471` duplicates command routing for 7 commands.

Required work:

1. Both ingress.py and shared_mode_dispatch.py should call
   `runtime_skills.handle_skills_command` as the single owner.
2. Both modules should call the same conversation command handlers.
3. Delete `_shared_skills_inline_handler` and `_shared_inline_command_handler`.

Exit criteria:
- `shared_mode_dispatch.py` ≤ 450 lines
- No duplicated dispatch tables

### F5. Fix cmd_start and cmd_help decorator bypass

`ingress.py:451` `cmd_start` and `ingress.py:478` `cmd_help` manually inline
the normalization/dedup/gate logic that `@_command_handler` provides. Two code
paths for the same operation — CLAUDE.md bug class #1.

Required work:
- Apply `@_command_handler` to both functions
- Remove manual normalization/dedup/gate logic

### F6. Freeze mutable adapter models in pending and recovery machines

`PendingRequestWorkflowModel` at `pending/machine.py:25` and
`TransportWorkflowModel` at `recovery/machine.py:20` are mutable dataclasses.
`run_pending_request_event()` and `run_transport_event()` mutate them in place.
The machine conventions doc says machines use frozen dataclasses and pure
functions.

Required work:
1. Make both model dataclasses frozen
2. Change adapter functions to return new result objects instead of mutating
3. Update all consumers
4. Add equivalence tests

### F7. Clean up remaining vocabulary and dead code

`inbound_types.py:120` has dead `surface_binding_id` field. Several docstrings
use "surfaces" inconsistently with "channels" vocabulary.

Required work:
1. Rename or delete `surface_binding_id`
2. Update docstrings to use "channels"
3. Add `surface_binding_id` to the vocabulary gate's forbidden list

### F8. Commit the plan and repair status traceability

`store_plan.md` has uncommitted local edits. `status.md` correction log stops
at `a686565` and does not include its own reconciliation commit.

Required work:
1. Commit `store_plan.md` with all current edits
2. Update `status.md` correction log through current HEAD
3. Update `docs/orchestration_inventory.md` if F1 changed ownership
4. Commit status and inventory

### F9. Clean up store parity gaps

Two store seams have public methods in SQLite that do not exist in Postgres:

- `publish_ui_timeline()` at `app/registry_service/store.py:1172` — public
  method in SQLite, no Postgres counterpart. Not in abstract base. No external
  callers — both stores use the internal `_publish_ui_timeline_conn()`.
- `close()` at `app/content_store_sqlite.py:1137` — public method in SQLite,
  no Postgres counterpart. Not in abstract base. No external callers.

Required work:
1. Delete `publish_ui_timeline` public method from SQLite (dead code)
2. Delete content store `close()` from SQLite or add to both + abstract base
3. Add structural gate tests asserting registry and content store public method
   sets are identical across both backends

Hard rules:
- No public method may exist in one backend but not the other unless the
  abstract base explicitly marks it as optional
- The parity gate must be automated

### F10. Fix the surface→channel delivery kind migration gap

Slice 2 (`837b4ed`) renamed delivery `kind` values from `surface_input` →
`channel_input` and `surface_action` → `channel_action` in both store
implementations. But no Postgres migration updates existing rows, and the
delivery routing at `delivery.py:122` only checks for `channel_input` — it
will silently drop any in-flight deliveries with the old `surface_input` kind.
This violates CLAUDE.md's transport contract change rule.

Required work:
1. Add Postgres migration `0009_rename_delivery_kinds.sql` to update existing
   rows
2. Update SQLite registry store `_CREATE_SQL` if it references old kind values
3. Add a backwards-compatibility guard in `delivery.py` accepting both old and
   new values with a deprecation log, OR document that migration must run
   before deploying the new code
4. Add the same guard in `bridge.py:173` if using option (a)

Hard rules:
- The migration and code change must be documented as a coordinated pair
- No delivery kind value may be written by one version and unreadable by another

### F11. Remove remaining registry surface vocabulary from live schema/runtime

Post-audit review found that the registry store/runtime still carried live
`surface` vocabulary after F10:

- SQLite schema/runtime still used `surface_capabilities_json` and
  `origin_surface`
- Postgres store code still queried those old column names
- runtime registry-delivery code still accepted `surface_input` and
  `surface_action`
- structural gates exempted entire files instead of limiting the legacy tokens
  to explicit migration owners

Required work:
1. Rename the SQLite registry schema/runtime contract to
   `channel_capabilities_json` and `origin_channel`, with an explicit SQLite
   migration for existing databases
2. Add Postgres migration `0010_rename_registry_channel_columns.sql` to rename
   the remaining registry columns in-place
3. Remove runtime legacy delivery-kind normalization from
   `app/agents/bridge.py` and `app/agents/delivery.py`; old delivery kinds
   must be rewritten by migrations, not carried as a live runtime contract
4. Tighten structural gates so:
   - legacy registry column tokens appear only in explicit migration owners and
     migration tests
   - legacy delivery kind tokens appear only in explicit migration owners and
     migration tests

Hard rules:
- live app runtime/store code must not retain `origin_surface` or
  `surface_capabilities_json` after this slice
- live app runtime code must not accept `surface_input` or `surface_action`
  after this slice
- gates must use exact-owner exceptions, not whole-seam carve-outs

Exit criteria:
- SQLite and Postgres registry store code use only `channel_*` vocabulary
- runtime registry delivery handling no longer carries legacy `surface_*` kind
  compatibility
- legacy `surface_*` tokens are limited to historical migrations and explicit
  migration tests

### Post-Audit Acceptance Gates

All prior Architecture Remediation and Phase 8 Acceptance Gates must hold,
plus:

- worker.py contains no inline workflow logic
- `app/workflows/execution/finalization.py` exists with no `app.channels` imports
- Completion ownership is documented in worker_dispatch
- Usage recording failure handling is explicitly documented
- `execution_channel_context` is not defined in any `app/channels/` file
- `format_provider_error` is not defined in any `app/channels/` file
- `execution.py` does not define passthrough wrappers for workflow functions
- No extracted Telegram module imports behavioral functions from siblings
  (except routing targets)
- Gate test enforces sibling import discipline
- `shared_mode_dispatch.py` does not define `_shared_skills_inline_handler` or
  `_shared_inline_command_handler`
- `shared_mode_dispatch.py` ≤ 450 lines
- `cmd_start` and `cmd_help` use `@_command_handler`
- `PendingRequestWorkflowModel` and `TransportWorkflowModel` are frozen
- `run_pending_request_event` and `run_transport_event` do not mutate inputs
- `surface_binding_id` is renamed or deleted
- `store_plan.md` is committed with no local-only edits
- `status.md` correction log includes all remediation commits through the
  latest code-bearing closure slice, and the closing status artifact names that
  slice explicitly
- Postgres migration 0009 exists and renames delivery kinds
- Postgres migration 0010 exists and renames the remaining registry
  `surface_*` columns to `channel_*`
- runtime registry delivery handling no longer carries legacy
  `surface_input`/`surface_action` compatibility; migrations own the rewrite
- Registry store public method sets are identical between SQLite and Postgres
- Content store public method sets are identical between SQLite and Postgres
- No dead public store methods exist in one backend but not the other
- live app code retains no registry `surface_*` schema/runtime vocabulary
  outside explicit migration owners/tests
- Full test suite is green with recorded pass/skip/fail count

## Post-Remediation Policy

When this architecture remediation track is complete:

1. feature work may resume
2. any new decomposition must obey the no-satellite-back-import rule
3. any new test seam must follow the same injection/context pattern as production
4. durable transition systems must either use the repo-standard explicit machine
   style or be explicitly classified as procedural and non-durable
5. if a future feature needs to reopen a major architecture gate, it must do so
   explicitly in the plan before implementation

## Required Audits At Every Milestone

Each milestone must explicitly audit:

1. equivalent ingress paths across both channels
2. raw vs resolved state usage
3. completion ownership where background/recovery state is touched
4. durable state vs in-memory state authority
5. test boundary correctness
6. adjacent regression risk
7. whether a known pre-existing failing test needs to be fixed or formally reclassified before touching that contract
8. whether any deleted module path still has live imports
9. whether browser UI still uses registry HTTP ingress only

## Hard “Do Not” List

Do not:

- keep old helpers alive because tests still call them
- preserve bad architecture for stale tests
- add a temporary second authority “until later”
- put workflow logic in channel ingress, HTTP routes, or UI code
- centralize all inbound behavior into one mega orchestrator
- use aliasing or naming tricks that obscure whether one or two paths exist
- add new lifecycle features before the structural gates pass
- split registry into separate top-level architectural peers again
- let generic action envelopes become the workflow API

## Milestone Acceptance Gates

This section is sealed historical artifact language from the earlier
replacement-plan phase.

It is not the authoritative completion gate for the reopened remediation work.
The only authoritative gate list is:

- `Architecture Remediation Acceptance Gates`

above in this document.

Keep this section only as historical context for the pre-Phase-7 shape. Do not
use it to decide whether the repo is done.

## Success Criteria

This replacement plan is complete only when:

- runtime skills, provider guidance, credentials, and capabilities each have one owner
- no parallel old/new runtime paths exist
- Telegram and registry are both channels with ingress and egress over shared workflow modules
- registry UI performs all mutations through registry HTTP ingress
- Telegram ingress is not a mutable runtime state hub
- runtime and agents do not depend on channel internals
- channel decomposition does not rely on satellite modules importing back into a parent entrypoint
- Telegram presentation lives in its presenter layer
- registry HTTP and UI are structurally separated
- stale tests no longer influence architectural decisions
- tests follow the same explicit context and dependency boundaries as production code
- workflow modules are concern-owned and typed, not a universal action bus
- runtime composition/admission/dispatch are owned by `app/runtime/*`
- new channels can be added by writing channel packages and wiring them in composition, not reworking the architecture
