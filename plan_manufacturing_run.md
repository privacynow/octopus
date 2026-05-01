# Manufacturing Protocol Remediation And Live Acceptance Plan

This is the execution plan for closing the remaining product issues and then
proving Octopus with a new, impressive manufacturing intelligence protocol. It
is written so a new team can continue with little or no chat context.

## Objective

Fix and verify every currently open product issue from `issues.md`, then use
the fixed product to create and run a new UI-authored protocol in real Safari.
The protocol must generate a browser-only offline artifact that would impress a
manufacturing manager: a synthetic, state-of-the-art manufacturing intelligence
command center with comprehensive default data, traceability, quality,
performance, defects, cycle time, equipment, maintenance, energy, and executive
reporting.

The product itself must remain generic. Do not hardcode manufacturing,
analytics, solar, semiconductor, glass, battery, or customer-specific behavior
into Octopus. Manufacturing-specific content belongs only in the protocol that
is authored through the Registry UI and in artifacts produced by that run.

## Current Context From The Repo

Working checkout:

```text
/Users/tinker/output/bots/telegram-agent-bot
```

Deployment checkout:

```text
/Users/tinker/octopus
```

Current branch:

```text
feature/protocol
```

Latest pushed commit at the time this plan was written:

```text
74a17a6e Record verified analytics protocol rerun
```

Recently verified product state:

- Real Safari protocol run `afe7792a151c4e3ab74d4de7a7e2ec79` completed from
  the visible UI.
- M1 executed the requirements and validation stages.
- M2 executed the package build stage, proving the Registry protocol path can
  delegate from M1 to M2.
- Directory/package artifacts now verify, open, browse, download, and copy path
  from the run artifact page.
- Run progress feedback is improved, but still needs broad verification on
  larger non-analytics workflows.

Current manufacturing execution pass:

- Protocol:
  `Adaptive Manufacturing Intelligence Command Center`
- Protocol id:
  `b0974e104404409481426d31842b56d4`
- Latest successful Registry UI run:
  `25e2f70f8b9545ffa4e477582628bb97`
- Final package artifact:
  `artifact_4`, `sha256 79ea0bff24db`,
  `artifacts/manufacturing-intelligence/package`
- Real Safari verified:
  default synthetic data, explicit relationship confirmation, joined analytics,
  heat-map output, manager dashboards, multiple CSV upload, adapted synthetic
  single-table mode, adapted synthetic relationship-preserving mode, and local
  management report export.
- Artifact-level follow-up:
  reset/data replacement should clear stale detail-panel relationship evidence
  in the generated `index.html` package. This belongs in scenario refinement,
  not product-hardcoded manufacturing behavior.

Relevant code and docs:

- Protocol editor and runs UI:
  `octopus_registry/ui/js/components/protocol-workspace.js`
- Shared UI artifact action helper:
  `octopus_registry/ui/js/helpers/kit.js`
- Dashboard cleanup UI:
  `octopus_registry/ui/js/components/dashboard.js`
- Conversations and linked work:
  `octopus_registry/ui/js/components/conversation-detail.js`
  and `octopus_registry/ui/js/components/conversation-list.js`
- Skills surface:
  `octopus_registry/ui/js/components/skill-catalog.js`
- Telegram protocol commands:
  `app/runtime/telegram_ingress.py`,
  `app/runtime/telegram_protocols.py`,
  `app/presentation/telegram.py`
- Shared protocol launch model:
  `octopus_sdk/protocols/launch.py`
- Protocol engine and services:
  `octopus_sdk/protocols/engine.py`,
  `octopus_sdk/protocols/service.py`,
  `octopus_registry/protocol_store.py`
- Architecture:
  `docs/ARCHITECTURE.md`
- Existing scenario guide:
  `docs/examples/offline-csv-analytics.md`
- Active issues:
  `issues.md`

Important current architecture facts:

- Registry owns protocol persistence, HTTP APIs, idempotency, run projection,
  and task dispatch.
- SDK owns protocol document models, validation, launch helpers, prompt
  rendering, stage decision parsing, and lifecycle evaluation.
- Registry UI and Telegram should consume the same SDK protocol behavior.
- Protocol launch must remain generic unless a protocol author defines
  `metadata.run_inputs`.
