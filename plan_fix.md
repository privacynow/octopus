**Protocol Product Fix Plan**

## Problem Statement

The current protocol product still fails the real bar for success:

- not "the code path exists"
- not "the tests pass"
- not "the workflow engine can execute it"

The bar is:

- can a normal author build the workflows they actually care about through the UI
- can they understand what each step does, who does it, what it reads/writes, and what happens next
- can they rehearse those workflows visually and trust the outcomes
- can they do this without being exposed to internal protocol-engine concepts that are not needed for standard authoring

That is not fully true today.

The most visible symptom is that internal escape hatches are still present in the default editor:

- `Custom runtime selector` still appears inside Assignment
- `Advanced` still appears as a named stage section

But the deeper issue is broader:

- the product still behaves too much like a protocol schema editor
- the tests still prove too much at the control/mechanics level and not enough at the workflow-usability level

So the real problem is not just visibility of two sections. The real problem is that the product rule
"normal authors do not see internal escape hatches" is not yet enforced as a system invariant, and the
test suite is not yet centered on the real workflows this product is meant to support.

**Feature-complete means scenario-complete.**

A feature is only complete when at least one UI scenario spec for each target workflow passes end-to-end:

- author
- rehearse
- execute

Isolated control tests, API tests, or engine tests are necessary, but they are not sufficient on their own.

## Context

### Current authoring model

The progressive inline stage stack is now the primary authoring surface. That part is directionally right:

- stage list is primary
- editor is inline under the selected stage
- workflow map is optional
- assignment can be authored by skill or agent
- insertion, deletion, rehearsal, and execution all work in the current runtime

### Current product mismatch

Despite those improvements, the standard authoring path still leaks internal concepts:

- custom runtime selector values
- direct internal stage tuning fields
- advanced headings and surfaces that imply operator-level control is part of ordinary authoring

That matters because the product is being built for workflows like:

1. Software Engineering
- planning
- review
- architecture
- review
- implementation
- review
- acceptance

2. Document Approval
- draft
- review
- revise loop
- approve

3. Data Analysis / Reporting
- load spreadsheet or CSV
- filter dataset
- run Python analytics
- render templated PDF report
- upload or publish the final report

Those workflows should be authorable and rehearseable through a clean workflow-builder UI. They should not
require users to understand runtime selector internals, stage key management, or per-stage internal tuning
unless they are explicitly in an operator/power-user path.

## Product Rule

This plan makes one product rule explicit and enforceable:

**Normal authors do not see internal protocol-engine escape hatches in the default authoring path.**

That means:

- no `Custom runtime selector` in the standard Assignment UI
- no `Advanced` stage section in the standard stage editor
- no visible `stage_key`, `max_rounds`, or `timeout_seconds` controls in standard authoring

If those controls still exist, they must exist only in a deliberately gated operator surface.

## Decisions

1. There are two authoring surfaces, conceptually:
- `standard`
- `operator`

2. The default UI is always `standard`.

3. The `standard` surface must not render internal controls in the DOM at all.
- not collapsed
- not hidden with CSS
- not behind `<details>`

4. The `operator` surface may expose internal controls, but only behind explicit gating.

5. The gating must be enforceable in both UI and API.
- UI-only hiding is not sufficient

6. Scenario-based workflow tests become the primary product acceptance bar.
- Software Engineering
- Document Approval
- Data Analysis / Reporting

7. Existing broad live audits remain valuable, but they are secondary to workflow-purpose tests.

8. Canonical operator entry is capability-based.
- PR CI and the default product path use only `standard`
- operator-only UI may exist for support/platform use, but it is not part of the standard path and should not be assumed in PR CI

## Discussion

### Why collapsed disclosures are not enough

Treating `Custom runtime selector` and `Advanced` as collapsed disclosures was the wrong design decision.
That still exposes the model to users and keeps the product semantically cluttered.

If the product rule is "normal authors should not need these controls," the correct implementation is:

- do not render them in the standard surface

Anything weaker turns the rule into opinion rather than invariant.

### Why this is not only a UI issue

If the UI hides `stage_key`, timeouts, or custom selectors but the normal session can still submit those
fields through the same API without restriction, the product rule is theater.

