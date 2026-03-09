# Commercial Polish Plan

Phased plan to bring telegram-agent-bot to commercial readiness. Focuses on
user-facing usability, safety, and the supporting runtime architecture needed
to make the product durable as the surface grows.

Ordering principle: activation before abuse control. Fix the flows that make
users leave before guarding against the traffic you don't yet have.

---

## Current Status Snapshot (2026-03-09)

This section tracks observed implementation status in the repo. Detailed scope
and design notes remain below.

| Phase | Status | Notes |
|---|---|---|
| Phase 1 | Done | All 8 items shipped: cancel, clear-credentials with confirmation, onboarding, credential status, skill info, error mapping, group chat visibility, stale button TTL. |
| Phase 2 | Done | All three items shipped: table rendering, HTML fallback, and mobile summarization with `/raw` + `/compact`. |
| Phase 3 | Done | Rate limiting, admin safety posture, proactive prompt size warnings, runtime health checks all shipped. |
| Phase 4 | Done | All items shipped. 4.1 managed immutable store with content-addressed objects, atomic refs, cross-instance locking, GC, session self-healing, three-tier resolution, and 7 bugs found and fixed during review. 4.2-4.5 shipped earlier. |
| Phase 5 | In progress | Transport/webhook foundation. 5.1 transport normalization done. 5.2 webhook mode deferred until after 6.1 (SQLite). |
| Phase 6 | In progress | Session and execution-context work: 6.1 SQLite sessions next, then per-chat projects, then file policy. |
| Phase 7 | Not started | Ecosystem work. 7.1 registry lands after phases 5 and 6. |

### Phase 1 Status

| Item | Status | Notes |
|---|---|---|
| 1.1 `/cancel` command | Done | Handler registered and covered by handler tests. |
| 1.2 `/clear_credentials` command | Done | Confirmation flow with inline buttons before clearing. Clears setup, deactivates affected skills. |
| 1.3 Onboarding overhaul | Done | Tiered help, first-run welcome, and README updated with full command reference and feature docs. |
| 1.4 Credential status in `/skills list` | Done | `[needs setup]` and `[ready]` annotations are implemented. |
| 1.5 Skill info improvements | Done | `Requires:` and `Providers:` are shown; preview truncates at 1000 chars with paragraph-aware cutoff. |
| 1.6 Human-readable credential errors and clickable setup links | Done | 401/403/404/5xx guidance and HTML `<a href>` setup links are implemented and tested. |
| 1.7 Group chat credential visibility and admin override | Done | Blocking user/time is shown, admin cancel works, and foreign setup timeout is 5 minutes. |
| 1.8 Stale button UX cleanup | Done | `created_at` on `PendingRequest` plus TTL rejection on stale approval/retry buttons. |

### Phase 2 Status

| Item | Status | Notes |
|---|---|---|
| 2.1 Mobile summarization and `/raw` + `/compact` | Done | `app/summarize.py` with ring buffer + Claude Haiku summarizer. `/compact on\|off` per-chat toggle, `/raw [N]` retrieval. `BOT_COMPACT_MODE` and `BOT_SUMMARY_MODEL` config. Integrated in `execute_request`. |
| 2.2 Markdown table rendering | Done | Markdown tables detected and converted to aligned `<pre>` blocks in `md_to_telegram_html`. Tables inside code fences left alone. |
| 2.3 Robust HTML chunk splitting | Done | Post-split validation added to `split_html()`. If any chunk has unbalanced tags, falls back to stripping HTML and splitting as plain text. |

### Phase 3 Status

| Item | Status | Notes |
|---|---|---|
| 3.1 Rate limiting | Done | `app/ratelimit.py` sliding-window limiter. `BOT_RATE_LIMIT_PER_MINUTE` / `BOT_RATE_LIMIT_PER_HOUR` config. Admin exempt. Integrated in `handle_message`. |
| 3.2 Usage tracking, quota, and billing hooks | Deferred | Requires token-cost mapping and billing integration — deferred to Phase 4+. |
| 3.3 Admin safety posture | Done | `/doctor` warns when `BOT_ADMIN_USERS` not explicitly set and multiple allowed users exist. |
| 3.4 Proactive prompt size warnings | Done | Pre-activation projection with inline keyboard confirmation. `estimate_prompt_size()` in skills.py. Callback handler `handle_skill_add_callback`. |
| 3.5 `/doctor` runtime health checks | Done | API ping via `claude -p` / `codex exec --ephemeral`. Stale session scan (pending requests + incomplete setups). |

### Phase 4 Status

| Item | Status | Notes |
|---|---|---|
| 4.1 Managed immutable skill store foundation | Done | Content-addressed objects, atomic refs, cross-instance flock, GC, schema guard, three-tier resolution, session self-healing in `_load()`, stale-skill filtering in admin/cross-chat paths, `--doctor` schema check. 7 bugs found and fixed during review. |
| 4.2 Locally modified skill protection | Done | Confirmation prompts for update of modified skills, `/skills diff <name>`, batch update confirmation. |
| 4.3 Configuration template per provider | Done | `setup.sh` prunes codex-specific config for claude instances and vice versa. |
| 4.4 Admin session visibility | Done | `/admin sessions` summary and `/admin sessions <chat_id>` detail views. `list_sessions()` in storage.py. |
| 4.5 Conversation export | Done | `/export` sends ring buffer history as downloadable text file with session metadata header. |

