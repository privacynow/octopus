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
  `docs/local-data-analytics-demo.md`
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

## Open Issues To Close

### P0-1: Workflow Builder Skill Continuity

Problem:

- In the protocol builder, skill selection can send the user to a generic Skills
  page with no stage context.
- The user cannot reliably select or create a skill and return to the same
  stage with the assignment preserved.

Implementation:

1. Inspect the stage assignment UI in `protocol-workspace.js`.
2. Inspect the skill catalog surface in `skill-catalog.js`.
3. Implement one coherent stage-scoped skill flow:
   - search existing skills from the stage assignment context
   - select an existing skill for the current stage
   - mark or create a needed new skill for the current stage
   - return to the same stage with draft data preserved
4. If full-page Skills navigation remains available, pass explicit return
   context and render a contextual `Use for current stage` action.
5. Do not create a second skill model.
6. Do not use "capability" as the user-facing noun.

Tests:

- Unit/contract:
  `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_protocols.py -q`
- Browser:
  targeted Playwright coverage for stage-scoped skill select/create/return.
- Real Safari:
  create a blank protocol and verify:
  - stage with no assignment
  - stage with skill only
  - stage with agent only
  - stage with skill plus agent
  - stage with needed new skill
  - no stage data is lost after skill selection

### P0-2: Runtime/Product Customer-Handoff Language Audit

Problem:

- Runtime prompts or generated protocol instructions must not mention internal
  delivery concepts such as "customer handoff" unless the user explicitly typed
  those words.

Implementation:

1. Search:
   ```bash
   rg -n "customer handoff|handoff guide|handoff" README.md docs issues.md octopus_registry octopus_sdk app tests
   ```
2. Separate repository planning docs from runtime/product paths.
3. Remove the phrase from:
   - run launch UI copy
   - protocol prompt builders
   - default protocol instructions
   - negative prompt text
   - generated artifact expectations
   - tests that assert runtime wording
4. Keep delivery-process wording only in planning/docs when it is not fed to
   agents or surfaced in product UI.

Tests:

- `./.venv/bin/python -m pytest tests/test_protocols.py tests/test_protocol_service.py tests/test_registry_ui_contract.py -q`
- Real Safari:
  create and run a small generic protocol. Inspect run inputs, stage
  instructions, generated artifact names, and generated artifact content.
  Confirm the phrase is absent unless typed by the user.

### P1-1: Protocol Authoring Matrix

Problem:

- Protocol authoring has improved, but the full assignment and artifact matrix
  has not been reverified after recent changes.

Implementation:

- Fix any discovered product defects in `protocol-workspace.js` in the existing
  protocol authoring pipeline.
- Do not add new routes or alternate editors for the same behavior.

Real Safari matrix:

1. Clean data if the existing UI state is noisy.
2. Create a blank protocol named `Protocol Authoring Matrix Verification`.
3. Add stages covering:
   - no assignment
   - skill only
   - agent only
   - skill plus preferred agent
   - needed new skill
   - add stage below current stage
   - remove stage
   - reorder or navigate stages
   - edit artifacts inside stage context
   - open workflow map on demand
4. Validate and publish.
5. Confirm all draft data is preserved.

### P1-2: Artifact Action Consistency

Problem:

- Package artifact actions are verified from the run artifact page, but not
  across every surface.

Implementation:

1. Reuse `UI.createArtifactActionRow` and `_protocolArtifactActionRow`.
2. Do not create surface-specific artifact action implementations.
3. Ensure artifact states and actions are consistent for:
   - run overview
   - run artifacts tab
   - stage detail
   - conversation linked work
   - delegation/task detail
   - dashboard references
   - Telegram artifact commands
4. For package/directory artifacts, actions should be:
   - `Open` loads an appropriate default file, usually `index.html` when
     present
   - `Contents` lists package contents
   - `Download` downloads the package as a zip
   - `Copy path` copies the workspace path

Tests:

- `./.venv/bin/python -m pytest tests/test_registry_ui_contract.py tests/test_registry_sdk_contract.py tests/test_protocol_telegram.py -q`
- Real Safari:
  use one completed run and inspect the same package artifact from every
  available UI surface.
- Live Telegram:
  use `/protocol artifacts <run_id>` and
  `/protocol artifacts <run_id> download <artifact_key>`.

### P1-3: Conversations, Runs, And Delegations Need One Lineage

Problem:

- Conversations, runs, stage work, delegations, and artifacts can still feel
  like separate apps instead of one lineage.

Implementation:

1. Inspect `conversation-detail.js`, `conversation-list.js`, and
   `protocol-workspace.js`.
2. Ensure conversation linked work subscribes to run updates and shows useful
   state without requiring the user to click away and back.
3. Ensure run stage detail points to the routed task/delegation where relevant.
4. Ensure task/delegation detail points back to the run/stage/conversation.
5. Keep routed tasks as runtime internals; present them as linked work where
   possible.

Tests:

- Start work from a conversation in real Safari.
- Route work to M2 using `@m2`.
- Start a protocol from the UI where supported.
- Navigate:
  conversation -> linked run/delegation -> artifact -> run -> conversation.
- Confirm no blank full-activity view.

### P1-4: Telegram Protocol Parity

Problem:

- Telegram protocol behavior needs live verification.
- Telegram currently supports `/protocol start <slug> <problem statement>`, but
  the shared launch model supports richer generic fields. If Telegram cannot
  express context, constraints, expected outputs, or protocol-authored
  `metadata.run_inputs`, that is a parity gap to fix through the shared SDK
  launch helpers, not a parallel Telegram implementation.

