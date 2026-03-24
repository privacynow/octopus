# Registry UI: Conversation detail

[← Manual home](../README.md) · [Prev: Conversation search](conversations-search.md) · [Next: Routed tasks →](tasks.md)

**Route:** `/ui/conversations/{conversation_id}` — also reached from lists or task rows.

**Operator actions**

| Action | Notes |
|--------|--------|
| **Compose** | Operator message; **Enter** to send; session + CSRF. |
| **Cancel** | Conversation cancel via actions API. |
| **Export** | Markdown export download. |
| **Messages only** | Toggle between chat-only and the full event stream. |
| **Scroll up for older history** | Older activity loads automatically when the top sentinel enters view. |

**Timeline:** user/bot lines render as **bubbles**; structured kinds such as **provider request/response**, **tool execution**, **approval**, **delegation**, **task status**, and **error** render as event cards. With **WebSocket** upgrade on `/v1/ws`, new events append live; older history comes from sequence-based `/events` pagination.

![Conversation detail](../../assets/registry/ui/06-conversation-detail-annotated.png)
