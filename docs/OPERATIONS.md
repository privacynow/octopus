# Operations Guide

This guide is for people who operate an Octopus environment: checking health,
preparing a demo or evaluation, restarting services, and debugging product
behavior through supported surfaces.

If you are installing Octopus for the first time, start with
[GETTING_STARTED.md](GETTING_STARTED.md). For everyday browser use, start with
[USER_GUIDE.md](USER_GUIDE.md). For workflow design, use
[PROTOCOLS.md](PROTOCOLS.md).

## Operating Goal

A ready Octopus environment should let a user:

1. start the stack
2. open the Registry
3. verify agent health
4. use a conversation
5. run or author a protocol
6. inspect stages, work, artifacts, and audit history
7. open or download produced artifacts
8. repeat the path without private database edits

## Environment Assumptions

- Docker Desktop is running.
- Git is installed.
- At least one Telegram-backed local agent is configured and started.
- Provider authentication is configured for at least one execution agent that
  will perform model-backed work.
- Telegram chat usage is optional unless that channel is part of the evaluation.
- The default local Registry URL is `http://127.0.0.1:8787/ui`.

Plain-language setup details for Docker Desktop, Windows WSL2, model provider
login, and first-run agent creation live in
[GETTING_STARTED.md](GETTING_STARTED.md). Keep this operations guide focused on
running and validating an environment that already exists.

## Start And Verify

From the repository root:

```bash
./octopus
./octopus status
```

Expected healthy state:

- registry is running
- at least one configured bot is running
- target agent is connected
- target agent is execution-healthy
- Registry opens in a browser

If an optional provider-backed bot is disconnected because credentials are not
configured, exclude that bot from the ready path.

Provider auth means the agent can use its configured model provider, such as
Codex or Claude. If `./octopus status` says a provider is not configured, use:

```text
./octopus
Diagnose -> Provider auth
```

Authenticate only the provider you intend to use for the ready path.

## Common Commands

```bash
./octopus
./octopus status
./octopus start registry
./octopus start bots
./octopus restart bots
./octopus connect m1
./octopus logs m1 --follow
./octopus shell m1
./octopus doctor m1
./octopus clean
```

For non-technical users, `./octopus status` is the safest command to ask for:
it reports what is running without changing the environment.

Use logs for monitoring active work. Avoid waiting blindly when a run is in
progress; watch the relevant registry run, container logs, and health state.

## Registry Orientation

Show the three product areas:

| Area | Entries | Purpose |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Active collaboration, protocol execution, artifacts, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow authoring and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Operational state, routing diagnostics, and usage visibility. |

Tasks and approvals are valid linked/internal surfaces, but they are not the
primary customer navigation path.

## Smoke Test

Use this path before a customer demo or product evaluation:

1. Run `./octopus status`.
2. Open the Registry URL.
3. Confirm `Work -> Agents` has one connected execution-healthy agent.
4. Open `Work -> Conversations`.
5. Send a short, non-sensitive request.
6. Confirm a response appears.
7. Open `Build -> Protocols`.
8. Select or create a simple protocol.
9. Validate and publish if needed.
10. Start a run.
11. Inspect `Work -> Runs`.
12. Open or download every customer-relevant artifact.

The standard authoring surface should show title, instructions, assignment,
artifacts, routing, validation, and run feedback. It should not expose raw
runtime internals to standard authors.

## Run Inspection

For a protocol run, inspect:

- `Overview`: status, protocol, stage, workspace, entry agent, actions
- `Stages`: stage status, assignment, inputs, outputs, linked work
- `Artifacts`: declared and produced artifacts with available actions
- `Audit`: launch context, transitions, decisions, and operator actions

The user should be able to understand what ran, who executed each stage, which
files were expected, which files were produced, and what remains blocked.

## Artifact Handoff

For every customer-relevant artifact:

