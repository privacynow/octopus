# Customer Handoff Guide

This is the generic handoff checklist for a customer-facing Octopus demo or
evaluation. It is built from supported product surfaces: Registry UI, Telegram,
the Octopus CLI, and documented commands.

This guide is repository documentation. Do not ask a customer protocol run to
generate or update this file. A protocol run should produce the customer's own
working artifacts, such as app files, local READMEs, validation reports, and
analysis outputs.

Scenario-specific walkthroughs belong in separate guides. For the verified
offline CSV analytics SPA scenario, use
[local-data-analytics-demo.md](local-data-analytics-demo.md).

## Handoff Goal

A customer should be able to:

1. clone the repository
2. start Octopus
3. verify registry and agent health
4. use the browser registry
5. create or run a protocol
6. inspect stages, work, and artifacts
7. open or download produced artifacts
8. repeat the workflow without hidden setup or private database edits

## Environment Assumptions

- Docker Desktop is running.
- Git is installed.
- Provider authentication is configured for at least one execution agent.
- Telegram is optional unless the demo includes Telegram commands.
- The default local Registry URL is `http://127.0.0.1:8787/ui`.

## Start And Verify

From the repository root:

```bash
./octopus
./octopus status
```

Expected healthy state:

- registry is running
- at least one configured bot is running
- the target agent is connected
- the target agent is execution-healthy
- the registry URL opens in a browser

If an optional provider-backed bot is disconnected because credentials are not
configured, do not include that bot in the customer-ready path.

## Registry Orientation

Open the Registry UI and show the three product areas:

| Area | Entries | Purpose |
| --- | --- | --- |
| Work | Conversations, Runs, Agents | Active collaboration, protocol execution, and agent health. |
| Build | Protocols, Skills, Guidance | Reusable workflow authoring and runtime capability management. |
| Operations | Dashboard, Routing, Usage | Operational state, routing diagnostics, and usage visibility. |

Tasks and approvals are still valid linked/internal surfaces, but they are not
the primary customer navigation path.

## Conversation Smoke Test

Use this to verify basic agent execution before demonstrating protocols:

1. Open `Work -> Conversations`.
2. Start a new conversation with an execution-healthy agent.
3. Send a short, non-sensitive request.
4. Confirm a response appears in the conversation timeline.
5. Open activity or linked work if present and confirm start/finish events are
   visible.

If direct assignment is part of the demo:

1. Use an `@agent` target from the conversation composer.
2. Confirm the composer switches to assignment mode.
3. Send the assignment.
4. Confirm linked work is assigned to the targeted agent and completes.

## Protocol Authoring Smoke Test

Use this to verify the current blank-authoring path:

1. Open `Build -> Protocols`.
2. Click `New protocol`.
3. Choose `Start blank`.
4. Name the protocol.
5. Add declared artifacts.
6. Add stages in order.
7. Configure each stage assignment.
8. Attach stage inputs and outputs.
9. Configure transitions.
10. Click `Validate`.
11. Confirm the validation succeeds.
12. Click `Publish`.
13. Confirm the protocol state changes to `PUBLISHED`.
14. Confirm `Run protocol` is available.

The standard authoring surface should show title, instructions, assignment,
artifacts, routing, validation, and run feedback. It should not expose raw
runtime internals to standard authors.

## Run Launch Smoke Test

From a published protocol:

1. Click `Run protocol`.
2. Select an execution-healthy entry agent.
3. Fill the generic launch form:
   `Workspace`, goal, context, constraints, and expected outputs.
4. Check for expected-output warnings.
5. Fix artifact declarations if the warning reveals a real contract mismatch.
6. Start the run.
7. Confirm the browser opens or links to `Work -> Runs`.

Protocol authors can define custom `metadata.run_inputs` for specialized
workflows. When no custom inputs are defined, the product should stay generic.

## Run Inspection

Open the run in:

```text
Work -> Runs
```

Review:

- `Overview`: status, protocol, stage, workspace, entry agent, actions.
- `Stages`: stage status, assignment, inputs, outputs, linked work.
- `Artifacts`: declared and produced artifacts with available actions.
- `Audit`: transitions and operator actions.

The customer should be able to answer what ran, who/what executed each stage,
which files were expected, which files were produced, and where to open or
download them.

## Artifact Handoff

For every customer-relevant artifact:

1. Open or preview it from the run.
2. Download it if the customer needs a local copy.
3. Confirm the file content matches the declared output.
4. Confirm missing artifacts are shown as missing rather than broken buttons.
5. Confirm artifact actions are available from the relevant run/stage/work
   context.

If a produced artifact cannot be previewed, opened, downloaded, or located from
the customer-facing surface where it appears, record that as a product issue.

## Telegram Parity

Only include Telegram when the environment is configured for it.

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
they disagree, treat that as a product issue rather than a demo caveat.

## Cleanup

For a reusable demo environment, use documented product controls:

1. Open `Operations -> Dashboard`.
2. Use workspace maintenance only when intentionally resetting a demo
   environment.
3. Preserve agents, credentials, skills, guidance, and tokens unless the
   explicit goal is a full teardown.

Do not clean a customer environment without a clear operator decision.

## What To Avoid

- Do not use real private data in a demo unless the deployment and customer
  explicitly allow it.
- Do not paste raw confidential rows or transcripts into run prompts.
- Do not present rehearsal as provider-backed execution.
- Do not present a generated artifact as if it were repository documentation.
- Do not hide missing artifacts, broken downloads, stale run state, or provider
  execution faults.
- Do not make a scenario-specific behavior sound like a product default.

## Handoff Completion Checklist

The handoff is ready when:

- `./octopus status` is healthy for the demo path
- Registry opens at the expected URL
- at least one conversation smoke test succeeds
- a protocol can be created or selected, validated, published, and run
- run detail shows useful overview, stages, artifacts, and audit context
- produced artifacts can be opened or downloaded
- optional Telegram commands match Registry state
- any scenario-specific instructions are confined to that scenario guide
