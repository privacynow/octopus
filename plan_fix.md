**Protocol Authoring Recovery Plan**

This plan fixes the structural problem, not just the renderer symptoms.

The target is:

- `Process` = orient
- `Detail` = build/edit
- `Map` = inspect/advanced

The current failure is that the product is still renderer-led:
- process cards
- mobile compact
- desktop graph

That has to end. The product needs one editing surface with one mental model across desktop and mobile.

## 1. North Star

### 1.1 Product principles
- Visual editing stays, but graph-first editing does not.
- The primary editing contract is structured workflow editing, not a node-edge canvas.
- Desktop and mobile share one editor semantics; only layout changes.
- Viewport width must never decide whether the user gets a different product.
- Ordinary authoring must work without opening `Map`.
- `Map` is optional and advanced, not required.

### 1.2 Success bar
A non-technical user should be able to:
- open a workflow
- understand where they are
- add a role
- add a step
- add a route
- edit a step
- understand selector assignment
- validate/publish

without needing the graph to rescue them.

## 2. Locked Decisions

### 2.1 Canonical data model
Keep:
- one `draft.document`
- one save/autosave/conflict path
- one selector model shape
- one projection pipeline
- one run/rehearsal model

Do not add:
- a second protocol model
- a persisted phase model in this pass
- alternate save APIs
- viewport-specific authoring data paths

### 2.2 Surface model
The only workflow surfaces are:
- `Process`
- `Detail`
- `Map`

### 2.3 Segment/phase rule
For this pass:
- top-level “phases” are current derived projection segments
- this is presentation vocabulary, not a new persisted domain concept
- if the business later needs authored phases, that is a separate model change

### 2.4 Editing authority
- `Detail` is the primary editing surface
- `Map` is optional advanced inspection/manipulation
- ordinary route authoring must be possible in `Detail`
- `Map` may offer advanced connect as a shortcut, but never as the only path

## 3. Product Architecture

## 3.1 Process
Purpose:
- orient the user
- show major workflow sections
- let the user drill in

Must show:
- section/segment name
- owner summary
- step count
- branch/outcome summary
- run status summary in rehearsal mode

Must not show:
- graph edges
- dense lifecycle/editor chrome
- full editing controls

## 3.2 Detail
Purpose:
- primary editing surface
- everything an ordinary user needs to build and maintain the workflow

Must support:
- role creation/editing
- step creation/editing
- route creation/editing
- artifact assignment
- selector assignment
- rehearsal context

Desktop and mobile:
- same information
- same actions
- same user flow
- only layout differs

## 3.3 Map
Purpose:
- inspect topology
- scan the whole workflow
- perform optional advanced visual operations

Must be:
- explicit
- secondary
- clearly labeled as advanced/visual map

Must not be:
- the default drill-in editor
- required for normal authoring

## 4. Surface Defaults

Lock the defaults now so they do not drift.

### 4.1 Empty protocols
- default surface: `Detail`
- current task: `create-role`
- graph/map hidden by default

### 4.2 Small protocols
Suggested lock:
- if `0 stages`: `Detail`
- if `1-5 stages` and `<= 1 segment`: `Detail`
- do not force `Process`

### 4.3 Larger protocols
Suggested lock:
- if `>= 6 stages` or `> 1 segment`: `Process`

### 4.4 Map
- never default
- explicit user action only

## 5. Authoring Task Model

Do not introduce another uncontrolled mode axis.

### 5.1 Explicit surfaces
Persist only:
- `workspaceSurface = process | detail | map`

### 5.2 Selection
Keep:
- selected segment
- selected role
- selected step
- selected route

### 5.3 Task state
`authoringTask` should be derived from:
- `workspaceSurface`
- `selection`
- `editorMode`

It should not become another independent long-lived state machine unless necessary.

### 5.4 Allowed tasks
Inside `Detail`, tasks are:
- `create-role`
- `edit-role`
- `create-step`
- `edit-step`
- `create-route`
- `edit-route`
- `review`
- `rehearse`

