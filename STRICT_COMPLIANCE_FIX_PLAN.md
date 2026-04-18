# Strict compliance remediation plan

**Document type:** **Frozen close-out record** (not a live execution backlog).  
**Version:** 3.2  

**Purpose:** Preserve **what was done**, **why**, and **where the evidence lived** for the strict-compliance push that landed the extracted protocol adapter, the `octopus_sdk/protocols/` package split, and the associated test pyramid. For **current** product status and normative rules, use **`protocol_remediation_plan.md`**.

---

## Evidence as of (snapshot—not timeless)

| Field | Value |
|-------|--------|
| **Date** | 2026-04-16 |
| **Referenced commits** | `8fc8c63`, `d27365c` (strict-compliance close-out train) |
| **Test run** | Strict protocol suite: **381 passed** (snapshot at close-out; re-run after major changes) |
| **OpenAPI** | `docs/registry-openapi.json` regenerated with **no checked-in diff** at that snapshot |
| **Product plan** | **`protocol_remediation_plan.md`** set to **`Status: implemented`** in the same release narrative (see that file for current header) |

**Do not** treat pinned commits or pass counts as **permanent** proof without re-running tests. They document **what was verified at close-out**.

---

## Terminology: protocol persistence shape

Do **not** describe the outcome as a “thin store” in the sense of a tiny file. The result is:

- **`octopus_registry/protocol_store.py`** — **extracted bounded adapter**: dedicated protocol persistence and orchestration logic (a **large** module by line count; **bounded** by domain).
- **`octopus_registry/store_postgres.py`** — **delegates** protocol work through that adapter instead of embedding all protocol SQL and branching in one omnibus class.

So: **extracted protocol adapter / dedicated protocol persistence module**, not “thin” in the sense of small.

---

## What this close-out established (structural)

| Blocker (original plan) | Outcome |
|-------------------------|---------|
| **`octopus_sdk/protocols/`** + **`protocols/engine.py`** | **Closed** — package layout, **`engine.py`** import-gated; **`core.py`** reduced to a thin re-export over **`models.py`**, **`documents.py`**, **`builtins.py`**. |
| **Authority separation** | **Closed** — SDK engine remains decision-only; registry owns orchestration; proof via import gates and contract tests. |
| **Single pipeline / extracted adapter** | **Closed** — protocol orchestration and persistence live in **`protocol_store.py`**; **`RegistryPostgresStore`** uses thin delegating wrappers. |
| **§7.4** errors + client parity | **Closed** — stable error bodies and client code sets locked by service/SDK tests at evidence date. |
| **Review count/cap + edge counting** | **Closed** — registry-supplied **`review_edge_counts`**, first-class API fields, tests at evidence date. |

---

## Close-out evidence table

Work items from the original plan and where they were backed at close-out:

| Item | Resolution | Evidence (see snapshot date above) |
|------|------------|-------------------------------------|
| **Extracted protocol adapter** | Orchestration/persistence in **`octopus_registry/protocol_store.py`**; canonical applier path in the adapter layer | `tests/test_protocols.py`, `tests/test_registry_store_type_contract.py`, `tests/contracts/test_registry_store_contract.py` |
| **`core.py` split** | Thin re-export; submodules hold models/documents/builtins | `tests/test_zero_import_gates.py`, `tests/test_sdk_type_safety.py`, `tests/test_protocol_engine.py` |
| **§13 pyramid** | Property-style, fuzz, chaos, timeline | `tests/test_protocol_properties.py`, `tests/test_protocols.py`, `tests/test_protocol_chaos.py` |
| **Route matrix (403/404)** | Table-driven / contract coverage | `tests/test_registry_service.py`, `tests/test_registry_sdk_contract.py` |
| **§20 refresh** | **`protocol_remediation_plan.md`** updated in same train as code | That document’s §20 and document control |

---

## Authority separation (normative — still valid)

These rules remain **engineering law** for future changes; they are not “done” in the sense of never touching code again—they constrain **how** future protocol work is allowed to land.

| Layer | Owns | Must not own |
|-------|------|--------------|
| **SDK engine** (`octopus_sdk/protocols/engine.py`) | Decision logic only | DB, registry imports, HTTP, Telegram, imperative task creation |
| **Registry / adapter** (`protocol_store.py`, store) | Load state, resolve participants, call engine, persist, routed tasks, idempotency | Second lifecycle evaluator beside the engine |
| **Bot / runtime** | Execute assigned work | Independent protocol state machine |
| **UI / Telegram** | Render, invoke registry APIs | Local transition rules |

