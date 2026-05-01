# Auto Protocol Plan

## Status

This is the execution plan for a new first-class Auto Protocol capability. The
initial implementation now follows this plan through the SDK, Registry API,
Registry UI, Telegram surface, persistence, and focused test coverage. Remaining
future work should continue to use this document as the product and architecture
context rather than adding a parallel Auto Protocol path.

The goal is to turn high-level user requirements into useful, ready-to-run
protocols, and to let users improve existing protocols with natural language
requests. The feature must work from both the Registry UI and Telegram without
creating separate protocol models, separate lifecycle rules, or surface-specific
authoring behavior.

## Problem Statement

Protocol authoring is currently powerful but too manual. A user must already
understand how to decompose work into stages, choose participants, assign agents
or skills, declare artifacts, write stage instructions, add review loops,
configure transitions, validate, publish, and then run. That is not acceptable
as the main path for non-technical users or for users who understand their
business goal but not agentic workflow design.

What we need in the protocol editor is an "auto mode": a simple box where a
user describes the outcome they want, adds optional constraints, and asks
Octopus to design the protocol. The system should produce an appropriate
canonical protocol draft with stages, participants, assignments, artifacts,
review gates, feedback loops, approvals, run inputs, and final evidence. The
draft should be normal protocol data, editable in the existing editor, and
runnable through the existing protocol runtime after validation and publish.

The same capability must also be available through Telegram. A user should be
able to generate, review, modify, publish, and run a protocol from Telegram when
the generated protocol is sufficiently clear and complete. Registry remains the
rich editor, but Telegram must be a real lightweight authoring surface, not just
a link generator.

The feature must also revise existing protocols. Users should be able to ask
Auto Protocol to improve a generated draft, a manually created draft, an
imported protocol, or a published protocol. Published protocols must not be
mutated in place; revisions are prepared as draft changes and only affect future
runs after explicit publish.

## Originating Example

The working litmus test is a game concept:

- a browser-based 2D platformer, fighting game, and team/strategy hybrid
- popular figures from history as characters
- historically grounded, with some humor
- browser-first, smooth, high-quality 2D gameplay
- sprites, detailed backgrounds, sound, story, level design, testing, and polish
- a workflow that should involve creative direction, historical review, game
  design, 2D art, sound, implementation, playtesting, UX review, and final
  evidence

This example is useful because a weak auto generator will collapse it into a
generic "build the game" stage. A useful generator will infer domain-specific
roles, staged deliverables, design reviews, creative and historical constraints,
technical architecture, asset planning, gameplay implementation, QA, playtest
loops, and release evidence.

This example must not be hard-coded. It is one acceptance scenario, similar to
the manufacturing analytics example. The product must work for many domains:
analytics, manufacturing, games, compliance workflows, operations, creative
work, security review, fintech workflows, research, product design, and other
high-value customer work.

## Product Decisions

1. Auto Protocol is a first-class SDK protocol-authoring capability.

   It is not a browser-only feature, Telegram-only command, template generator,
   skill text, or prompt file. The SDK owns the product workflow, typed request
   and response models, deterministic policy, compiler, validation handoff,
   critique, repair loop, and revision behavior.

2. The model assists; product code owns the behavior.

   The system may call a model to analyze requirements, infer the domain,
   propose workflow structure, critique drafts, and revise protocols. The model
   output is structured input to product code. Product code compiles, validates,
   gates, and persists the result. This must not rely on a single `SKILL.md`
   incantation or opaque prompt blob.

3. The output is always a canonical protocol document.

   There is no generated-protocol format, Telegram protocol format, browser
   protocol format, or import-only format. Auto Protocol produces and revises
   the same protocol documents already used by SDK validation, Registry
   persistence, export/import, publish, and run execution.

4. Registry owns persistence and API. Bot runtimes own provider execution.

   The Registry stores Auto Protocol sessions, protocol drafts, validation
   results, and publish/run state. Provider/model calls should be performed by
   bot runtimes or a provider-capable worker through SDK ports. The Registry
   must not become a provider execution runtime.

5. Registry and Telegram are peer surfaces over one shared capability.

   Registry provides the rich visual authoring and editing surface. Telegram
   provides a compact conversational surface with structured messages and inline
   buttons. Both call the same SDK/Registry-backed Auto Protocol lifecycle.

6. Generation and revision are the same product family.

   Auto Protocol must support:

   - create from a high-level requirement
   - explain an existing protocol
   - revise a draft protocol
   - prepare a revision from a published protocol
   - preview changes
   - apply changes
   - validate
   - publish
   - run

7. Review loops are inferred, not blindly templated.

   Planning, review, build, revise, accept, and final evidence are a useful
   minimum pattern for serious work, but not a fixed template. The generator
   must inspect the requirement and choose an appropriate workflow. A simple
   task may need a short workflow. A commercial game, analytics application,
   regulated workflow, or customer deliverable needs specialized stages,
   reviewers, evidence, and feedback loops.