- Dashboard cleanup removes authored workspace work records and preserves
  agents, runtime skills, routing policy, guidance, tokens, and catalog content.

## Non-Negotiable Rules

- Use real Safari for product acceptance.
- Use the visible Registry UI for protocol creation, publishing, running, and
  run inspection.
- Use the live Telegram tab for Telegram acceptance against M1 and M2.
- Do not use M3 for this plan. M3 is registered but unavailable because Claude
  auth is not configured.
- Do not create product state with direct database writes, hidden API scripts,
  seeded records, or invisible URLs.
- Database inspection and container logs are allowed for diagnosis only.
- Do not ask again for permission to clean workspace data through the Dashboard
  UI. Permission has already been granted.
- If existing data makes testing noisy, clean it from the Dashboard UI only.
- Do not introduce parallel implementations or compatibility shims.
- Extend the existing code paths in place.
- Do not hardcode this manufacturing scenario into the product.
- Do not add built-in protocol templates, starters, galleries, accelerators, or
  dashboard shortcuts for this scenario.
- Avoid product/runtime use of the phrase "customer handoff". It may appear in
  repository planning docs only when discussing delivery process, not in
  protocol UI, run prompts, stage instructions, or generated artifacts.

## Public Manufacturing Reference Themes

Use these as public, non-proprietary design inspiration only. Do not copy
proprietary processes or imply that the generated artifact represents any real
company.

- NIST digital thread research emphasizes lifecycle traceability, standardized
  data exchange, manufacturing and quality feedback loops, and trustworthy
  product data:
  https://www.nist.gov/programs-projects/digital-thread-manufacturing
- NIST supply-chain data traceability emphasizes correct source, version,
  authorization, and trustworthiness for manufacturing-related data:
  https://www.nist.gov/ctl/smart-connected-manufacturing-systems-group/trustworthiness-and-traceability-supply-chain-data
- Corning public Manufacturing 4.0 material emphasizes AI/ML, high-resolution
  quality systems, per-unit quality "resume" style traceability, and digital
  maturity frameworks:
  https://www.corning.com/worldwide/en/the-progress-report/crystal-clear/factories-of-the-future
- Corning smart manufacturing material emphasizes AI, ML, cloud, IIoT,
  real-time collection/analysis, low-latency factory connectivity, quality,
  efficiency, and sustainability:
  https://www.corning.com/in-building-networks/worldwide/en/home/verticals/manufacturing.html
- TSMC public manufacturing material emphasizes strict process and quality
  control, fault detection and classification, advanced equipment control,
  advanced process control, process variation detection, tool matching,
  self-diagnosis, and front-end to back-end manufacturing intelligence:
  https://www.tsmc.com/english/dedicatedFoundry/manufacturing/engineering
- Tesla public solar support material emphasizes user-visible performance
  monitoring and generation over time, which is useful inspiration for clear
  manufacturing performance visualizations:
  https://www.tesla.com/support/energy/solar-panels/after-installation/understanding-system-performance

Translate those themes into generic artifact requirements:

- digital thread and genealogy from material lot to finished unit
- unit-level quality resume
- process run history and recipe context
- inline metrology and final test
- defect taxonomy and Pareto analysis
- SPC, Cp/Cpk, drift, and control limit monitoring
- FDC-style equipment health and alarm correlation
- APC-style recommended process adjustments, clearly labeled as advisory
- OEE, downtime, bottleneck, queue time, cycle time, and WIP analytics
- yield waterfall and loss attribution
- energy, water, scrap, and carbon-per-good-unit views
- lot, line, tool, chamber, shift, operator role, supplier, and material
  traceability
- explainable recommendations with source data and confidence, not black-box
  claims

## Product Readiness Prerequisites

`issues.md` is the canonical product backlog and acceptance tracker. The
manufacturing plan is a scenario runbook and should not duplicate the product
issue list. Before running this scenario for customer-facing acceptance, close
or explicitly waive the relevant blockers in `issues.md`, especially:

