**Protocol UX Fix Plan**

## Current Baseline

This file is the current defect and cleanup ledger for protocol authoring and run inspection.

Current repo branch:
- `feature/protocol`

Current deployed target:
- `http://127.0.0.1:8787`
- deployed through `/Users/tinker/octopus` only

Current live verification status on the deployed build:
- protocol authoring live suite passes:
  - blank draft
  - software engineering desktop
  - document approval desktop
  - software engineering mobile
  - draft conflict shell
- contract suite passes:
  - `tests/test_registry_ui_contract.py`
  - `tests/test_registry_ui_kit_contract.py`
- live audit artifact set contains more than 500 captures:
  - current `live-audit` directory contains 671 files

## What Is Finished

These items are implemented and should not be replanned as open:

- step-first authoring is the main path
- `Create new role…` is inline in step creation
- assignment uses one combined editor with:
  - `Required skill`
  - `Pinned agent`
- choosing skill then agent and agent then skill now converge to the same stored selector model
- `preferred_agent_id` is preserved through the normal editor path
- refresh no longer drops the workflow surface
- the workflow map is hidden by default and can be shown on demand
- the workflow map toggle works live
- the misleading top-level `Add route` path is gone
- branch editing stays inside routing
- stage insertion works in the middle of an existing workflow
- live skill-assigned and agent-assigned protocol execution has been exercised through the runs surface

## What Was Removed

These older UX paths are no longer the product direction:

- assignment as a strategy-first editor
- participant-first authoring
- an always-prominent workflow map
- duplicate contextual dropdowns under the main assignment controls

## Remaining Verified Product Defects

These are the live issues still worth fixing. They are smaller than the earlier structural problems, but they are real.

### 1. Mobile authoring is still too dense

Current state:
- the selected-step editor is first, which is correct
- routing, instructions, artifacts, and advanced are now collapsed on compact screens
- the workflow canvas/map is no longer permanently expanded

What is still wrong:
- the page is still long on a phone-sized screen
- the assignment context cards still consume a lot of vertical space
- the workflow section at the bottom still adds cognitive weight even when the user is editing one step

Fix direction:
- compress assignment context copy further if possible
- consider collapsing the workflow section itself on compact screens when a stage is selected
- keep only one clear primary task visible on mobile at a time

### 2. Mobile runs is still too dense

Current state:
- run list/detail works
- execution can be inspected on mobile

What is still wrong:
- filter controls and status chips are crowded
- list items are visually dense
- the page still feels like a desktop list compressed into a narrow width

Fix direction:
- simplify filter presentation on compact screens
- reduce visual weight of run cards
- keep detail secondary until a run is explicitly selected

### 3. Desktop focused-step editing is still heavier than it should be

Current state:
- the map is demoted correctly
- the inspector is primary
- assignment duplication is materially reduced

What is still wrong:
- hero metadata plus assignment context still produce more reading than necessary
- the assignment context sections are better, but still text-heavy

Fix direction:
- keep shrinking inspector prose
- bias toward short summaries and selectable controls over explanatory paragraphs

## Verification Defect

### Live exhaustive audit bookkeeping is not clean

Current state:
- the broad live audit produces the screenshot matrix
- authoring and viewport slices complete
- execution and runs captures are present in the artifact set

What is still wrong:
- `.tmp/playwright/live-exhaustive-audit.spec.js` does not consistently terminate cleanly after the execution slice, even though it produces the artifacts
- that is verification debt, not product UX debt

Fix direction:
- isolate the execution slice from the authoring matrix
- make the audit script persist findings once per completed slice instead of only at the end

## Sequencing From Here

If work continues, the correct order is:

1. mobile authoring density
2. mobile runs density
3. desktop inspector text compression
4. live exhaustive audit harness cleanup

That order keeps product issues ahead of verification-tool cleanup.
