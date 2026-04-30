# Offline CSV Analytics SPA Scenario Guide

This guide captures the verified UI-only path for turning a blank protocol into
a browser-based offline CSV analytics SPA. It is intentionally scenario-specific
documentation. Do not turn these prompts, field labels, artifacts, or sample
domain terms into product defaults.

The customer-safe boundary is:

- do not paste real customer rows, names, meeting text, or proprietary details
  into protocol instructions or run inputs
- use generic local-CSV analytics wording in the product
- keep uploaded CSV processing inside the generated browser app
- use synthetic sample data for demonstration and validation
- treat inferred relationships as suggestions until the user confirms them

## Expected Final Artifact

The user-facing deliverable is:

- `artifacts/offline-analytics-package/index.html`

Supporting files inside the package:

- `artifacts/offline-analytics-package/README.md`
- `artifacts/offline-analytics-package/samples/*.csv`
- `artifacts/offline-analytics-package/validation-report.md`

Supporting protocol artifact:

- `artifacts/requirements.md`

The generated app should be a self-contained browser SPA that can:

- upload multiple CSV files
- profile schemas and row counts
- infer candidate relationships from common fields and key-like values
- allow manual relationship confirmation/removal
- generate default synthetic manufacturing-like sample data
- adapt synthetic generation to uploaded schemas and confirmed relationships
- run aggregations, charts, heat maps, and table outputs
- export generated data, relationships, and aggregate outputs

The app may use a solar-cell/panel style sample dataset. The app itself must
remain generic and schema-driven.

## Preconditions

1. Start Octopus and verify the registry is running.
2. Open the Registry UI, normally `http://127.0.0.1:8787/ui`.
3. Confirm at least one Codex-backed agent is connected and
   execution-healthy.
4. Use real Safari for the customer-facing validation pass.

## Create The Protocol From Blank

Open:

```text
Build -> Protocols
```

Then:

1. Click `New protocol`.
2. Choose `Start blank`.
3. Set the display name to:

   ```text
   Offline CSV Analytics SPA Build Protocol
   ```

4. Use this slug:

   ```text
   offline-csv-analytics-spa-build-protocol
   ```

5. Keep the description generic, for example:

   ```text
   Build and validate a self-contained browser SPA for local multi-CSV analytics.
   ```

## Declare Artifacts

Declare these artifacts before publishing:

| Display name | Path | Kind | Verify |
| --- | --- | --- | --- |
| Requirements specification | `artifacts/requirements.md` | `workspace_file` | yes |
| Offline analytics package | `artifacts/offline-analytics-package` | `workspace_file` (package directory) | yes |

## Add Stages

Create three meaningful stages. Assign each stage to an execution-healthy agent
that can write files in the workspace.

### Stage 1

Display name:

```text
Define requirements
```

Outputs:

```text
Requirements specification
```

Instructions:

```text
Produce artifacts/requirements.md for a generic offline browser SPA for local multi-CSV analytics. Do not use real customer data, real names, or meeting transcript content. The app must let a user upload multiple CSV files, profile schemas, infer and allow editing relationships, generate default synthetic manufacturing-style sample data, adapt synthetic data to uploaded schemas and inferred relationships, render aggregations, charts, and heat maps, export aggregate outputs, and keep uploaded rows local in the browser. Keep requirements domain-neutral while allowing sample data to resemble sequential manufacturing process data.
```

Transition:

```text
completed -> Build offline SPA package
```

### Stage 2

Display name:

```text
Build offline SPA package
```

Inputs:

```text
Requirements specification
```

Outputs:

```text
Offline analytics package
```

Instructions:

```text
Read artifacts/requirements.md and build the final offline user-facing package in artifacts/offline-analytics-package. Produce index.html, README.md, validation-report.md, and a samples/ directory with representative CSV files inside that package directory. The index.html must run in a browser with no backend, accept multiple uploaded CSV files, infer schema/profile/relationships from arbitrary uploaded CSVs, allow manual relationship edits, generate default manufacturing-like synthetic data before uploads, adapt synthetic data after uploads, provide dynamic aggregations, charts and heat maps, and export aggregate outputs. Keep the app generic and domain-neutral; sample CSVs may use a solar-cell/panel style manufacturing scenario.
```

Transition:

```text
completed -> Validate Safari package
```

### Stage 3

Display name:

```text
Validate Safari package
```

Inputs:

```text
Requirements specification
Offline analytics package
```

Outputs:

```text
Offline analytics package
```

Instructions:

```text
Inspect the generated package for completeness and update artifacts/offline-analytics-package/validation-report.md. Validate that the generated index.html is intended for Safari/browser use, works offline from local artifacts, includes a sample-data workflow, schema and relationship inference, manual relationship editing, synthetic data generation, aggregation, charts, heat maps, and exports. Record pass/fail notes and known limitations.
```

Transition:

```text
completed -> complete
```

## Validate And Publish

1. Click `Validate`.
2. Confirm the protocol validates without errors.
3. Click `Publish`.
4. Confirm the protocol state changes to `PUBLISHED`.
5. Confirm `Run protocol` is visible.

If the UI warns that expected outputs are not declared artifacts during run
launch, stop and fix the artifact declarations before using this with a
customer.

## Start The First Run

Click `Run protocol` and fill the generic run form.

Use an execution-healthy entry agent and the default workspace unless the
environment requires a different workspace.

Goal:

```text
Build a generic offline browser SPA package for local multi-CSV analytics. The target user has manufacturing process data exported as CSVs from multiple stages and wants a repeatable personal-computer tool. Do not use real customer data or raw meeting transcript details. Produce artifacts/offline-analytics-package/index.html as the final user-facing file, plus README, sample CSV files, and a validation report inside the same package directory. The app must infer schemas and relationships, allow manual relationship edits, generate default synthetic solar cell and panel style data, adapt synthetic generation from uploaded CSVs, create aggregations, charts, heat maps, and export aggregate outputs.
```

Context:

```text
Use a generic manufacturing process scenario with multiple CSV exports from sequential stages. Demonstration sample data may resemble solar cell, cell-to-panel, panel test, process measurement, and defect/result tables, but the tool itself must remain domain-neutral and infer structure from arbitrary uploaded CSV files.
```

Constraints:

```text
Real customer data and raw meeting content must not be used. Keep CSV processing local in the browser. Do not require a backend for the final app. It is acceptable to use battle-tested JavaScript libraries only if the delivered app remains usable from the artifacts generated by this run.
```

Expected outputs:

```text
artifacts/offline-analytics-package containing index.html, README.md, samples/*.csv, and validation-report.md.
```

Start the run, then open it from:

```text
Work -> Runs
```

## Inspect The Run

Use the run tabs in order:

1. `Overview`: confirm status, current stage, entry agent, workspace, and run
   guidance.
2. `Stages`: confirm each stage moved to `completed`.
3. `Artifacts`: confirm all declared outputs are produced and no required
   artifact is missing.
4. `Audit`: confirm transitions show the expected stage progression.

For the latest verified run, the product generated two verified artifact
outputs from the visible Safari UI: `artifacts/requirements.md` and the
`artifacts/offline-analytics-package` package directory. The package contained
`index.html`, `README.md`, sample CSVs, and `validation-report.md`.

## Validate The Generated App In Safari

Open the package artifact from the run artifact action in real Safari. The
`Open` action should load
`artifacts/offline-analytics-package/index.html`; the `Contents` action should
show README, samples, and validation report files inside the package.

Expected first-load checks:

1. The app renders without a backend.
2. The upload area accepts multiple CSVs.
3. Schema/profile, relationships, aggregation, charts, heat map, exports, and
   notes/status sections are visible.
4. No real customer data or meeting text appears in the app.

Default synthetic-data path:

1. Generate default synthetic data.
2. Confirm the app creates multiple related tables.
3. Confirm schema profiles and relationship candidates appear.
4. Run the default aggregation.
5. Confirm result rows, grouped output, bar/trend/heat-map visuals, and a data
   table render.

Verified Safari evidence from the latest package run
(`afe7792a151c4e3ab74d4de7a7e2ec79`):

- 6 synthetic tables
- 948 browser-local rows
- schema profiles rendered
- 25 inferred relationship candidates rendered
- accepting two relationship candidates updated confirmed relationships to 2
  and reduced candidates to 23
- a 432-row aggregate
- 5 aggregate groups
- one confirmed join path
- bar chart, trend chart, heat map, and aggregate table rendered

