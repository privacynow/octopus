# Product Usability And Execution Readiness Plan

This is the active continuation plan for the Octopus product. It is written so
a new session/model can resume without relying on prior chat context.

## Resume Here

Canonical tracking model:

- `issues.md` is the single product readiness backlog and acceptance tracker.
- `plan_manufacturing_run.md` is a scenario runbook for the manufacturing demo
  only. It should not duplicate the product backlog.
- Product blockers from the manufacturing plan are consolidated in
  `Open Blockers` below with status, evidence, and next acceptance step.
- Scenario-specific artifact follow-ups stay in `issues.md` when they expose a
  product gap, and stay in the manufacturing plan only when they are instructions
  for recreating that scenario.

## Latest Manufacturing Intelligence Run Evidence

Date: 2026-04-30

Verified in real Safari:

- Created and ran `Adaptive Manufacturing Intelligence Command Center` through
  Registry UI, not direct API or database mutation.
- Latest successful run:
  `25e2f70f8b9545ffa4e477582628bb97`.
- Final package artifact:
  `artifact_4`, `sha256 79ea0bff24db`,
  `artifacts/manufacturing-intelligence/package`.
- Run completed 6 / 6 stages. M2 handled package build stages and M1 handled
  charter/spec/validation/executive review stages, proving multi-agent protocol
  handoff through the Registry path.
- Generated artifact opened in Safari from the Registry artifact route.
- Artifact workflow verified:
  default synthetic generation, unconfirmed relationship candidates, evidence
  review, explicit relationship confirmation, joined analytics builder,
  heat-map output, manager dashboards, multiple local CSV upload, single-table
  adapted synthetic mode, relationship-preserving adapted synthetic mode, and
  local management report export.

Product-generic issues found and fixed in this workstream:

- SDK stage prompts did not clearly separate run-level goals from the current
  stage's output write scope. This let a stage pre-fill artifacts assigned to
  later stages. Fix: render input artifacts as read-only context, output
  artifacts as write scope, and explicitly prohibit creating or overwriting
  later-stage artifacts in `octopus_sdk/protocols/documents.py`.
- Runs page could briefly show `Select a run...` for a selected run during
  refresh. Fix: keep selected-run loading state visible while detail is loading.
- Linked work view could appear blank until the user switched away and back.
  Fix: show a loading state while linked work is loaded.
- Full activity contained repeated nonterminal task status events such as
  thinking, still-working, command, draft-reply, and running updates. Fix:
  compact nonterminal `task.status` rows per task while keeping terminal
  outcomes and actionable/contentful events visible.

Artifact-level issue found and documented for the next scenario refinement:

- The generated `index.html` can retain stale detail-panel relationship evidence
  after Reset or data replacement. This is scenario artifact behavior, not a
  product feature to hardcode. The next manufacturing protocol refinement should
  require reset/data-load handlers to clear selected detail state.

Resume from the verified generic offline-analytics scenario acceptance run.
Directory/package artifacts, linked-run freshness, retry-attempt clarity, and
run progress feedback have been fixed and deployed. The latest real Safari run
completed from the visible UI, produced the package artifact, delegated the
build stage to M2, and opened the generated SPA from the run artifact action.

Current git state at the time this section was added:

- The latest deployed product code before this documentation update was commit
  `311a57fb`.

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

First verification target after this scenario:

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
- Latest deployed product commit before this documentation update: `311a57fb`
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

- The local analytics scenario is useful acceptance evidence, but it must not
  become the product default, runtime default, protocol-run default, or
  artifact vocabulary.

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

### Resolved: Protocol Run Launch Genericity

Previously observed:

- Protocol run launch is now too tightly tied to the data analytics example.
- The product risks looking like it exists only to build a manufacturing/local
  analytics tool.

Current verified behavior:

- Run launch uses generic goal, context, constraints, and expected-output
  fields unless the selected protocol supplies authored custom inputs.
