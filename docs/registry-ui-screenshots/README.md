# Registry UI screenshot capture

Refreshes **annotated PNGs** under `docs/assets/registry/ui/` (embedded in [registry-guide.md](../registry-guide.md) and in [manual/registry-ui/](../manual/registry-ui/) feature pages). Optional **`capture:manual`** writes raw PNGs under `docs/assets/manual/` for fixture-based captures.

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

`annotate.py` writes `*-annotated.png` using sibling `*.meta.json` files (rectangle + arrow coordinates from capture). **Labels** are rendered in a **dark footer band** under the screenshot (numbered list), not as yellow boxes on top of the UI. Re-run **`npm run capture`** if you change layout; then **`annotate.py`** again.

## Notes

- `capture-guide.spec.ts` uses **structural selectors** against the real SPA (`#content .filter-bar + div` for list panes, `#usage-summary` / `#usage-table`, etc.). If you change layout order or drop those hooks, update the spec—**do not** add capture-only `id`s to production UI components.
- Playwright starts the registry on `127.0.0.1:19987` with env vars set in `playwright.config.cjs` (including `REGISTRY_ALLOW_DESTRUCTIVE_MIGRATION=1` for local DB upgrades). If SQLite errors mention missing columns, delete **`.capture-registry.sqlite3`** in this directory and re-run **`npm run capture`**.
- Tokens are `guide-capture-*` (must not be known-default tokens per `app/channels/registry/auth.py`).
