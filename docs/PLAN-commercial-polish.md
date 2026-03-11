# Commercial Product Plan

This document describes the product we are building and the shape it must
have to feel finished, trustworthy, and commercially usable. It is not the
build log. Current implementation status lives in
[STATUS-commercial-polish.md](STATUS-commercial-polish.md). Runtime
boundaries and storage/queue authority live in
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
  Archived implementation reference for the detailed roles/skills build.
- `STATUS-agent-roles-and-skills.md`
  Archived shipped-status reference for the detailed roles/skills build.

The detailed historical steps inside the separate roles/skills design doc stay
as they are. This document summarizes that shipped work under Phases 3-5 and
leaves the domain doc as the archived implementation reference.

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

## Roadmap Rules

- The roadmap should be one strict execution order, not priority buckets.
- Phases 1-10 are sealed as shipped history.
- New roadmap work begins at Phase 11.
- `transport idempotency` means the durable `update_id` journal and work-item
  uniqueness.
- `content dedup` means optional suppression of identical consecutive
  messages; it is not part of the core transport contract.
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

## Sealed Historical Build Record

If rebuilding from scratch, build in this order.

The detailed shipped sections below retain the older sublabels (`A`, `IIa`,
`III.5`, and similar) as archived design references. The authoritative roadmap
ordering is the numbered phase map above, with the remaining Phase 11-19
sequence later in this document.

### Sealed Phase 1 (former Phase A) — Core Telegram product loop

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

### Sealed Phase 2 (former Phase B) — Safety and trust controls

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

### Sealed Phase 3 — Roles and instruction-only skills

This shipped work is summarized here and retained in detail in
[PLAN-agent-roles-and-skills.md](PLAN-agent-roles-and-skills.md) and
[STATUS-agent-roles-and-skills.md](STATUS-agent-roles-and-skills.md).

What shipped under Phase 3:

- visible role selection and instruction-only capability layering
- session-visible role/skill activation instead of hidden prompt fragments
- deterministic skill resolution as part of the execution surface

### Sealed Phase 4 (former Phase C) — Skills and credentials

Historical note: in the authoritative numbered roadmap, this section mostly
maps to sealed Phase 4. Phase 3's instruction-only capability foundation is
tracked in the archived roles/skills docs above.

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

### Sealed Phase 6 (former Phase D) — Output quality and mobile usability

Historical note: in the authoritative numbered roadmap, former Phase D and
former Phase III roll up into sealed Phase 6, Output, compact mode, and
progress UX.

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

### Sealed Phase 7 (former Phase E) — Durable runtime and execution context

Historical note: this section maps to sealed Phase 7 in the authoritative
numbered roadmap.

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

### Sealed Phase 5 (former Phase F) — Managed capability distribution

Historical note: in the authoritative numbered roadmap, the shipped scope of
former Phases F and G rolls up into sealed Phase 5, Skill store and capability
distribution.

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

#### Former Phase G — Registry and ecosystem (sealed Phase 5 historical detail)

Goal: allow durable remote capability distribution on top of the managed store.

Includes:

- registry index
- artifact fetch and verification
- digest enforcement before activation
- search and install UX

Acceptance:

- tampered artifacts do not become active state
- registry-backed skills behave like normal managed skills after install

### Sealed Phase 10 (former Phase H) — Hardening and invariants

Historical note: this section is one of the core inputs to sealed Phase 10,
Structural hardening, invariants, and test ownership.

Goal: make regressions expensive and obvious.

Includes:

- invariant test suite
- edge-case test suites
- shared test harnesses
- health/reporting consistency across CLI and Telegram entry points

Acceptance:

- high-risk cross-cutting invariants are tested directly
- major runtime behavior is protected by contract tests, not only scenario tests

### Sealed Phase 8 (former Phase I) — Public trust profile

Historical note: former Phase I plus former Phases IIa and IIb roll up into
sealed Phase 8, Public trust, model profiles, and settings UX.

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

#### Former Phase IIa — Model profiles: state and plumbing (sealed Phase 8 historical detail)

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

#### Former Phase IIb — Inline-keyboard UX for session settings (sealed Phase 8 historical detail)

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

### Former Phase III — Compact defaults and perceived latency (sealed Phase 6 historical detail)

Historical note: this shipped work is sealed inside Phase 6 in the
authoritative numbered roadmap.

Goal: make the bot feel fast and readable on mobile without requiring user
configuration.

Depends on: Phase D (compact mode, `/compact`, `/raw`), Phase E (execution
context, rendering contract).

This phase layers on top of the resolved context and rendering contract. It
does not invent parallel state.

#### Execution sequencing

Phase III covers several distinct workstreams. The recommended build order is:

1. **III.5 Layer 1 + III.5a** — progress normalization + heartbeat.
   Low risk, fully specified, ships independently.
2. **III.1–III.4** — compact defaults, expandable blockquote rendering,
   inline expand/collapse, summary-first response shape. Separate
   workstream from progress — touches rendering and prompt structure.
3. **III.5 Layer 2 + III.5b** — structured progress events, unified
   progress renderer, verbose/debug mode. Build after Layer 1 proves
   out in production.
4. **III.6** — prompt weight reduction. Independent of the above, can
   happen at any point.

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
first update almost immediately. Product rule: immediate visible progress
before provider invocation, with provider-neutral wording.

This should be built in two layers:

**Layer 1: immediate UX normalization**

- send an immediate neutral status message before invoking the provider
  subprocess:
  - `Working...`
  - `Resuming...`
  - `Preparing approval...`
- do not expose provider names in normal user progress:
  - not `Starting claude...`
  - not `Starting codex...`
  - not `codex timed out...`
- do not expose provider-internal ids or terms in normal user progress:
  - thread ids
  - session ids
  - internal compaction terminology
- timeout and terminal states should also use provider-neutral wording:
  - `Request timed out after N seconds.`
  - `Completed.` or equivalent neutral terminal state if the progress message
    remains visible after the final reply is sent
- the progress message and the final reply are separate Telegram messages
  (progress is created at `execute_request():746`, final reply is sent via
  `send_formatted_reply():502`). The progress message must reach a clean
  terminal state — do not leave it stuck on the last heartbeat or thinking
  indicator. For Layer 1, keep a neutral terminal like `Completed.`

**Layer 2: unified progress contract**

The long-term architecture should not rely on each provider owning the final
user-facing HTML vocabulary. Providers may observe different underlying events,
but the product should expose one progress language.

