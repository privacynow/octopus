# Commercial Product Plan

This document is the master roadmap for the finished product shape and the
order in which it should be built. It is not the build log. Current
implementation status lives in
[STATUS-commercial-polish.md](STATUS-commercial-polish.md). Runtime
boundaries and storage authority live in
[ARCHITECTURE.md](ARCHITECTURE.md).

Use this document as the planning reference if the bot were rebuilt from
scratch.

---

## Planning References

- `PLAN-commercial-polish.md`
  Master roadmap, product vision, and ordered execution plan.
- `STATUS-commercial-polish.md`
  Phase-by-phase shipped/current status mirror.
- `ARCHITECTURE.md`
  Source of truth for runtime boundaries, storage authority, and queue
  ownership.
- `PLAN-agent-roles-and-skills.md`
  Archived implementation reference for the detailed capability-system build.
- `STATUS-agent-roles-and-skills.md`
  Archived shipped-status reference for the detailed capability-system build.

The detailed historical steps inside the separate roles/skills design doc stay
as they are. This document summarizes that shipped work under Phases 3-5 and
keeps the master roadmap linear.

---

## Product Definition

Telegram Agent Bot is a Telegram-native interface to a local coding agent.
The product is not "a CLI wrapper in chat." The product is:

- a secure remote control surface for Claude Code or Codex
- a mobile-friendly conversation interface for real development work
- a capability system that layers skills, credentials, projects, and safety
  controls on top of raw model execution
- an operator-manageable service that can run for one user, a team, or a
  shared group chat

The bot should feel like a coherent product even when the underlying provider
changes.

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
4. Skills behave like capabilities, not like hidden prompt fragments. Users
   can discover them, understand them, activate them, and recover from
   missing credentials cleanly.
5. Output is readable in Telegram on a phone. If the model emits something
   awkward for Telegram, the bot adapts it.
6. Operators can understand what the bot is doing, inspect health, and manage
   capability distribution without needing to read the code.

---

## Primary User Journeys

### 1. Ask for work

The user sends a normal message, optionally with files. The bot runs the
provider against the correct execution context and returns a readable answer.

### 2. Review before execution

When approval mode is on, the bot shows a plan first. The user can approve,
reject, or let it expire. If context changes, the request must not continue.

### 3. Add a capability

The user browses skills, inspects one, sees whether it is ready or needs
setup, activates it, and is prompted for credentials only when needed.

### 4. Recover from mistakes

The user can cancel pending state, clear credentials, reset a session, switch
project, switch policy, or remove a skill without getting trapped.

### 5. Operate a real bot instance

The operator can bootstrap a bot, run health checks, inspect sessions, manage
skills, and update the bot without losing the product model.

---

## Non-Goals

These are intentionally out of scope for the core product plan:

- full billing and quota systems
- multi-agent delegation as a user-facing concept
- Docker/Kubernetes control plane concerns
- hosted SaaS architecture decisions
- general-purpose package manager behavior outside the skill system

Those may matter later, but they are not the core product definition.

---

## Design Principles

### User-first surface

The README and Telegram UX should speak to end users first. Internal module
structure, implementation details, and operator internals belong in dedicated
docs.

### One authoritative runtime model

Execution identity must be resolved once and reused everywhere. Approval,
retry, provider state invalidation, and `/session` should all describe the
same underlying truth.

### Safety through explicit state

Approval mode, file policy, project binding, skill activation, and credential
setup should all be visible and inspectable. Hidden state is where confusing
bugs become safety bugs.

### Capability layering

Raw provider execution is only one layer. The finished product also depends on
skills, credentials, projects, file policy, output shaping, and admin tools.

### Telegram-native output

Readable mobile output is a correctness property, not cosmetic polish.

### Rebuildability

The plan should describe a shape we can rebuild from scratch, not a sequence
of patches we happened to ship.

---

## Roadmap Rules

- The roadmap is one strict execution order, not priority buckets.
- Phases 1-10 are sealed as shipped history.
- New roadmap work begins at Phase 11.
- This master plan keeps the product-vision role. Shipped history is retained
  below instead of being deleted.
- The roadmap is optimized for a Postgres-first deployment model. After
  migration, Postgres is the sole runtime backend. SQLite is import-source
  only during cutover.
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive user
  messages. It is not part of the core transport contract.

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

