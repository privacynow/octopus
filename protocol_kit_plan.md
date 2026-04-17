# Protocol UX + Authoring Kit Plan

_Status: draft for review. Supersedes `protocol_plan.md` and `new_protocol_plan.md` as the canonical forward direction._

## 1. Context

The registry has three authoring surfaces — **protocols**, **skills**, **guidance** — plus observability surfaces (**agents**, **conversations**, **runs**, dashboards). Each authoring surface was built in isolation and invented its own chrome: its own lifecycle strip, its own draft-state chip, its own review tab, its own input helpers, its own destructive-action dialect. The three sit next to each other on the same site without sharing a design language.

The most advanced of the three — protocols — is also the most compromised. It is implemented as a **settings form over a JSON document** (section tabs, inspector panels, a CSS-grid pseudo-diagram, raw-JSON editor). That is the wrong product shape for a workflow graph: authors think in terms of participants, stages, and transitions, not in terms of editing `stage_kind` fields. Consequence: leaked Pydantic errors, server-seeded placeholder values (`"Untitled Protocol"`, `"protocol-2"`) sitting in inputs as real content, implementation-term labels (`strict_completion`, `require_output_verification`) exposed to users, built-in example protocols mixed into the authored catalog, and a parallel `/ui/protocol-runs` page for "operating" a run that is neither usable from Telegram nor from agent conversations nor from future bots.

At the same time, the SDK layer has quietly converged on a coherent substrate: bots enroll, bots mirror conversations, bots route tasks, and the protocol engine already dispatches stages via the same routed-task framework that powers direct delegation. The shape is right underneath; the UI on top has not caught up.

This plan commits to the product shape that follows from the substrate:

- **Protocols is the flagship authoring experience**, built canvas-first, on a shared authoring kit.
- **Operation of runs is not a protocol-UX feature.** It is an SDK capability rendered by whichever bot surface the user is in — Telegram, agent conversation, registry web, future bot.
- **The kit is extracted first for protocols, migration of skills/guidance is deferred but committed-to** with a manifest, a checklist, and an acceptance gate.
- **No parallel code paths, no backward-compat shims.** Replace the old shape; the kill list is enforced.

## 2. Problem statement

Today's registry UX fails four product tests simultaneously:

1. **Wrong metaphor for protocols.** The primary surface is CRUD over a JSON document. A protocol is a workflow graph; authors need direct manipulation, live feedback, and rehearsal. The current surface provides none of those.

2. **Invocation and observation are not poly-surface.** "Run a protocol" is implemented directly against the registry's HTTP. Telegram bots have to reinvent the path; agent conversations have no sanctioned path at all; future bots will drift. The `/ui/protocol-runs` page is the registry's privileged operate screen, which makes the registry look like the home of operation even though the substrate is cross-surface.

3. **No shared design language.** Skills (2,279 LOC), guidance (662 LOC), protocols (3,097 LOC) each own their own chrome. Every change has to be made three times; consistency drifts monotonically.

4. **Implementation leaks into product.** Pydantic validation text, server-side defaults presented as user values, domain keys as UI labels, built-in examples mixed with authored records, a pseudo-diagram that cannot be arranged, inspector forms as the only editing surface. Non-technical authors cannot use it; technical authors tolerate it; nobody prefers it.

The fix is not a list of patches. It is a product shape — enforced by a shared kit — that all three authoring surfaces inhabit.

## 3. Discoveries (verified in code)

### 3.1 The SDK substrate is already coherent

Confirmed present in `octopus_sdk`:

- `RegistryParticipant`, `RegistryConversationMirror`, `RegistryCoordination`, `RegistryDiscovery`, `RegistryParticipantHealth`, composed by `RegistryParticipantImplementation`.
- `ConversationProjectionPort` with a real `NoOpConversationProjection` fallback.
- `TaskRoutingPort`, `RoutedTaskRequest`, formal state machines for routed tasks and delegated tasks in `task_protocol.py`.
- `ProtocolRunEngine` in `octopus_sdk/protocols/engine.py` produces `RoutedTaskRequest` with IDs of the form `protocol-stage:{stage_execution_id}`.

### 3.2 Protocol stages already ride the task framework

Not a plan — a fact.

- `protocols/engine.py::build_dispatch_request` emits the routed task.
- `octopus_registry/store_shared/routed_tasks.py` writes events to both the origin conversation and the **recipient conversation** (`recipient_conversation_id` + `recipient_inserted_events`).
- `octopus_registry/server.py::_broadcast_task_record_events` fans those out over WebSockets.
- `octopus_registry/server.py::_protocol_run_id_from_task_record` recognizes `protocol-stage:*` task IDs so the broadcast picks up the protocol context.

Consequence: the receiving agent's conversation state in the registry is updated in real time when it receives and completes a protocol stage — same way tasks work. One dispatch path, no parallelism. Test coverage should make this explicit (see Step 2).

### 3.3 Agents are enrollment-sourced and admin-editable

