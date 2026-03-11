# Architecture

This document describes the bot in terms of contracts, runtime boundaries, and
core components. It is not a feature changelog. Current implementation status
lives in [STATUS-commercial-polish.md](STATUS-commercial-polish.md).

For end-user usage, start with [README.md](../README.md).

After the roadmap's migration phases land, Postgres is the sole supported
runtime backend. The current SQLite-backed session and transport stores remain
important as the shipped baseline and as the cutover import source, but they
are not the long-term runtime authority.

---

## System Contract

Telegram Agent Bot provides a Telegram-native control surface for a local
coding agent.

The system contract is:

1. Telegram is the user interface.
2. Claude Code or Codex is the execution backend.
3. The bot resolves the effective execution context before invoking the
   provider.
4. The bot owns safety, capability layering, output adaptation, and durable
   state.

The product is therefore more than "chatting with a CLI." It is a runtime that
adds:

- approval and retry workflows
- skill and credential management
- per-chat session state
- per-chat project and file policy
- trust-tiered access (`trusted | public`) when open mode is enabled
- user-facing model profiles that resolve to provider-specific model IDs
- durable work-item queue with crash recovery
- transport delivery guarantees for burst traffic and duplicate delivery
- normalized progress events rendered once for Telegram
- Telegram-safe rendering and progressive disclosure for long responses
- operator visibility and health reporting

---

## Runtime Boundaries

The codebase is organized around these hard boundaries.

### 1. Transport boundary

Input arrives as Telegram updates and is normalized into inbound transport
types before business logic runs.

Primary module: `app/transport.py`

Inbound types:

- `InboundMessage` — text + attachments
- `InboundCommand` — slash command with parsed args
- `InboundCallback` — inline keyboard callback

Contract:

- transport normalization extracts user, chat, command, callback, text,
  and attachments into frozen dataclasses
- business logic never depends on raw Telegram payload structure when a
  normalized type exists
- `serialize_inbound()` / `deserialize_inbound()` round-trip events to JSON
  for durable storage in the work queue

### 2. Work-queue boundary

All inbound updates are journaled and serialized through a durable work queue
before processing. This replaces in-memory-only duplicate-delivery handling
and per-chat locking as the primary transport authority.

Primary modules:

- `app/work_queue.py` — current journal, claiming, recovery adapter
- `app/worker.py` — async loop that drains unclaimed items

Current implementation storage: `transport.db` (separate from `sessions.db`
— different lifecycle and retention). After migration, equivalent runtime
authority moves to Postgres.

Tables:

- `updates` — every received `update_id`, with payload and state
- `work_items` — processable units derived from updates

Work-item states:

```
queued ──> claimed ──> done
                  ──> failed
                  ──> pending_recovery ──> (user replay or discard)
           (crash) ──> recovered via recover_stale_claims() ──> queued
```

Control-flow exceptions:

- `LeaveClaimed` — process shutting down; item stays claimed for recovery
  on next boot
- `PendingRecovery` — item needs user decision (replay/discard); worker
  skips completion
- `ReclaimBlocked` — replay attempted but another item for the same chat
  is already claimed

Contract:

- duplicate `update_id` delivery is transport-idempotent (journaled, not
  reprocessed)
- per-chat ordering is enforced durably via atomic claiming
- inline handler path claims synchronously; worker loop drains anything
  left unclaimed (crash recovery, enqueue-without-claim)
- `claim_next_any()` uses `BEGIN IMMEDIATE` for atomic claiming across
  concurrent tasks
- multiple polling processes for the same token are detected and warned
  about, not supported

### 3. Session boundary

Session state is durable and chat-scoped.

Primary modules:

- `app/session_state.py` — typed models (`SessionState`, `PendingApproval`,
  `PendingRetry`, `AwaitingSkillSetup`)
- `app/storage.py` — current session-store adapter, session listing, upload
  paths

Current implementation storage: `sessions.db` (WAL mode, schema-versioned).
After migration, equivalent runtime authority moves to Postgres.

Contract:

- runtime orchestration operates on typed session objects
- handler and request logic should not mutate raw dict session state
- user-selected runtime controls (project binding, file policy, compact mode,
  model profile) belong here
- authorization policy does not belong here; trust tier is resolved per request

### 4. Execution-context boundary

