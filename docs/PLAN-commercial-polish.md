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

### G. Public trust profile

- mixed-trust auth contract: per-user resolution of `trusted | public`
- restricted execution scope for public users
- forced inspect-only file policy
- isolated public working directory
- disabled skill management for public users
- mandatory rate limiting in public mode

### H. User-perceived performance and model control

- model profiles (fast / balanced / best) as stable user-facing tier names
- per-chat model profile selection, trust-tier-aware
- inline-keyboard driven command UX for all session settings
- compact mode as default for mobile-oriented deployments
- expandable blockquote and inline expand/collapse for long responses
- summary-first response shape via prompt structure
- sub-second first visible progress
- prompt weight reduction for faster time-to-first-token

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

### Phase I — Public trust profile

Goal: make the bot safe to expose publicly without relying on approval mode
as a security boundary.

Depends on: Phase B (safety controls), Phase E (execution context, file
policy, project binding).

The threat model: when `BOT_ALLOW_OPEN=1`, any Telegram user can interact
with the bot. Approval mode is not a security boundary because the same
anonymous user who requests can also approve. The correct model is a
restricted trust profile with isolated scope and reduced capabilities.

Architectural decision: the auth contract uses **mixed trust** — per-user
resolution of `trusted | public`. This is not a global toggle. When
`allow_open` is true, each user is resolved individually: users in the
allowed set are `trusted` and get full access; all others are `public` and
get restricted scope. This means a single bot instance can serve both
trusted team members and anonymous public users simultaneously.

#### I.1 Public-mode contract

When a user is not in the allowed-user set and the bot is in open mode, the
public trust profile applies:

- `file_policy` forced to `inspect` (read-only, non-overridable)
- working directory forced to an explicit public root
  (`BOT_PUBLIC_WORKING_DIR`) instead of the operator's main working dir
- `extra_dirs` restricted to public root only (no operator extra dirs)
- skill activation, removal, setup, and management disabled
- `/send` disabled or constrained to public root
- `/project` disabled (public users do not get project access)
- `/model` optionally restricted to a subset of profiles

#### I.2 Mandatory rate limiting in public mode

When `allow_open=True`, rate limiting must be explicitly configured or
sensible defaults apply automatically. A public bot with no rate limit is an
open compute endpoint.

- if `rate_limit_per_minute=0` and `rate_limit_per_hour=0` in public mode,
  apply conservative defaults (e.g., 5/min, 30/hour)
- operator can override with explicit values
- `/doctor` warns if public mode is active with no explicit rate limits

#### I.3 Public-mode enforcement — two layers

Public-mode enforcement has two distinct layers that must not be conflated:

**Layer 1: Execution-scope enforcement (in `resolve_execution_context`)**

Execution-scope constraints — forced inspect, forced public root, stripped
extra_dirs — must resolve into `ResolvedExecutionContext`. This is where
file scope and policy are enforced. If these live only as handler checks,
they will drift between message, approval, retry, and future entry points.

- `resolve_execution_context()` receives a `trust_tier` parameter
- when `trust_tier == "public"`:
  - `file_policy` forced to `"inspect"` regardless of session override
  - `working_dir` forced to `BOT_PUBLIC_WORKING_DIR`
  - `base_extra_dirs` forced to empty (no operator extra dirs)
- these constraints flow into context hash, approval validation, retry
  validation, provider context — automatically, because they are in the
  resolved context

**Layer 2: Command-availability gating (in handlers)**

Command restrictions — disabling `/skills`, `/project`, `/send`,
`/policy` — are handler-layer concerns. They control what a public user
can invoke, not what the execution context resolves to.

- `is_public_user(user)` predicate: `allow_open` is true and user is not
  in any allowed-user set
- public users cannot invoke skill management, project binding, policy
  override, or unrestricted `/send`
- admin and store commands remain gated by `is_admin()` (already correct)
- approval mode may optionally be forced on for public users as a UX
  transparency measure, but it is not the security boundary

This split means: even if a handler check is missed or a new entry point is
added, the resolved execution context still enforces the public scope.

Acceptance:

- a public user cannot read or write files outside the public root
- a public user cannot activate skills or manage credentials
- a public user cannot use the bot as an unrestricted compute endpoint
- an operator running a public bot gets clear `/doctor` warnings about
  missing rate limits or missing public root config
- the public trust profile is a concrete scope restriction, not an abstract
  identity system
- execution-scope constraints are enforced in the resolved context, not
  only in handler checks

### Phase IIa — Model profiles: state and plumbing

Goal: add an authoritative effective-model field to the resolved execution
context so model selection works through the same contract as every other
execution identity field.

Depends on: Phase E (execution context, session state, context hash).
Does NOT depend on Phase I (public trust). Public trust can later cap which
profiles are available by constraining the input to the same resolution.