The rule must hold across:

- rendered UI
- request/patch acceptance
- tests
- live audit

### Why workflow examples must drive the tests

A passing control-level test suite is not enough.

The product is meant to support real authoring outcomes:

- a software engineering workflow with revise loops
- a document approval workflow with revise/approve decisions
- a data-analysis/reporting workflow with explicit data and report artifacts

If the tests do not prove those workflows are authorable, rehearseable, and executable through the UI,
the test suite is still too shallow.

## Target State

### Standard authoring path

Normal authors see:

- step purpose
- assignment by skill or specific agent
- optional refinement where appropriate
- instructions
- artifacts in/out
- routing / next-step behavior
- delete action in a normal destructive-action location
- rehearsal as a first-class safe proving ground

Normal authors do not see:

- custom runtime selector
- direct stage key editing
- per-stage internal retry/timeout knobs
- generic "Advanced" sections containing internal system controls

### Operator path

Operators may access:

- custom runtime selector
- stage key editing
- max rounds
- timeout seconds
- any other internal protocol tooling that is truly needed

But this must be explicitly gated, not part of the standard authoring flow.

## Recommended Gating Model

Use one coherent gating model. The recommended implementation is:

1. **Surface mode**
- `standard`
- `operator`

2. **Capability source**
- session capability such as `can_edit_protocol_internals`

3. **Optional route/query support for operator entry**
- only if needed for support/debugging
- but capability remains the authority

Recommended rule:

- UI derives `authoringSurface` from capability
- API enforces the same capability for internal fields

This keeps the product coherent and testable.

## Scenario Assertion Contract

Every primary workflow scenario must satisfy the same assertion categories. These are not optional notes;
they are the contract that turns "usable for the purpose" into something testable.

### Structure

- stage order is readable inline in the progressive editor
- section/step organization is understandable without relying on the workflow map
- standard authoring path does not expose operator-only controls

### Routing

- revise / approve / complete transitions are visible and correct in UI state
- route targets match the authored intent
- where the product uses URLs or selected state, those reflect the same routing truth

### Assignment

- every touched step is authored using only the standard assignment UI
- skill vs agent choice is understandable per step
- optional refinement is clear and does not force internal-selector understanding

### Artifacts

- when the workflow depends on data flow, the inputs/outputs chain is visible and understandable
- artifacts are verified as part of the workflow model, not just checked for existence

### Rehearsal

- rehearsal proves ordered stage/state progression, not just panel visibility
- revise / approve / accept / fail loops progress in the expected order
- the same progression is visible in both workflow and run surfaces where the product exposes it

### Execution

- the run reaches the expected terminal state
- where the product defines artifact or outcome state, that state is also verified

### Negative Invariants

These are gates inside every scenario, not a separate-only suite:

- no `Custom runtime selector` on the standard path
- no `Advanced` stage section on the standard path
- no `stage_key`, `max_rounds`, or `timeout_seconds` on the standard path

## Implementation Plan

### Phase 1. Define surface capabilities explicitly

Files likely involved:
- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- any session/capability plumbing already used by the registry UI

Work:
- introduce one explicit surface decision in the workspace: `standard` vs `operator`
- do not infer this from local editor state
- keep one editor pipeline; conditionally omit subtrees based on surface

Guidance:
- extend existing workspace/session state rather than adding a second editor implementation
- standard path must be the default everywhere

### Phase 2. Remove internal selector escape hatches from standard Assignment

Files:
- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)

Work:
- stop rendering the `Custom runtime selector` disclosure in standard mode
- keep it only in operator mode

Guidance:
- do not hide it with CSS
- do not render it and then collapse it
- remove it from the DOM entirely in standard mode

### Phase 3. Remove `Advanced` stage section from standard authoring

Files:
- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)

Work:
- stop rendering the `Advanced` section in standard mode
- relocate `Delete step` to a normal destructive-action location in the standard editor
- keep `stage_key`, `max_rounds`, and `timeout_seconds` operator-only

Guidance:
- use an existing action placement pattern if one already exists
- do not create another special-purpose section just to hold delete

