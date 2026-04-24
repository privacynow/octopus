# Registry UI/UX Consolidation Plan

## Status

This is the active implementation plan.

The Registry UI is no longer blocked by one isolated protocol-editor bug. The
current failure mode is product-level cognitive overload: internal system
concepts are exposed as first-class user surfaces, related concepts are split
across multiple tabs, and the places where redundancy would help users act are
missing.

This plan replaces the previous protocol-only framing with a Registry-wide UI
consolidation plan. Protocol authoring remains part of the work, but the larger
goal is to make the product understandable from a human user's perspective:

- users should know where to create workflows
- users should know where to start work
- users should know what agents can do
- users should know what happened after execution
- users should know where outputs/artifacts live
- operators should still have diagnostics, but not as default authoring UI
- the same object should not appear under multiple names unless the distinction
  is meaningful and visible

No implementation should add parallel UI or API paths. Consolidate existing
surfaces and extend the current components, stores, SDK interfaces, and tests in
place.

## Core Problem Statement

The Registry currently exposes implementation layers as peer navigation items:

- Gallery
- Protocols
- Runs
- Tasks
- Conversations
- Agents
- Skills
- Routing
- Guidance
- Workers / capacity / selector diagnostics inside agent detail

This asks users to understand the Registry's internals before they can do
simple work. A user should not need to know the difference between installed
skills, advertised skills, routing skills, selector resolution, task threads,
runtime workers, and protocol templates just to answer:

- What can this agent do?
- Can I start a conversation with it?
- Can I run a protocol?
- Where are the outputs?
- Is the system healthy enough to use?

The main live issues are:

1. `Gallery` is actually a small protocol-template/examples surface, not a
   gallery of all protocols. It conflicts with `Protocols` and creates a false
   mental model.
2. `Agents` is overloaded. The page mixes profile, health, skills, routing
   diagnostics, admin controls, workers, capacity, conversations, and task
   threads into one dense scroll.
3. The agent page has the wrong redundancy. It repeats health/connectivity in
   multiple places, but does not keep `Start conversation` available when the
   user scrolls down into related work.
4. `Skills`, `Advertised skills`, and `Routing` describe the same capability
   domain from different system layers. They are currently presented as
   separate product concepts.
5. `Selector resolution preview` is useful as an operator diagnostic, but it is
   not meaningful on the default agent profile page.
6. `Capacity 0 / 1` exposes scheduler internals without explanation. It is not
   legible as user-facing state.
7. `Workers` is empty for current agents and reads as broken or irrelevant.
   Worker/runtime diagnostics should not occupy default product space when
   empty.
8. Admin controls are visually and conceptually mixed into normal agent use.
   Trust tier, token rotation, capacity mutation, and soft-delete are operator
   tools.
9. Skill lists are intimidating and not scalable. A flat list of every skill or
   generated skill name does not help a user pick a capability.
10. Runs, tasks, conversations, approvals, and artifacts are still not presented
    as one clear execution lineage.
11. Protocols can be created and launched, but the route from protocol template
    to authored protocol to conversation launch to run outputs is still spread
    across too many surfaces.
12. Deployment practice must be disciplined: code changes happen in the source
    checkout, then push/pull into the canonical Octopus checkout. Do not deploy
    from stale local `.deploy` state and do not use source-to-target sync as the
    deployment mechanism.

## Product Principles

### 1. Product nouns beat system nouns

Default navigation should use terms that match user goals:

- Work
- Build
- Team
- Operations

Internal terms are allowed only where they directly support an operator task.

### 2. One concept, one primary home

Each object type needs one primary surface:

- authored workflows live in `Protocols`
- reusable starters live in `Templates`
- human-facing execution lives in `Runs`
- people/agents live in `Agents`
- agent abilities live in `Capabilities`
- low-level routing diagnostics live in `Operations`

Cross-links are allowed. Duplicate primary homes are not.

### 3. Progressive disclosure by default

The default path shows what the user can act on now. Diagnostics and internals
are behind explicit progressive disclosure or operator-only routes.

### 4. Good redundancy is action redundancy

Repeat important actions where users need them:

- start conversation from agent header and related-work section
- run protocol from protocol page, conversation page, and agent context
- open/download/copy artifact wherever a concrete artifact appears

