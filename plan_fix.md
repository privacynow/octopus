**Protocol UX Density And Hierarchy Plan**

## Status

The protocol authoring product is functionally coherent, but it is still too
dense, too verbose, and too cognitively heavy once a workflow grows past a few
steps.

The current standard surface is no longer broken in the earlier ways:

- step-owned assignment works
- focused secondary surfaces exist
- artifact editing stays in workflow context
- `Done` gives the selected step a real local exit
- end-to-end authoring, rehearsal, and execution scenarios are green

That is not the finish line.

The next product pass is about scaling the interface for real workflows so a
human author can read, edit, insert, and navigate without carrying too much UI
weight at once.

This document replaces the previous verified-state framing with the active plan
for that next pass.

## Problem Statement

The remaining product issue is not correctness first. It is information
hierarchy, density, and interaction cost.

### 1. The stage stack is still too loud

With larger workflows like Software Engineering, every row and control still
demands too much attention.

Symptoms:

- non-selected stages carry too much visible metadata
- insertion buttons repeat loudly across the stack
- row chrome competes with actual stage names
- the selected stage editor opens a large document and the rest of the stack
  does not recede enough

The result is a screen that works, but asks the user to parse too much.

### 2. The insertion affordance is explicit but too heavy

`Add below` is clear, but it reads like a tool command rather than a natural
structural insertion affordance.

For a repeated interaction inside a workflow stack, that is too verbose.

The product should feel more like:

- insert here

and less like:

- invoke the add-below action

### 3. The selected step editor still exposes too much at once

Even with `Done`, the selected step is still a large multi-section document.

The issue is not that any individual section is wrong. The issue is that:

- too many sections are visible with similar visual weight
- too much helper copy stays persistent
- the editing surface does not compress enough as workflow complexity grows

### 4. The UI does not yet adapt strongly enough to workflow size

The same authoring treatment is being applied to:

- a blank one-step draft
- a three-step approval flow
- a seven-step software engineering workflow
- a future larger branched workflow

That is the wrong model.

The surface needs to respond not just to viewport size, but to workflow size
and complexity.

### 5. Cognitive load remains too high on mobile and desktop

Desktop still feels busy when several stages are visible.

Mobile still turns one stage into a long task document instead of a more
focused “edit one thing at a time” experience.

The problem is not pure responsiveness. It is task shaping.

## Product Goal

The product should feel like a lightweight workflow builder that scales.

A user should be able to:

1. read the structure quickly
2. identify the active stage immediately
3. insert a stage without reading a full button label each time
4. edit one stage without the rest of the page competing for attention
5. move through larger workflows without fatigue

The stage stack should communicate structure first, detail second.

## Design Principles

### 1. Structure first, detail on demand

Unselected stages should be structurally legible and visually quiet.

The selected stage should hold the detail.

### 2. One loud thing at a time

When a stage is selected:

- that stage is the loudest thing
- the rest of the stage stack recedes
- secondary surfaces remain secondary

### 3. Repeated controls should be compact and standard

Insertion and row-level actions should feel like standard structural controls,
not repeated blocks of command text.

### 4. Density must scale with workflow size

The more stages the workflow has, the more aggressively the UI should compact
non-essential detail.

### 5. The same product model must hold across desktop and mobile

No separate authoring concept for mobile.

The surface can be more compressed or stepwise, but the mental model must stay
the same.

## Product Decisions

### 1. `Done` stays explicit

Do not convert `Done` into a minus icon or ambiguous icon-only control.

Reason:

- minus reads as remove/collapse/subtract
- `Done` clearly means “I am finished with this stage editor”
- the product still benefits from explicit language at the primary close point

Refinement direction:

- keep `Done`
- optionally pair it with a collapse icon visually
- do not replace it with icon-only affordance

### 2. `Add below` should evolve into a lighter insertion affordance

The current wording is too heavy for a repeated inline action.

Target behavior:

- use a more standard `+` / insertion bar / inline insertion affordance
- keep accessible labeling such as `Add step below`
- reduce visual and textual weight in the normal surface

Important:

- there must still be a clear insertion target
- the action must remain explicit for accessibility and tests
- this is a presentation and interaction refinement, not a semantic change

### 3. Non-selected rows should become much quieter

For non-selected stages:

- show stage name first
- show one short metadata line only
- reduce button chrome
- remove repeated explanatory text
- avoid duplicating detail that is already in the open editor

### 4. Selected-stage editing should become more progressive

The selected stage editor should not feel like opening the entire universe of
that stage at once.

Direction:

- fewer always-open sections
- shorter helper copy
- stronger disclosure for secondary sections
- one clearly dominant subsection at a time when appropriate

### 5. Density should respond to workflow complexity

Introduce workflow-aware compression rules.

Target bands:

- `1–3 stages`: slightly richer row summaries are acceptable
- `4–8 stages`: compact non-selected rows aggressively
- `8+ stages` or branching-heavy workflows: stronger compression and more
  reliance on structure over per-row detail

This adaptation should come from the same authoring pipeline, not a second UI.

### 6. Focused secondary surfaces remain focused

Do not regress map, settings, or artifact editing back into sprawling slabs.

This pass is about reducing density without losing the focused-surface model.

## Proposed UX Changes

### A. Stage row redesign

Replace the current row emphasis with a quieter structure-first row.

For each non-selected stage:

- primary line: stage name
- secondary line: compact owner/assignment summary
- row actions: visually minimized
- insertion affordance: lightweight `+` between rows or attached to row edges

For the selected stage:

- keep inline editor
- keep `Done`
- keep local destructive action
- reduce surrounding row noise

