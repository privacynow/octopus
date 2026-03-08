# Agent Roles & Skills System — Design Plan

## 1. Problem Statement

Today every bot instance is a generic CLI bridge. The user sends text, the provider CLI processes it, the bot relays the response. There is no way to shape what the agent knows, how it behaves, or what integrations it has access to.

We want three things:

1. **Roles** — a bot operator can give each instance a personality and focus ("Senior Python engineer", "DevOps specialist for our AWS infrastructure")
2. **Skills** — reusable packages of instructions, procedures, and tool integrations that users can browse, add, and remove without editing files or understanding provider internals
3. **An ecosystem path** — a structure where skill publishers can create and share skills, and skill users can discover and activate them through a simple conversational interface

### Three actors

| Actor | Analogy | What they do |
|-------|---------|--------------|
| **Platform operator** | Apple | Runs the bot, maintains the runtime, configures instances via `setup.sh` |
| **Skill publisher** | App developer | Creates skills — writes instructions, declares dependencies, publishes to catalog |
| **Skill user** | App Store customer | Browses available skills, toggles them on/off via Telegram, provides their own credentials when prompted |

The skill user is the primary audience. They should never need to touch a filesystem, edit config files, or understand provider differences.

### What's missing today

- **No system prompt** — raw user text goes straight to the provider CLI
- **No role definition** — no personality, expertise focus, or behavioral constraints
- **No skill system** — no way to attach instructions, procedures, or tool integrations
- **No per-instance differentiation** — two Claude bots behave identically except for model choice

---

## 2. Key Decisions

### D1: Skill format — hybrid with provider escape hatches

A skill is a directory with a universal instruction file and optional provider-specific configuration.

**Simple skill** (instruction-only — the common case):
```
code-review/
  skill.md              # instructions in markdown, YAML frontmatter for metadata
```

**Tool skill** (needs API access or provider-specific features):
```
jira-integration/
  skill.md              # instructions
  requires.yaml         # credential/dependency declarations
  claude.yaml           # optional: Claude-specific config (MCP servers, tool restrictions)
  codex.yaml            # optional: Codex-specific config (scripts, sandbox settings)
```

**Why hybrid**: Simple skills (code review, debugging, team conventions) are just instructions — the same text works for both providers. The platform translates `skill.md` to the provider's native delivery mechanism. But tool-using skills need provider-specific config (MCP servers for Claude, scripts for Codex) that cannot be unified without building a runtime abstraction layer. The escape hatches handle this without penalizing the simple case.

**Why not fully provider-specific**: Most skills are instruction-only. Forcing publishers to maintain `claude.md` + `codex/SKILL.md` duplicates content, raises the publishing barrier, and the instruction text is usually identical anyway.

**Why not fully universal**: Claude and Codex have fundamentally different tool integration mechanisms. A single format that tries to abstract MCP servers and Codex scripts would be a leaky compiler. Provider-specific files let publishers use native capabilities without the platform interpreting them.

### D2: Skill activation is per-chat, hot-loaded with Codex reset on change

Active skills are stored in the session JSON per chat. Different conversations on the same bot can have different skill sets. `BOT_SKILLS` in `.env` sets the default for new chats.

Neither provider maintains a long-running process between messages — each `run()` spawns a fresh subprocess. However, the providers differ in how mid-conversation changes behave:

- **Claude**: `--append-system-prompt` is rebuilt from active skills every `run()` call. It operates outside the conversation history, so changes (additive or subtractive) take effect cleanly on the very next message.
- **Codex**: The prompt prefix is prepended to the user's message text, which means it becomes part of the conversation history on that turn. On a resumed thread, prior turns still contain the old prefix. Additive changes (adding a skill) work fine — the new prefix is a superset. But subtractive or contradictory changes (`/skills remove`, `/role clear`, role replacement) leave stale instructions in thread history that cannot be retracted. To guarantee deterministic behavior, `/skills add`, `/skills remove`, `/skills clear`, `/role set`, and `/role clear` all reset the Codex thread (clear `thread_id` from provider state). The next message starts a fresh thread with only the current role and skills. Conversation context is lost, but the alternative — stale instructions silently competing with current ones — would produce unpredictable behavior that's hard to debug.

**Codex resume and `--add-dir`**: `codex exec resume` does not accept `--add-dir`. This means a resumed Codex thread cannot receive new directory access — the upload dir and any approval-granted dirs passed on the initial `exec` are the only ones available for the life of that thread. In practice this is rarely a problem: the chat-specific upload dir is set on the first message and doesn't change. If new directory access is needed mid-conversation (e.g., from the permission-denial retry flow), the Codex thread must be reset so the next `exec` can include the new `--add-dir` paths. In the current app, permission-denial retries go through the `retry_allow` callback handler (not `approve_pending()`). When `retry_allow` has new `extra_dirs` and the provider is Codex, it must clear `thread_id` before calling `execute_request()`.

This asymmetry is inherent to the Codex CLI and cannot be abstracted away.

### D3: Credentials belong to the user, scoped per user

When a skill requires API keys or tokens (declared in `requires.yaml`), the bot prompts the user on Telegram — same pattern as BotFather token setup.

**Credentials are scoped per user, not per chat or per instance.** A GitHub personal access token belongs to a person, not to a conversation or a bot. In a group chat, multiple users share the same `chat_id` but must have separate credential stores. In private chats, `user_id` and `chat_id` happen to be the same, so the distinction is invisible — but the implementation must use `user_id` as the key.

Storage: credentials live in a per-user credential file at `~/.telegram-agent-bot/<instance>/credentials/<user_id>.json`, encrypted at rest (see §7.3). They are injected into the provider subprocess environment at `run()` time based on the requesting user's stored credentials.

