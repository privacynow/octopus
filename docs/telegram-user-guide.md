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
- inspect or replace a custom skill package

Examples you may use:

```text
/skills
/skills add <name>
/skills remove <name>
/skills package <name>
/skills package <name> <json>
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

Typical examples:

```text
/guidance show codex
/guidance preview codex
```

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
