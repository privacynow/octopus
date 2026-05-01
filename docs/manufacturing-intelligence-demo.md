# Manufacturing Intelligence Command Center Scenario Guide

This guide documents the UI-only manufacturing intelligence acceptance run. It
is intentionally scenario-specific. Do not turn these field labels, sample data
names, stage prompts, dashboards, or manufacturing terms into product defaults.

The product requirement proved by this scenario is generic: a user can create a
blank protocol, publish it, run it through Registry UI, delegate stages across
agents, and receive a browser-only artifact that handles local CSV data without
backend processing.

## Verified Run

Latest verified Registry run:

- Protocol: `Adaptive Manufacturing Intelligence Command Center`
- Protocol id: `b0974e104404409481426d31842b56d4`
- Run id: `25e2f70f8b9545ffa4e477582628bb97`
- Run result: completed, 6 / 6 stages
- Final package artifact: `artifact_4`
- Artifact hash: `sha256 79ea0bff24db`
- Package path:
  `artifacts/manufacturing-intelligence/package`

Live Safari verification covered:

- default synthetic data generation
- relationship candidates starting unconfirmed
- explicit high-evidence relationship confirmation
- evidence panel review
- joined analytics builder output
- heat-map output
- dashboard views for yield, defects, process, equipment, flow, and exports
- local upload of multiple CSV files
- adapted synthetic data in both single-table and relationship-preserving modes
- local management report export

Known artifact-level issue found during the run:

- after Reset or data replacement, the detail panel can retain stale
  relationship evidence from the prior dataset. This is not product-hardcoded;
  fix it in the next scenario protocol refinement or generated artifact
  validation prompt.

## Preconditions

1. Start Octopus and confirm Registry is reachable.
2. Open real Safari to the Registry UI.
3. Confirm M1 and M2 are connected and execution-healthy.
4. Use only synthetic or privacy-safe context in protocol fields.
5. Do not paste real meeting transcript text, customer names, proprietary
   fields, or company data into protocol stages or run inputs.

## Create From Blank

Open:

```text
Build -> Protocols -> New protocol -> Start blank
```

Set:

```text
Display name: Adaptive Manufacturing Intelligence Command Center
Slug: adaptive-manufacturing-intelligence-command-center
Description: Build and validate a browser-only manufacturing intelligence package with synthetic data, traceability, quality analytics, process performance, equipment health, and executive reporting.
```

## Participants

Use two execution-healthy agents:

```text
M1: protocol planning, specification, validation, and executive review
M2: implementation/build stages for generated package artifacts
```

Do not make M2 manufacturing-specific in the product. M2 is only the assigned
stage participant for this user-authored protocol.

## Artifacts

Declare these artifacts:

| Display name | Path | Kind | Verify |
| --- | --- | --- | --- |
| Manufacturing intelligence charter | `artifacts/manufacturing-intelligence/charter.md` | `workspace_file` | yes |
| Manufacturing data model specification | `artifacts/manufacturing-intelligence/data-model.md` | `workspace_file` | yes |
| Analytics and UX specification | `artifacts/manufacturing-intelligence/app-spec.md` | `workspace_file` | yes |
| Manufacturing intelligence package | `artifacts/manufacturing-intelligence/package` | `workspace_file` package directory | yes |
| Manufacturing validation report | `artifacts/manufacturing-intelligence/validation-report.md` | `workspace_file` | yes |
| Executive review memo | `artifacts/manufacturing-intelligence/executive-review.md` | `workspace_file` | yes |

## Stages

Create the stages below in order. Each stage should transition to the next on
`completed`; the final stage transitions to complete.

### 1. Define Manufacturing Intelligence Charter

Participant: `M1`

Outputs:

```text
Manufacturing intelligence charter
```

Instructions:

```text
Produce artifacts/manufacturing-intelligence/charter.md.

Define a privacy-safe, generic manufacturing intelligence objective for an offline browser package. The target user is a manufacturing manager who needs repeatable insight across materials, process stages, equipment, quality, test, defects, throughput, energy, and shipment readiness. Do not use real company names, real people, meeting transcript text, customer data, or proprietary process details.

Include:
- business goal and user profile
- privacy boundary: uploaded rows stay in browser
- expected data sources: CSV exports from multiple process stages
- required outputs: offline index.html, README, sample CSVs, data dictionary, management reports, and validation notes
- decision-support boundary: recommendations are explainable review prompts, not automatic control instructions
- success criteria for traceability, quality analytics, process drift, equipment health, WIP, yield, scrap, energy, and exports

The charter must keep the product generic. Manufacturing examples are only sample content for this protocol run.
```