There is one authoritative resolved execution context per request.

Primary module: `app/execution_context.py`

Contract:

- all context-sensitive behavior derives from the same resolved object
- context hash is computed in one place only
- approval validity, retry validity, provider thread invalidation, and
  `/session` must all agree on the same execution identity
- public/open execution-scope restrictions resolve here, not in handlers
- effective model selection resolves here, not inside providers
- downstream functions receive resolved fields — never raw `session.*` or
  `config.*` for working_dir, active_skills, file_policy, extra_dirs, or
  project_id

### 5. Request-flow boundary

Request orchestration is pure business logic, independent of Telegram
transport details.

Primary modules:

- `app/request_flow.py` — validation, credential satisfaction, pending
  validation, denial handling
- `app/approvals.py` — pure functions for preflight prompt building and
  denial formatting

Contract:

- `check_credential_satisfaction` receives the resolved active_skills list,
  not the raw session
- `validate_pending` reads trust_tier from the stored pending state so the
  context hash is recomputed with the same identity shape that created it
- handlers decide how to render outputs and buttons, not how business rules
  work

### 6. Provider boundary

Providers implement a shared protocol and receive only provider-facing
contexts.

Primary modules:

- `app/providers/base.py` — protocol, `RunResult`, `PreflightContext`,
  `RunContext`, `ProgressSink`
- `app/providers/claude.py`
- `app/providers/codex.py`

Contract:

- providers do not resolve session or project state
- provider contexts are already resolved before invocation
- health checks are split into cheap local checks and runtime probes
- providers emit `ProgressEvent` instances (see rendering boundary);
  they never build display HTML directly

### 7. Capability boundary

Skills, credentials, provider config fragments, and the managed store are a
capability layer on top of raw provider execution.

Primary modules:

- `app/skills.py` — skill catalog, loading, resolution
- `app/store.py` — managed skill installation and GC
- `app/registry.py` — remote artifact download and digest verification
- `app/skill_commands.py` — Telegram commands for skill management

Contract:

- skill resolution is deterministic: custom > managed > built-in
- managed skills are immutable content-addressed objects behind refs
- credentials are per-user and loaded only at execution time

### 8. Rendering boundary

The bot owns adaptation from model output to Telegram-safe output, including
both final responses and in-flight progress.

Primary modules:

- `app/formatting.py` — Markdown-to-Telegram HTML conversion, message
  splitting, table rendering
- `app/summarize.py` — compact-mode summarization, raw-response ring buffer,
  chat history export
- `app/progress.py` — normalized progress event family and shared HTML
  renderer

**Progress contract (implemented):**

Both providers map raw CLI events to a shared `ProgressEvent` family:

```
Thinking          Model reasoning, no visible output yet
CommandStart      Shell command execution started
CommandFinish     Shell command completed (exit code, output preview)
ToolStart         Non-command tool invocation started
ToolFinish        Non-command tool invocation finished
ContentDelta      Visible reply text arriving (with recent tool activity)
DraftReply        Intermediate agent commentary
Denial            Tool call or action blocked by sandbox/permissions
Liveness          Provider heartbeat (long compaction, resume timeout)
```

The shared `render()` function owns all user-facing HTML wording. Providers
call `render_progress(event)` — they never construct display HTML directly.

- Codex maps raw events via `CodexProvider._map_event()` (classmethod)
- Claude maps events inline in `ClaudeProvider._consume_stream()`
- Internal events (thread IDs, session metadata) are suppressed at the
  mapping layer — `_map_event` returns `None` and the event is never rendered

**Response contract:**

- compact/full response presentation is a rendering concern
- long responses use progressive disclosure: expandable blockquote (≤ 4000
  chars) or expand/collapse buttons (> 4000 chars)
- expand/collapse resolves a stable slot reference back to the raw-response
  ring buffer before re-rendering
- provider names, thread IDs, and internal details never leak into user-facing
  progress or response output

---

## Component Map