### 5.5 Existing `editorMode`
Rationalize it instead of duplicating it.

Target:
- `editorMode` survives only for short-lived interaction substates
- examples:
  - `create-role`
  - `create-step`
  - `create-route`
  - `rehearse`
  - optional `map-connect`

Do not keep:
- one task model in `Detail`
- and a second unrelated insert/connect system beside it

## 6. Process Surface Contract

## 6.1 Content
Each segment card shows only:
- title
- owner summary
- step count
- branch/outcome summary
- “Open detail” action
- optional rehearsal status

### 6.2 Actions
Allowed:
- open detail
- open map
- add role
- add segment entry step if needed
- global validate/publish via compressed header

Not allowed:
- full step editing
- route editing
- graph controls

### 6.3 Mobile/Desktop
Desktop:
- rail or grid
Mobile:
- vertical stack/timeline

Same semantics, different arrangement.

## 7. Detail Surface Contract

This is the heart of the fix.

## 7.1 Core structure
For a selected segment:
- segment header
- ordered step flow
- selected entity editor
- contextual actions only

### 7.2 Step flow
The main content is a structured flow of step cards, not a graph.

Each step card shows:
- name
- owner role
- kind
- route summary
- input/output summary
- local status/rehearsal signal if applicable

### 7.3 Selection behavior
- click step -> select step and open step editor
- click route summary -> select route and open route editor
- click role indicator -> open role editor if applicable

No hidden modes. No click should silently switch product behavior.

## 7.4 Editor pane
Selected entity opens a contextual editor:
- step editor
- role editor
- route editor

Desktop:
- sticky side panel

Mobile:
- stacked panel below the flow
- optionally accordion/bottom-sheet behaviors if they simplify interaction

## 7.5 Step editor sections
Keep one editor shell, but finish it properly:
- Basics
- Instructions
- Artifacts
- Routing
- Advanced

Rules:
- `Routing` is first-class and practical
- `Artifacts` and `Advanced` collapse when not needed
- `Basics` and `Routing` are always easy to reach

## 8. Routing Rules

This is one of the biggest missing pieces.

## 8.1 Routing must work in Detail
All ordinary route creation and editing must work in `Detail`.

That includes:
- intra-step routing
- cross-step routing within segment
- cross-segment routing
- terminal outcomes

## 8.2 Route editing rules
For a selected step, `Routing` must show:
- existing outgoing routes
- decision label
- target label
- target type:
  - same segment step
  - different segment step
  - terminal outcome

### 8.3 Cross-segment routing
Do not leave this vague.

Lock:
- cross-segment routes are created and edited in `Detail`
- targets from other segments appear in grouped pickers:
  - “This section”
  - “Other sections”
  - “Finish outcomes”

### 8.4 Map routing
Allowed:
- advanced connect gesture
- advanced topology changes

Not allowed:
- being the only place to connect normal routes

## 9. Rehearsal Behavior

Rehearsal must become part of the same product, not a bolt-on.

## 9.1 Process in rehearsal
Show:
- macro progress
- which segment is active or blocked
- high-level state chips

## 9.2 Detail in rehearsal
Show:
- step execution state inline on step cards
- current step / blocked step / completed step
- rehearsal actions or context in the selected step area
- fields disabled where appropriate

This is the primary rehearsal editing/observation surface.

## 9.3 Map in rehearsal
Show:
- advanced visual state overlay
- optional full topology status

Not required for ordinary rehearsal comprehension.

## 10. Header and Chrome Compression

The current top-heavy layout is a structural issue.

## 10.1 Authoring header rules
Visible on first paint:
- protocol name
- save/conflict state
- one compact primary action group

Move to overflow:
- slug editing
- archive
- discard
- less-common lifecycle actions
- secondary admin controls

### 10.2 Page header rules
On authoring route:
- remove or drastically collapse marketing/admin intro copy
- workflow content must appear near the top immediately

