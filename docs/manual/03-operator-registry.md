# Operator: Registry web UI

[← Manual home](README.md) · [Prev: Octopus](02-operator-octopus.md) · [Next: Sign in →](registry-ui/sign-in.md)

The Registry **operator SPA** (`ui/`) lets you inspect enrolled bots, conversations, routed tasks, approvals, usage, and provider guidance from one browser shell. Octopus prints a **`/ui`** URL when the registry runs; sign in with **`REGISTRY_UI_TOKEN`** from **`.deploy/registry/.env`**.

The manual splits the UI into **feature pages** below. Most pages embed the same **annotated desktop screenshots** used by [registry-guide.md](../registry-guide.md), under `docs/assets/registry/ui/`; the mobile quick-look page uses raw mobile captures so the narrow layout stays readable. For regeneration, see the registry guide § *Regenerating UI screenshots*.

## Registry UI — feature pages (read in order)

1. [Sign in](registry-ui/sign-in.md) — login form and operator credential
2. [Dashboard](registry-ui/dashboard.md) — attention-first landing page with summary, queue previews, and health
3. [Approvals](registry-ui/approvals.md) — pending decisions in one queue
4. [Agents list](registry-ui/agents-list.md) — registry members, server-side search/state filters, pagination
5. [Agent detail](registry-ui/agent-detail.md) — identity, workers, inline conversations
6. [Agent-scoped conversations](registry-ui/agent-conversations.md) — full-page list for one agent
7. [All conversations (list)](registry-ui/conversations-list.md) — create, search, status filter
8. [Conversation search](registry-ui/conversations-search.md) — debounced query (`q`, ≥3 characters)
9. [Conversation detail](registry-ui/conversation-detail.md) — human-first timeline, compose, cancel, export
10. [Routed tasks](registry-ui/tasks.md) — routed work row summaries, inline detail, and parent conversation links
11. [Capabilities](registry-ui/capabilities.md) — global coordination toggles
12. [Skills catalog](registry-ui/skills-catalog.md) — search plus install / uninstall
13. [Usage](registry-ui/usage.md) — token/cost rollups and date ranges
14. [Provider guidance](registry-ui/guidance.md) — provider selector, draft editor, lifecycle controls
15. [Deep links](registry-ui/deep-links.md) — bookmarkable dashboard/detail URLs
16. [Mobile quick look](registry-ui/mobile.md) — drawer navigation, one-column approvals, and compact conversation detail

**Also:** CLI registry flows (SVG) — [Octopus CLI](02-operator-octopus.md) and [`docs/assets/registry/`](../assets/registry/).
