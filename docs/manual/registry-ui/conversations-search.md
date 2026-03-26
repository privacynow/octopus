# Registry UI: Conversation search

Manual: [Home](../README.md) · Registry UI: [Overview](../03-operator-registry.md) · Previous: [Conversations list](conversations-list.md) · Next: [Conversation detail](conversation-detail.md)

**Route:** `/ui/conversations`

Search stays on the same route. The input is debounced and sends the query to
the server as `q`, so the filtered list reflects the real registry dataset
rather than only the conversations already rendered in the browser.

The screenshot below uses `Release` from the seeded docs dataset so you can see
the list narrow without leaving the page.

![Conversations filtered](../../assets/registry/ui/05b-conversations-filtered.png)
