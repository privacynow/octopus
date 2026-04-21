**Protocol Product Plan: Interactive Workflow Builder**

## Problem Statement

The product has moved past its earliest structural failures, but it is still not
fully shaped around the job it is supposed to do.

The goal is not to expose a protocol schema editor. The goal is to let a normal
human author create, test, and evolve real multi-step workflows through the UI.

The current gaps are now clearer:

1. The **workflow map** was demoted correctly in principle but degraded in
practice.
- `Show workflow map` currently reveals a narrow, fit-to-column graph that is
  hard to read and effectively loses its value.
- The map is still technically mounted, but when explicitly opened it does not
  behave like a useful interactive workspace.

2. The **artifact model** is still too implicit.
- Authors can see artifact checkboxes on steps, but the product does not teach
  clearly where artifacts come from or how they map to real files, code, repos,
  reports, or documents.
- This makes the workflow feel abstract at exactly the point where it needs to
  become concrete.

3. The **authoring surface** is better, but still not sufficiently
workflow-shaped for 0-to-1 creation.
- A real author needs to create new workflows from a business goal, not from a
  mental model of stage schemas and runtime internals.
- The product must support practical “build a new process” work, not just edit
  seeded templates.

4. The **test suite** is stronger than before, but it still needs to align even
more tightly with product-purpose behavior.
- We need tests that prove a human can manifest useful workflows through the UI
  and APIs.
- We must not confuse “the engine can run it” with “the product made it easy and
  legible to author.”

5. The next frontier is **composition**.
- The product should support creating new protocol-driven assistants by
  combining protocols and skills through the UI.
- That must be done through the same registry APIs the product owns, not via
  direct database manipulation or hidden server-side shortcuts.

This plan replaces the earlier “cleanup and closeout” framing with a product
plan for the next coherent version of protocol authoring.

## Product Vision

The product should feel like a **workflow builder with runtime-backed proof**.

A normal author should be able to:

1. define the workflow steps
2. define what each step consumes and produces
3. decide who can do each step
4. define review / branch / finish behavior
5. rehearse the workflow visually
6. execute it against real connected agents
7. refine it without leaving the UI

The UI should support:

- **standard authoring**
  for normal workflow builders
- **operator tooling**
  for rare internal/runtime controls

And it must do so without duplicating the implementation pipeline.

## Design Principles

### 1. Workflow first, schema second

Authors think in:

- steps
- artifacts
- people/bots
- outcomes

They do not think first in:

- selectors
- stage keys
- timeout knobs
- protocol internals

The product should lead with workflow concepts and hide schema mechanics unless
they are truly needed.

### 2. Progressive disclosure with real power on demand

Power features must remain available, but only when deliberately invoked.

This applies to:

- operator-only internals
- the workflow map
- advanced composition flows

Important rule:

- **hidden by default** must not mean **crippled when opened**

### 3. One surface per job

If two controls change the same thing, that is a product smell.

If two panels compete to be the primary editor, that is a product smell.

The solution is not more toggles. The solution is cleaner ownership:

- stage stack is the primary authoring surface
- artifact catalog is the primary artifact-definition surface
- workflow map is an optional interactive reference surface
- operator controls live only on the operator path

### 4. Concrete over abstract

A human building a real process needs to see:

- file paths
- repo locations
- document outputs
- report artifacts
- review loops

The UI should bias toward concrete terms and concrete outputs.

### 5. UI manifests truth through APIs

No DB patching. No “make the database right and let the UI catch up.”

Everything the user authors must be manifested through:

- protocol draft/version APIs
- skills/catalog/guidance APIs
- run/rehearsal APIs
- existing registry management surfaces

If a workflow cannot be created through the product UI and its APIs, it is not
done.

## Core User Journeys

These are the workflows the product must make natural.

### A. Software Engineering

The user should be able to:

- open or create a software engineering workflow
- define planning, review, architecture, implementation, and acceptance stages
- model revise loops
- rehearse revise/accept behavior
- execute the run and inspect the result

### B. Document Approval

The user should be able to:

- create draft/review/approve flow
- define revise loop behavior
- assign steps clearly
- rehearse revise then approve
- execute and inspect the completed run

### C. Data Analysis / Reporting

The user should be able to build a pipeline like:

- ingest CSV or Excel from the workspace
- filter the dataset
- run analytics in Python
- generate a PDF report
- upload or publish the final result

