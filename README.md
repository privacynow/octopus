# Telegram Agent Bot

Talk to AI through Telegram. Supports **Claude Code** and **Codex CLI** — each bot runs as its own instance with separate config and conversation history.

**Repo**: [github.com/privacynow/octopus](https://github.com/privacynow/octopus)

## Getting Started

You need Python 3.12+ and the CLI for your chosen provider (`claude` or `codex`) installed.

```bash
git clone git@github.com:privacynow/octopus.git ~/telegram-agent-bot
cd ~/telegram-agent-bot
./setup.sh
```

The setup wizard walks you through everything:

1. Picks an instance name (e.g. `my-claude`)
2. Guides you through creating a Telegram bot via @BotFather and validates the token
3. Asks which provider and model to use
4. Asks who should have access (Telegram `@usernames` or numeric IDs)
5. Shows a summary of your configuration
6. Offers to launch the bot as a background service

Once running, send a message to your bot on Telegram.

To add another bot, run `./setup.sh` again. Each bot needs its own @BotFather token.

## Using the Bot

### Core Commands

| Command | What it does |
|---|---|
| `/new` | Start a fresh conversation |
| `/cancel` | Cancel a running request |
| `/approval on\|off` | Toggle plan approval before execution |
| `/approve` / `/reject` | Approve or reject a pending plan |
| `/send <path>` | Have the bot send you a file |
| `/id` | Show your Telegram user ID |
| `/help` | Show all commands (tiered — admins see more) |

### Skills

| Command | What it does |
|---|---|
| `/skills list` | Show active skills and credential status |
| `/skills add <name>` | Activate a skill |
| `/skills remove <name>` | Deactivate a skill |
| `/skills diff <name>` | Show local modifications to a skill |
| `/skills search <query>` | Find available skills in the store |
| `/skills install <name>` | Install from store (admin) |
| `/skills uninstall <name>` | Remove from store (admin) |
| `/skills updates` | Check for new versions |
| `/skills update all` | Update everything (admin) |

After installing, any user can activate a store skill in their chat with `/skills add <name>`. See [docs/OPS-skill-store.md](docs/OPS-skill-store.md) for the full operations guide.

### Mobile & Output

| Command | What it does |
|---|---|
| `/compact on\|off` | Toggle response summarization (shorter for mobile) |
| `/raw [N]` | Retrieve full raw response (default: latest) |
| `/export` | Download recent conversation history (last 50 turns) |

### Admin & Diagnostics

| Command | What it does |
|---|---|
| `/doctor` | Health check — provider status, stale sessions, config |
| `/admin sessions` | List all active sessions (admin) |
| `/clear_credentials` | Remove stored skill credentials |
| `/role [text]` | Set or clear bot persona |
| `/session` | Show current session info |

### Key Features

**Approval flow**: When enabled (default), the bot generates a read-only plan before making changes. You approve or reject via inline buttons. After approval, the bot executes with full permissions — no redundant permission prompts.

**File exchange**: Upload files to the bot. The model can send files back in its response.

**Rate limiting**: Admins can set per-user rate limits (per-minute and per-hour) to control costs.

**Compact mode**: Long responses are automatically summarized using a fast model. Use `/raw` to retrieve the full output when needed.

**Prompt size warnings**: Large skill prompts trigger a confirmation before sending to the provider, preventing surprise costs.

## Managing Bots

```bash
systemctl --user status telegram-agent-bot@my-claude    # check status
systemctl --user restart telegram-agent-bot@my-claude   # restart
journalctl --user -u telegram-agent-bot@my-claude -f    # view logs
```

## Configuration

Config lives at `~/.config/telegram-agent-bot/<instance>.env`. The setup wizard creates this for you. To edit later:

```bash
$EDITOR ~/.config/telegram-agent-bot/my-claude.env
systemctl --user restart telegram-agent-bot@my-claude
```

See `.env.example` for all available options. Key settings:

| Setting | Default | Notes |
|---|---|---|
| `BOT_PROVIDER` | `claude` | `claude` or `codex` |
| `BOT_MODEL` | provider default | e.g. `claude-opus-4-6`, `gpt-5.4` |
| `BOT_TIMEOUT_SECONDS` | `300` | Max seconds per request. Use `3600` for long generations. |
| `BOT_APPROVAL_MODE` | `on` | Preflight plan approval |
| `BOT_WORKING_DIR` | `$HOME` | Where the CLI runs |
| `BOT_ADMIN_USERS` | same as allowed | Who can install/update store skills |
| `BOT_SKILLS` | *(none)* | Default skills for new chats (comma-separated) |
| `BOT_RATE_LIMIT_PER_MINUTE` | `0` (off) | Max requests per user per minute |
| `BOT_RATE_LIMIT_PER_HOUR` | `0` (off) | Max requests per user per hour |
| `BOT_COMPACT_MODE` | `off` | Enable response summarization by default |
| `BOT_SUMMARY_MODEL` | `claude-haiku-4-5-20251001` | Model used for compact summaries |

## Development

```bash
./scripts/bootstrap.sh                                    # create venv
./scripts/test_all.sh                                     # canonical full test suite (1,459 checks)
./scripts/doctor.sh <instance>                            # health check
```

### Architecture

| Module | Purpose |
|--------|---------|
| `app/transport.py` | Inbound normalization — converts Telegram updates into frozen dataclasses before business logic |
| `app/telegram_handlers.py` | Command/message/callback handlers, approval flow, provider execution |
| `app/skills.py` | Skill catalog, prompt composition, credential management, three-tier resolution |
| `app/store.py` | Immutable content-addressed skill store with atomic refs and GC |
| `app/storage.py` | Per-chat JSON session persistence |
| `app/providers/` | CLI provider abstraction (Claude, Codex) |
| `app/formatting.py` | Markdown-to-Telegram HTML conversion and message splitting |

See [docs/PLAN-commercial-polish.md](docs/PLAN-commercial-polish.md) for the roadmap and [docs/STATUS-commercial-polish.md](docs/STATUS-commercial-polish.md) for current progress.
