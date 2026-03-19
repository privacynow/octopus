# Orchestration Inventory

Last updated: 2026-03-18

This document is the committed orchestration inventory required by
`store_plan.md` Track F / F1.

Classification vocabulary is fixed. Every concern below is classified as exactly
one of:

- `explicit machine required`
- `procedural workflow acceptable`
- `misplaced orchestration that must move`

This file is the gating reference for Track F / F2-F6.

## Repo-Wide Rule

Durable or replay-sensitive transition systems must end in one concern-owned
workflow package under `app/workflows/*`.

`runtime/*`, `agents/*`, and channel packages may bridge I/O and persistence
handoff, but they do not own durable business transitions.

## Channel Entry Boundaries

Channel bootstrap and ingress ownership are intentionally not classified as
workflow orchestration concerns in this inventory.

Current Telegram boundary:

- `app/channels/telegram/bootstrap.py` owns PTB application construction and
  route registration
- `app/channels/telegram/ingress.py` owns normalized event translation and
  handler dispatch
- `app/channels/telegram/worker.py` and
  `app/channels/telegram/shared_mode_dispatch.py` are channel-local support
  modules, not durable workflow owners

Those modules are channel entrypoint owners, not durable workflow owners. This
inventory covers the concern-owned orchestration packages they call into.

## Inventory

### 1. Lifecycle

- Concern: runtime-skill and provider-guidance lifecycle transitions
- Current owners:
  - `app/workflows/lifecycle_machine.py`
  - `app/workflows/runtime_skills/authoring.py`
  - `app/workflows/runtime_skills/approval.py`
  - `app/workflows/provider_guidance/management.py`
- Current style: functional decision machine plus procedural workflow consumers
- Classification: `explicit machine required`
- Authoritative destination:
  - keep the decision machine in `app/workflows/lifecycle_machine.py`
  - keep lifecycle-specific orchestration in the runtime-skill and provider-guidance workflow packages
- Why:
  - transitions are durable
  - replay and partial-repair behavior is required
  - atomic application is already enforced at the store boundary
- Follow-on owner: no relocation required; this concern is the repo’s standard example for F2

### 2. Pending Approval / Retry

- Concern: pending approval and pending retry state transitions
- Current owners:
  - `app/workflows/pending/machine.py`
  - `app/workflows/pending/requests.py`
- Current style: functional decision machine plus procedural workflow consumer
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/pending/machine.py`
  - `app/workflows/pending/requests.py`
- Why:
  - the state is durable and replay-sensitive
  - transition legality is already explicit
  - the concern now follows the repo-standard machine style under a concern-owned package
- Follow-on owner: Track F / F5 complete

### 3. Transport Recovery

- Concern: queue claim, stale recovery, replay reclaim, discard, and supersede transitions
- Current owners:
  - `app/workflows/recovery/machine.py`
  - `app/workflows/recovery/results.py`
  - `app/workflows/recovery/transport_contract.py`
  - `app/work_queue*.py` consumers
- Current style: functional decision machine with concern-owned result/contract helpers
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/recovery/machine.py`
  - `app/workflows/recovery/results.py`
  - `app/workflows/recovery/transport_contract.py`
- Why:
  - queue/recovery is a durable transition system
  - replay and stale-claim semantics are first-class runtime contracts
  - the concern now owns its machine, result, and contract types together
- Follow-on owner: Track F / F5 complete

### 4. Credential / Setup Progression

- Concern: `awaiting_skill_setup` lifecycle, foreign-setup detection, requirement progression, ready/cancel/clear
- Current owners:
  - `app/workflows/runtime_skills/setup_machine.py`
  - `app/workflows/runtime_skills/setup.py`
  - `app/credential_flow.py` for rendering helpers only
- Current style: functional decision machine plus workflow consumer
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/runtime_skills/setup_machine.py`
  - `app/workflows/runtime_skills/setup.py` as the consumer/orchestrator only
- Why:
  - the state is conversational and durable in session storage
  - the concern previously had split ownership over `session.awaiting_skill_setup`
  - cancellation, foreign-setup, completion, and credential-clear semantics need one authoritative transition owner
- Follow-on owner: Track F / F3 complete
- Resolved split owners removed by F3:
  - `app/credential_flow.py` no longer owns setup-state transitions

### 5. Delegation Progression

- Concern: parent delegation-plan state, child routed-task state, cancel/approve/result-application/resume-readiness
- Current owners:
  - `app/workflows/delegation/machine.py`
  - `app/workflows/delegation/coordination.py`
  - `app/workflows/delegation/contracts.py`
  - `app/agents/delegation.py` thin bridge
  - `app/agents/delivery.py` thin bridge
  - `app/session_state.py` delegated-task and pending-delegation records
- Current style: functional decision machine plus thin bridge adapters
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/delegation/machine.py`
  - `app/workflows/delegation/coordination.py`
  - `app/workflows/delegation/contracts.py`
- Why:
  - parent and child states are durable and multi-step
  - the durable state inventory is now explicit in the delegation machine
  - result application and resume readiness are workflow concerns, not agent-bridge concerns
- Follow-on owner: Track F / F4 complete

### 6. Request Execution / Preflight

- Concern: execution admission, preflight, pending-approval creation, provider run orchestration, reply/result shaping
- Current owners:
  - `app/runtime/dispatch.py`
  - `app/workflows/execution/contracts.py`
  - `app/workflows/execution/requests.py`
  - `app/workflows/execution/finalization.py`
  - `app/request_flow.py`
  - `app/approvals.py` as helper policy/approval logic
- Current style:
  - `app/runtime/dispatch.py` is channel-agnostic provider-call plumbing
  - `app/workflows/execution/requests.py` is the concern-owned execution workflow
  - `app/workflows/execution/finalization.py` owns post-execution result/reporting orchestration
  - `app/request_flow.py` remains a procedural helper module
- Classification: `procedural workflow acceptable`
- Authoritative destination:
  - `app/runtime/dispatch.py` remains only queue-claim to provider-run plumbing
  - `app/workflows/execution/*` remains the execution/preflight workflow owner
- Why:
  - runtime no longer owns business workflows
  - execution/preflight orchestration now lives under a concern-owned workflow package
  - post-execution finalization no longer lives in Telegram worker code
  - the remaining request-flow helpers are acceptable procedural workflow code
- Follow-on owner: Track F / F6 complete

## Acceptable Procedural Workflow Notes

The concerns above are the durable or semi-durable orchestration systems that
must be inventoried before F2-F6.

Not every workflow in the repo needs to become a machine. The following remain
procedural-workflow acceptable unless later evidence says otherwise:

- `app/request_flow.py` as a pure validation/helper module
- catalog reads and preview builders
- straightforward credential management mutations that do not own a durable progression
- presentation-only channel adapters

Those are not exemptions for the six concerns above. They are just the current
boundary of where a machine is required versus where a procedural workflow is
acceptable.
