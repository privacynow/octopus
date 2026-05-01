# Manufacturing Intelligence Command Center Scenario Guide

This guide documents a UI-only product-readiness dry run. The customer-user is
the person authoring, publishing, running, and inspecting the protocol in
Octopus. Manufacturing is the example domain; it is not a product default and
should not be hardcoded into the Registry, SDK, or runtime.

The scenario proves that Octopus can support serious multi-agent work: a user
can define a protocol, route stages across agents, use reviewer gates and
revision loops, and receive a browser-only artifact that opens directly from the
Registry.

## Product Bar

A technically complete artifact is not enough. The run fails if the final output
is a raw table browser, schema debugger, export panel, manual analytics builder,
or collection of disconnected files.

The accepted result must feel like a commercial workflow:

1. plan the outcome and acceptance bar
2. review the plan before downstream work begins
3. design the data model
4. review and accept or return the data model
5. design the user experience and analytics journey
6. implement the browser artifact
7. review UX and interaction quality
8. send implementation back for revision until accepted
9. record final readiness evidence

The final artifact must be one self-contained HTML application. It should guide a
first-time user from start state to useful analytics without requiring raw data
model knowledge.

Required first-use path:

1. generate demo data, load a local CSV/JSON file, or inspect included sample
   data
2. see useful KPI cards, charts, and guidance immediately after data generation
3. filter by understandable dimensions such as site, line, product, shift,
   status, quality state, time window, and risk tier
4. drill from metrics or charts into contributing evidence
5. pin findings idempotently and export a local summary
6. use the same app comfortably in wide and narrow Safari

## Boundaries

Use fictional, privacy-safe manufacturing examples only. Do not paste real
customer names, factory names, product names, meeting transcripts, proprietary
process details, or real operational data into the protocol or run fields.

Do not describe this scenario as a customer handoff. The customer-user is
testing the product path they would use themselves.

Do not add use-case-specific product code to make this scenario pass. If the
product has a gap, fix the product generically. If only the protocol or example
copy is weak, fix the protocol or this guide.

## Preconditions

1. Start Octopus and confirm the Registry UI is reachable.
2. Open real Safari to the Registry UI.
3. Confirm at least two execution-healthy agents are connected.
4. Use only synthetic or privacy-safe context in protocol fields.
5. Keep verification UI-only: create, import, publish, run, open, and inspect
   through the Registry UI.

## Protocol Setup

Create the protocol from a package import or from blank. If building from blank,
use these settings.

Display name:

```text
Adaptive Manufacturing Commercial Readiness Review-Gated V2
```

Slug:

```text
adaptive-manufacturing-commercial-readiness-review-gated-v2
```

Description:

```text
Build and validate a commercially credible browser-only manufacturing command
center through planning, reviewer gates, data modeling, UX design,
implementation, UX review loops, interaction quality checks, and readiness
evidence.
```

## Participants

Use execution-healthy agents and role names that describe responsibility. These
roles are part of the user-authored protocol, not product defaults.

For a two-agent dry run:

| Participant | Suggested agent | Responsibility |
| --- | --- | --- |
| Planner / Reviewer | M1 | Plan quality, acceptance criteria, review gates, and readiness evidence. |
| Data Modeler | M2 | Fictional manufacturing data model and validation rules. |
| UX Architect / Reviewer | M1 | First-time-user journey, responsive UX, and interaction review. |
| Implementer | M2 | Single-file browser artifact implementation. |

In larger deployments, assign separate specialist agents where available.

## Artifacts

Declare these artifacts and enable verification for each:

| Key | Display name | Path | Kind |
| --- | --- | --- | --- |
| `operating_plan` | Operating plan | `artifacts/manufacturing-intelligence/operating-plan.md` | `workspace_file` |
| `plan_review` | Plan review | `artifacts/manufacturing-intelligence/plan-review.md` | `workspace_file` |
| `data_model` | Data model | `artifacts/manufacturing-intelligence/data-model.md` | `workspace_file` |
| `data_model_review` | Data model review | `artifacts/manufacturing-intelligence/data-model-review.md` | `workspace_file` |
| `ux_spec` | UX analytics specification | `artifacts/manufacturing-intelligence/ux-analytics-spec.md` | `workspace_file` |
| `command_center_html` | Command center HTML | `artifacts/manufacturing-intelligence/command-center.html` | `workspace_file` |
| `ux_review` | UX review | `artifacts/manufacturing-intelligence/ux-review.md` | `workspace_file` |
| `readiness_evidence` | Readiness evidence | `artifacts/manufacturing-intelligence/readiness-evidence.md` | `workspace_file` |