The registry's agent identity (authority, slug, advertised skills, trust tier, transport descriptor) comes from `RegistryParticipant.enroll`, driven by the bot. Hand-editing those declared fields in the UI would lie to the system.

However, **the registry UI is also the admin/management surface, like the Octopus CLI.** Trust tier, capacity, token rotation, skill grants/revocations, connectivity control, and lifecycle actions are legitimate admin operations and must be editable in the UI with permissions. "Read-only" is the wrong framing; the right framing is:

- **Identity fields** (declared by the bot on enrollment): displayed, not hand-edited in the UI.
- **Admin fields** (operational control): editable in the UI with the right permissions.
- **Participation** (active behavior): fully operational. Agents send and receive coordination actions, own conversations, accept and execute routed tasks and protocol stages, and update registry state as they work.

### 3.4 The SDK gaps that matter

Two gaps in the SDK matter for the shape of this plan:

- **Protocol invocation is not a formal port.** Every invoker calls the registry HTTP / authority client directly. This is fine for one bot; it will drift for many.
- **Protocol observation is not a formal port.** Same problem.

Both need to be promoted to first-class ports before we build runs-surface + rehearsal + cross-bot invocation against them, otherwise we will ship a registry-privileged runs page and still have the same drift.

### 3.5 UI bloat is real and is three files

- `octopus_registry/ui/js/components/protocol-workspace.js` — 3,097 LOC. Section-tabbed, form-driven, inspector-per-entity, raw-JSON-as-tab.
- `octopus_registry/ui/js/components/skill-catalog.js` — 2,279 LOC. Its own lifecycle chrome.
- `octopus_registry/ui/js/components/guidance-editor.js` — 662 LOC. Its own lifecycle chrome.

Each has its own text/number/select input helpers. Each has its own destructive-action styling. Each invents its own empty states.

## 4. Decisions (locked)

1. **One engine, one routing, one projection path.** No parallel dry runtime.
2. **Protocol UX has two modes: Author and Rehearse.** Operation is not a protocol-UX feature.
3. **Protocol invocation and observation become formal SDK ports**: `ProtocolInvocationPort`, `ProtocolObservationPort`. Every bot surface — Telegram, agent runtime, registry web, future bot — consumes them.
4. **Rehearsal is one provisional agent per session, many roles via distinct routed-task threads.** Transport is a rehearsal panel in the registry UI. Canned and author-typed responses supported. Setup is automatic on session start, teardown automatic on session end. No N-enrollments.
5. **Agents page stays "Agents."** The registry UI is the admin/management surface (parallel to the Octopus CLI). Identity fields are enrollment-sourced and displayed; admin fields are editable under permissions; participation is fully active.
6. **Protocol stages continue to ride the routed-task framework** (already true). Hardened by explicit integration tests.
7. **Authoring kit first, protocols reshape onto it, other surfaces migrate after.** Deferred migration is formalized with a manifest, a per-surface checklist, an acceptance gate against new bespoke UX code, and an explicit completion criterion.
8. **Runs surface is a general observability product.** Protocol runs is the first populated shape; the data model and UI are future-proofed for delegation chains, coordination actions, long agent sessions, cross-authority runs.
9. **Templates and examples live in a Gallery.** They are not rows in the authored catalog and not in `protocol_definitions`. `software-engineering` moves to the Gallery store.
10. **Selector-first participant picking.** Authors pick participants by selector (skill, role, authority), with live resolution preview via `preview_target_resolution`. Specific-agent pins are a rare override.
11. **Plain-language UI.** No `strict_completion`, no `stage_kind`, no `require_output_verification`, no Pydantic text, no server-seeded placeholder values in inputs. A **human-language dictionary** maps domain keys to display labels and help text, used by every surface.
12. **First-run authoring rules (locked, enforced by the kit).**
    - Blank draft fields render truly empty on first paint; nothing prefilled that looks like user content.
    - Hint text uses placeholder styling only; a saved value is never rendered as a hint.
    - Slug is *suggested* only after the display name is entered (and only if empty); never prefilled on first paint.
    - All first-run authoring copy is task-oriented and non-technical: label, help, empty-state, and validation messages answer "what do I do next?" rather than naming implementation concepts.
    - The canvas has a progressive first-run state that walks a blank draft through first participant → first stage → first transition without leaving the canvas.
13. **Save semantics (locked).**
    - Draft-scope edits use **debounced autosave**: details-panel field changes, canvas mutations, and lifecycle-header text fields commit through `saving → saved` on the draft-state chip.
    - **Lifecycle transitions are always explicit**: publish, archive, discard are button actions; never silent, never autosaved.
    - **Conflict detection is required**: multi-tab or multi-client edits detected via record version / etag; chip enters `conflict` state with a resolution prompt. Not deferrable.
    - `saved` on the chip means persisted server-side — never "debounce timer cleared."