- P0-1 stage-scoped skill select/create/return continuity.
- P0-2 runtime/product customer-handoff language audit.
- P1-1 generic protocol authoring matrix.
- P1-2 artifact actions across all surfaces, including package default
  `index.html` surfacing and rendered text/Markdown preview.
- P1-3 conversation, run, delegation, and artifact lineage.
- P1-6 live run progress at scale.
- P1-7 desktop and narrow Safari audit.

Recently closed and kept as regression scenarios in `issues.md`:

- P1-4 true Telegram protocol parity with a fresh Telegram-started run.
- P1-5 Telegram human UX: avoid GUID-first flows, dense artifact walls, and raw
  URL overload.

Keep scenario-specific manufacturing instructions below. If a scenario run
reveals a generic product problem, add or update it in `issues.md` instead of
creating a second backlog in this file.

## Development, Test, Deploy Loop

Use this loop for every product fix.

1. Edit in:
   ```text
   /Users/tinker/output/bots/telegram-agent-bot
   ```
2. Check worktree:
   ```bash
   git status --short
   ```
3. For UI JavaScript changes:
   ```bash
   node --check octopus_registry/ui/js/components/protocol-workspace.js
   node --check octopus_registry/ui/js/components/skill-catalog.js
   node --check octopus_registry/ui/js/components/conversation-detail.js
   node --check octopus_registry/ui/js/components/dashboard.js
   ```
   Only run `node --check` for files actually changed.
4. Run focused Python tests:
   ```bash
   ./.venv/bin/python -m pytest \
     tests/test_protocols.py \
     tests/test_protocol_service.py \
     tests/test_protocol_telegram.py \
     tests/test_registry_ui_contract.py \
     tests/test_registry_sdk_contract.py \
     -q
   ```
5. Run targeted Playwright only for edited UI paths:
   ```bash
   ./.tmp/playwright/node_modules/.bin/playwright test tests/e2e/playwright/protocol-ui.spec.js
   ```
   Narrow to focused specs when possible.
6. Run:
   ```bash
   git diff --check
   ```
7. Commit and push:
   ```bash
   git add <changed files>
   git commit -m "<clear message>"
   git push
   ```
8. Pull into deployment checkout:
   ```bash
   git -C /Users/tinker/octopus pull
   ```
9. Redeploy:
   ```bash
   cd /Users/tinker/octopus
   ./octopus redeploy --yes
   ```
10. Verify status:
   ```bash
   ./octopus status
   ```
11. M3 may be stopped for missing Claude auth. That is not blocking.
12. Hard-refresh Safari:
   ```text
   Option+Command+R
   ```
13. Run real Safari acceptance before claiming the issue fixed.
14. Use container logs instead of passive sleeping:
   ```bash
   docker logs --tail 300 octopus-registry-service-1
   docker logs --tail 220 octopus-lift-and-shift-m1-bot-bot-1
   docker logs --tail 220 octopus-lift-and-shift-m2-bot-bot-1
   ```

Run the full Python suite before the final product acceptance commit if product
runtime, SDK protocol behavior, Telegram, or persistence paths changed:

```bash
./.venv/bin/python -m pytest -q
```

## Manufacturing Wow Run: UI-Only Protocol

Only start this run after the product issues above are fixed, deployed, and
verified in Safari.

### Cleanup Before Creating The Protocol

If the UI is noisy, clean workspace data first:

1. Open real Safari.
2. Go to:
   ```text
   http://127.0.0.1:8787/ui/dashboard
   ```
3. Open `Workspace maintenance`.
4. Click `Clean workspace data`.
5. Enter the current Registry UI password.
6. Type:
   ```text
   CLEAN
   ```
7. Confirm.
8. Verify M1 and M2 remain healthy.

### Protocol Identity

Create this protocol from blank in real Safari.

UI path:

```text
Build -> Protocols -> New protocol -> Start blank
```

Display name:

```text
Adaptive Manufacturing Intelligence Command Center
```

Slug:

```text
adaptive-manufacturing-intelligence-command-center
```

Description:

```text
Build and validate a browser-only manufacturing intelligence package with synthetic data, traceability, quality analytics, process performance, equipment health, and executive reporting.
```

Authoring rule:

- Assign M1 to charter, review, and validation stages.
- Assign M2 to data-generation and app-build stages.
- Do not assign M3.
- Do not use real company names, real customer rows, meeting transcripts, or
  proprietary process details in the protocol.

### Protocol Artifacts

Declare these artifacts before publishing.

| Display name | Path | Kind | Verify |
| --- | --- | --- | --- |
| Manufacturing intelligence charter | `artifacts/manufacturing-intelligence/charter.md` | `workspace_file` | yes |
| Manufacturing data model specification | `artifacts/manufacturing-intelligence/data-model.md` | `workspace_file` | yes |
| Analytics and UX specification | `artifacts/manufacturing-intelligence/app-spec.md` | `workspace_file` | yes |
| Manufacturing intelligence package | `artifacts/manufacturing-intelligence/package` | `workspace_file` package directory | yes |
| Manufacturing validation report | `artifacts/manufacturing-intelligence/validation-report.md` | `workspace_file` | yes |
| Executive review memo | `artifacts/manufacturing-intelligence/executive-review.md` | `workspace_file` | yes |

Expected artifact key names to record during the run:

- `manufacturing_intelligence_charter`
- `manufacturing_data_model_specification`
- `analytics_and_ux_specification`
- `manufacturing_intelligence_package`
- `manufacturing_validation_report`
- `executive_review_memo`

If the UI generates slightly different keys, record the actual keys from the
run artifact tab and use those actual keys in Telegram.

### Stage 1

Display name:

```text
Define manufacturing intelligence charter
```

Participant:

```text
M1
```

Inputs:

```text
None
```

Outputs:

```text
Manufacturing intelligence charter
```

Instructions:

```text
Produce artifacts/manufacturing-intelligence/charter.md.

Define a privacy-safe, generic manufacturing intelligence objective for an offline browser package. The target user is a manufacturing manager who needs repeatable insight across materials, process stages, equipment, quality, test, defects, throughput, energy, and shipment readiness. Do not use real company names, real people, meeting transcript text, customer data, or proprietary process details.

The charter must explain the management questions the package should answer:
- What is my current yield and where is yield lost?
- Which lines, tools, chambers, recipes, shifts, suppliers, or material lots are driving defects?
- How do process parameters drift across stages?
- Which units, lots, panels, wafers, or modules have a complete quality resume?
- Which equipment states, alarms, maintenance events, or queue times predict quality loss?
- Where are bottlenecks, downtime, WIP aging, and cycle time losses?
- Which energy, water, scrap, and carbon-per-good-unit patterns matter?
- What recommendations should a manager review today, and what evidence supports them?

The charter must keep the product generic. Manufacturing examples are only sample content for this protocol run.
```

Transition:

```text
completed -> Design synthetic manufacturing data model
```

### Stage 2

Display name:

```text
Design synthetic manufacturing data model
```

Participant:

```text
M2
```

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

The model must include at least these CSV tables and relationships:
- plants.csv: plant_id, region, timezone, product_family, capacity class
- lines.csv: line_id, plant_id, area, process_family, takt target
- tools.csv: tool_id, line_id, tool_type, vendor_class, chamber_count, criticality
- recipes.csv: recipe_id, product_family, process_step, revision, target window fields
- material_lots.csv: material_lot_id, supplier_class, material_type, received_at, incoming_quality fields
- work_orders.csv: work_order_id, product_family, priority, due_date, planned_quantity
- units.csv: unit_id, work_order_id, current_status, product_family, build_start, build_end
- unit_genealogy.csv: parent_unit_id, child_unit_id, relationship_type, material_lot_id
- process_runs.csv: run_id, unit_id, lot_id, line_id, tool_id, chamber_id, recipe_id, process_step, started_at, ended_at, operator_role, shift
- process_measurements.csv: measurement_id, run_id, metric_name, metric_value, target, lower_spec, upper_spec, unit
- metrology_results.csv: metrology_id, unit_id, run_id, station_id, metric_name, value, lower_spec, upper_spec, method
- inspection_defects.csv: defect_id, unit_id, run_id, defect_code, defect_family, severity, x_position, y_position, image_feature_score
- electrical_tests.csv: test_id, unit_id, test_stage, voltage, current, power, efficiency, leakage, bin, pass_fail
- reliability_tests.csv: reliability_id, unit_id, test_type, duration_hours, stress_condition, degradation_rate, pass_fail
- tool_events.csv: event_id, tool_id, chamber_id, event_type, started_at, ended_at, severity, alarm_code
- maintenance_events.csv: maintenance_id, tool_id, chamber_id, maintenance_type, started_at, ended_at, replaced_part_class
- environmental_energy.csv: record_id, plant_id, line_id, hour, energy_kwh, water_liters, temperature_c, humidity_pct
- quality_dispositions.csv: disposition_id, unit_id, disposition, reason_code, reviewer_role, disposition_at
- shipments.csv: shipment_id, unit_id, customer_segment, ship_date, final_quality_grade

