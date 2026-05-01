# Telegram Guide

Telegram has two roles in the current product. First, the supported CLI path
creates new local agents as Telegram-backed bot runtimes. Second, Telegram can
be used as an optional chat and control surface over the same registry/runtime
backend as the browser UI. It should not have a separate protocol, skill,
artifact, or guidance model.

Use [GETTING_STARTED.md](GETTING_STARTED.md) if the Telegram-backed agent is
not configured yet. Use [USER_GUIDE.md](USER_GUIDE.md) for the main browser
workflow and [PROTOCOLS.md](PROTOCOLS.md) for protocol concepts.

## Before You Use Telegram

Telegram chat is not required for the browser Registry workflow after an agent
exists. The Telegram-backed bot configuration is currently required to create
that local agent in the CLI. An operator needs:

- a Telegram bot token from BotFather
- a configured Octopus agent that uses that token
- provider authentication for the model provider that agent uses
- a healthy Registry connection

New users should confirm the browser Registry works first. It is easier to see
agent health, run state, and artifacts there.

## First Use

1. Open Telegram.
2. Find the configured bot.
3. Send a normal message.

Examples:

- `summarize this repo`
- `help me debug this error`
- `draft a response to this issue`

If approval mode is enabled, execution may pause until approval is granted in
Telegram or the Registry UI.

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

## Skills

Telegram uses the same skill backend as the Registry UI.

Useful commands:

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

Remember the skill states:

- available on this bot
- default for new conversations
- active in this conversation
- routing skills

Admin permissions are required for store install/update/uninstall and custom
skill approval/publish/archive operations.

## Guidance

Guidance is provider baseline policy. It is not a skill.

Examples:

```text
/guidance show codex
/guidance preview codex
```

Depending on permissions, Telegram may expose draft edit, submit, approve,
reject, publish, and archive flows. These must use the same backend lifecycle
as the Registry UI.

## Protocols

Telegram can list, start, inspect, watch, and control protocols that already
exist in the Registry. It can also use Auto Protocol to generate, review,
apply, publish, and run a generated protocol from chat. The browser Registry
remains the richer editor for detailed manual changes, package import/export,
and visual review.

Current command shape:

```text
/protocol list
/protocol recent
/protocol auto <requirement>
/protocol auto modify latest|<session_id> <change request>
/protocol auto status latest|<session_id>
/protocol improve <slug> <change request>
/protocol start <slug> <problem statement> [--context <text>] [--constraints <text>] [--workspace <ref>]
/protocol status latest|<number|short_id>
/protocol artifacts latest|<number|short_id>
/protocol artifacts <run> download <artifact_number|artifact_key>
/protocol preview <run> <artifact_number|artifact_key>
/protocol export latest|<number|short_id>
/protocol watch latest|<number|short_id>
/protocol unwatch latest|<number|short_id>
/protocol retry <run> [reason]
/protocol accept <run> [reason]
/protocol send-back <run> [reason]
/protocol cancel <run> [reason]
```

Behavior:

- `recent` lists visible runs with numbers, status, current stage, and short
  ids.
- `auto` generates a protocol from a high-level requirement and returns a
  compact review card with Summary, Stages, Artifacts, Warnings, Apply Draft,
  Publish, and Publish & Run buttons. Publish and run buttons appear only when
  validation and assignments are ready.
- `auto modify latest` revises the most recent generated protocol in this chat.
- `auto status latest` shows the latest generated protocol again.
- `improve` creates a draft revision proposal for an existing published
  protocol.
- Follow-up commands can use `latest`, the shown number, or the short id.
- `latest` is local to the current chat. Use `/protocol recent` if another
  chat or bot started the run.
- `start` creates a registry protocol run and starts watching it from the chat.
- `start` uses the same shared SDK launch model as the Registry UI.
- Optional launch fields are parsed from `--context`, `--constraints`, and
  `--workspace`; each option consumes text until the next option marker.
- Protocol-authored custom run input keys can be passed with the same
  `--custom-key <text>` shape.
- `status` reports registry run state and deep links when available.
- `artifacts` lists declared and produced artifacts compactly.
- `preview` opens a rendered preview for text and Markdown artifacts when
  available, with open/download fallbacks.
- `export` returns a JSON run export.
- Destructive or high-impact actions may require confirmation.

Telegram messages may include action buttons for Status, Artifacts, Preview,
Open, Send, Export, Watch, Stop updates, Apply Draft, Publish, and Publish &
Run. These buttons call the same registry-backed protocol service as the slash
commands.

## Artifacts

If a command reports produced artifacts, users should be able to preview, open,
or download them through registry artifact routes when available.

Package artifacts should expose the default open action when the package
contains a browser entry such as `index.html`, and a contents action when a
directory browser is useful.

If a document is declared but not produced yet, Telegram should say that
clearly. If an available artifact cannot be opened from the Registry, treat that
as a product issue.

## If The Bot Seems Broken

Tell an operator:

- which bot you used
- which Telegram chat
- what command or message you sent
- whether approval was pending
- whether a protocol run id was shown
- whether artifacts were expected

Operators should check:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

They should also inspect the Registry conversation, run, linked work, and
artifacts.
