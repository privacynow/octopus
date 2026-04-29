# Customer Handoff Readiness Plan

This is the active product plan. It replaces the older capability-refactor plan
as the source of truth for what must be fixed before the repository can be
handed to a customer.

The customer does not care about curated artifacts, internal demos, or state we
created by direct API/database manipulation. The product must let a customer
clone the repo, start the system, create or use workflows through the UI and
supported bot surfaces, execute work, inspect runs, and open/download produced
artifacts without us narrating every click.

## Problem Statement

The product has useful building blocks:

- agents that execute work,
- skills that shape work,
- conversations,
- protocols,
- runs,
- delegations,
- artifacts,
- Registry UI,
- Telegram,
- Octopus CLI,
- SDK interfaces.

The handoff gap is that these pieces are not yet consistently presented as one
human workflow. A customer can still hit broken or confusing paths:

- first-run setup requires tribal knowledge,
- protocol creation can feel fragile,
- skills can feel mandatory when they should be optional,
- runs, delegations, conversations, and artifacts do not always show one clear
  lineage,
- generated/test/rehearsal data can still distort user expectations if not
  carefully gated,
- protocol use from conversations and Telegram is not yet obviously equivalent
  to Registry UI behavior,
- artifact actions are not consistently obvious everywhere,
- the local-only analytics use case is not supported as a repeatable UI-created
  workflow,
- docs and manuals can describe the ideal path while the product still exposes
  rough edges.

The goal is not to polish one generated artifact. The goal is to make the
product reliably produce, review, run, and inspect those artifacts from normal
customer-facing surfaces.

## Current Baseline

Completed background work that should remain regression-protected:

- User-facing `Capabilities` language was replaced with `Skills` in the product
  surface.
- SDK/admin naming was tightened around interfaces, implementations, admin
  operations, registry projection, skills, and routing skills.
- Generated/audit/test records are hidden by default on the main UI surfaces
  with explicit reveal controls.
- Agents, Skills, Conversations, and Runs have moved toward inline expansion
  rather than side drawers.
- Protocol runs expose Overview, Stages, Artifacts, and Audit structure.
- Artifact rows have a shared action model in current code paths: preview/open/
  download/copy path/unavailable reason.
- M1 and M2 are the verified customer-demo topology. M3 remains excluded unless
  Claude auth is configured.

Known current concern from the manufacturing analytics demo:

- The generated browser app can generate synthetic data and produce findings,
  but it is not a product acceptance artifact.
- The app has limited synthetic-data levers.
- The app does not expose enough schema/relationship editing controls for a
  customer to adapt complex extracts.
- The review notes identified field-mapping/key-validation gaps.
- These are evidence that the product needs better workflow guidance and
  artifact-quality checks, not evidence that we should hand-edit demo output.

## Product North Star

The customer should be able to do this from a clean clone:

1. Start Octopus.
2. Verify the Registry UI and agents are healthy.
3. Start a new conversation or open Protocols.
4. Create or choose a protocol.
5. Configure stages without being forced into skills or agents prematurely.
6. Execute the protocol.
7. Watch the run progress.
8. Inspect linked conversations/delegations/tasks in context.
9. Preview, open, download, or copy paths for produced artifacts.
10. Troubleshoot failed/stale/missing states without guessing.
11. Repeat the flow from the UI, Telegram, or documented CLI/API entry points
    where those surfaces intentionally expose the same behavior.

The manufacturing analytics customer path must specifically support:

- local-only handling of proprietary CSV/Oracle-derived data,
- using the model to generate local scripts/apps/tools rather than uploading raw
  customer rows to the model provider,
- explicit artifact declarations and outputs,
- review of generated code/tooling,
- browser or local execution of generated tooling,
- aggregate report/download output,
- clear privacy copy explaining what stays local and what is sent to the model.

## Hard Rules

- Do not create parallel implementations for the same product behavior.
- Do not seed database state as a substitute for testing the UI and bot paths.
- Do not make curated generated artifacts the acceptance target.
- Do not treat code-defined templates, starters, accelerators, or demo scripts
  as proof that users can create the workflow. The default customer path is
  blank protocol authoring in the Protocols UI. Templates are allowed only when
  a user publishes a protocol as a reusable template and later copies that
  user-authored template.
