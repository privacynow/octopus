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
Telegram runs and inspects protocols that have already been authored and
published in the Registry UI; protocol creation, editing, and publishing remain
Registry workflows.

Current command shape:

```text
/protocol list
/protocol recent
/protocol start <slug> <problem statement> [--context <text>] [--constraints <text>] [--expected-outputs <text>] [--workspace <ref>]
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

- `recent` lists visible protocol runs with numbers, status, current stage, and
  short ids. Follow-up commands can use `latest`, the shown number, or the
  short id instead of a full run id.
- `latest` is local to the current chat. When another bot or chat started the
  run, use `/protocol recent` and then the shown number or short id.
- `start` creates a registry protocol run and starts watching it from the chat.
- `start` uses the same shared SDK launch model as Registry UI. The simple
  historical form is still valid. Optional launch fields are parsed from
  `--context`, `--constraints`, `--expected-outputs`, and `--workspace`; each
  option consumes text until the next option marker.
- `status` reports registry run state and deep links when available.
- `artifacts` lists declared and produced artifacts compactly, with numbered
  preview/open/download actions for artifacts the registry can serve.
- `preview` opens a rendered preview for text and Markdown artifacts when
  available, plus open/download fallbacks.
- `export` returns a JSON run export.
- Telegram messages show short run references for normal use. Export filenames
  and browser URLs may still contain the full canonical run id for traceability.
- Protocol messages include action buttons where Telegram supports them:
  Status, Artifacts, named Preview/Open/Send actions for each artifact, Export,
  Watch, and Stop updates. These buttons call the same registry-backed protocol
  service as the slash commands; they are not a separate protocol execution
  path.
- Partial protocol requests prefer progressive discovery. For example,
  `/protocol status`, `/protocol artifacts`, `/protocol preview`, `/protocol
  export`, `/protocol watch`, and `/protocol unwatch` can use the current
  chat's latest visible run when a run is not supplied, and artifact actions
  guide the user to choose from the artifact list when needed.
- destructive or high-impact actions may require confirmation.
- stage and terminal notifications come from registry run state, not
  Telegram-only state.

## Routed Work

If one bot delegates work to another, the parent Telegram thread remains the
main user-facing thread. Registry work/task records may exist underneath, but
users should not have to chase unrelated child conversations to understand the
main result.

## Artifacts

If a command reports produced artifacts, users should be able to preview, open,
or download them through registry artifact routes when available. Package
artifacts should expose the default app/open action when the package contains a
browser entry such as `index.html`, and a separate contents action when a
directory browser is useful. If a document is declared but not produced yet,
Telegram should say that clearly.

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
