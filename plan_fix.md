# Registry Human-Usability Refactor Plan

## Status

This is the active plan. It replaces the previous incremental UI cleanup plan.

Implementation progress:

- Runs default split-pane composition has been removed in source. The selected
  run now expands inline through the existing `Kit.runsList` path.
- Runs route now has a viewport-bounded shell so long selected-run content
  scrolls inside the work area instead of forcing page-level document scroll.
- Conversation list rows now support inline inspection for status, agent,
  primary actions, and linked runs before opening the full conversation
  workspace.
- Conversation list now has a viewport-bounded shell with internal list
  scrolling.
- Shared artifact action rendering is still reused; no new artifact row path
  was introduced.
- Runs evidence now uses the single `Overview / Stages / Artifacts / Audit`
  model in source, and `Stages` has a nested stage navigator so a long protocol
  does not dump every stage card at once.
- The latest broad Playwright pass exposed follow-on issues now tracked in the
  active work: authoring was requesting disconnected M3's skill catalog and
  surfacing 503 console errors; E2E specs still encoded removed `Outputs` and
  `Open conversation` labels; one data-analysis execution remained `running`
  beyond the current scenario timeout and must be inspected as a real stuck-run
  risk, not dismissed as a test artifact.
- The next broad Playwright pass narrowed the active failures to two concrete
  UI/product issues: run stage evidence navigation was not switching away from
  the current stage when a stage execution id was missing or unstable, and the
  meta-assistant scenario kept creating timestamp-named custom capabilities
  that polluted authoring lists. Both are now treated as product regressions,
  not only test-maintenance problems.
- Remaining phases still require full visual audit, broader Work-surface
  alignment, deployment verification, and end-to-end scenario execution.

The latest finding is product-level, not page-level: the Registry still has
multiple competing interaction models for the same kind of object. Stages and
some task views use progressive inline expansion. Runs now expand inline, but
the expanded run still renders outputs, execution, participants, decisions, and
issues as unrelated sub-apps with different layout models. Conversations use a
full-page document/workspace with long vertical flow. Agents, capabilities,
protocol authoring, tasks, approvals, and artifacts each expose related
concepts with different density, action placement, and expansion behavior.

That inconsistency is the core usability failure. The fix is not more local CSS
or another one-off Runs redesign. The fix is one Registry interaction grammar,
applied across every major surface.

## What Went Wrong In The Previous Pass

The prior work improved pieces of the UI but did not fully solve the human
workflow:

- Desktop was treated as wider mobile instead of a distinct work surface with
  its own hierarchy and reading rhythm.
- Runs moved to inline expansion but kept the old mental model inside the
  expanded detail: Outputs, Execution, Participants, Decisions, and Issues each
  tell a different story about the same run evidence.
- Conversations still behave like a long document rather than a bounded
  workspace with persistent context and reachable actions.
- Related objects such as run, task, conversation, approval, stage, and artifact
  are still rendered as neighboring resources instead of one lineage.
- Some clickable-looking rows do not reveal the expected details in place.
- Horizontal pressure was reduced in isolated spots but not solved at the
  interaction-model level.
- Vertical overflow is still uncontrolled on long Runs and Conversations views,
  and Runs can embed a dense dashboard inside a single expanded row.
- Dense metadata, repeated pills, borders, and raw technical concepts still
  compete with the user's actual job.

The new plan treats these symptoms as one design-system and product-flow issue.

## Product North Star

A human user should be able to:

- create or choose a protocol
- start work from a conversation, agent, protocol, or dashboard
- follow execution from protocol to run to stage to task to artifact
- understand what happened without joining separate lists mentally
- preview, open, download, or copy produced artifacts wherever they appear
- recover from blocked, failed, or stale work without needing raw internals
- use agents and capabilities without understanding selector diagnostics,
  workers, raw capacity, or routing plumbing

The UI must make the workflow visible through product concepts, not through
database objects or implementation layers.

## Latest Active Fixes

- Real Safari full-audit pass on 2026-04-24 confirmed the next blocking
  defect: completed protocol stage tasks opened by clicking a collapsed Tasks
  row did not re-render into their expanded artifact state, even when the API
  payload already contained `result.artifacts` and the matching Run showed the
  artifacts. This violates the artifact action contract because a human
  entering from Tasks cannot preview, open, download, or copy output paths
  without knowing to jump to Runs. Fix direction: keep the existing shared task
  artifact renderer, make expansion state part of the task-list render
  signature and the keyed item signature, then force one re-render when a row
  expands or collapses.