14. **Responsive behavior is an invariant, not a finishing step.**
    - Every kit primitive's contract includes defined breakpoint behavior; no primitive is "done" until its responsive behavior has tests at those breakpoints.
    - The canvas has an explicit narrow-width mode (stacked/list-with-arrows) — not shrink-and-hope; decided per primitive as part of its first PR.
15. **Reuse-first, no duplication at any layer.**
    - Before introducing any new function, class, method, style, or endpoint, search the existing codebase for something that already serves the need and extend it.
    - If an existing construct does not fit, the first response is to ask whether it can be generalized to fit, not to fork a parallel one.
    - Only when an existing construct genuinely cannot be extended — and the reason is captured in the PR — does a new construct land, and it replaces whatever it supersedes in the same change.
    - This rule applies equally to Python (SDK, registry, app), JavaScript (kit and consumers), and CSS (tokens, utilities, primitive styles).
16. **No parallel code paths, no backward-compat shims.** The kill list is enforced.
17. **Dead code and tests are removed continuously.**
    - Every step's PRs end with a dead-code sweep for anything the step orphaned: unreachable functions, unused imports, stale tests, dead CSS classes, retired endpoints.
    - Dead code does not stay for "one more cycle." It leaves with the change that orphaned it.

## 5. Target product shape

### 5.1 Protocol UX (flagship)

Two modes, one surface.

**Author mode.** Primary surface is a **canvas**: nodes are stages (typed visually: work / review / acceptance), edges are transitions (drawn and labeled with decisions: complete / accept / revise / fail), participants render as lanes or colored badges, artifacts flow on edges so "what moves between stages" is visible. Selection selects a node or edge. A single **details panel** to the side binds to the selection — editing happens in one place, not in a scroll-and-find inspector buried under a tab. Direct manipulation is the norm: drag to arrange, draw to connect, click-rename inline, Tab/Enter to cycle, Cmd+Z to undo. Participant picking is selector-first with live preview of who currently matches. Plain-language labels throughout, sourced from the shared dictionary.

**Rehearse mode.** Same canvas, with stage nodes showing live execution state. A **rehearsal panel** shows the per-role conversation threads that the rehearsal agent is handling. Author can type responses manually or pick canned responses from a scenarios library attached to the protocol (or referenced from a shared scenarios store). No real-world side effects; external-transport egress is gated. Rehearsal is a real run under a rehearsal authority/flag — same engine, same routing, same projection — just with a dry-scope constraint.

**Navigation to runs.** From any authored protocol, "Recent runs" links deep into the runs surface. Authoring does not host operation.

### 5.2 Agents (admin + observability)

One page, three concerns:

- **Presence.** Who is enrolled, connectivity, last heartbeat, trust tier, authority, advertised skills, current workload (active routed tasks and protocol stages).
- **Selector resolution.** "Who matches `skill:plan` right now?" surfaced live via `preview_target_resolution`. Used by authors during protocol design; reusable in the Agents page for quick inspection.
- **Admin actions** (permission-gated): adjust trust tier, override capacity, rotate agent tokens, grant/revoke skill access, force-disconnect, soft-delete, provision placeholder records if the workflow requires. Same actions available from the Octopus CLI; same domain, different surface.

Identity fields declared at enrollment are displayed clearly and not hand-edited. Admin fields are editable.

### 5.3 Runs (observability)

Top-level `/ui/runs`. Protocol runs is the initial populated shape; the data model treats runs as an event-sourced, multi-step, multi-agent instance, with protocol-run a specialization. Views: list with filters (status, protocol, authority, time window), detail page with timeline, participant view, stage/task detail, live event stream via `ProtocolObservationPort`. Ops actions: pause, resume, abort, reassign — consistent with routed-task and protocol state machines.

### 5.4 Gallery (templates + examples)

Top-level `/ui/gallery`. Curated templates for protocols, skills, guidance. Each entry: name, description, preview (for protocols: animated or static graph thumbnail), source, "Start from this" action that copies into an authored draft. Entries live in a dedicated `*_templates` store, surfaced only from the Gallery. `software-engineering` moves here. Authored records and template records are never mixed in the same list.

### 5.5 Skills and guidance

Adopt the authoring kit chrome (lifecycle header, draft-state chip, details panel, dictionary, validation surface, gallery entry point). Behavior unchanged in the first protocol-focused pass; full migration of their internal editing surfaces onto kit primitives is the deferred stage, governed by the acceptance gate.

## 6. Architecture

### 6.1 SDK ports — new and existing

**Promoted / new:**

- `ProtocolInvocationPort`
  - `invoke(protocol_id_or_slug, inputs, *, idempotency_key, origin: TransportActorKey) -> RunId`
  - Consumed by Telegram (`/run …`), agent runtime (tool call), registry UI ("Run" button), future bots.
