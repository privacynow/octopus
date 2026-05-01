# User Guide

This guide is for people using Octopus through the browser Registry UI.

It assumes Octopus is already installed and running. If you have not opened the
Registry yet, start with [GETTING_STARTED.md](GETTING_STARTED.md).

Use this guide when you want to understand the product: how to talk to agents,
use skills, run protocols, inspect outputs, and decide what to do when work
looks stuck.

## The Product In One Minute

Octopus is a shared control center for AI agent work.

- Use `Conversations` for open-ended work.
- Use `Agents` to see who is available and healthy.
- Use `Protocols` for repeatable staged workflows.
- Use `Runs` to watch protocol execution and inspect what happened.
- Use `Artifacts` to preview, open, or download outputs.
- Use `Skills` to make reusable capabilities available to agents.
- Use `Guidance` for provider-level policy.
- Use `Dashboard`, `Routing`, and `Usage` when you need operational context.

## Core Vocabulary

| Term | Meaning |
| --- | --- |
| Registry | The browser UI and backend that coordinate agents, runs, artifacts, and health. |
| Agent | A configured bot runtime that can receive work. |
| Conversation | A thread where a user and agent exchange messages. |
| Skill | Reusable instructions or tooling an agent can use. |
| Guidance | Provider-level policy; not a conversation skill. |
| Protocol | A reusable staged workflow. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced file/output. |
| Routing | How Octopus decides which agent receives delegated or staged work. |

## First 20 Minutes

This path proves the basic product without requiring a customer scenario,
Telegram, or direct database access.

1. Open the Registry URL from `./octopus status`.
2. Open `Work -> Agents`.
3. Confirm one agent is connected and execution-healthy.
4. Open `Work -> Conversations`.
5. Start a conversation with that agent.
6. Send a short non-sensitive request.
7. Confirm the response appears in the conversation timeline.
8. Open `Build -> Protocols`.
9. Inspect an existing protocol or create a simple blank protocol.
10. Run a published protocol.
11. Open the run from `Work -> Runs`.
12. Check the current status, stages, artifacts, and audit history.

If step 3 fails, the product is not ready for normal use yet. Ask the operator
to check [GETTING_STARTED.md](GETTING_STARTED.md) or
[OPERATIONS.md](OPERATIONS.md).

## Navigation

The Registry is grouped by job.

| Area | Entries | Use it for |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Active collaboration, protocol execution, artifacts, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow design and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Health, routing diagnostics, and usage visibility. |

`Tasks` and `Approvals` may appear through links. They are part of execution
lineage, not a separate primary app to learn first.

## Talk To An Agent

Use conversations for ad hoc work: questions, drafting, debugging, planning, or
one-off analysis.

1. Open `Work -> Conversations`.
2. Choose an existing conversation or start a new one.
3. Pick a healthy agent when the UI asks for one.
4. Send a clear request.
5. Watch the timeline for progress and output.
6. Open linked work, runs, or artifacts when they appear.

Good first requests are small and non-sensitive. For example:

```text
Summarize what this workspace appears to contain.
```

If a conversation mentions linked work but there is no clear way to inspect the
result, treat that as a product issue.

## Check Agent Health

Open `Work -> Agents` to answer:

- which agents are connected?
- which agents can execute work right now?
- which provider and role is each agent using?
- what skills or routing labels does an agent advertise?
- can I open or start a conversation with this agent?

Connected means the Registry can see the agent. Execution-healthy means the
agent can actually do model-backed work. Those are related, but not the same.

If an agent is connected but not execution-healthy, provider authentication is a
common cause. An operator can check `./octopus status` or
`./octopus doctor <bot>`.

## Use Skills

Skills are reusable instructions or tools. They can support conversations,
protocol stages, Telegram, and routing.

| Skill state | Meaning |
| --- | --- |
| Catalog | Skills known to Octopus. |
| Available on this bot | Skills one agent runtime can use. |
| Default for new conversations | Skills seeded into future conversations. |
| Active in this conversation | Skills enabled in one existing thread. |
| Routing skills | Derived routing projection used for delegation and stage assignment. |

Common workflow:

1. Open `Build -> Skills`.
2. Choose the agent or bot context.
3. Search or filter instead of scanning long lists.
4. Install, enable, activate, import, export, or author a skill where your
   permissions allow it.
5. Return to the conversation or protocol that needs the skill.

Making a skill available on a bot does not automatically activate it in every
old conversation. Setting a default affects new conversations, not existing
ones.

## Use Guidance

Guidance is baseline policy for a model provider, such as Codex or Claude. It
is not a skill and it is not activated per conversation.

Typical workflow:

1. Open `Build -> Guidance`.
2. Choose the provider or agent context.
3. Edit the draft.
4. Preview composed runtime guidance.
5. Submit, approve, publish, or archive where permitted.

Most users should not need to change guidance during ordinary work.

## Run A Protocol

Use protocols when work needs repeatable stages, assigned responsibilities,
review decisions, or declared artifacts.

For detailed authoring and run behavior, use [PROTOCOLS.md](PROTOCOLS.md).

Short path:

1. Open `Build -> Protocols`.
2. Choose a published protocol.
3. Click `Run protocol`.
4. Select a healthy entry agent.
5. Fill in the launch fields.
6. Review the declared artifacts.
7. Start the run.
8. Open the run in `Work -> Runs`.

The launch dialog collects run-specific context. Unless a protocol defines
custom `metadata.run_inputs`, the shared fields are workspace, goal, additional
context, and constraints. Those inputs help agents execute this run; they do
not rewrite the published stages, assignments, skills, transitions, or artifact
paths.

## Read A Run

Open `Work -> Runs` when you want to know what happened or what is happening
now.

A useful run page should answer:

- what protocol ran?
- which version ran?
- what stage is active now?
- which agent is working?
- what did the latest agent update say?
- were there review loops or repeated attempts?
- what outputs were declared?
- what outputs were produced?
- what is blocked, waiting, failed, canceled, or complete?

For active runs, watch the run status and latest agent update before retrying.
A long-running stage is not automatically stuck. It should show enough progress
or state for a user to understand whether work is still moving.

## Open Artifacts

Artifacts are the visible outputs of work.

An artifact can be:

- declared but not produced yet
- available
- unavailable from the current host
- expired or deleted

Where supported, artifact actions should include preview, open, download, copy
path, or package browsing. Missing or inconsistent artifact actions are product
issues, not a normal user burden.

## Use Telegram

Telegram is optional. It is a peer client over the same registry/runtime
backend, not a separate product model.

Use Telegram for quick chat, status checks, protocol run controls, and artifact
links when a Telegram bot token is configured. Use [TELEGRAM.md](TELEGRAM.md)
for setup notes and command details.

If you are new, learn the browser Registry workflow first. It exposes more
context and is easier to inspect when something goes wrong.

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

Useful distinctions:

- connected does not always mean execution-healthy
- running should mean active work, not stale work
- skill availability, defaults, active conversation skills, and routing skills
  are related but distinct
- a protocol can declare an artifact before any stage produces it
- Registry and Telegram should agree about the same run

## Where To Go Next

- [GETTING_STARTED.md](GETTING_STARTED.md) if setup or provider login is the
  problem
- [PROTOCOLS.md](PROTOCOLS.md) for protocol authoring, run inspection, export,
  and import
- [TELEGRAM.md](TELEGRAM.md) for Telegram usage
- [OPERATIONS.md](OPERATIONS.md) for health checks, logs, and demo readiness
