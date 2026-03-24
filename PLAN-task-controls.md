# PLAN: Task Controls and Execution Audit Events

## Context

The registry event contract was intentionally tightened to the kinds that are live today:

- `message.user`
- `message.bot`
- `provider.response`
- `approval.decided`
- `delegation.proposed`
- `delegation.submitted`
- `delegation.completed`
- `task.status`
- `error`

That cleanup was directionally correct. It removed dead schema surface and kept the SDK, config, HTTP validator, and active publishers aligned.

The next step is not to re-add dormant kinds as placeholders. The next step is to add the missing capabilities as a **single end-to-end change set** so the system stays coherent:

- provider request audit
- tool execution audit
- browser-visible pending approvals
- file change visibility

This plan defines how to add those capabilities without recreating the drift that caused the recent fixes.

## Architecture rules

These are hard rules for this change set.

1. **One live contract only.**
   - If a kind exists in the SDK schema, it must have a publisher or a committed implementation in the same change set.
   - If a kind is publishable in config, it must be accepted by the SDK validator.
   - If the UI plan lists a kind as current, it must exist in the SDK and have real publisher semantics.

2. **Reuse existing interfaces and surfaces.**
   - Reuse `ConversationEvent` in `registry_sdk/events.py`.
   - Reuse `ExecutionEventSink` as the execution-side publishing façade.
   - Reuse `RunResult` as the provider-to-workflow result carrier.
   - Reuse `POST /v1/conversations/{id}/actions` for approve/reject/cancel. No new approval endpoint.

3. **No parallel paths.**
   - Do not add a second registry client.
   - Do not add a second event sink.
   - Do not add a second approval action surface.
   - Do not add a second “tool summary” representation if one already exists.

4. **No dormant schema-only event kinds.**
   - We do not keep event kinds in the contract “for later”.
   - New kinds land only when the publisher, UI handling, config, tests, and docs land together.

5. **No redundant concepts.**
   - If `tool.execution` becomes the canonical tool-audit event, `provider.response.tool_calls` must be removed.
   - File changes must not be represented both as standalone `file.change` events and as structured fields on `tool.execution`.
   - Approval buttons must derive from `approval.requested` plus the existing `/actions` surface, not from a second ad hoc browser-only control model.

6. **Explicit data only. No hidden defaults.**
   - Event timestamps are explicit.
   - Routed-task timestamps are explicit.
   - Approval request details are explicit.
   - No “fill it in later” code paths in adapters or validators.

7. **Docs are downstream of code, not a second source of truth.**
   - The SDK event taxonomy is authoritative.
   - Config must reference that taxonomy.
   - Plans and UI docs must be updated in the same change set.

## Problem statement

We want to support:

1. Prompt audit in the registry timeline.
2. Tool and file activity in the registry timeline.
3. Pending approvals in the browser, using the same domain flow as Telegram.

The system cannot get there by sprinkling old kinds back into the schema map.

That would recreate the exact failure mode we just fixed:

- schema kinds that nothing publishes
- config kinds the validator rejects
- UI plans that list kinds that do not exist
- duplicate semantics between event kinds
- publishers and consumers evolving independently

The fix is a single contract-first change set with removals as well as additions.

## Decisions

### D1. Add `provider.request`

`provider.request` becomes a real event kind.

Purpose:
- audit what was sent to the provider
- show operator-visible execution context at the start of a run

Publisher:
- `ExecutionEventSink`, from the existing `execute_request` / `request_approval` flow

### D2. Add `tool.execution`

`tool.execution` becomes the canonical structured tool-audit event.

Purpose:
- record individual tool use in the conversation timeline
- support operator inspection without parsing provider-specific raw output

Publisher:
- `ExecutionEventSink`, after provider completion, from structured tool execution records collected in `RunResult`

### D3. Do **not** restore standalone `file.change`

This is the main anti-drift decision.

We want file change visibility, but we do **not** want two competing representations:

