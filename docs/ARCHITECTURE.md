# Architecture

This document describes the bot in terms of contracts, runtime boundaries, and
core components. It is not a feature changelog. Current implementation status
lives in [STATUS-commercial-polish.md](STATUS-commercial-polish.md).

For end-user usage, start with [README.md](../README.md).

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
- transport delivery guarantees for burst traffic and duplicate delivery
- Telegram-safe rendering
- progressive disclosure for long responses
- operator visibility and health reporting

---

## Runtime Boundaries

The codebase is organized around a few hard boundaries.

### 1. Transport boundary

Input arrives as Telegram updates and is normalized into inbound transport
types before business logic runs.

Primary module:

- `app/transport.py`

Contract:

- transport normalization is responsible for extracting user, chat, command,
  callback, message text, and attachments
- business logic should not depend on raw Telegram payload structure when a
  normalized type already exists
- transport delivery is responsible for update ownership and delivery
  semantics:
  - polling is single-owner by design
  - duplicate Telegram delivery (`update_id`) must be safe
  - bursty same-chat traffic must receive visible acknowledgment
  - no update should be silently lost because a second request arrived quickly

### 2. Session boundary

Session state is durable and chat-scoped, but runtime logic uses typed session
objects rather than raw storage dicts.

Primary modules:

- `app/session_state.py`
- `app/storage.py`

Contract:

- storage persists session data
- runtime orchestration operates on `SessionState`
- storage may serialize as dict/JSON internally, but handler and request logic
  should not mutate raw dict session state
- user-selected runtime controls such as project binding, file policy,
  compact-mode override, and model-profile override belong here
- authorization policy does not belong here; trust tier is resolved per
  request and only persisted if the product needs it for visibility or
  delivery semantics

### 3. Execution-context boundary

There is one authoritative resolved execution context per request.

Primary module:

- `app/execution_context.py`

Contract:

- all context-sensitive behavior must derive from the same resolved object
- context hash is computed in one place only
- approval validity, retry validity, provider thread invalidation, and
  `/session` must all agree on the same execution identity
- public/open execution-scope restrictions must resolve here, not only in
  command handlers
- effective model selection must resolve here, not inside provider-specific
  command builders

### 4. Request-flow boundary

Request orchestration is pure business logic and should not depend on Telegram
transport details.

Primary module:

- `app/request_flow.py`

Contract:

- request validation, credential satisfaction, pending validation, and denial
  handling belong here
- handlers decide how to render outputs and buttons, not how the business
  rules work

### 5. Provider boundary

Providers implement a shared protocol and receive only provider-facing
contexts.

Primary modules:

- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`

Contract:

- provider implementations do not resolve session or project state themselves
- provider contexts are already resolved before provider invocation
- provider health checks are split into cheap local checks and runtime probes

### 6. Capability boundary

Skills, credentials, provider config fragments, and the managed store are a
capability layer on top of raw provider execution.

Primary modules:

- `app/skills.py`
- `app/store.py`
- `app/registry.py`
- `app/skill_commands.py`

Contract:

- skill resolution is deterministic
- managed skills are immutable artifacts behind refs
- credentials are per-user and loaded only at execution time

### 7. Rendering boundary

The bot owns adaptation from model output to Telegram-safe output.

Primary modules:

- `app/formatting.py`
- `app/summarize.py`

Contract:

- output shown to users must be readable in Telegram
- formatting correctness is part of runtime correctness
- compact/full response presentation is a rendering concern
- long-response progressive disclosure (expandable blockquote, expand/collapse
  buttons) should derive from one stored response source of truth

---

## Component Map

```
Telegram transport
  transport.py
       |
       v
Telegram handlers
  telegram_handlers.py
  skill_commands.py
       |
       +-------------------+
       |                   |
       v                   v
request_flow.py      doctor.py / ratelimit.py
       |
       v
execution_context.py
       |
       +-------------------+
       |                   |
       v                   v
skills.py             session_state.py / storage.py
store.py / registry.py
       |
       v
