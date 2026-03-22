# Operator: Octopus CLI

[← Manual home](README.md) · [Prev: Setup](01-setup.md) · [Next: Registry UI →](03-operator-registry.md)

Illustrations below use **annotated PNG mocks** (Playwright capture of HTML fixtures). **Vector storyboards** in [`docs/assets/octopus/`](../assets/octopus/) mirror the same menus in the CRT style used across the repo — keep them in sync when [`octopus`](../../octopus) menus change.

**`./octopus help`** (full text): [04-octopus-help.svg](../assets/quickstart/04-octopus-help.svg).

## Main menu (multiple bots)

When at least one bot exists and the default bot is already running, **`./octopus`** opens the main menu.

![Main menu](../assets/manual/oct-01-main-menu-annotated.png)

![Main menu storyboard (SVG)](../assets/octopus/01-main-menu.svg)

| # | Flow |
|---|------|
| 1 | Add a bot |
| 2 | [Manage bot](#manage-bot) |
| 3 | Connect bot to registry |
| 4 | [Workspace](#workspaces) |
| 5 | [Advanced](#advanced-and-webhook) |

## Manage bot

![Manage bot menu](../assets/manual/oct-02-manage-bot-annotated.png)

![Manage bot storyboard (SVG)](../assets/octopus/02-manage-bot.svg)

| # | Action |
|---|--------|
| 1 | View logs (`./octopus logs`) |
| 2 | Restart |
| 3 | Stop |
| 4 | Health check (`./octopus doctor`) |
| 5 | [Edit settings](#edit-settings) |
| 6 | Registry connection wizard |
| 7 | Back |

### Edit settings

![Edit settings](../assets/manual/oct-03-edit-settings-annotated.png)

## Status and logs

`./octopus status` shows bots, **per-registry connection rows** when in registry mode, local registry state, and provider authentication.

![./octopus status](../assets/manual/oct-04-status-annotated.png)

## Registry subcommands

`./octopus registry` opens an interactive menu when the local registry exists (start/stop/logs/status). When the registry is running, the CLI prints the **Registry UI** URL; the password is `REGISTRY_UI_TOKEN` in `.deploy/registry/.env`.

![Registry menu](../assets/manual/oct-05-registry-menu-annotated.png)

### Remote registry (HTTPS)

When adding a **remote** connection, Octopus prompts for URL, enrollment token, and **scope** (`full` / `channel` / `coordination`).

![Remote registry prompts](../assets/manual/oct-06-remote-registry-annotated.png)

**Storyboard SVGs** (connect/switch/disconnect): see [docs/assets/registry/](../assets/registry/) — e.g. [06-connect-remote.svg](../assets/registry/06-connect-remote.svg), [10-manage-registry-connections.svg](../assets/registry/10-manage-registry-connections.svg).

## Workspaces

Shared host folders mounted into selected bots:

![workspace help](../assets/manual/oct-07-workspace-annotated.png)

![Workspace CLI storyboard (SVG)](../assets/octopus/03-workspace.svg)

## Advanced and webhook

![Advanced menu](../assets/manual/oct-08-advanced-annotated.png)

**Webhook mode** (shared runtime deployment):

![Webhook configuration](../assets/manual/oct-09-webhook-annotated.png)

![Advanced + webhook storyboards (SVG)](../assets/octopus/04-advanced-webhook.svg)

## Nuclear reset: `./octopus clean`

![./octopus clean warning](../assets/manual/oct-10-clean-annotated.png)

![Clean confirmation storyboard (SVG)](../assets/octopus/05-clean.svg)

---

**Commands without menus:** `./octopus start|stop|logs|doctor|registry …|workspace …|clean|help` — see `./octopus help`.