### 10.3 Height budget
Lock a UI budget:
- mobile first meaningful workflow content visible within first viewport
- desktop workflow content should begin without requiring the user to scroll past an admin wall

## 11. Selector UX Redesign

This needs a real product treatment.

## 11.1 Principle
Picker-first, manual override second.

### 11.2 Data sources
Lock the source of options before implementation.

- `agent`
  - source: existing registry/connected agent data
- `skill`
  - source: manifest/catalog/registry-backed known skills, whatever is already authoritative in the product
- `role`
  - source: curated manifest-backed options or an explicit small in-repo taxonomy for this pass

If a source does not exist, define it before building the UI.

### 11.3 Control behavior
If `selector_kind = agent`
- primary control: searchable agent picker
- secondary: preview
- advanced: manual override

If `selector_kind = skill`
- primary control: searchable skill picker
- secondary: preview
- advanced: manual override

If `selector_kind = role`
- primary control: searchable role/archetype picker
- secondary: preview if applicable
- advanced: manual override

### 11.4 Shared kit boundary
Do not fork selector UX across call sites.

Create one shared selector control path, for example:
- `Kit.selectorField`
or equivalent shared module

Use it in:
- role creation
- participant editing
- anywhere else selector authoring appears

## 12. Detail vs Compact Reuse

Do not “rename compact to Detail.”

That would be another shortcut.

Correct rule:
- reuse visual patterns and primitives from compact
- do not treat compact as the Detail implementation
- build `Detail` as its own shell using:
  - same projection
  - same selection
  - shared card primitives
  - shared editor primitives

## 13. Map Strategy

Do not let `Map` balloon.

## 13.1 Map v1
Phase 1 Map goal:
- take the current graph experience
- move it behind an explicit advanced entry
- make sure it is not needed for normal work

No promise yet of perfect diagramming.

## 13.2 Map v2
Only after structural recovery:
- routing/layout polish
- better fit/pan/zoom
- improved collision handling
- richer expert connect/edit affordances

This splits relocation from polish and keeps scope sane.

## 14. Undo, Conflict, Revision

These are not optional.

## 14.1 Undo/redo
- `Detail` must preserve undo/redo semantics
- step edits, role edits, route edits all participate in the same draft history

## 14.2 Conflict state
- conflict must still block validate/publish/archive/rehearse where appropriate
- conflict message must be visible in `Detail`
- reloading or overwrite-after-reload must still work from the primary editing surface

## 14.3 Save state visibility
Save/conflict state must remain obvious without dominating the screen.

## 15. Consolidation Strategy

This is where “single path” must become true again.

## 15.1 What stays
- one canonical document
- one save/conflict pipeline
- one projection system
- one selector shape
- one rehearsal pipeline

## 15.2 What changes
- `focus` stops meaning “graph editor”
- `focus` becomes `Detail`
- `full graph` becomes `Map`
- viewport width stops deciding editing product

## 15.3 What gets deleted
After migration:
- width-based authoring product fork
- desktop `focus -> graph` as the default drill-in editor
- mobile `focus -> compact` as a separate editing product
- stale toolbars and CSS that only exist for those branches
- tests asserting the old behavior

## 16. Implementation Phases

## Phase A: Contract and state freeze
Work:
- define `workspaceSurface = process | detail | map`
- define exact default-entry rules
- define selection model
- define routing authority in `Detail`
- define Map authority as advanced only
- define selector data sources
- define rehearsal behavior per surface

Acceptance:
- all structural decisions above are locked before UI churn

## Phase B: Shell compression
Work:
- compress lifecycle/header
- remove or collapse admin intro copy on authoring route
- move secondary actions to overflow
- keep save/conflict visible

Acceptance:
- first meaningful workflow content appears quickly on both mobile and desktop

## Phase C: Build Detail v1
Work:
- create step-flow based `Detail`
- same semantics for desktop and mobile
- responsive layout only
- route summaries inline
- contextual editor pane
- no dependency on graph for normal edits

Acceptance:
- desktop and mobile drill-in feel like the same product