- The same Safari pass confirmed the Runs and Dashboard surfaces still expose
  stale/running protocol work as normal `running` or `leased` work even when a
  stuck-lease issue exists elsewhere. This is tracked as an active usability
  follow-up: stale state must be visible at the row/card where the user sees
  the work, not only inside a separate issue tab or dashboard footer.
- The same Safari pass confirmed the Protocols list is functionally correct but
  visually flooded by timestamped/generated scenario definitions. This is a
  release-readiness risk for human use. Test-created protocols must either be
  cleaned up, created in an explicit test namespace, or filtered from the
  default team-authored list without hiding real team protocols.
- Run stage evidence navigation must be keyed by a stable stage identity with a
  safe fallback to stage key, so clicking `Load data`, `Architecture`, or any
  other stage changes the inline evidence card predictably.
- Generated timestamp capability names must not appear in default authoring
  lists. Capability lists may expose them through explicit search or operator
  tooling, but normal protocol authoring should remain human-scaled.
- E2E scenario fixtures must reuse human-named capabilities instead of creating
  new timestamp-named skills on every run. Test data that makes the product UI
  worse is itself a product-quality failure.
- After every redeploy, real Safari must be hard-refreshed with
  `Option+Command+R` before visual judgment, because a normal reload can keep
  stale CSS and JavaScript assets.
- Shared segmented controls must activate from the button itself, not from a
  fragile delegated click path. Run evidence, stage editor subtabs, and other
  tabbed controls should all inherit the same reliable behavior from
  `UI.createSegmentedControl`.
- Run detail global chrome must stay quiet. Summary metadata and run-level
  interventions belong in `Overview`, not above every evidence tab. Retry,
  accept, send back, and cancel should only appear when the current run state
  and stage transitions make that action real; export remains available as an
  audit action.
- Dark theme kit pills must use the shared theme tokens instead of falling back
  to light-only `--color-*` defaults. Filter chips, status chips, and related
  list pills must remain readable in both light and dark themes.
- Artifact rows may remain row-clickable for preview, but their accessible name
  must describe the artifact itself, not swallow child actions such as
  `Preview`, `Open`, `Download`, and `Copy path`.

## Core Product Rule

Use one object interaction grammar everywhere:

1. A row/card gives a readable summary.
2. Clicking the row expands details inline directly under that row/card.
3. Only one item in a list is expanded by default unless a surface explicitly
   needs multi-select comparison.
4. The expanded content is progressive: summary first, artifacts/actions next,
   lineage/context next, technical details last.
5. Full detail pages still exist for deep links and power use, but they are
   secondary. They must not be the only way to inspect an object.
6. URLs with an object id select and expand the matching row, not just open a
   disconnected side panel.

This same grammar applies to runs, conversations, tasks, approvals, protocol
stages, agents, capabilities, and dashboard work cards unless there is a clear
product reason to make an exception.

## Runs Product Model

The Runs surface must use one hierarchy:

1. Run
2. Stages in authored workflow order
3. Stage evidence
4. Artifacts, tasks, decisions, participants, and issues attached to that stage

Global run views are allowed, but they must be rollups of this hierarchy, not a
second unrelated model. For example:

- `Overview` summarizes the run state, current problem, blocking issues, and
  next actions.
- `Stages` is the primary inspection model and shows stages in workflow order
  from Planning through Acceptance.
- `Artifacts` is the same artifact renderer grouped by producing stage; it is
  not a separate flat artifact universe with a different visual language.
- `Audit` is the raw operational escape hatch for participants, decisions, and
  technical events.

Runs fails usability review if:

- the same artifact appears in `Outputs` and `Execution` through different row
  models
- stage order is reversed from the authored workflow
- more than two navigation layers are visible at once
- status problems such as stuck leases are hidden behind an Issues tab
- participants and decisions are shown as primary concepts before the user can
  understand the stage they belong to
- a user must mentally join run, task, stage, conversation, and artifact from
  separate screens to understand what happened

## Viewport Contract

Primary Registry work surfaces must be viewport-bounded:

- The app shell stays within the browser viewport.
- Navigation and page identity remain stable.
- Search/filter/action regions do not scroll away immediately.
- Lists use internal scrolling or visible pagination sized to the available
  work area.
- Expanded details are contained and scroll internally when needed.
- Conversation composer and primary actions remain reachable.
- No surface relies on full-document vertical scrolling for normal operation.
- No surface introduces horizontal page overflow at desktop or narrow widths.

