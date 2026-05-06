# User Guide

This guide is for people using Octopus through the browser Registry UI.

It assumes Octopus is already installed and running. If you have not opened the
Registry yet, start with [GETTING_STARTED.md](GETTING_STARTED.md).

Use this guide when you want to understand the product: how to talk to agents,
use skills, run protocols, inspect outputs, and decide what to do when work
looks stuck. It assumes at least one local agent has already been created and
started. Today, that first local agent is created through Telegram-backed bot
setup in the `./octopus` CLI.

## How The Guides Split Responsibilities

Use **this guide** for the everyday browser workflow: find agents, start
conversations, run published protocols, read run progress, and open artifacts.

Use [PROTOCOLS.md](PROTOCOLS.md) when you are designing or changing a protocol:
stages, reviewers, transitions, artifacts, run inputs, import, export, and
publish behavior. That guide also covers **Auto Protocol** (plain-language
drafting and revision) next to manual authoring.

The overlap is intentional but shallow. This guide gives enough protocol
context for a user to run and inspect work. The protocol guide is the canonical
place for authoring patterns and decisions.

## The Product In One Minute

Octopus is a shared control center for AI agent work.

- Use `Conversations` for open-ended work.
- Use `Agents` to see who is available and healthy.
- Use `Protocols` for repeatable staged workflows. **Auto Protocol** (in the
  same area) can propose a first draft or revisions from plain language; you
  still validate and publish like any other protocol. Details live in
  [PROTOCOLS.md](PROTOCOLS.md).
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
| Auto Protocol | Optional flow under `Build -> Protocols` that drafts or revises a normal protocol from a written goal; not a separate file format. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced file/output. |
| Routing | How Octopus decides which agent receives delegated or staged work. |

## First 20 Minutes

This path proves the basic product without requiring a customer scenario or
direct database access. It does not require using Telegram chat, but it does
require the Telegram-backed agent created during setup.

1. Open the Registry URL from `./octopus status`.
2. Open `Work -> Agents`.
3. Confirm one agent is connected and execution-healthy.
4. Open `Work -> Conversations`.
5. Start a conversation with that agent.
6. Send a short non-sensitive request.
7. Confirm the response appears in the conversation timeline.
8. Open `Work -> Agents` again and confirm the agent still looks healthy.
9. Open `Operations -> Dashboard` and confirm there is no blocking issue for
   the agent you plan to use.

If step 3 fails, the product is not ready for normal use yet. Ask the operator
to check [GETTING_STARTED.md](GETTING_STARTED.md) or
[OPERATIONS.md](OPERATIONS.md).

After this basic path works, move to `Build -> Protocols` when you are ready to
run a repeatable staged workflow. Do not make a new user create a blank protocol
as their first proof that the product works; start from a published protocol or
a guided scenario in [PROTOCOLS.md](PROTOCOLS.md). When you are ready to design
your own workflow, **Auto Protocol** is one way to get a structured first draft
without typing every stage by hand—still read the validation and publishing
steps in the same protocol guide.

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

For creating, editing, publishing, importing, exporting, reviewer loops, and
**Auto Protocol**, use [PROTOCOLS.md](PROTOCOLS.md).

### Run a published protocol

Use this path when a protocol is already published and you only need to start a
run.

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

### Start from a new workflow (Auto Protocol)

If you need a new workflow and do not want to build every stage manually, open
`Build -> Protocols` and choose `Auto protocol`. Describe the outcome in plain
language (and optional constraints). Octopus creates a normal editable draft
with inferred stages, reviewers, artifacts, and launch inputs. Review it, apply
it, resolve any validation or assignment warnings, then publish and run through
the same controls as any other protocol. For revision from chat or deeper
authoring notes, stay with [PROTOCOLS.md](PROTOCOLS.md) and
[TELEGRAM.md](TELEGRAM.md).

