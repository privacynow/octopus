**Protocol Product Plan: Executed State And Regression Bar**

## Problem Statement

The protocol product was failing in the exact places that matter for real
workflow authoring:

1. The UI exposed too much of the engine model.
- normal authors were forced to reason about selectors, internals, and layout
  seams instead of steps, artifacts, assignments, and outcomes

2. The workflow map was present but not productively usable.
- always-visible map layouts competed with editing
- later, a demoted map degraded into a cramped, effectively unreadable sidecar

3. Artifact authoring was too implicit.
- step checkboxes appeared before the product taught where artifacts came from
- real outputs like files, reports, and datasets were not concrete enough in
  the authoring flow

4. The authoring model was not strong enough for 0-to-1 creation.
- templates were easier to edit than new workflows were to create
- the product risked being a protocol schema editor instead of a workflow
  builder

5. The scenario bar was under-specified.
- mechanics could pass while real user workflows still felt unclear or fragile

This document now records the executed product direction, the implementation
decisions that are in force, the tests that prove them, and the regression bar
that future changes must satisfy.

## Context

The product is meant to let a normal human author create, rehearse, execute,
and evolve real multi-step workflows through the UI and registry APIs.

The primary target workflows remain:

1. Software Engineering
2. Document Approval
3. Data Analysis / Reporting
4. Meta Protocol Assistant

The product standard is not "the backend can technically run it." The standard
is:

- the workflow can be authored through the UI
- the workflow can be rehearsed visually
- the workflow can be executed against live connected agents
- the result is inspectable in the runs UI

All of that must happen through the product surfaces and APIs, not database
mutation.

## Discussion

### 1. Product shape over implementation leakage

The right product model is a workflow builder with runtime-backed proof, not a
thin schema editor. The UI therefore needs to bias toward:

- step purpose
- inputs and outputs
- assignment
- routing
- rehearsal

and away from:

- runtime internals
- stage plumbing
- operator-only controls

### 2. Optional does not mean degraded

The workflow map should not dominate the primary editor, but when the user asks
to see it, it must become a real interactive workspace. Hidden-by-default is a
prominence decision, not a value reduction.

### 3. One control per field

The product should not present two write surfaces for the same value. That rule
now governs assignment refinement:

- small agent match sets use a pill-only control
- larger match sets use a selector-only control

There is no longer a duplicate select-plus-pill surface for the same pinning
field.

### 4. Workflow scenarios are the release bar

The release bar is not isolated controls. The release bar is the set of named
workflow scenarios that must pass author -> rehearse -> execute end to end.

### 5. Standard vs operator paths are a real product boundary

Normal authors should not see internal escape hatches in the standard path.
Operator tooling remains possible, but it is not part of the default authoring
surface.

## Decisions

These decisions are now the product contract for this phase:

1. The stage stack with inline editing is the primary authoring surface.
2. The workflow map stays in the product but is hidden by default.
3. `Show workflow map` must open a legible, interactive, on-demand surface.
4. Artifacts are a first-class protocol concept and are authored at the
   protocol level, then attached to steps.
5. Assignment stays stage-owned on the standard path.
6. Assignment refinement uses one writable control per state:
- pills only for small match sets
- selector only for larger match sets
7. Standard-path internal escape hatches do not render:
- no custom runtime selector
- no generic advanced stage section
- no stage key editing
- no timeout/max-round controls
8. All authoring flows are manifested through UI + registry APIs, not DB edits.
9. One coherent implementation pipeline remains the rule. No duplicate authoring
   systems.

## Implemented Product Behavior

### 1. Primary authoring surface

The product now uses:

- progressive inline stage editing
- local add/remove/insert actions
- step-owned assignment
- stage-local routing
- artifact attachment in human-readable terms

The detached "pick somewhere, edit somewhere else" model is no longer the
standard path.

### 2. Workflow map

The workflow map now behaves as an optional reference surface instead of a
permanently dominant surface.

When explicitly opened, it is:

- interactive
- synchronized with stage selection
- large enough to be useful
- available on desktop and mobile in a focused presentation

### 3. Artifact authoring

Artifact authoring is framed as "workflow files and outputs" rather than raw
checkbox plumbing.

The product now supports clearer artifact definition and attachment around:

- what the workflow uses
- what the workflow creates
- where those outputs live
- what later steps read and produce

The data-analysis scenario exercises this concretely through:

- source data
- filtered data
- analysis summary
- rendered report
- published output

### 4. Assignment

Standard-path assignment now supports:

- skill-based assignment
- specific-agent assignment
- optional pinning/refinement without duplicate controls

The product behavior is:

- if the skill match set is small, present one pill-only pin control
- if the skill match set is larger, present one selector-only pin control
- do not show both in the same state

### 5. Meta composition

The product now supports a real UI/API composition scenario where a user can:

- create or refine a skill through the skill-management UI
- approve and publish it
- use it in a new protocol draft
- rehearse that protocol
- publish the resulting assistant/workflow

This is proven through the meta assistant scenario spec rather than by DB setup.

## Scenario Assertion Contract

Each scenario remains complete only when it passes these categories end to end.

### A. Software Engineering

Required assertions:

- Structure:
  inline stage order is readable and editable without relying on the map
- Routing:
  revise loops and acceptance routing are visible and correct
- Assignment:
  standard assignment UI is sufficient for touched stages
- Rehearsal:
  revise -> revise -> accept progression is visible and ordered
- Execution:
  the workflow completes against live connected agents

### B. Document Approval

Required assertions:

- Structure:
  draft/review/approve progression is legible inline
- Routing:
  revise loops back correctly, approve reaches terminal state
- Assignment:
  standard assignment UI is sufficient
- Rehearsal:
  revise then approve progression is visible
- Execution:
  the workflow completes correctly

### C. Data Analysis / Reporting

Required assertions:

- Structure:
  ingest -> filter -> analyze -> render -> publish is readable inline
- Artifacts:
  artifact catalog and step attachments clearly express the pipeline
- Assignment:
  standard assignment UI is sufficient for each stage
- Rehearsal:
  stage progression is visible through the data/report flow
- Execution:
  the run completes and reaches the publish stage outcome

### D. Meta Protocol Assistant

Required assertions:

- Skill composition:
  a skill is authored/refined, approved, and published through the UI/API
- Protocol composition:
  that capability is used in a new protocol draft
- Rehearsal:
  the composed workflow can be rehearsed
- Publishability:
  the resulting protocol can be published through the UI

### Negative invariants

The following must remain absent on the standard authoring path during scenario
runs:

- custom runtime selector
- generic advanced stage section
- stage key editing
- timeout/max-round internals

## Implementation Guidance

Future work in this area must preserve these rules:

1. Extend the existing authoring/editor pipeline in place.
2. Reuse existing canvas/editor helpers before introducing new ones.
3. Do not add duplicate control surfaces for the same field.
4. Do not reintroduce operator-only controls into the standard DOM.
5. Keep the map optional but fully interactive when opened.
6. Keep artifact authoring concrete, human-readable, and tied to real outputs.
7. Express changes through the registry APIs and existing product surfaces.

## Executed Fixes In This Pass

The following verified issues were fixed as part of the current executed state:

1. Skill studio lifecycle state now derives effective publishable state
   correctly after approval.
2. Skill publish no longer shows false failure on stale abort/fetch timing.
3. Publish API timeout was increased only where needed instead of adding a
   parallel path.
4. Blank-draft protocol settings access was aligned with the real direct-button
   UI.
5. Assignment editor rerenders now refresh after async skills/agents load.
6. Artifact labeling and attachment copy were made concrete and step-readable.
7. Rehearsal canned scenario responses persist across polling/session refreshes
   instead of visually resetting.
8. The meta assistant flow now proves skill + protocol composition through the
   UI/API.
9. The workflow map remains optional while preserving usable interactivity.

## Verification Matrix

These commands are the current verification bar and what they prove.

1. `./.venv/bin/python -m pytest tests/test_protocols.py tests/test_protocol_rehearsal.py tests/test_protocol_engine.py tests/test_db_postgres.py tests/test_registry_ui_contract.py tests/test_registry_service.py tests/test_registry_ui_kit_contract.py -q`
- proves SDK/runtime/store/contracts remain coherent
- current result: `224 passed`

2. `./.tmp/playwright/node_modules/.bin/playwright test tests/e2e/playwright/protocol-ui.spec.js --config=tests/e2e/playwright.config.js`
- proves the four named workflow scenarios pass end to end through the product
- current result: `9 passed`

3. `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-execution-smoke.spec.js --config=.tmp/playwright/playwright.live.config.js`
- proves live execution smoke for agent and skill assignment
- current result: `1 passed`

4. `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-exhaustive-audit.spec.js --config=.tmp/playwright/playwright.live.config.js`
- proves broad live authoring/rehearsal/execution/runs coverage
- current result: `9 passed`

5. `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-runs-filter-matrix.spec.js --config=.tmp/playwright/playwright.live.config.js`
- proves runs surface coverage across viewports
- current result: `1 passed`

6. `find .tmp/playwright/live-audit -type f | wc -l`
- proves breadth of the live audit capture set
- current result: `609`

## Current Verified State

The current verified live state on Octopus is:

1. No verified blocking defects remain in the scoped authoring, rehearsal,
   execution, or runs surfaces.
2. All four named scenarios are passing through the UI and APIs.
3. Standard-path negative invariants are holding.
4. The exhaustive live audit remains above the 500-screenshot bar.

## Definition Of Done

For this scoped plan, the work is complete when all of the following are true:

1. The standard authoring path supports the named workflows through the UI.
2. Rehearsal proves the intended stage progression visually.
3. Live execution succeeds against connected agents.
4. The workflow map is optional but genuinely usable when opened.
5. Artifacts are authored and attached as concrete workflow outputs.
6. The meta composition flow works through UI + APIs.
7. Standard-path negative invariants hold.
8. The verification matrix is green.
9. The exhaustive live audit remains at 500+ screenshots.

That bar is currently met.

## Next-Step Rule

No open item remains from this plan.

Any newly discovered regression or product gap should be added here as a new
explicit defect or feature requirement rather than reopening old completed
items implicitly.
