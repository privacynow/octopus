# Octopus user manual

End-to-end documentation for **operators** (deployment, `./octopus`, Registry) and **product users** (Telegram chat, commands, approvals). Raster figures use **thin outlines** on the UI and **numbered captions in a bottom margin** (from [`annotate.py`](../registry-ui-screenshots/annotate.py)) so labels do not cover content. **SVG** storyboards use the same terminal CRT styling as [`docs/assets/registry/`](../assets/registry/).

## How to read this manual

| Volume | Chapters | Audience |
|--------|----------|----------|
| **Setup & operator** | [Setup](01-setup.md) · [Octopus CLI](02-operator-octopus.md) · [Registry browser](03-operator-registry.md) | Who runs Docker and owns `.deploy/` |
| **Product** | [Telegram](04-product-telegram.md) | Chat users and in-channel admins |
| **Integration** | [Registry API](05-integration-api.md) | Automation, bots calling `/v1/…` |
| **Reference** | [Troubleshooting](06-troubleshooting.md) · [Flow index](../flows-catalog.md) | Everyone |

**Canonical flow list (code pointers):** [flows-catalog.md](../flows-catalog.md).  
**Architecture:** [ARCHITECTURE.md](../../ARCHITECTURE.md).  
**Focused registry tutorial:** [registry-guide.md](../registry-guide.md).

## Regenerating screenshots

From repo root (Node + Chromium + repo `.venv` with `requirements-dev.txt`):

```bash
cd docs/registry-ui-screenshots
npm install && npx playwright install chromium
npm run capture:all
../../.venv/bin/python annotate.py
```

See [registry-ui-screenshots README](../registry-ui-screenshots/README.md) for details.

---

### Chapter index

1. [Overview & terminology](00-overview.md)
2. [Setup](01-setup.md) — BotFather token, provider auth, first run
3. [Operator: Octopus](02-operator-octopus.md) — menus, status, registry, workspaces, webhook, clean
4. [Operator: Registry UI](03-operator-registry.md) — every browser screen (live capture)
5. [Product: Telegram](04-product-telegram.md) — commands, settings, skills, approvals, runtime modes
6. [Integration: Registry API](05-integration-api.md) — HTTP surface vs UI coverage
7. [Troubleshooting](06-troubleshooting.md) — escalation order