- The latest Safari analytics run used only those generic fields. Manufacturing
  wording came from the user-authored run prompt, not product defaults.
- Expected-output warnings now understand declared package paths and did not
  warn for the verified package artifact run.

Acceptance:

- Run a software-engineering protocol and confirm no data-analytics-specific
  fields appear.
- Run a document/review protocol and confirm no manufacturing/data-specific
  fields appear.
- Run a local analytics protocol and confirm any scenario wording appears only
  because the user authored it.

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

### P1: Runs Need Continued Progress UX Audit

Observed:

- Runs now show live grounded progress, including current stage/task,
  participant, elapsed time, stage rail state, and clearer stage evidence.
- The latest Safari acceptance run was understandable from the run page while
  it progressed and after it completed.
- Broad non-analytics and large-protocol runs still need audit so the same
  component stays readable outside the analytics scenario.

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
- Rendered preview for text/Markdown artifacts when the browser would otherwise
  show raw content
- Open
- Open app/default entry for package artifacts when a clear default file such as
  `index.html` exists
- Contents/browse for package artifacts
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
- Confirm package artifacts reveal important contained files such as
  `index.html` without requiring the user to infer them from an opaque artifact
  key.

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
- Start a fresh protocol run from Telegram, not just inspect an existing
  Registry-created run.
- Watch status while the run progresses.
- Inspect artifacts after completion.
- Export and download at least one artifact.
- Open the same run in Registry and confirm state matches.
- Confirm the Telegram run path uses shared SDK/registry protocol behavior, not
  a Telegram-only execution path.

### P1: Telegram Protocol UX Is Too Command-Centric

Observed in live Safari:

- `/protocol artifacts <run_id>` and `/protocol export <run_id>` work, but they
  require opaque run GUIDs that are not discoverable or humane.
- Artifact lists render as dense walls of paths, artifact keys, byte counts, and
  raw URLs.
- Important user-facing files inside package artifacts, especially `index.html`,
  are not surfaced directly in Telegram.
- Markdown artifact links open raw browser text. That is useful as a fallback,
  but not a polished preview.
- The Telegram surface was verified against an existing run, but a fresh
  Telegram-started run was not completed and cross-checked.

Expected:

- Telegram should offer a guided path for common protocol operations:
  recent runs, latest run, numbered selections, protocol names/slugs, and
  artifact display names should work without the user copying GUIDs.
- Artifact output should be compact by default:
  a summary first, then preview/open/download/details actions on demand.
- Package artifacts should expose a default app/open action when an `index.html`
  or equivalent entry exists.
- Text and Markdown artifacts should have a rendered preview option in addition
  to raw open and download.
- The implementation should remain shared with future bot surfaces through SDK
  or presentation abstractions, not Telegram-only protocol logic.

Acceptance:

- In real Safari Telegram, start from `/protocol list` or a recent-run command
  and complete a full run lifecycle without manually copying a long run GUID.
- Use a concise artifact list that names artifacts in human language and offers
  preview/open/download/details without a wall of URLs.
- Preview a Markdown artifact from Telegram through a rendered view.
- Open the generated package app/default file from Telegram without first
  browsing a raw package directory.
- Confirm M1 and M2 inherit the same behavior.

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

Latest verified real Safari run:

- Protocol: `Generic Offline CSV Analytics Builder`
- Protocol id: `aa64d5be4eba410cab39ab1676565264`
- Run: `afe7792a151c4e3ab74d4de7a7e2ec79`
- Created from a blank protocol through the UI.
- Published and started from the UI.
- Run inputs were sanitized generic local-CSV analytics requirements. They did
  not include real names, raw meeting transcript text, customer rows, or
  proprietary data.
- Stages:
  1. Define local analytics requirements - M1
  2. Build offline CSV analytics package - M2
  3. Validate offline analytics package - M1

Confirmed behavior:

- Stage 1 completed and produced `artifacts/requirements.md`
  (`artifact_1`, verified).
