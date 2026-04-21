**Protocol UX Coherence Plan**

## Status

This document supersedes the earlier "executed state" framing.

The product is not finished from a user-experience perspective. Core runtime,
authoring, rehearsal, and execution mechanics work, but the live UI still
fails the more important bar:

- a human author should be able to build, inspect, revise, and close out work
  fluidly
- the product should feel like one coherent workflow builder
- optional surfaces should stay useful without becoming sprawling page slabs

This plan captures the verified live UX problems, the product decisions needed
to fix them, the implementation sequence, and the regression bar that must be
green before this area is considered complete again.

## Problem Statement

The remaining problems are not isolated bugs. They are interaction-coherence
problems.

### 1. There is no consistent close/collapse model

In the live product:

- opening a stage expands a long inline editor
- there is no local, obvious `Close`, `Done`, or `Collapse` action for that
  editor
- opening route details, protocol settings, artifacts, or the map changes the
  page, but not through one consistent focus model

The user is forced to escape indirectly by clicking some other thing, scrolling
away, or re-entering another surface.

That is not a fluent editing experience.

### 2. The page is still too dense and sprawling

The standard authoring page still accumulates multiple major surfaces in one
vertical scroll:

- lifecycle header
- toolbar
- protocol settings
- artifact catalog
- workflow map
- stage stack
- expanded stage editor
- validation
- rehearsal

Even after simplification work, the page still behaves like stacked slabs
instead of a controlled editing environment.

### 3. The workflow map is optional, but not focused

The map is now interactive again, but opening it still inserts another large
section into the main page flow.

That means:

- it pushes the actual stage editor farther down
- it competes with the stage stack instead of feeling like an intentional
  secondary workspace
- opening it does not feel like “switch to map mode”; it feels like “add
  another big card”

### 4. Artifact definition breaks stage context

Stage-level artifact attachment is inline, but artifact definition/editing is
still routed through the separate protocol/artifact surface.

In practice:

- the stage says “these are this step’s inputs and outputs”
- clicking to define/edit artifacts jumps the user to another drawer/surface
- that surface is not locally closable in a way that feels tied to the stage
  they were working on

This breaks context and teaches the wrong mental model.

### 5. Desktop and mobile are structurally aligned, but not behaviorally humane

The product does share a broad structure across viewports, but the resulting UX
is still too document-like:

- desktop keeps too many large sections open
- mobile turns one selected step into a long scrolling form
- optional surfaces still pile onto the same vertical flow

That is technical responsiveness, not good task flow.

### 6. The release bar still needs to validate workflow usability, not just
mechanics

The tests already cover substantial authoring and execution flows, but they now
need to explicitly prove the new interaction rules:

- close/collapse behavior
- focused map behavior
- contextual artifact editing behavior
- reduced-density authoring behavior

The product is only complete when these behaviors are proven in the real
workflow scenarios.

## Context

The protocol product exists to let a human author create and operate practical
multi-step workflows through the UI and registry APIs.

The primary workflow families remain:

1. Software Engineering
2. Document Approval
3. Data Analysis / Reporting
4. Meta Protocol Assistant

The standard is not “the backend can technically run it.”

The standard is:

- the workflow can be created from zero through the UI
- the workflow can be edited without losing local context
- the workflow can be rehearsed visually
- the workflow can be executed against live connected agents
- the workflow can be inspected afterward in runs

All of that must happen through product surfaces and APIs, not database edits
or operator shortcuts.

## Verified Live Findings

These findings are grounded in live inspection of the deployed Octopus build
and the current live audit artifacts.

### Desktop findings

1. `Protocol settings` dominates the primary view when opened.
- It occupies the top of the page and pushes the workflow down.
- It feels like a separate page section embedded into the authoring flow.

2. An opened stage becomes a long exposed form.
- The editor opens inline, but it does not offer a local close/collapse action.
- The selected row remains the only obvious anchor back to the stage.