That means:

- providers emit a small normalized progress state or structured progress event
- one shared progress renderer owns:
  - wording
  - formatting
  - liveness heartbeat
  - compact vs verbose progress display
- provider-specific detail can still exist, but only when it is intentionally
  exposed as user-meaningful progress rather than leaking implementation
  internals

The first implementation pass may normalize strings while keeping the current
`ProgressSink` boundary, but the target contract is a shared progress model,
not endless provider-specific HTML tweaks.

Design guardrails before implementation:

- Codex is the current reference UX for long-running interactivity. Layer 2
  should treat Codex as the no-regression baseline and Claude as the provider
  that primarily needs to catch up. The target is not to average both
  providers down to a thinner common denominator
- the normalized event model must be rich enough to preserve the current
  Codex UX. A schema like `ToolStart(name)` / `ToolFinish(name)` is too lossy
  if it cannot represent:
  - command text
  - exit code
  - tool output preview
  - denial / rejected-action states
  If Layer 2 introduces typed events, the contract should distinguish command
  execution from generic tool lifecycle rather than flattening both into the
  same shape
- Codex no-regression must be explicit. Before refactoring provider progress,
  capture and preserve at least these user-visible properties on long-running
  Codex requests:
  - time to first visible progress is not worse
  - command start / finish visibility is not lost
  - output preview, denial, and draft-reply richness are not lost
  - rate limiting and shared rendering do not coalesce meaningful Codex
    semantic events into silence
  Improvement is welcome, but a quieter or less informative Codex UX is a
  regression
- the shared renderer must NOT become the source of truth for the final model
  reply. Provider run logic still owns final reply assembly; the renderer owns
  only the user-visible progress/status message
- completion and liveness ownership must be explicit:
  - handler-owned heartbeat remains the default owner of idle liveness
  - provider-specific liveness (for example long resume/compaction states)
    must be typed and must not fight the heartbeat loop for the same surface
  - if ownership changes, the plan must say who is allowed to overwrite the
    progress message in idle, draft, timeout, and terminal states
- invisible provider activity must not suppress user-visible liveness. Signals
  such as Claude `input_json_delta` may be useful as activity hints, but they
  must not count as `content_started` and must not leave the user with a
  frozen status message and no heartbeat
- Layer 2 must preserve provider parity across all equivalent entry points,
  not just normal `run()`:
  - standard execution
  - approval preflight (`run_preflight()`)
  - resume flows
  - timeout and interruption paths
  - provider error paths
- test scope for Layer 2 must go beyond renderer unit tests:
  - focused contract tests for the normalized event model
  - real entry-point tests through the Telegram status message object chain
    used by `reply_text()` / `edit_text()`
  - adjacent regression tests for false positives, especially heartbeat
    suppression, internal-detail leakage, and Codex detail loss
  Output-equivalence tests alone are not enough: if Layer 2 improves Claude
  interactivity, some user-visible output should change by design

Current diagnosis (why Codex feels more interactive today):

- the shared Telegram progress layer is already common across providers:
  `TelegramProgress`, `_heartbeat()`, and the initial `Working...` /
  `Resuming...` status message are shared
- the main difference is provider-side event richness, not the Telegram
  framework:
  - Codex currently emits and renders many intermediate states: thinking,
    command start, command finish with output, tool calls, draft/commentary
    assistant text, and final answer
  - Claude currently renders far less: in the current implementation, visible
    updates come primarily from `tool_use` starts and `text_delta` content
- practical result:
  - Codex feels active before the final answer because it can show meaningful
    intermediate work
  - Claude is mostly silent until a tool starts or the first reply text delta
    arrives, so the user mostly sees only the generic heartbeat
- rate limiting amplifies the gap: Claude emits many small text deltas that
  the progress sink naturally coalesces, while Codex emits chunkier semantic
  events that survive the rate limiter better
- Codex also has an extra provider-specific liveness message on long
  resume/compaction paths; Claude has no comparable special-case progress path
- open question: capture at least one real long-running Claude `stream-json`
  trace from the shipped CLI version and prove which ignored events are
  actually present. The plan should not assume a richer Claude event stream
  without typed evidence
- practical migration stance:
  - keep today's Codex experience unless there is typed evidence that a change
    is neutral or better
  - use the shared progress contract primarily to let Claude surface more of
    its real intermediate work
  - avoid refactors whose main effect is making Codex and Claude equally quiet

Revised Layer 2 architecture:

1. `ProgressEvent` family in `app/progress.py`
   The normalized contract should preserve current Codex detail rather than
   flattening it away. A richer event family is acceptable if needed. At
   minimum, distinguish:
   - `Thinking`
   - `CommandStart(command)`
   - `CommandFinish(command, exit_code?, output_preview?)`
   - `ToolStart(name, detail?)`
   - `ToolFinish(name, output_preview?)`
   - `DraftReply(text)`
   - `ContentDelta(text)` — visible reply text, sets `content_started`
   - `Denial(detail)` — blocked/denied action
   - `Liveness(detail)` — visible provider-owned liveness only when the
     handler heartbeat is not the right owner
   Non-visible provider activity such as Claude `input_json_delta` should stay
   adapter-local as an activity hint. It must not be rendered and must not set
   `content_started`.

2. `ProgressRenderer` in `app/progress.py`
   - owns shared user-facing wording and formatting for the progress/status
     message
   - takes `ProgressEvent` plus renderer state and returns HTML (or `None`)
   - may own accumulated preview state for the status message only
   - must NOT become the source of truth for the final model reply; provider
     run logic still owns final reply assembly

3. Provider adapters
   - each provider gets a `_map_event()` layer from raw CLI events to
     `ProgressEvent | None`
   - Claude adapter should expand coverage to real structured events that are
     present in captured traces: thinking blocks, tool starts, tool-result /
     denial signals, and reply deltas
   - Codex adapter should map its current event set into the normalized family
     without losing command text, exit codes, output previews, or draft-reply
     semantics

Suggested implementation sequence:

1. Capture and check in representative raw-event fixtures for both providers,
   especially one real Claude long-running `stream-json` trace and at least
   one representative long-running Codex trace
2. Capture the current Codex visible-message sequence as a regression fixture:
   initial status, meaningful intermediate updates, and terminal state. Layer 2
   should not proceed until the project can prove the current Codex experience
   is preserved or improved
