# Operator: Octopus CLI

[← Manual home](README.md) · [Prev: Setup](01-setup.md) · [Next: Registry UI →](03-operator-registry.md)

Running **`./octopus`** with no arguments opens the new state-driven operator menu: **Recommended Actions**, **Lifecycle**, **Bots**, **Registry**, **Workspaces**, **Diagnose**, and **Status**. Non-interactive commands are verb-first (`status`, `start`, `stop`, `restart`, `redeploy`, `connect`, `disconnect`, `logs`, `shell`, `doctor`, `clean`, `help`) and are listed in **`./octopus help`**:

![./octopus help](../assets/quickstart/04-octopus-help.svg)

The no-arg menu now centers the next useful action instead of the older static five-option menu. Add-bot, lifecycle, registry, and workspace operations all live behind that same menu:

![Main menu](../assets/octopus/01-main-menu.svg)

**Lifecycle** handles bulk or targeted `start`, `stop`, `restart`, and `redeploy`. `restart` preserves volumes and reuses current images; `redeploy` rebuilds/recreates managed targets while still preserving bot and registry state by default. Every mutating action previews the exact candidates once unless `--yes` is supplied.

![Bots menu](../assets/octopus/02-manage-bot.svg)

**`./octopus status`** shows each bot’s mode, registry lines, provider auth, and managed-image freshness:

![./octopus status](../assets/octopus/06-status.svg)

**Workspaces** bind a host directory to one or more bots from the `Workspaces` section of the menu:

![Workspace](../assets/octopus/03-workspace.svg)

**Diagnose** groups logs, shell access, doctor, and provider-auth recovery in one place:

![Diagnose menu](../assets/octopus/04-advanced-webhook.svg)

**`./octopus clean`** is destructive (drops `.deploy`, volumes, and provider login). Confirm by typing `yes`:

![clean](../assets/octopus/05-clean.svg)
