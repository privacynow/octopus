# Architecture

Talk to Claude Code or Codex CLI from Telegram. This document describes the product as built — its vision, architecture, design decisions, and extension points.

---

## Product Vision

A secure, multi-user Telegram bridge to local coding agents. You send a message from your phone; the bot runs Claude or Codex on your files and sends the answer back. The bot adds approval workflows, skill-based capability management, encrypted credential storage, multi-project support, and mobile-friendly output — things the raw CLIs don't have.

**Design goals:**
- Work from anywhere (phone, laptop, group chat)
- Stay in control (review a plan before anything executes)
- Run multiple independent instances (different tokens, providers, models)
- Extend with skills (domain knowledge, integrations, workflow automation)
- Never leak credentials or allow cross-chat file access

---

## System Overview

```
  +-----------+        +---------------------+        +-------------------+
  |           |  msg   |                     |  exec  |                   |
  |  Telegram +------->+  Telegram Agent Bot +------->+ Claude / Codex    |
  |   User    |        |                     |        |   CLI             |
  +-----+-----+        +----------+----------+        +--------+----------+
        ^                         |                             |
        |       reply / files     |       reads & writes        |
        +-------------------------+                    +--------v----------+
                                                       |   Working Dir &   |
                                                       |   Project Files   |
                                                       +-------------------+
```

---

## Module Map

```
app/
  main.py               Entry point: config, provider factory, startup
  config.py             BotConfig loading, validation, .env parsing
  telegram_handlers.py  Telegram commands, message routing, callbacks
  skill_commands.py     /skills subcommand handlers
  request_flow.py       Pure business logic (no Telegram imports)
  execution_context.py  Authoritative execution identity and context hash
  session_state.py      Typed session models and serialization
  storage.py            SQLite session CRUD, file paths, schema migration
  skills.py             Skill catalog, instructions, credentials, provider config
  store.py              Managed skill store: install, uninstall, update, GC
  registry.py           Remote skill registry: fetch, download, verify
  transport.py          Inbound message normalization
  approvals.py          Preflight prompt building, denial formatting
  formatting.py         Markdown-to-Telegram HTML, text splitting
  summarize.py          Compact mode summarization, raw-response ring buffer
  ratelimit.py          Per-user sliding-window rate limiter
  doctor.py             Health checks, stale session detection
  providers/
    base.py             Provider protocol, RunContext, PreflightContext, RunResult
    claude.py           Claude CLI: stream-json, session-id, MCP config
    codex.py            Codex CLI: exec --json, thread-id, script staging
```

Total: ~7,000 lines of production code across 19 modules.

---

## Request Lifecycle

### Normal message (approval off)

```
  Telegram Update
       |
       v
  normalize_message()          transport.py — InboundUser, InboundMessage
       |
       v
  is_allowed(user)?            config — user ID or @username check
       |  no → silent drop
       v
  CHAT_LOCKS[chat_id]          asyncio.Lock — serialize per chat
       |
       v
  rate_limit.check(user)?      ratelimit.py — sliding window
       |  over limit → "try again in Ns"
       v
  download_attachments()       transport.py → uploads/{chat_id}/
       |
       v
  _load(chat_id)               storage.py → SessionState
       |
       v
  credential setup active?     session.awaiting_skill_setup
       |  yes → capture credential, validate, encrypt, save → return
       v
  execute_request()
       |
       +---> resolve_execution_context()    execution_context.py
       |         session + config → ResolvedExecutionContext
       |
       +---> check_credential_satisfaction()  request_flow.py
       |         missing creds? → start setup flow → return
       |
       +---> assemble extra_dirs
       |         upload_dir + config.extra_dirs + denial_dirs + script_dir
       |
       +---> codex thread invalidation       (if codex)
       |         context_hash changed or boot_id changed → clear thread
       |
       +---> build_run_context()             skills.py → RunContext
       |         system_prompt + provider_config + credential_env
       |
       +---> provider.run()                  providers/{claude,codex}.py
       |         CLI subprocess, streaming progress updates
       |
       +---> handle result
                 timeout → error message
                 denials → save PendingRetry, show retry buttons
                 success → format, optionally summarize, send reply
       |
       v
  _save(chat_id, session)      storage.py — persist updated state
```

