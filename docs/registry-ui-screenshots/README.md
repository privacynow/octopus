# Registry UI screenshot capture

This folder owns the Playwright harness that refreshes the published registry UI
docs images under
[`docs/assets/registry/ui/`](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui).

The capture run now treats desktop and mobile as one docs pipeline:

- desktop route captures used by `registry-guide.md` and the manual feature pages
- mobile reference captures used by `manual/registry-ui/mobile.md`
- sibling `*.meta.json` files consumed by `annotate.py`

This harness is for **documentation captures**, not runtime validation. For
live runtime validation, use the disposable smoke harness under
`scripts/e2e/run_live_registry_smoke.sh`. The `--snapshot-deploy` input to that
live harness is the same `.deploy` snapshot shape produced by
`scripts/ops/backup_octopus_deploy.sh` and
`scripts/ops/refresh_octopus_with_backup.sh`.

## Prerequisites

- Node.js
- repo root `.venv`
- Playwright Chromium browser installed

## Commands

```bash
cd docs/registry-ui-screenshots
npm install
npx playwright install chromium
npm run capture
npm run annotate
```

Optional:

```bash
npm run capture:manual
npm run capture:all
```

## What `npm run capture` does

- starts a throwaway registry on `127.0.0.1:19987`
- seeds agents, conversations, approvals, routed tasks, usage, and guidance
- signs into `/ui`
- captures the current desktop routes
- captures the mobile dashboard, approvals, and conversation workspace
- writes refreshed raw PNGs plus sibling `*.meta.json` overlay files

## What `annotate.py` does

`annotate.py` reads the sibling `*.meta.json` files and writes
`*-annotated.png`. Those annotated variants are kept as optional review assets;
the published docs pages now use the raw PNG captures directly.

## Notes

- update selectors in `capture-guide.spec.ts` when the production DOM changes;
  do not add docs-only ids to product code
- the docs capture dataset is synthetic and intentionally stable
- usage captures are driven by provider-response usage data
- delegated child usage appears in parent conversation totals when the seeded
  routed-task result includes usage
