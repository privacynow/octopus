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
- a Telegram-backed bot configuration for each local agent you create today

Octopus uses Docker to run those services. Docker is the local app that keeps
the Registry, database, and agents isolated from the rest of your computer. For
normal Octopus use, you should not need to learn Docker commands.

The `./octopus` command is the Octopus control panel. It starts the local stack,
shows health, helps configure agents, and provides operator actions such as
logs, diagnostics, restarts, and provider login.

Important current constraint: new local agents are created through
Telegram-backed bot setup. You can use the browser Registry as your main product
surface after that, but the first working agent still needs a Telegram bot token
today.

## What You Need

You need:

- Docker Desktop or Docker Engine
- Git
- Python 3
- a Telegram account so you can create a bot token with BotFather
- access to at least one model provider used by your agents, such as Codex or
  Claude

Provider authentication means Octopus can use your approved model-provider
account inside the local agent container. It is not a Telegram token and it is
not the Registry login. Without provider auth, an agent may appear in the UI but
fail when it tries to do model-backed work.

A Telegram bot token creates the local agent identity. Provider auth lets that
agent use a model. You need both for a useful first environment.

## Mac Setup

1. Install Docker Desktop for Mac.
2. Open Docker Desktop.
3. Wait until Docker Desktop says it is running.
4. Install Git if it is not already installed. On many Macs, this command opens
   Apple's command line tools installer:

```bash
xcode-select --install
```

5. Confirm Git and Python 3 exist:

```bash
git --version
python3 --version
```

If Python is missing, or if later setup says `venv` is unavailable, install a
current Python 3 from [python.org](https://www.python.org/downloads/macos/) or
with Homebrew:

```bash
brew install python
```

Then open a new terminal and run `python3 --version` again.

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

Keep the Octopus checkout inside Ubuntu's Linux filesystem, for example
`~/octopus`. Avoid cloning under `/mnt/c/...`; that Windows-mounted path is
slower and can create file permission problems. When the Registry is running,
open `http://127.0.0.1:8787/ui` from your normal Windows browser.

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
git clone https://github.com/privacynow/octopus.git ~/octopus
cd ~/octopus
```

If your team uses a private repository URL, use the HTTPS clone URL they provide
and sign in when Git asks. SSH clone URLs are fine too, but only use them if you
already have GitHub SSH keys configured.

## Start Octopus

Run:

```bash
./octopus
```

The first run may take longer because Octopus creates a Python virtual
environment and builds local images.

If the CLI shows recommended actions, start there. For a first environment, the
usual order is:

1. add a bot or agent configuration
2. authenticate that agent's provider, such as Codex or Claude
3. start the Registry
4. start stopped bots
5. run `./octopus status`

## Create The First Agent

Octopus needs at least one agent before it can do useful work. Today, the
supported CLI path creates that agent as a Telegram-backed bot runtime.

Create a Telegram bot token with BotFather:

1. Open Telegram.
2. Start a chat with [BotFather](https://t.me/BotFather).
3. Send `/newbot`.
4. Choose a display name.
5. Choose a username that ends in `bot`.
6. Copy the token BotFather gives you.
7. Paste it into the Octopus CLI when asked.

Then choose the provider for that agent, such as `codex` or `claude`.

Treat the Telegram token like a password. Do not paste it into documents,
screenshots, chats, or tickets.

You can still use the browser Registry UI as the main product surface. Telegram
chat is optional for day-to-day use, but the Telegram-backed bot setup is
currently how new local agents are created. If no Telegram-backed agents have
been configured and started, the Registry will not have agents to show.

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

What to expect:

- Codex-backed agents usually show a device-login URL and code. Open the URL in
  your browser, enter the code, sign in, approve access, then return to the
  terminal.
- Claude-backed agents usually open an interactive Claude session. If it is not
  already logged in, run `/login`, finish the browser or token flow, then run
  `/exit`.
- Each provider is checked separately.
- If you do not plan to use a provider, that provider can remain unconfigured.

Healthy provider auth means the agent can actually execute model-backed work.
After login, run `./octopus status` again and confirm the provider no longer
shows as unconfigured.

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

A healthy first environment should look broadly like this:

```text
Registry: running
Registry UI: http://127.0.0.1:8787/ui
Connected bots:
  - my-agent: connected, execution healthy, provider codex
Provider auth:
  codex: configured
```

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
start or configure a Telegram-backed bot from the CLI. Until at least one of
those bots is configured and started, `Work -> Agents` will be empty.

`Provider auth not configured`

The agent cannot use its model provider yet. Run `./octopus`, then
`Diagnose -> Provider auth`.

`Agent connected but not execution healthy`

The Registry can see the agent, but the agent cannot complete model-backed
work. Check provider auth and run `./octopus doctor <bot>`.

`Telegram bot token missing or rejected`

The first supported local agent setup needs a Telegram bot token. Create a token
with BotFather, paste the token exactly, and make sure the bot username ends in
`bot`.

`Telegram commands do not work`

The Telegram bot token or Telegram-side command setup is incomplete. The agent
can still be useful through the browser Registry if it is connected and
execution-healthy. Use [TELEGRAM.md](TELEGRAM.md) for Telegram command details.

## After Setup

Use these next, in a sensible order for most people:

- [USER_GUIDE.md](USER_GUIDE.md) for the normal browser workflow
- [PROTOCOLS.md](PROTOCOLS.md) for repeatable staged workflows, including Auto
  Protocol when you want a structured first draft from plain language
- [TELEGRAM.md](TELEGRAM.md) when Telegram is part of your environment
- [OPERATIONS.md](OPERATIONS.md) for health checks, logs, demo readiness, and
  troubleshooting