8. Direct publish and run require explicit user action.

   Auto Protocol may prepare a valid draft and show a `Publish` or
   `Publish & Run` action when safe. It must not silently publish or run. Direct
   publish/run is allowed from Telegram and Registry only when validation
   passes, assignments are resolved, run inputs are satisfied, and the user
   confirms.

9. Existing published versions remain immutable.

   Revising a published protocol creates or updates a draft revision. Existing
   runs keep pointing at the published protocol version they used.

10. Agent and skill mapping must be explicit enough to run.

    Auto Protocol should infer roles and preferred capabilities, then map them
    to available agents or routing skills when possible. If a stage cannot be
    assigned safely, the session should show an unresolved decision and block
    publish/run until the user resolves it.

11. The feature must be usable by non-technical users.

    Users should not need to understand JSON, Docker, internal stage keys, raw
    model prompts, or the database. They should see the intended outcome, staged
    plan, assigned roles, expected artifacts, warnings, and clear buttons.

## Current Architecture Context

The current architecture already provides the boundaries this feature must
respect:

- `octopus_sdk/` owns shared contracts, protocol models, protocol engine,
  workflow use cases, registry clients, transport abstractions, and testing
  fakes.
- `octopus_registry/` owns the FastAPI app, protocol store/runtime, Registry
  UI, WebSocket updates, artifact resolution, and persistence.
- `app/` owns bot process composition, Telegram channel, provider adapters,
  runtime sessions, work queues, and deployment CLI.

The import direction is fixed:

```text
app/              -> octopus_sdk/
octopus_registry/ -> octopus_sdk/
octopus_sdk/      -> neither app/ nor octopus_registry/
```

Existing protocol SDK code gives us important building blocks:

- `octopus_sdk/protocols/documents.py`
  - canonical protocol parsing, normalization, and validation helpers
- `octopus_sdk/protocols/models.py`
  - protocol document, draft, mutation, run, artifact, issue, and launch models
- `octopus_sdk/protocols/ports.py`
  - authoring, catalog, invocation, observation, artifact access, and run
    control ports
- `octopus_sdk/protocols/service.py`
  - shared protocol operations for launch/list/status/artifacts/actions/export
- `octopus_registry/protocol_http.py`
  - protocol authoring, import/export, validation, publish, and run HTTP routes
- `octopus_registry/protocol_store.py`
  - canonical protocol persistence and mutation application
- `app/runtime/telegram_protocols.py`
  - Telegram-facing protocol commands over the shared protocol service
- `octopus_registry/ui/js/components/protocol-workspace.js`
  - current browser protocol authoring surface

What is missing is the Auto Protocol authoring/revision interface itself.

## Target Capability

Auto Protocol should support these user flows.

### Registry Create Flow

1. User opens `Build -> Protocols`.
2. User clicks `Auto protocol`.
3. User enters a high-level requirement and optional constraints.
4. User optionally chooses the design agent/model source if more than one is
   available.
5. System creates an Auto Protocol session.
6. System analyzes the requirement and produces a structured protocol design.
7. UI shows:
   - inferred goal
   - assumptions
   - stage map
   - participant roles
   - proposed assignments
   - artifacts
   - review loops
   - run inputs
   - warnings and unresolved decisions
8. User can modify the request, ask for changes, or apply the generated draft.
9. Applying creates a normal editable protocol draft.
10. User validates, publishes, and runs through the existing protocol workflow.

### Registry Revise Flow

1. User opens an existing protocol draft or published protocol.
2. User clicks `Improve with Auto Protocol`.
3. User describes the change.
4. System previews a revision with a change summary and diff.
5. User applies or asks for another revision.
6. Draft protocols update the draft after confirmation.
7. Published protocols create or update a draft revision, never the immutable
   published version.
8. Existing validation, publish, and run paths continue to own lifecycle.

### Telegram Create Flow

1. User sends a command such as:

   ```text
   /protocol auto <high-level requirement>
   ```

2. Telegram creates an Auto Protocol session through the Registry-backed
   service.
3. Telegram shows a compact generated protocol summary:
   - name
   - inferred domain
   - goal
   - stage count
   - reviewers and loops
   - artifacts
   - assignment readiness
   - validation status
4. Telegram presents inline buttons:
   - `Stages`
   - `Agents`
   - `Artifacts`
   - `Warnings`
   - `Modify`
   - `Apply Draft`
   - `Publish`
   - `Run`
   - `Open in Registry`
5. User can page through stage cards.
6. User can ask for changes in natural language.
7. If the draft is valid and all required mappings are resolved, user can
   publish and run from Telegram.

### Telegram Revise Flow

