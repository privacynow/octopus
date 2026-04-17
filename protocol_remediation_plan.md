# Protocol System Remediation Plan

Status: strict_compliance_pending
Last updated: 2026-04-16 (v4.1)
Audience: engineering, product, operations

---

## 1. Objective, non-negotiables, and principles

### 1.1 Objective

Bring the protocol system from a **working vertical slice** to a **commercially viable product** without **reducing scope**, **weakening guarantees**, or **normalizing gaps** in the current implementation. **The code must be brought up to the specification, not the specification down to the code.**

### 1.2 Non-negotiables

- **One orchestration pipeline only.** No duplicate engine in registry, runtime, and UI.
- **One canonical persistence path.** All protocol run / stage / participant **state mutations** in the registry must flow through **one canonical applier** (single store method or thin wrapper family that always runs the same SQL and side effects). Evaluation may use multiple SDK helpers (`dispatch` preflight, task result, operator action, synthetic timeout), but **persistence must not** use competing styles (inline `UPDATE` branches alongside the applier for the same concern). See **§19.2**.
- **The SDK is the single owner of protocol lifecycle rules** — transition validation, policy enforcement, and advancement decisions.
- **Visible fields and controls must be enforced, not advisory** (policies, leases, artifact verification, strict stage modes).
- **If a field or control is not enforced, it must not remain user-visible.** Hide it until implemented rather than training users to ignore it.
- Protocol runs must be **deterministic**, **auditable**, **idempotent**, and **observable**.
- **Artifact handling** must move from logical placeholders to a **verifiable contract** (observations, hashes, blocking rules).
- **Shipping docs, API, authorization, and operations** must match **actual behavior** (OpenAPI, runbooks, client types).

### 1.3 Initial gap list this remediation addressed (reference)

| Gap | Location / symptom |
|-----|---------------------|
| Lifecycle orchestration in store | `octopus_registry/store_postgres.py` instead of a pure SDK engine |
| Unenforced policies | `single_active_writer`, `max_review_rounds` in definition but not in engine |
| Placeholder artifacts | Rows without existence/hash verification |
| Permissive work stages | Advance without satisfying declared completion contract |
| Narrow API | Current shipped API is below the intended commercial contract: missing commercial error, idempotency, concurrency semantics |
| Versioning | `schema_version` absent from `ProtocolDefinitionDocumentRecord` |
| Governance | Authz, audit, retention, export not fully specified or enforced |
| Surfaces | Registry UI and Telegram functional but not product-complete |

### 1.4 Plan scope (this document)

This plan unifies:

- **Post-implementation code review** (orchestration embedded in the registry store, unenforced policies, weak artifact integrity, API gaps versus product goals).
- **Commercial product-spec expectations** (positioning, security posture, API maturity, operator experience, integrations, measurable quality).

**Non-goals**

- Narrowing the product to match bugs (e.g. dropping operator actions because they are unimplemented).
- Declaring policies “documentation only” unless explicitly moved to a **deferred phase** with a **dated commitment** and **visible UI**.
- Leaving transition logic embedded in a single store implementation without an SDK-owned engine.

### 1.5 Source of truth and related documents

- **`protocol_remediation_plan.md` (this file) is the single active source of truth** for protocol remediation, hardening, implementation sequencing, governance, and rollout. **Normative behavior** (enums, transitions, participant resolution, advancement rules, tenancy/authz V1) is specified in **§2.3, §4–§8, §12**, and **§5.3**—not only in narrative elsewhere. Implementations must match those sections; where **§1.6** leaves a product fork open, behavior is **gated** as stated there (e.g. `paused`, webhooks).
- **`protocol_plan.md`** is **background and original product narrative** (domain model, early architecture). It does **not** drive sequencing and **must not** override §§4–8 or §12. **Do not** allocate delivery or implementation effort to updating it unless there is a **separate** archival or compliance reason; treat it as **read-only context** for engineers.
- **Do not** introduce a separate “implementation spec” markdown file (e.g. a phantom `*_implementation_spec.md`). Normative engineering rules live **in this file** until shipped; optional user-facing markdown under `docs/` is added only when you actually create those files (see §14). Code and OpenAPI must match reality, not imaginary paths.

### 1.6 Closed product decisions for this release

These decisions are **closed for the current protocol release** and are no longer open design forks:

| Decision | Chosen behavior |
|----------|-----------------|
| Run lifecycle includes `paused` | **Excluded from V1.** `ProtocolRunStatus` stays `queued | running | blocked | completed | failed | cancelled`. No `pause` / `resume` API, UI, or Telegram controls in this release. |
| External event delivery | **Registry realtime invalidations only** for this release. No SSE or signed outbound webhooks in the same pass. |
| Provider/model policy | **One provider/model contract per run** for V1. Per-participant overrides remain unsupported. |
| Artifact verification waivers | **Mode A only** for this release: no waivers. Definitions containing `artifact.verify: false` are rejected. |
| Retention and export defaults | **90-day default retention**. Export is available to **operator**, **auditor**, and **admin** roles only. |

---

## 2. Product and commercial context

These items drive UX priority, schema (`visibility`, ownership), and what “done” means beyond passing tests.

### 2.1 Personas and jobs-to-be-done

Document personas (P11 or earlier in this file): for **platform operator**, **team lead**, **compliance reviewer**, and **bot developer**, one sentence each on **when they use Protocols versus normal conversations** (e.g. audit vs speed vs automation). **Do not assume a file exists** until you add it under `docs/`.

### 2.2 Success metrics

Define and instrument metrics (see §9): time-to-first-successful-run, mean stages per run, distribution of review-loop counts, run completion rate, operator intervention rate, blocked-run rate. Record definitions **in this plan or in real dashboards/docs** when they exist—**not** in a placeholder path.

### 2.3 Packaging and tenancy

**Normative V1 model (blocking for P5/P9 schema and authz)**—refine only via explicit amendment to this file:

| Concept | Rule |
|--------|------|
| **Scope** | Every protocol **definition** carries **`owner_org_id`** (or equivalent) and **`visibility`**: `org_private` (default), **`org_shared`** (readable within the same org), or **`registry_template`** (cross-org readable **only** when a deployment explicitly enables global templates; default **off**). |
| **Runs** | A run is created in **`run_org_id`** (from the **starting principal**). The **definition** must be visible to that org under the rules above. Cross-tenant start without visibility is **403** / `NOT_VISIBLE`. |
| **List/get** | Registry APIs **filter** definitions and runs by caller **org** unless the caller holds a **platform admin** (or documented break-glass) role. |
| **Marketplace** | Out of scope for V1 unless added as a **dated** phase; do not imply marketplace URLs or billing in schema until then. |

**No ambiguous global visibility:** if `registry_template` is disabled, treat all definitions as org-scoped only.

### 2.4 Positioning versus alternatives

Add a short comparison (here or in real docs when written): Protocols vs **ad-hoc delegation**, **external CI**, and **human-only review tools**—for buyers and internal alignment.

---

## 3. Architectural correction: SDK-owned protocol engine

### 3.1 Problem

Protocol run progression and dispatch orchestration live primarily in **`octopus_registry/store_postgres.py`** (`_advance_protocol_run_for_task_in_tx`, related helpers). The SDK provides models, validation, prompts, and parsing, but **the state machine is not a first-class, testable component** in `octopus_sdk/`, contradicting the rule that **shared workflow logic belongs in the SDK**.

