# UI-only protocol creation and execution runbook

This runbook documents the repeatable UI-only path used to create, publish, launch, execute, and verify two protocols:

- A support escalation packet protocol.
- A software engineering protocol that produces a working feature flag rollout simulator.

The proof run used stamp `1777000689035`. To reproduce the exact names and artifact paths from the proof, use that stamp everywhere below. To avoid collisions with the existing proof data, choose a new numeric stamp and replace `<STAMP>` consistently in every field.

## Preconditions

- Registry UI is running and you can sign in normally.
- Agent `M1` is connected and healthy.
- Use only UI controls for creation, publishing, launch, execution, and verification.
- Do not populate database rows or call registry APIs directly as part of this run.
- When a stage editor is open, click `Done` before moving to the next stage if you want to keep the screen compact and avoid losing track of the active stage.

## Flow 1: Support escalation packet

### Create the protocol

1. Open the Registry UI.
2. Click `Protocols`.
3. Click `New protocol`.
4. In the protocol name field, enter:

```text
UI Only Support Escalation Packet <STAMP>
```

5. Open `Protocol settings`.
6. Open `Workflow files`.
7. Add these artifacts:

| Artifact label | Relative path |
| --- | --- |
| Intake notes | `ui-only/<STAMP>/support-packet/intake.md` |
| Operator runbook | `ui-only/<STAMP>/support-packet/operator-runbook.md` |
| Customer update | `ui-only/<STAMP>/support-packet/customer-update.md` |
| On-call handoff | `ui-only/<STAMP>/support-packet/handoff.json` |

8. Click `Back to workflow`.

### Configure stages

Create exactly three stages, in this order. Use the inline stage editor for each stage.

#### Stage 1

| Field | Value |
| --- | --- |
| Stage name | `Triage intake` |
| Stage type | `Work` or the default work type |
| Role name | `Triage writer` |
| Role key | `triage-writer` |
| Assignment | Specific agent |
| Agent | `M1` or `lift-and-shift-m1-bot` |

Instructions:

```text
Create ui-only/<STAMP>/support-packet/intake.md. Use the problem statement to write realistic incident context for a payment webhook latency spike. Include timeline, affected systems, user impact, assumptions, and open questions. Do not write generic filler; make it usable for a real on-call handoff.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Writes | Intake notes |

Routing:

| Outcome | Destination |
| --- | --- |
| `completed` | Draft operator runbook |

#### Stage 2

| Field | Value |
| --- | --- |
| Stage name | `Draft operator runbook` |
| Stage type | `Work` or the default work type |
| Role name | `Runbook author` |
| Role key | `runbook-author` |
| Assignment | Specific agent |
| Agent | `M1` or `lift-and-shift-m1-bot` |

Instructions:

```text
Read ui-only/<STAMP>/support-packet/intake.md. Create ui-only/<STAMP>/support-packet/operator-runbook.md and ui-only/<STAMP>/support-packet/customer-update.md. The runbook must include verification commands, dashboards/signals to inspect, mitigation steps, rollback criteria, and escalation rules. The customer update must be concise, honest, non-technical, and include current impact, mitigation status, and next update timing.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Intake notes |
| Writes | Operator runbook |
| Writes | Customer update |

Routing:

| Outcome | Destination |
| --- | --- |
| `completed` | Publish handoff packet |

#### Stage 3

| Field | Value |
| --- | --- |
| Stage name | `Publish handoff packet` |
| Stage type | `Work` or the default work type |
| Role name | `Packet publisher` |
| Role key | `packet-publisher` |
| Assignment | Specific agent |
| Agent | `M1` or `lift-and-shift-m1-bot` |

Instructions:

```text
Read ui-only/<STAMP>/support-packet/intake.md, ui-only/<STAMP>/support-packet/operator-runbook.md, and ui-only/<STAMP>/support-packet/customer-update.md. Create ui-only/<STAMP>/support-packet/handoff.json as valid JSON. Include incident_id, severity, affected_services, current_owner, next_actions, artifact_paths, and readiness_status. Set readiness_status to ready only if the packet is coherent and all listed artifacts exist.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Intake notes |
| Reads | Operator runbook |
| Reads | Customer update |
| Writes | On-call handoff |

Routing:

| Outcome | Destination |
| --- | --- |
| `completed` | Complete |

### Publish

1. Click `Validate`.
2. Confirm that there are no protocol issues.
3. Click `Publish`.
4. Confirm the published protocol is visible in the protocols list.

## Flow 2: Software engineering simulator

### Create the protocol

1. Click `Protocols`.
2. Click `New protocol`.
3. In the protocol name field, enter:

```text
UI Only Software Engineering Simulator <STAMP>
```

4. Open `Protocol settings`.
5. Open `Workflow files`.
6. Add these artifacts:

| Artifact label | Relative path |
| --- | --- |
| Problem statement | `ui-only/<STAMP>/feature-flag-rollout-simulator/problem.md` |
| Delivery plan | `ui-only/<STAMP>/feature-flag-rollout-simulator/plan.md` |
| Implementation status | `ui-only/<STAMP>/feature-flag-rollout-simulator/status.md` |
| Simulator app | `ui-only/<STAMP>/feature-flag-rollout-simulator/index.html` |
| Usage README | `ui-only/<STAMP>/feature-flag-rollout-simulator/README.md` |
| Manual test plan | `ui-only/<STAMP>/feature-flag-rollout-simulator/test-plan.md` |

7. Click `Back to workflow`.

### Configure stages

Create exactly seven stages, in this order. Each stage should be assigned to `M1` or `lift-and-shift-m1-bot`.

#### Stage 1

| Field | Value |
| --- | --- |
| Stage name | `Planning` |
| Stage type | `Work` |
| Role name | `Planner` |
| Role key | `planner` |

Instructions:

```text
Create ui-only/<STAMP>/feature-flag-rollout-simulator/problem.md and ui-only/<STAMP>/feature-flag-rollout-simulator/plan.md. Define requirements for a polished self-contained feature flag rollout simulator used by platform engineers. The plan must include UX, data model, calculations, testing approach, and acceptance criteria.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Writes | Problem statement |
| Writes | Delivery plan |

Routing: `completed` to `Plan Review`.

#### Stage 2

| Field | Value |
| --- | --- |
| Stage name | `Plan Review` |
| Stage type | `Review` |
| Role name | `Plan reviewer` |
| Role key | `plan-reviewer` |

Instructions:

```text
Review the plan for realism and completeness. Accept if it is coherent, scoped, and testable; revise only for material gaps.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |

Routing: `completed` to `Architecture`.

#### Stage 3

| Field | Value |
| --- | --- |
| Stage name | `Architecture` |
| Stage type | `Work` |
| Role name | `Architect` |
| Role key | `architect` |

Instructions:

```text
Refine ui-only/<STAMP>/feature-flag-rollout-simulator/plan.md with implementation architecture. Specify HTML structure, CSS visual approach, JavaScript state model, deterministic scenario calculations, and accessibility behavior.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |
| Writes | Delivery plan |

Routing: `completed` to `Architecture Review`.

#### Stage 4

| Field | Value |
| --- | --- |
| Stage name | `Architecture Review` |
| Stage type | `Review` |
| Role name | `Architecture reviewer` |
| Role key | `architecture-reviewer` |

Instructions:

```text
Review the architecture for maintainability, browser compatibility, and usability. Accept if it is safe to implement.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |

Routing: `completed` to `Implementation`.

#### Stage 5

| Field | Value |
| --- | --- |
| Stage name | `Implementation` |
| Stage type | `Work` |
| Role name | `Implementer` |
| Role key | `implementer` |

Instructions:

```text
Create ui-only/<STAMP>/feature-flag-rollout-simulator/index.html, ui-only/<STAMP>/feature-flag-rollout-simulator/README.md, ui-only/<STAMP>/feature-flag-rollout-simulator/test-plan.md, and ui-only/<STAMP>/feature-flag-rollout-simulator/status.md. Build a polished single-file HTML app with embedded CSS and JavaScript, no external dependencies. The app must model feature flag rollout decisions: total users, rollout percent, canary cohort, error budget, incident risk, blast radius, and recommendation. Include interactive controls, accessible labels, meaningful visual styling, deterministic calculations, and example scenarios. The README must explain use cases and the test plan must include at least eight manual checks.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |
| Writes | Implementation status |
| Writes | Simulator app |
| Writes | Usage README |
| Writes | Manual test plan |

Routing: `completed` to `Implementation Review`.

#### Stage 6

| Field | Value |
| --- | --- |
| Stage name | `Implementation Review` |
| Stage type | `Review` |
| Role name | `Implementation reviewer` |
| Role key | `implementation-reviewer` |

Instructions:

```text
Review whether the simulator, README, and test plan exist and match the plan. Accept if the deliverables are usable and coherent.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |
| Reads | Implementation status |
| Reads | Simulator app |
| Reads | Usage README |
| Reads | Manual test plan |

Routing: `completed` to `Acceptance`.

#### Stage 7

| Field | Value |
| --- | --- |
| Stage name | `Acceptance` |
| Stage type | `Acceptance` |
| Role name | `Acceptance reviewer` |
| Role key | `acceptance-reviewer` |

Instructions:

```text
Accept the run if the software deliverables are present, realistic, and useful. Revise only if the application or documentation is missing.
```

Files and outputs:

| Direction | Artifact |
| --- | --- |
| Reads | Problem statement |
| Reads | Delivery plan |
| Reads | Implementation status |
| Reads | Simulator app |
| Reads | Usage README |
| Reads | Manual test plan |

Routing: `completed` to `Complete`.

### Publish

1. Click `Validate`.
2. Confirm that there are no protocol issues.
3. Click `Publish`.
4. Confirm the published protocol is visible in the protocols list.

## Launch protocols from a conversation

Use this path to prove that published protocols are usable from the same conversation surface that already supports skills and agents.

### Start from M1

1. Click `Conversations`.
2. Open an existing `M1` conversation or start a new M1 conversation from the quick-start area.
3. Click `Protocols`.
4. In the protocol drawer, use `Search published protocols` if the list is long.
5. Select the published protocol from `Published protocol`.
6. Fill `Describe what this protocol should accomplish`.
7. Click `Start protocol`.
8. After the run starts, use `Recent linked runs` in the same drawer to open the run.

### Support launch prompt

Use this prompt with `UI Only Support Escalation Packet <STAMP>`:

```text
Payment webhook latency increased from p95 900ms to 8.2s after a queue consumer deploy. Customers see delayed invoice status updates in the dashboard. Create an escalation packet for on-call handoff with concrete mitigation steps, customer update, and next-owner summary.
```

Expected proof run for stamp `1777000689035`:

| Field | Value |
| --- | --- |
| Run ID | `96fcac0c36654507a07c3291618067f6` |
| Final status | `completed` |
| Completed stages | Triage intake, Draft operator runbook, Publish handoff packet |

Expected output artifacts:

| Artifact | UI actions that should be available after completion |
| --- | --- |
| Intake notes | Preview, Download, Copy path |
| Operator runbook | Preview, Download, Copy path |
| Customer update | Preview, Download, Copy path |
| On-call handoff | Preview, Download, Copy path |

### Software launch prompt

Use this prompt with `UI Only Software Engineering Simulator <STAMP>`:

```text
Build a polished self-contained feature flag rollout simulator for platform engineers. It should help decide whether a rollout percentage is safe using total users, canary cohort, error budget, observed error rate, and blast radius. Produce a working HTML app, README, and test plan. Keep it realistic enough for an internal platform team demo.
```

Expected proof run for stamp `1777000689035`:

| Field | Value |
| --- | --- |
| Run ID | `5df4889fba7b4aa487b7952f76844ccd` |
| Final status | `completed` |
| Completed stages | Planning, Plan Review, Architecture, Architecture Review, Implementation, Implementation Review, Acceptance |

Expected output artifacts:

| Artifact | UI actions that should be available after completion |
| --- | --- |
| Problem statement | Preview, Download, Copy path |
| Delivery plan | Preview, Download, Copy path |
| Implementation status | Preview, Download, Copy path |
| Simulator app | Open, Download, Copy path |
| Usage README | Preview, Download, Copy path |
| Manual test plan | Preview, Download, Copy path |

When opening the simulator app, the page should render a working app titled:

```text
Feature Flag Rollout Guardrail
```

## Verify a completed run from the UI

1. Open the linked run from the conversation drawer, or click `Runs` and search by run ID or protocol name.
2. Confirm the run status is `completed`.
3. Confirm the stage progression shows every expected stage.
4. Open `Outputs`.
5. For each Markdown or JSON artifact, click `Preview` and confirm the content is specific to the prompt.
6. For the HTML simulator artifact, click `Open` and confirm the app renders in a browser tab.
7. Use `Download` for any artifact that should be saved locally.
8. Use `Copy path` when you need the workspace location for a collaborator or follow-up task.

If a run has not reached the stage that creates an output yet, the artifact should be shown as not ready or unavailable instead of offering a broken download.

## What this proves

- A protocol can be authored from zero to one using only the UI.
- Artifacts can be declared in the protocol editor and mapped to real stage reads and writes.
- Published protocols can be launched from conversations.
- Runs remain discoverable from the conversation and the runs surface.
- Completed output artifacts can be previewed, opened, downloaded, or copied from the UI.
- The software engineering flow produces a non-toy deliverable: a self-contained browser app plus README and test plan.
