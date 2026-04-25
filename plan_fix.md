# Registry Product Simplification And Human-Usability Plan

## Status

This is the active plan. It replaces the previous incremental UI cleanup plan.

The next pass is not another visual polish pass. The product has an information
architecture problem: too many implementation nouns are first-class navigation
items, related objects are split across multiple screens, and authoring blocks
users before they can express intent. The fixes below consolidate the product
around human workflows first, then run the full automated and real Safari audit.

Do not resume the 500+ screenshot audit until the known product issues in this
plan are fixed. A broad audit before these fixes will only re-confirm known
failure modes.

### Implementation Checkpoint

Current execution pass:

- `P2.19`: router now swaps the new route shell before waiting for async route
  readiness, so old content cannot remain visible under a new URL.
- `P1.4` / `P1.5`: `Approvals` and `Tasks` are removed from default main nav;
  routes remain for deep links/operator access.
- `P4.15` / `P4.23`: stage creation now allows a name-only unassigned draft
  stage; owner role and assignment are progressive fields.
- `P4.15`: add-stage clicks with an unfinished draft now require continue,
  move, or discard instead of silently resetting the draft.
- `P4.26`: stage Assignment now supports `New capability needed` using the
  existing capability selector pipeline instead of a new runtime selector.
- `P4.26`: existing template capabilities that are not currently advertised by
  a live agent remain `Existing capability`; `New capability needed` is explicit
  author intent, not an inferred catalog-miss state.
- `P4.25`: Capabilities now defaults to a human catalog from existing routing
  capability data; bot-scoped management remains available through the bot
  selector.
- Focused syntax checks are clean. Browser scenario verification must run
  after octopus pull/redeploy because the current local registry process serves
  previously deployed assets.
- Deployment note: octopus redeploy restarted registry, M1, and M2, but M3 is
  blocked by missing Claude provider auth. `/Users/tinker/octopus/.deploy/provider-auth/claude/.claude.json`
  is zero bytes and the M3 container exits with `Claude auth not found`.

## Core Diagnosis

The Registry currently exposes database/runtime objects as peer products:

- conversations
- runs
- tasks
- approvals
- protocols
- templates
- capabilities
- agents
- routing
- usage
- guidance

Some of those are real concepts, but they are not all primary user
destinations. A normal user is trying to:

- start or resume work
- author a workflow
- launch a workflow
- understand execution status
- inspect outputs
- recover from blocked work
- manage agents/capabilities at the right abstraction level

The UI should organize around those jobs. Runs, tasks, approvals, conversations,
stages, artifacts, and agents must be rendered as one lineage, not as unrelated
lists that the user has to mentally join.

## Product North Star

A human user should be able to:

1. Start work from a conversation, protocol, dashboard item, or agent.
2. Create a protocol from zero without needing every runtime detail up front.
3. Add stages without losing entered data.
4. Leave assignment blank until validation/publish/execute time.
5. Assign by agent, by existing capability, by a newly created capability, or
   leave unassigned intentionally.
6. Follow execution from protocol to run to stage to task to conversation to
   artifact without switching mental models.
7. Preview, open, download, or copy produced artifacts wherever they appear.
8. See stale, blocked, failed, or waiting states where the object appears.
9. Avoid operator-only internals unless intentionally using Operations.

## Hard Product Rules

- The default UI must show human workflows, not implementation tables.
- Top-level navigation must be small enough to be learnable.
- A thing should have one canonical user-facing home.
- Deep links may exist for diagnostics, but they should not force extra top
  level navigation.
- Creating a draft object must not require execution-ready configuration.
- Assignment is progressive. It must not block stage creation.
- Draft data must never be lost by switching tabs, clicking another panel, or
  opening a different stage insertion point.
- Concrete artifacts use one shared Preview/Open/Download/Copy contract
  everywhere.
- Declared-but-missing artifacts must never render broken file actions.
- Operator controls live in Operations or explicit technical details, not
  default authoring or work review.

## Issue Tracking And Evidence Model

This file is the single active source of truth for product intent, execution
tracking, and verification. The former `ui_issues.md` audit has been absorbed
into this plan as stable issue IDs, workstreams, route/component references,
and verification requirements.

Every new issue must be added here with a stable ID before implementation or
broad audit continues. Do not create a second active UI plan.

### Evidence Tags

- `S`: static review from source, route, or component structure.
- `H`: human usage or real-browser observation.
- `V2`: follow-up verification required through a dedicated pass, tooling, or
  cross-browser exercise.

### ID Namespaces

- `P1`: information architecture, product model, navigation, and terminology.
- `P2`: platform shell, router, resilience, shared primitives, and lifecycle.
- `P3`: dashboard, work/executions, runs, tasks, approvals, usage, and artifacts.
- `P4`: protocol authoring, templates, catalog, capabilities, and build flows.
- `P5`: conversations, agents, collaboration, and recent work.
- `P6`: presentation, responsive behavior, accessibility, login, and i18n.
- `P7`: operations, routing diagnostics, guidance, admin controls, and runtime
  framing.

### Tracking Rule

Product findings live in the narrative sections below. Engineering execution
lives in `Engineering Backlog Index` and `Execution Workstreams`. Every Open
Finding should map to at least one `P` ID and one implementation phase before
work starts.

## Evidence Summary

The findings below combine prior implementation review with the real Safari
inventory. They are symptoms of the same product model failure, not isolated
widget bugs.

## Real Safari Inventory

This inventory was performed in real desktop Safari against the deployed local
registry UI. It is not a substitute for the later 500+ screenshot audit; it is
the product-surface evidence that defines what must be fixed before that audit
is meaningful.

### Cross-Surface Failures

Observed:

- A normal navigation click from `/ui/approvals` to `/ui/protocols` changed the
  URL to `/ui/protocols?workflow_map=auto` but left the Approvals page rendered
  until Safari was manually reloaded. This is a release-blocking real-browser
  navigation/cache failure.
- Rehearsal, generated test protocols, generated task threads, and timestamped
  draft data leak into default user surfaces. They dominate Conversations,
  Dashboard, Tasks, Runs, and Protocols.
- The same underlying work appears as dashboard cards, conversation rows, run
  rows, task rows, agent recent work, and protocol issues. The UI asks users to
  assemble lineage manually.
- Empty or rare surfaces still receive primary navigation weight, especially
  Approvals and Tasks.
- Operator concepts are better hidden than before in some places, but still
  appear as normal product concepts in Routing, Guidance, Capabilities, and
  Agent details.
- The visual system is cleaner than earlier passes, but density comes from
  model duplication, not only spacing. More whitespace will not fix duplicate
  nouns and split lineage.

### Dashboard

Observed:

- Top cards mix attention metrics, inventory metrics, usage counters, and
  unavailable cost data.
- The Dashboard duplicates Approvals, Tasks, Conversations, Agents, and
  Protocol issues rather than presenting one prioritized resume/attention
  queue.
- `Approvals` consumes prime space even when it says only `Nothing waiting on
  review`.
