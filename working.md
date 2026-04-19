# Working Notes For Future Agents

This document explains how protocol authoring work has been handled in this repo, how we test it, how we deploy it to the local octopus checkout, and what the current product state is.

It is intentionally operational. It should let a new agent continue the work without guessing.

## 1. Ground Rules

- Work in place. Do not create parallel product paths, temporary compatibility shims, or duplicate editors.
- Extend the current pipeline instead of adding “one more mode” or “one more renderer.”
- The current authoring direction is:
  - `Process` = orient / navigate
  - `Detail` = primary build/edit surface
  - `Map` = explicit advanced visual inspection/manipulation
- Viewport width must not decide which product the user gets. Desktop and mobile can differ in layout, not in core authoring semantics.
- The protocol document remains the single source of truth. Do not introduce a second authoring model.

These constraints are aligned with [AGENTS.md](/Users/tinker/output/bots/telegram-agent-bot/AGENTS.md) and with the recent protocol remediation work.

## 2. Repos And Checkouts

There are two important working trees:

- Main repo checkout:
  - `/Users/tinker/output/bots/telegram-agent-bot`
- Local octopus deploy checkout:
  - `/Users/tinker/octopus`

Normal flow:

1. Make and test changes in `/Users/tinker/output/bots/telegram-agent-bot`
2. Commit and push the branch from the main repo
3. Pull that branch into `/Users/tinker/octopus`
4. Redeploy from `/Users/tinker/octopus`

Typical branch in this work:

- `feature/protocol`

## 3. Current Product State

As of this document:

- Large protocols default to `Process`
- Drill-in goes to `Detail`
- `Map` is explicit and advanced
- Ordinary route editing is supported in `Detail`
- The lifecycle header is compressed
- Rehearsal state is rendered in `Detail`, not only on the graph canvas
- Browser specs live in a stable committed path under `tests/e2e/playwright`
- `.tmp/playwright` is still used as the Playwright harness/runtime and screenshot output area

Important recent commits on `feature/protocol`:

- `294d499` `Unify protocol authoring detail editor`
- `82d8bc6` `Tighten protocol map and detail checks`
- `7c00082` `Keep role selection stable in detail view`
- `174a8a5` `Unify protocol detail flow and browser checks`
- `eef1362` `Make protocol overflow control accessible`
- `103e3ca` `Show rehearsal state in protocol detail`
- `b0171e5` `Align protocol browser check with overflow actions`

## 4. Current Plan Status

The current plan source in the repo is:

- [plan_fix.md](/Users/tinker/output/bots/telegram-agent-bot/plan_fix.md)

The parts already implemented are:

- Product surfaces reframed to `Process / Detail / Map`
- Header compression on the authoring route
- Unified `Detail` surface as the primary editor
- `Map` demoted to an explicit advanced surface
- Browser tests moved to a stable repo path
- Live Playwright coverage for:
  - blank draft
  - software engineering template
  - mobile detail flow
  - conflict flow
  - capture generation

The parts still likely to need more work:

- Detail surface polish, especially desktop visual quality
- Selector UX depth and data source quality
- Map visual quality and expert affordances
- Continued reduction of visual noise in step editing
- Commercial-grade fit and finish on both desktop and mobile

## 5. Important Files

Main product files:

- [octopus_registry/ui/js/components/protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
- [octopus_registry/ui/js/helpers/kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js)
- [octopus_registry/ui/css/main.css](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/css/main.css)

Contract / unit-style UI checks:

- [tests/test_registry_ui_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_contract.py)
- [tests/test_registry_ui_kit_contract.py](/Users/tinker/output/bots/telegram-agent-bot/tests/test_registry_ui_kit_contract.py)

Stable browser specs:

- [tests/e2e/playwright.config.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright.config.js)
- [tests/e2e/playwright/protocol-ui.spec.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui.spec.js)
- [tests/e2e/playwright/protocol-ui-capture.spec.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/protocol-ui-capture.spec.js)
- [tests/e2e/playwright/helpers/protocol-helpers.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/helpers/protocol-helpers.js)
- [tests/e2e/playwright/playwright-runtime.js](/Users/tinker/output/bots/telegram-agent-bot/tests/e2e/playwright/playwright-runtime.js)

Playwright harness directory:

- `/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright`

## 6. How We Test

There are three main layers of testing used in this work.

### 6.1 Python UI contract checks

Run from the main repo:

```bash
./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_registry_ui_kit_contract.py -q
```

What this covers:

- expected functions and wiring in `protocol-workspace.js`
- expected helpers and rendering contracts in `kit.js`
- basic guard rails when refactoring product structure

This is the fastest check after changing UI JS/CSS structure.

### 6.2 Live Playwright behavioral checks

Playwright specs are committed under `tests/e2e/playwright`, but the runtime currently comes from `.tmp/playwright/node_modules` through `playwright-runtime.js`.

Run from:

- `/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright`

Behavior suite:

```bash
npx playwright test protocol-ui.spec.js --config=../../tests/e2e/playwright.config.js
```

Capture suite:

```bash
npx playwright test protocol-ui-capture.spec.js --config=../../tests/e2e/playwright.config.js
```

Important details:

- Base URL defaults to `http://127.0.0.1:8787`
- It can be overridden with `PLAYWRIGHT_BASE_URL`
- Login token is read from `REGISTRY_UI_TOKEN` if present
- If `REGISTRY_UI_TOKEN` is not set, the helper reads it from:
  - `/Users/tinker/octopus/.deploy/registry/.env`

The live browser suite currently checks:

- blank draft authoring flow
- role-first and step-first creation
- route creation
- publish and rehearse
- process-first experience for the Software Engineering template
- mobile usability of the template
- conflict handling

### 6.3 Visual inspection

After running the capture suite, inspect the generated images under:

- `/Users/tinker/output/bots/telegram-agent-bot/.tmp/playwright`

Key captures:

- `protocol-list-page.png`
- `protocol-blank-page.png`
- `protocol-role-page.png`
- `protocol-detail-page.png`
- `protocol-overview-page.png`
- `protocol-focus-page.png`
- `protocol-full-page.png`
- `protocol-mobile-process-page.png`
- `protocol-mobile-focus-page.png`

Typical review pattern:

1. Run the capture spec
2. Open the main overview/detail/full/mobile captures
3. Check for:
   - overlapping labels
   - overly tall top chrome
   - hidden or clipped content
   - confusing or busy route editing
   - desktop/mobile semantic drift

The visual review is not optional. The recent protocol work has repeatedly passed logic tests while still looking wrong.

## 7. How We Deploy To Octopus

The local deploy checkout is:

- `/Users/tinker/octopus`

The deployment config root is:

- `/Users/tinker/octopus/.deploy`

Important `.deploy` locations:

- registry config:
  - `/Users/tinker/octopus/.deploy/registry`
- registry env:
  - `/Users/tinker/octopus/.deploy/registry/.env`
- provider auth:
  - `/Users/tinker/octopus/.deploy/provider-auth`
- bot data:
  - `/Users/tinker/octopus/.deploy/bots`
- workspace data:
  - `/Users/tinker/octopus/.deploy/workspaces`
- logs:
  - `/Users/tinker/octopus/.deploy/logs`

Typical deployment flow:

### 7.1 Push from the main repo

From `/Users/tinker/output/bots/telegram-agent-bot`:

```bash
git push origin feature/protocol
```

### 7.2 Pull into octopus

From anywhere:

```bash
git -C /Users/tinker/octopus pull --ff-only
```

### 7.3 Redeploy

From `/Users/tinker/octopus`:

```bash
./octopus redeploy --yes
```

This rebuilds and recreates:

- registry
- M1
- M2
- M3

### 7.4 Validate deploy health

Health:

```bash
curl -sS http://127.0.0.1:8787/healthz
```

Expected:

```json
{"ok":true}
```

Status:

```bash
./octopus status
```

What to look for:

- registry `running`
- `M1`, `M2`, `M3` connected
- execution healthy
- freshness current
- no execution faults

## 8. Working Knobs And Levers

These are the common knobs used while iterating.

### 8.1 Browser base URL

Set:

- `PLAYWRIGHT_BASE_URL`

Used when testing a non-default registry URL.

### 8.2 Registry UI token

Set:

- `REGISTRY_UI_TOKEN`

If omitted, the helper falls back to:

- `/Users/tinker/octopus/.deploy/registry/.env`

### 8.3 Viewport-specific checks

The mobile test explicitly sets:

```js
await page.setViewportSize({ width: 390, height: 844 });
```

If working on mobile behavior, keep that path green and inspect the mobile screenshots after capture.

### 8.4 Graph/map review

Use the Software Engineering template as the main acceptance artifact.

Check:

- `Process` opens first for large workflows
- `Detail` drill-in is coherent
- `Map` is available but not required
- rehearsal state appears in `Detail`

### 8.5 Conflict behavior

The browser suite uses direct API draft updates to force conflicts. If conflict behavior changes, update both:

- the UI logic
- the browser flow in `protocol-ui.spec.js`

## 9. Current Editing / Product Conventions

These conventions matter because the protocol area was previously drifting into multiple incompatible UI products.

- `Process` is navigation/orientation
- `Detail` is the main editor
- `Map` is advanced
- Graph editing cannot be the only path for normal work
- Cross-segment route authoring must still be possible without relying on `Map`
- Header/admin chrome should stay compressed
- Rehearsal should be understandable in `Detail`, not only on the graph

If changing the protocol UI, always ask:

1. Does this create a second authoring product?
2. Does this push ordinary users back into `Map`?
3. Does this make desktop and mobile behave like different products again?

If the answer is yes, the change is probably wrong.

## 10. What An Agent Should Do Before Making New Changes

Recommended sequence:

1. Read this file
2. Read [plan_fix.md](/Users/tinker/output/bots/telegram-agent-bot/plan_fix.md)
3. Read [protocol-workspace.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/components/protocol-workspace.js)
4. Read [kit.js](/Users/tinker/output/bots/telegram-agent-bot/octopus_registry/ui/js/helpers/kit.js)
5. Run the Python UI contract tests
6. Run the live Playwright behavior suite
7. Run the capture suite and inspect the images
8. Make the smallest in-place change that improves the current product direction

## 11. Known Current Rough Edges

The work is materially better than before, but it is not finished.

Known likely follow-up areas:

- Detail surface still needs commercial-level polish
- Desktop detail remains visually dense
- Selector UX is improved directionally but still constrained by the quality of available catalogs
- Map is now in the right place product-wise, but still visually legacy in places
- Mobile is better, not complete

Do not solve these by reintroducing multiple authoring paths.

## 12. Current Safety Notes

- Do not stage or revert unrelated local user files casually.
- In this workspace there have been unrelated plan/doc changes and deletions; inspect `git status` carefully before staging.
- Prefer staging explicit paths, not broad `git add .`
- If only docs/tests changed, do not redeploy unless runtime parity is specifically needed
- If runtime/UI code changed, push -> pull in octopus -> redeploy -> recheck health -> rerun Playwright

## 13. Short Operational Checklist

For code changes:

1. Edit in `/Users/tinker/output/bots/telegram-agent-bot`
2. Run:
   - `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_registry_ui_kit_contract.py -q`
3. If UI behavior changed, run:
   - `npx playwright test protocol-ui.spec.js --config=../../tests/e2e/playwright.config.js`
   - `npx playwright test protocol-ui-capture.spec.js --config=../../tests/e2e/playwright.config.js`
4. Inspect capture PNGs in `.tmp/playwright`
5. Commit and push
6. Pull into `/Users/tinker/octopus`
7. Redeploy if runtime changed
8. Check:
   - `curl -sS http://127.0.0.1:8787/healthz`
   - `./octopus status`

That is the working process used in this protocol authoring effort so far.
