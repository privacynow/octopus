# Strict compliance remediation plan

**Version:** 2.3  
**Purpose:** The **single** execution plan for strict compliance: bring the repository into **strict** alignment with **`protocol_remediation_plan.md`** as normative spec—not reinterpretation. **`NOT VERIFIED` is treated as a release blocker** until discharged by mechanical proof (tests, CI gates, or spec amendment with explicit version bump).

**Audience:** Engineers owning SDK, registry HTTP, store, UI, tests, and documentation.

---

## Stop condition (release bar)

Work is **not** complete until **all** of the following hold:

1. **No `NON-COMPLIANT` or `NOT VERIFIED` rows** remain against **`protocol_remediation_plan.md`** under the strict audit methodology (same **COMPLIANT / NON-COMPLIANT / NOT VERIFIED** discipline).
2. **`§20` is refreshed from evidence**—tests, CI, docs, **`docs/registry-openapi.json`**, live checks—not optimism or narrative.
3. **Status** in **`protocol_remediation_plan.md`** is not flipped to “implemented” / “complete” until **Phase 12** acceptance is satisfied.

Treat every **`partial` / `missing` / `not verified`** item in the plan and matrices as **release-blocking** until closed with linked proof.

---

## Principles

1. **No spec loosening** in the same release as fixes unless **`protocol_remediation_plan.md` is amended** (version bump, changelog entry, §20 honesty until bars pass).
2. **One vertical slice per phase** where possible; **structural blockers** (below) must land before polishing on a non-compliant base.
3. **Acceptance = automated** where the spec allows: contract tests, OpenAPI diff, import gates, targeted integration tests.
4. **Spec-implied work is in scope:** lease semantics (**§4.3**), Tier 2 artifacts (**§5.5**), performance/timeline bars (**§13** and **`protocol_remediation_plan.md`** performance/testing sections), and **`§18`** proof rows are **not** optional add-ons—they must appear in this plan explicitly or the plan is underspecified.

---

## Structural blockers (priority order)

These must be planned and executed deliberately:

| Blocker | Primary phases |
|---------|----------------|
| **`octopus_sdk/protocols/`** package + **`protocols/engine.py`** (§3.4) | **1** |
| **Authority separation stays real** (SDK decides, registry orchestrates, bot executes, UI/Telegram surface only) | **1–2, 10–11** |
| **Thin store / single orchestration pipeline** (`store_postgres` coordinator, resolver in **`store_shared/agents.py`**, one applier path—not cosmetic) | **2** |
| **§7.4** stable error body + **SDK/server code-set parity** | **3–4** |
| **First-class review count/cap** then **edge-aware revise counting** | **5–6** |

---

## Authority separation (normative)

Strict compliance requires a **clean authority split**. This is not optional implementation style; it is the architectural rule that keeps “engine in SDK” from turning into “SDK orchestrates the system.”

| Layer | Owns | Must not own |
|-------|------|--------------|
| **SDK engine** (`octopus_sdk/protocols/engine.py`) | **Decision logic only**: protocol validation support, dispatch evaluation, task-result evaluation, operator-action evaluation, timeout evaluation, policy enforcement, typed decision records | DB access, connected-agent lookup, HTTP/Telegram concerns, routed-task creation side effects, registry persistence, provider execution |
| **Registry / store** (`octopus_registry/...`) | **Orchestration authority**: load state, resolve participants from registry truth, call engine, persist through one applier path, create routed tasks, emit events after commit, enforce idempotency / transaction boundaries | Re-implement protocol lifecycle decisions already owned by the engine, maintain a second evaluator in store branches |
| **Bot / runtime** (`app/...`) | **Execution only**: run assigned work, collect outputs / artifact observations, report routed-task results | Independent protocol lifecycle evaluation, stage advancement, participant resolution |
| **UI / Telegram surfaces** | Render state, invoke registry APIs, observe outcomes | Local lifecycle evaluation, local transition rules, direct protocol state mutation outside registry APIs |

**Normative rules:**

