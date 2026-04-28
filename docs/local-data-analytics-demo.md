# Local Data Analytics Demo

This guide describes a customer-facing demo for data analytics and reporting
when the customer does not want raw CSV data uploaded or pasted into a model
prompt.

## Demo Message

Octopus can help build local analytics tooling. The model writes and revises
code. The code runs locally against customer files. The customer controls what
summaries, logs, and artifacts are shared back into the conversation.

Do not claim that the model can never see data unless the deployment has
technical controls enforcing that boundary. The safe claim for this demo is:

- raw CSVs stay in the local workspace
- the model is asked to generate/review scripts
- scripts process the files locally
- only controlled summaries, errors, or selected outputs are shared back

## Customer Scenario

The customer has property information in CSV files and wants:

- data profiling
- data quality checks
- aggregate reporting
- market/property summaries
- repeatable report generation
- downloadable artifacts

They do not want to provide raw property rows to the model.

## Prepare The Demo

Use synthetic data with the same general shape as the customer's data.

Recommended local structure:

```text
workspace/
  data/
    properties.csv
  scripts/
  reports/
```

Synthetic columns can include:

- `property_id`
- `address_city`
- `address_state`
- `zip`
- `property_type`
- `bedrooms`
- `bathrooms`
- `square_feet`
- `lot_square_feet`
- `year_built`
- `assessed_value`
- `sale_price`
- `sale_date`
- `occupancy_status`

Use fake values only.

## Demo Flow

### 1. Start Octopus

```bash
./octopus
./octopus status
```

Open the registry URL printed by status.

### 2. Open A Conversation

In the registry UI, open or create a conversation with the target agent.

Explain the privacy boundary before sending the prompt:

```text
The CSV stays local. We are asking the assistant to write scripts that inspect
and process it locally. We will share schema summaries, logs, and aggregate
outputs only when we choose to.
```

### 3. Send The Analytics Prompt

Example prompt:

```text
Build a local property analytics pipeline for CSV files in ./data.

Privacy rule: do not ask me to paste raw CSV rows into chat. Write scripts that
run locally against the files. If you need to inspect the data, create a
profiling script that outputs column names, data types, missing-value counts,
row counts, basic numeric summaries, and validation warnings. Use only those
controlled summaries for follow-up reasoning.

Create:
- scripts/profile_properties.py
- scripts/build_property_report.py
- reports/property_profile.md
- reports/property_summary.md
- reports/property_summary.csv

The report should include:
- record count
- missing-value summary
- price distribution
- median sale price by ZIP
- median assessed value by property type
- top data quality warnings
- recommended follow-up analyses

Make the scripts safe to rerun and document how to run them.
```

### 4. Have The Agent Generate Code

The expected output is code and instructions, not raw data analysis performed
inside the prompt.

The useful artifacts are:

- profiling script
- report-building script
- markdown report
- CSV summary
- optional chart outputs

### 5. Run Scripts Locally

Run the generated scripts in the local workspace or bot shell, depending on the
deployment:

```bash
python scripts/profile_properties.py data/properties.csv reports/property_profile.md
python scripts/build_property_report.py data/properties.csv reports/
```

If a script fails, paste the error/log excerpt into the conversation. Do not
paste raw rows.

### 6. Iterate

Example follow-up:

```text
The profiling script found missing assessed_value in 8% of rows and sale_price
outliers above the 99th percentile. Update the report script to flag those
records in a separate QA output and add a short executive summary.
```

### 7. Review Artifacts

Use the registry conversation/run/work context to inspect generated artifacts
where available.

Expected artifact examples:

- `scripts/profile_properties.py`
- `scripts/build_property_report.py`
- `reports/property_profile.md`
- `reports/property_summary.md`
- `reports/property_summary.csv`
- `reports/property_quality_flags.csv`

If an artifact is produced but cannot be previewed/downloaded from a surface
that references it, note that as a product gap rather than changing the demo
story.

## Optional Protocol Framing

If protocol flows are stable in the demo environment, present the workflow as a
repeatable protocol:

1. profile data
2. review profile summary
3. generate analytics script
4. run analytics script locally
5. review report
6. revise or publish outputs

If protocol authoring/runtime is not stable enough for a live customer demo,
keep the demo in a conversation and explain that the same workflow can be made
repeatable as a protocol.

## What To Avoid

- Do not use real customer CSVs in a sales demo.
- Do not paste raw rows into the conversation.
- Do not upload private files to the model.
- Do not claim absolute data isolation unless the deployment enforces it.
- Do not demo unfinished protocol/UI paths if the conversation workflow is more
  reliable.
- Do not hide script failures. Use them to show local iteration and debugging.

## Success Criteria

The customer should understand:

- Octopus can orchestrate local analytic work.
- The model can generate and revise analysis code.
- Customer data can remain in the local workspace.
- Scripts can produce repeatable reports and QA outputs.
- Generated code and reports are traceable as artifacts.
- The workflow can later become a reusable protocol.
