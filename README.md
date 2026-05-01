# Octopus Agent Platform

Octopus is a local control center for AI agent work. It gives teams one place
to start agents, talk to them, build repeatable workflows, watch runs, and open
the artifacts those runs produce.

Use Octopus when you want more than a single chat thread:

- coordinate one or more AI agents
- run staged workflows with reviews and handoffs
- reuse skills and provider guidance
- inspect what happened after a run
- export or import protocol packages
- use the browser Registry UI, with Telegram-backed local agents over the same
  backend

This repository is the shipped Python/FastAPI product. `plan_java.md` is
planning material only; it is not the runtime described here.

## Start Here

Choose the path that matches what you need today.

| Goal | Start with |
| --- | --- |
| Install Octopus and open it for the first time | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| Learn the browser Registry UI | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| Create, run, export, or import workflows | [docs/PROTOCOLS.md](docs/PROTOCOLS.md) |
| Use Telegram as a chat surface | [docs/TELEGRAM.md](docs/TELEGRAM.md) |
| Operate, demo, or troubleshoot a local stack | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| Walk through a complete example | [docs/examples/README.md](docs/examples/README.md) |

If you are brand new, read `GETTING_STARTED.md` first. It explains Docker
Desktop, Telegram-backed agent setup, model provider login, the `./octopus`
command, and the first healthy browser check without assuming you already know
those tools. In the current product, new local agents are created through the
Telegram-backed bot setup flow before they appear in the Registry.

## How To Think About Octopus

| Concept | Plain meaning |
| --- | --- |
| Registry | The local web app and backend that coordinate the system. |
| Agent | A configured bot runtime that can receive work. |
| Conversation | A thread where a user and agent exchange messages. |
| Skill | Reusable instructions or tooling an agent can use. |
| Guidance | Baseline policy for a model provider, separate from skills. |
| Protocol | A reusable staged workflow with assignments and decisions. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced output from work. |

## The Product Areas

The Registry UI is grouped by the job you are doing:

| Area | Entries | Purpose |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Day-to-day collaboration, protocol execution, artifacts, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow authoring and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Stack overview, routing diagnostics, and usage visibility. |

`Tasks` and `Approvals` exist as linked execution surfaces. Most users should
open them from conversations, runs, dashboard cards, or direct links when they
need lineage context.

## Developer References

These are useful after you understand the product path:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - package boundaries,
  deployment topology, data model, protocol architecture, UI model, and
  architecture rules.
- [docs/SDK_BOT_DEVELOPMENT.md](docs/SDK_BOT_DEVELOPMENT.md) - SDK/runtime
  extension guide.
- [docs/SKILLS_MODEL.md](docs/SKILLS_MODEL.md) - lower-level skill state and
  package model.
- [docs/PROTOCOL_ASSIGNMENT_AUDIT.md](docs/PROTOCOL_ASSIGNMENT_AUDIT.md) -
  assignment model audit and validation notes.
- [docs/registry-openapi.json](docs/registry-openapi.json) - checked-in
  OpenAPI artifact for the Registry API.

## Examples

Examples are intentionally separate from the core product guide so one customer
scenario does not become the product narrative.

- [Manufacturing intelligence](docs/examples/manufacturing-intelligence.md):
  a protocol scenario for creating an offline manufacturing command center
  artifact.
- [Offline CSV analytics](docs/examples/offline-csv-analytics.md):
  a browser-only multi-CSV analytics package scenario.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