Long content is allowed, but it must live inside an intentional work region, not
push the whole application below the screen.

## Shared Design Contracts

### 1. Expandable Object Row

Every repeated operational object should use the same contract:

- summary title
- human status
- key context
- primary action or inline expand action
- secondary actions that wrap inside the row
- expanded region directly below the selected row

Rows that do not expand or navigate must not look clickable.

### 2. Progressive Expansion Panel

Expanded panels use the same section order:

1. Outcome or current state
2. Primary actions
3. Produced or expected artifacts
4. Lineage and related work
5. Decisions, approvals, or issues
6. Technical details

Sections should be collapsed or summarized when they are not central to the
current task.

### 3. Execution Lineage

Execution views must present one story:

- protocol
- run
- stage
- task
- assigned agent or participant
- conversation or activity
- approval or decision
- artifacts

The user should be able to enter from any of these objects and understand the
same hierarchy.

### 4. Artifact Action Contract

Every concrete artifact reference uses the same shared artifact row:

- label
- producing stage/task
- path
- verification or availability state
- Preview when previewable
- Open when browser-viewable
- Download when bytes are available
- Copy path

Declared artifacts that have not been produced must say `Not produced yet` or
`Declared only`. They must not render broken Preview/Open/Download actions.

### 5. Capability Contract

Users see capabilities. Operators see routing internals.

Default authoring and conversation surfaces should show:

- capability name
- plain-language description
- available agents
- where it can be used
- setup state

Default surfaces should not show selector resolution, advertised skill plumbing,
generated timestamp skill spam, raw worker state, or raw capacity mutation.

### 6. Density Contract

Lower density is achieved by reducing simultaneous concepts, not by shrinking
everything.

Default UI should use:

- fewer borders
- calmer typography for inactive rows
- more whitespace around major decisions
- compact rows only for repeated scan lists
- plain-language labels instead of raw IDs wherever possible
- technical details behind explicit disclosure

## Current Live Defects To Fix

### Runs

Observed problem:

- Runs uses inline expansion now, but the expanded detail still has no single
  product model.
- `Outputs` presents artifacts as a flat list.
- `Execution` presents stage outputs through a different stage card model.
- `Participants` and `Decisions` expose raw operational records as peer tabs,
  even though they are usually supporting evidence for a stage.
- `Issues` hides critical state such as stuck leases behind a tab instead of
  elevating it to the run row and header.
- Stage order in Execution can be reverse-chronological instead of authored
  workflow order, so Acceptance appears before Planning.
- The detail region can show triage tabs, status chips, run-row expansion,
  detail tabs, participant filters, stage tabs, metadata cards, action groups,
  and artifact rows at the same time.
- The visual language changes between subtabs, making users infer whether they
  are looking at the same evidence, a different evidence set, or raw internals.

Target behavior:

- Runs list remains full-width within the work area.
- Clicking a run expands the run detail inline under that run row.
- The expanded run panel uses four progressive sections at most:
  - `Overview`: state, outcome, active issue, next action, and root context
  - `Stages`: workflow-ordered stage timeline with stage evidence inline
  - `Artifacts`: the same artifact row grouped by producing stage
  - `Audit`: decisions, participants, raw task links, and support diagnostics
- Stage order follows the authored workflow, not reverse execution insertion
  order.
- Output artifacts and stage artifacts use the same renderer and same action
  placement.
- Participants and decisions are contextual inside Stages first, then available
  in Audit for raw inspection.
- Critical issues are elevated into the run row and Overview before the user
  opens Audit.
- Deep links select and expand the target run and open the most relevant
  section without creating another route-specific model.
- Long lineage uses contained scrolling or section pagination inside the
  expanded run panel.
- `Stages` uses one nested stage navigator and renders one active stage evidence
  card at a time; the authored workflow remains visible without turning the run
  into a vertical wall.

### Conversations

Observed problem:

- Conversation list is calmer than Runs but still uses full-page vertical flow.
- Selecting a conversation navigates away instead of first offering inline
  context.
- Conversation detail can become a long workspace where task boards, linked
  runs, artifacts, and messages exceed the viewport.
- Composer and primary actions can become detached from the current context.
- Operational task threads can look empty when the useful content is activity.
- Linked runs are visible, but not progressively inspectable in place.

Target behavior:

- Conversation rows can expand inline for preview, linked runs, recent tasks,
  recent artifacts, and primary actions.
- `Open full conversation` remains available for message-heavy work.
- Full conversation detail is a viewport-bounded workspace.
- Header/context remains stable.
- Composer remains reachable.
- Linked runs and tasks expand in place using the same run/task expansion
  contract.
