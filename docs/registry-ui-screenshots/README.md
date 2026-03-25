# Registry UI screenshot capture

Refreshes **annotated PNGs** under `docs/assets/registry/ui/` (embedded in [registry-guide.md](../registry-guide.md) and in [manual/registry-ui/](../manual/registry-ui/) feature pages). The live registry capture now reflects the **dashboard-first UI** and current event/API contract. Optional **`capture:manual`** still writes raw PNGs under `docs/assets/manual/` for fixture-based captures. The published mobile reference images (`14-mobile-dashboard`, `15-mobile-approvals`, `16-mobile-conversation`) are sourced from the Playwright smoke review captures and kept as raw PNGs so the narrow layout stays legible.

## Prerequisites

- Node.js (for `npx playwright`)
- Repo root `.venv` with `requirements.txt` + **`pip install -r requirements-dev.txt`** (includes **Pillow** for `annotate.py` and `uvicorn` for registry capture)

## Commands

**Registry UI (live app on port 19987) + manual fixtures (static HTML):**

```bash
cd docs/registry-ui-screenshots
npm install
npx playwright install chromium
npm run capture          # registry UI → docs/assets/registry/ui/
npm run capture:manual   # fixtures → docs/assets/manual/
# or: npm run capture:all
../../.venv/bin/python annotate.py   # both asset dirs (registry/ui + manual)
```

**Isolated live registry smoke (snapshot-based disposable stack):**

```bash
bash ../../scripts/e2e/run_live_registry_smoke.sh \
  --snapshot-deploy /path/to/saved/.deploy
```

That harness is separate from screenshot capture:

- it copies a saved `.deploy` snapshot into `.tmp/e2e-live-smoke/`
- builds fresh images from the current repo
- starts disposable registry + bot containers
- runs API smoke and `live_registry_smoke.spec.js`
- tears the stack down unless `--keep-fresh-stack` is passed

Use it when validating real registry delegation/runtime behavior. Use
`npm run capture` when regenerating the published docs screenshots.

`annotate.py` writes `*-annotated.png` using sibling `*.meta.json` files (rectangle + arrow coordinates from capture). **Labels** are rendered in a **dark footer band** under the screenshot (numbered list), not as yellow boxes on top of the UI. Re-run **`npm run capture`** if you change layout; then **`annotate.py`** again.

## Notes

- `capture-guide.spec.ts` uses the **current** SPA routes and selectors (`/ui` dashboard, `/ui/agents`, `/ui/conversations/:id`, `.conversation-meta`, `#usage-summary`, `.guidance-textarea`, etc.). If you rename those structures, update the spec—**do not** add capture-only ids to production UI components.
- `ui-overhaul-smoke.spec.ts` writes mobile review captures under `docs/registry-ui-screenshots/test-results/`; when the mobile docs images need refresh, promote those PNGs into `docs/assets/registry/ui/14-mobile-dashboard.png`, `15-mobile-approvals.png`, and `16-mobile-conversation.png`.
- Playwright starts the registry on `127.0.0.1:19987` with env vars set in `playwright.config.cjs`. The capture run now removes the throwaway SQLite DB before startup, so each run starts from a clean screenshot seed.
- Usage screenshots come from seeded **`provider.response`** events only; there is no separate legacy usage seeding path anymore.
- Tokens are `guide-capture-*` (must not be known-default tokens per `app/channels/registry/auth.py`).