- Stage 2 delegated to M2 correctly and produced
  `artifacts/offline-analytics-package` (`artifact_2`, directory/package,
  verified, 71,969 bytes, sha prefix `91fcece63558`).
- Stage 3 completed on M1 and accepted the package: "Offline analytics package
  validated successfully with no blocking handoff issues."
- The run page showed `completed`, `3 / 3` stages, two output artifacts, zero
  issues, and package actions `Open`, `Contents`, `Download`, and `Copy path`.
- The package contents contained `index.html`, `README.md`,
  `validation-report.md`, and five sample CSV files under `samples/`.
- Registry and agent logs confirmed the M2 build stage executed through the
  normal protocol/delegation path; no database or API setup was used for
  scenario acceptance.
- The generated package was intentionally scenario-shaped, but the product
  protocol, launch fields, runtime, package verification, and package browsing
  stayed generic.

UX issues resolved during this pass:

- Stale linked-run behavior was addressed by subscribing conversation linked
  work to protocol-run websocket updates.
- Directory/package artifacts verify through the same artifact finalization
  path as file artifacts.
- Package contents browsing works generically for directory/package artifacts.
- Retry evidence marks previous attempts instead of presenting stale output
  state as current run state.
- Run progress now surfaces the live/current stage, task, participant, elapsed
  time, and clearer stage evidence labels.
- Expected-output warnings correctly accept a declared package directory that
  contains `index.html`, README, samples, and reports.

Generated SPA validation from the latest package:

- The package `Open` action opened
  `artifacts/offline-analytics-package/index.html` in real Safari from the run
  artifact UI.
- First load rendered a self-contained offline multi-CSV analytics app with
  upload, schema, relationship, aggregation, chart, heat-map, export, and
  synthetic-data controls.
- `Generate default synthetic data` produced 6 tables, 948 rows, 25 inferred
  candidates, and zero confirmed relationships.
- Accepting `Cells.panel_id -> Panels.panel_id` and
  `Process Measurements.panel_id -> Panels.panel_id` visibly updated the
  confirmed relationship count to 2 and reduced candidate count to 23.
- `Run aggregation` produced 432 joined source rows, 5 result groups, one join
  path, and rendered bar chart, trend chart, heat map, and aggregate table.
- The validator report inside the package recorded a pass, confirmed inline
  CSS/JS with no external script/CDN/fetch/XHR/sendBeacon/storage/API/database
  dependency, and exercised sample CSV loading plus adapted synthetic data in a
  JS harness.

Remaining issues after the latest scenario pass:

- Relationship inference remains heuristic and can present ambiguous
  high-confidence suggestions. This is acceptable for exploration because the
  app treats them as suggestions until the user confirms them.
- After accepting a relationship, aggregate helper text can remain stale until
  `Run aggregation` is clicked again. The run still produced correct results
  after the explicit aggregation action.
- Artifact package actions still need a broad surface check outside the run
  artifact page: stage detail, linked work, delegation/task detail, dashboard
  references, and Telegram.
- Telegram protocol parity still needs a live Telegram recheck, even though the
  Registry protocol path verified M1-to-M2 delegation.
- Full desktop and narrow Safari audits remain open for broad product polish.

## Open Blockers

