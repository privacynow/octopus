# Commercial Product Plan

This document is the master roadmap for the finished product shape, the order
in which it should be built, and the historical decisions that still matter.
It is not the build log. Current implementation status lives in
[status.md](status.md). Runtime
boundaries, contracts, and storage authority live in
[ARCHITECTURE.md](ARCHITECTURE.md).

Use this document for four different questions:

- What is the product supposed to be?
- What has already shipped?
- What should be built next?
- Why do certain constraints and decisions exist?

---

## How To Use This Plan

- `plan.md`
  Product vision, ordered roadmap, sealed history, lessons learned, and
  decision record.
- `status.md`
  Phase-by-phase shipped/current status mirror and implementation log.
- `ARCHITECTURE.md`
  Source of truth for runtime boundaries, queue/storage authority, and
  contracts that code must preserve.
- Archived roles/skills docs
  Historical appendices only; the current product definition, shipped outcome,
  and roadmap are fully captured in this plan, the status mirror, the
  architecture doc, and the README.

The detailed historical steps inside the separate roles/skills design doc stay
as they are. This document summarizes that shipped work under Phases 3-5 and
keeps the domain docs as archived implementation references.

---

## Product Definition

Telegram Agent Bot is a Telegram-native interface to a local coding agent. The
product is not "a CLI wrapper in chat." The product is:

- a secure remote control surface for Claude Code or Codex
- a mobile-friendly conversation interface for real development work
- a capability system that layers skills, credentials, projects, and safety
  controls on top of raw model execution
- an operator-manageable service that can run for one user, a team, or a
  shared group chat

The bot should feel like one coherent product even when the provider changes.

---

## Product Contract

If the product is working correctly, these statements are true:

1. A user can ask for work from Telegram and get a useful answer without
   understanding the implementation details behind the bot.
2. The bot makes the execution context explicit: what role is active, which
   skills are active, which files are in scope, which project is bound, and
   whether the session is inspect-only or may edit files.
3. Approval and retry flows are safe, deterministic, and never operate on
   stale context silently.
4. Skills behave like capabilities, not hidden prompt fragments. Users can
   discover them, understand them, activate them, and recover from missing
   credentials cleanly.
5. Output is readable in Telegram on a phone. If the model emits something
   awkward for Telegram, the bot adapts it.
6. Operators can understand what the bot is doing, inspect health, and manage
   capability distribution without needing to read the code.

---

## Primary User Journeys

| Journey | Successful outcome |
|---------|--------------------|
| Ask for work | The user sends a normal message, optionally with files. The bot runs the provider against the correct execution context and returns a readable answer. |
| Review before execution | When approval mode is on, the bot shows a plan first. The user can approve, reject, or let it expire. If context changes, the request must not continue. |
| Add a capability | The user browses skills, inspects one, sees whether it is ready or needs setup, activates it, and is prompted for credentials only when needed. |
| Recover from mistakes | The user can cancel pending state, clear credentials, reset a session, switch project, switch policy, or remove a skill without getting trapped. |
| Operate a real bot instance | The operator can bootstrap a bot, run health checks, inspect sessions, manage skills, and update the bot without losing the product model. |

---

## Non-Goals

These are intentionally out of scope for the core product plan:

- full billing and quota systems before the runtime is stable
- Docker or Kubernetes control-plane design
- hosted SaaS architecture decisions
- general-purpose package-manager behavior outside the skill system

Note: multi-agent delegation is now an active product feature tracked under
Phase 20. It is no longer a non-goal.

Those may matter later, but they are not the core product definition.

---

## Design Principles

| Principle | Why it matters |
|-----------|----------------|
| User-first surface | The README and Telegram UX should speak to end users first. Internal module structure and operator detail belong in dedicated docs. |
| One authoritative runtime model | Execution identity must be resolved once and reused everywhere. Approval, retry, provider state invalidation, and `/session` should all describe the same truth. |
| Safety through explicit state | Approval mode, file policy, project binding, skill activation, and credential setup should all be visible and inspectable. Hidden state is where confusing bugs become safety bugs. |
| Capability layering | Raw provider execution is only one layer. The finished product also depends on skills, credentials, projects, file policy, output shaping, and admin tools. |
| Telegram-native output | Readable mobile output is a correctness property, not cosmetic polish. |
| Rebuildability | The plan should describe a shape that can be rebuilt from scratch, not a sequence of patches that happened to ship. |

---

## Product Capabilities

The product is complete when these capability areas are in place.

| Area | Complete means |
|------|----------------|
| A. Conversation and execution | Normalized inbound transport, per-chat session state, request execution, provider progress, file upload/download, and conversation reset/export. |
| B. Safety and control | Approval and retry flows, explicit inspect vs edit policy, per-chat project binding, stale-context invalidation, rate limiting, and health visibility. |
| C. Capability management | Skill discovery, activation/deactivation, credential prompting and clearing, skill info, and provider compatibility. |
| D. Runtime durability | Durable session storage, recoverable skill store, runtime diagnostics, session normalization, and webhook/polling parity. |
| E. Distribution and ecosystem | Managed immutable skill store, remote registry-backed discovery and installation, and provider-specific execution extensions. |
| F. Confidence and quality | Scenario tests, invariant tests, and edge-case coverage around callbacks, sessions, providers, formatting, and store integrity. |
| G. Public trust profile | Mixed-trust auth, restricted public execution scope, forced inspect-only file policy, isolated public working directory, disabled public skill management, and mandatory rate limiting in public mode. |
| H. User-perceived performance and model control | Stable user-facing model profiles, trust-aware model selection, inline-keyboard settings UX, compact default, expandable long responses, summary-first replies, and early visible progress. |

---

## Roadmap Rules

- The roadmap is one strict execution order, not priority buckets.
- Phases 1-15 are sealed as shipped history.
- Phase 20 is the active roadmap phase (Networked Multi-Agent Platform).
- Phases 16-19 remain on the roadmap but are deferred behind Phase 20.
- From Phase 13 onward, the roadmap is split by **capability tier**, not by
  database ideology:
  - **local/product track first**: backend-neutral product work plus a
    first-class Local Runtime mode
  - **shared-runtime track last**: Postgres queue authority, multi-process
    ingress, and durability confidence
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive
  messages. It is not part of the core transport contract.
- **Current shipped state:** Local Runtime is the supported deployment mode,
  with SQLite as the default backend and Postgres as a supported alternate
  backend under the same product contract.
- Shared Postgres queue authority is no longer the immediate universal next
  step; it is deferred to the end of the roadmap as an advanced
  **Shared Runtime** capability tier.

---

## Linear Phase Map

This is the authoritative phase sequence.

| Phase | Scope | State |
|------:|-------|-------|
| 1 | Core Telegram loop | Sealed / shipped |
| 2 | Safety, approvals, and rate limiting | Sealed / shipped |
| 3 | Roles and instruction-only skills | Sealed / shipped |
| 4 | Credentialed and provider-specific skills | Sealed / shipped |
| 5 | Skill store and capability distribution | Sealed / shipped |
| 6 | Output, compact mode, and progress UX | Sealed / shipped |
| 7 | Durable session state and execution context | Sealed / shipped |
| 8 | Public trust, model profiles, and settings UX | Sealed / shipped |
| 9 | Durable transport, transport idempotency, webhook mode, and restart recovery | Sealed / shipped |
| 10 | Structural hardening, invariants, and test ownership | Sealed / shipped |
| 11 | Workflow ownership extraction | Sealed / shipped |
| 12 | Postgres runtime cutover | Sealed / shipped |
| 13 | Storage backend abstraction and Local Runtime mode | Sealed / shipped |
| 14 | Product polish on local foundations | Sealed / shipped |
| 15 | Behavior extensions | In progress |
| 16 | Registry trust and governance | Remaining |
| 17 | Usage accounting, quotas, and billing | Remaining |
| 18 | Shared Runtime: Postgres queue authority in webhook mode | Remaining |
| 19 | Shared Runtime: multi-process scale and durability confidence | Remaining |

---

## Sealed Phases 1-14

Phases 1-14 are shipped and sealed. They stay here as historical reference.

| Phase | Historical source | What shipped | Lasting lesson |
|------:|-------------------|--------------|----------------|
| 1 | Former Phase A | Core Telegram loop: normalized transport, routing, provider execution, file flow, and foundational session commands. | Normalize transport first. Product logic should not depend on raw Telegram payload shape. |
| 2 | Former Phase B | Safety surface: approval/retry, stale-context rejection, `/cancel`, rate limiting, and `/doctor`. | Safety features fail when they are phrased as UX only instead of durable state and invalidation rules. |
| 3 | Archived roles/skills docs | Roles and instruction-only capabilities as visible, user-understandable product features. | Skills must behave like visible capabilities, not hidden prompt fragments. |
| 4 | Former Phase C plus archived roles/skills docs | Credentialed and provider-specific skills, guided setup, encrypted per-user credential storage. | Capability setup and credential capture need their own product flow; they cannot stay as ad hoc side effects. |
| 5 | Former Phases F and G | Managed skill store, immutable object/ref model, registry fetch/search/install, digest verification. | Capability distribution works best as immutable content plus refs, not mutable in-place installs. |
| 6 | Former Phase D plus former Phase III | Output shaping, compact mode, `/raw`, export, progressive disclosure, summary-first replies, and shared progress UX. | Rendering is part of correctness. Compact mode is a rendering concern, not a second conversation model. |
| 7 | Former Phase E | Typed session state, authoritative execution context, project binding, file policy, and context-hash invalidation. | Resolve execution identity once and reuse it everywhere. |
| 8 | Former Phase I plus former Phases IIa and IIb | Mixed trust, model profiles, and inline settings UX. | Public safety comes from resolved execution scope, not from approval mode or hidden handler checks alone. |
| 9 | Former Phase IV plus later recovery hardening | Durable transport, transport idempotency, webhook foundation, queued feedback, and explicit replay/discard recovery. | `transport idempotency` is core. Automatic replay is unsafe. `content dedup` is optional policy, not the transport contract. |
| 10 | Former Phase H plus later hardening/testing work | Invariants, owner suites, execution-context hardening, and test isolation. | Confidence comes from explicit ownership and invariant tests, not from ever-growing overflow suites. |
| 11 | Phase 11 (this plan) | Workflow ownership extraction: transport and pending_request state machines (python-statemachine), single claim and single insert paths, repository-owned CAS and idempotency, versioned transport schema (validate-only for existing DBs), impossible rejections fatal, chat integrity, strict replay/supersede/recover helpers. | Extract workflow ownership before database migration so the new backend does not inherit open-coded transition logic. Library owns graph and guards; repository owns SQL and already_handled. |
| 12 | Phase 12 (this plan) | Postgres runtime cutover: Postgres-backed session and transport stores shipped, `BOT_DATABASE_URL` required at startup, validate-only runtime startup, explicit DB bootstrap/update/doctor commands, Postgres integration suites, and Compose-based tooling/E2E layer. | Split runtime ownership cleanly: infrastructure provides the database, repo-owned commands bootstrap/update/doctor it, and the app validates then runs. |
| 13 | Phase 13 (this plan) | Storage backend abstraction and Local Runtime mode: SQLite became the default backend, Postgres stayed supported through the same storage and transport contracts, and startup/E2E/docs shifted to a SQLite-first local path. | Backend abstraction is valuable only when the product contract stays the same above the storage seam. |
| 14 | Phase 14 (this plan) | Product polish on local foundations: operator health clarity, dead-end command fixes, command-specific actionability, command/callback parity, and help/discoverability hardening. | Product polish matters most when it removes dead ends and makes the main path obvious. |

The archived roles/skills docs remain as historical appendices for now, but
their product-level content is already absorbed here under Phases 3-5.

---

## Historical Lessons And Decisions

This section keeps the important "why" from shipped work without turning the
plan into a build diary. Each item records a decision that should survive, why
it survived, and which failure pattern taught it.

### 1. Capability system

- Keep skills visible and user-comprehensible. The bot should explain what a
  skill does, where it came from, whether it is active, and whether it needs
  credentials.
- Keep instruction-only capabilities distinct from credentialed or
  provider-specific setup. Those are separate product problems and should stay
  modeled separately.
- Keep deterministic resolution order: custom override, then managed install,
  then built-in catalog.
- The mistake to avoid is letting capability behavior disappear into prompt
  assembly, undocumented precedence, or hidden provider-specific branches.

### 2. Trust, scope, and settings

- Approval mode is not a security boundary in public mode. Public safety comes
  from execution-scope enforcement.
- Trust should resolve per user (`trusted | public`), not as a global bot
  mode.
- Public restrictions belong in `resolve_execution_context()` first and in
  handler gating second. If this split collapses, message, approval, retry,
  and future worker paths drift apart.
- Model profiles should be stable user-facing tier names such as `fast`,
  `balanced`, and `best`. Users should not need raw provider model strings.
- Inline-keyboard settings should reuse the same session mutations as text
  commands rather than inventing a second state path.
- The failure pattern here is policy drift: one path enforces trust or model
  rules, another path forgets, and the bot becomes inconsistent.

### 3. Output and progress UX

- Compact mode is a rendering concern, not a second conversation model.
- The raw-response ring buffer is the single source of truth for `/raw` and
  expand/collapse regeneration.
- Shared progress wording should be provider-neutral at the user surface, but
  the event model must still preserve meaningful provider-specific detail.
- Rich Codex progress is the no-regression baseline for long-running
  interactivity. Shared progress should help Claude catch up, not flatten both
  providers down.
- Heartbeat or visible liveness must have explicit ownership. Invisible
  provider activity must not suppress user-visible liveness.
- The mistake to avoid is treating "shared UX" as "thin lowest-common-
  denominator UX."

### 4. Durable transport and recovery

- `transport idempotency` is the core duplicate-delivery guarantee.
  `content dedup` is optional policy layered on top.
- Session continuity and request replay are separate concepts. Preserving
  provider context across restart does not justify automatic request replay.
- `pending_recovery` needs explicit ownership and durable terminal outcomes
  such as `replayed`, `discarded`, and `superseded`.
- Replay and discard actions should target a stable durable recovery reference,
  not merely "the latest interrupted item."
- Blocked replay, already-handled recovery, and discarded or superseded
  recovery should classify differently rather than collapsing into one generic
  failure outcome.
- Polling remains single-owner. The scale path is webhook plus durable queue
  plus workers.
- The core request queue remains application-owned. Generic broker or
  workflow systems are not the default answer for Phases 11-14.
- The failure pattern to remember is split ownership between live handlers and
  workers. That is where fresh-command races, replay confusion, and bad
  terminal-state handling came from.

**Transport invariants (runtime contract)**

These are the authoritative runtime invariants for the durable work queue.
They are enforced by DB checks in the current schema and by a single shared
row validator in the repository. Invalid state is never normalized into a
benign outcome.

- `work_items.state` must be one of: `queued`, `claimed`, `pending_recovery`, `done`, `failed`.
- If `state == "claimed"`, then `worker_id` must be present.
- If `state == "claimed"`, then `claimed_at` must be present.
- At most one `claimed` row may exist per chat.
- Corruption is surfaced (e.g. `TransportStateCorruption`), not normalized to `already_handled`.
- Replay/discard must never lie about ownership or terminal outcome.
- The machine owns legal transitions; the repository owns races, idempotency, and `already_handled`.
- `completed_at` is terminal-only (`done` or `failed`); it is not an
  interruption or recovery timestamp.

**Transport schema (versioned across both supported backends)**

- SQLite `transport.db` has a versioned schema. The current build expects the current supported schema/layout and may apply the narrow in-place migrations explicitly owned by the SQLite transport implementation.
- Postgres runtime storage uses SQL migrations under `app/db/migrations/postgres/` and is bootstrapped/updated via the tooling flow.
- If an existing DB has an unsupported schema version or layout, the app fails fast with a neutral error (e.g. "Unsupported transport.db schema/layout for this build"). The app does not mutate existing DBs before validating them.
- Review priority: correctness and repository invariants first; migration breadth is secondary to preserving the transport-store contract and clean backend seams.

### 5. Workflow ownership and engineering discipline

- Workflow extraction is only justified when repeated durable-state bugs and
  review cost show that open-coded transitions are the bottleneck.
- If extraction happens, it should be narrow and contract-first: start with
  transport/recovery and approval/retry, not with a whole-app state-machine
  rewrite.
- Define workflow state machines before choosing any framework or library.
  States, transitions, owners, and durable commit points come first.
- Typed session models, explicit outcome ownership, and contract-shaped tests
  reduce a large class of silent stale-context and ownership bugs.
- Test ownership matters. Overflow suites and duplicated invariants reduce
  confidence because nobody clearly owns what a failure means.
- Raw provider fixtures are worth keeping. Synthetic event tests alone do not
  prove mapping fidelity.
- The mistake to avoid is architecture theater: a larger framework or fancier
  diagram is not evidence that ownership, invalidation, or recovery semantics
  actually improved.

### 6. Language and naming decisions

- Use `transport idempotency` for durable `update_id` journaling and work-item
  uniqueness.
- Use `content dedup` only for optional suppression of repeated identical
  messages.
- Use `public trust` or `trust tier` for authorization posture, and
  `execution context` for the resolved runtime shape that providers receive.
- Keep these names stable. Several earlier design discussions became confusing
  because one overloaded term carried multiple unrelated concerns.

### 7. Concrete failure patterns worth remembering

- Fresh live commands were once stealable by the worker path because handler-
  owned work items were created in a claimable state. Future queue changes
  must keep initial ownership explicit.
- Automatic replay after restart proved unsafe for contextual confirmations and
  any request with partial side effects. Recovery must stay user-intent-owned.
- Shared progress work is useful only if it preserves real provider semantics.
  Flattening progress detail makes the product feel less alive, not more
  consistent.
- Test overflow files and duplicated invariants created the illusion of
  coverage while hiding ownership. Confidence improved only after suites had
  explicit responsibility.

---

## Cross-Cutting Contracts

These are the rules future changes must preserve.

### Execution identity contract

There is one authoritative execution identity per request. It includes:

- role
- active skills
- skill digests
- provider config digest (skill YAML content, scoped to active provider)
- execution config digest (effective model resolved from session profile
  override or config default, subject to trust-tier restrictions; Codex
  sandbox/full-auto/dangerous/profile settings)
- base extra dirs
- project id
- effective working dir
- file policy
- provider name

This identity is the basis for:

- context hash
- approval validity
- retry validity
- Codex thread invalidation
- `/session` display

Codex thread invalidation has a second trigger independent of context hash:
bot restart (`boot_id` change) also clears stale threads, because the provider
process that owned the thread no longer exists.

### Workflow state-machine contract

The bot should define two authoritative workflow families:

- transport / claim / recovery
- approval / retry / replay

Both families should be contract-first, not framework-first.

Required properties:

- explicit states and allowed transitions
- one completion owner per terminal or recovery-needed outcome
- durable commit points for every state-changing transition
- stable recovery references for user-owned replay/discard flows
- outcome codes that distinguish:
  - blocked replay
  - already-handled recovery
  - discarded recovery
  - superseded interrupted work

Transport workflow state should be explicit:

- `queued`
- `claimed`
- `pending_recovery`
- `done`
- `failed`

Pending-request workflow state should be explicit:

- idle
- `pending_approval`
- `pending_retry`
- terminal outcomes such as executed, rejected, expired, stale, or cancelled

The plan commits to the workflow contracts first; implementation uses
python-statemachine narrowly (see Phase 11). Persistence remains in-app.

### Pending request contract

Pending approval and retry are one workflow family, not ad hoc records.

Pending approval and retry state must always carry:

- original requester identity
- original prompt and images
- original context hash
- creation timestamp

Validation must check:

- expiry
- context freshness
- ownership or authorization

Every terminal pending outcome must have a named owner.

### Skill resolution contract

Skill resolution is deterministic:

1. custom override
2. managed installed skill
3. built-in catalog skill

Any surface that shows source, compatibility, or body content must use the
resolved tier, not guess.

### Credential contract

Credentials are:

- stored per user
- never stored in chat session state
- captured conversationally
- deleted from the chat when captured
- loaded only for the requesting user during execution

In group chats, credential setup uses a single-slot model: only one user may
be in setup at a time. A second user's setup attempt is rejected with a
visible message identifying who is active. Setups auto-expire after 5 minutes
to prevent wedging a shared chat if the setup owner disappears.

### Output contract

The formatting layer is responsible for adapting model output to Telegram. If
raw model output is unreadable in Telegram, the bot still owns the problem.

The raw-response ring buffer remains the source of truth for `/raw` and
expand/collapse regeneration.

Normal user progress should:

- use provider-neutral wording
- preserve meaningful provider semantics rather than flattening them away
- hide provider names, thread ids, and session ids in normal user mode
- keep heartbeat/liveness ownership explicit

### Health contract

`/doctor` and CLI doctor should be two renderers over the same health
orchestration, not separate implementations.

### Transport delivery contract

- one active ingress owner per bot token (polling is single-owner)
- every inbound update receives a visible response or acknowledgment
- per-chat ordering is preserved; no concurrent writes out of order
- duplicate update delivery (same `update_id`) is `transport idempotency`
- the core request queue remains application-owned rather than delegated to a
  generic broker
- `content dedup` is not part of this contract; if it is ever added, it is
  optional product policy above durable delivery
- polling conflict is detected and warned, not silently tolerated

---

## Verification Strategy

The roadmap assumes three complementary test layers plus phase-specific
coverage for the remaining infrastructure work.

### 1. Scenario tests

End-to-end user workflows through handler entry points.

Examples:

- normal message flow
- approval flow
- skill activation and credential setup
- export and compact mode

### 2. Contract and invariant tests

Small high-value tests for cross-cutting rules.

Examples:

- inspect mode can never become writable for Codex
- changing execution identity invalidates stale approvals
- registry digest mismatch leaves no installed state
- configured extra dirs reach provider context
- public mode plus model switching does not allow profile escalation
- project plus file policy plus approval plus model change invalidates
  correctly
- shared progress preserves semantic-rich provider events while keeping one
  coherent user-facing vocabulary
- inline-claim vs worker-claim races preserve correct ownership
- failed recovery-notice delivery never becomes false `done`

### 3. Edge-case suites

Boundary conditions the happy path misses.

Examples:

- double-click callbacks
- provider timeout or empty response
- formatting edge cases
- session reset during pending state

### 4. Remaining-phase coverage

- Workflow extraction tests: allowed and forbidden transitions, terminal
  ownership, duplicate delivery idempotency, replay/discard races,
  blocked-replay vs already-handled classification, stable recovery
  references, and second interruption handling.
- Postgres cutover tests: schema bootstrap, DB bootstrap/update/doctor,
  startup validation, rollback safety, and backward-compatible payload
  deserialization. SQLite-to-Postgres import tests are optional follow-on work
  if an import tool is later added.
- Queue and worker tests: row-lock claiming, inline-claim vs worker-claim
  races, lease expiry, cross-process ordering, webhook enqueue-plus-worker
  dispatch, failed recovery-notice delivery classification, and recovery after
  crash.
- Product tests: `/project` inline keyboard, public-trust interactions,
  `content dedup` acknowledgment, and richer project or policy scope.
- Usage tests: authoritative metering, quota enforcement, replay-safe
  accounting, and billing-event integrity.

---

## Product Docs Split

The docs should have distinct jobs:

- `README.md`
  User-facing product entry point.
- `status.md`
  Build log and current implementation status.
- `plan.md`
  Product vision, roadmap, and durable lessons and decisions.
- `ARCHITECTURE.md`
  Contracts, components, and runtime model.

If a document starts turning into another document, split it rather than
blurring the audience.

---

## Detailed Phase Specifications

The remaining sections preserve the detailed specification for later-phase
work. Phase 11 and Phase 12 remain here because their contracts still shape
everything that follows. Phase 13 and Phase 14 are now shipped but stay here
as design reference. Phase 15 is the active phase. Phases 16-19 are still
future roadmap work.

Where a subsection says "before Phase 13" or similar, read it as archived
decision record from the point in time when that gate was active. Those
sections are kept because they explain why the current roadmap looks the way it
does, not because they are still live instructions.

### Phase 11 - Workflow Ownership Extraction (Sealed)

Phase 11 is sealed. The seal checklist is met; the following text remains as
historical reference for the workflow/repository contract that Phase 12 builds on.

Behavior-preserving refactor only.

- Extract two authoritative workflow owners first: transport/recovery and
  approval/retry.
- Define the workflow contracts explicitly before changing persistence:
  - transport state: `queued`, `claimed`, `pending_recovery`, `done`,
    `failed`
  - pending state: no pending work, `pending_approval`, `pending_retry`, and
    terminal outcomes such as executed, rejected, expired, stale, or cancelled
- Reuse existing normalized inbound payloads, typed session dataclasses, and
  resolved execution context.
- Introduce store interfaces around the current persistence seams so handlers
  and workers stop open-coding durable transitions.
- Add stable recovery references, explicit terminal-disposition ownership, and
  outcome codes that distinguish blocked replay, already-handled recovery,
  discard, and supersede.
- Keep the extraction narrow and contract-first.
- Do not turn the whole application into one giant state machine.

**Phase 11 workflow — corrected policy (hard gate for Phase 11 and pending_request extraction).**

- **Ownership:** The **library** owns the workflow graph, guards, validators, internal self-transitions, and final states. No second transition table, validator function, or event-name dispatch layer anywhere else. The **repository** owns SQL, idempotency, compare-and-update, and the repository-level outcome `already_handled`. Adapter types (`TransportWorkflowModel`, `TransportDisposition`, `TransitionResult`) are allowed only as machine input/callback host and repository-to-caller result types; they must not encode transition legality.
- **Library usage (2.x):** `strict_states=True` on the machine **class**. `rtc=True` and `allow_event_without_transition=False` are **instance** settings in 2.x — pass them when **instantiating** the machine, not as class attributes. Prefer direct machine methods (e.g. `sm.claim_inline()`) where possible. Any `run_transport_event(model, event_name)` must be a thin adapter around a real machine call; if it switches on event names or encodes outcomes itself, it is a second FSM and is not allowed.
- **Machine callbacks must stay pure/in-memory.** No SQL, Telegram, provider calls, or durable side effects inside machine actions or validators.
- **already_handled:** Stays repository-level only. After a compare-and-update returns `rowcount == 0`, **re-read the row** before classifying. Map to `already_handled` only when the row is **missing** or **no longer in the source state because another actor won**. Any other situation is an invariant/corruption problem and must be surfaced.
- **Initial row creation:** A direct insert into the true initial state (`queued`) is fine. Creating a row already in `claimed` is semantically a **transition**, not pure creation. That path must either run the machine from `queued` → `claimed` before persisting, or be wrapped in a very narrow helper explicitly defined as “create + immediate claim” that still derives the target state from the real machine contract.
- **Unknown DB state:** Must not collapse to a silent no-op. Treat as corruption/invariant failure and surface.
- **Tests follow the same ownership split:** Use the real `StateMachine` for workflow tests (allowed/forbidden transitions, guards). Repository tests own `already_handled`, compare-and-update races, and row-missing/rowcount-zero behavior. No test should mirror a dict-based transition table or a second FSM.