#### IIa.1 Model profile mapping

Add a provider-aware model tier system:

- three stable profile names: `fast`, `balanced`, `best`
- each maps to a provider-specific model ID in config
- operator configures available profiles and the default profile
- config: `BOT_MODEL_PROFILES=fast:claude-haiku-4-5-20251001,balanced:claude-sonnet-4-6,best:claude-opus-4-6`
- config: `BOT_DEFAULT_PROFILE=balanced`

The profile names are what users see. Model IDs are what providers receive.
This is better than raw model strings because:

- users don't need to remember model identifiers
- validation is trivial (three valid values)
- when Anthropic ships a new model, the operator updates the mapping without
  users changing anything
- provider portability is cleaner

"Faster default model" is not a separate initiative. It is a config choice:
set `BOT_DEFAULT_PROFILE=balanced` in setup wizard defaults.

#### IIa.2 Per-chat model profile in session state

Add `model_profile` to `SessionState`:

- empty string means use config default
- model profile is resolved at execution time: session override > config
  default
- effective model ID flows into `execution_config_digest` (already in hash)
- changing profile correctly invalidates pending approvals and Codex threads

#### IIa.3 Provider plumbing

- `resolve_execution_context()` resolves effective model from session
  profile override > config default
- effective model ID flows into `execution_config_digest`
- provider `RunContext` receives effective model ID
- providers use effective model ID instead of raw `config.model`

Acceptance:

- model profile selection flows through the authoritative execution context
- `/session` reflects the effective model profile, not just the raw model ID
- changing model profile invalidates stale approvals and Codex threads
- provider receives the resolved model, not the config default

### Phase IIb — Inline-keyboard UX for session settings

Goal: make all session settings discoverable without typing identifiers.

Depends on: Phase IIa (model profiles), existing toggle commands.

This is a UX pass, not a logic change. The session mutations are the same as
the text commands. The callback handler pattern already exists for
approve/reject/retry.

Commands to convert:

- `/model` → `[Fast]  [Balanced]  [Best]`
- `/policy` → `[Read only]  [Read & write]`
- `/approval` → `[Review first]  [Run immediately]`
- `/compact` → `[Short answers]  [Full answers]`
- `/project` → buttons for each configured project + `[Clear]`
- `/skills add` (no args) → available skills as buttons

When a command is invoked with no arguments, show current state and action
buttons instead of requiring the user to type the exact value.

Public-trust integration (after Phase I lands): public users see only the
profiles and settings they are allowed to change. Buttons for restricted
settings are either hidden or shown as disabled with explanation.

Acceptance:

- a user can change model, policy, approval, compact, and project without
  typing any identifier or keyword
- public users see only the profiles they are allowed to use

### Phase III — Compact defaults and perceived latency

Goal: make the bot feel fast and readable on mobile without requiring user
configuration.

Depends on: Phase D (compact mode, `/compact`, `/raw`), Phase E (execution
context, rendering contract).

This phase layers on top of the resolved context and rendering contract. It
does not invent parallel state.

#### III.1 Compact mode defaults

- recommend `BOT_COMPACT_MODE=1` for mobile-oriented instances
- mention `/compact on|off` toggle in first-run welcome message
- no device detection — Telegram's Bot API does not provide client metadata
- no heuristics (private-vs-group guessing is unreliable and feels arbitrary)
- possibly default `BOT_COMPACT_MODE=1` in new instance configs generated
  by `setup.sh`

#### III.2 Expandable blockquote rendering

Telegram Bot API supports `<blockquote expandable>` in HTML mode. Use this
as the native "compact with expand" primitive:

- short visible summary above the fold
- full detail collapsed in an expandable blockquote below
- no second LLM pass required — the rendering layer structures the existing
  response

This is the best Telegram-native primitive for "show less, expand on demand."

#### III.3 Inline expand/collapse via message editing

For responses that exceed the expandable-blockquote limit, use
`editMessageText` with an inline "Show full answer" / "Collapse" button:

- bot sends compact version with a `[Show full]` inline button
- button press edits the message to show the full response (or vice versa)
- uses the existing callback handler pattern
- `/raw` remains available for the complete unformatted output

**Storage contract for expand/collapse:** The full response is already stored
in the raw-response ring buffer (per-chat, filesystem-backed). The
expand/collapse flow regenerates the rendered variant from the raw ring
buffer on button press — it does not store a second rendered copy. This
means:

- no new per-message response cache or rendered-variant store
- the raw ring buffer is the single source of truth for response content
- if the raw entry has been evicted (ring buffer rotated), the expand
  button shows a "response no longer available, use /raw" message
- the callback payload carries the ring-buffer slot index, not the content

#### III.4 Summary-first response shape

Ask the model to produce a structured response:

- 2–4 line answer-first summary
- then full detail below

This improves perceived latency without needing a second LLM pass. It is a
prompt/role instruction, not a post-processing step.

Do not use a second fast LLM by default for compacting. If the fast model
runs after the main answer finishes, it improves readability but worsens
end-to-end latency. A second pass is only justified if:

- it replaces the main model for the task, or
- the summary is sent first and details delivered later

#### III.5 Faster first visible progress

Perceived latency improves significantly when the user sees a meaningful
first update almost immediately. Product rule: first visible progress within
1 second of request submission.

This may require:

- sending an immediate "thinking..." status before provider invocation
- tuning progress-streaming intervals
- ensuring the progress callback fires on first provider output, not on a
  polling timer

#### III.6 Prompt weight reduction

Smaller effective prompts reduce time-to-first-token:

- shorter default role text
- fewer always-on skills (only load what the session actually uses)
- avoid injecting capability text for inactive skills
- measure prompt token count as part of `/doctor` or `/session` diagnostics

This is less visible than model switching but contributes to perceived speed.

Acceptance:

- new users discover compact mode without reading docs
- the default feels right for the deployment context
- long responses use expandable blockquotes or inline expand/collapse
- first visible progress arrives within 1 second
- prompt weight is observable and minimized

### Phase IV — Update delivery and burst safety

Goal: ensure every inbound update gets a visible response, even under
bursty same-user or same-chat traffic.

Depends on: Phase A (transport normalization), Phase B (per-chat
serialization), Phase E (durable runtime and session state).

This is a transport reliability feature, not a latency feature. It
strengthens the existing per-chat serialization model without changing
the concurrency architecture. The stateful guarantees (update_id
idempotency, queued request tracking) require the durable state
foundation from Phase E — implementing queue/dedup semantics before
the authoritative durable state layer risks repeating the same
architectural mistake as a late storage migration.

#### IV.1 Polling conflict detection

Add a `/doctor` check for polling conflicts:

- Telegram returns HTTP 409 when a second `getUpdates` call conflicts
  with an active poller
- `/doctor` detects this and warns the operator
- startup logs a warning if conflict is detected
- recommended action: switch to webhook mode or stop the other process

#### IV.2 Idempotent update handling

Track `update_id` to make duplicate delivery safe:

- store last-seen `update_id` per ingress
- if an update arrives with an already-processed `update_id`, skip it
- this protects against Telegram re-delivering updates after a timeout

#### IV.3 Busy/queued feedback

When a request arrives while another is in-flight for the same chat:

- send an immediate "still working on your previous request, yours is
  queued" acknowledgment
- the queued request executes normally when the in-flight request
  completes
- no request is silently dropped or lost

#### IV.4 Content-based deduplication (optional/tunable)

If the same user sends identical text within a short configurable window,
optionally treat it as a duplicate:

- off by default — intentional repeated sends must not be suppressed
- operator-configurable window (e.g., `BOT_DEDUP_WINDOW_SECONDS=0`)
- when enabled, respond once and acknowledge the duplicate
- this is a convenience optimization, not a core contract

The core contract is already sufficient: every inbound update gets a visible
response, `update_id` idempotency prevents processing the same Telegram
update twice, and burst traffic is queued with visible feedback.
Content-based dedup is layered on top for operators who want it.

Acceptance:

- every inbound update receives a visible response or acknowledgment
- duplicate `update_id` delivery is safe
- bursty same-user traffic does not lose messages
- polling conflict is detected and warned in `/doctor`

---

## Cross-Cutting Contracts

These are the rules future changes must preserve.

### Execution identity contract

There is one authoritative execution identity per request. It includes:

- role
- active skills
- skill digests
- provider config digest (skill YAML content, scoped to active provider)
- execution config digest (effective model — resolved from session profile
  override or config default, subject to trust-tier restrictions;
  codex_sandbox, codex_full_auto, codex_dangerous, codex_profile)
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

### Transport delivery contract

- one active ingress owner per bot token (polling is single-owner)
- every inbound update receives a visible response or acknowledgment
- per-chat ordering is preserved; no concurrent writes out of order
- duplicate update delivery (same `update_id`) is idempotent
- polling conflict is detected and warned, not silently tolerated

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

Cross-feature invariant examples (required before merging parallel tracks):

- public mode + model switching does not allow profile escalation
- inspect policy + model profile change preserves inspect enforcement
- compact mode + long replies + public users renders correctly
- project + file policy + approval + model change invalidates correctly

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

These are legitimate product areas that sit outside the current build phases.
They are ordered by likely relevance, not urgency.

### Multi-worker webhook architecture

Webhook mode already exists in the product. The extension area is
multi-worker / multi-process webhook deployment. That would require:

- stronger cross-process serialization guarantees
- concurrency semantics beyond in-memory chat locks
- explicit deployment guidance for multi-worker operation

Note: polling is single-owner by design. Multi-process support means
webhook + shared state, not multi-poller polling. Transport reliability
for single-process operation (polling conflict detection, update_id
idempotency, burst handling) is covered in Phase IV.

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

### Confidence extensions

The current test strategy covers product behavior well, but a larger product
surface can justify deeper confidence layers such as:

- concurrency-focused handler tests
- richer attachment transport integration tests
- streaming progress integration tests
- real provider CLI smoke tests

### Usage accounting and billing (deferred)

The core product does not require billing hooks to be coherent. A commercial
layer can be added later for:

- token and cost accounting
- quota enforcement
- billing integration
- usage reporting

This is intentionally last. The product should feel complete, safe, and
usable before billing is layered on.

---

## Build Priority (Next Work)

Phases A–H are complete. Phases I, IIa, IIb, III, and IV are built in
parallel but share contracts that must freeze first.

### Step zero: shared contract freeze

Before any feature branch starts, agree on and lock:

- `SessionState` additions (`model_profile`, `trust_tier`, any new fields)
- `ResolvedExecutionContext` additions (effective model, trust tier if
  context-visible)
- trust-tier / public-mode semantics (`trusted | public` per-user
  resolution, scope restrictions, what is overridable vs forced)
- effective model / profile semantics (session override > config default,
  trust-tier restrictions on available profiles)
- file-policy precedence rules (trust tier may force inspect; session
  override only within trust-tier ceiling)
- user-visible surfaces: what `/session`, `/help`, and approval messages
  show for new state
- transport delivery semantics: `update_id` idempotency contract, queued
  request acknowledgment rules, what state tracks in-flight vs queued
  requests, where that state lives (durable vs in-memory)

This is not optional. The parallel tracks share execution context, session
state, rendering contract, and transport delivery semantics. If the
contracts drift during parallel development, integration produces the same
bugs that sequential ordering was meant to prevent — just faster.

### Parallel build by ownership

| Track | Phase | Scope |
|-------|-------|-------|
| A: execution context + session schema + transport state | Step zero | `SessionState` additions, `ResolvedExecutionContext` additions, provider context plumbing, context-hash updates, trust-tier parameter, transport delivery state schema (update_id tracking, in-flight/queued request state, durable vs in-memory decision) |
| B: model profiles (state + plumbing) | IIa | profile mapping, session field, provider plumbing, hash/invalidation |
| C: public trust enforcement | I | `is_public_user()` predicate, execution-scope enforcement in context resolution, command gating in handlers, `/doctor` warnings, rate-limit defaults |
| D: model + settings UX | IIb | `/model` command, inline-keyboard UX for all session settings |
| E: compact/latency UX + rendering | III | expandable blockquotes, expand/collapse from raw ring buffer, summary-first rendering, first-progress timing, prompt weight, setup wizard defaults |
| F: transport reliability (behavior) | IV | polling conflict detection, idempotent update handling, busy/queued feedback, deduplication window — uses state schema defined in track A |

### Merge order

Even if built in parallel, merge in dependency order:

1. shared state / context contract (track A)
2. model profiles state + provider plumbing (track B)
3. public trust enforcement (track C) — execution-scope layer then command gating
4. model + settings UX (track D)
5. compact / latency UX (track E)
6. transport reliability (track F)

Note: tracks B and C are independent of each other — both depend on track A.
Model profiles do not wait on public trust. Public trust can later cap
available profiles by constraining the input to model profile resolution.
Track F depends on track A for transport state schema (update_id tracking,
in-flight/queued state) but is independent of tracks B–E.

### Cross-feature invariant tests

Before merging all tracks, add invariant tests for the dangerous
cross-feature combinations:

- public mode + model switching (can a public user escalate to `best`?)
- inspect policy + model profile (does changing model break inspect
  enforcement?)
- compact mode + long replies + public users
- project + file policy + approval + model change

The risk is not "feature A broken alone." It is the cross-feature matrix.

Billing and usage accounting are explicitly deferred. They are not blocking
any of the above.

---

## Completion Standard

The product is commercially ready when:

- the core user journeys are clean and understandable
- execution context is explicit and safe
- the skill system is discoverable and recoverable
- the output is Telegram-native and mobile-friendly
- operators can diagnose and manage the system confidently
- cross-cutting invariants are enforced by tests, not memory
- users can control model speed/capability without knowing provider internals
- public deployments have a concrete trust profile, not optimistic defaults
- long responses use native Telegram primitives for progressive disclosure
- first visible progress arrives within 1 second of request submission
- cross-feature invariant tests cover the dangerous combination matrix
- every inbound update receives a visible response, even under burst traffic
- polling conflicts are detected and warned, not silently tolerated
