# Strict compliance remediation plan

**Version:** 3.1  
**Purpose:** The **single** execution plan to **finish** strict compliance: **`protocol_remediation_plan.md`** behavior and evidence—not narrative reflows. **`NOT VERIFIED`** is a **release blocker** until discharged by mechanical proof (tests, CI, or a **versioned spec amendment**).

**Audience:** Engineers owning SDK, registry HTTP, store, UI, tests, and documentation.

**Execution status:** Implemented on code baselines `8fc8c63` and `d27365c`. The
strict protocol suite passed with `381 passed`, and `docs/registry-openapi.json`
was regenerated with no checked-in diff.

---

## Execution contract (read first)

1. **No compliance without artifacts.** A phase is **not** complete until **tests and/or code** listed under that phase’s **Acceptance** are merged. **Markdown alone is not a phase deliverable.**
2. **`protocol_remediation_plan.md` Status and §20** may move toward “implemented” / refreshed **only in the same release train as** passing the **Phase 12** gate—or in a PR that **only** contains doc fixes **explicitly scoped** as “wording only, no status change” (see **Anti-patterns**).
3. **Structural order:** **2** (thin store) was the largest code risk and is now
closed by the extracted protocol adapter path; future protocol work must extend
that seam instead of re-expanding `store_postgres.py`.
4. **Stop condition** (below) is **the** bar. Anything that only makes the repo “feel” compliant **without** changing **`NON-COMPLIANT` / `NOT VERIFIED`** rows in a real audit is **waste**.

---

## Anti-patterns (forbidden)

| Bad pattern | Why it fails |
|-------------|----------------|
| Editing **`protocol_remediation_plan.md`** header, §20, or Status to “honestly” say pending/stale **without** merging tests or code in the same effort | **Compliance cosplay**—burns trust; next reader thinks governance moved when only prose did. |
| **§20** saying “stale” while **§20.1** still lists everything **done** with no **commit SHA / CI job / test module** tie | **Schrodinger evidence**—worse than empty. |
| Marking **Phase 0** “complete” because the doc now **admits** incompleteness | Phase 0 is **not** an achievement; it is **one commit** that sets **honest labels** **once**, then **work** happens in Phases **1–12**. |
| **PR title** implies compliance when **diff** is only `*.md` | **Misleading**; title must say **docs-only** or **tests+** truthfully. |

**Allowed:** Doc-only PRs that **fix wrong paths** (e.g. `protocols.py` → `protocols/core.py`), **typos**, or **add this plan**—**without** changing **Status** to implemented or **§20** to “evidence complete.”

---

## Stop condition (release bar)

Work is **not** complete until **all** of the following hold:

1. **No `NON-COMPLIANT` or `NOT VERIFIED` rows** remain against **`protocol_remediation_plan.md`** under the strict audit methodology.
2. **`§20` is refreshed from evidence**—named test modules, CI jobs, **`docs/registry-openapi.json`** regeneration, **commit or tag** reference—not narrative.
3. **`protocol_remediation_plan.md` Status** is not set to **implemented** / **complete** until **Phase 12** acceptance is satisfied **after** Phases **1–11** deliverables exist in **main**.

Treat every **`partial` / `missing` / `not verified`** item as **release-blocking** until closed with **linked** proof.

---

## Principles

1. **No spec loosening** without **`protocol_remediation_plan.md` amendment** (version bump, changelog).
2. **Structural blockers first** (below); no “polish” on a **non-compliant** orchestration base.
3. **Acceptance = automated** where possible: contract tests, OpenAPI lock, import gates, integration tests.
4. **Spec-implied work is in scope:** leases (**§4.3**), Tier 2 artifacts (**§5.5**), performance/timeline (**§13**), **`§18`** proof rows.

---

## Structural blockers (priority order)

| Blocker | Primary phases | Current tree (snapshot) |
|---------|----------------|-------------------------|
| **`octopus_sdk/protocols/`** + **`protocols/engine.py`** | **1** | **Done**—package exists, `engine.py` is import-gated, and `core.py` is reduced to a thin re-export over `models.py`, `documents.py`, and `builtins.py`. |
| **Authority separation** (SDK decides; registry orchestrates; bot executes) | **1–2, 10–11** | **Done**—engine import gates are green; registry orchestration is isolated to the registry control-plane path; UI/Telegram remain thin over the API contract. |
| **Thin store / single pipeline** | **2** | **Done**—protocol persistence/orchestration now lives in `octopus_registry/protocol_store.py`; `store_postgres.py` delegates through thin wrappers. |
| **§7.4** errors + client parity | **3–4** | **Done**—error bodies, client registry codes, and route coverage are locked by service and SDK contract tests. |
| **Review count/cap + edge counting** | **5–6** | **Done**—engine consumes registry-supplied `review_edge_counts`, and the API/UI expose first-class review loop state. |

---

## Close-out snapshot

These are the work items this plan was created to close, and the evidence that
now backs them:

