# Customer Handoff Guide

This guide is built from tested product paths. Do not add a step here unless it
has been exercised from a customer-facing surface: Registry UI, Telegram,
Octopus CLI, or a documented command.

This guide is repository documentation. It is not a protocol artifact, and a
customer protocol run should not be asked to generate or update this file. A
protocol run should produce the customer's working outputs: tool files, local
README files, validation reports, findings reports, and other artifacts that
belong to that run.

Current status: in progress. Use this guide as the working handoff script while
the remaining blockers in `issues.md` are being closed. Steps marked
`Verified` were exercised from a customer-facing UI surface, not by direct
database writes.

Current customer-ready entry point under test:

1. open `Operations -> Dashboard`,
2. use `Workspace maintenance -> Clean workspace data` only when resetting a
   demo environment,
3. open `Build -> Protocols`,
4. create a blank protocol,
5. define stages, files, assignments, and routing from the UI,
6. publish and run it from the UI,
7. inspect outputs and artifacts from the run UI.

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

Status: verified in real Safari for one blank-authored local analytics protocol;
repeat after each redeploy before customer handoff.

Expected blank-authoring flow:

1. Go to `Build -> Protocols`.
2. Click `New protocol`.
3. Confirm a blank draft opens immediately.
4. Name the protocol.
5. Define shared files/artifacts.
6. Add stages from scratch.
7. Assign each stage by agent, by skill, or leave it dynamic.
8. Define routing between stages and terminal outcomes.
9. Click `Validate`.
10. Confirm the toast says `Protocol validated.`
11. Click `Publish`.
12. Confirm state changes from `DRAFT` to `PUBLISHED`.
13. Confirm `Run protocol` appears.

Observed result:

- A protocol named `Customer Local Analytics Tool Builder` was created from a
  blank protocol in real Safari using the Protocols UI.
- The protocol used three customer-readable stages:
  `Define local data contract`, `Build local browser analytics tool`, and
  `Review local tool outputs`.
- Stage assignments were entered from the normal assignment UI: M1 for data
  contract/review and M2 for the implementation stage.
- The implementation stage declared `apps/manufacturing-analytics/index.html`
  and `apps/manufacturing-analytics/README.md`.
- The review stage consumed the implementation artifacts and declared
  `reports/local-tool-validation.md` and
  `reports/manufacturing-analytics-findings.md`.
- The protocol was validated, published, and started from the UI.

Remaining authoring verification:

- Blank protocol creation still needs a full matrix pass for add/remove/reorder
  and assignment variants: no assignment, skill only, agent only, skill plus
  preferred agent, and needed new skill.

### Run And Artifact Inspection

Status: verified for the UI-created local analytics run in real Safari; broader
cross-surface artifact drill-through is still open.

Verified run-start steps:

1. On the published blank-authored analytics protocol, click `Run protocol`.
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

- Run `35f81d5e6bd741c2b16900fc7940ca71` was started from the UI-created
  protocol and completed in real Safari.
- Runs showed the terminal `completed` state, stage count, artifact count,
  elapsed time, current-stage/history context, and completed-run estimate.
- The Artifacts tab grouped outputs by producing stage.
- The generated browser app opened from the artifact `Open` action.
- Markdown report artifacts exposed preview/open/download/copy-path actions.

Remaining verification:

- The same artifact references still need verification from stage detail,
  conversation-linked work, dashboard references, and Telegram.
- Downloaded files still need a clean handoff pass from a fresh deploy.

### Telegram Protocol Use

Status: not yet verified in this pass.

Planned steps:

1. Send `/protocol list`.
2. Start a protocol with `/protocol start <slug> <problem statement>`.
3. Inspect with `/protocol status <run_id>`.
4. Inspect artifacts with `/protocol artifacts <run_id>`.
5. Open the Registry run link.
6. Confirm Telegram and Registry show the same run state and artifacts.

### Local Analytics Workflow

Status: verified once through a blank-authored protocol in real Safari; repeat
after the current prompt-contract fix is deployed.

Verified steps so far:

1. Start from `Build -> Protocols`.
2. Click `New protocol`.
3. Build the analytics workflow from blank.
4. Define stage artifacts and stage-to-stage inputs/outputs.
5. Validate and publish the draft.
6. Click `Run protocol`.
7. Fill the run dialog with goal, file/data context, key relationships,
   expected outputs, and privacy constraints.
8. Start the run.
9. Wait for terminal completion.
10. Open the generated browser app artifact.
11. Set `Key faults` to `Clean relationships`.
12. Click `Generate synthetic data`.
13. Click `Validate keys`.
14. Click `Run analytics`.
15. Confirm validation passes, aggregate findings render, key lineage is shown,
    and export controls are visible.

Remaining steps:

- Confirm the local tool README, validation report, and findings report are
  downloadable.
- Confirm no generated artifact is presented as the repository customer
  handoff guide.

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