1. User references a protocol:

   ```text
   /protocol improve <protocol-ref> <change request>
   ```

2. Telegram creates or resumes an Auto Protocol session for that protocol.
3. System previews the change summary, affected stages, assignment changes,
   artifact changes, and warnings.
4. User can page through changes, ask for more edits, apply, publish, run, or
   open in Registry.
5. Published protocols are revised through a draft revision.

## SDK Design

Add a new SDK protocol authoring module. Suggested file:

```text
octopus_sdk/protocols/auto_design.py
```

The exact file name can change during implementation, but the capability should
live under `octopus_sdk/protocols/` because it is protocol authoring logic.

### SDK Models

Define typed models for request, session, analysis, plan, draft, revision,
warnings, actions, and render summaries. Use the existing SDK model style.

Suggested models:

```text
ProtocolAutoDesignRequest
ProtocolAutoDesignSession
ProtocolAutoDesignActor
ProtocolAutoDesignContext
ProtocolAutoDesignAnalysis
ProtocolAutoDesignAssumption
ProtocolAutoDesignQuestion
ProtocolAutoDesignPlan
ProtocolAutoDesignStagePlan
ProtocolAutoDesignRolePlan
ProtocolAutoDesignArtifactPlan
ProtocolAutoDesignAssignmentPlan
ProtocolAutoDesignReviewLoopPlan
ProtocolAutoDesignRunProfile
ProtocolAutoDesignDraft
ProtocolAutoDesignWarning
ProtocolAutoDesignValidationSummary
ProtocolAutoDesignRevisionRequest
ProtocolAutoDesignRevisionPreview
ProtocolAutoDesignChangeSummary
ProtocolAutoDesignApplyResult
ProtocolAutoDesignRenderCard
ProtocolAutoDesignAction
```

Important fields:

- `mode`: `create`, `revise`, or `explain`
- `surface`: `registry`, `telegram`, `api`, or future channel
- `requirement_text`
- `constraints_text`
- `target_protocol_id`
- `target_version_id`
- `target_draft_revision`
- `source_document`
- `available_agents`
- `available_skills`
- `workspace_ref`
- `preferred_design_agent_id`
- `analysis`
- `plan`
- `draft_document`
- `run_profile`
- `validation`
- `warnings`
- `unresolved_decisions`
- `change_summary`
- `idempotency_key`

### SDK Ports

Extend `octopus_sdk/protocols/ports.py` with ports that keep the SDK
process-neutral.

Suggested ports:

```text
ProtocolAutoDesignSessionPort
ProtocolAutoDesignModelPort
ProtocolAutoDesignWorkerPort
```

Responsibilities:

- `ProtocolAutoDesignSessionPort`
  - create session
  - get session
  - update session state
  - append session event
  - list recent sessions for actor/chat/protocol
- `ProtocolAutoDesignModelPort`
  - run structured requirement analysis
  - run structured protocol planning
  - run structured critique
  - run structured revision analysis
- `ProtocolAutoDesignWorkerPort`
  - dispatch model-backed design work to a provider-capable bot runtime
  - return structured results to the Registry session

The Registry adapter implements session persistence. Bot runtimes implement the
model port because they own provider execution. Registry can implement a worker
port that dispatches to a bot runtime instead of directly calling a provider.

### SDK Service

Add an SDK service that orchestrates Auto Protocol behavior:

```text
AutoProtocolService
```

Suggested methods:

```text
create_session(...)
generate_draft(...)
revise_protocol(...)
explain_protocol(...)
preview_revision(...)
apply_revision(...)
apply_generated_draft(...)
validate_session_draft(...)
publish_session_draft(...)
launch_session_protocol(...)
render_session_cards(...)
```

The service should use existing protocol authoring and run services where
possible:

- `ProtocolAuthoringPort` for create/save/validate/publish/diff
- `ProtocolInvocationPort` and `ProtocolService` for launch
- existing document parsing and validation helpers for canonical documents

The service must not duplicate publish, run, export, or import behavior.

### Deterministic Compiler

The model should not directly write the final protocol document without product
checks. Add a deterministic compiler that converts the structured design plan
into the canonical protocol document.

Compiler responsibilities:

- generate stable slugs and stage keys
- preserve existing stable keys during revision when possible
- create metadata and run inputs
- create participants/roles
- create stages
- create assignments
- create transitions
- create review loops
- declare artifacts
- attach stage input/output artifacts
- set protocol policies
- normalize instructions
- produce readable validation and warning context

The compiler should call or align with existing canonical document helpers
instead of creating a second document normalizer.

### Coded Design Policy

Add coded policy that guides model output and validates the compiled design.
This is the core product quality layer.

Policy rules should include:

- Serious workflows need separate planning, production, review, revision, and
  final evidence stages.
- Review stages must have concrete acceptance criteria and explicit decision
  vocabulary.
