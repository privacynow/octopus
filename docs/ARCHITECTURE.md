# Architecture

This document describes the bot in terms of contracts, runtime boundaries, and
core components. It is not a feature changelog. Current implementation status
lives in [STATUS-commercial-polish.md](STATUS-commercial-polish.md).

For end-user usage, start with [README.md](../README.md).

Phase 13 is complete: **Local Runtime** is the only supported mode. The default
path is **SQLite** (no `BOT_DATABASE_URL`); **Postgres** is a supported alternate
backend when `BOT_DATABASE_URL` is set. **Shared Runtime** is out of scope until
a later phase.

- **Runtime matrix:** local + sqlite = default; local + postgres = supported; shared = rejected.
- **Backend seam:** `app/runtime_backend.py` is the only backend selector; `storage.py` and `work_queue.py` are backend-neutral facades. Implementations: `storage_sqlite`, `storage_postgres`, `work_queue_sqlite`, `work_queue_postgres`.
- **Contract suites:** `tests/contracts/test_session_store_contract.py` and `tests/contracts/test_transport_store_contract.py` run against both SQLite and Postgres and define backend-neutral behavior.
- **E2E:** Primary gate is `test_compose_sqlite_local_runtime_primary` (Docker bot, no Postgres). Bounded Postgres coverage: bootstrap/doctor and bot startup with Postgres tooling.

---

## System context (high-level)

```
  +--------+                    +------------------------------------------+
  | User   |  Telegram API     | Bot process                              |
  |(client)|<=================>|                                          |
  +--------+  updates / send    |  +-------------+  +-------------------+  |
                               |  | transport   |  | work_queue        |  |
                               |  | (normalize) |->| (journal, claim)  |  |
                               |  +-------------+  +-------------------+  |
                               |         |                  |           |
                               |         v                  v           |
                               |  +-------------+  +-------------------+  |
                               |  | handlers    |  | worker_loop       |  |
                               |  | (routing,    |  | (drain unclaimed) |  |
                               |  |  Telegram   |  +-------------------+  |
                               |  |  I/O)       |           |              |
                               |  +------+------+           |              |
                               |         |     +------------+              |
                               |         v     v                           |
                               |  request_flow, execution_context,         |
                               |  session_state, skills                    |
                               |         |                                 |
                               |         v                                 |
                               |  +-------------+  +-------------------+     |
                               |  | providers   |  | progress /       |     |
                               |  | (Claude,    |->| formatting /      |     |
                               |  |  Codex)     |  | summarize         |     |
                               |  +------+------+  +-------------------+     |
                               +--------|-----------------------------------+
                                        |
                                        v
                               +-------------------+
                               | Execution backend |
                               | (Claude Code /   |
                               |  Codex process)  |
                               +-------------------+
```

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

The codebase is organized around these hard boundaries. Data and control
flow respect these layers; business logic does not skip across them.

```
  +----------------+  +----------------+  +----------------+  +----------------+
  | 1. Transport    |  | 2. Work queue  |  | 3. Session     |  | 4. Execution   |
  |    boundary     |  |    boundary    |  |    boundary    |  |    context     |
  | Normalize       |->| Journal, claim,|  | Durable        |  | One resolved   |
  | inbound types   |  | workflow       |  | chat-scoped    |  | context/request|
  +----------------+  +----------------+  +----------------+  +----------------+
  +----------------+  +----------------+  +----------------+  +----------------+
  | 5. Request flow |  | 6. Provider    |  | 7. Capability  |  | 8. Rendering   |
  |    boundary     |  |    boundary    |  |    boundary    |  |    boundary    |
  | Validation,     |  | Protocol,      |  | Skills, store,|  | Progress,      |
  | credentials,    |  | run/preflight  |  | registry       |  | format, raw    |
  | pending         |  | ProgressEvent  |  |                |  |                |
  +----------------+  +----------------+  +----------------+  +----------------+
```

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
- serialized inbound payload shapes are part of the runtime cutover contract
  and must remain stable across the current SQLite runtime and the later
  Postgres cutover; any optional import tool added later will depend on the
  same shape stability