The command center artifact must be a single HTML file with inline CSS and
JavaScript. It must not depend on sibling files, external URLs, CDNs, external
fonts, fetch calls, telemetry, or backend APIs.

## Stage Flow

Reviewer stages should be `review` stages with these transitions:

```text
accept -> next authoring stage
revise -> previous authoring stage
fail -> failed
```

Authoring stages transition on `completed`. The final readiness stage
transitions to complete.

### 1. Define Operating Plan

Participant: `Planner / Reviewer`

Output: `operating_plan`

Instructions:

```text
Create the operating plan for a product-readiness dry run of Octopus. The actual
user is the customer operator who will build and run protocols in Octopus; do
not frame this as a customer handoff or a bespoke deliverable.

Define the target outcome: a commercial-quality manufacturing intelligence
command center that a first-time user can generate from a protocol run.

Include audience, success criteria, staged workflow, review gates,
accepted/revise/fail decision rules, fictional data/privacy constraints,
artifact expectations, and the human path from generating or loading data to
useful charts and drilldowns.

Require the final UI to be a single self-contained HTML app that opens directly
from Registry artifacts with no sibling assets, CDN, fetch, or backend
dependency.

End with PROTOCOL_DECISION: completed and a short PROTOCOL_SUMMARY.
```

### 2. Review Operating Plan

Participant: `Planner / Reviewer`

Inputs: `operating_plan`

Output: `plan_review`

Instructions:

```text
Review the operating plan as a commercial product gate. Accept only if it treats
the customer as the Octopus user building and running the protocol, defines a
real multi-stage workflow with reviewer loops, covers planning, data modeling,
UX design, implementation, UX review, and readiness evidence, and gives concrete
acceptance criteria for a self-contained browser artifact.

If the plan uses customer-handoff language, collapses the workflow into one
build step, or leaves the final app vague, choose revise and list exact repairs.

Write the review artifact with findings and end with PROTOCOL_DECISION: accept,
revise, or fail plus PROTOCOL_SUMMARY.
```

### 3. Design Data Model

Participant: `Data Modeler`

Inputs: `operating_plan`, `plan_review`

Output: `data_model`

Instructions:

```text
Create a practical fictional manufacturing analytics data model for the command
center. Include facts, dimensions, keys, relationships, field definitions,
grain, validation rules, and a synthetic data generation plan.

Support both generated demo data and user-loaded data. The model must enable
progressive analytics: fab overview, line/tool health, yield, downtime, WIP,
lots, excursions, root-cause drilldowns by fab area, product, recipe, shift,
tool, and time.

Keep it privacy-safe and fictional.

End with PROTOCOL_DECISION: completed and a short PROTOCOL_SUMMARY.
```

### 4. Review Data Model

Participant: `Planner / Reviewer`

Inputs: `operating_plan`, `data_model`

Output: `data_model_review`

Instructions:

```text
Review the data model as a gate before UX design. Accept only if it is
understandable to non-experts, supports realistic manufacturing analytics
questions, includes demo generation and user-load paths, defines
dimensions/facts/relationships clearly, and avoids private or real customer
data.

Choose revise if the model forces users to understand raw schema before seeing
value, lacks drilldown dimensions, or cannot power charts and tables.

Write the review artifact and end with PROTOCOL_DECISION: accept, revise, or
fail plus PROTOCOL_SUMMARY.
```

### 5. Design UX Analytics Experience

Participant: `UX Architect / Reviewer`

Inputs: `operating_plan`, `data_model`, `data_model_review`

Output: `ux_spec`

Instructions:

```text
Design the SPA experience for a first-time user. The first screen must make the
path obvious: generate demo data, load CSV/JSON, or inspect included sample
data, then progressively reveal executive KPIs, chart-first dashboards, guided
insights, filters, drilldowns, data quality notes, and exportable findings.

Specify responsive behavior for narrow and wide Safari. Call out what controls
should be icons, tabs, toggles, segmented controls, chips/pills, and tables.
Avoid an overwhelming raw builder; avoid ugly pill rows and hamburger overlap.

Drilldowns and findings must be intuitive and idempotent: pinning the same
insight twice must not create duplicate findings, repeated actions must not
create stale or contradictory state, and detail drawers must close cleanly and
not hide essential controls in narrow Safari.

The design must be beautiful, calm, dense enough for operators, and usable
without data-model expertise.

End with PROTOCOL_DECISION: completed and a short PROTOCOL_SUMMARY.
```

