**Protocol UX Product Plan**

## Status

This file is the active implementation plan.

The current protocol editor is functionally far better than the earlier broken
state, but it is still not product-complete. The remaining issues are not
primarily correctness bugs. They are interaction-model, hierarchy, density, and
workflow-usability problems.

This plan replaces the previous "verified green state" framing. The standard is
now product-shaped:

- a human author can build and evolve real workflows through the UI
- a human operator can understand what happened after execution
- the editing flow stays anchored and easy to follow
- the working area stays in view
- deeper editing does not sprawl downward into a long document
- map, settings, and artifact definition stay available without dominating the
  main workflow surface
- runs, tasks, approvals, and artifacts read as one connected lineage rather
  than unrelated admin surfaces
- the tests prove those workflows end to end

## Core Problem Statement

The current editor still behaves too much like an expanded configuration
document and not enough like a progressive workflow builder.

The main live problems are:

1. Opening a stage expands a large editor below the row and pushes the working
   area downward. The user loses the visual anchor they just clicked.
2. Too many things are visible at once inside an open stage:
   - basics
   - assignment
   - routing
   - instructions
   - inputs and outputs
   - actions
3. Secondary surfaces still interrupt the primary authoring flow:
   - workflow map is available, but its presentation still needs to behave like
     a focused workspace when opened
   - protocol settings can still feel like a separate slab
   - artifact editing can still break continuity if it behaves like a detached
     catalog instead of a local stage-owned action
4. The UI got more compact, but not lighter. Spacing was reduced faster than
   chrome, borders, sections, and repeated labels were removed. That increased
   perceived density.
5. The interface still exposes too much of each stage at one time, which scales
   poorly when workflows have many stages or richer artifact flows.
6. Operational surfaces still feel siloed:
   - `Runs`
   - `Tasks`
   - `Approvals`
   - artifact/file outputs
   - stage executions
   are rendered like neighboring resource types, not one traceable workflow
   history.
7. Artifact observability is too weak after execution:
   - users cannot clearly see where artifacts live on disk
   - users cannot reliably open/download/copy them from the operational
     surfaces
   - artifacts do not read as stage inputs/outputs/reviewed outputs in a way
     that explains the workflow result
   - the current implementation still treats artifact bytes too much like a
     registry-local file concern instead of a shared workspace concern
8. UX coverage still cheats too often when setup is created outside the normal
   product flow. That makes tests less trustworthy as product-usability proof.

The result is a product that works, but still asks the user to manage the UI
instead of progressing naturally through the workflow they are building.
And after the workflow runs, it still asks the user to infer lineage and output
state instead of showing it clearly.

## Product Standard

A feature in this area is only complete when at least one scenario spec for
each target workflow passes end to end through the UI:

- author
- rehearse
- execute

Isolated controls, green APIs, or passing smoke tests are not enough.

The target workflows are:

1. Software Engineering
2. Document Approval
3. Data Analysis / Reporting
4. Meta Protocol Assistant

## Product Principles

### 1. One anchor, one active work area

When a stage is selected, that stage stays visually anchored. The active work
surface for that stage remains immediately adjacent to the anchor, not below a
long stack of open content.

### 2. One meaningful task at a time

Inside a stage, the UI should guide the user through one active subpanel at a
time. The editor should feel progressive, not document-like.

### 3. Secondary surfaces are focused, not stacked

Workflow map, protocol settings, and artifact definition remain available, but
they must open as focused secondary workspaces, not as additional slabs in the
main scroll.

### 4. Space is part of the product

Brightness, rhythm, and breathing room are not decorative. They are part of
comprehension. Reducing cognitive load requires removing simultaneous structure,
not only tightening spacing.

### 5. No duplicate pipelines

There is one authoring pipeline. All improvements must extend the existing
selection, projection, and editor model in place.

### 6. UI manifests change through API-backed actions

The product must support creating and evolving workflows, skills, and protocol
compositions through the UI/API path. No database-first shortcuts.