Skills and roles remain per-chat (they describe the conversation's behavior, not the user's identity). Credentials are the exception because they represent individual access.

**Per-request credential check**: When a chat has credentialed skills active, the credential satisfaction check must run before any provider call — both `execute_request()` and `request_approval()`. In the current handler flow, approval-mode traffic hits `request_approval()` first; without the check there, a user would get a preflight plan and approval prompt for a request that can't actually execute. If credentials are missing, the bot replies with a setup prompt (e.g., "github-integration needs your GitHub token. Use `/skills setup github-integration` to configure it.") and skips both preflight and execution. This is implemented as a shared helper called from both paths.

The bot deletes the user's message containing the secret after reading it.

### D4: Skill catalog has three tiers

1. **Built-in** — ships with the repo in `skills/catalog/`. Curated, tested, always available.
2. **Custom** — user-created skills in `~/.config/telegram-agent-bot/skills/`. Same format. Appear alongside built-ins. Override built-ins if same name.
3. **Store** (future) — remote skill registry. Browse, install, rate. Not in scope for initial implementation.

### D5: Structured config for rich definitions, env for operational settings

Lifted from the gateway architecture: `.env` files are good for flat operational config (token, provider, timeout, allowed users) but break down for structured data like role descriptions longer than a sentence.

- **`.env`**: `BOT_ROLE` (short role description or empty), `BOT_SKILLS` (comma-separated defaults for new chats). Keeps simple cases simple. **Important**: `BOT_ROLE` must be properly serialized in the `.env` file — double-quoted with internal `"` escaped as `\"` and `\` escaped as `\\`. Without quoting, `load_dotenv_file()` strips everything after `#` (a role like `Senior C# engineer` becomes `Senior C`). Without escaping, a role containing `"` or `\` produces a broken `.env` entry. `set_env_value()` in `setup.sh` must handle this serialization — not just wrap in quotes, but escape the content. For roles that are too complex for a one-liner, use `role.md` instead (see below).

**Separation of concerns**: `BOT_ROLE` in `.env` is the *instance default* — set by the platform operator via `setup.sh`. The `/role` Telegram command sets a *chat-local override* stored in the session JSON. It does NOT write to `.env`. This means a skill user can customize the role for their conversation without mutating operator-owned instance defaults. New chats still start with the operator's `BOT_ROLE`.
- **`role.md` file** (optional): For roles that need more than a one-liner, the operator can place a markdown file at `~/.config/telegram-agent-bot/<instance>.role.md`. If present, it overrides `BOT_ROLE`. This is the recommended path for rich role descriptions — no quoting issues, supports multi-line markdown, mirrors the gateway's `prompt_file` pattern.

### D6: Codex delivery uses prompt prefix (not filesystem artifacts)

**Spike result (codex-cli 0.111.0)**: Codex does NOT discover `SKILL.md` folders or `AGENTS.md` from `--add-dir` paths. Skill discovery only searches `~/.codex/skills/` (a global, shared directory). `AGENTS.md` is only read from the working directory (`-C` path). Neither mechanism supports per-chat scoping.

**Decision**: Both providers use the same delivery approach — compose role + skill instructions into text and inject it into the prompt. For Claude this is `--append-system-prompt`; for Codex this is a prompt prefix prepended to the user's message. This is simpler, avoids filesystem concurrency issues, and means no generated artifacts are needed on disk.

### D7: Preserve current behavior when no skills are active

If no role or skills are configured, the bot behaves exactly as it does today — no system prompt, no extra flags, no file generation. Zero-change guarantee for existing deployments.

### D8: Provider protocol gets a `RunContext`

The current `Provider.run()` signature passes `provider_state`, `prompt`, `image_paths`, `progress`, and `extra_dirs`. This is not enough for the skill system — providers also need active skill instructions, role text, provider-specific skill flags (MCP config, tool restrictions), and decrypted credential env vars.

Rather than adding many parameters to `run()`, we introduce two context dataclasses:

```python
@dataclass
class PreflightContext:
    """Sanitized context for approval planning — no secrets, no tool wiring."""
    extra_dirs: list[str]
    system_prompt: str           # composed role + skill instructions
    capability_summary: str      # human-readable summary of active tool capabilities (Phase 3)

@dataclass
class RunContext(PreflightContext):
    """Full execution context — extends PreflightContext with secrets and provider config."""
    provider_config: dict        # provider-specific structured config (see below)
    credential_env: dict[str, str]  # decrypted skill credentials for subprocess env
```

**Why two types**: Preflight produces an approval summary — it needs role and skill context so the plan reflects actual execution behavior, but it should NOT receive decrypted credentials (unnecessary secret exposure) or the live provider config (MCP server definitions, scripts) that would force planning runs to initialize integrations they don't use.

**`capability_summary`** (Phase 3): A human-readable text summary of what tool capabilities are active — e.g., "Has access to: GitHub API (via MCP), disk write (sandbox: workspace-write)". This is appended to `system_prompt` so the preflight plan can account for tool-backed capabilities without receiving the actual wiring. In Phase 1 this is empty (`""`).

**`provider_config`** (Phase 3): A structured dict rather than `list[str]` because provider-specific skill config includes things that aren't CLI flags — Codex scripts, sandbox overrides, env vars from `codex.yaml`. Claude config (MCP servers, tool allow/deny lists) also benefits from structured representation rather than pre-serialized flag strings. Each provider interprets the dict according to its own needs. In Phase 1 this is empty (`{}`).

Signatures:

```python
async def run(
    self,
    provider_state: dict[str, Any],
    prompt: str,
    image_paths: list[str],
    progress: ProgressSink,
    context: RunContext | None = None,
) -> RunResult:

async def run_preflight(
    self,
    prompt: str,
    image_paths: list[str],
    progress: ProgressSink,
    context: PreflightContext | None = None,
) -> RunResult:
```

