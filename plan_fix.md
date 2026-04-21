**Protocol UX Verification Status**

## Current Verified State

The current protocol authoring, rehearsal, execution, and runs surfaces have
been re-verified on the live Octopus deployment from commit `94ce099`.

Live verification completed against:
- `/Users/tinker/octopus`
- `http://127.0.0.1:8787`

## What Was Fixed In This Pass

1. Inline create-step assignment controls now stay functional after the
   progressive editor rerenders.
- Pending-stage bindings are rebound against the current rendered controls.
- The create-step shell key now tracks the authoring fields users actually edit
  before assignment, so the inline editor stays coherent.

2. Segmented controls now use delegated click handling in the shared UI helper.
- This removes dependence on per-button listeners surviving DOM reconciliation.

3. The tracked Playwright coverage now matches the real assignment behavior.
- Existing-stage assignment tests no longer assume a second matching agent
  exists when only one agent matches the chosen skill.

## Live Audit Results

The current live audit is clean.

Verification completed:
- `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_registry_ui_kit_contract.py -q`
  - `41 passed`
- `./.venv/bin/python -m pytest tests/test_protocol_rehearsal.py tests/test_protocol_engine.py tests/test_protocols.py tests/test_db_postgres.py -q`
  - `75 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test tests/e2e/playwright/protocol-ui.spec.js --config=tests/e2e/playwright.config.js`
  - `7 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-execution-smoke.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `1 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-exhaustive-audit.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `9 passed`
- `./.tmp/playwright/node_modules/.bin/playwright test .tmp/playwright/live-runs-filter-matrix.spec.js --config=.tmp/playwright/playwright.live.config.js`
  - `1 passed`

Fresh live audit artifacts:
- `.tmp/playwright/live-audit`
- `619` files captured

## Coverage Included

The live sweep covered:
- blank draft creation
- inline role creation
- assignment by skill
- assignment by specific agent
- inline stage insertion
- stage deletion
- branch/finish editing
- Software Engineering template editing
- Document Approval template editing
- mobile authoring
- rehearsal flows
- published execution flows
- runs matrix capture across desktop/tablet/mobile

## Open Defects

None verified in the current live pass.

## Rule Going Forward

Any newly observed problem must be:
1. reproduced against the live Octopus deployment
2. added here as a concrete defect
3. fixed and re-verified through the same live harness before this file is
   considered changed again
