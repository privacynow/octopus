---
name: manufacturing-local-analytics
display_name: Manufacturing Local Analytics
description: Build repeatable local data profiling and manufacturing quality analysis scripts without sending raw rows to the model.
---
Use this skill when helping a user build analytics or reporting tooling for local manufacturing, process, quality, or traceability data.

Core rules:

- Treat raw CSV rows, database extracts, proprietary identifiers, and full source files as local-only by default.
- Ask for file paths, schemas, row counts, join keys, and aggregate summaries before asking for raw data.
- Prefer scripts that run in the user's workspace over manual copy/paste analysis.
- Make scripts idempotent, deterministic, and safe to rerun.
- If the user asks for a demo or the referenced files are absent, generate realistic deterministic synthetic manufacturing CSV fixtures locally before profiling.
- Separate model-visible context from local-only source data.
- Produce artifacts that can be reviewed: input contract, profiling summary, analysis script, findings report, QA flags, and validation manifest.
- Do not accept placeholder artifacts. Renderable outputs must contain real visible findings, not "not generated" or validation-failed messages.
- Validate primary-key and foreign-key relationships before interpreting results.
- Call out data-quality problems separately from product-quality findings.
- Do not imply prediction certainty when the data only supports detection, correlation, or prioritization.