### Phase 4. Align API behavior with the product rule

Files likely involved:
- protocol HTTP / save/update handling in the registry
- any document patch/update surface that accepts stage field mutation

Work:
- enforce that standard sessions cannot submit or mutate operator-only fields
- reject or ignore internal-field writes unless operator capability is present

Guidance:
- do not rely on UI hiding alone
- document the allowed field set per surface

### Phase 5. Rework test strategy around workflow-purpose scenarios

The test suite must prove real user goals, not just field mechanics.

#### 5A. Software Engineering scenario

The UI test must validate that a normal author can:
- author or edit the workflow inline
- assign stages cleanly by skill or agent
- model revise loops
- rehearse `revise -> accept` review cycles visually
- publish and execute successfully

It must assert:
- **Structure:** the stage stack is readable inline and is the primary authoring surface
- **Routing:** review stages route back correctly on revise and forward correctly on accept
- **Assignment:** touched stages are configured through the standard assignment editor only
- **Artifacts:** required planning / architecture / implementation outputs align with the workflow
- **Rehearsal:** revise and accept loops progress in the expected order
- **Execution:** the run reaches the expected terminal state
- **Negative invariants:** no custom selector or stage-advanced internals appear on the standard path

#### 5B. Document Approval scenario

The UI test must validate:
- draft -> review -> revise -> draft -> review -> approve
- clear assignment and step editing
- clean rehearsal of revise/approve outcomes
- successful final execution

It must assert:
- **Structure:** the draft / review / approve flow is readable inline
- **Routing:** revise returns to draft and approve completes the flow
- **Assignment:** touched stages use only the standard assignment UI
- **Artifacts:** the document flow remains understandable in the authored pipeline
- **Rehearsal:** revise then approve progression is visible and ordered
- **Execution:** the run reaches the expected terminal state
- **Negative invariants:** no custom selector or stage-advanced internals appear on the standard path

#### 5C. Data Analysis / Reporting scenario

This is the missing scenario and it should be added as a first-class test fixture.

Through the UI, the test should build and verify:
- load spreadsheet or CSV
- filter data
- run analysis
- render PDF report
- upload/publish report

It must assert:
- **Structure:** the pipeline reads as a sequence of real workflow steps, not protocol internals
- **Routing:** any review/publish branches are visible and correct
- **Assignment:** every touched step is authored through the standard assignment UI
- **Artifacts:** raw data -> filtered data -> analysis output -> report -> published output is visible and correct
- **Rehearsal:** meaningful workflow progression is visible where the scenario defines it
- **Execution:** the workflow reaches the final publish/upload step correctly
- **Negative invariants:** no custom selector or stage-advanced internals appear on the standard path

#### Readiness for 5C

5C should not be treated as "implicitly testable later." It needs explicit readiness conditions:

- a template or deterministic UI-build path exists for:
  - load data
  - filter data
  - analyze
  - render report
  - publish/upload
- the artifact kinds needed by that flow exist in the environment under test
- any integration assumptions needed for report publication are available in the test environment

If any of the above is missing, 5C is blocked as a product milestone, not merely deferred as test work.

### Phase 6. Add negative tests for the product rule

Tests should explicitly fail if the rule is violated.

These tests are necessary but not sufficient. They run on every PR, but they do not replace the
scenario-driven release bar in Phase 5.

Standard authoring assertions:
- `Custom runtime selector` has count `0`
- `Advanced` has count `0`
- `stage_key` input has count `0`
- `max_rounds` input has count `0`
- `timeout_seconds` input has count `0`

Operator-only tests:
- if operator path exists, confirm those controls appear only there

### Phase 7. Update exhaustive live audit

The live audit should remain broad, but it must now explicitly include:

- standard-path assertions that forbidden controls never appear
- scenario-driven authoring, rehearsal, and execution for:
  - Software Engineering
  - Document Approval
  - Data Analysis / Reporting

This is in addition to the existing broad UI matrix.

The hierarchy is:

- Phase 5 scenarios = release depth bar
- Phase 6 negative invariants = PR gate
- Phase 7 live audit = breadth validation

The live audit must include the same forbidden-control checks, but it should not outrank the scenario specs.

