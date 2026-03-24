# Octopus CLI storyboards (SVG)

Terminal-style diagrams for **non-registry** Octopus flows. They use the same panel, **CRT glow** (`feGaussianBlur` + green phosphor matrix + duplicate `use` layers), and **IBM Plex Mono** styling as [`../registry/04-connect-local.svg`](../registry/04-connect-local.svg). Blur strength matches the registry set (`stdDeviation` 0.85, glow layer opacity ~0.52).

| File | Flow |
|------|------|
| [01-main-menu.svg](01-main-menu.svg) | State-driven main menu — Recommended Actions, Lifecycle, Bots, Registry, Workspaces, Diagnose, Status |
| [02-manage-bot.svg](02-manage-bot.svg) | Bots submenu — add/connect/disconnect/start/stop/restart/redeploy/inspect |
| [03-workspace.svg](03-workspace.svg) | Workspace menu — create, attach, detach, inspect |
| [04-advanced-webhook.svg](04-advanced-webhook.svg) | Diagnose submenu — logs, shell, doctor, provider auth |
| [05-clean.svg](05-clean.svg) | `cmd_clean` confirmation |
| [06-status.svg](06-status.svg) | `./octopus status` output |

**Registry-specific** SVGs remain under [`../registry/`](../registry/) (connect, switch, disconnect, …).

**Help output** is illustrated in [`../quickstart/04-octopus-help.svg`](../quickstart/04-octopus-help.svg).
