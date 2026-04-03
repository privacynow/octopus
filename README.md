# Octopus Agent Platform

Octopus runs Claude or Codex behind Telegram and adds a local registry so
operators can manage bots, inspect conversations, review approvals, route
tasks, manage skills, and edit provider guidance from a browser UI.

The main entrypoint is:

```bash
./octopus
```

`./octopus` owns local deployment state under `.deploy/`, starts and reconnects
the local registry stack, and handles normal operator lifecycle work.

## What Ships In This Repo

- `app/`
  Telegram bot runtime, provider integrations, Postgres-backed runtime state,
  and the `./octopus` CLI
- `octopus_registry/`
  Registry service, WebSocket layer, store, ingress, and browser UI
- `octopus_sdk/`
  Shared runtime contracts, workflows, registry protocols, and composition seams

## Product Model

Octopus has three main operator concepts:

- `Skills`
  What a bot can do for a task
- `Routing skills`
  The skill-derived projection used for discovery and cross-bot delegation
- `Guidance`
  Provider-level baseline policy for Claude/Codex behavior on one bot

Skills use one shared backend model across the registry UI and chat clients.
The main user-facing skill states are:

- `Catalog`
- `Available on this bot`
- `Default for new conversations`
- `Active in this conversation`

These states are distinct. Making a skill available on a bot does not activate
it in all conversations. Defaults seed new conversations only. Routing skills
are bot-level and derived from skill readiness plus routing policy; they are
not a second product object.

Guidance stays separate from skills:

- skills are selectable capability packages
- guidance is provider-scoped baseline policy
- published guidance applies to every run for that provider on that bot
- guidance is not routed and is not activated per conversation

## Deployment Model

The shipped runtime is:

- `registry-first`
- `Postgres-only`
- `Docker-first` for local operation through `./octopus`

There is no supported SQLite runtime path in this repo.

### Local Docker Topology

The local `./octopus` deployment does **not** run one giant shared database for
everything. It starts:

- one registry stack
- one bot stack per bot
- one Postgres container per stack

So a normal local deployment looks like:

- `octopus-registry` -> `registry-postgres`
- `octopus-<bot-slug>` -> `<bot-slug>-postgres`

All runtime services still consume `OCTOPUS_DATABASE_URL`, but in CLI-managed
Docker deployments that value is injected automatically and points at the
stack-local Postgres host.

Example live URLs inside the containers:

- registry service:
  `postgresql://bot:bot@registry-postgres:5432/bot`
- bot service:
  `postgresql://bot:bot@lift-and-shift-m1-bot-postgres:5432/bot`

If you deploy outside `./octopus`, every runtime service still requires a valid
Postgres `OCTOPUS_DATABASE_URL`.

### Registry URLs

The registry uses three different URL concepts:

- `REGISTRY_BIND_HOST` + `REGISTRY_PORT`
  Where Docker publishes the registry on the host
- `REGISTRY_PUBLIC_URL`
  What operators open in the browser and what remote bots use
- `http://registry:8787`
  The internal Docker URL used by co-deployed local bot containers

`0.0.0.0` is only a listen address. It is not a usable browser URL or bot URL.

## Quick Start

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Clone the repo into a persistent checkout:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Setup offers three modes:

- `Autonomous`
  Private bot with no approval gates
- `Safe`
  Default mode; requests pause for approval before execution
- `Advanced`
  Manual role, tags, description, allowed users, timeout settings, working
  directory, and default skills

## First Run

After setup:

1. Run `./octopus status`.
2. Open the registry UI at the URL shown in status output.
3. Send the bot a normal Telegram message.
4. If approval mode is enabled, approve the request in Telegram or the registry UI.

At that point the essential path is working:

- Telegram user message in
- provider execution
- optional approval gate
- bot reply back in the same chat
- operator visibility in the registry UI

## Operator Surfaces

Octopus has two operator surfaces and one end-user surface.

### End Users

For most users, Octopus is just a Telegram bot.

- send a normal message
- use `/help` for command discovery
- if approval mode is enabled, the bot pauses for review before executing
- routed work still comes back into the same parent chat

### Registry UI

The browser UI is the main product surface for operators. Core routes:

- `Dashboard`
  Health, activity, recent work, and follow-up items
- `Approvals`
  Pending operator decisions
- `Agents`
  Bot roster and health
- `Conversations`
  Thread list and quick-start actions
- `Conversation detail`
  Replies, routing, tasks, settings, skills, and activity in one place
- `Tasks`
  Cross-conversation routed task queue
- `Usage`
  Conversation-level token and cost rollups
- `Skills`
  Availability, activation, custom skill authoring, and store operations
- `Guidance`
  Published provider policy, draft policy, and composed runtime preview
- `Routing`
  Skill-derived routing policy and discovery controls

### CLI

`./octopus` is the deployment and admin surface. It is not the richest product
surface for skills or guidance; registry UI and chat are.

Core commands:

```bash
./octopus
./octopus status
./octopus start registry
./octopus start bots
./octopus connect m1
./octopus restart bots
./octopus redeploy registry
./octopus logs m1 --follow
./octopus shell m1
./octopus doctor m1
./octopus clean
```

The CLI supports these actions:

- `status [--live-provider]`
- `start [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]`
- `stop [target...] [--yes]`
- `restart [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]`
- `redeploy [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]`
- `connect [target...] [--yes] [--registry-url URL --registry-enroll-token TOKEN] [--registry-id ID] [--registry-scope SCOPE]`
- `disconnect [target...] [--yes] [--registry-id ID]`
- `logs <target> [--follow]`
- `shell <target>`
- `doctor <target> [--live-provider]`
- `clean`