### Approval flow (approval on)

```
  User sends message
       |
       v
  request_approval()
       |
       +---> build_preflight_context()    (no secrets, no credential_env)
       |
       +---> provider.run_preflight()     read-only plan generation
       |
       +---> save PendingApproval         prompt, images, context_hash, timestamp
       |
       v
  Show plan + inline buttons:  [✅ Approve]  [❌ Reject]

  User taps Approve
       |
       v
  validate_pending()
       |  expired? → "Expired, send again"
       |  context changed? → "Context changed, send again"
       v
  execute_request(skip_permissions=True)
       |
       ... (same as normal flow above)
```

### Denial retry flow

```
  Provider returns denials (e.g., "Write to /tmp/x.txt denied")
       |
       v
  Save PendingRetry             prompt, context_hash, denial records
       |
       v
  Show denial details + buttons:  [✅ Grant & retry]  [❌ Skip]

  User taps Grant & retry
       |
       v
  validate_pending()
       |
       v
  extract denial_dirs()         request_flow.py — unique parent dirs from denials
       |
       v
  execute_request(extra_dirs=denial_dirs, skip_permissions=True)
```

---

## Session Model

```
SessionState
  ├── provider: str                    "claude" or "codex"
  ├── provider_state: dict             provider-specific (thread_id, session_id, etc.)
  ├── approval_mode: str               "on" or "off"
  ├── approval_mode_explicit: bool     true if user ran /approval (not just config default)
  ├── active_skills: list[str]         ordered list of active skill names
  ├── role: str                        chat-specific persona
  ├── project_id: str                  bound project name (empty = default working_dir)
  ├── file_policy: str                 "inspect", "edit", or "" (use config)
  ├── compact_mode: bool | None        None = use config default
  ├── created_at: str                  ISO 8601
  ├── updated_at: str                  ISO 8601
  │
  ├── pending_approval: PendingApproval | None
  │     ├── request_user_id: int
  │     ├── prompt: str
  │     ├── image_paths: list[str]
  │     ├── attachment_dicts: list[dict]
  │     ├── context_hash: str
  │     └── created_at: float
  │
  ├── pending_retry: PendingRetry | None
  │     ├── request_user_id: int
  │     ├── prompt: str
  │     ├── image_paths: list[str]
  │     ├── context_hash: str
  │     ├── denials: list[dict]
  │     └── created_at: float
  │
  └── awaiting_skill_setup: AwaitingSkillSetup | None
        ├── user_id: int
        ├── skill: str
        ├── remaining: list[dict]    [{key, prompt, help_url, validate}, ...]
        └── started_at: float
```

### Storage

```
~/.telegram-agent-bot/{instance}/
  sessions.db                SQLite WAL-mode database
  uploads/{chat_id}/         Downloaded photos and documents
  credentials/{user_id}.json Fernet-encrypted per-user credentials
  scripts/{chat_id}/         Staged Codex helper scripts
  raw/{chat_id}/             Ring buffer: last 50 raw responses per chat
```

SQLite schema:

```sql
sessions (
  chat_id     INTEGER PRIMARY KEY,
  provider    TEXT,
  data        TEXT,          -- JSON-serialized SessionState
  has_pending INTEGER,       -- fast predicate for pending approval/retry
  has_setup   INTEGER,       -- fast predicate for credential setup
  project_id  TEXT,
  file_policy TEXT,
  created_at  TEXT,
  updated_at  TEXT
)
```

Typed boundary: `_load()` returns `SessionState`, `_save()` accepts `SessionState`. No raw dict access in handler code.

---

## Execution Context

Single authoritative representation of the execution identity. Built once per request, consumed by all downstream logic.