| ID | Severity | Status | Issue | Evidence | Next acceptance step |
| --- | --- | --- | --- | --- | --- |
| P0-1 | Critical | Open | Workflow builder skill catalog breaks assignment continuity. | The builder can route authors to the generic Skills page without preserving stage assignment context. | In real Safari, create a blank protocol and verify stage-scoped skill search/select/create/return without losing draft data. |
| P0-2 | Critical | Open | Customer-handoff language can leak into protocol/runtime/artifacts. | Planning docs intentionally use handoff language, but runtime/product paths still need a source audit. | Search runtime/UI/prompt/test paths, remove product leaks, then run a small UI-authored protocol and inspect prompts/artifacts. |
| P1-1 | High | Open | Protocol authoring assignment matrix is not fully reverified after latest changes. | Manufacturing and analytics protocols were authored, but the generic no-skill/skill-only/agent-only/skill-plus-agent/new-skill matrix was not fully exercised. | Run the blank-protocol matrix in real Safari and fix any data-loss or navigation defects. |
| P1-2 | High | Partially verified | Artifact actions are not consistent across every surface. | Registry run/stage artifact links and Telegram open/download now work, but broad surfaces remain unverified; Telegram did not directly expose `index.html` inside the package. | Verify preview/open/default-app/contents/download/copy path from run overview, run artifacts, stage detail, task/delegation, conversation linked work, dashboard references, and Telegram. |
| P1-3 | High | Partially verified | Conversations, runs, and delegations can still feel unrelated or stale. | Linked work blank/stale behavior was improved, but end-to-end conversation -> delegation/run -> artifact -> conversation freshness has not been rerun after the latest fixes. | Start conversation work, delegate to M2, launch or link a protocol, and verify bidirectional lineage in real Safari. |
| P1-4 | High | Partially verified | Telegram protocol parity is incomplete. | M1/M2 can inspect existing run artifacts and export through shared registry paths; a fresh Telegram-started protocol run was not completed and cross-checked. | Use Telegram to list, start, watch, status, artifacts, export, download, unwatch, then open the same run in Registry. |
| P1-5 | High | Open | Telegram protocol UX is too command-centric for humans. | Live Telegram required opaque run GUIDs and produced dense artifact walls with full URLs; package default file and rendered preview were not discoverable. | Add/gate a human flow for recent/latest runs, numbered choices, concise artifact summaries, rendered previews, and package default app links; verify in M1 and M2. |
| P1-6 | High | Partially verified | Run progress is improved but needs broad non-analytics scale verification. | The manufacturing run was readable after completion; active progress at larger scale and non-analytics protocols still need live observation. | Run a larger generic protocol and verify bounded live stage progress, active state, failures/stale states, and reduced dense activity overload. |
| P1-7 | High | Open | Full desktop/narrow Safari audit is not complete after current blockers. | Several targeted Safari paths passed, but not a full desktop plus narrow pass across dashboard, protocols, editor, runs, conversations, skills, and artifacts. | Run the audit after P0/P1 functional blockers close. |
| P2-1 | Medium | Open | Clean-clone/customer-self-service pass remains unproven. | README/docs were updated, but a fresh setup from docs has not been executed. | Run setup from docs in a clean environment or equivalent dry run and fix product/docs gaps. |
| P2-2 | Medium | Open | Workspace cleanup UI needs post-deploy Safari verification. | Cleanup was authorized and used earlier, but the final post-deploy preservation/removal matrix was not reverified. | Use Dashboard cleanup in Safari and confirm agents/skills/guidance remain while workspace records are removed. |
| P2-3 | Medium | Open | Stale/interrupted run recovery needs UI confirmation after redeploy. | Stuck lease/timeout filters exist, but controlled interruption and recovery actions remain unproven. | Interrupt a disposable run safely, verify issue filters, then retry/cancel/send back from UI and inspect timeline. |

## Implementation Order

1. Verify stage-scoped skill select/create/return from a blank protocol.
2. Verify artifact actions across remaining reference surfaces, including
   package default `index.html` surfacing and rendered text/Markdown preview.
3. Verify conversation/delegation/run lineage freshness from a new run.
4. Verify Telegram protocol parity against the shared SDK behavior with a fresh
   Telegram-started run.
5. Fix and verify Telegram human UX: avoid GUID-first flows, use recent/latest
   run selection, compact artifact summaries, preview/open/download/details,
   and package default app links.
6. Run a larger generic protocol to audit progress visualization at scale.
7. Run clean-clone/docs pass.
8. Verify workspace cleanup and stale/interrupted run recovery from the UI.
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
