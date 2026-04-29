# Customer Handoff Guide

This guide is built from tested product paths. Do not add a step here unless it
has been exercised from a customer-facing surface: Registry UI, Telegram,
Octopus CLI, or a documented command.

Current status: in progress. Use this guide as the working handoff script while
the remaining blockers in `issues.md` are being closed. Steps marked
`Verified` were exercised from a customer-facing UI surface, not by direct
database writes.

Current customer-ready entry point under test:

1. open `Operations -> Dashboard`,
2. use `Workspace maintenance -> Clean workspace data` only when resetting a
   demo environment,
3. open `Build -> Protocols`,
4. choose the local analytics starter,
5. review the starter workflow,
6. create an editable protocol,
7. publish and run it from the UI.

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

Status: partially verified on the deployed Octopus checkout.

Verified UI/CLI steps:

1. Run `./octopus status`.
2. Open `http://127.0.0.1:8787/ui`.
3. Confirm Registry is running.
4. Confirm M1 and M2 are connected and execution-healthy in the Dashboard.
5. Treat M3/Claude as optional unless Claude auth has been configured.

Observed result:

- Registry, M1, and M2 were running after redeploy.
- M1 and M2 were connected and execution-healthy.
- M3 was not part of the customer-ready path because Claude auth was not
  configured.

Remaining gap:

- This still needs one clean-clone verification pass from a fresh checkout.

### New Conversation

Status: verified in Registry UI.

Verified steps:

1. Open Registry UI.
2. Go to `Work -> Conversations`.
3. Click `Start a new conversation with M1`.
4. In the composer, enter:
   `Using the Documentation skill if available, give me a five bullet checklist for preparing a customer-safe local CSV analytics demo. Do not ask for or use real customer data.`
5. Send the message.
6. Open the conversation timeline.
7. Confirm the response appears in the Conversation tab.
8. Open `Full Activity` and confirm start/finish events are visible.

Observed result:

- M1 responded with a five-bullet checklist.
- The conversation timeline and activity stream both showed the work.

### Skills

Status: partially verified through conversation use; catalog audit still open.

Verified steps:

1. Go to `Work -> Conversations`.
2. Start a conversation with M1.
3. Ask for work using `Documentation skill` wording.
4. Confirm the response is generated and reflects the requested skill context.

Remaining catalog verification:

- Go to `Build -> Skills`.
- Confirm generated/test skills are hidden by default.
- Open a skill row and confirm the actual instructions are visible.
- Confirm the skills page remains readable with a large skill list.

### Agent Targeting

Status: verified in Registry UI.

Verified steps:

1. Open the M1 conversation created above.
2. In the composer, enter:
   `@m2 Reply with exactly: M2 route ok`
3. Confirm the composer switches from normal send to `Assign`.
4. Click `Assign`.
5. Open linked work from the conversation.
6. Confirm the task is assigned to M2.
7. Wait for completion.
8. Confirm the result is exactly `M2 route ok`.

Observed result:

- The request routed to M2.
- Linked work completed and returned the expected text.

### Protocol Authoring

Status: implementation updated; real Safari verification must be rerun after
redeploy.

Expected template flow:

1. Go to `Build -> Protocols`.
2. Click `New protocol`.
3. Confirm the starter chooser opens without generated timestamp test starters.
4. Find `Manufacturing Local Analytics`.
5. Click `Review customer startup`.
6. Confirm the review dialog shows stages and artifacts before creating
   anything.
7. Click `Create editable draft`.
8. Confirm a draft opens with seven stages:
   `Define Input Contract`, `Generate Profile Script`, `Run Profile Locally`,
   `Generate Analysis Script`, `Run Analysis Locally`, `Validate Outputs`, and
   `Review Report`.
9. Click `Validate`.
10. Confirm the toast says `Protocol validated.`
11. Click `Publish`.
12. Confirm state changes from `DRAFT` to `PUBLISHED`.
13. Confirm `Run protocol` appears.

Observed result:

- Earlier Safari runs created and published a Manufacturing Local Analytics
  draft from the UI.
- The flow has since changed from one-click `Use template` to review-before-
  create, so acceptance must be rerun.

Remaining authoring verification:

- Blank protocol creation still needs a full pass for add/remove/reorder and
  assignment variants: no assignment, skill only, agent only, skill plus
  preferred agent, and needed new skill.

### Run And Artifact Inspection

Status: partially verified with a real protocol run in real Safari.

Verified run-start steps:

1. On the published Manufacturing Local Analytics protocol, click
   `Run protocol`.
2. Confirm the run dialog opens with these fields:
   `Entry agent`, `Workspace`, `Customer analytics goal`, `Data mode`,
   `Local files or synthetic fixture shape`, `Keys and joins`,
   `Required outputs`, and `Privacy boundary`.
3. Leave the default customer-safe fields in place.
4. Click `Start run`.
5. Confirm the app navigates to `Work -> Runs` with the new run expanded.
6. Confirm the Overview shows status, current stage, workspace, root
   conversation, live guidance, elapsed time, output count, and available
   actions.
7. Click `Artifacts`.
8. Confirm produced artifacts and declared-but-missing artifacts are both shown.
9. Click `Preview` for `input_contract.json`.
10. Confirm the preview modal opens and displays the JSON contract.
11. Click `Close`.

Observed result:

- Earlier run `b1c958a308b248a3838aff8022595767` started from the UI and
  produced the first contract artifact.
- Artifact actions were visible: `Preview`, `Open`, `Download`, and `Copy path`.
- The run-launch form and liveness copy have since changed, so acceptance must
  be rerun after redeploy.

Remaining verification:

- The current run must finish or fail with a clear terminal state.
- Final artifacts must be opened/downloaded from Runs.
- The same artifact references still need verification from stage detail,
  conversation-linked work, and Telegram.

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

Status: in progress through a UI-created protocol run.

Verified steps so far:

1. Start from `Build -> Protocols`.
2. Click `New protocol`.
3. Choose `Manufacturing Local Analytics`.
4. Validate and publish the draft.
5. Click `Run protocol`.
6. Confirm the run dialog asks for goal, file/data context, key
   relationships, expected outputs, and privacy constraints.
7. Start the run.
8. Confirm the run begins and produces the first contract artifact.

Remaining steps:

- Wait for the run to reach a terminal state.
- Open/download the generated local tool artifact.
- Confirm synthetic demo mode generates deterministic local fixture CSVs when
  customer files are absent.
- Confirm aggregate findings are visible.
- Confirm the handoff README/report artifact is downloadable.

### Dashboard Cleanup

Status: implementation updated; real Safari verification must be rerun after
redeploy.

Expected steps:

1. Go to `Operations -> Dashboard`.
2. In `Workspace maintenance`, click `Clean workspace data`.
3. Enter the Registry UI password.
4. Type `CLEAN`.
5. Confirm the action removes conversations, tasks, protocols, runs, artifacts,
   events, and deliveries.
6. Confirm agents, skill catalog entries, guidance, and tokens remain.
7. Confirm the bots do not need to be restarted for Dashboard to repopulate
   agent health.

## Known Handoff Blockers

See `issues.md` for the active blocker list. Do not hand this repository to a
customer as self-service until the blockers are closed or explicitly marked
non-blocking with customer-facing workarounds.
