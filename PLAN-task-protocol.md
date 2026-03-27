# Plan: Registry UI and Operator Workspace Redesign

## Purpose

Redesign the registry operator product from first principles on top of the
already-completed protocol/backend work.

This plan replaces the old "finish the remaining UI gaps" framing.

That framing was wrong.

The last UX pass proved that incremental compression of the existing screens is
not good enough. The product needs a coherent redesign of:

- information hierarchy
- navigation flow
- visual system
- action model
- responsive behavior
- empty states
- live-update behavior

The goal is not to make the current UI less bad.

The goal is to make the registry feel like one intentional operator console.

## Current baseline

Current baseline for redesign and verification:

- repo branch contains revert commit `6399964`
- that revert backs out failed commit `76da175`
- `/Users/tinker/octopus` has been redeployed cleanly to that reverted state

Protocol/backend work that is already complete and must be preserved:

- structured coordination protocol and typed routed-task lifecycle
- shared exact alias resolution for authoritative routing
- plain `@selector ...` routing in registry and Telegram
- direct-assignment operator messages preserved in conversation history
- delegated usage rollup support
- deterministic routed-task IDs
- SDK-owned selector parsing and lifecycle validation
- vendored `morphdom` and `Fuse.js`

Baseline distinction:

- backend preserved:
  - typed coordination actions
  - direct assignment inserts `message.user`
  - deterministic task IDs
  - lifecycle validation
  - exact alias resolver
  - usage rollup support in store logic
- UI infrastructure preserved:
  - vendored `morphdom`
  - vendored `Fuse.js`
  - `UI.reconcileChildren`
  - router, API client, and websocket plumbing
  - current conversation semantics that already include
    `delegation.submitted`
- redesign targets:
  - component implementations
  - CSS/layout system
  - route-level information architecture
  - smoke expectations and visual review standards

This redesign does **not** reopen the backend protocol architecture unless a UI
need reveals a real product bug.

## Problem statement

The registry UI is still not commercially acceptable.

The current and recently-failed states show the same root problem:

- screens are built as piles of panels instead of operator workspaces
- metadata and empty states are visually louder than actual work
- headings, subtitles, pills, tabs, cards, and actions compete with each other
- the same design language is not carried cleanly across Conversations, Tasks,
  Dashboard, Agents, Approvals, and Usage
- screens explain themselves too much instead of getting out of the way
- the product still behaves like an admin scaffold instead of a sleek
  operations tool

The redesign must therefore start from operator jobs, not from the current DOM.

## What happened last time

The failed pass was not random. It failed for specific reasons.

### Mistakes made

1. We treated "reduce noise" as a local CSS/layout compression problem.
2. We patched individual screens instead of redesigning the shared product
   grammar.
3. We kept too much of the old panel structure and only changed styling around
   it.
4. We overused generic pills/chips for metadata that should have been quiet
   inline text.
5. We changed the Conversation view more than Tasks and Full activity, so the
   same route looked like multiple different products stitched together.
6. We accepted "functionally improved" as if it meant "product-quality UX."
7. We relied too much on tests and smoke while underweighting direct visual
   review.
8. We optimized for explicitness and then overcorrected into awkward compact
   fragments.
9. We tolerated partial migration language like "mostly done" and "dominant
   path," which made it too easy to ship unfinished UI.
10. We let empty states, metadata, and helper text occupy more visual weight
    than the main action.
11. We showed internal or low-actionability metadata without explaining what it
    meant or giving the operator a useful action from it.
12. We rendered controls that looked like labels, so quick-start and agent
    actions were visually ambiguous.
13. We redesigned the core work routes more than the admin/support routes, so
    Capabilities, Skills, and Guidance still looked like a different product.
14. We allowed empty-state text to float misaligned inside oversized shells,
    which made quiet screens look broken instead of calm.
15. We duplicated status and helper copy in multiple forms:
    `Status: published` plus `PUBLISHED`, `Shortcut: /`, and other ambient text
    that added noise without changing the next action.
16. We left delegated-work milestones too close to raw event payloads, so the
    Conversation tab could show machine-ish fragments, duplicated labels, and
    unreadable concatenated task details instead of clear operator phrasing.