**Policy in one sentence:** Library owns graph, guards, validators, internal self-transitions, and final states; repository owns SQL, idempotency, compare-and-update, and `already_handled`; adapter types are allowed; any second transition table, validator function, or event-name dispatch layer is not allowed.

**Phase 11 simplification target.**

- `transport_recovery.py` owns states, events, guards, validators, and
  machine dispositions.
- `work_queue.py` owns row loading, full row validation, compare-and-update,
  reread-on-race, and repository-level outcomes.
- `telegram_handlers.py` and `worker.py` only orchestrate and surface
  user-safe or developer-safe failures.
- No helper should infer workflow truth from raw SQL state filters alone.
- No public helper should accept ambiguous target-state strings when an
  explicit operation exists.

**Core simplification rule:** every transport operation should follow one
path: load without pre-filtering away bad states, validate the full row
invariant set, run the real machine event if a transition is involved,
persist with compare-and-update, reread on `rowcount == 0`, then classify
race vs `already_handled` vs corruption.

**Phase 11 repository shape and cleanup work.**

- Public transport operations should converge on explicit verbs:
  `complete_work_item(item_id)`, `fail_work_item(item_id, error)`,
  `mark_pending_recovery(item_id)`, `discard_recovery(item_id)`,
  `reclaim_for_replay(item_id, worker_id)`,
  `claim_for_update(chat_id, update_id, worker_id)`,
  `claim_next(chat_id, worker_id)`, and `claim_next_any(worker_id)`.
- `get_pending_recovery_for_update(data_dir, chat_id, update_id)` and
  `get_latest_pending_recovery(data_dir, chat_id)` are the lookup APIs; call
  sites use the appropriate one by name (no wrapper).
- Use one shared row validator in the repository. It must enforce the full
  invariant set, not just the state enum: valid `state`, and for `claimed`
  rows, non-null `worker_id` and `claimed_at`.
- Keep shared private primitives for row loading, chat integrity checks,
  compare-and-update application, and CAS-miss classification. No business
  helper should open-code its own load-check-update flow.
- Direct scanners such as stale-claim recovery and pending-recovery
  supersession must validate every loaded row through the shared row
  validator or shared repository primitives before using it.
- Enqueue without claimant identity inserts `queued` directly. Creating a row
  already in `claimed` is only allowed for a narrow create-plus-immediate-
  claim path that still derives its target state from the real machine
  contract.
- In development, corruption in `claim_next_any()` is fail-fast. Do not
  silently skip, normalize, or spin forever on a corrupt chat.
- Boundary behavior stays asymmetric: handlers and recovery callbacks catch
  corruption, log loudly, and show a generic user-safe error; the worker
  treats corruption as a developer-visible invariant failure and stops.
- `completed_at` stays terminal-only. If interruption timing matters later,
  add a separate recovery or interruption timestamp rather than overloading
  `completed_at`.

**Phase 11 implementation: python-statemachine (narrow use).**