### 3.2 Target state

Introduce a **`ProtocolRunEngine`** in **`octopus_sdk/`** that:

- Accepts **pure inputs**: `ProtocolDefinitionDocumentRecord`, `ProtocolRunRecord` snapshot, relevant `ProtocolStageExecutionRecord` rows, routed-task result payload (`status`, `full_text`, `summary`, timestamps), **artifact observations** (§5).
- Returns **typed transition decisions**: terminal outcome with **stable reason codes**; or next stage execution seed; or artifact manifest mutations as **data**, not SQL.
- Imports **no** database drivers, FastAPI, or Telegram.

**One call path:** routed task completion still lands in the registry store; the store **loads state**, runs the **engine inside a transaction boundary**, and **persists** the engine’s commands only.

### 3.3 Migration

1. Extract current store logic into engine functions **line-by-line** first, with **characterization tests** snapshotting today’s behavior.
2. Replace inline conditionals with engine calls.
3. Add policies, integrity, and new semantics **only** in the engine, then persist.

### 3.4 Deliverables and acceptance

- `octopus_sdk/protocols/engine.py` (or split submodules).
- `tests/test_protocol_engine.py` — pure unit tests, no Postgres for core cases.
- Refactored `RegistryPostgresStore` protocol paths that **only** persist engine results.
- **Duplicate `routed_task_id` completion** applies transitions **idempotently**—no second fork of the graph; covered by tests (see §13).

---

## 4. Run lifecycle, leases, and policies

### 4.1 Terminal and non-terminal states

Document and implement a **single state machine** consistent with **§8.2.2–§8.2.3**. Canonical run/stage status enums are **`queued`, `running`, `blocked`, `completed`, `failed`, `cancelled`** (see **`ProtocolRunStatus`** / **`ProtocolStageExecutionStatus`**). **`paused`** is **not** part of those enums until **§1.6** is closed and **§8.2.2** is amended—do not document `running → paused` as shipped behavior before that.

### 4.2 `max_review_rounds`

**Definition:** A review round is a producer↔reviewer **revise loop** on a defined edge. When **revise** count for that edge exceeds **`policies.max_review_rounds`**, the run must **not** loop silently—terminate with **`max_review_rounds_exceeded`** (blocked or failed per product choice). Expose **current count vs cap** in API and UI.

### 4.3 `single_active_writer` and leases

At most one **write-capable** stage may hold a **write lease** at a time. Implement using schema fields (`lease_owner`, `lease_expires_at`) where missing.

**Lease semantics** (spell out in implementation and, when you write real docs, reproduce there): acquire on dispatch, renew on progress/heartbeat, release on terminal stage or timeout, **admin break** (steal lease) with audit, behavior on **bot restart** (TTL vs explicit release).

### 4.4 Acceptance

- Integration tests: graph exceeding review rounds → terminal policy outcome, not infinite loop.
- Concurrent write dispatch → deterministic reject or queue.

---

## 5. Artifacts, integrity, and manifest semantics

### 5.1 Problem

Rows are inserted with **empty `content_hash`** and paths from definitions without proving files exist.

### 5.2 Artifact observations (verifiable contract)

Extend the execution/result path so the **runtime** reports structured **artifact observations** for declared outputs (in routed-task result or dedicated payload):

| Field | Purpose |
|-------|---------|
| Path | Relative to run workspace (secure join) |
| Existence | Boolean |
| Size | Bytes |
| Hash | SHA-256 or project standard |
| Modified time | For staleness checks |
| Optional content sampling | Policy-defined (e.g. head/tail only for large files) |

**Source of truth for verification is runtime-side** so Telegram, registry-origin runs, and future transports share one contract.

Persist observations in the registry; **each `artifact_key`** has an unambiguous **current** pointer (§5.4). Block or fail transitions when required outputs are **missing or invalid** per protocol definition and stage strictness.

### 5.3 Tier 1 advancement rules

After a **work** stage’s routed task completes successfully, before advancement:

- For each declared **output**: **§5.3a** applies; **§5.3b** applies only when the product ships **publisher-gated waivers** (not **no-waiver mode**).
- On failure: **`blocked`** with `artifact_missing` / `artifact_integrity_failed`—no silent advance.

#### 5.3a Verification (always)

Unless **§5.3b** exempts a specific output, require **runtime artifact observations** (§5.2) proving existence and hash (or project-standard integrity) for that output.

#### 5.3b Artifact verification waivers (`artifact.verify: false`) — **normative**

This section **closes** the former open decision: implement **either** mode **A** or **B** per deployment config—document which in **`README.md`** / ops config.

| Mode | Behavior |
|------|----------|
| **A — No waivers** | Definitions **must not** contain `artifact.verify: false` on any output. **Validation rejects** at draft save or publish. P3 implements rejection. |
| **B — Publisher-gated waivers** | `artifact.verify: false` may appear **only** on a **declared output** in the **definition JSON**. **Publish** of a version containing any waiver bit requires **`publisher`** role (or equivalent). Registry persists **`verify_waiver` metadata** on the definition version (or an append-only audit event: `artifact_key`, `publisher_id`, `definition_version_id`, timestamp). At advancement, **skip** hash/existence checks for that output only; emit structured **`waiver_applied`** in logs/audit with the same fields. |

**No silent waivers:** authors cannot toggle waivers **after** publish without a **new** version and **publisher** gate.

**Who verifies (observations path):** Prefer **bot-reported observations** in the result contract (`octopus_sdk/registry/models.py` or routed-task result schema). Registry filesystem read **only** if deployment allows. **Document** the chosen authoritative path per deployment mode in **this plan** or in **real** operator docs when they exist—not a stub filename.

### 5.4 Current artifact in manifest

Rule: **latest non-superseded row per `artifact_key`** unless the protocol adds an explicit pointer—keep the rule **here** or in **actual** shipped documentation.

### 5.5 Tier 2 (same phase if feasible)

Size limits; binary vs text rules per kind.

---

## 6. Work stages, timeouts, execution semantics, and remediation

### 6.1 Strict completion (definition-driven)

- **`stage.strict_completion`**: when `true`, require **`PROTOCOL_SUMMARY:`** (and optionally **`PROTOCOL_DECISION: completed`**) for work stages, not only reviews.
- **`stage.require_output_verification`**: ties to §5 defaults.

### 6.2 Contract-invalid remediation (distinct from review rejection)

Distinguish **normal review rejection** (`revise` from reviewer) from **contract violation** (missing `PROTOCOL_DECISION`, parse failure, missing artifact). Define a **controlled remediation path**: e.g. **blocked** stage with operator **retry** or **send-back** to producer with reason codes `protocol_contract_invalid` vs `review_rejected`. Infrastructure failures map separately (`provider_unavailable`, etc.).

### 6.3 Provider and model

Either support **per-participant** overrides in the definition (`provider_profile` / `effective_model_override`) **or** document **V1: single provider per run** and **reject** per-stage overrides until implemented—no silent mixing.

### 6.4 Timeouts

**`stage.timeout_seconds`**: wall-clock enforcement (registry deadline job vs provider cancel). On timeout → **`failed`** or **`blocked`** per policy. Document clock source.

### 6.5 Failure taxonomy

