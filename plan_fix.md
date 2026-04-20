**Protocol Workspace Finalization Plan**

This plan is grounded in fresh live captures from the exact deployed protocol page under review, not old artifacts:

- `/ui/protocols?panel=protocol&protocol_id=a5ea2060a09041c1a18f92f220e1dade`
- desktop wide
- mobile compact

Current state is directionally better than the old multi-surface product, but it still fails on:

- desktop density
- mobile composition
- duplicated information across canvas, outline, and inspector
- one broken authoring path (`Add route` on blank draft)

The fix is not another visualization mode. The fix is to make the existing single-canvas architecture strict about information ownership and shell behavior.

## 1. Product Contract

The shipped authoring product remains:

1. **Workflow canvas**
   The primary workflow-reading surface.
2. **Inspector**
   The only editing surface for protocol settings, stages, participants, routes, artifacts, and rehearsal state.
3. **Synced outline**
   Structural navigation companion to the same scene and selection model.

The shipped authoring product is **not**:

- a separate overview surface
- a separate detail surface
- a separate topology surface
- a separate full-graph product mode

Internal distinctions may exist for:

- selection
- camera state
- level-of-detail
- compact vs wide composition

Those distinctions must not re-emerge as parallel user-facing products.

## 2. Source Of Truth Rules

### 2.1 Visual review provenance

No visual conclusion is valid unless it comes from:

- a fresh capture
- the exact live URL or exact authored flow under review
- a named viewport

Old `.tmp/playwright` artifacts are not evidence unless they were generated in the same step and their provenance is explicit.

### 2.2 Information ownership

Every fact shown in the workflow UI must have one primary owner.

**Canvas owns**

- spatial order
- mainline structure
- branch/finish affordances
- local route context when focused

**Canvas does not own**

- long assignment prose
- selector explanation
- paragraph summaries
- inspector-style footnotes

**Outline owns**

- section / step navigation
- same order as the scene
- same labels as the scene
- selection and keyboard traversal

**Outline does not own**

- participant/skill prose
- route explanation
- another narrative summary of the workflow

**Inspector owns**

- protocol settings
- participant assignment
- stage editing
- route editing
- artifacts
- rehearsal detail

### 2.3 Mobile and desktop semantics

Desktop and mobile share:

- one scene model
- one selection model
- one inspector model

They may differ in composition:

- desktop: canvas-primary
- compact/mobile: outline-primary with focused canvas support

That is allowed because it is one product with one model, not two products.

## 3. Actual Problems In The Current Code

### 3.1 Desktop density

In `octopus_registry/ui/js/components/protocol-workspace.js` and `octopus_registry/ui/js/helpers/kit.js`:

- story nodes still carry `label + meta + secondary`
- outline rows still carry section meta and child meta
- inspector still defaults to protocol settings when nothing is selected
- shell width is split too evenly between outline, canvas, and right column

Result:

- graph boxes are text-heavy and ugly
- fit-all canvas shrinks meaningful labels too much
- outline duplicates what the graph already says
- protocol settings steal width from the workflow

### 3.2 Mobile composition

In `octopus_registry/ui/css/main.css`:

- compact layout stacks canvas above outline and details
- compact graph host is still a large first block
- inspector is still an in-flow column, not a contextual compact editor

Result:

- graph-first on a narrow screen
- long vertical scroll before meaningful editing
- settings dumped into the same scroll path as the workflow

### 3.3 Broken authoring flow

`Add route` on a blank draft still does not reliably transition into the route editor path. This blocks final acceptance and deployment.

## 4. Non-Negotiable Decisions

1. Do not add new view modes, new tabs, or new explanation surfaces.
2. Reduce information payload before styling boxes.
3. Make the canvas lighter at fit-all, not richer.
4. Make the outline structural, not narrative.
5. Move protocol settings out of the default right rail when the workflow itself is the main task.
6. On compact widths, selection/structure comes first; fit-all graph does not.
7. Fix route creation before final push/pull/deploy.
8. Delete dead CSS, dead tests, dead helpers, and stale capture utilities as the new path stabilizes.

## 5. Detailed Execution Plan

### Phase 0: Review discipline and capture harness

- Add one explicit capture path for exact live URLs under review.
- Use that harness for desktop wide, comfortable, and compact viewports.
- Delete temporary capture helpers after the final pass if they are not part of the permanent test suite.

Acceptance:

- every screenshot used for judgment names the exact URL and viewport it came from

### Phase 1: Shrink canvas label payloads

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- `octopus_registry/ui/js/helpers/kit.js`

Changes:

- rewrite story-scene node data so fit-all nodes only carry:
  - title
  - one compact metric line at most
- remove `secondary` prose from story segments
- reduce focused-scene labels to what is necessary for local context
- keep assignment and detailed summaries in the inspector, not the graph
- update Cytoscape node sizing to match the lighter payload instead of the old paragraph-sized boxes

Acceptance:

- fit-all nodes show at most two short visible text lines
- graph remains readable without the inspector open

