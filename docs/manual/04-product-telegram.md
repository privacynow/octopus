# Product: Telegram

Manual: [Home](README.md) · Previous: [Registry UI deep links](registry-ui/deep-links.md) · Next: [Registry HTTP API](05-integration-api.md)

Chat handling lives under [`app/channels/telegram/`](../../app/channels/telegram/). **`/help`** and **`/start`** list commands; **plain text** (not starting with `/`) is the main conversation with the agent. **`/settings`** uses inline buttons (`setting_*` callbacks). **`/skills`** lists and activates skills; **`/approval`**, **`/approve`**, **`/reject`**, **`/cancel`** apply when approval gates are on.

![Help and a normal user message](../assets/product/telegram-help.svg)

Inline button callbacks include `retry_*`, `approval_*`, `delegation_*`, `recovery_*`, `setting_*`, `skill_add_*`, `skill_update_*`, `clear_cred_*`, expand/collapse — indexed in [flows-catalog.md §4](../flows-catalog.md#4-product-telegram-chat-end-user--admin).

## Runtime modes

Telegram behavior is shaped by three different config axes:

- **`BOT_AGENT_MODE`** — `standalone` vs `registry`
- **`BOT_RUNTIME_MODE`** — `local` vs `shared`
- **`BOT_PROCESS_ROLE`** — `all`, `webhook`, or `worker`

Command registration specifically depends on **`BOT_RUNTIME_MODE`**:

- in non-shared mode, the Telegram bootstrap registers the full direct command
  set
- in shared mode, commands such as `/new`, `/approval`, `/approve`,
  `/reject`, `/skills`, `/cancel`, `/project`, `/policy`, and `/model` are
  routed through the shared command dispatcher instead of being handled as
  standalone-process Telegram actions

See [`bootstrap.py`](../../app/channels/telegram/bootstrap.py) for the exact
registration split.

Practical command list for end users: root [README.md](../../README.md).