```
ResolvedExecutionContext (frozen dataclass)
  ├── role                     chat persona
  ├── active_skills            ordered skill list
  ├── skill_digests            {name: sha256(skill.md)}
  ├── provider_config_digest   sha256(provider YAML content)
  ├── execution_config_digest  sha256(model + codex flags)
  ├── base_extra_dirs          from config (not uploads, not denials)
  ├── project_id
  ├── working_dir              resolved: project root or config.working_dir
  ├── file_policy
  ├── provider_name
  │
  └── context_hash (derived)   SHA-256 of all identity fields above
```

### Context hash usage

```
  Context hash computed at request time
       |
       ├──> Stored in PendingApproval.context_hash
       |      └──> Validated on /approve — reject if context drifted
       |
       ├──> Stored in PendingRetry.context_hash
       |      └──> Validated on retry — reject if context drifted
       |
       └──> Stored in provider_state["context_hash"] (Codex)
              └──> Compared on next request — clear thread if drifted
```

### What changes the hash

| Field | Example trigger |
|-------|----------------|
| role | `/role security expert` |
| active_skills | `/skills add github-integration` |
| skill_digests | Operator edits a skill.md file |
| provider_config_digest | Operator edits claude.yaml or codex.yaml |
| execution_config_digest | Operator changes BOT_MODEL, CODEX_SANDBOX, CODEX_FULL_AUTO |
| base_extra_dirs | Operator changes BOT_EXTRA_DIRS |
| project_id | `/project use webapp` |
| working_dir | `/project use webapp` (different root) or BOT_WORKING_DIR changes |
| file_policy | `/policy inspect` |
| provider_name | Config change (rare — requires restart) |

---

## Provider System

### Protocol

```python
class Provider(Protocol):
    name: str
    def new_provider_state() -> dict
    async def run(provider_state, prompt, image_paths, progress, context) -> RunResult
    async def run_preflight(prompt, image_paths, progress, context) -> RunResult
    def check_health() -> list[str]
    async def check_runtime_health() -> list[str]
```

### Context objects

```
PreflightContext (read-only planning, no secrets)
  ├── extra_dirs: list[str]
  ├── system_prompt: str
  ├── capability_summary: str
  ├── working_dir: str
  └── file_policy: str

RunContext(PreflightContext)  (full execution)
  ├── provider_config: dict       MCP servers, scripts, CLI overrides
  ├── credential_env: dict        decrypted secrets as env vars
  └── skip_permissions: bool      user already approved this action
```

### Claude provider

```
claude -p --output-format stream-json --verbose
  [--model MODEL]
  [--session-id UUID | --resume --session-id UUID]
  [--permission-mode plan|inspect|edit]
  [--append-system-prompt "..."]
  [--mcp-config /tmp/mcp.json]
  [--allowedTools "tool1,tool2"]
  [--disallowedTools "tool3"]
  [--add-dir /path1 --add-dir /path2]
  [-i image1.png -i image2.png]
  -- "user prompt"
```

Session model: UUID-based `session_id`. First message creates session; subsequent messages resume with `--resume`.

### Codex provider

```
codex exec --json
  [--model MODEL]
  [--profile PROFILE]
  [--sandbox MODE]
  [--skip-git-repo-check]
  [--full-auto | --dangerously-bypass-approvals-and-sandbox]
  [-C /working/dir]
  [--add-dir /path1 --add-dir /path2]
  [-i image1.png]
  -- "user prompt"

codex exec resume --json
  --thread-id THREAD_ID
  [--model MODEL]
  [-C /working/dir]
  -- "user prompt"
```

Session model: `thread_id`. First message has no thread; response includes new `thread_id`. Subsequent messages resume with `--thread-id`. Thread invalidation on context drift or bot restart.

**Resume limitation:** `--add-dir` is not accepted on resume. Extra dirs (scripts, uploads) are staged on the first exec and persist in the thread's context.

### Provider result handling

```
RunResult
  ├── text: str              response body
  ├── returncode: int        0 = success, 124 = timeout, other = error
  ├── timed_out: bool
  ├── provider_state_updates: dict    {thread_id: "...", ...}
  └── denials: list[dict]    [{tool_name, tool_input}, ...]
```

