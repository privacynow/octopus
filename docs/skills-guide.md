# Skills Guide

This guide explains how skills work in practice and how to add or author them.

## What A Skill Is

A skill changes what a bot can do for a task.

Skills can include:

- instructions
- setup requirements
- provider-specific extensions
- supporting files

## The Important Skill States

You will see the same states in the registry UI and in chat:

- `Catalog`
  what skills exist
- `Available on this bot`
  what that bot can use
- `Default for new conversations`
  what gets seeded into new chats for that bot
- `Active in this conversation`
  what is currently turned on in one chat

These are different.

Examples:

- making a skill available on a bot does not activate it everywhere
- making a skill a default does not turn it on in older conversations
- activating a skill in one conversation does not change bot-wide availability

## Skill Sources

### Core

Built into the runtime image.

These are part of the shipped bot environment.

### Store

Installed from the remote skill store onto a bot.

### Custom

Authored inside Octopus and managed through the draft / review / publish
lifecycle.

## Skill Kinds

Skills also have an execution kind:

- `prompt`
  active in a conversation as operator-selected instructions composed into the
  provider run context
- `executable`
  active in a conversation as runtime-orchestrated behavior, not only extra
  prompt text

Both kinds use the same bot-level availability and conversation-level
activation model. The difference is how the runtime applies them once active.

## Add A Store Or Core Skill To A Bot

Use the registry UI:

1. open `Skills`
2. choose the bot
3. find the skill
4. install or enable it so it becomes `Available on this bot`

After that, decide whether to:

- make it a default for new conversations
- activate it only in one conversation

## Activate A Skill In One Conversation

Use the conversation’s `Skills` panel:

1. open the conversation
2. open `Skills`
3. activate the skill
4. if setup is required, submit the requested credential values

This is the right move when the skill is needed only for one chat.

## Make A Skill Default For New Conversations

Use the bot-level skill controls in the registry UI.

This affects:

- future conversations for that bot

It does not automatically update existing chats.

## Skill Setup

Some skills are `Ready` immediately.

Some show `Needs setup`, which usually means credentials or configuration are
required before the skill can be used.

Setup is shared across registry and chat clients. The browser may present the
flow more comfortably, but the underlying rules are the same.

## Author A Custom Skill

Custom skills are authored from the unified registry `Skills` page.

The workspace is still bot-scoped, so you choose the target bot first unless
you opened `Skills` from an agent page and the bot is already bound. Drafts,
publish state, and package export/import all belong to that bot's mutable skill
catalog.

Typical flow:

1. create a draft
2. use `Write` for title, description, and instructions
3. use `Setup` for credential requirements
4. use `Review` to fix validation problems and move the draft through lifecycle
5. use `Advanced` only for package import/export, provider config, files, and revision details

The shared draft package can include:

- `name`
- `display_name`
- `description`
- `body`
- `requirements`
- `provider_config`
- `files`

## Custom Skill Files

Attached files are governed by shared backend policy:

- safe relative paths only
- reserved filenames may not be reused
- only `.sh` files may be executable
- at most 16 files
- 64 KB per file
- 256 KB total

Registry uploads and chat-side file mutations go through the same validation
rules.

## Validation And Publishing

Validation is backend-owned.

That means:

- clients do not invent their own rules
- submit and publish both invoke shared validation
- publish readiness is derived from the draft content

If a draft is invalid, it may still be editable, but submit or publish remain
blocked until the validation problems are fixed.

## Routing Skills

Routing is derived from skills. It is not a second skill system.

A routing skill is a skill that is:

- available on the bot
- runtime-ready
- allowed by routing policy

That derived set is what other bots can discover for delegation.

## Registry And Chat

The registry and Telegram are peer clients over the same backend operations.

The registry is the richer wrapper:

- easier editing
- `Write`, `Setup`, `Review`, and `Advanced` workspace stages
- validation panels and lifecycle actions in `Review`
- package import/export and low-level package details in `Advanced`

Telegram exposes smaller text-oriented operations against the same model.

## If You Need The Lower-Level Model

For the technical package/lifecycle model, use
[skills-model.md](skills-model.md).