### 2. Work-queue boundary

All inbound updates are journaled and serialized through a durable work queue
before processing. This replaces in-memory-only duplicate-delivery handling
and per-chat locking as the primary transport authority.

Primary modules:

- `app/work_queue.py` — journal, claiming, compare-and-update, recovery adapter
- `app/worker.py` — async loop that drains unclaimed items
- `app/workflows/transport_recovery.py` — workflow graph and transition legality (library)
- `app/workflows/results.py` — `TransitionResult`, `TransportDisposition`, domain exceptions

Current implementation storage: `transport.db` (separate from `sessions.db`
— different lifecycle and retention). After migration, equivalent runtime
authority moves to Postgres.

Tables:

- `updates` — every received `update_id`, with payload and state
- `work_items` — processable units derived from updates (state column matches workflow states)

**Transport workflow (library-backed)**

Transition legality is owned by `TransportRecoveryMachine` (python-statemachine).
The repository owns: SQL, idempotency, compare-and-update, and the
repository-level outcome `already_handled` (row missing or no longer in
source state after a failed update). The machine is pure: no SQL or I/O
inside validators or actions. The adapter `run_transport_event(model, event_name, **kwargs)`
runs the machine, catches `TransitionNotAllowed` and domain exceptions
(`OtherClaimedForChat`, `BlockedReplay`, `NotStaleClaim`), and returns
`TransitionResult`. Narrow APIs: `discard_recovery(item_id)` for user
discard; replay and supersede are separate operations.

Work-item state machine (ASCII):

```
                    +------------------+
                    |                  |
                    v                  |
  +------+  claim_inline/claim_worker  +--------+  complete   +------+
  |queued| -------------------------->|claimed | ----------> | done |
  +------+                             +--------+     fail    +------+
       ^                                    |    ----------> +------+
       |                                    |                 |failed|
       | recover_stale_claim                 | move_to_       +------+
       | (guard: is_stale)                   | pending_recovery
       |                                    v
       |                             +------------------+
       |                             | pending_recovery |
       |                             +------------------+
       |                                    |
       |         reclaim_for_replay          |  discard_recovery
       |         (guard: !other_claimed)     |  supersede_recovery
       +------------------------------------+  ----------> done
```

Events (machine methods): `claim_inline`, `claim_worker`, `complete`, `fail`,
`move_to_pending_recovery`, `recover_stale_claim`, `reclaim_for_replay`,
`discard_recovery`, `supersede_recovery`. Guards: per-chat single-claimed
(no claim/reclaim if another item for same chat is claimed); same-worker
re-claim is allowed (disposition `already_claimed_by_worker`); recover only
when repository sets `is_stale=True`.

Control-flow exceptions:

- `LeaveClaimed` — process shutting down; item stays claimed for recovery
  on next boot
- `PendingRecovery` — item needs user decision (replay/discard); worker
  skips completion
- `ReclaimBlocked` — replay attempted but another item for the same chat
  is already claimed

Contract:

- duplicate `update_id` delivery is `transport idempotency` (journaled, not
  reprocessed)
- per-chat ordering is enforced durably via atomic claiming
- inline handler path claims synchronously; worker loop drains anything
  left unclaimed (crash recovery, enqueue-without-claim)
- `claim_next_any()` uses `BEGIN IMMEDIATE` for atomic claiming across
  concurrent tasks
- `content dedup` is not part of this boundary; if added later it sits above
  the durable queue as explicit user-visible policy
- the queue remains application-owned through the Postgres migration; generic
  broker adoption is intentionally out of scope for the core request path
- multiple polling processes for the same token are detected and warned
  about, not supported

**Transport invariants (runtime contract)**

These are the authoritative runtime invariants. They are enforced by DB
checks in the current schema and by a single shared row validator in the
repository. Invalid state is never normalized into a benign outcome.

