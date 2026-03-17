# Foundation-First Execution Plan

## Goal

Build the right seams first, then move runtime skills and provider guidance into
durable storage without baking in today's mistakes.

## Non-Negotiable Principles

- One abstraction, multiple implementations.
- No parallel paths for the same concern.
- Interfaces before implementations.
- Registry is the only public HTTP API.
- Telegram remains a first-class UI surface.
- Capability parity across Telegram and registry.
- Dedicated content schema.
- Bot runtime uses shared services in-process, not HTTP calls to registry, for
  runtime reads.
- SQLite/Postgres parity in the same slice.

## Core Problems To Fix First

1. "Skills" means two different things today.
   - Runtime skills: prompt/config/helper script skills for end users.
   - Routing skills: agent discovery/routing traits in the registry.
   - These must be separated.

2. Inbound abstraction is missing.
   - Outbound surface abstraction exists.
   - Inbound lifecycle logic is still mostly Telegram-specific.
   - Registry UI is not yet another implementation of the same inbound seam.

3. Content ownership is wrong.
   - Repo files
   - filesystem stores
   - session state
   - in-memory prompt composition
   - all mixed together

4. Config semantics are wrong.
   - `BOT_AGENT_SKILLS` falling back to `BOT_SKILLS` is a conceptual bug.
   - Config validation should not import repo/runtime catalog loading.

## Current Architectural Reality

### Runtime skills

Current runtime skills come from:

- repo `skills/catalog`
- filesystem managed store
- filesystem custom store
- session `active_skills`
- runtime prompt composition in `app/skills.py`

### Registry "skills"

The registry already uses "skills" for a different concept:

- agent-advertised routing/discovery capabilities
- stored in `skills_json`
- used by:
  - `list_capabilities()`
  - `skills_override`
  - `search_agents()`
  - routed-task eligibility

Files involved:

- `app/agents/runtime.py`
- `app/config.py`
- `app/registry_service/store.py`
- `app/registry_service/store_postgres.py`

These must be separated from runtime skills.

### Surface abstraction

Current abstraction is only partial:

- outbound surface abstraction exists in:
  - `app/transports/ports.py`
  - `app/transports/factory.py`
- inbound lifecycle interaction is still mostly Telegram-specific:
  - `app/telegram_handlers.py`
  - `app/skill_commands.py`

Registry UI is not yet another implementation of the same inbound lifecycle seam.

## Locked Decisions

1. Do the hard things first.
   - Do not defer the missing inbound abstraction.
   - Do not defer the runtime-skill vs routing-capability split.

2. Registry remains the only public HTTP/programmatic API surface in phase 1.
   - No second public bot-local API.

3. Telegram remains a first-class UI surface.
   - `/skills` stays.
   - Telegram and registry must be implementations of the same lifecycle
     abstraction.

4. Parity means capability parity, not identical widget parity.
   - Same operations
   - same invariants
   - same service layer
   - surface-appropriate UX

5. Activation remains in `SessionState.active_skills` for this refactor.
   - No normalized activation table in this slice.

6. Runtime skills and routing capabilities are distinct product concepts.
   - They must have distinct names, schemas, and APIs.

7. Built-in and imported runtime skills are immutable.
   - Custom skills support draft + publish.
   - Published revisions are immutable.
   - One active revision pointer is the current version.

8. Backed-up developer tooling content stays out of the repo and out of runtime.
   - `docs/codex-skills/*`
   - backed-up `CLAUDE.md`
   - backed-up `AGENTS.md`

## Naming And Domain Separation

### A. Runtime Skills

End-user bot skills:

- debugging
- code-review
- github-integration
- etc.

Used for:

- prompt composition
- provider config
- requirements
- helper scripts
- `/skills`

### B. Provider Runtime Guidance

Bot runtime provider instructions:

- Claude guidance
- Codex guidance

Used for:

- provider execution behavior

### C. Routing Capabilities

Agent-advertised routing/discovery traits in the registry.

Used for:

- discovery
- capability-based routing
- registry agent filtering
- operator visibility

Use these names consistently:

- `skills` = runtime skills
- `capabilities` = routing/discovery traits

## Target Architecture

There should be four layers:

### 1. Domain services

Single source of lifecycle/business truth.

Examples:

- `SkillCatalogService`
- `SkillActivationService`
- `ProviderGuidanceService`
- `SkillApprovalService`
- `SkillImportService`
- `CapabilityService`

