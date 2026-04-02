# Product: Telegram

Manual: [Home](README.md) · Previous: [Registry UI deep links](registry-ui/deep-links.md) · Next: [Registry HTTP API](05-integration-api.md)

Chat handling lives under [`app/channels/telegram/`](../../app/channels/telegram/). **`/help`** and **`/start`** list commands; **plain text** (not starting with `/`) is the main conversation with the agent. **`/settings`** uses inline buttons (`setting_*` callbacks). **`/skills`** exposes the same shared skill backend as the registry UI; **`/approval`**, **`/approve`**, **`/reject`**, **`/cancel`** apply when approval gates are on.

The chat skill vocabulary matches the registry UI:

- `Catalog`
- `Installed on bot`
- `Active in conversation`
- `Core / Store / Custom`
- `Needs setup / Ready`

Chat and browser are peer clients over the same backend operations. They may
bundle steps differently, but they must not diverge in rules or outcomes.

![Help and a normal user message](../assets/product/telegram-help.svg)

Inline button callbacks include `retry_*`, `approval_*`, `delegation_*`, `recovery_*`, `setting_*`, `skill_add_*`, `skill_update_*`, `clear_cred_*`, expand/collapse — indexed in [flows-catalog.md §4](../flows-catalog.md#4-product-telegram-chat-end-user--admin).

## Runtime modes

The SDK still models Telegram behavior across three config axes:

- **`BOT_AGENT_MODE`** — `standalone` vs `registry`
- **`BOT_RUNTIME_MODE`** — `local` vs `shared`
- **`BOT_PROCESS_ROLE`** — `all`, `webhook`, or `worker`

For the shipped Telegram runtime in this repo, the product profile is stricter
than the generic SDK:

- Telegram runs in `BOT_AGENT_MODE=registry`
- startup requires configured registry connections
- those connections must collectively provide full participant coverage across
  `channel` and `coordination`

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
