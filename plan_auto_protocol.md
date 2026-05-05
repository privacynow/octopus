# Auto Protocol Execution Plan

## Status

This document is the execution contract for rebuilding Auto Protocol as a
commercial product feature. It replaces the prior plan and the abandoned local
`feature/protocol` implementation direction.

The implementation must start from the clean product branch, not from the
stale `feature/protocol` branch. That branch proved several useful concepts,
but it also introduced unsafe package shaping, source-context loss on revise,
broad lexical gates, weak event summaries, and a plan rewrite that removed too
much product context. Treat it as research input only.

This plan has no optional phases and no deferred product gaps. If a capability
is listed here, it is part of the implementation. If a current behavior
conflicts with this document, change the behavior rather than adding a second
path around it.

## Problem Statement

Manual protocol authoring is too demanding for the users we are building for.
A user may understand the business, creative, operational, financial, or
technical outcome they need, but they should not need to understand agentic
workflow design before Octopus becomes useful.

Today a user must know how to decompose work into stages, declare participants,
map agents and skills, write stage prompts, define artifacts, add review loops,
configure transitions, validate, publish, run, and inspect outputs. That is
not a commercially acceptable default path.

Auto Protocol must become the easy button inside Registry and Telegram:

1. The user describes the outcome in plain language.
2. Octopus analyzes the requirement and designs a requirement-specific workflow.
3. Octopus produces a normal protocol draft with focused work packages,
   artifact contracts, critical reviews, revision loops, assignments, run
   inputs, and acceptance evidence.
4. The user can inspect, modify, publish, and run the protocol from Registry or
   Telegram.
5. When the run completes, the primary user-facing artifact is obvious and
   easy to open. The user should not hunt through review notes and intermediate
   design artifacts to find the thing they asked for.

The product value is not prompt forwarding. A generated protocol is only useful
if it decomposes the requirement better than a generic CLI prompt would, guides
agents through the right subproblems, forces serious review, records revisions,
and produces inspectable evidence.

## Lessons Learned

### From the Generated Game Runs

The Profits of Doom runs showed that richer decomposition improves outcomes.
When the protocol included requirements, domain grounding, UX, asset/content
planning, implementation, review, and verification loops, the result improved
materially compared with a single build stage.

The same runs also showed the current weaknesses:

- output quality still depends too much on the user's prompt wording
- reviewers often accept shallow artifacts too readily
- review strictness must be enforced in stage instructions and transitions,
  not left to user phrasing
- the primary playable artifact is buried among many review and planning
  artifacts
- the final artifact stage can appear too early relative to late review and
  evidence stages
- late reviewers sometimes review upstream design decisions that should already
  have been accepted earlier

### From the Manufacturing Analytics Runs

The manufacturing analytics example showed that a technically supported
protocol can still produce a poor user outcome if the protocol does not guide
the agent through progressive user paths, data readiness, synthetic data,
chart-first workflows, drilldowns, recommendations, and evidence.

The product fix is not to hand-edit one artifact. The protocol generator must
create the right staged work and quality bars so the run naturally produces an
artifact a non-technical user can understand.

### From the Risk Engine Scenario

The risk decision engine scenario makes the lexical ceiling obvious:

- high-performance risk decision engine
- Flink and Java
- dynamic feature definitions
- DSL-based rules engine
- built-in machine learning model catalog
- payments, onboarding, money movement, lending, investor onboarding
- governance, audit, performance, explainability, maintainability
- rich operator UI

A broad token system can detect "risk", "data", "UI", and "architecture". It
cannot reliably infer the real work: Flink topology, Java build strategy,
streaming state and backpressure, DSL grammar and rule evaluation, feature
versioning, model catalog lifecycle, risk-domain scenarios, auditability,
performance benchmarks, security boundaries, human maintainability, and
release evidence.

Adding domain keywords is the wrong direction. Auto Protocol needs a
model-assisted semantic planning step, with deterministic SDK policy enforcing
the shape and safety of the result.

### From the Abandoned Branch

The abandoned branch introduced useful product ideas but implemented them
without enough invariants:

- package disabling could remove required outcome and verification packages
- reshape after revise could lose the original source protocol context
- a server-side review cap existed but overrides bypassed it
- broad tokens still activated expensive packages
- session events exposed too little data for useful status UX
- the plan was compressed instead of made execution-ready

Do not salvage that implementation wholesale. Reimplement the useful concepts
through one coherent SDK-owned pipeline.

## Product Principles

1. **One canonical protocol path.**

   Auto Protocol produces and revises normal protocol documents. There is no
   generated-protocol schema, Registry-only schema, Telegram-only schema, or
   import-only schema.

2. **No duplicate implementations.**

   Registry and Telegram call the same Registry API, the same SDK records, the
   same compiler, the same validation, the same publish path, and the same run
   path. If behavior differs by surface, that difference must be presentation
   only.

3. **No backwards-compatibility shims.**

   Use one request shape, one response shape, and one event shape. Do not add
   alias fields, compatibility branches, or old/new generator modes. If a field
   name is wrong, rename it and update callers and tests in the same change.

4. **No silent fallback to weak planning.**

   Model-assisted semantic planning is part of the product path. Deterministic
   lexical signals may provide hints and coverage checks, but they must not be
   the authority for serious protocol shape. If the design worker cannot
   produce a valid structured plan, the session is blocked with a clear error.

5. **Product code owns behavior.**

   The model proposes structured analysis and work packages. SDK code validates,
   normalizes, compiles, repairs, rejects invalid topology, applies policies,
   and emits canonical protocol JSON.

6. **Registry stores state; bot runtimes execute providers.**

   Registry owns sessions, persistence, HTTP, UI, events, publish, and run
   orchestration. Provider/model execution happens in bot runtime code through
   SDK interfaces. Registry must not become an LLM runtime.

7. **Non-technical users are the default audience.**

   Users should not need to know JSON, Docker, model prompts, internal stage
   keys, database tables, or artifact contracts. The UI should show intent,
   stages, roles, assignments, warnings, primary artifact, and actions in plain
   human terms.

8. **Primary outcomes are first-class.**

   Every generated protocol must declare exactly one primary artifact contract
   unless the user explicitly asks for a multi-output deliverable. Runs UI and
   Telegram must surface that artifact before supporting reviews, plans, and
   evidence.

9. **Reviews are adversarial enough to matter.**

   Reviewers must inspect artifacts, compare against the original requirement
   and accepted upstream artifacts, look for better approaches, and choose
   `revise` when quality is materially below the bar. Friendly rubber-stamp
   reviews are product failures.

10. **Reviewer context stays independent.**

    Distinct review domains use distinct participant keys. Runtime repeats of
    the same stage can reuse that stage participant's thread, but separate work
    and review domains must not collapse into one conversation.

11. **Published versions remain immutable.**

    Revising a published protocol prepares a draft revision. Existing runs
    remain tied to the published version they used.

12. **Execution evidence matters.**

    A run is not commercially ready because every stage emitted text. It is
    ready when the primary artifact exists, opens or can be inspected, satisfies
    the requirement, survived critical review, and has release evidence.

13. **Stage count is a product and cost constraint.**

    Dozens of stages are not acceptable as the default answer to rich
    requirements. They are harder for humans to inspect, harder to assign, and
    expensive to run. Auto Protocol must design the smallest workflow that can
    honestly deliver and review the requested outcome. When a requirement is too
    large for a bounded protocol, the system should produce a scoped delivery
    tranche with explicit assumptions and backlog, or block with a clear
    request to narrow the outcome. It must not silently generate a 30-stage
    token burner.

## Target User Flows

### Registry: Generate New Protocol

1. User opens the Protocols workspace.
2. User chooses Auto Protocol.
3. User enters a high-level requirement and constraints.
4. Registry creates an Auto Protocol session.
5. Registry dispatches design work to a provider-capable bot runtime through
   the SDK-defined design job interface.
6. The design worker returns structured analysis: requirement summary,
   assumptions, domain risks, work packages, artifact contracts, role needs,
   review rubrics, primary artifact, and suggested run inputs.