Classify outcomes for **error_code**, UI, and runbook: **infrastructure**, **validation/contract**, **normal review**, **policy** (max rounds, lease). Maps to §9 runbook and §11 blocked UX.

### 6.6 Cost and usage (future)

Link `protocol_stage_execution_id` to usage/billing when product requires it; record the linkage in **this plan** or **real** metrics documentation when it exists.

---

## 7. API, control plane, platform maturity, and SDK client

Implement the full commercial API surface for protocols, hardened for external and internal clients.

### 7.1 Protocol definitions

Include lifecycle-consistent **delete or archive**; **`GET /v1/protocols/{protocol_id}/versions/{version_id}`** if not redundant; **list** with **pagination and filters**: `lifecycle_state`, `slug`, `created_after`, cursor—aligned with UI.

### 7.2 Protocol runs and sub-resources

- `GET /v1/protocol-runs` (existing) with filters aligned to metrics.
- `GET /v1/protocol-runs/{run_id}/participants`
- `GET /v1/protocol-runs/{run_id}/artifacts`
- `GET /v1/protocol-runs/{run_id}/timeline`
- **`GET /v1/protocol-runs/{run_id}/export`** — JSON bundle (run, transitions, artifact manifest, hashes) for **legal / offline review**; **data residency** and region pinning documented as future if needed.

### 7.3 Operator actions

Typed endpoints for this release: **cancel**, **retry**, **accept**, **send-back** — each **idempotent** (`Idempotency-Key`), **optimistic concurrency** (`If-Match` / `version`), **409** with current version on conflict. Response indicates **first apply vs replay**. `pause` / `resume` are intentionally excluded in V1 per **§1.6**.

### 7.4 Stable errors

Publish a **registry of `error_code` values** and HTTP mapping in **`octopus_registry/server.py`**, with shared **SDK client types** in **`octopus_sdk/registry/client.py`** (or adjacent module) so clients parse errors deterministically. Examples: `PROTOCOL_INVALID_TRANSITION`, `LEASE_HELD`, `MAX_REVIEW_ROUNDS_EXCEEDED`, `ARTIFACT_VERIFICATION_FAILED`, `CONCURRENT_MODIFICATION`, `IDEMPOTENCY_REPLAY`. Stable JSON body: `{ "error_code", "message", "details" }`.

### 7.5 Authorization, ownership, and roles

**Schema (align with §2.3):** definitions carry **`owner_org_id`**, **`visibility`**, **`created_by`**, **`updated_by`**; runs carry **`run_org_id`**, **`started_by`**, and links to **`entry_agent_id`** as today. **Publish** and **archive** require **`publisher`** (definitions); **operator** actions on runs require **`operator`** or **`admin`** per endpoint table you add to OpenAPI.

Define **role-based actions** with explicit names: **author**, **publisher**, **operator**, **auditor**, **admin** (map to registry roles / service accounts). Capture who may draft/publish/archive definitions; who may start/cancel/send-back/view artifacts/export; **operator** vs **service account** vs **entry agent** scoped to run—**in this file** or in **auth docs you actually add** (e.g. under `docs/` when P11 ships them). **Export/download** (§7.2) allowed only for **`auditor`**, **`operator`**, or **`admin`** unless tightened further in §10.

### 7.6 OpenAPI and contracts

**OpenAPI** generated from handlers, shipped with registry releases. **Contract tests**: SDK fixtures as golden API responses; **client** types aligned with §7.4.

---

## 8. Protocol definition contract, schema versioning, and migrators

### 8.1 `schema_version`

Add **`schema_version`** to **`ProtocolDefinitionDocumentRecord`** in **`octopus_sdk/protocols/`** and **require** it in validation.

### 8.2 Full DSL (normative)

The following subsections are the **canonical V1 enumerations and rules** unless **§1.6** explicitly defers (e.g. `paused`). They align with **`octopus_sdk/protocols/`** (`ProtocolStageKind`, `ProtocolRunStatus`, `ProtocolStageExecutionStatus`); implementation and tests must not drift without an amendment here.

#### 8.2.1 Stage kinds

| Kind | Purpose |
|------|---------|
| `work` | Producer stage; default allowed decision `completed` if transitions omit keys |
| `review` | Reviewer stage; default decisions `accept`, `revise`, `fail` |
| `acceptance` | Final acceptance stage; same default decision shape as `review` unless the definition narrows |

Graph edges and **allowed decisions** come from each stage’s **`transitions`** map and **`allowed_decisions()`** semantics in code.

#### 8.2.2 Run and stage execution statuses

**Protocol run** and **protocol stage execution** use the same status vocabulary:

`queued` | `running` | `completed` | `failed` | `cancelled` | `blocked`

**`paused` (run-level):** not a shipped **`ProtocolRunStatus`** value until the **§1.6** row for `paused` is **closed** and this subsection is updated. Until then, **do not** expose `paused` in API or public UI.

#### 8.2.3 Legal transitions (runs and stage executions)

- **Non-terminal → non-terminal:** `queued` → `running` on dispatch/start; `running` → `blocked` on policy/artifact/lease failure; `running` → `completed` | `failed` | `cancelled` on engine terminal decisions; `blocked` → `running` when unblocked (operator or engine remediation).
- **Terminal:** `completed`, `failed`, `cancelled` do not transition to non-terminal states **except** documented **admin repair** or **data migration** (audited, out of band).
- **Advancement along the protocol graph** creates **new** stage execution rows; moving the run’s “current” work is expressed by engine decisions and foreign keys, not by reusing a single stage execution row across different `stage_key` values.

**Review-loop and max rounds:** when **`max_review_rounds`** is exceeded, terminate per §4.2 with reason **`max_review_rounds_exceeded`** (run may be `blocked` or `failed` per product choice recorded in §1.6 / §4).

#### 8.2.4 Timeouts and escalation

- **`stage.timeout_seconds`:** enforce wall clock per §6.4; on expiry set stage execution (and run if applicable) to **`failed`** or **`blocked`** per **one** documented policy per deployment; persist **`failure_code`** distinguishing timeout from other failures.
- **Lease / single writer:** lease conflict → **`blocked`** or deterministic reject per §4.3; no silent double-writer.

#### 8.2.5 Participant resolution

**Normative algorithm:** **§12** (must match **`_dispatch_protocol_stage_in_tx`** + **`resolve_selector`** behavior in `octopus_registry/store_postgres.py` and `octopus_registry/store_shared/agents.py` during extraction; engine must not invent a second resolution path).

#### 8.2.6 Artifact semantics

**§5** (observations, manifest, **§5.3** waiver modes). Optional user docs under `docs/` may restate this for operators—**only after those files exist.**

**There is no other authoritative spec file** for these enums and rules.

### 8.3 In-memory migrators

Add **in-memory definition migrators** so **published** definition rows remain **immutable** on disk but load at **current schema** at read time (upgrade N→current in memory). Drafts may be rewritten in place via migration tooling. **Do not** silently rewrite published DB blobs without a controlled migration project.

Compatibility rules:

- **Published definitions remain immutable.**
- **Drafts may be migrated in place** through explicit tooling.
- **Runtime read paths may up-convert historical schema versions in memory** when loading published definitions.

### 8.4 SQL and tooling