- `tool.execution.file_changes[]`
- `file.change`

That is duplicated semantics. The canonical representation will be:

- file changes nested under `tool.execution`

Result:
- **do not** re-add `file.change` to the event taxonomy
- **remove** any lingering `file.change` references from plans/docs/UI assumptions

### D4. Add `approval.requested`

`approval.requested` becomes the canonical pending-approval event.

Purpose:
- show pending approvals in the browser timeline
- let the SPA render approve/reject controls against the existing `/actions` surface

Publisher:
- the existing approval-creation path in `request_approval`, not a Telegram-only callback path

### D5. Keep `approval.decided`

`approval.decided` remains the decision event written by the operator action flow.

No second “approval result” kind is added.

### D6. Remove `tool_calls` from `provider.response`

If `tool.execution` exists, `provider.response.tool_calls` is redundant.

`provider.response` remains the response/accounting event:
- `prompt_tokens`
- `completion_tokens`
- `cost_usd`
- `provider`

It does **not** also carry tool execution detail.

### D7. Reuse `/actions`; do not add a new approval mutation API

The browser should continue using:

- `POST /v1/conversations/{id}/actions`

with existing action semantics:
- `approve`
- `reject`
- `cancel_conversation`

Internal delivery mapping may continue to translate browser-friendly `approve` / `reject` to `approve_pending` / `reject_pending`, but that translation remains one existing implementation path, not a second public API.

### D8. Reuse `RunResult`; do not add a second provider telemetry interface

Providers already return `RunResult`.

We extend `RunResult` to include structured tool execution records. We do **not** add:
- a second provider event client
- a raw provider telemetry side channel
- a new provider-to-registry interface

### D9. One source of truth for event kinds

The event taxonomy lives in `registry_sdk/events.py`.

`app/config.py` publish levels must be defined against that canonical set. The change set must add an invariant test that publishable kinds cannot drift away from schema-supported kinds.

## Target event taxonomy

After this change set, the canonical conversation event kinds are:

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

Explicitly **not** in the taxonomy:

- `file.change`

## Target schema contract

### `provider.request`

Top-level fields:
- `actor`: optional display actor
- `content`: the redacted prompt text actually sent to the provider

Metadata:

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

Notes:
- `content` is the human-readable audit text
- `prompt_char_count` is structural; it does not duplicate the prompt body
- no second `prompt_text` field in metadata

### `provider.response`

Metadata becomes:

```python
class ProviderResponseMetadata(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    provider: str
```

Removed:
- `tool_calls`

Reason:
- tool execution moves to `tool.execution`

### `tool.execution`

Canonical structured tool-audit event.

One event per completed tool execution, not separate start/finish event kinds.

Metadata:

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

Top-level content:
- short human-readable summary of the tool action

Notes:
- `file_changes[]` is the only file-change representation in the event model
- command tools and non-command tools both use this same kind

### `approval.requested`

Canonical pending-approval event.

Metadata:

```python
class ApprovalRequestedMetadata(BaseModel):
    request_kind: Literal["preflight", "retry", "delegation"]
    actor_key: str
    trust_tier: str
    approve_action: Literal["approve_pending"]
    reject_action: Literal["reject_pending"]
    expires_at: str | None = None
```

Top-level content:
- the approval prompt shown to the user/operator

Notes:
- no callback token is exposed in the event contract
- the browser acts on the current conversation-level pending state via the existing `/actions` surface

### `approval.decided`

Keep existing required fields:

```python
class ApprovalMetadata(BaseModel):
    action: str
    decided_by: str
    decision: Literal["approved", "rejected"]
```

## Event ID strategy

This change set should not keep random ad hoc IDs for the new audit/control events.

For every execution run, derive a stable `execution_event_prefix` once, then derive event IDs from it:

- `provider.request` → `exec:{prefix}:request`
- `provider.response` → `exec:{prefix}:response`
- `tool.execution` #0 → `exec:{prefix}:tool:0`
- `tool.execution` #1 → `exec:{prefix}:tool:1`

