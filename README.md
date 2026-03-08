# Telegram Agent Bot

Talk to AI through Telegram. Supports **Claude Code** and **Codex CLI** — each bot runs as its own instance with separate config and conversation history.

## Getting Started

You need Python 3.12+ and the CLI for your chosen provider (`claude` or `codex`) installed.

```bash
git clone <repo-url> ~/telegram-agent-bot
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

| Command | What it does |
|---|---|
| `/new` | Start a fresh conversation |
| `/approval on\|off` | Toggle plan approval before execution |
| `/approve` / `/reject` | Approve or reject a pending plan |
| `/send <path>` | Have the bot send you a file |
| `/id` | Show your Telegram user ID |
| `/help` | Show all commands |

**Approval flow**: When enabled (default), the bot generates a read-only plan before making any changes. You approve or reject via buttons in the chat.

**File exchange**: You can upload files to the bot. The model can send files back in its response.

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
| `BOT_TIMEOUT_SECONDS` | `300` | Max seconds per request. Use `3600` for long generations. |
| `BOT_APPROVAL_MODE` | `on` | Preflight plan approval |
| `BOT_MODEL` | provider default | e.g. `claude-opus-4-6`, `gpt-5.4` |
| `BOT_WORKING_DIR` | `$HOME` | Where the CLI runs |

## Development

```bash
./scripts/bootstrap.sh                                    # create venv
for t in tests/test_*.py; do .venv/bin/python "$t"; done  # python tests
bash tests/test_setup.sh                                  # setup wizard tests
./scripts/doctor.sh <instance>                            # health check
```