- Active tasks and protocol issues are split, so stale leases require mental
  joining across panels.
- Rehearsal/test activity is rendered as default user work.

Expected:

- Dashboard should show prioritized attention and resume points only.
- Empty categories should collapse.
- Stale/blocking work should be one consolidated attention model.
- Test/rehearsal work should be hidden unless operator/audit mode is active.

### Conversations

Observed:

- The default list is dominated by rehearsal-generated task threads such as
  Plan, Review Document, Draft Document, Implementation, and Architecture.
- `Open` is not useful for operational task threads because it does not tell the
  user whether messages, work, artifacts, or blocked actions exist.
- Rehearsal appears as a normal quick-start agent.
- Approvals appears as a shortcut even though the page is empty.
- Conversations and task threads have filters, but the default state still shows
  all, which makes the page feel like an operations log.

Expected:

- Default Conversations should prioritize human conversations and active
  conversation-launched work.
- Operational task threads should be grouped under their parent run or surfaced
  only when the user chooses a work/activity view.
- Conversation rows should expose linked run/artifact state when that is the
  useful content.

### Runs / Work

Observed:

- Inline expansion is the right direction, but the surface still mixes run
  triage, run evidence tabs, stage/task internals, operator interventions, and
  artifact actions inside one dense row.
- Completed runs with artifacts do expose Preview/Open/Download/Copy actions,
  but the user must pick the run, pick `Artifacts`, and then understand that
  artifact rows expand into actions.
- Some runs marked `running` are actually stale lease/problem states.
- The run detail still exposes raw IDs, workspace, review loop, task IDs, and
  dispatch decisions too early.
- `Overview`, `Stages`, `Artifacts`, and `Audit` are the right section names,
  but they need one narrative model and consistent card grammar.

Expected:

- Row status and Overview should elevate current state, issue, next action, and
  produced outputs.
- Artifacts should be available from Overview when a run has meaningful output,
  not only after navigating to the Artifacts subtab.
- Raw internals belong in Audit.

### Tasks

Observed:

- Tasks duplicate run/stage execution rows as a peer Work destination.
- Expanded task detail shows useful lineage links, but it mostly repeats data
  the run stage already owns.
- Task rows are heavily polluted by rehearsal-generated stage tasks.
- The task page is useful as a deep link, but not as a normal navigation item.

Expected:

- Task detail should be embedded under the canonical Work/Run stage.
- `/ui/tasks` can remain for operator/deep-link access, but default users should
  not choose Tasks versus Runs.

### Approvals

Observed:

- The page currently says only `No approvals waiting`.
- It has no surrounding explanation, no lineage, and no example of why a user
  would visit it directly.

Expected:

- Approvals should be contextual to a run, stage, task, or conversation.
- The empty approval queue should not be a top-level default destination.

### Protocols

Observed:

- The Protocols list is flooded with generated drafts and near-duplicates:
  many `Software Engineering Draft`, `Document Approval Draft`, timestamped
  Data Analysis, Meta Protocol Assistant, and generated draft names.
- The list reports large counts (`42 draft`, `40 published`, `88 all`) without
  helping the user find the canonical protocols.
- `New protocol` creates a draft cleanly, but the resulting blank editor still
  makes users pick/create an owner role before they can create a named stage.
- Entered stage name survived switching between Basics and Assignment, which is
  good and must be preserved.
- `Create step` with only a name fails with `Name the owner role before
  creating this step`, proving name-only unassigned authoring is still not
  supported.

Expected:

- Protocols should default to canonical team workflows, with generated/audit
  variants grouped or hidden.
- Stage creation should require only a display name.
- Role/agent/capability assignment should be progressive and validated later.

### Templates

Observed:

- Templates is understandable and sparse: Start blank, Software Engineering,
  and Document Approval.
- It still feels separate from Protocols even though it is a protocol starter
  mode.

Expected:

- Templates can stay as a Build nav item only if it remains a focused starter
  surface and Protocols clearly links to it.
- The same starter cards should be reusable from Protocols without creating a
  second product model.

### Capabilities

Observed:

- Capabilities opens to a required `Choose a bot` selector and otherwise says
  `Choose a bot to manage its capabilities`.
- The page is scoped like bot administration, not a human capability catalog.
- The bot selector menu showed only M1 and M2 in this pass, while other parts
  of the product show M3 and Rehearsal.
- Selecting M1 from the native Safari menu did not visibly update the page in
  this pass, which needs reproduction and testing.

Expected:

- Default Capabilities should be a catalog and authoring surface for reusable
  human-facing capabilities.
- Bot-scoped capability management should be a secondary/operator mode.
- Agent availability should be consistent across surfaces.

### Agents

Observed:

- Agent list is improved and closer to human-readable: M1, M2, M3, Rehearsal,
  readiness, Start conversation, Details.
- Rehearsal still appears as a normal agent.
- Agent detail still duplicates capabilities in Overview and Capabilities
  sections.
- Agent detail has Start conversation and Run protocol in multiple places,
  which is useful for reachability but currently reads as redundant rather than
  intentionally sticky/local.
- Recent work mixes conversations and task threads without making the run
  lineage primary.
- Operations and diagnostics are collapsed, which is correct, but their content
  still needs to be treated as operator-only.

Expected:

- Rehearsal/test agents should not appear as normal user agents by default.
- Agent detail should summarize capabilities once, then offer search/manage as
  a secondary action.
- Recent work should group by conversation/run rather than raw task threads.

### Routing, Usage, And Guidance

Observed:

- Routing is a raw diagnostics page with skill names, advertisers, and disable
  toggles. It is appropriate for Operations, not normal authoring.
- Usage is a cost/token table and belongs in Operations.
- Guidance is provider/bot baseline editing with Write/Review/Advanced tabs.
  It is admin/operator configuration, not a normal user workflow.

Expected:

- Keep these under Operations.
- Do not let Routing/Guidance vocabulary leak into Protocol authoring,
  Conversations, or Agent default views.

### Inventory Priority Order

1. Fix real Safari navigation/cache stale-content behavior before trusting any
   visual audit result.
2. Remove or demote top-level Approvals and Tasks from default navigation.
3. Make blank protocol authoring name-first and assignment-optional.
4. Hide/group generated rehearsal/test data from default Dashboard,
   Conversations, Tasks, Runs, Protocols, and Agents.
5. Consolidate Runs/Tasks/Conversations around one work lineage model.
6. Make Capabilities a human catalog first and bot-scoped management second.
7. Keep Routing, Usage, Guidance, selector preview, workers, and raw runtime
   state inside Operations.

## Current Human Findings

These are not isolated bugs. They are symptoms of the same product model
failure.

### 1. Approvals Is A Poor Top-Level Destination

Observed:

- `Approvals` is in the main Work nav.
- The page is usually empty.
- When populated, approvals are pending decisions tied to conversations, tasks,
  runs, retries, or recovery.
- The page does not explain why it exists or where an approval fits in the
  larger execution lineage.

Decision:

- Remove `Approvals` from primary navigation.
- Keep the approval API, backend model, event renderers, and action handling.
- Surface approvals contextually:
  - Dashboard attention item
  - Conversation timeline and context panel
  - Run Overview when a stage/run is waiting on approval
  - Task detail when a task is blocked by approval
  - Operations queue for operators if needed

Acceptance:

- No `Approvals` item appears in default main nav.
- Pending approval actions are still reachable from the context where they
  matter.
- `/ui/approvals` may remain as an operator/deep-link route, but it is not a
  primary product destination.

### 2. Tasks And Runs Are Overlapping User Destinations

Observed:

- Runs and Tasks both show execution work.
- Tasks often duplicate run/stage/artifact/conversation context.
- Users have to choose between `Runs` and `Tasks` without knowing whether they
  want the workflow, the stage work item, or the output.
- Task pages are useful as detail views, but not as a peer top-level product
  beside Runs.

Decision:

- Consolidate default Work navigation around a single execution surface.
- Rename or remodel `Runs` as `Work` or `Executions` if that better fits the
  product language.
- Make runs the primary rows because they represent the whole workflow.
- Render tasks inside run stages, conversation context, dashboard items, and
  agent recent work.
- Keep `/ui/tasks` as a deep-link/operator route only until we prove it can be
  fully absorbed.

Acceptance:

- Default nav does not force users to pick between Runs and Tasks.
- A run expands to show stages, stage tasks, artifacts, decisions, and issues.
- Task deep links still select and expand the relevant task.
- Any task row clearly shows its parent run/stage/conversation.

### 3. Protocol Stage Creation Is Too Rigid And Loses Work

Observed:

- Creating a stage currently requires assignment before the stage can exist.
- The UI pushes users toward available skills even when they just want to
  draft a step.
- There is no natural path to create/request a missing capability from stage
  authoring.
- Users can lose stage data after switching panels, changing assignment mode,
  or clicking another add-stage affordance.
- This blocks 0-to-1 protocol authoring and produces the feeling that the UI is
  fighting the user.

Decision:

- Stage creation requires only a stage name.
- Owner role, assignment, instructions, artifacts, and routing are progressive.
- Assignment states become:
  - `Unassigned for now`
  - `Specific agent`
  - `Existing capability`
  - `New capability needed`
- `Create step` never discards entered data.
- If a pending stage exists and the user clicks another add-stage action, show
  a local choice: continue current draft, move draft here, or discard.
- Validation/publish/execute surfaces incomplete assignment as a fixable issue,
  not as an authoring blocker.

Acceptance:

- A user can create a new protocol with multiple named unassigned stages.
- Switching between Basics, Assignment, Instructions, and Files never loses the
  pending stage draft.
- Clicking add below another stage does not silently reset the pending draft.
- A user can assign just an agent.
- A user can assign just a capability.
- A user can leave assignment blank.
- A user can mark that a new capability is needed.

### 4. Capabilities Are Not Yet A Human-Scaled Model

Observed:

- Skills/capabilities can appear as an intimidating long list.
- Generated/test-created names can pollute normal authoring.
- Capability, routing skill, advertised skill, and selector preview still leak
  as separate concepts.
- Protocol authoring depends on available skills too early.

Decision:

- Default UI says `Capabilities`.
- Operator/debug UI may say routing, selector, advertised skills, or workers.
- Default capability pickers must be searchable, grouped, and compact.
- Generated/test fixtures must not appear in default pickers unless explicitly
  searched or in operator mode.
- Missing capability flow should be possible from stage authoring:
  - name the needed capability
  - optionally draft instructions
  - assign later when available
  - optionally send to capability creation flow

Acceptance:

- Capability picker is not a wall of names.
- Generated timestamp names do not appear in default authoring lists.
- Stage creation is not blocked by missing capability availability.
- New capability need is represented in the protocol definition without
  creating fake runtime plumbing.

### 5. Runs Still Expose Too Many Models Inside One Expansion

Observed:

- Runs now expand inline, but the detail still mixes Overview, Stages,
  Artifacts, Audit, issue cards, metadata grids, action groups, and stage cards
  in a dense way.
- Some output rows look clickable but child actions are the real affordances.
- Stuck/running state can read as simply `running`.
- Operator actions can appear too global.

Decision:

- Runs remain the primary execution/work surface.
- Expanded run detail uses one hierarchy:
  - Run
  - Stage
  - Task
  - Conversation/activity
  - Artifact
  - Decision/approval/issue
- `Overview` contains current state, active issue, meaningful next action, and
  concise metadata.
- `Stages` is the main narrative, ordered by authored workflow order.
- `Artifacts` is a rollup of the same artifact rows used inside stages.
- `Audit` contains raw participants, transitions, issue records, and operator
  diagnostics.
- Run-level actions appear only where they are real for the current state.

Acceptance:

- A stale lease shows as needs attention, not only `running`.
- Artifacts render consistently in Overview/Stages/Artifacts/task contexts.
- Clicking an artifact row previews when previewable or clearly offers actions.
- No more than two local navigation layers are visible inside an expanded run.

### 6. Conversations Are Still Split Between Chat And Operational Work

Observed:

- Some conversations are nearly empty even when tasks/runs reference them.
- A conversation launched from a task/run can look useless if the useful content
  is operational activity.
- Protocols can be launched from conversations, but the resulting run/artifacts
  must remain visible from the conversation context.

Decision:

- Conversation detail defaults to the most useful view:
  - message conversation when messages exist
  - work/activity view when it is operational
- Linked runs/tasks expand using the same work detail model.
- Protocol launch from conversation should show started run and outputs without
  requiring a separate Runs hunt.

Acceptance:

- Opening a task-linked conversation never looks empty if work exists.
- A conversation-launched protocol can be followed to run status and artifacts.
- Users can start another conversation/launch from the relevant context without
  scrolling to a distant header.

### 7. Agents Are Still Too Dense And Operational

Observed:

- Agent pages expose capabilities, advertised skills, selector diagnostics,
  workers, capacity, health, connectivity, and admin controls at once.
- Start conversation can be hard to reach from lower sections.
- Empty worker panels create noise.
- Capacity like `0/1` is not meaningful to normal users.

Decision:

- Agent default detail should be:
  - who this is
  - Ready/Busy/Unavailable/Needs setup
  - primary actions: Start conversation, Run protocol
  - top capabilities
  - recent work
  - technical details collapsed
- Worker, selector, trust, token, capacity, and routing diagnostics move to
  Operations or an explicit technical tab.

Acceptance:

- A normal user can start work with an agent without reading operational
  diagnostics.
- Empty worker panels are hidden from default view.
- Capacity is translated to human work state.
- Capabilities are summarized and searchable, not dumped.

### 8. Dashboard Risks Becoming Another Duplicate Index

Observed:

- Dashboard can duplicate approvals, tasks, runs, conversations, agents, and
  protocol issues.
- It is useful as an attention surface, not as another full resource browser.

Decision:

- Dashboard shows attention and resume points only.
- Dashboard cards deep-link into the canonical Work/Conversation/Agent surface
  with the relevant row expanded.