---

## Skill System

### Three-tier resolution

```
  _resolve_skill("github-integration")
       |
       v
  1. custom/github-integration/     ← operator-authored, highest priority
       |  not found
       v
  2. managed/refs/github-integration.json → objects/{digest}/
       |  not found                        ← installed from store
       v
  3. skills/catalog/github-integration/   ← built-in, lowest priority
```

### Skill anatomy

```
skills/catalog/{name}/
  skill.md             YAML frontmatter + markdown instructions
  requires.yaml        credential requirements (optional)
  claude.yaml          Claude-specific: MCP servers, tool filters (optional)
  codex.yaml           Codex-specific: sandbox, scripts, overrides (optional)
```

**skill.md** frontmatter:
```yaml
---
display_name: "GitHub Integration"
description: "GitHub API access via MCP server or helper scripts"
---
[markdown body — injected into system prompt when skill is active]
```

**requires.yaml:**
```yaml
credentials:
  - key: GITHUB_TOKEN
    prompt: "Paste your GitHub personal access token"
    help_url: https://github.com/settings/tokens/new
    validate:
      method: GET
      url: https://api.github.com/user
      header: "Authorization: Bearer ${GITHUB_TOKEN}"
      expect_status: 200
```

**claude.yaml** (MCP server config):
```yaml
mcp_servers:
  github:
    command: node
    args: ["/path/to/mcp-server-github/dist/index.js"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
allowed_tools:
  - "mcp__github__*"
```

**codex.yaml** (script staging + sandbox):
```yaml
sandbox: "workspace-execute"
scripts:
  - name: "gh-helper.sh"
    path: "scripts/gh-helper.sh"
```

### Prompt composition

```
  build_system_prompt(role, active_skills)
       |
       v
  1. Role preamble           "You are a security expert."
  2. For each active skill:
       load skill.md body
       prepend "## {Display Name}" header
  3. Concatenate all sections
       |
       v
  Final system prompt (appended via --append-system-prompt or prompt prefix)
```

### Provider config merging

```
  build_provider_config("claude", ["github-integration", "linear-integration"], cred_env)
       |
       v
  For each skill with claude.yaml:
    merge mcp_servers dicts
    concatenate allowed_tools lists
    concatenate disallowed_tools lists
    resolve ${VAR} placeholders with cred_env
       |
       v
  Merged provider config → written to temp MCP config file → passed to CLI
```

### Credential lifecycle

```
  User: /skills add github-integration
       |
       v
  check_credentials()         does user have GITHUB_TOKEN stored?
       |  no
       v
  Start AwaitingSkillSetup    save to session, prompt user
       |
       v
  User sends: ghp_abc123...
       |
       v
  validate_credential()       HTTP GET https://api.github.com/user
       |  200 OK              with Authorization: Bearer ghp_abc123...
       v
  save_user_credential()      Fernet encrypt, save to credentials/{user_id}.json
       |
       v
  delete credential message   best-effort, prevents token from sitting in chat
       |
       v
  Activate skill              add to session.active_skills
```

**Encryption:** `Fernet(base64(SHA-256(telegram_token)))` — key derived from bot token, per-instance isolation.

**Credential isolation:** Credentials are per-user, not per-chat. When Alice requests and Bob approves in a group chat, Alice's credentials are injected (via `request_user_id` on PendingApproval).

---

## Managed Skill Store

### Layout

```
~/.config/telegram-agent-bot/skills/
  custom/
    {name}/                    operator-authored, editable, highest priority
  managed/
    version.json               schema version marker
    .lock                      flock for cross-instance safety
    objects/
      {sha256}/                immutable content-addressed snapshots
        skill.md
        requires.yaml
        claude.yaml
        ...
    refs/
      {name}.json              logical name → digest + provenance
    tmp/                       staging area for in-progress installs
```

### Install / update / uninstall