Do not repeat passive status labels without adding comprehension or action.

### 5. Capabilities are user-facing; routing is infrastructure

Users choose capabilities. The system routes. Operators inspect routing.

### 6. Run lineage is one story

Every execution view should reveal:

- protocol
- run
- stages
- routed tasks
- agent/participant assignment
- approvals/decisions
- conversations/activity
- artifacts read, written, reviewed, approved, or verified

The user should not have to mentally join independent lists.

### 7. Shared workspace artifacts are first-class outputs

Concrete runtime artifacts must consistently expose:

- label
- producing stage/task
- path
- verification state
- preview/open/download/copy path actions when available

Declared design-time artifacts must not pretend bytes exist before a run has
produced them.

### 8. Operator tools stay available, but not dominant

Routing, selector preview, workers, token rotation, trust tier, and raw capacity
are real capabilities. They belong in `Operations` or operator drawers, not in
the normal author/agent/product path.

## Target Information Architecture

### Primary Navigation

Replace the current flat navigation with four grouped areas.

#### Work

Default operational work surfaces:

- Dashboard
- Conversations
- Runs
- Tasks
- Approvals

`Work` answers: what is happening, what needs attention, and where do I resume?

#### Build

Creation and authoring surfaces:

- Protocols
- Templates
- Capabilities, if skill authoring is user-facing

`Build` answers: what can I create, edit, publish, and reuse?

#### Team

People/agent surfaces:

- Agents
- Agent detail
- Agent conversations/runs/tasks

`Team` answers: who can do work, what can they do, and how do I start with
them?

#### Operations

Operator-only or advanced surfaces:

- Routing
- Selector diagnostics
- Worker/runtime diagnostics
- Guidance/provider configuration
- Trust/capacity/token controls
- Usage

`Operations` answers: how is the system wired and healthy?

### Navigation Decisions

- Rename `Gallery` to `Templates`.
- Move `Templates` under `Protocols` or keep it as a secondary item in `Build`,
  not as a peer that sounds like all protocols.
- Do not show `Routing`, `Guidance`, or selector diagnostics in the normal
  authoring path unless the current user/session is in operator mode.
- Keep `Runs` top-level because it is a real user need, but every protocol and
  conversation should link into the same run detail contract.

## Target Page Designs

## Protocols and Templates

### Problem

`Gallery` currently contains protocol examples/templates, while `Protocols`
contains authored definitions. The split is understandable internally but not
obvious to users.

### Target

`Protocols` becomes the workflow home:

- Published
- Drafts
- Templates
- Recent runs

Templates are starters, not a separate product destination.

### Behavior

- `New protocol` opens a choice:
  - start blank
  - start from template
  - compose from existing protocol/capability
- Template cards clearly say `Template`, not `Protocol`.
- Using a template creates an authored draft and moves the user into the normal
  protocol editor.
- Published protocol detail includes:
  - start from conversation
  - run now
  - recent runs
  - output artifacts from recent runs
  - edit draft if permitted

### Acceptance

- A user can explain the difference between a template and a protocol from the
  UI alone.
- There is no top-level `Gallery` label.
- No protocol exists only in Templates unless it is explicitly a template.
- Creating a protocol from a template follows the same authoring pipeline as
  blank creation.

## Agent List

### Problem

Agent cards combine status, identity, provider, slug, capacity, and trust tier
without prioritizing what users need.

### Target

Agent list answers:

- Is this agent usable?
- What kind of agent is it?
- What can I start?
- What are its top capabilities?

### Behavior

Each agent card should show:

- display name
- status: `Ready`, `Busy`, `Unavailable`, or `Needs setup`
- provider
- top 3 capabilities plus `+N more`
- last active time
- primary action: `Start conversation`
- secondary action: `View details`

Avoid showing raw values such as `capacity 0/1` on the list. If capacity must be
visible, translate it:

- `Ready`
- `Busy: 1 of 1 work slots used`
- `Idle: 0 of 1 work slots used`

### Acceptance

- The list is scannable with M1, M2, M3, and Rehearsal.
- A user can start a conversation without opening the detail page.
- Raw agent IDs are not shown in the default card.
- Raw capacity notation is not shown in the default card.