- `work_items.state` must be one of: `queued`, `claimed`, `pending_recovery`, `done`, `failed`.
- If `state == "claimed"`, then `worker_id` must be present.
- If `state == "claimed"`, then `claimed_at` must be present.
- At most one `claimed` row may exist per chat.
- Corruption is surfaced (e.g. `TransportStateCorruption`), not normalized to `already_handled`.
- Replay/discard must never lie about ownership or terminal outcome.
- The machine owns legal transitions; the repository owns races, idempotency, and `already_handled`.
- `completed_at` is set only when a work item reaches a terminal state (`done` or `failed`); it is not set on `move_to_pending_recovery`.

**Transport schema (versioned, migration deferred)**

- `transport.db` has a versioned schema; the current build expects the current schema/layout. Unsupported schema/layout fails fast with a neutral error. Migration/upgrade path is deferred to the Postgres/runtime phases.

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

**Project and settings UX contract**

Project binding and session settings are part of the same durable chat-scoped
session contract. The current authoritative fields are:

- `SessionState.project_id`
- `SessionState.model_profile`
- `SessionState.file_policy`
- `SessionState.compact_mode`

`ProjectBinding` (in `app/session_state.py`) carries per-project inherited
defaults: `file_policy` and `model_profile`. These are parsed from
`BOT_PROJECTS` using `|`-separated optional fields:
`name:/path[|file_policy[|model_profile]]`.

Resolution order (applied in `resolve_execution_context`):

- **file_policy:** session explicit > project default > "" (edit)
- **model_profile:** session explicit > project default > config default > config.model

`/policy inherit` and `/model inherit` clear session-explicit overrides,
returning to project or global defaults. The same semantics are available via
`setting_policy:inherit` and `setting_model:inherit` callbacks.

Current mutating entry points live in `app/telegram_handlers.py`:

- command handlers:
  - `cmd_project`
  - `cmd_model` (including `inherit` subcommand)
  - `cmd_policy` (including `inherit` subcommand)
  - `cmd_compact`
- inline callback handler:
  - `handle_settings_callback` (handles `setting_model:inherit`, `setting_policy:inherit`)

Preferred inline-callback shape:

- Keep one settings callback namespace and one handler-owned mutation path.
- Extend the existing `setting_*` callback family for future discoverability
  work (for example project selection/clear) instead of introducing a second
  project-specific callback subsystem.

Contract:

- `/settings` is a discoverability surface over these existing
  fields and mutations, not a second configuration system.
- Commands and inline callbacks must converge on the same mutation semantics:
  acquire `_chat_lock(...)`, load `SessionState`, mutate the existing fields,
  apply reset/invalidation rules, and `_save(...)`.
- Project and settings UI must not bypass the typed session boundary or create
  raw-dict mutation paths.
- No additional workflow state machine belongs here. This surface is
  synchronous session mutation; the existing Phase 11 workflow families remain:
  transport/recovery and pending approval/retry.

Reset and invalidation rules:

- Changing `project_id` resets provider session state and clears pending
  approval/retry state.
- Changing `file_policy` resets provider session state and clears pending
  approval/retry state.
- Changing `model_profile` relies on the existing `ResolvedExecutionContext`
  and `context_hash` invalidation contract; no second invalidation mechanism is
  allowed.
- Changing `compact_mode` is a rendering preference and does not reset
  provider session state.

Trust/public contract:

- Public-mode restrictions for project and policy changes stay at the existing
  handler gates (`_public_guard(...)`) and model-resolution layer
  (`resolve_effective_model(...)` public profile restrictions).
- Settings discoverability must not introduce a second public/trusted policy
  tree in callbacks or markup code.

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
- `app/workflows/pending_request.py` — pending approval/retry workflow graph
  and transition legality (library)

Contract:

- `check_credential_satisfaction` receives the resolved active_skills list,
  not the raw session
- `classify_pending_validation()` is the authoritative classifier for pending
  freshness (`ok`, `expired`, `context_changed`)
- pending approval/retry transition legality is owned by
  `PendingRequestMachine`; handlers choose the event (`approve_execute`,
  `expire`, `invalidate_stale`, `reject`, `cancel`) and then persist or clear
  session state
- `validate_pending` remains the user-facing message layer built on the same
  classification rules, not a second source of truth
