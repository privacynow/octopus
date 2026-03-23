# Octopus user manual

For **operators** (Docker, `./octopus`, Registry browser) and **chat users** (Telegram). **Mermaid** diagrams render from markdown. **[§ Registry web UI](03-operator-registry.md)** is the hub; **each feature** (sign-in, agents, conversations, tasks, …) has its **own page under [registry-ui/](registry-ui/)** with an **embedded annotated screenshot**. The [registry guide](../registry-guide.md) mirrors the same PNGs in one long tour plus regeneration steps.

## Read in order

1. [Overview & terminology](00-overview.md) — how the pieces fit together
2. [Setup](01-setup.md) — token, provider auth, first run
3. [Octopus CLI](02-operator-octopus.md) — menus, status, workspaces, clean
4. [Registry web UI](03-operator-registry.md) — hub, then [Sign in](registry-ui/sign-in.md) … [Deep links](registry-ui/deep-links.md) (feature pages under [registry-ui/](registry-ui/))
5. [Telegram](04-product-telegram.md) — commands and chat behavior
6. [Registry HTTP API](05-integration-api.md) — `/v1/…` and UI coverage
7. [Troubleshooting](06-troubleshooting.md) — what to run when something fails

**Also:** [registry-guide.md](../registry-guide.md) (full Registry tour + screenshot regeneration) · [ARCHITECTURE.md](../../ARCHITECTURE.md) · [flows-catalog.md](../flows-catalog.md).
