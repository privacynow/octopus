# Registry UI screenshot capture

Used to refresh PNGs under `docs/assets/registry/ui/` for `docs/registry-guide.md`.

## Prerequisites

- Node.js (for `npx playwright`)
- Repo root `.venv` with `requirements.txt` installed (provides `uvicorn` for the webServer)
- This folder’s `.venv` with **Pillow** (`python3 -m venv .venv && .venv/bin/pip install Pillow`) for `annotate.py`

## Commands

```bash
cd docs/registry-ui-screenshots
npm install
npx playwright install chromium
npm run capture
./.venv/bin/python annotate.py
```

`annotate.py` writes `*-annotated.png` next to each raw capture.

## Notes

- Playwright starts the registry on `127.0.0.1:19987` with env vars set in `playwright.config.cjs`.
- Tokens are `guide-capture-*` (must not be known-default tokens per `app/channels/registry/auth.py`).
