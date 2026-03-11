# Architecture

This document describes the bot in terms of contracts, runtime boundaries, and
storage authority. It is not a feature changelog. Current implementation
status lives in [STATUS-commercial-polish.md](STATUS-commercial-polish.md).

For end-user usage, start with [README.md](../README.md).

After the roadmap's migration phases land, Postgres is the sole supported
runtime backend. The current SQLite-backed session and transport stores remain
important as sealed shipped history and as the import source for that cutover,
but they are no longer the long-term runtime authority described here.

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

The runtime therefore adds:

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

## Runtime Authority

- Execution identity is resolved once and reused everywhere downstream.
- The core request queue remains application-owned. Phases 11-14 do not adopt
  Celery, Temporal, PGMQ, or another generic broker for the primary Telegram
  request path.
- Postgres is the runtime authority after migration for session storage and
  work-queue ownership.
- Filesystem storage remains authoritative for uploads, encrypted credentials,
  managed skill objects/refs, raw-response history, and staged helper files.
- Historical note: the shipped implementation today uses SQLite-backed
  adapters (`sessions.db` and `transport.db`) behind the same contracts.

Terminology:

- `transport idempotency`: durable `update_id` journal plus one-work-item
  ownership for a given update
- `content dedup`: optional suppression policy for identical consecutive user
  messages; not part of the core transport contract

---

## Runtime Boundaries

The codebase is organized around these hard boundaries.

### 1. Transport boundary

Input arrives as Telegram updates and is normalized into inbound transport
types before business logic runs.

Primary module: `app/transport.py`

Inbound types:

- `InboundMessage` - text plus attachments
- `InboundCommand` - slash command with parsed args
- `InboundCallback` - inline keyboard callback

Contract:

- transport normalization extracts user, chat, command, callback, text, and
  attachments into frozen dataclasses
- business logic never depends on raw Telegram payload structure when a
  normalized type exists
- `serialize_inbound()` and `deserialize_inbound()` round-trip normalized
  payloads to JSON for durable queue storage

### 2. Transport and recovery workflow boundary

All inbound updates are journaled and serialized through a durable work queue
before processing. This replaces in-memory-only duplicate-delivery handling as
the primary transport authority.

Current primary modules:

- `app/work_queue.py` - journal, claiming, recovery
- `app/worker.py` - async loop that drains runnable items

Authoritative queue shape after migration:

- `updates` table - every received `update_id`, payload, and receipt metadata
- `work_items` table - processable units derived from updates

Work-item states:

```
queued -> claimed -> done
                -> failed
                -> pending_recovery -> replayed / discarded / superseded
         crash -> recovered -> queued
```

Control-flow exceptions:

- `LeaveClaimed` - process shutting down; item stays claimed for recovery
- `PendingRecovery` - item needs explicit replay/discard decision
- `ReclaimBlocked` - replay attempted while another item for the same chat is
  already claimed

Contract:

- duplicate `update_id` delivery is idempotent and not reprocessed
- per-chat ordering is enforced durably through queue claiming rules
- inline handler path may claim synchronously; worker loop drains anything left
  runnable
- webhook ingress should normalize, persist, and acknowledge quickly
- workers become the primary execution path in webhook plus Postgres mode
- no provider execution occurs inside a long-lived queue claim transaction

Historical note:

- Today's shipped implementation uses `transport.db` and SQLite transactions in
  `app/work_queue.py`.
- After Phase 13, the same authority moves to Postgres with row-lock claiming
  and lease metadata while preserving payload JSON shapes.

### 3. Session boundary

Session state is durable and chat-scoped.

Primary modules:

- `app/session_state.py` - typed models (`SessionState`, `PendingApproval`,
  `PendingRetry`, `AwaitingSkillSetup`)
- `app/storage.py` - session CRUD, session listing, upload paths

Contract:

- runtime orchestration operates on typed session objects
- handler and request logic should not mutate raw dict session state
- user-selected runtime controls (project binding, file policy, compact mode,
  model profile) belong here
- authorization policy does not belong here; trust tier is resolved per
  request

Historical note:

- The shipped adapter today is SQLite-backed `sessions.db`.
- After Phase 12, the session store moves to Postgres while retaining the same
  typed dataclass boundary.

### 4. Execution-context boundary

There is one authoritative resolved execution context per request.

Primary module: `app/execution_context.py`

Contract:

- all context-sensitive behavior derives from the same resolved object
- context hash is computed in one place only
- approval validity, retry validity, provider thread invalidation, and
  `/session` must agree on the same execution identity
- public/open execution-scope restrictions resolve here, not in handlers
- effective model selection resolves here, not inside providers
- downstream functions receive resolved fields, never raw `session.*` or
  `config.*` for working_dir, active_skills, file_policy, extra_dirs, or
  project_id

### 5. Approval and retry workflow boundary

Request orchestration is pure business logic, independent of Telegram
transport details.

Primary modules:

- `app/request_flow.py` - validation, credential satisfaction, pending
  validation, denial handling
- `app/approvals.py` - pure functions for preflight prompt building and denial
  formatting

