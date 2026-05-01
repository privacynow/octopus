# User Guide

This guide is for people using Octopus through the browser Registry UI. It
starts with the smallest useful workflow, then introduces protocols, skills,
Telegram, and operations only when they become relevant.

If you are only operating the stack, use [OPERATIONS.md](OPERATIONS.md). If you
are designing workflows, use [PROTOCOLS.md](PROTOCOLS.md).

## The Product In One Minute

Octopus gives you a shared control plane for AI agents.

- Use `Conversations` for open-ended work.
- Use `Protocols` when the work should follow repeatable stages.
- Use `Runs` to inspect a protocol execution.
- Use `Artifacts` to open, preview, or download generated outputs.
- Use `Skills` to make reusable capabilities available to agents.
- Use `Guidance` for provider baseline policy.
- Use `Dashboard`, `Routing`, and `Usage` when you need operational context.

## Core Vocabulary

| Term | Meaning |
| --- | --- |
| Agent | A bot runtime connected to the registry. |
| Conversation | A thread where a user and agent exchange messages. |
| Skill | Reusable instructions or tooling an agent can use. |
| Guidance | Provider-level policy; not a skill. |
| Protocol | A reusable staged workflow. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced file/output. |
| Routing | How Octopus decides which agent receives delegated or staged work. |

## Start And Open

From the repository root:

```bash
./octopus
./octopus status
```

Open the Registry URL printed by `./octopus status`. The default local URL is:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

Before doing real work, confirm:

- `Work -> Agents` shows at least one connected agent
- the target agent is execution-healthy
- `Operations -> Dashboard` does not show a relevant blocking issue

## First 20 Minutes

1. Open `Work -> Agents`.
2. Confirm one agent is connected and execution-healthy.
3. Open `Work -> Conversations`.
4. Start a conversation with that agent.
5. Send a short non-sensitive request.
6. Confirm the response appears in the conversation timeline.
7. Open `Build -> Protocols`.
8. Inspect an existing protocol or create a simple blank protocol.
9. Run a published protocol.
10. Open the run from `Work -> Runs`.
11. Check `Stages`, `Artifacts`, and `Audit`.

This path proves the basic product without requiring a customer scenario,
Telegram, or direct database access.

## Navigation

The Registry is grouped by job.

| Area | Entries | Use it for |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Active collaboration, protocol execution, artifacts, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow design and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Health, routing diagnostics, and usage visibility. |

`Tasks` and `Approvals` may appear through links. They are part of the execution
lineage, not a separate primary app to learn first.

## Conversations

Use conversations for ad hoc work.

You can:

- open an existing thread
- start a new thread with an agent
- send registry-origin messages where supported
- inspect timeline activity
- see linked work and protocol runs
- manage conversation-specific skill activation

If a conversation has linked work but no clear way to inspect the result, treat
that as a product issue.

## Agents

Use `Work -> Agents` to answer:

- which agents are connected?
- which agents are execution-healthy?
- what provider and role is each agent using?
- what routing skills does an agent advertise?
- can I open or start a conversation with this agent?

Connected is not the same as execution-healthy. Use the health labels and
`./octopus doctor <bot>` when the distinction matters.

## Skills

Skills are reusable instructions or tools. The same skill model is used by the
Registry UI, Telegram, protocol stages, and routing.

| Skill state | Meaning |
| --- | --- |
| Catalog | Skills known to Octopus. |
| Available on this bot | Skills one agent runtime can use. |
| Default for new conversations | Available skills seeded into future conversations. |
| Active in this conversation | Skills enabled in one existing thread. |
| Routing skills | Derived routing projection used for delegation and stage assignment. |

Common workflows:

1. Open `Build -> Skills`.
2. Choose the agent/bot context.
3. Search or filter rather than scanning long lists.
4. Install, enable, activate, import, export, or author a skill where your
   permissions allow it.

Making a skill available on a bot does not automatically activate it in every
old conversation. Setting a default affects new conversations, not existing
ones.

## Guidance

Guidance is provider baseline policy. It is not a skill and it is not activated
per conversation.

Typical workflow:

1. Open `Build -> Guidance`.
2. Choose the provider or agent context.
3. Edit the draft.
4. Preview composed runtime guidance.
5. Submit, approve, publish, or archive where permitted.

## Protocols And Runs

Use protocols when the work needs repeatable stages, assigned responsibilities,
review decisions, or declared artifacts.

For detailed authoring and run behavior, use [PROTOCOLS.md](PROTOCOLS.md).

The short version:

1. Open `Build -> Protocols`.
2. Create from blank or copy a user-authored template.
3. Add stages, assignment, transitions, and artifacts.
4. Validate and publish.
5. Start a run from the published version.
6. Inspect the run in `Work -> Runs`.

The launch dialog collects run-specific context. Unless a protocol defines
custom `metadata.run_inputs`, the shared fields are workspace, goal, additional
context, and constraints. Those inputs help the agents execute the run; they do
not rewrite the published stage contract or artifact paths.

## Artifacts

Artifacts are the visible outputs of work.

An artifact can be:

- declared but not produced yet
- available
- unavailable from the current host
- expired or deleted

Where supported, artifact actions should include preview, open, download, copy
path, or package browsing. Missing or inconsistent artifact actions are product
issues, not a normal user burden.

## Telegram

Telegram is optional. It is a peer client over the same registry/runtime
backend, not a separate product model.

Use Telegram for quick chat, status checks, protocol run controls, and artifact
links when a Telegram bot token is configured. Use [TELEGRAM.md](TELEGRAM.md)
for command details.

## If Something Looks Wrong

Start in the Registry:

1. `Operations -> Dashboard`
2. affected `Conversation`
3. affected `Run`
4. affected `Agent`
5. linked work/task detail
6. artifact actions

Then ask an operator to check:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

Useful status distinctions:

- connected does not always mean execution-healthy
- running should mean active work, not stale work
- skill availability, defaults, active conversation skills, and routing skills
  are related but distinct
- a protocol can declare an artifact before any stage produces it
- Registry and Telegram should agree about the same run