- Do not treat `scripts/demo/.../run_demo.py` as a customer path. It is an
  internal regression fixture only.
- Do not make skills mandatory for stage creation.
- Do not make agent selection mandatory for stage creation.
- Do not lose draft stage data when switching panels, tabs, stages, filters, or
  add-stage anchors.
- Do not expose internal selector/runtime/advanced controls on the normal
  authoring path.
- Do not let generated/test/rehearsal records dominate default customer pages.
- Do not use Registry-only concepts for behavior that must also work through
  SDK clients, Telegram, Slack, WhatsApp, or CLI.
- Do not introduce new vague nouns where existing product nouns are sufficient.
- Do not claim handoff readiness without a clean-clone pass and real Safari
  desktop plus narrow-mode verification.

## Definition Of Done

Customer-ready handoff is done only when every item below passes from a clean checkout
without direct database setup:

| Gate | Required Result |
| --- | --- |
| Clean clone | Customer can clone, configure, start, and verify the system from docs. |
| Agents | M1/M2 healthy state is visible and truthful; M3 is either configured or clearly optional. |
| New conversation | User can start a blank conversation without stale demo content. |
| Skills | User can inspect, activate, and use skills without seeing internal generated noise by default. |
| Agent targeting | User can send work to a specific agent and see that agent execute it. |
| Skill routing | User can route by skill and see the selected agent/work result. |
| Protocol authoring | User can create a protocol, add/remove/reorder stages, leave stages unassigned, assign only a skill, assign only an agent, assign both, or mark a needed new skill. |
| Protocol execution | User can publish/start a protocol from UI and conversation surfaces; stages progress and terminal state is correct. |
| Runs | User can find the run, understand status, inspect stages, linked work, and audit without all sections expanding at once. |
| Artifacts | Every artifact reference shows the same state/action contract: declared, missing, produced, previewable, openable, downloadable, copyable, or unavailable with reason. |
| Conversations | Conversations with linked work are not empty-looking; they show the relationship to runs/delegations/artifacts. |
| Telegram | Telegram can list/start/status/watch protocol runs and expose artifact state through the shared SDK path. |
| Local analytics | User can use the product to generate local-only analysis tooling for CSV-like manufacturing data without uploading raw rows to the model. |
| Docs | README, setup guide, customer manual, data analytics walkthrough, and troubleshooting match the actual product. |
| Audit | Real Safari desktop and narrow mode pass; automated regression suite passes; remaining issues are documented and not handoff blockers. |

## Active Workstreams

### W0: Clean Clone And First-Run Setup

Problem:

The customer handoff begins before the UI. If setup is confusing, the demo fails
before product value is visible.

Implementation:

1. Create or update a single setup path in the README.
2. Document prerequisites: Git, Docker, required ports, model credentials, and
   optional Claude/M3 configuration.
3. Provide one command path to start the stack.
4. Add a smoke command that proves Registry, M1, and M2 are healthy.
5. Make M3 optional and explicit in docs unless Claude auth is present.
6. Ensure demo data is not required for the first meaningful path.
7. Add troubleshooting for stale containers, cache, ports, missing auth, and
   failed agent enrollment.
8. Document the blank-authoring path for the local analytics use case:
   - user opens `Build -> Protocols`,
   - user clicks `New protocol`,
   - user creates stages, files, assignments, and routing from scratch,
   - user publishes and runs the protocol through the same UI/API pipeline used
     by every normal author.

Acceptance:

- A fresh clone can start the system using only the documented path.
- UI health, `./octopus status`, and API health agree.
- The docs do not mention stale setup paths or removed root planning files.
- A customer can create the local analytics protocol from blank without editing
  code, running `run_demo.py`, using a hidden built-in, or touching advanced
  runtime fields.

### W1: Navigation And Product Information Architecture

Problem:

The UI still risks exposing implementation concepts as peer products. A
customer needs a small, stable mental model.

Target IA:

- Work: Conversations, Runs, Agents, Delegations if standalone delegated work is
  intentionally exposed.
- Build: Protocols, Skills.
- Operations: Dashboard, Usage, Guidance, Routing, diagnostics/admin.

Implementation:

1. Review current navigation in real Safari desktop and narrow mode.
2. Remove or hide destinations that are empty, duplicate, or operator-only.
3. Keep deep links for diagnostic routes, but do not promote them in default nav.
4. Ensure Agents lives where users start/inspect work, not under a fake Team
   concept.
