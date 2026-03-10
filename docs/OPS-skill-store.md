# Skill Store Operations Guide

## Overview

The skill store provides managed skill distribution via an immutable
content-addressed object store. Admins install, update, and uninstall
skills through Telegram commands. Skills resolve through a three-tier
model: **custom** overrides take priority, then **managed** refs, then
**built-in catalog** skills.

When `BOT_REGISTRY_URL` is configured, skills can also be fetched from a
remote registry with SHA-256 digest verification.

## Directory Layout

```
skills/
  catalog/              # built-in skills, always available
  store/                # bundled skill sources for install
    my-skill/
      skill.md          # required — frontmatter + instructions
      requires.yaml     # optional — credential requirements
      claude.yaml       # optional — Claude provider config
      codex.yaml        # optional — Codex provider config

<data_dir>/skills/
  custom/               # user-created skills (editable)
    my-custom-skill/
      skill.md
  managed/
    objects/<sha256>/    # immutable content-addressed skill content
    refs/<name>.json    # name → digest mapping with provenance
    version.json        # schema version guard
    .lock               # cross-instance file lock for mutations
```

## Three-Tier Resolution

When the bot resolves a skill name, it checks in order:

1. `custom/<name>` — user-created, fully editable
2. `managed/refs/<name>.json` → `managed/objects/<digest>/` — immutable managed skill
3. `catalog/<name>` — built-in, ships with the repo

The first match wins. A custom skill with the same name as a managed
skill shadows it. `/skills info` and `/skills list` always show the
resolved tier.

## Configuration

### BOT_ADMIN_USERS

Controls who can install, uninstall, and update managed skills.

```bash
BOT_ADMIN_USERS=@alice,123456789
```

If unset, falls back to `BOT_ALLOWED_USERS`. Set explicitly in
multi-user deployments.

### BOT_SKILLS

Default skills activated for new chats.

```bash
BOT_SKILLS=code-review,debugging
```

### BOT_REGISTRY_URL

Remote skill registry for `/skills search` and `/skills install`
fallback.

```bash
BOT_REGISTRY_URL=https://registry.example.com/skills/index.json
```

## Telegram Commands

### Browsing

| Command | Who | Description |
|---|---|---|
| `/skills search <query>` | any user | Search bundled store and registry |
| `/skills info <name>` | any user | Show resolved skill details and compatibility |

### Installation

| Command | Who | Description |
|---|---|---|
| `/skills install <name>` | admin | Install from bundled store or registry |
| `/skills uninstall <name>` | admin | Remove managed ref and sweep from all sessions |

Install creates an immutable object and writes a ref. If a custom skill
with the same name exists, it shadows the managed version (both coexist).

Uninstall removes the ref. Orphaned objects are cleaned up by GC at
startup.

### Updates

| Command | Who | Description |
|---|---|---|
| `/skills updates` | any user | Compare managed refs against store sources |
| `/skills update <name>` | admin | Update the managed ref to current store content |
| `/skills update all` | admin | Update all non-pinned managed refs |
| `/skills diff <name>` | any user | Show content diff for a managed skill |

Both update commands check prompt size across all chats where updated
skills are active and warn if the composed prompt exceeds the threshold.

### Per-Chat Activation

| Command | Description |
|---|---|
| `/skills add <name>` | Activate in current chat |
| `/skills remove <name>` | Deactivate from current chat |
| `/skills list` | Show active skills with tier tags |

`/skills list` shows `(managed)`, `(custom)`, and `[custom override]`
tags to indicate the resolved tier.

## Managed Ref Format

Each managed ref is a JSON file at `managed/refs/<name>.json`:

```json
{
  "digest": "a1b2c3...",
  "source": "store",
  "installed_at": "2026-03-08T15:30:00+00:00",
  "pinned": false
}
```

| Field | Purpose |
|---|---|
| `digest` | SHA-256 of the skill content — points to `objects/<digest>/` |
| `source` | `"store"` or `"registry"` |
| `installed_at` | ISO 8601 timestamp |
| `pinned` | If true, `/skills update all` skips this ref |

Registry-installed refs also carry `publisher` and `version` metadata.

## Immutable Object Store

Objects live at `managed/objects/<sha256>/` and are never modified after
creation. Content hashing is deterministic: files sorted by relative
path, each contributing path and content bytes to a single SHA-256 digest.

Install and update are atomic ref swaps — the new object is written
first, then the ref is updated via write-to-tmp + `os.rename`.

## Registry Integration

When `BOT_REGISTRY_URL` is set:

- `/skills search` falls back to the registry after checking the bundled
  store
- `/skills install` falls back to the registry when a skill is not found
  locally
- Downloaded artifacts are verified against the registry's SHA-256 digest
  before creating objects
- Digest mismatch rejects the install — no ref is created

## Startup GC

At startup, the store runs conservative garbage collection:

- Unreferenced objects older than 1 hour are removed
- Stale `.tmp` directories and ref temps are cleaned
- Schema version is checked; the store refuses to operate if the schema
  is newer than the code supports

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

### Optional files

**`requires.yaml`** — credential requirements:

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

**`claude.yaml`** / **`codex.yaml`** — provider-specific config.

### Prompt size

The bot warns when the composed system prompt exceeds the threshold. Keep
skill instructions concise. Test with `/skills add` and check for
warnings.

## Troubleshooting

### "Only admins can install store skills"
The user is not in `BOT_ADMIN_USERS`.

### "Skill not found"
Not in bundled store, custom dir, or registry. Check the name and
whether `BOT_REGISTRY_URL` is configured.

### "Schema version mismatch"
The managed store was written by a newer version of the bot. Update the
bot code or delete `managed/version.json` to reset (will lose managed
state).

### Custom skill shadows managed version
A custom skill in `custom/<name>` takes priority. Remove the custom
skill to use the managed version, or keep it as an intentional override.
