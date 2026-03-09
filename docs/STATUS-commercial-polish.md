# Commercial Polish — Implementation Status

Current as of 2026-03-09. Tracks progress against [PLAN-commercial-polish.md](PLAN-commercial-polish.md).

---

## Phase Completion Summary

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 | Activation & self-service | Mostly done |
| Phase 2 | Output quality | Done |
| Phase 3 | Trust & cost control | Done |
| Phase 4 | Operational hardening | Mostly done (4.1 deferred) |
| Phase 5 | Ecosystem & extensibility | Not started |

---

## Test Suite

Canonical full-suite runner: `./scripts/test_all.sh`

Current suite: 1,293 passing checks across 20 entrypoints.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_approvals.py` | 11 | Preflight prompt building, denial formatting. |
| `test_claude_provider.py` | 16 | Claude CLI command construction, API ping health check. |
| `test_codex_provider.py` | 55 | Codex CLI command construction, thread invalidation, progress parsing, health check with real flags. |
| `test_config.py` | 16 | Config loading, validation, `.env` parsing, rate limit and admin config. |
| `test_formatting.py` | 297 | Markdown-to-Telegram HTML conversion, balanced HTML splitting, table rendering, directive extraction. |
| `test_handlers.py` | 92 | Core handler integration: happy-path routing, role/session behavior, `/doctor` warnings (admin fallback, stale sessions, prompt size), `/help`, `/start`. |
| `test_handlers_admin.py` | 12 | `/admin sessions` summary and detail views, access gating. |
| `test_handlers_approval.py` | 53 | Approval and pending-request flows: preflight, approve/retry/skip, stale pending TTL. |
| `test_handlers_codex.py` | 33 | Codex-specific handler behavior: thread invalidation, boot ID, retry semantics, script staging. |
| `test_handlers_credentials.py` | 155 | Credential and setup flows: capture, validation, isolation, clear/cancel, group-setup protection. |
| `test_handlers_export.py` | 4 | `/export` command: no history, document generation, access gating. |
| `test_handlers_output.py` | 20 | Output presentation: `/compact`, `/raw`, table rendering, summarization flows. |
| `test_handlers_ratelimit.py` | 11 | Rate limiting integration: blocking, admin exemption (explicit vs implicit), per-user isolation. |
| `test_handlers_store.py` | 28 | Store handler flows: install/update/uninstall, locally modified confirmation, prompt-size warnings. |
| `test_high_risk.py` | 78 | Cross-cutting invariants: requester identity, context hash staleness, credential injection, system prompt injection. |
| `test_ratelimit.py` | 21 | RateLimiter unit tests: sliding window, per-minute/per-hour, user isolation, clear, expiry. |
| `test_skills.py` | 201 | Skill engine: catalog, instruction loading, prompt composition, credential encryption, context hashing. |
| `test_storage.py` | 41 | Session CRUD, upload paths, directory creation, session sweep, `list_sessions()`. |
| `test_store.py` | 115 | Store module: discovery, search, install/uninstall, SHA-256 provenance, locally_modified persistence. |
| `test_summarize.py` | 34 | Ring buffer (full prompt, kind field, rotation at 50), export formatting, backward compat, summarization. |
| `test_setup.sh` | 34/35 | Installer/setup wizard flows, provider-pruned config generation. (1 systemd test skipped in CI.) |

---

## Phase 3 — Trust & Cost Control

### What shipped

**3.1 Rate limiting** (`app/ratelimit.py`)
- Sliding-window limiter with `BOT_RATE_LIMIT_PER_MINUTE` / `BOT_RATE_LIMIT_PER_HOUR` config.
- Admins exempt only when `BOT_ADMIN_USERS` is explicitly set (not fallback).
- Integrated in `handle_message` before any provider work.

**3.3 Admin safety posture**
- `admin_users_explicit: bool` in BotConfig distinguishes explicit config from fallback.
- `/doctor` warns when `BOT_ADMIN_USERS` not set and multiple allowed users exist.
- Rate limiter respects the explicit/fallback distinction.

**3.4 Proactive prompt size warnings**
- `estimate_prompt_size()` in `app/skills.py` projects prompt size before activation.
- Inline keyboard confirmation when projected size exceeds threshold.
- `handle_skill_add_callback` processes confirm/cancel.

**3.5 Runtime health checks**
- Claude: API ping via `claude -p --model <model> --max-turns 1`.
- Codex: API ping via `codex exec --ephemeral` mirroring real execution flags (sandbox, skip-git-repo-check, model, profile, working dir).
- Age-gated stale session scan: pending requests >1h, credential setup >10m.

**3.2 Usage tracking** — Deferred. Requires token-cost mapping and billing integration.

### Bugs found and fixed

| Bug | Severity | Root cause | Fix |
|-----|----------|-----------|-----|
| Rate limiter ineffective for implicit admins | High | Admin fallback made all users admin-exempt from rate limiting | Added `admin_users_explicit` flag; rate limiter only exempts when explicitly configured |
| Codex health check fails in valid environments | Medium | Ping command didn't use real execution flags | Mirror `--sandbox`, `--skip-git-repo-check`, `--model`, `--profile`, `-C working_dir` |
| `/doctor` stale scan counts fresh sessions | Medium | No age threshold — any pending request was flagged | Added `_STALE_PENDING_SECONDS = 3600`, `_STALE_SETUP_SECONDS = 600` |
| `/doctor` false positive for explicit admin with equal user sets | Low | Warning triggered when admin set == allowed set regardless of explicit config | Check `admin_users_explicit` flag, not set equality |

---

## Phase 4 — Operational Hardening

### What shipped

**4.2 Locally modified skill protection**
- `/skills update <name>` shows confirmation prompt with inline keyboard when skill has local modifications.
- `/skills update all` lists all locally modified skills and requires single confirmation.
- `/skills diff <name>` shows unified diff between installed and store versions (first 2000 chars).
- `is_locally_modified()` and `diff_skill()` in `app/store.py`.

**4.3 Configuration template per provider**
- `setup.sh` prunes codex-specific config lines when provider is claude (and vice versa).
- `.env.example` remains the full reference; generated configs are clean.

**4.4 Admin session visibility** (`app/storage.py`, `app/telegram_handlers.py`)
- `list_sessions()` in storage.py reads all session files, returns sorted summary dicts.
- `/admin sessions` — summary view: total sessions, pending approvals, top skills by usage.
- `/admin sessions <chat_id>` — detail view: provider, approval mode, skills, timestamps.
- Admin-gated via `is_admin()`.

**4.5 Conversation export**
- Ring buffer upgraded: full prompt storage (no truncation), `kind` field (`request`/`approval`/`system`), capacity 10 → 50.
- Approval plan turns now captured in ring buffer.
- `export_chat_history()` in `app/summarize.py` formats entries with kind labels and backward compat for old `prompt_preview` field.
- `/export` sends session metadata header + history as downloadable `.txt` document.
- Header includes scope note: "last 50 exchanges, command replies and older turns not included."
- `/help` updated to list `/export` and `/admin sessions`.

**4.1 Repairable skill store operations** — Deferred. Requires intent logging and recovery on startup; most complex item in phase.

### Design decisions

**Ring buffer vs append-only log**: The `/export` feature deliberately reuses the existing ring buffer rather than building a separate conversation log. The ring buffer stores the last 50 turns with full prompts, which covers most practical export needs. A proper append-only log is a future option if unbounded history becomes a requirement. The export header documents the scope limitation.

**Admin session listing**: Returns all sessions sorted by `updated_at`. No pagination — bounded by number of session files on disk. Detail view shows per-session metadata without loading provider state internals.

---

## What's Not Yet Implemented

| Item | Status | Notes |
|------|--------|-------|
| 3.2 Usage tracking & quotas | Deferred | Needs token-cost mapping, billing integration |
| 4.1 Repairable store operations | Deferred | Intent log + recovery; most complex Phase 4 item |
| 5.1 Third-party skill registry | Not started | Remote install, signature verification, trusted publishers |
| 5.2 Webhook mode | Not started | `BOT_MODE=poll\|webhook`, aiohttp server, `/health` endpoint |