17. We preserved too much fixed route geometry, so sparse conversations and
    filtered/empty list states still sat inside oversized shells with large
    vertical gaps and wasted width.
18. We treated delegated milestones as structural events instead of operator
    outcomes, so "task submitted" / "task completed" could appear without
    clearly surfacing what actually happened.
19. We allowed fallback identifiers to leak into operator-facing summaries:
    raw conversation ids in task rows, raw target ids in delegation summaries,
    and duplicate `@target` suggestions for the same agent.

### Mistakes to avoid

1. Do not patch the old layout one panel at a time.
2. Do not invent a separate visual treatment for every route.
3. Do not use pills for non-status metadata.
4. Do not stack page header, local header, panel header, subtitle, and empty
   state if one header and one work surface will do.
5. Do not ship because tests are green while the screen still looks wrong.
6. Do not accept "mostly migrated" reconciliation behavior.
7. Do not call a screen done while desktop and mobile still look like different
   products.
8. Do not add explanatory prose unless it changes the user's next action.
9. Do not let empty states become the main visual object on a screen.
10. Do not treat visual review as optional after implementation.
11. Do not surface metadata in prime screen real estate unless its meaning is
    clear and the operator can use it.
12. Do not present actions as passive pills, chips, or labels.
13. Do not leave legacy admin/support routes outside the redesign system.
14. Do not let empty-state text sit misaligned inside a decorative container.
15. Do not repeat the same fact in subtitle text, helper text, and badge form.
16. Do not ship a mobile shell whose navigation drawer does not actually open.
17. Do not render routed-work milestones as raw task field dumps.
18. Do not preserve oversized fixed-height route geometry when the screen is
    quiet or sparse.
19. Do not require expansion to learn the outcome of completed delegated work.
20. Do not leak raw internal identifiers into primary operator summaries when a
    human-facing label exists.
21. Do not show the same routing target twice in the `@` suggestion list.

## Discussion and decisions

This section captures the product decisions so implementation does not drift.

### 1. Product identity

The registry is an operator console.

It is not:

- a generic admin dashboard
- a marketing site
- a CRUD-heavy back-office tool
- a collection of unrelated panels

The UI must feel:

- calm
- dense
- confident
- action-oriented
- progressively discoverable
- visually consistent

### 2. Main operator jobs

The product must make these jobs easy:

1. Start or resume work with the right agent quickly.
2. See what needs intervention right now.
3. Read a conversation and act without losing context.
4. Inspect delegated work without drowning in machine detail.
5. Check approvals and act immediately.
6. Understand agent health and availability.
7. Understand cost/usage in a way that matches actual work.

If a screen element does not support one of those jobs, it is a candidate for
removal.

### 3. Navigation model

Keep the left rail.

Reason:

- it gives stable section context
- it avoids inventing new top-level navigation
- it already works for desktop and can collapse on mobile

Decision:

- do not add new top-level views or side panels
- streamline the existing routes instead
- use local sub-navigation only when the route genuinely has multiple modes
- mobile drawer/rail behavior is part of the shared shell contract and must work
  before route polish is considered complete

### 4. Conversation product model

Conversation detail is the center of the product.

Decision:

- redesign this route first and make other routes align to it

Conversation route contract:

- one compact local header
- one primary work surface
- one pinned composer region
- one set of tabs with distinct semantics

The route must never look like stacked decorative bands.

### 5. Tab semantics

Final tab contract:

- `Conversation`
  - human-readable operator thread
  - includes operator messages
  - includes bot replies
  - includes approvals
  - includes concise human-facing routed-work milestones, including
    `delegation.submitted`
- `Tasks`
  - structured delegated work for the conversation
  - no duplicate board + log for the same task
- `Full activity`
  - raw event stream
  - denser, more log-like, less decorative

There is no fallback interpretation here.

### 6. Quick-start model

Decision:

- starting work should happen directly from Conversations and Agents
- no popup-first flow
- no billboard buttons

Implementation model:

- compact connected-agent quick-start row on Conversations
- `Open conversation` / `Start conversation` on Agents surfaces
- reuse current routes
- prefer reuse of an existing open conversation when relevant

### 7. Visual language

