# PLAN: UI Overhaul

## Status

This document is the single target-state plan for the registry product overhaul.

It supersedes using these documents independently:

- `PLAN-ui-redesign.md`
- `PLAN-task-controls.md`
- scattered review findings about SDK, API, event-model, and SPA drift

Those documents remain useful as background, but implementation should follow this plan.

## Context

The product has been converging toward a single resource API and a single strict event model:

- one registry SDK contract
- one stored conversation event envelope
- one operator mutation surface through `/messages` and `/actions`
- one execution-side publishing surface through `ExecutionEventSink`

At the same time, the desired browser experience has outgrown the original SPA plan. The original redesign document assumed kinds and payloads that were not actually live. The task-controls plan correctly identified the missing capabilities, but it was still a separate plan. That split is how we end up with drift:

- SDK/config/event publishers do one thing
- the UI plan assumes another
- reviewers then have to reconcile incompatible target states after the fact

This plan fixes that by treating the overhaul as one coordinated change set:

1. finalize the backend, API, SDK, and data-model contract
2. add the missing audit and operator-control capabilities
3. redesign the SPA against that final contract

## Product goals

The overhaul should deliver all of the following together:

1. A polished, mobile-first, light/dark registry SPA.
2. A correct chat experience with pinned compose, independent timeline scrolling, predictable live updates, and true older-history loading.
3. A clean operator-facing event timeline that supports:
   - conversation messages
   - provider request audit
   - provider response accounting
   - tool execution audit
   - approval request and approval decision history
   - delegation lifecycle
   - task status
   - errors
4. Browser-based approve/reject/cancel controls using the same domain model and public API surface as every other operator action.
5. Dashboard summary cards that show real global counts, not page-local guesses.
6. One contract across SDK, config, validators, publishers, store queries, and UI rendering.

## Non-goals

These are explicitly out of scope:

1. Framework migration. The SPA stays vanilla HTML, CSS, and JS.
2. Backward compatibility for removed legacy event kinds, metadata shapes, or UI-only payload conventions.
3. A second approval API, second registry client, second event sink, second event envelope, or second browser-only control model.
4. A standalone `file.change` conversation event kind.
5. Real-time per-token or per-tool streaming into the registry timeline during execution. This plan uses post-execution structured audit events.
6. Multiple coexisting dashboard summary models. There is one global summary contract.

## Architecture rules

These are hard rules. They exist specifically to prevent another round of cleanup work.

### 1. One contract only

There must be exactly one authoritative definition of:

- conversation event kinds
- event metadata shapes
- operator mutation surfaces
- task-routing payload shapes
- dashboard aggregate payloads

Authoritative sources:

- `registry_sdk/events.py` for conversation event taxonomy and metadata
- `registry_sdk/tasks.py` for routed-task payloads
- registry HTTP routes for operator/browser mutations
- registry HTTP summary endpoint for dashboard aggregates

Config, stores, publishers, UI code, and plans must derive from those sources. They must not define parallel handwritten copies.

### 2. Reuse existing interfaces and surfaces

Do not invent parallel abstractions when an existing one already fits.

Reuse:

- `ConversationEvent`
- `ExecutionEventSink`
- `RunResult`
- `ConversationProjectionPort`
- `GET /v1/conversations/{id}/events`
- `POST /v1/conversations/{id}/messages`
- `POST /v1/conversations/{id}/actions`

If a new capability needs to be added, extend the existing contract instead of adding a side path.

### 3. No dormant schema kinds

No event kind may exist only "for later."

If a kind exists in the SDK schema, then in the same change set it must also have:

- validator support
- publish-level support
- a real publisher or explicitly committed producer
- tests
- UI handling or documented generic fallback behavior

### 4. No duplicate representations

One concept gets one canonical representation.

Required decisions:

- tool audit lives in `tool.execution`, not also in `provider.response.tool_calls`
- file changes live only in `tool.execution.file_changes[]`, not in a second standalone `file.change` event
- pending approvals render from `approval.requested`, not from a browser-only pending-control model
- dashboard summary comes from one endpoint, not from inferred counts on paginated list pages

