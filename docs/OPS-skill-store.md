# Skill Store Operations Guide

## Overview

The skill store is a local directory (`skills/store/`) that acts as a curated catalog of installable skills. Admins can browse, install, update, and uninstall store skills via Telegram commands. Installed skills are copied to the custom skills directory (`~/.config/telegram-agent-bot/skills/`) with a `_store.json` provenance manifest.

## Directory Layout

```
skills/
  catalog/          # built-in skills, always available
  store/            # store skills, installable by admins
    my-skill/
      skill.md      # required — frontmatter + instructions
      requires.yaml # optional — credential requirements
      claude.yaml   # optional — Claude provider config
      codex.yaml    # optional — Codex provider config

~/.config/telegram-agent-bot/skills/
  my-skill/         # installed copy (same structure as above)
    _store.json     # provenance manifest (auto-generated)
```

## Configuration

### BOT_ADMIN_USERS

Controls who can install, uninstall, and update store skills.

```bash
# In your instance .env file:
BOT_ADMIN_USERS=@alice,123456789    # comma-separated usernames and/or IDs
```

If unset, falls back to `BOT_ALLOWED_USERS` (all allowed users are admins). Set this explicitly in multi-user deployments.

### BOT_SKILLS

Default skills activated for new chats. Store-installed skills can be listed here after installation.

```bash
BOT_SKILLS=code-review,debugging,my-store-skill
```

Note: you cannot uninstall a skill that is listed in `BOT_SKILLS`. Remove it from the config first.

## Telegram Commands

All store commands are subcommands of `/skills`.

### Browsing

| Command | Who | Description |
|---|---|---|
| `/skills search <query>` | any user | Substring search on skill name and description |
| `/skills info <name>` | any user | Show skill metadata and full instructions |

### Installation

| Command | Who | Description |
|---|---|---|
| `/skills install <name>` | admin | Copy skill from store to custom dir |
| `/skills uninstall <name>` | admin | Remove store-installed skill, sweep from all chats |

Install copies the skill directory and writes `_store.json`. If a custom (user-created) skill with the same name exists, install refuses — uninstall the custom skill first.

Uninstall:
1. Checks the skill is not in `BOT_SKILLS` (config guard)
2. Removes the skill from `active_skills` in all saved sessions (session sweep)
3. Deletes the installed directory

### Updates

| Command | Who | Description |
|---|---|---|
| `/skills updates` | any user | Compare installed skills against store, show status |
| `/skills update <name>` | admin | Re-install a single skill from store |
| `/skills update all` | admin | Re-install all skills with available updates |

Status values from `/skills updates`:
- **up to date** — installed hash matches store
- **update available** — store content changed since install
- **locally modified** — installed content was edited after install

Both `/skills update <name>` and `/skills update all` check prompt size across all chats where updated skills are active and warn if the composed prompt exceeds 8,000 characters.

### Per-Chat Activation

After installing, users activate/deactivate store skills like any other skill:

| Command | Description |
|---|---|
| `/skills add <name>` | Activate in current chat |
| `/skills remove <name>` | Deactivate from current chat |
| `/skills list` | Show active skills (store-installed show `(store)` tag) |

## Provenance Manifest (_store.json)

Every store-installed skill gets a `_store.json` file:

```json
{
  "content_sha256": "a1b2c3...",
  "installed_at": "2026-03-08T15:30:00+00:00",
  "locally_modified": false,
  "source": "store",
  "store_path": "skills/store/my-skill"
}
```

| Field | Purpose |
|---|---|
| `source` | Always `"store"` — distinguishes from user-created skills |
| `store_path` | Relative path to the store source directory |
| `installed_at` | ISO 8601 UTC timestamp of last install/update |
| `content_sha256` | SHA-256 of all files at install time (excludes `_store.json`) |
| `locally_modified` | Set to `true` when `check_updates()` detects local edits |

The hash is computed deterministically: files sorted by relative path, each contributing its path and content bytes to a single SHA-256 digest.

## Authoring a Store Skill

### Minimum viable skill

Create a directory in `skills/store/` with a `skill.md`:

```markdown
---
name: my-skill
display_name: My Skill
description: One-line description shown in search results
---

Instructions injected into the system prompt when this skill is active.
```

The frontmatter fields:
- `name` — must match the directory name
- `display_name` — human-readable name
- `description` — shown in `/skills search` and `/skills info`

### Optional files

**`requires.yaml`** — credential requirements. The bot prompts users for setup via `/skills setup <name>`:

```yaml
credentials:
  - key: API_TOKEN
    prompt: "Paste your API token"
    help_url: https://example.com/tokens
    validate:
      method: GET
      url: https://api.example.com/me
      header: "Authorization: Bearer ${API_TOKEN}"
      expect_status: 200
```

**`claude.yaml`** / **`codex.yaml`** — provider-specific config (tool permissions, allowed commands, etc.).

### Prompt size

The bot warns when the composed system prompt (role + all active skills) exceeds 8,000 characters. Keep skill instructions concise. Test with `/skills add` and check if a warning appears.

## Content Hashing

SHA-256 verification runs at two points:

1. **Post-install** — immediately after copying, the installed directory is re-hashed and compared against the store source. If they differ (filesystem corruption), the install is rolled back.
2. **Update check** — `check_updates()` compares the installed hash against the manifest hash (local modification detection) and the store hash (update detection).

## Troubleshooting

### "Only admins can install store skills"
The user is not in `BOT_ADMIN_USERS`. Either add them or set the variable to include their username/ID.

### "Skill 'X' already exists as a custom skill"
A user-created skill in `~/.config/telegram-agent-bot/skills/X/` has no `_store.json`. Remove it manually or via the filesystem before installing the store version.

### "Skill 'X' is listed in BOT_SKILLS"
Cannot uninstall a skill that the operator configured as a default. Remove it from `BOT_SKILLS` in the `.env` file first.

### "SHA-256 verification failed after install"
Filesystem issue during copy. Check disk space and permissions on `~/.config/telegram-agent-bot/skills/`.

### Locally modified skill won't update
Updates overwrite local modifications with a warning. This is intentional — the store version is the source of truth. If you need local customizations, create a separate custom skill instead.