These phases are shipped history. They stay in this document so the roadmap
retains its lineage, but they are sealed rather than reopened as new planning
work.

### Phase 1 - Core Telegram Loop

Historical anchor: former Phase A.

Goal: make the bot useful for one user in one chat.

Includes:

- transport normalization
- message routing
- provider execution
- file uploads and artifact sending
- `/help`, `/start`, `/new`, `/session`
- basic formatting and chunking

Acceptance:

- a user can send a message with or without files and get a readable reply
- a fresh session and a reset session both behave predictably

### Phase 2 - Safety, Approvals, and Rate Limiting

Historical anchor: former Phase B.

Goal: make execution controllable rather than optimistic.

Includes:

- approval mode
- pending approval and retry state
- explicit expiry and stale-context rejection
- `/cancel`
- rate limiting
- `/doctor`

Acceptance:

- no request executes after its context changes
- denial and retry flows are understandable and recoverable
- a slow or broken provider reports failure cleanly

### Phase 3 - Roles and Instruction-Only Skills

Historical anchors: capability-system foundation from the separate
roles/skills plan and status docs.

Goal: let the bot expose clear capability layering before credentials,
provider-specific setup, or store distribution enter the picture.

Includes:

- role catalog and role selection
- instruction-only skill discovery and activation
- deterministic skill resolution at the session surface
- explicit session visibility for active role and active skills

Acceptance:

- a user can understand what a role or instruction-only skill does before
  enabling it
- instruction-only capabilities behave like visible product features, not
  hidden prompt fragments

Historical detail remains in:

- [PLAN-agent-roles-and-skills.md](PLAN-agent-roles-and-skills.md)
- [STATUS-agent-roles-and-skills.md](STATUS-agent-roles-and-skills.md)

### Phase 4 - Credentialed and Provider-Specific Skills

Historical anchors: capability-system credential/setup work from the separate
roles/skills docs.

Goal: let richer skills attach real setup requirements without making the bot
opaque or fragile.

Includes:

- conversational credential setup
- encrypted per-user credential storage
- readiness display for missing setup
- provider-specific skill configuration and compatibility handling
- `/clear_credentials`

Acceptance:

- missing credentials are handled as a guided flow, not a crash or silent fail
- provider-specific capability setup is explicit and recoverable

Historical detail remains in:

- [PLAN-agent-roles-and-skills.md](PLAN-agent-roles-and-skills.md)
- [STATUS-agent-roles-and-skills.md](STATUS-agent-roles-and-skills.md)

### Phase 5 - Skill Store and Capability Distribution

Historical anchors: former Phases F and G, plus the shipped managed-store and
registry work.

Goal: ship skills as managed capabilities rather than mutable ad hoc
directories.

Includes:

- immutable content-addressed object store
- atomic refs
- GC and schema guard
- custom override tier
- managed update and diff flows
- registry index, artifact fetch, and digest verification
- search and install UX

Acceptance:

- install/update/uninstall do not depend on fragile in-place mutation
- users can tell whether a skill is catalog, managed, or custom
- tampered artifacts do not become active state

### Phase 6 - Output, Compact Mode, and Progress UX

Historical anchors: former Phase D and former Phase III.

Goal: make the bot pleasant to use in Telegram on real devices and keep long
requests legible while they run.

Includes:

- table rendering
- robust HTML splitting
- compact mode
- raw response retrieval
- export
- expandable blockquote rendering
- inline expand/collapse for long replies
- summary-first response shape
- provider-neutral progress wording
- liveness heartbeat and normalized progress events

Acceptance:

- long responses remain legible on mobile
- first visible progress arrives before provider invocation
- idle waiting states show visible liveness instead of freezing
- provider names, thread IDs, and internal mechanics do not leak into normal
  user-facing progress

### Phase 7 - Durable Session State and Execution Context

Historical anchor: former Phase E.

Goal: make state explicit, durable, and safe across richer sessions.

Includes:

- durable session store
- typed `SessionState` boundary
- authoritative resolved execution context
- per-chat project binding
- file policy
- context-hash invalidation

Acceptance:

- changing role, skills, project, policy, or provider config invalidates stale
  state everywhere it should