5. Ensure templates are a Protocols utility, not a separate product gallery.
6. Ensure Guidance is framed as Build or Operations according to actual user
   task, not buried under a misleading admin bucket.

Acceptance:

- A first-time user can explain the sidebar after one pass.
- No top-level item opens an empty or redundant surface.
- Each major noun has one canonical home.

### W2: Protocol Authoring From UI

Problem:

Protocol creation must be safe and progressive. Users must not lose work or be
forced into decisions they are not ready to make.

Implementation:

1. Audit protocol creation from the UI in real Safari.
2. Fix stage creation so partially entered data is never lost.
3. Support these assignment states naturally:
   - no assignment yet,
   - skill only,
   - agent only,
   - skill plus preferred agent,
   - needed new skill,
   - later operator-only/internal configuration.
4. Make add-stage insert below the current stage, not only at the end.
5. Keep inline stage editing progressive, not sprawling.
6. Ensure stage artifacts are edited in stage context, not in an unclosable
   drawer at the bottom of the page.
7. Ensure workflow map remains interactive and on-demand without replacing the
   primary authoring path.
8. Remove tests that assert old standard-path Advanced/custom-runtime/internal
   controls; keep only operator-path coverage if the operator path exists.

Acceptance:

- User creates a protocol from blank using UI only.
- User can create the manufacturing/local analytics workflow from a blank
  protocol in the Protocols UI without editing code or relying on a silent
  pre-seeded template.
- User can still manually inspect/edit the generated stages and artifacts after
  creation.
- User adds, removes, edits, and reorders stages without lost input.
- User creates a stage with no skill and no agent.
- User creates a stage with only an agent.
- User creates a stage with only a skill.
- User creates a stage with a needed new skill.
- User declares input and output artifacts per stage.
- User publishes and runs the protocol.

### W3: Protocol Execution, Runs, Delegations, And Lineage

Problem:

Runs, tasks/delegations, conversations, and artifacts can still appear as
independent concepts. Users need one lineage: intent -> work -> execution ->
outputs.

Implementation:

1. Make Runs the canonical surface for protocol execution.
2. Keep standalone Delegations as agent-to-agent work, not protocol stage peers.
3. In Conversations, show linked runs/delegations/artifacts inline when they
   exist.
4. In Runs, show stage tasks/delegations as children of run/stage.
5. Make status truthful:
   - running,
   - waiting for human,
   - completed,
   - failed,
   - stale running,
   - canceled,
   - blocked/unavailable.
6. Add stale lease detection and visible recovery language.
7. Add cleanup/retention policy for generated, stale, failed, and historical
   runs without hiding important audit history.

Acceptance:

- A user can start from a conversation and find the resulting run.
- A user can start from a run and find related conversations/delegations.
- A user can see whether a run is truly running or stale.
- Pagination keeps selected items visible and never blanks stage/run content.

### W4: Artifact Contract Everywhere

Problem:

Artifacts are the customer-visible proof of value. They must be first-class and
consistent wherever referenced.

Implementation:

1. Use one shared artifact row/action helper everywhere.
2. Apply it to:
   - Runs overview,
   - Runs artifacts tab,
   - stage details,
   - task/delegation details,
   - conversation linked work,
   - dashboard references,
   - Telegram artifact responses.
3. Represent artifact states explicitly:
   - declared but not produced,
   - produced and previewable,
   - produced and downloadable,
   - produced but unavailable on this host,
   - path/reference only,
   - failed generation.
4. Keep preview/open/download/copy path actions separate and visibly clickable.
5. Avoid full-row button nesting that hides actions from accessibility tools.
6. Cap text previews and render unsupported formats with clear fallback copy.

Acceptance:

- A produced text/markdown/CSV/code artifact can be previewed.
- A produced artifact can be downloaded.
- A path can be copied even when content is unavailable.
- Missing declared outputs do not look clickable or broken.
- Same artifact appears consistently from run, stage, task, conversation, and
  Telegram where applicable.

### W5: Protocols From Conversations And Bot Surfaces

Problem:

Protocols should be usable like skills from conversations and bot channels. This
must not be a Registry UI special.

Implementation:

1. Keep Registry APIs canonical for protocol persistence/execution.
2. Put shared protocol client/service behavior in the SDK.
3. Keep Telegram parsing/rendering channel-specific, but use SDK protocol
   service for list/start/status/watch/actions/artifacts.
4. Ensure Registry UI and Telegram launch equivalent runs.
5. Expose only useful protocol operations in Telegram:
   - list,
   - start,
   - status,
   - watch/unwatch,
   - actions where safe,
   - artifacts,
   - links to Registry for authoring.
6. Do not expose full protocol authoring in Telegram unless a future product
   decision explicitly calls for it.
7. Make future Slack/WhatsApp able to reuse the same SDK protocol service.

Acceptance:

- Registry UI can launch a published protocol from a conversation.
- Telegram can launch the same protocol and produce equivalent run lineage.
- Telegram can show artifact state for the run.
- Protocol behavior does not live as duplicated workflow logic inside Telegram.

### W6: Local-Only Manufacturing Analytics Workflow

Problem:

The customer use case is not "upload proprietary CSVs to a model." The product
must guide the user to generate local tooling that operates on local files.

Implementation:

1. Support this use case through the normal blank protocol authoring flow. Do
   not add a customer-specific starter, accelerator, hidden template, database
   seed, dashboard shortcut, or code-defined blueprint.
2. Document the manual construction path as the primary customer path:
   - protocol name and description,
   - customer-ready stage sequence,
   - assignment options,
   - artifact keys, paths, and descriptions,
   - transitions,
   - run dialog input fields,
   - review acceptance criteria.
3. Ensure the Protocols UI supports the authoring mechanics needed to build the
   workflow from blank:
   - stage creation does not require a skill,
   - stage creation does not require an agent,
   - file/artifact declarations are stage-aware and reusable,
   - routing can be expressed without internal runtime controls,
   - run input prompts can be configured from protocol metadata through UI or
     another standard authoring surface.
4. Create a customer-authored protocol flow that asks for:
   - data source type: CSV extracts, Oracle tables, or synthetic demo,
   - table/file names,
   - key relationships,
   - business question,
   - privacy constraint,
   - desired output format: script, browser app, report, notebook, or all.
5. Ensure the model receives only schema/intent/sample-safe descriptions unless
   the user explicitly provides sample data.
6. Generate local artifacts:
   - requirements,
   - data contract/schema map,
   - executable local script or browser app,
   - README/run instructions,
   - validation checklist,
   - aggregate-report output contract.
7. Add an artifact review stage that checks:
   - no network/model calls from generated local tooling,
   - local file loading works,
   - synthetic data generation is tunable enough,
   - schema/key relationships are editable,
   - outputs are aggregate by default,
   - raw export is separate and clearly local.
8. Add a final handoff stage that produces customer instructions for running the
   generated tool locally.
9. Keep `scripts/demo/manufacturing_local_analytics/run_demo.py` only as an
   internal deterministic regression fixture. It may validate artifact quality,
   but it must not be referenced as the customer acceptance path.
10. Remove code-defined protocol templates from product surfaces. If an
    internal fixture remains for tests, it must not be loaded by Registry
    template APIs, shown in Protocols, or described as a customer path.

Recommended protocol stages:

1. Intake and privacy boundary.
2. Data contract and relationship design.
3. Tooling implementation.
4. Local execution/verification.
5. Review and handoff package.

Acceptance:

- User creates/runs this workflow from a blank protocol in Protocols UI only.
- The workflow produces a local tool artifact and a human README.
- Raw customer rows are not required or transmitted to the model.
- Synthetic demo mode produces visible findings.
- The user can open/download the generated tool and instructions from the run.
- A run cannot be accepted if a declared renderable artifact is only a
  placeholder saying validation did not pass.

### W7: Generated Artifact Quality Gates

Problem:

Generated artifacts can technically exist but still be unsuitable for handoff.
The product needs review criteria that fail the run or mark it needing revision.

Implementation:

1. Add protocol instructions that require explicit acceptance criteria for
   generated apps/scripts.
2. For local analytics tools, require checks for:
   - tunable synthetic data levers,
   - add/remove fields or a documented schema-extension path,
   - editable key relationships,
   - mapping-aware validation,
   - no external dependencies unless declared,
   - no external network calls for local processing,
   - clear run instructions,
   - visible aggregate outputs,
   - downloadable reports.