```
  /skills install {name}
       |
       v
  Read from bundled store      skills/store/{name}/
       |
       v
  Hash directory content       SHA-256 of sorted (path, mode, content)
       |
       v
  Stage to managed/tmp/        copy files
       |
       v
  Move to objects/{digest}/    atomic rename, idempotent
       |
       v
  Write refs/{name}.json       SkillRef with digest, source, timestamp
       |
       v
  "Installed. Use /skills add {name} to activate."


  /skills update {name}
       |
       v
  Re-install from store        may produce same or different digest
       |
       v
  If digest changed            context hash changes → stale approvals rejected


  /skills uninstall {name}
       |
       v
  Guard: not in BOT_SKILLS?    refuse if config depends on it
       |
       v
  Delete refs/{name}.json      object becomes unreferenced
       |
       v
  GC collects object later     1-hour grace period, cross-instance safe
```

### Remote registry

```
  /skills install {name}       (when BOT_REGISTRY_URL is set)
       |
       v
  Fetch index.json             {skills: {name: {digest, artifact_url, ...}}}
       |
       v
  Download .tar.gz artifact    to temp dir
       |
       v
  Verify SHA-256               registry digest vs actual content
       |  mismatch → abort, clean up
       v
  Install as managed object    same flow as local store install
```

---

## Security Model

### Authentication and authorization

```
  Telegram Update arrives
       |
       v
  Extract user ID + @username
       |
       v
  is_allowed(user)?
       |
       ├── user.id in config.allowed_user_ids         → allowed
       ├── user.username in config.allowed_usernames   → allowed
       ├── config.allow_open (and no users restricted) → allowed
       └── otherwise                                   → silent drop
```

Admin (install/uninstall/update) uses separate `admin_user_ids` / `admin_usernames`. Falls back to allowed users if BOT_ADMIN_USERS not explicitly set.

### Path access control

```
  /send /path/to/file    or    SEND_FILE: /path/to/file
       |
       v
  resolve_allowed_path(raw_path, allowed_roots)
       |
       ├── project bound?
       │     roots = [project.root_dir] + project.extra_dirs + [chat_upload_dir]
       │
       └── no project?
             roots = [config.working_dir] + config.extra_dirs + [chat_upload_dir]
       |
       v
  Resolve symlinks, check path is within one of the roots
       |  outside → None (blocked)
       v
  Return resolved path
```

Upload dirs are per-chat (`uploads/{chat_id}/`) — one chat cannot read another's uploaded files.

### Credential security

```
  User sends credential in chat
       |
       v
  Fernet.encrypt(value)        key = base64(SHA-256(telegram_token))
       |
       v
  Save to credentials/{user_id}.json
       |
       v
  Delete credential message    best-effort Telegram API call
       |
       v
  On execution:
    load_user_credentials()    Fernet.decrypt
    inject as env vars         passed to provider subprocess, not logged
```

### Group chat safety

```
  Alice starts /skills setup for github-integration
       |
       v
  session.awaiting_skill_setup = {user_id: Alice, skill: "github-integration", ...}
       |
       v
  Bob sends /skills setup for linear-integration
       |
       v
  "Alice is currently setting up github-integration. Please wait."
  (Bob's request rejected — single setup slot, won't overwrite)

  10 minutes pass with no response from Alice
       |
       v
  Setup auto-expires (SETUP_TIMEOUT_SECONDS = 300)
       |
       v
  Bob can now start his own setup
```

### Rate limiting

```
  Per-user sliding window (in-memory, resets on restart)
       |
       ├── per_minute: N requests in last 60s
       └── per_hour: N requests total in last 3600s

  Admins exempt (if BOT_ADMIN_USERS explicitly set)
```

---

## Multi-Instance Model

```
  ~/.config/telegram-agent-bot/
    production.env              instance "production"
    production.role.md          custom role for production
    staging.env                 instance "staging"
    skills/
      custom/                   shared across instances
      managed/                  shared across instances (flock-protected)

  ~/.telegram-agent-bot/
    production/                 isolated: sessions, uploads, credentials
      sessions.db
      uploads/
      credentials/
    staging/                    isolated: sessions, uploads, credentials
      sessions.db
      uploads/
      credentials/
```