- Work stages should produce or update declared artifacts.
- Review stages should inspect declared artifacts, not vague completion claims.
- High-risk domains should include domain, safety, compliance, or security
  review where appropriate.
- Creative workflows should separate creative direction, asset production,
  implementation, and polish/review when those are materially different jobs.
- Software workflows should include architecture/design, implementation,
  testing, review, and final evidence where complexity justifies it.
- Analytics workflows should include data understanding, data model, analysis,
  visualization/UX, validation, and evidence stages where appropriate.
- If only one execution-healthy agent exists, the workflow may assign multiple
  roles to that agent, but review stages must remain distinct.
- If no assignment can be resolved, keep the draft editable but block publish
  until the user resolves the mapping.
- Final evidence should state what was built, what was reviewed, what artifacts
  exist, what remains risky, and how to inspect the output.

This policy should be code and tests, not just prompt text.

### Model Call Shape

Use structured model calls with explicit schemas. Avoid free-form Markdown as
the contract between model and product code.

Recommended call sequence:

1. Requirement normalization
   - product code trims, classifies mode, applies limits, attaches context
2. Requirement analysis
   - model returns domain, goals, deliverables, constraints, risks, roles,
     likely artifacts, open questions, and assumptions
3. Plan generation
   - model returns structured roles, stages, review loops, transitions,
     artifacts, assignment intents, and run profile
4. Deterministic compile
   - product code creates the canonical protocol document
5. SDK validation
   - existing protocol validation checks the compiled document
6. Critique
   - model and coded policy inspect the draft for gaps
7. Repair
   - product code and model perform bounded repair attempts
8. Surface rendering
   - product code creates Registry and Telegram-friendly summaries/cards

Repair attempts should be bounded. If the system cannot produce a publishable
draft, it should return a draft plus clear unresolved decisions rather than loop
indefinitely.

## Registry Implementation

### Persistence

Add Registry persistence for Auto Protocol sessions. Suggested tables under
the `agent_registry` schema:

```text
protocol_auto_sessions
protocol_auto_session_events
```

Suggested `protocol_auto_sessions` fields:

- `session_id`
- `status`
- `mode`
- `surface`
- `actor_kind`
- `actor_id`
- `chat_ref`
- `source_protocol_id`
- `source_version_id`
- `source_draft_revision`
- `target_protocol_id`
- `target_draft_revision`
- `preferred_design_agent_id`
- `requirement_text`
- `constraints_json`
- `analysis_json`
- `plan_json`
- `draft_definition_json`
- `run_profile_json`
- `validation_json`
- `warnings_json`
- `unresolved_decisions_json`
- `change_summary_json`
- `last_error`
- `created_at`
- `updated_at`

Suggested `protocol_auto_session_events` fields:

- `event_id`
- `session_id`
- `sequence`
- `event_kind`
- `actor_kind`
- `actor_id`
- `payload_json`
- `created_at`

The event log is useful for audit, Telegram message rendering, retries, and
human-readable modification history.

### Store Methods

Extend the Registry store interface and Postgres implementation with methods
for Auto Protocol session persistence. Keep the store as persistence, not
product logic.

Suggested methods:

```text
create_protocol_auto_session(...)
get_protocol_auto_session(...)
update_protocol_auto_session(...)
append_protocol_auto_session_event(...)
list_protocol_auto_sessions(...)
```

### HTTP API

Add Registry API routes that expose Auto Protocol sessions and actions. Exact
paths can be refined during implementation, but they should be grouped and
clear.

Suggested routes:

```text
POST /v1/protocol-auto/sessions
GET  /v1/protocol-auto/sessions/{session_id}
POST /v1/protocol-auto/sessions/{session_id}/generate
POST /v1/protocol-auto/sessions/{session_id}/revise
POST /v1/protocol-auto/sessions/{session_id}/apply
POST /v1/protocol-auto/sessions/{session_id}/validate
POST /v1/protocol-auto/sessions/{session_id}/publish
POST /v1/protocol-auto/sessions/{session_id}/run
POST /v1/protocol-auto/sessions/{session_id}/actions
```

Route behavior:

- create session records the user request and target protocol context
- generate starts model-backed design work
- revise applies a natural language change request to the session or target
  protocol
- apply creates or updates a normal protocol draft
- validate delegates to existing protocol validation
- publish delegates to existing protocol publish
- run delegates to existing protocol invocation
- actions handle Telegram/UI button actions with idempotency keys

All mutation routes need existing auth/CSRF/bearer behavior, permissions,
idempotency, and OpenAPI updates.

### Worker Dispatch

Registry must not own provider execution. For model-backed generation, add an
adapter that dispatches design work to a provider-capable bot runtime.

Suggested shape:

1. Registry creates or updates an Auto Protocol session.
2. Registry selects a design-capable agent:
   - explicit user choice
   - current Telegram bot when invoked from Telegram
   - healthy default agent if configured
   - otherwise return a setup/warning state
3. Registry sends a management request or routed task to that agent with the
   structured design request.
4. Bot runtime executes the SDK Auto Protocol design worker using its provider.
5. Bot returns structured analysis/plan/draft/critique results.
6. Registry stores the session update and broadcasts invalidation.

This keeps provider execution in bot runtimes while keeping the product session
and lifecycle in Registry.

### Realtime Updates

Add WebSocket invalidation for Auto Protocol sessions. Options:

```text
protocol-auto-session:{session_id}
protocols
```

The Registry UI should show progress while generation or revision is running:

- queued
- analyzing
- planning
- compiling
- validating
- critiquing
- ready
- blocked
- failed

Telegram should receive status updates through the same session events, rendered
as message edits or follow-up messages.

## Bot Runtime Implementation

Add a bot-runtime capability for Auto Protocol design work.

Suggested files to inspect or extend:

```text
app/agents/registry_control_processor.py
app/runtime/telegram_protocols.py
app/runtime/telegram_shared_dispatch.py
app/runtime/bot_services.py
app/providers/
octopus_sdk/execution.py
octopus_sdk/protocols/auto_design.py
```

The bot runtime should:

- advertise or accept an Auto Protocol design work kind
- receive structured design requests from Registry
- call the current provider through existing provider/runtime abstractions
- return structured SDK model responses
- avoid writing Registry DB directly
- avoid inventing bot-local protocol documents
- use idempotency and cancellation where available

Telegram invocation should still go through Registry session APIs so the
session, draft, publish, and run lifecycle stays centralized.

## Registry UI Implementation

Add Auto Protocol to the protocol workspace without replacing the existing
editor.

Suggested user experience:

- Add an `Auto protocol` action near `New protocol`.
- Add an `Improve with Auto Protocol` action when a protocol is selected.
- Use one progressive panel, not a detached wizard that hides the protocol.
- Keep the first input simple:
  - high-level requirement
  - optional constraints/details
  - optional design agent/model selector only when needed
- After generation, show:
  - summary
  - assumptions
  - stage map
  - participants/roles
  - assignments
  - artifacts
  - review loops
  - run inputs
  - validation status
  - unresolved decisions
  - buttons for modify, apply, publish, run, open draft
- Let the user ask for changes in plain language.
- Show a diff/change summary before applying revisions.
- Applying a generated result should use the existing draft editor state.
- Publishing and running should use existing controls and validation.

Narrow/mobile design requirements:

- no hidden critical actions
- no overlapping action bars or menus
- cards or rows must have stable dimensions and readable labels
- stage review should be paginated or collapsed when space is limited
- action buttons should wrap cleanly
- warnings should stay visible before publish/run

The UI must not perform protocol compilation in browser JavaScript. It should
render SDK/Registry results and edit canonical drafts through existing draft
save paths.

## Telegram Implementation

Telegram needs a compact but complete authoring surface.

### Commands

Suggested command additions:

```text
/protocol auto <requirement>
/protocol improve <protocol-ref> <change request>
/protocol auto status [latest|session]
/protocol auto open [latest|session]
/protocol auto cancel [latest|session]
```

The exact commands can be refined, but the user-facing model should be simple:

- start a new auto protocol
- improve an existing protocol
- inspect the generated protocol
- modify it
- apply/publish/run

### Render Model

Telegram should not dump raw JSON or huge Markdown. Use progressive messages
and inline buttons.

Suggested message cards:

- summary card
- assumptions card
- warnings card
- stage page card
- agents/assignments card
- artifacts card
- run inputs card
- change summary card
- validation card

Suggested buttons:

```text
Summary
Stages
Next
Back
Agents
Artifacts
Warnings
Modify
Apply Draft
Publish
Run
Publish & Run
Open in Registry
Cancel
```

Button handlers should call Registry Auto Protocol session actions. Telegram
should not mutate local protocol state.

### Publish And Run Gates

Telegram may show `Publish` or `Publish & Run` only when:

- the session has an applied draft or can safely apply one
- SDK validation passes
- required stage assignments are resolved
- required run inputs have values or defaults
- the user has permission
- the protocol is not in a draft conflict
- the action is confirmed with an idempotency key

If gates fail, Telegram should show the specific missing decision and offer the
next useful action.

## Existing Protocol Revision Semantics

Auto Protocol must treat source lifecycle correctly.

### Draft Protocol

- Preview changes against the current draft.
- Use current draft revision for conflict detection.
- Apply only after confirmation.
- Preserve stable identifiers where possible.
- Validate after apply.

### Generated Unpublished Protocol

- Treat as a normal draft/session result.
- Allow repeated modification before apply.
- Do not create duplicate protocols unless the user chooses that.

