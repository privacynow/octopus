# Protocol authoring recovery — execution plan

*Single canonical draft document; two validation lenses (draft vs strict); one editor pipeline. The failure is structural (flat peer-level graph, missing inspector contract) not cosmetic. This plan merges the interaction-first diagnosis, the overview/focus large-workflow model, explicit projection invariants, and a mandatory ship gate—including the **Software Engineering** template.*

---

## Executive summary

We keep **one** `draft_definition_json` blob and **one** save path. On top of it we add a **derived projection layer** so the UI never treats a large workflow as a single mile-wide peer graph: **overview** shows collapsed structure (segments, roles, branches); **focus** expands a local neighborhood for step and transition editing and for **rehearse** overlay. Semantic workflow stays in canonical fields; **zoom, pan, focus target, minimap, and optional positions** live in **`metadata.ui`** (or equivalent), ignored by strict validation and runtime. **Phase 1** finishes the empty/first-run inspector contract and verifies existing mode work; **Phase 2** delivers projection, real layout engines, and canvas controls. **No release** without passing the combined ship gate below.

---

## 1. Problem statement

The failure is **not** primarily “bad SVG lines.” It is a **missing authoring interaction contract** and a **wrong structural metaphor**: projecting the **entire** document into **one** peer-level graph guarantees horizontal sprawl for templates like **Software Engineering**. Historical issues included **`firstRun` suppressing the inspector**, hidden connect hijacking, **runtime agent labels** driving lane chrome, and **hand-built geometry** without a layout contract. The **canonical document model and APIs** are largely right; the **editor layer** must be rebuilt **on top** without forking persistence.

**Bottom line:** The fix is not “make the current graph scroll better.” The fix is **stop treating a large workflow as one flat peer-level graph**, using the same move commercial workflow tools use: **high-level map + detail in context**, not infinite horizontal detail.

---

## 2. Context

- **Single source of truth:** `draft_definition_json` + **`draft_revision`** / **`If-Match`**; **published** versions immutable for runs.
- **SDK:** `validate_protocol_document(..., mode="draft"|"strict")` in `octopus_sdk/protocols/documents.py`; **strict** yields **`ProtocolDefinitionDocumentRecord`** via `canonical_protocol_document` (`models.py`).
- **Registry:** conflict handling, rehearsal flags, selector preview HTTP.

---

## 3. Current implementation status (audit snapshot)

**Already aligned in code (do not regress):**

| Area | Status |
|------|--------|
| Draft save vs publish | `save_protocol_draft` uses **draft** validation; publish/validate use **strict** (`protocol_store.py`, SDK). |
| Named editor modes | `idle` / `insert-role` / `insert-stage` / `connect` / `rehearse`—not a separate hidden `connectState`. |
| Decision defaults | `_defaultDecisionForStageKind` / `_decisionOptionsForStage` align with `stage_kind`. |
| Participant injection | No automatic append of **participants** from connected agents; agents feed **suggestions** only. |

**Still missing (this plan closes these):**

| Gap | What fixes it |
|-----|----------------|
| Dense / medium-size workflows (5–10 stages) still collide or sprawl | **Renderer and node-density replacement** (§7.4, §7.6). |
| Full expanded graph still reads badly | **`full` view completion** with the same layout pipeline (§6.1, §7.4). |
| View chrome vs semantics | **Editor-only view state** stays out of semantic workflow fields (§7.5). |
| Hand-tuned x/y only | **Single layout pipeline** with graph-derived ordering and clean routing (§7.4). |
| Rehearse on full canvas | **Rehearse overlays focus graph** (§6.3). |

### 3.1 Code map (holistic anchor to current tree)

Execution is **not** abstract: the following paths are where behavior lives **today**. Line numbers are **approximate** and drift with edits—re-grep when implementing.

**Client — protocol authoring UI**

| Location | What exists today | Plan phase |
|----------|-------------------|------------|
| `octopus_registry/ui/js/components/protocol-workspace.js` | `renderProtocolWorkspace`; `editorMode` (`idle` / `insert-role` / `insert-stage` / `connect` / `rehearse`); `workflowView` (`overview` / `focus` / `full`); **`_buildWorkflowProjection()`** builds segments from one draft document; **`_workflowData()`** switches overview/focus/full from the same projection; **`_detailsEl()`** already keeps overview inspector visible on empty drafts; stage editor is grouped but still too tall and form-heavy for repeated editing; topology ordering still leans on **document array order** | **P1:** keep current interaction model, replace weak topology ordering and finish progressive stage editor shell. **P2:** improve projection edge cases and simplify overview payload. |
| `octopus_registry/ui/js/helpers/kit.js` | **`workflowCanvas`** (~1023): single canvas path for overview/focus/full, but still **hand-tuned** column/row geometry, oversized lane bands, fixed node sizes, and manual edge label placement | **P2:** keep one canvas API, replace its internal layout/routing/density rules with one cleaner pipeline; add fit/zoom/reset and responsive density. |