This is a critical product-spec scenario because it forces the UI to model real
artifacts and not just abstract steps.

### D. Meta Protocol Assistant

The user should be able to create a **protocol-driven assistant that creates new
protocols** by composing:

- existing skills
- newly authored skills
- existing protocol templates
- new protocol drafts

Example:

- gather a business goal
- identify missing capabilities
- author or refine skills
- assemble a new workflow from stages
- rehearse the draft process
- publish the new assistant

This must happen through the UI and APIs, not through database seeding.

## Target Product Model

## 1. Standard Authoring Surface

The standard surface should be the default and should present:

- stage stack
- inline stage editor
- add-below / insert-before-target actions
- artifact catalog
- rehearsal entry point
- publish/archive lifecycle
- optional workflow map entry point

The standard surface must not render:

- custom runtime selector
- generic `Advanced` stage section
- stage key editing
- timeout knobs
- per-stage internal retry knobs

## 2. Operator Surface

The operator surface may expose:

- custom runtime selector
- stage key editing
- timeout controls
- max rounds
- other runtime-internal tooling

But only with explicit capability-based gating.

## 3. Workflow Map Model

The workflow map stays in the product, but with different prominence:

- hidden by default
- opened on demand
- fully interactive when opened

When opened:

- desktop: map gets real space
- mobile: map opens in a full-screen or nearly full-screen panel
- interactions remain live:
  - click/tap nodes
  - inspect routes
  - zoom
  - fit
  - preserve selection
  - preserve viewport where sensible

The map is a secondary reference workspace, not a permanently cramped sidebar.

## 4. Artifact Model

Artifacts are the durable contract between steps.

The product must teach that clearly:

1. artifacts are defined at the protocol level
2. steps read and write those artifacts
3. runtime verifies or observes them

The current raw artifact shape is not enough for usability, so the product layer
must be more concrete.

### Product-facing artifact presets

The UI should present artifact presets such as:

- Dataset / spreadsheet
- Code file
- Document / notes
- Structured data
- PDF report
- Published record
- Repository location
- Control-plane note

These do not require immediate backend duplication.

The UX can map them to the existing canonical types where possible:

- `workspace_file`
- `control_plane_text`

If the current canonical model is too weak for a useful product expression, then
the SDK/API should be extended deliberately rather than compensated for with
browser-only invention.

### Artifact authoring must answer

For each artifact:

- what is it called
- what type of thing is it
- where does it live
- is it expected to already exist, or be created by the workflow
- should completion require verification

### Step attachment must answer

For each step:

- what does it read
- what does it write
- are those inputs/outputs understandable without reading raw keys

The checkbox model alone is not sufficient unless it is wrapped in a clearer
artifact-definition experience.

## 5. Assignment Model

Assignment remains stage-owned and standard-path friendly.

The normal authoring modes are:

- By skill
- Specific agent

Refinement remains optional:

- small match sets: pills only
- larger match sets: selector only

The product must not show duplicate controls for the same field.

The operator-only selector escape hatch remains operator-only.

## 6. Composition Model

The product should support composing a new protocol-driven assistant through the
UI.

That means one coherent authoring flow where a user can:

1. define a new capability goal
2. inspect available skills
3. create or refine missing skills through skill-management APIs
4. create a new protocol draft
5. add stages that use those skills
6. rehearse the draft workflow
7. publish the result

This is the beginning of a meta-authoring product:

- protocols can help create protocols
- skills can help power protocol stages
- the UI remains the manifestation layer

## Detailed Product Behavior

## A. Workflow Map

### Current problem

`Show workflow map` reveals a surface that is too small to be useful.

### Correct behavior

When a user explicitly asks for the map:

- it should open in a **focused map mode**
- it should stay interactive
- it should be legible

### Desktop behavior

Preferred order:

1. Open a large split mode with the map taking substantial width
2. If that still feels cramped, use a full-width map mode with an editor return
   action

Not acceptable:

- a narrow sticky side column that reduces the graph to a thumbnail

### Mobile behavior

Open the map in:

- full-screen sheet
- or dedicated full-screen panel

The map should not be a tiny embedded preview at the bottom of the flow.

### Interaction rules

The map must support:

- node/edge selection
- route inspection
- zoom/fit
- stage-focus navigation back into the inline editor

### Aesthetic rules

- high contrast
- generous width
- clear active selection
- no attempt to cram dense graph labels into a sidebar

## B. Artifact Authoring