### 7. Run lineage must be obvious

Operational surfaces must explain the hierarchy:

- Protocol
- Run
- Stage execution
- Task / routed task / assignment attempt
- Approval / decision
- Artifacts read, written, reviewed, approved, or verified

The UI should reveal this as one story, not force the user to mentally join
independent lists.

### 8. Artifact observability comes before rich preview

Before rendering every possible file type inline, the product must first make it
easy to answer:

- what artifact was involved?
- which stage/task/run did it belong to?
- where is it on disk?
- can I open it, download it, or copy its path?

### 9. Shared workspace is the canonical substrate for workspace files

For `workspace_file` artifacts, the canonical bytes live in the shared
workspace, not inside a registry-local store and not as a bot-private concept.

The product model is:

- registry owns artifact metadata, lineage, and workflow state
- bots and humans are peers operating on the same shared files
- artifact access from the UI must resolve through that shared substrate

Tracked human provenance is a follow-on capability, not a blocker for this
phase. The current phase must leave a clean slot for it without implementing a
full provenance system yet.

## Decisions

### A. Selected stage becomes a focused working thread

The selected stage row remains the local anchor.

It shows:

- stage name
- compact summary
- explicit `Done`
- destructive action only where appropriate
- local insertion affordance nearby, not as a repeated heavy command

### B. The stage editor becomes progressive

The selected stage owns one active subpanel at a time:

- Step basics
- Assignment
- Routing
- Instructions
- Inputs and outputs

Moving deeper into the stage swaps or focuses the local work area instead of
expanding the page downward indefinitely.

### C. `Done` stays explicit

Do not replace `Done` with an icon-only affordance. The exit from stage editing
should remain unmistakable.

### D. Insertion becomes structural, not command-heavy

The inline insertion affordance should feel like "insert here", not "invoke a
builder command".

Likely direction:

- lightweight `+` insertion bar or slot between stages
- visible label only when useful
- no return to repeated large `Add below` buttons

### E. Inactive rows recede by omission, not just compression

Non-selected rows should show only the structural information needed to scan
the workflow:

- title
- one short status/assignment line where useful
- insertion affordance nearby

They should not carry excessive summary or helper text.

### F. Artifact editing is stage-contextual first

Artifact attachment and artifact definition belong in the stage flow first.

The user should be able to:

- attach artifacts to a stage inline
- create a new artifact from that stage
- edit the selected artifact definition in local context
- return directly to the same stage artifact panel

The protocol-wide artifact catalog remains available as a management surface,
not as the default editing destination from a stage.

### G. Map and settings are focused secondary workspaces

When opened intentionally:

- workflow map must be properly sized and fully interactive
- protocol settings must open as a focused secondary workspace
- both must preserve context and return the user to the same stage/list state

They should not extend the main page into a longer stacked document.

### H. Density responds to workflow size, but never by compression alone

More complex workflows should compress inactive structure more aggressively, but
selected work should still retain breathing room. Do not answer complexity only
by shrinking paddings and gaps.

### I. Runs become the canonical operational container

`Runs` should become the primary operational home for protocol execution.

`Tasks`, `Approvals`, and artifact evidence should behave like focused views
into that run lineage, not peer concepts with unclear relationship.

### J. Artifact rendering is progressive, not universal

Do not try to render every artifact type inline.

Adopt a support ladder:

- baseline: metadata + path + actions
- lightweight preview for safe/common renderable formats
- open/download for everything else

### K. UX scenarios must create meaningful state through the product path

For scenario tests that claim usability:

- no database writes
- no hidden data seeding for normal user journeys
- no creating critical state through privileged back doors unless the scenario
  is explicitly about an operator-only flow

Public API calls are acceptable only when they are part of the intended product
surface for that workflow.

### L. Artifact access must follow artifact kind, not registry locality

The system should not assume the registry is the conceptual owner of artifact
bytes.

For now:

- `workspace_file` artifacts resolve through the shared workspace model
- registry uses that shared substrate to provide preview/open/download actions
- bots remain the primary writers for automated stage execution
- humans must be able to participate against the same workspace files

Later:

- human edits, reviews, and approvals should be tracked explicitly in artifact
  provenance and run history

That future provenance model must be compatible with the current shared
workspace approach, but it is not required to ship this phase.

## Target UX

### Default workflow view

The default view is a quiet, scan-friendly stage stack.

What is visible:

- workflow header
- lightweight top actions
- stage stack
- insertion slots

What is not visible by default:

- full map
- full settings slab
- full artifact catalog
- full long-form stage editor

### Selected stage view

Selecting a stage should:

- keep the selected row in place as the anchor
- open a local focused work area directly beneath or attached to that row
- keep the work header visible
- expose one active subpanel by default

The user should not need to scroll just to reach the thing they just opened.

### Progressive subpanel flow

Inside a selected stage:

- opening Assignment focuses Assignment
- opening Inputs and outputs focuses Inputs and outputs
- deeper actions use local `Back` or `Done`
- previously open panels do not remain equally expanded underneath

### Artifact flow

From a stage, the author should be able to say:

- this step reads these artifacts
- this step writes these artifacts
- add a new workflow file/output right here
- edit this artifact definition right here

This is especially important for:

- code files
- documents
- datasets
- generated reports
- published outputs

### Map flow

`Show workflow map` should mean:

- open the map properly
- keep it interactive
- use it intentionally
- return cleanly to the stage flow

It should not mean:

- reveal another dense block in the main scroll

### Operational flow

When the user opens a run, task, or approval, the product should answer:

- what workflow did this come from?
- what stage is this part of?
- what happened before and after?
- what artifacts were read or produced?
- where are those artifacts now?

The user should not have to jump blindly between `Runs`, `Tasks`, and other
screens to reconstruct a single execution.

### Artifact flow after execution

From a run or task detail surface, the user should be able to:

- see stage-related artifact inputs and outputs
- see whether they were declared, available, verified, reviewed, or approved
- see the workspace-relative path
- reveal the resolved disk path when the artifact is local
- `Open`
- `Download`
- `Copy path`

For `workspace_file` artifacts, these actions must work against the same shared
workspace files that bots and humans use during execution. The UI should not
depend on a second artifact-copy pipeline just to make preview/download work.

Preview is conditional:

- text/code/json/yaml/logs: syntax-highlighted preview
- markdown: rendered preview with raw toggle
- csv/tsv: bounded table preview
- pdf: native embedded preview in a focused panel
- images: thumbnail/lightbox
- xlsx/docx/pptx and similar: metadata + open/download first, richer preview
  only if a reliable rendering path exists

## Scenario Assertion Contract

Every major scenario must prove these categories through the standard UI path.

### Structure

- stage order remains readable
- selected stage remains anchored
- no reliance on the map for primary authoring
- opening a stage does not push the active work area below the fold without
  need

### Progressive focus

- one active subpanel is primary at a time
- local `Done` and local back/close behavior are clear
- settings, map, and artifact definition can open and close without breaking
  stage context

### Routing

- transitions or outcomes are visible and correct
- revise/approve or branch semantics remain understandable

### Assignment

- assignment uses the standard path only
- skill/agent choices stay understandable
- no internal selector escape hatches appear in the standard path

### Artifacts

- stage reads/writes are visible and editable inline
- artifact definitions can be created and edited from the stage flow
- data/file/report chains remain understandable and correct
- operational artifact actions must work against the deployed product path, not
  only against seeded metadata

### Rehearsal

- ordered stage progression is visible
- the workflow behaves as expected under revise/accept and other scenario
  outcomes

### Execution

- terminal state is correct
- artifact/outcome state is correct where the product defines it
- the run/task lineage is understandable without cross-referencing unrelated
  pages
- artifact location and access actions are available from the operational path

## Target Workflow Specs

### 1. Software Engineering

The user can:

- scan a multi-stage workflow without overload
- open `Planning`, `Architecture`, or `Implementation` and stay anchored there
- edit assignment, routing, and artifacts progressively
- rehearse revise loops and acceptance flow
- execute the workflow through the live registry

Specific interaction bar:

- editing `Architecture` artifacts must stay on `Architecture`
- opening a stage must keep the selected work area in view
- non-selected stages must remain quiet enough to scan

### 2. Document Approval

The user can:

- scan the draft-review-approval flow quickly
- edit one step at a time without page sprawl
- rehearse revise and approve outcomes
- execute the workflow through the live registry

### 3. Data Analysis / Reporting

The user can:

- create or edit a flow like:
  - load data
  - filter rows
  - analyze
  - render report
  - publish
- define artifacts as real workflow files/outputs
- attach them to each step in context
- understand the artifact chain visually
- rehearse and execute the workflow through the live registry

### 4. Meta Protocol Assistant

The user can:

- create a custom skill draft through the UI/API path
- keep it selected while editing
- publish it
- create a protocol that uses it
- compose a protocol-driven assistant that helps create further protocols or
  skills
- prove this through rehearsal and execution, not database shortcuts

## Operational Product Gap

The next product gap is not primarily in authoring. It is in operational
understanding.

Today the product makes the user do too much joining across surfaces:

- `Runs` looks like one concept
- `Tasks` looks like another
- `Approvals` looks like another
- artifacts feel implicit or hidden

That prevents the user from understanding the real hierarchy:

- this run executed this workflow
- this stage created this task
- this decision advanced or blocked it
- these artifacts were involved
- these files are the concrete outputs

The plan below addresses that by turning runs into the main operational
container and making artifact evidence visible and actionable.

That operational gap now has an explicit architectural shape:

- registry owns run/task/artifact lineage
- shared workspace owns `workspace_file` bytes
- bots and humans are peers against that shared substrate
- preview/download/open must work through that model, not through registry-only
  locality assumptions

## Implementation Plan

### Phase 0. Re-baseline with live findings

Before implementation starts:

- replace stale "green/complete" framing in tests and docs
- codify the current regressions as named scenario expectations
- capture representative before-state screenshots for:
  - desktop overview
  - selected stage
  - artifact editing
  - map open
  - mobile selected stage

### Phase 1. Stage anchor model

Objective:

- keep the selected stage header anchored
- prevent the active work area from drifting out of view immediately after open

Implementation direction:

- reuse the existing selection model
- restructure the selected row/editor composition so the working header and the
  active panel live in one local shell
- preserve scroll position intentionally instead of letting the page grow first
  and relying on the user to chase the editor

Acceptance:

- opening a stage keeps the active work surface visible without manual
  corrective scrolling
- clicking `Done` closes the local work surface cleanly

### Phase 2. Progressive subpanel model

Objective:

- convert the open stage from a long document into a progressive work flow

Implementation direction:

- reuse the existing sections:
  - basics
  - assignment
  - routing
  - instructions
  - inputs/outputs
- add one active-subpanel state inside the existing editor pipeline
- make opening one major subpanel demote the others
- keep summary affordances for collapsed sections minimal

Acceptance:

- only one major subpanel reads as the active working area
- opening a new subpanel does not keep the old one equally expanded below it

### Phase 3. Local artifact editing

Objective:

- keep artifact definition inside stage context for normal authoring

Implementation direction:

- reuse the existing artifact editor implementation
- move or host it as a local stage-owned subpanel or nested local workspace
  rather than forcing a jump to the protocol-wide artifact surface
- preserve the protocol-wide artifact catalog as a separate management view

Acceptance:

- from `Inputs and outputs`, the user can add/edit an artifact and return
  directly to the same stage
- no context-breaking jump is required for ordinary artifact work

### Phase 4. Focused secondary workspaces

Objective:

- make map and settings helpful without disrupting the main authoring flow

Implementation direction:

- workflow map opens in a properly sized focused surface
- protocol settings open in a focused secondary surface
- both preserve the prior stage selection and viewport context
- both close cleanly back to the same workflow state

Acceptance:

- map is fully interactive and usable when opened
- map/settings do not lengthen the main editor into another stacked slab

### Phase 5. Density and hierarchy correction

Objective:

- restore breathing room and visual lightness without reintroducing sprawl

Implementation direction:

- reduce simultaneous visible structure
- reduce borders and repeated card framing where possible
- keep more whitespace around the active panel
- make inactive rows quieter through omission, not just smaller paddings
- keep `Done` explicit
- evolve insertion toward a cleaner structural affordance

Acceptance:

- the interface feels lighter, not merely smaller
- larger workflows remain easier to scan than the current live build

### Phase 6. Workflow-size responsiveness

Objective:

- make the same UI scale across small and large workflows

Implementation direction:

- for small workflows, allow slightly richer row summaries
- for medium workflows, compress inactive rows more aggressively
- for larger workflows or branched workflows, lean harder on quiet structure and
  focused editing

Acceptance:

- Software Engineering remains scannable
- Document Approval remains simple
- Data Analysis remains readable despite richer artifact structure

### Phase 7. Scenario tests first-class

Objective:

- prove workflow usability, not only mechanics

Implementation direction:

- update Playwright scenario specs so they assert:
  - anchored stage selection
  - active work panel visibility
  - local `Done` / local return behavior
  - stage-contextual artifact editing
  - focused map/settings behavior
- keep backend/runtime tests unchanged except where new UI/API flows require
  additional proof

Acceptance:

- each target workflow has at least one primary owning scenario spec
- scenario specs become the release bar

### Phase 8. Operational lineage model

Objective:

- make the relationship between runs, tasks, approvals, stage executions, and
  artifacts obvious

Implementation direction:

- treat `Runs` as the canonical operational container
- add explicit lineage summaries to run detail:
  - protocol
  - current/completed stage executions
  - decisions
  - tasks/assignment attempts
  - artifacts
- make task and approval views show their parent run and stage context
- reduce the feeling that these are unrelated modules

Acceptance:

- a user can open a run and understand the execution story without jumping
  across the product
- a user can open a task and immediately see which run and stage it belongs to

### Phase 9. Shared workspace artifact access model

Objective:

- make `workspace_file` artifact access coherent with the real product model

Implementation direction:

- centralize artifact path/access resolution instead of scattering local-path
  logic across task/run handlers
- treat the shared workspace as the canonical byte substrate for
  `workspace_file` artifacts
- make the deployed registry access those shared workspace files through the
  existing Octopus workspace configuration, without introducing a second
  artifact storage path
- keep the model compatible with human collaborators editing the same files
  later

Acceptance:

- `Open`, `Download`, and `Copy path` work for `workspace_file` artifacts from
  the deployed UI
- the implementation does not depend on database-side artifact byte copies
- the implementation does not introduce a parallel artifact-serving pipeline

### Phase 10. Artifact observability in operational views

Objective:

- make artifact outputs first-class evidence on runs, tasks, and stage
  executions

Implementation direction:

- expose artifacts on run detail, stage execution detail, and task detail
- show relationship type:
  - reads
  - writes
  - verified output
  - reviewed
  - approved
- show workspace-relative path prominently
- support resolved local path as secondary detail when available
- add actions:
  - `Open`
  - `Download`
  - `Copy path`

Acceptance:

- users can locate real outputs from the operational UI without guessing
- users can move directly from an execution record to the underlying file

### Phase 11. Preview ladder

Objective:

- add useful preview only where it is reliable and low-friction

Implementation direction:

- support focused preview for:
  - text/code/json/yaml/logs
  - markdown
  - csv/tsv
  - pdf
  - images
- do not force preview for office binaries or complex formats without a solid
  rendering path
- keep preview secondary to the artifact card and access actions

Acceptance:

- preview enhances understanding without turning the UI into a generic file
  browser