3. The workflow map opens as a page-extending slab.
- It is interactive.
- It is still inserted above the stage stack rather than opened as a focused
  secondary workspace.

4. Artifact editing still leaves stage context.
- Artifact attachment is local to the stage.
- Artifact definition/editing still routes through the protocol-level artifact
  surface instead of staying tied to the current stage.

### Mobile findings

1. Overview is still dense before any editing starts.
- Lifecycle actions, toolbar actions, and sections accumulate quickly.

2. Selected-stage editing becomes a very long vertical document.
- basics
- assignment
- refinement context
- routing
- instructions
- artifact checklists

3. Map-open mobile state is better than before, but still page-additive.
- It appears as another large block in the scroll rather than a focused
  temporary workspace.

## Discussion

### 1. The real problem is focus management

The product now has the right building blocks, but not the right focus model.

The user needs:

- one primary thing they are editing right now
- one obvious way to close it or return
- one optional secondary workspace at a time

The current UI still lets surfaces accumulate instead.

### 2. Optional surfaces should be mode changes, not extra slabs

`Show workflow map`, `Protocol settings`, and artifact definition are all valid
secondary surfaces.

They should behave like focused, intentional modes or local sub-editors.

They should not simply append more large sections into the same vertical page.

### 3. Artifact authoring should follow workflow context

Artifacts are not abstract protocol metadata. In the target workflows they are
the actual outputs and hand-offs:

- plans
- code files
- reports
- datasets
- PDFs
- published results

So artifact editing should feel like a continuation of stage authoring, not a
jump to a detached admin surface.

### 4. Consistency matters more than local convenience

The product needs one coherent rule for opening and closing major surfaces.

Right now the rules differ by surface:

- stage selection opens inline
- route selection shifts panel context
- settings changes the top of the page
- map inserts a new slab
- artifact editing jumps away

That inconsistency is a bigger UX problem than any individual panel.

### 5. No duplicate authoring pipelines remains a hard rule

These fixes must extend the current stage-stack authoring path.

Do not introduce:

- one desktop editor model and one mobile editor model
- one stage artifact flow and another global artifact flow with different
  semantics
- a second map implementation for “focused mode”

One coherent path, reused across surfaces.

## Product Decisions

These decisions define the target behavior for the next implementation pass.

1. The stage stack remains the primary authoring surface.
2. Only one major authoring focus should be open at a time.
3. Every opened major surface must have an explicit, local close/collapse
   affordance.
4. Clicking the selected stage again may collapse it, but there must also be a
   visible local close control on the expanded editor.
5. `Protocol settings` becomes a focused secondary surface, not an always-open
   slab in the same page flow.
6. `Show workflow map` opens a focused, interactive map workspace.
7. Artifact definition/editing from a stage must stay in stage context.
8. Protocol-level artifact catalog remains available, but only as a secondary
   management surface.
9. Desktop defaults must reduce vertical density.
10. Mobile must present one primary task at a time rather than one long open
    document.
11. Standard/operator separation remains intact.
12. All changes must continue to operate through UI + APIs, not DB mutation.

## Target Interaction Model

### A. Stage editing

When a stage is selected:

- the stage row expands inline
- the expanded editor has a local header action to close/collapse
- the editor can be collapsed without selecting some other row first
- only one stage editor is open at a time

Expected close behaviors:

- `Close` or `Done` in the stage editor header
- optional second path: clicking the selected stage row again collapses it

### B. Protocol settings

`Protocol settings` should not behave as a giant slab inserted into the same
document flow.

Target behavior:

- desktop: open as a focused settings surface above or beside the stack with a
  clear `Back to workflow` / `Close settings`
- mobile: open as a sheet or full-screen settings view with a clear close
  affordance

It must not remain visually merged into ordinary stage authoring.

### C. Workflow map

`Show workflow map` should behave like entering a focused map workspace.

Target behavior:

- desktop:
  - open as a focused secondary workspace with meaningful size
  - preserve viewport and selection
  - close returns to the prior stage/editor context