`context=None` preserves backward compatibility and the D7 zero-change guarantee. `execute_request()` builds a `RunContext` for `run()`; `request_approval()` builds a `PreflightContext` for `run_preflight()`. Both are built from the same session state. The preflight context is not a subset of the run context at runtime — it's built separately to ensure secrets never leak into the planning path.

This keeps the provider protocol clean — providers receive structured context objects rather than knowing how to load skills themselves. The skill engine and `telegram_handlers.py` own the composition; providers own the delivery.

---

## 3. Provider Delivery Mechanisms

The skill system must work with both providers. The user never sees this — it's the platform's job to translate.

### 3.1 Claude Code

| Mechanism | How we use it |
|-----------|---------------|
| `--append-system-prompt <text>` | Inject composed role + skill instructions per `run()` call |
| `--allowedTools` / `--disallowedTools` | Skill-specific tool restrictions (from `claude.yaml`) |
| `--mcp-config <json>` | Skill-specific MCP server definitions (from `claude.yaml`) |
| `CLAUDE.md` in `--add-dir` | Not used — `--append-system-prompt` is simpler and immediate |

### 3.2 Codex CLI

| Mechanism | How we use it |
|-----------|---------------|
| Prompt prefix | Prepend composed role + skill instructions to the user's prompt text |
| Scripts (Phase 3) | Staged in a chat-scoped dir and added via `--add-dir` on new threads (see below) |

**Why not filesystem delivery for skills**: Codex only discovers `SKILL.md` from `~/.codex/skills/` (a global shared dir, not per-chat) and `AGENTS.md` from the `-C` working dir only. Prompt prefix is simpler, chat-safe, and consistent with Claude's approach.

**Script staging (Phase 3)**: Unlike instructions (which are text injected via prompt prefix), Codex scripts from `codex.yaml` are actual files that need to be on disk so Codex can execute them. These are staged in a chat-scoped directory (`~/.telegram-agent-bot/<instance>/scripts/<chat_id>/`) and passed via `--add-dir` on new threads. Script content is deterministic (copied from the skill catalog), so concurrent chats with the same skills produce identical files — no clobbering risk. The directory is cleaned up on `/new`. This is a Phase 3 concern; Phase 1-2 have no script delivery.

### 3.3 Translation

For each active skill, the skill engine:

| Step | Claude | Codex |
|------|--------|-------|
| Instructions | Concatenate `skill.md` body text into `--append-system-prompt` | Concatenate `skill.md` body text into prompt prefix |
| Role | Prepend "You are a {role}." to system prompt | Prepend "You are a {role}." to prompt prefix |
| Tool config | Read `claude.yaml` → `provider_config` → MCP/tool flags | Read `codex.yaml` → `provider_config` → sandbox/scripts/env |
| Credentials | Inject env vars into subprocess environment | Same |

---

## 4. Skill Format Specification

### 4.1 `skill.md` (required)

YAML frontmatter + markdown body:

```markdown
---
name: code-review
display_name: Code Review
description: Reviews code for correctness, style, and security issues
---

When reviewing code:
- Focus on correctness first, then readability, then performance
- Flag security issues (injection, auth bypass, secrets in code)
- Suggest concrete fixes, not just problems
- Be direct: "This has a bug" not "You might want to consider..."
- If the code is good, say so briefly and move on
```

Fields:
- `name` (required): hyphen-case identifier, must match directory name
- `display_name` (required): human-readable name for UI
- `description` (required): one-line description shown in `/skills list`
- Body: the actual instructions delivered to the provider

### 4.2 `requires.yaml` (optional)

Declares credentials and dependencies:

```yaml
credentials:
  - key: GITHUB_TOKEN
    prompt: "Paste a GitHub personal access token (needs 'repo' scope)"
    help_url: "https://github.com/settings/tokens/new"
    validate:
      method: GET
      url: "https://api.github.com/user"
      header: "Authorization: Bearer ${GITHUB_TOKEN}"
      expect_status: 200

  - key: JIRA_URL
    prompt: "Your Jira instance URL (e.g. https://yourteam.atlassian.net)"
```

When a user activates a skill with `requires.yaml`, the bot checks if all credentials are already configured for that user. Missing ones are prompted conversationally.

### 4.3 `claude.yaml` (optional)

Provider-specific configuration for Claude instances:

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"

allowed_tools:
  - "mcp__github__*"
  - "Read"
  - "Grep"

disallowed_tools:
  - "Bash(rm:*)"
```

### 4.4 `codex.yaml` (optional)

Provider-specific configuration for Codex instances:

```yaml
sandbox: workspace-write

scripts:
  - name: github-query.sh
    source: scripts/github-query.sh

config_overrides:
  - "sandbox_permissions=[\"disk-full-read-access\"]"
```

### 4.5 Full example: instruction-only skill

```
debugging/
  skill.md
```

One file. Works on both providers. Publisher writes it in 5 minutes.

### 4.6 Full example: tool-integrated skill

```
github-integration/
  skill.md              # instructions for working with GitHub
  requires.yaml         # needs GITHUB_TOKEN
  claude.yaml           # MCP server for @modelcontextprotocol/server-github
  codex.yaml            # scripts for GitHub API access
  scripts/
    github-query.sh     # helper script for Codex
```

---

## 5. Storage Layout

### Instance data (runtime state)

```
~/.telegram-agent-bot/<instance>/
  sessions/<chat_id>.json        # existing — now includes active_skills, role, awaiting_skill_setup
  uploads/<chat_id>/             # existing
  credentials/<user_id>.json     # NEW — per-user encrypted skill credentials
