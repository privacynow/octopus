# Operator: Octopus CLI

[← Manual home](README.md) · [Prev: Setup](01-setup.md) · [Next: Registry UI →](03-operator-registry.md)

Running **`./octopus`** with no arguments opens either the **first-bot wizard** (no `.deploy` yet) or the **main menu** when bots already exist. Non-interactive commands (`status`, `start`, `logs`, `doctor`, `registry`, `workspace`, `clean`, `help`) are listed in **`./octopus help`**:

![./octopus help](../assets/quickstart/04-octopus-help.svg)

The **main menu** includes add bot, manage bots, connect bot to registry, manage workspaces, and advanced options:

![Main menu](../assets/octopus/01-main-menu.svg)

**Manage bots** opens a per-bot menu (logs, restart, stop, doctor, edit settings, connect to registry, back). Registry connection flows (local vs remote, multiple connections, switch, disconnect) are illustrated under [`docs/assets/registry/`](../assets/registry/) — start with [04-connect-local.svg](../assets/registry/04-connect-local.svg) and [06-connect-remote.svg](../assets/registry/06-connect-remote.svg).

![Manage bot menu](../assets/octopus/02-manage-bot.svg)

**`./octopus status`** shows each bot’s mode, registry lines, whether the local registry is up, and provider auth:

![./octopus status](../assets/octopus/06-status.svg)

**Workspaces** bind a host directory to one or more bots (`workspace create`, `add-bot`, `verify`):

![Workspace](../assets/octopus/03-workspace.svg)

**Advanced → Configure webhook mode** sets `BOT_WEBHOOK_URL` and listen port for shared-runtime webhook deployments:

![Advanced and webhook](../assets/octopus/04-advanced-webhook.svg)

**`./octopus clean`** is destructive (drops `.deploy`, volumes, and provider login). Confirm by typing `yes`:

![clean](../assets/octopus/05-clean.svg)
