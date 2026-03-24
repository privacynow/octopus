# Registry UI: Conversation detail

[← Manual home](../README.md) · [Prev: Conversation search](conversations-search.md) · [Next: Routed tasks →](tasks.md)

**Route:** `/ui/conversations/{conversation_id}` — also reached from lists or task rows.

**Operator actions**

| Action | Notes |
|--------|--------|
| **Compose** | Operator message; **Enter** to send; session + CSRF. |
| **Cancel** | Conversation cancel via actions API. |
| **Export** | Markdown export download. |
| **Conversation** | Default view: replies, approvals, delegation progress, task updates, and problems. |
| **Full activity** | Shows every stored event, including provider and tool activity. |
| **Scroll up for older history** | Older activity loads automatically when the top sentinel enters view. |

**Timeline:** user/bot lines render as **bubbles**. The default view is now human-first: approvals, delegation updates, task progress, and errors stay visible, while lower-level provider/tool activity moves behind the **Full activity** toggle. With **WebSocket** upgrade on `/v1/ws`, new events append live; older history comes from sequence-based `/events` pagination.

![Conversation detail](../../assets/registry/ui/06-conversation-detail-annotated.png)