### 2. Persistence ports

Explicit storage abstractions.

Examples:

- `ContentStore`
- `CapabilityStore`
- existing session store remains for activation state

### 3. Surface interaction ports

Shared inbound lifecycle abstraction.

Examples:

- `LifecycleSurface`
- `SkillLifecycleSurface`
- or a command/action dispatcher over typed operations

### 4. Surface implementations

- Telegram
- Registry UI + registry HTTP handlers
- future Slack

No surface should own separate business logic.

## Important Architecture Choice

Use a dedicated content schema, but do not force the bot to call registry over
HTTP for runtime content access.

Correct model:

- Registry hosts the only public HTTP API.
- Bot runtime and registry both use the same content services/store.
- Bot calls services in-process.
- Registry calls the same services through HTTP/UI handlers.

This gives:

- encapsulation
- one service layer
- one content schema
- no duplicated logic
- no runtime network dependency for prompt resolution
- standalone still works

## Phase 0: Fix The Missing Abstractions

### 0.1 Separate runtime skills from routing capabilities

Required changes:

- stop `BOT_AGENT_SKILLS` from falling back to `BOT_SKILLS` in `app/config.py`
- rename/clarify registry-facing "skills" to "capabilities" in the service layer
  and UI
- keep backward compatibility at the edge only if necessary, but the internal
  model must be clean

End state:

- runtime skills live in the content domain
- routing capabilities live in the registry capability domain
- no shared schema or config fallback pretending they are the same thing

### 0.2 Create a real inbound lifecycle abstraction

Current problem:

- Telegram owns command parsing and lifecycle orchestration
- Registry UI is a separate path
- There is no shared inbound seam for lifecycle operations

Required abstraction:

Add a surface-neutral lifecycle layer for operations such as:

- list skills
- read skill
- search skills
- create draft
- edit draft
- submit approval
- approve/reject
- publish/archive
- install/import/update/uninstall
- activate/deactivate/clear
- manage provider guidance

The important rule:

- Telegram and registry must call the same underlying typed operations

End state:

- Telegram `/skills ...` handlers become an adapter
- Registry HTTP/UI handlers become another adapter
- future Slack becomes another adapter

### 0.3 Pull lifecycle logic out of storage helpers

Current problem:

- `app/store.py` mixes storage with product semantics
- `app/skills.py` mixes loading, resolution, prompt composition, and authoring
  helpers

Required change:

Move business rules into services:

- install/update rules
- diff logic
- prompt-size checks
- approval logic
- precedence resolution
- import verification decisions

Storage modules should persist/query only.

## Phase 1: Define The Correct Service Layer

### 1.1 Runtime skill services

Create:

- `SkillCatalogService`
- `SkillActivationService`
- `SkillApprovalService`
- `SkillImportService`

Responsibilities:

- resolution
- lifecycle operations
- publish semantics
- diff generation
- prompt-size impact analysis
- import/update handling
- activation validation against session state

### 1.2 Provider guidance service

Create:

- `ProviderGuidanceService`

Responsibilities:

- effective guidance resolution
- revision lifecycle
- preview
- publish semantics

### 1.3 Capability service

Create:

- `CapabilityService`

Responsibilities:

- registry capability declarations
- capability overrides
- capability search/filter semantics

This remains separate from runtime skills.

## Phase 2: Define The Persistence Interfaces

Create explicit ports first.

Suggested modules:

- `app/content_models.py`
- `app/content_store_base.py`
- `app/content_store_sqlite.py`
- `app/content_store_postgres.py`
- `app/content_store.py`

Separate capability persistence if needed:

- `app/capability_store_base.py`
- or keep using registry store with renamed internal semantics

### Content domains in the content store

- runtime skills
- provider runtime guidance

### Content store rules

- SQLite/Postgres parity in the same slice
- no repo-file runtime lookups in the store
- no Telegram/registry surface logic in the store

## Phase 3: Data Model

### 3.1 Runtime skills

#### `skill_namespaces`

- `skill_id`
- `slug`
- `display_name`
- `description`
- `archived_at`
- `created_at`
- `updated_at`

#### `skill_tracks`

- `track_id`
- `skill_id`
- `source_kind` (`builtin`, `imported`, `custom`)
- `source_uri`
- `publisher`
- `version_label`
- `pinned`
- `is_mutable`
- `visibility` (`private`, `pending_approval`, `shared`)
- `owner_actor`
- `approved_by`
- `approved_at`
- `active_revision_id`
- `created_at`
- `updated_at`