- Operational task threads default to the activity/task view when that is the
  useful content.
- Long task/activity lists are paginated or internally scrolled within the
  available work area.

### Tasks

Observed problem:

- Task detail is closer to the target model, but still must be aligned with
  Runs and Conversations.
- Task artifacts and parent lineage must remain consistent everywhere a task
  appears.

Target behavior:

- Task rows expand inline under the clicked task.
- Expanded task content shows parent run, parent stage, assignment, expected
  outputs, actual artifacts, and conversation/activity.
- Task detail deep links select and expand the matching task.
- Artifact actions are identical to Runs and Conversations.

### Approvals

Observed problem:

- Approvals can read as isolated decisions rather than part of execution
  lineage.

Target behavior:

- Approval rows expand inline.
- Expanded approval content shows the run/stage/task context, artifact(s) under
  review, decision state, reviewer, and links/actions.
- Approval artifacts use the same artifact row contract.

### Dashboard

Observed problem:

- Dashboard risks becoming another duplicate resource index.

Target behavior:

- Dashboard shows high-level entry points and attention items.
- Dashboard cards expand inline only enough to orient the user.
- Full details route to the canonical surface, where the selected row expands.
- Recent artifacts use the same action contract.

### Protocols And Stages

Observed problem:

- Protocol stages are closest to the desired inline model, but density and
  screen movement can still disrupt work.
- Stage authoring must not reintroduce side panels or disconnected drawers.

Target behavior:

- Stage editor remains inline under the selected stage.
- Add-stage and remove-stage actions stay local to the stage.
- Stage sub-sections are progressive and do not push the active work below the
  screen unnecessarily.
- Artifact expectations are clear before execution and become actionable after
  a run produces bytes.
- Standard authoring hides internal runtime selector and advanced plumbing.

### Agents And Capabilities

Observed problem:

- Agents and capabilities still expose too many internal concepts as default
  content.
- Capabilities can become an intimidating wall of names.
- There is still risk of duplicated skill/routing/advertised-skill concepts.

Target behavior:

- Agent list uses human status: Ready, Busy, Unavailable, Needs setup.
- Agent detail has a stable header with Start conversation and Run protocol.
- Capabilities are grouped, searchable, and summarized.
- Generated timestamp names do not appear in default pickers.
- Selector preview, raw routing, worker diagnostics, token rotation, trust
  mutation, and capacity mutation live in Operations or technical details.

## Target Information Architecture

### Work

Surfaces:

- Dashboard
- Conversations
- Runs
- Tasks
- Approvals

Purpose:

- what is happening
- what needs attention
- where to resume
- where to inspect outputs

### Build

Surfaces:

- Protocols
- Templates
- Capabilities when authoring is user-facing

Purpose:

- create, edit, publish, reuse, and launch workflows

### Team

Surfaces:

- Agents
- Agent detail
- Agent-related work

Purpose:

- understand who can do work
- start work with an agent
- inspect an agent's recent work

### Operations

Surfaces:

- Routing
- Selector diagnostics
- Worker/runtime diagnostics
- Provider guidance
- Capacity, trust, tokens, usage

Purpose:

- inspect and operate the system
- not default authoring or execution flow

## Implementation Guidance

Do not add parallel UI layers. Extend existing shared primitives and page
renderers in place.

Before adding a new function, component, CSS class, or API projection:

1. Search for the existing shared primitive.
2. Extend the shared primitive if the concept is the same.
3. Replace page-local behavior with the shared primitive when possible.
4. Add a new helper only if there is no coherent existing owner.
5. If a new helper is necessary, document its single responsibility and use it
   from every relevant surface immediately.

Known shared concepts that should have one owner:

- object row
- expandable detail panel
- work-surface viewport container
- action row
- metadata grid
- artifact row/actions
- lineage projection
- capability projection
- status badge/status language
- pagination/internal-scroll behavior

## Implementation Phases

### Phase 0: Inventory And Removal Map

Goals:

- identify every list/detail, side-panel, drawer, and full-document-scroll
  pattern
- map each to the target inline expansion grammar
- find page-local duplicate row/artifact/action components

Steps:

1. Inventory Runs, Conversations, Tasks, Approvals, Dashboard, Protocols,
   Agents, Capabilities, and Operations.
2. Mark each current pattern:
   - keep and extend
   - replace with shared expandable row
   - move to Operations
   - delete as duplicate/dead code
