# Local Manufacturing Analytics Demo

This guide is the customer-safe demo for analytics and reporting when the
customer does not want proprietary CSV rows sent to a model provider.

## Demo Message

Octopus can help build repeatable local analytics tooling. The assistant
generates and reviews code. The code runs inside the customer's workspace
against local files. The customer decides which summaries, logs, and output
artifacts are shared back into the conversation or protocol run.

Safe claim for this demo:

- raw CSVs stay in the local workspace
- model-visible context is limited to schema, counts, relationship checks, and
  aggregate summaries
- scripts process the files locally
- findings, flags, charts, and manifests are generated as local artifacts
- the workflow can be repeated as a protocol run

Do not claim absolute data isolation unless the deployment enforces that
boundary technically.

## Customer Scenario

The customer has manufacturing data from several process stages:

- cell or component records
- panel or assembly records
- mapping records that relate components to assemblies
- test results by manufacturing stage

The files have primary and foreign keys such as `panel_id` and `cell_id`.
The user wants to detect how parameters change across stages, identify defect
signals, and produce a daily repeatable report without uploading raw data.

## UI-First Protocol Build

The customer-facing proof is not the built-in template and not a database seed.
Build a protocol manually in the Registry UI so the customer can repeat the
same steps.

Create a protocol named:

```text
Manufacturing Analytics App Builder
```

Suggested stages:

1. define browser app contract
2. build self-contained browser app
3. review browser app

Suggested artifacts:

- `apps/manufacturing-analytics/index.html`
- `reports/app-review.md`

Stage instructions should ask the agent to generate a single self-contained
HTML/CSS/JavaScript app. The app must let a user generate synthetic
manufacturing data, upload local CSVs, define primary/foreign keys, run
in-browser analytics, view findings, and export reports. The app must not make
network calls for uploaded data.

From the protocol page, click `Run protocol`, choose an entry agent, and fill:

- `What should this run accomplish?`: build a self-contained manufacturing
  analytics browser app for process-stage CSVs.
- `Files or data context`: panels, cells, panel-to-cell mapping, and test
  result CSV files may exist locally, but raw customer rows must not be pasted
  into chat.
- `Keys and relationships`: `panels.panel_id -> test_results.panel_id`,
  `panels.panel_id -> panel_cells.panel_id`, `cells.cell_id ->
  panel_cells.cell_id`.
- `Expected outputs`: self-contained `index.html`, app review notes, exportable
  findings.
- `Privacy or execution constraints`: raw private rows stay local; the model
  may receive schema, aggregate summaries, and app requirements only.

Open the run from the Runs page, then use the artifact actions to open or
download `apps/manufacturing-analytics/index.html`. In the opened app, generate
synthetic data or upload local sample CSVs, run analytics, and export the
findings.

## Starter Template And Golden Script

The repository also contains a starter manufacturing analytics template and a
deterministic local script. These are useful for regression testing and for a
known-good reference, but they are not a substitute for the UI-first customer
flow above.

The starter template is:

```text
Manufacturing Local Analytics
```

It is available from `Build -> Protocols -> New protocol -> Use template`.

The starter template stages are:

1. define input contract
2. generate profile script
3. run profile locally
4. generate analysis script
5. run analysis locally
6. validate outputs
7. review report

The starter template artifacts are:

- `protocol/input_contract.json`
- `scripts/profile_manufacturing_data.py`
- `reports/profile_summary.md`
- `reports/model_visible_context.md`
- `scripts/analyze_manufacturing_quality.py`
- `reports/quality_flags.csv`
- `reports/defect_summary.csv`
- `reports/manufacturing_findings.md`
- `reports/defect_heatmap.html`
- `reports/run_manifest.json`

## Automated Golden Demo

Run the deterministic local demo from a fresh clone:

```bash
./.venv/bin/python scripts/demo/manufacturing_local_analytics/run_demo.py \
  --workspace .tmp/demo/manufacturing-local-analytics
```

The command creates synthetic manufacturing CSVs, copies the local scripts into
the workspace, runs the profiler and analyzer, validates privacy checks, and
writes the full artifact set.

Expected output includes:

- `reports/manufacturing_findings.md`
- `reports/quality_flags.csv`
- `reports/defect_summary.csv`
- `reports/defect_heatmap.html`
- `reports/run_manifest.json`

Known deterministic findings:

- Vendor `V2` has elevated high-risk rate.
- High lamination temperature appears in the flagged population.
- Night-shift records contain missing final test rows.

## Registry Rehearsal Demo

If the registry is running and you have the UI token, the same command can
create a real protocol draft from the built-in template, publish it, start a
rehearsal run, and attach the generated local artifacts through the run artifact
APIs:

```bash
REGISTRY_UI_TOKEN=<token> \
OCTOPUS_REGISTRY_URL=http://127.0.0.1:8787 \
./.venv/bin/python scripts/demo/manufacturing_local_analytics/run_demo.py \
  --workspace .tmp/demo/manufacturing-local-analytics \
  --require-registry
```

Open the run shown in `reports/run_manifest.json` and review the artifacts.
This is a rehearsal run: external transports are gated, but the run, stages,
and artifact content use the same protocol/run/artifact surfaces as normal
authoring.

For customer acceptance, prefer the UI-first `Run protocol` flow. Rehearsal is
for authoring validation, not proof of provider-backed execution.

## Telegram Inspection

After a run exists, Telegram can inspect it through the same protocol service:

```text
/protocol status <run_id>
/protocol artifacts <run_id>
/protocol artifacts <run_id> download <artifact_key>
```

Use the download command for concrete artifacts when the bot should send the
file into the chat instead of only linking back to Registry.

## Live Conversation Script

Use this when demonstrating the product to a customer:

```text
We are not going to paste your CSV rows into chat. We will ask Octopus to build
scripts that run locally. The only information we share with the model is the
schema, row counts, relationship checks, aggregate profile, logs, and selected
outputs we approve.
```

Then ask the agent:

```text
Use the Manufacturing Local Analytics skill.

Build a local manufacturing analytics pipeline for CSV files in ./data.

Privacy rule: do not ask me to paste raw CSV rows into chat. Write scripts that
run locally against the files. If you need to inspect the data, create a
profiling script that outputs table names, columns, row counts, missing-value
counts, relationship checks, and aggregate summaries only.

Expected files:
- data/panels.csv
- data/cells.csv
- data/panel_cells.csv
- data/test_results.csv

Join keys:
- panels.panel_id -> panel_cells.panel_id
- panels.panel_id -> test_results.panel_id
- cells.cell_id -> panel_cells.cell_id

Create:
- scripts/profile_manufacturing_data.py
- scripts/analyze_manufacturing_quality.py
- reports/profile_summary.md
- reports/model_visible_context.md
- reports/manufacturing_findings.md
- reports/quality_flags.csv
- reports/defect_summary.csv
- reports/defect_heatmap.html
- reports/run_manifest.json

The report should flag vendor, shift, line, temperature, missing final tests,
and hotspot/visual defect signals. Make the scripts deterministic and safe to
rerun.
```

## What To Show

1. Open `reports/model_visible_context.md` and point out that it contains schema
   and aggregates, not raw source rows.
2. Open `scripts/analyze_manufacturing_quality.py` and explain that it reads
   local files.
3. Open `reports/manufacturing_findings.md` and show the executive summary.
4. Open `reports/quality_flags.csv` and show panel-level output generated by
   the local script.
5. Open `reports/defect_heatmap.html` and show the renderable chart artifact.
6. Open `reports/run_manifest.json` and show validation status and artifact
   paths.

## What To Avoid

- Do not use real customer CSVs in a sales demo.
- Do not paste raw rows into the conversation.
- Do not upload private files to the model.
- Do not claim prediction when the demo only proves detection and correlation.
- Do not present rehearsal as provider-backed autonomous execution.
- Do not hide script failures. Use failures to show local iteration.

## Success Criteria

The customer should understand:

- Octopus can help build local analytics code without raw data prompts.
- Scripts can transform local CSVs into repeatable reports.
- Generated reports and scripts are visible as artifacts.
- Protocols make the workflow repeatable.
- The product boundary is honest: the model helps write and revise tooling; the
  local runtime processes private data.