7. SDK policy compiles that analysis into a canonical protocol draft.
8. Registry shows a clear preview:
   - outcome summary
   - inferred work packages and rationale
   - stage map
   - review loops
   - roles and proposed assignments
   - primary artifact
   - supporting artifacts
   - warnings and blockers
9. User can ask Auto Protocol to revise the draft.
10. User applies the draft into the normal protocol editor.
11. User publishes and runs through the normal protocol lifecycle when gates
    pass.

### Registry: Improve Existing Protocol

1. User opens an existing draft or published protocol.
2. User chooses Improve with Auto Protocol.
3. Registry includes the full source protocol document in the design job.
4. User enters the desired change.
5. The same model-assisted analysis and compiler path produces a revised
   canonical draft.
6. Registry previews what changed in stages, roles, artifacts, assignments,
   run inputs, and primary artifact behavior.
7. Applying a draft protocol updates that draft.
8. Applying a published protocol creates or updates the draft revision only.

### Telegram: Generate, Modify, Publish, Run

1. User sends `/protocol auto <requirement>`.
2. Telegram sends the same Auto Protocol request shape to Registry.
3. Telegram receives the same session shape as Registry.
4. Telegram renders compact cards:
   - summary
   - work packages
   - stages
   - roles
   - artifacts
   - warnings
   - blockers
5. User can ask for modifications from Telegram.
6. If the generated draft is valid and assignments are resolved, Telegram can
   apply, publish, and run the protocol with explicit user button actions.
7. After a run starts, Telegram shows progress and then promotes the primary
   artifact when it is produced.

### Telegram: Improve Existing Protocol

1. User references a protocol and sends a change request.
2. Telegram starts the same revise session used by Registry.
3. Telegram renders the summary, changes, warnings, and actions.
4. User can apply, publish, run, or open the full editor in Registry.

## Target Architecture

### Required Pipeline

```text
User requirement
  -> Registry Auto Protocol session
  -> design job dispatched to bot runtime
  -> provider-backed semantic planner returns typed SDK records
  -> SDK merges analysis with deterministic policy
  -> SDK compiles one canonical protocol document
  -> SDK validates, repairs structural issues, and blocks semantic failures
  -> Registry stores session and emits events
  -> Registry/Telegram render the same session
  -> user applies/publishes/runs through existing lifecycle
  -> Runs UI/Telegram surface status and primary artifact
```

There is no alternate lexical-only product path. Lexical and deterministic
logic remain useful for coverage terms, safety checks, repair, and validation,
but not as the sole designer for serious workflows.

### Module Ownership

`octopus_sdk/protocols/auto_design.py`

- Own typed Auto Protocol request/session/analysis/plan records.
- Own work package, artifact, role, stage, review, and primary artifact
  records.
- Own the compiler from structured plan to canonical protocol JSON.
- Own semantic validation and repair.
- Own render summaries that are surface-neutral.

`octopus_sdk/protocols/ports.py`

- Define the Auto Protocol session port used by clients.
- Define the design job/model port used by Registry and bot runtimes.
- Define typed request and response records for provider-backed planning.

`octopus_registry/protocol_http.py`

- Own HTTP routes and request normalization.
- Own auth checks and action gates.
- Do not call model providers.
- Do not compile protocols in browser-specific or Telegram-specific ways.

`octopus_registry/protocol_store.py` and `octopus_registry/store_postgres.py`

- Persist sessions, events, plans, draft documents, warnings, blockers,
  primary artifact metadata, and run/publish linkage.
- Return event summaries rich enough for user-facing status.

`app/`

- Own bot runtime execution of design jobs.
- Use existing provider adapters and SDK contracts.
- Return structured planner output or typed errors.
- Do not write Registry-specific protocol variants.

`octopus_registry/ui/js/components/protocol-workspace.js`

- Own Registry Auto Protocol UI.
- Render the shared session and summaries.
- Do not implement generation logic in JavaScript.

Registry run UI modules

- Promote primary artifacts.
- Render status, current stage, review loops, failures, blockers, and evidence.
- Collapse supporting plans and review notes behind the primary outcome.