3. Identify old split-pane assumptions in CSS and JS.
4. Identify tests that assert old side-panel behavior.
5. Update this plan with any discovered blockers before implementation.

Acceptance:

- every affected surface has one target interaction model
- no duplicate replacement components are proposed
- old tests that encode broken UI are listed for rewrite or deletion

### Phase 1: Shared Interaction Grammar

Goals:

- create or extend one reusable object-row and expansion contract
- create one viewport-bounded work-surface contract

Steps:

1. Extend the existing shared list/row primitive to support inline expansion.
2. Extend the existing panel/section primitive for progressive expansion
   content.
3. Add a shared work-surface layout that bounds list and expansion content to
   the viewport.
4. Add a shared internal-scroll/pagination rule for long sections.
5. Ensure action rows wrap inside their container, not based only on global
   viewport breakpoints.
6. Ensure passive rows do not advertise clickability.

Acceptance:

- one shared row expansion contract exists
- one shared viewport work-surface contract exists
- shared artifact rows fit inside the expansion panel
- desktop and narrow use the same mental model

### Phase 2: Runs Evidence-Model Refactor

Goals:

- keep inline run expansion
- replace the current competing run sub-models with one evidence hierarchy
- make Runs match the progressive stage/task model without hiding critical
  state

Steps:

1. Keep the existing full-width inline run list and remove any remaining dead
   side-detail assumptions.
2. Replace the run detail sub-tabs with at most four sections: `Overview`,
   `Stages`, `Artifacts`, and `Audit`.
3. Make `Stages` the primary inspection model:
   - sort stages by authored workflow order
   - show current/completed/blocked state per stage
   - show the assigned participant/agent as supporting context
   - show stage tasks and stage artifacts inline
   - show stage decisions or approvals as contextual evidence
4. Make `Artifacts` a rollup of the same stage artifact rows:
   - group by producing stage
   - use the same Preview/Open/Download/Copy path action row
   - show declared/missing outputs without broken actions
5. Move raw `Participants` and `Decisions` into `Audit`:
   - retain all operational data
   - present it as support/debug evidence, not primary user workflow
6. Elevate critical status:
   - stuck lease, blocked, failed, timeout, or stale-running state appears in
     the run row and Overview
   - Issues remains available in Audit but is not the only discovery path
7. Preserve deep links by selecting the target run and activating the relevant
   section without creating a second route-specific renderer.
8. Remove duplicate Outputs/Execution artifact row rendering and tests that
   assert separate visual models.

Acceptance:

- Runs has no default disconnected side-detail panel.
- Clicking a run expands detail inline under that run.
- The expanded run has no more than two visible navigation layers at once.
- Stage order is Planning to Acceptance for the Software Engineering protocol.
- `Overview` surfaces stuck/blocked/stale status without opening Audit.
- `Stages` and `Artifacts` use the same artifact component and action layout.
- Artifacts can be previewed/opened/downloaded/copied from both stage context
  and rollup context.
- Participants and decisions remain inspectable but do not dominate the default
  run understanding path.
- Run detail does not create horizontal overflow on desktop.
- Run detail does not push the whole page beyond the viewport for normal use.

### Phase 3: Conversations Viewport Workspace

Goals:

- make Conversations consistent without losing the conversation workspace
  value

Steps:

1. Add inline expansion to the conversation list for quick preview and linked
   work.
2. Keep `Open full conversation` as a secondary action.
3. Refactor full conversation detail into a viewport-bounded workspace.
4. Keep header/context and composer reachable.
5. Make linked runs expand in place using the Run expansion contract.
6. Make linked tasks expand in place using the Task expansion contract.
7. Default operational task threads to activity/tasks when messages are empty.
8. Add pagination or internal scrolling for long activity/task lists.

Acceptance:

- Conversation list supports inline inspection.
- Full conversation detail does not become an uncontrolled document scroll.
- Composer remains reachable.
- Linked runs/tasks are inspectable without context-jumping.
- Empty-looking operational task threads are eliminated.

### Phase 4: Tasks, Approvals, Dashboard Alignment

Goals:

- align adjacent Work surfaces with the same grammar

Steps:

1. Ensure task list/detail uses the same row expansion and viewport contract.
2. Ensure approval list/detail uses the same row expansion and lineage sections.
3. Ensure Dashboard cards link to canonical surfaces and only expand enough to
   orient the user.
4. Remove duplicate artifact/action rendering from these pages.
5. Rewrite tests that assumed side panels or disconnected details.

Acceptance:

- tasks, approvals, and dashboard work cards follow the same interaction model
- artifacts and lineage read the same across all Work surfaces
- no duplicate page-local artifact row remains

### Phase 5: Protocol, Agent, And Capability Cleanup

Goals:

- keep the authoring and team surfaces aligned with the same product rules

Steps:

1. Preserve inline protocol stage editing.
2. Ensure stage sub-sections are progressive and viewport-aware.
3. Keep internal runtime selector and advanced plumbing out of the standard
   authoring path.
4. Refactor agent detail around summary, actions, capabilities, related work,
   technical details, and operations.
5. Keep `Start conversation` and `Run protocol` reachable in agent context.
6. Consolidate skills/routing/advertised skills into user-facing capabilities.
7. Hide generated timestamp skill spam from default pickers.

Acceptance:

- standard authors do not see operator plumbing
- agents are usable without understanding internals
- capabilities are scannable and reused across conversation/protocol/agent UI

### Phase 6: Visual Density And Desktop Polish

Goals:

- make the product feel calm and readable without hiding useful actions

Steps:

1. Reduce borders where section hierarchy already communicates grouping.
2. Use quieter typography for inactive rows.
3. Increase internal padding where rows feel cramped.
4. Reduce spacing between inactive repeated rows where the current rhythm feels
   wasteful.
5. Keep active expanded rows visually clear but not heavy.
6. Audit action placement so users do not have to scan across the entire
   screen for primary actions.
7. Validate in real desktop Safari, not only a narrow automated viewport.

Acceptance:

- inactive rows are easy to scan but not visually loud
- active rows are clear without making the screen dense
- desktop feels intentionally designed, not stretched mobile
- narrow/mobile remains usable

### Phase 7: Tests And Product Scenarios

Goals:

- make the UI behavior enforceable
- stop relying on direct database setup as a substitute for human workflow

Required UI scenarios:

1. Create a protocol from blank through UI.
2. Create a protocol from template through UI.
3. Add, remove, and reorder/inspect stages through UI.
4. Select capability and optional agent through UI.
5. Launch a protocol from conversation through UI.
6. Execute a realistic software-engineering protocol and verify outputs.
7. Open the run from conversation and inspect inline run expansion.
8. Open the task from run and inspect inline task expansion.
9. Preview/open/download/copy artifacts from run, task, conversation, and
   dashboard references.
10. Inspect a stale/running/problem run and verify the status language is
    understandable.
11. Use an agent from the agent page without seeing operator internals.
12. Open Operations and verify routing/selector diagnostics remain available
    for operator paths.

Negative invariants:

- no custom runtime selector in standard protocol authoring
- no `Advanced` plumbing section in standard authoring
- no selector preview on default agent detail
- no raw token/trust/capacity mutation in normal user flow
- no empty workers panel in default agent detail
- no generated timestamp skill spam in default pickers
- no disconnected Runs side-detail panel in the default Runs path
- no page-level horizontal overflow on desktop or narrow widths

Testing rules:

- UI scenarios must create and mutate state through product UI or product APIs,
  not direct database writes.
- Database inspection is allowed only to diagnose or verify, never as the
  primary way to create UI state.
- Contract tests should cover shared primitives so fixes stay consolidated.
- Old tests that assert broken split-pane or duplicate behavior must be removed
  or rewritten.

### Phase 8: Visual Audit And Deployment

Goals:

- verify breadth after scenario depth is green
- deploy from the canonical flow only

Visual audit must include:

- real desktop Safari Runs list and expanded run
- real desktop Safari Runs Overview, Stages, Artifacts, and Audit sections
- real desktop Safari comparison that the same artifact renders consistently
  in stage context and artifact rollup context
- real desktop Safari Conversations list and full conversation
- narrow/mobile Runs and Conversations
- Tasks inline expansion
- Approvals inline expansion
- Protocol stage editor
- Agent list and agent detail
- Capabilities picker/search
- Dashboard recent work and artifacts
- Operations routing/selector diagnostics

The screenshot audit is breadth. Passing scenario specs are the release bar.

Deployment rule:

1. Commit in `/Users/tinker/output/bots/telegram-agent-bot`.
2. Push from that checkout.
3. Pull in `/Users/tinker/octopus`.
4. Redeploy from `/Users/tinker/octopus`.

Do not use source-to-target sync as the deployment mechanism.

## Definition Of Done

This work is done only when:

- Runs uses inline expansion by default and no longer uses a disconnected
  side-detail panel.