- Dashboard should not implement separate artifact, approval, or task detail
  models.

Acceptance:

- Dashboard has no page-local detail model for objects that already have a
  canonical surface.
- Every Dashboard item answers `why should I care now?`.

### 9. Operations Needs To Absorb Plumbing

Observed:

- Routing, usage, guidance, selector preview, workers, trust, capacity, tokens,
  runtime diagnostics, and generated/test data are operator concerns.
- Some of these leak into default authoring and agent views.

Decision:

- Operations becomes the place for:
  - routing diagnostics
  - selector preview
  - workers/runtime health
  - provider guidance
  - usage
  - admin trust/capacity/token controls
  - generated/test data visibility

Acceptance:

- Default Work/Build/Team views do not expose operator plumbing.
- Operators can still access diagnostics without hidden hacks.

## Target Navigation

Default navigation should collapse to this shape:

### Work

- Dashboard
- Conversations
- Work or Executions

Notes:

- `Work/Executions` replaces the normal-user need for separate Runs and Tasks.
- Approvals are contextual, not a default nav item.
- Tasks may remain as a deep-link/operator route during migration.

### Build

- Protocols
- Templates
- Capabilities

Notes:

- Protocols should make blank authoring easy.
- Templates are starters, not a separate gallery mystery.
- Capabilities are human-facing skills.

### Team

- Agents

Notes:

- Agent default view is work-oriented, not operational.

### Operations

- Routing
- Usage
- Guidance
- Diagnostics/Admin as needed

Notes:

- Selector preview, workers, capacity, trust, tokens, and raw routing belong
  here.

## Implementation Principles

- Do not add duplicate renderers.
- Extend existing shared primitives first.
- Remove or demote surfaces instead of adding new explanatory layers.
- Keep routes/API endpoints when they are useful deep links, but do not expose
  them as primary nav unless they serve a normal human job.
- Prefer one shared lineage projection for run/task/conversation/artifact.
- Prefer one shared artifact action row everywhere.
- Prefer one shared expandable-row grammar everywhere.
- Use tests to prevent reintroducing top-level clutter and assignment blockers.

## Engineering Backlog Index

This index absorbs the executable defects and verification hooks from the former
`ui_issues.md`. The tables are intentionally terse; the product rationale and
acceptance criteria remain in the narrative, phases, and Open Findings Log.

### P1: Information Architecture And Product Model

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P1.1 | S/H | Sidebar exposes too many implementation nouns as peer destinations. | 1 | Default nav review in real Safari and DOM assertions. |
| P1.2 | S | `/ui/templates` and `/ui/gallery` mount the same gallery. | 1 | One canonical URL or explicit redirect/alias test. |
| P1.3 | S | Terminology drifts between Capabilities, skills, Templates, gallery, and Protocol examples. | 1, 5 | User-facing string inventory. |
| P1.4 | S/H | Approvals is a rare or empty queue but appears as a normal Work destination. | 1, 4 | Contextual approval scenario; default nav hides/demotes Approvals. |
| P1.5 | S/H | Tasks and Runs expose the same execution work as separate apps. | 1, 3 | Task deep links land in canonical Work/Run lineage. |
| P1.6 | H | Generated, rehearsal, and test-created data dominates default user surfaces. | 1, 3, 5, 7 | Default pages hide/group test and rehearsal records unless operator/audit filter is active. |

### P2: Platform Shell, Router, Resilience, And Primitives

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P2.1 | S | 404 page is bare and lacks a recovery path. | 8 | Route `/ui/does-not-exist`; confirm Home recovery link. |
| P2.2 | S | Logout intentionally bypasses SPA routing but is undocumented for contributors. | 8 | Contributor note or router test preserves full navigation. |
| P2.3 | S | Sidebar closes at `<=900px` during resize and can surprise users. | 8 | Resize pass with open sidebar. |
| P2.4 | S | `/` search focus and Escape drawer behavior are useful and must be preserved. | 8 | Keyboard smoke test. |
| P2.5 | S | Timestamp refresh can create layout shift. | 8 | Visual check with stable tabular widths or capped timestamp cells. |
| P2.6 | V2 | Session expiry/401 handling needs consistent redirect and return behavior. | 8 | Scripted expired-session test. |
| P2.7 | V2 | CSRF bootstrap failure needs a user-visible degraded state. | 8 | Forced CSRF failure test. |
| P2.8 | V2 | Offline/slow network can create duplicate toasts or endless loading. | 8 | Network throttling/offline test. |
| P2.9 | V2 | WebSocket reconnect and route subscription lifecycle need verification. | 8 | Route-change and reconnect integration test. |
| P2.10 | S | Toast stack can cover important UI. | 8 | Toast cap/dismiss behavior test. |
| P2.11 | S | `reportError` can produce very long toast text. | 8 | Long-error truncation test. |
| P2.12 | S | Delegated segmented-control clicks are a shared primitive and must be preserved. | 8 | Component test for segmented controls after rerender. |
| P2.13 | S/V2 | `makePressable` keyboard parity is not verified everywhere. | 8 | Keyboard audit. |
| P2.14 | S | Lifecycle slug chip says `Protocol settings` when slug is empty. | 2, 8 | Protocol header copy assertion. |
| P2.15 | S | Title change and blur can both commit, creating double-save risk. | 2, 8 | Single-commit autosave test. |
| P2.16 | S | First-run state hides toolbar and creates inconsistent chrome. | 2 | Blank protocol visual test. |
| P2.17 | S/H | First-run card stacks too many CTAs. | 2 | Blank protocol first-run review. |
| P2.18 | S/V2 | User-facing strings mix `Kit.dict` and hardcoded English. | 8 | String inventory and policy. |
| P2.19 | H | Real Safari can render stale content after SPA navigation. | 8 first | Real Safari nav invariant across all default nav items. |

### P3: Dashboard, Work, Runs, Tasks, Approvals, Usage, And Artifacts

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P3.1 | S/H | Dashboard is dense and duplicates multiple resource indexes. | 1, 3, 4, 7 | Dashboard attention-queue assertions. |
| P3.2 | S | Protocol stat subtitle packs too many metrics into one string. | 1 | Dashboard card readability review. |
| P3.3 | S | Task fallback titles can become repetitive and generic. | 3 | Task title fallback test. |
| P3.4 | S | Dashboard tiles do not always explain which user question they answer. | 1 | Dashboard content review. |
| P3.5 | S/H | Approvals empty state is a dead end when no approvals are waiting. | 4 | Empty approval queue no longer primary default surface. |
| P3.6 | S | `Needs review` can be redundant on approval cards. | 4 | Approval-card copy review when populated. |
| P3.7 | S | Runs header copy can be heavy on narrow layouts. | 6 | Narrow visual pass. |
| P3.8 | S/H | Run filters plus inline detail can produce tall, dense pages. | 6 | Expanded-run viewport test. |
| P3.9 | S | Operator action dialogs are safe but tiring at volume. | 6, 7 | Applicable-action and dialog-copy review. |
| P3.10 | S | Usage header has little purpose framing. | 7 | Operations/Usage copy review. |
| P3.11 | S | Usage token cells wrap poorly on narrow screens. | 8 | Responsive table test. |
| P3.12 | H | Artifact Preview/Open/Download/Copy is not yet encoded as a cross-surface invariant. | 3, 6, 7 | Shared artifact row tests in runs, stages, tasks, and conversations. |
| P3.13 | H | Stale leases can still read as ordinary `running` work. | 3, 6 | Stuck-lease row and Overview assertions. |
| P3.14 | H | Runs and Tasks are polluted by rehearsal-generated stage tasks. | 1, 3 | Default Work pages filter/group rehearsal work. |