Contract:

- `check_credential_satisfaction()` receives resolved `active_skills`, not the
  raw session
- `validate_pending()` reads `trust_tier` from stored pending state so the
  context hash is recomputed with the same identity shape that created it
- handlers decide how to render outputs and buttons, not how approval/retry
  rules work
- Phase 11 extracts this workflow into a more explicit owner without changing
  the underlying contracts

### 6. Provider boundary

Providers implement a shared protocol and receive only provider-facing
contexts.

Primary modules:

- `app/providers/base.py` - protocol, `RunResult`, `PreflightContext`,
  `RunContext`, `ProgressSink`
- `app/providers/claude.py`
- `app/providers/codex.py`

Contract:

- providers do not resolve session or project state
- provider contexts are already resolved before invocation
- health checks are split into cheap local checks and runtime probes
- providers emit `ProgressEvent` instances; they never build display HTML
  directly

### 7. Capability boundary

Skills, credentials, provider config fragments, and the managed store are a
capability layer on top of raw provider execution.

Primary modules:

- `app/skills.py` - skill catalog, loading, resolution
- `app/store.py` - managed skill installation and GC
- `app/registry.py` - remote artifact download and digest verification
- `app/skill_commands.py` - Telegram commands for skill management

Contract:

- skill resolution is deterministic: custom > managed > built-in
- managed skills are immutable content-addressed objects behind refs
- credentials are per-user and loaded only at execution time

### 8. Rendering boundary

The bot owns adaptation from model output to Telegram-safe output, including
both final responses and in-flight progress.

Primary modules:

- `app/formatting.py` - Markdown-to-Telegram HTML conversion, message
  splitting, table rendering
- `app/summarize.py` - compact-mode summarization, raw-response ring buffer,
  chat history export
- `app/progress.py` - normalized progress event family and shared HTML
  renderer

Progress contract:

- providers map raw CLI events to a shared `ProgressEvent` family
- the shared renderer owns all user-facing progress wording
- internal provider details such as thread IDs, session IDs, and internal
  resume mechanics are suppressed at the mapping layer
- compact/full response presentation is a rendering concern
- long responses use expandable blockquotes or expand/collapse callbacks
- the raw-response ring buffer is the single source of truth for `/raw` and
  expand/collapse regeneration

### 9. Health and admin boundary

Shared health/reporting orchestration exists above transport and provider
details.

Primary modules:

- `app/doctor.py`
- Telegram handlers for `/doctor` and admin session views

Contract:

- Telegram `/doctor` and CLI doctor are two renderers over the same health
  orchestration
- admin views report current durable state rather than rebuilding state from
  logs or heuristics

---

## Component Map

```
Telegram updates
  |
  v
transport.py            Normalize InboundMessage / Command / Callback
  |
  v
transport/recovery workflow
  |
  +---- inline claim path --------+
  |                               |
  v                               v
telegram_handlers.py           worker.py
skill_commands.py
  |
  +----------- approval/retry workflow -----------+
  |                                               |
  v                                               v
request_flow.py                               approvals.py
  |
  v
execution_context.py       Resolve trust tier, model, file roots, context hash
  |
  +------------------+-------------------+
  |                  |                   |
  v                  v                   v
session_state.py   skills/store.py     providers/*
storage.py         registry.py
  |                                       |
  |                                       v
  |                                   progress.py
  |                                       |
  +--------------------------+------------+
                             |
                             v
                     formatting.py / summarize.py
```

---

## Core Data Contracts

### SessionState

Runtime representation of a chat session.

It owns:

- provider identity and provider-local state
- approval mode
- active skills and role
- project binding and file policy
- model-profile override and compact-mode override
- pending approval/retry state
- awaiting credential setup state

It does not own:

- user credentials
- authorization policy
- uploads
- skill contents
- provider binaries

### PendingApproval and PendingRetry

Pending state must carry:

- original requester identity
- original prompt and image list
- original context hash
- trust tier at creation time
- creation time

`PendingRetry` additionally carries denial records used to derive retry
permissions.

### ResolvedExecutionContext

Single authoritative execution identity.

Identity fields:

- role
- active skills
- skill digests
- provider config digest
- execution config digest
- base extra dirs
- project id
- effective working dir
- file policy
- provider name

Resolved controls:

- effective model profile
- effective model ID
- trust tier
- effective allowed roots / extra dirs
- provider-facing working dir

It is the source of:

- context hash
- `/session` display
- provider-facing working dir
- approval/retry freshness
- Codex thread invalidation

### Inbound Payloads

Normalized inbound payloads are durable queue inputs, not temporary handler
objects. Their serialized JSON shape must remain backward compatible across the
SQLite-to-Postgres cutover.

### Provider Contexts

`PreflightContext` carries:

- extra dirs
- system prompt
- capability summary
- working dir
- file policy
- effective model ID

`RunContext` extends it with:

- provider config
- credential env
- permission-bypass flag
- effective model ID

### RunResult

Provider execution result carrying:

- text
- returncode
- timed_out
- resume_failed
- provider_state_updates
- denials

### ProgressEvent

Frozen dataclasses emitted by providers during execution. Rendered to Telegram
HTML by the shared renderer in `progress.py`.

---

## Storage and Queue Authority

### Runtime authority after migration

Postgres owns runtime state after Phase 12.

Required authority:

- chat-scoped session rows
- `updates` table for inbound update journal
- `work_items` table for runnable/claimed/terminal state
- row-lock claiming and lease metadata
- recovery metadata for replay, discard, and supersession
- one-way import from SQLite during cutover

Queue ownership rules:

- webhook ingress normalizes, persists, and acknowledges quickly
- workers claim runnable work items atomically
- per-chat ordering is preserved by claim rules, not by hope or handler timing
- provider execution happens outside the queue-claim transaction
- terminal ownership is written back durably after execution

### Current shipped implementation

The shipped baseline still uses:

- `sessions.db` for session storage
- `transport.db` for update journal and work items

This matters because:

- it is the migration import source for Phase 12
- it is the compatibility reference for payload JSON and typed session shapes
- it is the sealed historical implementation that proved the current runtime
  contracts

### Filesystem authority

Filesystem-backed durable assets remain outside the runtime database:

- uploads per chat
- encrypted credentials per user
- managed skill objects, refs, and custom overrides
- raw-response ring buffer
- staged Codex helper scripts

---

## Request Lifecycle Contracts

### Normal request

1. Normalize inbound message.
2. Authorize user and resolve trust tier.
3. Persist update journal entry and create/claim work item.
4. Load typed session state.
5. Resolve authoritative execution context.
6. Check credential satisfaction using resolved `active_skills`.
7. Build provider context from resolved fields.
8. Invoke provider and stream `ProgressEvent` instances.
9. Persist updated session and work-item state.
10. Format and send response.
11. Save raw response to the ring buffer.
12. Deliver directed artifacts using resolved allowed roots.

### Approval and retry

1. Resolve execution context.
2. Build preflight context.
3. Run provider preflight.
4. Store pending approval or retry state.
5. Render approval/retry actions.

Approval and retry succeed only if:

- pending state exists
- it is not expired
- context hash still matches
- authorization still matches the stored trust tier and owner

### Recovery

1. Interrupted claimed work is recovered durably.
2. Recovery owner moves it to `pending_recovery` instead of auto-replaying.
3. User chooses replay or discard, or a fresh message supersedes it.
4. Replay may reuse still-valid provider context, but replay ownership is
   still explicit user intent.

---

## Access and Safety Model

### User authorization

Only allowed users may interact unless open mode is enabled. In open mode,
users resolve to:

- `trusted`: users in the allowed-user set
- `public`: everyone else

### Admin authorization

A narrower set of users may manage store-backed skills and inspect broader
session state.

### Approval mode

Controls whether execution requires preflight review before running.

### File policy

Controls whether the session is inspect-only or may edit.

### Project binding

Controls which working directory is in scope.

### Allowed roots

Allowed roots derive from the resolved execution context:

- resolved working dir
- resolved base extra dirs
- chat upload dir
- denial-derived retry dirs

They must never be computed from raw config/session state once a resolved
context exists.

### Public-trust enforcement

Two layers must remain separate:

- execution-scope enforcement in `resolve_execution_context()`
- command-availability gating in Telegram handlers

This split ensures new entry points inherit safe public behavior rather than
reimplementing it.

---

## Interfaces That Must Stay Stable

The following contracts should only change deliberately:

- `SessionState`
- `PendingApproval` and `PendingRetry`
- normalized inbound payload JSON shapes
- `ResolvedExecutionContext`
- `PreflightContext` and `RunContext`
- `Provider` protocol and `RunResult`
- `ProgressEvent` family and renderer contract
- `check_credential_satisfaction()` resolved-skill input contract
- `validate_pending()` trust-tier contract
- work-item state machine
- transport delivery semantics for `update_id`, claiming, and terminal states
- managed store layout (`objects/`, `refs/`, `custom/`)
- registry index format versioning
- raw-response ring-buffer slot format

Changing these should trigger both code review and contract-test updates.

---

## Rebuild Guidance

If rebuilding the bot from scratch, preserve this order of responsibility:

1. Normalize transport into durable inbound types.
2. Persist inbound update journal and enforce transport idempotency.
3. Create/claim work items with per-chat ordering rules.
4. Load typed session state.
5. Resolve trust tier and authoritative execution context.
6. Apply approval/retry/business rules using resolved context.
7. Build provider-facing context from resolved fields.
8. Invoke provider and map raw events into `ProgressEvent`.
9. Persist terminal session and work-item outcomes.
10. Render Telegram-safe output and progressive disclosure.
11. Save raw response history.
12. Deliver artifacts using resolved allowed roots.

That order is more important than the exact module names.

The single most important architectural rule is unchanged: once
`resolve_execution_context()` produces a `ResolvedExecutionContext`, all
downstream code reads execution-scope fields from that object, not from raw
`session.*` or `config.*`.