- pending validation reads trust_tier from the stored pending state so the
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
transport.py            Normalize InboundMessage / Command / Callback; serialize_inbound for queue
  |
  v
work_queue.py           Journal update_id, create work item; claim (uses workflow for transition)
  |
  +---> workflows/transport_recovery.py   TransportRecoveryMachine, run_transport_event (pure)
  |     workflows/results.py              TransitionResult, TransportDisposition, domain exceptions
  |
  +----(inline claim)-----+----(worker drain)----+
  |                        |                      |
  v                        v                      v
telegram_handlers.py    worker.py              worker_dispatch (same as inline)
skill_commands.py
  |
  +-----------------+-------------------+
  |                 |                   |
  v                 v                   v
request_flow.py   doctor.py         ratelimit.py
approvals.py
workflows/pending_request.py    PendingRequestMachine, run_pending_request_event (pure)
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

## Sequence and Data Flow Diagrams

### End-to-end: normal message (inline path)

```
  User          Telegram        transport    work_queue      handlers         request_flow    execution_context   provider
    |               |               |             |               |                   |                |              |
    |-- message --->|               |             |               |                   |                |              |
    |               |-- update ----->|             |               |                   |                |              |
    |               |               | normalize  |               |                   |                |              |
    |               |               | InboundMsg  |               |                   |                |              |
    |               |               |------------>| record_and_   |                   |                |              |
    |               |               |             | enqueue()     |                   |                |              |
    |               |               |             | (INSERT       |                   |                |              |
    |               |               |             |  updates +    |                   |                |              |
    |               |               |             |  work_items)  |                   |                |              |
    |               |               |             |<-------------|                   |                |              |
    |               |               |             |               | _chat_lock()      |                |              |
    |               |               |             |<-------------- claim_for_update()|                |              |
    |               |               |             | (run_transport_event + UPDATE)      |                |              |
    |               |               |             |-------------->|                   |                |              |
    |               |               |             |               | load session      |                |              |
    |               |               |             |               | resolve_execution_context()        |              |
    |               |               |             |               |----------------------------------->|              |
    |               |               |             |               |                   | check_credential|              |
    |               |               |             |               |                   | validate_pending|              |
    |               |               |             |               |                   |<---------------|              |
    |               |               |             |               | execute_request() |                |              |
    |               |               |             |               |----------------------------------->| run()        |
    |               |               |             |               |                   |                |------------->|
    |               |               |             |               |                   |                | ProgressEvent|
    |               |               |             |               |<-----------------------------------| render()     |
    |               |               |             | complete_work_item()              |                |              |
    |               |<-------------- reply_text (and/or progress edits) --------------|                |              |
```

### Inline vs worker: two claiming paths

```
  INLINE PATH (handler holds lock, claims this update)
  -----------------
  handle_message / handle_command
       |
       v
  record_and_enqueue(worker_id=boot_id)  -->  item created as 'claimed' when allowed
       |
       v
  _chat_lock() --> claim_for_update(chat_id, update_id, worker_id)
       |
       v
  execute_request / worker_dispatch(kind, event, item)

  WORKER PATH (drains queue; no update_id yet)
  -----------------
  worker_loop()
       |
       v
  claim_next_any(worker_id)  -->  SELECT queued + NOT EXISTS claimed for chat, then
                                  run_transport_event(claim_worker) + UPDATE
       |
       v
  worker_dispatch(kind, event, item)  -->  same dispatch as inline (request_flow, provider)
       |
       v
  complete_work_item() or LeaveClaimed / PendingRecovery
```

### Recovery: pending_recovery and replay/discard/supersede

```
  Item in 'claimed'  -->  (interrupt / crash notice)  -->  mark_pending_recovery()
       |
       v
  pending_recovery  -->  User sees [Replay] [Discard]
       |
       +-- reclaim_for_replay(item_id, worker_id)  -->  run_transport_event(reclaim_for_replay)
       |        (guard: no other item for chat claimed)       |
       |        success: state=claimed; dispatch again        v
       |        blocked: ReclaimBlocked                        claimed
       |
       +-- discard_recovery(item_id)  -->  run_transport_event(discard_recovery)  -->  done
       |
       +-- supersede_pending_recovery(chat_id)  -->  (fresh message path)
                run_transport_event(supersede_recovery) per item  -->  done
```