**Server / SDK (already match draft vs strict)**

| Location | Role |
|----------|------|
| `octopus_registry/protocol_store.py` | `save_protocol_draft` → `validate_protocol_document(..., mode="draft")`; `validate_protocol` / `publish_protocol` → `mode="strict"`. |
| `octopus_sdk/protocols/documents.py` | `validate_protocol_document`, `draft_protocol_document_data`. |
| `octopus_sdk/protocols/models.py` | Strict `ProtocolDefinitionDocumentRecord` rules. |

**Not in the codebase yet (this plan introduces)**

| Item | Notes |
|------|--------|
| **Editor-only persisted chrome** | No shared persisted zoom/pan/full-graph state beyond local `workflowView`; add only if the chosen controls need it, and keep it non-semantic (§7.5). |
| **Renderer replacement** | Projection exists; the remaining missing piece is a **dense, collision-resistant layout/routing pipeline** inside the current `workflowCanvas`. |
| **Software Engineering ship gate** | Product expectation is written here, but the full browser/screenshot gate still needs to be encoded in tests. |

**Tests that already guard the surface**

| Test | What it enforces |
|------|------------------|
| `tests/test_registry_ui_contract.py` | `protocol-workspace.js` contains `renderProtocolWorkspace`, `Kit.workflowCanvas(`, etc. |
| `tests/test_registry_ui_kit_contract.py` | Kit exports include `workflowCanvas`. |
| `tests/test_kit_acceptance_gate.py` | Protocol workspace must use Kit primitives (`workflowCanvas`, `detailsPanel`, …)—extend when new primitives land. |

**Phase-to-file summary**

| Phase | Primary touch |
|-------|----------------|
| **P1** | `protocol-workspace.js` (`_detailsEl`, selection/overview behavior); optional copy/docs for draft vs strict. |
| **P2** | `protocol-workspace.js` (projection), `kit.js` (`workflowCanvas` + layout), new or vendor layout module, **`metadata.ui`** persistence + server/SDK strip if stored server-side, Playwright + **Software Engineering** template scenarios. |

---

## 4. Locked decisions

| # | Decision |
|---|----------|
| D1 | **Authoring interaction state** is a first-class state machine (modes **and** transitions)—not a pile of booleans. |
| D2 | **Draft save** uses draft-safe validation; **publish** uses **strict** document validation. |
| D3 | **Editor-only** state never mutates semantic protocol fields; stored under **`metadata.ui`** (or sidecar)—see **§7.5**. |
| D4 | **Lanes** = **authored roles** (`participants`); never default lane labels from **connected agent slugs** without an explicit user action. |
| D5 | **Quick-start / connected-agent auto-participant** paths that **inject** into **participants** without a **Role creation** flow stay **removed**. |
| D6 | **Phase 1** (interaction + inspector) and **Phase 2** (projection + layout) are **one recovery**; **ship gate = both pass**—layout is not “later polish.” |
| D7 | **Playwright** is merge-blocking for listed flows once ship criteria exist. |
| D8 | Large protocols are **not** one flat peer-level graph forever; the editor uses **`overview`**, **`focus`**, and explicit **`full`** graph **views** on the same canonical document. |
| D9 | In **Author** mode, the inspector is **never suppressed** only because the graph is empty—see **§6.4**. |
| D10 | Editor-only view chrome (zoom, pan, focus/full view, minimap viewport, optional node positions) stays **non-semantic** and must not affect strict validation or runtime—see **§7.5**. |
| D11 | The **Software Engineering** template is a **ship-gate artifact**—see **§11** (G6). |

---

## 5. Draft-safe vs strict validation

**Problem this fixes:** Strict validation requires e.g. at least one stage and non-empty `metadata.slug`. If the editor only persisted strict-shaped documents, **empty drafts** could not autosave.

| When | Mode | Purpose |
|------|------|---------|
| Autosave / `PUT` draft | **`draft`** | Incomplete graphs allowed; issues as warnings / next actions. |
| Publish / validate-for-release | **`strict`** | Runnable shape for version snapshot and runs. |
| Server `save_protocol_draft` | **`draft`** alignment | Must not require strict canonical record for incomplete drafts. |

**UX copy:** “Draft can be incomplete; **Publish** requires a valid protocol.”