- `/session` always reflects the same execution context the provider sees

### Phase 8 - Public Trust, Model Profiles, and Settings UX

Historical anchors: former Phase I and former Phases IIa/IIb.

Goal: make the bot safe to expose publicly while keeping model and session
controls explicit and usable.

Includes:

- mixed-trust auth contract: `trusted | public`
- public execution-scope enforcement in resolved context
- forced inspect-only public file policy
- isolated public working directory
- mandatory public-mode rate limiting
- stable model profiles: `fast`, `balanced`, `best`
- per-chat model-profile selection
- inline-keyboard driven settings UX for model, policy, approval, compact,
  and project selection

Acceptance:

- a public user cannot use the bot as an unrestricted compute endpoint
- public restrictions are enforced in the resolved execution context, not only
  in handlers
- users can change common session settings without typing identifiers

### Phase 9 - Durable Transport, Transport Idempotency, Webhook Mode, and Restart Recovery

Historical anchors: former Phase IV, the shipped webhook foundation, and the
restart-recovery hardening work.

Goal: make inbound delivery, queue ownership, and interruption handling
durable.

Includes:

- durable `update_id` journal
- explicit `updates` and `work_items` durable transport state
- queued/busy feedback with durable work-item ownership
- polling-conflict detection
- webhook ingress foundation
- crash recovery for claimed items
- explicit `pending_recovery` replay/discard flow
- fresh-message supersession of stale interrupted work

Acceptance:

- every inbound update receives a visible response or acknowledgment
- duplicate `update_id` delivery is safe
- per-chat ordering is preserved durably
- interrupted work is never blindly replayed without explicit user intent

Notes:

- This phase seals `transport idempotency` as shipped.
- `content dedup` is not part of this sealed phase. It remains optional future
  work in Phase 17.

### Phase 10 - Structural Hardening, Invariants, and Test Ownership

Historical anchors: former Phase H, the workflow-hardening track, and the
test-ownership/isolation work that sealed the shipped runtime.

Goal: make regressions expensive and obvious.

Includes:

- invariant test suite
- edge-case and contract suites
- shared test harnesses
- health/reporting consistency across CLI and Telegram entry points
- workflow guardrails around transport, approval, retry, and recovery paths
- test-ownership refactor and isolation cleanup

Acceptance:

- high-risk cross-cutting invariants are tested directly
- major runtime behavior is protected by contract tests, not only scenario
  tests
- the test tree has clear owners for transport, execution context, request
  flow, output, and recovery behavior

---

## Remaining Phases

Every still-relevant deferred or future item now lives here in ordered form.

### Phase 11 - Workflow Ownership Extraction

Behavior-preserving refactor only.

- Extract two authoritative workflow owners first: transport/recovery and
  approval/retry.
- Reuse existing normalized inbound payloads, typed session dataclasses, and
  resolved execution context.
- Introduce store interfaces around the current persistence seams so handlers
  and workers stop open-coding durable transitions.

### Phase 12 - Postgres Runtime Cutover

Make Postgres the only supported runtime backend after migration.

- Add `BOT_DATABASE_URL` and pool settings.
- Use `psycopg` v3 async pooling.
- Avoid an ORM.
- Keep schema management repo-owned with versioned SQL plus a small migration
  runner.
- Provide one-way import from SQLite session and transport data into Postgres.
- Preserve current payload JSON shapes and current dataclass contracts.

### Phase 13 - Postgres Queue Authority in Webhook Mode

Keep the core Telegram request path as an app-owned Postgres queue, not a
generic task broker.

- Retain explicit `updates` and `work_items` tables.
- Retain row-lock claiming, leases, recovery metadata, and replay/discard
  ownership.
- In webhook mode, ingress should normalize, persist, and acknowledge quickly.
- Workers become the primary execution path.

Terminology lock:

- `transport idempotency`: durable `update_id` journal and work-item
  uniqueness
- `content dedup`: optional user-message suppression policy, not part of core
  transport

### Phase 14 - Multi-Process / Multi-Worker Deployment

Add true cross-process ingress and worker concurrency on top of the Postgres
queue.

- Preserve per-chat single-flight ordering, `update_id` idempotency, recovery
  safety, and explicit terminal ownership across processes.
