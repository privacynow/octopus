# Product: Telegram

[← Manual home](README.md) · [Prev: Registry UI — deep links](registry-ui/deep-links.md) · [Next: Integration →](05-integration-api.md)

Chat handling lives under [`app/channels/telegram/`](../../app/channels/telegram/). **`/help`** and **`/start`** list commands; **plain text** (not starting with `/`) is the main conversation with the agent. **`/settings`** uses inline buttons (`setting_*` callbacks). **`/skills`** lists and activates skills; **`/approval`**, **`/approve`**, **`/reject`**, **`/cancel`** apply when approval gates are on.

![Help and a normal user message](../assets/product/telegram-help.svg)

Inline button callbacks include `retry_*`, `approval_*`, `delegation_*`, `recovery_*`, `setting_*`, `skill_add_*`, `skill_update_*`, `clear_cred_*`, expand/collapse — indexed in [flows-catalog.md §4](../flows-catalog.md#4-product-telegram-chat-end-user--admin).

## Runtime modes

Command availability depends on **`runtime_mode`** (standalone vs shared worker). See [`bootstrap.py`](../../app/channels/telegram/bootstrap.py) for what gets registered.

Practical command list for end users: root [README.md](../../README.md).