- Runs uses one evidence hierarchy: Run -> Stages -> stage evidence ->
  artifacts/tasks/decisions/participants/issues.
- Runs does not render the same artifact or stage evidence through unrelated
  visual models across subtabs.
- Runs exposes no more than two visible navigation layers at once.
- Runs shows critical stuck/blocked/stale status in the row and overview, not
  only inside an Issues or Audit tab.
- Runs stages are ordered by authored workflow order.
- Conversations list supports inline inspection and full conversation detail is
  viewport-bounded.
- Runs and Conversations do not overflow horizontally on real desktop Safari.
- Runs and Conversations do not rely on uncontrolled full-document vertical
  scrolling for normal use.
- Tasks, Approvals, Dashboard, Protocol stages, Agents, and Capabilities follow
  the same object interaction grammar where applicable.
- Artifacts use one preview/open/download/copy contract everywhere concrete
  bytes exist.
- Declared or missing artifacts never show broken file actions.
- Users can trace protocol, run, stage, task, conversation, approval, and
  artifact as one lineage.
- Standard authoring paths hide operator internals.
- Operator tools remain available in Operations.
- UI scenario tests exercise real product flows instead of direct database
  state creation.
- Old duplicate/dead UI paths and tests are deleted as the new shared contract
  replaces them.
- Visual audit confirms desktop and narrow/mobile are both usable.
- Deployment follows push here, pull there.

## Risks And Mitigations

### Risk: Inline Runs Become A Dashboard Inside A Row

Mitigation:

- keep `Overview`, `Stages`, `Artifacts`, and `Audit` as the only default
  sections
- make `Stages` the primary path and demote raw records to `Audit`
- avoid participant filters, stage tabs, and detail tabs being visible together
- require the artifact rollup to reuse the same stage artifact renderer

### Risk: Inline Expansion Becomes Too Tall

Mitigation:

- allow one expanded row by default
- make sections progressive
- use internal scrolling/pagination inside long sections
- keep full detail pages as secondary escape hatches

### Risk: Removing Split Panes Hurts High-Volume Triage

Mitigation:

- preserve fast filters/search
- keep keyboard-friendly row selection
- keep compact summaries
- use inline expansion for detail without losing list context

### Risk: Conversations Need A Different Model

Mitigation:

- use inline expansion for conversation list and linked objects
- keep full conversation as a bounded workspace
- do not force message-heavy work into a tiny row expansion

### Risk: Shared Primitives Become Over-General

Mitigation:

- shared primitives own layout and interaction contracts
- page renderers still own product-specific content
- avoid new parallel run/task/conversation components

### Risk: Visual Cleanup Only Shrinks The UI

Mitigation:

- reduce simultaneous concepts first
- then tune spacing, borders, and typography
- validate visually after each major surface

### Risk: Tests Miss Human Workflow Again

Mitigation:

- require UI-created state for scenario tests
- include artifact outcome assertions
- include real desktop Safari visual checks
- record discovered issues in this plan before continuing broad audit

## Immediate Next Steps

1. Refactor Runs expanded detail to the `Overview`, `Stages`, `Artifacts`,
   `Audit` evidence model.
2. Sort run stages by authored workflow order and verify Software Engineering
   reads Planning through Acceptance.
3. Consolidate Outputs and Execution artifact rendering into one shared row
   contract grouped by producing stage.
4. Move raw Participants and Decisions into Audit while surfacing their
   stage-relevant summaries inside Stages.
5. Elevate stuck/blocked/stale state into the run row and Overview.
6. Convert Conversations linked runs to the same bounded run preview model.
7. Continue aligning Tasks, Approvals, Dashboard, Protocol stages, Agents, and
   Capabilities with the shared work-surface and artifact contracts.
8. Run UI scenarios and real Safari visual audit after each major surface.

## Open Findings Log

New findings discovered during implementation or audit must be added here with:

- surface
- reproduction path
- observed behavior
- expected behavior
- severity
- fix owner or phase
- verification method

Current open findings:

- Runs / real Safari: the expanded run detail is technically inline but still
  uses competing sub-models. `Outputs` renders artifacts as a flat list,
  `Execution` renders stage evidence with different navigation and row
  treatment, `Participants` and `Decisions` expose raw records as peer tabs,
  and `Issues` hides critical state. Expected behavior: one evidence hierarchy
  with `Overview`, `Stages`, `Artifacts`, and `Audit`, where global views are
  rollups of stage evidence rather than separate visual systems. Severity:
  high. Fix owner: Runs evidence-model refactor. Verification method: real
  Safari expanded run review plus automated assertions that stage order,
  artifact actions, issue elevation, and section count match the Runs Product
  Model.