### Phase 5 Status

| Item | Status | Notes |
|---|---|---|
| 5.1 Thin inbound transport normalization | Done | `app/transport.py` with frozen inbound dataclasses. All handlers normalized. |
| 5.2 Webhook mode | Not started | Deferred until after 6.1 SQLite — lands on transactional storage instead of JSON files. |

### Phase 6 Status

| Item | Status | Notes |
|---|---|---|
| 6.1 SQLite session backend | Not started | Next execution item. Replaces per-chat JSON session blobs; schema includes future `project_id` and `file_policy` fields from day one. |
| 6.2 Per-chat project model | Not started | Named chat bindings on top of the current working-dir model. |
| 6.3 File policy | Not started | `inspect|edit` threaded through session/project/provider context. |

### Phase 7 Status

| Item | Status | Notes |
|---|---|---|
| 7.1 Third-party skill registry | Not started | Lands after phases 5 and 6 on top of the 4.1 store foundation. |

---

## Planned Next Sequence

Execution from the current state:

1. ~~**5.1** — add thin inbound transport normalization~~ Done.
2. **6.1** — move chat sessions from JSON blobs to SQLite
3. **5.2** — add webhook mode on top of SQLite + normalized inbound path
4. **6.2** — add optional per-chat project bindings
5. **6.3** — add file policy (`inspect|edit`)
6. **7.1** — add the third-party registry using the 4.1 store architecture

`5.1` is complete. `6.1` is next — SQLite gives webhook, projects, and file
policy a transactional foundation instead of building on per-chat JSON files.
The schema carries `project_id` and `file_policy` columns from day one so
later phases fill in existing columns rather than requiring migrations.

`5.2` lands after `6.1` so the webhook ingress path writes to SQLite from day
one. The first webhook cut remains **single-process** — SQLite WAL mode
replaces the in-memory `CHAT_LOCKS` dict for write serialization.

The deferred item `3.2` (usage tracking / billing hooks) remains intentionally out of sequence and is not part of the next execution block.

---

## Phase 1 — Activation & Self-Service

The features that determine whether a new user succeeds or gives up. Every item
here directly affects first-session completion and day-one workflows.

### 1.1 `/cancel` command

**Problem**: Users stuck in credential setup or waiting on a pending approval
have no escape hatch. The only option is `/new`, which destroys the entire
conversation and resets all state.

**Scope**:
- Add `/cancel` command handler.
- If `awaiting_skill_setup` is in progress for this user, clear it and reply
  "Credential setup cancelled."
- If `pending_request` exists, clear it and reply "Pending request cancelled."
- If neither is active, reply "Nothing to cancel."
- In group chats, only the owning user or an admin can cancel.
- Admins can cancel another user's stalled credential setup (ties into Phase 2
  group chat visibility).

**Files**: `app/telegram_handlers.py` (new handler + register in
`build_application`).

**Tests**: Handler test for each cancel path (setup, pending, nothing), plus
group chat ownership check.

---

### 1.2 `/clear_credentials` command

**Problem**: Users have no way to reset their own stored credentials. If a token
is rotated, compromised, or entered wrong, they must ask an admin or manually
delete files on the server. For paying users, this is a day-one workflow.

**Scope**:
- `/clear_credentials` — clears ALL credentials for the calling user.
- `/clear_credentials <skill>` — clears credentials for a specific skill.
- After clearing, affected active skills are deactivated in the current chat
  (since they no longer have credentials).
- Confirm before clearing: "This will remove your stored credentials for
  <skill> and deactivate it. Continue? [Yes/No]"

**Files**: `app/telegram_handlers.py` (new handler + register in
`build_application`), `app/skills.py` (credential deletion function).

**Tests**: Handler tests for clear all, clear single, confirmation flow, and
skill deactivation after clear.

---

### 1.3 Onboarding overhaul

**Problem**: Onboarding is the biggest user-facing weakness. The in-product copy
presents the bot as a "{provider} CLI Bridge" with a raw command list. The
README is incomplete relative to the actual product surface. New users don't
understand approval mode, skills, or credentials. This creates higher support
burden and lower activation.

This is a unified workstream — not just a `/help` rewrite.

**In-product help**:
- Rewrite `HELP_TEMPLATE` to use product language instead of developer jargon.
  Drop "CLI Bridge" framing. Lead with what the bot does, not what it wraps.
- One-line examples for each command (e.g., `/role You are a Python expert`).
- Brief explanation of approval mode: "When on, the bot shows a plan before
  executing. When off, it executes immediately."
- Brief explanation of skills: "Skills add domain knowledge and tools. Use
  /skills to browse and activate them."
- Two-tier help: `/help` shows summary, `/help <topic>` shows detailed help
  for approval, skills, or credentials.

**README parity**:
- Audit README.md against actual feature surface. Document all commands,
  approval flow, skill system, credential setup, group chat behavior.
- Add a "Quick Start" section: install → setup → first message → first skill.
- Add a "For Mobile Users" section explaining `/compact` mode.

**First-run experience**:
- On first message in a new chat, send a brief welcome: "I'm ready. Send me a
  message or type /help to see what I can do." (One sentence, not a wall.)
- If approval mode is on, mention it: "Approval mode is on — I'll show a plan
  before acting."

**Files**: `app/telegram_handlers.py` (`HELP_TEMPLATE`, `cmd_start`, first-run
logic), `README.md`.