### B. Insertion redesign

Replace visually heavy repeated `Add below` buttons with one of:

1. inline `+` bars between rows
2. row-edge insertion controls
3. hover/focus-visible insertion affordances on desktop plus always-visible
   compact affordance on mobile

Product rule:

- insertion remains local
- insertion remains structurally obvious
- insertion should no longer dominate the stack visually

### C. Editor section hierarchy

Rebalance the selected stage editor.

Target order:

1. step basics
2. assignment
3. next-step / routing
4. instructions
5. inputs and outputs

But not all with equal weight.

Rules:

- basics and assignment remain easiest to access
- routing stays compact until needed
- instructions and artifacts use shorter copy and stronger disclosure
- helper text should explain only what the user cannot infer from the label

### D. Adaptive row density

Add a workflow-complexity presentation mode derived from existing document
state.

Inputs can include:

- number of stages
- number of segments
- whether branching exists
- whether a stage is selected

Outputs:

- row summary verbosity
- insertion affordance style
- default map emphasis
- default section disclosure strength

This should be derived from current document state and reused by the same
renderer, not implemented as a second authoring view.

### E. Mobile task shaping

Keep the same model, but reduce simultaneity.

Target mobile behavior:

- the stage stack stays concise
- opening a stage emphasizes one editing task at a time
- insertion remains lightweight
- secondary surfaces remain focused
- long helper prose is reduced further than desktop

### F. Copy simplification

Audit and cut copy that is currently explanatory but expensive.

Keep:

- labels that define meaning
- warnings that prevent mistakes
- short contextual status text

Cut or shorten:

- repeated descriptive paragraphs
- explanatory lines the user already learned from prior interactions
- duplicate summaries across row and editor

## Implementation Strategy

### Phase 1. Add a reusable density model

Primary file:

- [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)

Work:

- derive a workflow presentation mode from existing workflow data
- expose small reusable booleans/tokens such as:
  - compact row mode
  - compact summary mode
  - large workflow mode
  - branching-present mode

Do not create a second render path.

### Phase 2. Redesign row summaries

In [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js):

- reduce row metadata duplication
- keep one short summary line
- lower the visual weight of non-selected controls
- ensure selected row/editor remains the clear focal point

In [main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css):

- reduce row chrome density
- improve spacing hierarchy
- make non-selected rows quieter without harming legibility

### Phase 3. Replace `Add below` presentation

In the existing insertion path:

- keep current insertion semantics
- replace repeated button-heavy presentation with compact insertion controls
- preserve testable accessible names

Do not create a second insertion code path.

### Phase 4. Rebalance editor section disclosure

In the selected stage editor:

- reduce always-open sections
- reduce helper copy
- ensure the most common tasks are visually primary
- keep artifacts and routing reachable without dominating

### Phase 5. Apply mobile-specific compression

Using the same renderer:

- reduce visible non-selected metadata further on mobile
- simplify section presentation
- ensure insertion and close behavior remain obvious with less chrome

### Phase 6. Audit text and repeated summaries

Cut duplicated explanatory text in:

- stage rows
- editor sections
- artifact surfaces
- assignment helper blocks

### Phase 7. Re-run scenario and breadth verification

After implementation:

- rerun all authoring/rehearsal/execution scenarios
- rerun the breadth audit
- visually inspect the Software Engineering template as the primary scaling
  reference

## Scenario Assertion Contract For This Pass

The following are now required on top of the existing functional scenario bar.

### Software Engineering

Must prove:

- non-selected stage rows are compact and scannable
- insertion does not feel like repeated command buttons
- selected-stage editing is the clear focal point
- the user can move through the 7-stage flow without excessive repeated UI
  text

### Document Approval

Must prove:

- smaller workflows still feel simple, not over-abstracted
- insertion and editing remain obvious with the lighter controls

### Data Analysis / Reporting

Must prove:

- artifact-heavy workflows remain readable after density reduction
- compact rows do not obscure artifact-bearing stages

### Meta Protocol Assistant

Must prove:

- compositional flows with custom skills still read clearly
- compact rows still communicate assignment and purpose sufficiently

## Acceptance Criteria

This pass is complete only when all of the following are true:

1. `Done` remains explicit and locally accessible.
2. `Add below` has been replaced or visually transformed into a lighter,
   standard insertion affordance without changing insertion semantics.
3. Non-selected stages are materially quieter than the selected stage.
4. The selected stage editor exposes less simultaneous weight than today.
5. The UI adapts its density based on workflow size and complexity.
6. Desktop and mobile both feel lighter without introducing a second authoring
   model.
7. The Software Engineering workflow is visibly easier to scan and edit than
   the current build.
8. The existing focused-surface model for map, settings, and artifacts remains
   intact.
9. Scenario tests and live audit remain green after the hierarchy pass.

## Verification Plan

The same test philosophy stays in force:

- scenario specs are the release bar
- exhaustive audit is breadth validation
- every reported density or interaction regression should become a targeted
  scenario or visual audit expectation

Minimum verification:

- `pytest` contract suite
- live `protocol-ui.spec.js`
- live execution smoke
- live exhaustive audit with 500+ screenshots
- live visual inspection of Software Engineering on desktop and mobile

## Regression Rules

1. No duplicate authoring pipelines.
2. No return to heavy slab stacking.
3. No icon-only ambiguity at the primary close point.
4. No separate “compact mode” implementation path; density must be derived from
   the same workflow renderer.
5. Insertion remains local and explicit even if its chrome becomes lighter.
6. Artifact editing remains stage-contextual for normal authoring.