`app/runtime/telegram_ingress.py`, `app/runtime/telegram_protocols.py`,
`app/presentation/telegram.py`

- Own Telegram commands, callbacks, and presentation.
- Call the same Registry Auto Protocol endpoints.
- Render the same concepts compactly.

## SDK Records

The implementation should use explicit records, not raw dictionaries crossing
major boundaries.

Required records:

- `ProtocolAutoDesignRequestRecord`
- `ProtocolAutoDesignSessionRecord`
- `ProtocolAutoDesignAnalysisRecord`
- `ProtocolAutoDesignModelRequestRecord`
- `ProtocolAutoDesignModelResponseRecord`
- `ProtocolAutoDesignWorkPackageRecord`
- `ProtocolAutoDesignArtifactPlanRecord`
- `ProtocolAutoDesignPrimaryArtifactRecord`
- `ProtocolAutoDesignRolePlanRecord`
- `ProtocolAutoDesignStagePlanRecord`
- `ProtocolAutoDesignReviewPolicyRecord`
- `ProtocolAutoDesignRunProfileRecord`
- `ProtocolAutoDesignWarningRecord`
- `ProtocolAutoDesignEventSummaryRecord`
- `ProtocolAutoDesignChangeSummaryRecord`

Required request fields:

- `mode`: `create` or `revise`
- `surface`: `registry`, `telegram`, or `api`
- `requirement_text`
- `constraints_text`
- `target_protocol_id`
- `target_version_id`
- `target_draft_revision`
- `source_document`
- `available_agents`
- `available_skills`
- `workspace_ref`
- `actor_ref`
- `chat_ref`
- `idempotency_key`

Do not add alias fields. Callers must use the canonical field names.

Required model response fields:

- normalized requirement summary
- domain and risk assessment
- assumptions
- open questions that block generation
- work packages with stable keys and rationale
- roles and required skills
- artifact contracts
- primary artifact contract
- review rubrics
- stage topology hints
- run input recommendations
- acceptance criteria
- evidence requirements
- warnings

The model response is not a protocol document. It is structured input to the
SDK compiler.

## Requirement Analysis

The semantic planner must infer work from the user's actual requirement, not
from customer examples or a closed keyword table.

For a game requirement, it may infer game design, art direction, animation,
sound, playable implementation, playtesting, and release evidence.

For manufacturing analytics, it may infer data readiness, synthetic data,
quality checks, dashboard design, analytics dimensions, drilldowns,
recommendations, usability review, browser implementation, and evidence.

For a risk decision engine, it may infer streaming architecture, Flink topology,
Java service structure, DSL grammar, rule execution, feature lifecycle, model
catalog governance, risk-domain scenarios, audit/explainability, UI authoring,
performance testing, and operational controls.

These examples are acceptance probes, not product branches. The implementation
must not contain branches for games, manufacturing, fintech, drones, defense,
or any named customer domain.

## Work Package Policy

Every work package must have:

- stable `package_key`
- human display name
- rationale
- owned role
- required skills
- artifact key and artifact description
- dependencies on prior artifacts
- quality bar
- review role
- review rubric
- allowed revise target

Required package rules:

- A generated protocol must include a requirements/planning package.
- A generated protocol must include exactly one primary outcome package unless
  the user's requirement explicitly demands multiple primary deliverables.
- A generated protocol must include a final adversarial outcome acceptance
  stage that inspects or exercises the primary artifact and records release
  evidence.
- Packages that produce artifacts must have a review or acceptance gate.
- Core outcome and acceptance packages cannot be removed by any shaping or
  revision operation.
- If a requested reshape would remove the primary outcome, verification, or
  acceptance path, the SDK blocks the session.
- Related subproblems should be consolidated into one work package when a
  separate package would create a shallow stage or duplicate review.
- The planner must include a stage-count rationale when it proposes more than
  the standard budget.

## Stage Topology

The compiler must produce a workflow that is easy to reason about:

1. Requirements/planning work.
2. Requirements review.
3. Domain, architecture, data, UX, content, asset, risk, or other inferred work
   packages, each followed by its own review when it produces a material
   artifact.