## Agent Detail

### Problem

Agent detail is currently a mixed admin/runtime/capability/conversation page.
It is too dense and too scroll-dependent.

### Target

Agent detail becomes a progressive profile with persistent actions.

### Default Layout

#### Header

Show:

- agent name
- simple status
- provider
- slug if needed, but subdued
- primary CTA: `Start conversation`
- secondary CTA: `Run protocol with this agent`

Keep the primary CTA sticky or repeated near the bottom of related work.

#### Overview

Show only human-legible basics:

- provider
- status
- last active
- trust tier if meaningful to users
- workspace/scope only if it affects use

Move raw IDs into `Technical details`.

#### Capabilities

Show curated capability groups:

- Core engineering
- Integrations
- Review and quality
- Custom

Show top capabilities first. Allow search/filter. Do not dump every skill as a
wall of chips.

Use capability names users understand. Keep raw selectors hidden unless the user
opens technical details.

#### Related Work

Show:

- recent conversations
- recent runs
- active tasks
- recent artifacts if they exist

Use one combined “recent work” story before listing every task thread.

#### Technical Details

Collapsed by default:

- agent ID
- slug
- transport
- execution state
- raw capacity
- registry scope
- advertised skills/raw selectors

#### Operations

Visible only for operators or behind an explicit `Operations` tab/drawer:

- trust tier mutation
- capacity mutation
- token rotation
- disconnect / soft-delete
- selector resolution preview
- worker diagnostics

### Workers

Hide `Workers` when empty in the default view.

If workers exist, show a compact runtime summary:

- process count
- last heartbeat
- current assignment
- link to diagnostics

Full worker detail belongs in Operations.

### Selector Preview

Move selector preview out of default agent detail.

New home:

- `Operations > Routing diagnostics`
- optional deep link from agent technical details: `Test routing selectors`

Rename to `Routing selector test` or `Selector diagnostics`.

Explain it in product terms:

> Test how @agent, @skill, and @role selectors resolve before changing routing
> or protocol assignment rules.

### Acceptance

- Default agent page fits the first meaningful summary and primary actions in
  one viewport on desktop.
- Mobile shows a clear header, status, and primary action before any dense data.
- `Start conversation` is reachable without scrolling back to the top.
- `Selector resolution preview` is not visible on the default agent page.
- Empty workers are not visible on the default agent page.
- Admin actions are not mixed into normal agent use.

## Capabilities, Skills, and Routing

### Problem

The current UI has three overlapping concepts:

- installed skills
- advertised skills
- routing skills

Users see them as separate lists and cannot tell which one they should care
about.

### Target

Create one user-facing concept: `Capabilities`.

Capabilities answer:

- what can agents do?
- which agents can do it?
- can I use it in a conversation?
- can I assign it in a protocol stage?
- does it require setup?

Routing is the operator implementation layer behind capabilities.

### Behavior

#### Capabilities Page

Replace or consolidate `Skills` and the user-facing parts of `Routing`.

Each capability row/card shows:

- name
- description
- category
- available agents
- setup status
- use surfaces:
  - conversation
  - protocol stage
  - routing selector
- status:
  - available
  - setup required
  - disabled
  - operator-only

#### Agent Capability View

On agent detail, show capabilities scoped to that agent with the same model.

#### Routing Diagnostics

Move raw routing toggles and advertised-by details into Operations:

- capability enable/disable
- advertised-by raw agents
- selector test
- routing policy internals

### Generated / Duplicate Skills

Generated skills with timestamp suffixes must not appear as normal catalog
choices.

Rules:

- standard picker shows published, named, user-meaningful capabilities only
- generated/prototype skills are grouped under `Generated` or hidden behind
  `Show generated capabilities`
- duplicate names collapse to one capability with version/source detail
- if a skill is stale, deleted, or superseded, it is not shown in default
  authoring pickers

### Acceptance

- A user sees one capability list, not separate skill/routing concepts.
- Agent detail and protocol assignment use the same capability presentation.
- Routing internals remain accessible to operators.
- Timestamp-generated skill names do not pollute default pickers.
- The same capability can be used from conversation and protocol assignment
  without duplicative UI logic.