- `ProtocolObservationPort`
  - `list_runs(…) -> list[RunRecord]`
  - `get_run(run_id) -> RunRecord` (detail includes stages; distinct `list_stages` method deferred until a consumer needs it)
  - `list_run_issues(…) -> list[IssueRecord]`
  - `list_run_artifacts(run_id) -> list[ArtifactRecord]`
  - `list_run_timeline(run_id) -> list[TransitionRecord]`
  - `export_run(run_id) -> ExportRecord`
  - Consumed by registry runs UI (rich rendering), Telegram (status echoes), agent runtime (tool output), future bots.
  - **Streaming is not on the port.** Live event delivery is owned by the existing WS feed at `/v1/ws` (session-auth). Port consumers poll `get_run` for snapshots; UI surfaces subscribe to the WS. A streaming method is added only when a non-UI consumer actually needs it; no stub lands in the meantime.

**Existing, unchanged:**

- `RegistryParticipant`, `RegistryConversationMirror`, `RegistryCoordination`, `RegistryDiscovery`, `RegistryParticipantHealth`.
- `ConversationProjectionPort`.
- `TaskRoutingPort`, `RoutedTaskRequest`, task / delegated-task state machines.
- `ProtocolRunEngine` (dispatch via routed tasks).

**Bot SDK reference and starter:** a minimal in-tree reference bot that implements all required ports. The Telegram bot is *a* reference; the starter exists so the SDK contract is not defined by what Telegram happens to do. Used as a conformance harness for the rehearsal bot and any future bot.

### 6.2 Engine and routing

Unchanged for the production path. Protocol stages continue to dispatch as routed tasks; the framework continues to write events to origin and recipient conversations.

Additions for rehearsal:

- A **rehearsal scope** — either a dedicated rehearsal authority or a trust-tier/flag on the existing authority (decided at implementation time; leaning dedicated authority for isolation).
- An **engine-level side-effect gate** on rehearsal scope: outbound webhooks, credential egress, external providers and any port that touches the real world returns a dry no-op.

### 6.3 Rehearsal bot (in-process)

Single agent per rehearsal session. Implements:

- `RegistryParticipant` — enrolls on session start under the rehearsal scope with a broad skill advertisement matching the protocol's participants; retires on session end.
- `ConversationProjectionPort` — lightweight; projects the rehearsal panel threads back into registry conversations so they appear in the registry UI like real work.
- `TaskRoutingPort` — claims `protocol-stage:*` routed tasks addressed to the rehearsal scope, dispatches each to the rehearsal panel, awaits a response, submits the result back through `submit_task_result`.

Transport is the rehearsal panel — a kit primitive. No external-transport code, no heartbeat daemons, no separate enrollment UX for the author.

Response sources:

- **Canned** — scenarios attached to the protocol (or referenced from a shared scenarios store) provide pre-recorded outputs per role/stage.
- **Author-typed** — interactive responses through the panel; used to exercise edge cases.

### 6.4 Data

- `protocol_definitions` holds only authored records.
- New `protocol_templates` store holds examples. Optional author-opt-in promotion of a published protocol into the Gallery.
- Server-side defaults for draft creation (`display_name = "Untitled Protocol"`, `slug = "protocol-N"`) removed. Drafts are empty until the user types. Placeholders are client-side hints only, with correct `::placeholder` styling.

### 6.5 Authoring kit

Shared UI module consumed by every registry surface. Each primitive has: a purpose, an API contract (props, events, state shape), stylistic invariants, and a test bar (unit + visual baseline). Primitives are delivered in the sequence protocols needs them, and each must land with adoption in at least one non-protocol surface stub to prove the contract is not protocol-shaped.

See the Kit manifest (§7) for the primitive list.

### 6.6 Integration seams (concrete anchors)

The steps in §9 touch the following existing seams. Named here so implementation does not have to rediscover them, and so changes there are reviewed as seam work rather than as ad-hoc edits.