- Tooling to upgrade drafts **N → N+1** with changelog.
- SQL migrations for new columns (loop counters, lease fields, verification flags, retention, **resolution rationale**, ownership).
- **Backfill** existing rows: `schema_version`, ownership defaults, required metadata.

---

## 9. Realtime, webhooks, observability, and support tooling

### 9.1 Internal realtime

Reuse registry **WebSocket or SSE**: e.g. `protocol_run.updated`, `protocol_run.stage_changed`, `protocol_run.terminal` — **no second parallel channel**.

### 9.2 Partner integrations

Either **optional signed outbound webhooks** with the **same event schema** as realtime, or a **documented** first-class **SSE** integration for external systems.

### 9.3 Logs and metrics

Structured logs: `protocol_run_id`, `protocol_stage_execution_id`, **`participant_key`**, `routed_task_id`, `transition_kind`, `error_code`. Metrics per §2.2 and **stage duration**, **loop depth**, **artifact verification failures**, **timeout rate**, **per-stage cost/usage** linkage when available.

### 9.4 Runbook

**Operations / runbook content:** failure codes, unblock steps, workspace verification, mapping **failure taxonomy** (§6.5) to operator actions. **Protocol failures must be diagnosable without reading raw model text.** Put this in **this plan**, **`docs/ARCHITECTURE.md`**, or **new files you create**—not a pretend path.

### 9.5 Admin and support views

**Registry operator surfaces** (or admin API) for: **blocked runs**, **stuck leases**, **expired timeouts**, **invalid contract results**—with filters and links to timeline/artifacts.

---

## 10. Security, audit, compliance, and data lifecycle

- **Artifacts and problem statements** may contain secrets: **redaction** rules for logs and API fields; **download** allowed only per role; **no** default public artifact download.
- **Retention**: `retention_until` or equivalent for org policy; cold archive hooks as required.
- **Audit**: `protocol_transitions` as narrative audit; **operator** `accept` / `send-back` may require **append-only `compliance_events`** (or equivalent) for WORM-style requirements.
- **Pen-test** checklist: cross-tenant run access, path traversal on artifact paths.

---

## 11. Operator surfaces: Registry UI and Telegram

### 11.1 Registry UI

- **Layout:** Master–detail, **sticky** primary actions, independently scrollable panes, breakpoints; **read-only run status** on narrow viewports.
- **Onboarding:** Empty states and **first-run wizard** (create → validate → publish → start run).
- **Designer:** JSON + structured forms; **YAML** import/export with same validator; **validation gutter** (inline errors); **diff** draft vs last published; keyboard **accessibility**; ARIA on timeline.
- **Run detail:** Timeline **filterable by participant**; **blocked** state with reason and remediation; artifact table with path, hash, verification, download per policy.
- **Intervention controls:** cancel/send-back/retry/accept with **confirmation**, **reason capture**, **concurrency conflict** handling (surface `409`), **audit-visible** outcomes.

### 11.2 Telegram

- Commands aligned with §7 (**list**, **start**, **status**, **cancel/retry/accept/send-back** where safe).
- **Deep link** to registry run in status messages.
- **Stage-change** and **terminal** notifications; **debounced** and **rate-limited** (max messages per minute per run).
- **Destructive** actions: **confirmation + short reason** for audit (§10).
- **Thin client:** invokes and observes shared engine; **does not** own protocol logic.

### 11.3 UI acceptance

Contract tests avoid **only** brittle string snapshots; prefer stable selectors or roles.

---

## 12. Runtime, transport, and participant resolution

### 12.1 Runtime flow

Document in **`docs/ARCHITECTURE.md`**, this plan, or code comments (must exist in at least one real place): why **`protocol-stage:`** `routed_result` short-circuits delegation continuation in **`app/channels/registry/delivery_transport.py`**; authoritative path is **task completion → `update_routed_task_result` → engine advance**.

### 12.2 Participant resolution (normative algorithm)

Dispatch for a stage execution **builds a `TargetSelector`**, then **`resolve_selector`** chooses a **single connected agent**. Behavior must match the following (and existing registry code during refactor):

1. **Load** the stage’s **`participant_key`** from the definition; read **`ProtocolParticipant`** (selector, `required_skills`, etc.).
2. **If `participant.selector` is present:** use it as the **selector** (explicit `agent` / `skill` / `role`).
3. **Else if `required_skills` is non-empty:** `TargetSelector(kind="skill", value=<first required skill>, preferred_agent_id=<run.entry_agent_id>)`.
4. **Else:** `TargetSelector(kind="agent", value=<run.entry_agent_id>)`.
5. **`resolve_selector(conn, selector)`** (see `octopus_registry/store_shared/agents.py`):
   - Collect **connected** agent rows matching the selector (`agent` alias/slug/display, `skill` in advertised skills, `role`).
   - If **`preferred_agent_id`** is set: the resolved agent **must** be that id among matches, or **fail** (deterministic error—no silent fallback).
   - If **no** matches: **fail** (no connected agent).
   - If **multiple** matches and **no** `preferred_agent_id`: **fail** (ambiguous selector—operator must narrow definition or registry data).
   - If **exactly one** match (or preferred narrowed to one): **that** agent is the dispatch target.

**Not in V1 unless explicitly added:** capacity/load ranking beyond the rules above; “first of N” when ambiguous is **not** allowed—ambiguity is an error.

### 12.3 Audit fields

**Persist** resolution for debugging and compliance: **`selector` snapshot** (kind/value/preferred), **resolved `target_agent_id`**, **`resolution_outcome`** (`ok` | `error`), **error detail** if any—on `protocol_run_participants` or equivalent (see P9 for schema alignment).

---

## 13. Testing and quality bar

| Layer | Expectations |
|-------|----------------|
| **Engine** | Table-driven tests for **every transition class**; branches: success, task failed, parse fail, terminals, revise, max rounds, lease conflict, artifact failure, **idempotent duplicate result**, **contract-invalid remediation**. |
| **Store** | Persistence mapping only; engine fixtures. |
| **HTTP** | Authz, idempotency, concurrency, **error_code** bodies. |
| **Integration** | Full routed-task round trips, artifact verification, policy enforcement, operator interventions, **restart recovery**, concurrency conflicts. |
| **E2E** | Telegram + registry UI on same run id. |
| **Chaos** | Registry unavailable mid-transition; **duplicate** task results; **stale idempotency** retries; **lease expiry**. |
| **Property-based** | Protocol graph: no orphan stages; reachability from `first_stage` to a terminal. |
| **Fuzzing** | Random JSON into `validate_protocol_document` must not crash. |
| **Performance** | SLO: e.g. p95 **`GET .../timeline`** for large N (indexes, timeline pagination). |

Replace tests that **encoded bugs** with spec-aligned expectations.

---

## 14. Documentation (what exists vs what P11 may add)

**Facts today**

- **`protocol_remediation_plan.md`** (this file) — active engineering plan; **exists**.
- **`protocol_plan.md`** — original narrative; **exists** (background only per §16).
- **`README.md`** (repo root) — **exists**.
- **`docs/ARCHITECTURE.md`** — **exists**; extend it for protocol subsystem boundaries when you implement.

**Nothing in `docs/` today is named `protocol-*.md`** — that pattern was a mistake. **Do not** treat any invented path as real.

**P11 deliverables (create files only when you implement P11)**

Add **real** markdown under `docs/` (or extend `docs/ARCHITECTURE.md`) to cover these **topics**—**you choose filenames** when you write them:

| Topic | Purpose |
|-------|---------|
| Operator | Start run, read stages, intervene, runbook alignment with §9 |
| Intervention | Operator actions, conflicts, audit implications |
| Author | Participants, artifacts, review policies, strict flags |
| Artifacts | Observations, verification paths, current-manifest rule, waivers |
| Leases | Full lease lifecycle (may duplicate §4 content for readers) |
| Metrics | §2.2 definitions and how dashboards map to them |
| Personas | §2.1 in reader-friendly form |
| Security / authz | §7.5 in reader-friendly form |

**Always required for a commercial API**

- **OpenAPI** (or equivalent) generated from **`octopus_registry/server.py`** handlers — §7.6; ship with registry releases.

**P11 also updates** (files that already exist)

- **`README.md`** — short protocol feature blurb + link to this remediation plan.
- **`docs/ARCHITECTURE.md`** — protocol boundaries: SDK engine vs registry store vs runtime, and links to code paths (`store_postgres.py`, `delivery_transport.py`, `octopus_sdk/protocols/`).

---

## 15. Bootstrap, migration, seeding, and one authoritative path

- **One authoritative migration/bootstrap path** for product-critical state — **no** reliance on hidden runtime constructor side effects for protocol definitions.
- **Builtin protocol seeding** (e.g. software-engineering) lives in the **canonical** migration or bootstrap step so definitions exist **predictably** and **audibly**.
- **Additive DB migrations** for new columns, indexes, constraints; **backfill** `schema_version`, ownership, and resolution fields.
- **Do not** ship ad-hoc startup behavior as the only place definitions appear.

**Split for phasing:** **§15 shell** (migrations + single seed entrypoint) is required by **P1b** so later phases do not entrench one-off startup paths. **P10** completes backfills, production hardening, and operational verification—not the first time migrations appear.

---

## 16. Documentation authority and implementation governance

### 16.1 Roles of documents

| Document | Role |
|----------|------|
| **`protocol_remediation_plan.md`** (this file) | **Single active source of truth** for what to build, how, in what order, and what “done” means. |
| **`protocol_plan.md`** | **Original vision / background** — useful for context; **not** the driver of sequencing. **No delivery or implementation effort** to keep it current; archival/read-only unless a **separate** stakeholder explicitly commissions an update. |
| **User-facing docs under `docs/`** | **Only after P11 creates them** — explain shipped behavior to operators/authors; must match code. See §14. |

### 16.2 Maintenance rules

- Add normative engineering detail to **this file** first. Add **real** files under `docs/` when you write them (P11); **not** to a separate implementation-spec markdown.
- **`protocol_plan.md`:** follow **§16.1** — no standing work to refresh it; commissioned or archival updates only.
- Track implementation gaps, deferred items, and resolved product decisions here.
- When **exit criteria** are met: status **approved**, **owner**, **review date**.
- Implementation gaps versus product goals: track as **dated open items** here—**do not** narrow requirements to match bugs.

---

## 17. Rollout and phasing

Phases are **ordered dependencies**, not optional drops.

| Phase | Deliverable | Depends on |
|-------|-------------|------------|
| P1 | Engine extraction + characterization tests | — |
| P1b | **§15 shell:** authoritative SQL migration chain for protocol tables; **single** seed/bootstrap path for builtin definitions (no constructor-only seeding); may be minimal data in early PRs but **must** be the path later phases extend | P1 |
| P2 | Policy + lease enforcement + engine tests; **DSL + migrators** (§8) | P1, P1b |
| P3 | Artifact **observations** + verification (runtime + registry contract) | P1, P1b |
| P4 | Work-stage strict modes + timeouts + **contract remediation** paths (§6) | P1, P1b |
| P5 | Full API (§7), **client error types**, auth/roles, export, list filters (§2.3, §7.5) | P1, P1b |
| P5a | **Thin registry UI**: read-only run list + run detail + timeline (**dogfooding**) | P5 |
| P6 | Realtime + metrics + webhooks/SSE; **admin/support views** (§9.5) | P5 |
| P7 | Full UI (§11) | P5a, P6 |
| P8 | Telegram parity (§11.2) | P5 |
| P9 | Security, audit, retention schema (§10); **resolution rationale** persistence | P5 |
| P10 | **§15 completion:** backfills, production migration polish, operational verification; **no** new ad-hoc bootstrap paths | P2–P9 |
| P11 | **§14**: OpenAPI, **README.md** and **`docs/ARCHITECTURE.md`** updates; **optional** new `docs/*.md` for operator/author topics (you create the files) | Prior phases |

**Rule:** Do not ship **P7** as “complete” without **P5** operator APIs unless feature-flagged with a **dated** temporary limitation documented in this file.

**Execution:** For a **canonical rebuild** (recommended when seams have diverged), follow **§19** and validate with **§18.1**—the P1–P11 table remains the dependency spine, but **order of work** should follow **§19.12**.

---

## 18. Success criteria (acceptance bar)

The subsystem is **commercially viable** when:

1. **All lifecycle decisions** come from the **SDK engine**, not store-local orchestration logic.
2. **No visible policy field** remains unenforced (or is removed with migration).
3. **No work stage** advances without satisfying its **declared completion contract** (strict + verification as defined).
4. **Every operator mutation** is **idempotent**, **auditable**, and **concurrency-safe**.
5. **Every run** can be explained from **logs**, **audit records**, and **timeline** data.
6. **Definitions** are **schema-versioned** and **migratable** (including in-memory read path for published).
7. **Registry UI**, **Telegram**, and **SDK client** operate on the **same contract** and show the **same run truth**.
8. **Artifact observations** are first-class; **current pointer** per `artifact_key` is unambiguous.
9. **§7** API, **error registry**, **idempotency**, and **auth roles** are shipped and documented.
10. **Realtime and/or webhooks/SSE** and **metrics** (§2.2, §9) meet ops needs.
11. **Security** review (§10) passed.
12. **§13** test pyramid green in CI.
13. **§2** personas and metrics are defined and instrumented.
14. **Bootstrap and seeding** (§15) are deterministic and reviewed.
15. **This remediation plan** is current and authoritative; **OpenAPI**, **`README.md`**, and **`docs/ARCHITECTURE.md`** match shipped behavior; any **optional** operator docs under `docs/` match reality if and when they exist (no imaginary spec files).

### 18.1 Rebuild acceptance bar (stricter than §18 alone)

Use this checklist **before** calling protocol remediation **done** after a **canonical rebuild** (§19). It restates §18 in seam-specific terms.

1. **One persistence path** — Dispatch, task-result, operator-action, and **timeout** outcomes may use different SDK evaluators, but **all** persist through **one canonical registry applier** (§1.2, §19.2–§19.3).
2. **One builtin source of truth** — SDK **seeds** builtins; **DB** is the only runtime/control-plane read for templates and published definitions (§19.4).
3. **No advisory UI** — Nothing visible in API/UI/docs is unimplemented (§1.2, §19.9).
4. **Timeouts** — Overdue running stages are handled by **maintenance/synthetic timeout** through the **same** applier; not only “late task result” (§19.6).
5. **Historical definitions** — `schema_version`: immutable JSON on disk, **in-memory migrate** to current, **validate** migrated model (§19.5).
6. **Tenancy and roles** — Visibility, org, export, and errors match **§2.3** and **§7** (no `NOT_FOUND` where **`NOT_VISIBLE`** is required).
7. **Surface parity** — Registry UI, Telegram, SDK client, and HTTP API share **one** protocol truth (§19.8–§19.9).
8. **One-sentence explanation** — *Protocol lifecycle decisions are evaluated in the SDK and persisted through one canonical registry applier on one routed-task completion pipeline (plus explicit synthetic events for timeout and operator actions), with DB-backed definitions.*