Library choice: [python-statemachine](https://pypi.org/project/python-statemachine/) (PyPI 2.6.0 as of 2026-03). Add to requirements as `python-statemachine>=2.6,<3`. Use for both this bot and multiagent bot, only for the two workflow families below.

**Constraint:** The library must not own persistence, queueing, or recovery truth. Postgres (or SQLite during cutover) row state remains authoritative. The machine defines and validates only: allowed states, allowed transitions, guards/validators, transition outcome classification. It must not own: persistence, transactions, queue polling, locks, provider execution, or Telegram I/O.

**Pattern:** Load row from DB → build small domain model → run machine to validate transition → commit new state and side effects in our own transaction. Side effects stay outside the library.

**Why this library:** Async support; guards and validators; external/domain-model state storage (no ORM); diagrams for docs/review; run-to-completion processing model. Fits the need for explicit durable state inspection, admin/status surfaces, and recovery provenance.

**Why not others:** `transitions` is more dynamic/magic-heavy and async/event-loop handling is on you. `Automat` is input-driven and less natural for explicit state inspection and recovery. Temporal/Celery/PGMQ are the wrong layer for the core request path; queue stays app-owned.

**Package layout:** `app/workflows/` with `transport_recovery.py`, `pending_request.py`, `results.py` (explicit transition outcomes). Extract transport workflow first from `work_queue.py` and `telegram_handlers.py`; then pending-request workflow from `session_state.py`, `telegram_handlers.py`, `request_flow.py`.

**TransportRecoveryMachine:** States `queued`, `claimed`, `pending_recovery`, `done`, `failed`. Transitions: `claim_inline`, `claim_worker`, `complete`, `fail`, `move_to_pending_recovery`, `reclaim_for_replay`, `discard_recovery`, `supersede_recovery`, `recover_stale_claim`. Guards/outcomes: per-chat single-claimed invariant; pre-claimed inline item reusable by same worker; blocked replay vs already-handled recovery distinct; failed recovery-notice delivery never maps to `done`; fresh live work never classified as recovered.

**PendingRequestMachine:** States `none`, `pending_approval`, `pending_retry`, plus terminal outcomes via result classification. Transitions: `create_approval`, `create_retry`, `approve_execute`, `reject`, `expire`, `invalidate_stale`, `cancel`, `clear_after_execution`.

**Code shape:** Thin domain models (e.g. `TransportWorkflowModel`, `PendingRequestWorkflowModel`). Machine methods stay pure: take model, return `TransitionResult` (allowed, new_state, disposition, reason, optional user_message_key). DB writes stay in repository/service code around the machine call; no side effects inside state-machine callbacks. `work_queue.py` becomes repository + transaction code; handlers stop open-coding state decisions; `request_flow.py` orchestrates over resolved context plus pending-request workflow.

**Tests:** Add machine contract tests (allowed/forbidden transitions, replay/discard/already-handled/blocked classification, inline vs worker claim, stale vs fresh) before refactoring call sites. New suites: `tests/test_transport_workflow_machine.py`, `tests/test_pending_request_workflow_machine.py`. Keep integration coverage in existing `test_work_queue.py`, `test_workitem_integration.py`, `test_request_flow.py`.

**Defaults:** The library is the sole owner of transition legality; no hand-rolled transition table or validator as fallback. Machine callbacks stay pure (no SQL, Telegram, or provider calls). No generic workflow framework or broker as part of this refactor.

**Phase 11 execution order.**

1. Lock the transport invariants in docs; keep schema versioning and
   validate-before-use explicit (no mutate-before-validate; migration deferred).
2. Add or tighten the shared row validator so every load and reread path
   enforces the full row invariant set.
3. Narrow the public repository API around explicit operations rather than
   stringly-typed target states.
4. Move every remaining transport mutation onto the shared repository
   primitives and compare-and-update classification path.
5. Route direct scanners such as `recover_stale_claims()` through the shared
   validator or shared primitives.
6. Keep enqueue and preclaim behavior narrow: `queued` without claimant,
   explicit create-plus-immediate-claim only when a real claimant exists.
7. Keep corruption handling asymmetric: generic user-safe failures at handler
   boundaries, fail-fast worker behavior in development.
8. Remove temporary compatibility wrappers once all call sites use the
   explicit repository API.

**Phase 11 seal checklist (done when moving to Phase 12):** All three claim entry points use one shared claim helper; both initial-insert paths use one shared insert helper; no transport mutation helper open-codes its own CAS/reread classification; repository-shape tests pin the single-claim and single-insert behavior; docs/status truthfully reflect that state.

### Phase 12 - Postgres Runtime Cutover *(complete, historical phase record)*

This section is preserved because it explains why the repo still has explicit
Postgres tooling, migrations, and integration suites. It is a sealed
historical phase record, not the current runtime contract. The current shipped
runtime is the Phase 13+ Local Runtime baseline: SQLite-default, Postgres as a
supported alternate backend, with the current operator paths documented in
[README.md](../README.md), [status.md](status.md), and
[ARCHITECTURE.md](ARCHITECTURE.md).

Phase 12 itself made Postgres the only supported runtime backend after cutover.
It was a contract-preserving backend replacement and
environment/bootstrap phase, not a queue redesign phase and not a CI/CD phase.
Implementation complete; see [status.md](status.md).

**What Phase 12 is solving.**

- Phase 11 stabilized the workflow and repository contracts.
- Phase 12 replaces the SQLite runtime authority under those contracts.
- Phase 12 must also define the missing operational contract that SQLite hid:
  where the database comes from, who initializes it, how schema SQL is applied,
  and what must happen before the bot starts in a fresh environment.
- The app must not depend on a "magical Postgres" that already exists.

**Development-first scope.**

- Build the Postgres runtime for current development use first.
- Keep webhook-primary queue authority, leases, and multi-worker behavior in
  the later **Shared Runtime** phases (now Phases 18-19). Phase 12 only
  replaces the storage backend under the current single-process contract.
- Do not spend Phase 12 effort on in-place SQLite schema migrations.
- Do not make SQLite-to-Postgres import a gating requirement during
  development. If preserving dev/test data becomes worthwhile later, that can
  be added as an optional follow-up tool rather than as the core Phase 12
  deliverable.
- Do not make CI/CD, cloud-provider automation, or hosted control-plane design
  part of the Phase 12 critical path. Those come after the manual environment
  lifecycle is explicit and working.

**Phase 12 hard requirements.**

- Preserve current payload JSON shapes, current dataclass contracts, and the
  workflow outcome taxonomy defined in Phase 11. Postgres is a storage cutover
  under stable contracts, not a semantic rewrite.
- Preserve the current "fresh machine can be made runnable from repo-owned
  instructions" experience. The steps may become more explicit than SQLite, but
  they must still be repo-owned, documented, and repeatable.
- Keep application runtime responsibility separate from infrastructure and
  schema bootstrap responsibility.

**Operational contract (new explicit requirement).**

Phase 12 should be built around three separate responsibilities:

1. Infrastructure provisioning
   - A Postgres service exists and is reachable.
   - This may be Docker-managed in development, Docker-managed or external in
     staging, and external/managed in production.
2. Database bootstrap and update
   - The schema namespace, tables, indexes, and schema version records are
     created and updated by explicit repo-owned commands against an existing
     database and runtime role supplied by infrastructure.
   - This is not implicit application startup behavior.
3. Application runtime
   - The bot reads runtime config, connects, validates schema compatibility, and
     runs.
   - The bot does not create the Postgres server, create the runtime database,
     create the role, or apply schema changes on startup.

**Startup rule.**

- App startup is validate-only:
  - read `BOT_DATABASE_URL`
  - connect
  - validate schema/version/layout
  - fail clearly if not ready
- App startup is not allowed to auto-migrate, auto-create roles, or "repair"
  missing schema.

**Environment model.**

Treat each running bot environment as an explicit unit, not as an implicit
machine-global default.

- One environment should have:
  - environment name (`dev-alice`, `staging-main`, `prod`, etc.)
  - bot instance name
  - Telegram bot token
  - runtime config/env file
  - database host + database name + schema namespace + runtime role
  - working directory / branch or release source
- Use one database per environment. Do not mix multiple branch/staging/dev
  environments inside one shared runtime database.
- Inside each database, keep one runtime schema namespace such as
  `bot_runtime`.

This is especially important because multiple dev and staging environments are
likely. Side-by-side branch testing should mean separate app instances and
separate Postgres databases, not one shared database with mixed state.

**Recommended environment shapes.**

| Environment | Recommended app shape | Recommended Postgres shape | Reason |
|-------------|-----------------------|----------------------------|--------|
| Development | Docker container | Docker Compose Postgres | Preserves "fresh machine works" with an explicit, reproducible local stack. |
| Staging | Docker container | Start with Docker Compose Postgres; allow external Postgres later | Matches development initially, then can move closer to production once the contract is stable. |
| Production | Docker container | External / managed or separately managed Postgres | Keeps runtime contracts the same while avoiding single-host Postgres fragility by default. |

Production is intentionally left open at the infrastructure layer. Phase 12
should not hard-code AWS, SSH-only deploys, or a specific hosting platform. The
important contract is that the app runtime and database lifecycle stay
separate.

**Shipped Phase 12 operating shape.**

- Development:
  - Docker Compose is the canonical shape for Postgres, DB tooling, and the app runtime.
  - The supported bot image is real provider-enabled (includes the chosen
    Claude or Codex CLI), built via repo-owned script from `BOT_PROVIDER`;
    stub-provider image is test/dev-only.
- Staging:
  - Follows the same Docker-first bootstrap/update/doctor contract as development.
  - Postgres may remain Compose-managed or move external without changing the
    ownership model.
- Production:
  - Keep the app containerized.
  - Prefer external or managed Postgres over a same-host Postgres container
    unless this is intentionally low-ops.

**Repo-owned workflows (the things operators and developers actually run).**

Phase 12 should introduce four explicit workflows and document them as the only
supported lifecycle:

1. App bootstrap
   - Build or refresh the app image and related runtime assets.
   - `scripts/app/bootstrap.sh` remains useful for local development and tests, but
     Docker is the primary product-facing operational path.
2. DB bootstrap
   - Apply repo-owned schema to an *existing* database (database and runtime role
     must already exist, e.g. via Compose postgres image or out-of-band provisioning).
   - CLI reads `BOT_DATABASE_URL` and runs schema SQL only; create schema namespace
     and apply full repo-owned SQL from scratch.
3. DB update
   - Apply pending schema versions to an existing environment before app
     restart when the repo adds new SQL files
4. DB doctor
   - Validate connectivity, schema version, required tables, required indexes,
     and compatibility with the current build

The app itself should not absorb these workflows.

**Suggested command surface.**

The exact filenames can change, but the plan should assume a command set like:

- `scripts/app/bootstrap.sh`
- `scripts/db/db_bootstrap.sh`
- `scripts/db/db_update.sh`
- `scripts/db/db_doctor.sh`
- optional convenience wrapper for local development such as:
  - `scripts/app/dev_up.sh`
  - or `make dev-first`
  - or Compose profiles plus one-shot services

These commands are the missing DevOps seam. CI/CD can automate them later, but
Phase 12 should make them usable manually first.

**Docker-first operating shape.**

Phase 12 establishes one canonical Compose shape for the tooling layer instead
of leaving every developer to improvise:

- expected services:
  - `postgres`
  - one-shot repo-owned helpers:
    - `db-bootstrap`
    - `db-update`
    - `db-doctor`
  - `bot`
- helper services run from the repo/app image (or a closely related tooling
  image), so SQL and validation logic are versioned with the code
- the app container does not run `systemd`; the container runtime owns the
  process lifecycle
- the tooling stack must be runnable from a clean repo with no bot runtime env
- the bot runtime is environment-specific and container-first:
  - the container receives explicit runtime env
  - it uses the Compose hostname `postgres`
  - the image must include the chosen provider runtime
  - provider login state is expected to persist in a dedicated bot-home volume,
    not in the image layers

**First-time sequence for a brand-new development environment.**

The first-time path is explicit and repeatable:

1. Build or bootstrap the app runtime.
2. Start the Compose Postgres service.
3. Wait for Postgres readiness.
4. Run DB bootstrap against that Postgres (DB and role already exist; Compose
   postgres image creates them from env):
   - create schema namespace
   - apply all repo SQL
5. Run DB doctor.
6. Provide runtime env for the bot container:
   - Telegram token
   - provider selection
   - access policy (`BOT_ALLOWED_USERS` or `BOT_ALLOW_OPEN`)
7. Run the guided provider-login step in the bot container so the selected CLI
   stores its login state in the bot-home volume.
8. Verify provider health.
9. Start the bot container against the bootstrapped Postgres service.

The long-term UX can be wrapped in a single convenience command, but Phase 12
must document the underlying steps clearly first.

**Update sequence for an existing environment.**

- Code-only change:
  - rebuild app image or refresh Python deps
  - restart app
- Schema change:
  - run DB update first
  - then restart app
- App startup should fail if schema is behind the current build
- App startup should fail if the chosen provider CLI is missing or its runtime
  auth/health check is not usable
- Do not hide schema updates inside bot startup "just this once"

**Runtime config and credentials.**

- Add `BOT_DATABASE_URL` as the app runtime connection string.
- Add pool settings such as:
  - min/max connections
  - connect timeout
  - statement timeout if needed
- Keep bootstrap/admin credentials separate from app runtime credentials.
  Phase 12 may use a separate bootstrap URL or bootstrap-only command inputs for
  first-time DB/role creation.
- Do not make the bot app itself depend on cloud-provider admin credentials.
  Cloud or host provisioning belongs to environment/bootstrap tooling, not to
  the runtime process.

**Contract boundary (the abstraction layer).**

- Keep the current repository boundary as the abstraction:
  - session storage contract from `storage.py`
  - transport/work-queue contract from `work_queue.py`
- The backend swap should happen behind these contracts. Callers in handlers,
  worker orchestration, request flow, and execution-context code should not
  grow backend-specific branches.
- Temporary backend selection during bring-up is acceptable, but permanent dual
  runtime support is not the goal. The target end state is one Postgres-backed
  runtime path.

**Suggested backend interfaces.**

- `SessionStore`
  - `session_exists`
  - `load_session`
  - `save_session`
  - `delete_session`
  - `ensure_data_dirs` or equivalent bootstrap seam
- `TransportStore`
  - `record_and_enqueue`
  - `record_update`
  - `enqueue_work_item`
  - `update_payload`
  - `claim_for_update`
  - `claim_next`
  - `claim_next_any`
  - `complete_work_item`
  - `fail_work_item`
  - `mark_pending_recovery`
  - `get_pending_recovery_for_update`
  - `get_latest_pending_recovery`
  - `discard_recovery`
  - `reclaim_for_replay`
  - `recover_stale_claims`
  - `purge_old`
  - `has_queued_or_claimed`
- Keep these as narrow repository contracts, not generic ORM-style models.

**Runtime architecture.**

- Add `BOT_DATABASE_URL` and pool settings.
- Use `psycopg` v3 with pooled Postgres connections.
- Avoid an ORM.
- Keep schema management repo-owned with versioned SQL plus a small migration
  runner.
- Keep machine/state logic in Python and persistence authority in the database.
- Keep provider execution and Telegram I/O outside repository transactions.
- Keep `storage.py` and `work_queue.py` as the public runtime boundary if that
  is the least disruptive path; delegate internally to configured store
  implementations instead of scattering `if postgres` branches across the app.

**Postgres schema shape.**

- Use one Postgres schema namespace for bot runtime data (for example
  `bot_runtime`) so the runtime tables are clearly separated from any future
  analytics, billing, or registry tables.
- Keep repo-owned SQL files such as:
  - `app/db/migrations/postgres/0001_runtime.sql`
  - `app/db/migrations/postgres/0002_...sql` for later additive changes
- Track applied versions in a dedicated schema-migrations table instead of a
  generic `meta` row.

**Sessions schema (preserve current session contract).**

- `sessions`
  - `chat_id BIGINT PRIMARY KEY`
  - `provider TEXT NOT NULL DEFAULT ''`
  - `data JSONB NOT NULL DEFAULT '{}'::jsonb`
  - `has_pending BOOLEAN NOT NULL DEFAULT FALSE`
  - `has_setup BOOLEAN NOT NULL DEFAULT FALSE`
  - `project_id TEXT NULL`
  - `file_policy TEXT NULL`
  - `created_at TIMESTAMPTZ NOT NULL`
  - `updated_at TIMESTAMPTZ NOT NULL`
- Indexes:
  - `sessions(updated_at)`
  - add `has_pending` or `(has_pending, updated_at)` only if query patterns
    justify it during implementation
- Preserve the current typed `SessionState`, `PendingApproval`, and
  `PendingRetry` boundary by keeping `data` as authoritative JSONB for now.
  Phase 12 is not the time to normalize session internals into many tables.

**Transport schema (preserve current transport contract).**

- `updates`
  - `update_id BIGINT PRIMARY KEY`
  - `chat_id BIGINT NOT NULL`
  - `user_id BIGINT NOT NULL`
  - `kind TEXT NOT NULL`
  - `payload JSONB NOT NULL DEFAULT '{}'::jsonb`
  - `received_at TIMESTAMPTZ NOT NULL`
  - `state TEXT NOT NULL DEFAULT 'received'`
- Indexes:
  - `(chat_id, received_at)`
- `work_items`
  - `id TEXT PRIMARY KEY`
  - `chat_id BIGINT NOT NULL`
  - `update_id BIGINT NOT NULL UNIQUE REFERENCES updates(update_id) ON DELETE CASCADE`
  - `state TEXT NOT NULL`
  - `worker_id TEXT NULL`
  - `claimed_at TIMESTAMPTZ NULL`
  - `completed_at TIMESTAMPTZ NULL`
  - `error TEXT NULL`
  - `created_at TIMESTAMPTZ NOT NULL`
- Constraints:
  - `CHECK (state IN ('queued','claimed','pending_recovery','done','failed'))`
  - `CHECK (state != 'claimed' OR worker_id IS NOT NULL)`
  - `CHECK (state != 'claimed' OR claimed_at IS NOT NULL)`
- Indexes:
  - `(state, chat_id)`
  - `(chat_id, state)`
  - unique partial index on `(chat_id)` where `state = 'claimed'`
- Keep the current work-item id shape (`TEXT`/hex id) unless there is a strong
  reason to change it; Phase 12 should preserve current contracts and payloads.

**Repository implementation approach.**

- Implement Postgres-specific repository modules rather than sprinkling SQL
  conditionals into the SQLite modules.
- Recommended structure:
  - `app/db/postgres.py` for pool/bootstrap lifecycle
  - `app/db/postgres_migrate.py` for the lightweight SQL runner
  - `app/db/postgres_doctor.py` for connectivity/schema validation
  - `app/storage_pg.py` for session-store implementation
  - `app/work_queue_pg.py` for transport-store implementation
- Keep the existing SQLite modules as the behavioral reference during bring-up.
  Once Postgres passes the same contract tests, switch the runtime path instead
  of maintaining long-term dual behavior.

**Transaction and concurrency model.**

- Preserve the exact repository semantics established in Phase 11:
  - explicit transactions
  - exact compare-and-update
  - reread classification on zero-row updates
  - corruption surfaced, not normalized
- In Postgres, implement these using:
  - `INSERT ... ON CONFLICT DO NOTHING` for idempotent update journal writes
  - `UPDATE ... WHERE ... RETURNING ...` for exact compare-and-update
  - `SELECT ... FOR UPDATE` only where row locking is needed for correctness
- Keep claim transactions short. Do not hold database transactions open across
  provider execution or Telegram I/O.
- Keep queue redesign out of Phase 12. Row-lock worker claiming as the primary
  queue authority belongs to the later **Shared Runtime** phases.

**Testing strategy for Phase 12 and beyond.**

Phase 12 extends the contract-owner suite structure; it does not replace it
with container-heavy black-box testing.

- Keep pure contract and workflow suites fast and backend-independent.
- Keep persistence and integration confidence in real Postgres.
- Add a small explicit bootstrap/startup/update E2E layer on top of that.
- Do not make app-container E2E the main confidence layer.

**Four-layer test model.**

1. Pure or owner suites
   - Workflow machines, execution context, request-flow logic, provider event
     mapping, formatting, progress, and other backend-independent contracts.
   - No Postgres required.
   - No app container required.
2. In-process integration
   - Real handlers, real request flow, real repository or store, fake Telegram,
     fake provider, real Postgres.
   - This becomes the main confidence layer for Phase 12 storage cutover work.
   - The app runs under normal pytest or venv execution here, not inside the
     app container.
3. Postgres bootstrap and schema integration
   - Real Postgres, repo-owned DB bootstrap, DB update, DB doctor, and startup
     validation checks.
   - Focused on operational contract, not normal handler behavior.
4. E2E
   - Full stack: app container + Postgres container + explicit
     bootstrap/update/doctor flows.
   - Small smoke set only: first boot, schema update, startup validation,
     minimal happy-path request flow.

**Isolation model (current shipped harness).**

- Postgres integration suites require Docker.
- The harness starts a dedicated test-only Postgres container per pytest-xdist
  worker.
- Each worker:
  - gets one database inside that container
  - applies schema once
  - truncates or resets runtime tables between tests
- The harness never uses `BOT_DATABASE_URL` or any dev/staging/production DB
  for truncation or schema mutation.
- Do not use transaction rollback as the global isolation strategy.

**Why truncate or reset, not rollback.**

- Rollback isolates only work performed on the same connection.
- This codebase uses real commits, multiple connections, async coordination, and
  later a connection pool.
- Rollback cannot reliably isolate:
  - committed writes from app code
  - multiple connections in one test
  - handler vs worker concurrency
- Rollback remains acceptable only inside narrow single-connection repository
  tests, not as the default suite-wide cleanup model.

**Behavioral parity vs mechanical parity.**

- "Tests pass against Postgres" means the same scenarios and contracts still
  hold.
- It does not mean every SQLite-era test file can switch backends without edits.
- Expect real test migration work in places that currently touch SQLite
  directly, especially:
  - `test_work_queue.py`
  - `test_sqlite_integration.py`
  - handler or doctor tests that assert SQLite-specific schema or corruption
    behavior
- The goal is behavioral equivalence under Postgres, not zero test edits.

**What should stay backend-independent.**

- Workflow-machine suites
- execution-context suites
- request-flow business-rule suites
- progress and formatting suites
- most provider tests

These should remain fast and should not depend on Docker or Postgres.

**What must migrate from SQLite to Postgres.**

- Session-store persistence coverage
- transport and work-queue repository coverage
- storage-backed handler integration coverage
- work-item serialization, replay, discard, and stale-recovery integration
  coverage

This is a test migration, not a second long-term backend matrix. After Phase 12
lands, there should not be a permanent parallel SQLite-vs-Postgres runtime test
split for the core request path.

**SQLite test cleanup rule.**

- `test_sqlite_integration.py` does not survive as-is.
- Replace or split it into:
  - backend-neutral integration coverage moved into shared owner suites
  - a Postgres integration suite for the new runtime backend
  - optionally, a short-lived SQLite-only suite during bring-up if needed for
    cutover confidence
- Remove long-term SQLite runtime tests once Postgres becomes the supported
  backend.

**App container rule.**

- Integration tests run under pytest on host or venv, talking to real Postgres.
- The app container is used only in the small E2E layer.
- Do not make normal integration confidence depend on building or starting the
  app container for every test run.

**Suggested implementation sequence.**

1. Freeze the Phase 11 repository contract with the current tests so the
   backend swap is measured against behavior, not assumptions.
2. Absorb the Phase 12 operational and testing contract into the core docs:
   - README for operator-facing bootstrap/run/update guidance
   - ARCHITECTURE for runtime and testing contracts
   - STATUS for current shipped posture
3. Add runtime config:
   - `BOT_DATABASE_URL`
   - pool size / timeout settings
   - optional bootstrap/admin connection inputs for DB bootstrap
4. Add Postgres bootstrap/update/doctor tooling:
   - versioned SQL runner
   - schema/version validation
   - explicit DB bootstrap command
5. Add the Phase 12 Postgres harness:
   - dedicated test-only Postgres container per pytest worker
   - one database per worker
   - truncate/reset cleanup between tests
   - clear split between backend-independent suites, Postgres integration
     suites, and E2E
6. Add canonical development Docker services:
   - `postgres`
   - `bot`
   - one-shot helpers for bootstrap/update/doctor
7. Add Postgres session schema and `SessionStore` implementation.
8. Migrate session persistence and integration coverage from SQLite to
   Postgres-backed fixtures and assertions.
9. Add Postgres transport schema and `TransportStore` implementation.
10. Port the exact Phase 11 repository rules:
   - claim path
   - replay/discard path
   - stale-recovery path
   - exact CAS + reread classification
11. Migrate work-queue and storage-backed integration suites from SQLite to
    Postgres-backed fixtures and assertions.
12. Add backend-selection wiring behind the existing public storage/work-queue
    boundary.
13. Run the owner suites and in-process integration suites against Postgres.
14. Add the small Compose-based E2E layer for bootstrap/startup/update flows.
15. Prove a brand-new development environment can go from zero to running using
    only repo-owned instructions and commands.
16. Flip the runtime to Postgres as the supported backend for current
    development.
17. Remove the long-term SQLite runtime test path once Postgres is the
    supported backend.
18. Only then move to Phase 13 storage-backend abstraction and Local Runtime
    work.

**Acceptance and test plan for Phase 12.**

- Contract tests:
  - existing owner suites keep their ownership boundaries and continue to cover
    the same contracts
  - existing transport workflow-machine tests still pass (backend-independent)
  - existing pending-request machine tests still pass
  - existing session/request-flow contracts still pass against the
    Postgres-backed session store
- Schema tests:
  - brand-new Postgres DB boots from repo-owned SQL
  - DB bootstrap creates the expected schema namespace, tables, indexes, and
    schema-migrations records
  - DB update applies only pending versions
  - unsupported/mismatched schema version fails clearly at app startup
  - required indexes and constraints exist
- Environment/bootstrap tests:
  - canonical dev Compose stack can boot from zero on a fresh machine
  - app startup fails clearly if Postgres is unreachable
  - app startup fails clearly if schema is missing or behind
  - DB doctor reports connectivity/schema problems without starting the app
  - two development environments can run side-by-side with separate databases
    and separate app config
- Test-harness requirements:
  - one Postgres service per run
  - one database per pytest worker
  - truncate/reset cleanup between tests is the default isolation strategy
  - rollback is used only in narrow single-connection tests, not as suite-wide
    isolation
- Session tests:
  - `SessionState` round-trips through JSONB without shape changes
  - `PendingApproval` / `PendingRetry` persistence behavior is unchanged
  - project binding / file policy / model profile fields preserve current
    semantics
- Transport tests:
  - `record_and_enqueue` remains idempotent on duplicate `update_id`
  - exact CAS on claim / complete / fail / replay / discard remains unchanged
  - one-claimed-per-chat invariant is enforced by both repository logic and the
    partial unique index
  - replay/discard ownership semantics match SQLite behavior
  - stale recovery preserves the same classification semantics
- Non-goals for Phase 12 tests:
  - no permanent dual SQLite and Postgres runtime suite
  - no requirement that SQLite-coupled tests migrate without edits
  - no SQLite-to-Postgres import tests required yet
  - no multi-worker queue/lease tests yet
  - no webhook-primary queue semantics yet
  - no CI/CD automation required yet

**Completion standard for Phase 12.**

- Postgres can run the current bot end-to-end for development use.
- The repository/workflow contract remains behaviorally identical to the
  stabilized Phase 11 contract.
- The environment/bootstrap lifecycle is explicit:
  - who provides Postgres
  - who runs DB bootstrap
  - who runs DB update
  - what startup validates
- The testing lifecycle is explicit:
  - owner suites remain the main contract layer
  - persistence and integration coverage runs against real Postgres
  - per-worker databases plus truncate/reset provide isolation
  - a small Compose-based E2E layer covers bootstrap/startup/update flows
- A fresh development environment can be brought from zero to a working bot
  using repo-owned commands without tribal knowledge.
- No application layer outside the storage/work-queue boundary depends on
  SQLite-specific behavior.
- The codebase is ready for the next roadmap phase without re-litigating state
  ownership, repository semantics, or basic environment bootstrap.

### Pre-Phase-13 Execution Program (Required Gate)

This is not a new numbered phase. It is the required execution program between
sealed Phase 12 and the next structural roadmap phase.

Reason:

- Phase 12 established the Postgres runtime, Docker-first operating shape, and
  explicit DB lifecycle.
- That foundation should now be turned into a genuinely low-friction product
  path before more infrastructure is added.
- Starting Phase 13 too early would create another infra-heavy cycle before the
  current product path is simple and trustworthy for operators and users.

Execution rule:

- Complete these milestones in order.
- Do not start the next milestone until the current one has:
  - code implemented through existing contracts
  - realistic tests added or migrated
  - relevant targeted suites passing
  - `status.md` updated accurately
- Do not mark the pre-Phase-13 gate complete until the gate checklist at the
  end of this section is satisfied.

#### Milestone A - Turnkey Docker Runtime

Objective:

- Make the Docker path the real happy path, not just the documented one.

Required outcomes:

- The supported bot image includes the selected provider runtime.
- The supported Docker path includes a guided provider-auth step that persists
  CLI login state in a bot-home volume and reuses that same volume at runtime.
- A fresh machine can go from clone to working bot with:
  - Docker
  - Postgres
  - DB bootstrap
  - DB doctor
  - provider login
  - provider health verification
  - bot startup
- The Docker path should not require operator improvisation beyond token and
  access configuration and one guided provider login.

Implementation rules:

- Reuse the current Compose and DB tooling shape; do not invent a second
  bootstrap path.
- Keep app startup validate-only.
- Keep DB bootstrap/update/doctor explicit and separate from app startup.
- Keep provider auth out of the image build itself; use runtime login state in
  a persistent bot-home volume instead.
- Keep one uniform operator command for provider login even if the underlying
  provider-specific flows differ (`codex --login` vs `claude` + `/login`).
- Provider-login setup must use the same image and the same persistent bot-home
  volume as the runtime bot service.
- Do not reintroduce multiple equally-promoted runtime modes in the user-facing
  docs.

Tests required:

- Clean-repo Compose tooling E2E:
  - Postgres starts
  - DB bootstrap succeeds
  - DB doctor succeeds
- Bot image and runtime: the supported image is real provider-enabled (built
  from `infra/docker/Dockerfile.bot` via build script). Tests should prove the image
  contains the selected provider and can reach a real request execution path,
  not only startup.
- Provider auth and persistence:
  - guided provider-login step writes auth state into the bot-home volume
  - runtime bot service reuses that same volume
  - startup fails clearly when provider auth is missing
  - `/doctor` and any provider-status tooling report unauthenticated state with
    the exact next step
- Tooling/bootstrap/doctor Compose E2E remain. Stub-provider image may be used
  for test/dev-only smoke when real provider is unavailable, but it is not the
  supported product-runtime proof.
- Update smoke:
  - DB update runs cleanly on an already bootstrapped environment

Done when:

- `README.md` can honestly present Docker as the primary path without caveats
  that force users into host-run.
- The supported image, provider-login flow, and Compose runtime are enough for
  a fresh operator to reach a working bot.

#### Milestone B - Config and Onboarding Simplification

Objective:

- Reduce the number of operator choices and the amount of setup knowledge
  needed before first success.

Required outcomes:

- One primary bot runtime config shape:
  - container env file for Docker path
- One primary provider-auth shape for the Docker product path:
  - guided in-container CLI login persisted in the bot-home volume
- Error messages for missing token/provider/access settings point directly to
  the correct fix.
- `/doctor`, startup validation, provider-status checks, and DB tooling tell
  operators what is wrong in product language, not only implementation
  language.

Implementation rules:

- Keep one primary `.env.bot` path in Docker docs and examples.
- Do not expand the front-door docs with multiple equivalent modes.
- Keep advanced/fallback modes documented only in deeper docs.

Tests required:

- Config validation tests for missing/invalid token, provider, and access
  policy
- Provider-auth validation tests for:
  - missing login/auth state
  - missing provider binary
  - login state persisted and reused across setup/runtime containers
- Doctor output tests for missing config and runtime misconfiguration
- Startup integration tests for common failure paths
- Compose smoke that proves the documented minimal env actually works

Done when:

- A new operator can follow one short path without choosing between run modes.
- The top setup failures produce clear next steps.

#### Milestone C - User-Facing Settings And `/project` Polish

Objective:

- Use the stable backend and workflow contracts to improve the product surface
  people actually touch.

Required outcomes:

- `/project` is low-friction and discoverable.
- Settings/profile changes are discoverable without memorizing many commands.
- Inline keyboard flows reuse the existing settings callback patterns instead of
  creating one-off UI paths.

Implementation rules:

- Reuse the existing settings-inline-keyboard and callback handling patterns.
- Reuse existing dataclasses, session fields, and execution-context semantics.
- Do not create a second project or profile scoping system.
- This milestone intentionally pulls forward low-risk discoverability and UX
  polish that was previously deferred to later roadmap work. Do not widen it
  into queue-dependent or multi-worker-dependent UX.

Current implementation seams that this milestone must extend, not replace:

- Command handlers in `app/telegram_handlers.py`:
  - `cmd_project`
  - `cmd_model`
  - `cmd_policy`
  - `cmd_compact`
- Inline callback path in `app/telegram_handlers.py`:
  - `handle_settings_callback`
- Session and storage contract:
  - `SessionState.project_id`
  - `SessionState.model_profile`
  - `SessionState.file_policy`
  - `SessionState.compact_mode`
  - `_load()` / `_save()` over the existing session store
- Serialization / concurrency boundary:
  - `_chat_lock(...)` for all mutating command and callback paths
- Authoritative context / invalidation logic:
  - `resolve_execution_context(...)`
  - `ResolvedExecutionContext.context_hash`
  - existing provider-session reset pattern:
    `session.provider_state = _prov().new_provider_state()`
  - existing pending-state clearing pattern:
    `session.clear_pending()`

No new workflow state machine is required for this milestone. Project and
settings changes are synchronous session mutations under `_chat_lock`, with
existing pending-request invalidation and provider-session reset rules already
providing the necessary safety behavior. Do not introduce a new FSM, queue
concept, or persistence layer here.

Detailed design:

1. Add one discoverable entry surface, not a second settings system.
- Add `/settings` as a thin menu entry point over the existing setting fields.
- `/settings` should not own new state; it should render the current values and
  expose buttons that reuse the same mutations already supported by:
  - `/model`
  - `/policy`
  - `/compact`
  - the new `/project` inline flow
- Keep command parity: commands remain first-class and must continue to work.
  Inline UI is a discoverability layer over the same authoritative mutations.

2. Make `/project` work like the other discoverable runtime controls.
- Keep `/project list`, `/project use <name>`, and `/project clear`.
- Add an inline keyboard path for `/project` status/default invocation:
  - show current project (or default working dir)
  - show configured projects as buttons
  - show a clear button when a project is active
- Reuse the existing callback routing pattern instead of inventing a separate
  callback subsystem.
- Preferred callback shape: stay inside the current `setting_*` namespace, for
  example `setting_project:<name>` and `setting_project:clear`, so one handler
  continues to own session-setting callbacks.

3. Keep mutation semantics identical across commands and callbacks.
- `/project use`, `/project clear`, `/model`, `/policy`, `/compact`, and the
  corresponding inline buttons must all funnel into the same session mutation
  semantics:
  - acquire `_chat_lock(...)`
  - load `SessionState`
  - mutate the existing session fields
  - when required, reset `provider_state`
  - when required, clear pending approval/retry state
  - save via `_save(...)`
- Do not let command paths and callback paths drift into different behavior.

4. Keep context invalidation rules explicit and minimal.
- Changing `project_id` must:
  - reset provider session state
  - clear pending approval/retry state
  - preserve the rest of the session
- Changing `file_policy` must:
  - reset provider session state
  - clear pending approval/retry state
- Changing `model_profile` should continue to rely on the existing
  `ResolvedExecutionContext.context_hash` invalidation rules and current
  handler behavior. Do not add separate ad hoc invalidation state.
- Changing `compact_mode` is a rendering setting and should not reset provider
  session state.

5. Respect trust/public restrictions through existing gates.
- Keep `_public_guard(...)` as the entry gate for project and file-policy
  mutations.
- Keep public-user profile restrictions in the existing model-profile
  resolution path (`resolve_effective_model` / public profile allowlist).
- Do not add a second public-safety check tree in the new inline flow.

6. Stay inside existing libraries and patterns.
- Continue using `python-telegram-bot` `InlineKeyboardButton` and
  `InlineKeyboardMarkup`.
- Continue using the existing typed dataclasses and provider/session reset
  semantics.
- Do not add a new UI helper library, state container, callback registry, or
  custom persistence abstraction for this milestone.

Recommended implementation sequence:

1. Add `/settings` as a read-only summary + inline keyboard entry point over
   current settings.
2. Extend `handle_settings_callback` to support project selection/clear in the
   same callback namespace and mutation pattern.
3. Update `/project` default output to show the same discoverable inline
   choices instead of text-only status.
4. Refine `/model`, `/policy`, and `/compact` output so commands and callbacks
   render consistently.
5. Only after the command/callback parity is correct, tighten wording and
   markup for discoverability.

Tests required:

- Real handler/integration tests through production code paths for:
  - `/project` list/use/clear
  - inline settings/profile changes
  - callback flows and markup cleanup
- Regression tests that prove context hashes and pending invalidation still
  behave correctly when project/profile changes occur
- Real handler/integration tests through production paths for:
  - `/settings` default view and keyboard contents
  - `/project` default view with active/no-active project
  - `setting_project:<name>` and `setting_project:clear`
  - command/callback parity for model/profile, policy, compact, and project
- Contention tests that prove project/settings callbacks still answer exactly
  once and serialize through `_chat_lock(...)` under in-flight work
- Public-user tests for:
  - `/project` denied in public mode
  - `setting_policy:*` denied in public mode
  - restricted model profiles still blocked through the callback path
- Regression tests that prove:
  - project changes reset `provider_state`
  - policy changes reset `provider_state`
  - project/policy changes clear pending approval/retry state
  - compact changes do not reset `provider_state`
  - context hash changes still flow through the existing
    `ResolvedExecutionContext` contract rather than a new ad hoc mechanism

Done when:

- Project binding, model/profile selection, and key settings are discoverable
  and low-friction.
- `/settings` and `/project` are thin discoverability layers over the same
  authoritative session mutations the command paths already use.
- No new settings/project state model, persistence path, or workflow framework
  was introduced.

#### Milestone D - Progress, Recovery, And Trust Clarity

Objective:

- Make long-running work, interruptions, and trust/profile state feel simpler
  and more understandable to non-technical users.

Required outcomes:

- Progress wording stays provider-neutral and truthful.
- Recovery/replay/discard wording is clear and avoids “system-like” jargon.
- Approval/retry prompts and trust/profile visibility are easier to interpret.

Implementation rules:

- Keep provider semantics rich internally, but simplify user-visible wording.
- Do not flatten away meaningful semantic distinctions in the shared progress
  model.
- Reuse the existing recovery and approval contracts; improve wording and
  presentation around them.

Tests required:

- Handler/output/recovery suites for user-visible strings and flows
- Scenario tests for:
  - interrupted run
  - approval required
  - retry invalidated by stale context
  - compact/progress wording under long runs

Done when:

- Interrupted runs, approval flows, and long-running tasks feel understandable
  rather than “system-like.”

#### Milestone E - Usability Hardening Before Phase 13 (historical, shipped)

Objective:

- Finish the pre-Phase-13 gate by making the current product boring,
  self-consistent, and easier to maintain.
- This milestone is **not only wording cleanup**. It is the final
  end-to-end hardening pass over the current Docker/operator path, the main
  Telegram user journey, and the recently grown code/test structure that now
  owns those behaviors.
- The default path is the strongest justified fix: if a full simplification,
  dead-code removal, duplicate-concept consolidation, or owner-suite cleanup
  will leave the product more correct, reliable, maintainable, or easier to
  operate, it belongs here.

Why this milestone is broader than a “polish pass”:

- Earlier phases already proved that the repo gets riskier when:
  - duplicated invariants and overflow suites create the illusion of coverage
    instead of clear ownership
  - dead code and stale helpers survive after the authoritative seam moved
  - message/callback/operator parity drifts while each path individually looks
    acceptable
- The repo history already contains successful examples of the right cleanup
  model:
  - weak duplicate tests removed and unique tests moved into owner suites
  - dead code removed after review
  - duplicate helper/test infrastructure consolidated
- Milestone E should apply the same standard again where the current codebase
  review shows it is warranted.

Current codebase review that drives this milestone:

- Handler ownership is still concentrated in a very large
  `app/telegram_handlers.py` (~3000 lines). This is not automatically wrong,
  but it increases the cost of duplicated helpers, stale inline copy, and
  drift between command/callback/admin paths.
- Test ownership has grown again in a few large suites:
  - `tests/test_handlers.py` (~1600 lines)
  - `tests/test_workitem_integration.py` (~1600 lines)
  - `tests/test_request_flow.py` (~1000 lines)
  - `tests/test_handlers_approval.py` (~680 lines)
- Shared test helpers already live in `tests/support/handler_support.py`
  (`fresh_data_dir`, `FakeProgress`, `send_command`, `get_callback_data_values`)
  and prior refactors already consolidated some duplication there. Bucket E
  should continue that model instead of tolerating new drift.
- The current milestone work has improved user-facing seams (`/settings`,
  `/project`, recovery/retry copy, trust/profile display, operator scripts),
  which means Bucket E must now:
  - finish the remaining friction in those primary paths
  - remove stale duplicate logic introduced or exposed during the polish work
  - re-home or merge tests that no longer belong in catch-all suites

Concrete cleanup items already identified by review and therefore in scope:

- **Settings / project / model owner collapse in `app/telegram_handlers.py`.**
  The same setting families still have too many owners:
  - model mutation and display:
    - `cmd_model`
    - `handle_settings_callback(setting == "model")`
    - `cmd_settings`
    - `_settings_model_profile_state(...)`
  - project mutation and display:
    - `cmd_project`
    - `handle_settings_callback(setting == "project")`
    - `cmd_settings`
    - `_resolve_project(...)`
  - approval / compact / policy row rendering:
    - dedicated commands (`/approval`, `/compact`, `/policy`)
    - `/settings`
  This is an explicit Bucket E contract. The target shape is:
  - one small authoritative mutator per setting family where command and
    callback paths share the same durable mutation and reset behavior
  - one small authoritative row/builder per setting family where the dedicated
    command and `/settings` share the same visible control state
  - fewer open-coded button rows and fewer repeated inline state transitions
    in command/callback bodies

- **Public command/callback surface tests must be re-homed out of
  `tests/test_request_flow.py`.**
  The current review found handler-surface tests regrowing in the request-flow
  suite:
  - public `/session` display checks
  - public `/settings` display and keyboard checks
  - public `/model` command and `setting_model:*` callback surface checks
  - public `setting_project:*` denial surface checks
  Those belong with handler command/callback ownership, not with execution
  context / pending validation / trust-hash logic. The target shape is:
  - `tests/test_handlers.py` owns user-visible command/callback surfaces
  - `tests/test_request_flow.py` owns execution context, trust shaping,
    invalidation, stale detection, and request-lifecycle contracts
  - where overlap remains intentional, the plan must name the distinct
    contract each suite owns

- **Handler-suite setup reuse must improve.**
  The review found repeated open-coded:
  - `fresh_data_dir()`
  - `make_config(...)`
  - `setup_globals(...)`
  blocks inside `tests/test_handlers.py`, including recent Bucket D cases,
  despite `tests/support/handler_support.py` already providing:
  - `fresh_env(...)`
  - `send_command(...)`
  - `send_callback(...)`
  - `get_callback_data_values(...)`
  This is an explicit Bucket E rationalization target. The target shape is:
  - new handler-surface tests default to `fresh_env(config_overrides=...)`
  - repeated public-user setup is factored into one small shared test helper if
    that reduces drift
  - no new hand-rolled setup clones are added while shared fixtures already
    exist

- **“No moves” or “no refactor needed” is not an acceptable conclusion unless
  the candidate audit is written down.**
  For each large owner seam or suite above, Bucket E must record:
  - what candidates were considered
  - which ones were merged / moved / extracted / deleted
  - which ones stayed and why
  Silent “looked fine” is not enough for this milestone.

Mandatory guidance inputs before coding:

- Repo-local guidance:
  - `AGENTS.md`
  - `CLAUDE.md`
- Global guidance:
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Local skills that must be used where they apply:
  - `docs/codex-skills/contract-change-audit/SKILL.md`
    - for any cross-cutting user-visible or operator-visible contract change
    - explicitly:
      - state the contract being changed
      - identify the authoritative source
      - enumerate equivalent ingress paths with `rg`
      - audit raw vs resolved reads
      - list failure paths, including restart-in-the-middle and
        recovery-interrupted-again
      - define invariants before touching code
  - `docs/codex-skills/invariant-test-builder/SKILL.md`
    - for every multi-axis test cleanup or owner-suite rationalization
    - explicitly:
      - identify the contract axes first
      - add focused contract, real entry-point, and adjacent regression tests
      - prefer negative-capability checks
      - assert both visible output and state
      - name the oracle explicitly
  - `docs/codex-skills/progress-ux-audit/SKILL.md`
    - for any remaining progress/liveness/output/rendering cleanup
    - explicitly:
      - keep wording provider-neutral
      - keep compact/full/raw/export derived from one stable source
      - verify the message object chain the user actually sees
  - `docs/codex-skills/durable-state-hardening/SKILL.md`
    - whenever Bucket E touches pending state, recovery, work items, or any
      durable operator/runtime path
    - explicitly:
      - write the state machine and completion owner table
      - identify durable commit points
      - treat in-memory state as optimization only
      - test success, failure/interruption, duplicate/idempotency, and
        recovery/restart as applicable

Implementation rules (carry these literally into execution guidance):

1. Fix contracts, not call sites.
- Enumerate equivalent ingress paths with `rg` before editing.
- For this repo, the parity checklist remains:
  - message
  - command
  - callback
  - admin
  - CLI
  - approval
  - retry

2. Use the strongest justified fix as the default.
- Do not present a weaker shortcut as equally valid just because it is
  cheaper.
- If a larger cleanup clearly improves correctness, reliability,
  maintainability, performance, safety, or operator usability, do it.
- Only keep the scope narrower when the task is genuinely bounded to copy,
  docs, or another cosmetic change.

3. Use the authoritative source only.
- If resolved execution context exists, use it in user-visible or
  safety-sensitive logic.
- If a builder/helper already owns a concept, update that owner instead of
  duplicating equivalent logic inline.
- If no authoritative owner exists for a cross-cutting setting family, create
  one before patching multiple call sites.

4. Treat failure paths and dead ends as product correctness.
- No-op, already-handled, wrong-user, busy, startup-failure, doctor, provider
  auth, and update-after-pull paths are first-class product behavior.
- If the system tells the user or operator something false, that is a real
  bug, not just “rough wording.”

5. Simplification and refactoring are in scope when evidence-backed.
- Include:
  - dead code elimination
  - duplicate helper/builder/dataclass rationalization
  - stale inline logic removal after centralization
  - test ownership cleanup
  - weak duplicate test removal only when a stronger owner test exists
- Do not include:
  - repo-wide aesthetic churn
  - speculative abstraction
  - rename-only sweeps with no contract or ownership payoff
  - “audit says no change” conclusions without a written candidate list and
    justification

6. Do not overclaim.
- `status.md` must only move when code and tests prove the
  runtime behavior.
- Bucket E is not done because a few small fixes landed; the full audit,
  simplification pass, and verification envelope must be complete.

Milestone E is split into four required workstreams.

### E1. Product-path hardening

Audit and fix the current primary user and operator journeys end to end.

Required audit surfaces:

- Docker/operator path:
  - `scripts/app/dev_up.sh`
  - `scripts/app/guided_start.sh`
  - `scripts/provider/build_bot_image.sh`
  - `scripts/provider/provider_login.sh`
  - `scripts/provider/provider_status.sh`
  - `scripts/provider/provider_logout.sh`
  - `scripts/db/db_bootstrap.sh`
  - `scripts/db/db_update.sh`
  - `scripts/db/db_doctor.sh`
  - `README.md`
- Telegram path:
  - `/start`
  - `/help`
  - `/settings`
  - `/project`
  - `/session`
  - `/model`
  - approval / retry / recovery
  - no-op / already-handled / wrong-user / busy paths
  - public/trusted/admin restriction surfaces

Required outcomes:

- One clear operator path and one clear end-user path
- No stale command/docs drift
- No misleading doctor/provider-health distinction
- No misleading startup/update/rebuild guidance
- No obviously confusing no-op or denial state left in the primary path
- `status.md` and `README.md` reflect the real current
  Bucket E state and do not preserve stale “Current / Next” pointers from
  earlier bucket stages

### E2. Structural simplification and dead-code cleanup

Do a repo-wide audit of the seams touched by Milestones C-D and Buckets A-D.

Required audit targets:

- dead helpers, stale branches, unused imports, obsolete compatibility paths
- duplicate concept owners in:
  - `app/telegram_handlers.py`
  - `app/user_messages.py`
  - `app/execution_context.py`
  - operator scripts
- duplicate builders/helpers introduced by recent polish work
- stale inline messages that should now live in the authoritative owner
- explicitly review duplicated setting-family owners and builders in:
  - `cmd_model`
  - `cmd_project`
  - `cmd_settings`
  - `handle_settings_callback`
  - `/approval`, `/compact`, `/policy` command-specific status/rendering paths

Required outcomes:

- Remove dead code where the authoritative seam has clearly replaced it
- Consolidate duplicate concept logic where drift risk is real
- Keep the simplification behavior-preserving unless a real contract bug is
  also being fixed
- Prefer a smaller number of authoritative helpers/builders over parallel
  partial owners
- Collapse duplicated model/project/policy/approval/compact logic so command
  and callback paths share the same state-transition or row-building owner when
  they are meant to express the same contract
- Remove repeated button-row construction and open-coded mutation branches when
  one small helper can own the concept more clearly

Examples of the right work here:

- consolidate duplicate display-state logic when `/settings`, `/model`,
  `/session`, or help surfaces now share one truth
- consolidate duplicated setting-family mutation logic when command and
  callback paths both set the same durable fields and reset the same provider
  state
- consolidate duplicated settings row/button builders when `/settings` and
  the dedicated setting command (`/model`, `/policy`, `/compact`, `/approval`)
  should stay in lockstep
- remove old helper paths left behind after centralizing user-facing copy
- remove stale operator-path instructions that survive only in one script or
  one doc

### E3. Test ownership and suite rationalization

This is required work, not optional cleanup.

The codebase review shows that a few large suites have grown again and need an
ownership pass:

- `tests/test_handlers.py`
- `tests/test_workitem_integration.py`
- `tests/test_request_flow.py`
- `tests/test_handlers_approval.py`

Required audit questions:

- Is this test asserting a distinct contract, boundary, or failure mode?
- Is it in the suite that actually owns that contract?
- Is there a weaker duplicate proving the same thing through the same
  boundary?
- Is a shared helper already available in `tests/support/handler_support.py`
  and not being reused?
- Is the test oracle correct (original message vs returned status message vs
  edited callback message vs persisted state)?
- Is this actually a handler-surface test that drifted into
  `tests/test_request_flow.py` or another suite that should instead own only
  context / orchestration / durable-state contracts?
- If the conclusion is “no move needed,” what concrete candidate was reviewed
  and what contract does the current suite uniquely own?

Required outcomes:

- Move misplaced tests into owner suites where that improves responsibility
- Merge or delete weak duplicate tests only when a stronger owner test remains
- Consolidate duplicate test helpers instead of cloning them again
- Re-home public `/settings`, `/session`, `/model`, and related `setting_*`
  surface checks so handler command/callback ownership is clear
- Keep `tests/test_request_flow.py` focused on execution identity, trust
  shaping, pending validation, and lifecycle contracts rather than regrowing
  command-surface assertions
- Reduce repeated `fresh_data_dir() + make_config() + setup_globals()`
  scaffolding inside handler suites by reusing `fresh_env(...)` and other
  helpers from `tests/support/handler_support.py`
- Keep negative capability tests and boundary tests that prove the system
  cannot overfire
- Do not reduce confidence in the name of prettiness

The standard is the earlier ownership refactor:
- overflow suites removed
- unique tests strengthened
- owner suites clarified
- shared helpers consolidated

Bucket E should repeat that standard where recent growth warrants it.

### E4. Final truthfulness and verification

After the hardening and simplification work, run the full verification envelope
for the touched areas.

Required verification:

- config / doctor / startup tests
- shell/operator contract tests
- Compose E2E
- persistence/integration suites touched by the work
- real handler/callback flows touched by Milestones B-D
- owner suites touched by test rationalization

Testing rules from the repo guidance and local skills apply directly:

- every nontrivial change needs:
  - a focused contract test
  - a real entry-point integration test
  - an adjacent regression test
- every user-visible test must declare the right oracle
- every classification or invalidation fix needs a false-positive boundary
  test
- if Bucket E touches a durable path, success/failure/interruption/recovery
  ownership must still be proven

Recommended implementation sequence:

1. Write a contract-first preamble for Bucket E:
  - contract(s) being changed
  - source of truth
  - affected entry points
  - state/persistence touched
  - failure paths
  - required invariants
  - tests to add or rationalize
2. Do one bounded repo-wide audit and classify findings into:
  - product-path friction
  - dead code / stale code
  - duplicate concept owner
  - test ownership drift
  - weak duplicate test
  - stale docs/status
  - duplicated setting-family owner
  - handler-surface tests in the wrong suite
  - repeated test setup that should use shared helpers
3. Group the findings into separate contracts instead of one giant cleanup
   patch.
4. For each large owner seam or suite, write the candidate list and the chosen
   target shape before editing. “No move” or “no extract” is acceptable only
   with explicit evidence.
5. Implement product fixes and structural simplifications together where they
   share the same authoritative seam.
6. Move/rationalize tests only after the owning seam is clear.
7. Run the real verification envelope.
8. Update `status.md` only after the runtime behavior and
   tests are confirmed.

Anti-patterns forbidden in this milestone:

- wording-only patches when the real issue is a broken or duplicated owner
- repo-wide rename churn without contract payoff
- test deletion without a stronger remaining owner test
- new generic frameworks or speculative abstractions
- leaving duplicated setting-family owners in place after the audit already
  proved drift risk, then claiming the simplification pass is complete
- leaving handler-surface tests in `tests/test_request_flow.py` while claiming
  test ownership was rationalized, unless the plan names the distinct contract
  that suite still uniquely owns
- claiming “hardening complete” while the large catch-all suites and touched
  operator/handler paths still drift

Done when:

- The Docker/operator path is boring and self-consistent.
- The main Telegram user journey is coherent end to end.
- The remaining rough edges in doctor/startup/onboarding/update/no-op states
  are resolved.
- Dead code and duplicate concept owners exposed by the polish work are
  removed or consolidated where justified.
- The recently regrown suites are rationalized enough that test ownership is
  clearer, not murkier.
- The verification envelope passes:
  - config/doctor/startup
  - shell/operator
  - Compose E2E
  - touched persistence/integration suites
  - touched handler/callback owner suites
- The docs and status are truthful.
- At that point, and only at that point, should work move to
  **Phase 13 - Storage backend abstraction and Local Runtime mode**.

#### Gate Before Phase 13 (historical)

Do not start Phase 13 until all of the following are true:

- The Docker path is the actual supported happy path, not just the documented
  one.
- New users can get from zero to running without advanced choices.
- The main Telegram workflows feel polished enough that more infrastructure work
  would clearly unlock the next need.
- The current product is stable enough that webhook/multi-process work solves a
  real problem rather than an architectural desire.
- `status.md` truthfully reports the pre-Phase-13 execution
  program as complete.

### Remaining-Phase Execution Discipline

These rules apply to every remaining phase below. They are not optional.

- **Classify the work first:**
  - `session/config/UI mutation`
  - or `workflow/runtime`
- Use the existing FSM architecture only for real workflow/runtime problems:
  durable named states, allowed/forbidden transitions, recovery/terminal
  outcomes, or time-/actor-separated progression.
- Do **not** add a new FSM for simple synchronous settings, session, UI, or
  operator-path mutation.
- Fix contracts, not call sites.
- Audit equivalent paths before coding:
  command, callback, handler, worker, script, operator flow, and docs.
- Prefer resolved context over raw session/config for user-visible and
  safety-sensitive behavior.
- Tests must prove the user/operator contract through the real boundary, not
  only helper behavior.
- Rendering and wording are product correctness, not decorative polish.
- Update `status.md` only after code and tests confirm the
  behavior.

### Phase 13 - Storage Backend Abstraction And Local Runtime Mode

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: use the existing FSM architecture only for
  real workflows; do not add a new FSM for simple synchronous storage,
  session, or UI mutation.

Objective:

- Restore a first-class **Local Runtime** mode, with SQLite as the default
  backend for both Docker and host deployments, while keeping product behavior
  as backend-neutral as possible.

Workflow classification:

- This phase is primarily **storage/runtime abstraction**, not a new workflow
  family.
- Reuse the existing Phase 11 workflow machines; do not add a third workflow
  FSM.

Required outcomes:

- Introduce backend-neutral runtime/storage contracts around:
  - session storage
  - transport/work-item storage
  - pending approval/retry persistence
- Support **Local Runtime** directly in:
  - Docker
  - host mode
- SQLite becomes the **default** backend for Local Runtime.
- Product/core code above the storage boundary should not need code changes
  just because the deployment is using SQLite instead of Postgres.
- Postgres may remain supported as a simple store backend, but **without**
  shared-runtime queue authority semantics in this phase.

Implementation rules:

- Do not pretend SQLite and Postgres are identical at the shared-runtime queue
  authority layer.
- Do isolate genuinely common storage contracts so product features can stay
  backend-neutral.
- Do not hand-roll a second storage model in handlers or request flow.
- Reuse the current repository/workflow contracts as the behavioral reference.
- Keep Local Runtime single-machine semantics explicit rather than trying to
  emulate Shared Runtime queue authority in SQLite.

Tests required:

- Storage contract tests against the Local Runtime backend
- Same product behavior tests through real command/callback/handler paths under
  Local Runtime
- Docker and host local-mode startup/bootstrap/update/doctor tests
- Regression tests proving Local Runtime preserves current product semantics for
  session, approval/retry, and transport ownership

Done when:

- Local Runtime works in both Docker and host mode with SQLite as the default
  backend.
- Product-layer features above the storage boundary no longer require
  backend-specific code changes in normal implementation work.

### Phase 14 - Product Polish On Local Foundations

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: default to session/config/UI mutation and
  reuse the current handler/session architecture unless a real workflow with
  durable states and transitions appears.

Objective:

- Continue user-facing polish on top of the Local Runtime and backend-neutral
  product contracts.

Workflow classification:

- Default: `session/config/UI mutation`.
- No new FSM unless a real workflow problem appears and is justified.

Implementation rules:

- Reuse existing handler, callback, session, and user-message seams.
- Keep command/callback parity.
- Fix authoritative seams, not one-off strings or one call site.
- Use resolved context as the display/safety authority.

Tests required:

- Real handler and callback integration tests
- Adjacent regression tests for discoverability, restrictions, and no-op
  states
- Usability-focused contract tests on the actual user-facing surfaces

Done when:

- The main Telegram product journey remains coherent under Local Runtime and
  backend-neutral contracts.

### Phase 15 - Behavior Extensions

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: only add or extend FSM-backed logic when a
  new durable workflow truly exists; otherwise keep changes inside existing
  session, request-flow, and rendering seams.

Objective:

- Add demand-gated product behavior extensions without coupling them to a
  specific runtime backend.

Workflow classification:

- Most work here should remain product/session/config work.
- If a new extension becomes a real workflow, reuse the existing FSM approach
  rather than hand-rolling transitions.

Scope:

- Demand-gated `content dedup` using explicit user-visible policy and durable
  fingerprints
- Expanded project/policy scope using the existing execution-context and
  project binding model
- Other backend-neutral product behaviors that do not require Shared Runtime
  queue authority

Required workstreams and sequencing:

1. **Slice 1 — Per-project defaults** is the first shipped workstream for
   this phase and remains the behavioral reference for how Phase 15 should be
   executed: extend existing config, execution-context, handler, and test
   owners instead of building a parallel subsystem.
2. **Slice 2 — Worker-owned live execution and cancellation** is the next
   required workstream. It moves fresh provider-starting work off the Telegram
   update handler path and makes the worker-owned execution lane the only owner
   of active provider runs. User-visible live cancel must be built on that
   ownership model; PTB dispatcher concurrency tricks are not an acceptable
   design.
3. **Slice 3 — Claude progress usability** follows Slice 2. It improves Claude
   progress structure by reusing the existing shared progress event family and
   renderer rather than adding a Claude-only rendering path.
4. **Later Slice — Content dedup** remains demand-gated future work and must
   stay behind the shipped cancel/progress work. Do not let it overtake Slice 2
   or Slice 3.

Implementation rules:

- Reuse existing data flows first. Before introducing a new helper, type, or
  test family, inspect the current owners and extend them if they are already
  the authoritative seam.
- This phase is explicitly about enhancing the current architecture, not
  building parallel capability systems. That means:
  - reuse current handler and callback ingress as thin normalization/enqueue
    owners, not as the owner of long-running provider execution
  - reuse current provider protocol and result types
  - reuse the existing work queue as the primary owner of both fresh and
    recovered provider-starting work
  - reuse `_chat_lock` as the per-chat execution guard inside the worker-owned
    path, not as a reason to keep provider execution inline in Telegram update
    handlers
  - reuse the existing shared progress event family and renderer
  - enhance existing tests before creating a shadow suite
- Do not force weak reuse when the concept genuinely needs a new local helper
  or type. New code is allowed when it extends the existing owner cleanly.
  What is forbidden is bypassing the current owners with a second mechanism.
- Do not create a second scoping, dedup, progress, or cancellation system.
- Keep behavior extensions layered above the existing transport and
  execution-context contracts.
- Do not move progress or cancel orchestration into `request_flow.py`. That
  module remains pure business logic with no Telegram transport, progress, or
  subprocess ownership.
- Do not add a speculative new FSM or a second durable cancellation model for
  live cancellation in this phase. Small durable metadata that distinguishes
  fresh live work from replay/recovery work is allowed if it is required to
  make the worker-owned path correct and testable.
- Do not change the `ProgressSink` protocol to carry cancellation semantics.
  Keep rendering and control separate even when they are used together in the
  same execution path.
- Do not rely on PTB `concurrent_updates`, custom update-processor tricks, or
  direct handler concurrency as the production live-cancel mechanism.
- Treat any existing cancel-priority processor, cutoff-map, or direct-handler
  overlap experiment as rejected scaffolding, not as a partial delivery target
  to harden.
- Do not invent Claude progress semantics that the raw stream does not prove.
  If the stream does not clearly prove a `ToolFinish` or `CommandFinish`, do
  not synthesize one.

#### Slice 2 — Worker-Owned Live Execution And Cancellation

Problem statement:

- Historically, `/cancel` only cleared pending approval/retry or credential
  setup.
- When a provider subprocess is actively running inside a Telegram update
  handler, the dispatcher is blocked behind that live execution. PTB-level
  concurrency workarounds either leave `/cancel` serialized and ineffective or
  reopen broad update fan-out that can burn tokens and queue unintended runs.
- The correct fix is to move provider-starting live work off the Telegram
  update handler path and onto the existing durable worker-owned execution
  lane, then make `/cancel` signal that worker-owned run.

Current implementation status:

- The core worker-owned redesign is now the active runtime shape for fresh
  plain-message execution and approval preflight:
  - fresh provider-starting messages are admitted durably with
    `record_and_admit_message()`
  - recovered stale claims are durably requeued with
    `dispatch_mode='recovery'`
  - the worker-owned path is the owner of fresh execution for those request
    types
  - `/cancel` can signal a live worker-owned run through `_LIVE_CANCEL`
  - `/cancel` can also cancel an admitted-but-not-yet-running fresh queued
    item through the durable queue
  - credential-setup replies are handled inline after `record_update()` only
    and are not enqueued as provider work
  - Postgres fresh admission is serialized per chat with an advisory lock
- Remaining work in this family is now:
  - proof-hardening for the new queue/cancel/credential invariants
  - completing worker-path ownership expansion where callback-driven execution
    is still inline
  - extracting a project-owned transport/output port plus simulator so the
    real worker-owned path can be exercised through a realistic fake transport
    instead of ad hoc PTB-shaped doubles

Contracts in this slice:

1. **Worker-owned execution contract**
- Telegram update handlers for provider-starting work must normalize input,
  persist/enqueue work, send any immediate UX response, and return promptly.
- The only place that may call live provider execution owners such as
  `execute_request()` or `request_approval()` for fresh work is the worker-owned
  execution path.
- Fresh live work and recovered/replay work must be explicitly distinguished.
  They must not continue to share an ambiguous single dispatch meaning.
- That distinction must be durable. Recovered stale claims must carry explicit
  recovery routing metadata on the authoritative work item so restart recovery
  can never silently auto-run old provider work as if it were fresh.

2. **Live cancel ingress contract**
- `/cancel` during a worker-owned live provider run must request cancellation
  immediately without requiring PTB dispatcher concurrency.
- `/cancel` when there is no live run must preserve the current pending/setup
  and no-op behavior exactly.
- Fresh provider-starting message admission must be atomic at the durable queue
  boundary. If the chat already has fresh provider work in `queued` or
  `claimed`, the next fresh message must not be admitted as another runnable
  provider item.
- A second plain message while a live run is active, or while fresh provider
  work is already queued for that chat, must not later reach the provider
  accidentally. The shipped product policy in this phase is reject/coalesce,
  not “busy now, run later” and not “queue another provider run behind it”.

3. **Provider cancel outcome contract**
- Provider execution gains a typed, user-initiated cancel outcome distinct from:
  - timeout
  - typed resume failure
  - restart/shutdown interruption that remains `LeaveClaimed`
- User-requested cancel must not route through restart recovery.

Source of truth:

- `work_queue` remains the owner of durable work-item lifecycle.
- The transport-store schema remains the owner of durable routing metadata for
  fresh versus recovered work and of atomic per-chat fresh-work admission.
- `worker_loop()` in `app/worker.py` and worker dispatch remain the owners of
  pulling fresh and recovered work from the durable queue.
- `_chat_lock` remains the owner of per-chat execution serialization, but now
  inside the worker-owned execution path rather than as justification for
  keeping provider execution inline in Telegram update handlers.
- `execute_request()`, `request_approval()`, and replay execution remain the
  owners of terminal user-visible live execution outcome, but they must be
  entered from the worker-owned path for fresh work as well.
- `RunResult` in `app/providers/base.py` remains the provider outcome type.
- Provider subprocess lifecycle remains owned inside `app/providers/claude.py`
  and `app/providers/codex.py`.

Required implementation shape:

- Add `cancelled: bool = False` to `RunResult`.
- Extend the provider `run()` and `run_preflight()` contract to accept a
  separate cancel signal or execution-control object. Do **not** attach
  cancellation semantics to the `ProgressSink` protocol.
- Add durable dispatch metadata to the work-item contract, with an explicit
  column such as `dispatch_mode` whose shipped values in this phase are
  `fresh` and `recovery`.
- Make fresh provider-starting work worker-owned rather than inline:
  - Telegram message/approval/retry ingress writes durable work and returns
    quickly
  - worker dispatch must be able to tell “fresh live execution” from
    “recovered stale execution that needs recovery UX”
- Move every provider-starting entry point onto the worker-owned path:
  - fresh plain-message execution
  - approval preflight
  - approve-to-execute and retry-allow execution
  - replay/recovery execution
- Keep the required durable fresh-versus-recovered routing metadata on the
  authoritative work-item/dispatch contract rather than inventing a
  Telegram-only side channel.
- `recover_stale_claims()` must durably requeue stale claimed message work as
  recovery work, not as plain fresh queued work:
  - `state = 'queued'`
  - `worker_id = NULL`
  - `claimed_at = NULL`
  - `dispatch_mode = 'recovery'`
- Add an atomic durable admission API for fresh provider-starting messages.
  The admission decision must happen in one store transaction:
  - `duplicate` if the update already exists
  - `busy` if the chat already has fresh provider work in `queued` or
    `claimed`
  - `admitted` only if a new fresh work item was durably recorded
- The handler busy decision must be based on that durable admission API, not on
  `_LIVE_CANCEL`. `_LIVE_CANCEL` is too late for admission control because it
  only exists after provider execution/preflight actually starts.
- Add a small private live-execution registry keyed by `chat_id` in the
  worker-owned execution layer. Use it only for process-local cancellation
  signaling and cleanup. It must not become a second durable state model.
- Register the live execution record immediately before the provider call and
  clear it in a `finally` block on every exit path.
- `/cancel` must use a fast path that only checks the worker-owned live
  registry:
  - if a live execution exists, set the cancel signal immediately and return a
    user-facing cancellation-requested message
  - if no live execution exists, fall through to the current locked path for
    credential setup and pending approval/retry cancellation
- `execute_request()`, `request_approval()`, and replay execution must treat
  `result.cancelled` as a normal terminal handled outcome:
  - update the status message to cancelled
  - do not send the final result text
  - do not raise `LeaveClaimed`
  - let the work item complete normally
- Remove any hidden production code path that drains worker execution inline
  from `handle_message` for tests. Shared handler tests must drive the real
  worker-owned path explicitly rather than relying on a secret alternate
  runtime mode.
- Do not use PTB dispatcher concurrency, custom update processors, cutoff maps,
  or direct handler overlap as the production mechanism for dropping queued
  work. Enforce the one-live-run-per-chat policy explicitly in the worker-owned
  design.
- Busy/coalesced user messaging must be truthful. Do not say a request is
  “queued and will run next” unless a bounded queue policy was deliberately
  implemented and covered by tests.
- Provider state must not be destructively reset on user cancel. Only typed
  resume failure continues to justify provider-state reset.
- Provider cancellation must not depend on “the next stdout line.” The provider
  implementation must race the cancel signal against blocked reads and process
  exit so a silent or stalled subprocess can still be cancelled promptly.

Affected code paths:

- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`
- `app/telegram_handlers.py`
- `app/worker.py`
- `app/work_queue.py`
- `app/work_queue_sqlite_impl.py`
- `app/work_queue_pg.py`
- `app/work_queue_sqlite.py`
- `app/work_queue_postgres.py`
- `app/db/postgres_migrate.py`
- `app/main.py`
- `app/user_messages.py`
- `tests/support/handler_support.py`

Failure-path rules:

- Double-cancel is idempotent.
- Cancel after process exit is a safe no-op.
- Restart during cancellation drops the in-memory signal and falls back to the
  existing `LeaveClaimed` recovery contract.
- Unexpected cleanup failure is an ordinary execution failure, not a successful
  cancel.

Required invariants:

- `/cancel` during live execution does not depend on PTB dispatcher
  concurrency and does not wait behind a long-running Telegram update handler
- `/cancel` during pending approval/retry still behaves exactly as before
- `/cancel` with no live execution and no pending/setup still shows the current
  nothing-to-cancel behavior
- stale recovered message work never auto-runs as fresh provider work after
  restart; it always routes to recovery UX first
- no chat can accumulate more than one fresh provider-starting work item in
  `queued` or `claimed` at a time
- a second plain message during a live run, or while fresh provider work is
  already queued for that chat, does not accidentally reach the provider later
- fresh live work and stale recovered work take the correct distinct paths
- cancelled execution does not leave the work item in `claimed`
- cancelled execution does not send the final assistant reply
- cancelled execution does not corrupt provider state; the next request works
  normally
- live execution registry entries are always cleaned up
- shared tests do not rely on hidden inline execution paths in production code
- busy replies accurately describe rejection/coalescing behavior

Tests required for Slice 2:

- Contract test: cancel signal set during Claude execution returns
  `RunResult.cancelled=True` within bounded time
- Contract test: cancel signal set during Codex execution returns
  `RunResult.cancelled=True` within bounded time
- Transport-store contract: stale claimed work recovered on restart returns to
  `queued` with durable `dispatch_mode='recovery'`
- Transport-store contract: fresh provider-starting message admission is atomic
  and returns `duplicate`, `busy`, or `admitted` correctly
- Transport-store contract: `busy` admission does not leave a second fresh
  queued provider item for the same chat
- Worker-path integration: fresh plain message is executed from the worker-owned
  path, not inline in the Telegram handler
- Worker-path integration: recovered stale message work sends replay/discard
  notice and does not call the provider
- Worker-path integration: `/cancel` during live execution updates the status
  message to cancelled and final result text is not sent
- Worker-path integration: `/cancel` during approval preflight has the same
  semantics on the worker-owned path
- Transport-store/Postgres regression: two real connections racing
  `record_and_admit_message()` for the same chat yield exactly one `admitted`
  and one `busy`, with only one fresh runnable item remaining
- Credential regression: while a real background worker is alive, a
  credential-setup reply from the owning user is handled inline, creates no
  provider work item, and never reaches the provider
- Queue cancel regression: `/cancel` before worker claim moves the admitted
  fresh item to terminal `failed/cancelled` state and provider call count
  remains zero after worker drain
- Handler integration: `/cancel` with no live execution preserves the current
  no-op behavior
- Fan-out regression: while a live run is active, or while fresh work is
  already durably queued for that chat, additional plain messages do not
  increase provider call count and do not create another runnable fresh work
  item for that chat
- Distinction regression: fresh live work does not go through recovery-notice
  UX; recovered stale work still does
- Adjacent regression: cancelled execution does not corrupt provider state; the
  next request succeeds normally
- Cleanup regression: the live cancel registry entry is removed on both
  cancellation and ordinary completion
- Shared-handler regression: tests no longer depend on hidden inline worker
  execution inside `handle_message`

#### Slice 3 — Claude Progress Usability

Problem statement:

- Codex already emits structured semantic progress through the shared progress
  event family.
- Claude currently folds most tool activity into `ContentDelta` plus
  `tool_activity`, which makes long runs feel like a replacing wall of text
  instead of a tool-by-tool progression.

Contracts in this slice:

1. **Claude event mapping contract**
- Claude stream events must map to the existing shared `ProgressEvent` family
  when the raw stream proves those semantics.
- This slice reuses the current renderer and event types; it does not create a
  Claude-only progress layer.

2. **Claude text-delivery invariants**
- richer tool events must not break visible text accumulation, `content_started`
  semantics, final result text, or rate limiting

Source of truth:

- `app/providers/claude.py` `_consume_stream()` remains the only Claude raw
  event mapping owner.
- `app/progress.py` remains the shared event family and renderer.
- `TelegramProgress` in `app/telegram_handlers.py` remains the status-message
  editor and rate limiter; it must not gain Claude-specific rendering logic.

Required implementation shape:

- Reuse the existing `ProgressEvent` types already used by Codex:
  - `ToolStart`
  - `ToolFinish`
  - `CommandStart`
  - `CommandFinish`
  - `ContentDelta`
- Promote Claude `tool_use` boundaries into separate semantic events when the
  raw stream proves them.
- Keep `ContentDelta` for actual visible text output. Text accumulation remains
  authoritative for the live reply preview.
- Stop using `tool_activity` as the primary structure once a tool is promoted
  to its own semantic event.
- Emit `ToolFinish` or `CommandFinish` only when the raw Claude stream clearly
  proves an end boundary or command outcome. Do not fabricate tool finishes or
  exit codes.
- Keep `content_started` tied to the first text delta only, not tool events.
- Keep final result text byte-for-byte equivalent to today. Progress changes are
  display-only.
- Keep the renderer unchanged in this slice. If existing events are sufficient,
  no renderer or `ProgressSink` change is allowed.

Affected code paths:

- `app/providers/claude.py`
- `tests/test_progress.py`
- `tests/fixtures/progress/claude_trace.ndjson`

Required invariants:

- text content still accumulates and displays correctly
- tool events do not swallow or delay text delivery
- `content_started` is still set on first text delta only
- final result text is unchanged
- existing rate limiting behavior remains intact unless a semantic boundary
  event explicitly needs `force=True`
- heartbeat still does not overwrite recent provider progress

Tests required for Slice 3:

- Contract test: Claude stream with proven tool-use boundaries emits the
  expected `ToolStart` and, where justified by raw traces, `ToolFinish`
- Contract test: text deltas still emit `ContentDelta` without loss or delay
- Regression test: `content_started` still flips on the first text delta only
- Fixture test: updated Claude trace fixture produces the expected event
  sequence
- Adjacent regression: text-only Claude responses render identically to the
  current behavior
- Adjacent regression: existing Codex progress tests remain green unchanged

Non-deliverables for Slice 2 and Slice 3:

- no new transport states
- no new FSM or new workflow library
- no second durable cancellation system beyond the required durable
  `dispatch_mode`/fresh-vs-recovered routing metadata
- no new progress event family if the current one is sufficient
- no Claude-specific Telegram rendering path
- no parallel provider-progress system
- no Codex provider behavior changes unless a shared invariant is found broken
- no deferring durable recovery routing, atomic fresh admission, or removal of
  hidden inline test execution from the shipped design

#### Slice 4 — Worker-Path Cancellation Verification

Problem statement:

- Slice 2 moved fresh live execution onto the worker-owned path and Slice 3
  improved progress rendering, but the test suite must now prove the real
  worker-path concurrency and anti-fan-out contracts rather than direct handler
  overlap or PTB dispatcher tricks.
- The suite must also prove that durable recovery routing and atomic fresh
  admission work under the real worker-owned design, not just in narrow unit
  tests.
- The readline/cancel race inside `_consume_stream` and `consume_stdout` is
  tested with pre-set events and fake processes whose `readline()` returns
  immediately.  Neither proves the race resolves correctly when `readline()`
  is actually blocked on a real file descriptor.
- The anti-fan-out rule needs a real worker-path proof: while one run is live,
  extra messages and `/cancel` must not result in multiple provider executions
  unless an explicit bounded queue policy says so.

This is a test-only slice.  No production code changes.

Contracts being verified (not changed):

1. **readline/cancel race contract** — `asyncio.wait` with
   `FIRST_COMPLETED` resolves promptly when the cancel event fires while
   `readline()` is blocked on a real subprocess pipe.
2. **Worker-path cancel ingress contract** — `/cancel` completes and delivers
   the user-facing ack while a worker-owned live execution is active.
3. **Anti-fan-out contract** — a second plain message during a live run does
   not later execute accidentally.
4. **Two-stage UX ordering contract** — "Cancellation requested." is delivered
   before "Cancelled." appears on the status message, from a single real
   worker-owned execution.
5. **Recovery routing contract** — recovered stale claimed message work is
   surfaced as replay/discard recovery, not auto-replayed as fresh work.
6. **No hidden inline-path contract** — shared handler tests exercise the real
   worker-owned path and do not rely on production-only switches that run the
   provider inline from `handle_message`.

Source of truth:

- the worker-owned live-execution registry (initially `_LIVE_CANCEL` or its
  successor owner seam) is the in-memory cancel registry.
- `_chat_lock` in `app/telegram_handlers.py` is the per-chat serialization
  owner for worker-owned execution.
- `_consume_stream` in `app/providers/claude.py` and `consume_stdout` in
  `app/providers/codex.py` own the readline/cancel race.
- `worker_loop()` in `app/worker.py` owns the fresh-live-work execution lane.
- `cmd_cancel` in `app/telegram_handlers.py` owns the live-cancel command path.

Required tests:

1. **Readline/cancel race with real subprocess.**
   - Spawn a real subprocess that blocks on stdout (e.g.
     `python3 -c "import time; time.sleep(60)"`).
   - Pass a cancel event to `_consume_stream`.
   - Schedule `event.set()` after a short delay (e.g. 0.1s).
   - Assert `_consume_stream` returns within a bounded time (e.g. 2s).
   - Assert the subprocess was killed (`proc.returncode is not None`).
   - Assert no spurious text was accumulated beyond what was emitted
     before cancel.
   - Run the same test shape for Codex `_run_cmd` with a blocking
     subprocess and injected cancel event.

2. **Worker-path cancel dispatch.**
   - Use a `FakeProvider` whose `run()` awaits a gate event before
     returning, so worker-owned execution holds the live registry and
     `_chat_lock` for a controlled duration.
   - Start fresh work through the real worker-owned path, not direct
     overlapping handler calls.
   - Send `/cancel` through the ordinary command path while the worker-owned
     run is active.
   - Assert the cancel event was set and `run()` saw it.
   - Assert the user-facing "Cancellation requested." ack arrived before the
     worker-owned run completed.
   - Assert the live run ended with the cancelled outcome (status message
     shows "Cancelled.", no final text sent).

3. **Anti-fan-out under spam.**
   - While a worker-owned run is active, send one or more additional plain
     messages to the same chat.
   - Assert those extra messages do not increase provider call count.
   - Assert the user gets the expected busy/coalesced response and no later
     accidental provider execution occurs after cancellation/completion.

4. **Recovery routing under restart.**
   - Create a claimed stale message item and recover it through the durable
     store.
   - Assert the recovered item returns to `queued` with durable
     `dispatch_mode='recovery'`.
   - Dispatch it through the real worker-owned path.
   - Assert the provider is not called.
   - Assert replay/discard notice is sent and the item moves to
     `pending_recovery`.

5. **Two-stage UX ordering.**
   - From the same test as (2), collect all user-visible messages in
     delivery order from the worker-owned path.
   - Assert "Cancellation requested." appears strictly before "Cancelled."
     in the sequence.
   - Assert no other cancel-related text appears between them.

6. **Cancel mid-stream (partial output).**
   - Spawn a subprocess that emits a few lines of JSON then blocks.
   - Set cancel after partial output has been consumed.
   - Assert accumulated text contains the partial output.
   - Assert `RunResult.cancelled` is True.
   - Assert no text corruption (partial line, truncated JSON).

7. **Adjacent: cancel does not interfere with non-cancel paths.**
   - After the concurrency cancel test completes, send a new message
     to the same chat.
   - Assert the new request executes normally (not cancelled).
   - Assert `_LIVE_CANCEL` is clean for that chat.

8. **No hidden inline-path proof.**
   - Shared handler tests that need full execution must explicitly drain the
     worker path rather than depending on production code that secretly runs
     provider work inline from `handle_message`.
   - Assert no shared test harness switch is required to make handler tests see
     provider execution.

Failure-path coverage:

- Cancel event set after subprocess has already exited naturally: the
  readline returns `b""` first, `cancel.is_set()` check in the cancel
  path is a safe no-op.  Test (1) covers this by also testing cancel
  after a fast-exiting subprocess.
- Double `/cancel` during a single execution: the event is already set,
  `cmd_cancel` replies "Cancellation requested." again idempotently.
  Existing test covers this; worker-path test (2) can optionally send
  two `/cancel` commands.

Implementation rules:

- All tests use real `asyncio.Event` and `asyncio.gather` — no mocking
  of the event loop or wait primitives.
- Subprocess tests use `sys.executable` with inline scripts — no
  external binary dependencies.
- All concurrency tests have explicit timeouts via `asyncio.wait_for`
  so a broken race fails fast (2–5s) rather than hanging.
- Tests live in `tests/test_cancel.py` plus adjacent worker-path suites if a
  given contract is more naturally owned there; do not force a fake “single
  class” boundary if it weakens worker-path realism.
- Recovery-routing tests belong in the existing recovery/work-item integration
  suites, not in a dispatcher-only micro-suite that ignores the durable store.
- No production code changes in this slice.  If a test reveals a bug,
  the fix goes in a subsequent Slice 2 follow-up under the worker-owned
  execution design, not via PTB dispatcher-concurrency hacks.

Non-deliverables:

- No cross-process or durable cancel testing (cancel is in-memory by
  design; restart recovery is already tested elsewhere).
- No PTB dispatcher-concurrency proof-by-direct-handler-overlap.
- No Telegram network I/O beyond the existing test doubles.

#### Slice 5 — Transport Port And Simulator

Problem statement:

- The runtime is now centered on worker-owned execution and queue-owned
  admission, and Slice 5 has already shipped an initial transport foundation:
  - `app/transports/` owns `InboundEnvelope`, `ConversationIO`,
    `EditableMessageHandle`, and `TransportCapabilities`
  - fresh plain-message admission now crosses a project-owned boundary via
    `InboundEnvelope` -> `admit_fresh_message(...)`
  - worker-owned outbound output now uses the Telegram adapter over
    `ConversationIO`
  - the simulator now provides one ordered **text** output log over the
    current fake Telegram surface
- That foundation is intentionally partial, not the end-state:
  - handler-owned replies and callback UI still use PTB-shaped message/query
    objects directly
  - the simulator is still a handler-level harness (`handle_message` / `cmd_*`
    injection), not a transport-ingress harness
  - callback injection is still missing as a first-class simulator capability
- Slice 5 therefore remains both:
  - product architecture for future transports
  - test infrastructure for realistic simulated-transport E2E-style coverage

Current shipped foundation:

1. **Project-owned transport types and ports**
- `app/transport.py` remains the owner of normalized inbound event types
  (`InboundMessage`, `InboundCommand`, `InboundCallback`)
- `app/transports/types.py` adds `InboundEnvelope`
- `app/transports/ports.py` adds:
  - `ConversationIO`
  - `EditableMessageHandle`
  - `TransportCapabilities`

2. **Production use today**
- Fresh plain-message ingress now builds `InboundEnvelope` in
  `handle_message()` and passes it through `app/transports/admission.py`
- Worker-owned output and worker-owned status edits use
  `TelegramConversationIO`
- Handler-owned output is **not** fully ported yet:
  - help/welcome replies still use PTB message/chat methods
  - command/callback replies still use PTB message/query methods

3. **Simulator use today**
- `tests/support/conversation_simulator.py` is a handler-level runtime harness
- It injects through `handle_message()` / `cmd_*`
- It runs the real worker loop
- It exposes one ordered **text** output log that currently includes:
  - `reply_text`
  - `edit_text`
  - `chat.send_message`
  - `reply_photo` / `reply_document` captions or placeholders
  - bot `send_message` / `send_photo` / `send_document`
  - bot message `edit_text`
  - callback `answer`
  - callback `edit_message_text`
- It explicitly does **not** include markup-only edits
  (`edit_message_reply_markup`)
- It does **not** yet drive ingress through `InboundEnvelope`
- It does **not** yet expose callback injection as a first-class simulator API

Remaining architecture gap for full Slice 5 completion:

- unify handler-owned outbound behavior behind `ConversationIO`
- move from direct handler injection toward a transport-level delivery harness
  without making PTB internals the contract
- add callback injection on the simulator surface
- keep the project-owned transport port small and capability-driven while
  making it the primary runtime abstraction instead of a worker-only helper

Contracts in this slice:

1. **Project-owned transport contract**
- The runtime owns a transport-neutral inbound envelope around the existing
  `InboundMessage` / `InboundCommand` / `InboundCallback` family.
- The runtime also owns a transport-neutral outbound conversation port for:
  - sending text
  - sending files/images
  - editing status messages
  - answering user actions
  - exposing capabilities and one ordered user-visible event stream in tests
- Telegram becomes one adapter implementation of that contract, not the
  contract itself.

2. **Simulator contract**
- A project-owned simulator must be able to inject inbound events over time,
  run the real worker loop, and expose one ordered output log without using
  PTB internals as the primary realism target.
- The canonical simulated-transport cancel test must prove the real
  production path:
  - message admitted
  - worker-owned long-running provider starts
  - `/cancel` arrives during the run
  - ordering and terminal state are correct

3. **Future-transport contract**
- The transport port must be small and capability-driven so future adapters
  such as Slack, SMS, WhatsApp, iMessage, or email could implement it later.
- This slice does **not** implement those adapters now. It only defines and
  proves the shared contract.

Source of truth:

- `app/transport.py` remains the owner of normalized inbound event types.
- Transport-port modules under `app/transports/` own the outbound conversation
  contract and the transport-neutral envelope wrapper shipped in this slice.
- Telegram adapter code remains the owner of PTB-specific normalization and
  PTB-specific send/edit/callback wiring.
- The current simulator is a handler-level runtime harness; the full Slice 5
  target is a simulator that sits on the project-owned transport contract
  rather than behaving like a fake PTB dispatcher.

Required implementation shape:

- Preserve and extend the shipped transport-core seam:
  - `InboundEnvelope`
  - `ConversationIO`
  - `EditableMessageHandle`
  - `TransportCapabilities`
- Reuse the existing `InboundMessage`, `InboundCommand`, and `InboundCallback`
  types rather than creating a second inbound event family.
- Complete the Telegram adapter migration so handler-owned output and
  worker-owned output share the same project-owned outbound contract.
- Remove remaining ad hoc `_BotMessage`-style special casing in favor of the
  transport-owned output abstraction the handler path uses too.
- Keep Telegram-specific concerns such as callback payload encoding in the
  Telegram adapter layer.
- Build a simulator that:
  - injects inbound events through a project-owned delivery surface
  - starts/stops the real worker loop
  - records ordered text sends/edits/actions in one log
  - supports waiting on conditions such as “provider started” or “text X
    appeared”
- Do not make PTB `Application` internals the primary simulator target.
- Do not build a giant generic omni-channel framework; only extract the
  contract needed by today’s runtime and tests.

Affected code paths:

- `app/transport.py`
- `app/telegram_handlers.py`
- `app/worker.py`
- new transport-port module(s) under `app/`
- `tests/support/handler_support.py`
- new simulator support module(s) under `tests/support/`

Tests required for Slice 5:

- Simulator E2E-ish test: message → long-running provider → `/cancel` through
  the real worker-owned path, with one ordered output log proving:
  - cancellation ack appears
  - cancelled terminal status appears later
  - provider call count is 1
  - queue state and `_LIVE_CANCEL` cleanup are correct
- Simulator regression: cancel before worker claim produces the queued-cancel
  terminal state and provider call count remains 0
- Simulator regression: second fresh message while one run is admitted/active
  gets the busy/coalesced response and never becomes a second runnable fresh
  item
- Simulator regression: credential-setup reply while a worker is alive stays
  off the queue and never reaches the provider
- Simulator regression: recovered stale work with
  `dispatch_mode='recovery'` shows replay/discard recovery UX and never
  auto-runs as fresh work
- Handler/worker parity regressions proving the final port migration did not
  split user-visible behavior between PTB-direct and port-owned paths

Non-deliverables:

- No additional transport adapter implementations yet
- No PTB-dispatcher realism-for-its-own-sake harness
- No second inbound event family or second worker queue
- No transport-specific business-logic fork for Telegram versus simulator

Tests required for Phase 15 generally:

- Real handler/request-flow tests
- Real transport-store contract tests for fresh admission and recovery routing
- Contract tests for user-visible behavior and opt-in policy
- Regression tests for public/trust restrictions and execution-context
  invalidation
- Slice 2 provider, transport-store, worker-path, and handler cancel tests
- Slice 3 Claude trace and progress contract tests

Done when:

- Slice 2 ships worker-owned live execution and live cancellation of active
  provider execution and approval preflight without introducing a second
  cancellation system or unsafe PTB update concurrency, and without leaving
  dispatcher-concurrency or cutoff-map experiments in the shipped path.
- Slice 2 also ships durable `dispatch_mode` routing for recovered stale work,
  atomic per-chat fresh-work admission, truthful busy/coalesced messaging, and
  no hidden production code path that runs provider execution inline for tests.
- Slice 3 ships richer Claude progress by reusing the existing shared progress
  event family and renderer without degrading text delivery or Codex behavior.
- Slice 4 proves the cancel mechanism works under real worker-owned
  cooperative concurrency: readline/cancel race with real subprocesses,
  worker-path cancel ingress, anti-fan-out under spam, recovery routing,
  two-stage UX ordering, no hidden inline-path masking, and partial-output
  cancel. Test-only slice, no production code changes.
- Slice 5 end-state ships a small project-owned transport/output port plus a
  simulator that can drive the real worker-owned runtime through a realistic
  fake transport. Telegram remains one adapter over that port; future
  transports can implement the same contract later without forcing PTB
  internals into the business-logic core.
- **Current checkpoint (shipped foundation, not end-state):**
  - proof-hardening is complete (credential suite, queued-cancel contract and
    Postgres regression, stale comments)
  - transport types/ports are in place
  - fresh plain-message admission crosses the `InboundEnvelope` boundary
  - worker-owned outbound output uses the Telegram adapter over
    `ConversationIO`
  - canonical simulator E2E coverage exists
  - simulator remains a handler-level harness
  - handler-owned outbound behavior is not yet fully unified behind the port
  - transport-level ingress and callback injection are not yet complete
- New implementation work for Phase 15 continues to extend the current owners
  instead of building shadow abstractions around them.

### Phase 20 - Networked Multi-Agent Platform

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- No new surface or registry feature may bypass the existing
  workflow/state-machine model. Registry-originated actions must use the same
  underlying workflow ownership as Telegram.
- No parallel execution paths. Registry deliveries enter the local work queue
  and are processed by the same worker/state-machine core as Telegram messages.
- Registry is a delivery and visibility plane, not an execution engine.

Objective:

Build the product into a **networked multi-agent platform** with one public
registry control plane and many private bots.

End-state capability:

- A human can start work from **Telegram** or from the **Registry UI**.
- A product bot can refine requirements, ask follow-up questions, and plan work.
- The product bot can discover specialist bots by role, skills, tags, and
  description, and delegate work through the registry gateway.
- Bots may run on local desktops, private machines, VPS/cloud hosts, or
  same-host Docker containers without exposing public HTTP APIs.
- Telegram remains a supported, reduced surface.
- Registry UI is a richer, first-class alternate client.
- Both surfaces act on the same underlying conversation, workflow, and
  execution state.

Architecture principles:

- One authoritative execution core per bot (local worker-owned queue).
- One authoritative workflow/state-machine layer.
- One canonical conversation identity (`ConversationRef`).
- No surface-specific orchestration forks.
- No registry-side shadow execution engine.
- Bot-local worker/state-machine execution remains the final authority.
- Registry owns delivery routing, presence, discovery, and timeline mirroring.
- Bots do not expose public HTTP APIs in v1; they use outbound polling only.
- Registry is the only public component.

Network model:

- Bots poll the registry for: routed delegated tasks, registry UI user input,
  registry UI actions, and control signals (cancel/approve/reject).
- Bots use outbound authenticated HTTP with bearer tokens issued at enrollment.
- Routed work: originating bot submits to registry → registry queues to target
  bot poll queue → target bot executes locally → result flows back to registry
  → registry delivers to originating bot as `routed_result` delivery.

Bot configuration:

- `BOT_AGENT_MODE=registry|standalone`
- `BOT_AGENT_DISPLAY_NAME`, `BOT_AGENT_SLUG`, `BOT_AGENT_ROLE`
- `BOT_AGENT_TAGS`, `BOT_AGENT_DESCRIPTION`, `BOT_AGENT_SKILLS`
- `BOT_AGENT_REGISTRY_URL`, `BOT_AGENT_REGISTRY_ENROLL_TOKEN`
- `BOT_AGENT_POLL_INTERVAL_SECONDS`
- Registry-issued credentials (`agent_id`, `agent_token`, poll cursor) are
  stored in bot-local runtime state (`data_dir/agent/registry_state.json`),
  not written back to operator config.

Connectivity states:

- `connected`: registry mode with active registry connectivity
- `degraded`: registry mode configured but registry unreachable; local
  Telegram operation continues; polls retry with backoff
- `standalone`: bot intentionally not using registry
- `offline`: registry-side classification only; bot has missed heartbeats

Registry outage behavior:

- Bot still starts in degraded state.
- Telegram and local interaction remain fully functional.
- Discovery, delegation, and registry UI sync are unavailable.
- Bot retries registration, heartbeat, and poll in the background.
- `/doctor` and logs report degraded state clearly.

---

#### Phase 20 — Milestone Status

##### M1 — Shared Conversation Core and Surface Refactor

**Status: Complete.**

Outcome:
- Shared conversation and surface concepts are now part of the runtime
  contract rather than Telegram-only implementation detail.
- Surface selection is owned by the transport factory at the dispatch
  boundary.
- Registry and Telegram flows share the same worker-owned orchestration path.
- Simulator coverage includes registry-surface flows through the durable worker
  boundary.

Acceptance criteria (complete):
- [x] Telegram behavior is preserved after adapter migration
- [x] No surface-specific orchestration fork exists in worker_dispatch
- [x] Shared conversation identity is testable across both surfaces
- [x] Simulator covers registry-surface flows through ConversationIO
- [x] Registry surface dispatches through same state machine as Telegram

---

##### M2 — Docker Multi-Instance and Registry-First Wizard

**Status: Complete.**

Outcome:
- One checkout can run multiple bot instances with per-instance env files.
- Registry-backed setup is the default operator path, with explicit standalone
  support.
- Repo-owned bot and registry scripts provide the primary operational surface.

Acceptance criteria (complete):
- [x] One checkout can run product/dev/test-writer/reviewer bots
- [x] Wizard is usable by non-technical operators
- [x] No second checkout required

---

##### M3 — Registry Service, Store, and UI Shell

**Status: Complete.**

Outcome:
- The registry now provides the public control plane for enrollment,
  presence, discovery, routed delivery, and operator visibility.
- Bots and humans both have first-class APIs.
- Registry UI exists as a richer alternate client surface.

Acceptance criteria (complete):
- [x] Bots can enroll, register, heartbeat, and poll
- [x] Humans can view bots and conversations in UI
- [x] Registry is the only public service needed
- [x] Bot-to-bot routed task round-trip verified in integration tests

---

##### M4 — Bot Polling Client and Routed Work Execution

**Status: Complete, including safety-gap hardening.**

Outcome:
- Polling, delivery dispatch, and routed-task execution all enter the same
  local worker/state-machine path as Telegram messages.
- Registry-side deliveries cover input, actions, control, routed work, and
  routed results.
- Safety hardening is part of the milestone definition: busy deliveries retry,
  report failures do not corrupt completed work, bad deliveries do not poison
  the whole batch, and the background runtime survives unexpected handler
  errors.

Acceptance criteria (complete):
- [x] Bots do not need public APIs
- [x] Registry-routed work enters the same local execution core
- [x] Registry-originated actions use the same workflow/state-machine rules
- [x] Chat-busy deliveries are retried, not lost
- [x] Completed work is not marked failed on registry report failure
- [x] One bad delivery does not poison the poll batch
- [x] Poll runtime survives unexpected handler exceptions

---

##### M1 Closure Gate — Required Before Remaining M5 Work

**Status: Complete.**

Purpose:
- Finish the M1 refactor before deeper M5 work by removing remaining
  post-dispatch surface forks from orchestration code.
- Keep surface selection, trust semantics, and adapter construction owned by
  the transport factory rather than by handlers.
- Ensure simulator coverage proves registry-surface traffic through the real
  durable worker path.

Acceptance criteria (complete):
- [x] `grep -n "conversation_surface" app/telegram_handlers.py` returns zero
      results
- [x] `grep -n "_BotMessage" app/telegram_handlers.py` returns zero results
- [x] `skip_approval` round-trip tests pass in `test_transport.py`
- [x] Full suite passes: `python -m pytest -x -q`
- [x] `test_registry_routed_result_resumes_parent_conversation_without_new_approval`
      still passes
- [x] `test_registry_surface_input_respects_approval_mode` still passes
- [x] At least one simulator test exercises a registry-surface message end-to-end

---

##### M5 — Product-Bot Discovery and Delegation

**Status: Complete.**

Scope:
- Telegram can discover candidate specialist bots through the registry using
  structured capability search.
- Parent-side delegation state is durable in bot-local session state and child
  results resume orchestration through the same worker-owned path.
- Delegation uses an explicit user-facing plan and approval step before any
  routed work is submitted.
- Approved plans submit routed tasks through the registry and preserve retry
  semantics when registry connectivity is degraded.

Role patterns (metadata only, not hardcoded logic):
- product, requirements, developer, test-writer, reviewer, tester
- Any role/skill combination is valid; these are examples, not constraints

Acceptance criteria:
- [x] Product bot can search for specialist bots by role and skills
- [x] Discovery results presented before delegation (not automatic)
- [x] Delegation requires explicit user approval before fan-out
- [x] Delegated work routes through registry and executes through the same
      local worker-owned runtime on the target bot
- [x] Parent bot resumes orchestration after receiving child results
- [x] Degraded mode blocks delegation and tells the user why

---

##### M6 — Hardening, Docs, and E2E Confidence

**Status: Complete.**

Scope:
- Exponential backoff with jitter for degraded registry polling
- `/doctor` diagnostics for registry connectivity, enrollment, stale contact,
  and pending delegation approval state
- Docs aligned so README and ARCHITECTURE describe the shipped multi-agent
  system, degraded-mode contract, and operator-facing registry behavior

Acceptance criteria:
- [x] Degraded behavior is explicit, observable, and tested
- [x] `/doctor` reports registry connectivity, enrollment status, stale contact,
      and stale pending delegation approval state
- [x] README describes multi-agent mode and degraded-mode operator behavior
- [x] ARCHITECTURE describes the multi-agent registry, surface factory, and
      degraded-mode contract
- [x] Full suite is green after the hardening and doc-alignment changes

---

##### M7 — Registry UI: Conversation Timeline and Human-Initiated Work

**Status: Complete.**

Scope:
- Bot publishes timeline events to the registry so the registry has real
  content to show: conversation start, progress updates (rate-limited),
  and outcome (done/failed). These flow through `RegistryConversationIO`
  lifecycle hooks, not through a new side-channel.
- Registry UI renders a conversation detail view with timeline events,
  replacing the bootstrap-only read board with a drill-down interface.
- Registry UI exposes a "New conversation" form so a human can initiate
  work from the UI without Telegram.
- Auto-refresh (5 s) renders new timeline events live.

Implementation seams:
- `RegistryConversationIO.bind()` — publish `started` event
- `RegistryConversationIO.on_outcome()` — publish `completed` or `failed`
- `RegistryConversationIO` progress sink — rate-limit, publish `progress`
  events at most once per 5 s
- `/v1/agents/timeline` (POST, already implemented) — bot posts events
- `/v1/ui/conversations/{id}/timeline` (GET, already implemented) — UI
  fetches events
- `/v1/ui/conversations` (POST, already implemented) — UI starts a
  conversation; bot polls and processes it as a `registry_input` delivery
- Registry UI `/ui` shell — extend existing HTML/JS to add:
  - Conversation row click → detail panel with timeline
  - Timeline event list (kind, title, body, timestamp)
  - "New conversation" button + modal form (target bot, message text)
  - Auto-refresh at 5 s (same as main bootstrap poll)

What M7 does NOT include:
- Approval / reject actions from UI (requires control-action delivery
  round-trip; deferred to a follow-on slice)
- WebSocket / SSE real-time push (polling at 5 s is sufficient)
- Work-item status mirroring into registry (conversation timeline is
  the richer visibility surface; raw queue state stays bot-local)

Acceptance criteria:
- [x] Bot publishes timeline events via `RegistryConversationIO` for
      start, progress (rate-limited), and outcome
- [x] Timeline events appear in `GET /v1/ui/conversations/{id}/timeline`
- [x] Registry UI shows conversation detail with timeline on click
- [x] Human can start a conversation from the Registry UI targeting any
      connected bot; bot receives and processes it
- [x] Auto-refresh renders new timeline events within 10 s of publication
- [x] Rate-limiting: at most one progress event per 5 s per conversation
- [x] All existing surface contracts (Telegram, degraded mode) unchanged
- [x] Full suite passes, including E2E

---

##### M8 — Registry UI Actions and Delegation Completion

**Status: Complete.**

Why this milestone exists:

M7 adds the Registry UI conversation timeline and lets a human start work
from the UI. But two concrete UX gaps remain before Phase 20 is complete
from a non-technical user's perspective:

1. **Approval-from-UI gap.** After M7, a user who starts a conversation
   from the Registry UI and triggers a delegation plan cannot approve or
   cancel that plan from the UI — they must switch to Telegram. The
   backend action APIs (`POST /v1/ui/conversations/{id}/actions`,
   `POST /v1/ui/conversations/{id}/cancel`) already exist. The gap is
   entirely in the UI: no approve/cancel controls are wired to those
   endpoints. For a user who initiated work from the Registry UI, this
   is a broken flow with no alternative visible in the interface.

2. **Delegation completion message path.** When child bots finish and
   the parent bot receives `routed_result` deliveries, the parent
   re-enters the worker path. The current M5 implementation does not
   specify what final message is sent to the originating surface.
   From the user's perspective: they approved delegation, child bots
   ran, and nothing concludes — no final answer arrives in the Registry
   UI or Telegram. This path must be defined, implemented, and tested.

Scope:

**Part 1 — Approve/cancel delegation from Registry UI**

- When the conversation timeline contains a `delegation_proposed` event
  (a delegation plan awaiting approval), render approve and cancel
  buttons alongside it in the detail view.
- Approve button → `POST /v1/ui/conversations/{id}/actions` with
  `{"action": "approve_delegation"}`.
- Cancel button → `POST /v1/ui/conversations/{id}/cancel` or
  `{"action": "cancel_delegation"}` depending on the action contract
  established in `store.add_conversation_action`.
- The bot receives these as `action` deliveries via its existing poll
  path and routes them through `handle_delegation_approve` /
  `handle_delegation_cancel` — the same handlers Telegram callbacks use.
- Degraded mode: if the bot is not connected, the action is queued as a
  delivery and processed when connectivity returns. The UI shows
  "pending" until the bot acks.

**Part 2 — Delegation completion: parent bot final response**

- When all delegated tasks reach `completed` or `failed` state, the
  parent bot must send a final synthesized response to the originating
  surface (Registry UI or Telegram).
- The final response content: the parent bot re-runs a brief synthesis
  prompt incorporating the child task results, or (if synthesis is too
  expensive) sends a structured summary: "Delegation complete. N tasks
  finished. Here are the results: …"
- The response is sent via the originating `ConversationIO` surface —
  Telegram sends it as a message; Registry surface publishes it as a
  `completed` timeline event with the full result body.
- If any tasks failed, the response says so explicitly and offers a
  retry path.
- Durable state: `PendingDelegation` transitions from
  `submitted` → `completed` (all tasks done) or `partial_failed`
  (some tasks failed). These states must be defined in
  `app/agents/orchestration.py` and honored by the durable state
  machine.

**Part 3 — Bot side: action delivery routing**

- The bot's delivery handler already routes `action` deliveries through
  `app/agents/bridge.py`. Verify that `approve_delegation` and
  `cancel_delegation` action kinds are routed to the correct handlers
  with the correct `chat_id` and `conversation_ref` extracted from the
  delivery payload.
- The action delivery must carry the `conversation_ref` so the handler
  can load the correct session. If this field is missing from the
  current action delivery schema, add it.

Implementation seams:
- `app/agents/bridge.py` — route `approve_delegation` / `cancel_delegation`
  action deliveries to `handle_delegation_approve` / `handle_delegation_cancel`
- `app/telegram_handlers.py` — `_handle_delegation_approve` and
  `_handle_delegation_cancel` already exist; verify they work when
  invoked from registry delivery (not just from Telegram callback)
- `app/agents/orchestration.py` — define `completed` and `partial_failed`
  delegation states; add `all_tasks_terminal(delegation)` predicate
- `app/transports/registry_adapter.py` — `on_work_complete` publishes
  the final result as a timeline event with full body
- `app/registry_service/app.py` (UI) — approve/cancel buttons on
  delegation-proposed timeline events; "pending" state while awaiting
  bot ack

What M8 does NOT include:
- Retry of individual failed child tasks from UI (deferred; requires
  per-task action routing)
- Push notifications when delegation completes (deferred; polling at
  5 s is sufficient)
- Any change to the Telegram approval/cancel flow (must remain
  unchanged)

Acceptance criteria:
- [x] A user who starts a conversation from Registry UI and receives a
      delegation plan can approve or cancel it from the UI without
      switching to Telegram
- [x] When all delegated tasks complete, the parent bot sends a final
      result to the originating surface (Registry UI or Telegram)
- [x] When some tasks fail, the user sees which tasks failed and a clear
      next step
- [x] `PendingDelegation` status transitions to `completed` or
      `partial_failed` after all tasks reach terminal state
- [x] Action deliveries (`approve_delegation`, `cancel_delegation`) are
      routed to the correct handlers on the bot side and carry enough
      context (`conversation_ref`, `chat_id`) to load the right session
- [x] Telegram approval/cancel flow is unchanged
- [x] Degraded mode: actions queue and process on reconnect; UI shows
      pending state, not silent failure
- [x] Full suite passes, including E2E

---

##### M9 — First-Run Polish and Registry UI World-Class UX

M8 completes the multi-agent feature set. M9 is the commercial-polish pass: fix
every friction point that prevents a first-time user from successfully bringing
up a bot from a fresh `git clone`, and upgrade the Registry UI from a functional
prototype to a world-class, production-quality interface.

This milestone is triggered by a full first-run walkthrough that identified 17
concrete UX failures across the setup scripts, README, and Registry UI. Each is
addressed below.

---

**Section A — Provider Login Exit Confusion (critical)**

*Problem:* `scripts/provider/container_provider_login.sh` launches the Claude or
Codex CLI inside a Docker container and prints a brief instruction, but the user
has no visual cue inside the live CLI that they must exit when authentication is
complete. The current user experience: enter a live AI CLI session, complete the
login flow, and then be stuck — with no reminder that "exit" is the next step.

*Fix A1 — Pre-entry warning banner.*
Before launching the provider CLI, print a clearly bordered banner:

```
╔══════════════════════════════════════════════════════════════╗
║  ACTION REQUIRED — INSIDE THE CLAUDE CLI                     ║
║                                                              ║
║  1. Run:  /login                                             ║
║  2. Follow the browser link to authenticate.                 ║
║  3. When done — TYPE:  /exit   (or press Ctrl-D)             ║
║                                                              ║
║  You MUST exit the CLI to return to setup.                   ║
╚══════════════════════════════════════════════════════════════╝
```

*Fix A2 — Post-exit confirmation.*
After the CLI exits, print:
```
✓ Claude authentication complete. Returning to setup...
```
If the container exits with a non-zero code, print:
```
✗ Authentication may have failed (exit code N). Re-run this step
  if the provider health check fails in the next step.
```

*Fix A3 — Codex parity.*
`codex --login` has its own exit flow. Before launching codex, print the
equivalent banner explaining that `q` or `Ctrl-C` returns to setup once
authentication is complete.

*Implementation seam — exit code capture:*
The script uses `set -euo pipefail`. The provider CLI may exit non-zero even
on a clean auth session. Capture the exit code explicitly immediately after the
CLI call, then continue unconditionally to the post-exit message and the existing
health check. Do NOT use `|| true` to swallow the code. Pattern:

```bash
claude
exit_code=$?
if [ "$exit_code" -eq 0 ]; then
  echo "✓ Claude authentication complete. Returning to setup..."
else
  echo "✗ Authentication may have failed (exit code $exit_code). Re-run this"
  echo "  step if the provider health check fails in the next step."
fi
# fall through unconditionally to health check
```

The health check at the bottom of the script is the actual failure gate — the
post-exit message is informational only.

*Files:* `scripts/provider/container_provider_login.sh`

---

**Section B — Guided Start Script (guided_start.sh)**

*Pre-existing bugs to fix first:* The current `guided_start.sh` has three
orphaned variable assignments that must be removed before adding new features:
- Line that sets `registry_prompt=` is immediately overwritten by `registry_token=` — delete the orphaned line
- First of two `role=` assignments captures the tags prompt result before being overwritten by `tags=` — delete the orphaned line
- First of two `role=` assignments captures the skills prompt result before being overwritten by `skills=` — delete the orphaned line

*Problem B1 — Enrollment token prompt has no hint.*
When the user is asked "Registry enrollment token", they have no idea where to
find it. If the registry was just started locally (auto-started by
`auto_start_local_registry_if_needed`), the token is in `.env.registry` — but
the script never says so.

*Fix B1:* After auto-starting the local registry, read the enrollment token from
`.env.registry` automatically and skip the prompt entirely, printing:
```
  ✓ Enrollment token read from .env.registry (auto-configured)
```
If the user is connecting to a remote registry, prompt as before but add the
hint: `(check your registry's .env.registry or admin panel)`.

*Implementation seam — structural ordering:* This fix requires restructuring the
script flow. Currently `create_env_file_if_missing` runs before
`auto_start_local_registry_if_needed`, so the token is not yet in `.env.registry`
when the registry URL prompt fires. The fix splits prompt collection into two
phases: (1) collect bot name, token, provider, mode, and registry URL, write a
minimal env file; (2) call `auto_start_local_registry_if_needed` which starts the
registry and reads the token; (3) if local registry and token was auto-read,
append it to the env file silently; if remote registry, prompt for the token with
the hint. The `auto_start_local_registry_if_needed` function must also match
`http://172.17.0.1:8787` in its case statement alongside the existing
`host.docker.internal` and `localhost` variants.

*Problem B2 — Advanced field overload.*
12–14 interactive questions including Role, Tags, Description, and Skills confuse
first-time users. These fields have valid advanced use cases but are not needed
to get a working bot.

*Fix B2:* Add a "quick setup / full setup" fork at the top of prompt collection:
```
Setup mode? [quick/full] (quick):
```
- **quick** (default): ask only Bot name, Token, Provider, Mode (4–5 questions
  total, including registry URL if mode=registry). Write defaults: `working_dir=/home/bot`,
  `timeout=3600`, `allow_open=1`. Print at end: "Advanced settings (role, tags,
  description, skills) can be set by editing $BOT_ENV_FILE."
- **full**: current behavior, all prompts.

*Problem B3 — `host.docker.internal` fails on Linux.*
The default registry URL `http://host.docker.internal:8787` works on
macOS/Docker Desktop but is unreachable from Docker containers on Linux.

*Fix B3:* Detect the OS at prompt time. On Linux, default to
`http://172.17.0.1:8787` and add a comment in the generated env file:
```
# Registry URL: use host.docker.internal on macOS/Windows, 172.17.0.1 on Linux.
```
Detection: `if [ "$(uname -s)" = "Linux" ]; then default_registry_url="http://172.17.0.1:8787"; fi`

*Problem B4 — No success summary.*
After `./scripts/app/start_instance.sh` succeeds, the script prints minimal
output. The user doesn't know what they have, how to use it, or what to do next.

*Fix B4:* Replace the final plain-text echo block with a boxed success summary:
```
╔══════════════════════════════════════════════════════════════╗
║  Bot is running!                                             ║
║                                                              ║
║  • Open Telegram and message your bot to start.              ║
║  • Registry UI: http://localhost:8787  (if registry mode)    ║
║  • Logs:  ./scripts/app/logs_instance.sh default             ║
║  • Stop:  ./scripts/app/stop_instance.sh default             ║
╚══════════════════════════════════════════════════════════════╝
```
The registry UI line is omitted in standalone mode. The registry URL shown must
be the actual URL from the env file, not a hardcoded localhost — read it with
`grep -E '^\s*BOT_AGENT_REGISTRY_URL='` from `$BOT_ENV_FILE`. Box lines are
exactly 64 characters wide (matching Section A banners). Use `printf` for the
variable-width registry URL line to pad correctly.

*Files:* `scripts/app/guided_start.sh`, `scripts/lib_env.sh` (if needed)

---

**Section C — Registry Start Script (registry/start.sh)**

*Problem:* The script creates `.env.registry` and prints "Enrollment token is
stored in .env.registry" but never prints the actual token value. The user must
open the file to find it.

*Fix C1:* After writing `.env.registry`, extract and print the enrollment token.
The file is already sourced via `set -a; . "$ENV_FILE"; set +a` before the
`docker compose` call, so `$REGISTRY_ENROLL_TOKEN` is in scope. Print it:
```bash
echo "Enrollment token: $REGISTRY_ENROLL_TOKEN"
echo "(also stored in $ENV_FILE — keep this file private)"
```
This applies on both first-run (token just generated) and subsequent runs (token
already in file). The existing `echo "Enrollment token is stored in $ENV_FILE."`
line is replaced, not supplemented.

*Files:* `scripts/registry/start.sh`

---

**Section D — README**

*Problem D1 — Redundant Step 2 and lost registry URL.*
Step 2 says "Start the registry" with `./scripts/registry/start.sh`. But
`guided_start.sh` already calls `auto_start_local_registry_if_needed()` which
starts the registry automatically for localhost URLs. The README makes users do
this manually before running guided setup — so the registry starts twice. Worse:
the user runs Step 2, the registry URL is printed to the terminal, and then they
immediately get buried in 12–14 `guided_start.sh` questions. By the time setup
finishes, the URL has scrolled off or been forgotten. It is never reprinted at
the end of setup.

*Fix D1:* Collapse into one command. Replace Steps 2 and 3 with:
```
./scripts/app/guided_start.sh
```
Add a note: "If you chose registry mode, the registry starts automatically."
Keep a separate "Manual registry start" section for advanced use.
The success summary (Fix B4) must reprint the registry URL so it is the last
thing the user sees — not something that scrolled past mid-setup.

*Problem D2 — No BotFather link or new-bot walkthrough.*
The README says "you need a Telegram bot token" but doesn't explain how to get
one. First-time Telegram bot users don't know about BotFather.

*Fix D2:* Add a "Create your bot token" subsection:
```
1. Open Telegram → search for @BotFather → tap Start
2. Send: /newbot
3. Follow the prompts (choose a name, choose a username ending in "bot")
4. Copy the token BotFather gives you — you'll need it in setup
```

*Problem D3 — "What You Need" lists enrollment token as a prerequisite.*
The prerequisites section says "Registry enrollment token (from your registry
admin)". This makes the registry sound like an external dependency. For the
common case (local registry), the token is auto-generated.