### Published Protocol

- Never mutate the immutable published version.
- Preview changes against the published snapshot.
- On apply, create or update a draft revision for that protocol.
- Existing runs remain tied to their original published version.
- Future runs use the revised version only after publish.

### Imported Or Copied Protocol

- Treat the imported/copy protocol as a normal draft or published protocol based
  on its lifecycle state.
- Do not create special import-only revision behavior.

## Assignment And Agent Mapping

Auto Protocol should infer the roles needed for the work, but publishable
protocols need executable assignments.

Recommended behavior:

1. Query current authoring options, available agents, routing skills, and health.
2. Infer role intents independently from runtime assignments.
3. Prefer specific stage assignments when a matching healthy agent is clear.
4. Use routing skill assignment when skill routing is the better durable choice.
5. If only one healthy agent is available, allow assigning all executable
   stages to that agent with a warning, while preserving distinct reviewer
   stages.
6. If no safe mapping exists, keep the protocol draft but block publish/run.
7. Surface unresolved mappings in Registry and Telegram with clear choices.

Do not apply skills to bots, install skills, or mutate agent configuration as a
side effect of generating a protocol. That can be a future explicit action.

## Run Profile

Auto Protocol should generate a run profile so users are not forced to invent a
large subjective instruction block at launch time.

The run profile should include:

- default problem statement
- optional custom run input fields
- expected workspace needs
- constraints
- acceptance criteria
- expected artifacts
- evidence expectations
- assumptions that should be confirmed before running

Registry and Telegram should show these fields as launch inputs. The user can
edit them, but the protocol should already carry a reasonable run contract.

## Quality Bar For Generated Protocols

A generated protocol should be judged by whether a real user can run it and get
a useful outcome, not by whether it contains many stages.

Quality checks:

- The goal is clear.
- The workflow decomposes the work into meaningful responsibilities.
- Each stage has concrete instructions.
- Reviewers know what to accept, revise, or fail.
- Revision loops route to the stage that can fix the problem.
- Artifacts are declared before they are produced.
- Final evidence tells the user what happened and how to inspect the result.
- Assignments are resolved or clearly blocked.
- Run inputs are understandable.
- The protocol is editable.
- Export/import still works.
- Telegram and Registry show the same underlying protocol state.

## Implementation Phases

### Phase 0: Baseline Audit

- Re-read protocol SDK models, document helpers, ports, and service.
- Re-read Registry protocol HTTP/store/runtime paths.
- Re-read Telegram protocol command code.
- Identify existing provider execution and management request paths that can
  carry structured Auto Protocol design work.
- Confirm current validation behavior for unassigned draft stages and publish
  blockers.
- Confirm how protocol draft revisions and publish versioning behave today.

Deliverable:

- short implementation notes in the eventual PR description
- no product behavior change

### Phase 1: SDK Contracts

- Add Auto Protocol SDK models.
- Add Auto Protocol ports.
- Add render-card models for Telegram/UI summaries.
- Add skeleton `AutoProtocolService`.
- Export the new SDK surface through `octopus_sdk/protocols/__init__.py` and
  `octopus_sdk/protocols/core.py` if appropriate.
- Add tests for model serialization and validation.

Deliverable:

- typed SDK interface compiles
- no Registry/UI/Telegram behavior yet

### Phase 2: SDK Compiler And Policy

- Implement deterministic plan-to-protocol compiler.
- Implement coded policy checks.
- Implement canonical validation handoff.
- Implement fake model port for tests.
- Implement bounded critique/repair loop against fake model output.
- Add tests for:
  - simple workflow generation
  - game-development style workflow generation
  - analytics workflow generation
  - high-risk workflow requiring reviewer gates
  - unresolved assignment warnings
  - no hard-coded example strings
  - stable key preservation during revision

Deliverable:

- SDK can turn structured plans into valid canonical protocol drafts in tests

### Phase 3: Registry Session Persistence And API

- Add DB migration/schema updates for Auto Protocol sessions/events.
- Extend store base and Postgres store.
- Add Registry API routes.
- Wire API routes to SDK service.
- Add idempotency, permissions, validation, and error handling.
- Add WebSocket invalidations.
- Regenerate `docs/registry-openapi.json`.
- Add Registry API/store tests.

Deliverable:

- API can create sessions, store generated previews, apply drafts, validate,
  publish, and run using fake worker/model ports

### Phase 4: Bot Runtime Design Worker

- Add SDK-backed design worker handling in bot runtime.
- Add provider-backed structured model adapter.
- Add management/routed-task handler for Auto Protocol design requests.
- Ensure cancellation and idempotency are handled where available.
- Add tests with fake provider responses.

Deliverable:

- Registry can dispatch Auto Protocol design work to a bot runtime instead of
  executing provider calls itself

### Phase 5: Registry UI