### Crash recovery: stale claims

```
  Startup
     |
     v
  recover_stale_claims(current_worker_id, max_age_seconds)
     |
     v
  For each work_items WHERE state='claimed':
     compute is_stale (worker_id != current_worker OR claimed_at too old)
     if is_stale:
        run_transport_event(model, "recover_stale_claim")  -->  allowed
        UPDATE work_items SET state='queued', worker_id=NULL, claimed_at=NULL
     |
     v
  Worker loop (and inline path) can claim requeued items again.
```

### Data flow: where data lives

```
  +------------------+     +------------------+     +------------------+
  |   transport.db   |     |   sessions.db    |     |   Filesystem     |
  +------------------+     +------------------+     +------------------+
  | updates          |     | session rows     |     | uploads/{chat_id}|
  |  update_id PK    |     |  chat_id PK      |     | raw/{chat_id}    |
  |  chat_id,payload |     |  provider, JSON  |     | credentials (enc)|
  | work_items       |     |  has_pending,    |     | store: objects/  |
  |  id, state,      |     |  project_id, etc |     |   refs/, custom/  |
  |  worker_id,      |     +------------------+     +------------------+
  |  claimed_at,     |
  |  completed_at   |
  +------------------+

  Normalized inbound (JSON) is stored in updates.payload and work_items
  (kind/payload or equivalent). Session state is typed in memory
  (SessionState) and persisted as JSON in sessions.db. Execution
  context is resolved per request from session + config and never
  stored raw.
```

### Storage layout (shipped implementation)

```
  data_dir/
  ├── transport.db          # WAL; updates + work_items; separate lifecycle
  ├── sessions.db           # WAL; chat session state, schema version
  ├── uploads/
  │   └── {chat_id}/        # Inbound files per chat
  ├── raw/
  │   └── {chat_id}/        # Ring buffer for /raw and expand/collapse
  └── (store root)/
      ├── objects/         # Content-addressed skill objects
      ├── refs/            # Refs pointing to objects
      └── custom/          # User-override skills
```

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

### Transport workflow types

**TransportWorkflowModel** (mutable): Built from a work_items row plus guard
inputs (worker_id, requesting_worker_id, has_other_claimed_for_chat, is_stale).
The machine reads/writes `state`; validators/conditions use the guard fields;
actions set `disposition`. No SQL or I/O in model methods.

**TransitionResult**: `allowed`, `new_state`, `disposition`, `reason`. Returned
by `run_transport_event()`. Repository uses it to decide whether to commit
and what to return.

**TransportDisposition**: Outcome classification (ok, already_claimed_by_worker,
other_claimed_for_chat, blocked_replay, discarded, replayed, superseded,
stale_recovered, done, failed, invalid_transition, guard_failed, already_handled).
`already_handled` is repository-only (row missing or state changed by another
actor); the machine never returns it.

**Domain exceptions** (raised by machine validators, mapped by adapter to
TransitionResult): `OtherClaimedForChat`, `BlockedReplay`, `NotStaleClaim`.

### Pending-request workflow types

**PendingRequestWorkflowModel** (mutable): Built from stored pending state and a
validation classification result (`ok`, `expired`, `context_changed`). The
machine reads and writes `state`; actions set the resulting disposition. No SQL
or I/O in model methods.

**PendingRequestTransitionResult**: `allowed`, `new_state`, `disposition`,
`reason`. Returned by `run_pending_request_event()`. Handlers and request flow
use it to decide whether to execute, clear pending state, or surface a user
message.

**PendingRequestDisposition**: `ok`, `executed`, `rejected`, `expired`,
`invalidated`, `cancelled`, `invalid_transition`, `guard_failed`.

---

## State and Storage Model

### Durable storage

