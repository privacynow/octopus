# Registry UI: Agent conversation deep link

Manual: [Home](../README.md) · Registry UI: [Overview](../03-operator-registry.md) · Previous: [Agent detail](agent-detail.md) · Next: [Conversations list](conversations-list.md)

**Route:** `/ui/agents/{agent_id}/conversations`

This route is kept for deep links and compatibility, but it is not a separate
product surface anymore. It renders the same agent workspace as
`/ui/agents/{agent_id}` and scrolls you to the inline conversation section for
that agent.

Use it when a log, bookmark, or API response sends you to the older
agent-conversations URL.

![Agent conversations](../../assets/registry/ui/04-agent-conversations.png)
