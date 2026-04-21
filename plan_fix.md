**Protocol UX Fix Plan**

## Current Status

This file is the current source of truth. It supersedes earlier plans that assumed assignment was still participant-owned or that the main remaining work was only density tuning.

Current live/deployed baseline during this update:

- repo branch: `feature/protocol`
- latest implemented assignment commit in repo/octopus flow: `447b36a`
- live target for verification: `http://127.0.0.1:8787`

## What Is Actually Finished

These items are working and should not be replanned as if they were still missing:

- step-first authoring exists
- inline `Create new role…` exists
- stage selectors are already canonical in the product/runtime path
- skill dropdowns and agent dropdowns are real catalog-backed controls
- refresh no longer drops the overview graph
- the workflow map exists and is useful as reference context
- skill selection can surface matching agents
- agent selection can surface that agent’s advertised skills
- live protocol authoring Playwright coverage passes on the current deployed build

## What Is Not Finished

The assignment editor is still conceptually wrong.

### Primary open defect

The assignment UX is still strategy-first and asymmetrical:

- choose `skill`, then choose an agent:
  - the UI can still feel like it changes shape or “resets”
- choose `agent`, then choose a skill:
  - the UI reorients around the other choice instead of preserving one stable surface
- the same authored intent is represented through different editor states depending on interaction order

This is the main remaining protocol-authoring defect.

### Secondary open defects

These are still real, but they are sequenced after the assignment editor fix:

1. the workflow map is still too prominent by default and competes with the primary editor
2. mobile authoring is still too dense
3. mobile runs is still too dense
4. desktop focused-step editing is still text-heavy

## Correct Product Model

The normal assignment editor should not ask “what strategy?” first.

It should expose two peer controls:

1. `Required skill`
2. `Pinned agent`

Each is optional individually, but at least one must be set.

The editor must behave the same regardless of interaction order:

- choose skill only
- choose skill then agent
- choose agent only
- choose agent then skill
- clear skill
- clear agent

The layout must stay stable across all of those transitions.

The workflow map should also stop acting like the always-primary surface.

- the primary authoring surface is the editor/outline flow
- the workflow map remains available as a reference workspace
- on desktop it should be easy to show, hide, or expand without losing state
- on mobile it should not be permanently visible by default

The map stays in the product, but it should no longer dominate the screen before the user asks for it.

## Canonical Selector Mapping

Keep one canonical selector model. Do not add another layer.

Map UI state to the existing selector model like this:

- no skill + no agent
  - invalid
- skill + no agent
  - `TargetSelector(kind="skill", value=skill)`
- no skill + agent
  - `TargetSelector(kind="agent", value=agent)`
- skill + agent
  - `TargetSelector(kind="skill", value=skill, preferred_agent_id=agent)`

This uses the existing runtime/storage model in place.

## Important Runtime Semantics

Current runtime semantics already matter here:

- `skill` only
  - dynamic among matching connected agents
- `agent` only
  - pinned to that agent
- `skill + preferred_agent_id`
  - pinned to that preferred matching agent

This is not currently a soft preference. It is effectively a hard pin inside the skill selector path.

That behavior is acceptable for this fix because the UI language is “pin,” not “prefer if available.”

Do not change runtime semantics in this pass.

## What To Remove From The UX

The current strategy-first framing is the source of confusion.

Remove from the normal authoring flow:

- the `Strategy` dropdown as the primary control
- mode-specific editor shapes that switch between “agent mode” and “skill mode”
- helper sections that become the effective primary editor after a choice
- an always-prominent workflow map that competes with the right-hand editor during ordinary step editing

Keep the advanced selector path, but demote it sharply.

## Advanced Selector Decision

`Runtime role tag or custom selector` is not part of the normal authoring path.

Keep it only because it still covers cases the normal editor does not:

- runtime role tags
- custom selector values not represented by normal catalogs
- internal/system paths

But:

- keep it collapsed
- keep it visually separate
- do not let it compete with the normal agent/skill editor

## Implementation Plan

### Phase 1. Replace strategy-first editor with a combined editor

Primary file:

- `/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js`

Actions:

- remove `Strategy` as the primary visible authoring choice
- render one stable assignment surface with:
  - `Required skill`
  - `Pinned agent`
- keep both controls visible and editable at all times
- derive the selector from those two fields instead of using `selector_kind` as the UI driver

Acceptance for this phase:

- choosing skill then agent does not change the editor shape
- choosing agent then skill does not change the editor shape
- both values remain visible after each interaction

### Phase 2. Normalize editor state around two fields

Refactor editor state so the UI works from:

- `selectedSkill`
- `selectedAgent`

Then derive the canonical selector only at commit boundaries.

For existing selectors:

- `kind=skill`
  - `selectedSkill = selector.value`
  - `selectedAgent = selector.preferred_agent_id || ''`
- `kind=agent`
  - `selectedSkill = ''`
  - `selectedAgent = selector.value`
- advanced/custom
  - normal editor empty
  - advanced editor owns that state

Acceptance for this phase:

- save/reload produces the same visible editor state
- no order-dependent reorientation remains

### Phase 3. Rework the contextual assist sections

Reuse existing helpers instead of inventing new paths:

- `_agentsAdvertisingSkill(...)`
- `_selectorAgentSkills(...)`
- `_selectorAgentRecord(...)`

Rules:

- if a skill is selected, show matching agents context
- if an agent is selected, show that agent’s skills context
- if both are selected, show both contexts
- if only one is selected, show only the relevant context

The context sections must become pure aids to the two-field editor, not alternate modes.

Acceptance for this phase:

- pills and dropdowns update the same underlying field values
- no helper section causes the editor to switch modes

### Phase 4. Keep one commit path only

Refactor existing commit/update logic so all assignment updates go through one derivation helper.

Areas to update in:

- `/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js`

Specifically:

- pending-stage creation path
- existing-stage edit path
- summary rendering path
- save/reload hydration path

Rules:

- no separate save path for “skill-first”
- no separate save path for “agent-first”
- no temporary UI-only state that disagrees with the stored selector

Acceptance for this phase:

- editing an existing step preserves the combined selection across save/reload
- creating a new step preserves the combined selection across create/save/reload

### Phase 5. Tighten validation and copy

Validation should describe the combined editor, not selector internals.

Required copy behavior:

- no skill + no agent:
  - “Choose a required skill, a pinned agent, or both.”
- skill + agent where agent does not advertise skill:
  - explicit mismatch warning/error
- skill only:
  - dynamic language
- skill + agent:
  - pinned language

Copy changes:

- remove primary “strategy” language from the normal flow
- keep advanced selector wording separate and explicit

Acceptance for this phase:

- users understand the combined editor without having to infer internal selector kinds

### Phase 6. Demote map prominence without removing it

This is a layout/product step, not a selector-model step.

Goal:

- keep the workflow map
- stop making it the default dominant surface during ordinary editing

Desktop target:

- outline + editor remain primary
- map is available on demand or in a resizable/collapsible region
- opening the map preserves selection and viewport state

Mobile target:

- map is not always visible by default
- it is available via an explicit `Show workflow map` action or equivalent
- it opens in a composition that does not bury the editor or outline

Rules:

- do not remove the map
- do not create a second authoring workflow
- do not fork semantics between desktop and mobile
- map visibility is a presentation/layout decision only

Acceptance for this phase:

- the editor no longer competes with a permanently dominant map during normal editing
- the map is still one action away and preserves state when shown
- desktop and mobile both treat the map as reference context unless the user explicitly opens it

### Phase 7. Verify execution, not just editing

Live verification must include actual execution against Octopus:

1. agent only
2. skill only
3. skill + pinned agent

Verify:

- saved selector shape
- successful dispatch
- expected target resolution behavior

Do not stop at UI assertions only.

### Phase 8. Then address density

Only after the assignment editor is stable and symmetric and the map no longer dominates the workspace:

1. reduce mobile authoring density
2. reduce mobile runs density
3. reduce desktop focused-step text density

That work stays in scope, but it is sequenced after:

- the assignment-model fix
- the map-prominence fix

because those two product issues currently shape the page more than pure copy/spacing cleanup does.

## Tests Required

### Local

- `/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_contract.py`
- `/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_kit_contract.py`
- `/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui.spec.js`

### Live Octopus

Always test against:

- `http://127.0.0.1:8787`

Required live flows:

1. blank draft
   - choose skill only
   - choose agent only
   - choose skill then agent
   - choose agent then skill
   - open and close the workflow map
2. Software Engineering template
   - edit existing assignment both ways
   - verify editor-first layout with map hidden and visible
3. actual execution
   - published run with agent only
   - published run with skill only
   - published run with skill + pinned agent
4. mobile
   - edit without map shown by default
   - explicitly open the map and verify it is usable and dismissible

## Deployment Rule

Do not test a local-only build and infer live behavior.

Required order:

1. commit in this repo
2. push `feature/protocol`
3. `git -C /Users/tinker/octopus fetch origin feature/protocol`
4. `git -C /Users/tinker/octopus pull --ff-only`
5. `./octopus redeploy registry --yes`
6. test live on `http://127.0.0.1:8787`

## Definition Of Done

This assignment issue is done only when:

- there is one stable assignment editor
- the editor uses two peer controls:
  - required skill
  - pinned agent
- picking values in either order leads to the same visible state
- save and reload preserve the same visible state
- the workflow map is available but no longer the default dominant editing surface
- opening and closing the map preserves useful state instead of feeling like a separate product
- live execution works for:
  - skill only
  - agent only
  - skill + pinned agent
- advanced selector remains available but is clearly secondary

## Superseded Direction

The older direction in previous versions of this file that framed the next work as:

- participant-owned assignment migration
- stage-owned migration as if not yet implemented
- density-only cleanup as the main remaining work

is superseded.

The current main remaining fixes are:

1. the combined, symmetric assignment editor described above
2. demoting workflow-map prominence so the editor becomes the clear primary workspace