**Mechanical proof at close-out:** import gate on **`engine.py`**; pure-engine tests; integration tests for applier + routed tasks; UI/Telegram contract tests.

---

## Phase-by-phase record (closed)

Below is **what was delivered** for each phase of the original numbered plan. **No “Remaining”** open items—anything still vague at close-out was either completed or folded into **`protocol_remediation_plan.md`** §18 / §20.

| Phase | Topic | Closed by (summary) |
|-------|--------|---------------------|
| **0** | Governance labels | Aligned **`protocol_remediation_plan.md`** status/§20 with evidence-driven narrative in the close-out train |
| **1** | SDK package + `engine.py` | Package layout, **`core.py`** re-export split, docs path updates, import gates |
| **2** | Single pipeline | **`protocol_store.py`** extraction; **`store_postgres`** delegation; contract tests |
| **3–4** | §7.4 HTTP + client errors | **`details`** on errors; client registry parity; sampled route tests |
| **5–6** | Review rounds + edges | API fields + **`review_edge_counts`** + engine enforcement |
| **7** | Lease + Tier 2 | Covered by existing engine/store tests and **`protocol_remediation_plan.md`** acceptance rows at evidence date |
| **8** | §14 doc naming | No forbidden **`docs/protocol-*.md`**; guides renamed; **`test_protocol_docs.py`** |
| **9** | 403 vs 404 | Service + SDK contract tests per close-out scope |
| **10** | §13 pyramid + perf | Named modules (properties, fuzz, chaos, timeline) |
| **11** | UI / Telegram / security | Contract tests + docs/OpenAPI aligned at snapshot |
| **12** | Audit + §20 + status | Strict suite green; §20 refreshed; **`Status: implemented`** on product plan when appropriate |

---

## Historical rules (why doc-only PRs were forbidden)

During execution, the team used these rules to avoid **compliance cosplay**:

- **No phase “complete”** without **tests and/or code** merged.
- **No** **`Status: implemented`** on the strength of markdown alone.
- **§20** evidence tied to **commits, modules, or CI**—not narrative alone.

Those rules **guided** this close-out. **Future** releases should repeat the same discipline; they are not re-audited here.

---

## Appendix A — Historical execution order (archived)

The following was **sequencing guidance during the project**. It is **not** current scheduling truth after close-out.

```text
Phase 0 → Phase 1 → Phase 2 (extracted adapter — largest effort) → Phases 3–4
→ Phases 5–6 → Phase 7 → Phase 8 (may run early if isolated) → Phase 9
→ Phase 10 → Phase 11 → Phase 12
```

---

## Appendix B — Historical effort rough order (archived)

Rough **relative** sizing during execution (not estimates for future work):

| Phase band | Relative size (at execution time) |
|------------|-------------------------------------|
| 0 | Small |
| 1 | Medium |
| 2 | Very large |
| 3–4 | Small |
| 5–7 | Medium–large |
| 8 | Small |
| 9–10 | Medium |
| 11 | Large |
| 12 | Process + evidence |

---

## Carry-forward maintenance (ongoing—not backlog)

These are **not** failed close-out items; they are **normal** post-ship hygiene:

- **Re-run** the strict protocol suite and **regenerate OpenAPI** when protocol surfaces change.
- **Re-audit** **`protocol_remediation_plan.md`** §18 if the spec or behavior diverges.
- **Avoid** re-expanding **`store_postgres.py`** with new protocol logic—**extend** **`protocol_store.py`** and the SDK seam instead.

---

## Explicit non-goals (for future edits to this file)

- Do **not** turn this document back into a **live checklist** without **renaming** it (e.g. a new `STRICT_COMPLIANCE_LIVE.md`).
- Do **not** **loosen** the spec without a **version bump** on **`protocol_remediation_plan.md`**.

---

## Document control

| Version | Date | Notes |
|---------|------|--------|
| 1.0–2.3 | 2026-04-01 … 04-16 | Iterations toward strict compliance |
| 3.0 | 2026-04-16 | Completion plan + anti-patterns |
| 3.1 | 2026-04-16 | Close-out evidence (commits, suite count) |
| **3.2** | **2026-04-16** | **Reconciliation:** frozen close-out record; **evidence as of**; **terminology** (extracted adapter); **no mixed Done/Remaining**; **phases as closed table**; **dependency/effort archived**; **carry-forward** section; contradictions with **`protocol_remediation_plan.md` Status** removed |