**Tests**: Handler test that `/help` contains examples and key terms. Handler
test for `/help skills` detailed output. First-run message test.

---

### 1.4 Credential status in `/skills list`

**Problem**: Users can't tell which skills require credential setup until they
try to add one and get prompted. This makes skill discovery frustrating and
reduces activation.

**Scope**:
- In `/skills list` output, annotate each skill with credential status:
  - `[active]` — already activated (current behavior).
  - `[needs setup]` — has `requires.yaml` credentials that this user hasn't
    provided.
  - `[ready]` — credentials satisfied, can be activated immediately.
  - No annotation — no credentials required.
- This requires loading the requesting user's credentials during list display.

**Files**: `app/telegram_handlers.py` (`cmd_skills` list handler),
`app/skills.py` (expose a function to check credential status without starting
setup flow).

**Tests**: Handler test with a skill that has requirements, verify annotation
appears. Test with satisfied credentials shows `[ready]`.

---

### 1.5 Skill info improvements

**Problem**: `/skills info <name>` truncates instructions at 500 chars, often
mid-sentence. Users can't get a full picture of what a skill does before
deciding to activate it.

**Scope**:
- Increase preview to 1000 chars, breaking at the nearest paragraph boundary
  (double newline) rather than mid-sentence.
- Show credential requirements (from `requires.yaml`) in the info output:
  "Requires: GITHUB_TOKEN, LINEAR_API_KEY".
- Show provider compatibility (if `claude.yaml` or `codex.yaml` exists, note
  which providers are supported).

**Files**: `app/telegram_handlers.py` (skills info handler), `app/skills.py`
(expose requirements summary).

**Tests**: Handler test for info output format, paragraph-aware truncation.

---

### 1.6 Human-readable credential errors and clickable setup links

**Problem**: Validation failures show raw HTTP details like "Expected status
200, got 401". Users unfamiliar with APIs don't know what to do. The `help_url`
renders as plain text — users must manually copy-paste into a browser.

**Credential validation errors**:
- Map common HTTP status codes to human-readable guidance:
  - 401/403 → "Token was rejected. Double-check you copied the full token and
    that it has the required permissions."
  - 404 → "The validation endpoint was not found. The service may have changed
    its API."
  - 5xx → "The service is temporarily unavailable. Try again in a few minutes."
- Keep the raw status code in the message for debugging, but lead with the
  human-readable guidance.

**Clickable help URLs**:
- Format `help_url` as Telegram HTML link: `(<a href="url">setup guide</a>)`.
- If help_url is missing, omit the link entirely (no empty parens).

**Files**: `app/skills.py` (`validate_credential` function),
`app/telegram_handlers.py` (`_format_credential_prompt`).

**Tests**: Unit tests for each status code mapping. Handler test verifying
HTML `<a>` tag in prompt output.

---

### 1.7 Group chat credential visibility and admin override

**Problem**: In group chats, if one user starts credential setup, all other
users are blocked with "Another user is completing credential setup" and no
visibility into who's blocking or how long they've been waiting.

**Current state**: Foreign setup already auto-expires after 10 minutes
(`_SETUP_TIMEOUT_SECONDS`). `/skills remove`, `/skills clear`, and `/new` are
all correctly blocked while another user is mid-setup. The protection is solid;
the gap is messaging and admin control.

**Scope**:
- Include the blocking user's ID or display name in the foreign-setup message:
  "User @alice is completing credential setup (started 3 min ago). Please wait
  or ask them to finish."
- Admin override via `/cancel` (from 1.1) can clear another user's stalled
  setup.
- Consider reducing the expiry timeout from 10 minutes to 5 minutes.

**Files**: `app/telegram_handlers.py` (foreign setup message, cancel handler).

**Tests**: Group chat test with named blocking user. Admin cancel test.

---

### 1.8 Stale button UX cleanup

**Problem**: Pending approvals are intentionally persisted across restarts —
`approve_pending()` will still execute them if the context hash is unchanged.
But very old pending requests become confusing. Users click a week-old button
and get unexpected behavior.