- Add Auto Protocol entry points in protocol workspace.
- Add session progress panel.
- Add generated protocol review panel.
- Add natural language modification input.
- Add change summary/diff preview.
- Add unresolved assignment resolution UI.
- Add apply, validate, publish, run, and open draft actions.
- Verify wide and narrow layouts.
- Add UI contract tests and Playwright coverage.

Deliverable:

- user can generate, revise, apply, publish, and run through Registry UI

### Phase 6: Telegram Surface

- Add Telegram Auto Protocol commands.
- Add session tracking per chat.
- Add render cards and inline button handlers.
- Add stage pagination.
- Add modify/apply/publish/run flows.
- Add gates for unresolved decisions and validation failures.
- Add tests for command parsing, card rendering, button action handling, and
  publish/run gating.

Deliverable:

- user can generate, review, modify, publish, and run from Telegram

### Phase 7: Cross-Surface Acceptance

Run the same class of tests from Registry and Telegram.

Acceptance scenarios:

1. Generate a simple protocol from Registry.
2. Generate a simple protocol from Telegram.
3. Generate the game-development litmus protocol from Registry.
4. Generate the game-development litmus protocol from Telegram.
5. Modify the generated game protocol once from each surface.
6. Apply generated drafts.
7. Validate and publish.
8. Run with the generated run profile.
9. Inspect run status, stage progression, artifacts, and final evidence.
10. Export/import the generated protocol as a normal protocol package.
11. Revise an existing manually created draft.
12. Revise an existing published protocol and confirm a draft revision is used.

Acceptance must use the product surfaces for final proof:

- Registry UI in a real browser
- Telegram in the real Telegram surface when available
- no direct database writes
- no API-only shortcut as the final proof

Lower-level unit, SDK, API, and fake-provider tests are still required because
they prove the invariants faster and make regressions easier to isolate.

### Phase 8: Documentation

Update user-facing and architecture docs:

- `README.md`
- `docs/USER_GUIDE.md`
- `docs/PROTOCOLS.md`
- `docs/TELEGRAM.md`
- `docs/ARCHITECTURE.md`
- `docs/SDK_BOT_DEVELOPMENT.md`
- `docs/examples/README.md`

Add at least one Auto Protocol example guide after the feature works. The game
scenario can be one example, but it should be written as a product example, not
as a hard-coded feature premise.

Documentation should explain:

- when to use Auto Protocol
- how to generate from Registry
- how to generate from Telegram
- how to revise an existing protocol
- why review loops matter
- why publish/run may be blocked
- how to resolve assignments
- how generated protocols remain normal editable/exportable protocols

### Phase 9: Cleanup And Release Readiness

- Remove any temporary fake routes or debug UI.
- Confirm no duplicate protocol lifecycle logic was introduced.
- Confirm no provider execution moved into Registry.
- Confirm no browser-only or Telegram-only protocol format exists.
- Confirm OpenAPI and docs match shipped behavior.
- Confirm all tests and product smoke tests pass.

## Test Plan

### SDK Tests

- Auto Protocol model serialization and validation
- design request normalization
- structured fake model responses
- deterministic compiler output
- coded policy checks
- critique/repair bounds
- canonical validation integration
- revision against draft protocol
- revision against published protocol snapshot
- run profile generation
- render card generation

### Registry Tests

- session creation
- session update/event append
- permission enforcement
- idempotency
- worker dispatch
- apply generated draft
- apply revision to draft
- apply revision to published protocol as draft revision
- validate/publish/run delegation
- WebSocket invalidation
- OpenAPI route coverage

### Bot Runtime Tests

- design worker receives structured request
- provider adapter returns structured model output
- malformed provider output becomes a useful session error
- cancellation/idempotency behavior
- no direct Registry DB writes

### Telegram Tests

- command parsing
- session creation from chat
- compact summary rendering
- stage pagination
- warnings rendering
- modify flow
- apply flow
- publish/run gate behavior
- callback idempotency
- open Registry link generation

### Registry UI Tests

- generate from blank
- improve current draft
- improve published protocol
- change preview/diff
- unresolved assignments
- apply/validate/publish/run
- wide layout
- narrow layout
- no overlapping action menus
- no unreadable button labels or clipped pills

### End-To-End Tests

- Registry create, modify, publish, run
- Telegram create, modify, publish, run
- generated protocol export/import
- existing protocol revision
- published protocol revision without mutating old runs

## Acceptance Criteria

The feature is acceptable when all of the following are true:

- Auto Protocol logic lives in SDK, not browser JS or Telegram command code.
- Registry and Telegram use the same Auto Protocol session lifecycle.
- Generated output is a canonical protocol document.
- Existing protocol validation/publish/run paths are reused.
- Existing export/import works without special cases.
- Bot runtimes perform provider execution through SDK ports.
- Registry does not become a provider runtime.
- Users can generate a protocol from Registry.
- Users can generate a protocol from Telegram.
- Users can revise an existing draft from Registry and Telegram.
- Users can revise an existing published protocol without mutating the published
  version.
