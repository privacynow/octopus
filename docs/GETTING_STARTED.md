# Getting Started

This guide gets a new user from nothing installed to a running Octopus Registry
with at least one agent ready for work.

It assumes you may not know Docker, provider authentication, or the Octopus CLI
yet. That is fine. The goal is to get the product open, healthy, and ready for a
first browser workflow.

## What You Are Starting

Octopus runs several local services on your computer:

- the Registry backend and browser UI
- a local database for Registry state
- one or more agent runtimes
- optional Telegram-facing bot access

Octopus uses Docker to run those services. Docker is the local app that keeps
the Registry, database, and agents isolated from the rest of your computer. For
normal Octopus use, you should not need to learn Docker commands.

The `./octopus` command is the Octopus control panel. It starts the local stack,
shows health, helps configure agents, and provides operator actions such as
logs, diagnostics, restarts, and provider login.

## What You Need

You need:

- Docker Desktop or Docker Engine
- Git
- Python 3
- access to at least one model provider used by your agents, such as Codex or
  Claude
- a Telegram bot token only if the CLI asks you to create a Telegram-backed
  agent or you plan to use Telegram

Provider authentication means Octopus can use your approved model-provider
account inside the local agent container. It is not a Telegram token and it is
not the Registry login. Without provider auth, an agent may appear in the UI but
fail when it tries to do model-backed work.

## Mac Setup

1. Install Docker Desktop for Mac.
2. Open Docker Desktop.
3. Wait until Docker Desktop says it is running.
4. Install Git if it is not already installed. On many Macs, this command opens
   Apple's installer:

```bash
xcode-select --install
```

5. Confirm Python 3 exists:

```bash
python3 --version
```

If that prints a Python version, continue.

## Windows Setup

Use WSL2 with Ubuntu. That is the clearest Windows path for this repository
because the Octopus launcher is a Bash script.

1. Install Docker Desktop for Windows.
2. During Docker setup, enable WSL2 integration.
3. Install Ubuntu from the Microsoft Store if you do not already have it.
4. Open Docker Desktop and wait until it is running.
5. Open Ubuntu, not PowerShell, for the commands below.
6. In Docker Desktop, confirm Ubuntu integration is enabled.
7. In Ubuntu, install the basic command-line tools:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

8. In Ubuntu, confirm Docker is reachable:

```bash
docker ps
```

If Docker is not reachable from Ubuntu, check Docker Desktop's WSL integration
settings before continuing.

## Linux Or Ubuntu Setup

Linux users can use Docker Engine with the Docker Compose plugin, or Docker
Desktop for Linux.

Confirm these commands work:

```bash
docker ps
docker compose version
python3 --version
git --version
```

If `docker ps` requires `sudo`, either use your normal local Docker setup or add
your user to the Docker group according to your Linux distribution's Docker
instructions.

On Ubuntu, the usual local prerequisites are:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

## Get The Code

Choose a directory where you keep projects, then clone the repository:

```bash
git clone git@github.com:privacynow/octopus.git ~/octopus
cd ~/octopus
```

If you do not use SSH keys with GitHub, use the HTTPS clone URL your team
provides.

## Start Octopus

Run:

```bash
./octopus
```

The first run may take longer because Octopus creates a Python virtual
environment and builds local images.

If the CLI shows recommended actions, start there. Common first-run actions are:

- add a bot or agent configuration
- authenticate a provider such as Codex or Claude
- start the Registry
- start stopped bots

## Add Or Check An Agent

Octopus needs at least one agent before it can do useful work.

If the CLI asks for a Telegram bot token, create one with BotFather:

1. Open Telegram.
2. Start a chat with [BotFather](https://t.me/BotFather).
3. Send `/newbot`.
4. Choose a display name.
5. Choose a username that ends in `bot`.
6. Copy the token BotFather gives you.
7. Paste it into the Octopus CLI when asked.

Then choose the provider for that agent, such as `codex` or `claude`.

You can still use the browser Registry UI as the main product surface. Telegram
is optional as a user interface, but a Telegram-backed bot configuration may be
part of the local agent setup.

## Authenticate The Model Provider

When Octopus says provider authentication is required, use the CLI flow:

```bash
./octopus
```

Then choose:

```text
Diagnose -> Provider auth
```

Pick the provider that needs login, such as `codex` or `claude`, and finish the
provider's login flow.

What this means:

- Codex-backed agents need Codex authentication.
- Claude-backed agents need Claude authentication.
- Each provider is checked separately.
- If you do not plan to use a provider, that provider can remain unconfigured.

Healthy provider auth means the agent can actually execute model-backed work.

## Check Status

After setup, run:

```bash
./octopus status
```

For a usable first environment, look for:

- Registry: `running`
- at least one connected bot under `Connected bots`
- the target agent marked execution healthy
- provider auth configured for the provider you plan to use
- a Registry URL, normally `http://127.0.0.1:8787/ui`

If an optional bot is stopped because its provider is not configured, that does
not block your first use as long as at least one intended agent is connected and
healthy.

## Open The Registry

Open the URL from `./octopus status`:

- [http://127.0.0.1:8787/ui](http://127.0.0.1:8787/ui)

Then check:

1. `Work -> Agents` shows at least one connected, execution-healthy agent.
2. `Work -> Conversations` can start or open a conversation.
3. `Operations -> Dashboard` does not show a blocking issue for the agent you
   plan to use.

## First Smoke Test

Use a small, non-sensitive request first:

1. Open `Work -> Conversations`.
2. Start or open a conversation with a healthy agent.
3. Send: `Say hello and tell me what workspace you can see.`
4. Wait for the reply.
5. Open `Work -> Agents` and confirm the agent still looks healthy.

After that works, continue to [USER_GUIDE.md](USER_GUIDE.md) for the product
walkthrough.

## Stop Or Restart

To stop the local stack:

```bash
./octopus stop
```

To start it again:

```bash
./octopus
```

To inspect status without changing anything:

```bash
./octopus status
```

## Common First-Run Problems

`Docker is not reachable`

Docker Desktop is not running, or WSL integration is off on Windows. Open Docker
Desktop and wait until it is running. On Windows, enable Ubuntu integration in
Docker Desktop.

`Registry is stopped`

The local web app is not running yet. Run `./octopus`, then choose the
recommended start action.

`No connected bots`

No agent is running or enrolled with the Registry. Run `./octopus status`, then
start or configure a bot from the CLI.

`Provider auth not configured`

The agent cannot use its model provider yet. Run `./octopus`, then
`Diagnose -> Provider auth`.

`Agent connected but not execution healthy`

The Registry can see the agent, but the agent cannot complete model-backed
work. Check provider auth and run `./octopus doctor <bot>`.

`Telegram commands do not work`

The Telegram bot token or Telegram-side setup is incomplete. Use
[TELEGRAM.md](TELEGRAM.md) after the browser workflow is healthy.

## After Setup

Use these next:

- [USER_GUIDE.md](USER_GUIDE.md) for the normal browser workflow
- [PROTOCOLS.md](PROTOCOLS.md) for repeatable staged workflows
- [TELEGRAM.md](TELEGRAM.md) when Telegram is part of your environment
- [OPERATIONS.md](OPERATIONS.md) for health checks, logs, demo readiness, and
  troubleshooting