*Fix D3:* Replace the enrollment token prerequisite with: "Registry enrollment
token — auto-generated if you start a local registry (see below)."

*Problem D4 — No "what success looks like."*
After completing setup, the user has no reference point for whether it worked.

*Fix D4:* Add a "Verify it's working" section at the end of Quick Start:
```
Open Telegram, find your bot (search for its username), and send:
  What files are in my working directory?
You should receive a response within a few seconds.

If using registry mode, open http://localhost:8787 to see the bot listed
as connected and the conversation appearing in real time.
```
The suggested first message must be something guaranteed to work — not
"review this diff" (requires a diff) or "hello" (underuses the product).
"What files are in my working directory?" exercises the full pipeline with
no prerequisites and gives an immediate, concrete, non-trivial response.

*Problem D5 — Working directory note causes confusion.*
A note about the bot's working directory appears mid-setup in a context where
it's confusing. New users don't know what a "working directory" means in this
context.

*Fix D5:* Move to a "Configuration" or "Troubleshooting" section at the bottom.
In Quick Start, keep only the default (`/home/bot`) with no explanation.

*Problem D6 — No Registry UI screenshot or description.*
The Registry UI is one of the product's primary differentiators — it provides
real-time conversation visibility, multi-bot management, and (after M7/M8)
human-initiated work and delegation approval. It is completely invisible in the
README. A user who reads the README has no idea the UI exists or what it looks
like.