```

Note: credentials are per-user, not per-chat (see §7.3). Sessions no longer contain credential data — only skill activation state and role.

### Instance config (operator settings)

```
~/.config/telegram-agent-bot/
  <instance>.env                 # existing — adds BOT_ROLE, BOT_SKILLS defaults
  <instance>.role.md             # optional — rich role description (overrides BOT_ROLE)
  skills/                        # NEW — custom skills (shared across instances)
    my-team-conventions/
      skill.md
    my-deploy-procedure/
      skill.md
      requires.yaml
```

### Repo (ships with the project)

```
skills/catalog/                  # built-in skills
  code-review/
    skill.md
  testing/
    skill.md
  debugging/
    skill.md
  ...
```

### Skill resolution order (Phase 4+)

Phase 1 only has built-in skills. When custom skills are added in Phase 4, resolution order is:
1. Custom: `~/.config/telegram-agent-bot/skills/<name>/`
2. Built-in: `<repo>/skills/catalog/<name>/`

First match wins. Custom overrides built-in.

---

## 6. User Interfaces

### 6.1 Skill user — Telegram commands

The primary interface. Non-technical users manage skills entirely through chat.

**Browse and toggle:**
```
/skills
> Active: code-review, debugging
> Available: testing, devops, documentation, security, refactoring, architecture

/skills add testing
> ✅ Added 'testing'. Active on next message.

/skills remove debugging
> Removed 'debugging'.

/skills list
> Skills available:
>   code-review*   — Reviews code for correctness, style, and security
>   testing*       — Write and fix tests, TDD guidance
>   debugging      — Systematic bug investigation
>   devops         — Infrastructure, CI/CD, deployment
>   documentation  — Technical writing
>   security       — Security review and hardening
>   refactoring    — Code cleanup and modernization
>   architecture   — System design and planning
>   (* = active)

/skills clear
> All skills removed.
```

**Skill with credentials (first-time setup):**
```
/skills add github-integration
> 🔧 github-integration needs setup.
>
> Paste a GitHub personal access token (needs 'repo' scope).
> Guide: https://github.com/settings/tokens/new

ghp_abc123...

> ✅ Token verified. github-integration is now active.
```

The bot deletes the message containing the token after reading it.

Each user sets up their own credentials, even on a shared bot. User A's GitHub token is never used for user B's requests.

**Credential management:**
```
/skills setup github-integration
> Re-enter credentials for github-integration.
>
> Paste a GitHub personal access token (needs 'repo' scope):
```

**Role management (chat-local override, does not change instance default):**
```
/role
> Role: Senior Python engineer

/role DevOps specialist managing Kubernetes clusters
> Role updated for this chat. Active on next message.

/role clear
> Role reset to instance default.
```

### 6.2 Platform operator — setup.sh

After provider and model selection, the wizard adds role and skill steps.

**New instance:**
```
--- Agent Role ---
What should this agent's role be?
  Examples:
    "Senior Python engineer specializing in distributed systems"
    "DevOps specialist managing AWS infrastructure"
  Leave blank for a general-purpose agent.
  For longer descriptions, create ~/.config/telegram-agent-bot/<instance>.role.md

Role: Senior Python engineer

--- Skills ---
Available skills:
  1. code-review    — Reviews code for correctness, style, and security
  2. testing        — Write and fix tests, TDD guidance
  3. debugging      — Systematic bug investigation
  4. devops         — Infrastructure, CI/CD, deployment
  5. documentation  — Technical writing
  6. security       — Security review and hardening
  7. refactoring    — Code cleanup and modernization
  8. architecture   — System design and planning

Select skills (comma-separated numbers, 'all', or blank for none): 1,2,3

Selected: code-review, testing, debugging
```

Writes to `.env` (via `set_env_value()` which handles quoting and escaping):
```
BOT_ROLE="Senior Python engineer"
BOT_SKILLS=code-review,testing,debugging
```

**Existing instance** — shows current role/skills in config summary, offers edit option.

### 6.3 Skill publisher — file creation

A publisher creates a skill by:

1. Making a directory under `~/.config/telegram-agent-bot/skills/` (custom) or `skills/catalog/` (built-in)
2. Writing a `skill.md` with YAML frontmatter and instruction body
3. Optionally adding `requires.yaml` for credentials
4. Optionally adding `claude.yaml` / `codex.yaml` for provider-specific features

The skill appears in `/skills list` immediately (built-in after deploy, custom after file creation).

Future: `/skills create <name>` scaffolds the directory structure.

---

## 7. Session and Config Changes

### 7.1 Session state (per-chat)

```json
{
  "provider": "claude",
  "provider_state": {"session_id": "...", "started": true},
  "approval_mode": "on",
  "active_skills": ["code-review", "testing", "debugging"],
  "role": "Senior Python engineer",
  "awaiting_skill_setup": null,      // see below — includes initiating user_id
  "pending_request": null,
  "created_at": "...",
  "updated_at": "..."
}
```

New fields:
- `active_skills` (list of skill names) — initialized from `BOT_SKILLS` when a new chat starts
- `role` (string) — initialized from `BOT_ROLE` / `<instance>.role.md`
- `awaiting_skill_setup` (object or null) — tracks in-progress credential setup: `{"user_id": 12345, "skill": "github-integration", "remaining": [{"key": "GITHUB_TOKEN", ...}]}`. The `user_id` field identifies who initiated the setup — the handler MUST verify that the next plain-text message comes from this user before consuming it as a credential. Messages from other users during setup are handled normally. Must be included in the session restore whitelist in `load_session()` so it survives bot restarts.

Note: credentials are stored per-user, not per-chat (see §7.3). Sessions contain no credential values.

### 7.2 BotConfig additions

```python
@dataclass(frozen=True)
class BotConfig:
    # ... existing fields ...
    role: str                    # BOT_ROLE or contents of <instance>.role.md
    skills: tuple[str, ...]      # BOT_SKILLS — default skills for new chats
