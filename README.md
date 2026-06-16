# Octopus Agent Platform

Octopus is a local control center for AI agent work. It gives teams one place
to start agents, talk to them, build repeatable workflows, watch runs, and open
the artifacts those runs produce.

Use Octopus when you want more than a single chat thread:

- coordinate one or more AI agents
- run staged workflows with reviews and handoffs
- draft protocols with **Auto Protocol** (plain-language goals) or manual
  authoring—see [docs/PROTOCOLS.md](docs/PROTOCOLS.md)
- reuse skills and provider guidance
- inspect what happened after a run
- open runnable artifacts as small web-routed apps or APIs when a run produces
  an interactive system, while still downloading the full package
- retain produced artifact packages so important outputs survive bot workspace
  cleanup or a lost live path
- archive or soft-delete completed runs without destroying the audit trail
- export or import protocol packages
- use the browser Registry UI, with Telegram-backed local agents over the same
  backend

This repository is the shipped Python/FastAPI product. Planning notes and
generated local deployment state are not required for the runtime described
here.

## Start Here

Choose the path that matches what you need today.

| Goal | Start with |
| --- | --- |
| Install Octopus and open it for the first time | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| Learn the browser Registry UI | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| Create, run, export, or import workflows (including Auto Protocol) | [docs/PROTOCOLS.md](docs/PROTOCOLS.md) |
| Use Telegram as a chat surface | [docs/TELEGRAM.md](docs/TELEGRAM.md) |
| Operate, demo, troubleshoot, or move a stack | [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| Walk through a complete example | [docs/examples/README.md](docs/examples/README.md) |

If you are brand new, read `GETTING_STARTED.md` first. It explains Docker
Desktop, Telegram-backed agent setup, model provider login, the `./octopus`
command, and the first healthy browser check without assuming you already know
those tools. In the current product, new local agents are created through the
Telegram-backed bot setup flow before they appear in the Registry.

## Fresh Deployments

The tracked repository does not include a ready-to-run deployment. `./octopus`
creates host-local deployment state under `.deploy/` the first time you start
the Registry, create a bot, authenticate a provider, or attach a workspace.

Only `.deploy/bots/.env.example` is tracked. Everything else under `.deploy/`
is generated local state and may contain secrets, provider login state, database
volumes, build logs, absolute host paths, Telegram bot identities, and old
machine-specific names. Do not copy this directory to a public machine unless
you are intentionally migrating a trusted private environment and have rotated
or protected the credentials.

For a new public host, clone the repository fresh and let `./octopus` create
new deployment state. If the Registry must be reachable from other machines,
bind the service to a reachable interface and set a real public URL before
creating or connecting bots:

```bash
./octopus start registry --registry-bind-host 0.0.0.0 --registry-public-url https://octopus.example.com
```

Use `0.0.0.0` only as the bind address. Browser users and remote bots need the
public URL, preferably behind HTTPS and firewall or reverse-proxy controls. For
step-by-step setup and migration notes, use
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) and
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Reviewer Path

For a technical review, start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
and the tests named there. The fast deterministic gate is:

```bash
python3 -m venv .venv
.venv/bin/pip install -c constraints.txt -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q tests/test_protocol_docs.py tests/test_startup_diagnostics.py tests/test_octopus_cli.py tests/test_octopus_cli_manager.py tests/test_registry_service.py::test_registry_openapi_asset_matches_generated_schema
```

Live browser and provider-backed protocol checks require a configured local
Octopus deployment; they are intentionally separate from the clean-clone unit
gate.

## How To Think About Octopus

| Concept | Plain meaning |
| --- | --- |
| Registry | The local web app and backend that coordinate the system. |
| Agent | A configured bot runtime that can receive work. |
| Conversation | A thread where a user and agent exchange messages. |
| Skill | Reusable instructions or tooling an agent can use. |
| Guidance | Baseline policy for a model provider, separate from skills. |
| Protocol | A reusable staged workflow with assignments and decisions. |
| Auto Protocol | An optional authoring path that proposes a normal protocol draft from a described outcome; same format as manual work. See the protocol guide. |
| Run | One execution of a published protocol. |
| Artifact | A declared or produced output from work. Multi-file artifacts can be browsed, retained, or downloaded as zip packages; runnable artifacts can also be started and opened through the Registry. |

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
- [SECURITY.md](SECURITY.md) - security posture, reporting, and deployment
  cautions.
- [CONTRIBUTING.md](CONTRIBUTING.md) - local development and contribution
  expectations.

## Examples

Examples are intentionally separate from the core product guide so one customer
scenario does not become the product narrative.

- [Manufacturing intelligence](docs/examples/manufacturing-intelligence/README.md):
  a step-by-step protocol walkthrough for creating, running, and validating an
  offline manufacturing command center artifact.
- [Offline CSV analytics](docs/examples/offline-csv-analytics.md):
  a browser-only multi-CSV analytics package scenario.

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