---

## 19. Execution strategy: canonical rebuild (vs endless patching)

**Problem:** A branch that accumulated **one** routed-task completion path but **many** lifecycle seams and **store-owned** orchestration will not converge by patching alone.

**Approach:** Treat any existing **feature/protocol** branch as **reference only**. **Cherry-pick ideas and passing tests**, not architecture. **Rebuild** protocol behavior on a **fresh branch from `main`**, with **`protocol_remediation_plan.md` (this file)** as the **governing** document, porting only code that **satisfies** it.

### 19.0 Review refinements (implementation notes)

- **Applier identity** — Decide explicitly whether the canonical applier is **`_apply_protocol_engine_decision_in_tx`** (extended to cover all outcomes) or a **new** single entry point that replaces it; there must be **one** persist API, not two “canonical” methods. Document the chosen name/signature in the first refactor PR.
- **Cherry-pick discipline** — **Allowed:** characterization tests, pure SDK helpers, types, bugfixes that do not fork persistence. **Disallowed:** copying `_dispatch_*` / inline `UPDATE` blocks from a reference branch without routing through the applier.
- **Phase E0 risk** — If **§1.6** stays open, the rebuild stalls. **Time-box** decisions or adopt the **recommended default** column in **§1.6** and revise later via amendment.
- **Merge/rebase risk** — A long-lived rebuild branch conflicts with parallel **`main`** work; plan **rebase cadence** or integration checkpoints, not only technical milestones.
- **Registry realtime (when you ship P6)** — Protocol run/stage events must be emitted **after** the applier’s DB commit (same truth as reads), not from pre-persist branches, or realtime reintroduces dual truth.
- **Execution order nuance** — Within **E6**, ship **visibility / `NOT_VISIBLE` / list semantics** before **E7** UI/Telegram so surfaces do not encode wrong HTTP behavior.

### 19.1 Phase E0 — Lock product decisions

Close **§1.6** before writing feature code. No coding affected phases until each row has a **single** chosen option.

### 19.2 Non-negotiable: canonical applier

- **All** mutations to `protocol_runs`, `protocol_stage_executions`, `protocol_run_participants`, `protocol_transitions`, compliance events (when applicable), artifact rows, `version`, `blocked_code`, `blocked_detail`, `termination_summary`, `retention_until`, `current_stage_*`, lease fields, and timestamps — **through one applier** (see **§19.0**).
- **Evaluation** may have multiple SDK entrypoints (preflight, resolution outcome, routed task result, operator action, **deadline expiry**), but they must converge on **one decision record shape** then **one** persist path.

### 19.3 Phase E1 — Rebuild the lifecycle seam (one mutation path)

1. **SDK** remains owner of lifecycle **decisions**; collapse the **public** surface in `octopus_sdk/protocols/` so every stimulus yields **one** decision record shape (or explicit variants documented in one module).
2. **Stimuli** to cover: dispatch preflight, dispatch resolution result, routed task result, operator action, **deadline expiry** (synthetic).
3. **Refactor** `_dispatch_protocol_stage_in_tx` in `octopus_registry/store_postgres.py` to **orchestration only**: load snapshot → SDK eval → resolve participant if needed → SDK resolution outcome → **canonical applier** (same as task-result and operator paths).
4. **Expand** the applier; **do not** add parallel side paths.
5. **Remove or wire** dead fields (`repeat_current_stage`, etc.): implement end-to-end + tests, or **delete**.

### 19.4 Phase E2 — Builtin protocols: DB truth

1. **Database** is the only runtime/control-plane source for builtin definitions after seed.
2. **`get_protocol_template`** (and equivalents) must use **DB-backed** definition/version paths, **not** direct SDK reads for control plane.
3. **Bootstrap** is authoritative and **early**: seeding + schema init on the **canonical** migration path (§15, **P1b**); **no** hidden runtime-only side effects as the sole source of truth.

### 19.5 Phase E3 — Schema/versioning contract

1. **In-memory migrators** for published definition JSON: immutable on disk, migrate N→current in memory, validate.
2. **Loader** accepts supported historical versions, migrates, validates migrated model; **raw** stored JSON unchanged.
3. **Tests:** old published → load OK; unsupported future → clear failure; migrated shape matches expectations.

### 19.6 Phase E4 — Policy enforcement (complete)

1. **`max_review_rounds`** — Count the **real** producer–reviewer **loop** in the graph (revise edge), not an approximation by counting same `stage_key` executions; surface in API/UI; enforce in SDK. **Design note:** Record the **counted unit** in implementation tickets (e.g. each **traversal of the revise edge** between named stages, or a dedicated loop id)—avoid mid-build graph algorithm debates.
2. **Single-active-writer** — Lease **acquire / renew / expiry / admin break / retry** through one dispatch path; **no** second lease logic in the store.
3. **Active timeouts** — **Maintenance** (or existing registry background) finds overdue **running** executions and feeds **synthetic timeout** through **same** engine/applier as other events (no timeout-specific persistence fork). **Idempotency:** If a **late routed-task result** arrives after a timeout transition, **one** outcome wins—resolve via the same applier (e.g. terminal timeout vs ignored late result with stable reason codes); document the rule and test it.

### 19.7 Phase E5 — Artifacts

1. **Runtime observations** are authoritative; finish the contract: existence, integrity/hash, current-pointer, supersession, failure codes.
2. **Waiver mode** — **Fully** enforce **§5.3b** mode **A** or **B** (publisher-gated metadata + audit if B); **no** hardcoded mode if product requires **deployment-configurable** behavior. **Forward compatibility:** If mode **A** ships first but **B** is plausible, add **nullable** publish-time waiver metadata columns (or equivalent) when you touch schema so mode **B** does not require a second migration-only project.
3. **Work-stage completion** — Advance only when strict markers, verification, and contract rules are satisfied; otherwise blocked/contract-invalid paths.

### 19.8 Phase E6 — API, auth, tenancy, errors

1. **Operator + definition lifecycle** — Implement or **explicitly exclude** (with doc/UI parity): pause/resume if chosen, cancel/retry/accept/send-back, definition archive if required; **hide** unsupported controls.
2. **List filters** — `cursor`, `limit`, `slug`, `lifecycle_state`, **`created_after`** where §7 requires.
3. **Visibility** — §2.3 exactly: **`registry_template`** gated by **deployment config** (default **off**); cross-tenant `get`/`start` use **`NOT_VISIBLE`** (or equivalent), not generic `not_found`; lists omit invisible rows.
4. **Audit** — `protocol_transitions` = lifecycle truth; compliance events = operator/security/export; document and test separation.
5. **Errors + OpenAPI** — One **stable** protocol error registry in code + SDK types; OpenAPI reflects real routes; **protocol** contract tests on handlers—**no** hand-maintained second spec.

