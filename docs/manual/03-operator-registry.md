# Operator: Registry web UI

[← Manual home](README.md) · [Prev: Octopus](02-operator-octopus.md) · [Next: Sign in →](registry-ui/sign-in.md)

The Registry **operator SPA** (`ui/`) lets you inspect enrolled bots, conversations, routed tasks, approvals, usage, and provider guidance from one browser shell. Octopus prints a **`/ui`** URL when the registry runs; sign in with **`REGISTRY_UI_TOKEN`** from **`.deploy/registry/.env`**.

The manual splits the UI into **feature pages** below. **Each page embeds its annotated screenshot** (same assets as [registry-guide.md](../registry-guide.md), under `docs/assets/registry/ui/`). For regeneration, see the registry guide § *Regenerating UI screenshots*.

## Registry UI — feature pages (read in order)

1. [Sign in](registry-ui/sign-in.md) — login form and operator credential
2. [Dashboard](registry-ui/dashboard.md) — global summary from `/v1/summary`
3. [Agents list](registry-ui/agents-list.md) — registry members, current-page filters, pagination
4. [Agent detail](registry-ui/agent-detail.md) — identity, workers, inline conversations
5. [Agent-scoped conversations](registry-ui/agent-conversations.md) — full-page list for one agent
6. [All conversations (list)](registry-ui/conversations-list.md) — create, search, status filter
7. [Conversation search](registry-ui/conversations-search.md) — debounced query (`q`, ≥3 characters)
8. [Conversation detail](registry-ui/conversation-detail.md) — timeline, compose, cancel, export
9. [Routed tasks](registry-ui/tasks.md) — routed work cards and parent conversation links
10. [Capabilities](registry-ui/capabilities.md) — global coordination toggles
11. [Skills catalog](registry-ui/skills-catalog.md) — search plus install / uninstall
12. [Usage](registry-ui/usage.md) — token/cost rollups and date ranges
13. [Provider guidance](registry-ui/guidance.md) — provider selector, draft editor, lifecycle controls
14. [Deep links](registry-ui/deep-links.md) — bookmarkable dashboard/detail URLs

**Also:** CLI registry flows (SVG) — [Octopus CLI](02-operator-octopus.md) and [`docs/assets/registry/`](../assets/registry/).