### P4: Protocol Authoring, Templates, Catalog, And Capabilities

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P4.1 | S/H | First-run protocol card has too many CTAs. | 2 | Primary CTA plus More/progressive controls. |
| P4.2 | S | Protocol toolbar differs before and after first step. | 2 | Blank and nonblank protocol chrome comparison. |
| P4.3 | S/H | Add-step entry points are redundant and not clearly anchored. | 2 | Stage insertion flow review. |
| P4.4 | S | Insert label is computed but not clearly shown to the user. | 2 | Add-below/before label assertion. |
| P4.5 | S | Workflow files, protocol files, and files/outputs labels conflict. | 2 | String and route label review. |
| P4.6 | S/H | Workflow map can replace context instead of acting as on-demand spatial review. | 2 | Map opens interactively without losing stage context. |
| P4.7 | H | `Done` can be misread as save/submit instead of closing the stage editor. | 2 | Stage editor copy/behavior review. |
| P4.8 | H | One-tab-at-a-time stage editor slows cross-field editing. | 2 | Wide-screen authoring review. |
| P4.9 | S | `Files & outputs` and `Inputs and outputs` naming drifts. | 2 | Single label policy. |
| P4.10 | S | Routing appears as both tab list and inline route editor. | 2 | Routing authoring hierarchy review. |
| P4.11 | S | `Open route details` copy is misleading when the row is already the control. | 2 | Copy assertion. |
| P4.12 | S | Internal labels such as `Protocol management surface` leak into author UI/ARIA. | 2, 8 | ARIA and visible-copy audit. |
| P4.13 | S/H | Resize triggers full render and can cause focus/caret loss. | 2, 8 | Resize during insert/edit test. |
| P4.14 | S | Long dataset keys are opaque support details. | 8 | Keep internal only or document for support. |
| P4.15 | S/H | Insert-step cluster: DOM sync before validation can clobber draft, mandatory selector blocks unassigned flow, empty catalog lacks in-flow escape, `_startStageInsert` resets draft, rerenders amplify mismatch. | 2 | UI-only failed-create preservation, resize, empty catalog, and add-stage tests. |
| P4.16 | S | Standard/operator authoring split must omit internals from standard DOM and API. | 2, 8 | Negative tests for Advanced/custom runtime/internal fields. |
| P4.17 | V2 | Autosave debounce, dirty indicator, and multi-tab conflicts need stress testing. | 2, 8 | Multi-tab conflict and autosave test. |
| P4.18 | V2 | Deep links must restore workspace panel/map state after refresh. | 2, 8 | Query-param restoration matrix. |
| P4.19 | S | Templates page title and `Protocol examples` section name drift. | 1, 5 | Naming assertion. |
| P4.20 | S/H | Capability surface is dense and mixes catalog, agent, and management concepts. | 5 | Human catalog first, bot management secondary. |
| P4.21 | S/H | Routing diagnostics copy belongs in Operations and needs impact framing. | 7 | Operator route warning/context review. |
| P4.22 | S/H | Guidance has dense provider/agent/tab controls and belongs in Operations. | 7 | Guidance route framing review. |
| P4.23 | H | Blank stage still requires owner role before creation. | 2 | Create named unassigned stage without owner role. |
| P4.24 | H | Protocol list is flooded by near-duplicate generated drafts and variants. | 1, 5 | Canonical protocols shown first; generated variants grouped/hidden. |
| P4.25 | H | Capabilities opens as bot-admin-first and bot selector appeared inconsistent in Safari. | 5, 8 | Catalog default plus selector consistency test. |
| P4.26 | H | Missing capability has no natural authoring path from stage assignment. | 2, 5 | `New capability needed` UI-only scenario. |

### P5: Conversations, Agents, Collaboration, And Recent Work

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P5.1 | S/H | Conversation list filters and quick starts are busy, especially on mobile. | 7, 8 | Filter-collapse and mobile smoke test. |
| P5.2 | S | `/` search hint is invisible on touch. | 8 | Touch/narrow affordance review. |
| P5.3 | V2 | Conversation detail needs dedicated audit for composer, timeline, task board, settings, focus traps, scroll stacks, send/WS races, and markdown edge cases. | 7, 8 | Dedicated conversation detail audit. |
| P5.4 | V2 | Composer autocomplete keyboard and assistive-tech behavior is unverified. | 7, 8 | Keyboard/AT test. |
| P5.5 | V2 | Event renderers have inconsistent density across event kinds. | 7 | Shared event card review. |
| P5.6 | S | Agent list has useful Kit alignment and search behavior that should be preserved. | 5 | Agent list regression test. |
| P5.7 | S/H | Agent detail can scroll long and `Opening...` can feel stuck until navigation completes. | 5 | Loading timeout/error review. |
| P5.8 | S | Execution reset window feels magical without explanation. | 5 | Copy or operator documentation. |
| P5.9 | V2 | `/ui/agents/:id/conversations` reuses detail module but needs entry-specific verification. | 5, 8 | Route-specific scenario. |
| P5.10 | H | Conversations default list is dominated by rehearsal task threads and weak `Open` states. | 7 | Human conversations prioritized; operational threads grouped by run. |
| P5.11 | H | Agent detail duplicates capabilities and treats Rehearsal as normal default agent. | 5 | Rehearsal/test agent hidden or grouped; capabilities summarized once. |

### P6: Presentation, Responsive, Accessibility, Login, And i18n

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P6.1 | S | Nearby breakpoints can create layout jumps. | 8 | Breakpoint token review. |
| P6.2 | S | Runs mobile reorder is useful, but filters can still stack densely. | 8 | Mobile/narrow Runs pass. |
| P6.3 | S | Protocol full re-render can cause keyboard/AT focus loss. | 2, 8 | Keyboard focus preservation test. |
| P6.4 | S/V2 | Icon-only controls need complete ARIA-label verification. | 8 | Axe and manual keyboard pass. |
| P6.5 | V2 | Theme color contrast is not systematically measured. | 8 | Light/dark contrast audit. |
| P6.6 | V2 | `prefers-reduced-motion` behavior is not audited. | 8 | Reduced-motion CSS pass. |
| P6.7 | V2 | Print styles are likely absent and need a product decision. | 8 | Print decision, then test if supported. |
| P6.8 | V2 | Ultra-wide tables need max-width or horizontal-scroll policy. | 8 | Ultra-wide Usage/Runs pass. |
| P6.9 | S | Login hides sidebar via inline styles and needs cleanup verification. | 8 | Login enter/leave route test. |
| P6.10 | S | Password field uses `search-input` class. | 8 | Dedicated password-field class. |
| P6.11 | V2 | Mobile matrix is not yet complete beyond smoke/density checks. | 8 | Mobile route matrix. |
| P6.12 | V2 | Success metrics are not defined for IA changes. | 8 | Define measures such as time-to-first-stage and clicks-to-artifact. |

