# Registry User Guide

This guide describes the current browser registry UI.

For protocol-specific operator and author workflows, see
[operator-protocol-guide.md](operator-protocol-guide.md) and
[author-protocol-guide.md](author-protocol-guide.md).

Open the registry URL printed by:

```bash
./octopus status
```

Default local URL:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

## Navigation

The registry is grouped by job.

### Work

Use Work for active collaboration and execution state.

Current entries:

- `Conversations`
- `Runs`
- `Agents`

`Tasks` still exists as routed work behind the scenes, but it is not a primary
navigation item. Open linked work from conversations, runs, dashboard cards, or
direct task links.

### Build

Use Build to define reusable behavior.

Current entries:

- `Protocols`
- `Skills`
- `Guidance`

Skills are the UI-facing catalog for runtime skills. Guidance is provider
policy, not a skill.

Templates are managed inside Protocols. There is no separate gallery/templates
menu in the current UI.

### Operations

Use Operations for platform inspection.

Current entries:

- `Dashboard`
- `Routing`
- `Usage`

Approvals still exist, but are surfaced from Dashboard or direct links rather
than as primary navigation.

## Conversations

Use `Conversations` to inspect and continue registry-origin or bot-origin
threads.

You can:

- open existing conversations
- inspect timeline activity
- send registry-origin messages where supported
- see linked work and linked protocol runs
- switch to conversation task/work views when a thread has delegated or routed
  work
- manage conversation-specific skill activation

If a conversation appears empty while work or runs are linked, treat that as a
product bug. The intended model is that related work and outputs are visible
from the conversation.

## Runs

Use `Runs` to inspect protocol executions.

Run detail is organized around:

- Overview
- Stages
- Artifacts
- Audit

Use Runs when you need to answer:

- what protocol is executing?
- what stage is active?
- what work was created?
- what artifacts were declared or produced?
- is the run blocked, stale, failed, completed, or waiting?
- what operator actions are available?

Actions such as retry, accept, send-back, cancel, and export are contextual.
If an action appears where its purpose is unclear, that is a UI issue to fix.

## Agents

Use `Agents` to inspect bots/agents.

You can:

- see connection and execution health
- open an agent detail
- start or open conversations for the agent
- inspect advertised/routing skills
- reveal generated work when needed

The agent page should summarize skills/skills instead of showing a wall
of names. If generated/test agents dominate the list, use filters and treat the
default list as needing cleanup.

## Protocols

Use `Protocols` for authoring reusable workflows and managing templates.

You can:

- create from blank
- copy from a saved user-authored template when one exists
- edit stages
- add a stage below the current stage
- remove stages
- configure assignment
- declare artifacts
- inspect routing/transition flow
- show the workflow map on demand
- publish a protocol
- publish a protocol as a user-authored template
- start or inspect runs

Protocols do not ship with prepackaged starter workflows in the default
customer path. To reuse a workflow, create it from blank, publish it, then use
`Publish as template` from the protocol actions. That saved template can be
copied into a new editable protocol later without changing the original.

Standard authoring should focus on:

- stage title/instructions
- assignment
- routing
- artifacts
- rehearsal/run feedback

Standard authors should not see internal runtime controls such as custom
runtime selectors, raw stage keys, max rounds, or timeout fields. Operator-only
controls must stay gated.

Current publish validation still requires stages to resolve an assignment. Draft
authoring may allow incomplete steps while the author is building.

## Skills

Use `Skills` to manage skills.

The same underlying skill model supports:

- catalog browsing
- bot availability
- defaults for new conversations
- active conversation skills
- routing skill projection
- custom skill drafts/lifecycle

Generated skills should not dominate the default catalog. Use explicit
filters when you need generated/rehearsal entries.

## Guidance

Use `Guidance` to manage provider baseline policy.

Guidance affects provider/runtime behavior once published. It is not activated
like a conversation skill.

Typical flow:

1. choose agent/provider context
2. edit draft guidance
3. preview composed runtime prompt
4. submit/approve/publish where permitted

## Dashboard

Use `Dashboard` for operational orientation.

It summarizes:

- approvals
- active work
- work needing follow-up
- recent completed work
- protocol runs
- protocol issues
- agent health

Dashboard cards can link into hidden-but-valid surfaces such as Approvals and
Tasks.

## Routing

Use `Routing` to inspect routing policy and skill-derived routing availability.

Routing is operational. It should explain why an agent can or cannot receive
delegated work.

## Usage

Use `Usage` for usage rollups.

## Reading Status Correctly

Keep these distinctions in mind:

- connected does not always mean execution-healthy
- running must mean actual active work; stale or stuck work should be labeled
  honestly
- a skill can be available on a bot but inactive in a conversation
- a skill default applies to new conversations, not old ones
- a protocol run can create routed tasks as stage execution work
- a declared artifact may not be produced yet
- a produced artifact should be previewable/downloadable wherever it is linked

## If Something Looks Wrong

Start in the registry:

1. Dashboard
2. affected Conversation
3. affected Run
4. affected Agent
5. linked Work/Task detail
6. Artifacts section

Then use CLI:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```
