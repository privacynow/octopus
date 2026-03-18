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

The architecture-and-lifecycle recovery plan is complete through Milestone 13.

What is now true:

1. the repo shape follows the `channels/`, `workflows/`, `ports/`, and `runtime/` model
2. the old `transports/` ownership and ingress monoliths are no longer the live architecture
3. lifecycle schema, lifecycle workflows, Telegram parity, registry parity, and registry rich editing are all landed
4. the registry browser UI mutates through registry HTTP ingress rather than a server-side shortcut path

The feature freeze that existed earlier in this plan is now lifted.

The plan below remains authoritative as an architectural contract and milestone
record, but the gating condition has changed:

- foundational recovery work is complete
- lifecycle work is complete through the planned editor milestone
- new feature work is unblocked
- hardening is now a normal follow-up slice, not a global blocker

## Current Plan State

As of 2026-03-17:

- Milestones 1-13 are complete
- the earlier feature freeze is lifted
- no additional architecture freeze milestone remains open in this plan
- future work must preserve the channel/workflow/runtime ownership model rather than reopen it

### Feature Freeze Status

The earlier freeze existed to prevent new work from landing on bad
foundations. That condition no longer applies.

Feature work is now allowed under the normal rules:

- no parallel paths
- no channel-owned workflow logic
- no registry UI side doors
- no stale-test-driven compatibility seams
- new work must land on the current `channels/*`, `workflows/*`, `ports/*`, and `runtime/*` shape

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
      contracts.py
    credentials/
      management.py
      contracts.py
    conversation/
      control.py
      settings.py
      contracts.py
    pending/
      requests.py
      contracts.py
    recovery/
      replay.py
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

## Next Execution Track

The architecture recovery track is complete. There is no Milestone 14 in this
plan.

The next concrete work is ordinary feature delivery on top of the now-stable
architecture.

Execution policy for post-M13 work:

1. new feature slices are allowed and no longer blocked by the earlier freeze
2. hardening work is optional follow-up work, not a prerequisite to shipping new features
3. any new feature must land directly on `channels/*`, `workflows/*`, `ports/*`, and `runtime/*`
4. if a proposed feature requires reopening the architecture, that architectural work must be planned explicitly rather than smuggled into feature code

Implementation guidance for post-M13 work:

- prefer adding new behavior to the correct current owner over preserving transitional shapes
- preserve valid contracts and tests, not legacy file paths
- delete or rewrite stale tests in the same slice if they encode dead ownership
- do not add aliases to “smooth” a new feature onto the wrong layer
- if a feature needs a new channel, add a new channel package rather than branching inside an existing one
- if a feature needs a new workflow concern, add a concern-owned workflow module rather than expanding a generic dispatcher

Allowed next-track work now includes:

- new product features
- lifecycle UX improvements
- approval-policy enhancements
- additional channels
- non-blocking hardening and audit slices

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

Feature work may resume only when all of the following are true:

- channels are the only external boundary shape in the repo
- egress lives under `ports/egress.py` and `channels/*/egress.py`
- current workflows live under `app/workflows/*` with local contracts
- `runtime/composition.py` owns channel wiring
- `runtime/*` owns admission and dispatch
- Telegram and registry are both thin channel packages over shared workflow modules
- registry browser UI performs all mutations through registry HTTP ingress
- no deleted legacy path remains imported

## Success Criteria

This replacement plan is complete only when:

- runtime skills, provider guidance, credentials, and capabilities each have one owner
- no parallel old/new runtime paths exist
- Telegram and registry are both channels with ingress and egress over shared workflow modules
- registry UI performs all mutations through registry HTTP ingress
- stale tests no longer influence architectural decisions
- workflow modules are concern-owned and typed, not a universal action bus
- runtime composition/admission/dispatch are owned by `app/runtime/*`
- new channels can be added by writing channel packages and wiring them in composition, not reworking the architecture
