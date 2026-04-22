**Protocol UX Verification Record**

## Status

The scoped protocol-authoring UX work is complete on the standard authoring
surface and verified live on Octopus.

This file no longer tracks an open implementation plan. It now records:

- the product behaviors that are considered complete
- the scenario bars that must stay green
- the verification commands and live results that back those claims
- the regression rules for future changes

## Verified Product State

### 1. Primary authoring flow

The stage stack is the primary authoring surface.

- stages are created inline
- expanded stage editors are local to the selected stage
- `Done` closes the selected stage editor
- `Add below` inserts under the current stage instead of appending at the end
- `Delete step` is local to the step editor, not buried in an internal section

### 2. Assignment UX

Standard authors use the normal assignment surface only.

- assign by skill
- assign by specific agent
- optionally pin a matching agent for a skill-based step
- available agents and skills come from live registry data
- small matching-agent sets use pills instead of duplicated pills plus select

The standard path does not expose internal selector plumbing.

### 3. Focused secondary surfaces

Secondary surfaces are focused and explicitly closable.

- `Protocol settings` opens as a focused secondary surface
- `Show workflow map` opens a focused interactive map surface
- `Back to workflow` returns to the stage stack
- these surfaces no longer sprawl through the main vertical authoring flow

### 4. Artifact UX

Artifacts are authored in workflow context.

- stage-level reads/writes stay inline under the current step
- stage-local artifact editing stays tied to the current step
- protocol-level artifact management still exists as a secondary surface
- artifact editing no longer needs to break stage context for normal authoring

### 5. Standard surface restrictions

The standard authoring surface hides internal escape hatches.

- no `Custom runtime selector`
- no `Advanced` section in the normal step editor
- no standard-path editing of `stage_key`, `max_rounds`, or `timeout_seconds`

### 6. Map behavior

The workflow map remains available, but on demand.

- default authoring is list/editor first
- explicit map open gives a usable interactive workspace
- map close returns to workflow authoring
- map is no longer treated as the dominant default surface

## Scenario Release Bar

The product is only considered complete when these scenario bars are green
through the UI and live registry APIs.

### 1. Software Engineering

The UI must support:

- planning
- review / revise loop
- architecture
- review
- implementation
- review / revise loop
- acceptance

Verified expectations:

- inline stage editing is coherent
- assignment stays step-owned
- artifact attachment stays on the selected stage
- rehearsal visibly proves revise loops
- real execution completes on the live registry

### 2. Document Approval

The UI must support:

- draft
- review
- revise
- review
- approve

Verified expectations:

- authoring is possible without internal controls
- revise/approve routing is visible and correct
- rehearsal proves revise then approve
- live execution reaches terminal completion

### 3. Data Analysis / Reporting

The UI must support:

- define workflow artifacts for data, summaries, and outputs
- author the pipeline through the standard stage editor
- rehearse stage progression
- execute the workflow through the live registry

Verified expectations:

- artifacts are defined and attached through UI/API flows
- assignment is clear per step
- pipeline artifacts remain understandable in the UI
- rehearsal and execution both complete successfully

### 4. Meta Protocol Assistant

The UI must support:

- publish a custom skill through the product surface
- create a protocol that uses that skill
- rehearse the protocol
- execute it through the live registry

Verified expectations:

- no database-only shortcuts
- composition is done through UI and registry APIs
- rehearsal completes
- live execution completes

## Verification Matrix

Current verified commands and results:

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
  - registry running
  - `M1`, `M2`, `M3` connected
  - no execution faults

## Current Verified State

No verified blocking defects remain from the scoped plan or the current
exhaustive live pass.

That statement is limited to the verified standard authoring and runs surfaces.
It does not mean the product is immune to future regressions. It means the
current bar is green and backed by the live evidence above.

## Regression Rules

Future work in this area must preserve these rules:

1. No duplicate authoring pipeline.
- Extend the existing stage-stack workflow editor in place.

2. No standard-path internal escape hatches.
- Internal/runtime selector controls stay out of the standard surface.

3. Secondary surfaces must be focused and explicitly closable.
- No return to sprawling slab-style stacking.

4. Artifact editing must remain stage-contextual for normal authoring.
- Protocol-level artifact management stays secondary.

5. Scenario specs are the release bar.
- A control existing is not enough.
- A backend path existing is not enough.
- The target workflow must be authorable, rehearseable, and executable through
  the real UI and APIs.

6. The exhaustive audit is breadth validation, not a second implementation path.
- It may broaden screenshot coverage.
- It must not drift away from the same live UI contract the main scenario suite
  exercises.

7. Every newly reported bug should become a named live scenario or targeted
   regression test before it is considered fixed.