- Users can publish and run directly from Telegram when gates pass.
- Users can open and continue editing in Registry when they need richer control.
- Generated protocols contain requirement-specific stages, artifacts, review
  loops, and final evidence.
- The game-development litmus example produces a domain-specific workflow, not
  a generic one-stage protocol.
- The product does not contain hard-coded logic for that example.
- Narrow and wide Registry layouts are readable and usable.
- Telegram messages are compact, progressive, and action-oriented.
- Final acceptance is proven through real product surfaces, not database
  shortcuts.

## Risks And Mitigations

### Risk: Generic Protocols

The model may produce a generic workflow for specialized requirements.

Mitigation:

- use coded design policy
- critique generated drafts
- test against multiple domains
- require artifact and review specificity

### Risk: Prompt-Only Product Behavior

The feature could degrade into a large prompt with little product structure.

Mitigation:

- structured models
- deterministic compiler
- coded policy checks
- validation and repair outside the model
- tests against fake model output

### Risk: Registry Provider Execution

Registry UI needs model-backed generation, but provider execution belongs in bot
runtimes.

Mitigation:

- use a SDK model/worker port
- dispatch model-backed work to a capable bot runtime
- keep Registry responsible for session and protocol persistence only

### Risk: Telegram Becomes A Separate Authoring System

Telegram could accidentally create its own lifecycle and document format.

Mitigation:

- Telegram actions call Registry Auto Protocol session APIs
- render cards are derived from SDK summaries
- apply/publish/run delegate to existing backend paths

### Risk: Unsafe Published Protocol Mutation

Natural language revision could rewrite a published protocol in place.

Mitigation:

- published protocols always create/update draft revisions
- old runs stay bound to immutable versions
- tests cover this explicitly

### Risk: Poor Assignment Mapping

Generated protocols may look good but fail publish due to unresolved agents or
skills.

Mitigation:

- query authoring options before generation
- render assignment readiness clearly
- provide explicit resolution UI/buttons
- block publish/run until executable stages are mapped

### Risk: Message Overload In Telegram

Large generated protocols can exceed Telegram message limits or overwhelm users.

Mitigation:

- use compact render cards
- paginate stages
- summarize first
- use buttons for details
- avoid raw JSON

## Non-Goals For Initial Release

- generating or installing new skills automatically
- replacing the manual protocol editor
- supporting bulk "generate all protocols"
- silently publishing or running generated protocols
- storing provider credentials in Registry
- creating a second protocol package format
- hard-coding the game example or any customer example
- direct database mutation as a user-visible workflow

## Open Design Questions

These should be resolved during implementation, not by adding parallel paths.

1. How should Registry select the default design-capable bot when multiple bots
   are healthy?

   Recommended initial behavior: use explicit user choice when available,
   default to the current Telegram bot for Telegram sessions, and otherwise
   choose a configured/default healthy bot with a visible warning.

2. Should generated drafts be applied immediately or kept as previews first?

   Recommended behavior: generate into an Auto Protocol session first. Apply to
   a normal protocol draft only after user confirmation. `Publish & Run` may
   perform apply, publish, and run in one confirmed action when all gates pass.

3. How many repair attempts should be allowed?

   Recommended initial behavior: one deterministic repair pass and one
   model-assisted repair pass. If validation still fails, return the draft with
   warnings and unresolved decisions.

4. Should Auto Protocol create custom run input fields by default?

   Recommended behavior: yes, when the requirement implies recurring launch
   variables. Keep the generated run profile simple and readable.

5. Should Auto Protocol ask clarifying questions before generating?

   Recommended behavior: only when a missing answer blocks safe protocol design.
   Otherwise generate a draft with explicit assumptions and let the user revise.

## Implementation Guardrails

- Do not add parallel protocol lifecycle logic.
- Do not add browser-only generated protocol state.
- Do not add Telegram-only generated protocol state.
- Do not move provider execution into Registry.
- Do not bypass SDK protocol validation.
- Do not bypass existing publish/run methods.
- Do not mutate published protocol versions in place.
- Do not hard-code customer examples.
- Do not require users to understand JSON to review generated protocols.
- Do not rely on a skill text file as the main product behavior.

## Definition Of Done

Auto Protocol is done when a non-technical user can describe a real goal in
Registry or Telegram, receive a readable generated protocol, understand the
stages and review loops, make natural language modifications, resolve any
required assignments, publish it, run it, and inspect the outputs through the
normal run/artifact surfaces. The same generated protocol must be a normal
canonical protocol that can be edited, exported, imported, versioned, and run
without special handling.