### 2. Design Synthetic Manufacturing Data Model

Participant: `M2`

Inputs:

```text
Manufacturing intelligence charter
```

Outputs:

```text
Manufacturing data model specification
```

Instructions:

```text
Read artifacts/manufacturing-intelligence/charter.md and produce artifacts/manufacturing-intelligence/data-model.md.

Design a comprehensive synthetic data model for an advanced, generic manufacturing operation. The default sample domain may blend solar module, precision glass, battery, and semiconductor-style ideas, but do not use real brand names, real product names, real factory names, or proprietary data.

Specify tables, columns, primary keys, foreign key candidates, row-count targets, defect/performance signals, and relationships for plants, lines, tools, recipes, material lots, work orders, units, genealogy, process runs, process measurements, metrology, inspection defects, electrical or final tests, reliability tests, tool events, maintenance events, environmental or energy records, quality dispositions, and shipments.

Include deliberate but explainable synthetic patterns:
- supplier/material cohort quality risk
- chamber/tool drift before maintenance
- recipe revision yield and cycle-time tradeoff
- inspection defect position heat-map signal
- WIP and shipment readiness exceptions
- energy per good unit
- process capability/SPC style metrics

The model must be rich enough to support useful dashboards and random synthetic CSV generation, while still being safe and fictional.
```

### 3. Specify Analytics And User Experience

Participant: `M1`

Inputs:

```text
Manufacturing intelligence charter
Manufacturing data model specification
```

Outputs:

```text
Analytics and UX specification
```

Instructions:

```text
Read the charter and data model specification. Produce artifacts/manufacturing-intelligence/app-spec.md.

Specify a browser-only offline SPA that feels like an operations command center for a manufacturing manager while remaining generic and schema-driven. The app must work from local files with no backend and no external network dependency.

The SPA must:
- upload multiple local CSV files
- profile tables, row counts, column roles, candidate primary keys, and warnings
- infer relationship candidates from common fields, uniqueness, overlap, and cardinality
- require explicit user confirmation before joined analytics
- generate default synthetic manufacturing data using the data model
- after upload, generate adapted synthetic data from observed schemas and confirmed relationships
- clearly label single-table adapted synthetic mode if no relationships are confirmed
- render dynamic aggregations, charts, heat maps, and tabular results
- expose manager views for yield, defects, quality resume, process drift, equipment health, cycle time, WIP, resources, recommendations, and exports
- export CSV, relationship JSON, schema JSON, recommendation Markdown, and management report Markdown

Include expected visual layout, accessibility expectations, Safari validation steps, and privacy caveats.
```

### 4. Build Offline Manufacturing Intelligence Package

Participant: `M2`

Inputs:

```text
Manufacturing intelligence charter
Manufacturing data model specification
Analytics and UX specification
```

Outputs:

```text
Manufacturing intelligence package
```

Instructions:

```text
Build the final offline package in artifacts/manufacturing-intelligence/package.

Produce at minimum:
- index.html
- README.md
- data-dictionary.md
- validation-report.md
- reports/management-brief.md
- reports/analytics-methods.md
- reports/sample-insights.md
- samples/plants.csv
- samples/lines.csv
- samples/tools.csv
- samples/recipes.csv
- samples/material_lots.csv
- samples/work_orders.csv
- samples/units.csv
- samples/unit_genealogy.csv
- samples/process_runs.csv
- samples/process_measurements.csv
- samples/metrology_results.csv
- samples/inspection_defects.csv
- samples/electrical_tests.csv
- samples/reliability_tests.csv
- samples/tool_events.csv
- samples/maintenance_events.csv
- samples/environmental_energy.csv
- samples/quality_dispositions.csv
- samples/shipments.csv

The index.html must be self-contained and browser-only. It must not require a backend, package install, build step, or external network. It may use inline JavaScript and CSS. It must support local uploaded CSVs and keep uploaded rows in browser memory.

Implement the full workflow:
- default synthetic data generation
- uploaded CSV parsing
- schema profiling
- relationship candidate inference
- explicit relationship confirmation
- joined analytics only after confirmation
- adapted synthetic generation that follows uploaded schemas and confirmed relationships
- single-table adapted synthetic mode when no relationships are confirmed
- dynamic aggregation builder
- heat-map view
- charts and tabular outputs
- manager dashboards
- local exports

Do not use real companies, real products, real people, real customer names, transcript text, or proprietary fields. Keep the artifact impressive but fictional and privacy-safe.
```

### 5. Validate Package Completeness

Participant: `M1`

Inputs:

```text
Manufacturing intelligence package
```

Outputs:

```text
Manufacturing validation report
```

Instructions:

```text
Inspect artifacts/manufacturing-intelligence/package and produce artifacts/manufacturing-intelligence/validation-report.md. Also update artifacts/manufacturing-intelligence/package/validation-report.md if needed.

Validate:
- package exists and contains required files
- index.html is self-contained
- no external scripts, fetch, sendBeacon, backend calls, real company names, real customer names, or meeting transcript content
- all sample CSVs have headers and plausible rows
- primary keys are unique where expected
- relationship candidates start unconfirmed
- joined analytics use confirmed relationships only
- upload resets confirmations
- adapted synthetic generation works in single-table and relationship-preserving modes
- dashboards and exports are present
- README is useful for a non-technical manufacturing manager

Record pass/fail evidence and any limitations. Do not silently approve missing functionality.
```

### 6. Prepare Executive Review

Participant: `M1`

Inputs:

```text
Manufacturing validation report
Manufacturing intelligence package
```

Outputs:

```text
Executive review memo
Manufacturing intelligence package
```

Instructions:

```text
Produce artifacts/manufacturing-intelligence/executive-review.md and update artifacts/manufacturing-intelligence/package/reports/management-brief.md if needed.

Write for a manufacturing manager. Explain what the generated package proves, what sample data is included, what decisions the dashboards support, and how a manager should interpret the recommendations. Include a concise morning review sequence:
1. load or generate data
2. inspect schema and relationships
3. confirm relationships
4. review yield, defects, drift, equipment, flow, resources, and recommendations
5. export the management report

Include privacy limits, synthetic-data caveats, and why the package is decision support rather than automatic control.
```

## Run Inputs

Use these values in `Run protocol`.

Workspace:

```text
default
```

Goal:

```text
Produce a second-pass, customer-facing offline manufacturing intelligence command center package that incorporates prior validation findings. The package must be impressive for a manufacturing manager while remaining privacy-safe and generic. It must include a self-contained index.html SPA, sample CSV files, README, data dictionary, validation report, management reports, and executive review. It must allow local CSV upload, schema profiling, relationship inference, explicit relationship confirmation, dynamic aggregations, heat maps, charts, manager dashboards, exports, and adapted synthetic data generation from uploaded schemas and confirmed relationships.
```

Context:

```text
Use only synthetic, privacy-safe, non-proprietary manufacturing examples. The sample domain may blend patterns from advanced solar/module, precision glass, battery, and semiconductor-style factories, but do not use real company names, real factory names, real product names, real customer names, meeting transcript text, or proprietary process details. The Octopus product must remain generic; this manufacturing scenario is only a user-authored protocol run.
```

Constraints:

```text
Final artifact must be a browser-only offline package at artifacts/manufacturing-intelligence/package. It must run without backend access and without external network dependency. Relationship candidates must start unconfirmed and joined analytics must require explicit confirmation. Adapted synthetic generation must label single-table mode when relationships are unconfirmed and relationship-preserving mode after confirmation. Recommendations must be explainable decision support, not automatic control instructions.
```

Expected outputs:

```text
artifacts/manufacturing-intelligence/charter.md
artifacts/manufacturing-intelligence/data-model.md
artifacts/manufacturing-intelligence/app-spec.md
artifacts/manufacturing-intelligence/package containing index.html, README.md, data-dictionary.md, reports/*.md, samples/*.csv, and validation-report.md
artifacts/manufacturing-intelligence/validation-report.md
artifacts/manufacturing-intelligence/executive-review.md
```

## Safari Verification Checklist

After the run completes, open the package artifact from the run page and verify:

1. `Data` starts empty, then `Generate default synthetic data` loads 19 tables.
2. `Relationships` shows candidates with `Confirmed: 0`.
3. `Evidence` shows score, overlap, uniqueness, and cardinality details.
4. `Confirm reviewed high-evidence batch` changes the confirmed count.
5. `Analytics Builder` can run a confirmed join analysis.
6. `Analytics Builder` can render the heat-map output.
7. `Command Center`, `Quality`, `Process`, `Equipment`, `Flow`,
   `Resources`, and `Recommendations` render manager-facing views.
8. `Upload CSVs` accepts multiple local sample CSV files.
9. `Generate adapted synthetic from uploaded schemas` first labels
   single-table mode when relationships are unconfirmed.
10. Confirm uploaded-schema relationships, run adapted generation again, and
    verify relationship-preserving mode.
11. `Exports` can generate management report Markdown locally.

Record any product or artifact usability issue in `issues.md`.
