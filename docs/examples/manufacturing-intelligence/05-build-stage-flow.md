# 05. Build Stage Flow

Goal: build the staged workflow before publishing.

Create these eight stages in order.

## Stage 1

Name: `Define Operating Plan`  
Participant: `Planner / Reviewer`  
Output: `Operating plan`

Instructions:

```text
Create artifacts/manufacturing-intelligence/operating-plan.md for a product-readiness dry run. Define the customer as the Octopus user building and running the protocol. Cover audience, success criteria, fictional data boundaries, review gates, artifact expectations, and the path from generated or loaded data to useful charts and drilldowns. End with PROTOCOL_DECISION: completed and PROTOCOL_SUMMARY.
```

## Stage 2

Name: `Review Operating Plan`  
Type: `Review`  
Participant: `Planner / Reviewer`  
Inputs: `Operating plan`  
Output: `Plan review`

Instructions:

```text
Review the operating plan as a commercial product gate. Accept only if it treats the customer as the Octopus user, defines real multi-stage work with reviewer loops, and gives concrete acceptance criteria for a self-contained browser artifact. Choose revise for one-off delivery language, one-step workflow, or vague UX. End with PROTOCOL_DECISION: accept, revise, or fail and PROTOCOL_SUMMARY.
```

## Stage 3

Name: `Design Data Model`  
Participant: `Data Modeler`  
Inputs: `Operating plan`, `Plan review`  
Output: `Data model`

Instructions:

```text
Create artifacts/manufacturing-intelligence/data-model.md with fictional manufacturing facts, dimensions, keys, relationships, validation rules, and synthetic data generation plan. Support generated demo data and user-loaded data. Enable overview, line/tool health, yield, downtime, WIP, lots, excursions, and root-cause drilldowns. End with PROTOCOL_DECISION: completed and PROTOCOL_SUMMARY.
```

## Stage 4

Name: `Review Data Model`  
Type: `Review`  
Participant: `Planner / Reviewer`  
Inputs: `Operating plan`, `Data model`  
Output: `Data model review`

Instructions:

```text
Review the data model as a gate before UX design. Accept only if it is understandable to non-experts, supports useful manufacturing analytics, includes demo generation and user-load paths, and avoids private data. Choose revise if it forces raw-schema knowledge first or cannot power charts and drilldowns. End with PROTOCOL_DECISION: accept, revise, or fail and PROTOCOL_SUMMARY.
```

## Stage 5

Name: `Design UX Analytics Experience`  
Participant: `UX Architect / Reviewer`  
Inputs: `Operating plan`, `Data model`, `Data model review`  
Output: `UX analytics specification`

Instructions:

```text
Create artifacts/manufacturing-intelligence/ux-analytics-spec.md. Design a progressive SPA for a first-time user: generate demo data, load CSV/JSON, inspect sample data, then reveal KPIs, charts, filters, drilldowns, data quality notes, and findings. Specify responsive wide and narrow Safari behavior. Reject raw-builder-first UX, ugly pill rows, and hamburger overlap. End with PROTOCOL_DECISION: completed and PROTOCOL_SUMMARY.
```

## Stage 6

Name: `Implement Command Center`  
Participant: `Implementer`  
Inputs: `Operating plan`, `Data model`, `UX analytics specification`  
Output: `Command center HTML`

Instructions:

```text
Implement artifacts/manufacturing-intelligence/command-center.html as exactly one self-contained HTML file with inline CSS and JavaScript only. No external CSS, scripts, fonts, images, modules, CDNs, sibling files, fetch, sendBeacon, or backend APIs. Build a polished manufacturing intelligence SPA with generate demo data, local CSV/JSON load path, sample preview, KPI strip, responsive charts, filters, drilldowns, insights, findings, exports, and a data dictionary. Findings must be idempotent. Wide and narrow Safari must be readable with no overlapping menus, pills, buttons, or drawers. Use fictional data only. End with PROTOCOL_DECISION: completed and PROTOCOL_SUMMARY.
```

## Stage 7

Name: `Review Command Center UX`  
Type: `Review`  
Participant: `UX Architect / Reviewer`  
Inputs: `Command center HTML`, `UX analytics specification`  
Output: `UX review`

Instructions:

```text
Review artifacts/manufacturing-intelligence/command-center.html against the UX spec. Accept only if it is self-contained, polished, progressive, chart-first, responsive, and supports generate/load data plus meaningful drilldowns. Choose revise for external dependencies, raw-schema-first workflow, ugly pills, hamburger overlap, clipped text, duplicate findings, stale drawers, or missing charts. Write artifacts/manufacturing-intelligence/ux-review.md and end with PROTOCOL_DECISION: accept, revise, or fail and PROTOCOL_SUMMARY.
```

## Stage 8

Name: `Record Readiness Evidence`  
Participant: `Planner / Reviewer`  
Inputs: all previous artifacts  
Output: `Readiness evidence`

Instructions:

```text
Create artifacts/manufacturing-intelligence/readiness-evidence.md. Summarize what the run proved about multi-stage planning, reviewer decisions, revision routing, data modeling, UX design, implementation, artifact verification, interaction checks, and the final direct-open HTML output. Include remaining risks and next improvements. Do not present this as a one-off delivery project. End with PROTOCOL_DECISION: completed and PROTOCOL_SUMMARY.
```

## You Are Done When

- Eight stages exist in order.
- Review stages use `Review`.
- Each stage has its expected inputs and outputs attached.
- The workflow does not collapse into one build stage.

Previous: [Add Participants](04-add-participants.md)  
Next: [Configure Review Loops](06-configure-review-loops.md).
