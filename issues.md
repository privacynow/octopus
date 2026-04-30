# Product Usability And Execution Readiness Plan

This is the active continuation plan for the Octopus product. It is written so
a new session/model can resume without relying on prior chat context.

## Resume Here

Resume from the generic offline-analytics scenario acceptance run. Directory
artifact verification has been fixed and deployed; the current product focus is
artifact package browsing, linked-run freshness, retry-attempt clarity, and a
full Safari rerun from the UI.

Current git state at the time this section was added:

- The latest deployed code before the current artifact-browse/linked-run edit
  was commit `df253abf`.

Acceptance sequencing is non-negotiable:

1. edit and test in `/Users/tinker/output/bots/telegram-agent-bot`,
2. commit and push,
3. pull in `/Users/tinker/octopus`,
4. redeploy with `./octopus redeploy --yes`,
5. verify `./octopus status`,
6. hard-refresh real Safari with `Option+Command+R`,
7. then test real Safari desktop and narrow flows.

Do not repeat these mistakes:

- Do not create protocols with API calls, database writes, seeded rows, hidden
  URLs, or scripts for product acceptance. Use the UI like a human.
- Do not add built-in starters, accelerators, or code-defined protocol
  templates.
- Do not make local analytics the default protocol-run experience.
- Do not put `customer handoff` language in protocol UI, run prompts, stage
  instructions, artifacts, or negative prompt text.
- Do not send users from stage assignment to a dead-end Skills Catalog page.
  Skill selection/creation must preserve stage context and return to the stage.

First verification target after P0-2:

- Create a generic non-analytics protocol from blank in the UI.
- Publish and run it.
- Confirm run launch is generic and contains no analytics-specific fields.
- Confirm Safari acceptance is performed only after push, pull, deploy, status,
  and hard refresh.

Likely file areas:

- Protocol editor and run launch UI JavaScript under `octopus_registry/ui/js/`.
- Protocol authoring/run input model code under `octopus_sdk/protocols/` and
  registry protocol routes/stores.
- Skill catalog and stage assignment UI code under `octopus_registry/ui/js/`.
- Run detail and stage progress UI code under `octopus_registry/ui/js/`.
- Tests: `tests/test_protocols.py`, `tests/test_protocol_service.py`,
  `tests/test_protocol_telegram.py`, `tests/test_registry_ui_contract.py`,
  `tests/test_registry_sdk_contract.py`, and targeted UI/Playwright specs.

The goal is not to make one demo artifact look good. The goal is to make the
product usable by a human who can clone the repo, start the system, create
workflows through the UI, run them, understand live progress, inspect linked
work, and open/download produced artifacts.

## Current State

Repository:

- Working repo: `/Users/tinker/output/bots/telegram-agent-bot`
- Deployment checkout: `/Users/tinker/octopus`
- Current branch: `feature/protocol`
- Latest deployed commit before the current artifact-browse/linked-run edit:
  `df253abf`
- M1 and M2 are the required working topology for customer/demo acceptance.
- M3/Claude is optional unless Claude auth is configured. A stopped M3 with
  `claude not configured` is not a handoff blocker.

Verified recently:

- Python full suite passed: `2236 passed` in about `10:22`.
- Targeted protocol/SDK/UI contract slice passed.
- Real Safari run proved that a protocol can be authored from the UI, published,
  run, and used to open a generated app artifact.
- `./octopus status` after redeploy showed Registry running, M1/M2 connected,
  M1/M2 execution healthy, and no execution faults.

Important caveat:

- The latest real Safari protocol evidence overfit the local analytics use case.
  That scenario is useful, but it must not become the product default, runtime
  default, protocol-run default, or artifact vocabulary.

## Product Vocabulary

Use these product nouns:

- Agent
- Skill
- Routing skill
- Conversation
- Protocol
- Stage
- Run
- Delegation
- Artifact
- Guidance
- Registry UI
- Telegram
- Octopus CLI
- SDK interface
- SDK implementation
- Admin operation

Do not reintroduce these as user-facing product nouns:

- Capability
- Advanced
- Custom runtime selector
- Starter
- Accelerator
- Built-in protocol
- Gallery
- Customer handoff

`Customer handoff` may appear only in repository planning/docs that describe how
we prepare the repo for a customer. It must not appear in protocol authoring UI,
run launch UI, generated protocol instructions, protocol artifacts, stage names,
artifact names, or negative prompt text such as "do not create a customer
handoff guide." The protocol should only ask for the user's real requested
outputs.

## Hard Rules

- Do not create parallel implementations for the same behavior.
- Do not add backward-compatibility shims unless explicitly requested.
- Extend the existing pipeline in place.
- Do not use direct database writes, API scripts, seeded rows, or hidden URLs as
  product acceptance.
- Database inspection is allowed for diagnosis only.
- Protocol acceptance must be UI-only: click, type, select, publish, run, and
  inspect through the visible product like a human.