### P7: Operations, Routing, Guidance, Admin, And Runtime Framing

| ID | Evidence | Finding | Phase | Verification |
|----|----------|---------|-------|--------------|
| P7.1 | H/S | Routing exposes powerful skill-disable toggles with little product framing. | 7, 8 | Operator-only route plus warning/context copy. |
| P7.2 | H/S | Usage belongs in Operations and needs cost/token framing, not default work focus. | 7 | Operations navigation and copy review. |
| P7.3 | H/S | Guidance is provider/bot baseline editing and should remain Operations/admin. | 7 | Guidance route framing and role/capability gate. |
| P7.4 | V2 | Multi-tenant/role model is assumed but not exhaustively defined. | 1, 7, 8 | Product role/capability policy. |
| P7.5 | V2 | Security beyond CSRF/session, including markdown/XSS and approval action abuse, needs a dedicated pass. | 8 | Security review and targeted tests. |

## Execution Workstreams

Implementation phases describe product sequence. Workstreams describe how
engineering should group code and verification without creating duplicate paths.

| Order | Workstream | Goal | Primary IDs | Phases |
|-------|------------|------|-------------|--------|
| W0 | Real Safari navigation gate | Prove URL and rendered content stay synchronized before trusting further visual audit. | P2.19 | 8 first |
| W1 | Protocol insert and assignment integrity | Name-only stages, no draft clobber, optional assignment, missing-capability path. | P4.15, P4.23, P4.26, P4.13, P6.3 | 2 |
| W2 | Information architecture consolidation | Remove/deprioritize dead nav, merge Tasks/Runs story, contextualize Approvals, canonical URLs. | P1.1-P1.6, P3.5, P1.2 | 1, 3, 4 |
| W3 | Work lineage and artifact contract | One run/stage/task/conversation/artifact narrative with shared artifact actions. | P3.8, P3.12-P3.14, P5.10 | 3, 6, 7 |
| W4 | Protocol catalog, templates, and capabilities | Human-scaled protocol and capability authoring, generated variant grouping, catalog-first capabilities. | P4.19, P4.20, P4.24, P4.25 | 5 |
| W5 | Conversations and agents | Human conversation defaults, recent work lineage, agent work-first detail. | P5.1-P5.11 | 5, 7 |
| W6 | Platform resilience and lifecycle | Session, CSRF, offline, WS, toasts, lifecycle commit correctness. | P2.1-P2.18 | 8 |
| W7 | Presentation, accessibility, responsive, i18n | Breakpoints, focus, ARIA, contrast, motion, login, mobile, strings. | P6.1-P6.12, P2.18 | 8 |
| W8 | Operations and admin framing | Keep routing, usage, guidance, selectors, workers, capacity, and trust in framed operator surfaces. | P7.1-P7.5, P4.21, P4.22 | 7, 8 |

### Workstream Verification Matrix

| Stream | Minimum verification |
|--------|----------------------|
| W0 | Real Safari clicks every default nav item and asserts URL, active nav item, heading, and visible content match without reload. |
| W1 | Playwright and real Safari: blank protocol, empty skill catalog, failed create preserves fields, resize during insert, agent-only assignment, capability-only assignment, missing capability, unassigned stage. |
| W2 | Real Safari nav review, link/deep-link tests, contextual approval test, Tasks/Runs deep-link parity. |
| W3 | Data-analysis and software-engineering runs with real artifacts; artifact actions checked from Overview, Stages, Artifacts, task context, and conversation context. |
| W4 | Protocol list generated-variant filtering, template starter flow, Capabilities catalog default, bot-management selector consistency. |
| W5 | Conversations list/detail, task-linked conversation, conversation-launched protocol, agent start conversation, agent run protocol. |
| W6 | 401/session expiry, CSRF bootstrap failure, offline/slow network, WS reconnect, toast truncation, lifecycle single commit. |
| W7 | Axe, keyboard-only pass, light/dark contrast, reduced motion, mobile/narrow matrix, login route cleanup, string inventory. |
| W8 | Operator-only access/framing for Routing, Usage, Guidance, workers, selector preview, capacity, trust, and runtime diagnostics. |

## Implementation Phases

### Phase 1: Navigation And Information Architecture

Steps:

1. Remove `Approvals` from default main nav.
2. Decide final label for `Runs`: keep `Runs` temporarily or rename to
   `Work/Executions`.
3. Remove `Tasks` from default nav once task deep links are covered from Work.
4. Keep `/ui/tasks` and `/ui/approvals` routes for deep links/operator access.
5. Update Dashboard and Conversation links to route to canonical Work context
   where possible.
6. Update user guide/tests that expect Approvals/Tasks as normal nav items.

Acceptance:

- Default nav has fewer Work items.
- No critical approval or task action is lost.
- Deep links continue to work.

### Phase 2: Protocol Stage Creation

Steps:

1. Change create-stage validation to require only a display name.
2. Represent missing assignment as `unassigned` or absent selector, not an
   invalid authoring state.
3. Add an explicit `Unassigned for now` assignment mode in the standard editor.
4. Add `New capability needed` as a standard authoring option that stores a
   human capability need without creating fake routing plumbing.
5. Preserve pending stage draft across:
   - panel switches
   - assignment mode switches
   - role edits
   - instructions edits
   - artifact panel visits
   - add-stage clicks elsewhere
6. If another add-stage point is clicked while a draft exists, show a local
   continue/move/discard choice.
7. Move execution-readiness checks to Validate/Publish/Run.

Acceptance:

- Create three unassigned stages from blank protocol using UI only.
- Switch across every stage editor tab without data loss.
- Assign one stage to an agent only.
- Assign one stage to an existing capability only.
- Mark one stage as needing a new capability.
- Validate shows incomplete assignment issues in plain language.

### Phase 3: Work Surface Consolidation

Steps:

1. Make the Run/Work list the canonical execution entry point.
2. Ensure expanded run shows stage/task/conversation/artifact lineage.
3. Ensure task deep links select and expand the parent run/stage/task context
   where possible.
4. Keep `/ui/tasks` as an operator/deep-link fallback until parity is proven.
5. Remove duplicate task/run summary cards where the same information appears
   twice.

Acceptance:

- A user can inspect a task from a run without opening a separate peer page.
- A user can inspect produced artifacts from run stage context and task context.
- Task-only route no longer carries unique normal-user functionality.

### Phase 4: Contextual Approvals