Implementation:

1. Inspect `app/runtime/telegram_ingress.py`,
   `app/runtime/telegram_protocols.py`, `app/presentation/telegram.py`, and
   `octopus_sdk/protocols/launch.py`.
2. Preserve the simple one-line start command.
3. Add a coherent Telegram path for richer launch inputs if missing. Acceptable
   approaches:
   - guided multi-message launch session based on `protocol_run_launch_form`
   - a structured command that maps to the same SDK launch request
   - a documented fallback where only `problem_statement` is supported, if the
     product decision is to keep Telegram lightweight
4. The chosen path must call the shared SDK protocol service and must not
   duplicate protocol execution logic.
5. Ensure artifact listing and download use the canonical artifact routes.

Live Telegram acceptance:

1. Use the Telegram browser tab already opened by the operator.
2. Use M1/M2 only.
3. Send:
   ```text
   /protocol list
   ```
4. Start a small verification protocol:
   ```text
   /protocol start telegram-parity-smoke Build a tiny verification report and produce the declared artifact.
   ```
5. Record the returned run id.
6. Send:
   ```text
   /protocol watch <run_id>
   /protocol status <run_id>
   /protocol artifacts <run_id>
   /protocol export <run_id>
   ```
7. After completion, download at least one artifact:
   ```text
   /protocol artifacts <run_id> download <artifact_key>
   ```
8. Open the same run in Registry Safari and confirm status/artifacts match.
9. Send:
   ```text
   /protocol unwatch <run_id>
   ```

### P1-5: Run Progress At Scale

Problem:

- The latest small run was understandable, but larger protocols need proof that
  progress stays visual, bounded, and human-readable.

Implementation:

1. Reuse one stage-progress component or one shared rendering function.
2. Do not create separate run-list, run-detail, and conversation progress
   implementations.
3. For more than five stages, show a bounded rail:
   - previous
   - current
   - next
   - compressed before/after groups
4. Show completed, running, waiting, failed, skipped, and stale states with
   accessible text labels.
5. Use restrained animation only for real active progress.

Tests:

- Create and run the manufacturing protocol in this plan. It has enough stages
  to prove scale.
- Observe active progress in real Safari without relying on sleeps. Use logs
  when needed to know whether work is moving.
- Verify current stage remains visible and understandable.
- Verify a human can tell whether the run is healthy, blocked, failed, or done.

### P1-6: Desktop And Narrow Safari Audit

Problem:

- Recent work has not had a complete desktop and narrow Safari audit.

Acceptance:

1. Desktop Safari, normal window:
   - Dashboard
   - Protocols
   - Protocol editor
   - Run list
   - Run detail
   - Stage detail
   - Artifact package open/contents/download
   - Conversation linked work
   - Skills stage-scoped flow
2. Narrow Safari:
   - repeat the same high-risk surfaces
   - no overlapping text
   - no unreachable panels
   - no unusable side-by-side panes
   - progressive UI remains readable

### P2-1: Clean Clone And Self-Service Docs

Problem:

- Clean clone setup remains unproven.

Implementation:

1. Audit README and docs for current architecture, setup, and protocol use.
2. Ensure docs distinguish:
   - product-neutral protocol authoring
   - scenario-specific manufacturing demo
   - cleanup/admin steps
   - Telegram protocol commands
3. Do not tilt README or architecture docs toward this manufacturing scenario.
4. Scenario-specific instructions belong in a scenario guide or this plan.

Verification:

- Use the documented start flow in a clean environment when practical.
- At minimum, run docs consistency checks and verify setup commands are current.

### P2-2: Dashboard Cleanup Verification

Problem:

- Cleanup UI needs post-deploy Safari verification.

Current UI behavior:

- Dashboard -> Workspace maintenance -> Clean workspace data
- Dialog asks for Registry UI password and `CLEAN`.
- It removes conversations, tasks, protocols, runs, artifacts, events, and
  deliveries.
- It preserves agents, runtime skills, routing policy, guidance, tokens, and
  catalog content.

Acceptance:

1. In real Safari, open Dashboard.
2. Click `Clean workspace data`.
3. Enter the current Registry UI password.
4. Type:
   ```text
   CLEAN
   ```
5. Confirm cleanup.
6. Verify agents M1 and M2 remain registered and healthy.
7. Verify skills and guidance are still present.
8. Verify old conversations, protocol definitions, runs, artifacts, and events
   are gone from the default UI.

### P2-3: Stale/Interrupted Run Recovery

Problem:

- Stale leases and interrupted runs need visible recovery behavior.

Implementation:

1. Use the existing run issue filter options:
   - blocked runs
   - contract errors
   - stuck leases
   - expired timeouts
2. Do not create a separate recovery model.
3. Make terminal/retryable states visible in the run UI.
4. Ensure retry/send-back/cancel actions carry expected version and show clear
   results.

Acceptance:

- Start a disposable protocol run.
- Interrupt or stop the execution path in a controlled way only if safe.
- Verify the run issue appears in the correct filter.
- Use UI action to retry/cancel/send back.
- Confirm the run state and timeline explain what happened.

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

Expected outputs:

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
- `docs/local-data-analytics-demo.md`
  - do not replace it with manufacturing content
- new scenario doc if needed:
  `docs/manufacturing-intelligence-demo.md`
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
