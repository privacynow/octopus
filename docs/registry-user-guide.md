# Registry User Guide

This guide is for operators using the browser UI.

The registry is where you manage bots, inspect conversations, review work, and
control skills and guidance.

## Open The Registry

Start with:

```bash
./octopus status
```

Open the `ui:` URL from the output. In a default local deployment that is:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

## Main Areas

### Dashboard

Use `Dashboard` to get oriented quickly.

It shows:

- open conversations
- recent work
- approvals
- agent health
- summary-level activity

Use this page when you want to answer:

- is the stack healthy?
- is work moving?
- is anything waiting for operator action?

### Agents

Use `Agents` to inspect each bot.

You can:

- see whether a bot is connected
- see execution health
- inspect routing skills
- jump into that bot’s conversations

### Conversations

Use `Conversations` to find active threads.

You can:

- open an existing conversation
- inspect activity
- see provider responses and task history

### Conversation Detail

This is the main working screen once a conversation exists.

Use it to:

- read the timeline
- send replies
- inspect tasks and routed work
- manage active conversation skills
- change conversation settings

If a bot needs a skill in one specific chat, activate it from that
conversation’s `Skills` panel.

### Approvals

Use `Approvals` when approval mode is enabled.

You can:

- review pending requests
- approve
- reject

### Tasks

Use `Tasks` to inspect routed or delegated work across conversations.

This is useful when:

- work was routed to another bot
- you need to see cross-conversation progress
- you want to inspect failures or stuck work

### Usage

Use `Usage` for token and cost rollups by conversation.

### Routing

Use `Routing` to inspect skill-derived routing availability and routing policy.

This is where you verify what bots are advertising for cross-bot delegation.

### Skills

Use `Skills` to manage what bots can do.

You can:

- see what skills exist
- see what is installed on a specific bot
- install store skills
- create or import custom skills from the same page
- manage defaults for new conversations
- author custom skills

Important distinction:

- `Installed on this bot` is bot-level
- `Active in this conversation` is conversation-level

Making a skill available on a bot does not turn it on in every conversation.

### Guidance

Use `Guidance` to control provider baseline policy for a bot.

This is not a skill.

You can:

- inspect published guidance
- edit draft guidance
- preview the composed runtime prompt
- publish provider guidance for Claude or Codex

### Protocols

Use `Protocols` when the work is a reusable multi-stage workflow instead of a
one-off conversation.

You can:

- create or import protocol drafts
- validate, diff, publish, and archive protocol definitions
- start runs against a connected bot
- inspect participants, artifacts, transitions, and blocked reasons
- intervene with typed actions: `retry`, `accept`, `send-back`, `cancel`
- inspect protocol issues for blocked runs, invalid contracts, expired
  timeouts, and stuck leases

For the full workflow and runbook, use
[operator-protocol-guide.md](operator-protocol-guide.md).

## Typical Operator Workflows

### Review A New Conversation

1. open `Dashboard` or `Conversations`
2. open the conversation
3. read the timeline
4. if approval is pending, approve or reject

### Add A Skill To A Conversation

1. open the conversation
2. open the `Skills` panel
3. activate the skill
4. if setup is required, submit the requested credential values

### Make A Skill Available On A Bot

1. open `Skills`
2. choose the bot
3. find the skill
4. install or enable it on that bot

### Author A Custom Skill

1. open `Skills`
2. choose the target bot if it is not already implied by the route
3. create a draft or import a package from the main `Skills` page
4. use `Write` for title, description, and instructions
5. use `Setup` for credential requirements
6. use `Review` for validation and lifecycle actions
7. use `Advanced` only for package import/export, provider config, files, and revision history

For the full skills workflow, use
[skills-guide.md](skills-guide.md).

### Update Provider Guidance

1. open `Guidance`
2. choose the provider
3. edit the draft
4. review the runtime preview
5. publish

### Run A Protocol

1. open `Protocols`
2. choose a published definition
3. pick a target bot
4. enter workspace and problem statement
5. start the run
6. monitor the run detail and support-issues views
7. intervene only when the run is blocked or policy requires it

### Author A Protocol

1. open `Protocols`
2. create a draft or import JSON/YAML
3. edit participants, artifacts, stages, and policies
4. validate the draft
5. diff against the published version
6. publish when ready

For authoring details, use
[author-protocol-guide.md](author-protocol-guide.md).

## Reading Status Correctly

When looking at the registry, keep these distinctions in mind:

- a bot can be `connected` but still have an execution fault
- a skill can be `available on this bot` but not active in the current conversation
- a skill can be a default for new conversations without being active in older ones
- guidance is always-on provider policy once published; it is not activated like a skill

## If Something Looks Wrong

Start with:

1. `Dashboard`
2. `Agents`
3. the affected `Conversation`
4. `Approvals` if work is waiting

Then verify on the CLI:

```bash
./octopus status
./octopus doctor <bot>
```