Decision:

- abandon the current layered card-on-card-on-card feel
- use a restrained editorial operations-console language

Rules:

- one accent family
- quiet metadata
- status chips only for status
- one spacing scale
- one border/shadow system
- modest radius
- no oversized pills for IDs, counts, or references
- no giant empty-state slabs
- both light and dark themes must be intentionally designed from the same
  system, not derived by lazy inversion
- empty-state text must align cleanly within its container and never look like a
  stray sentence dropped into a bubble

### 8. Metadata and actionability model

Decision:

- visible metadata must earn its place
- every top-level metadata item must answer at least one of:
  - what am I looking at?
  - what state is it in right now?
  - what can I do next?

Rules:

- status and freshness may be top-level because they support immediate action
- actor/assignment metadata may be top-level only when its role is explicit:
  - `With M1`
  - `Assigned to M2`
  - `Started in registry`
- ambiguous labels like `Agent` and `Source` are not acceptable in prime UI
- raw reference IDs are not primary metadata
- event counts are not primary metadata unless rendered as an action:
  - `Activity (8)` opening `Full activity`
- if metadata is diagnostic, internal, or rarely used, move it to progressive
  disclosure:
  - `Details`
  - copy action
  - secondary inspector
- metadata that remains visible must be quiet, compact, and aligned
- avoid duplicated lifecycle/status rendering:
  - not `Status: published` plus a `PUBLISHED` badge unless the badge adds
    distinct action meaning
- helper text like `Shortcut: /` must be secondary and rare, not ambient litter
- delegated-work metadata in the Conversation tab must be written in operator
  language, not schema language
- if an event is shown in the Conversation tab, the operator must be able to
  read it without parsing IDs, raw status fields, or concatenated machine terms

This is not permission to throw metadata away casually.

It is a requirement to render it in a form an operator can understand and use.

### 9. Responsive model

Decision:

- desktop and mobile are both first-class
- mobile is not a shrunken desktop stack

Rules:

- desktop uses width effectively without turning into a stretched wasteland
- mobile keeps one clear working surface visible
- composer remains easy to reach
- local actions compress cleanly
- tabs remain legible and tappable
- the mobile drawer must open, close, and restore focus correctly
- route empty states must remain aligned and compact on mobile, not degrade into
  broken strips or oversized blank cards

### 9. Reconciliation model

Decision:

- `morphdom` is the reconciliation primitive everywhere on operator-facing
  success/update paths

Rules:

- no remaining redraw-driven operator screen on routine updates
- no "we vendor morphdom but still clear the container first" loophole
- first-load skeletons and fatal-error resets are the only acceptable full
  clear cases

### 10. Accessibility model

Accessibility is part of the redesign foundation, not a cleanup phase.

Rules:

- use native interactive elements where possible
- tabs, segmented controls, and list actions must be keyboard navigable
- every segmented control that uses roving `tabIndex` must support:
  - `ArrowLeft`
  - `ArrowRight`
  - `Home`
  - `End`
- route and view transitions must preserve or intentionally move focus
- reduced-motion support must remain intact
- both light and dark themes must meet usable contrast standards
- accessibility must be designed during Phase 0 and verified in later phases,
  not bolted on at the end

### 11. Verification model

Decision:

- source review, tests, and smoke are necessary but insufficient
- private visual review on disposable Docker stacks is a hard promotion gate

Rules:

- desktop review required
- mobile review required
- live deployed UI review required after octopus promotion

## Design principles

1. One dominant surface per route.
2. Metadata is quiet.
3. Empty states are small.
4. Actions live where decisions happen.
5. Information density beats decorative framing.
6. Progressive disclosure beats ambient explanation.
7. Consistency across routes beats local cleverness.
8. The UI must scale to many agents, many tasks, and many conversations.
9. The operator should see the next action before the explanation.
10. If it looks like multiple products stitched together, it is wrong.

## Information architecture target

### Conversations index

Must contain:

- route title
- compact connected-agent quick-start row
- compact filters/search
- conversation list

Must not contain:

- essay-like helper text
- billboard CTAs
- giant empty-state cards

Quick-start rules:

- controls must read unmistakably as controls, not labels
- the row must scale cleanly to many connected agents
- the route must still work gracefully with 20+ connected agents
- graceful handling does not require rendering every connected agent inline
- a curated inline subset plus a clear overflow path is acceptable
- do not add redundant labels like `Start with` when the controls already make
  the action obvious
- supporting metadata about agents belongs behind progressive disclosure or on
  the destination route, not in the launcher row
- empty-state messaging must be aligned with the list shell, not dropped into a
  thin orphan strip above a large void
- filtered and empty states must collapse the route vertically instead of
  leaving a large unused slab beneath a thin status strip

### Conversation detail

Must contain:

- one compact header with title, quiet metadata, status/time, and actions
- tab strip
- one main content surface
- pinned composer region

Must not contain:

- repeated route title
- repeated "Conversation" panel titles
- giant metadata pills for ref/event count
- stacked horizontal stripes serving the same purpose
- empty-state regions larger than the composer/action area

Header rules:

- top-level metadata must be written in operator-facing terms, not internal
  schema terms
- labels like `Agent` and `Source` are not acceptable if they do not explain
  role
- assignment and origin must be distinguishable when both matter
- event counts may only remain visible if rendered as an obvious action
- reference IDs must not occupy primary visual hierarchy
- low-frequency diagnostic metadata must move behind progressive disclosure
- the operator must be able to tell, at a glance:
  - who this conversation is with
  - whether work was routed and to whom
  - current status
  - what action is available next
- delegated conversations must make the relationship explicit:
  - `With M1`
  - `Assigned to M2`
  - `Started in registry`
  rather than generic schema labels
- if an activity count is shown at all, it must be rendered as an action, not a
  decorative fact
- raw ids may only appear behind progressive disclosure, never in the primary
  metadata row
- vertical rhythm must stay tight:
  - no oversized gap between title and metadata
  - no oversized gap between metadata and tabs
  - no oversized gap between tabs and primary content
- sparse conversations must collapse vertically instead of reserving a large
  empty viewport-shaped panel

### Tasks

Must contain:

- compact task-state filters
- dense structured task presentation
- clear action affordances
- human-readable task summaries that expose the result/outcome directly when the
  task is complete

Must not contain:

- large tutorial copy
- empty lanes dominating the route
- duplicated representations of the same task
- clumsy list-box filters for small finite state sets
- raw conversation ids or raw routed target ids in primary row metadata

### Dashboard

Must contain:

- immediate status at a glance
- clear intervention queue
- dense summaries of active work

Must not contain:

- slide-deck prose
- oversized preview cards
- decorative sections without action value
- large empty cards that say little and do nothing

Empty-state rules:

- collapse or combine quiet sections instead of rendering a grid of mostly empty
  boxes
- `View all` must not dominate sections that have little or nothing to show
- empty and quiet states must still feel intentional, not like unfinished
  scaffolding

### Agents

Must contain:

- dense roster
- health/status
- immediate conversation start/open action

Must not contain:

- detours for the common "talk to this bot" action

Metadata rules:

- agent name and current state are primary
- provider/model/slug style metadata is secondary
- supporting metadata should be quiet or progressively disclosed
- supporting metadata must never compete with the primary action

### Capabilities

Must contain:

- compact route shell aligned to the shared workspace system
- clear capability rows with direct enable/disable action
- concise explanation only if it changes operator action

Must not contain:

- title + subtitle + tiny floating empty sentence over a huge blank field
- legacy page-header styling that ignores the shared redesign system

Empty-state rules:

- if no capabilities exist, the route must still feel composed and actionable
- empty messaging must be anchored to the route shell and aligned correctly

### Skills

Must contain:

- dense catalog rows
- clear primary install/uninstall action
- search that stays visually subordinate to the list itself

Must not contain:

- scattered title/subtitle/hint text that reads like UI litter
- loose vertical spacing that makes the catalog feel unfinished
- install actions visually detached from the skill they act on

Catalog rules:

- skill name is primary
- description is secondary
- install/uninstall is the clear action
- helper text like `Shortcut: /` must be quiet, compact, and only present if it
  genuinely improves use

### Guidance

Must contain:

- one clear provider context
- one clear lifecycle/status presentation
- direct draft/preview/publish actions

