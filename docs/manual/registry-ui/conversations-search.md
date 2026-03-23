# Registry UI: Conversation search

[← All conversations (list)](conversations-list.md) · [Registry UI hub](../03-operator-registry.md) · [Next: Conversation detail →](conversation-detail.md)

**Route:** still **`/ui/conversations`** — the search box is **debounced**; the server receives **`q`** only after you type **at least three characters**, which keeps noise and load down.

The screenshot below uses the demo query **`Acme`** against synthetic titles from the doc capture seed (FTS-backed list narrowing).

![Conversations filtered](../../assets/registry/ui/04b-conversations-filtered-annotated.png)