- mobile:
  - open as a full-screen sheet/panel
  - close returns to the prior stage/editor context

The map remains interactive:

- select step
- select transition
- zoom
- fit

But it should not just add another tall block to the page.

### D. Artifact editing

From the stage’s `Inputs and outputs` section:

- `Add new artifact` and `Edit workflow files and outputs` should open a local
  artifact manager/editor tied to that stage
- artifact definition should appear inline below that stage or in a local sheet
  anchored to that stage context
- `Done` / `Back to step` must return the user to the same stage editor

Protocol-wide artifact catalog remains useful for:

- overview
- cleanup
- deduplication
- management across the whole workflow

But stage-originated artifact editing should not force a context break.

### E. Density and disclosure

Desktop default open state should become more disciplined:

- keep `Step basics` and `Assignment` open by default
- keep `Routing`, `Instructions`, and `Inputs and outputs` collapsed or
  compact by default when appropriate
- reduce helper copy where the controls already explain themselves

Mobile should go further:

- only one section within a stage editor expanded by default
- secondary surfaces opened as sheets/full-screen panels
- persistent toolbar density reduced before stage selection

## Implementation Plan

### Phase 1. Establish one focus model

Unify major-surface behavior around one primary focus abstraction in
[protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js).

This should cover:

- stage focus
- protocol settings focus
- artifact focus
- map focus
- route focus

Requirements:

- one source of truth for the active major surface
- query-state alignment for refresh/back/forward
- no surface remaining “open” only because a large section was appended into
  the document

Implementation guidance:

- extend the existing `selection` / `editorMode` pipeline rather than adding a
  parallel focus router
- preserve the current query-driven approach
- encode enough state so refresh returns the user to the same meaningful place

### Phase 2. Add explicit close/collapse behavior

Make close behavior local and consistent.

Requirements:

- expanded stage editor has explicit close/collapse action
- settings surface has explicit close action
- artifact editor has explicit close/back action
- map workspace has explicit close action

Implementation guidance:

- reuse the current inline stage editor shell rather than creating a second
  editor variant
- use one close pattern across desktop and mobile, adapting presentation only
  where needed

### Phase 3. Recompose protocol settings as a secondary surface

Protocol settings should stop occupying the top of the normal stage-authoring
flow.

Requirements:

- opening settings enters a focused settings mode
- closing settings returns to the stage stack exactly where the user was
- artifact catalog shown from settings remains usable, but does not own the
  stage editing loop

Implementation guidance:

- reuse the existing protocol settings and artifact catalog components
- change placement and focus behavior, not data ownership

### Phase 4. Recompose the workflow map as a focused workspace

Requirements:

- map opens in a focused workspace with real room to breathe
- map closes back to prior stage/settings context
- map retains interactivity and synchronization
- mobile map is a full-screen panel or sheet, not an inserted block

Implementation guidance:

- reuse existing `workflowCanvas` and map state
- do not create a second graph implementation
- only change how the map is presented and entered/exited

### Phase 5. Make artifact editing contextual

Requirements:

- stage-originated artifact creation/editing stays tied to the current stage
- artifact definitions can be created and edited without losing stage context
- protocol-wide artifact management remains available as a secondary path

Implementation guidance:

- reuse the existing artifact editor shell and artifact catalog logic
- present it as a local sub-editor/sheet from the stage path
- keep one artifact data pipeline and one artifact save pipeline

### Phase 6. Reduce density and rewrite default disclosure

Requirements:

- desktop stage editor opens with less visual mass
- mobile stage editor exposes one primary task at a time
- helper text is shortened where controls are already clear
- toolbar and settings footprint are reduced in the normal authoring flow

Implementation guidance:

- prefer changing default open state and surface placement before rewriting all
  copy
- keep copy changes small and purposeful

### Phase 7. Expand scenario tests to cover coherence rules

Add explicit scenario assertions for:

1. Close/collapse
- selecting a stage opens it
- local close returns to stack-only state
- selected-stage repeat interaction behaves as designed