1. **The SDK engine must be testably pure.** It may import `octopus_sdk.protocols.*` models/helpers, but it must not import `octopus_registry`, `app`, Telegram modules, DB drivers, or HTTP frameworks.
2. **Participant resolution is a registry-side port.** The engine consumes a typed resolution result or resolver callback contract supplied by the registry; it must not discover connected agents itself.
3. **Routed-task creation is registry-side.** The engine may return a routed-task request specification, but task creation, persistence, and event emission remain registry responsibilities.
4. **No second lifecycle evaluator may exist in UI, Telegram, or bot runtime.** Those surfaces may display, invoke, and execute, but they may not decide transitions independently.

**Mechanical proof requirements (covered in later phases):**

- Import-boundary tests or gates proving the engine does not depend on registry/runtime modules.
- Pure-engine unit tests using in-memory models only.
- Integration proof that routed-task creation happens through the registry orchestration/applier path, not as an engine side effect.
- Contract/integration proof that UI and Telegram cannot mutate protocol state except through registry endpoints.

---

## Phase 0 — Governance and status honesty

**Goal:** Reset false completion claims; align **`protocol_remediation_plan.md`** with strict compliance reality.

| Action | Owner | Acceptance |
|--------|--------|------------|
| Set **`Status`** to **`in_progress`** or **`strict_compliance_pending`** (not broad “implemented”). | Docs + eng lead | Visible in plan header. |
| Mark **`§20` as stale** (banner + date): evidence must be re-proven before trust. | Docs | Readers do not assume §20 reflects strict pass/fail. |
| Add or extend **§20.x** (or equivalent) **strict checklist** with **PASS / FAIL / PENDING** per §18 line item; update **only** when **Phase 12** criteria are met. | Docs + eng | Plan truth matches CI gates. |
| Optional: **`STRICT_COMPLIANCE.md`** or **CI** that fails if required §18 rows are **PENDING** for release. | Infra | Documented gate. |

**Do not** delete §20 evidence tables—**annotate** where needed: **narrow (product) vs strict spec** completion.

---

## Phase 1 — SDK layout: `octopus_sdk/protocols/` package and `protocols/engine.py` (§3.4)

**Problem:** The spec names **`octopus_sdk/protocols/engine.py`**. Today **`octopus_sdk/protocols.py`** is a **file**, and **`octopus_sdk/protocol_engine.py`** is a **sibling module**. Python cannot have both **`protocols.py`** and **`protocols/`** on disk.

**Target layout (minimal spec compliance):**

```text
octopus_sdk/protocols/
  __init__.py          # Public re-exports matching former octopus_sdk.protocols surface
  engine.py            # ProtocolRunEngine (moved from protocol_engine.py)
  bootstrap.py         # Optional: move from protocol_bootstrap.py OR re-export only
  ...                  # Split former protocols.py into cohesive modules (not one giant __init__)
```

**Steps (order matters):**

1. **Inventory** every `from octopus_sdk.protocols import ...` and `import octopus_sdk.protocols` across repo (grep + **`tests/test_zero_import_gates.py`**).
2. **Create package** `octopus_sdk/protocols/`:
   - **Split** current **`protocols.py`** into real submodules (e.g. `models.py`, `definitions.py`, `validation.py`, `builtins.py`, `text.py`) **or** a **staged internal migration**:
     - **Stage A:** `protocols/_legacy.py` (verbatim move) + **`__init__.py`** re-exports to unblock.
     - **Stage B:** split `_legacy.py` into proper modules **before** any final strict compliance claim.
3. **Move** `ProtocolRunEngine` and **`DEFAULT_PROTOCOL_RUN_ENGINE`** from **`protocol_engine.py`** → **`protocols/engine.py`**.
4. **Delete** **`octopus_sdk/protocol_engine.py`** after imports point at **`octopus_sdk.protocols.engine`** or **`protocols/__init__.py`** re-exports.
5. **Handle `protocol_bootstrap.py`:** prefer **`protocols/bootstrap.py`** + re-export, or a minimal root **`protocol_bootstrap.py`** that imports from the package only if the spec allows.
6. **Remove** the old **`octopus_sdk/protocols.py`** file once imports resolve.
7. **Run** full test suite + **`tests/test_zero_import_gates.py`** + packaging smoke.
8. Add or extend **import-boundary tests** so **`octopus_sdk/protocols/engine.py`** cannot import registry, runtime, Telegram, DB-driver, or HTTP-framework modules.

**Staging vs shims (normative):**