1. Open or preview it from the run.
2. Retain the package when the artifact matters beyond the live workspace.
3. Download it if the customer needs a local copy.
4. Confirm the content matches the declared output.
5. Confirm missing artifacts are labeled as missing.
6. Confirm artifact actions appear wherever the artifact is linked.
7. For runnable artifacts, start the app, open the Registry-routed URL, exercise
   the primary UI/API path, inspect health/logs if available, and stop the
   runtime when evaluation is complete.
8. Export the run when audit handoff matters; runtime instances and runtime
   events are included in the run export alongside stages, artifacts, tasks, and
   transitions.

If a produced artifact cannot be previewed, opened, downloaded, or located from
the customer-facing surface where it appears, record that as a product issue.

## Telegram Parity

Only include Telegram chat checks when the evaluation needs that surface. The
underlying local agent may still be Telegram-backed even when users operate
through the browser Registry.

Useful protocol commands:

```text
/protocol list
/protocol recent
/protocol start <slug> <problem statement>
/protocol status latest
/protocol artifacts latest
/protocol preview latest 1
/protocol artifacts latest download 1
/protocol export latest
```

Telegram and Registry should describe the same run state and artifact set. If
they disagree, treat that as a product issue.

## Troubleshooting Runbook

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
- assignment and participant resolution
- provider execution fault state
- stuck lease or timeout issue

Common issue responses:

| Issue | Response |
| --- | --- |
| `artifact_missing` | Inspect producing stage output and artifact metadata. |
| `artifact_integrity_failed` | Inspect hash, path, and verification. |
| `participant_resolution_failed` | Inspect stage assignment and connected agents. |
| `lease_held` | Inspect active or stale work lease. |
| `stage_timeout` | Inspect worker health and provider result. |
| `max_review_rounds_exceeded` | Decide whether to accept, send back, or cancel. |

## Cleanup

For a reusable demo environment:

1. Use documented product controls.
2. Preserve agents, credentials, skills, guidance, and tokens unless the goal is
   a full teardown.
3. Do not clean a customer environment without an explicit operator decision.

Runnable artifact processes have explicit runtime limits. The bot runtime reaps
expired local processes, and Registry maintenance records expired runtime state
and events so operators can see what happened. Prefer `Stop app`, `Archive`, or
`Delete` from the run artifact controls before using broader workspace cleanup.

The Dashboard workspace cleanup control is the product-safe cleanup path. It
performs a dry run through the connected bot, reports candidate paths and byte
counts, then deletes only approved transient categories after confirmation.
Use the older workspace-data reset only for intentional demo resets; it removes
Registry work records while preserving agents, skills, guidance, credentials,
and tokens.

Run archive/delete is separate from workspace cleanup. Archive hides completed
or failed runs from normal views while preserving audit and retained packages.
Delete is a soft-delete retention action and requires explicit confirmation.

## What To Avoid

- Do not use real private data in a demo unless the deployment and customer
  explicitly allow it.
- Do not paste raw confidential rows or transcripts into run prompts.
- Do not present rehearsal as provider-backed execution.
- Do not present a generated artifact as repository documentation.
- Do not hide missing artifacts, broken downloads, stale run state, or provider
  faults.
- Do not make a scenario-specific behavior sound like a product default.
- Do not use direct database writes as customer acceptance evidence.

## OpenAPI

The generated registry OpenAPI artifact is checked in at:

- [registry-openapi.json](registry-openapi.json)

The README links the same artifact as
[docs/registry-openapi.json](registry-openapi.json).
Update the artifact when registry route contracts change.

## Ready Checklist

- `./octopus status` is healthy for the demo path
- Registry opens at the expected URL
- at least one conversation smoke test succeeds
- a protocol can be selected or created, validated, published, and run
- run detail shows useful overview, stages, artifacts, and audit context
- produced artifacts can be opened or downloaded
- optional Telegram commands match Registry state
- scenario-specific instructions are confined to the relevant example guide