- Runs / real Safari: Execution can show Software Engineering stages in reverse
  human order, with Acceptance before Planning. Expected behavior: stages
  render in authored workflow order from Planning through Acceptance unless the
  user explicitly chooses an audit chronology. Severity: high. Fix owner: Runs
  evidence-model refactor. Verification method: open a Software Engineering
  run and assert visible stage order starts with Planning and ends with
  Acceptance.
- Runs / real Safari: more than two navigation layers can be visible at once
  in one expanded run: triage tabs, status chips, run-row expansion, run detail
  tabs, participant filters, and execution stage tabs. Expected behavior: the
  default run detail exposes at most one run-section control plus one local
  progressive control inside the active section. Severity: high. Fix owner:
  Runs evidence-model refactor. Verification method: visual audit and DOM
  assertions for visible tab groups/navigation controls inside expanded run.
- Runs / real Safari: a run can show the plain row/status value `running` even
  when its write lease has expired and the detail Issues section reports
  `stuck lease · lease_expired`. Expected behavior: stuck/problem state is
  visible at row and status-summary level without requiring users to discover
  the Issues tab. Severity: medium-high. Verification method: load
  `/ui/runs?status=running`, expand a stuck run, and confirm the row/status
  calls out the stuck lease condition before opening Issues.
- Conversations / real Safari: linked runs inside conversation previews and
  full conversation headers are still navigation links/chips only. They can
  route users to Runs, but they cannot be inspected progressively from the
  conversation context. Expected behavior: linked runs use the shared run
  expansion contract or an equivalent bounded preview so users can inspect
  state/artifacts without mentally jumping between disconnected pages.
  Severity: medium. Fix owner: linked-object lineage pass. Verification method:
  open `/ui/conversations`, expand a conversation with linked runs, and inspect
  the run without leaving the conversation work surface.
- Protocols / real Safari: one route transition from Templates to Protocols
  briefly rendered the previous Templates content under the Protocols URL until
  reload. This was not reproduced on a second attempt. Expected behavior:
  route content and URL always reconcile without manual refresh. Severity: low
  unless reproduced. Verification method: repeat top-nav transitions across
  Templates, Protocols, Runs, Conversations, Tasks, Agents, and Capabilities in
  real Safari with cache disabled/normal refresh.
- Audit coverage: this pass exercised broad real Safari flows, but it has not
  yet produced a literal 500+ screenshot corpus. Expected behavior: do not
  claim the 500+ screenshot breadth gate until the harness records and indexes
  that many distinct Safari screenshots. Severity: process. Verification
  method: screenshot manifest with count, route, viewport, action, and result.
- Deployment / real environment: M3 still fails to stay up after redeploy while
  Registry, M1, and M2 are healthy. Expected behavior: either M3 is configured
  and usable, or scenarios and UI copy clearly treat it as unavailable so users
  do not route work to a dead agent. Severity: medium. Verification method:
  redeploy from `/Users/tinker/octopus`, check container health, then validate
  `/ui/agents` reports the same usable agent set.

Resolved or verified in the latest implementation passes:

- Runs: split-pane detail was replaced by inline expansion and
  collapse-on-active-row behavior. The internal run evidence model remains open
  and is tracked above.
- Runs / real Safari: changing the status filter clears stale incompatible
  selections and removes stale `run_id` values.
- Runs / real Safari: completed participant rows prefer resolved outcomes over
  raw running state.
- Runs / real Safari: artifact Outputs expose the shared Preview/Open/Download/
  Copy path action row when concrete bytes exist.
- Conversations / real Safari: the list uses inline expansion, one expanded
  conversation at a time, and click-to-collapse for the active row.
- Conversations / real Safari: the full conversation page uses top-level tabs
  rather than rendering all subsections simultaneously.
- Tasks / real Safari: tasks now use the same single inline expansion contract
  as Runs, Conversations, and protocol stages; clicking a different task
  collapses the previous detail and clicking the active task collapses it.
- Tasks / real Safari: the implementation task for run
  `186e8080c07342e2943dd0fbf821c740` exposes produced output artifacts inline
  with Preview/Open/Download/Copy path actions after redeploy and reload.
- Protocol stages / real Safari: stage rows expand inline, Done collapses the
  editor, Assignment hides Advanced/custom runtime internals, Files & outputs
  stays on the selected stage, and the workflow map remains interactive on
  demand.