### 5. Explicit data only

Critical wire data must not be filled in by silent defaults or inferred compatibility shims.

Required explicitly:

- event IDs
- event timestamps
- event metadata shape
- task timestamps
- pagination semantics
- approval request semantics
- dashboard aggregate payload shape

Optional fields are allowed only when they are truly optional in the domain, not because the implementation is unfinished.

### 6. One operator mutation surface

Browser actions must use the existing conversation resource endpoints:

- `POST /v1/conversations/{id}/messages`
- `POST /v1/conversations/{id}/actions`

No second browser-only approval endpoint is allowed.

### 7. Backend first, then UI

The UI cannot be implemented against imagined backend behavior.

If the target UI requires backend, SDK, API, or database work, that work is part of this plan and must land first or in the same phase. The UI does not get to assume it.

### 8. Removals land with additions

Whenever a new canonical representation is added, the replaced representation must be removed in the same change set.

Examples:

- adding `tool.execution` requires removing `provider.response.tool_calls`
- adding dashboard summary endpoint means the dashboard stops inferring totals from paginated agent lists
- adding `approval.requested` means browser approval UI must stop relying on dead placeholders or ad hoc heuristics

### 9. Docs are downstream of code

The code contract is authoritative.

Plans and docs must be updated in the same change set, but they must describe the actual contract, not preserve dead shapes for convenience.

## Final target-state contract

This section defines the final contract the product should implement. Later phases describe how to get there.

## Final resource API

The SPA depends on these resource surfaces:

- `GET /v1/summary`
- `GET /v1/agents`
- `GET /v1/agents/{id}/status`
- `GET /v1/agents/{id}/conversations`
- `GET /v1/conversations`
- `POST /v1/conversations`
- `GET /v1/conversations/{id}`
- `GET /v1/conversations/{id}/events`
- `POST /v1/conversations/{id}/messages`
- `POST /v1/conversations/{id}/actions`
- `GET /v1/conversations/{id}/export`
- `GET /v1/tasks`
- `GET /v1/usage`

This plan intentionally does not add a second "approval" or "audit" API surface. Those capabilities flow through the existing conversation resources plus new event kinds.

## Final event envelope

All timeline rendering and live updates use the same stored event envelope:

```json
{
  "seq": 12,
  "event_id": "evt-123",
  "conversation_id": "conv-123",
  "agent_id": "agent-123",
  "kind": "message.user",
  "actor": "Alice",
  "content": "Hello",
  "metadata": {},
  "created_at": "2026-03-24T00:00:00+00:00"
}
```

The UI renders from:

- top-level `actor`
- top-level `content`
- top-level `created_at`
- `metadata`

It must not depend on old names such as `request_user_id`.

## Final event taxonomy

The final supported conversation event kinds are:

- `message.user`
- `message.bot`
- `provider.request`
- `provider.response`
- `tool.execution`
- `approval.requested`
- `approval.decided`
- `delegation.proposed`
- `delegation.submitted`
- `delegation.completed`
- `task.status`
- `error`

Explicitly not part of the target-state taxonomy:

- `file.change`

## Final metadata contract

The SDK owns these shapes. The UI plan is downstream of them.

### `message.user` / `message.bot`

```python
class MessageMetadata(BaseModel):
    attachments: list[str] = []
```

These events primarily render from top-level `actor` and `content`.

### `provider.request`

```python
class ProviderRequestMetadata(BaseModel):
    provider: str
    model: str
    execution_mode: Literal["run", "resume", "preflight", "retry"]
    working_dir: str
    file_policy: str
    image_count: int
    prompt_char_count: int
```

Top-level `content` is the redacted prompt text actually sent to the provider.

### `provider.response`

```python
class ProviderResponseMetadata(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    provider: str
```

No `tool_calls` field exists in the final target state.

### `tool.execution`