3. Define `ProgressEvent` and `ProgressRenderer` with focused contract tests in
   `app/progress.py`
4. Add explicit Codex no-regression tests around time-to-first-visible-progress,
   command start / finish rendering, output-preview richness, and
   heartbeat/rate-limit interaction
5. Migrate Codex first behind `_map_event()` and prove parity with today's
   visible detail and liveness behavior
6. Migrate Claude next and add the newly surfaced thinking / tool-result /
   draft progress coverage
7. Wire both `run()` and `run_preflight()` through the same renderer while
   keeping the existing handler heartbeat as the default idle-liveness owner
8. Only then add provider-owned liveness for gaps the generic heartbeat cannot
   explain, with explicit tests proving no duplicate heartbeat, no invisible
   heartbeat suppression, and no final-reply regressions

#### III.5a Liveness heartbeat for idle states

Weak liveness is a separate problem from first visible progress.

If the model is reasoning internally and has not yet emitted visible text, the
status should not appear frozen. Add a heartbeat for idle non-content states:

- `Working...`
- `Still working... 10s`
- `Still working... 25s`

Rules:

- heartbeat should fire when there has been no visible progress change for a
  short interval
- heartbeat applies only while the bot is in a known non-content phase, not
  by inspecting or classifying arbitrary HTML from the provider
- the heartbeat decision is driven by an explicit state flag, not by string
  comparison against `progress.last_text`:
  - the code that sends initial status (Working..., Resuming..., etc.) sets
    `content_started = False`
  - the provider streaming path sets `content_started = True` the first time
    real reply text arrives (claude.py: first text_delta, codex.py: first
    final_text assignment)
  - the heartbeat loop checks the flag; once True, it stops firing
  - this avoids any coupling to the exact wording of status messages and
    naturally extends into Layer 2's structured progress model
- once actual reply text is streaming, heartbeat must stop rather than
  appending elapsed time onto the draft content
- cadence should taper: first heartbeat at ~5s, then every ~10-15s — alive
  without being noisy
- typing indicators remain useful ambient presence, but heartbeat is the
  explicit visible liveness signal

Implementation shape:

- heartbeat is a sibling background task (same pattern as `keep_typing()`),
  not a wrapper class around `ProgressSink`
- the flag is a simple `asyncio.Event` shared between the heartbeat task and
  the provider call site — when set, heartbeat stops
- heartbeat calls `progress.update(..., force=True)` — same interface, no new
  protocol
- lifecycle: `asyncio.create_task()` at request start, `.cancel()` in finally
  block alongside `typing_task.cancel()`

#### III.5b Provider detail policy

Not all intermediate provider events should be shown to normal end users.

Default product behavior:

- show user-meaningful phases:
  - working
  - thinking
  - using tools
  - drafting reply
  - finishing
- hide provider-specific implementation details:
  - provider names
  - thread/session ids
  - raw provider resume mechanics

Tool and command detail should be treated as a product decision, not an
accidental provider leak. If detailed tool activity is shown, it should still
use the shared progress vocabulary and formatting shape.

#### III.6 Prompt weight reduction

Smaller effective prompts reduce time-to-first-token:

- shorter default role text
- fewer always-on skills (only load what the session actually uses)
- avoid injecting capability text for inactive skills
- measure prompt size (character estimate) in both `/session` and `/doctor`

This is less visible than model switching but contributes to perceived speed.

Acceptance:

- new users discover compact mode without reading docs
- the default feels right for the deployment context
- long responses use expandable blockquotes or inline expand/collapse
- first visible progress is sent before provider invocation
- idle waiting states show visible liveness rather than freezing indefinitely
- normal user progress does not expose provider names or thread/session ids
- prompt weight is observable in `/session` and `/doctor`

#### III.7 Follow-on Hardening: targeted workflow-state-machine extraction

This is the next architectural hardening item after the progress/liveness work
is stable. It is not a product feature. It is an internal reliability and
maintainability investment.

Important framing:

- this is not a recommendation to rewrite the whole bot around a generic state
  machine library
- this is not justified by direct user-visible feature payoff
- this is only worth doing if restart/recovery/approval/orchestration bugs keep
  consuming review time and operator trust

##### Problem statement

Several parts of the bot are already acting like state machines, but they are
currently expressed implicitly across handlers, queue helpers, worker code,
and session mutations:

- work-item lifecycle:
  - `queued`
  - `claimed`
  - `pending_recovery`
  - terminal outcomes like `done` and `failed`
- pending request lifecycle:
  - no pending request
  - pending approval
  - pending retry
  - cleared / invalidated / executed
- restart recovery lifecycle:
  - interrupted
  - captured durably
  - awaiting user choice
  - replayed / discarded / superseded / failed

The current pain is not that the states are unknown. The pain is that:

- transition rules are spread across multiple modules
- completion ownership is easy to get wrong
- second-order failure paths are easy to miss:
  - recovery interrupted again
  - recovery notice delivery failure
  - replay blocked by another claimed item
  - stale callback or duplicate click
- handler code still mixes ingress adaptation, UX, and durable transition logic

That is why fixes can look locally correct but still leave contract bugs at the
durable boundary.

##### Decision

If this work is taken on, the approach should be narrow and contract-first:

- extract only the workflows that are already behaving like explicit durable
  state machines
- keep SQLite durable state as the authority
- keep Telegram/provider code as ingress/egress adapters
- prefer plain, explicit transition code first:
  - typed state enums or equivalent
  - transition functions
  - guarded transactional writes
  - explicit owner per terminal outcome
- evaluate a state machine library only if it clearly reduces code and review
  risk after the workflow boundaries are already explicit

Do not do this:

- do not rewrite the entire bot around a state machine framework
- do not try to model every Telegram command and callback as one giant machine
- do not move correctness into in-memory library objects while durable state is
  still the real authority
- do not pay a major migration cost just for prettier diagrams or vocabulary

##### Why not a library-first rewrite

A battle-tested state machine library may help with modeling, but it does not
solve the hardest part of this bot by itself:

- durable transactional ownership
- crash/restart replayability
- multiple ingress paths touching the same durable state
- external provider side effects and interruption

Most libraries are strongest for in-memory transition modeling. This bot's
hardest bugs live at the boundary between SQLite, async handlers, worker
recovery, and provider execution. A library cannot replace careful ownership and
transaction design there.

So the recommended order is:

1. Make the workflows explicit in plain code.
2. Consolidate transitions behind one owner module per workflow.
3. Reassess whether a library would actually simplify the result.

##### Initial scope

Candidate workflows for extraction:

- work-item / recovery orchestration
  - claim
  - complete
  - leave claimed
  - move to pending recovery
  - reclaim for replay
  - supersede / discard / fail
- pending approval / retry orchestration
  - create pending
  - validate context
  - approve / reject / retry / clear
  - invalidate on real context change

Out of scope for the first pass:

- provider progress streaming
- compact/raw/export rendering
- help/settings/menu UX flows
- all session fields and command routing
- a single global machine for the whole application

##### Target architecture

Each extracted workflow should have:

- one authoritative transition module
- one small typed state model
- one place where allowed transitions are defined
- explicit guards for adjacent failure cases
- explicit completion ownership
- explicit durable commit points

Handler code should become thinner:

- normalize ingress
- authorize
- call workflow transition/orchestration function
- render the returned user-visible outcome

The workflow module should own:

- state validation
- transition legality
- durable writes
- terminal disposition
- returned outcome codes that explain what happened

##### Expected benefits

If done well, this should improve:

- reviewability:
  - fewer "was this exit path finalized?" questions
- reliability:
  - fewer owner-boundary bugs in restart/recovery and approval flows
- maintainability:
  - less logic spread across `telegram_handlers.py`, `worker.py`, and queue
    helpers
- testing clarity:
  - contract tests can target explicit transitions instead of reverse-engineered
    behavior

This is mainly a defect-rate reduction and change-safety investment, not a
speed or feature investment.

##### Costs and caveats

This work is expensive and should be treated as such:

- large refactor surface
- low direct product payoff
- high migration risk if done broadly
- can easily become architecture theater if the scope is not kept narrow

It is only justified if the current pattern continues:

- repeated durable-state bugs in the same workflows
- growing review effort to verify owner/finalization semantics
- more tests without proportional increase in confidence

If those costs are not currently dominating, defer this work.

##### Implementation sequence

If taken on, the recommended order is:

1. Write the current state tables explicitly for:
   - work items / recovery
   - pending approval / retry
2. Name every transition owner and terminal owner.
3. Extract transactional transition helpers behind one module per workflow.
4. Update handlers/worker to call those helpers instead of open-coding
   transitions.
5. Add contract tests at the workflow boundary.
6. Add one real entry-point integration test per dangerous ingress path.
7. Only then decide whether a library would meaningfully reduce complexity.

##### Tests required before calling this complete

Focused contract tests:

- allowed and forbidden transitions for each extracted workflow
- terminal ownership on every exit path
- second interruption / second recovery behavior
- duplicate click / duplicate delivery idempotency
- false-positive boundaries for invalidation and replay rejection

Entry-point integration tests:

- message ingress
- command ingress where the same workflow applies
- callback ingress where the same workflow applies
- worker recovery path

Adjacent regression tests:

- a safe fresh request is not blocked by stale durable state
- a blocked replay stays actionable later
- unrelated read-only or settings actions do not accidentally finalize pending
  recovery unless the contract explicitly says they should

##### Go / no-go rule

Do this only as a targeted workflow extraction. If the proposal starts to look
like "rewrite the bot around a state machine library," stop and rescope.

### Sealed Phase 9 (former Phase IV) — Update delivery and burst safety

Historical note: this shipped work is sealed inside Phase 9, Durable
transport, transport idempotency, webhook mode, and restart recovery.

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

#### IV.2 Transport idempotency

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

#### IV.4 Content deduplication (optional/tunable)

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

## Remaining Phases

These phases are the active roadmap. Every still-relevant deferred or future
item belongs somewhere in this ordered sequence.

### Phase 11 — Workflow Ownership Extraction

Behavior-preserving refactor only.

- Extract two authoritative workflow owners first: transport/recovery and
  approval/retry.
- Reuse existing normalized inbound payloads, typed session dataclasses, and
  resolved execution context.
- Introduce store interfaces around the current persistence seams so handlers
  and workers stop open-coding durable transitions.

Detailed historical design record:

- former `III.7 — Follow-on Hardening: targeted workflow-state-machine
  extraction`
- archived 2026 execution record below

### Phase 12 — Postgres Runtime Cutover

Make Postgres the only supported runtime backend after migration.

- add `BOT_DATABASE_URL` and pool settings
- use `psycopg` v3 async pooling
- avoid an ORM
- keep schema management repo-owned with versioned SQL plus a small migration
  runner
- provide one-way import from SQLite session and transport data into Postgres
- preserve current payload JSON shapes and current dataclass contracts

### Phase 13 — Postgres Queue Authority in Webhook Mode

Keep the core Telegram request path as an app-owned Postgres queue, not a
generic task broker.

- retain explicit `updates` and `work_items` tables
- retain row-lock claiming, leases, recovery metadata, and replay/discard
  ownership
- in webhook mode, ingress should normalize, persist, and acknowledge quickly
- workers become the primary execution path

Detailed historical design record:

- archived future-design record below, especially the multi-worker webhook
  architecture section

### Phase 14 — Multi-Process / Multi-Worker Deployment

Add true cross-process ingress and worker concurrency on top of the Postgres
queue.

- preserve per-chat single-flight ordering, `transport idempotency`, recovery
  safety, and explicit terminal ownership across processes
- polling stays single-owner and dev-oriented
- scale path is webhook plus Postgres plus workers
- add queue depth, lease, worker-health, and recovery metrics

### Phase 15 — Durability Confidence Phase

Add the confidence work that becomes important only after the infrastructure
shift.

- cross-process queue tests
- crash/lease-recovery tests
- webhook ingress durability tests
- real provider smoke coverage for the new worker model

This is a distinct phase, not hidden inside earlier acceptance criteria.

### Phase 16 — Product Polish on Stable Foundations

Add the small UI work that is only worth doing after queue and worker
semantics stabilize.

- add `/project` inline keyboard by reusing the existing settings-inline-
  keyboard pattern and callback handling
- add optional verbose progress mode only after queue and worker semantics are
  stable

### Phase 17 — Behavior Extensions

Add demand-gated behavior extensions after the runtime is stable.

- add demand-gated `content dedup` using a durable content fingerprint and
  explicit user acknowledgment instead of silent drop
- expand project and policy scope using the existing project binding and
  resolved execution-context model rather than inventing a second scoping
  system

### Phase 18 — Registry Trust and Governance