- Do not make skills mandatory for stage creation.
- Do not make agents mandatory for stage creation.
- Do not force authors to choose skill plus agent when either one alone, both,
  or neither may be appropriate.
- Do not lose draft protocol/stage/artifact data when switching stages, panels,
  tabs, filters, assignment modes, or add-stage anchors.
- Do not expose internal runtime plumbing on the normal author path.
- Do not make a data analytics workflow the default protocol-run experience.
- Do not create code-defined templates, starters, accelerators, or customer
  shortcuts as product proof.
- User-authored templates are allowed: a user can publish a protocol as a
  reusable template and later copy that saved template.
- Generated/test/rehearsal records must not dominate default customer pages.
- Artifacts are first-class product outputs and must have consistent actions
  everywhere they are referenced.
- Real Safari is required for acceptance. Playwright and unit tests are not
  enough.

## Product North Star

A user should be able to:

1. Start Octopus.
2. Open Registry UI.
3. Confirm agents are healthy.
4. Start a conversation or create a protocol.
5. Create stages progressively without cognitive overload.
6. Assign no agent, one agent, no skill, one skill, both, or a needed new skill.
7. Declare inputs/outputs/artifacts without leaving the stage context.
8. Publish and run the protocol.
9. Watch run progress with live, truthful, scalable stage visualization.
10. Inspect conversations, delegations, runs, stages, and artifacts as one
    lineage instead of unrelated concepts.
11. Open, preview, download, or copy paths for artifacts wherever artifacts are
    referenced.
12. Repeat the same workflow from Registry UI and supported bot surfaces.

## Current Critical Problems

### P0: Workflow Builder Skill Continuity Is Broken

Observed:

- From the workflow builder, the Skills Catalog link opens the generic Skills
  page with no continuity.
- The user cannot create/update/select a skill in context and return it to the
  current stage assignment.
- The interaction feels like a dead-end navigation, not an assignment flow.

Expected:

- Stage assignment must keep context.
- If the user needs a skill, the workflow builder should support an inline or
  scoped skill flow:
  - search existing skills,
  - select an existing skill for this stage,
  - create or draft a new needed skill,
  - return to the same stage with the chosen/created skill applied or marked.
- Opening the full Skills surface from this context must preserve the stage
  assignment intent and provide a clear way back.

Implementation guidance:

- Reuse the existing stage assignment model and skill catalog data.
- Do not add a second skill system.
- Prefer a stage-scoped selector/create panel inside the protocol editor.
- If a full-page Skills route is used, pass a clear return context and render a
  contextual action such as `Use for current stage`.
- Do not use vague "capability" wording.

Acceptance:

- Create a protocol from blank in real Safari.
- Add a stage.
- Open skill selection from that stage.
- Search/select an existing skill and return to the same stage with it applied.
- Create or mark a needed new skill and return to the same stage without losing
  any stage data.
- Confirm no unrelated catalog dead-end is used as the primary flow.

### P0: Protocol Run Launch Is Overfit To Local Analytics

Observed:

- Protocol run launch is now too tightly tied to the data analytics example.
- The product risks looking like it exists only to build a manufacturing/local
  analytics tool.

Expected:

- Protocol run launch must be generic.
- Protocol-specific questions must come from user-authored protocol metadata,
  stage inputs, or run-input definitions.
- Local analytics is one acceptance scenario, not a default runtime surface.

Implementation guidance:

- Define or reuse one generic run-launch form model.
- The base form should ask only generic run inputs:
  - goal/problem statement,
  - optional context,
  - optional constraints,
  - optional expected outputs,
  - entry agent/workspace if needed.
- Any specialized fields must be generated from the selected protocol's own
  authored run-input schema, not hardcoded into the Registry UI.
- If protocol metadata does not define custom prompts, show generic prompts.
- Do not include `customer handoff` language in any run prompt.

Acceptance:

- Run a software-engineering protocol and confirm no data-analytics-specific
  fields appear.
- Run a document/review protocol and confirm no manufacturing/data-specific
  fields appear.
- Run a local analytics protocol and confirm its specific fields appear only
  because that protocol authored them.

### P0: Product Must Not Emit Customer-Handoff Language In Protocols

Observed:

- Planning/docs correctly say the customer handoff guide belongs in repo docs,
  but some runtime guidance/artifact expectations still mention this concept.
- Even negative prompt wording like "No customer handoff guide artifact" leaks
  an internal delivery concept into the protocol.

Expected:

- Protocols produce user-requested artifacts only.
- The runtime should never mention "customer handoff" to the model or inside
  generated artifacts unless the user explicitly uses those words in their own
  protocol.

Implementation guidance:

- Search UI copy, prompt builders, protocol launch defaults, docs used as prompt
  source, tests, and demo instructions.
- Remove "customer handoff" from product/runtime/protocol paths.
- Keep handoff wording only in repository planning docs and setup guides where
  it describes our delivery process.

Acceptance:

- Create and run a protocol from the UI.
- Inspect run prompt/context, stage instructions, generated artifacts, and
  artifact names.
- Confirm "customer handoff" is absent unless typed by the user as part of their
  own requested output.

### P0: Runs Need Live, Scalable Stage Visualization

Observed:

- Runs show useful data, but the experience is static and not visually clear
  enough while work is happening.
- Large protocols can overwhelm the UI.
- Previous attempts expanded too much at once or showed inconsistent run tabs.

Expected:

- Runs should visually show progress without overwhelming the page.
- The stage visualization should be animated, stateful, and bounded.
- If a protocol has more than five stages, show no more than five primary stage
  nodes at once:
  - previous,
  - current,
  - next,
  - plus compressed before/after groups when needed.
- Use clear state colors and motion:
  - completed,
  - current/running,
  - waiting,
  - failed,
  - skipped/not reached,
  - stale/needs attention.
- Keep the UI responsive and useful while a run updates.

Implementation guidance:

- Reuse the existing run/stage data model.
- Do not create a separate visualization data source.
- Add a single shared stage-progress component usable in run list expansion,
  run detail overview, and conversation-linked run cards.
- Use restrained animation: pulse/current progress, transition on stage change,
  no distracting constant motion.
- Preserve accessibility: text labels, aria state, reduced-motion support.

Acceptance:

- Start a real run in Safari.
- Watch stage state update while work is running.
- Verify current stage is visible without scrolling.
- Verify protocols with more than five stages show a compressed rail, not a
  wall of stages.
- Verify failed/stale states are visually obvious and textual.

### P1: Protocol Authoring Still Needs Matrix Verification

Expected matrix:

- Stage with no assignment.
- Stage with skill only.
- Stage with agent only.
- Stage with skill plus preferred agent.
- Stage with needed new skill.
- Add stage below current stage.
- Remove stage.
- Reorder or navigate stages without losing data.
- Edit artifacts inside stage context.
- Open workflow map on demand and interact with it.

Acceptance:

- All matrix paths must be exercised in real Safari from a blank protocol.
- No direct API/database setup counts.

### P1: Artifacts Must Be Consistent Everywhere

Expected artifact states:

- declared but not produced,
- produced and previewable,
- produced and openable,
- produced and downloadable,
- produced but unavailable on this host,
- path/reference only,
- failed generation.

Expected artifact actions:

- Preview
- Open
- Download
- Copy path
- Clear unavailable reason when an action cannot be offered

Surfaces:

- Run overview
- Run artifacts tab
- Stage detail
- Conversation linked work
- Delegation/task detail
- Dashboard references
- Telegram artifact commands

Acceptance:

- Use a real UI-created run.
- Confirm the same artifact exposes the same state/actions from every surface
  where it appears.

### P1: Conversations, Runs, And Delegations Need One Lineage

Expected:

- Conversations should not look empty when they have linked work.
- Runs should show stage work/delegations as children of the run/stage.
- Standalone delegations remain valid product concepts, but protocol stage
  execution should not look like an unrelated task app.

Acceptance:

- Start work from a conversation.
- Route work to another agent.
- Launch a protocol from a conversation where supported.
- Confirm the user can navigate conversation -> run/delegation -> artifacts and
  run/delegation -> conversation without guessing.

### P1: Telegram Must Use Shared SDK Protocol Behavior

Expected:

- Telegram should list/start/status/watch/cancel/retry/inspect artifacts for
  protocols through shared SDK protocol behavior.
- Telegram should not duplicate protocol execution logic.
- Future Slack/WhatsApp should be able to reuse the same SDK service.

Acceptance:

- Use Telegram to list protocols.
- Start a protocol.
- Watch status.
- Inspect artifacts.
- Open the same run in Registry and confirm state matches.

### P1: UI Information Architecture Must Stay Human-Centric

Expected current direction:

- Work: Conversations, Runs, Agents, Delegations if intentionally exposed.
- Build: Protocols, Skills, Guidance if guidance is an authoring/configuration
  task.
- Operations: Dashboard, Usage, Routing, diagnostics/admin.

Rules:

- No separate Gallery/Templates product surface.
- Templates are a utility inside Protocols and only user-authored.
- Do not promote empty or duplicate surfaces.
- Do not make implementation concepts peer product concepts.

Acceptance:

- First-time user can explain each sidebar item after one pass.
- No default nav item opens an empty or redundant page.

## Local Analytics Scenario Guidance

Local analytics is an acceptance scenario, not the product's identity.

Use it to prove:

- a user can create a protocol from blank,
- the model can generate local tools/scripts/apps,
- raw customer rows are not required in prompts,
- artifacts are produced and reviewable,
- generated tooling can process local data or synthetic data.

Do not:

- hardcode local analytics fields into generic run launch,
- use built-in protocols/starters,
- add dashboard shortcuts for this scenario,
- ask a protocol to generate repo customer docs,
- put customer-handoff language into the protocol.

Generic user-authored local analytics protocol shape:

1. Define objective and privacy boundary.
2. Define data contract and relationships.
3. Build local tool/script/app.
4. Verify local execution behavior.
5. Review generated outputs and either accept or send back.

The exact stage names, fields, and artifacts should be authored through the UI
by the user. They are not product defaults.

## Planned Test: Offline CSV Analytics SPA From UI-Only Protocol

Status: follow-up Safari run completed after generic product authoring fixes;
the scenario is now deliverable through a UI-authored generic protocol, with
one remaining generated-artifact quality risk around relationship suggestion
precision.

Goal:

- Test whether a generic user-authored protocol can produce a real browser
  based offline CSV analytics SPA from UI-only authoring, publishing, running,
  artifact inspection, and Safari validation.
- Use the manufacturing analytics scenario as a representative real-user
  workflow without adding product code, product UI, runtime defaults, or
  hardcoded behavior specific to this scenario.

Input guardrails:

- Do not paste meeting transcripts, names, or customer-specific details into
  protocol instructions, run prompts, stage instructions, or artifacts.
- Author the protocol from distilled generic requirements learned from the
  scenario.
- Keep the product use-case neutral. Any manufacturing wording belongs only in
  the user-authored protocol/run instructions and generated artifacts for this
  test.
- Do not use APIs, database writes, seeded state, or scripts to create product
  acceptance state. The protocol must be created, published, run, and inspected
  through visible Registry UI in real Safari.

Planned protocol shape:

1. Define analytics app requirements.
   - Specify offline/local processing boundaries.
   - Specify multi-CSV upload/paste, schema profiling, relationship inference,
     manual relationship editing, synthetic data generation, aggregations,
     heat maps, charts, exports, and user guidance.
2. Design dynamic data model and sample files.
   - Produce initial solar cell/panel style synthetic CSV examples.
   - Define generic inference rules for primary keys, foreign keys, common
     fields, value-overlap links, numeric/date/category profiling, and
     relationship confidence.
3. Build offline browser SPA.
   - Produce the final user-facing `index.html`.
   - Supporting artifacts may include README, sample CSVs, validation manifest,
     and review notes.
   - Battle-tested JavaScript libraries are allowed, but the final app must be
     usable offline. CDN dependencies must be vendored or embedded when the
     artifact is intended to run without a network.
4. Safari QA and artifact review.
   - Open the generated SPA in real Safari.
   - Upload the generated sample CSVs.
   - Verify inferred schemas and relationships.
   - Verify manual relationship edits.
   - Verify uploaded-file-derived synthetic data generation.
   - Verify default domain-shaped synthetic data before uploads.
   - Verify aggregations, filters, charts, heat maps, exports, and visual
     usability.
   - Produce a validation report with pass/fail evidence and follow-up issues.

Expected final artifact set:

- `index.html` as the final user-facing deliverable.
- `README.md` explaining how to use the offline app.
- Sample CSV files that demonstrate the initial scenario and can be uploaded
  back into the SPA.
- Validation report documenting Safari behavior, artifact actions, and any
  generated-app defects.

Acceptance criteria:

- A human can author the protocol from blank in real Safari without hidden
  setup.
- The run creates previewable/downloadable artifacts visible from the run and
  linked work surfaces.
- The generated `index.html` opens in real Safari and works as a browser app.
- The app accepts multiple CSV file types, profiles their schemas, proposes
  likely primary/foreign key relationships, and lets the user confirm or edit
  them.
- The app generates initial synthetic manufacturing-like data before upload.
- After one or more uploads, the synthetic data model follows observed columns,
  data types, value patterns, and inferred/confirmed relationships.
- The app performs dynamic aggregations and visual analysis, including heat
  maps and charts, from browser-local data.
- The app exports useful aggregate outputs without requiring raw rows to be
  sent to a model provider.
- The product itself remains generic; no product defaults or code paths are
  tied to this scenario.

Issue capture buckets for this test:

- Protocol authoring friction.
- Assignment, skill, or routing friction.
- Runtime/stage completion failures.
- Artifact preview, open, download, or copy-path failures.
- Generated SPA functional defects.
- Real Safari layout, usability, and visual polish defects.
- Genericity risks where the product nudges toward use-case-specific code or
  hardcoded UI.
- Privacy/offline risks where artifacts or prompts could expose private rows
  or require network access unexpectedly.

Initial Safari evidence:

- Protocol authored through real Safari from a blank protocol:
  `Offline CSV Analytics SPA Builder`
  (`10147e9330324d73ac5d89f812e33b23`).
- Run started through the visible Safari UI:
  `bbabb6dc161949aca1b7e81632d81327`.
- The run used sanitized generic manufacturing/local-CSV requirements. It did
  not include real customer names, raw meeting transcript text, or real data.
- Expected outputs entered in the run modal were
  `artifacts/index.html`, `artifacts/README.md`,
  `artifacts/samples/*.csv`, and `artifacts/validation-report.md`.