- **HTTP router:** `octopus_registry/protocol_http.py::build_protocol_router`. New endpoints that back `ProtocolInvocationPort` / `ProtocolObservationPort` (Step 1) land here, not directly in `server.py`. Keeps `server.py` from growing and keeps protocol routing in one factory.
- **Builtin templates and DB init:** Builtin protocol examples are served directly from the in-tree manifest (`octopus_sdk.protocols.core.builtin_protocol_documents`) via `protocol_store.list_protocol_templates` / `get_protocol_template`. There is no seeding of examples into `protocol_definitions`; `app/db/postgres_init.py::run_init` applies `init.sql` and nothing else protocol-specific. A persistent `protocol_templates` table lands only when author-opt-in promotion from published protocols is implemented (Step 4 sub-item); until then the manifest is the single source of truth for Gallery content. Nothing else in the codebase may seed protocol content.
- **Protocol persistence:** `octopus_registry/protocol_store.py::ProtocolPostgresAdapter` is the primary protocol persistence module; `octopus_registry/store_postgres.py::RegistryPostgresStore` delegates to it. New persistence for templates (Step 4), rehearsal scope bookkeeping (Step 6), observation-friendly run queries (Step 7), and any protocol-adjacent admin writes (Step 8) are added to `ProtocolPostgresAdapter` with thin delegation wrappers on `RegistryPostgresStore`. Non-protocol admin writes (agents trust tier, capacity, token rotation) go on `RegistryPostgresStore` directly, following the domain split already present.
- **Delegation-seam gate:** `tests/test_registry_store_type_contract.py::test_registry_store_protocol_delegates_match_adapter_signatures` asserts signature parity between `RegistryPostgresStore` wrappers and `ProtocolPostgresAdapter` methods. Any new protocol-adapter method added by this plan must be mirrored through the wrapper and must pass this test. Treated as a merge gate, not as opt-in coverage.
- **UI route structure:** `octopus_registry/ui/js/app.js` currently registers `/ui/protocols` (authoring) and `/ui/protocol-runs` (operations). Step 7 retires `/ui/protocol-runs` in favor of a top-level `/ui/runs` consuming `ProtocolObservationPort` and the runs widgets. The Gallery lands at `/ui/gallery` (Step 4). Router registrations are updated in the same PRs that deliver the new surfaces; no parallel routes.
- **Selector resolution seam:** `RegistryCoordination.preview_target_resolution` (`octopus_sdk/registry_participant.py`) with runtime implementation in `app/runtime/registry_participant.py`. Selector-first participant picking in the protocol authoring canvas (Step 5) consumes this existing port — no registry-local preview endpoint, no parallel resolver. Agents-page selector preview (Step 8) consumes the same path. Any new resolver behavior is added on the port, not alongside it.

## 7. Kit manifest