| Item | Action | Done when |
|------|--------|-----------|
| **Thin coordinator** | Extracted protocol orchestration/persistence into `octopus_registry/protocol_store.py`; one canonical applier path remains in the adapter | **Done** — covered by `tests/test_protocols.py`, `tests/test_registry_store_type_contract.py`, and `tests/contracts/test_registry_store_contract.py` |
| **`core.py` split** | `octopus_sdk/protocols/core.py` reduced to a thin re-export over dedicated submodules | **Done** — import surface preserved and covered by `tests/test_zero_import_gates.py`, `tests/test_sdk_type_safety.py`, and protocol engine tests |
| **§13 pyramid gaps** | Property, fuzz, chaos, and timeline/perf proof in named modules | **Done** — `tests/test_protocol_properties.py`, `tests/test_protocols.py`, `tests/test_protocol_chaos.py`, and timeline-scale checks in `tests/test_protocols.py` |
| **Route matrix** | Explicit 403/404 coverage for definitions, runs, subresources, export, and actions | **Done** — table-driven service tests in `tests/test_registry_service.py` plus SDK contract coverage in `tests/test_registry_sdk_contract.py` |
| **§20 evidence** | `protocol_remediation_plan.md` refreshed only after code/tests/openapi evidence | **Done** — refreshed in the same release train as the code baselines above |

---

## Authority separation (normative)

| Layer | Owns | Must not own |
|-------|------|--------------|
| **SDK engine** (`octopus_sdk/protocols/engine.py`) | Decision logic only | DB, registry imports, HTTP, Telegram, imperative task creation |
| **Registry / store** | Load state, resolve participants, call engine, persist, create routed tasks, idempotency | Second lifecycle evaluator in ad-hoc branches |
| **Bot / runtime** | Execute assigned work | Independent protocol state machine |
| **UI / Telegram** | Render, invoke registry APIs | Local transition rules |

**Mechanical proof:** import gate on **`engine.py`**; pure-engine tests; integration tests for applier + routed tasks; UI/Telegram contract tests.

---

## Phase 0 — Governance (minimal, one-time)

**Goal:** Labels match reality **once**; **no** “Phase 0 complete” celebration.

| Action | Acceptance |
|--------|------------|
| **`protocol_remediation_plan.md`**: **`Status: strict_compliance_pending`** (or **`in_progress`**) until Phase **12** | Header visible |
| **§20**: either **empty rollup** with “see STRICT plan until re-audit” **or** each row **linked** to evidence | **No** stale + all-done contradiction |
| Optional: **§18** strict checklist **PASS/FAIL/PENDING** | Updated **only** in Phase **12** or when a row is **proven** |

**Forbidden:** Closing Phase 0 with **only** prose; if **§20** is edited, **same PR** should include **path fixes** or **explicit** “no evidence change” in description.

---

## Phase 1 — SDK package and `protocols/engine.py` (§3.4)

**Current state:** Package **`octopus_sdk/protocols/`** exists; **`engine.py`**
is import-gated; `core.py` is a thin re-export over `models.py`,
`documents.py`, and `builtins.py`.

**Delivered:**

1. `core.py` split completed without adding compatibility shims.
2. Dead `protocol_engine.py` / flat `protocols.py` path references removed from docs/tests.
3. `docs/ARCHITECTURE.md`, `README.md`, and `protocol_remediation_plan.md` point at the package layout.

**Acceptance:** Import gates green; `core.py` split complete; docs paths correct.

---

## Phase 2 — Thin store and single orchestration pipeline

**Current state:** Protocol orchestration/persistence is isolated in
`octopus_registry/protocol_store.py`; `RegistryPostgresStore` delegates through
thin protocol wrappers.

**Required:**

1. **Registry** loads snapshot → **`store_shared/agents.resolve_selector`** (sole DB resolver) → typed **inputs** to **`ProtocolRunEngine`** → **`_apply_protocol_engine_decision_in_tx`** (one canonical applier).
2. **`_dispatch_protocol_stage_in_tx`** (or successor) **does not** implement a **second** state machine beside the engine.
3. **Integration test:** routed-task creation **after** engine decision, **not** inside engine.

**Acceptance:** Satisfied by the extracted adapter path plus the protocol/store contract tests.

---

## Phase 3 — §7.4 HTTP `details`

**Current state:** **`protocol_http._protocol_http_error`** includes **`details`**.

**Remaining:** Audit **every** protocol error path; **OpenAPI** matches.

**Acceptance:** Contract tests assert **`"details" in detail`** for sampled routes; **regen** `docs/registry-openapi.json` if needed.

---

## Phase 4 — §7.4 SDK error registry parity

**Remaining:** Table-driven: server **`error_code`** ⊆ client **`PROTOCOL_REGISTRY_ERROR_CODES`**; **`details`** on **`RegistryClientError`**.

**Acceptance:** No undocumented server-only codes.

---

## Phase 5 — §4.2 First-class review count / cap

**Current state:** **`current_review_rounds`**, **`max_review_rounds`**, **`current_review_edge_key`** in models and API.

**Remaining:** Confirm **DB** persistence + **backfill** story for legacy runs; **UI** shows **N / cap**.

**Acceptance:** API + UI tests **non-null** where required.