- Actual result: the run completed one stage, `requirements_spec`, and produced
  only `artifacts/requirements.md` (`artifact_1`, verified in the run UI).
- The artifact preview worked in Safari and showed a requirements document, but
  there was no generated SPA to open, no sample CSV set, no README, and no
  validation report. The generated-app Safari QA path was therefore blocked.

Findings from the first UI-only attempt:

- Blocking authoring defect: managing workflow files while a new stage draft is
  unsaved can hide or lose the draft. During stage 2 authoring, opening
  `Files & outputs` and adding an artifact returned the page to a state with
  only the first stage visible. The later "unfinished step draft" recovery did
  not restore the hidden draft editor.
- Blocking authoring defect: after the hidden draft state, `+ Add step` could
  change the URL to `panel=new-stage` without showing the new-stage form. This
  prevented creating the richer protocol needed for a realistic workflow.
- Stage/artifact identity defect: the first stage appeared as
  `requirements_spec`, matching the artifact name, even though the intended
  human stage title was a requirements-definition step. This makes stage
  semantics confusing and likely contributed to the protocol becoming a
  requirements-only workflow.
- Runtime outcome gap: the run accepted expected outputs for a complete offline
  SPA package, but the protocol only had one declared artifact and completed
  successfully after producing a requirements document. The UI did not warn
  that the published protocol could not produce the requested artifact set.
- Safari usability issue: large text areas in the protocol editor were easy to
  mis-target through Safari accessibility, and a later attempted instruction
  update did not persist before publication. This needs product-side review even
  if some friction is automation-specific, because a human must be able to
  verify and trust stage instructions before publishing.

Product fixes applied before the second attempt:

- Preserved unsaved stage drafts while managing workflow files/artifacts.
- Fixed the `+ Add step` pending-draft anchor so the new-stage form reliably
  opens after artifact work.
- Added a run-start warning when expected outputs do not match declared
  protocol artifacts.
- Added Playwright coverage for the draft/artifact authoring flow.

Second Safari evidence after product fixes:

- Protocol authored through real Safari from a blank protocol:
  `Offline CSV Analytics SPA Build Protocol`
  (`68586540cd7c4dd9a4aa960dc1b1f13d`).
- Run started through the visible Safari UI:
  `18bc37bf7faa40feb544c990fc36b156`.
- The run used sanitized generic local-CSV/manufacturing analytics
  requirements. It did not include real customer names, raw meeting transcript
  text, or real data.
- The published protocol had three meaningful stages: define requirements,
  build the offline SPA package, and validate the Safari package.
- The run completed all three stages and produced six verified artifacts with
  zero missing declared outputs: `artifacts/requirements.md`,
  `artifacts/index.html`, `artifacts/README.md`,
  `artifacts/samples/cells.csv`, `artifacts/samples/panels.csv`, and
  `artifacts/validation-report.md`.
- The generated `index.html` opened from the run artifact UI in real Safari and
  rendered as a self-contained browser app with upload, synthetic generation,
  schema profile, relationship inference, relationship editing, aggregation,
  chart, heat-map, and export controls.
- Default synthetic generation worked in Safari: 6 tables, 948 rows, 29
  confirmed relationships, 46 inferred candidates, and a cross-table aggregate
  over 432 joined rows with chart and heat-map output.
- Artifact download/upload loop worked in Safari using generated CSV artifacts
  plus a generated table export: 3 files uploaded, 3 logical tables, 56 rows,
  12 relationship candidates, and manual acceptance of an inferred relationship
  updated the confirmed relationship count.
- Uploaded-schema synthetic adaptation worked in Safari: the SPA generated 3
  synthetic tables and 120 rows from the uploaded schema profiles, with session
  notes stating that rows were regenerated rather than copied wholesale.
- Dynamic aggregation worked after adaptation: grouping by a selected uploaded
  schema field produced 3 result groups and updated the bar chart and aggregate
  table.
- Relationship JSON export downloaded successfully from Safari.
- Product genericity held: the product UI, persisted protocol machinery, and
  code changes remained use-case neutral; manufacturing-specific wording stayed
  inside this user-authored protocol/run and generated artifacts.

Generated artifact defects from the second run:

- `Clear session` resets counters/results but leaves stale aggregation status
  text from the previous run. This is a generated SPA state-management defect.
- `Export synthetic CSVs` is Safari-fragile. It triggered only one CSV download
  (`panel_tests*.csv`) instead of one file per loaded/synthetic table. Generated
  apps should prefer one explicit bundle/download or per-table export buttons
  over rapid multi-download loops.
- Relationship inference is useful for exploration but too eager after
  synthetic adaptation. It showed reciprocal and ambiguous high-confidence
  links, including `line_id` to `panel_id` candidates caused by regenerated
  identifier patterns. These should remain suggestions unless explicitly
  confirmed by the user.
- Inferred candidates that have already been accepted remain visible as
  candidates. That makes the relationship state harder to audit.

Current conclusion:

- The product can handle this scenario as a generic UI-authored protocol and
  produce a working offline SPA artifact through a real Safari run.
- No new generic product blocker was found in the second attempt. The remaining
  issues are generated-artifact quality issues, not a reason to hardcode this
  scenario into the product.

Follow-up generated-artifact iteration:

- A corrected second iteration was launched through the visible Safari UI
  against the same generic protocol:
  `9e9eca08818f436b85164228610b290f`.
- The follow-up prompt was sanitized defect feedback. It did not include real
  customer names, raw meeting transcript text, or real data, and it did not ask
  for product code or UI to become manufacturing-specific.
- The run completed all three stages. The run detail showed status
  `completed`, stage progress for define/build/validate all completed, and
  `Artifacts (6)`.
- The build produced the corrected browser artifact
  `artifacts/index.html` (`artifact_2`, 46,373 bytes), `README.md`, sample
  CSV artifacts, and an updated `artifacts/validation-report.md`.
- The corrected `index.html` opened from the run artifact UI in real Safari.
- Real Safari default synthetic generation worked: 6 tables, 948 browser-local
  rows, schema profiles, inferred relationship candidates, dynamic aggregate
  defaults, a 432-row aggregate, 5 result groups, bar chart, trend chart, heat
  map, and aggregate table.
- Real Safari `Clear session` now resets counters, schema sections,
  relationships, aggregate counts, charts, and session notes without retaining
  stale `Aggregated ...` status text.
- The corrected synthetic export flow now renders one explicit button per
  synthetic table under `Synthetic CSV Exports` instead of triggering a rapid
  multi-download loop. A real Safari click on `Export Panels CSV` updated the
  app note to `Exported synthetic table Panels.` and produced the expected
  `panels` CSV download.
- Candidate acceptance was verified on the generated artifact through the
  browser automation surface: accepting one inferred relationship reduced the
  candidate action count from 19 to 18 and added one confirmed relationship.
  This fixes the accepted-candidate visibility problem observed in the second
  run.
- The remaining generated-artifact quality risk is relationship precision.
  The app still presents many high-confidence suggestions and some ambiguous
  relationship directions. This is acceptable for an exploratory offline SPA
  only because suggestions remain unconfirmed until the user accepts them; it
  should be improved in future generated-app guidance if this scenario becomes
  a repeated customer workflow.

## Testing Policy

Use test tiers. Do not run the full suite reflexively during every small edit,
but do not claim readiness from unit tests alone.

### Fast Patch Checks

Run for most edits:

```bash
git diff --check
```

For edited Python:

```bash
./.venv/bin/python -m pytest <focused tests> -q
```

For edited UI JavaScript:

```bash
node --check <edited js file>
./.venv/bin/python -m pytest tests/test_registry_ui_contract.py -q
```

### Change-Slice Checks

Use when touching protocol, runs, artifacts, SDK, Telegram, or UI contracts:

```bash
./.venv/bin/python -m pytest \
  tests/test_protocols.py \
  tests/test_protocol_service.py \
  tests/test_protocol_telegram.py \
  tests/test_registry_ui_contract.py \
  tests/test_registry_sdk_contract.py \
  octopus_sdk/tests/test_wiring_verification.py \
  -q
```

Adjust the slice to match the touched files. Record skipped slices explicitly.

### Full Python Suite

Use before push/release or after low-level SDK/runtime changes:

```bash
./.venv/bin/python -m pytest -q
```

Current observed runtime is about 10 minutes for roughly 2200+ tests. This is
not expected to be sub-10 seconds.

### Real Safari Acceptance

Required before claiming UI/product readiness:

1. Use the actual Safari app, not only Playwright or the in-app browser.
2. Hard-refresh after deploy with `Option+Command+R`.
3. Test desktop width.
4. Test narrow/mobile-like width.
5. Create protocols through UI only.
6. Start runs through UI only.
7. Inspect generated artifacts through UI actions.
8. Record issues in this file and continue testing after each fix.

### Browser Automation

Playwright can be used for regression and screenshots, but it does not replace
real Safari acceptance. Playwright-created state is useful only when it mirrors
the visible user path.

## Deployment Process

Normal flow:

1. Edit in `/Users/tinker/output/bots/telegram-agent-bot`.
2. Test locally.
3. Commit and push from this repo.
4. Pull in `/Users/tinker/octopus`.
5. Redeploy from `/Users/tinker/octopus`.
6. Verify status.
7. Hard-refresh Safari.
8. Re-test real Safari flows.

Commands:

```bash
git status --short
git add <files>
git commit -m "<message>"
git push
git -C /Users/tinker/octopus pull
cd /Users/tinker/octopus
./octopus redeploy --yes
./octopus status
```

Notes:

- Use `./octopus redeploy --yes`; without `--yes`, non-interactive shells can
  fail at the confirmation prompt with `EOFError`.