The shipped implementation uses two SQLite databases with different
lifecycles. After migration, equivalent runtime authority moves to Postgres
for session state and the core request queue while preserving the same typed
session, transport-payload, and execution-context contracts. Phase 11 already
completed the workflow-owner extraction so the Postgres runtime does not
inherit open-coded transition logic.

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

```
  normalize → authorize → journal+claim → session → resolve context → credentials
       → provider context → invoke provider → persist session → format/send
       → save raw → deliver artifacts
```

Steps in order:

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

```
  User sends message (approval_mode=on)
       |
       v
  resolve_execution_context → build preflight context
       |
       v
  provider.run_preflight() (read-only) → build_preflight_prompt()
       |
       v
  store PendingApproval (trust_tier, context_hash, prompt, etc.)
       |
       v
  render plan + [Approve] [Reject] buttons
       |
  User clicks Approve → classify_pending_validation() → PendingRequestMachine
       |                  |
       |                  +-- executed    → execute_request
       |                  +-- expired     → clear pending, show expiry message
       |                  +-- invalidated → clear pending, show stale-context message
       |
  User clicks Reject  → PendingRequestMachine.reject → clear pending, reply
```

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
- duplicate `update_id` delivery is `transport idempotency` (journaled, not
  reprocessed)
- per-chat ordering is enforced by atomic claiming
- bursty same-chat traffic gets visible acknowledgment; nothing silently
  dropped
- crash recovery: `recover_stale_claims()` requeues items left in `claimed`
  state by a dead worker
- pending_recovery items require explicit user action (replay or discard)
- `content dedup` is not part of this contract; if added later it is optional
  behavior layered above durable delivery

Scaling path now has two explicit tiers:

- **Local Runtime**: single-machine authority, simpler deployment, SQLite as
  the planned default backend, and no shared queue-authority requirement.
- **Shared Runtime**: later webhook ingress plus shared Postgres queue
  authority plus worker loop as primary processing path.

The current shipped implementation sits between those tiers historically:
Postgres-only runtime from Phase 12, with future roadmap work restoring Local
Runtime as the primary deployment mode while keeping Shared Runtime as the
advanced scale path.

### Workflow ownership (Phase 11 shipped shape)

The Phase 11 workflow extraction is now in place for both workflow families:

- `TransportRecoveryMachine` in `app/workflows/transport_recovery.py`
- `PendingRequestMachine` in `app/workflows/pending_request.py`

Ownership split:

- library-backed workflow modules own transition legality, guards, and
  disposition classification
- repository/session code owns persistence, compare-and-update, and
  repository-only outcomes such as `already_handled`
- handlers and request flow orchestrate user-visible outcomes but do not define
  transition legality

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

### Four-layer model (current)

1. Pure or owner suites
   - workflow machines, execution context, request-flow rules, providers,
     progress, formatting, and other backend-neutral contracts
   - no Postgres required
   - no app container required
2. In-process integration
   - real handlers, real request flow, real repositories or stores, fake
     Telegram, fake providers, and real local persistence
   - SQLite still appears here for fast owner and handler coverage that uses
     `fresh_data_dir`
   - Postgres-backed persistence and queue integration now has its own suites
3. Postgres bootstrap and repository integration
   - `test_db_postgres.py`, `test_storage_pg.py`, and `test_work_queue_pg.py`
   - real Postgres, real schema bootstrap/update/doctor, real connection pool
   - focused on runtime storage, bootstrap/update rules, and schema validation
4. E2E
   - Compose-based smoke layer in `tests/e2e/test_compose_flows.py`
   - bootstrap, doctor, and startup validation of the tooling/runtime contract
   - bot-container tests use the real provider-enabled image when built (and
     prove provider + execution path where possible), or the stub image for
     test/dev-only smoke

### Current Postgres test harness

The Postgres integration harness is intentionally separate from app runtime
configuration.

- Docker is required for Postgres integration suites.
- The harness starts a dedicated **test-only** Postgres container per
  pytest-xdist worker.
- Each worker gets its own database inside that container.
- Schema is applied once per worker DB.
- Runtime tables are truncated between tests.
- The harness never uses `BOT_DATABASE_URL`, dev, staging, or production
  databases for truncation or schema mutation.