### 19.9 Phase E7 — UI / Telegram / runtime drift

1. **No** new UI until backend seams are unified; UI consumes **canonical** endpoints only.
2. **Hide or remove** unsupported controls (operator actions, visibility, waiver, pause, advisory fields).
3. **Telegram** thin: `/protocol` maps only to **real** APIs; no parallel protocol semantics or fake status.
4. **Canonical run visibility** in UI and Telegram: same stage, blocked reason, **review loop vs cap**, lease, artifact verification, transitions—**no** UI-only derivation.

### 19.10 Phase E8 — Commercial hardening

1. **Observability** from the **applier** (logs/metrics) keyed by `protocol_run_id`, `protocol_stage_execution_id`, `participant_key`, `routed_task_id`, error codes.
2. **Realtime (P6)** — When protocol events are exposed, they must reflect **post-applier** state (same projection consumers get from GET/timeline), consistent with **§19.0**.
3. **Support/admin** surfaces after the model is stable: blocked runs, lease conflicts, timeouts, contract failures, export/audit visibility.
4. **Retention / export / redaction** per §10 once §1.6 defaults are set.

### 19.11 Phase E9 — Test strategy

1. **Pure SDK** lifecycle tests (no Postgres): preflight, resolution failure, task success/failure, revise loops, operator actions, **synthetic timeout**, artifacts.
2. **Store** characterization: **one** persistence path — parity across dispatch blocked, resolution blocked, task blocked, operator blocked, running, terminal (**version**, blocked detail, retention, timestamps, participants, transitions).
3. **Builtin** — Seeded rows read via DB paths; bootstrap idempotent; **no** runtime direct SDK template reads.
4. **Multi-tenant** — `registry_template` off/on; **NOT_VISIBLE**; export roles; role boundaries.
5. **Timeout/maintenance** — Overdue stages **without** a routed result.
6. **E2E** — One run through create → dispatch → result → verification → transition → optional retry/send-back → **terminal**, single pipeline.

### 19.12 Phase E10 — Execution logistics

1. **Branch** — Fresh from `main`; reference branch for selective port only.
2. **Order** — Canonical bootstrap/schema → unified applier seam → DB builtin truth → policy + timeouts → artifacts → **tenancy / visibility / error shapes (E6 subset)** → **then** UI/Telegram alignment (E7) → observability/support → docs/tests/deploy. **Do not** build registry UI or Telegram protocol surfaces on **`NOT_FOUND`**/`403` behavior you intend to replace with **`NOT_VISIBLE`**-style errors.
3. **Ship** — Do not redeploy protocol changes widely until **§18.1** passes in **local + staging-like** environments.

### 19.13 Mapping E-phases to P1–P11

| E-phase | Primary P-phase overlap |
|--------|-------------------------|
| E0 | **Before** P1 — **§1.6** |
| E1 | **P1** (engine + applier) |
| E2 | **P1b**, §15 |
| E3 | **P2** (migrators §8) |
| E4 | **P2**, **P4** |
| E5 | **P3**, **P4** |
| E6 | **P5** |
| E7 | **P5a**, **P7**, **P8** |
| E8 | **P6**, **P9**, §9–§10 |
| E9 | **§13**, P11 tests |
| E10 | Process around **§17** |

---

## 20. Implementation status (code vs this plan)

This section is currently a **stale rolling snapshot**, not a strict-compliance close-out. The tree is being re-audited against **`STRICT_COMPLIANCE_FIX_PLAN.md`** and any remaining **`NON-COMPLIANT`** or **`NOT VERIFIED`** rows remain release-blocking until they are discharged with code and tests.

Treat the phase rows below as the last broad evidence snapshot, not the current strict stop-condition verdict. Refresh this section only after the strict re-audit and acceptance pass are complete.

### 20.1 Phase rollup (P1–P11)

| Phase | Status | Evidence / gap |
|-------|--------|----------------|
| **P1** Engine extraction | **done** | `ProtocolRunEngine` now lives at `octopus_sdk/protocols/engine.py`, with import-boundary enforcement in `tests/test_zero_import_gates.py` and pure engine coverage in `tests/test_protocol_engine.py`. |
| **P1b** §15 shell | **done** | Builtin bootstrap now lives on the canonical init path via `octopus_sdk/protocols/bootstrap.py`; `tests/test_db_postgres.py` covers seeding, additive restores, and schema contract. |
| **P2** Policies + DSL + migrators | **done** | Shared SDK protocol contracts now live under `octopus_sdk/protocols/`, with schema migration, lease/review policy enforcement, and generated/fuzzed validation coverage in `tests/test_protocols.py`. |
| **P3** Artifacts + verification | **done** | Runtime artifact observations, verification-state persistence, output-contract blocking, and release-mode-A waiver enforcement are live in the shared engine/store path. Artifact path traversal and absolute-path rejection are tested in `tests/test_protocols.py`. |
| **P4** Strict work + timeouts + remediation | **done** | Strict completion, contract-invalid blocking, maintenance-driven timeouts, duplicate-result idempotency, and late-result-after-timeout behavior are covered across `tests/test_protocol_engine.py`, `tests/test_protocols.py`, and `tests/contracts/test_registry_store_contract.py`. |
| **P5** Full API + auth + export | **done** | Protocol HTTP now emits stable `{error_code,message,details}` bodies, client/server error-code parity includes `LEASE_HELD`, `MAX_REVIEW_ROUNDS_EXCEEDED`, `ARTIFACT_VERIFICATION_FAILED`, `CONCURRENT_MODIFICATION`, and `IDEMPOTENCY_REPLAY`, and route-level visibility/export/action semantics are covered in `tests/test_registry_service.py` and `tests/test_registry_sdk_contract.py`. |
| **P5a** Thin UI | **done** | The registry UI consumes the shared protocol API directly and shows first-class review-loop state, with contract coverage in `tests/test_registry_ui_contract.py`. |
| **P6** Realtime + metrics + admin views | **done** | Realtime/admin surfaces remain on the canonical registry path, and the protocol strict suite plus store contract suite passed against the current tree. |
| **P7** Full UI | **done** | Protocol UI contract coverage stays green in `tests/test_registry_ui_contract.py`, including the updated shared protocol fields. |
| **P8** Telegram parity | **done** | Telegram protocol flows remain thin over the registry contract and pass in `tests/test_protocol_telegram.py`. |
| **P9** Security + audit + retention | **done** | Cross-tenant visibility, export-role enforcement, path traversal rejection, retention fields, and compliance/audit persistence remain covered by `tests/test_protocols.py`, `tests/test_registry_service.py`, and `tests/test_db_postgres.py`. |
| **P10** §15 completion | **done** | Protocol tables, defaults, bootstrap seeding, and additive recovery are now part of the DB schema contract in `tests/test_db_postgres.py`. |
| **P11** Docs + OpenAPI story | **done** | `docs/registry-openapi.json`, `README.md`, `docs/ARCHITECTURE.md`, the renamed protocol guides, and doc contract checks now match the package layout and shipped protocol surfaces in `tests/test_protocol_docs.py` and `tests/test_registry_service.py`. |

### 20.2 Implemented and traceable (strengths)