- **Temporary internal staging** (e.g. `_legacy` split) is an **implementation tactic** and is acceptable **if** it is **removed or fully absorbed** before claiming strict compliance.
- **No long-lived public compatibility shim** (e.g. old module path re-exporting forever) as a substitute for the **`protocols/`** package.

**Acceptance:**

- `import octopus_sdk.protocols` resolves to **package**.
- **`octopus_sdk/protocols/engine.py`** exists and contains **`ProtocolRunEngine`**.
- Import-boundary gates prove the engine remains **decision-only** per **Authority separation**.
- Docs updated: **`docs/ARCHITECTURE.md`**, **`protocol_remediation_plan.md` §20.2**, **`README.md`**.
- **§3.4** literal path satisfied.

**Risk:** Large diff; prefer **one mechanical PR** where possible; follow with a second PR for Stage B if needed.

---

## Phase 2 — Thin store coordinator and single orchestration pipeline

**Problem:** **`octopus_registry/store_postgres.py`** is not yet a **thin coordinator**: **`_dispatch_protocol_stage_in_tx`** and related paths can still own **too much lifecycle branching** in parallel with the engine. Strict compliance requires **one orchestration seam**: load snapshot → resolve participants → **single engine decision shape** → **one canonical persist path** (e.g. **`_apply_protocol_engine_decision_in_tx`**).

**Rules:**

- Keep **DB-backed participant resolution** in **`octopus_registry/store_shared/agents.py`** as the **sole** resolver pattern (no duplicate resolution logic in ad-hoc store methods).
- **`RegistryPostgresStore`** is the **sole orchestration authority**: load snapshot → call resolver → pass **typed resolution result** into **`ProtocolRunEngine`** → persist **only** through the **canonical applier**.
- **`_dispatch_protocol_stage_in_tx`** must **not** be the place where unrelated lifecycle branches diverge (routed-task creation, next-stage creation, timeout outcomes, operator outcomes should all flow from the **same engine decision record** and the **same persist path**).
- The engine may return a **routed-task request spec**, but **task creation** itself remains a **registry-side** action executed after the orchestration/apply path determines it should occur.

**Acceptance:**

- Architecture note or code comments + review sign-off documenting the **one** decision record type and **one** applier entry.
- Architecture note or code comments explicitly state **registry orchestrates, SDK decides, bots execute**.
- No parallel ad-hoc `UPDATE` paths on protocol tables for the same concern without justification tracked in **`protocol_remediation_plan.md`** or this plan.
- Integration proof that routed-task creation occurs through the registry path and not by imperative engine side effect.

**Dependency:** **Phase 1** (stable **`protocols/engine.py`** import path).

---

## Phase 3 — §7.4 HTTP error body shape (`details`)

**Problem:** Stable JSON includes **`details`** alongside **`error_code`** and **`message`**. **`octopus_registry/protocol_http.py`** must not emit two-key bodies only.

**Steps:**

1. **`_protocol_http_error`** (and any protocol **`HTTPException`** detail dicts) emit:

   ```json
   { "error_code": "...", "message": "...", "details": null | object | array }
   ```

   **`details` always present**—match **`protocol_remediation_plan.md` §7.4** literally (`null` or **`{}`** if empty).

2. Update **`tests/test_registry_service.py`** and protocol HTTP tests: assert **`"details" in body`**.
3. Regenerate **`docs/registry-openapi.json`** if error schemas are documented.

**Acceptance:** Every protocol route error response includes **`details`** per §7.4.

---

## Phase 4 — §7.4 SDK error registry vs server emission

**Problem:** Spec lists codes such as **`LEASE_HELD`**, **`MAX_REVIEW_ROUNDS_EXCEEDED`**, **`ARTIFACT_VERIFICATION_FAILED`**, **`CONCURRENT_MODIFICATION`**, **`IDEMPOTENCY_REPLAY`**. **`octopus_sdk/registry/client.py`** must cover **every** code the server emits; names must not drift (**`IDEMPOTENCY_REPLAY`** vs **`IDEMPOTENCY_CONFLICT`**).

**Decision (pick one, document in plan amendment if behavior changes):**

- **Option A (spec-first):** Server + client use **`IDEMPOTENCY_REPLAY`** (or whichever **`protocol_remediation_plan.md` §7.4** freezes).
- **Option B:** Amend §7.4 to canonicalize **`IDEMPOTENCY_CONFLICT`**—**requires versioned plan edit**.

