# Registry UI: Conversation search

[← Manual home](../README.md) · [Prev: Conversations list](conversations-list.md) · [Next: Conversation detail →](conversation-detail.md)

**Route:** still **`/ui/conversations`** — the search box is **debounced**; the server receives **`q`** only after you type **at least three characters**, which keeps noise and load down.

The screenshot below uses the demo query **`Release`** against synthetic conversation titles from the doc capture seed (FTS-backed list narrowing).

![Conversations filtered](../../assets/registry/ui/05b-conversations-filtered-annotated.png)