## Conversations

### Problem

Conversations are the natural starting point for work, but protocol launch and
agent/capability use are still inconsistently surfaced. Operational task
threads also look like empty chats when their useful content is activity.

### Target

Conversation detail becomes the primary “do work” surface.

### Behavior

Conversation composer should support:

- mention agent
- choose capability
- start protocol
- attach or reference artifact
- inspect linked runs

Protocol launch from conversation should use the same published protocol list as
the protocol page.

Operational task threads should default to activity view when activity is the
main content. Message-first conversations should default to chat.

### Acceptance

- A user can start a published protocol from a conversation without leaving the
  conversation surface.
- A user can use an agent/capability from the same area.
- Linked runs appear in context and open to run detail.
- Operational task threads do not look empty when they contain activity.

## Runs, Tasks, Approvals, and Artifacts

### Problem

Runs, tasks, approvals, conversations, and artifacts are currently rendered as
neighboring resources. Users need to see the hierarchy and lineage.

### Target

Execution UI presents one connected story:

- protocol
- run
- stage execution
- task
- conversation/activity
- approval/decision
- artifacts

### Behavior

#### Run Detail

Run detail should be the canonical execution record.

Show:

- run status
- current/final stage
- protocol name and version
- linked conversation
- stage timeline
- output artifacts
- decisions/approvals
- task lineage

#### Task Detail

Task detail should always show:

- parent run if any
- parent stage if any
- assigned agent
- expected inputs/outputs
- actual artifacts produced
- links back to run and conversation/activity

#### Approval Detail

Approval detail should show:

- run/stage/task context
- artifact(s) under review
- decision and reviewer
- links back to run and conversation/activity

#### Artifact References

Wherever a concrete artifact appears, expose the same action contract:

- Preview when previewable
- Open when browser-viewable
- Download
- Copy path

Where an artifact is only declared and not yet produced:

- show `Not produced yet`
- show which stage is expected to produce it
- do not render broken file actions

### Acceptance

- A user can start from a run, task, approval, or conversation and understand
  where they are in the same execution hierarchy.
- Runtime artifacts have consistent actions across surfaces.
- Declared-but-not-produced artifacts are clearly non-actionable.
- Duplicate artifact rows for the same current artifact are collapsed with
  history/stage context.

## Dashboard

### Problem

Dashboard should orient users but must not become another redundant resource
index.

### Target

Dashboard answers:

- What needs attention?
- What recently completed?
- What can I start?
- Are agents ready?

### Behavior

Dashboard sections:

- Attention: failed runs, blocked tasks, approvals needed
- Start: conversation, protocol, template
- Active work: running runs/tasks
- Outputs: recent artifacts
- Team: agent readiness summary

Each card links to the canonical surface, not a duplicate mini-detail.

### Acceptance

- Dashboard gives entry points without duplicating full pages.
- Agent status appears as a summary, not a second agent page.
- Recent artifacts link to the same artifact action contract.

## Operations

### Problem

Admin/operator functions are scattered through normal pages.

### Target

Operations becomes the home for infrastructure and diagnostics.

### Surfaces

- Routing policies
- Capability routing toggles
- Selector diagnostics
- Worker/runtime diagnostics
- Provider setup/guidance
- Trust and token management
- Capacity management
- Usage / quotas

### Behavior

Operations pages should be explicit about audience:

> These controls affect how Registry routes and executes work.

Normal users should not encounter these controls accidentally.

### Acceptance

- Normal agent detail does not show operator-only controls by default.
- Operators can still reach every existing diagnostic/control capability.
- Selector preview remains test-covered but is no longer a default profile
  widget.

## Visual and Interaction Direction

### Density

Reduce cognitive load by removing simultaneous structure, not merely shrinking
spacing.

Rules:

- fewer borders
- fewer all-caps labels
- less repeated metadata
- stronger section hierarchy
- more whitespace around major decisions
- compact only where scanning repeated rows

### Progressive Panels

Use progressive disclosure consistently:

- summary first
- primary action next
- related work next
- details on demand
- operations last

### Responsive Behavior

Mobile must not become a single long dense document.

Rules:

- sticky primary actions where appropriate
- collapsible technical details
- searchable capability lists
- related work tabs instead of huge stacked lists
- no horizontal overflow

## Implementation Plan

## Phase 0: Inventory and Product Boundaries

### Goals

- Identify every current navigation item and its user/operator purpose.
- Map each existing component to the target information architecture.
- Decide which surfaces are default, progressive, or operator-only.

### Steps

1. Document current routes:
   - Dashboard
   - Conversations
   - Tasks
   - Protocols
   - Gallery
   - Runs
   - Agents
   - Usage
   - Routing
   - Skills
   - Guidance
2. Classify each route:
   - user-facing work
   - user-facing build
   - team/agent
   - operator/diagnostic
3. Identify duplicated concepts:
   - Gallery/Templates
   - Skills/Capabilities/Routing
   - agent status pills/overview fields
   - conversations/task threads/activity
4. Identify missing useful redundancy:
   - start conversation from agent lower sections
   - run protocol from agent context
   - artifact actions across all references
5. Produce route migration notes before code edits.

### Acceptance

- Every existing route has one target home.
- No capability is lost.
- No new parallel implementation path is proposed.

## Phase 1: Navigation and Terminology

### Goals

- Rename confusing surfaces.
- Group navigation by product intent.
- Hide or demote operator surfaces from normal flow.

### Steps

1. Rename `Gallery` to `Templates`.
2. Move Templates into the `Build` group or into Protocols as an internal tab.
3. Group navigation visually:
   - Work
   - Build
   - Team
   - Operations
4. Move `Routing`, `Guidance`, and low-level diagnostics under Operations.
5. Decide whether `Skills` remains visible or becomes `Capabilities`.
6. Update labels and empty-state copy.
7. Update route tests and accessibility expectations.

### Acceptance

- No top-level route is named `Gallery`.
- Navigation communicates intent without requiring internal knowledge.
- Operator surfaces are still reachable but clearly separate.

## Phase 2: Protocols + Templates Consolidation

### Goals

- Make protocol creation and template usage one coherent workflow.

### Steps

1. Add Templates as a tab/section in Protocols.
2. Keep `Start blank` and `Use template` as creation choices.
3. Ensure template use creates a normal protocol draft.
4. Add recent runs and launch affordances to published protocol detail.
5. Remove any duplicated Gallery-only behavior.
6. Update E2E tests:
   - start blank
   - create from template
   - publish
   - launch from conversation
   - verify artifacts

### Acceptance

- Templates are clearly starters.
- Authored protocols remain in Protocols.
- The protocol lifecycle is discoverable from one home.

## Phase 3: Agent Page Refactor

### Goals

- Make agents usable as team members, not admin records.

### Steps

1. Refactor agent list cards:
   - display status as Ready/Busy/Unavailable/Needs setup
   - show top capabilities
   - add `Start conversation`
   - demote raw capacity
2. Refactor agent detail:
   - header with sticky/repeated `Start conversation`
   - capability summary
   - recent work
   - collapsed technical details
   - operator-only operations panel
3. Move selector preview into Operations.
4. Hide empty workers by default.
5. Translate capacity labels.
6. Remove repeated status pills that duplicate overview facts.
7. Add responsive behavior for mobile:
   - sticky action bar
   - capability search
   - related work tabs

### Acceptance

- A normal user can use an agent without seeing routing diagnostics.
- Start conversation is always easy to reach.
- Capability summary is scannable.
- Admin/runtime internals are progressive or operator-only.

## Phase 4: Capabilities Consolidation

### Goals

- Merge the user-facing parts of Skills and Routing into one capability model.

### Steps

1. Define a UI projection for capability:
   - name
   - description
   - category
   - available agents
   - setup state
   - routing state
   - usable surfaces
2. Reuse this projection in:
   - agent detail
   - protocol assignment
   - conversation composer
   - capability management
3. Move raw advertised skills and routing toggles to Operations.
4. Group generated/prototype skills.
5. Collapse duplicate/generated timestamp names.
6. Add search/filter/category behavior.
7. Update tests for:
   - agent capability display
   - protocol assignment picker
   - conversation capability use
   - routing diagnostics still accessible to operators

### Acceptance

