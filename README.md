# Octopus Agent Platform

Octopus is the current Python/FastAPI based agent platform for running Claude
or Codex behind managed bot runtimes. It provides:

- a local Docker-managed registry service
- one or more bot runtime stacks
- Telegram chat access when a bot token is configured
- registry-origin browser conversations
- agent enrollment and health
- routed work/delegation tracking
- skills and provider guidance management
- protocol authoring and protocol runs
- artifact metadata and artifact download/preview paths where implemented
- operator views for dashboard, routing, usage, runs, conversations, and agents

This repo is the shipped product codebase. The Java rebuild plan in
`plan_java.md` is planning material only; it is not the runtime described by
this README.

## Current Product Shape

The registry UI is grouped by job:

| Area | Current entries | Purpose |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Day-to-day collaboration, protocol run inspection, and agent contact/health. |
| Build | Protocols, Skills, Guidance | Reusable workflow authoring, skill management, and provider policy. |
| Operations | Dashboard, Routing, Usage | Stack overview, routing diagnostics, and usage visibility. |

Important current details:

- `Tasks` still exists as the routed-work backing model and API. It is no
  longer a primary navigation item; it is opened from conversations, runs,
  dashboard cards, or direct task links when lineage context matters.
- `Approvals` still exists as a route and API. It is surfaced from Dashboard
  or direct links rather than as a primary menu item.
- `Templates` are managed inside Protocols. There is no separate template
  gallery product surface in the main navigation, and no prepackaged starter
  protocols are exposed by default.
- Protocol authoring, run detail, artifacts, and linked work are actively being
  consolidated around one lineage model. Treat the docs in this repo as the
  source of truth for current behavior, not old screenshots or prior plans.

## Entrypoint

Use the host-side CLI:

```bash
./octopus
```

`./octopus` manages the local Docker deployment under `.deploy/`. In the
standard local setup it starts:

- the registry stack
- one bot stack per configured bot
- the Postgres containers those stacks need
- registry/bot connectivity wiring

You normally do not wire databases manually.

## Prerequisites

For the standard Telegram-enabled local setup:

- Docker Desktop is running
- you have a Telegram bot token from `@BotFather`
- you have provider auth available for Claude or Codex
- you cloned the repo into a persistent checkout

The runtime can also run in registry-only mode when no Telegram token is
configured.

## Quick Start

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Then verify:

```bash
./octopus status
```

Expected healthy state:

- registry is running
- configured bots are running
- registry connection state is connected
- execution state is healthy

## Open The Registry

`./octopus status` prints the registry URL. The default local URL is:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

Use the registry to:

- inspect conversations
- send registry-origin messages
- inspect protocol runs
- inspect agents and agent-generated work
- manage skills
- manage provider guidance
- author and publish protocols/templates
- inspect routing and usage
- find approvals or routed work through Dashboard and linked context

For the browser workflow, use
[docs/registry-user-guide.md](docs/registry-user-guide.md).

## Demo Use Case: Local Manufacturing Analytics Without Uploading Raw CSVs

One practical customer workflow is local data analytics and reporting.

The intended pattern is:

- keep customer CSVs in a local workspace
- ask the bot to generate or revise Python/R/SQL scripts for the analysis
- run those scripts locally against the CSVs
- share only controlled schema summaries, aggregate profiles, logs, test
  failures, or selected report outputs back into the conversation
- keep generated code, reports, and charts as local artifacts

This lets a customer use Octopus to build a repeatable analytics/reporting
pipeline without pasting raw manufacturing records into the model prompt. The
operator still controls the boundary: do not paste raw rows or attach private
files to chat unless that is explicitly approved for the deployment.

For development regression checks, run the deterministic local fixture:

```bash
./.venv/bin/python scripts/demo/manufacturing_local_analytics/run_demo.py \
  --workspace .tmp/demo/manufacturing-local-analytics
```

For a step-by-step demo, use
[docs/local-data-analytics-demo.md](docs/local-data-analytics-demo.md).

## Use Telegram

If Telegram is configured:

1. open Telegram
2. find your bot
3. send a normal message
4. use `/help` for the live command set

Common command families:

- `/project`
- `/skills`
- `/guidance`
- `/protocol`

Protocol commands currently include:

- `/protocol list`
- `/protocol start <slug> <problem statement>`
- `/protocol status <run_id>`
- `/protocol artifacts <run_id>`
- `/protocol export <run_id>`
- `/protocol watch <run_id>`
- `/protocol unwatch <run_id>`
- `/protocol cancel <run_id> [reason]`
- `/protocol retry <run_id> [reason]`
- `/protocol accept <run_id> [reason]`
- `/protocol send-back <run_id> [reason]`

For Telegram behavior, use
[docs/telegram-user-guide.md](docs/telegram-user-guide.md).

## Common CLI Commands

```bash
./octopus
./octopus status
./octopus start registry
./octopus start bots
./octopus restart bots
./octopus connect m1
./octopus logs m1 --follow
./octopus shell m1
./octopus doctor m1
./octopus clean
```

## Skills

Use this vocabulary:

- `Catalog`: what exists
- `Available on this bot`: what one agent can use
- `Default for new conversations`: what seeds future conversations
- `Active in this conversation`: what is enabled in one thread
- `Routing skills`: the skill-derived projection used for delegation/routing

For practical usage, use [docs/skills-guide.md](docs/skills-guide.md).
For the lower-level model, use [docs/skills-model.md](docs/skills-model.md).

## Protocols

Protocols are reusable multi-stage workflows stored in the registry control
plane and executed through routed work.

Current behavior:

- author drafts in the Protocols UI
- create new protocols from blank
- publish a protocol as a user-authored template and later copy from that saved
  template
- publish protocol definitions
- start runs from registry UI or Telegram
- inspect run overview, stages, artifacts, and audit data
- intervene with `retry`, `accept`, `send-back`, and `cancel` where permitted
- inspect declared and produced artifacts where artifact actions are available

Current constraints and known gaps:

- The runtime still uses routed tasks as the execution unit for stage work.
  The UI is being consolidated so users see this as linked work rather than a
  separate unrelated Tasks app.
- Standard protocol authors should not see internal runtime controls. Operator
  surfaces remain gated separately.
- Artifact action coverage is expected to be consistent across conversations,
  work, runs, stages, and Telegram. Any missing preview/download/open action is
  a product gap to fix, not a separate artifact model.

Protocol docs:

- [docs/author-protocol-guide.md](docs/author-protocol-guide.md)
- [docs/operator-protocol-guide.md](docs/operator-protocol-guide.md)
- [docs/protocol_assignment_audit.md](docs/protocol_assignment_audit.md)

## Architecture And Development

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  Current architecture, package boundaries, deployment topology, data model,
  UI model, and known limitations.
- [docs/sdk-bot-development.md](docs/sdk-bot-development.md)
  SDK/runtime extension guide.
- [docs/registry-openapi.json](docs/registry-openapi.json)
  Checked-in OpenAPI artifact for the registry API.

## Troubleshooting

Start here:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

Then check:

- registry reachable at `/ui`
- bot connected to registry
- provider auth valid
- execution fault state
- relevant conversation/run/work detail in registry
- artifact availability from the same host/container path expected by the
  artifact route

## Documentation Rule

If behavior changes, update the matching guide in the same change. Stale docs
are a product defect in this repo.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