4. Primary outcome generation/integration.
5. Final adversarial outcome acceptance.

Stage budgets:

- Small focused outcome: 5 to 7 stages.
- Standard serious outcome: 8 to 12 stages.
- Complex commercial outcome: 13 to 16 stages.
- Hard cap: 18 stages.

The hard cap includes review and acceptance stages. A proposed plan above the
cap is invalid. The compiler must consolidate adjacent packages, scope the
protocol to a coherent first delivery tranche, or block the session with a
clear narrowing request.

The primary outcome stage should be the second-last stage in normal generated
protocols. The last stage reviews or exercises that outcome, can send it back
to the outcome stage with concrete feedback, and records final release
evidence when accepted.

Avoid late review sprawl. Do not add several final reviewers after the primary
artifact is generated. Upstream plans, UX, data models, research, and
architecture should be reviewed at the time they are produced. If the final
artifact review finds that an upstream assumption was wrong, it sends the work
back to the primary outcome stage with specific corrective requirements rather
than adding a new late design-review chain.

## Review Policy

Review stages must be strict by default.

Reviewer instructions must require:

- direct artifact inspection
- comparison against original requirement
- comparison against accepted upstream artifacts
- evidence checks
- identification of missing depth, missing polish, missing tests, and weak
  assumptions
- revise decisions when material doubt remains
- concrete revision instructions, not vague criticism

The first review pass must use an adversarial posture. Reviewers should not
accept work because it is plausible or because a prior stage created something.
They must accept only when the artifact satisfies the quality bar.

Each review domain gets a distinct participant key. Repeated attempts of the
same stage use the same participant key for continuity. Different review
domains do not share participant keys.

Server-side review loop limits are authoritative and capped in SDK policy. UI,
Telegram, and API callers cannot bypass the cap.

## Primary Artifact Policy

Every generated protocol must declare primary artifact metadata in the protocol
document:

- `primary_artifact_key`
- display name
- produced by stage
- artifact kind
- expected path
- open/preview/browse behavior
- evidence requirements
- supporting artifact keys

Runs UI must use this metadata to show a primary outcome panel at the top of
run detail pages:

- current status
- primary artifact status
- open/preview/download/browse actions
- produced by stage
- latest size and observed time
- verification or acceptance state
- direct link to release evidence

Supporting artifacts remain available, but they should be grouped by purpose:

- planning
- domain/architecture/data/UX/content
- implementation support
- reviews
- release evidence

Telegram must follow the same hierarchy: primary artifact first, supporting
artifacts second.

## Session Events And Status UX

End users cannot watch bot logs. Auto Protocol and protocol runs must surface
state through product events.

Auto Protocol session events must include safe summaries for:

- session created
- design job queued
- design job running
- model analysis received
- compiled
- blocked
- revised
- applied
- published
- run started
- run linked

Event summaries must include enough data for Registry and Telegram:

- target protocol id
- source protocol id
- run id
- current status
- warning codes
- blocker codes
- unresolved assignment count
- stage count
- package count
- primary artifact key
- change summary
- actor
- timestamp

Runs UI must also show protocol execution status without requiring logs:

- current stage
- completed stage count
- active review loop
- last decision
- last failure
- blocked reason
- artifact production progress
- primary artifact availability

## Generation And Revision

Create and revise use the same pipeline.

Create:

```text
requirement + constraints
  -> model-assisted analysis
  -> SDK compile and validate
  -> session preview
  -> apply as normal draft
```

Revise:

```text
source protocol document + change request + constraints
  -> model-assisted analysis
  -> SDK compile and validate
  -> change summary and preview
  -> apply to the intended draft identity
```

Revision must never regenerate from only the user's latest change request when
there is a source protocol. The full source document and prior generated
context must be included.

Revision must not use a string patcher or a keyword stage appender. It uses the
same semantic planner, compiler, validation, and readiness gates as create.

## Registry API

Use one HTTP surface:

- `POST /v1/protocol-auto/sessions`
- `GET /v1/protocol-auto/sessions/{session_id}`
- `POST /v1/protocol-auto/sessions/{session_id}/revise`
- `POST /v1/protocol-auto/sessions/{session_id}/apply`
- `POST /v1/protocol-auto/sessions/{session_id}/publish`
- `POST /v1/protocol-auto/sessions/{session_id}/run`
- `GET /v1/protocol-auto/sessions/{session_id}/events`

Request and response bodies must use the SDK canonical fields. Update OpenAPI
in the same change as code.

Readiness gates:

- validation must pass
- semantic validation must pass
- design job must be complete
- assignments must be resolved or deliberately mapped to connected agents
- primary artifact contract must exist
- publish and run require explicit user action

Blocked responses must include:

- error code
- human message
- validation summary
- blocker list
- warning codes
- next action guidance

## Bot Runtime Design Worker

Provider-backed planning belongs in `app/`, not Registry.

Implementation requirements:

1. Registry creates a session and dispatches a design job.
2. Bot runtime receives the job through the existing runtime/registry
   integration pattern.
3. Bot runtime invokes the configured provider through existing provider
   adapters.
4. Provider prompt requests structured planner output matching SDK records.
5. Bot runtime validates the provider output shape before returning it.
6. Registry persists the returned typed payload.
7. SDK compiles and validates.

Design worker failures become session blockers with clear user-facing messages.
They must not silently fall back to a weaker protocol.

## Registry UI

The Registry UI must be progressive and outcome-focused.

After the user submits the initial requirement, the second screen has two
states:

- while planning is running, it must show useful progress context so users know
  the planner is analyzing requirements, shaping work packages, compiling the
  protocol, and validating readiness
- after planning completes, it must show a compact review surface, not a dense
  raw dump of every inferred stage and package

Auto Protocol preview should show:

- plain-language outcome summary
- primary artifact contract
- work package list and rationale
- stage map with review loops
- assignment readiness
- blockers and warnings
- publish/run readiness
- change summary for revisions

The user should be able to:

- revise the requirement
- revise an existing protocol
- apply the draft
- publish
- publish and run
- open the full protocol editor
- inspect blockers
- inspect assignment needs

The UI must not allow removal of required core packages. Any shape editing must
be submitted to SDK validation and can be rejected.

Narrow mode must remain usable. Menus, pills, dialogs, stage lists, warnings,
and artifact actions must not overlap. Test in real Safari.

## Telegram UI

Telegram must be a real authoring surface.

Commands:

- `/protocol auto <requirement>`
- `/protocol improve <protocol-ref> <change request>`
- `/protocol auto status`

Telegram messages must include:

- generated protocol summary
- primary artifact contract
- stages
- work packages
- artifacts
- assignment readiness
- warnings and blockers
- actions

Buttons:

- Summary
- Work packages
- Stages
- Artifacts
- Warnings
- Modify
- Apply Draft
- Publish
- Run
- Open Registry

When a generated protocol has no blockers, the user must be able to publish and
run from Telegram without opening Registry. When blockers exist, Telegram must
state them clearly and direct the user to the next concrete action.

## Implementation Sequence

All phases are required.

### Phase 1: Contract And Records

Files:

- `octopus_sdk/protocols/auto_design.py`
- `octopus_sdk/protocols/models.py` for records shared outside Auto Protocol
- `octopus_sdk/protocols/ports.py`
- `octopus_sdk/protocols/__init__.py`

Work:

1. Define canonical Auto Protocol records.
2. Define design model/job ports.
3. Remove alias-field request handling from the Auto Protocol path.
4. Add primary artifact records.
5. Add rich event summary records.
6. Add review policy records.

Exit gate:

- SDK records round-trip through model validation.
- Type exports are stable.
- Tests prove no alias request fields are accepted in the Auto Protocol API
  contract.

### Phase 2: Semantic Planner Worker

Files:

- `app/` runtime worker modules
- provider adapter integration files
- `octopus_registry/protocol_store.py`
- `octopus_registry/store_base.py`
- `octopus_registry/store_postgres.py`

Work:

1. Add design job dispatch from Registry to bot runtime.
2. Add bot runtime handler for Auto Protocol design jobs.
3. Add provider prompt and structured output validation.
4. Persist the typed planner response, job status, and errors.
5. Surface job events.

Exit gate:

- Registry does not execute providers in-process; it synchronously orchestrates
  provider-backed planning through the bot management RPC.
- A fake provider-backed worker can produce structured planner output.
- Worker failure blocks the session with a user-readable error.

### Phase 3: Compiler And Semantic Validation

Files:

- `octopus_sdk/protocols/auto_design.py`
- protocol validation tests

Work:

1. Compile structured work packages to canonical protocol JSON.
2. Enforce required packages and primary artifact policy.
3. Enforce stage topology.
4. Enforce stage budgets and the hard cap.
5. Enforce direct review or final acceptance for artifact-producing work.
6. Enforce distinct review participant keys.
7. Enforce server-side review loop caps.
8. Repair structural issues that can be safely repaired.
9. Block semantic issues that would produce misleading protocols.

Exit gate:

- A generated protocol cannot be ready without a primary artifact.
- A generated protocol cannot be ready with unreviewed material work.
- A generated protocol cannot remove core outcome/acceptance packages.
- Primary outcome is second-last in normal generated topology.
- A generated protocol cannot exceed the stage hard cap.

### Phase 4: Registry API And Persistence

Files:

- `octopus_registry/protocol_http.py`
- `octopus_registry/protocol_store.py`
- `octopus_registry/store_base.py`
- `octopus_registry/store_postgres.py`
- `octopus_sdk/registry/client.py`
- OpenAPI docs

Work:

1. Normalize API to the canonical request and response shape.
2. Store full sessions, planner payloads, compile output, warnings, blockers,
   and event summaries.
3. Add rich events endpoint.
4. Apply drafts through existing protocol draft save path.
5. Publish and run through existing protocol lifecycle.
6. Preserve published immutability for revisions.

Exit gate:

- Registry and SDK client use the same fields.
- OpenAPI matches runtime behavior.
- No provider calls exist in Registry.
- Apply/publish/run gates return actionable errors.

### Phase 5: Registry Authoring UI

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- shared UI helpers and styles used by protocol workspace

Work:

1. Build Auto Protocol create dialog.
2. Build Improve with Auto Protocol dialog.
3. Render work packages, stage map, reviews, assignments, blockers, warnings,
   and primary artifact.
4. Support modify/apply/publish/run actions.
5. Keep wide and narrow layouts clean in Safari.

Exit gate:

- A non-technical user can generate, inspect, apply, publish, and run a valid
  protocol from Registry.
- Narrow Safari has no overlapping menus, pills, dialogs, or stage controls.

### Phase 6: Telegram Surface

Files:

- `app/runtime/telegram_ingress.py`
- `app/runtime/telegram_protocols.py`
- `app/presentation/telegram.py`
- Telegram tests

Work:

1. Implement create and improve commands over the shared API.
2. Render summary, packages, stages, artifacts, warnings, blockers, and actions.
3. Implement apply/publish/run callbacks.
4. Persist session references per chat.
5. Promote primary artifact after run starts and after completion.

Exit gate:

- A user can generate, modify, publish, and run a valid protocol from Telegram.
- Telegram blocks invalid sessions with clear next actions.
- Telegram does not implement a separate generator.

### Phase 7: Runs UI And Artifact Surfacing

Files:

- Registry run UI modules
- artifact path/resolution modules
- `app/presentation/telegram.py`
- `app/runtime/telegram_ingress.py`

Work:

1. Add primary artifact panel to run details.
2. Distinguish declared placeholder artifacts from produced artifacts.
3. Show current run status, stage progress, active review loop, last decision,
   and blockers.
4. Group supporting artifacts under collapsible sections.
5. Link release evidence from the primary artifact panel.
6. Mirror the hierarchy in Telegram artifact messages.

Exit gate:

- A user opening a completed run can immediately identify and open the primary
  outcome.
- A user opening a running or failed run can understand what happened without
  bot logs.

### Phase 8: Documentation And Tests

Files:

- `README.md`
- user-facing docs
- architecture docs
- `tests/test_auto_protocol.py`
- registry service tests
- Telegram tests
- browser/UI tests

Work:

1. Document Auto Protocol from the user's perspective.
2. Document architecture boundaries from the developer perspective.
3. Add SDK unit tests.
4. Add Registry API tests.
5. Add Telegram tests.
6. Add Safari wide and narrow manual verification notes.
7. Add acceptance scenarios for the three probes below.

Exit gate:

- Focused tests pass.
- Full suite passes after implementation is complete.
- Docs explain how a new user generates, revises, publishes, runs, and inspects
  outputs.

## Acceptance Probes

These probes protect against hard-coding and shallow workflows.

### Probe 1: Profits Of Doom

Input: browser-runnable 2D platformer/fighting game with historical figures,
varied levels, special moves, animation, background detail, humor, historical
grounding, and playable Safari output.

Expected protocol characteristics:

- creative/game design
- historical/domain grounding
- UX/control design
- visual/media/art direction
- content/level/character variation
- implementation
- adversarial outcome acceptance
- primary playable artifact

### Probe 2: Manufacturing Analytics

Input: browser-runnable command center for non-technical plant leaders with
synthetic/local data, progressive data readiness, chart-first dashboards,
drilldowns, bottleneck/yield/scrap/WIP/downtime analysis, recommendations, and
Safari evidence.

Expected protocol characteristics:

- requirements and data readiness
- input/data model
- UX and progressive path design
- analytics views and dimensions
- implementation
- adversarial outcome acceptance
- primary analytics artifact

### Probe 3: Risk Decision Engine

Input: high-performance risk decision engine using Flink and Java, rich UI for
dynamic feature definitions, DSL rules, ML model catalog, payments, onboarding,
money movement, lending, investor onboarding, governance, audit, and
performance evidence.

Expected protocol characteristics:

- domain/risk grounding
- streaming architecture
- Java/Flink implementation strategy
- DSL/rules design
- feature lifecycle and model catalog design
- UI authoring workflow
- governance/audit/explainability
- performance and reliability evidence
- adversarial outcome acceptance
- primary technical delivery artifact

Passing these probes means Auto Protocol infers requirement-specific work
without product branches for the examples.

## Test Strategy

Run focused tests during implementation and the full suite only after the
feature is complete.

Required focused tests:

- SDK compiler tests for topology, reviews, primary artifact, and blockers.
- SDK stage-budget tests for small, standard, complex, and over-cap plans.
- SDK model response validation tests.
- Registry API tests for create, revise, apply, publish, run, and events.
- Registry worker-dispatch tests using fake design worker output.
- Telegram command and callback tests.
- Runs UI tests for primary artifact surfacing.
- Browser tests for Registry wide and narrow layout.

Required end-to-end tests:

- Generate, inspect, apply, publish, run, and inspect primary artifact for
  Profits of Doom.
- Generate, inspect, apply, publish, run, and inspect primary artifact for
  Manufacturing Analytics.
- Generate, inspect, apply, publish, run, and inspect primary artifact for a
  scoped Risk Decision Engine acceptance run.
- Repeat one create/publish/run flow from Telegram.

Manual verification must use real Safari for Registry and generated browser
artifacts.

## Non-Negotiable Quality Gates

The work is not done until all of these are true:

- There is one Auto Protocol pipeline.
- Registry does not execute provider calls.
- Telegram does not implement a separate generator.
- The SDK compiler owns canonical protocol output.
- Model planner output is structured and validated.
- Generated protocols have exactly one promoted primary artifact unless the
  requirement explicitly demands multiple primary deliverables.
- Primary artifact is obvious in Runs UI and Telegram.
- Generated protocols enforce critical review before acceptance.
- Generated protocols stay within the stage budget and never exceed the hard
  cap.
- Reviewers can and do revise low-quality work.
- Required outcome and acceptance packages cannot be removed.
- Revision preserves source protocol context.
- Session and run status are visible without reading logs.
- No example-specific product branches exist.
- No compatibility aliases or duplicate fields are added.
- Focused tests and final full-suite tests pass.