**Steps:**

1. **Freeze canonical set** in **`protocol_remediation_plan.md` §7.4** (single table).
2. Extend **`ProtocolRegistryErrorCode`** / **`PROTOCOL_REGISTRY_ERROR_CODES`** to full parity.
3. **`protocol_http.py`** and store paths emit **`error_code`** only from that set.
4. **Preserve `details` end-to-end** on **`RegistryClientError`** (or equivalent) for clients.
5. **Table-driven tests:** known failure paths → HTTP JSON **`error_code`** ∈ client set.

**Acceptance:** No server-only undocumented codes; client recognizes all protocol failures.

---

## Phase 5 — §4.2 First-class review-loop count vs cap (API + UI)

**Problem:** Spec requires **explicit** **current** revise-loop count and **cap** (`max_review_rounds`). Client-side derivation from stage rows alone is **not** strict compliance.

**Fields (names may follow product/OpenAPI but must be first-class):** e.g. **`current_review_rounds`** and **`max_review_rounds`** (or **`review_loop_current` / `review_loop_cap`**—keep **one** consistent pair in OpenAPI).

**Data model:**

- Extend **`ProtocolRunRecord`** / **`ProtocolRunDetailRecord`** (or nested object) with authoritative integers.
- **Persistence:** DB columns or JSON keyed by edge id—**single source of truth** for API responses.
- Include a **live-data migration/backfill** step for existing runs so rollout does not depend on nullable legacy behavior after the schema changes land.

**Steps:**

1. Schema migration if needed.
2. **SDK** models + **OpenAPI** regeneration.
3. **Store:** populate on relevant transitions; **GET** run detail returns fields.
4. **UI:** **`protocol-workspace.js`** — visible **N / cap** where spec requires.
5. **Tests:** non-null integers and consistency after revise transitions.

**Ordering:** Implement **Phase 5 before Phase 6**. Phase 5 establishes the contract surface and schema first; Phase 6 then updates engine semantics to use that authoritative shape.

---

## Phase 6 — §19.6 Revise-edge counting (engine)

**Problem:** Engine must not rely on **same `stage_key` + completed `revise`** heuristics alone. Counting must tie to the **revise edge** in the graph.

**Design:**

1. Identify **edge** in definition (e.g. `(from_stage_key, decision, to_stage_key)` for **revise**).
2. **Persist** counter per edge or **`loop_id`** in run/execution/transition state (**Phase 5** schema).
3. **Increment** only when **traversing** that **revise** edge.
4. **`ProtocolRunEngine.evaluate_task_result`:** enforce **`policies.max_review_rounds`** using **edge-based** count supplied in the registry-loaded evaluation input.

**Steps:**

1. Metadata for stage executions / transitions (e.g. **`revise_edge_id`**, **`parent_transition_id`**).
2. Extend the engine input shape so the registry/store provides the engine with the **transition history snapshot**, explicit **edge counters**, or equivalent derived loop metadata needed for evaluation.
3. Replace heuristic **`revise_count`** in **`octopus_sdk/protocols/engine.py`** (post–Phase 1 path) with **edge-aware** evaluation over those **registry-supplied inputs**; the engine must **not** open DB connections or perform persistence reads itself.
4. **Tests:** graphs where the same **`stage_key`** appears twice must not conflate counts.

**Acceptance:** **max_review_rounds** fires only when the **correct** edge exceeds cap.

---

## Phase 7 — Lease lifecycle + Tier 2 artifact semantics (§4.3, §5.5, §18)

**Problem:** These are **spec-required** (**§4.3**, **§5.5**, **§18**). The codebase must implement and **prove** full lease behavior and Tier 2 artifact rules where the normative plan demands them.

**Lease (§4.3):** Acquire, renew, expire, admin break, restart behavior—**engine + store path**, with errors wired to **Phase 3–4** codes where applicable.

**Tier 2 artifacts (§5.5):** Content sampling policy, size limits, binary vs text handling, **explicit verification failure codes**—implemented in the **shared protocol contract** and enforced consistently in engine/store.

**Acceptance:**

- Integration (and/or unit) tests per **critical** lease transitions and artifact violation paths.
- **`protocol_remediation_plan.md`** / **`§18`** rows for these topics can move to **COMPLIANT** only with **linked tests** (and docs where the spec requires operator visibility).