- M1/M2 connected and execution healthy is the required customer/demo topology.
- M3 stopped due to missing Claude auth is not blocking unless the task is
  explicitly about Claude/M3.
- If Safari appears stale after deploy, hard-refresh with `Option+Command+R`.

## Golden Scenarios

### Scenario A: Clean Clone To First Useful Output

1. Clone repo.
2. Configure required provider credentials.
3. Start Octopus.
4. Open Registry UI.
5. Confirm M1/M2 health.
6. Start a new conversation.
7. Ask for a small work product using a skill.
8. Verify response, linked work, and events.

Pass criteria:

- No stale demo prompt appears.
- Work completes or fails with a clear reason.
- User can find what happened from the UI.

### Scenario B: Protocol Authoring From Blank

1. Open Protocols.
2. Create blank protocol.
3. Add at least six stages to test scale.
4. Exercise all assignment states.
5. Add input/output artifacts per stage.
6. Add routing.
7. Open workflow map on demand and interact with it.
8. Publish.

Pass criteria:

- No stage data is lost.
- Skill catalog flow preserves assignment context.
- No required field blocks intentional blank assignment.
- No internal runtime controls appear.

### Scenario C: Generic Protocol Run

1. Run a non-analytics protocol.
2. Confirm run launch is generic.
3. Confirm no analytics-specific fields appear.
4. Watch animated stage progress.
5. Inspect stage details and artifacts.

Pass criteria:

- Run launch matches the selected protocol, not the analytics demo.
- Stage progress stays visible and scalable.

### Scenario D: Local Analytics As One Scenario

1. Create a local analytics protocol from blank.
2. Author any specialized run inputs through the protocol.
3. Publish and run it.
4. Generate local tool/script/app artifacts.
5. Open/download artifacts.
6. Verify synthetic/local mode works.

Pass criteria:

- No raw customer data required in prompts.
- No hardcoded product defaults for analytics.
- No customer-handoff wording in protocol/artifacts.

### Scenario E: Conversation And Delegation Lineage

1. Start a conversation.
2. Route work to a specific agent.
3. Route work by skill.
4. Launch a protocol from conversation where supported.
5. Inspect linked work and artifacts.

Pass criteria:

- Conversation does not look empty.
- User can navigate lineage without hidden links.

### Scenario F: Telegram Parity

1. List protocols in Telegram.
2. Start a protocol.
3. Watch status.
4. Inspect artifacts.
5. Open same run in Registry.

Pass criteria:

- Telegram and Registry show the same run.
- Artifact state matches.
- Protocol behavior comes from shared SDK path.

## Current Safari Run Notes - 2026-04-30

Real Safari run:

- Protocol: `Generic Offline CSV Analytics Builder`
- Run: `af676ede29424f6687299a51992d32a6`
- Created from a blank protocol through the UI.
- Published and started from the UI.
- Stages:
  1. Define local analytics requirements - M1
  2. Build offline CSV analytics package - M2
  3. Validate offline analytics package - M1

Confirmed behavior:

- Stage 1 completed and produced `artifacts/requirements.md`.
- Stage 2 delegated to M2 correctly and completed the package build.
- The generated package was intentionally scenario-shaped, but the product
  protocol, launch fields, and runtime stayed generic.

Blocker found:

- Stage 2 produced `artifacts/offline-analytics-package`, but the run blocked
  with `artifact_missing` because the declared output was a directory/package
  path. SDK finalization only verified regular files, so directory artifacts
  were reported as missing even when the agent created them.
- Generic fix required: verify directory workspace artifacts, hash directory
  contents, let run/task artifact routes open `index.html` from a directory,
  and download directory artifacts as zip files.

Resolution already verified:

- Commit `df253abf` added generic directory artifact verification and deploy
  support. After redeploy, retrying the same run from Safari completed stage 2
  and stage 3. The package artifact was verified as a directory output and the
  validator accepted it.
- Commit `46849c4e` added generic package artifact browsing from run/task
  artifact routes and UI action rows. Package artifacts now expose `Open`,
  `Contents`, `Download`, and `Copy path` without adding analytics-specific
  product behavior.
- Commit `865addc2` fixed retried run stage counting. The same run now shows
  `3 / 3` stages instead of counting the failed attempt as a fourth workflow
  stage.
- The generated SPA opened from the protocol run artifact in Safari and
  successfully generated default synthetic data, profiled 6 tables / 948 rows,
  inferred relationship candidates, rendered aggregation results, and displayed
  bar, trend, heat-map, and aggregate-table views.
- The package contents browser opened in Safari and listed the expected handoff
  files: `README.md`, `index.html`, sample CSVs, and `validation-report.md`.

UX issues resolved during this pass:

- The stale linked-run behavior was addressed by subscribing conversation
  linked work to protocol-run websocket updates.
- The contradictory package artifact state was addressed by verifying directory
  artifacts through the same artifact finalization path as file artifacts.
- Package contents browsing was added generically for directory/package
  artifacts.