## Phase D: Route editing in Detail
Work:
- route list/editor for selected step
- cross-segment route target selection
- terminal target selection
- route create/edit/delete from `Detail`

Acceptance:
- no ordinary route operation requires `Map`

## Phase E: Role and step creation flows
Work:
- progressive `create-role`
- progressive `create-step`
- land in contextual editor after creation
- reduce toolbar noise during create flows

Acceptance:
- creation feels guided, not busy

## Phase F: Selector redesign
Work:
- shared selector field primitive
- picker-first controls
- advanced manual override
- integrated preview

Acceptance:
- selector authoring is intuitive

## Phase G: Rehearsal alignment
Work:
- `Process` shows macro state
- `Detail` shows local execution state and disabled fields
- `Map` optional overlay

Acceptance:
- rehearsal feels native to the same product

## Phase H: Move graph to Map
Work:
- current graph becomes explicit `Map`
- clear entry/exit
- label as advanced/system view

Acceptance:
- graph still available, but not primary

## Phase I: Map polish
Work:
- only after H is stable
- improve graph quality if still needed

Acceptance:
- Map is valuable for experts, but not blocking sellability of authoring

## Phase J: Cleanup and deletion
Work:
- remove dead branches
- remove width-based editor product split
- remove stale CSS/JS/tests
- keep one coherent authoring story

Acceptance:
- code and product no longer describe two or three competing editors

## 17. Testing Strategy

Do not keep browser truth in ephemeral-only locations.

## 17.1 Stable test location
Move or maintain authoritative browser tests in committed stable locations under `tests/` or another stable repo-owned path, not `.tmp` as the canonical source of truth.

`.tmp` can remain a scratch area, not the contract.

## 17.2 Acceptance fixtures
Must cover:
- blank draft
- small workflow
- medium branching workflow
- Software Engineering template
- selector flows
- rehearsal flows

## 17.3 Required browser flows
- large workflow opens in `Process`
- segment opens `Detail`
- small workflow opens `Detail`
- create role
- create step
- create route
- edit route
- selector skill picker
- selector agent picker
- conflict block/reload/overwrite
- rehearsal in `Detail`
- explicit `Map` open

## 17.4 Screenshot gates
Desktop and mobile:
- Process
- Detail
- Map
- selector picker
- blank authoring
- medium workflow
- Software Engineering

## 17.5 Explicit ship blockers
Do not ship if:
- desktop and mobile Detail are different products
- graph is still required for normal route editing
- selector still defaults to raw text
- top chrome still dominates the viewport
- creation is still busy and non-progressive
- conflict/revision handling regresses
- rehearsal only feels correct in Map

## 18. Risks and Mitigations

### 18.1 Migration shock
Risk:
- users relied on direct graph connect

Mitigation:
- keep `Map` available early
- provide explicit “Open map” affordance during transition
- keep route creation in Detail clearly better, not merely different

### 18.2 Scope creep
Risk:
- trying to perfect Map while rebuilding Detail

Mitigation:
- split Map relocation from Map polish
- sellable authoring depends on Process + Detail first

### 18.3 Selector source gaps
Risk:
- no authoritative options list for skills/roles

Mitigation:
- define source contracts first
- if necessary, start with curated authoritative lists rather than fake completeness

### 18.4 State explosion
Risk:
- `workspaceSurface`, `editorMode`, `selection`, `authoringTask`, `rehearse`

Mitigation:
- derive task state
- keep only necessary persistent state

## 19. Definition of Done

The work is done when:

- `Process` is the calm orienting surface for larger workflows
- `Detail` is the one primary editing surface on desktop and mobile
- `Map` is explicit and advanced
- route authoring works in `Detail`, including cross-segment routes
- selector authoring is picker-first and understandable
- header/admin chrome no longer overwhelms the workflow
- creation flows are progressive
- rehearsal feels native in `Detail`
- width no longer decides which editing product the user gets
- old competing detailed-editor paths are removed
- the product can be shown without apologizing for how it works

