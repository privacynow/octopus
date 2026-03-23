# Octopus CLI storyboards (SVG)

Terminal-style diagrams for **non-registry** Octopus flows. They use the same panel, **CRT glow** (`feGaussianBlur` + green phosphor matrix + duplicate `use` layers), and **IBM Plex Mono** styling as [`../registry/04-connect-local.svg`](../registry/04-connect-local.svg). Blur strength matches the registry set (`stdDeviation` 0.85, glow layer opacity ~0.52).

| File | Flow |
|------|------|
| [01-main-menu.svg](01-main-menu.svg) | Main menu (`main_menu`) — five options |
| [02-manage-bot.svg](02-manage-bot.svg) | Manage bot (`manage_bot_menu`) |
| [03-workspace.svg](03-workspace.svg) | `workspace create` / `add-bot` / `verify` |
| [04-advanced-webhook.svg](04-advanced-webhook.svg) | `advanced_menu` + `configure_webhook_mode_flow` |
| [05-clean.svg](05-clean.svg) | `cmd_clean` confirmation |
| [06-status.svg](06-status.svg) | `./octopus status` output |

**Registry-specific** SVGs remain under [`../registry/`](../registry/) (connect, switch, disconnect, …).

**Help output** is illustrated in [`../quickstart/04-octopus-help.svg`](../quickstart/04-octopus-help.svg).
