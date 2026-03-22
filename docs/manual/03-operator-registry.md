# Operator: Registry web UI

[← Manual home](README.md) · [Prev: Octopus](02-operator-octopus.md) · [Next: Telegram →](04-product-telegram.md)

These screens are **live captures** of the Registry SPA with synthetic seed data. Regenerate with `npm run capture` in [`docs/registry-ui-screenshots/`](../registry-ui-screenshots/) (see [Manual home](README.md#regenerating-screenshots)).

## Sign in

Password = `REGISTRY_UI_TOKEN` (no separate username).

![Login](../assets/registry/ui/00-login-annotated.png)

## Agents (home)

![Agents list](../assets/registry/ui/01-agents-annotated.png)

## Agent detail

![Agent detail](../assets/registry/ui/02-agent-detail-annotated.png)

## Conversations for one agent

![Agent conversations](../assets/registry/ui/03-agent-conversations-annotated.png)

## All conversations

![All conversations](../assets/registry/ui/04-conversations-annotated.png)

### Search filter (3+ characters)

![Filtered conversations](../assets/registry/ui/04b-conversations-filtered-annotated.png)

## Conversation timeline (read-only)

![Conversation detail](../assets/registry/ui/05-conversation-detail-annotated.png)

## Routed tasks

Click a row to open the **parent conversation**.

![Tasks](../assets/registry/ui/06-tasks-annotated.png)

## Capabilities

![Capabilities](../assets/registry/ui/07-capabilities-annotated.png)

## Skills catalog

![Skills](../assets/registry/ui/08-skills-annotated.png)

## Usage

![Usage](../assets/registry/ui/09-usage-annotated.png)

## Deep links

**Agent:** `/ui/agents/{agent_id}`

![Agent deep link](../assets/registry/ui/10-agent-detail-deep-link-annotated.png)

**Conversation:** `/ui/conversations/{conversation_id}`

![Conversation deep link](../assets/registry/ui/11-conversation-deep-link-annotated.png)

## Logout

Use **Logout** in the sidebar footer (ends the operator session). The footer appears on **every** view; it is visible here on the agents home:

![Sidebar with Logout](../assets/registry/ui/01-agents-annotated.png)

## Limits

The timeline is **read-only** in the current UI; posting messages or export uses the **HTTP API**. See [registry-guide.md § limits](../registry-guide.md#what-the-ui-does-not-do-yet).