#### `skill_revisions`

- `revision_id`
- `track_id`
- `digest`
- `instruction_body`
- `requirements_json`
- `provider_config_json`
- `changelog`
- `created_by`
- `created_at`

#### `skill_files`

- `file_id`
- `revision_id`
- `relative_path`
- `content_text`
- `content_type`
- `executable`
- `digest`

### 3.2 Provider runtime guidance

#### `provider_guidance_tracks`

- `guidance_id`
- `provider` (`claude`, `codex`)
- `scope_kind` (`system`, `instance`)
- `scope_key`
- `is_mutable`
- `active_revision_id`
- `created_at`
- `updated_at`

#### `provider_guidance_revisions`

- `revision_id`
- `guidance_id`
- `digest`
- `content`
- `format`
- `created_by`
- `created_at`

## Phase 4: Keep Activation In Session State

This is explicit and non-negotiable for this slice.

- `SessionState.active_skills` remains the only activation source of truth
- `SkillActivationService` mutates session state through existing session storage
- no normalized activation table

## Phase 5: Seed And Migration Model

### 5.1 Repo seed assets

Move product seed assets into internal app-owned seed locations:

- `app/content_seed_assets/skills/...`
- `app/content_seed_assets/provider_guidance/...`

These are seed assets only.

### 5.2 Existing filesystem migration

Import existing:

- custom skills from `~/.config/octopus-agent/skills/custom`
- managed refs/objects from `~/.config/octopus-agent/skills/managed`

Preserve where possible:

- provenance
- installed timestamps
- version labels
- publisher
- pin state

### 5.3 Built-in updates

Built-in seeded updates advance automatically.

## Phase 6: Surface Parity Plan

Telegram and registry must share capability parity.

This does not require identical UX mechanics, but it does require the same
operations and rules.

### 6.1 Required lifecycle capability set

Both Telegram and registry must support:

- list skills
- info
- search
- activate
- deactivate
- clear
- create draft
- edit draft
- submit approval
- approve/reject
- publish
- archive
- import/install
- uninstall
- update
- diff/history
- provider guidance view/edit/publish/preview

### 6.2 UX interpretation

#### Registry UI

Best for:

- richer forms
- side-by-side diff
- revision history
- approval dashboard
- provider guidance editing
- file/script editing

#### Telegram

Must still support the same lifecycle, but through:

- guided multi-step chat flows
- buttons/callbacks
- previews
- compact diff/history presentation
- attachment/upload or chunked edit flows where needed

## Phase 7: Programmatic API Rule

Registry remains the only HTTP API surface in phase 1.

That means:

- registry service exposes lifecycle APIs
- Telegram uses service calls directly, not HTTP
- no second public bot-local API is introduced

### Important implementation note

Registry and bot runtime do not automatically share storage today.

So this plan requires an explicit shared content-backend configuration model.

### Recommended approach

- the content store has its own backend selector
- both bot runtime and registry service point to the same content backend
- SQLite same-host deployments can share the same DB files
- Postgres deployments share the same schema/database

Do not accidentally store runtime skills inside the registry metadata DB without
explicitly designing that.

## Phase 8: API Surface

Use separate API namespaces so runtime skills do not collide with registry
capabilities.

### Runtime skill catalog API

Recommended namespace:

- `/v1/catalog/skills`

Endpoints:

- `GET /v1/catalog/skills`
- `GET /v1/catalog/skills/{slug}`
- `GET /v1/catalog/skills/{slug}/tracks`
- `GET /v1/catalog/skills/{slug}/revisions`
- `GET /v1/catalog/skills/{slug}/files`
- `POST /v1/catalog/skills`
- `PATCH /v1/catalog/skills/{slug}`
- `POST /v1/catalog/skills/{slug}/revisions`
- `POST /v1/catalog/skills/{slug}/publish`
- `POST /v1/catalog/skills/{slug}/submit-approval`
- `POST /v1/catalog/skills/{slug}/approve`
- `POST /v1/catalog/skills/{slug}/archive`
- `POST /v1/catalog/skills/{slug}/install`
- `POST /v1/catalog/skills/{slug}/uninstall`
- `POST /v1/catalog/skills/{slug}/update`
- `GET /v1/catalog/skills/{slug}/diff`
- `GET /v1/catalog/skills/search`
- `POST /v1/catalog/skills/import`
- `POST /v1/catalog/skills/{slug}/validate`
- `POST /v1/catalog/skills/{slug}/preview`