Start instances independently:
```bash
python -m app.main production    # one terminal
python -m app.main staging       # another terminal
```

Each instance has its own Telegram token, provider, model, allowed users, and data. Skills (catalog, custom, managed) are shared because they are code, not user data.

---

## Formatting and Output

### Markdown to Telegram HTML

```
  Provider response (markdown)
       |
       v
  md_to_telegram_html()
       ├── stash fenced code blocks    → <pre><code class="...">
       ├── stash tables                → aligned <pre> blocks
       ├── stash inline code           → <code>
       ├── HTML-escape remaining text
       ├── apply heading / bold / italic / strikethrough / link regexes
       └── restore stashed blocks
       |
       v
  split_html(text, 4096)              Telegram message size limit
       ├── track open tags
       ├── close unclosed tags at chunk boundary
       └── re-open tags at next chunk start
       |
       v
  Send each chunk as a separate Telegram message
```

### SEND_FILE directives

```
  Provider includes in response:
    SEND_FILE: /home/user/output.csv
    SEND_IMAGE: /home/user/chart.png
       |
       v
  extract_send_directives(text)
       ├── strip directives from response text
       └── return [(type, path), ...]
       |
       v
  resolve_allowed_path(path)          security check
       |
       v
  Send as Telegram document or photo attachment
```

### Compact mode

```
  Response > 800 chars AND compact_mode on?
       |
       v
  summarize(text, summary_model)
       ├── claude -p --model haiku --output-format text -- "summarize..."
       ├── target: < 600 chars, preserve code/files/actions
       └── fallback: return original on timeout/error
       |
       v
  Send summary to chat (original saved to ring buffer → /raw retrieves it)
```

---

## Health Checks (/doctor)

```
  /doctor
       |
       v
  Config validation             token, provider, dirs, skills
       |
       v
  Provider health
       ├── binary in PATH?       claude / codex
       └── runtime probe         version check + API ping
       |
       v
  Per-chat checks
       ├── active skills valid?  exist in catalog, parseable
       └── prompt size ok?       warn if > 8,000 chars
       |
       v
  Stale session scan
       ├── pending approvals > 1 hour old
       └── credential setups > 10 minutes old
       |
       v
  Advisory warnings
       └── admin scope warning   if multiple users but admin not explicitly set
```

---

## Design Decisions

### One builder, one object, one hash

Context hashes were originally computed by hand in 5+ places with loose argument bags. Fields drifted between call sites. Now: `ResolvedExecutionContext` is the single authoritative object, `resolve_execution_context()` is the single builder, `context_hash` is a derived property. A parametrized invariant test proves every identity field affects the hash.

### Typed session boundary

Handler code never touches raw dicts. `_load()` returns `SessionState` (a dataclass); `_save()` accepts `SessionState`. Field additions are type-checked. Typos are caught at import time, not in production.

### Service layer extraction

Pure business logic (credential checking, pending validation, denial dir extraction) lives in `request_flow.py` — zero Telegram imports. Handlers delegate to these functions, then handle transport. This makes the decision logic testable without Telegram fakes.

### No backward compatibility

The codebase is in active development with a single operator. Legacy migration code, shim re-exports, and renamed-but-unused fields are deleted immediately. This keeps the codebase honest — if it's in the code, it's used.

### Provider as protocol, not base class

`Provider` is a `typing.Protocol` — duck-typed, no inheritance. Claude and Codex providers share no code. Each constructs its own CLI commands, parses its own output format, manages its own session model. The protocol defines the contract; the implementations are independent.

### Content-addressed skill store

Installed skills are stored as immutable content-addressed objects (`objects/{sha256}/`). Logical names are indirections (`refs/{name}.json → digest`). This makes installs idempotent, updates atomic, and garbage collection safe. The design generalizes to remote registries with signed artifacts.

### Credential encryption at rest

Credentials are Fernet-encrypted with a key derived from the Telegram bot token. This means: credentials are useless without the bot token, each instance has a different key, and the encryption is authenticated (tamper-evident). Credential messages are deleted from Telegram after capture.