**Non-goal:** Two documents in the DB—**one** JSON blob; **two validation lenses**.

---

## 6. Authoring model: views × modes × inspector

### 6.1 Graph views (structural)

| View | Purpose |
|------|---------|
| **`overview`** | Collapsed **workflow map**: roles as lanes, **segments** (not every atomic step), branch/join structure, compact terminal outcomes. **Not** the full peer-level editor. |
| **`focus`** | **Expanded local flow** for the selected segment or neighborhood: real **stages**, **explicit transition editing**, step editing with inspector. |
| **`full`** | Explicit “show every step” map for users who want the entire workflow at once. It is a supported product view, but it must use the same dense layout pipeline and cannot devolve into giant padded lane slabs. |

**Product shape (overview):** major workflow segments, not every atomic step; bounded-width layered layout; no “more steps = more columns forever.”

**Product shape (focus):** selected segment expanded; predecessor/successor context; orthogonal or port-aware routing for local graph; terminals in one compact sink column.

**Product shape (full):** every real stage visible, but still dense and readable for 5–10 stage workflows. `full` is not a debug map. It must fit, zoom, and pack vertically without text/pill collisions.

**Rehearse:** overlays **run state on the focus graph**, not on a mile-wide flat canvas.

### 6.2 Interaction modes (behavioral)

| Mode | Meaning |
|------|---------|
| **`idle`** | Selection drives inspector; no connect hijack. |
| **`insert-role`** | Add role flow; no document commit until confirm. |
| **`insert-stage`** | Add step flow; commit on confirm. |
| **`connect`** | One transition from a source stage; valid targets highlighted; **Cancel** / **Esc** exits. Lives in **focus** (or overview only if product explicitly supports a limited connect—default is **focus-first**). |
| **`rehearse`** | Read-only definition edits; rehearsal panel; overlay on **focus** graph. |

**`firstRun` / onboarding:** may remain as hints in the canvas **but** must **augment** the inspector, **not replace** it (§6.4).

### 6.3 How views and modes combine

- **`overview` + `idle`:** navigate structure; select segment to enter focus; inspector shows protocol overview or segment summary as designed—never “empty right column because graph is empty.”
- **`focus` + `idle`:** primary place for step/participant/transition selection and inspector detail.
- **`connect`:** only when **visibly** in connect mode (banner, cancel, highlights); **focus-first** for transition authoring.
- **`rehearse`:** same graph as **focus**, plus overlay; not a second flattened model.

**Invariant:** Overview **never** tries to be the full atomic-stage editor for large templates.

### 6.4 Inspector contract (empty overview and first-run)

**Locked rule:**

- In **Author** mode, the **right-side inspector is never suppressed** only because the graph is empty or the canvas is showing first-run copy.
- When **nothing concrete is selected** (no participant/stage/transition/artifact node), the inspector still shows:
  - **protocol overview fields** (e.g. description, policies when applicable—title/slug may remain in header as today)
  - the **primary creation action** for the current state (**Add role**, **Add step**, **Connect**, as appropriate)
  - draft-safe validation / next-action hints when useful
- **First-run guidance** (cards, empty states) **augments** the inspector; it does **not** replace it.

**Code direction:** Remove `_detailsEl()` patterns that return **`null`** for empty doc + overview merely to show only the canvas (see audit: empty `participantCount` && empty `stageCount` branch).

### 6.5 Navigation contract (overview ↔ focus)

If transition editing is **focus-first**, overview must not feel like it **hides** the real workflow.

- Overview **segments** show **summary counts** (e.g. steps inside, branches out).
- **Click segment** → enters **focus** for that segment (or neighborhood).
- **Breadcrumb / back** → returns to **overview**.
- **Selected segment** in overview stays **visually linked** to the focused detail (highlight, path, or equivalent).

---

## 7. Workflow projection, layout, and metadata

### 7.1 Projection layer (no second runtime model)

Build a **`WorkflowProjection`** (name implementation-defined) from the **existing** document:

- **No** new runtime protocol model, **no** new authoring API family, **no** duplicated save path.
- Same draft JSON in, **derived** overview segments + focus node list out.

### 7.2 Segment boundaries (projection must not lie)

A **segment** is a **derived** cluster—usually same-role linear chains between **boundaries**. The overview **must** define when a boundary starts/ends. **Minimum boundary types:**