```python
class FileChangeSummary(BaseModel):
    path: str
    change_type: Literal["created", "modified", "deleted", "renamed"]
    summary: str


class ToolExecutionMetadata(BaseModel):
    tool_name: str
    call_id: str
    status: Literal["completed", "failed", "denied"]
    input_summary: str
    output_summary: str
    duration_ms: int | None = None
    file_changes: list[FileChangeSummary] = []
```

Top-level `content` is a concise human-readable summary of the tool action.

### `approval.requested`

```python
class ApprovalRequestedMetadata(BaseModel):
    request_kind: Literal["preflight", "retry", "delegation"]
    actor_key: str
    trust_tier: str
    expires_at: str | None = None
```

Top-level `content` is the approval prompt text shown to the operator.

The metadata does not duplicate public action names. The public mutation surface is already defined by `/actions`.

### `approval.decided`

```python
class ApprovalMetadata(BaseModel):
    action: str
    decided_by: str
    decision: Literal["approved", "rejected"]
```

### `delegation.proposed` / `delegation.submitted` / `delegation.completed`

```python
class DelegationTaskSummary(BaseModel):
    title: str
    target: str
    status: str


class DelegationMetadata(BaseModel):
    tasks: list[DelegationTaskSummary]
```

### `task.status`

```python
class TaskStatusMetadata(BaseModel):
    status: str
    progress: int | None = None
```

No `title` field exists in the target-state task status metadata.

### `error`

```python
class ErrorMetadata(BaseModel):
    error_type: str
    message: str
```

## Final conversation event pagination contract

True chat UX requires explicit older-history support. This plan uses the existing `/events` resource, not a second history endpoint.

Target query semantics:

- `GET /v1/conversations/{id}/events?limit=50`
  - returns the latest 50 events in ascending `seq` order
- `GET /v1/conversations/{id}/events?before_seq=500&limit=50`
  - returns the 50 events immediately before `seq=500`, still in ascending order
- `GET /v1/conversations/{id}/events?after_seq=500&limit=50`
  - returns events with `seq > 500`, in ascending order

Rules:

- `before_seq` and `after_seq` are mutually exclusive
- returned events are always sorted oldest to newest within the returned window
- the default "latest window" behavior is part of the contract, not a client convention

## Final dashboard summary contract

Dashboard summary is one global read model, not inferred from paginated lists.

`GET /v1/summary` returns:

```json
{
  "generated_at": "2026-03-24T00:00:00+00:00",
  "agents": {
    "total": 12,
    "connected": 10,
    "degraded": 1,
    "disconnected": 1
  },
  "conversations": {
    "total": 143,
    "active": 18,
    "pending_approvals": 2
  },
  "tasks": {
    "running": 5,
    "pending": 1,
    "failed_24h": 3
  },
  "usage_24h": {
    "prompt_tokens": 123456,
    "completion_tokens": 78901,
    "cost_usd": 12.34
  }
}
```

Rules:

- this is the only source for dashboard totals
- page-level list endpoints remain paginated resource views, not aggregate sources
- no duplicate summary object should be embedded into unrelated list responses

## Final operator action contract

Conversation mutations remain:

- `POST /v1/conversations/{id}/messages` with `{ "text": "..." }`
- `POST /v1/conversations/{id}/actions` with `{ "action": "...", "payload": {...} }`

Canonical browser-facing actions:

- `approve`
- `reject`
- `cancel_conversation`

Internal workflow mapping may translate those into more specific internal action names, but that translation is not part of the public API contract and must not leak into the UI schema.

## Final approval lifecycle rules

The target state keeps approval semantics simple and deterministic:

1. At most one approval request may be open per conversation at a time.
2. Creating a pending approval writes `approval.requested`.
3. Acting on that pending approval through `/actions` writes `approval.decided`.
4. If an approval expires, the action endpoint rejects late decisions.
5. The UI may infer actionability from the latest unresolved `approval.requested` plus `expires_at`, but the server remains authoritative.

This avoids adding a second approval-read model or a request-ID negotiation API.

## Final event rendering matrix

The conversation timeline renders as follows:

- `message.user`, `message.bot`
  - chat bubbles
  - use top-level `actor`, `content`, `created_at`