**Dependency:** **Phases 2–4** (store/engine/error surfaces).

---

## Phase 8 — §14 Documentation naming

**Problem:** Spec forbids **`docs/protocol-*.md`**; repo may still ship forbidden filenames.

**Target names (examples):**

| Current | New (suggested) |
|---------|------------------|
| `docs/protocol-author-guide.md` | `docs/author-protocol-guide.md` |
| `docs/protocol-operator-guide.md` | `docs/operator-protocol-guide.md` |

**Steps:** `git mv`, update **`README.md`**, **`docs/ARCHITECTURE.md`**, **`docs/telegram-user-guide.md`**, **`docs/registry-user-guide.md`**, **`protocol_remediation_plan.md` §20**, **`tests/test_protocol_docs.py`**, grep for old paths.

**Acceptance:** Zero **`docs/protocol-*.md`** paths; contract tests green; **§14** satisfied by **fixing the repo**, not deleting the requirement.

**Timing (execution preference, not substance):** Run **early** (e.g. after Phase 1) if renames are **isolated**, or **late** before **Phase 12** to reduce churn while code moves. **Either is fine** if finished before any strict compliance claim.

---

## Phase 9 — Route-level tenancy and error semantics (403 vs 404)

**Problem:** Broad integration coverage alone is not enough—**explicit** tests are required for visibility vs existence on each surface.

**Requirement:**

- **GET** routes for definitions, runs, **participants, artifacts, timeline, export**, and **operator/action** endpoints (as applicable) must return **`403`** with **`PROTOCOL_NOT_VISIBLE`** (or spec-equivalent) when **visibility denies access**, and **`404`** only when the **resource id does not exist** for the tenant context.

**Acceptance:**

- Dedicated tests (module or markers) covering **subresources**, not only **`GET /v1/protocol-runs/{id}`**.
- Documented in CI / **`pytest.ini`** if split from default run.

**Dependency:** **Phases 3–4** (stable error JSON for assertions).

---

## Phase 10 — §13 Test pyramid + timeline / performance

**Purpose:** Mechanical proof layer. This phase proves boundaries, contracts, and invariants with automated tests. It does **not** replace the fuller product/spec verification required in **Phase 11**.

**Minimum deliverables (each **CI-gated** or explicitly documented if nightly):**

| # | Requirement | Approach |
|---|-------------|----------|
| 1 | **Duplicate routed-task result idempotency** | **Pure engine** case in **`tests/test_protocol_engine.py`** where applicable; plus store/integration as needed. |
| 2 | **Property-based graph** | Hypothesis (or similar): valid graphs → `validate_protocol_document` + reachability + no orphans; **no crash**. |
| 3 | **Fuzz** | `validate_protocol_document` / JSON loader with bounded random dicts; **no uncaught exception**. |
| 4 | **Chaos** (minimal) | Duplicate concurrent POSTs, stale idempotency, lease expiry, registry interruption—**documented** scenarios. |
| 5 | **Timeline / performance** | At least one **protocol timeline** (or equivalent hot path) check: e.g. p95 budget, large-N fixture—threshold recorded in test comment + **§20** evidence. |
| 6 | **Import / authority boundary** | Engine import-gate test; UI/Telegram/runtime integration or contract tests proving they do **not** evaluate lifecycle locally and can only mutate through registry APIs. |

**Steps:**

1. Dev dependencies (`hypothesis`, etc.) justified in **`pyproject.toml`** / requirements.
2. New modules under **`tests/`** with markers as needed.
3. **§13** and performance bars in **`protocol_remediation_plan.md`** cited in **`§20`** when cleared.
4. Add explicit **authority-separation** coverage: pure-engine tests with in-memory models only; integration proof that UI/Telegram/bot runtime do not own protocol transitions.

**Acceptance:** **`NOT VERIFIED`** for §13/performance rows cleared with **named** tests.

---

## Phase 11 — §11 UI, §11 Telegram, §10 security / ops

**Purpose:** Full product/spec proof layer. This phase uses the mechanics established in **Phase 10**, but closes the higher-level **§11**, **§10**, and **§18** evidence bars that require surface-level and operational verification.

**These remain failing until discharged by explicit evidence.**

