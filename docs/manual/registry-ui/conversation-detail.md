# Registry UI: Conversation detail

[← Manual home](../README.md) · [Prev: Conversation search](conversations-search.md) · [Next: Routed tasks →](tasks.md)

**Route:** `/ui/conversations/{conversation_id}` — also reached from lists or task rows.

**Operator actions**

| Action | Notes |
|--------|--------|
| **Compose** | Operator message; **Enter** to send; session + CSRF. |
| **Cancel** | Conversation cancel via actions API. |
| **Export** | Markdown export download. |
| **Messages only** | Toggle vs showing all event kinds. |
| **Load older** | Paginated history when the API exposes a cursor. |

**Timeline:** user/bot lines as **bubbles**; other kinds as **collapsible** cards. With **WebSocket** upgrade on `/v1/ws`, new events can append live; otherwise history loads via REST on navigation.

![Conversation detail](../../assets/registry/ui/05-conversation-detail-annotated.png)