Each entry: purpose, contract, invariants, test bar, initial consumers. (API signatures are indicative; finalized in the primitive's first PR.)

### 7.1 Lifecycle header

- **Purpose:** title, slug, draft-state chip, validate / publish / archive / discard actions. One place authors manage the record's lifecycle.
- **Contract:** `{ record, saveState, validators, actions: { validate, publish, archive, discard }, permissions }`.
- **Invariants:** destructive actions are visually consistent (`btn-danger` class, confirmation pattern). Save state chip shows `idle | editing | saving | saved | conflict | error` with the same labels everywhere.
- **Test bar:** unit test per action permission matrix; visual baseline.
- **Initial consumers:** protocol authoring, stub adoption in skills.

### 7.2 Draft-state chip

- **Purpose:** single, trustworthy save indicator.
- **Contract:** `{ state: 'idle' | 'editing' | 'saving' | 'saved' | 'conflict' | 'error', lastSavedAt, error }`.
- **Invariants:** never ambiguous; "saved" means persisted server-side; conflict surfaces a resolution path.
- **Test bar:** state-transition unit tests.
- **Initial consumers:** lifecycle header, rehearsal panel, any autosaving form.

### 7.3 Canvas

- **Purpose:** node-and-edge direct-manipulation surface.
- **Contract:** `{ nodes, edges, layout, selection, onMutate, onSelect, nodeRenderer, edgeRenderer, keyboard, firstRun }`.
- **Invariants:** node types are styled distinctly; edges are drawn with labels; drag to arrange; draw to connect; click to select; Cmd+Z / Cmd+Shift+Z for undo; keyboard navigation. When opened on a blank draft the canvas enters a **progressive first-run state** that guides the author through first participant → first stage → first transition inline (no modal, no separate wizard, no leaving the canvas); the state dismisses automatically once the graph has at least one participant, one stage, and one transition. On narrow widths (tablet/mobile) the canvas switches to an **explicit narrow-width mode** — stacked list-with-arrows — not a shrunk graph; mode switch is driven by viewport, not a toggle.
- **Test bar:** interaction tests (drag, connect, select, keyboard); visual baseline for node types; first-run state exits correctly as each prerequisite lands; narrow-width mode renders correctly at defined breakpoints.
- **Initial consumers:** protocol authoring canvas; protocol rehearsal canvas (same graph, live state overlay).

### 7.4 Details panel

- **Purpose:** single context-sensitive editor bound to the current canvas selection (or list selection on non-canvas surfaces).
- **Contract:** `{ target, schema, dictionary, onCommit }`.
- **Invariants:** one panel, not many; labels pulled from the dictionary; no domain-term leakage. Fields on a blank draft render empty on first paint — no prefilled text that resembles user content. Placeholder text uses placeholder styling and is never rendered from a persisted value. Derived fields (e.g. slug from display name) are *suggested* only after the user has entered the driving field, and never on first paint.
- **Test bar:** renders correct fields for each target type; commit flows end-to-end; first-paint rendering of a blank record has no value text in any input; suggestion behavior for derived fields fires only on user-driven input, not on load.
- **Initial consumers:** protocol authoring; later, skills and guidance.

### 7.5 Dictionary

- **Purpose:** map domain keys to human labels, help text, empty-state copy, and validation messages.
- **Contract:** `{ label(key), help(key), enumLabel(key, value), emptyState(surfaceKey), firstRun(surfaceKey, step) }`.
- **Invariants:** every user-facing string pulls through it; missing entries surface as test failures, not runtime silence. All first-run authoring copy is **task-oriented and non-technical** — labels, help, empty states, and validation answer "what do I do next?" and never name implementation concepts (no `strict_completion`, no `stage_kind`, no Pydantic paths). A copy-review checklist gates dictionary additions so new terms do not regress the rule.
- **Test bar:** coverage test — no domain key used in UI without a dictionary entry; lint check — no raw implementation terms appear outside the dictionary module; review gate on new or changed entries.
- **Initial consumers:** every surface that renders domain terms.

### 7.6 Validation surface

- **Purpose:** consistent display of errors, warnings, and readiness.
- **Contract:** `{ issues: [{ severity, message, path, action? }], layout: 'inline' | 'summary' }`.
- **Invariants:** no raw Pydantic text; every message is translated through the dictionary; inline where possible.
- **Test bar:** rendering of mixed-severity sets; translation of common upstream error shapes.
- **Initial consumers:** protocol authoring (draft + publish), skills (publish), guidance (publish).

### 7.7 Gallery

- **Purpose:** browse templates and examples; start a new authored record from one.
- **Contract:** `{ entries, filters, onPreview, onStart }`.
- **Invariants:** entries are clearly templates; no confusion with authored records.
- **Test bar:** filter behavior; preview rendering; onStart produces a new draft.
- **Initial consumers:** protocols (with `software-engineering` migrated in), future skills, future guidance.

### 7.8 Authored catalog

- **Purpose:** browse, filter, and open authored records across any surface (protocols today; skills, guidance, agents later).
- **Contract:** `{ records, lifecycleFilter, search, sort, onOpen, statusChipRenderer, emptyStateRenderer }`.
- **Invariants:** every row carries an explicit lifecycle chip (`draft` / `published` / `archived`) rendered with the same visual grammar as the lifecycle header chip. A lifecycle filter is present by default (all / draft / published / archived). Authored records and template/Gallery entries never mix in the same list. Empty states come from the dictionary and are task-oriented. Scale affordances (search, sort, grouping beyond lifecycle) are supported by the contract but are exposed per surface as needs arise; the first cut shows lifecycle filter + basic search. On narrow widths the list renders as a single-column card stack; filters collapse into a sheet, not a sidebar.
- **Test bar:** lifecycle filter applies correctly; status chip coverage across every lifecycle state; empty state renders from the dictionary; no template entries leak into authored results.
- **Initial consumers:** protocols authored list (first cut); skills and guidance when they migrate.

### 7.9 Runs widgets

- **Purpose:** list, detail, timeline, participants, stage/task detail, event stream — consuming `ProtocolObservationPort`.
- **Contract:** per-widget.
- **Invariants:** event-sourced; generalizable beyond protocols; consistent ops action placement.
- **Test bar:** streaming correctness; ops action state-machine compliance.
- **Initial consumers:** `/ui/runs`.

### 7.10 Rehearsal panel

- **Purpose:** render per-role conversation threads driven by the rehearsal bot; capture canned or author-typed responses.
- **Contract:** `{ runId, onResponse, scenarios }`.
- **Invariants:** no external egress; responses submit via `submit_task_result`; threads distinct per role.
- **Test bar:** end-to-end dry rehearsal test.
- **Initial consumers:** protocol rehearsal.

## 8. Kill list (what this deletes)

- Section-tab authoring (`Overview / Participants / Stages / Artifacts / Policies / Review / Advanced`).
- `_buildStageFlow` CSS-grid pseudo-diagram.
- Every `_build*Canvas` / `_build*Inspector` pair in `protocol-workspace.js`.
- Raw-JSON-as-tab for protocols (replaced by a developer menu action with a clear "you are leaving the guided editor" warning).
- Bespoke `/ui/protocol-runs` page — replaced by `/ui/runs` consuming the kit.
- `software-engineering` row in `protocol_definitions` — moved to `protocol_templates` and surfaced via the Gallery.
- Server-seeded default `display_name` / `slug` on draft creation.
- Per-section text/number/select input factories in protocols, skills, and guidance — replaced by the details panel primitive.
- Per-section ad-hoc lifecycle strips and destructive-action dialects in skills and guidance — replaced by the lifecycle header.
- Direct HTTP invocation / observation from Telegram and agent runtime — replaced by the `ProtocolInvocationPort` / `ProtocolObservationPort` consumers.

Dead tests (any covering deleted code paths) are removed with their code, not left as pending.

## 9. Implementation steps

**Dependency-ordered, not strictly sequential.** Each step is one or a small set of PRs; nothing is "done" until tests pass, its kill-list rows are executed, and any code it orphaned is removed in the same change.

**Dependency graph (parallel branches explicit):**

- **Independent branches, can proceed concurrently:** Step 1 (SDK ports) ⟂ Step 2 (participation tests) ⟂ Step 3 (kit foundation) ⟂ Step 4 (templates + Gallery).
- **Critical path for authoring pain relief:** Step 3 → Step 5. Does **not** depend on Steps 1 or 2. If resourcing is limited, Step 3 → Step 5 is the branch that ships user-visible authoring improvement earliest.
- Step 6 (rehearsal) depends on Step 1 (observation of stage state) and Step 5 (rehearsal panel sits inside the reshaped canvas).
- Step 7 (runs surface) depends on Step 1 (observation port) and Step 3 (runs widgets are kit primitives).
- Step 8 (agents admin) depends on Step 3 (consumes kit primitives).
- The acceptance gate (Step 9) lights **at Step 3** when the first primitive lands and expands incrementally as each subsequent primitive lands. Step 9 in the list below is the completion milestone ("gate coverage complete"), not the flag day.

### Step 1 — SDK ports for invocation and observation

- Define `ProtocolInvocationPort` and `ProtocolObservationPort` in `octopus_sdk/protocols/`.
- Registry-side implementation (HTTP + authority client).
- Telegram bot adopts both in place, removing any direct HTTP calls for runs.
- Agent runtime gains a protocol invocation tool that consumes the port.
- Contract tests pass for each implementation.

### Step 2 — Harden protocol participation tests

- Integration test: a stage dispatch writes events to the recipient conversation.
- Integration test: stage completion flows through `submit_task_result` and transitions the stage execution.
- Integration test: WebSocket broadcast covers both sides (`tasks`, `protocols`, origin + recipient conversations).
- Integration test: receiving agent's conversation UI shows stage context with a navigable link to the run.
- Any dead assertions or redundant tests elsewhere are removed.

### Step 3 — Kit foundation (primitives protocols needs)

- Lifecycle header.
- Draft-state chip.
- Dictionary (with first-run copy invariant enforced).
- Validation surface.
- Details panel (with blank-first-paint invariant enforced).
- Authored catalog (with lifecycle chip + filter).
- Each ships with a stub adoption in skills or guidance to prove the contract.
- Visual baselines captured; invariants (first-run rules, responsive behavior, save semantics) have tests before any surface consumes the primitive.
- **Acceptance gate lights here**: as each primitive lands, the CI check adds it to its coverage list and rejects new non-kit occurrences of the primitive's concern in `skills`, `guidance`, `agents`, `conversations`, `runs`, `dashboards`. The gate is incrementally enforced from this step onward; it does not wait for Step 9.

### Step 4 — Gallery and template store

- `protocol_templates` store.
- `/ui/gallery` surface consuming the gallery primitive.
- `software-engineering` migrated out of `protocol_definitions`.
- Optional author-opt-in promotion from published protocols.

### Step 5 — Protocol UX reshape

- Canvas primitive with the progressive first-run state.
- Protocol authoring built on canvas + details panel + lifecycle header + dictionary + validation surface + authored catalog.
- Selector-first participant picking with live `preview_target_resolution`.
- Plain-language labels everywhere (sourced from dictionary; no implementation terms in the UI).
- First-run field behavior honored: blank fields truly empty on first paint, placeholder styling only, slug suggested not prefilled.
- Authored catalog shows lifecycle chips and lifecycle filter; templates live in the Gallery and never mix in.
- Delete section-tab UX, `_buildStageFlow`, every `_build*Canvas/*Inspector` pair, raw-JSON-as-tab, server-seeded defaults.
- Protocol-workspace.js either shrinks dramatically or is split into kit-consumer modules; LOC is not a primary metric, clarity is. This absorbs the `protocol-workspace.js` size item (P2) from `ARCHITECTURE_DEBT_ANALYSIS.md` as a byproduct — no separate file-split step is scheduled.

### Step 6 — Rehearsal

- Rehearsal scope (authority or trust-tier; decided during design of this step).
- In-process `RehearsalParticipantBot`.
- Rehearsal panel primitive.
- Canned scenarios store and authoring affordance.
- Engine side-effect gate for rehearsal scope.
- End-to-end test: author draft → rehearse with canned scenario → verify engine walks the graph correctly without external egress.

### Step 7 — Runs surface

- `/ui/runs` consuming `ProtocolObservationPort` and the runs widgets.
- Retire bespoke `/ui/protocol-runs`.
- Data model is event-sourced and framed for future generalization (delegation chains, coordination actions, long sessions).

### Step 8 — Agents page: admin + observability

- Presence view (connectivity, skills, authority, trust tier, workload).
- Selector resolution preview.
- Admin actions gated by permissions: trust tier, capacity, token rotation, skill grants, disconnect, soft-delete, provisioning.
- Identity fields displayed, not hand-edited.

### Step 9 — Acceptance gate: coverage complete

- By this step the gate (lit at Step 3, expanded incrementally through Steps 4–8) covers every kit primitive the first cut delivers.
- Final pass: audit the CI check's coverage list against the kit manifest; every primitive from §7 is represented; no surface named in §4 item 15 can add a bespoke variant without the check failing.
- Existing bespoke code still remains until migrated (see deferred stage); the gate prevents new occurrences, not retroactive ones.
- Gate remains active throughout the deferred stage and after completion, as a standing invariant.

### Deferred stage — migrate skills, guidance, and the rest

Triggered after protocol UX is accepted. Per surface:

- **Skills catalog** — retire the per-section lifecycle strip, the bespoke review tab, the local input helpers. Adopt lifecycle header, details panel, dictionary, validation surface, gallery. Preserve studio / approval behavior. Net LOC drop expected but not a success metric.
- **Guidance editor** — retire the `<textarea>` + custom save chip. Adopt lifecycle header, draft-state chip, details panel, validation surface. A prose-editor variant may be added to the kit if guidance's needs exceed the details panel.
- **Conversations view** — keep the projection as-is. Adopt kit chrome, dictionary-sourced labels, consistent invalidation patterns.
- **Dashboards** — adopt kit list primitives, empty states, and lifecycle chips where applicable.

**Completion criterion:** zero non-kit UX code remains in `skills`, `guidance`, `agents`, `conversations`, `runs`, `dashboards`. Measured by the same lint/grep check that enforces the acceptance gate. The deferred stage is closed only when the check returns zero.

## 10. Testing strategy

- **Contract tests** per SDK port, passing for every implementation (registry, Telegram, agent runtime, reference bot, rehearsal bot).
- **Integration tests** around protocol participation (Step 2 set).
- **Kit primitive tests** — unit and visual baseline, enforced before adoption.
- **End-to-end test** for rehearsal, covering author draft → rehearse → verify engine walk + no external egress.
- **Acceptance-gate check** — CI job that greps for forbidden patterns in non-kit UX paths and fails on new occurrences.
- **Dead-code sweep** after each step — any code path left orphaned by the step's kill list is removed in the same PR, not in a follow-up.

## 11. Backlog (observability and runs, future)

Not in scope for the first cut. Captured here to inform data-model choices so we do not foreclose them.

- Timeline / trace view per stage.
- Run comparison and diff.
- Replay / fork from a chosen stage with different inputs or a newer protocol version.
- Run as rehearsal seed (use a real run's inputs as a scenario).
- Human-in-the-loop approvals at the run level.
- Generalize runs beyond protocols (delegation chains, coordination actions, long agent sessions).
- Annotations and pins on runs and stages.
- Per-protocol dashboards (success rate, stage duration p50/p95, grouped failure reasons).
- Audit export — signed run bundle.
- Cross-authority view with clear authority boundaries.
- Ops actions unified across run kinds (pause / resume / abort / reassign).

## 12. Open questions

1. **Rehearsal scope shape** — dedicated rehearsal authority, or a trust-tier / flag on the existing authority? Leaning dedicated authority for isolation and clean teardown.
2. **Canned scenarios storage** — embedded in the protocol template record, or a separate `protocol_scenarios` store? Leaning separate, so scenarios can reference multiple protocol versions.
3. **Gallery entry sources** — `protocol_templates` exclusively, or also author-opt-in promotion from published protocols? Leaning both, with promotion gated on author consent.
4. **Reference bot vs. Telegram-as-reference** — build a tiny in-tree reference bot to define the SDK contract independently of Telegram? Leaning yes — contract must not be defined by what Telegram happens to need.
5. **Acceptance-gate enforcement** — lint-level rule or CI grep? Whichever is cheaper to maintain and hardest to bypass.

## 13. Non-goals

- Shrinking files as an end in itself. Clarity and one-obvious-path are the targets.
- Rewriting skills, guidance, conversations, dashboards in the first cut. Those adopt kit chrome only; full migration is the deferred stage.
- Generalizing runs beyond protocols in the first cut. Data model allows it; UI exposes protocol runs only at first.
- Maintaining two code paths for any feature. Everything moves in place.

## 14. Known orthogonal debt (out of scope here)

`ARCHITECTURE_DEBT_ANALYSIS.md` tracks backend structural debt that is real, independent of this plan, and intentionally not advanced here:

- Narrowing the `AbstractRegistryStore` god Protocol (~89 methods, `octopus_registry/store_base.py`) into per-domain ports.
- Reducing `RegistryPostgresStore` (~1.7k lines) by continuing the domain-extraction pattern established by `ProtocolPostgresAdapter`.
- Reducing `server.py` (~1.8k lines) by continuing the router-extraction pattern established by `build_protocol_router`.
- `ingress.py` (~990 lines) decomposition.
- Test-coupling reduction: many tests import `RegistryPostgresStore` and `_SCHEMA` directly and are expensive to rehome behind ports.
- SDK protocols package file sizes (`models.py`, `documents.py`, `engine.py`) — this plan adds new files (`ports.py` for new SDK ports), it does not restructure existing ones.

This plan does not advance those items and does not block on them. When the debt items move, they move on their own track. When this plan touches a file those items also touch (`protocol_http.py`, `protocol_store.py`, `server.py`), the change follows the integration seams in §6.6 so the two tracks do not collide.