The specification must define primary keys, foreign keys, expected row counts, realistic synthetic distributions, intentional correlations, and defects. Include at least these engineered signals:
- one supplier class with elevated incoming contamination risk
- one tool chamber with subtle drift before a maintenance event
- one recipe revision with better yield but longer cycle time
- one line/shift combination with higher defect escape risk
- one process measurement that correlates with electrical performance
- one environmental condition that correlates with downtime or rework
- one false-positive correlation that the app should label as low confidence

The data model must support dynamic schema inference after user uploads arbitrary CSVs. The app must not depend on this exact default schema.
```

Transition:

```text
completed -> Specify analytics and user experience
```

### Stage 3

Display name:

```text
Specify analytics and user experience
```

Participant:

```text
M1
```

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

Required app capabilities:
- upload multiple arbitrary CSV files
- inspect schema profiles, row counts, missingness, data types, numeric ranges, categorical cardinality, date ranges, and sample values
- infer candidate primary keys and foreign keys from names, uniqueness, value overlap, and key-like patterns
- render a relationship graph and require user confirmation before using relationships for joins
- generate default synthetic manufacturing data using the data model
- after upload, generate synthetic data that follows uploaded schemas, data types, value patterns, and confirmed relationships
- let the user select source table, group fields, metric fields, aggregation functions, filters, and optional join path
- render executive KPI cards, yield waterfall, defect Pareto, process drift/SPC chart, Cpk/Ppk summary, tool health timeline, cycle time/WIP bottleneck view, energy per good unit, relationship graph, and heat maps
- produce an action review panel with recommendations, confidence, evidence, and caveats
- export selected tables, aggregate results, relationship map, and a management report
- include a privacy/offline indicator explaining that rows remain in the browser

Required visual quality:
- professional, dense but readable
- no marketing landing page
- no giant decorative hero
- no one-note color palette
- no overlapping text on desktop or narrow Safari
- progressive workflow: load data, confirm relationships, analyze, report
```

Transition:

```text
completed -> Build offline manufacturing intelligence package
```

### Stage 4

Display name:

```text
Build offline manufacturing intelligence package
```

Participant:

```text
M2
```

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

The package must contain:
- index.html
- README.md
- data-dictionary.md
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
- validation-report.md

index.html must be a self-contained browser SPA. It must run without a backend. It must not require network access. Use inline or embedded JavaScript and CSS. Do not use external CDNs unless all required code is embedded into the package. Prefer browser-native APIs and small purpose-built code.

The sample data must be internally consistent and impressive. Include enough rows to make charts meaningful, but keep the package usable in Safari. Target approximately:
- 2 plants
- 5 lines
- 30 tools
- 80 recipes/revisions
- 60 material lots
- 120 work orders
- 1,200 units
- 1,500 genealogy rows
- 7,000 process runs
- 30,000 process measurements
- 3,000 metrology rows
- 2,000 inspection defect rows
- 1,200 electrical test rows
- 400 reliability rows
- 1,000 tool events
- 300 maintenance events
- 1,500 environmental/energy records
- 1,200 quality dispositions
- 900 shipments

If performance requires smaller samples, reduce row counts while preserving all tables and relationships. Record final row counts in README.md and validation-report.md.

The app must have default synthetic data generation built in. It must also let a user upload the generated sample CSV files back into the app and reach similar analyses.

