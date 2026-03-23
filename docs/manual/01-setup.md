# Setup

[← Manual home](README.md) · [Prev: Overview](00-overview.md) · [Next: Octopus →](02-operator-octopus.md)

Get a **bot token** from **@BotFather** (`/newbot`), clone the repo, and run **`./octopus`** with no prior `.deploy/` to start the **first-bot wizard** (token, Claude or Codex, safe vs autonomous vs advanced). The CLI then builds the image, runs **provider login** when needed, and starts the container.

**Why SVG here (not PNG):** Setup steps are **storyboards**, like [`docs/assets/octopus/`](../assets/octopus/) and [`docs/assets/registry/`](../assets/registry/). **SVG** stays sharp at any zoom and matches the CRT terminal style for `./octopus` prompts. The **PNG** fixtures under `docs/assets/manual/setup-*.png` still exist for the optional Playwright **`capture:manual`** pipeline if you want raster regeneration with `annotate.py`; the manual does not depend on them.

### BotFather

![BotFather chat (illustrative)](../assets/setup/01-botfather.svg)

### Provider authentication

![Provider sign-in during Octopus](../assets/setup/02-provider-auth.svg)

### First-bot wizard (terminal)

![First-bot wizard](../assets/setup/03-first-bot-wizard.svg)

Older **quickstart** SVGs (same narrative, different framing): [01-first-bot-setup.svg](../assets/quickstart/01-first-bot-setup.svg), [02-bot-running.svg](../assets/quickstart/02-bot-running.svg), [03-octopus-status.svg](../assets/quickstart/03-octopus-status.svg).

Confirm **provider auth** with **`./octopus status`** (see [Operator: Octopus](02-operator-octopus.md)). Optional **registry**: [Registry UI](03-operator-registry.md) and [`./octopus` storyboards](02-operator-octopus.md).

**Security:** keep `TELEGRAM_BOT_TOKEN` and `REGISTRY_UI_TOKEN` secret; see root [README.md](../../README.md).