```

### 7.3 Credential storage and security

Credentials are stored per user, not per chat or per instance.

```
~/.telegram-agent-bot/<instance>/credentials/<user_id>.json
```

```json
{
  "github-integration": {
    "GITHUB_TOKEN": "<encrypted>",
    "JIRA_URL": "<encrypted>"
  }
}
```

This means:

- Each user has their own credential file, even on a shared bot or in group chats
- User A's GitHub token is never visible to or used by user B
- Credentials survive `/new` (which resets the chat session, not the user's credential store)
- A user who sets up a skill in one chat has the credentials available in any chat on the same bot instance

**Why per-user, not per-chat**: Sessions are keyed by `chat_id`. In a group chat, all users share the same `chat_id` and thus the same session. If credentials lived in the session, the first user to set up a skill would provide tokens used by everyone else in the group — a security violation. User-scoped storage avoids this entirely.

**Encryption at rest**: Credential values are encrypted using a key derived from the instance's `TELEGRAM_BOT_TOKEN` (which is already a secret the operator controls). Symmetric encryption (Fernet or similar) — the bot decrypts at runtime to inject into the subprocess environment.

**Injection at runtime**: When `execute_request()` builds the provider subprocess, it loads the requesting user's credential file, decrypts the values, and adds them to the subprocess environment:

```python
user_creds = load_user_credentials(data_dir, user_id, encryption_key)
env = os.environ.copy()
for skill_name in active_skills:
    for key, value in user_creds.get(skill_name, {}).items():
        env[key] = value
```

Only credentials for active skills are injected. Deactivating a skill removes its credentials from the environment without deleting them from storage (they're still there if the user re-enables the skill).

---

## 8. `app/skills.py` — The Skill Engine

```python
"""Skill catalog loading, validation, and prompt composition."""

@dataclass(frozen=True)
class SkillMeta:
    name: str
    display_name: str
    description: str
    has_requirements: bool
    has_claude_config: bool
    has_codex_config: bool

@dataclass(frozen=True)
class SkillRequirement:
    key: str
    prompt: str
    help_url: str | None
    validate: dict | None  # HTTP validation spec

def load_catalog() -> dict[str, SkillMeta]:
    """Discover skills from built-in catalog + custom skills dir.
    Custom overrides built-in on name collision."""

def get_skill_instructions(name: str) -> str:
    """Read the markdown body (minus frontmatter) from skill.md."""

def get_skill_requirements(name: str) -> list[SkillRequirement]:
    """Parse requires.yaml. Returns [] if no requirements."""

def check_credentials(name: str, user_credentials: dict) -> list[SkillRequirement]:
    """Return unsatisfied requirements for a skill given the user's stored credentials."""

# -- Prompt composition (shared by both providers) --

def build_system_prompt(role: str, skill_names: list[str]) -> str:
    """Compose role + skill instructions into text.
    Claude uses this as --append-system-prompt.
    Codex uses this as a prompt prefix."""

# -- Provider-specific config (Phase 3) --

def build_provider_config(
    provider: str, skill_names: list[str], credential_env: dict[str, str]
) -> dict:
    """Read claude.yaml/codex.yaml for each active skill, return structured config.
    Resolves ${VAR} placeholders against credential_env (e.g. ${GITHUB_TOKEN}
    in MCP server env or script env becomes the actual decrypted value).
    Claude: {mcp_servers: {...}, allowed_tools: [...], disallowed_tools: [...]}
    Codex: {scripts: [...], sandbox: "...", config_overrides: [...]}
    Each provider interprets this dict in its own run() implementation."""

# -- Credential management (per-user, not per-chat) --

def load_user_credentials(
    data_dir: Path, user_id: int, key: bytes
) -> dict[str, dict[str, str]]:
    """Load and decrypt a user's credential file.
    Returns {skill_name: {cred_key: plaintext_value}}."""

def save_user_credential(
    data_dir: Path, user_id: int, skill_name: str,
    cred_key: str, value: str, key: bytes,
) -> None:
    """Encrypt and save a single credential to the user's credential file."""

