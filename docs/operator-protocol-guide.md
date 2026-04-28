# Protocol Operator Guide

This guide is for operators, team leads, and reviewers inspecting or
intervening in protocol runs.

Protocols are for repeatable work where stage order, artifacts, review
decisions, and intervention history matter. Normal conversations are still the
right surface for ad hoc work.

## Starting A Run

From the registry UI:

1. open `Protocols`
2. choose a published protocol
3. start a run with the required problem/workspace context
4. inspect the run from `Runs`

From Telegram:

```text
/protocol list
/protocol start <slug> <problem statement>
```

Telegram automatically watches runs it starts.

## Reading Runs

Open:

```text
Work -> Runs
```

Run detail should be read through:

- Overview
- Stages
- Artifacts
- Audit

Expected questions:

- what protocol/version is running?
- what stage is active?
- what routed work/task records were created?
- what artifacts were declared?
- what artifacts were produced?
- what approvals or decisions are pending?
- is the run running, blocked, stale, failed, completed, or canceled?

## Runs And Routed Work

Protocol stage execution currently uses routed tasks as the execution
substrate.

Product interpretation:

- a protocol Run is the workflow execution
- a Stage Execution is one step in that run
- a routed Task is the executable work item created for a stage

The UI should show this as lineage, not as unrelated concepts. If operators
must jump between unrelated pages to understand one run, that is a UX gap.

## Operator Actions

Supported protocol actions:

- `retry`
- `accept`
- `send-back`
- `cancel`

Rules:

- actions are permission-gated
- actions are version/concurrency checked
- reasons are required for destructive or corrective actions where applicable
- every action is recorded in run/audit history
- Telegram may require explicit confirmation

Actions should appear in context. If global run buttons are unclear or look
available when they are not meaningful, the UI should be fixed rather than
documenting confusion as normal behavior.

## Artifacts

Operators should be able to inspect produced artifacts from:

- run overview
- run artifacts
- stage detail
- linked routed work/task
- conversation context
- Telegram artifact commands

Artifact states:

- declared but not produced yet
- available
- unavailable on this host
- expired/deleted

The intended action model is consistent preview/open/download/copy behavior
where the artifact is available. Missing action coverage is a product gap.

## Protocol Issues

The registry exposes protocol issue information for:

- blocked runs
- invalid contracts
- expired timeouts
- stuck leases
- missing artifacts
- participant/assignment resolution failures

Use Dashboard for summary-level detection and Runs/Protocols for detailed
inspection.

## Metrics

Registry summary paths expose protocol metrics such as:

- runs started
- runs completed
- blocked runs
- completion rate
- blocked rate
- intervention rate
- operator intervention count
- mean completion time
- stage execution counts
- review revision counts

Metrics should come from registry control-plane state, not browser-only
calculation.

## Security, Visibility, Export, And Retention

Exports are operator/auditor/admin functionality.

Protocol exports include:

- definition metadata and version
- run state
- participant/stage resolution
- artifact metadata and hashes
- transitions/actions/audit context

Exports should not expose artifact file contents unless explicitly requested
through artifact download/export functionality.

## Runbook

Start here:

```bash
./octopus status
./octopus doctor <bot>
./octopus logs <target> --follow
```

Then inspect:

- affected run
- active stage
- linked routed work/task
- artifact state
- assignment/participant resolution
- provider execution fault state
- stuck lease or timeout issue

Common issue responses:

- `artifact_missing`: inspect producing stage output and artifact metadata.
- `artifact_integrity_failed`: inspect hash/path/verification.
- `participant_resolution_failed`: inspect stage assignment and connected agents.
- `lease_held`: inspect active/stale work lease.
- `stage_timeout`: inspect worker health and provider result.
- `max_review_rounds_exceeded`: decide whether to accept, send back, or cancel.

## OpenAPI

The generated registry OpenAPI artifact is checked in at:

- [docs/registry-openapi.json](registry-openapi.json)

Update it when protocol route contracts change.
