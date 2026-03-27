# Octopus manual

This manual covers both operator workflows (`./octopus`, Docker, Registry UI)
and end-user chat behavior. The Registry section is organized around the
current operator console, not the older dashboard-first/card-heavy UI.

Registry screenshots under
[`docs/assets/registry/ui/`](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui)
represent both desktop and mobile. The published manual now embeds the raw
captures directly for both layouts; annotated variants remain optional review
artifacts in the screenshot pipeline, not the default docs presentation.

## Read in Order

1. [Overview & terminology](00-overview.md) — product map and shared terms
2. [Setup](01-setup.md) — first run, provider auth, bot token
3. [Octopus CLI](02-operator-octopus.md) — deployment, lifecycle, workspaces
4. [Registry web UI](03-operator-registry.md) — browser shell and feature pages
5. [Telegram](04-product-telegram.md) — commands, approvals, direct routing
6. [Registry HTTP API](05-integration-api.md) — `/v1/...` surfaces behind the UI
7. [Troubleshooting](06-troubleshooting.md) — common failures and recovery steps

## Registry UI Pages

- [Sign in](registry-ui/sign-in.md)
- [Dashboard](registry-ui/dashboard.md)
- [Approvals](registry-ui/approvals.md)
- [Agents list](registry-ui/agents-list.md)
- [Agent detail](registry-ui/agent-detail.md)
- [Agent conversation deep link](registry-ui/agent-conversations.md)
- [Conversations list](registry-ui/conversations-list.md)
- [Conversation search](registry-ui/conversations-search.md)
- [Conversation detail](registry-ui/conversation-detail.md)
- [Tasks](registry-ui/tasks.md)
- [Capabilities](registry-ui/capabilities.md)
- [Skills catalog](registry-ui/skills-catalog.md)
- [Usage](registry-ui/usage.md)
- [Provider guidance](registry-ui/guidance.md)
- [Deep links](registry-ui/deep-links.md)
- [Mobile quick look](registry-ui/mobile.md)

## Related Docs

- [README.md](/Users/tinker/output/bots/telegram-agent-bot/README.md)
- [ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md)
- [registry-guide.md](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-guide.md)
- [flows-catalog.md](/Users/tinker/output/bots/telegram-agent-bot/docs/flows-catalog.md)