*Fix D6:* Add a "Registry UI" section with:
- A screenshot saved to `docs/registry-ui-screenshot.png`, taken after M9 UI
  fixes (E1–E9) are complete so the screenshot reflects the polished state.
  Reference it in the README as `![Registry UI](docs/registry-ui-screenshot.png)`.
- A one-paragraph description: what the three panels show (Bots, Conversations,
  Routed Tasks), what makes it different from Telegram (real-time timeline,
  multi-bot view, approval flow, shareable conversation link), and the URL
  (`http://localhost:8787` for local setups).

*Files:* `README.md`, `docs/registry-ui-screenshot.png`

---

**Section E — Registry UI**

*Design direction to preserve:* The existing design is aesthetically considered
and distinctive. The warm cream palette (`#f7f3ea`, `#fffaf1`), teal accent
(`#0f766e`), radial gradient header highlight, backdrop blur on cards, 20px
border-radius, and soft box shadows are coherent and polished. In a static
screenshot the UI looks professional. All fixes below must preserve this design
direction. The goal is to make the UI functional and complete — not to restyle it.

*Problem E1 — IBM Plex Sans never loads.*
The CSS declares `font-family: "IBM Plex Sans", ...` but no `<link>` to Google
Fonts or a local font file exists. The UI falls back to system fonts inconsistently.