For approvals:

- `approval.requested` should derive from the conversation plus the pending request identity, not a random UUID
- recommended basis:
  - `conversation_key`
  - `pending.context_hash`
  - pending state kind (`preflight`, `retry`, `delegation`)

Reason:
- idempotent publish on retry
- no duplicate timeline cards when publish is retried

## Phase 0: Contract lock before implementation

Before code changes, write down the exact contract and remove contradictory assumptions.

### 0.1 Update the target docs

Update:
- `PLAN-ui-redesign.md`

So it no longer claims:
- `file.change` is a live event kind
- `approval.requested` is already in the SDK when it is not
- `provider.response` carries the old tool-call semantics once `tool.execution` lands

### 0.2 Freeze the target taxonomy in one place

In `registry_sdk/events.py`:
- add the new schema classes
- export the canonical kind set

In `app/config.py`:
- define publish levels from that kind set
- do not keep an independent handwritten superset

### 0.3 Remove the old assumption before adding the new one

In the same change set:
- remove `tool_calls` from `ProviderResponseMetadata`
- remove any plan/UI/docs references to standalone `file.change`

This is mandatory. Do not add `tool.execution` while also keeping old tool reporting.

## Phase 1: SDK and validator changes

Files:
- `registry_sdk/events.py`
- `registry_sdk/__init__.py`
- `registry_sdk/client.py`
- `app/config.py`
- `tests/test_registry_sdk_contract.py`
- `tests/test_config.py`

Implementation:

1. Add:
   - `ProviderRequestMetadata`
   - `ToolExecutionMetadata`
   - `FileChangeSummary`
   - `ApprovalRequestedMetadata`

2. Extend `EVENT_METADATA_SCHEMAS` with:
   - `provider.request`
   - `tool.execution`
   - `approval.requested`

3. Remove `tool_calls` from `ProviderResponseMetadata`.

4. Keep `extra="forbid"` on all schema classes.

5. Keep explicit timestamps required on all SDK models.

6. Update `PUBLISH_LEVEL_KINDS`:
   - `standard` and `full` must include the exact new live kinds
   - `file.change` must remain absent

7. Add invariant tests:
   - every publishable kind has a schema
   - no unsupported schema kind is accidentally omitted from the explicit “full” publish level unless intentionally documented

## Phase 2: Provider result model, not a second telemetry path

Files:
- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`
- related provider tests

Implementation:

1. Add structured provider result records to `app/providers/base.py`:

```python
@dataclass(frozen=True)
class FileChangeRecord:
    path: str
    change_type: str
    summary: str


@dataclass(frozen=True)
class ToolExecutionRecord:
    tool_name: str
    call_id: str
    status: str
    input_summary: str
    output_summary: str
    duration_ms: int | None = None
    file_changes: tuple[FileChangeRecord, ...] = ()