- The current implementation uses one dedicated container per worker, not one
  shared Postgres service for all workers.

### Owner suites and cross-cutting tests

The owner-suite model from Phase 10 still stands:

- one primary owner suite per contract
- `test_invariants.py` only for genuinely cross-cutting rules
- overflow and edge-case suites should be folded back into owner suites rather
  than kept as permanent parallel test taxonomies

Current owner families:

- request and approval contracts:
  `test_request_flow.py`, `test_pending_request_workflow_machine.py`,
  `test_handlers_approval.py`
- handler surfaces:
  `test_handlers.py`, `test_handlers_*`
- transport and recovery:
  `test_transport.py`, `test_work_queue.py`, `test_work_queue_pg.py`,
  `test_workitem_integration.py`, `test_transport_workflow_machine.py`
- storage and store:
  `test_storage.py`, `test_storage_pg.py`, `test_store.py`,
  `test_store_e2e.py`, `test_registry.py`
- provider and rendering contracts:
  `test_claude_provider.py`, `test_codex_provider.py`, `test_progress.py`,
  `test_formatting.py`, `test_summarize.py`
- configuration and setup:
  `test_config.py`, `tests/test_setup.sh`
- **operator shell scripts** (provider_login, provider_status, provider_logout,
  container_provider_login): `tests/test_docker_ops.sh` — fast shell contract
  tests with mocked `docker`, `python`, `claude`, and `codex`; pins argv, env
  propagation, and doctor failure output. Compose/E2E covers the heavier
  runtime and bootstrap path.

### SQLite-era tests and the Local Runtime direction

- Today, SQLite remains in the codebase for fast in-process tests and some
  legacy session/store coverage.
- The shipped runtime backend today is Postgres; persistence and integration
  confidence currently comes from the Postgres-backed suites.
- The roadmap direction after Phase 12 is to make SQLite relevant again as the
  default backend for **Local Runtime** under backend-neutral storage/runtime
  contracts.
- `test_sqlite_integration.py` is historical in the current shipped state, but
  Local Runtime work is expected to replace historical/legacy SQLite coverage
  with deliberate Local Runtime contract coverage.
- App-container testing still belongs only in the small E2E layer, not in the
  normal integration loop.

---

## Deployment and dependencies

All runtime dependencies are declared in **`requirements.txt`** (including
`python-telegram-bot`, `python-statemachine`, `cryptography`, etc.). The bot
must run with a Python environment that has those packages installed.

- **New installs:** `./setup.sh` calls `./scripts/bootstrap.sh`, which creates
  `.venv` and runs `pip install -r requirements.txt`. The app is then run as
  `.venv/bin/python -m app.main <instance>` (via `scripts/run.sh` or the
  systemd service).
- **After git pull (resumed / updated deployments):** Run
  `./scripts/bootstrap.sh` to refresh the venv from `requirements.txt`, then
  restart the bot. If this is skipped and the repo added a new dependency, the
  bot can fail at startup with `ModuleNotFoundError`.
- **Bootstrap script:** `scripts/bootstrap.sh` installs from `requirements.txt`
  every time it runs (creating or updating the venv), then runs a quick import
  check so missing dependencies fail immediately instead of at runtime.
- **Phase 12 runtime (shipped today):** Postgres is the only supported runtime
  backend in the current code. The app requires `BOT_DATABASE_URL` and
  validates schema at startup. Lifecycle splits into: infrastructure
  provisioning, DB bootstrap/update, and app runtime. Explicit repo-owned DB
  workflows (`scripts/db_bootstrap.sh`, `scripts/db_update.sh`,
  `scripts/db_doctor.sh`) prepare and verify the database before the bot
  starts.
- **Roadmap direction after Phase 12:** introduce two explicit deployment
  capability tiers:
  1. **Local Runtime** — default host and Docker deployment mode, SQLite-backed
     by default, single-machine authority, product-first
  2. **Shared Runtime** — later advanced mode with Postgres queue authority,
     webhook persist-first ingress, and multi-process workers