providers/base.py
providers/claude.py
providers/codex.py
```

This is the intended ownership model:

- handlers own routing and Telegram I/O
- request flow owns business rules
- execution context owns resolved runtime identity
- storage owns persistence
- providers own subprocess invocation
- skills/store/registry own capabilities
- formatting/summarize own output adaptation

---

## Core Data Contracts

### SessionState

`SessionState` is the runtime representation of a chat session.

It owns:

- provider identity and provider-local state
- approval mode
- active skills
- role
- project binding
- file policy
- model-profile override
- compact-mode override
- pending approval / retry state
- awaiting credential setup state

It does not own:

- user credentials
- authorization policy
- uploads
- skill contents
- provider binaries or processes

### PendingApproval / PendingRetry

Pending state must always carry:

- original requester identity
- original prompt and image list
- original context hash
- creation time

`PendingRetry` additionally carries denial records used to derive retry
permissions.

### ResolvedExecutionContext

This is the single authoritative execution identity used by runtime-sensitive
flows.

It carries these identity fields:

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

It also carries resolved execution controls used by provider invocation and
user-visible state, including:

- effective model profile
- effective model ID
- trust tier when that tier changes scope or user-visible controls
- effective allowed roots / extra dirs
- provider-facing working dir

It is the source of:

- context hash
- `/session` execution display
- provider-facing `working_dir`
- approval and retry freshness checks
- Codex thread invalidation

Codex thread reuse is valid only when:

- the current resolved execution identity still matches the stored context hash
- the current process boot ID still matches the stored boot ID

This means thread invalidation depends on both execution identity and process
continuity.

### Provider Contexts

Provider-facing contexts are intentionally narrower than session state.

`PreflightContext` contains:

- extra dirs
- system prompt
- capability summary
- working dir
- file policy
- effective model ID when preflight needs model-aware provider behavior

`RunContext` extends it with:

- provider config
- credential env
- permission-bypass flag
- effective model ID

Providers should not need to know about pending state, session timestamps, or
credential setup state.

---

## State and Storage Model

### Durable storage

The bot uses SQLite for session state and filesystem storage for everything
that is naturally file-oriented.

SQLite stores:

- chat session rows
- indexed session summaries (`has_pending`, `has_setup`, `project_id`,
  `file_policy`)
- any durable transport-delivery state the product decides to persist
  (`update_id` tracking, in-flight/queued request markers, or equivalent)

Filesystem stores:

- uploads per chat
- encrypted credentials per user
- managed skill objects and refs
- custom skills
- raw-response ring buffer
- staged Codex helper scripts

### Why this split exists

Session state benefits from:

- atomic updates
- indexed cross-session queries
- schema evolution

Files and artifacts benefit from:

- ordinary filesystem semantics
- direct provider access
- operator inspectability

### Response history and progressive disclosure

Long-response UX should reuse stored raw responses rather than inventing a
second rendered-state store.

Contract:

- the raw-response history is the source of truth for `/raw` and expand/collapse
  flows
- rendered compact/full variants are derived views, not separate durable state
- interactive expand/collapse should resolve a stable response reference back
  to stored raw content before rendering

---

## Skill and Capability Architecture

### Resolution model

Skill resolution is strictly ordered:

1. custom skill override
2. managed installed skill
3. built-in catalog skill

Any feature that displays skill details must use the resolved tier, not infer
it separately.

### Managed store model

Managed skills are stored as immutable content-addressed objects with logical
refs.

Properties:

- install/update are ref operations, not in-place directory mutation
- GC removes unreferenced objects conservatively
- schema guard protects incompatible managed-store versions
- custom skills remain editable and separate from managed artifacts

### Registry model

The registry is a source of managed artifacts, not a separate storage model.

Contract:

- registry artifact is downloaded to staging
- digest is verified before object creation
- only verified content becomes a managed object/ref

---

## Request Lifecycle Contracts

### Normal request

1. normalize inbound message
2. authorize user
3. serialize per-chat work
4. load and normalize session
5. resolve execution context
6. check credential satisfaction
7. build provider context
8. invoke provider
9. persist updated session state
10. format and send response

### Approval request

1. resolve execution context
2. build preflight context
3. run provider preflight
4. store `PendingApproval`
5. render plan + actions

Approval succeeds only if:

- pending state exists
- it is not expired
- its context hash still matches the current resolved context

### Retry request

Retry is the same validation pattern as approval, but includes retry-specific
permission scope derived from denials.

### Credential setup

Credential setup is conversational state, not a hidden side effect.

Contract:

- only the owning user may continue setup
- foreign setup blocks are visible and explain who is active
- only one credential-setup flow may be active in a shared chat at a time
- abandoned foreign setup blocks auto-expire after the timeout window
- captured credentials are deleted from chat after processing
- execution loads credentials for the request user, not the clicker or current
  chat broadly

### Transport delivery

Transport delivery is part of runtime correctness, not just deployment.

Contract:

- one active ingress owner per bot token
- duplicate Telegram delivery (`update_id`) is idempotent
- per-chat ordering is preserved
- if a second request arrives while one is in flight, the user receives a
  visible acknowledgment and the later request is not silently dropped
- multiple polling processes for the same token are an operator error to be
  detected and warned about, not a supported mode

Scaling path:

- single-process polling and single-process webhook share the same delivery
  semantics
- multi-process support means webhook + shared durable state +
  cross-process serialization, not multi-poller polling

---

## Access and Safety Model

The bot has several independent safety layers.

### User authorization

Only allowed users may interact with the bot.

When open mode is enabled, the product resolves users into trust tiers:

- `trusted`: users in the allowed-user set
- `public`: everyone else

### Admin authorization

A narrower set of users may manage store-backed skills and inspect broader
session state.

### Approval mode

Approval controls whether execution requires a preflight plan review first.

### File policy

File policy controls whether the session is inspect-only or may edit.

### Project binding

Project binding controls which working directory is in scope for the session.

### Allowed roots

Allowed filesystem roots derive from:

- effective project or default working dir
- configured extra dirs
- chat upload dir
- denial-derived retry dirs

These roots are part of the access contract; they should not drift from what
the provider actually receives.

### Public-trust enforcement

Public-mode enforcement has two layers that must stay distinct.

Execution-scope enforcement:

- forced inspect mode
- forced public working dir
- stripped operator extra dirs

These must resolve into `ResolvedExecutionContext`, so they automatically
affect provider context, context hash, approval freshness, and retry
freshness.

Command-availability gating:

- disabling skill management
- disabling project changes
- constraining `/send`
- restricting available model profiles or settings

These are handler-layer concerns because they control what the user may invoke,
not what execution resolves to.

---

## Provider Responsibilities

Provider implementations are responsible for:

- command construction
- subprocess execution
- progress streaming/parsing
- provider-local state updates
- health probes
- respecting `working_dir`, `extra_dirs`, `file_policy`, effective model, and
  provider config

They are not responsible for:

- session persistence
- approval decisions
- credential prompting
- skill discovery

### Claude-specific notes

- session-oriented backend
- inspect mode is best-effort via prompt/context restriction

### Codex-specific notes

- thread-oriented backend
- inspect mode is hard-enforced through sandbox selection
- thread invalidation depends on the authoritative context hash

---

## Health and Admin Components

### doctor.py

`doctor.py` is the shared health-orchestration layer for both:

- Telegram `/doctor`
- CLI doctor entry point

It owns:

- config validation
- provider health checks
- managed-store health checks
- stale session scanning
- per-chat skill validation when session/user context is provided
- public-mode diagnostics (rate limits, public root, trust-profile warnings)
- transport diagnostics such as polling-conflict detection

The rendering surface differs, but the health logic should not.

### Admin views

Admin views are reporting surfaces over current durable state.

Examples:

- `/admin sessions`
- session summaries
- stale pending and setup visibility

These should read normalized current state, not stale or guessed state.

---

## Testing Architecture

The test suite is organized around contracts, not only features.

### Handler and scenario tests

Exercise real user entry points through Telegram handlers.

### Invariant tests

Protect cross-cutting rules such as:

- context-hash stability and sensitivity
- approval and retry freshness
- inspect-mode enforcement
- public-trust enforcement in resolved context
- effective-model propagation and invalidation
- registry integrity
- async non-blocking guarantees
- provider-context propagation
- transport delivery guarantees (`update_id` idempotency, queued acknowledgment)

### Edge-case suites

Cover callback races, provider failures, formatting boundaries, and session
reset behavior.

### Setup / bootstrap tests

`test_setup.sh` protects the installation and bootstrap path separately from
the Python test suite.

---

## Interfaces That Must Stay Stable

The following are internal contracts that should only change deliberately:

- `SessionState`
- `ResolvedExecutionContext`
- `PreflightContext`
- `RunContext`
- `Provider` protocol
- transport delivery semantics (`update_id` handling, in-flight/queued rules)
- managed store layout (`objects/`, `refs/`, `custom/`)
- registry index format versioning

Changing these should trigger both code review and invariant test updates.

---

## Rebuild Guidance

If rebuilding the bot from scratch, preserve this order of responsibility:

1. normalize transport
2. apply transport-delivery rules (idempotency, queue/ack semantics)
3. load typed session state
4. resolve trust tier and authoritative execution context
5. apply business rules (`request_flow`)
6. build provider-facing context
7. invoke provider
8. persist session and any durable delivery state
9. render Telegram-safe output

That order is more important than the exact module names.
