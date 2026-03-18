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
  - `app/workflows/pending_request.py`
  - `app/workflows/pending/requests.py`
- Current style: `python-statemachine` machine plus procedural workflow consumer
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/pending/machine.py`
  - `app/workflows/pending/requests.py`
- Why:
  - the state is durable and replay-sensitive
  - transition legality is already explicit
  - the problem is package placement and machine-style inconsistency, not whether a machine is needed
- Follow-on owner: Track F / F5

### 3. Transport Recovery

- Concern: queue claim, stale recovery, replay reclaim, discard, and supersede transitions
- Current owners:
  - `app/workflows/transport_recovery.py`
  - `app/workflows/results.py`
  - `app/transport_contract.py`
  - `app/work_queue*.py` consumers
- Current style: `python-statemachine` machine plus result/contract helpers outside the owning concern package
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/recovery/machine.py`
  - `app/workflows/recovery/results.py`
  - `app/workflows/recovery/transport_contract.py`
- Why:
  - queue/recovery is a durable transition system
  - replay and stale-claim semantics are first-class runtime contracts
  - current ownership is split across root modules and a legacy-named contract file
- Follow-on owner: Track F / F5

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
- Follow-on owner: Track F / F3
- Resolved split owners removed by F3:
  - `app/skill_lifecycle_service.py`
  - `app/credential_flow.py` no longer owns setup-state transitions

### 5. Delegation Progression

- Concern: parent delegation-plan state, child routed-task state, cancel/approve/result-application/resume-readiness
- Current owners:
  - `app/agents/orchestration.py`
  - `app/agents/delegation.py`
  - `app/session_state.py` delegated-task and pending-delegation records
- Current style: procedural orchestration with scattered direct status-string edits
- Classification: `explicit machine required`
- Authoritative destination:
  - `app/workflows/delegation/machine.py`
  - `app/workflows/delegation/coordination.py`
  - `app/workflows/delegation/contracts.py`
- Why:
  - parent and child states are durable and multi-step
  - there is an explicit active-state inventory already in `app/agents/orchestration.py`
  - result application and resume readiness are workflow concerns, not agent-bridge concerns
- Follow-on owner: Track F / F4

### 6. Request Execution / Preflight

- Concern: execution admission, preflight, pending-approval creation, provider run orchestration, reply/result shaping
- Current owners:
  - `app/runtime/dispatch.py`
  - `app/request_flow.py`
  - `app/approvals.py`
  - `app/provider_guidance_service.py` preflight/run-context builders
- Current style:
  - `app/request_flow.py` is a procedural workflow helper and is acceptable
  - `app/runtime/dispatch.py` still mixes runtime plumbing with workflow decisions
- Classification: `misplaced orchestration that must move`
- Authoritative destination:
  - business and durable decision logic moves to a concern-owned workflow package such as `app/workflows/execution/*`
  - `app/runtime/dispatch.py` remains only queue-claim to provider-run plumbing
- Why:
  - runtime should not own business workflows
  - the concern currently spans pure helpers and a too-fat runtime orchestrator
  - Track A removed channel imports, but ownership is still not clean
- Follow-on owner: Track F / F6

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