3. In the UI, make review results visible as run/stage evidence, not hidden in
   a text artifact only.
4. When review finds partial gaps, show "accepted with issues" or "needs
   revision" clearly.

Acceptance:

- The review stage can reject or send back incomplete generated artifacts.
- The run Overview shows the review decision.
- Artifact gaps are visible without opening every raw file.

### W8: Documentation And Customer Manual

Problem:

Docs must describe the product that exists, not the product we wish existed.

Implementation:

1. Update README with:
   - product overview,
   - setup,
   - first run,
   - agent health,
   - common failures,
   - data privacy boundary.
2. Add or update customer guide:
   - start system,
   - start conversation,
   - use skills,
   - create a protocol,
   - run a protocol,
   - inspect artifacts,
   - use local-only analytics workflow.
3. Add troubleshooting:
   - Docker not running,
   - port conflict,
   - missing model credentials,
   - M3/Claude optional auth,
   - stale Safari cache,
   - missing artifact path,
   - stale run,
   - Telegram failure.
4. Add a demo script that does not depend on curated hidden state.
5. Remove or archive stale docs that contradict current nouns or routes.

Acceptance:

- A customer can follow the docs from clone to first successful run.
- The docs include exact clicks/commands for the golden path.
- The docs do not reference removed `Capabilities` UI copy or removed
  `/ui/templates`/`/ui/gallery` product routes.

### W9: Visual, Accessibility, And Responsiveness Audit

Problem:

Previous spot checks missed customer-visible bugs. The audit must be scenario
driven and performed in the real browser surfaces customers will use.

Implementation:

1. Fix known blockers before the 500+ screenshot breadth audit.
2. Run scenario-depth tests first:
   - clean setup,
   - conversations,
   - skills,
   - agents,
   - protocol authoring,
   - protocol execution,
   - runs,
   - artifacts,
   - Telegram,
   - local analytics.
3. Then run broad visual audit:
   - real Safari desktop,
   - real Safari narrow mode,
   - in-app browser smoke,
   - light/dark theme if supported,
   - keyboard navigation,
   - screen-reader/accessibility tree spot checks.
4. Record issues in this file as open blockers or non-blocking followups.

Acceptance:

- No known blocker remains open.
- Screenshots show consistent inline expansion, readable pills/buttons, and
  visible artifact actions.
- The product is usable without us pointing at hidden actions.

## Golden Customer Scenarios

These are the minimum UI-first scenarios. They must be automated where possible
and manually verified in real Safari before handoff.

### Scenario A: Clean Clone To First Useful Output

1. Clone repo.
2. Configure required credentials.
3. Start stack.
4. Open Registry UI.
5. Confirm M1/M2 health.
6. Start a conversation.
7. Ask for a small work product using a skill.
8. Verify response, linked work, and events.

Pass criteria:

- No stale demo prompt appears in the new conversation.
- Work completes.
- User can find what happened from the UI.

### Scenario B: Agent And Skill Routing

1. Open Agents.
2. Inspect M1 and M2.
3. Start conversation with one agent.
4. Route a request to a specific agent.
5. Route a request by skill.
6. Inspect resulting conversation/work state.

Pass criteria:

- Targeted agent identity is visible.
- Routed work completes or fails with clear reason.
- Skills list is readable and not flooded.

### Scenario C: Protocol Authoring From Blank

1. Open Protocols.
2. Create blank protocol.
3. Add five stages.
4. Leave one unassigned.
5. Assign one to a skill only.
6. Assign one to an agent only.
7. Assign one to skill plus preferred agent.
8. Add input/output artifacts.
9. Publish.
10. Start run.

Pass criteria:

- No stage data is lost.
- No required field blocks an intentionally blank assignment.
- Run appears in Runs.
- Stage artifacts are visible in context.

### Scenario D: Conversation-Launched Protocol

1. Start conversation.
2. Open protocol launcher.
3. Select published protocol.
4. Provide problem statement.
5. Start run.
6. Inspect linked run and artifacts from conversation.

Pass criteria:

- Conversation does not look empty.
- Run lineage is visible.
- Artifacts are accessible from both run and conversation paths.

### Scenario E: Telegram Protocol Run

1. List protocols in Telegram.
2. Start a protocol with a problem statement.
3. Check status.
4. Watch updates.
5. Inspect artifacts.
6. Open Registry link to the same run.