Steps:

1. Keep approval action handling intact.
2. Add approval context to run Overview/stage evidence when relevant.
3. Add approval context to conversation activity when relevant.
4. Add approval context to task detail when relevant.
5. Keep `/ui/approvals` as operator/deep-link queue.
6. Remove Dashboard dependence on Approvals as a separate browsing page.

Acceptance:

- Pending approval can be approved/rejected from the relevant conversation or
  work context.
- Empty approvals page is not a normal-user dead end.

### Phase 5: Capabilities And Agents Cleanup

Steps:

1. Compact capability lists with search, grouping, and generated-name filtering.
2. Add missing-capability capture from protocol stage assignment.
3. Make agent default detail work-first:
   - Start conversation
   - Run protocol
   - readiness
   - key capabilities
   - recent work
4. Move selector preview, workers, capacity, trust, and token controls to
   Operations/technical details.
5. Hide empty worker panels by default.

Acceptance:

- Agent page is usable without understanding routing internals.
- Capability picker is human-scaled.
- Missing capability authoring is possible without leaving the stage draft.

### Phase 6: Runs Detail Model Tightening

Steps:

1. Keep Overview/Stages/Artifacts/Audit as the only run detail sections.
2. Move run controls into Overview and show only real applicable actions.
3. Ensure stale/running/problem state is elevated in row and Overview.
4. Keep Stages ordered by authored workflow order.
5. Ensure Artifacts rollup reuses the same rows as stage/task contexts.
6. Remove clickable-looking rows that do nothing.

Acceptance:

- A user can explain the run state from the row and Overview.
- A user can get to artifacts from both stage and rollup views.
- `running` does not hide stuck lease or stale state.

### Phase 7: Conversation Flow Tightening

Steps:

1. Default operational conversations to activity/work view when messages are
   empty.
2. Keep linked runs/tasks/artifacts visible from conversation context.
3. Keep composer and primary actions reachable.
4. Make protocol launch results visible without hunting in Runs.

Acceptance:

- Conversations referenced by tasks/runs are not empty dead ends.
- Conversation-launched protocol runs are traceable to outputs.

### Phase 8: Tests And Audit

Depth tests before breadth audit:

1. Real Safari navigation invariant: clicking every default nav item updates
   both URL and rendered heading/content without manual reload.
2. Blank protocol authoring with unassigned stages.
3. Stage draft preservation across all panels and add-stage clicks.
4. Agent-only assignment.
5. Existing capability assignment.
6. Missing capability capture.
7. Validate/publish incomplete assignment behavior.
8. Conversation-launched protocol with run/artifact follow-through.
9. Software-engineering protocol with realistic output artifacts.
10. Approval action from context, not top-level nav.
11. Task/run lineage inspection from canonical Work surface.
12. Generated/rehearsal/test data hidden from default user surfaces unless an
    operator/audit filter is active.

Breadth audit after fixes:

- automated 500+ screenshot audit
- real desktop Safari manual pass
- real Safari cache refresh after redeploy using `Option+Command+R`
- narrow/mobile smoke pass
- no database seeding as substitute for UI-created state

Database inspection is allowed for diagnosis and verification only.

## Definition Of Done

This work is done only when:

- Default nav no longer exposes empty/rare implementation queues as primary
  destinations.
- Approvals remain functional but contextual.
- Tasks are contextual to work execution rather than a confusing peer to runs.
- Protocol stage creation works with name-only stages.
- Stage drafts cannot be silently lost.
- Assignment is optional during authoring and enforced later through clear
  validation.
- Agent-only, capability-only, missing-capability, and unassigned states are
  all supported naturally.
- Capabilities are human-scaled and generated names are filtered from defaults.
- Agent pages are work-first and not dominated by operations.
- Runs/Work presents one lineage model.
- Conversations do not look empty when work/activity exists.
- Artifacts use one action contract everywhere.
- Real Safari navigation does not show stale content after normal clicks.
- Generated/rehearsal/test work does not dominate default user surfaces.
- Real Safari confirms the flows visually after deployment.

## Open Questions

- Final label for the consolidated execution surface: `Runs`, `Work`, or
  `Executions`.
- Whether `/ui/tasks` should remain visible only for operators or disappear
  entirely from nav.
- Whether `/ui/approvals` should be operator-only, deep-link-only, or accessible
  from Dashboard attention only.
- Whether missing-capability capture creates a lightweight protocol artifact,
  a capability draft, or a validation issue until explicitly converted.

## Open Findings Log

New findings must be added here before broad audit continues.

### P1.4 / P3.5 Approvals Nav Dead End

- Surface: Work navigation / Approvals
- Reproduction: open `/ui/approvals` in real Safari with no pending approvals
- Observed: a top-level page says only `No approvals waiting`
- Expected: approvals are contextual to work/conversation/task/run, not a
  default top-level destination
- Severity: high for information architecture
- Phase: 1 and 4
- Verification: default nav hides Approvals; contextual approval test still
  passes

### P1.5 Tasks And Runs Compete

- Surface: Work navigation / Runs / Tasks
- Reproduction: inspect a protocol run and its generated tasks
- Observed: Runs and Tasks expose overlapping execution information as peer
  destinations
- Expected: one canonical Work/Execution surface with task detail nested in
  run/stage/conversation context
- Severity: high for usability
- Phase: 1 and 3
- Verification: task deep links work; default nav no longer forces Runs vs
  Tasks decision

### P4.15 Create Stage Blocks On Assignment

- Surface: Protocol authoring
- Reproduction: create blank protocol, add stage with name but no skill/agent
- Observed: stage creation requires a selector assignment
- Expected: stage can be created unassigned; validation handles readiness later
- Severity: critical for 0-to-1 authoring
- Phase: 2
- Verification: UI-only test creates multiple unassigned stages

### P4.15 Create Stage Draft Can Be Lost

- Surface: Protocol authoring
- Reproduction: start adding a stage, enter data, switch panels or click another
  add-stage affordance
- Observed: user can lose entered stage data or feel the draft reset
- Expected: draft persists or user is explicitly asked continue/move/discard
- Severity: critical for trust
- Phase: 2
- Verification: UI-only draft preservation test

### P4.26 Missing Capability Has No Natural Path

- Surface: Protocol authoring / Assignment
- Reproduction: create a stage whose needed skill/capability is not in the
  picker
- Observed: UI pushes available skills and does not allow authoring the need
- Expected: user can mark `New capability needed` and continue
- Severity: high
- Phase: 2 and 5
- Verification: UI-only missing capability scenario

### P5.11 Agent Page Operational Density

- Surface: Agents
- Reproduction: open an agent detail
- Observed: capabilities, advertised skills, selector diagnostics, workers,
  capacity, health, and admin concepts compete
- Expected: work-first detail with operations behind technical/Operations path
- Severity: high
- Phase: 5
- Verification: real Safari agent audit and DOM assertions for hidden default
  operator panels

### P5.3 / P5.10 Conversations Can Look Empty

