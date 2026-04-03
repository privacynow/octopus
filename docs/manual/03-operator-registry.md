# Operator: Registry web UI

Manual: [Home](README.md) · Previous: [Octopus CLI](02-operator-octopus.md) · Next: [Registry sign in](registry-ui/sign-in.md)

The Registry operator UI is the browser console under `/ui`. It is the main
surface for:

- watching active conversations and routed work
- approving or rejecting blocked actions
- opening or reusing conversations with connected agents
- following task state without dropping into raw logs
- reviewing full stored activity when you need diagnostics

The shell is one responsive SPA:

- left rail on desktop, drawer on mobile
- compact route header
- one primary work surface per route
- shared segmented controls, list rows, summary cards, and task/conversation
  semantics across desktop and mobile

Sign in with `REGISTRY_UI_TOKEN` from
`.deploy/registry/.env` after `./octopus start registry` and `./octopus connect`
have enrolled the bots you want to see.

## Main Routes

1. [Sign in](registry-ui/sign-in.md) — operator login
2. [Dashboard](registry-ui/dashboard.md) — summary rail plus current needs
3. [Approvals](registry-ui/approvals.md) — pending decisions with direct actions
4. [Agents list](registry-ui/agents-list.md) — search, state filter, open conversation
5. [Agent detail](registry-ui/agent-detail.md) — overview, workers, inline conversations
6. [Agent conversation deep link](registry-ui/agent-conversations.md) — compatibility route that lands on the same agent workspace
7. [Conversations list](registry-ui/conversations-list.md) — quick start, search, status filter, active threads
8. [Conversation search](registry-ui/conversations-search.md) — debounced server-side query on the same route
9. [Conversation detail](registry-ui/conversation-detail.md) — Conversation / Tasks / Full activity plus shared composer
10. [Tasks](registry-ui/tasks.md) — routed-task queue with summary rail, filters, expandable details
11. [Routing](registry-ui/routing.md) — routing-skill policy
12. [Skills catalog](registry-ui/skills-catalog.md) — catalog, install, uninstall
13. [Usage](registry-ui/usage.md) — prompt/completion/cost rollups
14. [Provider guidance](registry-ui/guidance.md) — provider-specific guidance lifecycle
15. [Deep links](registry-ui/deep-links.md) — bookmarkable agent and conversation URLs
16. [Mobile quick look](registry-ui/mobile.md) — current small-screen layout

## What The UI Assumes

- Conversations are the main operator workspace.
- The same composer handles normal replies and direct routing:
  `@m2`, `@skill:review`, or `@role:reviewer`.
- Routed work is represented as first-class tasks, not as provider-generated
  XML or free-form timeline text.
- Usage totals come from provider-response usage data and can roll delegated
  child work into the parent conversation when that usage is reported.

## Screenshots

The feature pages use the raw desktop and mobile captures under
[`docs/assets/registry/ui/`](/Users/tinker/output/bots/telegram-agent-bot/docs/assets/registry/ui).
Annotated variants remain available in the screenshot pipeline for internal
review, but the published manual now shows the interface directly. Regeneration
steps live in
[registry-guide.md](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-guide.md).
