# Commercial Product Plan

This document is the master roadmap for the finished product shape, the order
in which it should be built, and the historical decisions that still matter.
It is not the build log. Current implementation status lives in
[STATUS-commercial-polish.md](STATUS-commercial-polish.md). Runtime
boundaries, contracts, and storage authority live in
[ARCHITECTURE.md](ARCHITECTURE.md).

Use this document for four different questions:

- What is the product supposed to be?
- What has already shipped?
- What should be built next?
- Why do certain constraints and decisions exist?

---

## How To Use This Plan

- `PLAN-commercial-polish.md`
  Product vision, ordered roadmap, sealed history, lessons learned, and
  decision record.
- `STATUS-commercial-polish.md`
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
- multi-agent delegation as a user-facing concept
- Docker or Kubernetes control-plane design
- hosted SaaS architecture decisions
- general-purpose package-manager behavior outside the skill system

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
- Phases 1-12 are sealed as shipped history.
- New roadmap work begins at Phase 13.
- The roadmap after Phase 12 is now split by **capability tier**, not by
  database ideology:
  - **local/product track first**: backend-neutral product work plus a
    first-class Local Runtime mode
  - **shared-runtime track last**: Postgres queue authority, multi-process
    ingress, and durability confidence
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive
  messages. It is not part of the core transport contract.
- **Current shipped state:** Phase 12 runtime is Postgres-only.
- **Roadmap direction after Phase 12:** restore a first-class **Local Runtime**
  mode, with SQLite as the default backend for both Docker and host
  deployments, behind backend-neutral storage/runtime contracts.
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
| 13 | Storage backend abstraction and Local Runtime mode | Remaining |
| 14 | Product polish on local foundations | Remaining |
| 15 | Behavior extensions | Remaining |
| 16 | Registry trust and governance | Remaining |
| 17 | Usage accounting, quotas, and billing | Remaining |
| 18 | Shared Runtime: Postgres queue authority in webhook mode | Remaining |
| 19 | Shared Runtime: multi-process scale and durability confidence | Remaining |

---

## Sealed Phases 1-12

Phases 1-12 are shipped and sealed. They stay here as historical reference,
but the active roadmap begins at Phase 13.

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

**Transport schema (versioned, migration deferred)**

- `transport.db` has a versioned schema. The current build expects the current schema/layout.
- No migration system is implemented yet; upgrade/cutover strategy is deferred to the Postgres/runtime phases.
- If an existing DB has an unsupported schema version or layout, the app fails fast with a neutral error (e.g. "Unsupported transport.db schema/layout for this build"). The app does not mutate existing DBs before validating them.
- Review priority: correctness and repository invariants first; full upgrade-path engineering is not a release criterion yet. The codebase leaves a clean seam for future migrations.

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
- `STATUS-commercial-polish.md`
  Build log and current implementation status.
- `PLAN-commercial-polish.md`
  Product vision, roadmap, and durable lessons and decisions.
- `ARCHITECTURE.md`
  Contracts, components, and runtime model.

If a document starts turning into another document, split it rather than
blurring the audience.

---

## Remaining Phases

These phases are the active roadmap. Every still-relevant deferred or future
item belongs somewhere in this ordered sequence. Phase 12 is sealed. The next
numbered infrastructure phase is Phase 13, but work should not start there
immediately: the required pre-Phase-13 execution program below must be
completed first.

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

### Phase 12 - Postgres Runtime Cutover *(complete)*

Make Postgres the only supported runtime backend after cutover. Phase 12 is a
contract-preserving backend replacement and environment/bootstrap phase, not a
queue redesign phase and not a CI/CD phase. Implementation complete; see
[STATUS-commercial-polish.md](STATUS-commercial-polish.md).

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
   - `scripts/bootstrap.sh` remains useful for local development and tests, but
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

- `scripts/bootstrap.sh`
- `scripts/db_bootstrap.sh`
- `scripts/db_update.sh`
- `scripts/db_doctor.sh`
- optional convenience wrapper for local development such as:
  - `scripts/dev_up.sh`
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
  - `sql/postgres/0001_runtime.sql`
  - `sql/postgres/0002_...sql` for later additive changes
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
  - `STATUS-commercial-polish.md` updated accurately
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
  from `Dockerfile.bot` via build script). Tests should prove the image
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

