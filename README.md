# Octopus Agent Platform

Octopus runs Claude or Codex behind Telegram and adds a local registry so
operators can manage bots, monitor work, review approvals, inspect
conversations, route tasks, manage skills, and edit provider guidance from a
browser UI.

The main entrypoint is:

```bash
./octopus
```

`./octopus` manages local deployment state under `.deploy/`, starts and
reconnects the local registry stack, and handles normal operator lifecycle
work.

## Quick Start

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Clone the repo into a persistent checkout:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
./octopus
```

Setup offers three modes:

- **Autonomous**: private bot, no approval gates
- **Safe**: default; requests go through approval mode
- **Advanced**: manual role, tags, description, default skills, allowed users,
  working dir, and timeout settings

## First Run

After setup, verify the deployment before you start tuning features.

1. Run `./octopus status`.
2. Open the registry UI at the URL shown by `./octopus status`
   (default `http://127.0.0.1:<port>/ui`).
3. Send the bot a normal Telegram message.
4. If you chose **Safe** mode, approve the request in Telegram or the registry
   UI.

At this point the essential path is working:

- Telegram user message in
- provider execution
- optional approval gate
- bot reply back in the same chat
- operator visibility in the registry UI

Provider auth is reported at two levels:

- `not configured`: no provider auth artifacts are present
- `configured`: auth artifacts exist, but no live probe was requested

By default, `./octopus status` is static and cheap. Use
`./octopus status --live-provider`, `Diagnose -> Provider auth`, or
`Recommended Actions` when you want a live provider check. Live checks can
add:

- `authenticated`: the live provider probe succeeded
- `configured, unable to authenticate`: auth artifacts exist, but the live
  provider probe failed

Bot status now separates transport from execution:

- `transport connected` means the bot is enrolled in the registry and
  heartbeating normally
- `execution ready` means requests are allowed to execute
- `execution faulted` means a real runtime provider failure was classified as
  irrecoverable and new requests are blocked until reset

Execution faults are intentionally runtime-driven. Octopus does not try to
repair provider login during startup or deploy. If a request fails because a
provider login expired or an API key/account problem needs operator action,
the bot stays transport-connected and manageable, but execution is latched off
until an operator resets it.

## Deployment And Operations

The shipped runtime in this repo is registry-first:

- bots run in `BOT_AGENT_MODE=registry`
- Telegram startup expects registry connectivity
- the operator UI and bot runtime are designed to run together
- bots managed by `./octopus` can connect either to the co-deployed local
  registry or to a remote registry URL

Important URLs and env values:

- local registry bind address:
  `REGISTRY_BIND_HOST` + `REGISTRY_PORT`
  (`127.0.0.1`, `0.0.0.0`, or a concrete IP)
- local registry public/operator URL:
  `REGISTRY_PUBLIC_URL`
- bot-to-registry URL inside Docker for the co-deployed local registry:
  `http://registry:8787`
- operator login secret: `REGISTRY_UI_TOKEN` from `.deploy/registry/.env`
- bot enrollment secret: `REGISTRY_ENROLL_TOKEN` on the registry side, copied
  into bot registry connection records as `BOT_AGENT_REGISTRY_<n>_ENROLL_TOKEN`

The three registry URLs are intentionally different:

- **bind host + port**: where Docker publishes the local registry on the host
- **public URL**: what operators open in the browser and what remote bots use
- **internal Docker URL**: what co-deployed local bot containers use

`0.0.0.0` is only a listen address. It is never a usable browser or bot URL.

Example local registry starts:

```bash
./octopus start registry
./octopus start registry --registry-bind-host 0.0.0.0 --registry-public-url http://mybox.local:8787
./octopus restart registry --registry-bind-host 192.168.1.20 --registry-port 9000 --registry-public-url http://registry.example.internal:9000
```

Example bot connections:

```bash
./octopus connect m1
./octopus connect m1 --registry-url http://registry.example.internal:9000 --registry-enroll-token <token>
./octopus connect bots --registry-url http://registry.example.internal:9000 --registry-enroll-token <token> --registry-id qa --registry-scope observe
```

Remote registry enroll tokens are still distributed out-of-band. `./octopus`
does not fetch them from the registry UI or API.

Core operator commands:

```bash
./octopus
./octopus status
./octopus start registry
./octopus connect m1
./octopus restart bots
./octopus redeploy registry
./octopus shell m1
./octopus doctor m1
./octopus clean
```

For a persistent `~/octopus` checkout, the repo also ships non-interactive ops
helpers under [`scripts/ops/`](/Users/tinker/output/bots/telegram-agent-bot/scripts/ops):

```bash
bash scripts/ops/backup_octopus_deploy.sh --help
bash scripts/ops/refresh_octopus_with_backup.sh --help
```

Use the clean refresh flow when you need to redeploy without losing local
deployment state:

1. back up `~/octopus/.deploy`
2. `git pull --ff-only`
3. run `./octopus clean`
4. restore `.deploy`
5. start the registry and bots again
6. reconnect bots to the registry
7. verify registry health and bot freshness

The runtime supports multiple registry records through indexed
`BOT_AGENT_REGISTRY_<n>_*` env vars. `./octopus` keeps the local registry
workflow simple while also supporting explicit remote registry connection
records on bots.

## How People Use Octopus

Octopus has two primary user roles:

- **end users** interact with the bot in Telegram
- **operators** manage bots and work through the CLI and registry UI

### End Users

For most users, Octopus is just a Telegram chat bot.

