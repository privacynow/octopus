**Protocol UX Fix Plan**

## Current State

Protocol authoring now ships as a single progressive workflow editor on the live Octopus deployment.

Primary surface:
- section and stage stack
- one inline expanded editor at a time
- local `Add below` on the selected stage only
- local route insertion from the routing list
- workflow map hidden by default and opened on demand

Secondary surface:
- workflow map as optional reference only
- mobile runs list without the empty detail placeholder

This replaces the old split model of:
- detached editor column
- always-prominent map
- duplicated add-stage controls across every row and section

## What Is Verified Done

These are implemented and verified on the deployed Octopus build:

- step-first authoring is the main path
- `Create new role…` works inline during step creation
- assignment uses one combined editor with:
  - `Required skill`
  - `Pinned agent`
- choosing skill then agent and agent then skill converges to the same selector model
- `preferred_agent_id` survives the normal editor path
- refresh no longer drops the workflow surface
- the workflow map is hidden by default and can be shown on demand
- the misleading top-level `Add route` path is gone
- branch editing stays inside routing
- stage insertion works in the middle of an existing workflow
- stage deletion works from the inline editor
- selected-stage insertion is local instead of being offered on every stage and section row
- section headers no longer repeat the same stage title when the section and first stage are the same label
- empty assignment-context panels are compact instead of rendering large empty boxes
- mobile runs no longer render an empty detail panel before a run is selected
- live skill-assigned and agent-assigned execution both complete through the runs surface
- live exhaustive audit now completes cleanly

## Live Verification Summary

Deployed target:
- `http://127.0.0.1:8787`
- deployed through `/Users/tinker/octopus` only

Current verification status:
- contract suite passes
- protocol authoring live suite passes
- capture suite passes
- live execution smoke passes
- exhaustive live audit passes

Most recent exhaustive audit:
- 559 screenshots in `.tmp/playwright/live-audit`
- blank draft lifecycle covered
- Software Engineering template covered on desktop/tablet/mobile
- Document Approval template covered on desktop/tablet/mobile
- insert/delete/mutation path covered
- runs surface covered on desktop/tablet/mobile
- agent and skill execution verified against the live registry

## No Verified Blocking Defects Remain

The current exhaustive live pass did not leave any open blocking protocol-authoring or protocol-run defects.

That means there are no currently verified issues in this file that block:
- creating a protocol from scratch
- adding stages
- deleting stages
- assigning by skill
- assigning by agent
- inserting between stages
- publishing
- rehearsing
- executing through the live registry
- reviewing runs on desktop or mobile

## Non-Blocking Refinements If Revisited Later

These are not blockers from the current live pass, but they are the only remaining areas worth tightening if the surface is revisited:

1. Compact mobile runs filters further.
- The runs list is functional and no longer shows an empty detail panel, but the segmented controls and status chips still consume a lot of vertical space on very narrow screens.

2. Compress workflow header copy slightly more.
- The progressive stack is readable now, but the view-bar copy could be shortened further if more vertical headroom is needed.

3. Reduce secondary copy in the assignment editor when there are no live matches.
- The empty-state assignment context is much smaller than before, but it could still be reduced to an even terser note if future mobile tightening is needed.

## Cleanup Rule

Do not reintroduce:
- detached protocol step editors
- always-visible workflow maps
- duplicate add-stage controls on every row
- separate assignment surfaces
- participant-first authoring flows

Any future changes should extend the current progressive stack in place.