Targets:

- `registry`
- `bots`
- one bot slug
- a short alias like `m1` when unique

## Skills, Routing, And Guidance

### Skills

Skills are the primary user-facing capability model.

Orthogonal skill labels:

- `Source`
  `Core`, `Store`, `Custom`
- `Setup`
  `Needs setup`, `Ready`
- `Lifecycle`
  Draft through published/archive for mutable custom skills

Current behavior:

- `Core` skills ship with the runtime image
- `Store` skills are installed onto a bot from the registry UI or chat
- `Custom` skills are authored inside Octopus and use the same shared package model
- the browser `Skills` page manages bot availability and custom skill lifecycle
- conversation activation is separate and happens from a conversation’s `Skills` panel or chat commands
- defaults seed new sessions only; they do not activate every existing conversation
- submit and publish invoke backend validation

Custom skill drafts use one shared package model across registry and chat:

- metadata:
  `name`, `display_name`, `description`
- instructions:
  `body`
- setup:
  `requirements`
- provider extensions:
  `provider_config`
- artifacts:
  `files`

Validation and publish readiness are derived from package contents, not guessed
separately by each client.

### Routing

Routing is skill-derived. It is not a competing end-user concept called
`capabilities`.

Routing skills are the subset of bot skills that are:

- available on the bot
- runtime-ready
- allowed by routing policy

That derived set is used for discovery and cross-bot delegation.

### Guidance

Guidance is provider baseline policy.

- managed per provider, per bot
- published guidance applies to every run for that provider on that bot
- registry and chat expose the same lifecycle
- registry is the richer wrapper

The `Guidance` page separates:

- published policy
- draft policy
- composed runtime preview

For the full shared model, see:

- [docs/skills-model.md](/Users/tinker/output/bots/telegram-agent-bot/docs/skills-model.md)
- [ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md)

## Shared Workspaces

Workspaces let multiple bots collaborate on the same host directory mounted at
`/workspace/<name>` inside their containers.

Typical flow:

1. run `./octopus`
2. choose `Workspaces`
3. create the workspace
4. attach bots
5. restart the affected bots

Users can then switch into the workspace with `/project <name>`.

## Deployment And Operations

Example local registry operations:

```bash
./octopus start registry
./octopus start registry --registry-bind-host 0.0.0.0 --registry-public-url http://mybox.local:8787
./octopus restart registry --registry-bind-host 192.168.1.20 --registry-port 9000 --registry-public-url http://registry.example.internal:9000
```

Example registry connections:

```bash
./octopus connect m1
./octopus connect m1 --registry-url http://registry.example.internal:9000 --registry-enroll-token <token>
./octopus connect bots --registry-url http://registry.example.internal:9000 --registry-enroll-token <token> --registry-id qa --registry-scope observe
```

Remote registry enroll tokens are still distributed out-of-band.

For a persistent `~/octopus` checkout, the repo also ships non-interactive ops
helpers under [scripts/ops/](/Users/tinker/output/bots/telegram-agent-bot/scripts/ops):

```bash
bash scripts/ops/backup_octopus_deploy.sh --help
bash scripts/ops/refresh_octopus_with_backup.sh --help
```

The clean refresh flow:

1. backs up `~/octopus/.deploy`
2. pulls the latest code
3. runs `./octopus clean`
4. restores `.deploy`
5. starts the registry and bots again
6. reconnects bots to the registry
7. verifies registry health, bot connectivity, and image freshness

## Status, Health, And Faults

Provider auth is reported at two levels by default:

- `not configured`
- `configured`

`./octopus status` is intentionally static and cheap by default. Use:

- `./octopus status --live-provider`
- `./octopus doctor <bot> --live-provider`
- `Diagnose -> Provider auth`

when you want a live provider check.

Live checks add:

- `authenticated`
- `configured, unable to authenticate`

Bot status separates transport from execution:

- `connected`
  The bot is enrolled in the registry and heartbeating normally
- `execution healthy`
  Requests are allowed to execute
- `execution faulted`
  A provider/runtime failure was classified as irrecoverable and new requests
  are blocked until reset

Execution faults are intentionally runtime-driven. Octopus does not silently
repair provider login during startup or deploy. If a provider login expires or
an external provider/account problem needs operator action, the bot can remain
transport-connected while execution is latched off until an operator resets it.

## Troubleshooting

If something fails:

1. run `./octopus status`
2. run `./octopus doctor <bot>`
3. inspect the relevant `.deploy/.../.env` file
4. inspect registry connectivity and provider auth before changing code

If provider auth shows `configured, unable to authenticate`, the auth files are
present but the provider login is no longer valid. Re-run the provider auth
flow from `./octopus` -> `Diagnose` -> `Provider auth`.

If a bot shows `execution faulted`, fix the provider/account problem first,
then use `Reset execution` from the registry UI for that bot.

If a registry connection fails:

1. verify the registry URL
2. verify the enroll token and scope
3. inspect indexed `BOT_AGENT_REGISTRY_<n>_*` env records
4. check the bot’s local registry state
5. use `./octopus doctor <bot>`

For CLI-managed Docker deployments, also verify that the runtime service is
using the stack-local Postgres host in `OCTOPUS_DATABASE_URL`, not a shared
`postgres` alias.

## Documentation

- [ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md)
  System boundaries, runtime composition, registry flows, and deployment model
- [docs/skills-model.md](/Users/tinker/output/bots/telegram-agent-bot/docs/skills-model.md)
  Shared skills model, package format, lifecycle, and client semantics

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