### Phase 8. Clean up stale tests and assumptions

Delete or rewrite tests that assert `Advanced`, `Custom runtime selector`, or internal fields on the standard path.

Keep:
- low-level contract tests that guard core editor/runtime behavior
- low-level tests that are necessary preconditions for the scenario specs

Add:
- one primary owning spec for each major scenario
- negative product-rule tests on the standard path
- audit coverage only as supplementary breadth

## Parallel Workstreams

### Track A: Surface and API enforcement

- implement `standard` vs `operator`
- remove internal controls from the standard DOM
- align API permissions with the same rule

### Track B: Scenario specs and release gating

- add scenario skeletons early, even if initially red or skipped
- wire negative invariants as soon as the standard surface exists
- turn scenarios green only after Track A lands

Recommended execution order:

1. write or tighten scenario specs and negative expectations
2. implement surface/API gating
3. make scenarios green
4. run the broad live audit

## Implementation Guidance

1. Use the existing editor pipeline.
- do not build a second stage editor
- do not fork a second assignment editor

2. Omit subtrees instead of hiding them.
- standard mode should not render operator-only controls

3. Keep one selector model underneath.
- simplify the UI surface, not the runtime truth model

4. Keep delete accessible in standard mode.
- simplification must not remove essential workflow authoring actions

5. Treat rehearsal as a workflow-proofing tool, not a side mode.
- tests should demonstrate this value directly

6. Prefer scenario fixtures and templates over abstract test scaffolding.
- the product is about workflows, not generic protocol objects

7. Treat 5C honestly.
- if the product fixture or artifact model is not ready, record it as blocked
- do not claim Data Analysis / Reporting support based only on generic authoring mechanics

## Acceptance Criteria

This work is done only when all of the following are true:

1. In the standard authoring surface:
- `Custom runtime selector` is not rendered
- `Advanced` is not rendered
- `stage_key`, `max_rounds`, and `timeout_seconds` are not rendered

2. The standard UI still supports:
- add step
- delete step
- assign by skill
- assign by agent
- inline role creation
- artifact flow authoring
- routing / revise loops

3. The API enforces the same separation.

4. The Software Engineering UI scenario passes end-to-end:
- author
- rehearse revise/accept loops
- execute
- standard-path negative invariants hold during the same run

5. The Document Approval UI scenario passes end-to-end:
- author
- rehearse revise/approve loops
- execute
- standard-path negative invariants hold during the same run

6. The Data Analysis / Reporting UI scenario passes end-to-end, or is explicitly marked blocked by unmet 5C readiness conditions:
- author
- rehearse where applicable
- execute
- standard-path negative invariants hold during the same run

7. The live Octopus audit includes:
- standard-path negative checks
- rehearsal proof
- real execution proof
- 500+ screenshots minimum

## Risks

1. API enforcement may affect existing drafts that were previously edited through the old UI surface.
- legacy behavior needs either migration or explicit operator-only handling

2. Data Analysis / Reporting may be blocked by missing product fixture or artifact-model support.
- that is a product readiness issue, not merely a testing gap

## Verification Matrix

### PR Gate

- `pytest` UI and runtime contract suites
  - proves the single pipeline and core invariants still hold
- negative standard-path UI tests
  - prove forbidden controls do not appear for normal authors
- scenario specs
  - prove workflow-purpose authoring/rehearsal/execution for target workflows

### Release Bar

- all primary scenario specs green
- live Octopus audit green

### Breadth Audit

- 500+ screenshots minimum
- matrix coverage across desktop/tablet/mobile
- supplementary to scenario depth, not a replacement for it

## Immediate Next Steps

1. Add or tighten scenario specs first, including negative invariants.
2. Implement `standard` vs `operator` surface gating in the workspace.
3. Remove `Custom runtime selector` from standard Assignment.
4. Remove `Advanced` from standard stage editing and relocate delete.
5. Align API restrictions for internal-only fields.
6. Add or unblock the Data Analysis / Reporting scenario fixture and readiness conditions.
7. Redeploy to `/Users/tinker/octopus`.
8. Rerun exhaustive live audit and update this file with verified state.