```

2. Extend `RunResult`:

```python
tool_executions: list[ToolExecutionRecord] = field(default_factory=list)
```

3. Claude and Codex providers populate `tool_executions` while parsing their existing raw streams.

4. Do not publish registry events from provider modules.

5. If a provider cannot yet extract file changes reliably:
   - it should emit `tool_executions` with empty `file_changes`
   - it should **not** invent a partial `file.change` side channel

6. If a provider emits both command and tool activity, normalize both into `ToolExecutionRecord`.

## Phase 3: ExecutionEventSink additions

Files:
- `app/ports/execution_events.py`
- `app/workflows/execution/event_sink.py`
- `app/workflows/execution/requests.py`
- `tests/test_operational_units.py`
- execution/event-sink focused tests

Implementation:

1. Extend the existing sink interface with:
   - `on_provider_request(...)`
   - `on_tool_execution(...)`
   - `on_approval_requested(...)`

2. Do not add a second sink.

3. `RegistryEventSink` publishes:
   - `provider.request` before provider execution
   - `provider.response` after provider execution
   - one `tool.execution` event per `RunResult.tool_executions`
   - `approval.requested` when approval is created

4. `NoOpEventSink` grows the same methods and remains a singleton no-op.

5. `provider.response` publication must no longer include `tool_calls`.

6. `tool.execution` ordering:
   - publish after the provider returns, in the exact order collected in `RunResult.tool_executions`
   - this avoids needing a second live telemetry path now

## Phase 4: Provider-request audit publication

Files:
- `app/workflows/execution/requests.py`
- possibly `app/execution_context.py`
- tests covering execution publication

Implementation:

1. Build `provider.request` from existing execution data already available before the provider call:
   - prompt text
   - provider name
   - resolved model
   - working dir
   - file policy
   - image count

2. Reuse the same redaction rules already used for approval planning.

3. Do not duplicate prompt text in metadata.

4. Publish exactly once per provider run attempt.

5. If approval mode creates a preflight and then a real execution:
   - preflight uses `execution_mode="preflight"`
   - actual execution uses `execution_mode="run"` or `resume`

## Phase 5: Approval-request publication and browser controls

Files:
- `app/workflows/execution/requests.py`
- `app/workflows/pending/requests.py`
- `app/agents/delivery.py`
- `ui/js/components/conversation-detail.js`
- `ui/js/api.js`
- browser tests

Implementation:

1. Publish `approval.requested` at the moment a pending approval is created.

2. Derive it from existing pending-domain state:
   - `PendingApproval`
   - `PendingRetry`
   - delegation approval state where applicable

3. Top-level content is the approval prompt already shown to users.

4. Metadata uses the existing action semantics:
   - `approve_action="approve_pending"`
   - `reject_action="reject_pending"`

5. The SPA reuses existing `conversationAction(id, action, payload)`:
   - browser button “Approve” sends `approve`
   - browser button “Reject” sends `reject`
   - delivery mapping continues to translate those aliases to the existing pending-domain actions

6. Do not add:
   - `/approve`
   - `/reject`
   - `/pending`
   - or a browser-only approval endpoint

7. `approval.decided` remains the decision history event written by the store on action.

## Phase 6: UI and plan alignment

Files:
- `PLAN-ui-redesign.md`
- `ui/js/components/conversation-detail.js`
- any event rendering helpers introduced by the redesign

Implementation:

1. The UI plan must list the real final kind set, not placeholders.

2. Conversation detail must render:
   - `provider.request`
   - `tool.execution`
   - `approval.requested`
   - `approval.decided`

3. The UI must not expect:
   - standalone `file.change`
   - `provider.response.tool_calls`

4. `approval.requested` cards re-enable Approve/Reject buttons, but only for this live kind.

5. Unknown kinds still fall back to generic expandable cards.

## Phase 7: Test matrix

This change set is not done until all of these exist.

### SDK / contract tests

- `provider.request` metadata validates and rejects extras
- `tool.execution` metadata validates and rejects extras
- `approval.requested` metadata validates and rejects extras
- `provider.response` rejects legacy `tool_calls`
- `file.change` is rejected as unknown kind

### Config invariants

- publish levels include `provider.request`, `tool.execution`, `approval.requested`
- publish levels do not include `file.change`
- every publishable kind has a schema

### Sink / execution tests

- `execute_request` publishes `provider.request` before provider run
- `execute_request` publishes `provider.response` after run
- `execute_request` publishes `tool.execution` for collected tool records
- `request_approval` publishes `approval.requested`

### Store / HTTP / websocket tests

- HTTP accepts the new kinds with valid metadata
- HTTP rejects legacy shapes (`tool_calls`, `file.change`)
- websocket broadcasts the full stored envelope for the new kinds

### Browser tests

- `approval.requested` renders approve/reject controls
- clicking approve/reject uses existing `/actions`
- `approval.decided` renders correctly after action
- `tool.execution` renders nested file changes

### End-to-end tests

- one request with tool use produces:
  - `provider.request`
  - `tool.execution` events
  - `provider.response`
- one approval-required request produces:
  - `approval.requested`
  - browser approve
  - `approval.decided`

## Phase 8: Explicit removals in the same change set

This is mandatory.

When the new capability lands, remove these at the same time:

1. `provider.response.tool_calls`
2. all plan/UI/docs references to standalone `file.change`
3. any schema/config/test assumptions that `approval.requested` exists without a publisher
4. any UI assumptions that `tool.execution` and `provider.response.tool_calls` both describe tool use

Do not leave the old representation in place “for compatibility”.

## Risks and mitigations

### Risk 1: Provider-specific extraction quality differs

Mitigation:
- normalize into `RunResult.tool_executions`
- allow empty `file_changes`
- do not add provider-specific schema branches

### Risk 2: Approval cards become stale after context invalidation

Mitigation:
- `approval.requested` is history, not authoritative current state
- browser approve/reject still goes through existing pending-domain validation
- invalid/expired requests remain rejected by the same existing workflow rules

### Risk 3: Schema/config drift returns later

Mitigation:
- add invariant tests
- keep taxonomy sourced from SDK
- require every event-kind addition to touch SDK + config + publishers + tests + UI in one PR

### Risk 4: Tool/file semantics drift

Mitigation:
- `tool.execution` is canonical
- `file.change` remains absent
- `provider.response` remains accounting-only

## Out of scope

- live per-token or per-tool streaming into the registry during execution
- a second approval API
- a second file-change event kind
- backward compatibility for removed legacy event kinds

## Exit criteria

This plan is complete only when all of the following are true:

1. `provider.request`, `tool.execution`, and `approval.requested` are in SDK schema, config publish levels, and active publishers.
2. `file.change` is absent everywhere as a standalone kind.
3. `provider.response.tool_calls` is removed.
4. Browser approval works from `approval.requested` cards through the existing `/actions` endpoint.
5. The UI plan lists the real kind set and metadata shapes.
6. Invariant tests prevent future schema/config drift.

## Developer prompt

Implement the task-controls / execution-audit change set as one atomic contract update.

Rules:

- Reuse existing interfaces. Modify `ConversationEvent`, `ExecutionEventSink`, `RunResult`, and the existing `/v1/conversations/{id}/actions` surface. Do not add a second registry client, second sink, second approval API, or standalone `file.change` kind.
- The final event taxonomy must be exactly:
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
- `file.change` must remain absent. File changes, if present, belong inside `tool.execution.file_changes[]`.
- If `tool.execution` is added, remove `tool_calls` from `provider.response` in the same change. Do not leave both representations alive.
- `approval.requested` must be published from the existing pending-approval workflow, not from Telegram-only UI code.
- Browser approvals must reuse the existing conversation action route. No new approval endpoint.
- All timestamps and event IDs must be explicit. No SDK-generated or adapter-generated hidden defaults.
- Add invariant tests so `PUBLISH_LEVEL_KINDS` cannot drift from `EVENT_METADATA_SCHEMAS`.
- Update code, tests, and plan/docs in the same change set. Do not land schema-only or UI-only partial work.

Required files likely include:

- `registry_sdk/events.py`
- `registry_sdk/__init__.py`
- `registry_sdk/client.py`
- `app/config.py`
- `app/providers/base.py`
- `app/providers/claude.py`
- `app/providers/codex.py`
- `app/workflows/execution/event_sink.py`
- `app/workflows/execution/requests.py`
- `app/workflows/pending/requests.py`
- `app/agents/delivery.py`
- `ui/js/components/conversation-detail.js`
- `PLAN-ui-redesign.md`
- focused SDK / config / execution / registry / browser tests

Do not preserve legacy shapes “just in case”. The target state is one contract, one publisher path, one UI meaning per kind.