- Surface: Conversations
- Reproduction: open conversation referenced from a task/run with little message
  content
- Observed: conversation can appear empty even though work/activity exists
- Expected: operational conversations default to activity/work context
- Severity: high
- Phase: 7
- Verification: task-linked conversation test

### P3.8 Runs Still Overload The Expanded Panel

- Surface: Runs/Work
- Reproduction: expand a run with issues/artifacts/stages
- Observed: too many concepts and controls appear at once
- Expected: Overview/Stages/Artifacts/Audit with progressive disclosure and
  contextual actions
- Severity: high
- Phase: 6
- Verification: real Safari and Playwright run-detail assertions

### P2.19 Real Safari Navigation Can Render Stale Page Content

- Surface: Global navigation / real Safari
- Reproduction: open `/ui/approvals`, click `Protocols`
- Observed: URL changed to `/ui/protocols?workflow_map=auto`, but the rendered
  content still showed the Approvals page until manual reload
- Expected: every navigation click updates URL, selected nav item, heading, and
  content atomically without requiring reload
- Severity: critical for trusting visual audit and user navigation
- Phase: 8 first, then underlying UI/router fix before other release claims
- Verification: real Safari nav invariant clicks every default nav item and
  asserts URL plus visible heading/content match

### P1.6 Generated And Rehearsal Data Dominates Default Surfaces

- Surface: Dashboard, Conversations, Runs, Tasks, Protocols, Agents
- Reproduction: open the default pages in real Safari
- Observed: rehearsal conversations, operational task threads, generated draft
  protocols, and timestamped test variants dominate normal user surfaces
- Expected: default UI shows canonical human work; generated/rehearsal/test data
  is grouped, hidden, or exposed only through operator/audit filters
- Severity: high for product usability and trust
- Phase: 1, 3, 5, 7, and 8
- Verification: real Safari and Playwright default-surface tests assert no
  generated timestamp flood and no rehearsal agent/thread dominance in default
  views

### P4.24 Protocol List Flooded By Near-Duplicate Drafts

- Surface: Protocols
- Reproduction: open `/ui/protocols` in real Safari
- Observed: dozens of `Software Engineering Draft`, `Document Approval Draft`,
  timestamped Data Analysis, Meta Protocol Assistant, and generated draft names
  appear as peer protocol cards
- Expected: canonical team workflows are primary; generated variants are grouped
  under their source, archived, or hidden behind an operator/audit view
- Severity: high for Build usability
- Phase: 1 and 5
- Verification: Protocols default list shows canonical workflows first and does
  not flood with generated variants

### P4.23 Blank Stage Still Requires Owner Role

- Surface: Protocol authoring / New step
- Reproduction: create a blank protocol, click `Add first step`, enter only
  `Human audit step`, switch to Assignment, click `Create step`
- Observed: toast says `Name the owner role before creating this step`
- Expected: a named stage can be created unassigned; owner role, agent,
  capability, and missing capability are progressive fields
- Severity: critical for 0-to-1 protocol authoring
- Phase: 2
- Verification: UI-only test creates multiple named stages with no assignment
  or owner role

### P4.25 Capabilities Opens As Bot Admin Instead Of Capability Catalog

- Surface: Capabilities
- Reproduction: open `/ui/skills` in real Safari
- Observed: page requires `Choose a bot` before showing anything; it reads as
  per-bot administration rather than a human capability catalog
- Expected: default Capabilities is a searchable capability catalog; bot-scoped
  management is secondary/operator context
- Severity: high for Build usability
- Phase: 5
- Verification: default capabilities page shows human catalog and missing/new
  capability path; bot management remains reachable but not primary

### P4.25 Capabilities Bot Selector Appears Inconsistent

- Surface: Capabilities
- Reproduction: open the `Managed bot` selector in real Safari
- Observed: menu showed M1 and M2 only, while Agents shows M1, M2, M3, and
  Rehearsal; selecting M1 did not visibly update the page in this pass
- Expected: bot availability is consistent across surfaces and selector changes
  visibly update the management context
- Severity: medium until reproduced, high if confirmed
- Phase: 5 and 8
- Verification: real Safari selector test verifies options and page update for
  each visible managed bot

### P3.1 Dashboard Is An Index Instead Of An Attention Queue

- Surface: Dashboard
- Reproduction: open `/ui/` in real Safari
- Observed: Dashboard duplicates approvals, active tasks, completed tasks, open
  conversations, agents, protocol issues, usage, and protocol counts
- Expected: Dashboard shows prioritized resume/attention items with clear
  reasons and links into canonical surfaces
- Severity: high
- Phase: 1, 3, 4, 7
- Verification: Dashboard assertions check empty categories collapse and each
  item answers why it matters now

### P7.1 Operations Pages Expose Powerful Toggles Without Product Framing

- Surface: Routing
- Reproduction: open `/ui/routing` in real Safari
- Observed: raw skill advertiser rows and disable toggles are shown with little
  context
- Expected: this remains Operations-only and uses clear warnings/context for
  runtime-impacting toggles
- Severity: medium for default nav, high for accidental operator action
- Phase: 1, 8, and Operations cleanup
- Verification: default user path does not expose routing toggles; operator
  route has explanatory framing

## Route And Component Map

This map is retained from the absorbed audit charter so implementation can
trace product findings to the current UI code without creating a separate doc.

| Route | Primary renderer |
|-------|------------------|
| `/ui`, `/ui/` | `components/dashboard.js` |
| `/ui/approvals` | `components/approval-list.js` |
| `/ui/agents` | `components/agent-list.js` |
| `/ui/agents/:id` | `components/agent-detail.js` |
| `/ui/agents/:id/conversations` | `components/agent-detail.js` |
| `/ui/conversations` | `components/conversation-list.js` |
| `/ui/conversations/:id` | `components/conversation-detail.js` |
| `/ui/tasks` | `components/task-list.js` |
| `/ui/protocols` | `components/protocol-workspace.js` |
| `/ui/templates` | `components/gallery.js` |
| `/ui/gallery` | `components/gallery.js` |
| `/ui/runs` | `components/protocol-workspace.js` through `renderProtocolRuns` |
| `/ui/routing` | `components/routing-policy-list.js` |
| `/ui/skills` | `components/skill-catalog.js` |
| `/ui/usage` | `components/usage-view.js` |
| `/ui/guidance` | `components/guidance-editor.js` |
| `/ui/login` | `components/login-form.js` |

Supporting modules:

- `components/task-board.js`
- `components/composer-autocomplete.js`
- `components/event-renderers.js`
- `app.js`
- `router.js`
- `helpers/ui.js`
- `helpers/kit.js`
- `ui/css/main.css`

## Deployment Rule

When implementation resumes:

1. Commit in `/Users/tinker/output/bots/telegram-agent-bot`.
2. Push from this checkout.
3. Pull in `/Users/tinker/octopus`.
4. Redeploy from `/Users/tinker/octopus`.
5. Hard-refresh real Safari with `Option+Command+R`.
6. Run focused UI scenarios first, then broad audit.