### Current problem

The user sees artifact checkboxes on steps before understanding how artifacts are
declared or how they map to real work outputs.

### Correct behavior

Artifacts become a first-class catalog with a clearer “Things this workflow
uses and creates” frame.

### Standard UI structure

1. Artifact catalog panel
- add artifact
- choose preset/type
- set display name
- set location/path/reference
- set verification requirement

2. Step-level attachment
- reads
- writes
- presented in human-readable form

3. Runtime evidence
- when runs happen, artifacts show observation / verification state clearly

### Concrete examples

For Data Analysis:

- `source-data`
  - type: Dataset / spreadsheet
  - location: `data/source.xlsx`
- `filtered-data`
  - type: Dataset
  - location: `data/filtered.csv`
- `analysis-summary`
  - type: Structured data
  - location: `reports/summary.json`
- `report-pdf`
  - type: PDF report
  - location: `reports/final.pdf`
- `publication-record`
  - type: Published record
  - location: `reports/published.json`

For Software Engineering:

- `plan-doc`
  - type: Document
  - location: `docs/plan.md`
- `architecture-doc`
  - type: Document
  - location: `docs/architecture.md`
- `implementation-diff`
  - type: Code output
  - location: repo/workspace path(s)

### Design rules

- artifact names should be visible in step context
- locations must be concrete
- the product should visually distinguish:
  - existing input
  - generated output
  - published output

## C. 0-to-1 New Protocol Flow

### Current problem

The product is still easier to understand when editing a template than when
starting from a blank idea.

### Correct behavior

The blank-state authoring flow should help the user build a workflow from a
business goal.

### Proposed flow

1. Start a new protocol
2. Enter workflow name and short goal
3. Add the first step inline
4. Define what it does
5. Define what it reads/writes
6. Define who does it
7. Add next step below
8. Repeat until the flow is complete
9. Add branches/review loops only where needed
10. Rehearse
11. Publish

### Blank-state copy

Blank states should guide:

- Add first step
- Add artifact
- Use a template
- Show workflow map only after structure exists

### Good design rule

The blank flow should feel like assembling a pipeline, not configuring a
runtime state machine.

## D. Meta Protocol Assistant

### Goal

Let a user build a protocol-driven assistant that itself helps design new
protocols and skills.

### Example flow

The user wants to create an assistant that:

- asks for a business process goal
- suggests required steps
- identifies missing skills
- drafts those skills
- creates a new protocol draft
- assigns stages to those skills
- rehearses the result
- publishes the assistant

### Product implication

The UI must support composition across:

- skill catalog
- skill authoring/publishing
- protocol templates
- protocol drafts
- rehearsal

### API rule

This must happen through existing or deliberately extended registry APIs:

- create/update skill drafts
- publish/archive skills
- create/update protocol drafts
- clone templates
- publish protocols
- start rehearsals

No database mutation as a product-authoring shortcut.

### Testing implication

We need one scenario spec that proves a user can:

- create or refine at least one skill through the UI/API
- use it in a new protocol
- rehearse that new protocol
- publish it

## Implementation Plan

### Phase 1. Replace the optional-map layout model

Files likely involved:

- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js)
- [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css)

Work:

- remove the “tiny sticky side map” as the explicit-open default
- introduce focused map presentation for standard authors
- keep one workflow canvas implementation
- preserve interactivity and state sync

Acceptance:

- opening the map yields a legible interactive surface on desktop and mobile
- selection in the map and selection in the inline editor stay synchronized

### Phase 2. Redesign artifact authoring around real outputs

Files likely involved:

- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js)
- [models.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/models.py)
- [documents.py](/Users/tinker/output/bots/telegram-agent-bot/octopus_sdk/protocols/documents.py)

Work:

- redesign artifact catalog UX to emphasize concrete artifact presets
- make source/output/location/verification clearer
- keep one canonical artifact model underneath
- extend the canonical model only if the existing two-type model is truly too
  weak for product clarity

Acceptance:

- a new author can create a data/report workflow and understand where each
  artifact comes from and where it goes

### Phase 3. Tighten the blank-state 0-to-1 workflow builder

Files likely involved:

- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css)

Work:

- refine new-protocol blank states
- make “Add first step” and “Add artifact” first-class starting actions
- ensure inline step creation naturally leads into artifact attachment and
  routing

Acceptance:

- a new protocol can be built from blank through the UI without template
  dependence