2. Map focus
- map opens in focused mode
- selection and viewport persist
- close returns to prior context

3. Artifact context
- editing artifacts from a stage opens local artifact definition flow
- closing artifact editing returns to the same stage
- no jump to detached protocol-settings slab on the standard path

4. Refresh continuity
- refreshed page returns to the same meaningful focus state
- stage focus persists
- explicit map/settings focus persists when encoded in query state

These must be added to:

- [tests/e2e/playwright/protocol-ui.spec.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui.spec.js)
- live audit coverage in `.tmp/playwright/live-exhaustive-audit.spec.js`

### Phase 8. Visual audit and cleanup

After the interaction model lands:

- rerun live exhaustive audit
- confirm 500+ screenshot breadth
- remove dead UI states and stale tests tied to the old slab-style settings/map
  flow
- update `plan_fix.md` again only after the new product behavior is verified

## Scenario Assertion Contract

The named scenarios must now prove coherence, not just correctness.

### A. Software Engineering

Must prove:

- inline stage editing remains understandable
- stage editor can be closed fluently
- artifact editing from `Architecture` stays in local context
- map opens/closes as a focused secondary workspace
- rehearsal and execution still pass

### B. Document Approval

Must prove:

- revise/approve loop remains understandable
- mobile map behavior does not create page sprawl
- stage close/collapse behavior is clear on a short review workflow

### C. Data Analysis / Reporting

Must prove:

- artifacts feel like a real pipeline, not hidden metadata
- defining and editing datasets/reports from a stage feels local and natural
- author can move from ingest -> filter -> analyze -> render -> publish without
  getting pushed into disconnected settings flows

### D. Meta Protocol Assistant

Must prove:

- skill publishing and protocol composition remain UI/API-driven
- secondary surfaces do not overwhelm the core “compose workflow” task
- map/settings/artifacts remain supportive, not dominant

### Negative invariants

These still remain mandatory on the standard path:

- no custom runtime selector
- no generic advanced section
- no stage key editing
- no timeout/max-round controls

## Testing And Verification

### PR gate

Required on every change in this area:

1. `./.venv/bin/python -m pytest tests/test_protocols.py tests/test_protocol_rehearsal.py tests/test_protocol_engine.py tests/test_db_postgres.py tests/test_registry_ui_contract.py tests/test_registry_service.py tests/test_registry_ui_kit_contract.py -q`
2. `./.tmp/playwright/node_modules/.bin/playwright test tests/e2e/playwright/protocol-ui.spec.js --config=tests/e2e/playwright.config.js`

### Release bar

Required before calling this area complete again:

1. live authoring/execution scenario suite green
2. live exhaustive audit green
3. live runs matrix green
4. live audit capture count remains above 500

### Breadth rule

The 500+ screenshot rule remains breadth validation, not a substitute for
scenario specs.

## Risks

1. Focus-model changes can regress query-state handling again.
2. Map-mode changes can accidentally create a second graph interaction path if
   implemented carelessly.
3. Artifact contextual editing can create duplication if the same editor is
   rebuilt instead of relocated/reused.
4. Mobile sheets/full-screen panels can drift from desktop behavior if they are
   treated as a separate product instead of the same model with different
   presentation.

## Definition Of Done

This plan is complete only when all of the following are true:

1. A stage can be opened and closed fluently.
2. Protocol settings behaves as a focused secondary surface, not a page slab.
3. The workflow map behaves as a focused interactive workspace, not a block
   inserted into the main page flow.
4. Artifact definition/editing from a stage remains in stage context.
5. Desktop density is materially reduced by better disclosure and surface
   placement.
6. Mobile editing behaves like one primary task at a time, not one long open
   document.
7. All named scenarios still pass author -> rehearse -> execute end to end.
8. Standard-path negative invariants still hold.
9. The live exhaustive audit remains above the 500-screenshot bar.

That bar is not currently met. This document remains an active plan until those
conditions are proven green.