Must not contain:

- duplicated status rendering like `Status: published` plus `PUBLISHED`
- generic page-header chrome that is louder than the actual editor

Status rules:

- status must be rendered once at the primary hierarchy level
- supporting lifecycle context may appear secondarily if it changes action
- provider and status context must be compact, quiet, and aligned

### Approvals

Must contain:

- queue-oriented list
- direct action buttons
- minimal explanatory chrome

### Usage

Must contain:

- truthful rollup semantics
- compact summary + table

Must not contain:

- large explanatory blocks to justify basic numbers

## Visual system target

Define and apply one design system before route-by-route polish.

Required primitives:

- spacing scale: `4, 8, 12, 16, 24, 32, 48`
- typography roles:
  - page title
  - section title
  - body
  - meta
  - mono/meta
- surfaces:
  - base
  - panel
  - subtle
- controls:
  - primary button
  - secondary button
  - ghost button
  - status chip
  - segmented control
  - inline quick-action chip
- status tokens:
  - open
  - running
  - waiting
  - done
  - warning
  - failed
- shell primitives:
  - left rail
  - mobile drawer
  - route content shell
  - empty-state row/shell

Rules:

- IDs and event counts are text, not oversized pills
- chips are for status or compact quick actions only
- borders and separators do more work than extra background panels
- shadows are subtle
- radii are moderate
- empty-state styling is smaller and quieter than active content
- empty-state text alignment is part of the primitive, not left to per-route
  improvisation
- Phase 0 must produce concrete implemented values for all token categories
- later phases may only consume the Phase 0 system, not extend it ad hoc
- the old token system must be removed or rewritten during Phase 0, not kept
  alive beside the new one

## Execution plan

Status language is strict:

- a phase is either complete or incomplete
- there is no "mostly done"
- there is no "dominant path"
- no phase closes while any required route still violates its exit criteria

### Phase 0: Build the redesign foundation

Implement:

- rewrite shared layout and visual-system tokens in
  [ui/css/main.css](/Users/tinker/output/bots/telegram-agent-bot/ui/css/main.css)
- define shared primitives for:
  - headers
  - compact metadata rows
  - segmented controls
  - quick-start chip rows
  - compact empty states
  - dense list rows
  - pinned composer shells
  - route shell and mobile drawer behavior
- define concrete implemented values for:
  - spacing
  - typography roles
  - surface palette
  - status colors
  - border and shadow primitives
  - control styles
  - both light and dark themes
- remove or rewrite the old token system instead of layering a new one on top
- verify accessibility primitives as part of the system:
  - focus treatments
  - keyboardable tab/filter patterns
  - contrast
  - reduced-motion support
- unify shell state handling so mobile nav uses one working state model instead
  of conflicting classes

Rules:

- no Phase 1 work may begin before Phase 0 is complete
- no interleaving between Phase 0 and Phase 1
- Phase 0 must be committed and reviewed before any route rebuild starts
- no component may introduce local visual tokens after Phase 0 begins

Exit criteria:

- one shared design language exists in code
- the old token system no longer exists as a competing layer
- a complete concrete token system exists in code for both themes
- accessibility primitives are present in the shared system
- no new route work is done on ad hoc local styling
- Phase 0 is reviewed and frozen before Phase 1 begins
- mobile drawer/rail behavior works from the shared shell

### Phase 1: Redesign conversation detail from scratch

Implement:

- rebuild
  [ui/js/components/conversation-detail.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/conversation-detail.js)
  around a single workspace model
- delete and rewrite the component if the existing structure blocks the target
  layout; do not preserve a bad DOM/component tree out of convenience
- flatten header into one calm band
- remove redundant panel headers
- replace loud metadata pills with quiet inline metadata
- make the empty state compact and composer-first
- make `Conversation`, `Tasks`, and `Full activity` feel like variants of one
  system
- make `Full activity` dense and log-like
- ensure `Conversation` includes `delegation.submitted`
- ensure `Tasks` does not duplicate the same work
- remove fixed oversized quiet-state geometry so sparse conversations collapse
  to the content instead of reserving a mostly empty viewport-tall panel