*Fix E1:* Add `<link rel="preconnect" href="https://fonts.googleapis.com">` and
the IBM Plex Sans import, OR switch to a system-font stack that looks polished on
all platforms:
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
```
The system-font stack is the recommended fix: zero network dependency, loads
instantly, matches OS conventions.

*Problem E2 — No interactivity; no click targets; no hover states.*
All items in the Bots, Conversations, and Routed Tasks panels render as static
divs. Nothing is clickable. There are no hover states, no `cursor: pointer`,
no visual affordance that any action is possible. A user looking at this UI
cannot tell whether it is broken or intentionally a read-only board.

*Fix E2:*
- Wrap each item in a `<button>` or add `cursor: pointer` + `tabindex="0"` +
  `role="button"` + `onkeydown` handler for Enter/Space.
- Add hover state to `.item` CSS:
  ```css
  .item { cursor: pointer; transition: background 0.15s; }
  .item:hover { background: rgba(255, 255, 255, 0.08); }
  ```
- On click, open the existing detail side-panel (which already exists for
  conversations). Wire it to bots and routed tasks as well, or at minimum extend
  the existing conversation detail panel path for all item types.
- All interactive elements must be keyboard-accessible (Enter/Space to activate).

*Problem E3 — No loading state.*
On initial load, the three panels immediately render "Nothing yet." before the
first fetch resolves. On any network latency — including a healthy local server —
this looks like an empty, broken page. There is no spinner, skeleton, or any
indication that data is loading.

*Fix E3:*
- On page load, initialize each panel's `innerHTML` to
  `<div class="loading-state">Loading…</div>` before the first fetch fires.
  CSS: `.loading-state { text-align: center; padding: 2rem; color: #888; }`
- On subsequent polls (after the first successful load), show a non-disruptive
  "Refreshing…" badge in the header — not a full spinner — so browsing is not
  disrupted.
- Skeleton cards are an acceptable alternative to the loading-state div.

*Problem E4 — No last-refreshed indicator.*
The user has no way to know how fresh the data is or whether the UI is still
connected.

*Fix E4:* Add a `<span id="last-updated">` element in the header or footer.
Record `lastSuccessfulLoad = Date.now()` after each successful `loadBootstrap()`.
Update the display every second via `setInterval`:
```js
setInterval(() => {
  if (!lastSuccessfulLoad) return;
  const age = Math.floor((Date.now() - lastSuccessfulLoad) / 1000);
  const el = document.getElementById("last-updated");
  if (!el) return;
  el.textContent = age < 5 ? "Just updated" : `Updated ${age}s ago`;
  el.style.color = age > 60 ? "#ef4444" : age > 30 ? "#f59e0b" : "#6b7280";
}, 1000);
```
Call `clearErrorBanner()` (see E6) on each successful load so the banner
and the age indicator are in sync.

*Problem E5 — Raw API strings for status; no color coding.*
Status values are displayed as raw strings (e.g., "connected", "degraded",
"standalone"). There is no visual distinction between healthy, warning, and error
states.

*Fix E5:* Replace raw strings with styled badge chips. Add CSS color variants:
```css
.badge-connected  { background: #22c55e; color: #fff; }
.badge-degraded   { background: #f59e0b; color: #fff; }
.badge-standalone { background: #6b7280; color: #fff; }
.badge-pending    { background: #3b82f6; color: #fff; }
.badge-failed     { background: #ef4444; color: #fff; }
.badge-running    { background: #3b82f6; color: #fff; }
.badge-open       { background: #22c55e; color: #fff; }
.badge-cancelling { background: #f59e0b; color: #fff; }
.badge-completed  { background: #6b7280; color: #fff; }
```
Add a JS helper:
```js
function getBadgeClass(status) {
  const s = (status || "").toLowerCase().replace(/[^a-z]/g, "");
  const map = {
    connected: "badge-connected", degraded: "badge-degraded",
    standalone: "badge-standalone", pending: "badge-pending",
    failed: "badge-failed", running: "badge-running",
    open: "badge-open", cancelling: "badge-cancelling",
    completed: "badge-completed",
  };
  return map[s] || "";
}
```
Replace all `<span class="badge">${escapeHtml(status)}</span>` with
`<span class="badge ${getBadgeClass(status)}">${escapeHtml(status)}</span>`.

*Problem E6 — Full-page error replacement.*
On fetch failure, `document.body.innerHTML = rawErrorText` replaces the entire
UI with a developer-facing error dump.

*Fix E6:* Replace `document.body.innerHTML = ...` error handling with an inline
banner that is shown/hidden without destroying the page. JS pattern:
```js
function showErrorBanner(message) {
  let banner = document.getElementById("error-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "error-banner";
    banner.className = "error-banner";
    banner.setAttribute("role", "alert");
    document.body.prepend(banner);
  }
  banner.textContent = `⚠ Could not refresh data. Retrying… (${message})`;
  banner.style.display = "block";
}
function clearErrorBanner() {
  const banner = document.getElementById("error-banner");
  if (banner) banner.style.display = "none";
}
```
CSS:
```css
.error-banner {
  background: #fef2f2; border-left: 4px solid #ef4444;
  color: #991b1b; padding: 0.75rem 1rem; margin-bottom: 1rem; display: none;
}
```
Call `showErrorBanner(error.message)` on fetch failure, `clearErrorBanner()` on
next successful fetch. Never assign to `document.body.innerHTML`.

*Problem E7 — ASCII arrow in routed task display.*
Routed tasks show source and target with ` -> ` (literal ASCII). This looks
unfinished.

*Fix E7:* Replace with a Unicode arrow `→` or an SVG arrow icon.

*Problem E8 — Empty state is bare.*
When no bots, conversations, or tasks exist, the panel shows:
```
Nothing yet.
```
This communicates nothing useful to a new user.

*Fix E8:* Replace bare "Nothing yet." with per-panel instructional empty states.
Use a `EMPTY_STATES` map keyed by panel, rendered via `innerHTML` into a styled
`.empty-state` div:
```js
const EMPTY_STATES = {
  bots: "No bots connected yet. Start a bot in registry mode and it will appear here.<br><code>./scripts/app/guided_start.sh</code>",
  conversations: "No conversations yet. Send a message to your bot in Telegram to start.",
  tasks: "No routed tasks yet. Delegated tasks appear here in real time.",
};
```
CSS: `.empty-state { padding: 1.5rem; text-align: center; color: #888; font-size: 0.9rem; line-height: 1.6; }`

*Problem E9 — No favicon, no brand mark; tab title is default.*
The browser tab shows "Agent Registry" with the default browser icon. On a
desktop with many tabs this is indistinguishable.

*Fix E9:*
- Add an inline SVG favicon in `<head>` — no external files required:
  ```html
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%230f766e'/><text x='16' y='22' font-size='18' font-family='sans-serif' fill='white' text-anchor='middle'>A</text></svg>">
  ```
- `<title>Agent Registry</title>` is already present. If `REGISTRY_DISPLAY_NAME`
  env var is set, prepend it: `{display_name} — Agent Registry`. This lets
  operators with multiple registries distinguish tabs. If the env var is absent,
  leave the title as `Agent Registry`.

*Files:* `app/registry_service/app.py` (all inline HTML/CSS/JS)

*Implementation note — acceptance for M9 is operator-facing:* Most of M9 lives
in shell scripts, README, and inline frontend HTML/CSS/JS. Acceptance should be
proven with operator-script and README contract coverage, a live registry UI
render check, and a fresh screenshot captured from the running local registry
after the UI polish is complete.

---

**Files to change:**

| File | Sections |
|---|---|
| `scripts/provider/container_provider_login.sh` | A1–A3 |
| `scripts/registry/start.sh` | C1 |
| `scripts/app/guided_start.sh` | B1–B4 (+ pre-existing bug fixes) |
| `README.md` | D1–D6 |
| `app/registry_service/app.py` | E1–E9 (inline HTML/CSS/JS only) |
| `docs/registry-ui-screenshot.png` | D6 (screenshot taken after E fixes) |

**Implementation order within M9:**

1. A1–A3: Provider login banners (highest impact, single file, quick)
2. C1: Registry start token print (quick, single line)
3. B1–B4: Guided start script improvements (including auto-read token, quick
   mode, Linux default, success summary with registry URL reprinted)
4. D1–D6: README updates (collapse steps, BotFather, verified-first-message,
   working-dir relocation, Registry UI section with screenshot)
5. E1–E9: Registry UI polish (largest scope, self-contained; preserve existing
   design aesthetic throughout)

**What M9 does NOT include:**
- Registry UI real-time push (WebSocket/SSE) — deferred
- Registry UI authentication/login — deferred
- Telegram bot UI changes — out of scope
- Provider login flow changes to Docker image (no Dockerfile changes needed;
  all fixes are in shell scripts)

**Acceptance criteria:**
- [ ] A user following README Quick Start from `git clone` to first bot message
      can complete setup without confusion, without external documentation, and
      without needing to discover any step on their own
- [ ] Provider login script prints an explicit banner before launching the
      provider CLI stating what the user must do and how to exit; confirms
      success or failure after the CLI exits
- [ ] `guided_start.sh` quick mode asks ≤ 5 questions and works end-to-end
      for both registry and standalone modes
- [ ] `guided_start.sh` auto-reads the enrollment token for local registries
      with no manual token entry; prompts with a "where to find it" hint for
      remote registries
- [ ] `guided_start.sh` defaults to a platform-appropriate registry URL
      (`host.docker.internal` on macOS/Windows, `172.17.0.1` on Linux)
- [ ] `guided_start.sh` success summary reprints the registry URL, first-
      message suggestion, log command, and stop command as the final output
- [ ] `./scripts/registry/start.sh` prints the enrollment token value at
      startup alongside the note that it is stored in `.env.registry`
- [ ] README has a BotFather walkthrough with the token creation flow fully
      described; no external knowledge required to create a bot
- [ ] README "verify it's working" section recommends a first message that
      exercises the full pipeline with no prerequisites
      ("What files are in my working directory?")
- [ ] README has no redundant manual steps that `guided_start.sh` performs
      automatically; registry start is a single command
- [ ] README includes a Registry UI section describing what the UI shows and
      includes a screenshot or visual reference
- [ ] Registry UI uses a system-font stack; design aesthetic (cream palette,
      teal accent, radial gradient, backdrop blur, 20px radius, box shadows)
      is preserved
- [ ] Registry UI items have hover states and click targets; at least a
      basic detail view on click; keyboard-accessible
- [ ] Registry UI shows a loading spinner on initial load; a non-disruptive
      "Refreshing..." indicator on subsequent polls
- [ ] Registry UI shows a "last updated N seconds ago" indicator that ages to
      amber (> 30 s) and red (> 60 s)
- [ ] Status values are rendered as color-coded badge chips with the correct
      color for connected/degraded/standalone/pending/failed
- [ ] Fetch errors show an inline dismissable banner, not a full-page
      replacement; banner clears on next successful poll
- [ ] Routed task arrows use Unicode `→`, not ASCII ` -> `
- [ ] Empty states per panel have instructional text explaining how to populate
      them, not bare "Nothing yet."
- [ ] A favicon using the teal accent color is present; tab title is specific
      enough to identify the instance
- [ ] Full suite passes

---

##### M10 — Operations, Visibility, and Platform Maturity

**Why this milestone exists.**
After M9, first-run setup is polished and the Registry UI is world-class in presentation. M10 closes the operational gap between a demo-ready bot and one that a small team can run in production without constant operator intervention. It adds the six properties that every real deployment eventually requires: security (authenticated UI), observability (cost and usage visibility), maintainability (upgrade path), discoverability (search and filter), team safety (live user access control), and data portability (export and notifications). Two additional sections cover the highest-leverage power-user features: skills management from the UI and a stabilised programmatic trigger API. None of these require changes to the provider layer or the durable workflow core.

---

###### A. Registry UI Authentication

**Problem.**
The Registry UI is currently unauthenticated. Any process that can reach the port can read the full conversation history, send delegation actions, and invoke control actions. `REGISTRY_UI_TOKEN` exists as a config key but is only used as a query-parameter hint in guided_start.sh's success summary. It is not enforced server-side.

**Fix.**
Introduce a minimal single-password login form. The `REGISTRY_UI_TOKEN` value becomes the password. On successful login the server issues a short-lived session cookie (`registry_session`). All `/ui` and `/v1/ui` routes check for a valid session cookie; requests without one are redirected to `/ui/login` (GET) or rejected with 401 (API routes).

**Implementation seams.**

- `app/registry_service/app.py` — add two routes:
  - `GET /ui/login` — returns a styled inline HTML login form. Form POSTs to `/ui/login`.
  - `POST /ui/login` — reads `password` from form body, compares to `REGISTRY_UI_TOKEN` using `hmac.compare_digest`. On match: set `Set-Cookie: registry_session=<token>; HttpOnly; SameSite=Strict; Path=/` (64-char random hex, stored in a module-level dict mapping token → expiry). Redirect to `/ui`. On failure: re-render login form with an error message. No username field — single shared password.
  - `GET /ui/logout` — clears the cookie, redirects to `/ui/login`.
- Add a `_require_auth(request)` helper that reads the `registry_session` cookie, validates it against the in-memory session store, and returns the session or raises `web.HTTPFound("/ui/login")`.
- Call `_require_auth` at the top of every handler that serves `/ui` HTML or `/v1/ui` JSON. API routes return 401 JSON `{"error": "unauthorized"}` instead of redirecting.
- Session expiry: 24 hours from last use. Each validated request resets the expiry. No persistent session store — restart clears sessions (acceptable for single-operator use).
- If `REGISTRY_UI_TOKEN` is empty or not set, authentication is bypassed entirely (dev/local mode). Log a warning at startup.
- Login form CSS: match the existing dark theme (background `#0f172a`, card `#1e293b`, teal button `#0f766e`). Single centered card, 320 px wide, input and button full-width.
- Add a small "Logout" link to the top-right of the Registry UI nav bar (visible only when authenticated).

**Files to change.**
- `app/registry_service/app.py` — add login/logout routes, `_require_auth`, session store, nav bar logout link.
- `scripts/registry/start.sh` — `REGISTRY_UI_TOKEN` already generated and stored in `.env.registry`. No change needed.
- `docs/OPERATORS.md` (or equivalent) — note that restarting the registry service clears all active sessions.

**What M10A does NOT include.**
- Multi-user accounts or per-user permissions (M11+).
- OAuth / SSO.
- Persistent session storage across restarts.
- Rate limiting on the login endpoint (acceptable for single-operator use; add in M11 if needed).

---

###### B-0. Transport Store Abstraction Integrity and Postgres Parity

**Problem.**
M10E introduced three abstraction violations that leave the Postgres runtime broken for all new M10 transport features:

1. **`app/access.py` bypasses the transport-store abstraction.** It imports `sqlite3` directly, opens `data_dir/transport.db` with a short-lived `sqlite3.connect()` on every access check, and is never exercised by the Postgres backend. The module's own docstring says it is "intentionally leaf-level" and "depends only on config and transport-normalized user identity." That contract is broken.

2. **`work_queue_postgres.py` is missing `get_user_access`, `set_user_access`, and `list_user_access`.** These methods were added to `work_queue.py` (facade) and `work_queue_sqlite.py` but never implemented in `PostgresTransportStore`. Any Postgres-backed deployment calling `/allowuser`, `/blockuser`, or `is_allowed()` will raise `AttributeError` at runtime.

3. **No Postgres migration for `user_access` or `usage_log`.** SQLite's `_CREATE_SQL` at schema version 5 includes both tables. The Postgres migration set stops at `0002_work_items_dispatch_mode.sql`. A Postgres deployment is missing both tables entirely.

4. **The transport store contract test was not extended.** `tests/contracts/test_transport_store_contract.py` is the enforcement mechanism that runs every transport method against both backends. New methods were added to the SQLite store without simultaneously adding them to the contract test. The Postgres tests appeared green because they were blind to the new surface — not because the surface was correct.

**Root cause pattern.**
The M10E implementation read `work_queue_sqlite.py` but not `work_queue_postgres.py` or `work_queue_pg.py`, and did not extend the contract test. Every new method on the transport facade must have: (a) a Postgres implementation, (b) a Postgres migration, and (c) a contract test entry — in the same commit. Without (c), breakage is silent.

**Fix.**
Seven changes across eight files restore the invariant:

1. `app/access.py` — remove all DB access. Become purely policy.
2. `app/work_queue_sqlite.py` — fix `get_user_access` to not create `transport.db` when the file is absent (i.e., before the first message arrives on first boot).
3. `app/work_queue_pg.py` — add `get_user_access_override`, `set_user_access`, `list_user_access` as conn-based functions.
4. `app/work_queue_postgres.py` — add `get_user_access`, `set_user_access`, `list_user_access` wrapper methods delegating to `work_queue_pg`.
5. `app/db/migrations/postgres/0003_user_access_usage_log.sql` — new migration adding `user_access` and `usage_log` tables to `bot_runtime`.
6. `app/telegram_handlers.py` — update the `is_allowed()` wrapper to fetch the override through the facade before calling the pure policy function.
7. `tests/contracts/test_transport_store_contract.py` — add `user_access` contract cases that run against both SQLite and Postgres.
8. `CLAUDE.md` — add a standing rule: every new facade method must be in the contract test in the same commit.

**Implementation seams.**

**`app/access.py`**

Remove:
- `import sqlite3`
- `from pathlib import Path`
- `_db_access_override(data_dir, user_id)` function

Add:
```python
def is_allowed_user_with_override(
    config: BotConfig, user, override: str | None
) -> bool:
    """Apply DB override precedence on top of config baseline.

    override: 'allowed' | 'blocked' | None (no DB row found).
    Call sites fetch override from work_queue.get_user_access before calling this.
    """
    inbound = to_inbound_user(user)
    if inbound is None:
        return False
    if override == "blocked":
        return False
    if override == "allowed":
        return True
    return is_allowed_user(config, user)
```

Change `is_allowed_user(config, user)` to remove the DB call entirely — it becomes config-only:
```python
def is_allowed_user(config: BotConfig, user) -> bool:
    """Config baseline — no DB lookup.

    Use is_allowed_user_with_override when a live DB override is needed.
    """
    inbound = to_inbound_user(user)
    if inbound is None:
        return False
    if config.allow_open:
        return True
    if not config.allowed_user_ids and not config.allowed_usernames:
        return False
    return (
        inbound.id in config.allowed_user_ids
        or inbound.username in config.allowed_usernames
    )
```

`is_admin_user`, `is_public_user`, and `trust_tier` are unchanged.

The result: `access.py` has no storage imports, no `Path`, no file I/O of any kind.

**`app/work_queue_sqlite.py` — `get_user_access`**

The current implementation calls `self._transport_db(data_dir)` which creates `transport.db` as a side effect. `is_allowed()` runs before `record_and_admit_message` on every message — so on first boot, before any message is ever admitted, `transport.db` does not yet exist. Creating it just to answer "no override" would create an empty DB and confuse the migration path.

Replace:
```python
def get_user_access(self, data_dir: Path, user_id: int) -> str | None:
    conn = self._transport_db(data_dir)
    return work_queue_sqlite_impl.get_user_access_override(conn, user_id)
```

With:
```python
def get_user_access(self, data_dir: Path, user_id: int) -> str | None:
    # Use cached connection if already open (normal case after first message)
    if data_dir in self._connections:
        return work_queue_sqlite_impl.get_user_access_override(
            self._connections[data_dir], user_id
        )
    # DB not yet open — do not create it just for a read-only override check
    if not (data_dir / "transport.db").exists():
        return None
    # File exists but not cached — open normally (runs migrations)
    conn = self._transport_db(data_dir)
    return work_queue_sqlite_impl.get_user_access_override(conn, user_id)
```

**`app/work_queue_pg.py` — three new conn-based functions**

Add after the existing functions, matching the SQLite impl shape exactly:

```python
def get_user_access_override(conn, user_id: int) -> str | None:
    """Return 'allowed', 'blocked', or None when no override exists for user_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT access FROM bot_runtime.user_access WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_user_access(
    conn,
    user_id: int,
    access: str,
    reason: str,
    granted_by: int,
) -> None:
    """Upsert a user access override row."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bot_runtime.user_access
                   (user_id, access, reason, granted_by, granted_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (user_id) DO UPDATE SET
                   access = EXCLUDED.access,
                   reason = EXCLUDED.reason,
                   granted_by = EXCLUDED.granted_by,
                   granted_at = EXCLUDED.granted_at""",
            (user_id, access, reason, granted_by, now),
        )
    conn.commit()


def list_user_access(conn) -> list[dict]:
    """Return all user access overrides ordered by most recent grant first."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, access, reason, granted_by, granted_at "
            "FROM bot_runtime.user_access ORDER BY granted_at DESC"
        )
        rows = cur.fetchall()
    return [
        {
            "user_id": r[0],
            "access": r[1],
            "reason": r[2],
            "granted_by": r[3],
            "granted_at": r[4],
        }
        for r in rows
    ]
```

**`app/work_queue_postgres.py` — three new wrapper methods**

Add after the existing `purge_old` method, following the exact pattern of every other method in `PostgresTransportStore`:

```python
def get_user_access(self, data_dir: Path, user_id: int) -> str | None:
    with self._conn() as conn:
        return work_queue_pg.get_user_access_override(conn, user_id)

def set_user_access(
    self,
    data_dir: Path,
    user_id: int,
    access: str,
    reason: str = "",
    granted_by: int = 0,
) -> None:
    with self._conn() as conn:
        work_queue_pg.set_user_access(conn, user_id, access, reason, granted_by)

def list_user_access(self, data_dir: Path) -> list[dict]:
    with self._conn() as conn:
        return work_queue_pg.list_user_access(conn)
```

**`app/db/migrations/postgres/0003_user_access_usage_log.sql`** (new file)

```sql
-- Add user_access and usage_log tables for M10E access overrides and M10B usage tracking.
-- Version: 3

CREATE TABLE IF NOT EXISTS bot_runtime.user_access (
    user_id    BIGINT PRIMARY KEY,
    access     TEXT NOT NULL CHECK (access IN ('allowed', 'blocked')),
    reason     TEXT NOT NULL DEFAULT '',
    granted_by BIGINT NOT NULL DEFAULT 0,
    granted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runtime.usage_log (
    id                BIGSERIAL PRIMARY KEY,
    chat_id           BIGINT NOT NULL,
    work_item_id      TEXT NOT NULL,
    provider          TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL NOT NULL DEFAULT 0.0,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_usage_log_chat ON bot_runtime.usage_log (chat_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_recorded_at ON bot_runtime.usage_log (recorded_at);
```

`usage_log` is added here even though M10B has not been implemented yet, because the migration must exist before the application code that writes to it is deployed. The M10B Postgres implementation (`record_usage`, `get_usage_since` in `work_queue_pg.py` and `work_queue_postgres.py`) will be added as part of M10B.

**`app/telegram_handlers.py` — `is_allowed()` wrapper**

Change only the `is_allowed()` function. All existing call sites remain unchanged — they all call `is_allowed(user)`.

Replace:
```python
def is_allowed(user) -> bool:
    return access.is_allowed_user(_cfg(), user)
```

With:
```python
def is_allowed(user) -> bool:
    cfg = _cfg()
    inbound = access.to_inbound_user(user)
    if inbound is None:
        return False
    override = work_queue.get_user_access(cfg.data_dir, inbound.id)
    return access.is_allowed_user_with_override(cfg, user, override)
```

No other handler function changes. `is_admin` and `is_public_user` are unchanged.

**`tests/contracts/test_transport_store_contract.py` — user_access contract cases**

Add three test functions to the existing contract test. They use the `backend_and_data_dir` fixture which parameterizes over both SQLite and Postgres:

```python
def test_user_access_no_override_returns_none(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    result = get_user_access(data_dir, user_id=99999)
    assert result is None


def test_user_access_set_and_get_round_trip(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    set_user_access(data_dir, user_id=100, access="blocked", reason="test", granted_by=1)
    assert get_user_access(data_dir, user_id=100) == "blocked"
    set_user_access(data_dir, user_id=100, access="allowed", reason="reversed", granted_by=1)
    assert get_user_access(data_dir, user_id=100) == "allowed"


def test_user_access_list_returns_all_rows(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    set_user_access(data_dir, user_id=200, access="allowed", reason="a", granted_by=1)
    set_user_access(data_dir, user_id=201, access="blocked", reason="b", granted_by=1)
    rows = list_user_access(data_dir)
    user_ids = {r["user_id"] for r in rows}
    assert 200 in user_ids
    assert 201 in user_ids
```

Import `get_user_access`, `set_user_access`, `list_user_access` from `app.work_queue` at the top of the file alongside the existing imports.

**`CLAUDE.md` — standing rule to prevent recurrence**

Add a new rule to the "Repo-Specific Process" section:

> **Transport facade parity rule.** Every new method added to `app/work_queue.py` must land in the same commit as: (a) a `work_queue_pg.py` conn-based implementation, (b) a `PostgresTransportStore` wrapper in `work_queue_postgres.py`, (c) a Postgres migration if the method touches a new table, and (d) a contract test case in `tests/contracts/test_transport_store_contract.py`. If Postgres support is genuinely impossible in the same slice, the method must not be added to the facade or `__all__` until it is — a SQLite-only shortcut in the facade is not acceptable.

**Files to change.**

| File | Change |
|---|---|
| `app/access.py` | Remove `sqlite3`, `Path`, `_db_access_override`; add `is_allowed_user_with_override`; make `is_allowed_user` config-only |
| `app/work_queue_sqlite.py` | Fix `get_user_access` to not create DB when file absent |
| `app/work_queue_pg.py` | Add `get_user_access_override`, `set_user_access`, `list_user_access` |
| `app/work_queue_postgres.py` | Add `get_user_access`, `set_user_access`, `list_user_access` wrappers |
| `app/db/migrations/postgres/0003_user_access_usage_log.sql` | New file: `user_access` and `usage_log` tables |
| `app/telegram_handlers.py` | Update `is_allowed()` to fetch override from facade, call pure policy |
| `tests/contracts/test_transport_store_contract.py` | Add three `user_access` contract cases; import new facade functions |
| `CLAUDE.md` | Add transport facade parity rule |

**What M10B-0 does NOT include.**

- The `record_usage` and `get_usage_since` Postgres implementations — these land in M10B, which also implements the SQLite side. The `usage_log` table is added to the Postgres migration here so the migration is available when M10B deploys.
- Changes to the approval or recovery flow — `is_allowed` wraps only the user identity check, not work-item state transitions.
- Registry UI or Telegram command behavior changes — the user-facing behavior of `/allowuser`, `/blockuser`, and `is_allowed` is identical after this refactor.
- The `usage_log` Postgres methods (`record_usage`, `get_usage_since`) in `work_queue_pg.py` — those are M10B.

**Acceptance criteria.**

- [ ] `rg -n "sqlite3|import sqlite3" app/access.py` → no hits
- [ ] `rg -n "transport\.db|Path" app/access.py` → no hits
- [ ] `rg -n "SQLiteTransportStore|PostgresTransportStore" app/telegram_handlers.py` → no hits
- [ ] `work_queue.get_user_access(data_dir, user_id)` works under both SQLite and Postgres runtime
- [ ] `work_queue.set_user_access(data_dir, ...)` works under both backends
- [ ] `work_queue.list_user_access(data_dir)` works under both backends
- [ ] `blocked` override from `set_user_access` prevents a user in `BOT_ALLOWED_USERS` from sending messages without restart
- [ ] `allowed` override from `set_user_access` admits a user not in `BOT_ALLOWED_USERS` without restart
- [ ] `get_user_access` called when `transport.db` does not exist returns `None` and does not create the file
- [ ] `is_admin_user` still checks only config — no DB access
- [ ] The three new contract tests pass against both SQLite and Postgres backends
- [ ] All existing access, handler, and transport tests remain green
- [ ] `0003_user_access_usage_log.sql` is present in the Postgres migration directory
- [ ] CLAUDE.md includes the transport facade parity rule

---

###### B. Cost and Usage Visibility

**Problem.**
Operators have no visibility into token usage or cost. Every provider API response includes token counts (prompt tokens, completion tokens). These are currently discarded. Operators running Claude or Codex against paid APIs cannot forecast spend or detect runaway conversations without external tooling.

**Fix.**
Capture token usage from every provider run. Accumulate usage per conversation (session) and display it in the Registry UI conversation detail view. Show a daily total in the Registry UI header.

**Implementation seams.**

- `app/providers/base.py` — extend `RunResult` with optional fields:
  ```python
  prompt_tokens: int = 0
  completion_tokens: int = 0
  cost_usd: float = 0.0   # 0.0 means unknown; provider fills if calculable
  ```
- Each provider fills these fields from the API response where available. Claude provider reads `usage.input_tokens` and `usage.output_tokens`. Codex provider reads equivalent fields if exposed. If unavailable, fields remain 0 — no guessing.
- `app/storage.py` — add a `usage_log` table (or a JSONB column on `work_items`):
  ```sql
  CREATE TABLE usage_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id INTEGER NOT NULL,
      work_item_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      prompt_tokens INTEGER NOT NULL DEFAULT 0,
      completion_tokens INTEGER NOT NULL DEFAULT 0,
      cost_usd REAL NOT NULL DEFAULT 0.0,
      recorded_at REAL NOT NULL   -- Unix timestamp
  );
  CREATE INDEX usage_log_chat_id ON usage_log(chat_id);
  CREATE INDEX usage_log_recorded_at ON usage_log(recorded_at);
  ```
- `app/worker.py` (or wherever `RunResult` is processed after a successful run) — after work item completion, if `run_result.prompt_tokens > 0`, insert a `usage_log` row.
- `app/registry_service/app.py` — add `/v1/ui/usage` endpoint:
  - Returns `{ "daily_total": { "prompt_tokens": N, "completion_tokens": N, "cost_usd": F }, "by_conversation": [ { "chat_id": ..., "prompt_tokens": ..., ... } ] }`.
  - `daily_total` aggregates today's UTC rows.
- Registry UI conversation detail panel — append a small "Usage" row below the conversation metadata: `Tokens: 1,234 in / 567 out` and `Est. cost: $0.012` (omit cost row if `cost_usd` is 0 for all rows, i.e. unknown). Format numbers with `toLocaleString()`.
- Registry UI header — add a subtle daily token counter beside the "last updated" indicator: `Today: 12,345 tokens` (no cost figure in header to avoid alarm for operators who haven't set pricing). Load from `/v1/ui/usage` on bootstrap, refresh every 60 s.

**Files to change.**
- `app/providers/base.py` — extend `RunResult`.
- `app/providers/claude_provider.py`, `app/providers/codex_provider.py` — populate token fields.
- `app/storage.py` — `usage_log` table and DDL migration.
- `app/worker.py` (or equivalent) — insert usage row after run.
- `app/registry_service/app.py` — `/v1/ui/usage` endpoint, UI rendering.

**What M10B does NOT include.**
- Per-model pricing table (hard-code 0 cost for unknown models; operators can infer from token counts).
- Budget alerts or hard spend caps (add in M11 if requested).
- Historical charts or sparklines (plain numbers only in M10).

---

###### C. Upgrade Path

**Problem.**
There is no documented or tooled upgrade procedure. Operators who installed the bot at M5 have no safe path to M10 without risking data loss or schema breakage. SQLite schema changes added across milestones (e.g. `usage_log` in M10B, `status` column in M8) are applied only at first run via `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE` sprinkled through the code. There is no migration history, no rollback procedure, and no version marker.

**Fix.**
Introduce a lightweight schema migration system and a version file. Document the upgrade procedure in a single operations guide.

**Implementation seams.**

- `app/storage.py` — add a `schema_version` table:
  ```sql
  CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY,
      applied_at REAL NOT NULL
  );
  ```
- Write a `migrate(conn)` function that runs numbered migration functions in order:
  ```python
  MIGRATIONS = [
      (1, _migrate_v1_baseline),
      (2, _migrate_v2_add_usage_log),
      # ...
  ]
  def migrate(conn):
      current = _current_version(conn)
      for version, fn in MIGRATIONS:
          if version > current:
              fn(conn)
              conn.execute("INSERT INTO schema_version VALUES (?, ?)", (version, time.time()))
              conn.commit()
  ```
- Each `_migrate_vN_*` function is idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` via try/except on SQLite's `OperationalError: duplicate column name`).
- Call `migrate(conn)` once at startup before any other DB access.
- Add a `VERSION` file at the project root containing the current milestone string (e.g. `M10`). `scripts/app/guided_start.sh` reads it and prints `Bot version: M10` in the startup summary.
- `CHANGELOG.md` — create with a section per milestone listing the user-visible changes and the schema version bumped. One sentence per change, bulleted. No internal implementation details.
- `docs/UPGRADE.md` — document the upgrade procedure:
  1. `git pull`
  2. `pip install -r requirements.txt`
  3. Restart the bot (migrations run automatically on startup).
  4. Restart the registry service if running.
  5. Check `journalctl -u telegram-agent-bot -n 50` for migration log lines.
  - Note: sessions and conversations are preserved across upgrades. Usage history before M10 will show zero tokens (not backfilled).

**Files to change.**
- `app/storage.py` — `schema_version` table, `migrate()`, numbered migration functions.
- `app/__init__.py` or startup entry point — call `migrate()` at startup.
- `VERSION` (new file at project root).
- `CHANGELOG.md` (new file).
- `docs/UPGRADE.md` (new file).
- `scripts/app/guided_start.sh` — read and print `VERSION`.

**What M10C does NOT include.**
- Rollback / downgrade support (SQLite schema rollback is destructive; document "restore from backup" instead).
- Automated backup before migration (suggest in UPGRADE.md, do not automate in M10).

---

###### D. Conversation Search and Filter

**Problem.**
As conversation history grows, operators cannot find a specific conversation. The Registry UI renders all conversations in a single unsorted list. There is no way to filter by bot, by status, or by approximate date, and no way to search message content.

**Fix.**
Add a search and filter bar to the Registry UI conversations panel. Client-side filtering covers bot/status/date. Server-side SQLite FTS covers content search.

**Implementation seams.**

**Client-side filter (no new endpoints).**
- Above the conversations list, render a single-line filter bar containing:
  - A text input (`id="conv-search"`, placeholder `"Search…"`).
  - A `<select>` for status (`all / running / done / failed`).
  - A `<select>` for date range (`any / today / last 7 days / last 30 days`).
- On every `input`/`change` event, filter the in-memory `state.conversations` array and re-render the list. No network request for filter changes.
- Match logic: text input checks `conversation.title` and last message snippet (case-insensitive substring). Status select checks `conversation.status`. Date select checks `conversation.updated_at` (Unix timestamp).
- Show a filtered count: `"Showing 3 of 47 conversations"` when a filter is active; hide when showing all.
- Filter state is not persisted across page loads.

**Server-side FTS (new endpoint for content search).**
- SQLite FTS5 virtual table over the timeline events `body` column:
  ```sql
  CREATE VIRTUAL TABLE IF NOT EXISTS timeline_fts USING fts5(
      body,
      content=timeline_events,
      content_rowid=id
  );
  ```
- Populate on insert via trigger or explicit `INSERT INTO timeline_fts` after each `timeline_events` insert.
- New endpoint `GET /v1/ui/search?q=<query>&limit=20` — runs `SELECT te.conversation_ref, snippet(timeline_fts, 0, '<b>', '</b>', '…', 32) FROM timeline_fts JOIN timeline_events te ON te.id = timeline_fts.rowid WHERE timeline_fts MATCH ? LIMIT ?`. Returns `[{ "conversation_ref": "...", "snippet": "..." }]`.
- Registry UI: when the search input has 3+ characters and the user pauses typing (300 ms debounce), call `/v1/ui/search`. Highlight matched conversation entries in the list. Results replace the client-side filtered list.
- If `q` is fewer than 3 characters, revert to client-side filtering only.

**Files to change.**
- `app/registry_service/app.py` — filter bar HTML/CSS/JS, `/v1/ui/search` endpoint, FTS table DDL, timeline insert logic.
- `app/storage.py` — `timeline_fts` DDL in the migration path (M10D migration step).

**What M10D does NOT include.**
- Sorting (newest-first is the current order; do not add sort controls in M10).
- Saved search / bookmarks.
- Full-text search across work item text (limit to timeline events in M10).

---

###### E. Live User Access Control

**Problem.**
The `ALLOWED_USERS` config key is set once at startup and requires a bot restart to change. Operators cannot quickly block an abusive user or grant access to a new team member without downtime. There is no `/allowuser` or `/blockuser` command.

**Fix.**
Persist user access grants and blocks in SQLite. Add Telegram admin commands to modify the live list without restart.

**Implementation seams.**

- `app/storage.py` — new `user_access` table:
  ```sql
  CREATE TABLE IF NOT EXISTS user_access (
      user_id INTEGER PRIMARY KEY,
      access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')),
      reason TEXT NOT NULL DEFAULT '',
      granted_by INTEGER NOT NULL DEFAULT 0,
      granted_at REAL NOT NULL
  );
  ```
- `app/access.py` (new module) — `is_user_allowed(data_dir, user_id) -> bool`:
  - Check `user_access` table first. If a row exists, return `access == 'allowed'`.
  - Fall through to the existing `ALLOWED_USERS` env-var check.
  - Result: env-var list remains the baseline; DB overrides on top.
- `app/telegram_handlers.py` — add admin-only commands:
  - `/allowuser <user_id> [reason]` — upserts `user_access` row with `access='allowed'`. Replies `"User 123456 added to allowed list."`.
  - `/blockuser <user_id> [reason]` — upserts with `access='blocked'`. Replies `"User 123456 blocked."`.
  - `/listaccess` — replies with a formatted table of all rows in `user_access`, plus the count of users in `ALLOWED_USERS` env var.
  - These commands require the invoking user to be in `ADMIN_USERS` (existing config key). If `ADMIN_USERS` is empty, they are disabled.
- Replace existing per-request `is_allowed_user()` call sites with `await is_user_allowed(config.data_dir, user_id)` (async wrapper that runs the sync DB check on the thread pool).
- Registry UI `/v1/ui/access` endpoint — `GET` returns the `user_access` table as JSON (list of `{user_id, access, reason, granted_by, granted_at}`). Display as a simple table in the Registry UI admin panel (new panel tab: "Access"). No add/remove from UI in M10 — read-only display. Add/remove is Telegram-command-only in M10.

**Files to change.**
- `app/storage.py` — `user_access` table, DDL migration.
- `app/access.py` (new) — `is_user_allowed()`.
- `app/telegram_handlers.py` — `/allowuser`, `/blockuser`, `/listaccess` handlers.
- `app/registry_service/app.py` — `/v1/ui/access` endpoint, "Access" panel tab.

**What M10E does NOT include.**
- Adding/removing users from the Registry UI (Telegram commands are the authoritative interface in M10).
- Per-channel or per-skill access grants.
- Temporary / expiring access grants.

---

###### F. Conversation Export

**Problem.**
There is no way to extract a conversation for archival, sharing with a colleague, or audit review. Operators must manually copy-paste from the Registry UI or read raw SQLite.

**Fix.**
Add a Markdown export from the Registry UI and a `/export` Telegram command that sends the current conversation as a file.

**Implementation seams.**

- `app/registry_service/app.py` — new endpoint `GET /v1/ui/conversations/<conversation_ref>/export`:
  - Reads all timeline events for the conversation in chronological order.
  - Renders as Markdown:
    ```
    # Conversation: <title>
    Exported: <ISO date>

    ## [<timestamp>] <event kind>
    <body>
    ```
  - Returns `Content-Type: text/markdown`, `Content-Disposition: attachment; filename="conversation-<ref>.md"`.
- Registry UI conversation detail panel — add an "Export" button (top-right of the panel, beside the conversation title). Button triggers `window.open('/v1/ui/conversations/<ref>/export')`.
- `app/telegram_handlers.py` — `/export` command:
  - Reads the current chat's timeline events via the same storage query.
  - Renders the same Markdown format.
  - Sends it as a Telegram document (`bot.send_document(chat_id, InputFile(io.BytesIO(content.encode()), filename="conversation.md"))`).
  - Reply: `"Conversation exported as Markdown."` (then the document).
  - If no events exist: `"No conversation history to export."`.

**Files to change.**
- `app/registry_service/app.py` — export endpoint, "Export" button.
- `app/telegram_handlers.py` — `/export` command.

**What M10F does NOT include.**
- JSON or PDF export (Markdown only in M10).
- Bulk export of all conversations.
- Encrypted export.

---

###### G. Completion Notifications

**Problem.**
Long-running agent tasks can take minutes. Users or operators who do not have Telegram open miss the completion. There is no external notification mechanism: no webhook, no email.

**Fix.**
Add a configurable webhook callback that fires on conversation completion. Email fallback is out of scope for M10 (requires SMTP config, adds a dependency); document it as a future option.

**Implementation seams.**

- `app/config.py` — add `completion_webhook_url: str = ""`. This is the full URL the bot will POST to when a conversation reaches a terminal state.
- `app/worker.py` (or the completion path in `worker_loop`) — after marking a work item `done`, if `config.completion_webhook_url` is set, fire a non-blocking HTTP POST:
  ```json
  {
    "event": "conversation_completed",
    "conversation_ref": "telegram:agent-id:chat-id",
    "chat_id": 12345,
    "status": "done",
    "summary": "<first 200 chars of final reply>",
    "completed_at": "<ISO timestamp>"
  }
  ```
  Use `aiohttp.ClientSession` with a 5-second timeout. Log failures as warnings; do not retry; do not fail the work item if the webhook fails.
- `scripts/app/guided_start.sh` — add an optional prompt `"Completion webhook URL (optional, press Enter to skip): "`. Write `BOT_COMPLETION_WEBHOOK_URL` to `.env` if non-empty.
- Registry UI — in the bot status panel, show `Completion webhook: configured` or `Completion webhook: not set` based on whether the env var is present.

**Files to change.**
- `app/config.py` — `completion_webhook_url` field.
- `app/worker.py` — fire webhook after completion.
- `scripts/app/guided_start.sh` — optional prompt.
- `app/registry_service/app.py` — status panel display.

**What M10G does NOT include.**
- Retry logic for failed webhook calls (log-and-forget in M10).
- Email or SMS notifications.
- Per-conversation webhook override (single global URL only in M10).
- Webhook secret / HMAC signing (add in M11 if needed for security).

---

###### H. Skills Management from Registry UI

**Problem.**
Active skills are configured via `ACTIVE_SKILLS` in `.env` and require a restart to change. Operators cannot see which skills are currently active or toggle them without shell access.

**Fix.**
Add a read-only "Skills" panel to the Registry UI that lists all registered skills, shows which are active, and (for operators who want live toggling) exposes enable/disable actions that write through to a durable skills override table.

**Implementation seams.**

- `app/storage.py` — new `skills_override` table:
  ```sql
  CREATE TABLE IF NOT EXISTS skills_override (
      skill_name TEXT PRIMARY KEY,
      enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
      set_by TEXT NOT NULL DEFAULT 'ui',
      set_at REAL NOT NULL
  );
  ```
- `app/skills.py` (or wherever skills are resolved) — after resolving `ACTIVE_SKILLS` from config, apply overrides from `skills_override`: a row with `enabled=0` removes the skill from the active set even if it is in the env var; a row with `enabled=1` adds it even if it is not. The env var remains the baseline.
- `app/registry_service/app.py`:
  - `GET /v1/ui/skills` — returns list of all skills from the skills registry (name, description, active status, override status).
  - `POST /v1/ui/skills/<skill_name>/enable` — upserts `skills_override` row with `enabled=1`. Returns updated skills list.
  - `POST /v1/ui/skills/<skill_name>/disable` — upserts with `enabled=0`. Returns updated skills list.
  - Registry UI "Skills" panel — list of skill cards showing name, description, and a toggle switch. Toggle fires the enable/disable endpoint. Active-from-env skills show a small "from config" label; overridden skills show "overridden" label. The active set reloads on next worker poll cycle (no restart required if the skills check is per-request; if cached, add a `_reload_skills()` call triggered by the API write).

**Files to change.**
- `app/storage.py` — `skills_override` table, DDL migration.
- `app/skills.py` — apply overrides.
- `app/registry_service/app.py` — `/v1/ui/skills` endpoints, "Skills" panel.

**What M10H does NOT include.**
- Installing new skills from the UI (requires file system write + restart).
- Per-user or per-conversation skill assignment.
- Skill parameter editing from the UI.

---

###### I. Programmatic API Trigger

**Problem.**
There is no stable, documented way to start a conversation programmatically. The `POST /v1/ui/conversations` endpoint exists internally (used by the Registry when routing surface_input deliveries) but is undocumented, unauthenticated in isolation, and its request/response shape may change. Operators who want to trigger the bot from CI, a webhook, or another service have no stable contract.

**Fix.**
Stabilise and document `POST /v1/ui/conversations` as a first-class authenticated API endpoint. Authentication reuses the `REGISTRY_UI_TOKEN` bearer token (same credential as the UI login, different transport: `Authorization: Bearer <token>` header).

**Implementation seams.**

- `app/registry_service/app.py` — `POST /v1/ui/conversations`:
  - Current internal shape: `{ "conversation_ref": "...", "text": "...", "actor_ref": "...", "delivery_id": "...", "skip_approval": true }`.
  - Stabilised public shape:
    ```json
    {
      "chat_id": 12345,
      "text": "Run the nightly report",
      "skip_approval": false
    }
    ```
    (The server constructs `conversation_ref`, `actor_ref`, and `delivery_id` internally from `chat_id` and a generated UUID.)
  - Authentication: check `Authorization: Bearer <token>` header against `REGISTRY_UI_TOKEN`. If missing or wrong, return 401 `{"error": "unauthorized"}`. If `REGISTRY_UI_TOKEN` is empty, bypass auth (dev mode, same as the UI).
  - Response: `{"status": "admitted", "work_item_id": "..."}` or `{"status": "duplicate"}` or `{"status": "busy"}`.
  - Add `_require_bearer_auth(request)` helper (separate from the cookie-based `_require_auth` used by HTML routes).
- `docs/API.md` (new file) — document the endpoint:
  - Authentication.
  - Request body fields (all required vs optional).
  - Response codes and bodies.
  - A minimal curl example:
    ```bash
    curl -X POST http://localhost:8787/v1/ui/conversations \
      -H "Authorization: Bearer $REGISTRY_UI_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"chat_id": 12345, "text": "Run the nightly report"}'
    ```
  - Note that `chat_id` must correspond to an existing conversation (i.e., the user has messaged the bot at least once).

**Files to change.**
- `app/registry_service/app.py` — stabilise endpoint, add bearer auth, align request shape.
- `docs/API.md` (new file).

**What M10I does NOT include.**
- Starting a brand-new conversation with a user who has never messaged the bot (requires Telegram's `sendMessage` to a user who has not initiated contact — not allowed by Telegram's API without user initiation).
- Batch trigger (multiple conversations in one call).
- Webhook registration for receiving events programmatically (separate feature).

---

###### M10 — Files to Change

| Section | File | Change type |
|---------|------|-------------|
| A | `app/registry_service/app.py` | Login/logout routes, session store, `_require_auth`, nav logout link |
| B-0 | `app/access.py` | Remove DB access; add `is_allowed_user_with_override`; make `is_allowed_user` config-only |
| B-0 | `app/work_queue_sqlite.py` | Fix `get_user_access` to not create DB when absent |
| B-0 | `app/work_queue_pg.py` | Add `get_user_access_override`, `set_user_access`, `list_user_access` |
| B-0 | `app/work_queue_postgres.py` | Add `get_user_access`, `set_user_access`, `list_user_access` wrappers |
| B-0 | `app/db/migrations/postgres/0003_user_access_usage_log.sql` (new) | `user_access` and `usage_log` Postgres tables |
| B-0 | `app/telegram_handlers.py` | Update `is_allowed()` to use facade + pure policy |
| B-0 | `tests/contracts/test_transport_store_contract.py` | Add `user_access` contract cases (both backends) |
| B-0 | `CLAUDE.md` | Transport facade parity rule |
| B | `app/providers/base.py` | `RunResult` token fields |
| B | `app/providers/claude_provider.py` | Populate token fields from API response |
| B | `app/providers/codex_provider.py` | Populate token fields where available |
| B | `app/work_queue_sqlite_impl.py` | `record_usage`, `get_usage_since` functions |
| B | `app/work_queue_sqlite.py` | `record_usage`, `get_usage_since` wrappers |
| B | `app/work_queue_pg.py` | `record_usage`, `get_usage_since` conn-based functions |
| B | `app/work_queue_postgres.py` | `record_usage`, `get_usage_since` wrappers |
| B | `app/work_queue.py` | Add `record_usage`, `get_usage_since` to facade and `__all__` |
| B | `app/telegram_handlers.py` | Write usage log after successful run |
| B | `app/registry_service/app.py` | `/v1/ui/usage` endpoint, conversation usage display |
| B | `tests/contracts/test_transport_store_contract.py` | Add `usage_log` contract cases |
| C | `app/storage.py` | `schema_version` table, `migrate()` function, numbered migrations |
| C | `app/__init__.py` | Call `migrate()` at startup |
| C | `VERSION` (new) | Milestone version string |
| C | `CHANGELOG.md` (new) | Per-milestone user-visible changes |
| C | `docs/UPGRADE.md` (new) | Upgrade procedure |
| C | `scripts/app/guided_start.sh` | Print `VERSION` in startup summary |
| D | `app/registry_service/app.py` | Filter bar, `/v1/ui/search` endpoint, FTS table |
| D | `app/storage.py` | `timeline_fts` FTS5 table (M10D migration) |
| E | `app/storage.py` | `user_access` table (M10E migration) |
| E | `app/access.py` | `is_user_allowed()` |
| E | `app/telegram_handlers.py` | `/allowuser`, `/blockuser`, `/listaccess` |
| E | `app/registry_service/app.py` | `/v1/ui/access` endpoint, "Access" panel tab |
| F | `app/registry_service/app.py` | Export endpoint, "Export" button |
| F | `app/telegram_handlers.py` | `/export` command |
| G | `app/config.py` | `completion_webhook_url` field |
| G | `app/worker.py` | Fire webhook after completion |
| G | `scripts/app/guided_start.sh` | Optional webhook URL prompt |
| G | `app/registry_service/app.py` | Webhook status in bot status panel |
| H | `app/storage.py` | `skills_override` table (M10H migration) |
| H | `app/skills.py` | Apply overrides from DB |
| H | `app/registry_service/app.py` | `/v1/ui/skills` endpoints, "Skills" panel |
| I | `app/registry_service/app.py` | Stabilise `/v1/ui/conversations`, bearer auth |
| I | `docs/API.md` (new) | Public API documentation |

###### M10 — Implementation Order

The sections are ordered by risk and dependency, not by user value:

1. **C (Upgrade Path)** — implement first. The migration framework is a prerequisite for all other DB changes (B, D, E, H). Writing the `schema_version` table and `migrate()` before anything else ensures all subsequent DB changes land cleanly.
2. **A (Authentication)** — implement second. Once migrations are in place, auth is purely additive to the registry service with no DB changes. Getting auth right early prevents accidentally shipping M10 features unauthenticated.
3. **E (User Access Control)** — implement third. Depends on C for migration. `app/access.py` is a small, isolated module. Get the DB write path working before adding the Telegram commands.
4. **B-0 (Transport Store Abstraction Integrity)** — implement immediately after E ships. Fixes the abstraction violations introduced by E and makes the Postgres backend correct before any more transport methods are added.
5. **B (Cost Visibility)** — implement after B-0. Builds on the repaired abstraction. Adds `record_usage`/`get_usage_since` to both backends correctly from the start.
6. **D (Search and Filter)** — implement fifth. Client-side filtering has no dependencies. FTS5 depends on C.
7. **F (Export)** — implement sixth. No DB changes, minimal surface area.
8. **G (Webhook Notifications)** — implement seventh. Config change + one fire-and-forget HTTP call.
9. **H (Skills Management)** — implement eighth. Depends on C for migration. Skills override logic must be tested carefully to avoid silently dropping active skills.
10. **I (Programmatic API)** — implement last. Endpoint already exists; this is stabilisation + auth + docs. Low risk.

###### M10 — What M10 Does NOT Include

- Multi-user accounts or per-user permissions beyond the simple allowed/blocked access control in M10E.
- Budget alerts, hard spend caps, or automated cost enforcement (M11+).
- SMTP email or SMS notifications (webhook only in M10).
- Installing new skills or editing skill parameters from the Registry UI.
- A mobile-optimised Registry UI (responsive improvements may land but are not a gate).
- Any changes to the provider layer, durable workflow core, or Telegram polling logic.
- New approval flows or delegation changes (M10 is operational infrastructure, not feature additions to the conversation model).

###### M10 — Acceptance Criteria

- [ ] `GET /ui` redirects to `GET /ui/login` when `REGISTRY_UI_TOKEN` is set and no valid session cookie is present
- [ ] Login with the correct `REGISTRY_UI_TOKEN` value sets a `registry_session` cookie and redirects to `/ui`
- [ ] Login with a wrong password re-renders the login form with an error message and does not set a cookie
- [ ] When `REGISTRY_UI_TOKEN` is not set, `GET /ui` loads without authentication (dev mode)
- [ ] Registry UI conversation detail shows `Tokens: N in / N out` for conversations with usage data
- [ ] Registry UI header shows a daily token total that updates every 60 s
- [ ] Bot startup logs at least one `Applied migration vN` line the first time M10 is run; subsequent restarts log `Schema at vN, no migrations needed`
- [ ] `CHANGELOG.md` exists and lists user-visible changes for M10 and all prior milestones
- [ ] `docs/UPGRADE.md` exists with a numbered upgrade procedure
- [ ] Client-side filter by status correctly hides non-matching conversations without a network request
- [ ] `/v1/ui/search?q=hello` returns at most 20 results with HTML-highlighted snippets when "hello" appears in a timeline event body
- [ ] `/allowuser <id>` from an admin Telegram user persists the grant to SQLite and takes effect on the next message from that user without restart
- [ ] `/blockuser <id>` from an admin Telegram user blocks that user on the next message without restart
- [ ] `GET /v1/ui/conversations/<ref>/export` returns a valid Markdown file download
- [ ] `/export` in Telegram sends a `.md` file containing the conversation timeline
- [ ] A POST to `COMPLETION_WEBHOOK_URL` fires within 5 s of conversation completion when the config key is set; webhook failure does not fail the work item
- [ ] Skills panel in Registry UI shows each skill's name, description, active status, and override status
- [ ] Enabling a skill via the Registry UI toggle activates it for subsequent conversations without restart
- [ ] `POST /v1/ui/conversations` with a valid `Authorization: Bearer <token>` header and a known `chat_id` returns `{"status": "admitted", ...}`
- [ ] `POST /v1/ui/conversations` without a valid bearer token returns 401
- [ ] `docs/API.md` contains a working curl example that operators can copy-paste
- [ ] Full test suite passes

---

#### Phase 20 — Product-Level Acceptance Criteria

The feature is complete when all of the following are true:

1. Registry mode is the default and works from guided setup end-to-end.
2. Standalone mode remains explicitly available.
3. Bots can run privately without exposing public APIs.
4. Telegram and Registry UI act on the same conversation truth.
5. Delegated work routes through registry and executes through the same
   local worker-owned runtime.
6. Registry-originated actions do not bypass workflow/state-machine ownership.
7. Registry UI provides materially richer progress/state visibility than
   Telegram.
8. Operators can stand up registry plus multiple bots from one checkout with
   understandable scripts and config.
9. Degraded registry behavior is observable and never fatal to local operation.
10. Discovery and delegation require user approval; neither is automatic.

---

### Phase 16 - Registry Trust And Governance

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: governance and trust visibility should stay
  on existing product and resolved-context contracts unless a new durable
  workflow is explicitly justified.

Objective:

- Extend store and registry trust without coupling the product to Shared
  Runtime queue semantics.

Workflow classification:

- Primarily capability-management and governance work, not a new FSM by
  default.

Implementation rules:

- Reuse the current object/ref store architecture.
- Reuse the current registry metadata flow and digest-verification contract.
- Keep publisher signing and trust policy explicit and testable.

Tests required:

- Store/registry contract tests
- Trust-policy behavior tests
- Operator-path tests for governance and verification flows

### Phase 17 - Usage Accounting, Quotas, And Billing

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: accounting and quotas should reuse
  authoritative completion points and existing repository contracts rather than
  inventing a second execution-tracking model.

Objective:

- Add usage recording and quota logic in a backend-neutral product layer before
  Shared Runtime queue work.

Workflow classification:

- Primarily product/accounting logic.
- If later background processing is required, do not invent a broker now; keep
  accounting tied to authoritative completion points.

Implementation rules:

- Meter usage from authoritative execution completion points, not provider
  progress heuristics.
- Add usage recording first.
- Add quota enforcement second.
- Add billing integration and reporting third.

Tests required:

- Completion-owner and accounting attribution tests
- Quota enforcement tests through real request paths
- Regression tests proving accounting does not drift across backends

### Phase 18 - Shared Runtime: Postgres Queue Authority In Webhook Mode

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: this is explicit workflow/runtime work, so
  extend the existing FSM-backed transport and repository contracts rather than
  hand-rolling new queue logic in handlers or stores.

Objective:

- Introduce the **Shared Runtime** capability tier last, after Local Runtime
  and product work are stable.

Workflow classification:

- This is real **workflow/runtime** work.
- Reuse the existing transport workflow machine and repository ownership model;
  do not hand-roll queue transitions in handlers or workers.

Required outcomes:

- Keep the core Telegram request path as an app-owned Postgres queue, not a
  generic task broker.
- Retain explicit `updates` and `work_items` tables.
- Retain row-lock claiming, leases, recovery metadata, replay/discard
  ownership, stable recovery references, and explicit terminal dispositions.
- In webhook mode, ingress should normalize, persist, and acknowledge quickly.
- Workers become the primary execution path.

Implementation rules:

- This capability is for **Shared Runtime** only. Do not force Local Runtime to
  emulate it.
- Do not break the backend-neutral product layer above the runtime boundary.
- Keep provider execution outside long-lived claim transactions.

Tests required:

- Shared-runtime queue contract tests
- Webhook persist-first ingress tests
- Recovery/replay/discard ownership tests under the queue path

### Phase 19 - Shared Runtime: Multi-Process Scale And Durability Confidence

Guidance baseline:

- Follow the repo-local and global execution guidance before changing code or
  contracts:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/AGENTS-global.md`
  - `docs/CLAUDE-global.md`
- Apply the workflow decision rule from `Remaining-Phase Execution Discipline`
  before introducing abstractions: multi-process scale and durability remain
  workflow/runtime coordination work and must keep extending the existing
  transport FSM and repository ownership, not a parallel control plane.

Objective:

- Add multi-process scale and confidence work only after Shared Runtime queue
  authority exists.

Workflow classification:

- Real workflow/runtime coordination work; continue using the existing
  transport FSM and repository semantics as the transition authority.

Scope:

- Multi-process / multi-worker deployment
- Cross-process ingress and worker concurrency
- Queue depth, lease, worker-health, and recovery metrics
- Crash and lease-recovery tests
- Webhook ingress durability tests
- Real provider smoke coverage for the shared-runtime model

Implementation rules:

- Preserve per-chat single-flight ordering, `transport idempotency`, and
  explicit terminal ownership across processes.
- Treat Shared Runtime as a deployment capability tier, not as a second
  product.
- Do not widen Local Runtime complexity just to mimic Shared Runtime.

---

## Architecture Decisions

- Current shipped runtime after Phase 12 is Postgres-only.
- The roadmap after Phase 12 now changes direction: restore a first-class
  **Local Runtime** mode with SQLite as the default backend for both Docker and
  host deployments, behind backend-neutral storage/runtime contracts.
- Treat **Local Runtime** and **Shared Runtime** as explicit capability tiers:
  - Local Runtime: single-machine, SQLite-default, product-first
  - Shared Runtime: later Postgres queue authority, multi-process, webhook
    persist-first
- Product/core code should depend on common storage/runtime contracts where
  they are genuinely common, and should not need backend-specific code changes
  for normal feature work.
- Extract workflow ownership before any database migration so the new backend
  does not inherit open-coded transition logic.
- Use contract-first workflow state machines; implementation is
  python-statemachine (narrow use; persistence and queue authority remain
  in-app). See Phase 11 implementation.
- Keep the shared-runtime request queue app-owned. Do not adopt Celery,
  Temporal, PGMQ, or a dedicated broker for the Shared Runtime phases.
- Reuse existing `SessionState`, `PendingApproval`, `PendingRetry`,
  normalized inbound payloads, and resolved execution-context shapes. Extend
  only where needed for leases, attempts, and terminal disposition.
- Use an off-the-shelf Postgres-backed job library only later for secondary
  jobs such as billing, cleanup, reconciliation, or scheduled maintenance.

---

## Assumptions And Defaults

- The roadmap should now be optimized for:
  - backend-neutral product/core contracts
  - Local Runtime as the default deployment tier
  - Shared Runtime as a later advanced capability tier
- Phase 12 remains shipped history; no in-place SQLite upgrade or
  SQLite-to-Postgres import path is required as development-time gating
  work for the new roadmap direction.
- The master roadmap should present a strict execution order, not priority
  buckets.
- Confidence work remains in the roadmap because the Shared Runtime phases
  materially change failure modes.
- Workflow contracts are defined first; library choice (python-statemachine)
  is narrow and subordinate to the explicit state/ownership model.
- Usage recording and quotas now move ahead of Shared Runtime queue work, but
  must still depend on authoritative completion points rather than progress
  heuristics.
- Queue or library evaluation basis:
  [Celery broker docs](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html),
  [Temporal workflows](https://docs.temporal.io/workflows),
  [PGMQ](https://pgmq.github.io/pgmq/),
  [Procrastinate](https://procrastinate.readthedocs.io/).

---

## Completion Standard

The product is commercially ready when:

- the core user journeys are clean and understandable
- execution context is explicit and safe
- the skill system is discoverable and recoverable
- the output is Telegram-native and mobile-friendly
- operators can diagnose and manage the system confidently
- cross-cutting invariants are enforced by tests, not memory
- users can control model speed and capability without knowing provider
  internals
- public deployments have a concrete trust profile, not optimistic defaults
- long responses use native Telegram primitives for progressive disclosure
- first visible progress is sent before provider invocation
- recovery wording is truthful: fresh live work is not mislabeled as recovered
  work
- shared progress preserves semantic richness while keeping one coherent user
  vocabulary
- every inbound update receives a visible response, even under burst traffic
- polling conflicts are detected and warned, not silently tolerated

A roadmap phase is only complete when:

- the shipped behavior exists in code
- the relevant contract and regression tests exist
- [status.md](status.md) reflects the new
  phase state
- [ARCHITECTURE.md](ARCHITECTURE.md) matches the resulting runtime authority
  and boundary decisions

Shipped phases remain sealed history. New work should advance Phase 20
(active) rather than reopening Phases 1-15. Phases 16-19 remain deferred
behind Phase 20.
