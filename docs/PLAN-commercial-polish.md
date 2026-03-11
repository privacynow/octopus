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
- `PLAN-agent-roles-and-skills.md`
  Archived implementation reference for the detailed roles/skills build.
- `STATUS-agent-roles-and-skills.md`
  Archived shipped-status reference for the detailed roles/skills build.

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
- Phases 1-10 are sealed as shipped history.
- New roadmap work begins at Phase 11.
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive
  messages. It is not part of the core transport contract.
- Postgres is the sole runtime backend after migration. SQLite is import-source
  only during cutover.

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
| 11 | Workflow ownership extraction | Remaining |
| 12 | Postgres runtime cutover | Remaining |
| 13 | Postgres queue authority in webhook mode | Remaining |
| 14 | Multi-process / multi-worker deployment | Remaining |
| 15 | Durability confidence phase | Remaining |
| 16 | Product polish on stable foundations | Remaining |
| 17 | Behavior extensions | Remaining |
| 18 | Registry trust and governance | Remaining |
| 19 | Usage accounting, quotas, and billing | Remaining |

---

## Sealed Phases 1-10

Phases 1-10 are shipped and sealed. They stay here as historical reference,
but the active roadmap begins at Phase 11.

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

For the detailed capability-system lineage behind Phases 3-5, keep using
[PLAN-agent-roles-and-skills.md](PLAN-agent-roles-and-skills.md) and
[STATUS-agent-roles-and-skills.md](STATUS-agent-roles-and-skills.md).

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
- Polling remains single-owner. The scale path is webhook plus durable queue
  plus workers.
- The core request queue remains application-owned. Generic broker or
  workflow systems are not the default answer for Phases 11-14.
- The failure pattern to remember is split ownership between live handlers and
  workers. That is where fresh-command races, replay confusion, and bad
  terminal-state handling came from.

### 5. Workflow ownership and engineering discipline

- Workflow extraction is only justified when repeated durable-state bugs and
  review cost show that open-coded transitions are the bottleneck.
- If extraction happens, it should be narrow and contract-first: start with
  transport/recovery and approval/retry, not with a whole-app state-machine
  rewrite.
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

### Pending request contract

Pending approval and retry state must always carry:

- original requester identity
- original prompt and images
- original context hash
- creation timestamp

Validation must check:

- expiry
- context freshness
- ownership or authorization

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

### Health contract

`/doctor` and CLI doctor should be two renderers over the same health
orchestration, not separate implementations.

### Transport delivery contract

- one active ingress owner per bot token (polling is single-owner)
- every inbound update receives a visible response or acknowledgment
- per-chat ordering is preserved; no concurrent writes out of order
- duplicate update delivery (same `update_id`) is transport-idempotent
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

### 3. Edge-case suites

Boundary conditions the happy path misses.

Examples:

- double-click callbacks
- provider timeout or empty response
- formatting edge cases
- session reset during pending state

### 4. Remaining-phase coverage

- Workflow extraction tests: allowed and forbidden transitions, terminal
  ownership, duplicate delivery idempotency, replay/discard races, and second
  interruption handling.
- Postgres cutover tests: schema bootstrap, one-way SQLite import, rollback
  safety, and backward-compatible payload deserialization.
- Queue and worker tests: row-lock claiming, lease expiry, cross-process
  ordering, webhook enqueue-plus-worker dispatch, and recovery after crash.
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
- `OPS-*`
  Operator playbooks.

If a document starts turning into another document, split it rather than
blurring the audience.

---

## Remaining Phases

These phases are the active roadmap. Every still-relevant deferred or future
item belongs somewhere in this ordered sequence.

### Phase 11 - Workflow Ownership Extraction

Behavior-preserving refactor only.

- Extract two authoritative workflow owners first: transport/recovery and
  approval/retry.
- Reuse existing normalized inbound payloads, typed session dataclasses, and
  resolved execution context.
- Introduce store interfaces around the current persistence seams so handlers
  and workers stop open-coding durable transitions.
- Keep the extraction narrow and contract-first.
- Prefer explicit transition code before any library evaluation.
- Do not turn the whole application into one giant state machine.

### Phase 12 - Postgres Runtime Cutover

Make Postgres the only supported runtime backend after migration.

- Add `BOT_DATABASE_URL` and pool settings.
- Use `psycopg` v3 async pooling.
- Avoid an ORM.
- Keep schema management repo-owned with versioned SQL plus a small migration
  runner.
- Provide one-way import from SQLite session and transport data into
  Postgres.
- Preserve current payload JSON shapes and current dataclass contracts.

### Phase 13 - Postgres Queue Authority In Webhook Mode

Keep the core Telegram request path as an app-owned Postgres queue, not a
generic task broker.

- Retain explicit `updates` and `work_items` tables.
- Retain row-lock claiming, leases, recovery metadata, and replay/discard
  ownership.
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

- Postgres is the sole runtime backend after migration. SQLite is import-source
  only during cutover.
- Extract workflow ownership before any database migration so the new backend
  does not inherit open-coded transition logic.
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
- The master roadmap should present a strict execution order, not priority
  buckets.
- Confidence work remains in the roadmap even though it is not user-facing,
  because the infrastructure phases materially change failure modes.
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