```
Telegram updates
  |
  v
transport.py            Normalize InboundMessage / Command / Callback
  |
  v
work_queue.py           Journal update_id, create work item, claim
  |
  +----(inline claim)-----+----(worker drain)----+
  |                        |                      |
  v                        v                      v
telegram_handlers.py    worker.py              (same dispatch)
skill_commands.py
  |
  +-----------------+-------------------+
  |                 |                   |
  v                 v                   v
request_flow.py   doctor.py         ratelimit.py
approvals.py
  |
  v
execution_context.py    Resolve context, hash, model, trust tier
  |
  +-----------------+
  |                 |
  v                 v
skills.py         session_state.py / storage.py
store.py
registry.py
  |
  v
providers/base.py       Protocol: run, run_preflight, check_health
providers/claude.py     emit ProgressEvent --> progress.py render()
providers/codex.py      emit ProgressEvent --> progress.py render()
  |
  v
formatting.py           md_to_telegram_html, split_html, tables
summarize.py            Ring buffer, compact mode, /raw
progress.py             ProgressEvent family, shared render()
```

Ownership:

- transport normalizes inbound, serializes for durability
- work queue owns transport idempotency, claiming, and crash recovery
- worker drains unclaimed items; inline path claims synchronously
- handlers own routing, Telegram I/O, button rendering
- request flow owns business rules
- execution context owns resolved runtime identity
- storage owns session persistence
- providers own subprocess invocation, emit progress events
- progress owns all user-facing progress HTML wording
- formatting/summarize own response adaptation
- skills/store/registry own capabilities

---

## Core Data Contracts

### SessionState

Runtime representation of a chat session. The current shipped adapter stores it
as JSON in `sessions.db`; the post-migration runtime keeps the same typed
contract while moving authority to Postgres.

It owns:

- provider identity and provider-local state
- approval mode
- active skills and role
- project binding and file policy
- model-profile override and compact-mode override
- pending approval / retry state
- awaiting credential setup state

It does not own: user credentials, authorization policy, uploads, skill
contents, provider binaries.

### PendingApproval / PendingRetry

Pending state must carry:

- original requester identity
- original prompt and image list
- original context hash
- trust tier at creation time
- creation time

`PendingRetry` additionally carries denial records used to derive retry
permissions.

### ResolvedExecutionContext

Single authoritative execution identity. It carries:

Identity fields: role, active skills, skill digests, provider config digest,
execution config digest, base extra dirs, project id, effective working dir,
file policy, provider name.

Resolved execution controls: effective model profile, effective model ID,
trust tier, effective allowed roots / extra dirs, provider-facing working dir.

It is the source of: context hash, `/session` display, provider-facing
`working_dir`, approval/retry freshness, Codex thread invalidation.

Codex thread reuse is valid only when the resolved identity matches the stored
context hash AND the process boot ID matches the stored boot ID.

### Provider Contexts

Provider-facing contexts are intentionally narrower than session state.

`PreflightContext`: extra dirs, system prompt, capability summary, working dir,
file policy, effective model ID.

`RunContext` extends it with: provider config, credential env,
permission-bypass flag, effective model ID.

Providers do not need pending state, session timestamps, or credential setup
state.

### RunResult

Provider execution result carrying: text, returncode, timed_out,
resume_failed, provider_state_updates, denials.

### ProgressEvent

Frozen dataclasses (one per event type) emitted by providers during execution.
Rendered to Telegram HTML by the shared `render()` function in `progress.py`.

---

## State and Storage Model

### Durable storage

The shipped implementation uses two SQLite databases with different
lifecycles. After migration, equivalent runtime authority moves to Postgres
for session state and the core request queue while preserving the same typed
session, transport-payload, and execution-context contracts.

**Current shipped `sessions.db`** — chat session state:

- session rows (chat_id PK, provider, JSON data, timestamps)
- indexed summaries (`has_pending`, `has_setup`, `project_id`, `file_policy`)

**Current shipped `transport.db`** — update journal and work items:

- `updates` table — every received `update_id` with serialized payload
- `work_items` table — processable units with state machine
  (queued/claimed/done/failed/pending_recovery)

**Filesystem** stores:

- uploads per chat (`{data_dir}/uploads/{chat_id}/`)
- encrypted credentials per user
- managed skill objects and refs (`objects/`, `refs/`, `custom/`)
- raw-response ring buffer (`{data_dir}/raw/{chat_id}/`)
- staged Codex helper scripts

### Why this split exists

Session state benefits from atomic updates, indexed queries, schema evolution.

Files and artifacts benefit from filesystem semantics, direct provider access,
operator inspectability.

