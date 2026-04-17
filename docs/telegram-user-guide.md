# Telegram User Guide

This guide is for people using Octopus through Telegram.

For most users, Octopus is just a bot in a chat. You send a message, the bot
does work, and the reply comes back in the same conversation.

## First Use

1. open Telegram
2. find your bot
3. send a normal message

Examples:

- "summarize this repo"
- "help me debug this error"
- "draft a response to this issue"

If the bot is in approval mode, the request may pause until an operator
approves it.

## Basic Commands

Start with:

- `/help`

Common commands you may see:

- `/project <name>`
- `/skills ...`
- `/guidance ...`
- `/protocol ...`

The exact command set depends on how the bot is configured, but `/help` is the
entrypoint.

## Working With Projects

If the bot has multiple workspaces or projects attached, switch with:

```text
/project <name>
```

Use this when you want the bot to work in a specific mounted workspace.

## Approvals

If approval mode is enabled:

- your request may pause
- an approval request appears
- execution starts only after approval

Approvals may be handled:

- in Telegram
- in the registry UI

## Skills In Telegram

Telegram exposes the same shared skill backend as the registry UI.

The most important ideas are:

- a skill can be available on the bot
- a skill can be active in the current conversation
- those are not the same thing

Typical skill operations in chat include:

- inspect skills
- add or remove a skill from the conversation
- install store skills
- export a custom skill package
- import a custom skill package into a draft

Permission and capability gating still matters:

- `list`, `add`, `remove`, `clear`, `export`, and `import` are the normal
  conversation and draft-oriented operations when the bot exposes them
- store install, uninstall, and update actions are admin-only
- custom-skill approve, reject, publish, and archive actions are admin-only

Examples you may use:

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

The exact subcommands may evolve, so use `/help` or `/skills` to see the live
shape.

## Guidance In Telegram

Guidance is provider baseline policy, not a skill.

Telegram can expose guidance flows such as:

- show published guidance
- edit a draft
- preview the composed runtime prompt
- publish the draft

In the shipped Telegram surface:

- `show`, `preview`, `history`, `edit`, and `submit` use the shared backend
  lifecycle directly
- `approve`, `reject`, `publish`, and `archive` are admin-only

Typical examples:

```text
/guidance show codex
/guidance preview codex
```

## Protocols In Telegram

Telegram exposes the same shared protocol backend as the registry UI.

Current commands:

```text
/protocol list
/protocol start <slug> <problem statement>
/protocol status <run_id>
/protocol watch <run_id>
/protocol unwatch <run_id>
/protocol retry <run_id> [reason]
/protocol accept <run_id> [reason]
/protocol send-back <run_id> [reason]
/protocol cancel <run_id> [reason]
```

Important behavior:

- `start` automatically begins watching the new run in that Telegram chat
- `watch` and `unwatch` control follow-up notifications explicitly
- `status` includes the registry deep link when one is available
- `send-back` and `cancel` require an explicit `confirm` token plus a short
  reason before the action is applied
- stage-change and terminal notifications come from the shared registry run
  state, not a Telegram-only state machine

Examples:

```text
/protocol start software-engineering Build a secure review workflow for this repo
/protocol status run-123
/protocol send-back run-123 confirm tighten the artifact contract for plan.md
```

For the full operator workflow and runbook, use
[protocol-operator-guide.md](protocol-operator-guide.md).

## Routed Work

If one bot delegates work to another, the parent conversation still stays in
the same Telegram thread. You do not need to chase separate child threads just
to get the main answer.

## If The Bot Seems Broken

What you should tell an operator:

- what bot you used
- which Telegram chat it happened in
- whether the request is waiting for approval
- whether the bot stopped replying entirely
- whether it looks like a provider-auth problem

Operators should then check:

- the registry UI
- `./octopus status`
- `./octopus doctor <bot>`