### 6. Implement Command Center

Participant: `Implementer`

Inputs: `operating_plan`, `data_model`, `ux_spec`

Output: `command_center_html`

Instructions:

```text
Implement the artifact at
artifacts/manufacturing-intelligence/command-center.html. Create exactly one
self-contained HTML file with inline CSS and inline JavaScript. Do not reference
external CSS, scripts, fonts, images, modules, CDNs, sibling files, fetch,
sendBeacon, or backend APIs. The Registry artifact Open link must render the
complete app directly.

Build a polished SPA for manufacturing intelligence: progressive start state,
generate demo data button, CSV/JSON load path, sample data preview, KPI strip,
multiple responsive charts made with inline SVG/canvas/CSS, filter controls,
drilldowns by product/area/tool/shift/time, insights panel,
anomalies/excursions, WIP/yield/downtime views, and a human-readable data
dictionary.

Findings must be idempotent and useful: pinning the same drilldown or
auto-summary repeatedly must update or focus the existing finding, not duplicate
it; remove/export actions must behave predictably; exported summaries must
reflect the visible findings.

Drilldown drawers must work in wide and narrow Safari, close cleanly, avoid
covering critical navigation after a related-tab jump, and never leave stale
details from a previous dataset.

The UI must be readable in wide and narrow Safari, with no overlapping
hamburger/menu/buttons, no cramped or ugly pill rows, no clipped text, and no
need for users to understand raw schema before seeing value.

Use fictional data only. Do not use customer-handoff language.

End with PROTOCOL_DECISION: completed and a short PROTOCOL_SUMMARY.
```

### 7. Review Command Center UX

Participant: `UX Architect / Reviewer`

Inputs: `command_center_html`, `ux_spec`

Output: `ux_review`

Instructions:

```text
Review the implemented HTML artifact against the operating plan and UX
specification. Accept only if the file is self-contained, visually polished,
progressive for first-time users, chart-first, responsive, and supports
generate/load data plus meaningful drilldowns.

Inspect the code and behavior for interaction quality: repeated pinning of the
same drilldown must not create duplicate findings; repeated auto-summary actions
must not spam identical summaries; remove/export findings must reflect current
visible state; detail drawers must close cleanly; related-tab jumps must not
leave the app in a confusing or obstructed state; reset/data replacement must
not leave stale detail content; and narrow Safari must not show overlapping
tabs, pills, buttons, drawers, or clipped text.

Choose revise if it is an unstyled explorer, depends on sibling assets or
external resources, has ugly or excessive pills, hamburger/menu overlap, tiny
text, raw-schema-first workflow, missing charts, missing drilldowns, duplicate
findings, stale drawers, broken local load validation, or confusing first-use
path.

Write concrete findings in the review artifact and end with PROTOCOL_DECISION:
accept, revise, or fail plus PROTOCOL_SUMMARY.
```

### 8. Record Readiness Evidence

Participant: `Planner / Reviewer`

Inputs: `operating_plan`, `plan_review`, `data_model`,
`data_model_review`, `ux_spec`, `command_center_html`, `ux_review`

Output: `readiness_evidence`

Instructions:

```text
Create the readiness evidence artifact for this product-readiness dry run.
Summarize what the protocol proved about Octopus: multi-stage planning,
reviewer decisions, revision routing, data modeling, UX design, implementation,
UX review, artifact verification, interaction-quality checks, and the final
direct-open HTML output.

Include the final interaction evidence for generate/load affordances,
drilldowns, idempotent findings, exports, narrow Safari readability, and
local-only fictional data.

Include remaining risks and next improvements for a commercial customer using
Octopus to build their own protocols. Do not describe this as a handoff.

End with PROTOCOL_DECISION: completed and a short PROTOCOL_SUMMARY.
```

## Run Inputs

Workspace:

```text
default
```

Goal:

```text
Build and validate a commercially credible browser-only manufacturing command
center through planning, reviewer gates, data modeling, UX design,
implementation, UX review loops, interaction quality checks, and readiness
evidence.
```

Context:

```text
Product-readiness dry run for a customer operator using Octopus to build and run
this protocol. Use fictional manufacturing data only. The goal is to prove the
product workflow and produce a direct-open browser artifact, not a bespoke
customer handoff.
```

Constraints:

```text
No real customer data. No customer-handoff framing. The final
command_center_html artifact must be one self-contained HTML file with inline
CSS and JavaScript only: no external files, CDNs, fonts, images, fetch,
sendBeacon, or backend APIs. Review stages must use accept, revise, or fail
exactly as the protocol defines. Findings, drilldowns, reset, exports, and
narrow Safari layout must be interaction-quality checked.
```

Expected outputs:

```text
operating_plan, plan_review, data_model, data_model_review, ux_spec,
command_center_html, ux_review, readiness_evidence.
```

## UI Verification Checklist

Complete verification in real Safari from the Registry UI.

1. Export the protocol package from the source protocol.
2. Import the package as a new protocol or copy without overwriting existing
   protocols.
3. Publish the imported protocol.
4. Start a run from the UI.
5. Verify the run completes with all eight declared outputs and no issues.
6. Open `command_center_html` from the run artifact `Open` link.
7. Confirm first load presents a clear start path.
8. Generate demo data and verify KPI cards, charts, guidance, filters, and tabs
   appear immediately.
9. Open at least three analytics sections and confirm charts/tables are useful
   without raw schema knowledge.
10. Trigger a drilldown, use related-tab navigation, close the detail panel, and
    confirm the app remains understandable.
11. Pin the same drilldown twice and confirm there is only one finding, or that
    the existing finding is updated/focused.
12. Add an auto-summary twice and confirm the app does not spam duplicate
    summaries.
13. Export the findings summary locally and confirm it reflects visible
    findings.
14. Reset or regenerate data and confirm stale details/findings do not mislead
    the user.
15. Resize Safari to a narrow layout and confirm there is no overlapping
    navigation, pills, buttons, drawers, or clipped text.

## Validated V2 Run

The V2 protocol was imported as a new protocol, published, executed, and
verified from the Registry UI in real Safari.

| Field | Value |
| --- | --- |
| Protocol | `Adaptive Manufacturing Commercial Readiness Review-Gated V2` |
| Protocol ID | `a364b1bb3ac94089892db878552693f9` |
| Run ID | `b89bb6e2f1a64f30b7b5bb17c9358858` |
| Final status | `completed` |
| Outputs | `8 / 8` |
| Issues | `0` |
| Elapsed | `23m` |
| Command center artifact | `command_center_html` |
| Command center hash | `sha256 cc5b3452944c` |
| Command center size | `85,035 bytes` |
| Readiness evidence hash | `sha256 dc2511400202` |

The run exercised the revise path. The first implementation passed artifact
verification but the UX review rejected it because local JSON validation did not
match the accepted `dim_area` model and narrow Safari still had overlap risk.
The second implementation was accepted after revising canonical `dim_area`
loading and narrow Safari layout behavior.

Real Safari artifact checks completed from the Registry artifact `Open` link:

1. Initial state presented clear generate, load, and sample-inspection paths.
2. Generated demo data produced KPIs, validation status, filters, charts,
   tables, guided insights, and analytics tabs immediately.
3. Overview, Lines, Downtime, and Findings sections were readable and useful at
   the tested narrow Safari width.
4. KPI drilldown opened a usable right-side detail panel with close, pin, and
   related-tab controls.
5. Pinning the same KPI twice updated the existing finding instead of creating
   duplicate findings.
6. Adding auto-summary twice updated the existing summary instead of creating
   duplicate summaries.
7. Reset returned to the start state and cleared generated state without stale
   findings or detail panels.

## Reference Notes

The earlier `Adaptive Manufacturing Intelligence Command Center` run proved
basic protocol execution, but it was too shallow for product readiness because
it allowed a technically complete but unintuitive explorer. The review-gated V2
workflow supersedes it.

Known issue from the first review-gated dry run:

- Duplicate pinned findings were possible when the same drilldown was pinned
  repeatedly. The V2 protocol explicitly requires idempotent findings and makes
  duplicate findings a review-rejecting defect.