- `provider.request`
  - audit card
  - provider, model, execution mode, working dir, file policy, image count, prompt size
  - expandable prompt body from top-level `content`

- `provider.response`
  - compact metrics card
  - provider, prompt tokens, completion tokens, cost

- `tool.execution`
  - tool card
  - tool name, status, input summary, output summary, duration
  - nested file changes list from `file_changes[]`

- `approval.requested`
  - pending approval card
  - request kind, trust tier, expiry
  - Approve and Reject buttons wired to `/actions`

- `approval.decided`
  - compact decision card
  - action, decision, decided_by

- `delegation.proposed`, `delegation.submitted`, `delegation.completed`
  - delegation card
  - render `tasks[]` with title, target, status

- `task.status`
  - compact status card
  - status plus optional progress

- `error`
  - error card
  - error type plus message

- unknown kinds
  - generic expandable fallback card
  - show top-level `content` plus pretty-printed `metadata`

The generic fallback is deliberate. It is not a temporary development-only mode.

## Database and index implications

This plan reuses the existing event store. It does not add a second audit table or summary cache by default.

Required database work:

1. Add or verify indexes for event pagination:
   - `(conversation_id, seq)`
   - descending access path where needed for latest-window queries
2. Add or verify indexes needed for dashboard summary queries:
   - agent connectivity/state
   - task status and task timestamps
   - event kind and created_at for recent usage and pending approval counts
3. Keep event storage in the single canonical `events` table. Do not add parallel timeline tables.

Summary caching is out of scope unless real measurements prove it is necessary after the direct-query version lands.

## Sequencing overview

The work must land in this order:

1. Contract lock and document consolidation
2. SDK and config taxonomy changes
3. provider/runtime audit publication changes
4. approval lifecycle publication and action handling changes
5. conversation read-model and pagination changes
6. dashboard summary read-model changes
7. SPA shell, theme, layout, and component foundation
8. conversation detail redesign
9. dashboard, agent, task, and usage page redesign
10. cleanup, removals, and invariant enforcement

Do not start specialized UI event cards before the event contract and publishers are real.

## Phase 0: Consolidation and contract lock

### 0.1 Make this plan authoritative

This file becomes the sole execution plan for the overhaul.

Implementation must not mix and match from older plans.

### 0.2 Resolve planning contradictions up front

Before code work starts:

1. stop treating `provider.request`, `tool.execution`, and `approval.requested` as if they already exist
2. stop treating `file.change` as a live target-state concern
3. stop treating `provider.response` as the long-term tool-audit carrier
4. stop treating dashboard totals as something the SPA can infer from paginated resources
5. stop treating forward-only event pagination as sufficient for the desired chat UX

### 0.3 Freeze the product decisions

This plan assumes the following are true product decisions:

1. browser approvals are required
2. tool and file audit are required
3. global dashboard summary is required
4. true older-history scrolling is required
5. there will be one final event taxonomy, not a "current" and "future" version

If any of those change, revise the plan before implementation starts.

**Exit gate:** stakeholders agree on the final target state, not just the first implementation slice.

## Phase 1: SDK taxonomy, validators, and publish-level alignment

Files:

- `registry_sdk/events.py`
- `registry_sdk/__init__.py`
- `registry_sdk/client.py`
- `app/config.py`
- event-schema and config contract tests

Implementation:

1. Add `provider.request`, `tool.execution`, and `approval.requested` to the SDK event taxonomy.
2. Add the final metadata models from this plan.
3. Remove `tool_calls` from `ProviderResponseMetadata`.
4. Keep `extra="forbid"` on all metadata models.
5. Keep explicit timestamps required on event models.
6. Keep `file.change` absent.
7. Make publish levels derive from the canonical live taxonomy. Do not keep a second handwritten superset.

Required removals in the same phase:

- remove all references to `provider.response.tool_calls` from the canonical schema
- remove all config references to `file.change`
- remove any config-to-schema drift

Tests:

1. every publishable kind has a schema
2. every schema-backed live kind is represented in the intended publish levels
3. unknown kinds are rejected
4. extra metadata keys are rejected
5. removed kinds are rejected

**Exit gate:** SDK, config, and validator all agree on one exact live taxonomy.

## Phase 2: Provider result model and execution audit publication

Files:

- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`
- `app/workflows/execution/event_sink.py`
- `app/workflows/execution/requests.py`
- execution/provider tests

Implementation:

1. Extend `RunResult` with structured tool execution records.
2. Add file-change summaries nested inside tool execution records.
3. Extend `ExecutionEventSink` with:
   - `on_provider_request(...)`
   - `on_tool_execution(...)`
   - `on_approval_requested(...)`
4. Publish `provider.request` before provider execution.
5. Publish `provider.response` after provider execution.
6. Publish one `tool.execution` event per completed tool execution, in deterministic order.
7. Use stable derivable event IDs for all new audit events.

Rules:

- provider modules do not publish registry events directly
- no second telemetry path is introduced
- tool execution is not duplicated inside `provider.response`
- file changes are not duplicated as standalone events

Required removals in the same phase:

- remove any remaining `tool_calls` publication from the sink or result model
- remove any ad hoc event metadata fields not present in the SDK schema

Tests:

1. providers populate `RunResult.tool_executions`
2. sink publishes schema-valid `provider.request`
3. sink publishes schema-valid `provider.response`
4. sink publishes schema-valid `tool.execution`
5. event order is stable and deterministic
6. retried publish does not create duplicate cards due to stable event IDs

**Exit gate:** provider audit and tool audit are fully live through the canonical event model.

## Phase 3: Approval lifecycle publication and browser control semantics

Files:

- `app/workflows/execution/requests.py`
- pending-approval workflow modules
- `app/channels/registry/http.py`
- registry store backends
- approval-focused tests

Implementation:

1. Publish `approval.requested` whenever an approval is created.
2. Keep `approval.decided` as the canonical decision event.
3. Reuse the existing `/actions` endpoint.
4. Keep the public browser-facing actions as `approve`, `reject`, and `cancel_conversation`.
5. Ensure approval decisions are written with the final `ApprovalMetadata` shape.
6. Enforce at most one open approval per conversation.
7. Enforce expiry at the action-handler boundary.

Rules:

- no new approval endpoint
- no browser-only approval model
- no duplicated action names in event metadata
- no second approval status table

Tests:

1. approval creation writes `approval.requested`
2. approve/reject through `/actions` writes `approval.decided`
3. no pending approval means the action endpoint rejects the request
4. expired approvals cannot be decided
5. browser actions and non-browser actions share the same workflow semantics

**Exit gate:** browser approvals are possible with no special-case side path.

## Phase 4: Conversation event read model and pagination

Files:

- `app/channels/registry/http.py`
- `app/registry_service/store.py`
- `app/registry_service/store_postgres.py`
- migration/schema files if new indexes are required
- events API tests

Implementation:

1. Extend `GET /v1/conversations/{id}/events` to support:
   - default latest-window load
   - `before_seq`
   - `after_seq`
2. Keep response ordering ascending within a returned window.
3. Keep the envelope identical between HTTP and WebSocket paths.
4. Add the indexes needed for latest-window and before/after queries.
5. Keep export and non-chat use cases on the same event data.

Rules:

- do not add a separate history endpoint
- do not add a second event envelope for live updates
- do not require the UI to infer reverse pagination from a forward-only API

Tests:

1. latest-window load returns the newest N events ascending
2. `before_seq` returns the correct older slice
3. `after_seq` returns the correct newer slice
4. mutually exclusive cursors are enforced
5. WebSocket catch-up via `after_seq` reproduces consistent history

**Exit gate:** the event API can support the desired chat UX without client-side guesswork.

## Phase 5: Dashboard summary read model

Files:

- `app/channels/registry/http.py`
- registry store backends
- summary endpoint tests

Implementation:

1. Add `GET /v1/summary`.
2. Compute the global aggregates defined in this plan.
3. Use direct queries against the existing normalized tables.
4. Reuse existing concepts:
   - agent connectivity
   - conversation activity
   - pending approvals
   - task states
   - usage from `provider.response`

Rules:

- do not embed duplicate summary blocks into list endpoints
- do not ask the SPA to synthesize global counts from paginated resources
- do not introduce a summary cache or materialized table unless measurement proves it is necessary

Tests:

1. endpoint returns the documented payload shape
2. counts match seeded data
3. usage summary matches `provider.response` events only
4. pending approval count matches open approval state

**Exit gate:** the dashboard has one canonical aggregate source.

## Phase 6: SPA foundation, design system, and shell

Files:

- `ui/index.html`
- `ui/css/main.css`
- `ui/js/app.js`
- `ui/js/router.js`
- shared UI helpers

Implementation:

1. Replace magic-number spacing with tokenized spacing scale.
2. Add light and dark theme variables plus manual theme toggle.
3. Add glass/elevation system with graceful fallback where blur is unsupported.
4. Make the router own route transition timing and teardown.
5. Standardize card, stat-card, filter-bar, and empty-state helpers.
6. Add accessibility baseline:
   - keyboard-focus visible states
   - tab-order correctness
   - Enter/Space activation on non-button interactive elements
   - modal focus trapping
   - focus return on close
   - skip link
   - `prefers-reduced-motion`

Rules:

- no inline style mutation for layout/theming
- no duplicated card-rendering patterns
- no route-transition logic hidden in unrelated bootstrap code

Tests and checks:

1. light and dark theme snapshot/smoke checks
2. keyboard navigation smoke test
3. reduced-motion smoke test

**Exit gate:** the app shell is visually coherent, accessible, and ready for page-level work.

## Phase 7: Conversation detail redesign

Files:

- `ui/js/components/conversation-detail.js`
- `ui/js/api.js`
- related CSS
- conversation page tests

Implementation:

1. Restructure the conversation detail as a dedicated full-height flex view.
2. Keep metadata pinned at top.
3. Make the timeline the independent scroll region.
4. Keep the compose box pinned at the bottom.
5. Use the final event rendering matrix from this plan.
6. Add specialized cards for:
   - `provider.request`
   - `provider.response`
   - `tool.execution`
   - `approval.requested`
   - `approval.decided`
   - `delegation.*`
   - `task.status`
   - `error`
7. Keep the generic fallback card for unknown kinds.
8. Wire Approve and Reject buttons on `approval.requested` cards through `/actions`.
9. Implement correct live auto-scroll:
   - capture near-bottom state before append
   - scroll only if user was already near bottom
10. Implement older-history loading with:
   - top sentinel
   - scroll-anchor preservation on prepend
   - single-flight guard

Rules:

- no raw event publishing from the browser
- no dead button states
- no rendering assumptions that are not backed by the SDK schema

Tests:

1. event kind to card-type mapping
2. approval-request card actions hit `/actions`
3. history prepend preserves viewport anchor
4. live append does not yank the viewport when user is reading older messages
5. generic fallback card renders unknown kinds safely

**Exit gate:** the conversation view works as a real chat interface and as a structured event timeline.

## Phase 8: Dashboard, agent, task, usage, and list pages

Files:

- `ui/js/components/dashboard.js`
- `ui/js/components/agent-list.js`
- `ui/js/components/agent-detail.js`
- `ui/js/components/conversation-list.js`
- `ui/js/components/task-list.js`
- `ui/js/components/usage-view.js`
- related CSS

Implementation:

1. Dashboard uses `GET /v1/summary` for top-line stats.
2. Agent list and detail pages use the resource payloads directly, without inferring dashboard totals.
3. Conversation list focuses on browsing and filtering, not summary math.
4. Task view uses the existing task resource, not conversation metadata as a task proxy.
5. Usage view stays aligned with `provider.response` accounting.
6. Mobile layout collapses secondary detail blocks into stacked sections or accordions where necessary.

Rules:

- do not duplicate summary widgets across unrelated pages with different data sources
- do not infer task or usage totals from conversation-event cards

Tests:

1. dashboard reads only from `/v1/summary`
2. agent pages render current resource payloads cleanly
3. list pages remain usable on mobile

**Exit gate:** the rest of the SPA is consistent with the new shell and the final backend contract.

## Phase 9: Cleanup and removals

This phase is mandatory. It is where the anti-drift rules become real.

Remove:

1. any remaining references to `provider.response.tool_calls`
2. any remaining references to standalone `file.change`
3. any remaining UI assumptions that dashboard totals come from paginated lists
4. any remaining dead approval placeholder behavior
5. any plan/docs text that describes the old event taxonomy as current
6. any config or store logic that preserves removed kinds
7. any UI helper shape that duplicates the canonical event or action contract

Rules:

- do not leave aliases or "temporary" compatibility shapes
- do not leave stale schema text in docs
- do not keep both old and new render paths for the same concept

**Exit gate:** grep-able removal checks pass, and no dead contract paths remain.

## Phase 10: Invariants, tests, and release gates

This phase is the main protection against repeating recent mistakes.

### 10.1 Contract invariants

Add automated invariants for:

1. SDK schema kinds match intended publishable kinds
2. removed kinds do not appear in config
3. event publishers emit schema-valid metadata
4. stores and HTTP validators accept the canonical shapes and reject drift
5. summary endpoint shape is pinned
6. event pagination semantics are pinned

### 10.2 Integration coverage

Add or update tests that exercise:

1. provider run -> sink -> registry HTTP -> stored event for:
   - `provider.request`
   - `provider.response`
   - `tool.execution`
2. approval creation -> `approval.requested` -> browser action -> `approval.decided`
3. dashboard summary aggregates
4. reverse pagination
5. WebSocket live update consistency with stored events

### 10.3 SPA end-to-end coverage

Add browser tests for:

1. conversation load at latest window
2. scroll up to load older history
3. live append while at bottom
4. live append while scrolled away from bottom
5. approval card approve/reject flow
6. provider/tool audit card rendering
7. dashboard summary rendering
8. light/dark theme toggle
9. keyboard-only navigation through main flows

### 10.4 Release gates

The overhaul is not done until all of these are true:

1. one final event taxonomy exists in code and docs
2. SDK, config, publishers, validators, stores, and SPA all use that taxonomy
3. browser approvals work through `/actions`
4. conversation history supports older-history loading
5. dashboard totals come from the summary endpoint
6. no duplicate tool/file/approval/dashboard representations remain
7. all focused contract, integration, and browser tests pass

## Implementation order and slicing

Recommended implementation slices:

1. Phase 1
2. Phase 2
3. Phase 3
4. Phase 4
5. Phase 5
6. Phase 6
7. Phase 7
8. Phase 8
9. Phase 9
10. Phase 10

Do not reorder this to start with UI cards or CSS polish. The backend and contract slices must land first.

## Developer prompt

Use this plan as the only target-state contract for the overhaul.

Rules for implementation:

1. Reuse existing interfaces and surfaces. Extend `ExecutionEventSink`, `RunResult`, `ConversationEvent`, `/events`, and `/actions`. Do not create parallel abstractions.
2. Add and remove in the same change set. When `tool.execution` lands, remove `provider.response.tool_calls`. Do not leave both live.
3. Do not introduce standalone `file.change`.
4. Keep SDK schema, config publish levels, HTTP validators, publishers, stores, and UI rendering aligned at every step.
5. Do not add defaults, aliases, compatibility shims, or dormant future-only kinds.
6. Keep event IDs and timestamps explicit and deterministic where this plan specifies them.
7. Use `/v1/summary` for dashboard totals, never inferred counts from paginated resource endpoints.
8. Use `/v1/conversations/{id}/actions` for browser approvals and cancel, not a second endpoint.
9. Keep the event envelope identical between stored-history and WebSocket/live paths.
10. Treat generic fallback event rendering as a real product feature, not a temporary development crutch.

Before marking the overhaul done, verify all release gates in Phase 10. If any phase lands partially, the work is not complete.