| Track | Evidence required |
|-------|-------------------|
| **§11 UI** | **`tests/test_registry_ui_contract.py`**: no advisory controls where forbidden; review **count/cap** visibility; conflict/error display matches HTTP contract; deep links and confirmations where required; controls in **`protocol-workspace.js`** wired to real backend behavior. |
| **§11 Telegram** | **`tests/test_protocol_telegram.py`**: parity with HTTP/command contract; rate limiting / debouncing where spec requires. |
| **§10** | **Path traversal** tests on artifact paths; **redaction** of sensitive fields; **export-role** enforcement; **cross-tenant** access denial; **timeout / maintenance** behavior; updates to **`docs/ARCHITECTURE.md`**, renamed protocol guides, and **`docs/registry-openapi.json`**. |

**§18 / §18.1:** Per-row **PASS** only with linked test or doc; **§18.1(3)(7)** no advisory UI—audit or automation as needed.

**Acceptance:** Evidence pack or **§20** checklist entries **PASS** for these tracks.

**Dependency:** **Phases 5–7, 9–10** as applicable (API fields, errors, routes).

---

## Phase 12 — Re-audit, §20 refresh, OpenAPI, deploy

1. **Strict audit** of **`protocol_remediation_plan.md`**: **COMPLIANT / NON-COMPLIANT / NOT VERIFIED**—**no** row left **`NON-COMPLIANT`** or **`NOT VERIFIED`** unless the spec is **explicitly amended** with version bump.
2. **Refresh `§20` from the actual tree**: test module names, CI job names, commit or date stamp for evidence—**not** narrative optimism.
3. **Regenerate `docs/registry-openapi.json`**; snapshot or diff test if used.
4. **Run full protocol / strict suite**; fix failures until green.
5. **Deploy** per team process; record in runbook or release notes.
6. **Line-by-line pass** over **§18** and **§18.1** with evidence links.
7. **Only then** set **`protocol_remediation_plan.md` Status** to an **implemented** variant if appropriate.

**If any required row is still `NON-COMPLIANT` or `NOT VERIFIED`, it is not done.**

---

## Dependency graph (summary)

```text
Phase 0 (governance)
    ↓
Phase 1 (SDK package + engine path)
    ↓
Phase 2 (thin store / single pipeline)
    ↓
Phase 3 (HTTP details) ──→ Phase 4 (error codes); preserve details E2E
    ↓
Phase 5 (count/cap contract) ──→ Phase 6 (edge-aware counting)
    ↓
Phase 7 (lease + Tier 2)
    ↓
Phase 8 (doc rename) ── may run earlier if isolated (see Phase 8)
    ↓
Phase 9 (route 403/404)
    ↓
Phase 10 (pyramid + timeline)
    ↓
Phase 11 (UI / Telegram / security)
    ↓
Phase 12 (close-out)
```

**Note:** **Phase 8** can slide earlier in the calendar (after **1**) without changing the **logical** dependency on “rename done before compliance claim.”

---

## Estimated effort (order of magnitude)

| Phase | Scope |
|-------|-------|
| 0 | Small |
| 1 | Large (import churn) |
| 2 | Large (store architecture) |
| 3–4 | Medium |
| 5–6 | Large (schema + engine + UI) |
| 7 | Medium–large (semantics + tests) |
| 8 | Small |
| 9 | Medium (breadth of routes) |
| 10 | Medium–large (CI time) |
| 11 | Large |
| 12 | Small–medium (process + gates) |

---

## Explicit non-goals

- **Loosening** §7.4, §14, or §3.4 without a **versioned plan amendment**.
- **Marking §18 complete** without a **per-criterion** proof row.
- **Claiming strict compliance** while **internal `_legacy` staging** (Phase 1) remains the long-term public structure—finish **Stage B** or equivalent first.

---

## Document control

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-04-01 | Initial strict compliance fix plan from audit |
| 2.0 | 2026-04-01 | Expanded phases (thin store, lease/Tier 2, routes, perf, close-out); stop condition; staging vs shim |
| 2.1 | 2026-04-01 | Single consolidated plan: removed dual-plan framing |
| 2.2 | 2026-04-16 | Added explicit SDK/registry/bot authority split, import-boundary requirements, and authority-separation test/proof gates |
| 2.3 | 2026-04-16 | Clarified Phase 5→6 ordering, engine input boundaries, live-data backfills, structural blocker visibility, and Phase 10 vs 11 proof roles |