- rewrite routed-work milestone cards in `Conversation` so they:
  - use operator phrasing
  - do not leak raw IDs
  - do not concatenate task title, target, and status into unreadable strings
  - do not repeat the same status in label, summary, and body
  - surface the actual delegated outcome/result inline when work completes
  - never require expansion just to learn the answer/result of a completed task
- ensure delegation target labels always resolve to one human-facing target
  label in primary UI; raw fallback ids may not appear in milestone summaries
- dedupe `@` target suggestions so one agent appears once in the suggestion
  list, with aliases handled as secondary matching metadata rather than
  duplicate rows
- make desktop and mobile layouts deliberate, not incidental

Header constraints:

- desktop top chrome may contain only:
  - one title/action row
  - one metadata row
  - one tabs row
- no additional subtitle, panel-header, or redundant context row may appear
  above primary content
- total top chrome before primary content must not exceed `144px` on desktop at
  normal zoom
- metadata must fit in one row on desktop and at most two wrapped rows on
  mobile

Exit criteria:

- no stacked redundant horizontal bands remain
- no large dead empty pane dominates the route
- `Ref ...` and `0 events` are quiet metadata, not visual objects
- sparse conversation pages collapse vertically and use width efficiently
- delegated conversations clearly distinguish:
  - who the conversation is with
  - where it started
  - who current routed work is assigned to
- routed-work milestones in `Conversation` read as human events, not raw event
  payloads
- completed delegated work shows the outcome/result inline in the default
  Conversation view
- no raw internal id appears in visible milestone/header text when a
  human-facing label exists
- `@` suggestion rows are unique per target and read like clear actions, not
  duplicate aliases
- `Conversation`, `Tasks`, and `Full activity` all look intentionally related
- the route is elegant on desktop and usable on mobile

### Phase 2: Redesign Conversations index as a start/resume surface

Implement:

- rebuild
  [ui/js/components/conversation-list.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/conversation-list.js)
  into:
  - compact quick start
  - compact filters/search
  - dense conversation list
- remove essay copy and oversized empty states
- make connected-agent start actions compact and scalable

Exit criteria:

- dozens of connected agents still fit gracefully
- no billboard quick-start buttons remain
- empty states are compact and unobtrusive
- start/resume work is immediate from this route
- empty-state text is aligned correctly
- quick-start controls unmistakably read as controls

### Phase 3a: Redesign Dashboard and Tasks

Implement:

- rebuild
  [ui/js/components/dashboard.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/dashboard.js)
- rebuild
  [ui/js/components/task-list.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/task-list.js)

Required changes:

- compact operational density
- reduced explanatory copy
- no giant empty-state slabs
- segmented controls/chips where finite state filters make sense
- remove raw conversation-id leakage from task row metadata
- ensure filtered/quiet task states collapse cleanly without a thin orphan row
  over a large dead canvas

Exit criteria:

- the dashboard feels operational, not tutorial-like
- Tasks does not feel like an admin board demo
- quiet-state dashboard does not collapse into a grid of empty cards
- no thin orphan strips or misaligned empty-state text remain
- no task primary row leaks raw conversation ids or internal target ids
- completed task rows expose the useful outcome without drill-in when feasible

### Phase 3b: Redesign Agents, Approvals, Usage, Capabilities, Skills, and Guidance

Implement:

- rebuild
  [ui/js/components/agent-list.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/agent-list.js)
- refine or rewrite
  [ui/js/components/agent-detail.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/agent-detail.js)
  if the existing structure blocks the target layout
- rebuild
  [ui/js/components/approval-list.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/approval-list.js)
- refine or rewrite
  [ui/js/components/usage-view.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/usage-view.js)
  if the existing structure blocks the target layout
- rebuild
  [ui/js/components/capability-list.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/capability-list.js)
- rebuild
  [ui/js/components/skill-catalog.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/skill-catalog.js)
- rebuild
  [ui/js/components/guidance-editor.js](/Users/tinker/output/bots/telegram-agent-bot/ui/js/components/guidance-editor.js)

Required changes:

- compact operational density
- reduced explanatory copy
- no giant empty-state slabs
- direct conversation start/open from Agents
- usage semantics remain truthful and visually restrained
- legacy admin/support routes must adopt the same redesign system as the core
  work routes
