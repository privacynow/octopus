# Telegram Agent Bot

Talk to **Claude Code** or **Codex CLI** from Telegram — your phone, desktop, or a group chat.

**Repo**: [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## How It Works

```
  +----------+       +-------------------+       +--------------------+
  |          |  msg  |                   |  run  |                    |
  |   You    +-------> Telegram Agent Bot+------->  Claude / Codex   |
  |          |       |                   |       |                    |
  +----+-----+       +--------+----------+       +---------+----------+
       ^                      |                            |
       |        reply         |         reads & writes     |
       +----------------------+                   +--------v---------+
                                                  |   Your Files &   |
                                                  |  Working Directory|
                                                  +------------------+
```

You send a message in Telegram. The bot forwards it to a local coding agent. The agent works on your files and sends the answer back to the same chat.

## Why People Use It

- **Work from anywhere** — talk to your coding agent from your phone, laptop, or a group chat.
- **Stay in control** — review a plan before the bot executes anything.
- **Exchange files** — upload logs, screenshots, or documents and get files back.
- **Add skills** — extend the bot with integrations, domain knowledge, and workflow automation.
- **Run multiple bots** — each instance gets its own token, provider, model, and history.

## Get Started

You need Python 3.12+ and the CLI for your chosen provider (`claude` or `codex`) installed.

```bash
git clone git@github.com:privacynow/octopus.git ~/telegram-agent-bot
cd ~/telegram-agent-bot
./setup.sh
```

The setup wizard walks you through:

1. choosing a bot instance name
2. creating or pasting a Telegram bot token from `@BotFather`
3. selecting a provider and model
4. choosing who can talk to the bot
5. reviewing the config
6. optionally launching it as a background service

When it finishes, message your bot in Telegram and start using it.

## Using the Bot

### Ask for work

Send a normal message:

> "Review this diff and suggest a safer refactor."

Upload files and ask:

> "Summarize these logs and tell me what broke."

### Review before execution

Turn on approval mode and the bot shows you a plan before doing anything.

```
                     You send a request
                            |
                            v
                  Bot generates a plan
                            |
                            v
                    +-------+-------+
                    |               |
                 Approve          Reject
                    |               |
                    v               v
           Bot executes task   Nothing runs
                    |
                    v
          You get the result
```

Use `/approval on` to enable this. Use `/approve` or `/reject` (or the inline buttons) to respond.

### Work with files

Upload logs, screenshots, or documents alongside your message. The bot passes them to the agent and can send files back when done.

```
  You upload         Bot saves         Agent reads        Agent creates
   a file     --->   it locally  --->  & processes  --->  output files
                                                              |
                                                              v
                                                     Bot sends files
                                                      back to you
```

Use `/send <path>` to retrieve any file the agent created.

### Use skills

Skills extend the bot with domain knowledge, integrations, and custom behavior.

```
  /skills list             /skills add             Needs           Skill
  See what's    --->    github-integration  --->  credentials? --> is active!
  available                                        |
                                                   v
                                              Bot asks you,
                                              then deletes
                                             the secret message
```

If a skill would make the prompt too large, the bot warns you first.

### Compact mode for mobile

Long responses get summarized automatically when compact mode is on. Use `/raw` to see the full output whenever you need it.

## Commands

### Everyday

| Command | What it does |
|---|---|
| `/help` | Show command help |
| `/new` | Start a fresh conversation |
| `/cancel` | Cancel a pending request or credential setup |
| `/session` | Show the current chat's state |
| `/model [profile]` | View or switch the model profile |
| `/compact on\|off` | Summarize long responses for mobile |
| `/raw [N]` | Retrieve the full raw model output |
| `/export` | Download recent conversation history |
| `/id` | Show your Telegram user ID and username |

### Approval flow

| Command | What it does |
|---|---|
| `/approval on\|off\|status` | Control plan approval mode |
| `/approve` / `/reject` | Approve or reject the current plan |

### Skills

| Command | What it does |
|---|---|
| `/skills` | Show active skills in this chat |
| `/skills list` | Show all available skills and readiness |
| `/skills add <name>` | Activate a skill |
| `/skills remove <name>` | Deactivate a skill |
| `/skills clear` | Remove all active skills |
| `/skills setup <name>` | Re-enter credentials for a skill |
| `/skills info <name>` | Show skill details and compatibility |
| `/skills search <query>` | Search the skill store |

### Files and customization

| Command | What it does |
|---|---|
| `/send <path>` | Send a local file back into Telegram |
| `/role [text]` | Set or reset the bot persona for this chat |
| `/project list\|use\|clear` | Manage per-chat project bindings |
| `/policy inspect\|edit` | Set file access policy for this chat |
| `/clear_credentials [skill]` | Remove your stored skill credentials |

## For Operators

If you run the bot yourself, these resources cover setup, administration, and internals:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and contracts
- [docs/OPS-skill-store.md](docs/OPS-skill-store.md) — skill store operations
- [docs/PLAN-commercial-polish.md](docs/PLAN-commercial-polish.md) — product roadmap
- [docs/STATUS-commercial-polish.md](docs/STATUS-commercial-polish.md) — current status
- [.env.example](.env.example) — environment variable reference

### Operator commands

| Command | What it does |
|---|---|
| `/doctor` | Run a health check on the bot |
| `/skills create <name>` | Scaffold a custom skill |
| `/skills install <name>` | Install a skill from the store |
| `/skills uninstall <name>` | Remove a store skill |
| `/skills update <name>` | Update a managed skill |
| `/skills update all` | Update all managed skills |
| `/skills updates` | Show managed skill update status |
| `/skills diff <name>` | Show differences for a managed skill |

### Development

```bash
./scripts/bootstrap.sh          # create venv, install deps + dev deps
.venv/bin/python -m pytest      # run tests (sequential)
.venv/bin/python -m pytest -n auto  # run tests (parallel)
./scripts/test_all.sh           # pytest + bash setup wizard tests
./scripts/doctor.sh <instance>  # health check a running instance
```

Full test suite covers setup, handlers, providers, skills, and transport.