#### Milestone E - Usability Hardening Before Phase 13

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
- `STATUS-commercial-polish.md` must only move when code and tests prove the
  runtime behavior.
- Bucket E is not done because a few small fixes landed; the full audit,
  simplification pass, and verification envelope must be complete.

Milestone E is split into four required workstreams.

### E1. Product-path hardening

Audit and fix the current primary user and operator journeys end to end.

Required audit surfaces:

- Docker/operator path:
  - `scripts/dev_up.sh`
  - `scripts/guided_start.sh`
  - `scripts/build_bot_image.sh`
  - `scripts/provider_login.sh`
  - `scripts/provider_status.sh`
  - `scripts/provider_logout.sh`
  - `scripts/db_bootstrap.sh`
  - `scripts/db_update.sh`
  - `scripts/db_doctor.sh`
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
- `STATUS-commercial-polish.md` and `README.md` reflect the real current
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
8. Update `STATUS-commercial-polish.md` only after the runtime behavior and
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

#### Gate Before Phase 13

Do not start Phase 13 until all of the following are true:

- The Docker path is the actual supported happy path, not just the documented
  one.
- New users can get from zero to running without advanced choices.
- The main Telegram workflows feel polished enough that more infrastructure work
  would clearly unlock the next need.
- The current product is stable enough that webhook/multi-process work solves a
  real problem rather than an architectural desire.
- `STATUS-commercial-polish.md` truthfully reports the pre-Phase-13 execution
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
- Update `STATUS-commercial-polish.md` only after code and tests confirm the
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
2. **Slice 2 — Live cancellation of running work** is the next required
   workstream. It adds user-visible cancellation of active provider execution
   and approval preflight without changing transport states, queue ownership,
   or durable workflow families.
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
  - reuse current handler and callback ingress
  - reuse current provider protocol and result types
  - reuse the existing work queue and `_chat_lock` ownership model
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
- Do not add durable state, transport states, or a new FSM for live
  cancellation in this phase. Cancellation of a running subprocess is a live
  execution control problem, not a new durable workflow family.
- Do not change the `ProgressSink` protocol to carry cancellation semantics.
  Keep rendering and control separate even when they are used together in the
  same execution path.
- Do not invent Claude progress semantics that the raw stream does not prove.
  If the stream does not clearly prove a `ToolFinish` or `CommandFinish`, do
  not synthesize one.

#### Slice 2 — Live Cancellation Of Running Work

Problem statement:

- `/cancel` currently clears pending approval/retry or credential setup only.
- When a provider subprocess is actively running, `/cancel` cannot interrupt it
  because the current command path acquires `_chat_lock` and waits behind the
  very execution it is trying to stop.

Contracts in this slice:

1. **Live cancel ingress contract**
- `/cancel` during a live provider run must request cancellation immediately
  rather than queueing behind `_chat_lock`.
- `/cancel` when there is no live run must preserve the current pending/setup
  and no-op behavior exactly.

2. **Provider cancel outcome contract**
- Provider execution gains a typed, user-initiated cancel outcome distinct from:
  - timeout
  - typed resume failure
  - restart/shutdown interruption that remains `LeaveClaimed`
- User-requested cancel must not route through restart recovery.

Source of truth:

- `_chat_lock` in `app/telegram_handlers.py` remains the owner of per-chat
  serialization and work-item completion.
- `work_queue` remains the owner of durable work-item lifecycle.
- `execute_request()`, `request_approval()`, and replay execution in
  `handle_recovery_callback()` remain the owners of terminal user-visible live
  execution outcome.
- `RunResult` in `app/providers/base.py` remains the provider outcome type.
- Provider subprocess lifecycle remains owned inside `app/providers/claude.py`
  and `app/providers/codex.py`.

Required implementation shape:

- Add `cancelled: bool = False` to `RunResult`.
- Extend the provider `run()` and `run_preflight()` contract to accept a
  separate cancel signal or execution-control object. Do **not** attach
  cancellation semantics to the `ProgressSink` protocol.
- In `app/telegram_handlers.py`, add a small private live-execution registry
  keyed by `chat_id`. Use it only for process-local cancellation signaling and
  cleanup. It must not become a second durable state model.
- Register the live execution record before the provider call and clear it in a
  `finally` block on every exit path.
- `/cancel` must use a fast path **outside** `_chat_lock`:
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
- `app/user_messages.py`

Failure-path rules:

- Double-cancel is idempotent.
- Cancel after process exit is a safe no-op.
- Restart during cancellation drops the in-memory signal and falls back to the
  existing `LeaveClaimed` recovery contract.
- Unexpected cleanup failure is an ordinary execution failure, not a successful
  cancel.

Required invariants:

- `/cancel` during live execution does not wait behind `_chat_lock`
- `/cancel` during pending approval/retry still behaves exactly as before
- `/cancel` with no live execution and no pending/setup still shows the current
  nothing-to-cancel behavior
- cancelled execution does not leave the work item in `claimed`
- cancelled execution does not send the final assistant reply
- cancelled execution does not corrupt provider state; the next request works
  normally
- live execution registry entries are always cleaned up

Tests required for Slice 2:

- Contract test: cancel signal set during Claude execution returns
  `RunResult.cancelled=True` within bounded time
- Contract test: cancel signal set during Codex execution returns
  `RunResult.cancelled=True` within bounded time
- Handler integration: `/cancel` during live execution updates the status
  message to cancelled and final result text is not sent
- Handler integration: `/cancel` during approval preflight has the same
  semantics
- Handler integration: `/cancel` with no live execution preserves the current
  no-op behavior
- Adjacent regression: cancelled execution does not corrupt provider state; the
  next request succeeds normally
- Cleanup regression: the live cancel registry entry is removed on both
  cancellation and ordinary completion

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
- no new durable state for live cancellation
- no new progress event family if the current one is sufficient
- no Claude-specific Telegram rendering path
- no parallel provider-progress system
- no Codex provider behavior changes unless a shared invariant is found broken

#### Slice 4 — Cancel Concurrency Verification

Problem statement:

- Slices 2 and 3 shipped the cancel mechanism and progress improvements, but
  the test suite proves contracts in isolation only.  No test exercises the
  actual cooperative concurrency that makes `/cancel` work: one coroutine
  blocked in `execute_request` while a second coroutine runs `cmd_cancel` on
  the same event loop.
- The readline/cancel race inside `_consume_stream` and `consume_stdout` is
  tested with pre-set events and fake processes whose `readline()` returns
  immediately.  Neither proves the race resolves correctly when `readline()`
  is actually blocked on a real file descriptor.
- The two-stage UX ("Cancellation requested." then "Cancelled." on the
  status message) is asserted in separate tests but never proven to happen
  in the correct order from a single concurrent execution.

This is a test-only slice.  No production code changes.

Contracts being verified (not changed):

1. **readline/cancel race contract** — `asyncio.wait` with
   `FIRST_COMPLETED` resolves promptly when the cancel event fires while
   `readline()` is blocked on a real subprocess pipe.
2. **Lock-free cancel ingress contract** — `cmd_cancel` completes and
   delivers the user-facing ack while `_chat_lock` is held by
   `execute_request`.
3. **Two-stage UX ordering contract** — "Cancellation requested." is
   delivered before "Cancelled." appears on the status message, from a
   single concurrent execution.

Source of truth:

- `_LIVE_CANCEL` in `app/telegram_handlers.py` is the in-memory cancel
  registry.
- `_chat_lock` in `app/telegram_handlers.py` is the per-chat serialization
  owner.
- `_consume_stream` in `app/providers/claude.py` and `consume_stdout` in
  `app/providers/codex.py` own the readline/cancel race.
- `cmd_cancel` in `app/telegram_handlers.py` owns the cancel fast path.

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

