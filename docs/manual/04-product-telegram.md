# Product: Telegram

[← Manual home](README.md) · [Prev: Registry UI](03-operator-registry.md) · [Next: Integration →](05-integration-api.md)

Chat UX is implemented in [`app/channels/telegram/`](../../app/channels/telegram/). Screenshots below are **illustrative mocks** (not a live Telegram client) with the same structure as real chats.

## Help and normal messages

`/help` lists commands; **plain text** (not starting with `/`) is sent to the agent as the main conversation.

![Help and user message](../assets/manual/tg-01-start-help-annotated.png)

## Settings

`/settings` shows chat-specific options; inline buttons use callback prefixes like `setting_*`.

![Settings panel](../assets/manual/tg-02-settings-annotated.png)

## Skills

`/skills` lists active skills and catalog entries; `/skills add`, `/skills setup` configure credentials when prompted.

![Skills](../assets/manual/tg-03-skills-annotated.png)

## Approvals (safe mode)

When approval gates are on, the bot may present a **plan** before executing. Operators use `/approval`, `/approve`, `/reject`, `/cancel` as documented in the in-chat help.

![Approval flow](../assets/manual/tg-04-approval-annotated.png)

## Runtime modes (standalone vs shared worker)

Command registration differs between **`runtime_mode`** values — some commands are only registered on the **standalone** PTB process; **shared** mode routes several commands through the worker dispatcher.

![Runtime modes](../assets/manual/tg-05-runtime-modes-annotated.png)

**Source of truth:** [`bootstrap.py`](../../app/channels/telegram/bootstrap.py).

## Commands (quick reference)

Always refer to `/help` on your deployment. Root [README.md](../../README.md) lists a practical subset for end users.

---

**Callbacks** (inline buttons): `retry_*`, `approval_*`, `delegation_*`, `recovery_*`, `setting_*`, `skill_add_*`, `skill_update_*`, `clear_cred_*`, expand/collapse — see [flows-catalog.md §4](../flows-catalog.md#4-product-telegram-chat-end-user--admin).