Transport data has a different retention policy and lifecycle than sessions —
it tracks ephemeral update delivery, not long-lived chat state. That
separation remains after the Postgres cutover even though the backing store
changes.

### Response history and progressive disclosure

The raw-response ring buffer (capacity 50 per chat) is the single source of
truth for `/raw` and expand/collapse flows.

- `save_raw()` stores prompt + raw text in a numbered slot
- `load_raw()` retrieves the latest; `load_raw_by_slot()` retrieves by slot
- slots rotate FIFO; rotated slots return `None` (expand callback shows
  "no longer available")
- rendered compact/full variants are derived views, not separate durable state

---

## Skill and Capability Architecture

### Resolution model

Skill resolution is strictly ordered:

1. custom skill override
2. managed installed skill
3. built-in catalog skill

Any feature that displays skill details must use the resolved tier.

### Managed store model

Managed skills are stored as immutable content-addressed objects with logical
refs.

- install/update are ref operations, not in-place mutation
- GC removes unreferenced objects conservatively
- schema guard protects incompatible managed-store versions

### Registry model

The registry is a source of managed artifacts:

- artifact downloaded to staging
- digest verified before object creation
- only verified content becomes a managed object/ref

---

## Request Lifecycle Contracts

### Normal request

1. normalize inbound message
2. authorize user, resolve trust tier
3. journal update, create work item, claim
4. load and normalize session
5. resolve execution context (with trust tier)
6. check credential satisfaction (using resolved active_skills)
7. build provider context (from resolved context)
8. invoke provider (progress events rendered via shared renderer)
9. persist updated session state
10. format and send response (compact mode, tables, progressive disclosure)
11. save raw response to ring buffer
12. deliver directed artifacts (using resolved allowed roots)

### Approval request

1. resolve execution context
2. build preflight context
3. run provider preflight (read-only, `build_preflight_prompt()`)
4. store `PendingApproval`
5. render plan + approve/reject buttons

Approval succeeds only if: pending exists, not expired, context hash matches
(recomputed with stored trust_tier).

### Retry request

Same validation as approval, plus retry-specific permission scope from
denials.

### Credential setup

Credential setup is conversational state, not a hidden side effect.

- only the owning user may continue setup
- foreign setup blocks are visible and explain who is active
- one credential-setup flow per shared chat at a time
- abandoned foreign blocks auto-expire
- captured credentials are deleted from chat after processing
- execution loads credentials for the request user, not the clicker

### Transport delivery and recovery

- one active ingress owner per bot token
- duplicate `update_id` delivery is transport-idempotent (journaled, not
  reprocessed)
- per-chat ordering is enforced by atomic claiming
- bursty same-chat traffic gets visible acknowledgment; nothing silently
  dropped
- crash recovery: `recover_stale_claims()` requeues items left in `claimed`
  state by a dead worker
- pending_recovery items require explicit user action (replay or discard)

Scaling path: single-process polling today. Future multi-worker uses webhook +
shared Postgres queue authority + worker loop as primary processing path. The
current shipped implementation uses `transport.db` as the single-host
foundation.

---

## Access and Safety Model

### User authorization

Only allowed users may interact. When open mode is enabled, users resolve to:

- `trusted`: users in the allowed-user set
- `public`: everyone else

### Admin authorization

A narrower set of users may manage store-backed skills and inspect broader
session state.

### Approval mode

Controls whether execution requires preflight plan review.

### File policy

Controls whether the session is inspect-only or may edit.

### Project binding

Controls which working directory is in scope.

### Allowed roots

Derive from the resolved execution context:

- `resolved.working_dir` (project root, public root, or default)
- `resolved.base_extra_dirs` (empty for public users)
- chat upload dir
- denial-derived retry dirs

Must be computed from `ResolvedExecutionContext`, not raw config.

### Public-trust enforcement

Two layers:

**Execution-scope (in `resolve_execution_context`):** forced inspect policy,
forced public working dir, stripped extra dirs, stripped skills, disabled
project binding. These flow automatically into provider context, context hash,
approval/retry freshness, credential satisfaction, file roots, and artifact
delivery.

**Command-availability (in handlers):** disabled skill management, disabled
project changes, constrained `/send`, restricted model profiles. Public users
see only profiles in `public_model_profiles`.

---

## Provider Responsibilities