- **Environment identity:** Each running bot environment has its own database,
  config, Telegram token, and app instance identity. Side-by-side dev/staging
  environments use separate databases, regardless of whether the environment is
  running in Local Runtime or Shared Runtime mode.
- **Responsibilities are explicit:**
  1. infrastructure provides the runtime substrate for the selected mode
  2. repo-owned DB/runtime commands apply schema and validate compatibility
  3. the app validates and runs; it does not create the DB, role, or schema at startup
- **Primary operational model (roadmap direction):** Dockerized bot is still
  the primary operator path, but the backend/runtime contract now splits into:
  - Local Runtime as the default path
  - Shared Runtime as the later advanced path
- **Current Compose/tooling shape:** `scripts/dev_up.sh` brings Postgres up and
  runs bootstrap/update + doctor with no bot runtime config. That is current
  shipped behavior, not the final Local Runtime target state.
- **Supported bot image:** The supported Docker path uses a **real provider-enabled
  image** (includes the chosen Claude or Codex CLI). Build it with
  `./scripts/build_bot_image.sh`; the script selects the image target from
  `BOT_PROVIDER` so operators don’t choose Docker targets manually. Built from
  `Dockerfile.bot` (shared base + provider-specific stage). A **stub-provider
  image** (`Dockerfile.runnable`) exists only for **test/dev smoke** (e.g. E2E
  when the real CLI is unavailable) and is not the supported runtime.
- **Provider authentication contract (current direction):** Docker-first
  operation keeps the real provider CLI inside the image, but **auth state is
  not baked into the image**. The product direction is:
  1. a guided repo-owned provider-login step runs **inside the same bot image**
  2. login state is persisted in a dedicated **bot-home Docker volume**
  3. the runtime bot service mounts that same volume
  4. startup and `/doctor` validate not only binary presence but provider
     runtime/auth health before the bot is treated as ready
  This keeps the product Docker-first while preserving the subscription-style
  CLI login model for Claude Code and Codex. Advanced non-interactive modes
  such as API-key, Bedrock, or Vertex auth remain possible, but they are not
  the primary product-facing contract.
- **Provider-login ownership:** The intended supported onboarding flow is one
  uniform repo-owned command (for example `scripts/provider_login.sh`) that
  reads `BOT_PROVIDER`, launches the provider-specific login flow in-container,
  then verifies provider health using the same image + volume pair that the
  runtime bot will use. Operators should not need to know provider-specific
  credential file paths or Docker internals.
- **Bot-home volume and entrypoint:** The bot container uses a persistent
  `bot-home` volume mounted at `/home/bot`. The image runs an entrypoint that
  chowns `/home/bot` to the bot user (uid 1000) then execs as that user, so
  provider auth and data persist across runs regardless of volume creation
  order. Login/setup and runtime use the same image and volume.
- **Host-run bot:** Still supported as a secondary fallback/debug path in the
  shipped code. The roadmap direction is for both Docker and host to support
  Local Runtime directly, with the same product behavior above the storage
  boundary.
- **Later environments:** staging and production may choose:
  - Local Runtime for simpler single-machine deployments
  - Shared Runtime for more operationally demanding deployments
  while keeping explicit bootstrap/update/doctor contracts for the selected
  mode.

See [README.md](../README.md) for Get Started and "After updating (git pull)".

---

## Interfaces That Must Stay Stable

The following are internal contracts that should only change deliberately:

- `SessionState`
- `PendingApproval` / `PendingRetry` (including `trust_tier` field)
- `ResolvedExecutionContext`
- `PreflightContext` / `RunContext`
- `Provider` protocol and `RunResult`
- `ProgressEvent` family and `render()` contract
- serialized inbound payload JSON shape used by the durable work queue
- `check_credential_satisfaction` signature (resolved active_skills)
- `validate_pending` signature (trust_tier from stored pending)
- work-item state machine (queued/claimed/done/failed/pending_recovery) and
  `TransportRecoveryMachine` events/guards; `run_transport_event()` adapter
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