The app must include clear manufacturing-manager views:
- executive overview
- yield and loss waterfall
- defect Pareto and defect heat map
- unit genealogy and quality resume
- process drift and SPC
- equipment health and FDC-style event correlation
- cycle time, WIP aging, and bottleneck view
- energy, water, scrap, and carbon-per-good-unit view
- recommendation queue with evidence and confidence

Do not mention real company names or real customer data in the generated package. Use synthetic plant, line, tool, recipe, lot, and unit identifiers.
```

Transition:

```text
completed -> Validate package completeness
```

### Stage 5

Display name:

```text
Validate package completeness
```

Participant:

```text
M1
```

Inputs:

```text
Manufacturing intelligence package
Analytics and UX specification
Manufacturing data model specification
```

Outputs:

```text
Manufacturing validation report
Manufacturing intelligence package
```

Instructions:

```text
Inspect artifacts/manufacturing-intelligence/package and produce artifacts/manufacturing-intelligence/validation-report.md. Also update artifacts/manufacturing-intelligence/package/validation-report.md if needed.

Validate:
- required files exist
- index.html is self-contained and browser-oriented
- no external network dependency is required
- sample CSV headers match the data model
- primary and foreign key relationships are represented
- synthetic default data path exists
- upload/adapted synthetic path exists
- relationship confirmation path exists
- dashboards cover yield, defects, quality, process drift, equipment, cycle time, energy, and recommendations
- README gives a non-technical manufacturing manager enough instructions to use the package

Do not claim real Safari execution from inside this stage. This stage is package completeness and static/browser-readiness validation only. The human operator will perform real Safari acceptance after the run.
```

Transition:

```text
completed -> Prepare executive review
```

### Stage 6

Display name:

```text
Prepare executive review
```

Participant:

```text
M1
```

Inputs:

```text
Manufacturing intelligence charter
Manufacturing data model specification
Manufacturing intelligence package
Manufacturing validation report
```

Outputs:

```text
Executive review memo
Manufacturing intelligence package
```

Instructions:

```text
Produce artifacts/manufacturing-intelligence/executive-review.md and update artifacts/manufacturing-intelligence/package/reports/management-brief.md if needed.

Write for a manufacturing manager. Explain what the generated package proves, what sample data is included, what decisions the dashboards support, and how a manager should interpret the recommendations. Include a concise "morning review" sequence:
1. Check executive KPIs.
2. Review yield waterfall.
3. Inspect defect Pareto and heat map.
4. Open the highest-risk tool/line/recipe signal.
5. Review unit quality resumes for affected units.
6. Check bottleneck and cycle time impact.
7. Check energy/scrap impact.
8. Export the management report.