Providers are responsible for:

- command construction and subprocess execution
- mapping raw CLI events to `ProgressEvent` instances
- provider-local state updates (thread_id, session state)
- health probes (local + runtime)
- respecting working_dir, extra_dirs, file_policy, effective model

They are not responsible for: session persistence, approval decisions,
credential prompting, skill discovery, progress HTML wording.

### Claude-specific

- session-oriented backend
- inspect mode is best-effort via prompt/context restriction
- maps stream-json events to progress events inline in `_consume_stream()`

### Codex-specific

- thread-oriented backend
- inspect mode hard-enforced through sandbox selection
- thread invalidation depends on authoritative context hash + boot ID
- maps NDJSON events via `_map_event()` classmethod

---

## Health and Admin Components

### doctor.py

Shared health-orchestration layer for Telegram `/doctor` and CLI entry point.

Owns: config validation, provider health, managed-store health, stale session
scanning, per-chat skill validation, public-mode diagnostics (rate limits,
public root, trust profiles), transport diagnostics (polling-conflict
detection).

### Admin views

Reporting surfaces over current durable state: `/admin sessions`, session
summaries, stale pending and setup visibility.

---

## Testing Architecture

The test suite is organized around contracts, not only features.

### Handler and scenario tests

Exercise real user entry points through Telegram handlers. Use shared test
support (`tests/support/handler_support.py`) with `FakeChat`, `FakeProvider`,
`FakeProgress`, and helpers for `send_text`, `send_command`, `send_callback`.

### Invariant tests

Protect cross-cutting rules: context-hash stability, approval/retry freshness,
inspect-mode enforcement, public-trust enforcement, effective-model
propagation, credential satisfaction, command/callback parity, registry
integrity, async non-blocking guarantees, provider-context propagation,
transport delivery guarantees.

### Progress contract tests

Dedicated suite (`test_progress.py`) testing five layers: render() contract
for all event types, no-internals leak checks, Codex `_map_event` mapping,
end-to-end pipeline, Claude `_consume_stream` integration.

### Output and compact-mode tests

`test_handlers_output.py` covers compact toggle, `/raw` retrieval, table
rendering, blockquote and expand/collapse button paths, summary-first prompt
injection, expand→collapse→expand round-trips, rotated buffer edge case.

### Edge-case suites

Callback races, provider failures, formatting boundaries, session reset.

### Setup / bootstrap tests

`test_setup.sh` protects the installation wizard and generated configs.

---

## Interfaces That Must Stay Stable

The following are internal contracts that should only change deliberately:

- `SessionState`
- `PendingApproval` / `PendingRetry` (including `trust_tier` field)
- `ResolvedExecutionContext`
- `PreflightContext` / `RunContext`
- `Provider` protocol and `RunResult`
- `ProgressEvent` family and `render()` contract
- `check_credential_satisfaction` signature (resolved active_skills)
- `validate_pending` signature (trust_tier from stored pending)
- work-item state machine (queued/claimed/done/failed/pending_recovery)
- transport delivery semantics (`update_id` handling, claiming rules)
- managed store layout (`objects/`, `refs/`, `custom/`)
- registry index format versioning
- ring-buffer slot format (used by expand/collapse callback data)

Changing these should trigger both code review and invariant test updates.

---

## Rebuild Guidance

If rebuilding the bot from scratch, preserve this order of responsibility:

1. normalize transport (inbound types)
2. journal updates and enforce transport idempotency (durable work queue)
3. claim work item (atomic, per-chat serialized)
4. load typed session state
5. resolve trust tier and authoritative execution context
6. apply business rules using resolved context (`request_flow`)
   - credential checks use resolved active_skills
   - pending validation uses stored trust_tier
7. build provider-facing context from resolved context
8. invoke provider (progress events → shared renderer → Telegram)
9. persist session and durable delivery state
10. render Telegram-safe output (formatting, compact mode, tables)
11. save raw response to ring buffer
12. deliver directed artifacts using resolved allowed roots

That order is more important than the exact module names.

The single most important architectural rule: once `resolve_execution_context`
produces a `ResolvedExecutionContext`, all downstream code reads execution-scope
fields from that object. Never from raw `session.*` or `config.*` for
working_dir, file_policy, active_skills, extra_dirs, or project_id.