| Boundary | Role |
|----------|------|
| Protocol **start** | First stage(s) / entry |
| **Terminal** predecessor | Stage(s) that transition to `__complete__` / `__failed__` / `__cancelled__` |
| **Branch** point | Stage with multiple outgoing decisions or divergent targets |
| **Join** point | Stage with multiple inbound paths |
| **Participant change** | Stage whose role differs from predecessor in the collapsed chain |
| **Loop** entry / **loop** exit | Explicit rules for cycles (document in PR; do not collapse ambiguously) |
| **Future:** explicit “boundary” stage | Optional later flag in document—**not** required for v1 if rules above suffice |

**Collapse rule:** a **linear same-role** run **between** boundaries may collapse into **one segment** in overview.

**Focus rule:** selecting a segment **expands the real `stage` nodes** inside it (or a bounded neighborhood)—**no** second semantic model.

### 7.3 Replacing flat `_workflowData()`

- **`_workflowData()`** (or successor) becomes a **projection builder**: emits **overview segments** and **focus nodes/edges** from one document.
- **`workflowCanvas`** (or successor) learns **`overview`** vs **`focus`** rendering modes—not one flat graph for all cases.

### 7.4 Layout and routing (not CSS alone)

| Surface | Layout |
|---------|--------|
| **Overview** | Bounded-width layered layout using **graph-derived rank/order**, not stage array index. |
| **Focus** | Local graph with clean orthogonal or port-aware routing; edges meet nodes. |
| **Full** | Same layout family as focus, but with denser packing and stronger fit-to-screen defaults for medium-size workflows. |
| **Terminals** | One **compact** sink column—not giant peer lanes. |
| **Controls** | **Fit**, **zoom**, **pan**, **reset**; minimap only if still needed after density/layout fixes. |

Do **not** keep “index column = stage index” as the only layout strategy for large workflows. The current renderer’s fixed `laneHeight` / `columnWidth` / `nodeWidth` math is specifically what this phase replaces.

### 7.6 Density and node-content contract

Medium workflows are currently failing because the renderer lets text, badges, and edge labels compete for the same space. The canvas needs an explicit density contract:

| Element | Rule |
|---------|------|
| **Node label** | One primary line, truncated before it collides with badges or state chips. |
| **Secondary text** | One short secondary line max in dense modes; move the rest to inspector. |
| **Badges** | At most two visible badges in `overview` / `full`; additional state stays in inspector or tooltip. |
| **Lane chrome** | Compact headers or subtle separators only; lanes support reading, they do not dominate the graph. |
| **Edge labels** | Collision-aware placement; reduced or collapsed in `overview`, selective in `full`, always clearest in `focus`. |
| **Terminals** | Compact sink nodes, never rendered as peer lanes or giant decorative bands. |

No shipped mode may render:
- text under pills or buttons
- edge labels over node labels
- badges outside node bounds
- giant empty lane slabs that visually outweigh the workflow nodes

### 7.5 Editor metadata vs semantic document (`metadata.ui`)

| Semantic `definition_json` | Editor-only / `metadata.ui` (or client; v1 storage choice in PR) |
|--------------------------|-------------------------------------------------------------------|
| `participants`, `stages`, `artifacts`, `transitions`, `policies` | **Zoom**, **pan**, **viewport**, **minimap** state |
| `metadata.slug`, display name, description (product-facing) | **Current view** (`overview` \| `focus`), **focused segment id** |
| Anything strict validation reads | **Collapsed segment** UI state, **optional** persisted node positions for focus/overview |

**Rule:** Persist only **non-authoring** fields; **strip or ignore** for `canonical_protocol_document` / runtime. **Document** whether v1 persists **`metadata.ui` in DB** vs **localStorage**.

---

## 8. Transition authoring semantics (by `stage_kind`)

Align UI with `ProtocolStageDefinitionRecord.allowed_decisions()` in `models.py`.

| `stage_kind` | Primary decisions |
|----------------|-------------------|
| **work** | **`completed`** (default outgoing) |
| **review** | **`accept`**, **`revise`**, **`fail`** (or manifest subset) |
| **acceptance** | **`accept`**, **`fail`** |

Advanced: custom decision strings only if validator allows. **Terminal targets:** `__complete__`, `__failed__`, `__cancelled__` only.

---

## 9. Removal of runtime quick-start defaults (hard)

1. **No** auto-creating **participants** from the registry agent list without **Add role** confirm (blank / template / link to agent → then keys + selector).
2. **No** lane **primary** label from **agent.display_name** / **slug** unless the participant was **explicitly** created from that link.
3. Optional: **“Import from registry”** as a **secondary** action inside Add role—not default on empty canvas.

**Verification:** grep / acceptance gate so agent-driven lane identity cannot creep back.

---

## 10. Phased implementation and order