- no duplicated status copy or ambient shortcut litter
- empty states on admin/support routes must be composed and aligned

Exit criteria:

- these routes look like one product, not local exceptions
- Agents exposes direct start/open conversation action cleanly
- Approvals is queue-oriented, dense, and action-first
- Usage is compact, truthful, and visually restrained
- Capabilities, Skills, and Guidance no longer look like legacy scaffold pages
- `Shortcut: /` and similar hints are quiet and justified or removed
- status is not duplicated in both prose and badge form

### Phase 4: Complete reconciliation adoption

Implement:

- audit every operator-facing screen
- remove remaining normal-flow full rebuilds
- ensure all success/update paths use the existing `UI.reconcileChildren`
  wrapper over `morphdom`

Required routes:

- conversation detail
- conversation list
- task list
- dashboard
- agent list
- agent detail
- approval list
- usage

Exit criteria:

- no operator-facing success/update path clears and rebuilds a whole section
- only first-load skeleton and fatal error states may do full clears

### Phase 5: Complete interaction polish

Implement:

- contextual `@` assist only when relevant
- compact ambiguity/no-match UI
- coherent action placement
- keyboard and touch behavior review
- responsive review adjustments

Exit criteria:

- no always-on routing banner in idle composer
- target assist is discoverable and quiet
- mobile interaction feels intentional, not merely tolerated

### Phase 6: Strengthen tests and smoke to match the redesign

Implement:

- update existing tests to reflect final semantics
- extend
  [docs/registry-ui-screenshots/live_registry_smoke.spec.js](/Users/tinker/output/bots/telegram-agent-bot/docs/registry-ui-screenshots/live_registry_smoke.spec.js)
  for the final UX
- add no new one-off vanity tests

Required smoke coverage:

- conversation detail has one compact header system
- metadata is rendered as quiet inline text, not oversized pills
- conversation header metadata is understandable and actionable
- delegated conversation header clearly distinguishes `With`, `Assigned to`, and
  origin context when relevant
- `delegation.submitted` appears in Conversation
- `delegation.submitted` and `task.status` render as human-readable milestones,
  not raw task-field dumps
- completed delegated work shows its useful result in Conversation without
  expanding raw diagnostic detail
- Tasks and Full activity have correct distinct semantics
- Conversations quick-start is compact and direct
- Conversations quick-start controls read as controls and scale to many agents
- `@` suggestion results are unique per target and do not duplicate alias rows
- Agents can start/open conversation directly
- Agents keeps supporting metadata secondary to primary action
- composer remains visible
- mobile viewport coverage passes
- dark theme coverage passes
- desktop review passes
- mobile review passes
- segmented-control keyboard navigation passes
- `Full activity` behavior is explicitly verified
- keyboard navigation and focus behavior pass on the redesigned controls
- both light and dark themes pass review
- mobile drawer open/close behavior is explicitly verified
- empty-state alignment is explicitly verified on quiet routes
- sparse conversation and filtered-list routes are explicitly checked for
  collapsed height and absence of oversized dead space
- raw internal ids are not present in primary task/conversation summaries
- Capabilities, Skills, and Guidance routes are included in smoke/visual review
- no duplicated status rendering ships on Guidance

Exit criteria:

- the specific regressions that shipped in the failed pass are locked out by
  tests and live smoke

### Phase 7: Private visual review and promotion

Verification sequence:

1. full repo tests
2. disposable Docker smoke
3. private desktop visual review
4. private mobile visual review
5. iterate until the UI is calm, elegant, and coherent
6. commit
7. push
8. clean rebuild and redeploy `/Users/tinker/octopus`
9. review live deployed desktop UI
10. review live deployed mobile UI

Exit criteria:

- disposable-stack UI is elegant and coherent
- live deployed UI matches disposable-stack quality
- no route still exhibits the failed-pass symptoms

## Hard exit criteria

The redesign is not done until **all** of the following are true:

1. No operator-facing route contains oversized decorative empty states.
2. No conversation route contains redundant stacked header bands.
3. Metadata like reference IDs and event counts are visually quiet and aligned.
4. `Conversation`, `Tasks`, and `Full activity` are distinct, coherent, and
   intentionally styled.