- unsupported formats still have strong open/download/path handling

### Phase 12. UX scenario discipline

Objective:

- make "this workflow is usable" a trustworthy claim

Implementation direction:

- divide tests clearly:
  - contract/integration tests may use direct API setup where appropriate
  - UX scenario tests must create meaningful workflow state through the UI and
    intended public API surfaces
- remove hidden setup that bypasses ordinary authoring or operational flows for
  the scenarios that claim product usability
- add explicit checks for run/task/artifact lineage and artifact access from
  the UI

Acceptance:

- UX scenarios no longer depend on database-style shortcuts
- green scenario coverage means a user actually exercised the product path

### Phase 13. Exhaustive live audit

Objective:

- validate breadth after the focused scenario specs are green

Implementation direction:

- rerun the live exhaustive audit on the deployed build
- include desktop, tablet, and mobile
- include add stage, remove stage, select skill, select agent, artifact edits,
  map open/close, settings open/close, rehearsal, execution, run/task lineage,
  and artifact access actions
- retain the 500+ screenshot breadth bar, but treat it as breadth validation,
  not the primary correctness bar

Acceptance:

- live audit confirms no new interaction regressions
- screenshots show the anchored, progressive model across surfaces

### Phase 14. Cleanup

Objective:

- remove dead assumptions and duplicate coverage

Implementation direction:

- remove or rewrite stale tests tied to the old sprawling layout contract
- remove dead helper copy and duplicated summaries
- remove any obsolete UI branches kept only for earlier transition states
- remove stale test helpers that bypass the intended UX path for scenario
  coverage

Acceptance:

- one coherent authoring pipeline remains
- no stale interaction models are left behind in code or tests

## Standard-Path Restrictions That Must Remain

These remain required:

- no custom runtime selector in the standard path
- no standard-path `Advanced` section
- no standard-path editing of:
  - `stage_key`
  - `max_rounds`
  - `timeout_seconds`

If an operator surface exists, it must remain clearly separate and not pollute
the standard authoring path.

## Verification Matrix

The final verification bar for this plan is:

- backend/runtime contract tests
- primary scenario Playwright suite
- negative standard-path invariants
- live rehearsal and execution smoke
- operational lineage and artifact access scenario coverage
- shared-workspace artifact access coverage on the deployed build
- exhaustive live audit

The live audit remains a breadth requirement. The scenario specs are the depth
and release requirement.

## Definition of Done

This plan is complete only when all of the following are true on the deployed
Octopus build:

1. Opening a stage keeps the working area anchored and in view.
2. The selected stage uses a progressive subpanel model instead of a sprawling
   long-form expansion.
3. Artifact definition/editing is stage-contextual for ordinary authoring.
4. Workflow map and protocol settings behave as focused secondary workspaces.
5. The UI feels lighter and easier to scan than the current dense build,
   especially on Software Engineering.
6. Software Engineering passes end to end through the UI:
   - author
   - rehearse
   - execute
7. Document Approval passes end to end through the UI:
   - author
   - rehearse
   - execute
8. Data Analysis / Reporting passes end to end through the UI:
   - author
   - rehearse
   - execute
9. Meta Protocol Assistant passes end to end through the UI/API path:
   - create skill
   - create protocol
   - rehearse
   - execute
10. Runs, tasks, approvals, and artifacts read as one coherent operational
    hierarchy.
11. Artifact outputs can be located from the operational UI:
    - path visible
    - open/download/copy-path available
12. For `workspace_file` artifacts, those access actions resolve through the
    shared workspace model used by bots and available to future human
    collaborators.
13. Preview is available for the supported artifact types without overwhelming
    the operational surfaces.
14. UX scenario coverage for product-usability claims is authored through the
    UI/intended API path, not hidden setup.
15. The current implementation leaves a clean path for tracked human artifact
    provenance later without requiring that full provenance system to ship in
    this phase.
16. No duplicate authoring or operational pipeline was introduced.