2. **Lock-free cancel dispatch.**
   - Use a `FakeProvider` whose `run()` awaits a gate event before
     returning, so `execute_request` holds `_chat_lock` for a controlled
     duration.
   - Use `asyncio.gather` to run `handle_message` (which acquires the
     lock and blocks in `run()`) and a helper that sends `/cancel` then
     sets the gate.
   - Assert `cmd_cancel` delivered "Cancellation requested." before
     `handle_message` returned.
   - Assert the cancel event was set and `run()` saw it.
   - Assert `handle_message` completed with the cancelled outcome (status
     message shows "Cancelled.", no final text sent).
   - Use `_StickyReplyMessage` for the status-message oracle.

3. **Two-stage UX ordering.**
   - From the same test as (2), collect all user-visible messages in
     delivery order.
   - Assert "Cancellation requested." appears strictly before "Cancelled."
     in the sequence.
   - Assert no other cancel-related text appears between them.

4. **Cancel mid-stream (partial output).**
   - Spawn a subprocess that emits a few lines of JSON then blocks.
   - Set cancel after partial output has been consumed.
   - Assert accumulated text contains the partial output.
   - Assert `RunResult.cancelled` is True.
   - Assert no text corruption (partial line, truncated JSON).

5. **Adjacent: cancel does not interfere with non-cancel paths.**
   - After the concurrency cancel test completes, send a new message
     to the same chat.
   - Assert the new request executes normally (not cancelled).
   - Assert `_LIVE_CANCEL` is clean for that chat.

Failure-path coverage:

- Cancel event set after subprocess has already exited naturally: the
  readline returns `b""` first, `cancel.is_set()` check in the cancel
  path is a safe no-op.  Test (1) covers this by also testing cancel
  after a fast-exiting subprocess.
- Double `/cancel` during a single execution: the event is already set,
  `cmd_cancel` replies "Cancellation requested." again idempotently.
  Existing test covers this; concurrency test (2) can optionally send
  two `/cancel` commands.

Implementation rules:

- All tests use real `asyncio.Event` and `asyncio.gather` — no mocking
  of the event loop or wait primitives.
- Subprocess tests use `sys.executable` with inline scripts — no
  external binary dependencies.
- All concurrency tests have explicit timeouts via `asyncio.wait_for`
  so a broken race fails fast (2–5s) rather than hanging.
- Tests go in `tests/test_cancel.py` as a new `TestCancelConcurrency`
  class.
- No production code changes in this slice.  If a test reveals a bug,
  the fix goes in a subsequent slice with its own preamble.

Non-deliverables:

- No cross-process or durable cancel testing (cancel is in-memory by
  design; restart recovery is already tested elsewhere).
- No worker-path cancel test (worker calls `execute_request` the same
  way; the cancel event is registered by `execute_request` itself).
- No Telegram network I/O or real PTB dispatcher in these tests.

Tests required for Phase 15 generally:

- Real handler/request-flow tests
- Contract tests for user-visible behavior and opt-in policy
- Regression tests for public/trust restrictions and execution-context
  invalidation
- Slice 2 provider and handler cancel tests
- Slice 3 Claude trace and progress contract tests

Done when:

- Slice 2 ships live cancellation of active provider execution and approval
  preflight without introducing new durable state, queue states, or a parallel
  cancellation system.
- Slice 3 ships richer Claude progress by reusing the existing shared progress
  event family and renderer without degrading text delivery or Codex behavior.
- Slice 4 proves the cancel mechanism works under real cooperative concurrency:
  readline/cancel race with real subprocesses, lock-free dispatch, two-stage
  UX ordering, and partial-output cancel.  Test-only slice, no production
  code changes.
- New implementation work for Phase 15 continues to extend the current owners
  instead of building shadow abstractions around them.

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
- [STATUS-commercial-polish.md](STATUS-commercial-polish.md) reflects the new
  phase state
- [ARCHITECTURE.md](ARCHITECTURE.md) matches the resulting runtime authority
  and boundary decisions

Shipped phases remain sealed history. New work should advance Phases 11-19
rather than reopening Phases 1-10.