| Topic | Where |
|--------|--------|
| Task completion → engine → persist | `_advance_protocol_run_for_task_in_tx` → `ProtocolRunEngine.evaluate_task_result()` (`octopus_sdk/protocols/engine.py`) → `_apply_protocol_engine_decision_in_tx` `store_postgres.py` |
| Dispatch → engine → persist | `_dispatch_protocol_stage_in_tx` → registry-side `evaluate_protocol_dispatch()` (`octopus_registry/protocol_runtime.py`) → `ProtocolRunEngine.evaluate_dispatch_resolution()` (`octopus_sdk/protocols/engine.py`) → `_apply_protocol_engine_decision_in_tx` `store_postgres.py` |
| Operator actions (cancel/retry/accept/send-back) | `ProtocolRunEngine.evaluate_operator_action()` `octopus_sdk/protocols/engine.py`; HTTP `resource_act_on_protocol_run` `server.py` |
| Synthetic timeout → engine → persist | `run_protocol_maintenance()` / `_sweep_protocol_timeouts_in_tx` `store_postgres.py` → `ProtocolRunEngine.evaluate_stage_timeout()` |
| Tenancy (runs) | `_protocol_run_visibility_status` / `_protocol_run_detail_in_tx` `store_postgres.py`; `PROTOCOL_NOT_VISIBLE` mapping on run routes in `server.py` |
| Definition visibility | `_protocol_visible_to_access` (~990+) `store_postgres.py` |
| Export | `export_protocol_run` / `resource_export_protocol_run` ~1243+ `server.py` |
| Waiver mode A | `ProtocolArtifactDefinitionRecord` validator in `octopus_sdk/protocols/core.py` |
| Transport avoids double continuation | `delivery_transport.py` `protocol-stage:` short-circuit ~531–532 |
| Canonical builtin bootstrap | `app/db/postgres_init.py` + `octopus_sdk/protocols/bootstrap.py` |
| Protocol run invalidation on stage completion | `resource_routed_task_result` + `_protocol_run_id_from_task_record` `server.py` |
| Structured protocol authoring UI | `octopus_registry/ui/js/components/protocol-workspace.js` + `octopus_registry/ui/css/main.css` |
| Telegram run watch parity | `app/runtime/telegram_protocols.py` + `tests/test_protocol_telegram.py` |
| Checked-in OpenAPI contract | `scripts/generate_registry_openapi.py` + `docs/registry-openapi.json` + `tests/test_registry_service.py` |
| Protocol docs surface | `README.md`, `docs/ARCHITECTURE.md`, `docs/operator-protocol-guide.md`, `docs/author-protocol-guide.md`, `docs/telegram-user-guide.md`, `docs/registry-user-guide.md`, `tests/test_protocol_docs.py` |

### 20.3 Release decisions and carry-forward notes

| Decision / note | Plan | Current state |
|-----|------|----------------|
| Pause / resume | §7.3, §1.6 | Excluded from V1 by product decision; unsupported controls stay hidden across API/UI/Telegram. |
| Definition hard delete | §7.1 | Not part of the shipped lifecycle; archive is the terminal operator-facing lifecycle action for definitions. |
| Waiver mode | §5.3b | Release ships in mode A only (`artifact.verify: false` rejected). Extend schema/workflow only if a future release explicitly adopts mode B. |
| Future schema versions | §8.3 | Legacy-to-current in-memory migration is implemented for shipped versions. Add new migration steps in `migrate_protocol_document_data()` when `PROTOCOL_SCHEMA_VERSION` increments. |
| Contract test growth | §7.6, §13 | The checked-in OpenAPI artifact is locked to the live FastAPI schema and protocol route tests cover the shipped surface; expand scenario depth from this baseline as new protocol capabilities are added. |

### 20.4 How to use this section

- **Engineering:** Treat **§20.1** as the shipped baseline. Any future protocol work must update **this section** and the relevant acceptance criteria in the same PR.
- **Reviewers:** If a future change reopens one of these guarantees, it is a release-level regression, not a “follow-up cleanup”.

---

## Document control

| Version | Date | Notes |
|---------|------|--------|
| 1.0–1.1 | 2026-04-16 | Earlier drafts |
| 2.0 | 2026-04-16 | Holistic refactor by topic |
| 3.0 | 2026-04-16 | Merge: non-negotiables, gaps list, DSL/migrators, artifact observations, remediation path, SDK client errors, named roles, resolution audit, bootstrap §15, admin views, README/ARCHITECTURE, P10/P11 phasing |
| 3.1 | 2026-04-16 | Removed any notion of a separate `protocol_implementation_spec.md`; clarified §1.5, §8.2, §16; fixed P11 cross-reference; acceptance §18 |
| 3.2 | 2026-04-01 | Scrubbed invented `docs/protocol-*.md` paths; §14 lists topics + only real files (`README.md`, `docs/ARCHITECTURE.md`); cross-references fixed |
| 3.3 | 2026-04-01 | Normative §8.2 DSL enums/transitions; §12 resolution algorithm; §5.3a/b waiver modes; §2.3 V1 tenancy; §7.5 schema cross-ref; **P1b** §15 shell; `protocol_plan.md` non-delivery; metadata aligned |
| 3.4 | 2026-04-01 | Implementation status (now **§20**): P1–P11 rollup, strengths, gap citations (code vs plan) |
| 3.5 | 2026-04-01 | **§1.2** canonical applier; **§1.6** Phase E0 + recommendations; **§18.1** rebuild acceptance bar; **§19** execution strategy (E0–E10); **§20** code snapshot; **§17** execution cross-ref |
| 3.6 | 2026-04-01 | **§19.0** review refinements: applier identity, cherry-pick rules, E0/merge risk, realtime-after-commit, E6-before-E7 order; **§19.6–19.7** timeout idempotency + max_review_rounds design note + waiver forward-compat; **§19.10** realtime note; **§19.12** explicit tenancy-before-UI order |
| 3.7 | 2026-04-16 | Closed release decisions in **§1.6**; aligned §7 / §11 / §20 with shipped V1 contract (no pause/resume, archive + created_after + NOT_VISIBLE, DB-backed templates, timeout sweep, Mode A waivers) |
| 3.8 | 2026-04-16 | Final remediation close-out: all P1–P11 phases marked done with current evidence; structured protocol authoring UI, Telegram watch parity, checked-in OpenAPI artifact, protocol operator/author guides, protocol docs contract tests, and canonical bootstrap/maintenance coverage reflected in §20 |
| 3.9 | 2026-04-16 | Strict-compliance reset: status set back to pending, §20 marked stale until re-proven, and SDK path references updated to `octopus_sdk/protocols/` package layout |
| 4.0 | 2026-04-16 | Strict-compliance evidence refresh completed: SDK protocol package split landed, shared routed-task result dedupe fixed, review-loop/API contract proven, strict protocol/property/fuzz/performance tests added, docs/schema contracts updated, and the broad protocol suite re-passed |
| 4.1 | 2026-04-16 | Strict-compliance audit follow-up: status returned to pending, §20 explicitly marked stale again, dispatch ownership references updated to the registry-side helper + engine-resolution split, and path drift (`protocol_engine.py` / `protocols.py`) corrected where touched |

**Date note:** Versions **3.0–3.1** were authored **2026-04-16**; **3.2–3.6** edits are **2026-04-01**; **3.7–4.1** reflect the ongoing strict-compliance passes on **2026-04-16**. The **Last updated** field reflects the latest editorial pass (**v4.1**).
