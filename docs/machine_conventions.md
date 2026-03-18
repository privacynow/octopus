# Machine Conventions

Last updated: 2026-03-18

This document defines the repo-standard explicit machine style required by
`store_plan.md` Track F / F2.

## Standard

The standard explicit machine style for this repo is the **functional
decision-machine** shape already used by `app/workflows/lifecycle_machine.py`.

The standard shape is:

- `snapshot`
- `action`
- `decision`
- `effects`
- atomic application at the store or session boundary

`python-statemachine` remains migration-state only for not-yet-migrated
machines. It is not the long-term standard.

## Module Shape

A concern-owned machine module should normally provide:

- typed snapshot dataclass or equivalent immutable state view
- typed action enum or literal union
- typed effects dataclass
- typed decision dataclass with stable `status` and `ok` fields
- pure decision function such as `decide_<concern>_action(snapshot, action)`

The machine module itself does not:

- mutate sessions directly
- write the database directly
- send messages
- branch on channel type
- perform I/O

Application of effects happens in the owning workflow or store/session boundary.

## Required Semantics

Every repo-standard machine must satisfy these rules:

1. The decision function is pure for a given snapshot and action.
2. The decision result uses stable status strings that are safe for replay and idempotency.
3. Effects are explicit; hidden side effects are not allowed.
4. Durable multi-field transitions are applied atomically at the store boundary.
5. Session-state transitions are applied through one owning workflow boundary.
6. Invalid transitions return explicit machine outcomes rather than mutating partially.
7. Repair/replay decisions are first-class, not ad hoc special cases.

## Status Guidance

Decision statuses must be:

- stable across retries
- explicit enough for callers to distinguish success, duplicate, repair, and invalid cases
- suitable for external tests to assert without inspecting internals

Preferred categories:

- success state: `submitted`, `approved`, `published`, `archived`
- duplicate/idempotent state: `already_submitted`, `already_approved`, `already_published`
- repair state: same terminal outcome with effects that complete the interrupted work
- invalid state: `invalid_state`, `approval_required`, `blocked_replay`, or another concern-specific explicit status

## Allowed and Disallowed Patterns

Allowed:

- functional decision machine in `app/workflows/<concern>/machine.py`
- workflow module consumes machine decisions and applies effects
- store boundary applies durable effects atomically
- machine tests that exercise happy, duplicate, repair, and invalid paths

Disallowed:

- callback-driven mutable machines as a new standard
- introducing a third explicit machine style
- long-term coexistence of `python-statemachine` and functional machines as equal standards
- channel-specific rendering or transport logic inside a machine
- machines that reach into sibling workflow private helpers

## Migration Rule

Existing `python-statemachine` usages are migration-state only:

- `app/workflows/pending_request.py`
- `app/workflows/transport_recovery.py`

They remain valid only until the owning concern is migrated under Track F / F5.

No new `python-statemachine` machine may be added.

## Minimum Test Bar

Every new or migrated machine must add tests for:

- happy path
- duplicate or replay path
- interruption or repair path
- invalid transition or rejection path

If the concern is durable, the workflow or store tests must also prove:

- atomic effect application
- idempotent replay behavior
- no partial durable state after failure

## Completion Rule

A machine migration is not complete just because code moved files.

It is complete only when:

- the concern uses the functional decision-machine style
- the old machine path is deleted
- the owning workflow applies effects at one boundary
- the full suite and the concern-specific machine tests pass