Telegram can also start an Auto Protocol session when you want a chat-first
flow. The message should summarize the proposed workflow, show the primary
outcome, and provide obvious actions such as Apply Draft, Publish, Publish &
Run, Status, and Artifacts when they are available. Use Registry when you want
more room to inspect or manually edit the draft.

If a workflow matters, expect to see explicit review stages in the run history.
Good protocols do not rely on one agent producing the final output in one pass;
they route work through planner, implementer, and reviewer responsibilities so
weak output can be revised before the run completes.

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

The default Runs list is recent-first for meaningful work from Registry and
Telegram. Use the view filters when you want only runs that need attention,
running runs, completed runs, runs with outcomes, or runs from a specific
surface. Archived and deleted runs are hidden from the normal recent view; use
the archive/delete filters when you need retention history. Use `Show
generated/audit runs` for rehearsal, smoke, and internal generated work.

For active runs, watch the run status and latest agent update before retrying.
A long-running stage is not automatically stuck. It should show enough progress
or state for a user to understand whether work is still moving.

When a completed run needs to be improved, select it and use `Improve this run`.
Octopus sends the run objective, status, primary artifact, and produced artifact
summary through Auto Protocol and creates a normal revision of the original
protocol. The previous artifact remains audit evidence; the improvement creates
a new draft, publish, and run path.

## Open Artifacts

Artifacts are the visible outputs of work.

An artifact can be:

- declared but not produced yet
- available
- unavailable from the current host
- retained as a durable package
- expired or deleted

Where supported, artifact actions should include preview, open, download, copy
path, or package browsing. Missing or inconsistent artifact actions are product
issues, not a normal user burden.

Multi-file artifacts are always still packages. Use `Download` when you need the
complete zip, and use `Contents` when you need to inspect files in place. Use
`Retain package` for important outputs before workspace cleanup; if the live
workspace path later disappears, the artifact can still open or download from
the retained package.

Some artifacts are runnable products, such as browser games, analytics apps, or
backend systems with an operator UI and APIs. When the package contains
`octopus-runtime.json` or a static `index.html`, the run can show `Start app`
and `Open app`. Octopus starts the process inside the bot runtime, routes the
UI/API through the Registry, and keeps package browse/download actions available
beside the live app. Stop the runtime when you are done testing it.

## Archive, Delete, And Cleanup

Archive hides a run from the normal list while preserving the run, stages,
artifacts, retained packages, runtime events, and audit trail. Delete is a soft
delete used for retention and clutter control; it requires explicit
confirmation and keeps historical audit available to authorized operators.

Workspace cleanup lives under `Operations -> Dashboard`. It is dry-run-first:
Octopus asks a connected bot to scan its own workspace, shows transient
logs/caches/scratch directories it can remove, and only then executes the
approved cleanup. Cleanup should not remove the only copy of an important
artifact; retain the package first when the artifact matters.

## Use Telegram

Telegram has two roles today:

- setup role: the current CLI path creates local agents as Telegram-backed bot
  runtimes
- user-facing role: Telegram can also be a chat and control surface over the
  same Registry/runtime backend

Use Telegram for quick chat, status checks, protocol run controls, and artifact
links when a Telegram bot token is configured. Use [TELEGRAM.md](TELEGRAM.md)
for setup notes and command details.

If you are new, learn the browser Registry workflow first after the agent exists.
It exposes more context and is easier to inspect when something goes wrong.
Telegram should still be readable without keeping this guide open: protocol
cards should show the current state, the next safe actions, and the primary
artifact when one exists.

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

**Continue with the product**

- [PROTOCOLS.md](PROTOCOLS.md) for protocol authoring (including Auto Protocol),
  reviewer loops, export, import, and publish behavior
- [TELEGRAM.md](TELEGRAM.md) for Telegram chat, setup reminders, and protocol
  commands when a bot is configured
- [OPERATIONS.md](OPERATIONS.md) for health checks, logs, demo readiness, and
  operator troubleshooting

**If install or provider login is still the blocker**

- [GETTING_STARTED.md](GETTING_STARTED.md)