- Retry evidence now marks previous attempts instead of presenting stale output
  state as current run state.

UX issues still open:

- The generated SPA still needs a full fresh interactive rerun after the latest
  UI fixes. Safari verified the final package contents, but the desktop
  automation bridge stopped returning window state before a complete second
  from-blank run could be driven end to end.
- Full activity is no longer blank, but the newest progress is still dense:
  rows are collapsed, the page does not clearly auto-follow the latest event,
  and the user has to infer whether the run is still healthy.
- Conversation linked work and full activity eventually showed useful progress,
  but conversation drill-through should be rechecked from a new run after the
  package browser deployment.
- The run launch warning for "expected outputs not declared" is useful for
  strict artifacts, but it becomes confusing when a declared package directory
  intentionally contains `index.html`, README, samples, and reports. The UI
  should explain whether the user should declare one package output or each
  contained file.
- Manual Safari testing of the generated SPA found that inferred relationship
  Accept/Reject controls did not visibly update the confirmed relationship
  count. The validator accepted the artifact without catching that interactive
  defect, so the scenario rerun must include direct browser interaction checks,
  not just static file validation.
- Real Safari is the required acceptance browser. If the desktop automation
  bridge is unavailable again, use manual Safari inspection for acceptance and
  only use Playwright as a secondary regression aid.

## Open Blockers

| ID | Severity | Blocker | Required Fix |
| --- | --- | --- | --- |
| P0-1 | Critical | Workflow builder skill catalog breaks assignment continuity. | Implement stage-scoped skill select/create/return flow. |
| P0-2 | Critical | Protocol run launch is overfit to local analytics. | Replace hardcoded analytics launch fields with generic launch plus protocol-authored custom inputs. |
| P0-3 | Critical | Customer-handoff language can leak into protocol/runtime/artifacts. | Remove from product/runtime prompt paths; keep only repo planning docs. |
| P0-4 | Critical | Run progress is improved but still not obvious enough during active execution. | Make stage liveness more prominent, show current stage movement grounded in real run state, and reduce dense activity context. |
| P1-1 | High | Protocol authoring assignment matrix not fully reverified after latest changes. | Run real Safari matrix from blank protocol. |
| P1-2 | High | Package artifact actions are verified on the run artifact page but not yet across every reference surface. | Verify package Contents/Open/Download in run, stage, task, conversation, dashboard, and Telegram surfaces. |
| P1-3 | High | Conversations/runs/delegations can still feel unrelated or stale. | Consolidate lineage display, subscribe linked work to run updates, and verify drill-through freshness. |
| P1-4 | High | Telegram protocol parity needs live recheck. | Verify list/start/status/watch/artifacts against shared SDK path. |
| P1-5 | High | Full desktop/narrow Safari audit is not complete after current blockers. | Run only after P0/P1 blockers are fixed. |
| P2-1 | Medium | Clean-clone/customer-self-service pass remains unproven. | Run setup from docs in clean environment and fix docs/product gaps. |
| P2-2 | Medium | Workspace cleanup UI needs post-deploy Safari verification. | Verify password + `CLEAN` flow preserves agents/skills/guidance. |
| P2-3 | Medium | Stale/interrupted run recovery needs UI confirmation after redeploy. | Interrupt/redeploy during a run and confirm terminal retryable state. |
| P2-4 | Medium | Real Safari desktop automation became unavailable during the final contents check. | Treat as test-environment risk: recover Safari automation or perform documented manual Safari acceptance before closing the scenario. |

## Implementation Order

1. Recover real Safari interaction or arrange manual Safari acceptance if the
   automation bridge remains unavailable.
2. Start a fresh offline analytics protocol run from the UI using the deployed
   package-browser build.
3. Verify the final package from the run UI: Open SPA, Contents browser,
   README/sample CSV preview, zip download, and generated SPA interaction.
4. If the generated SPA still fails interactive checks, use protocol UI actions
   to retry/send back with specific artifact feedback.
5. Verify artifact actions across remaining reference surfaces.
6. Verify conversation/delegation/run lineage freshness.
7. Verify Telegram parity.
8. Run clean-clone/docs pass.
9. Run full desktop/narrow Safari audit.

Do not start the broad 500+ screenshot audit until P0 and P1 blockers are
closed. Broad screenshots are breadth; the golden scenarios above are depth.

## Decision Log

- `issues.md` is the active continuation plan.
- `plan_fix.md` remains removed and should not be recreated unless explicitly
  requested.
- Skills is the user-facing noun. Do not reintroduce Capabilities.
- Registry owns canonical protocol persistence and APIs.
- SDK owns shared protocol client/service behavior for Registry UI, Telegram,
  future Slack/WhatsApp, and CLI.
- Telegram is a peer surface, not a separate protocol implementation.
- Protocol authoring acceptance is UI-only.
- Local analytics is one scenario, not the product default.
- User-authored templates remain supported inside Protocols.
- Code-defined built-in templates/starters/accelerators are not product
  surfaces.