Include limitations: synthetic data only, heuristic relationship inference, recommendations are decision support, and production closed-loop control requires IT/OT validation.
```

Transition:

```text
completed -> complete
```

### Validate And Publish

In the Registry UI:

1. Click `Validate`.
2. Fix any validation errors through the visible UI.
3. Click `Publish`.
4. Confirm the state changes to `PUBLISHED`.
5. Confirm `Run protocol` is visible.

Do not publish if any stage instruction contains real names, company names,
meeting transcript text, proprietary data, or product-hardcoding language.

### Run Inputs

Click `Run protocol`.

Entry agent:

```text
M1
```

Workspace:

```text
default
```

Goal:

```text
Create and validate a customer-facing offline browser package that demonstrates a state-of-the-art generic manufacturing intelligence command center. The package must include a comprehensive synthetic manufacturing data model, sample CSV files, an offline index.html SPA, manager-ready reports, and validation notes. It should help a manufacturing manager explore yield, defects, quality, process drift, equipment health, cycle time, WIP, energy, scrap, and recommendations without sending raw rows to any backend.
```

Context:

```text
Use only synthetic, privacy-safe, non-proprietary manufacturing examples. The sample domain may blend patterns from advanced solar/module, precision glass, battery, and semiconductor-style factories, but do not use real company names, real factory names, real product names, real customer names, meeting transcript text, or proprietary process details. The Octopus product must remain generic; this manufacturing scenario is only a user-authored protocol run.
```

Constraints:

```text
Final artifact must be a browser-only offline package at artifacts/manufacturing-intelligence/package. It must contain index.html, README.md, data dictionary, sample CSVs, management reports, and validation report. The app must run without a backend and without external network access. It must infer schemas and relationship candidates from uploaded CSVs, require user confirmation before joins, generate default synthetic manufacturing data, adapt synthetic generation to uploaded schemas and confirmed relationships, render charts and heat maps, and export useful outputs. Recommendations must be explainable decision support, not automatic control instructions.
```

Declared artifacts:

```text
artifacts/manufacturing-intelligence/charter.md
artifacts/manufacturing-intelligence/data-model.md
artifacts/manufacturing-intelligence/app-spec.md
artifacts/manufacturing-intelligence/package containing index.html, README.md, data-dictionary.md, reports/*.md, samples/*.csv, and validation-report.md
artifacts/manufacturing-intelligence/validation-report.md
artifacts/manufacturing-intelligence/executive-review.md
```

### Live Run Monitoring

Use real Safari:

1. Open `Work -> Runs`.
2. Open the new run.
3. Keep the run page visible during execution.
4. Verify the progress rail shows the current stage without dense overload.
5. Verify M2 receives the build stage.
6. Expand stage details as work progresses.
7. Use logs to avoid passive waiting:
   ```bash
   docker logs --tail 300 octopus-registry-service-1
   docker logs --tail 220 octopus-lift-and-shift-m1-bot-bot-1
   docker logs --tail 220 octopus-lift-and-shift-m2-bot-bot-1
   ```
8. If a stage fails, use UI actions only:
   - inspect issue
   - send back with precise feedback
   - retry
   - cancel only if unrecoverable
9. Record every product usability issue in `issues.md`.
10. If a product blocker is found, fix the product generically, test, commit,
    push, pull, redeploy, hard-refresh Safari, clean data if needed, and rerun.

### Artifact Verification In Real Safari

After the run completes:

1. In the run artifact tab, verify all declared artifacts are present and
   verified.
2. For `Manufacturing intelligence package`, test:
   - `Open`
   - `Contents`
   - `Download`
   - `Copy path`
3. In `Contents`, verify at least:
   - `index.html`
   - `README.md`
   - `data-dictionary.md`
   - `validation-report.md`
   - `reports/management-brief.md`
   - `reports/analytics-methods.md`
   - `reports/sample-insights.md`
   - all sample CSV files listed in Stage 4
4. Open `index.html` from the package action in Safari.
5. First-load checks:
   - app renders without backend
   - no real company/customer/meeting text
   - privacy/offline indicator visible
   - load/generate/analyze/report workflow visible
   - no text overlap on desktop Safari
6. Generate default synthetic data:
   - verify all default tables exist
   - verify row counts are displayed
   - verify schema cards render
   - verify relationship candidates render as suggestions
7. Confirm relationships:
   - accept at least three relationships, including one genealogy relationship,
     one process-run relationship, and one quality/test relationship
   - verify accepted candidates move into confirmed relationships
   - verify candidate counts and confirmed counts visibly update
8. Analytics:
   - run default executive analysis
   - inspect yield waterfall
   - inspect defect Pareto
   - inspect process drift/SPC
   - inspect Cpk/Ppk summary if implemented
   - inspect tool health/FDC-style view
   - inspect cycle time/WIP bottleneck view
   - inspect energy/scrap view
   - inspect heat map
   - inspect recommendation queue
9. Upload loopback:
   - from package contents, download sample CSVs or use the package download
   - upload multiple sample CSVs into the generated SPA
   - verify schema inference
   - verify relationship suggestions
   - confirm relationships
   - run analysis on uploaded data
10. Adapted synthetic data:
    - generate synthetic data after uploads
    - verify generated fields follow uploaded schemas
    - verify confirmed relationships are preserved
    - verify rows are not copied wholesale
11. Exports:
    - export aggregate results
    - export relationship map
    - export management report
    - export one sample/generated CSV
12. Clear/reset:
    - clear the session
    - verify counters, charts, tables, relationship state, and status text reset
13. Narrow Safari:
    - repeat first-load, generate, relationship, analysis, and export smoke
      checks in a narrow window
    - verify no unreachable controls or overlapping text

### Artifact Quality Bar

The artifact is not accepted unless it would matter to a manufacturing manager.
It must show:

- not just charts, but actionable views
- not just synthetic CSVs, but an internally consistent digital thread
- not just correlations, but evidence and caveats
- not just uploads, but schema inference and relationship confirmation
- not just default data, but adapted synthetic generation from uploaded schemas
- not just one dashboard, but manager workflows for morning review,
  containment, root-cause exploration, and export/reporting

## Telegram Acceptance With The Manufacturing Run

After the manufacturing run exists in Registry, test Telegram against it.

1. In the Telegram tab, send:
   ```text
   /protocol list
   ```
2. Confirm `adaptive-manufacturing-intelligence-command-center` is listed after
   publication.
3. Start a small Telegram smoke run against a lightweight protocol first. If
   that passes, optionally start the manufacturing protocol from Telegram using
   a shorter goal:
   ```text
   /protocol start adaptive-manufacturing-intelligence-command-center Create the offline manufacturing intelligence package from the published protocol instructions using synthetic data only.
   ```
4. Record the returned run id.
5. Watch and inspect:
   ```text
   /protocol watch <run_id>
   /protocol status <run_id>
   /protocol artifacts <run_id>
   /protocol export <run_id>
   ```
6. Download the package or a smaller artifact:
   ```text
   /protocol artifacts <run_id> download manufacturing_intelligence_package
   ```
7. If the artifact key differs, use the actual key shown by
   `/protocol artifacts <run_id>`.
8. Open the same run in Registry Safari and verify:
   - same run status
   - same current/completed stage
   - same artifact state
   - downloaded artifact matches Registry artifact
9. Stop watching:
   ```text
   /protocol unwatch <run_id>
   ```

If Telegram cannot express the richer generic launch fields needed for serious
protocol starts, record that as a parity defect and fix it through the shared
SDK launch form path before calling Telegram parity complete.

## Final Documentation Updates

After product fixes and the manufacturing run are verified, update:

- `issues.md`
  - close fixed issues with run ids and evidence
  - leave only verified remaining risks
- `README.md`
  - keep product-neutral protocol capabilities current
  - do not make manufacturing the product identity
- `docs/ARCHITECTURE.md`
  - update only architecture-level facts
  - preserve SDK/Registry ownership boundaries
- `docs/examples/offline-csv-analytics.md`
  - do not replace it with manufacturing content
- new scenario doc if needed:
  `docs/examples/manufacturing-intelligence.md`
  - include repeatable UI-only protocol creation steps
  - include sanitized run inputs
  - include artifact verification checklist
  - keep it explicitly scenario-specific

## Final Acceptance Criteria

All of the following must be true before this plan is complete:

- Dashboard cleanup is verified in real Safari.
- Skill select/create/return works from stage context in real Safari.
- Protocol authoring matrix passes in real Safari.
- Product/runtime prompt paths do not leak internal delivery language.
- Artifact actions are consistent across run, stage, conversation linked work,
  task/delegation detail, dashboard references where present, and Telegram.
- Conversations, runs, delegations, and artifacts read as one lineage.
- Telegram can list, start, status, watch, export, and inspect/download
  artifacts through shared SDK protocol behavior.
- Run progress remains readable on the multi-stage manufacturing protocol.
- Desktop and narrow Safari audits pass.
- The manufacturing protocol is created from blank through the UI only.
- The manufacturing protocol runs successfully with M1 and M2 only.
- The final package opens from the run UI in real Safari.
- The generated SPA works offline in Safari.
- The generated default data model is comprehensive and internally consistent.
- The generated SPA can upload multiple CSVs, infer schemas, propose and
  confirm relationships, generate adapted synthetic data, run analytics, render
  charts/heat maps, and export outputs.
- `issues.md`, README, architecture docs, and scenario docs reflect the actual
  verified state.
- Final code/docs are committed and pushed from
  `/Users/tinker/output/bots/telegram-agent-bot`.
- Deployment checkout `/Users/tinker/octopus` is pulled and redeployed.
- `./octopus status` shows Registry, M1, and M2 healthy. M3 missing Claude auth
  remains non-blocking unless that changes.