- Users see capabilities, not routing internals.
- The same capability appears consistently across agent, protocol, and
  conversation surfaces.
- Generated junk names do not pollute default lists.

## Phase 5: Conversation-First Work Launch

### Goals

- Make conversations the natural place to use agents, capabilities, and
  protocols.

### Steps

1. Keep agent quick-start visible.
2. Add protocol launch with search/select in conversation detail.
3. Add capability selection in the same interaction model.
4. Show linked runs directly in conversation context.
5. Default operational task threads to activity/task view.
6. Ensure protocol launch uses SDK/shared infrastructure, not a UI-only path.
7. Test from Registry UI and Telegram where applicable.

### Acceptance

- A user can start work from conversation with:
  - agent
  - capability
  - protocol
- Linked runs and outputs are visible after execution.
- Task threads do not appear empty when activity exists.

## Phase 6: Execution Lineage and Artifact Contract

### Goals

- Make runs/tasks/approvals/conversations/artifacts read as one hierarchy.

### Steps

1. Define shared lineage card/component data:
   - protocol
   - run
   - stage
   - task
   - agent
   - conversation
   - artifacts
2. Use the shared projection in:
   - Runs
   - Tasks
   - Approvals
   - Conversations
   - Agent related work
   - Dashboard
3. Ensure artifact rows use one action component everywhere.
4. Distinguish declared artifacts from produced artifacts.
5. Collapse duplicate current artifacts with history.
6. Add output previews/open/download/copy path across all surfaces.

### Acceptance

- User can trace any task back to run/protocol/conversation.
- User can trace any artifact back to stage/task/run.
- Concrete artifact actions behave consistently everywhere.
- No broken actions appear for unproduced artifacts.

## Phase 7: Operations Surface

### Goals

- Preserve operator power while removing it from normal user flow.

### Steps

1. Create or consolidate Operations sections:
   - Routing
   - Selector diagnostics
   - Worker diagnostics
   - Provider/guidance setup
   - Capacity and trust controls
   - Tokens/disconnect
2. Move existing controls rather than reimplementing them.
3. Add clear warnings and audience copy.
4. Gate operator-only controls consistently in UI and API.
5. Update tests for both standard and operator surfaces.

### Acceptance

- Normal users do not see operator controls in default agent/product views.
- Operators retain all required controls.
- API permissions match UI visibility.

## Phase 8: Visual System Cleanup

### Goals

- Restore lightness and scan quality without hiding important actions.

### Steps

1. Audit cards, borders, labels, and repeated metadata.
2. Define density levels:
   - hero/summary
   - repeated list rows
   - technical details
   - diagnostic tables
3. Reduce unnecessary borders and all-caps labels.
4. Increase spacing around major decisions.
5. Use compact rows only for repeated scan lists.
6. Verify desktop and mobile screenshots at each step.

### Acceptance

- Default pages no longer look like dense admin forms.
- Mobile does not become a long unstructured scroll.
- Important actions remain visible.

## Phase 9: Testing and Visual Verification

### Required Scenario Specs

Each release candidate must pass UI-level scenarios for:

1. Create protocol from blank.
2. Create protocol from template.
3. Launch protocol from conversation.
4. Use agent capability from conversation.
5. Assign capability/agent in protocol stage.
6. Execute protocol and verify artifacts.
7. Open run from conversation.
8. Open task from run.
9. Open artifact from run/task/conversation/agent related work.
10. Operator opens routing diagnostics and selector test.

### Negative Invariants

Standard user paths must not show:

- custom runtime selector
- Advanced protocol internals
- selector resolution preview on agent detail
- token rotation
- soft-delete
- raw capacity mutation
- empty workers panel
- generated timestamp skill spam in default pickers

### Visual Audit

Use screenshots for:

- desktop nav
- mobile nav
- protocols/templates
- agent list
- agent detail top
- agent detail scrolled related work
- capabilities page
- conversation launch
- run detail artifacts
- task detail lineage
- operations diagnostics

The visual audit is breadth. Scenario specs are the release bar.

## Deployment Rule

Do not deploy from the source checkout if its `.deploy` state is not canonical.

Required deployment workflow:

1. Commit changes in `/Users/tinker/output/bots/telegram-agent-bot`.
2. Push from that checkout.
3. Pull in `/Users/tinker/octopus`.
4. Redeploy from `/Users/tinker/octopus`.

Do not use source-to-target rsync as the deployment mechanism.

## Definition of Done

This work is done only when:

- navigation no longer exposes confusing duplicate product nouns
- `Gallery` is gone or renamed/moved as Templates
- agent list and detail are usable without understanding internals
- capabilities replace the user-facing Skills/Routing split
- selector preview and worker diagnostics are operator diagnostics
- capacity is translated into human status
- start conversation is available where users need it
- protocol template to protocol draft to conversation launch is one coherent
  path
- runs/tasks/approvals/conversations/artifacts share one lineage contract
- artifact actions are consistent wherever concrete artifacts appear
- standard paths hide operator-only controls
- scenario specs pass end to end
- visual audit confirms desktop and mobile are progressive and lower-density
- deployment follows push/pull only

## Risks

### Risk: Hiding Operator Tools Too Aggressively

Mitigation: move controls to Operations with explicit links from technical
details, rather than deleting capabilities.

### Risk: Capabilities Model Becomes Another Parallel Layer

Mitigation: capability UI must be a projection over existing skill/routing data,
not a new independent data store.

### Risk: Templates Lose Discoverability

Mitigation: expose Templates inside Protocols and in the create flow, not as a
separate confusing top-level Gallery.

### Risk: Artifact Actions Diverge Again

Mitigation: one shared artifact action component and one shared artifact lineage
projection.

### Risk: Visual Cleanup Only Shrinks the UI

Mitigation: remove simultaneous sections and repeated labels before tightening
spacing.

### Risk: Tests Keep Cheating with API/DB Setup

Mitigation: scenario specs must create state through UI/API-backed product
actions, not direct database mutation.

## Immediate Next Steps

1. Implement navigation terminology and grouping.
2. Fold Gallery into Protocols as Templates.
3. Refactor agent detail into:
   - summary
   - capabilities
   - related work
   - technical details
   - operations
4. Consolidate user-facing Skills/Routing into Capabilities.
5. Move selector preview and worker diagnostics into Operations.
6. Add scenario specs and negative invariants before broad visual polish.
7. Run visual audit after each major surface change.

## Live Audit Findings

### Finding: Protocol Launch Can Produce Semantically Mismatched Artifacts

During UI-only launch from an agent conversation, the selected published
software-engineering simulator accepted a new release-note-generator problem
statement but kept static feature-flag simulator artifact paths and stage
language. The run did execute and produced downloadable artifacts, but the
artifact contract did not adapt to the user's stated outcome.

Required fix:

- make protocol launch make the selected protocol's fixed scope explicit before
  start, or require a template/protocol whose artifact paths are generic enough
  for arbitrary software-engineering problems
- add a scenario assertion that the problem statement, selected protocol name,
  artifact names, artifact paths, and generated artifact contents describe the
  same product
- prevent future "UI-only simulator <timestamp>" protocols from polluting the
  normal published-protocol selector, or move test fixtures behind an operator
  filter
- keep the Protocols tab as the full catalog, but make conversation launch
  progressive: recent official protocols first, search for the rest, and no
  timestamped fixture wall in the default selector

Implementation status:

- Default conversation protocol launch now collapses timestamp-generated
  protocols by family and shows only the latest family entry.
- Search remains able to find older generated versions when an operator/user
  intentionally needs them.
- The launch form now shows a protocol-scope warning: the problem statement is
  run context, not a schema rewrite. Published stage instructions and artifact
  paths remain fixed by the selected protocol.
- Capability lists and agent capability chips now hide timestamp-generated
  capability names by default while preserving search-based discovery.
- Artifact `Preview` now uses the same shared artifact action component with a
  content-link fallback, so a produced artifact still has an actionable path if
  inline JavaScript preview fails.

Remaining product work:

- Create or publish non-fixture protocols whose names, stage instructions,
  artifact paths, and generated outputs are generic enough for the advertised
  workflow.
- Add an end-to-end scenario that launches one of those protocols from the UI
  and asserts semantic alignment between selected protocol, problem statement,
  artifact path, artifact title, and artifact content.
