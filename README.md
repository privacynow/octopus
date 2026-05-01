# Octopus Agent Platform

Octopus helps teams coordinate AI agents through a local registry, browser UI,
Telegram, reusable skills, and protocol runs with auditable artifacts.

The product is built for practical agentic work: start agents, give them work,
turn repeated work into protocols, inspect what happened, and hand off the
outputs without private database edits or hidden setup.

This repo is the shipped Python/FastAPI product. `plan_java.md` is planning
material only; it is not the runtime described here.

## What Octopus Does

- runs a local registry and one or more bot runtimes
- exposes a browser Registry UI for conversations, agents, protocol runs,
  skills, guidance, routing, and usage
- optionally exposes Telegram as a chat client over the same backend
- lets teams author, publish, export, import, and run staged protocols
- tracks stage work, decisions, artifacts, and operator actions
- manages reusable skills and provider guidance without creating a second
  client-specific model

## How To Think About It

| Concept | Plain meaning |
| --- | --- |
| Agent | A configured bot runtime that can receive work. |
| Conversation | An interactive thread with an agent. |
| Skill | Reusable instructions or tooling an agent can use. |
| Guidance | Provider baseline policy; not a conversation skill. |
| Protocol | A reusable staged workflow with assignments, decisions, and artifacts. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced output from work. |

## Quick Start

Prerequisites:

- Docker Desktop is running
- provider auth is configured for at least one execution agent
- Telegram bot token is configured only if you want Telegram access

Start the local stack:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Verify health:

```bash
./octopus status
```

Expected healthy state:

- registry is running
- configured bots are running
- target agents are connected
- target agents are execution-healthy
- the Registry URL opens in a browser

The default local Registry URL is:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

## First 20 Minutes

1. Open the Registry URL printed by `./octopus status`.
2. Go to `Work -> Agents` and confirm at least one agent is connected and
   execution-healthy.
3. Go to `Work -> Conversations` and send a short non-sensitive request.
4. Go to `Build -> Protocols` and inspect or create a simple protocol.
5. Run a published protocol from the Registry UI.
6. Inspect the run in `Work -> Runs`, especially `Stages`, `Artifacts`, and
   `Audit`.
7. Use `Operations -> Dashboard` if something looks stuck or unhealthy.

## Documentation Paths

Start with the guide that matches the job you are doing:

| Path | Use it when |
| --- | --- |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | You are new to Octopus or need the normal browser workflow. |
| [docs/PROTOCOLS.md](docs/PROTOCOLS.md) | You need to author, run, export, import, or troubleshoot protocols. |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | You operate a local stack, prepare demos, inspect health, or debug runs. |
| [docs/TELEGRAM.md](docs/TELEGRAM.md) | You use Telegram as an optional chat surface. |
| [docs/examples/README.md](docs/examples/README.md) | You want a concrete scenario walkthrough. |

Developer references:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  Current package boundaries, deployment topology, data model, protocol
  architecture, UI model, and architecture rules.
- [docs/SDK_BOT_DEVELOPMENT.md](docs/SDK_BOT_DEVELOPMENT.md)
  SDK/runtime extension guide.
- [docs/SKILLS_MODEL.md](docs/SKILLS_MODEL.md)
  Lower-level skill state model.
- [docs/PROTOCOL_ASSIGNMENT_AUDIT.md](docs/PROTOCOL_ASSIGNMENT_AUDIT.md)
  Assignment model audit and validation notes.
- [docs/registry-openapi.json](docs/registry-openapi.json)
  Checked-in OpenAPI artifact for the registry API.

## Registry Navigation

The Registry UI is grouped by job:

| Area | Entries | Purpose |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Day-to-day collaboration, protocol execution, artifacts, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow authoring and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Stack overview, routing diagnostics, and usage visibility. |

`Tasks` and `Approvals` still exist as linked execution surfaces, but they are
not primary navigation. Open them from conversations, runs, dashboard cards, or
direct links when lineage context matters.

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

Use the UI or documented APIs for product validation. Direct database edits are
diagnostic tools, not proof that a customer workflow works.

## Examples

Examples are intentionally separate from the core product guide so one customer
scenario does not become the product narrative.

- [Manufacturing intelligence](docs/examples/manufacturing-intelligence.md):
  a customer-facing protocol scenario for creating an offline manufacturing
  command center artifact.
- [Offline CSV analytics](docs/examples/offline-csv-analytics.md):
  a browser-only multi-CSV analytics package scenario.

## Troubleshooting

Start with:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

Then inspect the Registry:

- `Operations -> Dashboard` for stack and work health
- `Work -> Runs` for protocol execution state
- `Work -> Conversations` for user-visible thread history
- `Work -> Agents` for connectivity and execution health
- `Operations -> Routing` for delegation and skill routing diagnostics

Treat broken previews, missing artifact actions, stale status labels, or
client disagreement between Telegram and Registry as product issues to fix.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