- Polling stays single-owner and dev-oriented.
- Scale path is webhook plus Postgres plus workers.
- Add queue depth, lease, worker-health, and recovery metrics.

### Phase 15 - Durability Confidence Phase

Add the confidence work that becomes important only after the infrastructure
shift.

- cross-process queue tests
- crash/lease-recovery tests
- webhook ingress durability tests
- real provider smoke coverage for the new worker model

This is a distinct phase, not hidden inside earlier acceptance criteria.

### Phase 16 - Product Polish on Stable Foundations

Add the small UI work that is only worth doing after queue and worker
semantics stabilize.

- Add `/project` inline keyboard by reusing the existing settings-inline-
  keyboard pattern and callback handling.
- Add optional verbose progress mode only after queue and worker semantics are
  stable.

Keep this phase intentionally small and UI-focused.

### Phase 17 - Behavior Extensions

Add demand-gated behavior extensions after the runtime is stable.

- Add demand-gated `content dedup` using a durable content fingerprint and
  explicit user acknowledgment instead of silent drop.
- Expand project and policy scope using the existing project binding and
  resolved execution-context model rather than inventing a second scoping
  system.

### Phase 18 - Registry Trust and Governance

Extend the managed store with trust and governance on top of the existing
digest-verification model.

- publisher signing
- organizational trust policy
- reuse of the current object/ref store architecture
- reuse of the current registry metadata flow

### Phase 19 - Usage Accounting, Quotas, and Billing

Build this last.

- Meter usage from authoritative execution completion points, not from
  provider-progress heuristics.
- Add usage recording first.
- Add quota enforcement second.
- Add billing integration and reporting third.
- If secondary background jobs are needed here, use a Postgres-native task
  library for those non-core jobs only.

---

## Architecture Decisions

- Postgres is the sole runtime backend after migration. SQLite is
  import-source only during cutover.
- Extract workflow ownership before any database migration so the new backend
  does not inherit open-coded transition logic.
- Keep the core request queue app-owned in Postgres. Do not adopt Celery,
  Temporal, PGMQ, or a dedicated broker for Phases 11-14.
- Reuse existing `SessionState`, `PendingApproval`, `PendingRetry`,
  normalized inbound payloads, and resolved execution-context shapes; extend
  only where needed for leases, attempts, and terminal disposition.
- Use an off-the-shelf Postgres-backed job library only later for secondary
  jobs such as billing, cleanup, reconciliation, or scheduled maintenance.

---

## Test Plan

- Workflow contract tests for allowed and forbidden transitions, terminal
  ownership, duplicate delivery idempotency, replay/discard races, and second
  interruption handling.
- Postgres cutover tests for schema bootstrap, one-way SQLite import, rollback
  safety, and backward-compatible payload deserialization.
- Queue and worker tests for row-lock claiming, lease expiry, cross-process
  ordering, webhook enqueue-plus-worker dispatch, and recovery after crash.
- Product tests for `/project` inline keyboard, public-trust interactions,
  content dedup acknowledgment, and richer project/policy scope.
- Usage tests for authoritative metering, quota enforcement, replay-safe
  accounting, and billing-event integrity.

---

## Assumptions and Defaults

- The roadmap is optimized for a Postgres-first deployment model, not for
  dual backend support.
- The master roadmap presents a strict execution order, not priority buckets.
- Confidence work stays in the roadmap even though it is not user-facing,
  because the infrastructure phases materially change failure modes.
- Payments and billing stay last because they depend on stable transport,
  worker ownership, and trustworthy execution accounting.
- Queue/library evaluation basis:
  [Celery broker docs](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html),
  [Temporal workflows](https://docs.temporal.io/workflows),
  [PGMQ](https://pgmq.github.io/pgmq/),
  [Procrastinate](https://procrastinate.readthedocs.io/).

---

## Completion Standard

A roadmap phase is only complete when:

- the shipped behavior exists in code
- the relevant contract and regression tests exist
- `STATUS-commercial-polish.md` reflects the new phase state
- `ARCHITECTURE.md` matches the resulting runtime authority and boundary
  decisions

Shipped phases remain sealed history. New work should be added by advancing the
remaining numbered phases rather than reopening Phases 1-10.