**Current state**: Missing or stale cases already return explicit messages
("Context changed since this request was made", "No pending request to
approve"). The gap is time-based staleness, not missing error handling.

**Scope**:
- Add a `created_at` timestamp to `PendingRequest`.
- On button click, reject if older than a configurable TTL (default: 1 hour,
  or `BOT_TIMEOUT_SECONDS` if longer). Show: "This request has expired
  (created X minutes ago). Please resend your message."
- Do NOT sweep pending requests on startup — they may still be valid if the
  context hasn't changed.

**Files**: `app/providers/base.py` (add `created_at` to `PendingRequest`),
`app/telegram_handlers.py` (TTL check in callback handlers).

**Tests**: Handler test for clicking expired button. Test that fresh button
still works.

---

## Phase 2 — Mobile Presentation & Output Quality

The primary user interface is Telegram on a phone. These items make the output
readable and the formatting reliable on mobile.

### 2.1 Mobile-first response summarization and `/raw` command

**Problem**: LLM responses are optimized for terminal/IDE consumption — long
code blocks, detailed step-by-step plans, full file diffs. On a phone screen in
Telegram, these are walls of text requiring aggressive scrolling. Plans, reviews,
and status updates are especially bad.

**Design**:
- After the provider returns a response, save the raw text to a per-chat ring
  buffer (last 50 responses).
- If compact mode is enabled, run the raw response through a cheap/fast
  summarization model (e.g., Haiku) before formatting and sending to Telegram.
- Short responses (under ~800 chars) skip summarization — they're already
  mobile-friendly.
- Every summarized message includes a footer:
  `"Summarized — /raw for full response"`
- `/raw` (or `/raw 1`) retrieves the most recent raw response, formats it
  normally (current formatting pipeline), and sends it.
- `/raw N` retrieves the Nth most recent (2 = previous, 3 = before that, etc.).
- `/compact on|off` toggles summarization per chat (stored in session).
- New config: `BOT_COMPACT_MODE=off` (instance-level default).
  `BOT_SUMMARY_MODEL=claude-haiku-4-5-20251001` (model used for summarization).

**Summarization prompt** (tight, domain-aware):
- Preserve: code snippets, file paths, commands, action items, errors, key
  decisions.
- Drop: step-by-step reasoning, caveats about obvious things, verbose
  explanations.
- Target: under 600 chars for plan/review/status responses; code-only responses
  returned unchanged.

**Ring buffer storage**:
- Store as JSON files in `{data_dir}/raw/{chat_id}/` with sequential numbering.
- Each entry: `{"timestamp": ..., "prompt": ..., "raw_text": ..., "kind": ...}`.
- Rotate on write: when count exceeds 50, delete oldest.

**Implementation note**: The summarization call should use `claude -p` with a
cheap model (`--model claude-haiku-4-5-20251001`), keeping the CLI-only
architecture. No SDK dependency. The call is lightweight — short system prompt,
raw text in, summary out, plain text output format. Timeout of 30 seconds.

**Files**: New `app/summarize.py` (summarization logic + ring buffer),
`app/telegram_handlers.py` (integration in `execute_request`, new `/raw` and
`/compact` handlers), `app/config.py` (new config keys).

**Tests**: Summarizer unit tests (short passthrough, long summarization, code
preservation). Ring buffer rotation tests. Handler tests for `/raw`,
`/compact`, and summarized footer presence.

---

### 2.2 Markdown table rendering

**Problem**: Models frequently generate markdown tables. Telegram doesn't
support HTML tables, so they render as unreadable plain text.

**Scope**:
- Detect markdown tables (lines with `|` column separators and `---` separator
  rows) in `md_to_telegram_html`.
- Convert to monospaced `<pre>` block with aligned columns (pad cells to
  uniform width). This preserves readability in Telegram's monospace font.
- Handle edge cases: tables with inconsistent column counts, tables inside code
  blocks (don't convert those).

**Files**: `app/formatting.py` (table detection and conversion).

**Tests**: Formatting tests for simple tables, ragged tables, tables inside
code fences (should be left alone).

---

### 2.3 Robust HTML chunk splitting

**Problem**: Long responses are split into 4096-char Telegram messages. Tag
balancing is attempted but edge cases (deeply nested tags, model-generated
broken HTML) can produce malformed chunks.

**Scope**:
- Add a post-split validation pass: parse each chunk with a simple tag-balance
  checker. If unbalanced, close open tags at chunk boundary and re-open at next
  chunk start.
- Add a fallback: if HTML parsing fails entirely, strip all tags and send as
  plain text rather than erroring.

**Files**: `app/formatting.py` (`split_html`).

**Tests**: Formatting tests with deeply nested tags, unclosed tags, and
malformed model output.

---

## Phase 3 — Trust & Cost Control

Guard against abuse and give operators visibility into spend. These become
critical as the user base grows beyond trusted early adopters.

### 3.1 Rate limiting

**Problem**: No rate limiting. A user (or compromised account) can spam the bot
and rack up unlimited API costs.

**Scope**:
- Per-user rate limit: configurable max requests per minute (default: 5) and
  per hour (default: 30).
- Per-chat rate limit for group chats (aggregate across all users).
- New config: `BOT_RATE_LIMIT_PER_MINUTE=5`, `BOT_RATE_LIMIT_PER_HOUR=30`.
- When limit exceeded, reply: "Rate limit reached. Please wait X seconds."
- Admins are exempt from rate limits.

**Files**: New `app/ratelimit.py` (token bucket or sliding window),
`app/telegram_handlers.py` (check before execution), `app/config.py` (new
config keys).

**Tests**: Rate limit unit tests. Handler test that rate-limited user gets
rejection message. Admin exemption test.

---

### 3.2 Usage tracking, quota, and billing hooks

**Problem**: No visibility into per-user or per-chat API consumption. Can't bill
customers, explain costs, or set spending caps.

**Scope**:
- Track per-request metadata: user_id, chat_id, provider, model, duration,
  token count (if available from provider output).
- Store in append-only log: `~/.telegram-agent-bot/<instance>/usage.jsonl`.
- New config: `BOT_BUDGET_LIMIT_USD=` per user per day (requires token→cost
  mapping).
- `/usage` — show requesting user's usage summary (today, this week, total).
- `/admin usage` — show aggregate usage across all users.

**Files**: New `app/usage.py`, `app/telegram_handlers.py` (instrumentation
around `execute_request`), `app/config.py` (budget config).

**Tests**: Usage tracking unit tests. Budget limit enforcement test.

---

### 3.3 Admin safety posture

**Problem**: `BOT_ADMIN_USERS` defaults to `BOT_ALLOWED_USERS` if not set. In a
multi-user deployment, every user silently becomes an admin with power to
install/uninstall skills and sweep all sessions. The README normalizes this
fallback. For a paid product, "everyone is admin unless you opt out" is a trust
problem.

**Scope**:
- In `/doctor` output, if `BOT_ADMIN_USERS` is not explicitly set AND there are
  more than one allowed user, emit a warning:
  "BOT_ADMIN_USERS not set — all allowed users have admin privileges
  (install/uninstall skills). Set BOT_ADMIN_USERS to restrict."
- This is a `/doctor`-only warning. `validate_config()` currently returns hard
  errors and `fail_fast()` exits on any returned string. Adding a non-fatal
  warning there would require a separate warning channel (e.g., returning a
  tuple of errors and warnings, or a log-only path). Keep it simple: `/doctor`
  is the right place for advisory checks that don't block startup.
- Update README to note the security implication of the fallback behavior
  rather than normalizing it.

**Files**: `app/telegram_handlers.py` (`cmd_doctor`), `README.md`.

**Tests**: Doctor test checking warning presence with multiple allowed users.

---

### 3.4 Proactive prompt size warnings

**Problem**: Prompt size warnings only appear after a skill is activated. Users
add multiple skills and only then discover the combined context is too large.

**Scope**:
- When running `/skills add <name>`, compute the PROJECTED total prompt size
  (current active skills + the new one) and warn BEFORE activating if it
  exceeds the threshold.
- Show: "Adding <name> would bring total prompt context to ~12,400 chars
  (threshold: 8,000). This may reduce response quality. Continue? [Yes/No]"
- Use inline keyboard buttons for confirmation.

**Files**: `app/telegram_handlers.py` (skills add handler), `app/skills.py`
(`check_prompt_size` or new `estimate_prompt_size`).

**Tests**: Handler test adding a skill that pushes over threshold, verify
warning shown and confirmation required.

---

### 3.5 `/doctor` runtime health checks

**Problem**: `/doctor` only checks "can the bot start" — binary availability,
config validity, data dir writability. It doesn't detect runtime issues like API
rate limits, invalid model names, or expired API keys.

**Scope**:
- Add a lightweight "ping" to the provider:
  - Claude: run `claude --version` (already done) + a minimal `-p` call with
    timeout to verify API connectivity.
  - Codex: run `codex exec --json --ephemeral` with a trivial prompt and short
    timeout.
- Report API key validity, model availability, and estimated latency.
- Add stale session detection: count sessions with `pending_request` or
  `awaiting_skill_setup` and report as informational.

**Files**: `app/providers/claude.py` and `app/providers/codex.py`
(`check_health` methods), `app/telegram_handlers.py` (`cmd_doctor`).

**Tests**: Provider health check tests with mock subprocess responses.

---

## Phase 4 — Operational Hardening

### 4.1 Managed immutable skill store foundation

**Decision**: Do not build a narrow intent-log patch and throw it away later.
Instead, build the final local store architecture now so that crash recovery
and the future third-party registry share the same foundation.

**Problem with the current model**:
- Store installs and updates mutate live skill directories in place.
- Custom editable skills and store-managed installs share the same directory
  model, which makes provenance and overwrite semantics awkward.
- Recovery is hard because the runtime treats on-disk skill dirs as mutable
  truth.
- The current model does not scale cleanly to remote registry artifacts,
  signatures, rollbacks, or durable provenance.

**Architecture goals**:
- Managed store artifacts are **immutable** once written.
- Installed skill names point to artifacts via lightweight **refs**, not by
  mutating a live directory in place.
- Install/update become atomic promotion/swap operations.
- Uninstall removes the ref first-class, with garbage collection handling
  unreferenced artifacts later.
- Startup recovery reconciles temp/backup/trash state from disk layout rather
  than replaying a generic transaction log.
- Sessions treat managed skills as **soft references** and self-heal if a ref
  disappears.
- Editable custom skills remain separate from managed store installs.

**Proposed on-disk model**:
- `skills/custom/<name>/...`
  - Operator-authored, editable custom skills.
- `skills/managed/objects/<full_sha256>/...`
  - Immutable skill artifacts, fully materialized on disk and keyed by full digest.
  - Object digest is SHA-256 over sorted files: `<relative_path>\0<mode_octal>\0<content>` per file. File mode bits are included so executable scripts preserve their permissions.
- `skills/managed/refs/<name>.json`
  - Logical mapping from skill name to active object digest and provenance.
- `skills/managed/tmp/`
  - Staging area for installs and updates before promotion.
- `skills/managed/trash/`
  - Short-lived holding area for uninstall / rollback / GC.
- `skills/managed/version.json`
  - Schema version marker (`{"schema": 1}`). Startup checks this before touching
    the managed store. If missing, treat as fresh init. If schema > known, refuse
    to operate (prevents old code from corrupting a newer layout).
- `skills/managed/.lock`
  - Cross-instance store mutation / GC / recovery lock. Read-only operations
    (`_skill_dir`, `load_catalog`) do NOT acquire this lock.

**Ref metadata**:
- Store ref metadata includes at least:
  - schema version
  - logical skill name
  - full object digest
  - source (`bundled-store`, later `registry`)
  - installed_at
  - version / publisher metadata when available
  - trust / verification state
  - optional pinning state for future update policy

**Resolution order**:
1. `skills/custom/<name>` — explicit local override
2. `skills/managed/refs/<name>` → object digest → immutable object dir
3. built-in catalog

This keeps local operator overrides simple while making store-installed skills
traceable and safe.

**Mutation model**:
- **Install**
  - Build artifact in `tmp/`
  - Validate parseability and provider config
  - Materialize `objects/<digest>/` only if it does not already exist
  - Write ref metadata
  - Atomically promote artifact + ref into place
- **Update**
  - Create a new immutable object
  - Atomically swap the logical ref from old digest to new digest
  - Old object remains available for rollback/GC
- **Uninstall**
  - Remove logical ref
  - Runtime stops resolving the skill by name
  - Old object becomes garbage-collectable
- **GC**
  - Runs at startup only (not periodic). Removes unreferenced objects older than
    1 hour (grace window for crash recovery) and abandoned temp/trash content.

**Recovery model**:
- Recovery is driven by filesystem state, not by a separate intent ledger.
- Recovery and mutation run under a cross-instance lock because the managed
  store is shared across bot instances.
- Ref writes are atomic: write `refs/<name>.json.tmp`, then rename into place.
- Object creation is idempotent: if `objects/<digest>/` already exists and is
  valid, reuse it rather than rewriting it.
- On startup:
  - clean abandoned temp dirs
  - resolve incomplete promotions
  - restore from backup/trash if needed
  - prune orphaned refs
  - garbage-collect unreferenced objects
- Recovery must be idempotent and safe to run on every startup.

**Session model changes**:
- Session `active_skills` remain logical skill names.
- If a managed ref is missing, the runtime removes that skill from the chat
  session during an explicit `normalize_active_skills(...)` step on load or
  before execution instead of
  assuming a perfect global sweep.
- This avoids coupling store mutation correctness to immediate cross-session
  rewrites.

**Validation vs normalization**:
- `validate_active_skills(...)` remains pure and read-only.
- A separate `normalize_active_skills(session, save_fn)` handles pruning stale
  logical skill names and persisting the cleaned session state.

**Locally modified skills**:
- The current "store-installed but edited in place" model does not survive this
  redesign cleanly.
- Store-managed skills become immutable.
- If an operator wants to customize a store skill, the workflow becomes:
  - fork/copy it into `skills/custom/<name>` (or a new custom name)
  - edit the custom copy
- `4.2` local-modification protection remains relevant until the new managed
  store model lands, but the long-term model is "managed immutable" vs
  "custom editable", not "managed but maybe edited".

**Override visibility**:
- `/skills list` should show when a custom skill shadows a managed ref
  (for example: `[custom override]`).
- `/skills info <name>` should state whether the skill currently resolves to
  `custom` or `managed`.
- `/skills update <name>` should report when the managed ref changed but a
  custom override remains active.
- No `fork` / `unfork` commands are part of the 4.1 foundation. Same-name
  custom shadowing is sufficient; extra UX can be added later only if needed.

**Development-mode clean break**:
- No migration or backward-compat support is planned for pre-4.1 installed
  skills.
- Existing development installs can be discarded/reset when the new layout
  lands.
- 4.1 defines the new baseline storage model for all later work.

**Scope**:
- New managed store layer in `app/store.py`
- Runtime resolution updates in `app/skills.py`
- Startup reconciliation in `app/main.py`
- Session self-healing for missing managed refs
- Cross-instance lock for mutation / recovery / GC
- User-facing override visibility in `/skills list`, `/skills info`, and
  managed-update messaging

**Non-goals for 4.1**:
- No remote registry fetch yet
- No publisher trust UI yet
- No billing/usage work
- No migration of legacy `_store.json` installs
- No backward-compat preservation for the old mixed custom/store layout
- No `fork` / `unfork` workflow in the foundation

**Files**:
- `app/store.py` — object/ref store, atomic ref writes, recovery, GC, locking
- `app/skills.py` — managed skill resolution, custom-vs-managed precedence,
  pure validation helpers
- `app/main.py` — startup recovery / reconciliation
- `app/storage.py` or handler/runtime call sites — session normalization for
  stale logical skill refs
- `app/telegram_handlers.py` — override visibility and managed-update messaging

**Tests**:
- Install/update/uninstall with crash simulation at each promotion phase
- Startup recovery idempotence
- Missing-ref session self-healing
- Custom-overrides-managed precedence
- Atomic ref write behavior
- Idempotent object creation / reuse
- GC only removes truly unreferenced objects
- Cross-instance lock behavior / serialization
- Override-visibility UX in list/info/update flows

---

### 4.2 Locally modified skill protection

**Note**: This item is partially subsumed by the 4.1 immutable store redesign.
Under the new model, managed skills cannot be edited in place — they are
immutable objects. "Local modifications" only occur when a custom skill in
`skills/custom/<name>` shadows a managed ref. The protection semantics change:

- `/skills diff <name>` compares `custom/<name>` against the managed object
  (if a managed ref exists for that name).
- `/skills update <name>` updates the managed ref. If a custom override exists,
  the message says "managed version updated; custom override still active."
- Batch update confirmation remains relevant for managed refs.

The existing confirmation and diff implementations (done before 4.1) will be
adapted during 4.1 implementation to use the new resolution model.

---

### 4.3 Configuration template per provider

**Problem**: `.env.example` shows all settings for all providers. Claude users
see `CODEX_SANDBOX`, `CODEX_FULL_AUTO`, `CODEX_DANGEROUS` which are irrelevant.
Codex users see Claude-specific comments.

**Scope**:
- `setup.sh` should generate a provider-specific `.env` file, omitting
  irrelevant sections entirely.
- Keep `.env.example` as the full reference, but generated configs are clean.

**Files**: `setup.sh`, `.env.example` (add section markers for conditional
generation).

**Tests**: Manual / script test that generated config for each provider only
contains relevant settings.

---

### 4.4 Admin session visibility

**Problem**: Admins have no visibility into active sessions across chats. They
can't tell which chats are active, stuck, or consuming resources.

**Scope**:
- `/admin sessions` — list all chats with sessions, showing:
  - Chat ID
  - Active skills count
  - Pending request status
  - Last activity timestamp
  - Provider state summary (thread_id or session_id present)
- `/admin sessions <chat_id>` — detailed view of a specific chat session.
- Admin-only (gated by `BOT_ADMIN_USERS`).

**Files**: `app/telegram_handlers.py` (new admin handler), `app/storage.py`
(list all sessions function).

**Tests**: Handler tests for admin access gate and output format.

---

### 4.5 Conversation export

**Problem**: Users can't export or download their conversation history through
the bot.

**Scope**:
- `/export` — exports the current chat's provider session as a downloadable
  file.
- For Claude: session transcript (if available from Claude Code's session
  storage).
- For Codex: thread transcript (if available from Codex's session storage).
- Format: plain text or markdown, sent as a Telegram document.
- If provider doesn't support transcript export, reply with session metadata
  only.

**Files**: `app/telegram_handlers.py` (new handler), provider-specific export
methods.

**Tests**: Handler test for export command. Test for provider without export
support.

---

## Phase 5 — Transport & Webhook Foundation

### 5.1 Thin inbound transport normalization

**Problem**: The current handler chain consumes raw `python-telegram-bot`
objects directly. That works for polling, but it makes the transport boundary
opaque and turns webhook mode into a larger refactor than necessary.

**Scope**:
- Introduce a small internal inbound-event shape for:
  - plain messages
  - attachments
  - callback payloads
  - effective chat/user/message identity
- Polling and webhook entrypoints both normalize into this same shape before
  handing off to business logic.
- Keep this intentionally thin:
  - no outbound abstraction yet
  - no attempt to rewrite all handlers around a generic transport interface
  - no multi-bot concepts
- The goal is a cleaner inbound seam, not a total handler rewrite.

**Files**:
- `app/telegram_handlers.py` — normalization helpers and handler entrypoint
  refactor
- `app/main.py` or a new small transport module — shared ingress for polling
  and webhook modes

**Tests**:
- Unit tests for message normalization
- Unit tests for callback normalization
- Regression test proving polling and webhook paths feed the same normalized
  payload into the business-logic layer

---

### 5.2 Webhook mode

**Problem**: The bot uses long-polling, which works but adds latency and
requires a persistent connection. For production deployments behind a reverse
proxy, webhook mode is more efficient and operationally cleaner.

**Scope**:
- New config: `BOT_MODE=poll|webhook`, `BOT_WEBHOOK_URL=`,
  `BOT_WEBHOOK_PORT=`.
- When `webhook`, start an aiohttp server and register the webhook URL with
  Telegram.
- Health endpoint at `/health` for load balancer checks.
- Webhook and polling must feed the same normalized inbound path from `5.1`.
- First webhook cut is explicitly **single-process**.
  - Current in-memory per-chat locks remain the concurrency guard.
  - Multi-worker webhook deployment is deferred until after Phase 6 session
    work.
- Graceful fallback: if webhook registration fails, fall back to polling with a
  warning.

**Files**:
- `app/main.py` (mode selection)
- new `app/webhook.py`
- `app/config.py` (new config keys)

**Tests**:
- Webhook registration test with mock Telegram API
- Health endpoint test
- Regression test that webhook and polling paths hit the same inbound
  normalization logic

---

## Phase 6 — Session & Execution Context

### 6.1 SQLite session backend

**Problem**: Per-chat JSON session blobs are simple, but they make
cross-session queries and runtime scans expensive and increasingly awkward as
the product surface grows (`/admin sessions`, `/doctor`, cross-chat prompt-size
checks, future webhook/runtime views).

**Scope**:
- Replace per-chat JSON session blobs with a SQLite-backed session store while
  keeping uploads, credentials, raw history, and the immutable skill store on
  the filesystem.
- Preserve the current storage API shape where practical:
  - `load_session`
  - `save_session`
  - `list_sessions`
- Design the schema for the near-term target model from day one. Include:
  - `chat_id`
  - provider/session state
  - approval mode fields
  - role
  - active skills
  - pending request / setup state
  - `project_id` (nullable or defaulted initially)
  - `file_policy` (nullable or defaulted initially)
- Add indexes needed for:
  - `/admin sessions`
  - stale-session scans
  - future project-bound session queries
- Do not try to move every file-backed subsystem into SQLite in this phase.

**Files**:
- `app/storage.py` or split storage modules
- `app/main.py` (startup initialization / migration hook)
- any admin/runtime call sites that currently walk session files directly

**Tests**:
- CRUD parity tests against the current session API
- one-time JSON-to-SQLite migration test
- list/query tests for admin and stale-session surfaces
- concurrency/regression tests around per-chat updates

---

### 6.2 Per-chat project model

**Problem**: The bot currently exposes one instance-level `BOT_WORKING_DIR`
plus `BOT_EXTRA_DIRS`. That is simple, but it forces one bot instance to have
one filesystem context. A single bot cannot cleanly serve multiple repos or
working areas without extra instances or config edits.

**Scope**:
- Introduce optional named projects on top of the current model.
- If no project config is defined, preserve today’s behavior via an implicit
  default project derived from `BOT_WORKING_DIR` and `BOT_EXTRA_DIRS`.
- Add per-chat project binding:
  - `/project` — show current project
  - `/project list` — list available projects
  - `/project use <name>` — bind this chat to a named project
- Project definition includes:
  - project id
  - root dir
  - readable dirs / allowed dirs
  - default file policy (used by 6.3)
- Switching projects must clear or invalidate provider session state and any
  stale pending approvals.
- `/session`, `/export`, and approval UX should surface the active project
  explicitly.
- Context hash must include the bound project’s filesystem view.

**Files**:
- `app/config.py` — project config loading/validation
- `app/storage.py` — persist chat→project binding
- `app/telegram_handlers.py` — `/project` commands, session reset on switch
- provider/context builders — use project dirs instead of only instance-level
  working dir

**Tests**:
- project config validation
- `/project list` and `/project use`
- provider-session invalidation on project switch
- approval invalidation on project switch
- `/session` and `/export` show current project

---

### 6.3 File policy

**Problem**: Approval mode answers "show a plan first?" but it does not answer
"may this session modify files?" The bot needs an explicit inspect-vs-edit
concept for safer review flows and clearer user expectations.

**Scope**:
- Add `file_policy = inspect|edit`.
- Persist file policy in session state.
- Default file policy can come from the bound project, with room for later
  per-chat override if needed.
- Surface the active policy in:
  - `/session`
  - approval UI / execution summaries where relevant
- Provider integration:
  - Codex should use actual read-only / write-capable execution flags where
    available.
  - Claude should use best-effort prompt/context restrictions and explicit UI
    messaging where hard enforcement is not possible.
- Context hash must include file policy so stale approvals and Codex thread
  reuse remain correct.

**Files**:
- `app/config.py` — default policy config if needed
- `app/storage.py` — persist `file_policy`
- `app/telegram_handlers.py` — show policy in `/session` and related surfaces
- provider/context builders — thread policy into execution context

**Tests**:
- session persistence for `inspect|edit`
- Codex command construction in both modes
- context-hash invalidation when file policy changes
- `/session` output coverage

---

## Phase 7 — Ecosystem & Extensibility

### 7.1 Third-party skill registry

**Decision**: Registry work builds directly on the 4.1 managed immutable store.
Do not add remote installs to the legacy mutable store model.

**Problem**: Skills can only come from the local bundled store. There is no way
to discover or install community or organization-published skills with durable
provenance and trust verification.

**Scope**:
- Add a remote registry/index that resolves logical skill names to immutable
  artifacts and metadata.
- Fetch registry artifacts into `skills/managed/objects/<sha256>/...`
  rather than unpacking directly into live skill dirs.
- Create/update logical refs only after artifact verification succeeds.
- Registry metadata should carry:
  - publisher identity
  - version
  - digest
  - signature / trust material
  - description/search fields
- Signature or publisher verification gates ref creation.
- `/skills search` and `/skills info` should be able to surface registry-backed
  results without changing the local managed-store architecture.
- `/skills install` remains name-driven where possible; remote URLs are an
  escape hatch, not the primary UX.

**Files**:
- `app/store.py` — registry fetch, artifact import, trust checks, ref creation
- `app/config.py` — trusted publishers / registry source config
- `app/telegram_handlers.py` — registry-backed search/install UX

**Tests**:
- Registry index parsing
- Artifact fetch/import into managed objects
- Signature / trust verification
- Ref creation only after verification
- Search/info/install flows against a mock registry

---

## Implementation Notes

- Ordering principle: activation before abuse control. Phase 1 fixes the flows
  that make users leave. Phase 2 makes output readable on the primary device.
  Phase 3 adds guardrails as the user base grows. Phase 4 hardens operations.
  Phases 5-7 add the transport, session, and ecosystem work needed for the
  next product step-up.
- Execution sequence from the current state is: `5.2` single-process webhook
  mode (`5.1` done), `6.1` SQLite sessions, `6.2` per-chat projects, `6.3`
  file policy, then `7.1` registry.
- `4.1` is intentionally broader than "repairable ops" because the registry
  should land on the final storage/provenance architecture, not on a temporary
  mutable-store patch.
- `6.1` is not a narrow backend swap. The SQLite schema should carry
  near-term fields like `project_id` and `file_policy` from day one so that
  phases 6.2 and 6.3 do not force an immediate second migration.
- `5.2` is explicitly single-process in the first cut because the current
  per-chat lock model is in-memory. Multi-worker webhook deployment is out of
  scope until after the Phase 6 session work lands.
- `4.1` does not introduce `fork` / `unfork`; same-name custom shadowing is
  the intentional low-complexity override model.
- Every feature gets a regression test before merge.
- Production bugs found during implementation get fixed immediately with a
  regression test, same as the agent-roles-and-skills work.
- No new external dependencies. The mobile summarization feature (2.1) uses
  `claude -p` with a cheap model, keeping the CLI-only architecture.