Extend the managed store with publisher signing and organizational trust
policy on top of the existing digest-verification model.

- reuse the current object/ref store architecture
- reuse the current registry metadata flow

### Phase 19 — Usage Accounting, Quotas, and Billing

Build this last.

- meter usage from authoritative execution completion points, not from
  provider-progress heuristics
- add usage recording first
- add quota enforcement second
- add billing integration and reporting third
- if secondary background jobs are needed here, use a Postgres-native task
  library only for those non-core jobs

---

## Architecture Decisions

- Postgres is the sole runtime backend after migration. SQLite is import-
  source only during cutover.
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

- The roadmap should be optimized for a Postgres-first deployment model, not
  for dual backend support.
- The master roadmap should present a strict execution order, not priority
  buckets.
- Confidence work remains in the roadmap even though it is not user-facing,
  because the infrastructure phases materially change failure modes.
- Payments and billing stay last because they depend on stable transport,
  worker ownership, and trustworthy execution accounting.
- Queue/library evaluation basis:
  [Celery broker docs](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html),
  [Temporal workflows](https://docs.temporal.io/workflows),
  [PGMQ](https://pgmq.github.io/pgmq/),
  [Procrastinate](https://procrastinate.readthedocs.io/).

---

## Archived Future-Design Record

These are legitimate product areas that extend beyond the core build phases.
They are retained because they capture decision history, design constraints,
and previous planning assumptions, but they are no longer the authoritative
remaining-work structure. The authoritative roadmap is the Phase 11-19
sequence above.

### Multi-worker webhook architecture

Historical mapping: this section primarily informs active Phases 13-15 in the
linear roadmap above.

> **Status:** The single-worker durable foundation described below has
> shipped (transport.db, work_queue.py, worker.py, pending_recovery). What
> remains is the multi-process deployment step: multiple workers claiming
> from the same durable queue across process boundaries.

Webhook mode already exists in the product. The next structural extension is
not "run more pollers." It is multi-worker / multi-process webhook deployment
on top of the existing durable ingress and work-item architecture.

The product goal is:

- no inbound Telegram update is lost because a process dies
- duplicate delivery is safe across restarts and workers
- per-chat ordering survives process boundaries
- queued/busy behavior is durable, not only in-memory
- the same foundation can later support gateway-style agent routing

Polling remains single-owner by design. Multi-process support means webhook +
shared durable state, not multi-poller polling.

#### Durable ingress contract

The transport architecture should evolve toward these contracts:

- one ingress owner per bot token
- inbound Telegram updates are durably recorded before business logic runs
- `update_id` idempotency is enforced in durable state, not only in memory
- chat-scoped execution ownership is enforced in durable state, not only by
  `CHAT_LOCKS`
- a worker may crash without silently losing the update it was handling
- the system may run with one worker first, but the contracts must not assume
  one process forever

#### Target architecture

The intended shape is:

1. Webhook ingress accepts the Telegram update and normalizes it.
2. The normalized update is inserted into a durable `updates` store keyed by
   `update_id`.
3. The transport layer creates or enqueues a chat-scoped `work_item`.
4. A worker claims the next runnable work item for a chat that is not already
   in flight.
5. The worker loads session state, resolves execution context, runs the
   request, and commits the resulting state transitions.
6. Completion, retryability, and failure are written back durably so recovery
   after crash/restart is explicit.

This is deliberately the same architecture needed for a future multi-agent
gateway bot, just without agent routing yet.

#### Historical SQLite-first implementation strategy (superseded)

This section records the earlier SQLite-first reasoning for the durable queue
extension. It is retained as decision history, but the active roadmap has
changed: after migration, Postgres is the runtime authority and SQLite is
import-source only during cutover.

Earlier SQLite-first rationale:

- durable update journal
- durable in-flight / queued request state
- chat work-item claiming
- ingress idempotency (`update_id`)
- restart-safe acknowledgment and recovery

This is preserved because it explains how the current shipped queue semantics
were originally staged, even though the remaining roadmap is now Postgres-
first rather than dual-backend.

#### Data model

The extension should introduce explicit durable transport state, separate from
the existing session table. The exact names may vary, but the architecture
needs equivalents of:

- `updates`
  - `update_id`
  - `chat_id`
  - `user_id`
  - `kind`
  - normalized payload
  - received timestamp
  - processing state
- `work_items`
  - stable work-item id
  - `chat_id`
  - origin update reference
  - queued / claimed / done / failed state
  - claimant / lease metadata
  - timestamps
- optional `chat_leases` or an equivalent claim model if the lease is not kept
  directly on `work_items`

The bot does not need a separate distributed queue system for this stage. The
important step is to move delivery ownership and in-flight state into durable
storage.

#### Worker model

Start with one worker even after the durable transport model lands.

That first step already buys:

- crash recovery
- durable burst handling
- webhook robustness
- explicit queue/in-flight state
- removal of the weakest in-memory delivery guarantees

Only after that foundation is stable should the product add multiple workers.

When multiple workers are introduced, the contract is:

- workers claim runnable work items atomically
- no long-lived database transaction is held while the provider is running
- provider execution happens outside the claim transaction
- completion is committed in a separate write
- expired claims can be recovered safely

#### Build sequence

If this extension is taken on, the recommended order is:

1. Add durable `update_id` tracking in SQLite.
2. Add durable queued / in-flight work-item state.
3. Make webhook ingress write durable update records before handler execution.
4. Route the current single-process bot through the durable work-item path.
5. Replace in-memory-only burst handling with durable queue state.
6. Add worker claiming semantics while still running a single worker.
7. Only then consider multi-worker webhook deployment.

This sequencing matters. It avoids repeating the earlier mistake of building
important behavior on top of a weaker state model and retrofitting the
foundation later.

#### Follow-on: safe restart recovery with preserved provider context

> **Status:** Shipped. The `pending_recovery` work-item state, user-intent-
> owned replay/discard, fresh-message supersession, and `ReclaimBlocked`
> exception are all implemented and tested. The spec below is preserved as
> the authoritative design reference.

This is linked to provider-state / resume hardening, but it is not the same
contract:

- state hardening decides when a provider session is valid to resume
- replay hardening decides who is allowed to re-issue an interrupted request

The product should keep the good behavior:

- provider conversation context may survive bot restart
- a fresh post-restart user message may continue on the resumed provider session
  when that session is still valid

The unsafe behavior is different:

- worker recovery must not blindly replay an interrupted user message through a
  resumed provider session
- conversationally-dependent confirmations such as `Yes do that` are not
  replay-safe, because their meaning comes from prior context and may re-trigger
  side effects like restarting the current bot instance
- partial side effects before interruption make automatic replay unsafe even
  when the provider session itself is healthy

##### Target contract

- session continuity and request replay are separate concepts
- preserving provider session context across restart is allowed
- automatic recovery must never blindly re-execute an interrupted request whose
  meaning depends on prior conversation context or partial side effects
- worker recovery owns durable capture of the interrupted request, not final
  replay
- user intent owns replay: a recovered request resumes only after explicit user
  choice
- fresh post-restart messages remain allowed; they must not be blocked forever
  by an older interrupted request

##### Durable state shape

The exact names may vary, but the runtime needs an explicit durable
`pending_recovery` concept rather than overloading `queued`, `claimed`, `done`,
or `failed`.

Required fields / equivalents:

- origin `update_id`
- request kind and normalized payload
- `request_user_id`
- original / interrupted boot id
- attempt count
- created / updated timestamps
- terminal disposition:
  - replayed
  - discarded
  - superseded by a newer request

The work-item state machine should have an explicit non-terminal outcome for
"interrupted, captured, awaiting user choice" instead of pretending the item is
either still runnable automatically or already complete.

##### Ownership and flow

Recommended flow:

1. A live request is interrupted by restart and its work item is recovered.
2. On next boot, the worker records durable pending-recovery state instead of
   auto-dispatching the original message back into provider execution.
3. The bot sends a recovery notice with explicit choices:
   - replay interrupted request
   - discard interrupted request
4. If the user chooses replay, the bot replays the original payload through the
   current session state, which may still use resumed provider context if that
   provider session remains valid.
5. If the user discards recovery, the durable pending-recovery state is cleared
   and the original interrupted request is finalized as discarded.
6. If the user sends a fresh message instead, that fresh request is allowed to
   proceed and the old pending recovery is finalized as superseded, not silently
   replayed later.

Explicit completion ownership:

- worker owns transition from interrupted claim to durable pending recovery
- user action (replay / discard / fresh-message supersession) owns finalization
- a second interruption during explicit replay must return to pending-recovery
  state with incremented attempt count; it must not re-enter an automatic boot
  loop

##### Design constraints

- do not rely on prompt-text heuristics like matching `restart`, `yes`, or
  similar phrases; the safety decision should come from the replay contract, not
  string guesses
- do not solve this by clearing provider session state on every restart; that
  would throw away a useful product feature
- do not let replay safety depend on in-memory locks alone; pending-recovery
  ownership must survive restart
- keep user-visible recovery wording explicit about what is being resumed:
  session context may survive, but the interrupted request itself needs user
  confirmation before replay

##### Tests required before shipping

Focused contract tests:

- interrupted request becomes durable pending recovery, not automatic replay
- explicit replay reuses current session state and original payload
- fresh post-restart message supersedes old pending recovery without discarding
  resumed session continuity
- second interrupted replay returns to pending recovery, not a replay loop

Entry-point integration tests:

- reproduce a contextual confirmation case like `Yes do that` after a bot
  restart and prove it is not auto-replayed
- prove a safe fresh post-restart message still resumes provider context and
  completes normally
- prove discard clears pending recovery and does not resurrect later

Adjacent regression tests:

- no false-positive recovery prompt for ordinary resumed requests with no
  pending recovery
- duplicate delivery / repeated callback on replay or discard remains idempotent
- timeout / resume-failed state hardening still works alongside pending recovery

#### Not in scope for this extension

- supporting multiple pollers on the same Telegram token
- distributed multi-host coordination from day one
- a full outbox/reliable-send subsystem before the durable ingress layer exists

The purpose of this extension is to make transport and request ownership
durable first. Multi-worker scale is a later deployment mode enabled by that
foundation.

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

## Archived 2026 Execution Record

All build phases (A–IV), public trust (I), model profiles (IIa/b), compact/
latency (III), transport reliability (IV), and the multi-worker webhook
extension (Ext) have shipped. See [STATUS-commercial-polish.md](STATUS-commercial-polish.md)
for the full build log. 780 pytest + 36 bash tests.

This section is retained because it records the decision history, bug context,
and near-term execution plan that produced the current shipped runtime. It is
not the authoritative remaining-work structure anymore; use the Phase 11-19
roadmap above for current planning.

### Priority 1: Test-suite ownership refactor

The test tree has accumulated overflow files, duplicated assertions across
suites, and owner drift. This refactor is the highest-leverage next step
because it makes every subsequent test addition land in the right place and
prevents further duplication. See the detailed refactor sequence below.

Important framing:

- owner-map extraction is groundwork, not completion
- a patch that only moves tests between files without deleting weak
  duplicates, strengthening owner-boundary coverage, or improving suite
  signal does not satisfy Priority 1
- the payoff for this track must be observable in at least one of:
  less duplicate noise, stronger owner-boundary assertions, or reduced
  suite maintenance burden

The contract is not "reduce test count." The contract is:

- each runtime contract has one clear owning test suite
- helper tests do not duplicate real-boundary coverage
- `test_invariants.py` only keeps truly cross-cutting invariants
- review-history or edge-taxonomy files do not become second owners

Use the current tree as authority before moving anything. In particular,
recovery/work-item behavior already has a healthy primitive-vs-boundary split:

- `tests/test_work_queue.py` owns durable queue/work-item primitives
- `tests/test_workitem_integration.py` owns worker/Telegram recovery boundaries

Refactor sequence:

1. Rebaseline current coverage against HEAD and write a short owner map.
   - identify stale review notes, duplicated assertions, and ownerless tests
   - do not move tests based on outdated bug reports or historical suite shape
2. Stabilize the recovery/work-item slice first.
   - keep durable primitive checks in `tests/test_work_queue.py`
   - keep real recovery/worker/callback boundaries in `tests/test_workitem_integration.py`
   - move duplicate recovery assertions out of `tests/test_invariants.py`
3. Dismantle the overflow files.
   - move any unique test from `tests/test_high_risk.py` to its owner suite, then delete the file
   - fold `tests/test_edge_callbacks.py`, `tests/test_edge_sessions.py`, and `tests/test_edge_providers.py` into owner suites, then delete them
4. Parameterize helper-heavy suites.
   - turn `tests/test_transport.py` into a normalization matrix plus the real handler-boundary tests
   - turn `tests/test_formatting.py` into table-driven groups for `trim_text`, markdown conversion, and `split_html`
   - fold any surviving formatting stress cases from `tests/test_edge_formatting.py` into those groups
5. Shrink `tests/test_invariants.py` to true cross-cutting ownership only.
   - keep resolved-context parity, public/trust enforcement, context-hash invalidation, and cross-ingress idempotency
   - move provider progress, recovery, export, and other owner-specific checks back to their domain suites
6. Add a short testing-ownership note documenting which suite owns which contract.

Completion bar:

- no contract is asserted in both an owner suite and `tests/test_invariants.py` without a clear boundary reason
- `tests/test_high_risk.py` and the non-essential `tests/test_edge_*.py` overflow files are removed
- moved tests are stronger than before or are deleted as redundant
- owner-map-only reshuffling does not count as completion
- at least one duplicate or weak test cluster is actually deleted, not
  merely relocated
- owner suites pass after each step; full suite passes at the end

### Priority 2: Fresh command ownership race (production bug, High)

**Bug report:** `dont_make_false_claims.md`

Fresh live commands are left in `state='queued'` by `_dedup_update()` while the
inline handler is still executing.  The background worker's `claim_next_any()`
steals them, then `worker_dispatch()` unconditionally sends false "interrupted
by a restart" recovery notices.  Confirmed 3× on two commands (`/compact`,
`/doctor`) with a 100% hit rate on lock-free command paths.  Regular messages
are immune because `_chat_lock` claims ownership before handler body execution.

**Root cause:** `record_and_enqueue()` creates items as `'queued'`.  Lock-free
commands never enter `_chat_lock`, so the item sits claimable for the entire
handler duration.

**Fix (6 items, execute in order):**

1. `work_queue.record_and_enqueue()` — add `worker_id` parameter, create items
   as `state='claimed'` with `worker_id` and `claimed_at` set.  The inline
   handler owns the item from birth.
2. `work_queue.enqueue_work_item()` — same change for test helper parity.
3. `work_queue.claim_for_update()` — recognize items already claimed by the
   same `worker_id` (the inline handler's `_boot_id`) and return them directly
   instead of returning None.
4. `_dedup_update()` — pass `_boot_id` as `worker_id` to `record_and_enqueue()`.
5. `_chat_lock` — when the item is already in `_pending_work_items` (pre-claimed
   by the decorator), skip re-claiming via `claim_for_update()`.
6. `complete_work_item()` — add state guard (`WHERE state IN ('queued','claimed')`)
   to prevent overwriting terminal states.

**Acceptance criteria:**

- Fresh `/compact`, `/doctor`, and at least one other lock-free command never
  produce recovery messaging.
- `claim_next_any()` cannot steal items created by the inline handler.
- Handler crash → item stays claimed → stale recovery picks it up.
- No duplicate processing — item processed exactly once.
- All existing tests pass.

### Priority 3: Test coverage gaps (low effort, high confidence value)

These are places where the implementation exists but the contract is not
proven by tests. Best done after or alongside Priority 2 so that each new
test lands in the correct owning suite from the start.

**a. Provider liveness vs heartbeat interaction test.** The handler heartbeat
and the provider `Liveness` event both update the same progress message. No
test proves they don't fight. Add a test that simulates a Codex long-running
resume (which emits `Liveness`) while the handler heartbeat is active, and
assert only one visible update per interval.

**b. Rate-limit + semantic event preservation test.** The progress sink
rate-limits updates. No test proves rate limiting doesn't suppress meaningful
Codex semantic events (command start/finish, tool events). Add an integration
test combining a real rate limiter with Codex command events and prove command
start/finish survive rate limiting.

**c. Raw event regression fixtures.** The plan called for checked-in raw
provider event traces (Codex NDJSON, Claude stream-json) as regression
fixtures. The current tests use synthetic events constructed in-memory, which
is adequate for contract tests but does not prove the mapping layer handles
real CLI output faithfully. Capture at least one representative trace per
provider from a real long-running request and add fixture-based regression
tests. (Higher effort than 2a/2b — requires real provider traces.)

### Priority 4: Test isolation and safe parallelization

**Objective:** Make handler-heavy tests independent of leaked module-global
state in `app.telegram_handlers`, then prove at least one slice runs safely
under parallel execution.

**Contract:**

- Handler tests must not depend on ambient global state leaking between cases.
- Per-test setup/reset must be explicit and complete.
- Any "parallel-safe" claim must be backed by isolated test runs, not file shuffling.

**Current leak surface:**

- Runtime globals in `app/telegram_handlers`: `CHAT_LOCKS`, `_current_update_id`,
  `_config`, `_provider`, `_boot_id`, `_rate_limiter`, `_pending_work_items`,
  `_bot_instance`.
- Session DB cache in `app/storage`: `_db_connections`.
- Transport DB cache in `app/work_queue`: `_db_connections`.
- Test helper state in `tests/support/handler_support`: `_next_update_id`.
- Direct global mutation exists in tests (especially `_bot_instance` in
  `test_workitem_integration.py`, `test_invariants.py`). `setup_globals()` only
  resets part of the surface. Include `app/skill_commands.py` in the audit
  (uses `th.CHAT_LOCKS` directly).

**Phase 1 — Audit matrix**

| State surface | Defining file | Who mutates | Who reads | Reset owner | Blocks xdist |
|---------------|---------------|-------------|-----------|-------------|--------------|
| `CHAT_LOCKS` | telegram_handlers | handler_support (clear in reset), skill_commands (acquire) | test_invariants (lock ref), isolation test | reset_handler_test_runtime | Yes |
| `_current_update_id` | telegram_handlers | handlers (_chat_lock) | _dedup_update | reset (set None in context) | Yes |
| `_config` | telegram_handlers | handler_support (setup_globals, reset) | handlers, tests via _cfg() | reset_handler_test_runtime | Yes |
| `_provider` | telegram_handlers | handler_support | handlers, tests | reset_handler_test_runtime | Yes |
| `_boot_id` | telegram_handlers | handler_support | handlers, codex thread invalidation | reset_handler_test_runtime | Yes |
| `_rate_limiter` | telegram_handlers | handler_support | handle_message | reset_handler_test_runtime | Yes |
| `_pending_work_items` | telegram_handlers | handlers, handler_support (clear) | handlers | reset_handler_test_runtime | Yes |
| `_bot_instance` | telegram_handlers | handler_support (setup_globals, set_bot_instance, reset) | worker_dispatch, send paths | reset_handler_test_runtime | Yes |
| `_db_connections` (session) | storage | storage._db, close_db, close_all_db | storage._db | close_all_db in reset | Yes |
| `_db_connections` (transport) | work_queue | _transport_db, close_transport_db, close_all_transport_db | work_queue functions | close_all_transport_db in reset | Yes |
| `_next_update_id` | handler_support | FakeUpdate ctor, reset | FakeUpdate | reset_handler_test_runtime | Yes |

Inventory: direct writes to handler globals are only in `tests/support/handler_support.py` (reset_handler_test_runtime, setup_globals, set_bot_instance). Tests use `setup_globals(` / `fresh_env(` ~296 times; no test file other than support mutates `_config`, `_provider`, `_boot_id`, `_rate_limiter`, or `_bot_instance`. `app/skill_commands.py` reads `th.CHAT_LOCKS[chat_id]` (no mutation).

**Phase 2 — One authoritative reset path:** Add `reset_handler_test_runtime()`
in `tests/support/handler_support.py` that clears `_config`, `_provider`,
`_boot_id`, `_rate_limiter`, `_bot_instance`, `_pending_work_items`,
`CHAT_LOCKS`; sets `_current_update_id` to None (current context); resets
`_next_update_id = 0`; closes session and transport DB caches. Prefer explicit
close-all helpers in `app/storage` and `app/work_queue`.

**Phase 3 — Helper stack authoritative:** `setup_globals()` calls
`reset_handler_test_runtime()` first; accept `bot_instance=None`. `fresh_data_dir()`
and `fresh_env()` close both DBs on exit and use the same reset/setup. Add
`autouse=True` fixture in `tests/conftest.py` that calls
`reset_handler_test_runtime()` before and after every test.

**Phase 4 — Remove direct global mutation:** Replace direct `th._bot_instance = ...`
in `test_workitem_integration.py` and `test_invariants.py` with helper-owned
setup. Route all writes through the support layer.

**Phase 5 — Isolation regression tests:** Create
`tests/test_handler_runtime_isolation.py`: (1) mutate state then
`reset_handler_test_runtime()` and assert all cleared; (2) clean runtime, assert
no leaked `_pending_work_items`, `_bot_instance`, `CHAT_LOCKS`; (3) assert
session and transport DB caches closed after teardown.

**Phase 6 — Pilot slice:** Use `test_handlers_output.py` then
`test_handlers_ratelimit.py` as first slices. Do not start with
`test_handlers_approval` or `test_workitem_integration` (more stateful, later).

**Phase 7 — Parallel proof:** Run pilot serially, then with `-n 2` at least
three times. Widen only after pilot is stable. Do not claim full-suite parallel
safety until at least one handler-heavy slice is measured and stable.

**Implementation boundaries:** No broad production refactor of handler logic
first. Extract pure logic only where it reduces coupling after reset
centralization. Do not leave direct test writes and helper setup in parallel
long; migrate and delete. Do not update `docs/STATUS-commercial-polish.md`
until pilot is proven under `-n 2`.

**Validation commands:**

- `rg -n "_th\._|th\._bot_instance\s*=|..." tests`
- `.venv-host/bin/python -m pytest -q tests/test_handler_runtime_isolation.py`
- `.venv-host/bin/python -m pytest -q tests/test_handlers_output.py`
- `.venv-host/bin/python -m pytest -q -n 2 tests/test_handlers_output.py`
- (repeat for ratelimit; combine slices with `-n 2`)

**Definition of done:** One authoritative reset path; per-test reset enforced by
conftest; no direct writes to handler globals outside support; isolation tests
pass; at least one handler slice passes under `-n 2` repeatedly; performance
claims measured.

**Recommended PR split:** (1) Audit note, reset helper, DB close-all, autouse
fixture, isolation tests. (2) Migrate pilot slice, remove direct `_bot_instance`.
(3) Parallel proof, status doc. (4) Expand to other handler suites after pilot.

**Note:** Local full-suite benchmarking is noisy until
`tests/test_sqlite_integration.py` stops assuming Linux `/proc/.../fd`. Exclude
from local timing or fix separately.

### Priority 5: Small feature gaps (low effort, product polish)

Historical mapping: this record now corresponds primarily to active Phases 16
and 17.

**a. `/project` inline keyboard.** `/model`, `/policy`, `/approval`, and
`/compact` all show inline keyboards when invoked with no arguments.
`/project` still requires typing subcommands. Add buttons for configured
projects + `[Clear]`.

**b. Content deduplication.** The plan specified an optional
`BOT_DEDUP_WINDOW_SECONDS` for suppressing identical consecutive messages
within a short window (IV.4). The core contract (`transport idempotency`)
is sufficient. **Demand-gated:** only implement if operators report
accidental double-sends in production.

### Priority 6: Architectural hardening (high effort, conditional)

Historical mapping: this record now corresponds primarily to active Phase 11
and the optional verbose-progress work in Phase 16.

**a. III.7 — Workflow state-machine extraction.** See the detailed spec in
the Phase III section above. Only justified if durable-state bugs continue
consuming review time.

**b. Verbose/debug progress mode.** III.5b implied a toggle between summary
progress (default) and verbose progress (full tool detail). The current
implementation has one rendering path. A `BOT_PROGRESS_VERBOSE` mode could
surface more intermediate detail for power users, but it is not blocking any
real use case today.

### Priority 7: Product extensions (future roadmap)

Historical mapping: this record now corresponds primarily to active Phases
13-19.

**a. Multi-worker webhook deployment.** The durable work-queue foundation is
shipped. The next step is actual multi-process webhook deployment where
multiple worker processes claim items from `transport.db`. See the Product
Extensions section above for the full specification.

**b. Usage tracking and billing.** Deferred. Requires token-cost mapping and
billing integration.

**c. Registry trust and signing.** Currently artifacts are verified by digest
only. A future extension could add publisher signing.

**d. Policy and project expansion.** Per-project file policy defaults,
project-scoped skill activation, richer project scoping models.

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
- first visible progress is sent before provider invocation
- cross-feature invariant tests cover the dangerous combination matrix
- every inbound update receives a visible response, even under burst traffic
- polling conflicts are detected and warned, not silently tolerated