### Activation API

- `GET /v1/conversations/{conversation_key}/skills`
- `POST /v1/conversations/{conversation_key}/skills/{slug}/activate`
- `POST /v1/conversations/{conversation_key}/skills/{slug}/deactivate`
- `POST /v1/conversations/{conversation_key}/skills/clear`

### Provider guidance API

- `GET /v1/provider-guidance`
- `GET /v1/provider-guidance/{provider}`
- `GET /v1/provider-guidance/{provider}/revisions`
- `POST /v1/provider-guidance/{provider}/revisions`
- `POST /v1/provider-guidance/{provider}/publish`
- `GET /v1/provider-guidance/{provider}/effective`
- `POST /v1/provider-guidance/{provider}/preview`

### Capability API

Keep separate. Do not merge with runtime skills.

Current registry capability endpoints/store semantics should evolve under a
capability name, not a runtime-skill name.

## Phase 9: Runtime Resolution

For each skill slug in session state:

1. resolve namespace
2. choose effective track by precedence:
   - custom
   - imported
   - builtin
3. load active revision
4. compose:
   - instruction body
   - requirement schema
   - provider config
   - helper files

For provider guidance:

1. resolve effective guidance from content store
2. inject into provider execution as current runtime already does
3. optional file materialization later only if needed

## Phase 10: Telegram Authoring Model

Because abstraction parity matters, Telegram cannot simply lose authoring.

### Recommended Telegram authoring model

- `/skills create <name>` creates a private draft
- bot walks the user through:
  - display name
  - description
  - instruction body
  - provider config editing
  - helper file add/remove/import
- `/skills edit <name>` resumes/edit draft
- `/skills submit <name>` sends for admin approval
- `/skills publish <name>` if permitted
- `/skills history <name>` and `/skills diff <name>`

This is more work, but it is the correct abstraction-respecting path.

## Phase 11: Specific Existing Problems To Fix

### 11.1 Config semantics

Fix `app/config.py`:

- stop validating `BOT_SKILLS` by importing `load_catalog()`
- stop making `BOT_AGENT_SKILLS` fall back to runtime `BOT_SKILLS`
- validate runtime skills and capabilities through the appropriate services

### 11.2 Store/service split

Refactor:

- `app/store.py`
- `app/skills.py`

so that:

- storage modules persist/query
- services own lifecycle logic
- surfaces call services

### 11.3 Registry naming

Refactor registry-facing "skills" concept toward "capabilities" in the service
layer and UI to avoid ongoing confusion.

### 11.4 Shared content backend config

Design and implement a content-backend selector used by both:

- bot runtime
- registry service

This is required if registry is the sole HTTP API surface for lifecycle.

## Phase 12: Implementation Sequence

1. Separate runtime skills from routing capabilities in config/model terminology.
2. Add inbound lifecycle abstraction/service layer.
3. Rebase Telegram `/skills` and registry lifecycle handlers onto that service
   layer.
4. Add content store interfaces and models.
5. Add SQLite/Postgres content store implementations + migrations + contract
   tests.
6. Add built-in seed loader and provider guidance seed loader.
7. Add filesystem migration importer.
8. Switch runtime resolution to DB-backed content store.
9. Remove repo/runtime dependency on `skills/catalog` and `skills/store`.
10. Expand Telegram and registry UI flows until lifecycle capability parity is
    satisfied.

## Acceptance Criteria

- Runtime skills and capabilities are separate concepts everywhere.
- Telegram and registry both use the same lifecycle services.
- Registry is the only public API.
- Telegram remains a first-class lifecycle UI.
- Activation still lives only in session state.
- Runtime skills and provider guidance are DB-backed.
- Built-ins seed automatically and update automatically.
- Custom/private/shared workflow works.
- Registry UI supports rich editing with CodeMirror 6.
- Telegram supports the same operations via guided flows/imports.
- Repo/file runtime dependencies for skills are removed.
- SQLite/Postgres parity is enforced by tests.

## Assumptions

- No external third-party dependency on current registry `/v1/ui/capabilities`
  semantics beyond this repo/product. If there is, handle rename as a
  coordinated breaking change.
- Standalone deployments keep working without registry HTTP because bot runtime
  uses services in-process.
