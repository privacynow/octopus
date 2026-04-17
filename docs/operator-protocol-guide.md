# Protocol Operator Guide

This guide is for operators, team leads, and compliance reviewers using
protocols from the registry UI or Telegram.

## Who Uses Protocols

- Platform operator: use protocols when work needs a durable, auditable,
  multi-stage workflow instead of a one-off conversation.
- Team lead: use protocols when you want predictable stage sequencing,
  review loops, and visible progress against a problem statement.
- Compliance reviewer: use protocols when you need exportable run history,
  intervention reasons, artifact metadata, and role-gated access.
- Bot developer: use protocols when you need to verify how a shared workflow
  behaves across the registry, Telegram, and routed-task runtime.

Normal conversations are still the right tool for ad hoc work. Protocols are
for repeatable workflows where stage order, artifacts, review decisions, and
operator intervention must be explicit.

## Starting A Run

From the registry UI:

1. open `Protocols`
2. choose a published definition
3. pick the target bot
4. provide workspace and problem statement
5. start the run

From Telegram:

```text
/protocol list
/protocol start <slug> <problem statement>
```

Telegram automatically watches runs it starts. Operators can also enable or
disable run notifications explicitly:

```text
/protocol watch <run_id>
/protocol unwatch <run_id>
```

## Reading Run State

Every run has the same canonical state across the registry UI, Telegram, and
the API:

- `queued`
- `running`
- `blocked`
- `completed`
- `failed`
- `cancelled`

Important fields:

- `current stage`: the active stage key
- `version`: optimistic concurrency token for operator actions
- `blocked detail`: the actionable reason when the run is blocked
- `participants`: who the current and past stages resolved to
- `artifacts`: current artifact manifest, hashes, and verification state
- `transitions`: append-only lifecycle history

## Support Issues And Admin Views

The registry exposes protocol issue views for:

- blocked runs
- invalid protocol contracts
- expired timeouts
- stuck leases

Use `Dashboard` for summary-level issue detection and `Protocols` for run-level
detail, transitions, participants, and artifacts.

## Operator Actions

Typed operator actions are:

- `retry`
- `accept`
- `send-back`
- `cancel`

Rules:

- actions are versioned and concurrency-checked
- `retry` is allowed only from blocked, failed, or cancelled stage executions
- `send-back` and `cancel` require a short reason
- Telegram requires explicit confirmation for destructive actions
- every action is recorded in the audit trail

Registry UI and Telegram both use the same backend action contract. If an
action returns a version conflict, refresh and review the current run state
before retrying.

## Metrics

The registry summary and dashboard expose protocol metrics from the same
control-plane source:

- `runs_started_24h`: runs created in the last 24 hours
- `runs_completed_24h`: runs that reached `completed` in the last 24 hours
- `runs_blocked_24h`: runs that entered `blocked` in the last 24 hours
- `completion_rate_24h`: completed / started over the last 24 hours
- `blocked_rate_24h`: blocked / started over the last 24 hours
- `intervention_rate_24h`: operator actions / started over the last 24 hours
- `operator_interventions_24h`: count of operator actions in the last 24 hours
- `mean_completion_seconds_24h`: mean run duration for completed runs
- `mean_stage_executions_per_terminal_run_24h`: average number of stage
  executions for terminal runs
- `mean_review_revisions_per_terminal_run_24h`: average number of `revise`
  decisions for terminal runs

Use these to answer:

- are runs finishing?
- are review loops healthy or oscillating?
- are operators intervening too often?
- are timeouts or blocked runs rising?

## Security, Visibility, Export, And Retention

Protocol definitions and runs are org-scoped by default.

- `org_private`: only the owning org can read
- `org_shared`: readable inside the owning org
- `registry_template`: cross-org readable only when the deployment enables it

Exports are allowed only for:

- `operator`
- `auditor`
- `admin`

Protocol exports include:

- definition metadata and version
- run state
- participant resolution
- artifact metadata and hashes
- transitions

They do not expose artifact file contents.

Default retention is 90 days unless deployment policy overrides it.

## Runbook

Use these first responses:

- `protocol_contract_invalid`: inspect the stage result and contract lines,
  then `retry` or `send-back`
- `artifact_missing` / `artifact_integrity_failed`: inspect artifact metadata,
  workspace path, and hash-producing stage output before retrying
- `participant_resolution_failed`: inspect participant selector, required
  skills, and connected agents
- `lease_held`: inspect the conflicting running write stage or stuck lease issue
- `stage_timeout`: inspect the stage timeout, worker health, and routed-task
  outcome
- `max_review_rounds_exceeded`: inspect review feedback quality and decide
  whether to `accept`, `send-back`, or end the run

## OpenAPI And API Consumers

The generated registry OpenAPI artifact is checked in at:

- [docs/registry-openapi.json](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-openapi.json)

That artifact is generated from the FastAPI registry app and locked by tests so
client integrations can rely on a checked-in contract, not only the live
endpoint.