Pass criteria:

- Telegram and Registry reference the same run.
- Artifact state matches.
- Protocol semantics come from shared SDK service.

### Scenario F: Local-Only Manufacturing Analytics

1. Open `Build -> Protocols`.
2. Click `New protocol`.
3. Name the blank protocol for local manufacturing analytics.
4. Define files/artifacts for the app or script, README, report, validation
   manifest, and generated aggregate outputs.
5. Add the stages from scratch.
6. Assign stages by skill, by agent, both, or neither where appropriate.
7. Define transitions and terminal success/failure outcomes.
8. Publish the protocol.
9. Start the protocol from UI.
10. State the privacy constraint: raw CSVs must not be sent to model provider.
11. Provide schema/table names and relationships manually through UI.
12. Generate local tool artifacts.
13. Open/download generated local tool and README.
14. Run synthetic demo mode.
15. Verify aggregate findings and downloadable report.

Pass criteria:

- The model never needs raw customer CSV rows.
- Produced artifacts are visible from the run.
- Generated tooling is useful without manual patching.
- Review stage catches missing local-tool requirements.

## Implementation Sequence

Execute in this order. Do not begin the final broad audit until phases 1-7 are
green.

### Phase 1: Handoff Setup And Docs Baseline

- Fix README/setup guide.
- Add clean-clone smoke instructions.
- Verify current stack start.
- Document M3 optional state.

### Phase 2: Protocol Authoring Reliability

- Fix UI-only stage creation, preservation, assignment, and artifact editing.
- Add/extend Playwright coverage for authoring states.
- Verify real Safari.

### Phase 3: Runs, Lineage, Artifacts

- Fix run/stage pagination and blank stage detail issues.
- Ensure artifact action contract everywhere.
- Add stale status semantics.
- Verify run/delegation/conversation drill-through.

### Phase 4: Conversation And Telegram Protocol Parity

- Finish shared SDK protocol service use.
- Ensure Telegram protocol artifact commands work.
- Verify Registry and Telegram equivalent runs.

### Phase 5: Local Analytics Workflow

- Build the workflow from blank through product primitives.
- Do not add built-in templates, starters, accelerators, hidden shortcuts, or
  database seeds.
- Ensure generated artifact review criteria are explicit.
- Verify no direct database setup.

### Phase 6: UI/UX Consistency

- Audit desktop and narrow layouts.
- Fix inconsistent expansion/drawer/tab/action models.
- Fix unreadable pills/buttons and dense screens.
- Keep progressive disclosure across stages/runs/conversations/agents/skills.

### Phase 7: Customer Manual

- Write step-by-step customer manual.
- Include data analytics workflow.
- Include troubleshooting.
- Verify every documented step against the deployed product.

### Phase 8: Full Acceptance Audit

- Run automated tests.
- Deploy clean.
- Hard-refresh real Safari.
- Run all golden scenarios.
- Run 500+ screenshot breadth audit after known blockers are fixed.
- Record any remaining non-blockers with severity and customer impact.

## Verification Matrix

| Check | What It Proves |
| --- | --- |
| `git diff --check` | Patch hygiene. |
| `node --check` on edited UI JS | No syntax regression in touched JS. |
| `.venv/bin/python -m pytest -q` | Python unit/integration suite is green. |
| `tests/test_registry_ui_contract.py` | UI vocabulary/routes/shared helper contracts hold. |
| `tests/test_protocols.py` and `tests/test_protocol_service.py` | Protocol creation/execution service behavior holds. |
| `tests/test_protocol_telegram.py` | Telegram protocol commands match shared behavior. |
| `tests/test_registry_sdk_contract.py` | SDK/Registry boundary remains coherent. |
| Playwright protocol UI suite | UI authoring/execution/artifact flows work. |
| Playwright work-surface suite | Conversations/Runs/Agents/Skills/Delegations remain usable. |
| Clean clone smoke | Docs and startup are real. |
| Real Safari desktop pass | Actual customer browser behavior works. |
| Real Safari narrow pass | Responsive mode works. |
| Telegram live/stub pass | Bot surface works beyond Registry UI. |
| Artifact drill-through pass | Artifacts can be found and acted on from every reference surface. |
| Local analytics pass | Customer use case works without uploading raw data. |

