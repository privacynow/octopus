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
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive
  messages. It is not part of the core transport contract.
- Postgres is the sole runtime backend after Phase 12. SQLite remains in the
  codebase only for test-only and historical paths; any SQLite-to-Postgres
  import bridge is optional follow-on work, not a required part of the cutover.

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
| 13 | Postgres queue authority in webhook mode | Remaining |
| 14 | Multi-process / multi-worker deployment | Remaining |
| 15 | Durability confidence phase | Remaining |
| 16 | Product polish on stable foundations | Remaining |
| 17 | Behavior extensions | Remaining |
| 18 | Registry trust and governance | Remaining |
| 19 | Usage accounting, quotas, and billing | Remaining |

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
item belongs somewhere in this ordered sequence. Phase 12 is sealed; active
work begins at Phase 13.

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
  Phase 13-14. Phase 12 only replaces the storage backend under the current
  single-process contract.
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
   - The database, runtime role, schema namespace, tables, indexes, and schema
     version records are created and updated by explicit repo-owned commands.
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
  - The default app image is a base image; a runnable bot image must also
    include the chosen provider CLI.
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
7. Start the bot container against the bootstrapped Postgres service.

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
  queue authority belongs to Phase 13.

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
18. Only then move to Phase 13 queue-authority work.

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
- The codebase is ready for Phase 13 without re-litigating state ownership,
  repository semantics, or basic environment bootstrap.

### Phase 13 - Postgres Queue Authority In Webhook Mode

Keep the core Telegram request path as an app-owned Postgres queue, not a
generic task broker.

- Retain explicit `updates` and `work_items` tables.
- Retain row-lock claiming, leases, recovery metadata, and replay/discard
  ownership.
- Retain stable recovery references and explicit terminal-disposition fields.
- In webhook mode, ingress should normalize, persist, and acknowledge
  quickly.
- Workers become the primary execution path.
- Provider execution should remain outside long-lived claim transactions.

### Phase 14 - Multi-Process / Multi-Worker Deployment

Add true cross-process ingress and worker concurrency on top of the Postgres
queue.

- Preserve per-chat single-flight ordering, `transport idempotency`, recovery
  safety, and explicit terminal ownership across processes.
- Polling stays single-owner and dev-oriented.
- Scale path is webhook plus Postgres plus workers.
- Add queue depth, lease, worker-health, and recovery metrics.
- Treat multi-worker support as a deployment extension on top of the queue
  contract, not as a new product model.

### Phase 15 - Durability Confidence Phase

Add the confidence work that becomes important only after the infrastructure
shift.

- Cross-process queue tests.
- Crash and lease-recovery tests.
- Webhook ingress durability tests.
- Real provider smoke coverage for the new worker model.

This is a distinct phase, not hidden inside earlier acceptance criteria.

### Phase 16 - Product Polish On Stable Foundations

Add the small UI work that is only worth doing after queue and worker
semantics stabilize.

- Add `/project` inline keyboard by reusing the existing settings-inline-
  keyboard pattern and callback handling.
- Add optional verbose progress mode only after queue and worker semantics are
  stable.
- Any richer progress mode should layer on top of the shared semantic-rich
  progress model rather than invent provider-specific output paths.
- Keep this phase intentionally small and UI-focused.

### Phase 17 - Behavior Extensions

Add demand-gated behavior extensions after the runtime is stable.

- Add demand-gated `content dedup` using a durable content fingerprint and
  explicit user acknowledgment instead of silent drop.
- Expand project and policy scope using the existing project binding and
  resolved execution-context model rather than inventing a second scoping
  system.

### Phase 18 - Registry Trust And Governance

Extend the managed store with publisher signing and organizational trust
policy on top of the existing digest-verification model.

- Reuse the current object/ref store architecture.
- Reuse the current registry metadata flow.

### Phase 19 - Usage Accounting, Quotas, And Billing

Build this last.

- Meter usage from authoritative execution completion points, not from
  provider-progress heuristics.
- Add usage recording first.
- Add quota enforcement second.
- Add billing integration and reporting third.
- If secondary background jobs are needed here, use a Postgres-native task
  library only for those non-core jobs.

---

## Architecture Decisions

- Postgres is the sole runtime backend after cutover. SQLite is the current
  development backend until Phase 12 lands; SQLite-to-Postgres import is
  optional and deferred unless preserving dev/test data becomes worthwhile.
- Extract workflow ownership before any database migration so the new backend
  does not inherit open-coded transition logic.
- Use contract-first workflow state machines; implementation is
  python-statemachine (narrow use; persistence and queue authority remain
  in-app). See Phase 11 implementation.
- Keep the core request queue app-owned in Postgres. Do not adopt Celery,
  Temporal, PGMQ, or a dedicated broker for Phases 11-14.
- Reuse existing `SessionState`, `PendingApproval`, `PendingRetry`,
  normalized inbound payloads, and resolved execution-context shapes. Extend
  only where needed for leases, attempts, and terminal disposition.
- Use an off-the-shelf Postgres-backed job library only later for secondary
  jobs such as billing, cleanup, reconciliation, or scheduled maintenance.

---

## Assumptions And Defaults

- The roadmap should be optimized for a Postgres-first deployment model, not
  for dual backend support.
- Phase 12 should be executable without building an in-place SQLite upgrade
  path or SQLite-to-Postgres import tool. Those are optional follow-on tasks,
  not development-time gating requirements.
- The master roadmap should present a strict execution order, not priority
  buckets.
- Confidence work remains in the roadmap even though it is not user-facing,
  because the infrastructure phases materially change failure modes.
- Workflow contracts are defined first; library choice (python-statemachine)
  is narrow and subordinate to the explicit state/ownership model.
- Payments and billing stay last because they depend on stable transport,
  worker ownership, and trustworthy execution accounting.
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
