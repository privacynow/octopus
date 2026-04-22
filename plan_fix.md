**Protocol UX Verified State**

## Status

The current standard protocol-authoring surface is verified live on Octopus.

This file is no longer the active implementation plan for the density pass.
It is the execution record and regression bar for the current live state.

## What Shipped

### 1. Density and hierarchy pass

The stage stack now scales more cleanly with workflow size.

- non-selected rows are quieter
- row summaries compress as workflows grow
- the selected stage stays visually primary
- the editor uses the same authoring pipeline; there is no parallel compact
  renderer

### 2. Lighter insertion affordance

The old repeated `Add below` command button is no longer the normal stage-stack
control.

- insertion is now exposed through a lighter inline `+ Add step` affordance
- insertion semantics are unchanged
- accessible labeling still uses `Add step below …`

### 3. Progressive editor polish

The selected stage editor is less verbose.

- assignment copy is shorter
- routing copy is shorter
- artifact copy is shorter
- dense layouts compress gaps and card spacing without changing the data model

### 4. Custom skill draft persistence

The skills surface now keeps a newly created custom draft selected immediately.

- creating a custom draft no longer loses selection during catalog refresh
- the meta assistant scenario now works through the UI/API path again
- the fix extends the existing skill list/selection pipeline instead of adding
  a second path

### 5. Audit harness alignment

The exhaustive live audit now uses the current insertion affordance instead of
the deleted `Add below` button contract.

## Verified Standard Surface

### Authoring

Verified on the live Octopus deployment:

- create blank draft
- add first step
- create new role inline
- assign by skill
- assign by specific agent
- pin a matching agent
- add step after current step
- insert between existing stages
- delete step
- edit artifacts on a non-first stage without losing selection
- publish
- rehearse
- archive

### Templates

Verified live:

- Software Engineering
- Document Approval
- Data Analysis / Reporting
- Meta Protocol Assistant

### Focused surfaces

Verified live:

- workflow map opens on demand
- protocol settings remain a focused secondary surface
- artifact editing remains in workflow context
- `Done` closes the selected stage editor locally

### Standard-path restrictions

Verified on the standard authoring path:

- no `Custom runtime selector`
- no standard-path `Advanced` editor
- no standard-path editing of `stage_key`
- no standard-path editing of `max_rounds`
- no standard-path editing of `timeout_seconds`

## Scenarios That Must Stay Green

### 1. Software Engineering

The UI must continue to prove:

- progressive stage editing
- lighter insertion
- artifact editing on `Architecture` stays on `Architecture`
- revise/accept rehearsal loops
- real execution through the live registry

### 2. Document Approval

The UI must continue to prove:

- step-owned assignment
- revise/approve routing
- rehearsal progression
- real execution through the live registry

### 3. Data Analysis / Reporting

The UI must continue to prove:

- artifact definition through workflow files and outputs
- step-to-step artifact attachment
- standard-path assignment
- rehearsal and execution through the live registry

### 4. Meta Protocol Assistant

The UI must continue to prove:

- create a custom skill draft
- keep that new skill selected in the skills workspace
- publish the custom skill
- author a protocol that uses it
- rehearse and execute through UI/API flows rather than database shortcuts

## Verification Matrix

Latest verified commands and results:

- `./.venv/bin/python -m pytest tests/test_protocols.py tests/test_protocol_rehearsal.py tests/test_protocol_engine.py tests/test_db_postgres.py tests/test_registry_ui_contract.py tests/test_registry_service.py tests/test_registry_ui_kit_contract.py -q`
  - `224 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test tests/e2e/playwright/protocol-ui.spec.js --config=tests/e2e/playwright.config.js`
  - `10 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-execution-smoke.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `1 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-exhaustive-audit.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `9 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-runs-filter-matrix.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `1 passed`
- `find .tmp/playwright/live-audit -type f | wc -l`
  - `961`
- `curl -sS http://127.0.0.1:8787/healthz`
  - `{"ok":true}`
- `./octopus status` from `/Users/tinker/octopus`
  - registry healthy
  - `M1`, `M2`, `M3` connected
  - no execution faults

## Current Verified State

No verified blocking defects remain from this pass on the standard authoring
and runs surfaces.

That statement is limited to the verified live surface and the commands above.
It does not mean no future bug can exist. It means there are no open verified
items left from this implementation and audit cycle.

## Regression Rules

Future work in this area must preserve these rules:

1. No duplicate authoring pipeline.
2. No return to command-heavy repeated insertion buttons.
3. No second compact authoring renderer.
4. No standard-path internal selector or stage-internals escape hatches.
5. Artifact editing stays stage-contextual for normal authoring.
6. Custom skill draft creation must keep the new draft selected immediately.
7. Scenario suites are the release bar; the exhaustive audit is breadth
   validation.