State reset path:

1. Click `Clear session`.
2. Confirm counters reset.
3. Confirm schema/profile sections clear.
4. Confirm relationship and aggregate sections clear.
5. Confirm old aggregation status text is gone.

Synthetic export path:

1. Generate synthetic data.
2. Open the synthetic export controls.
3. Export one table explicitly, such as `Panels`.
4. Confirm Safari downloads the CSV.
5. Confirm the app status identifies the exported table.

Avoid generated apps that trigger many rapid downloads at once in Safari.
Prefer per-table export buttons or a single bundled export action.

Upload and adaptation path:

1. Download or open the generated sample CSV artifacts.
2. Upload multiple CSVs into the generated app.
3. Confirm the app detects logical tables and row counts.
4. Confirm relationship candidates appear as suggestions, not automatic trusted
   joins.
5. Accept one candidate relationship.
6. Confirm the candidate disappears from the suggestions list and appears in
   confirmed relationships.
7. Generate adapted synthetic data from the uploaded schemas.
8. Confirm the generated rows follow the uploaded schema shape and confirmed
   relationships without copying uploaded rows wholesale.
9. Run an aggregation using a field from the uploaded/adapted schema.
10. Confirm charts and tables update.

Verified Safari evidence from the corrected run:

- 3 uploaded/generated CSV files were used in the loopback test
- 3 logical tables and 56 uploaded rows were detected
- accepting one relationship reduced candidate actions by one and increased
  confirmed relationships by one
- adapted synthetic generation produced 3 tables and 120 rows
- a selected adapted-schema aggregation produced 3 result groups

## If The First Run Needs Iteration

Start a second run from the same generic protocol and provide sanitized defect
feedback. Keep feedback focused on generated artifact behavior, not product
defaults.

Example corrected-run goal:

```text
Produce a corrected second iteration of the generic offline multi-CSV analytics SPA package. Keep the final user-facing file as artifacts/offline-analytics-package/index.html, with README, sample CSVs, and a validation report inside the same package directory. Preserve the generic local-browser CSV analytics scope: upload multiple CSVs, infer schemas, propose and manually confirm relationships, generate default synthetic data, adapt synthetic data from uploaded schemas, run dynamic aggregations, render charts/heat maps, and export useful outputs.
```

Example corrected-run context:

```text
A first Safari run produced a working app, but customer-facing defects remain. Fix these without adding product-specific or scenario-hardcoded behavior: Clear session must reset all status text and analysis state; synthetic CSV export must not rely on rapid multi-download loops in Safari; accepted relationship candidates should disappear from the candidate list; uploaded/adapted schema relationship inference should remain suggestions unless the user explicitly confirms them; avoid reciprocal duplicate relationship suggestions; synthetic data generated from uploaded schemas should preserve confirmed primary/foreign key relationships without copying uploaded rows wholesale.
```

Example corrected-run constraints:

```text
Do not include real customer data, real names, raw meeting transcript text, or any private source material. The product and app must remain use-case neutral; manufacturing-like sample data is allowed only as generic sample CSV content. The app must run locally in a browser without a backend. Do not use CDN dependencies unless the final artifact embeds what it needs to work offline. Favor explicit per-table export buttons or a single bundled export panel over automatic multiple downloads. Validation must cover real Safari UX expectations and state reset/export behavior.
```

## Known Limitations

- Relationship inference is heuristic. The generated app should make suggestions
  easy to inspect and confirm, not silently trust every candidate.
- The scenario validates that Octopus can generate and iterate an offline
  analytics tool. It does not prove production closed-loop manufacturing
  control.
- CDN libraries are acceptable only when the generated artifact embeds what it
  needs or the run explicitly declares online dependencies. A customer-facing
  offline package should not depend on a live CDN without saying so.

## Success Criteria

This scenario is ready to show when:

- the protocol was created from blank through the Registry UI
- the protocol was published and run through the UI
- the run completed all stages
- every declared artifact is produced
- `artifacts/offline-analytics-package/index.html` opens in real Safari from
  the package artifact action
- upload, relationship editing, synthetic data, aggregation, charts, heat map,
  exports, and clear/reset behavior all work
- no real customer data, names, meeting text, or private source content appears
  in protocol prompts or generated artifacts