### Phase 4. Refine assignment semantics without duplicating controls

Files likely involved:

- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css)

Work:

- keep standard assignment modes clean
- keep small-match pills and large-match select behavior
- ensure artifact + assignment + routing do not compete for visual prominence

Acceptance:

- assignment remains understandable and does not regress into duplicated control
  surfaces

### Phase 5. Implement meta-composition flow through UI and APIs

Files likely involved:

- protocol workspace UI
- skill catalog/management UI
- registry management API surfaces
- shared SDK models where needed

Work:

- add a guided composition path for “build a new assistant/process”
- allow users to pick existing skills
- allow creation/refinement of missing skills through UI/API
- allow those skills to be used immediately in protocol stage assignment

Acceptance:

- a new protocol-driven assistant can be created through the UI without DB
  manipulation

### Phase 6. Keep standard/operator separation strict

Files likely involved:

- protocol workspace UI
- registry API write surfaces

Work:

- retain capability-based gating
- ensure new artifact/map/composition features do not reintroduce standard-path
  leakage of operator-only controls

Acceptance:

- product power increases without reopening internal escape hatches for normal
  authors

## Test Strategy

## 1. Scenario Specs Are The Release Bar

The release bar remains:

- Software Engineering: author -> rehearse -> execute
- Document Approval: author -> rehearse -> execute
- Data Analysis / Reporting: author -> rehearse -> execute
- Meta Protocol Assistant: create skill/protocol composition via UI/API -> rehearse -> publish

## 2. Map Interaction Must Be Tested

We need explicit tests for:

- opening the map
- selecting nodes from the map
- returning to inline editor from the map
- preserving map interactivity
- mobile map presentation

## 3. Artifact Flow Must Be Tested

We need explicit tests for:

- defining artifacts from the catalog
- attaching them to steps
- validating required paths
- runtime verification visibility
- real data/reporting pipeline manifestation

## 4. Negative Invariants Stay In Force

Standard path must continue to omit:

- custom runtime selector
- advanced stage internals
- operator-only fields

## 5. Breadth Audit Remains Required

The live audit remains required and should continue to produce:

- 500+ screenshots minimum
- desktop, tablet, mobile coverage
- authoring, rehearsal, execution, and runs surfaces

But breadth does not replace depth. Scenario specs remain the release gate.

## Decisions

1. The workflow map stays in the product.
2. The workflow map is hidden by default.
3. When explicitly opened, the workflow map must be fully interactive and
   legible.
4. Artifacts become a first-class product concept, not just a checkbox list.
5. Artifact authoring must map to real files, documents, datasets, reports, and
   publishable outputs.
6. The UI manifests all changes through APIs, not DB writes.
7. Standard and operator paths remain distinct.
8. One editor pipeline remains the rule. No duplicate authoring systems.

## Risks

1. The current canonical artifact type model may be too narrow for the desired
   product clarity.
- If so, the right answer is deliberate SDK/API extension, not browser-only
  hacks.

2. The meta-protocol composition flow depends on skill-management surfaces being
   reliable enough for real authoring.
- If those APIs or UI surfaces are incomplete, that becomes a product milestone,
  not a documentation footnote.

3. The map refactor must preserve existing canvas logic.
- We should not fork a second graph implementation just to get a focused map
  mode.

## Definition Of Done

This work is done only when all of the following are true:

1. `Show workflow map` opens a legible, interactive, on-demand map surface.
2. The map is useful on desktop and mobile.
3. Artifact authoring clearly explains where artifacts come from and what they
   map to.
4. A normal user can build a realistic Data Analysis / Reporting workflow from
   scratch through the UI.
5. A normal user can build or refine Software Engineering and Document Approval
   workflows through the UI.
6. A user can create a new protocol-driven assistant by composing skills and
   protocols through UI/API flows, not DB mutation.
7. Standard-path negative invariants still hold.
8. Scenario specs pass end to end.
9. The exhaustive live audit passes with 500+ screenshots.

## Immediate Next Steps

1. Fix the workflow map presentation so explicit-open yields a focused
   interactive map mode.
2. Redesign artifact authoring so protocol-level artifact definitions are
   concrete and obvious.
3. Tighten the blank-state 0-to-1 creation flow around steps + artifacts +
   routing.
4. Add the first meta-protocol assistant scenario spec and identify any missing
   UI/API pieces required to make it real.
5. Re-run the full live scenario and audit matrix after each phase.