### Phase 1 — Interaction + topology correctness (finish gaps)

1. **Keep** the current interaction model (`editorMode`, overview inspector, focus-first connect) and verify it against §6; do not regress into hidden-mode behavior.
2. **Replace** array-order-as-topology ordering with graph-derived ordering/ranking for projection and layout input.
3. **Finish** the grouped stage editor so it behaves as a progressive editor rather than a tall admin form: keep sectioned editing, collapse advanced by default, and tighten responsive wide vs narrow behavior.

**Exit:** Playwright + manual: add role → add stage → inspector visible; connect + Esc; **empty overview still shows inspector**; no M1 lane without user intent.

### Phase 2 — Renderer replacement: overview / focus / full / layout (structural)

1. Keep **WorkflowProjection** and the current `overview` / `focus` / `full` product shape, but replace the current fixed-geometry renderer inside **`Kit.workflowCanvas`**.
2. Use **graph-derived** column/rank data and one layout/routing pipeline across `overview`, `focus`, and `full`.
3. Reduce lane chrome, simplify overview cards, and enforce the density contract in **§7.6**.
4. Add **fit / zoom / pan / reset** so `full` is a real product view, not a debug map.
5. Keep **focus-first** transition editing and rehearse on **focus** graph.
6. Persist only the editor chrome that is actually needed; do not expand persistence surface just because the plan mentions it.
7. **Software Engineering template** visual + Playwright review before declaring Phase 2 done.

**Exit:** See **§11** (G2, G6).

### Suggested implementation order (within Phase 2)

1. Projection ordering/ranking from real graph structure, not stage array position.
2. Canvas renderer replacement inside the current `workflowCanvas` API.
3. Dense node and edge-label rules for `overview`, `focus`, and `full`.
4. Fit/zoom/pan/reset.
5. Rehearse overlay on focus; full pass on **Software Engineering** template.

### Phase 3 — Dead-code removal and hardening

1. Delete superseded manual geometry / lane-band branches once the new renderer is live.
2. Delete or rewrite tests that assert old renderer behavior rather than product outcomes.
3. Keep one graph path only; no fallback renderer or compatibility layer.

---

## 11. Ship gate (mandatory)

| Gate | Requirement |
|------|----------------|
| **G1** | Phase 1 exit criteria pass. |
| **G2** | Phase 2 exit criteria pass (projection, layout, navigation, terminals). |
| **G3** | Publish uses **strict**; draft vs strict documented for authors. |
| **G4** | Quick-start agent injection remains removed (§9). |
| **G5** | Playwright green on CI with canonical env. |
| **G6** | **Software Engineering** template: **overview** usable without horizontal sprawl; **focus** keeps selected segment readable on one screen; **full** is readable with fit/zoom and no hidden text or pill collisions; **rehearse** overlay works in **focus**; **Playwright** coverage **plus** screenshot/visual review on this template specifically—not “informal visual review” only. |

**No** release of the recovered workflow editor **without G1–G6**.

---

## 12. Subsequent phases (after ship gate)

- Optional persistence expansion for editor-only chrome if needed after the new controls settle.
- Rehearse overlay polish on stable focus graph.
- Optional `protocol-workspace.js` file split.
- E2E expansion (multi-role, conflict tabs, long graphs).

---

## 13. Risks

| Risk | Mitigation |
|------|------------|
| Draft vs strict drift in store | Single validation helper; explicit mode per operation. |
| Mode state regresses to booleans | Central `editorMode`; one render pipeline. |
| New layout path adds another renderer | Keep one `workflowCanvas` API and replace internals in place; no fallback path. |
| Medium workflows still look dense after projection | Enforce §7.6 density contract and make Software Engineering the hard visual gate. |
| **Projection lies** | Boundaries explicit (§7.2); code review + tests on loops, joins, participant changes, terminals. |
| Large-template review becomes subjective | **G6** names template + measurable criteria + Playwright. |
| Editor-only chrome leaks into runtime | Keep it out of semantic workflow fields; strict/runtime ignore it. |

---

## 14. Summary

This plan targets the **real remaining gaps**: projection already exists, but the renderer is still the wrong tool for medium and large workflows. The recovery now centers on **graph-derived ordering**, a **single denser layout/routing pipeline** inside the existing canvas, a **strict node-density contract**, a **usable `full` view**, and a **Software Engineering**-backed ship gate. Execution order: **finish Phase 1 topology/editor correctness** → **Phase 2 renderer replacement and density cleanup** → **Phase 3 dead-code removal** → **G1–G6**. **No** “layout is optional polish,” and **no** return to a single mile-wide canvas for large workflows.

---
