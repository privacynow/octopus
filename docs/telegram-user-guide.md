# Telegram User Guide

This guide describes the current Telegram surface.

Telegram is a peer client over the same registry/runtime backend as the browser
UI. It is not supposed to own a separate protocol, skill, artifact, or guidance
model.

For operator-level protocol concepts, see
[operator-protocol-guide.md](operator-protocol-guide.md).

## First Use

1. open Telegram
2. find your configured bot
3. send a normal message

Examples:

- `summarize this repo`
- `help me debug this error`
- `draft a response to this issue`

If approval mode is enabled, execution may pause until approval is granted in
Telegram or the registry UI.

## Help

Use:

```text
/help
```

The live command set depends on bot configuration and permissions.

Common command families:

- `/project`
- `/skills`
- `/guidance`
- `/protocol`

## Projects

If the bot has multiple workspaces/projects:

```text
/project <name>
```

Use this before asking the bot to work in a specific mounted workspace.

## Skills In Telegram

Telegram uses the same skill backend as the registry UI.

Important distinctions:

- available on this bot
- default for new conversations
- active in this conversation
- routing skills

Examples:

```text
/skills
/skills list
/skills add <name>
/skills remove <name>
/skills export <name>
/skills export <name> published
/skills import
/skills import <target-name>
```

Admin permissions are required for store install/update/uninstall and custom
skill approval/publish/archive operations.

## Guidance In Telegram

Guidance is provider baseline policy. It is not a skill.

Examples:

```text
/guidance show codex
/guidance preview codex
```

Depending on permissions, Telegram may expose draft edit, submit, approve,
reject, publish, and archive flows. These must use the same backend lifecycle
as the registry UI.

## Protocols In Telegram

Telegram exposes protocol operations backed by the registry protocol service.

Current command shape:

```text
/protocol list
/protocol start <slug> <problem statement>
/protocol status <run_id>
/protocol artifacts <run_id>
/protocol export <run_id>
/protocol watch <run_id>
/protocol unwatch <run_id>
/protocol retry <run_id> [reason]
/protocol accept <run_id> [reason]
/protocol send-back <run_id> [reason]
/protocol cancel <run_id> [reason]
```

Behavior:

- `start` creates a registry protocol run and starts watching it from the chat.
- `status` reports registry run state and deep links when available.
- `artifacts` lists declared and produced artifacts and should expose download
  links for artifacts the registry can serve.
- `export` returns a JSON run export.
- destructive or high-impact actions may require confirmation.
- stage and terminal notifications come from registry run state, not
  Telegram-only state.

## Routed Work

If one bot delegates work to another, the parent Telegram thread remains the
main user-facing thread. Registry work/task records may exist underneath, but
users should not have to chase unrelated child conversations to understand the
main result.

## Artifacts

If a command reports produced artifacts, users should be able to download them
through registry artifact routes when available. If a document is declared but
not produced yet, Telegram should say that clearly.

Any artifact that appears as available in Telegram but cannot be opened from
the registry is a product gap to fix.

## If The Bot Seems Broken

Tell an operator:

- which bot you used
- which Telegram chat
- what command/message you sent
- whether approval was pending
- whether a protocol run id was shown
- whether artifacts were expected

Operators should check:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

They should also inspect the registry conversation, run, linked work, and
artifacts.