5. `delegation.submitted` is visible in the default Conversation tab.
6. Delegated-work milestones in `Conversation` are human-readable and do not
   leak raw task IDs or concatenated schema fragments.
7. Conversations quick-start scales cleanly to many agents.
8. Agents surfaces expose direct start/open conversation actions.
9. Dashboard, Tasks, Approvals, Agents, Usage, and Conversations share one
   design language.
10. Capabilities, Skills, and Guidance also share that same design language.
11. No normal operator update path uses a full redraw.
12. Desktop layout uses width effectively without wasted slabs.
13. Mobile layout is intentionally designed and verified.
14. The mobile drawer works reliably.
15. Light and dark themes are both intentionally designed and verified.
16. Tabs, controls, focus handling, and reduced-motion behavior remain
    accessible and usable.
17. Spacing, typography, surface treatment, and controls are consistent across
    all redesigned operator routes.
18. No orphaned decorative pills, stripes, redundant panel layers, or floating
    empty-state sentences remain.
19. No duplicated status/helper copy litters the UI.
20. No operator-facing header, row, milestone, or suggestion list leaks raw
    internal ids when a human-facing label exists.
21. Completed delegated work is understandable from the default Conversation
    view without requiring the operator to expand raw diagnostic detail.
22. `@` routing suggestions contain one visible row per target, not duplicate
    alias rows.
23. Private browser review confirms the product is calm, fluent, and elegant.
24. The live deployed octopus stack matches the reviewed build.

If any one of these is false, the redesign is incomplete.

## Non-goals

- fuzzy backend routing
- adding new top-level routes just to hide design problems
- leaving partial visual migrations in place
- keeping old panel structure and merely repainting it
- shipping because tests pass while the UI still looks wrong

## Developer prompt

```text
Redesign the Octopus registry operator UI from first principles on top of the
existing protocol/backend foundation.

Read first:
- PLAN-task-protocol.md
- ui/css/main.css
- ui/js/components/conversation-detail.js
- ui/js/components/conversation-list.js
- ui/js/components/task-list.js
- ui/js/components/dashboard.js
- ui/js/components/agent-list.js
- ui/js/components/agent-detail.js
- ui/js/components/approval-list.js
- ui/js/components/usage-view.js
- ui/js/components/capability-list.js
- ui/js/components/skill-catalog.js
- ui/js/components/guidance-editor.js
- ui/js/helpers/ui.js
- docs/registry-ui-screenshots/live_registry_smoke.spec.js

Current baseline:
- the last failed UX pass has already been reverted
- do not restore or patch that failed design
- rebuild the operator product cleanly from this reverted baseline

What failed last time:
- local compression instead of a real redesign
- reused old panel structure and merely changed styling
- metadata pills were louder than content
- route-specific tweaks created an inconsistent product
- tests/smoke were treated as enough while visual quality was not

Design target:
- sleek operator console
- dense but calm
- action-first
- progressively discoverable
- one design language across all operator routes
- one design language across work routes and admin/support routes
- minimal explanatory prose
- quiet metadata
- compact empty states
- no stacked decorative panel layers
- no floating, misaligned empty-state sentences

Non-negotiables:
- no "mostly done"
- no partial morphdom migration
- no oversized pills for IDs or event counts
- no billboard quick-start controls
- no giant empty states
- no redundant conversation header stripes
- no route that still looks like an admin scaffold
- no duplicated status prose plus badge when it says the same thing
- no broken mobile drawer
- no desktop-only success that falls apart on mobile
- no promotion until disposable-stack and live deployed UI both pass visual
  review

Implementation order:
1. build the shared visual/layout system
2. redesign conversation detail from scratch
3. redesign conversations index as compact start/resume surface
4. redesign tasks, dashboard, agents, approvals, and usage to match
5. finish morphdom adoption on every operator-facing success/update path
6. finish interaction polish and responsive behavior
7. strengthen smoke/tests for the failed regressions
8. run full verification
9. promote only after private desktop and mobile review both pass

Done means every hard exit criterion in PLAN-task-protocol.md is true.
```
