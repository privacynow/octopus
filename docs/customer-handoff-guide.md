# Customer Handoff Guide

This guide is built from tested product paths. Do not add a step here unless it
has been exercised from a customer-facing surface: Registry UI, Telegram,
Octopus CLI, or a documented command.

Current status: in progress. Use this guide as the working handoff script while
the remaining blockers in `issues.md` are being closed.

## Handoff Goal

A customer should be able to:

1. clone the repository,
2. start Octopus,
3. verify healthy agents,
4. create or use a protocol from the UI,
5. execute work,
6. inspect the run,
7. open or download artifacts,
8. repeat the local manufacturing analytics workflow without uploading raw CSV
   rows to a model provider.

## Environment Assumptions

- Docker Desktop is running.
- Git is installed.
- The customer has model/provider credentials for at least one Codex-backed bot.
- Claude/M3 is optional unless explicitly configured.
- Default Registry URL: `http://127.0.0.1:8787/ui`.

## Verified Paths

Record each verified path below as the product is exercised.

### Registry Health

Status: not yet verified from a clean clone.

Planned steps:

1. Run `./octopus status`.
2. Open `http://127.0.0.1:8787/ui`.
3. Confirm Registry is running.
4. Confirm M1 and M2 are connected and execution-healthy.
5. Confirm M3 is either healthy or clearly optional/not configured.

### New Conversation

Status: not yet verified in this pass.

Planned steps:

1. Open Registry UI.
2. Go to `Work -> Conversations`.
3. Start a new conversation.
4. Send a simple message.
5. Confirm the response appears in the timeline.
6. Confirm linked work/events are visible when work is created.

### Skills

Status: not yet verified in this pass.

Planned steps:

1. Go to `Build -> Skills`.
2. Confirm generated/test skills are hidden by default.
3. Open a skill row.
4. Confirm real instructions are visible.
5. Start or open a conversation and activate a skill.

### Protocol Authoring

Status: not yet verified in this pass.

Planned steps:

1. Go to `Build -> Protocols`.
2. Create a blank protocol.
3. Add stages.
4. Confirm stage data is not lost while switching between stages and panels.
5. Create assignment variants:
   - no assignment,
   - skill only,
   - agent only,
   - skill plus preferred agent,
   - needed new skill.
6. Declare input/output artifacts.
7. Publish.
8. Start a run.

### Run And Artifact Inspection

Status: not yet verified in this pass.

Planned steps:

1. Open `Work -> Runs`.
2. Select the run.
3. Use Overview.
4. Use Stages.
5. Use Artifacts.
6. Preview a text artifact.
7. Open or download a produced artifact.
8. Copy an artifact path.
9. Confirm declared-but-missing artifacts show a clear unavailable state.

### Telegram Protocol Use

Status: not yet verified in this pass.

Planned steps:

1. Send `/protocol list`.
2. Start a protocol with `/protocol start <slug> <problem statement>`.
3. Inspect with `/protocol status <run_id>`.
4. Inspect artifacts with `/protocol artifacts <run_id>`.
5. Open the Registry run link.
6. Confirm Telegram and Registry show the same run state and artifacts.

### Local Manufacturing Analytics

Status: not yet verified through the full UI flow in this pass.

Planned steps:

1. Start from `Build -> Protocols`.
2. Create or use the local manufacturing analytics workflow.
3. Provide schema, keys, and privacy constraints through the UI.
4. Run the protocol.
5. Open the generated local tool artifact.
6. Generate synthetic data in that tool.
7. Confirm aggregate findings are visible.
8. Download or copy the report output.

## Known Handoff Blockers

See `issues.md` for the active blocker list. Do not hand this repository to a
customer as self-service until the blockers are closed or explicitly marked
non-blocking with customer-facing workarounds.
