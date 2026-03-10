# Commercial Product Plan

This document describes the product we are building and the shape it must
have to feel finished, trustworthy, and commercially usable. It is not the
build log. Current implementation status lives in
[STATUS-commercial-polish.md](STATUS-commercial-polish.md).

Use this document as the planning reference if the bot were rebuilt from
scratch.

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

## Product Capabilities

The product is complete when these capability areas are in place.

### A. Conversation and execution

- normalized inbound transport
- per-chat session state
- request execution and provider progress updates
- file upload/download flows
- conversation reset and export

### B. Safety and control

- approval and retry flows
- explicit inspect vs edit policy
- per-chat project binding
- stale-context invalidation
- rate limiting
- health checks and operator visibility

### C. Capability management

- skill discovery
- skill activation/deactivation
- credential prompting, validation, storage, and clearing
- skill info and provider compatibility
- managed skill install/update/uninstall

### D. Runtime durability

- durable session storage
- recoverable skill store
- runtime health diagnostics
- session normalization and self-healing
- webhook/polling parity

### E. Distribution and ecosystem

- managed immutable skill store
- remote registry-backed skill discovery and installation
- provider-specific execution extensions

### F. Confidence and quality

- scenario tests for user workflows
- invariant tests for cross-cutting contracts
- edge-case coverage around callbacks, sessions, providers, formatting, and
  store integrity

---

## Build Program

If rebuilding from scratch, build in this order.

### Phase A — Core Telegram product loop

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

### Phase B — Safety and trust controls

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

### Phase C — Skills and credentials

Goal: let the bot grow capabilities without becoming opaque.

Includes:

- skill catalog
- skill activation and removal
- skill information and readiness display
- conversational credential setup
- encrypted per-user credential storage
- `/clear_credentials`

Acceptance:

- a user can understand what a skill does before enabling it
- missing credentials are handled as a guided flow, not a crash or silent fail

### Phase D — Output quality and mobile usability

Goal: make the bot pleasant to use in Telegram on real devices.

Includes:

- table rendering
- robust HTML splitting
- compact mode
- raw response retrieval
- export

Acceptance:

- long responses remain legible on mobile
- exported history is useful and honest about what it captures

### Phase E — Durable runtime and execution context

Goal: make state explicit, durable, and safe across richer sessions.

Includes:

- SQLite-backed session store
- typed session boundary
- authoritative resolved execution context
- per-chat project binding
- file policy
- context-hash invalidation

Acceptance:

- changing role, skills, project, policy, or provider config invalidates stale
  state everywhere it should
- `/session` always reflects the same execution context the provider sees

### Phase F — Managed capability distribution

Goal: ship skills as managed capabilities, not mutable ad hoc directories.

Includes:

- immutable content-addressed object store
- atomic refs
- GC and schema guard
- custom override tier
- managed update and diff flows

Acceptance:

- install/update/uninstall do not depend on fragile in-place mutation
- users can tell whether a skill is catalog, managed, or custom

### Phase G — Registry and ecosystem

Goal: allow durable remote capability distribution on top of the managed store.

Includes:

- registry index
- artifact fetch and verification
- digest enforcement before activation
- search and install UX

Acceptance:

- tampered artifacts do not become active state
- registry-backed skills behave like normal managed skills after install

### Phase H — Hardening and invariants

Goal: make regressions expensive and obvious.

Includes:

- invariant test suite
- edge-case test suites
- shared test harnesses
- health/reporting consistency across CLI and Telegram entry points

Acceptance:

- high-risk cross-cutting invariants are tested directly
- major runtime behavior is protected by contract tests, not only scenario tests

---

## Cross-Cutting Contracts

These are the rules future changes must preserve.

### Execution identity contract

There is one authoritative execution identity per request. It includes:

- role
- active skills
- skill digests
- provider config digest (skill YAML content, scoped to active provider)
- execution config digest (model, codex_sandbox, codex_full_auto,
  codex_dangerous, codex_profile)
- base extra dirs
- project id
- effective working dir (resolved from project binding or config default)
- file policy
- provider name

This identity is the basis for:

- context hash
- approval validity
- retry validity
- Codex thread invalidation (context hash change clears thread)
- `/session` display

Codex thread invalidation has a second trigger independent of context hash:
bot restart (boot_id change) also clears stale threads, because the provider
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
- ownership / authorization

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

The formatting layer is responsible for adapting model output to Telegram.
If raw model output is unreadable in Telegram, the bot still owns the problem.

### Health contract

`/doctor` and CLI doctor should be two renderers over the same health
orchestration, not separate implementations.

---

## Test Strategy

The plan assumes three complementary test layers.

### 1. Scenario tests

End-to-end user workflows through handler entry points.

Examples:

- normal message flow
- approval flow
- skill activation and credential setup
- export and compact mode

### 2. Contract / invariant tests

Small high-value tests for cross-cutting rules.

Examples:

- inspect mode can never become writable for Codex
- changing execution identity invalidates stale approvals
- registry digest mismatch leaves no installed state
- configured extra dirs reach provider context

### 3. Edge-case suites

Boundary conditions the happy path misses.

Examples:

- double-click callbacks
- provider timeout or empty response
- formatting edge cases
- session reset during pending state

---

## Product Docs Split

The docs should have distinct jobs:

- `README.md`
  User-facing product entry point
- `STATUS-commercial-polish.md`
  Build log and current implementation status
- `PLAN-commercial-polish.md`
  Product vision and rebuildable plan
- `ARCHITECTURE.md`
  Contracts, components, and runtime model
- `OPS-*`
  Operator playbooks

If a document starts turning into another document, split it rather than
blurring the audience.

---

## Product Extensions

These are legitimate product areas, but they are intentionally outside the
core build described above.

### Usage accounting and billing

The core product does not require billing hooks to be coherent. A commercial
layer can be added later for:

- token and cost accounting
- quota enforcement
- billing integration
- usage reporting

### Multi-process webhook architecture

Webhook mode already exists in the product. The extension area is
multi-worker / multi-process webhook deployment. That would require:

- stronger cross-process serialization guarantees
- concurrency semantics beyond in-memory chat locks
- explicit deployment guidance for multi-worker operation

### Confidence extensions

The current test strategy covers product behavior well, but a larger product
surface can justify deeper confidence layers such as:

- concurrency-focused handler tests
- richer attachment transport integration tests
- streaming progress integration tests
- real provider CLI smoke tests

### Policy and project expansion

The current project model and `inspect|edit` policy are intentionally simple.
If the product grows, likely extension areas are:

- richer project scoping models
- more granular file policies
- stronger organizational policy controls

### Registry trust expansion

The registry already verifies digests and installs managed artifacts, but a
broader ecosystem may later require:

- stronger publisher trust and governance models
- more explicit organizational trust configuration
- richer registry metadata and policy controls

---

## Completion Standard

The product is commercially ready when:

- the core user journeys are clean and understandable
- execution context is explicit and safe
- the skill system is discoverable and recoverable
- the output is Telegram-native and mobile-friendly
- operators can diagnose and manage the system confidently
- cross-cutting invariants are enforced by tests, not memory
