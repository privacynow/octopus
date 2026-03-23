# Operator: Registry web UI

[← Manual home](README.md) · [Prev: Octopus](02-operator-octopus.md) · [Next: Sign in →](registry-ui/sign-in.md)

The Registry **operator SPA** (`ui/`) lets you inspect enrolled bots, conversations, routed tasks, and coordination state. Octopus prints a **`/ui`** URL when the registry runs; sign in with **`REGISTRY_UI_TOKEN`** from **`.deploy/registry/.env`**.

The manual splits the UI into **feature pages** below. **Each page embeds its annotated screenshot** (same assets as [registry-guide.md](../registry-guide.md), under `docs/assets/registry/ui/`). For regeneration, see the registry guide § *Regenerating UI screenshots*.

## Registry UI — feature pages (read in order)

1. [Sign in](registry-ui/sign-in.md) — login form and operator credential
2. [Agents list](registry-ui/agents-list.md) — home grid, connectivity, pagination
3. [Agent detail](registry-ui/agent-detail.md) — identity, workers, inline conversations
4. [Agent-scoped conversations](registry-ui/agent-conversations.md) — full-page list for one agent
5. [All conversations (list)](registry-ui/conversations-list.md) — pagination, status filter
6. [Conversation search](registry-ui/conversations-search.md) — debounced query (`q`, ≥3 characters)
7. [Conversation detail](registry-ui/conversation-detail.md) — timeline, compose, cancel, export
8. [Routed tasks](registry-ui/tasks.md) — delegation table and parent conversation
9. [Capabilities](registry-ui/capabilities.md) — global coordination toggles
10. [Skills catalog](registry-ui/skills-catalog.md) — runtime catalog browse
11. [Usage](registry-ui/usage.md) — token/cost rollups and date ranges
12. [Deep links](registry-ui/deep-links.md) — bookmarkable agent and conversation URLs

**Also:** CLI registry flows (SVG) — [Octopus CLI](02-operator-octopus.md) and [`docs/assets/registry/`](../assets/registry/).