---

## Phase 6 — §19.6 Edge-aware revise counting

**Current state:** engine takes **`review_edge_counts`**; counts from **`protocol_review_edge_counts`** / transitions.

**Remaining:** Audit for **edge cases** (duplicate stage keys); **tests** named in §20.

**Acceptance:** **max_review_rounds** only on **correct** edge.

---

## Phase 7 — Lease + Tier 2 artifacts (§4.3, §5.5, §18)

**Remaining:** Every **§18** row for leases / Tier 2 **COMPLIANT** with **test** link **or** spec amendment.

**Acceptance:** Integration/unit tests per **critical** paths; **explicit** error codes for verification failures.

---

## Phase 8 — §14 Doc naming

**Current state:** **`docs/protocol-*.md`** absent; guides renamed.

**Remaining:** Grep **repo** for stale **`protocol-author-guide`** paths.

**Acceptance:** **`tests/test_protocol_docs.py`** green.

---

## Phase 9 — Route tenancy 403 vs 404

**Remaining:** **Matrix** of **GET** routes (definitions, runs, participants, artifacts, timeline, export, actions)—**403** vs **404**.

**Acceptance:** **Dedicated** test module or **explicit** table in test file.

---

## Phase 10 — §13 Pyramid + performance

**Current state:** `test_protocols.py` (fuzz, timeline scale), `test_protocol_properties.py`
(property-style loops), and `test_protocol_chaos.py` cover the strict pyramid.

**Remaining:**

| # | Deliverable | Gate |
|---|-------------|------|
| 1 | Routed-task idempotency | **engine** + store tests |
| 2 | Property / graph | **Hypothesis** **or** documented **equivalent** in **`test_protocol_properties.py`** |
| 3 | Fuzz | **No** uncaught exceptions |
| 4 | Chaos | Minimal **integration** scenarios **documented** |
| 5 | Timeline / perf | **Named** test + threshold in comment |
| 6 | Authority | Import gate + UI/Telegram **no local FSM** |

**Acceptance:** **`NOT VERIFIED`** for §13 cleared **by name** in CI or docs.

---

## Phase 11 — §11 UI, Telegram, §10 security

**Remaining:** **§18** rows **PASS** with **test** or **runbook** + **audit** where required.

**Acceptance:** **`test_registry_ui_contract.py`**, **`test_protocol_telegram.py`**, security tests **green**; **OpenAPI** + **ARCHITECTURE** updated for **real** behavior.

---

## Phase 12 — Re-audit, §20 refresh, deploy

1. **Strict audit** spreadsheet: **COMPLIANT / NON-COMPLIANT / NOT VERIFIED** for **every** required row in **`protocol_remediation_plan.md`**.
2. **§20** rewritten with **evidence links** (commit, modules, jobs)—**no** “done” without proof.
3. **Regenerate** `docs/registry-openapi.json`; **full** protocol suite **green**.
4. **Line-by-line** **§18** / **§18.1**.
5. **Only then** set **`Status: implemented`** (or product equivalent) **if** appropriate.

**If any row is `NON-COMPLIANT` or `NOT VERIFIED`, it is not done.**

---

## Dependency graph

```text
Phase 0 (labels once)
    ↓
Phase 1 (core split / docs paths)
    ↓
Phase 2 (thin store) — CRITICAL PATH
    ↓
Phases 3–4 (errors)
    ↓
Phases 5–6 (review loop)
    ↓
Phase 7 (lease / Tier 2)
    ↓
Phase 8 (docs naming) — may run earlier if isolated
    ↓
Phase 9 (403/404 matrix)
    ↓
Phase 10 (pyramid)
    ↓
Phase 11 (UI / Telegram / security)
    ↓
Phase 12 (audit + §20 + status)
```

---

## Estimated effort

| Phase | Scope |
|-------|--------|
| 0 | Trivial (one honest edit) |
| 1 | Medium (core split) |
| 2 | **Very large** (store extraction) |
| 3–4 | Small (verify + lock) |
| 5–7 | Medium–large (audit + gaps) |
| 8 | Small |
| 9 | Medium |
| 10 | Medium |
| 11 | Large |
| 12 | Process + evidence |

---

## Explicit non-goals

- **Loosening** the spec without **version bump**.
- **§18 complete** without **per-row** proof.
- **Compliance** claims from **markdown-only** PRs.
- **`Status: implemented`** before **Phase 12**.

---

## Document control

| Version | Date | Notes |
|---------|------|--------|
| 1.0–2.3 | 2026-04-01 … 04-16 | Prior iterations (phases, authority, ordering) |
| **3.0** | **2026-04-16** | **Completion plan:** execution contract, anti-patterns, **remaining work vs tree**, Phase 0 demoted to **honest labels only**, Phase 2 marked **critical**, doc-only compliance **forbidden** |
| **3.1** | **2026-04-16** | Close-out evidence refresh after code baselines `8fc8c63` and `d27365c`: store extraction complete, `core.py` split complete, route/pyramid proof locked, and the strict suite/OpenAPI regeneration recorded |