### Phase 2: Compress the outline into a skeleton

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- `octopus_registry/ui/js/helpers/kit.js`
- `octopus_registry/ui/css/main.css`

Changes:

- section rows show:
  - section name
  - count / compact status only
- child rows show:
  - step name
  - only the smallest necessary subtype/status, if any
- remove repeated participant/skill sentences from outline meta
- only show full child lists where selection/expansion justifies it

Acceptance:

- outline reads as navigation, not as a second summary panel
- section and child rows are scannable at a glance

### Phase 3: Reassign protocol settings to the inspector

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- `tests/e2e/playwright/protocol-ui.spec.js`
- `tests/e2e/playwright/protocol-ui-capture.spec.js`

Changes:

- stop showing protocol description/policies as the default details panel when nothing is selected
- use the existing lifecycle `Protocol` action to open protocol settings in the inspector
- when no specific entity is selected, keep the right column minimal rather than filling it with settings content

Acceptance:

- desktop workflow screen does not permanently sacrifice width to protocol settings
- protocol settings remain accessible, but only when explicitly opened

### Phase 4: Rebalance the desktop shell

Files:

- `octopus_registry/ui/css/main.css`

Changes:

- make the canvas column dominant
- narrow the outline column
- keep the inspector contextual and secondary
- add an intermediate “comfortable” layout tier so mid-width desktop does not fall back to an awkward stacked experience

Acceptance:

- on common desktop widths, the graph receives substantially more width than it does now
- outline and inspector no longer crowd the main canvas

### Phase 5: Recompose compact/mobile layout

Files:

- `octopus_registry/ui/css/main.css`
- `octopus_registry/ui/js/components/protocol-workspace.js`

Changes:

- compact layout becomes selection-first:
  - outline first
  - focused canvas second
  - inspector/settings contextual, not a permanent long block
- do not lead compact layout with a giant fit-all graph
- protocol settings open in the inspector path rather than living in the main scroll
- ensure compact shell uses the existing sidebar drawer behavior correctly and does not waste workflow width

Acceptance:

- mobile first meaningful action is structural selection, not panning a tiny graph
- compact layout no longer stacks “graph wallpaper + long outline + long settings form” in one scroll

### Phase 6: Fix route creation

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- `tests/e2e/playwright/helpers/protocol-helpers.js`
- `tests/e2e/playwright/protocol-ui.spec.js`
- `tests/e2e/playwright/protocol-ui-capture.spec.js`

Changes:

- make `Add route` deterministically switch to `create-route`
- ensure the route editor panel renders and remains visible after selection
- update tests to exercise the supported control path rather than a brittle stale assumption

Acceptance:

- blank-draft participant-first and step-first flow passes end-to-end

### Phase 7: Styling pass only after structure is fixed

Files:

- `octopus_registry/ui/css/main.css`
- `octopus_registry/ui/js/helpers/kit.js`

Changes:

- lighten node visual weight
- reduce border heaviness
- improve spacing inside outline and canvas
- tune typography hierarchy for compact summaries

Acceptance:

- boxes look lighter because they carry less and are styled for the lighter payload

### Phase 8: Dead-path cleanup

Files:

- protocol workspace JS/CSS/tests
- temporary capture utilities

Changes:

- delete stale tests that encode old dense layout assumptions
- delete temporary capture/spec helpers not needed permanently
- remove dead CSS rules replaced by the final composition
- keep one obvious path for workflow reading and one obvious path for editing

Acceptance:

- no dead alternate layout/test path remains in the repo

## 6. Testing Plan

### Functional

Required:

- `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_registry_ui_kit_contract.py -q`
- `npx playwright test protocol-ui.spec.js --config=../../tests/e2e/playwright.config.js`
- `npx playwright test protocol-ui-capture.spec.js --config=../../tests/e2e/playwright.config.js`

### Visual

For each major phase, capture:

- exact live URL under review
- desktop wide
- desktop comfortable
- compact/mobile

Required review targets:

- Software Engineering draft
- blank draft authoring
- Document Approval draft

### Hard review metrics

- fit-all graph nodes: max two short text lines
- outline rows: max two lines collapsed
- protocol settings are not permanently open by default beside the workflow
- compact/mobile first workflow action is structural selection, not graph panning
- compact/mobile no longer shows graph-first stacked authoring
- route creation works

## 7. Ship Blockers

Do not push/pull/deploy if any of these remain true:

- canvas nodes still carry dense multi-line summaries in fit-all view
- outline still duplicates participant/skill narrative
- protocol settings still occupy the default workflow side rail
- compact/mobile remains graph-first and stacked
- route creation still fails
- visual conclusions are based on stale artifacts

## 8. Execution Order

1. Update the plan and lock review discipline.
2. Fix route creation if it blocks reliable UI verification.
3. Reduce canvas label payloads.
4. Compress the outline.
5. Move protocol settings out of the default right rail.
6. Rebalance desktop shell.
7. Recompose compact/mobile layout.
8. Run the styling pass.
9. Remove dead code/tests/helpers.
10. Re-run full functional and live visual review.
11. Only then push, fast-forward `/Users/tinker/octopus`, and redeploy.
