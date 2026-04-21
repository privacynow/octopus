**Protocol UX Fix Plan**

## Product Direction

Protocol authoring should now be treated as a single progressive workflow editor.

Primary surface:
- section and stage stack
- one inline expanded editor at a time
- local stage insertion controls
- local routing controls inside the expanded stage

Secondary surface:
- optional workflow map
- opened on demand
- reference only, not the default dominant authoring surface

This replaces the older split model of:
- stage list / workflow surface on one side
- detached editor column on the other

The goal is consolidation:
- one stage stack
- one stage editor implementation
- one insertion model
- one assignment editor
- one mobile/desktop interaction model

## Current Baseline

Current repo branch:
- `feature/protocol`

Current deployed target:
- `http://127.0.0.1:8787`
- deployed through `/Users/tinker/octopus` only

Current live verification status before this refactor:
- protocol authoring live suite passes
- contract suite passes
- live audit artifact set already exceeds 500 captures

## What Is Finished

These items are implemented and should be preserved during the refactor:

- step-first authoring is the main path
- `Create new role…` is inline in step creation
- assignment uses one combined editor with:
  - `Required skill`
  - `Pinned agent`
- choosing skill then agent and agent then skill converges to the same selector model
- `preferred_agent_id` is preserved through the normal editor path
- refresh no longer drops the workflow surface
- the workflow map is hidden by default and can be shown on demand
- the misleading top-level `Add route` path is gone
- branch editing stays inside routing
- stage insertion works in the middle of an existing workflow
- live skill-assigned and agent-assigned execution has been exercised through the runs surface

## What Must Be Removed

These are no longer acceptable end states:

- detached right-hand step editor as the primary editing path
- split “select on the left, edit somewhere else” authoring
- an always-prominent workflow map
- duplicated insertion semantics that depend on invisible anchors

## Remaining Verified Product Defects

### 1. Stage list and editor are still disjoint

Current state:
- stage selection happens in the workflow outline / canvas shell
- editing happens in a detached details column
- the map used to visually mask this split
- with the map demoted, the separation is now exposed as unnecessary friction

Why this matters:
- the thing being edited is not visually the thing the user just selected
- insertion feels indirect instead of local
- mobile and desktop still inherit a split-shell architecture

Fix direction:
- make the section/stage stack the primary surface
- expand the selected stage editor inline under the selected stage
- keep only one expanded stage editor at a time
- remove the detached details-column authoring path

### 2. Add-stage actions are still too indirect

Current state:
- insertion logic works
- toolbar and selection-based actions still carry too much anchor inference

Why this matters:
- authors expect “Add stage” to mean “add here”
- insertion should be local to the current stage or route, not inferred from distant context

Fix direction:
- stage rows get local `Add below`
- route rows keep `Insert step here`
- section rows can expose `Add below section`
- remove dependence on a detached toolbar for normal stage growth

### 3. Mobile authoring is still too dense

Current state:
- assignment/editor behavior is materially improved
- the map is no longer always open

What is still wrong:
- the overall page still feels too stacked
- the progressive authoring surface is not yet the primary shell

Fix direction:
- use the same inline stage stack on mobile
- keep only one expanded editor visible
- keep map secondary and on demand
- collapse secondary editor sections by default on compact widths

### 4. Desktop focused-step editing is still heavier than it should be

Current state:
- assignment duplication is reduced
- map prominence is reduced

What is still wrong:
- detached editor structure still adds cognitive weight
- hero metadata and explanatory copy are still heavier than necessary

Fix direction:
- once the editor is inline, compress hero/meta copy
- keep short summaries and controls primary
- remove text that existed mainly to explain the old split model

### 5. Mobile runs is still too dense

Current state:
- run list/detail works
- execution can be inspected on mobile

What is still wrong:
- filter controls and cards are crowded
- the page still reads like a compressed desktop surface

Fix direction:
- simplify compact filters
- reduce card density
- keep detail secondary until selected

## Verification Defect

### Live exhaustive audit bookkeeping is not clean

Current state:
- the broad live audit produces the screenshot matrix
- authoring and viewport slices complete
- execution and runs captures are present in the artifact set

What is still wrong:
- `.tmp/playwright/live-exhaustive-audit.spec.js` does not consistently terminate cleanly after the execution slice even though it produces the artifacts

Fix direction:
- isolate execution from the main authoring matrix
- make the audit persist findings per completed slice

## Sequencing From Here

The correct order is now:

1. progressive inline stage/editor surface
2. local add-stage / insert semantics in that surface
3. compact/mobile behavior on the same progressive stack
4. desktop text compression inside the inline editor
5. mobile runs density
6. live exhaustive audit harness cleanup

This order matters.

Do not spend more time polishing the detached editor shell.
Replace it with the inline progressive surface first, then tune density on top of the correct structure.