- send a normal message to ask for work
- use `/help` for command discovery
- if approval mode is enabled, the bot pauses for review before executing
- if routed work is used, the parent reply still comes back into the same
  Telegram chat

Most users can get started with:

```text
/help
/project <name>
```

### Operators

Operators work through two surfaces:

- the `./octopus` CLI
- the local registry UI at `/ui`

Core registry UI routes:

- **Dashboard**: open conversations, running work, recent completions,
  follow-up items, and agent health
- **Approvals**: pending operator decisions
- **Agents**: roster plus direct open-conversation actions
- **Conversations**: active thread list and quick-start row
- **Conversation detail**: one workspace for replies, routing, tasks, and full
  activity
- **Tasks**: cross-conversation routed-task queue
- **Usage**: per-conversation token and cost rollups
- **Skills** and **Guidance**: operator management surfaces

## Shared Workspaces

Workspaces let multiple bots collaborate on the same host directory mounted at
`/workspace/<name>` inside the container.

Use:

1. `./octopus`
2. `Workspaces`
3. create the workspace
4. attach bots
5. restart the affected bots

Each member bot receives a `BOT_PROJECTS` entry, so users can switch into the
workspace with `/project <name>`.

## Skills And Guidance

Skills and guidance share one backend lifecycle across the registry UI and chat
clients.

The user-facing skill model has three layers:

- `Catalog`
- `Installed on bot`
- `Active in conversation`

And these orthogonal labels:

- `Source`: `Core`, `Store`, `Custom`
- `Setup`: `Needs setup`, `Ready`
- `Lifecycle`: draft through published/archive for custom skills

Current product behavior:

- `Core` skills ship with the bot runtime and can be turned on by default with
  `BOT_SKILLS`
- `Store` skills come from the remote skill store and can be installed on a bot
  from the browser **Skills** page or chat `/skills install ...`
- the browser **Skills** page manages what is installed on a bot and the custom
  skill lifecycle
- conversation activation is separate and happens in a conversation’s
  **Skills** panel or via chat `/skills add ...`
- guidance is provider-level instruction state for Claude/Codex behavior and is
  managed through Telegram `/guidance ...` commands or the browser
  **Guidance** page

Custom skills now use the same shared package model across the registry UI and
chat clients. A mutable draft can include:

- metadata: `name`, `display_name`, `description`
- instructions: `body`
- setup requirements: `requirements`
- provider extensions: `provider_config`
- supporting artifacts: `files`

The registry **Skills** page is the richest wrapper over those shared
operations, but it is not a different system. Telegram exposes the same draft
capability graph through `/skills ...` commands, including:

- `/skills package <name>` to inspect the full draft package as JSON
- `/skills package <name> <json>` to replace the full draft package

Submit and publish always invoke backend validation. Validation and
publish-readiness are derived from the package contents, not guessed separately
by each client. File and script policy is also shared across clients:

- safe relative paths only
- reserved skill-package filenames may not be reused
- only `.sh` files may be marked executable
- at most 16 attached files
- 64 KB per file, 256 KB total across attached files

If you need the full shared skill model, package format, lifecycle, and
provider guidance structure, see
[docs/skills-model.md](/Users/tinker/output/bots/telegram-agent-bot/docs/skills-model.md),
[ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md)
and [docs/manual/README.md](/Users/tinker/output/bots/telegram-agent-bot/docs/manual/README.md).

## Troubleshooting

If something fails:

1. `./octopus status`
2. `./octopus doctor <bot>`
3. inspect the relevant `.deploy/.../.env` file and registry settings

If `./octopus status --live-provider` or `Diagnose -> Provider auth` shows
`configured, unable to authenticate` for a provider, the auth files are
present but the provider login is no longer valid. Run `./octopus`, choose
`Diagnose`, then `Provider auth`, and complete the provider login flow again.

If a bot shows `execution faulted`, fix the underlying provider/account issue
first, then open the bot in the registry UI and use **Reset execution**. The
reset clears the latched fault and allows the next real request through. If
the provider is still broken, the bot faults again on that request and stays
blocked.

If a remote registry connection fails:

1. confirm the URL is `https://...`
   or `http://...` if that registry intentionally allows plain HTTP
2. confirm the enrollment token and scope values
3. inspect the indexed `BOT_AGENT_REGISTRY_<n>_*` env records
4. run `./octopus doctor <bot>` and inspect per-registry state

## Repo Layout

The codebase is split into three main packages:

- `app/`: shipped Telegram bot runtime and the `./octopus` CLI
- `octopus_registry/`: standalone registry service, websocket layer, store,
  ingress, and operator SPA
- `octopus_sdk/`: shared runtime contracts, workflows, registry protocols,
  composition seams, and test-only fixtures (`octopus_sdk/testing/`)

## Documentation

- [ARCHITECTURE.md](/Users/tinker/output/bots/telegram-agent-bot/ARCHITECTURE.md):
  registry, bot SDK, bot implementation, extending Octopus, and cross-cutting concerns
- [docs/manual/README.md](/Users/tinker/output/bots/telegram-agent-bot/docs/manual/README.md):
  operator and user manual
- [docs/registry-guide.md](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-guide.md):
  registry lifecycle and browser walkthrough
- [docs/flows-catalog.md](/Users/tinker/output/bots/telegram-agent-bot/docs/flows-catalog.md):
  flow inventory with code pointers

**Repo:** [github.com/privacynow/octopus](https://github.com/privacynow/octopus)