## Deployment And Audit Rule

For any handoff claim:

1. Commit and push from this repo.
2. Pull in the Octopus deployment checkout.
3. Redeploy from the deployment checkout.
4. Hard-refresh Safari with `Option+Command+R`.
5. Verify real Safari desktop.
6. Verify real Safari narrow mode.
7. Verify Telegram if bot behavior changed.
8. Record results in this file or in the customer handoff checklist.

## Open Blockers

| ID | Blocker | Required Fix |
| --- | --- | --- |
| H1 | Product is not clean-clone/customer-self-service proven. | Run and document clean-clone setup plus smoke. |
| H2 | Protocol authoring still needs full Safari UI-first verification. | Execute Scenario C and fix any state loss/assignment/artifact issues. |
| H3 | Run stage pagination/detail can blank or stick on wrong stage in Safari. | Fix selected-stage state and pagination; add regression test. |
| H4 | Artifact access must be verified across all references. | Run artifact drill-through from run, stage, task, conversation, Telegram. |
| H5 | Conversation-launched protocols need customer-obvious flow and lineage. | Execute Scenario D and fix missing linked-work presentation. |
| H6 | Telegram protocol parity must be rechecked after SDK/service work. | Execute Scenario E against live/stub topology. |
| H7 | Local-only analytics workflow is not yet a repeatable blank-authored product path. | Implement and verify Scenario F. |
| H8 | Customer docs/manual are not yet acceptance-tested. | Update docs and run every documented step. |
| H9 | Full real Safari desktop/narrow audit has not been completed after known blockers. | Run audit only after H1-H8 are addressed. |
| H10 | Manufacturing analytics acceptance still relied on code-defined starter/script references. | Remove built-in starter exposure; verify in real Safari that customer creates the protocol from blank UI and that `run_demo.py` is not part of acceptance. |
| H11 | UI-created manufacturing run accepted a placeholder heatmap that said validation did not pass. | Protocol instructions and launch defaults now reject placeholder/render-failed artifacts; rerun from UI and verify terminal artifacts. |
| H12 | Running protocol stages did not explain liveness/current state to the user. | Implemented run Overview liveness guidance with current stage, elapsed time, event update, output counts, and completed-run estimate when history exists; verify in real Safari during a live run. |
| H13 | Workspace reset required container/database intervention outside the product. | Implemented Dashboard workspace-data cleanup guarded by Registry UI password and `CLEAN` confirmation; verify it preserves agents/skills/guidance while removing workspace work records. |
| H14 | Run list could advance to a newer stage while the expanded run detail still showed the previous stage. | Runs now queue a selected-detail refresh whenever the list row has a newer status, stage, version, or timestamp; verify live run list, Overview, Stages, and Artifacts agree in real Safari. |
| H15 | Redeploying while a protocol stage task is running can leave the Registry task/run shown as running even when no provider command remains active in the bot container. | SDK routed-work recovery now reports interrupted routed tasks as failed results instead of leaving them hidden in pending recovery; redeploy and verify the UI shows terminal retryable state. |

## Non-Goals For Handoff

- Hand-editing a generated artifact and calling the product ready.
- Using `run_demo.py`, a hidden built-in template, a seeded template, or a
  customer-specific shortcut as the customer proof instead of blank UI
  authoring.
- Requiring a customer to use hidden URLs or direct API calls.
- Requiring direct database writes.
- Presenting M3/Claude as required when auth is not configured.
- Exposing operator-only authoring internals to normal users.
- Shipping a separate template/gallery UI when Protocols already owns
  user-authored reusable templates.

## Decision Log

- `issues.md` is the active handoff readiness plan.
- `plan_fix.md` remains removed; do not recreate it unless the team explicitly
  decides to rename this file.
- Skills is the user-facing noun; do not reintroduce Capabilities as product
  copy.
- Registry owns canonical protocol APIs and persistence.
- SDK owns shared client/service behavior for protocol use across channels.
- Telegram is a peer surface using shared SDK behavior, not a separate protocol
  implementation.
- Customer acceptance is based on repeatable product flows, not curated output
  files.
- Blank protocol authoring is the default product path.
- User-authored templates remain supported: publish a protocol as a template,
  then copy that saved template into a new editable protocol.
- Code-defined built-in protocol templates/starters are not part of the product
  surface.