### Per-chat upload isolation

Each chat gets its own upload directory (`uploads/{chat_id}/`). This prevents cross-chat file leakage in group chat scenarios. The chat upload dir is always included in `extra_dirs` for provider access.

### Approval mode as a first-class workflow

Approval is not a bolt-on — it's a core execution path. The preflight runs a read-only planning pass, shows the plan to the user, and waits for explicit approval. The pending state captures the full execution identity (context hash), so approvals are invalidated if anything changes between plan and execution.

---

## Built-in Skills

| Skill | Type | Credentials | Provider config |
|-------|------|-------------|-----------------|
| architecture | Instruction-only | — | — |
| code-review | Instruction-only | — | — |
| debugging | Instruction-only | — | — |
| devops | Instruction-only | — | — |
| documentation | Instruction-only | — | — |
| github-integration | Tool-integrated | GITHUB_TOKEN | claude.yaml (MCP), codex.yaml (scripts) |
| linear-integration | Tool-integrated | LINEAR_API_KEY | claude.yaml (MCP) |
| refactoring | Instruction-only | — | — |
| security | Instruction-only | — | — |
| testing | Instruction-only | — | — |

---

## Commands

### User commands

| Command | Purpose |
|---------|---------|
| `/help` | Show usage documentation |
| `/new` | Fresh conversation (reset thread/session, preserve credentials) |
| `/cancel` | Cancel credential setup or pending request |
| `/session` | Show current state (role, skills, provider, project) |
| `/approval on\|off\|status` | Toggle preflight approval mode |
| `/approve` / `/reject` | Respond to pending approval or retry |
| `/skills [subcommand]` | Skill management (list, add, remove, setup, clear, info, search) |
| `/role [text]\|clear` | Set or reset chat persona |
| `/policy inspect\|edit` | Set file access policy |
| `/project list\|use\|clear` | Manage per-chat project binding |
| `/compact on\|off` | Toggle mobile-friendly response summarization |
| `/raw [N]` | Retrieve Nth raw response from ring buffer |
| `/send <path>` | Download a file from the server |
| `/export` | Download conversation history as text file |
| `/id` | Show your Telegram user ID and username |

### Operator commands

| Command | Purpose |
|---------|---------|
| `/doctor` | Run health checks |
| `/skills create <name>` | Scaffold a custom skill |
| `/skills install <name>` | Install from store or registry (admin) |
| `/skills uninstall <name>` | Remove installed skill (admin) |
| `/skills update <name>\|all` | Update managed skill(s) (admin) |
| `/skills updates` | Show update status (admin) |
| `/skills diff <name>` | Show pending changes before update (admin) |
| `/admin sessions [chat_id]` | Session overview or detail (admin) |
| `/clear_credentials [skill]` | Remove stored credentials |

---

## Async Architecture

```
  python-telegram-bot (asyncio)
       |
       ├── Message handler        async, acquires CHAT_LOCKS[chat_id]
       ├── Command handlers       async, acquires CHAT_LOCKS[chat_id]
       ├── Callback handlers      async, acquires CHAT_LOCKS[chat_id]
       │
       └── Per request:
             ├── typing indicator  asyncio.create_task (cancelled on completion)
             ├── provider.run()    asyncio.create_subprocess_exec
             │     └── stdout reader loop (non-blocking)
             │     └── progress.update() with rate-limit throttle
             └── asyncio.wait_for(timeout_seconds)
```

No threads except the default executor (used only by `/doctor` for subprocess health probes). Provider streaming is fully async via subprocess pipes.

---

## Test Suite

537 pytest tests + 35 bash tests across 30 entrypoints.

Tests exercise the real production code path — `FakeProvider` records calls, minimal Telegram stand-ins (`FakeMessage`, `FakeChat`, `FakeUpdate`) capture replies. No mocking of internal modules. The invariant suite (`test_invariants.py`, 47 tests) guards cross-cutting contracts: context hash completeness, session round-trips, path consistency, extra_dirs forwarding.