def build_credential_env(
    active_skills: list[str],
    user_credentials: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Return env vars for all active skills' credentials (already decrypted)."""

async def validate_credential(req: SkillRequirement, value: str) -> bool:
    """Run the HTTP validation check if defined. Returns True if valid."""
```

---

## 9. Data Flow

### Message with active skills

```
User sends "review this PR"
    │
    ▼
handle_message() → execute_request()
    │
    ├─ Load session → active_skills = ["code-review", "testing"]
    │                  role = "Senior Python engineer"
    │
    ├─ (Phase 2) Per-request credential check for active credentialed skills.
    │  If requesting user is missing required credentials → reply with setup prompt, skip.
    │
    ▼
execute_request() builds contexts:
    │
    ├─ build_system_prompt(role, active_skills)
    │     → "You are a Senior Python engineer.\n\n## code-review\n...\n\n## testing\n..."
    │
    ├─ (Phase 2) load_user_credentials(user_id) → build_credential_env(active_skills, creds)
    ├─ (Phase 3) build_provider_config(provider, active_skills, credential_env)
    │     → resolves ${VAR} placeholders, returns structured config
    │
    ├─ RunContext(system_prompt, capability_summary, provider_config, credential_env, extra_dirs)
    ├─ PreflightContext(system_prompt, capability_summary, extra_dirs)
    │
    ▼
Provider.run(provider_state, prompt, image_paths, progress, context)
    │
    ├─ Claude: --append-system-prompt <context.system_prompt>
    │          --add-dir <chat upload dir>
    │          + flags from context.provider_config (Phase 3)
    │          -- "review this PR"
    │
    ├─ Codex: prepend context.system_prompt to prompt text
    │         --add-dir <chat upload dir>
    │         -- "<role + skills instructions>\n\n---\n\nreview this PR"
    │
    └─ spawn subprocess (env includes context.credential_env), stream output → Telegram
```

### `/skills add github-integration` with credential setup

```
User (Alice, user_id=111) sends "/skills add github-integration"
    │
    ▼
cmd_skills()
    ├─ Validate: "github-integration" exists in catalog
    ├─ check_credentials("github-integration", load_user_credentials(user_id=111))
    │     → [SkillRequirement(key="GITHUB_TOKEN", prompt="Paste a GitHub...")]
    │
    ├─ Set session: awaiting_skill_setup = {user_id: 111, skill, remaining}
    │
    └─ Reply: "🔧 github-integration needs setup.\n\nPaste a GitHub personal access token..."

Alice sends "ghp_abc123..."  (or Bob sends something — see check below)
    │
    ▼
handle_message() → detects awaiting_skill_setup
    ├─ CHECK: message.from_user.id == awaiting_skill_setup.user_id?
    │     NO  → handle as normal message (not a credential), skip setup flow
    │     YES → continue setup
    │
    ├─ validate_credential(requirement, "ghp_abc123...")
    │     → True (GET https://api.github.com/user returned 200)
    │
    ├─ Store: save_user_credential(user_id=111, "github-integration", "GITHUB_TOKEN", value)
    ├─ Delete user's message (contains secret)
    ├─ Add "github-integration" to session["active_skills"]
    ├─ If Codex provider: clear thread_id (D2 — skill set changed)
    │
    └─ Reply: "✅ Token verified. github-integration is now active."
```

---

## 10. Built-in Skill Catalog

| Skill | Description | Type |
|-------|-------------|------|
| `code-review` | PR/code review — correctness, style, security | Instruction-only |
| `testing` | Write and fix tests, TDD, regression tests | Instruction-only |
| `debugging` | Systematic bug investigation and diagnosis | Instruction-only |
| `devops` | Infrastructure, CI/CD, deployment, Terraform | Instruction-only |
| `documentation` | Technical writing, API docs, READMEs | Instruction-only |
| `security` | Security review, vulnerability analysis, hardening | Instruction-only |
| `refactoring` | Code cleanup, modernization, dead code removal | Instruction-only |
| `architecture` | System design, planning, trade-off analysis | Instruction-only |

All initial built-in skills are instruction-only. Tool-integrated skills (GitHub, Jira, etc.) are Phase 3. No `general` skill — if no skills are active, the agent runs with no extra instructions (current behavior).

---

## 11. What We Preserve

Explicitly listing what does not change, to avoid scope creep and regression:

| Existing behavior | Status |
|-------------------|--------|
| No skills configured → no system prompt, no extra flags | Preserved (D7) |
| Per-chat upload isolation | Preserved |
| Per-chat locking (`CHAT_LOCKS`) | Preserved — skill changes go through the lock |
| Provider protocol (`run()`, `run_preflight()`, etc.) | Extended — `run()` gets optional `RunContext`, `run_preflight()` gets optional `PreflightContext` (D8), backward compatible |
| Approval flow | Preserved — `run_preflight()` receives `PreflightContext` (role + skill text, no secrets) |
| Session persistence (JSON files) | Preserved — new fields are additive |
| `.env` as primary operational config | Preserved — `role.md` is optional |

---

## 12. Implementation Phases

### Phase 0: Codex delivery spike — COMPLETED

Tested on codex-cli 0.111.0. Results:

| Test | Result | Detail |
|------|--------|--------|
| `SKILL.md` via `--add-dir` | **FAIL** | Codex does not search `--add-dir` paths for skills |
| `AGENTS.md` via `--add-dir` | **FAIL** | Role not applied from `--add-dir` path |
| `AGENTS.md` in working dir (`-C`) | **PASS** | Role instructions applied (pirate dialect test) |
| `SKILL.md` in `~/.codex/skills/` | **PASS** | Discovered and used. Requires `description` in YAML frontmatter. |
| `SKILL.md` in working dir (`-C`) | **FAIL** | Not discovered — only `~/.codex/skills/` is searched |

**Decision**: Use prompt prefix for Codex skill delivery (same text composition as Claude, different injection point). Both providers share `build_system_prompt()`. No filesystem artifacts needed.

**Native Codex skills path** (`~/.codex/skills/`) is global and shared — not usable for per-chat skill scoping. Prompt prefix is the only viable approach for chat-scoped skills.

### Phase 1: Instruction-only skills

The foundation. Covers the most common use cases without touching tool integration or credential complexity.

**Scope**: `skill.md` format, built-in catalog, `/skills` and `/role` Telegram commands, `setup.sh` wizard integration, per-chat skill state, hot-loading, prompt injection for both providers.

| Step | What | Files |
|------|------|-------|
| 1 | Add `PreflightContext` and `RunContext` dataclasses to provider base; update `Provider.run()` (RunContext) and `Provider.run_preflight()` (PreflightContext) signatures | `app/providers/base.py` |
| 2 | Create `app/skills.py` — catalog discovery (built-in only), instruction loading, `build_system_prompt()` (shared by both providers), context builders (`RunContext`, `PreflightContext`) | `app/skills.py` (new) |
| 3 | Create built-in catalog — 8 `skill.md` files with real, tested instruction content | `skills/catalog/*/skill.md` (new) |
| 4 | Add `role` and `skills` to `BotConfig`, update `load_config()` to read `BOT_ROLE` (double-quoted) / `<instance>.role.md`, `validate_config()` | `app/config.py` |
| 5 | Add `active_skills` and `role` to session state, initialize from config defaults; include in `load_session()` restore whitelist | `app/storage.py` |
| 6 | Claude provider: read `context.system_prompt` → `--append-system-prompt`, `context.extra_dirs` | `app/providers/claude.py` |
| 7 | Codex provider: prepend `context.system_prompt` to user prompt text, pass `context.extra_dirs` | `app/providers/codex.py` |
| 8 | `execute_request()`: build `RunContext`, pass to `run()`. `request_approval()`: build `PreflightContext`, pass to `run_preflight()`. Both built from session state. | `app/telegram_handlers.py` |
| 9 | Implement `/skills` command (list/add/remove/clear); reset Codex `thread_id` on any skill change (see D2) | `app/telegram_handlers.py` |
| 10 | Implement `/role` command (view/set/clear) — chat-local override, does not write to `.env`; reset Codex `thread_id` on role change (see D2) | `app/telegram_handlers.py` |
| 11 | Update `/help` text, add skill/role display to `/session` | `app/telegram_handlers.py` |
| 12 | Add role/skill prompts to `setup.sh` new-instance and edit flows; `set_env_value()` must quote and escape `BOT_ROLE` (escape `"` and `\` inside double quotes) | `setup.sh` |
| 13 | Update `.env.example` with `BOT_ROLE` and `BOT_SKILLS` | `.env.example` |
| 14 | Tests: skill engine, config loading, `RunContext` building, provider command building (both providers), session state, Codex prompt prefix injection, Codex thread reset on skill/role change, preflight receives `PreflightContext` | `tests/test_skills.py` (new), `tests/test_high_risk.py` |

**Deliverable**: Users can `/skills add code-review` and the next message uses those instructions. Built-in skills are browsable via `/skills list`. Custom skill discovery is Phase 4.

### Phase 2: Credential-aware skills

Builds on Phase 1. Adds `requires.yaml` support, conversational credential setup, secret handling, per-user credential storage.

| Step | What | Files |
|------|------|-------|
| 15 | Add `requires.yaml` parsing to skill engine | `app/skills.py` |
| 16 | Create per-user credential storage: `credentials/<user_id>.json`, encryption/decryption helpers | `app/skills.py`, `app/storage.py` |
| 17 | Add `awaiting_skill_setup` to session state and `load_session()` restore whitelist | `app/storage.py` |
| 18 | Credential check on `/skills add` — load user's credentials, prompt for missing ones | `app/telegram_handlers.py` |
| 19 | Conversational credential input — detect `awaiting_skill_setup` in session, enforce `user_id` match, validate, store to user credential file | `app/telegram_handlers.py` |
| 20 | Secret handling — delete user's message after reading credential (best-effort, log warning on failure) | `app/telegram_handlers.py` |
| 21 | Per-request credential check + injection — shared helper called from both `execute_request()` and `request_approval()`; verify requesting user has all required credentials for active credentialed skills; if missing, reply with setup prompt and skip; if satisfied, load, decrypt, add to `RunContext.credential_env` | `app/telegram_handlers.py` |
| 22 | HTTP validation for credentials (optional `validate` in `requires.yaml`) | `app/skills.py` |
| 23 | `/skills setup <name>` — re-enter all credentials for an existing skill | `app/telegram_handlers.py` |
| 24 | Tests: credential flow, per-user isolation (two users same chat get separate stores), `user_id` enforcement on setup (Bob's message during Alice's setup is not consumed), per-request credential satisfaction check (missing creds → prompt not execution), secret deletion, env injection, encryption round-trip, `awaiting_skill_setup` survives restart | `tests/test_skills.py` |

**Deliverable**: Users can `/skills add github-integration`, get prompted for their token, and the skill activates with API access. Each user on a shared bot has their own credentials, even in group chats.

### Phase 3: Provider-specific skill config

Adds `claude.yaml` and `codex.yaml` support for skills that need MCP servers, tool restrictions, scripts, or other provider-native features.

| Step | What | Files |
|------|------|-------|
| 25 | Parse `claude.yaml` — extract MCP server defs, tool allow/deny lists into structured config | `app/skills.py` |
| 26 | Parse `codex.yaml` — extract scripts, config overrides, sandbox settings into structured config | `app/skills.py` |
| 27 | `${VAR}` placeholder resolution in `build_provider_config()` — interpolate credential values into MCP server env, script env, etc. before passing to provider | `app/skills.py` |
| 28 | Claude provider: read `context.provider_config` → translate to `--mcp-config`, `--allowedTools`, `--disallowedTools` flags | `app/providers/claude.py` |
| 29 | Codex provider: read `context.provider_config` → stage scripts in `scripts/<chat_id>/`, add via `--add-dir`, apply sandbox settings and config overrides | `app/providers/codex.py` |
| 30 | Build `capability_summary` from active provider_config for `PreflightContext` | `app/skills.py` |
| 31 | Create 2-3 tool-integrated built-in skills (e.g. `github-integration`) | `skills/catalog/` |
| 32 | Tests: MCP config generation, placeholder resolution, provider_config handling, capability_summary, script staging | `tests/test_skills.py` |

**Deliverable**: Skill publishers can create skills that configure MCP servers, restrict tools, and include helper scripts.

### Phase 4: Custom skills and ecosystem

| Step | What | Files |
|------|------|-------|
| 33 | Custom skill discovery from `~/.config/telegram-agent-bot/skills/` | `app/skills.py` |
| 34 | Override logic (custom > built-in for same name) | `app/skills.py` |
| 35 | `/skills create <name>` scaffolds a new custom skill directory | `app/telegram_handlers.py` |
| 36 | Show `(custom)` tag in `/skills list` for user-created skills | `app/telegram_handlers.py` |
| 37 | `/doctor` validates active skills — checks catalog presence, credential satisfaction | `app/telegram_handlers.py` |
| 38 | Tests: custom skill override, scaffold command | `tests/test_skills.py` |

**Deliverable**: Power users can create and manage custom skills alongside built-ins.

### Phase 5: Skill store (future)

Not designed in detail yet. Rough shape:

- Remote skill registry (Git repo, HTTP API, or similar)
- `/skills search <query>` — browse remote skills
- `/skills install <publisher/name>` — download and activate
- Versioning, ratings, trust levels

---

## 13. Resolved Questions

Questions raised during design, now closed with decisions.

### Resolved

**Q1: Codex skill discovery via `--add-dir`** — Tested on codex-cli 0.111.0. `--add-dir` does NOT trigger `SKILL.md` discovery. Codex only searches `~/.codex/skills/`. Decision: use prompt prefix for skill delivery (see D6, Phase 0 results).

**Q2: Codex `AGENTS.md` placement** — Tested. `AGENTS.md` works from the `-C` working directory but NOT from `--add-dir` paths. Decision: use prompt prefix for role delivery, consistent with skill delivery.

**Q3: Max prompt size** — Soft warning at 8000 chars in `/skills add` if the composed prompt (role + all active skills) would exceed the threshold. No hard limit. Log it. The user can remove a skill if quality degrades.

**Q4: Credential rotation** — `/skills setup <name>` re-prompts for all credentials for that skill. No single-key updates. Most skills have 1-2 credentials; re-entering both takes seconds. Simpler UX, simpler code.

**Q5: Skill conflicts** — Don't detect. Contradictory instructions across skills are the same problem as contradictory prompt text, and the model resolves it heuristically. Skill order determines prompt order (last skill's instructions come last). Document this.

**Q6: Message deletion permissions** — Best-effort deletion of credential messages. Works automatically in private chats (the common case). In groups, requires bot admin rights. If deletion fails, log a warning but don't fail the setup flow. Document the group admin requirement.

**Q7: Encryption key derivation** — Derive from `TELEGRAM_BOT_TOKEN`. Rotating the bot token is rare and deliberate; re-entering skill credentials afterward is a reasonable expectation. A separate random key in `.env` adds another secret to manage and back up for no practical benefit.

**Q8: Codex script cleanup** — Phase 3 stages helper scripts in `scripts/<chat_id>/`. Cleaned up on `/new` (which resets the session, so resetting staged scripts is consistent). On skill removal, stale script dirs are removed and the Codex thread is reset (D2) so the next `exec` gets a fresh `--add-dir` without the removed skill's scripts. Phases 1-2 have no on-disk artifacts.

---

## 14. File Changes Summary

### Phase 1 (instruction-only skills)

| File | Change |
|------|--------|
| `app/providers/base.py` | Add `PreflightContext` and `RunContext` dataclasses; update `Provider.run()` with optional `RunContext`, `Provider.run_preflight()` with optional `PreflightContext` |
| `skills/catalog/<name>/skill.md` | NEW — 8 built-in skill instruction files |
| `app/skills.py` | NEW — catalog loading, instruction reading, prompt building, `RunContext` builder |
| `app/config.py` | Add `role`, `skills` to BotConfig; `role.md` file loading; update `load_config()`, `validate_config()` |
| `app/storage.py` | Add `active_skills`, `role` to session defaults, load/save, and restore whitelist |
| `app/providers/claude.py` | Read `context.system_prompt` → `--append-system-prompt`; `context.extra_dirs`; `context.credential_env` into subprocess env (populated in Phase 2) |
| `app/providers/codex.py` | Prepend `context.system_prompt` to prompt; `context.extra_dirs`; `context.credential_env` into subprocess env (populated in Phase 2); reset `thread_id` on skill/role change (D2) |
| `app/telegram_handlers.py` | Add `/skills`, `/role` handlers; build `RunContext` in `execute_request()`, `PreflightContext` in `request_approval()`; Codex `thread_id` reset on new `extra_dirs` in `retry_allow`; update `/help`, `/session` |
| `setup.sh` | Add role/skill prompts to new + existing instance flows; `set_env_value()` must quote and escape `BOT_ROLE` |
| `.env.example` | Add `BOT_ROLE` and `BOT_SKILLS` |
| `tests/test_skills.py` | NEW — skill engine tests |
| `tests/test_high_risk.py` | Add skill injection tests for both providers, Codex thread reset on skill/role change, preflight `PreflightContext` |

### Phase 2+ (additive)

| File | Change |
|------|--------|
| `app/skills.py` | Add `requires.yaml` parsing, per-user credential encryption/decryption, provider config parsing |
| `app/storage.py` | Add `awaiting_skill_setup` to session state and restore whitelist; per-user credential file helpers |
| `app/telegram_handlers.py` | Credential prompting flow, secret deletion, `/skills setup`, `/skills create` |
| `app/providers/claude.py` | Read `context.provider_config` → MCP server flags, tool allow/deny flags |
| `app/providers/codex.py` | Read `context.provider_config` → stage scripts in `scripts/<chat_id>/`, add via `--add-dir`, apply sandbox/config overrides |
| `skills/catalog/` | Tool-integrated skills (github, etc.) |
| `~/.telegram-agent-bot/<instance>/credentials/` | NEW — per-user encrypted credential files (`<user_id>.json`) |

---

## 15. Current State

| Instance | Provider | Model | Role | Skills |
|----------|----------|-------|------|--------|
| m1 | Claude | claude-opus-4-6 | (none) | (none) |
| m2 | Codex | gpt-5.4 | (none) | (none) |
| m3 | Codex | gpt-5.4 | (none) | (none) |

All three are deployed as systemd user services and running. None have roles or skills configured yet. Phase 1 implementation will add the capability without disrupting existing behavior — no skills active means no change to current behavior.
