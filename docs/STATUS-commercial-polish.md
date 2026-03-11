# Commercial Polish - Implementation Status

Current as of 2026-03-11. Tracks progress against
[PLAN-commercial-polish.md](PLAN-commercial-polish.md).

---

## Current Snapshot

- Phases 1-10 are sealed as shipped.
- The next planned roadmap item is Phase 11, Workflow Ownership Extraction.
- The shipped runtime still uses SQLite-backed session and transport stores
  today; the roadmap shifts runtime authority to Postgres in Phases 12-14.
- `transport idempotency` is shipped in Phase 9.
- `content dedup` is intentionally unshipped and remains future work in
  Phase 17.

---

## Linear Roadmap Status

| Phase | Scope | Status | Note |
|------:|-------|--------|------|
| 1 | Core Telegram loop | Done | Core request/response, file flow, and session commands shipped. |
| 2 | Safety, approvals, and rate limiting | Done | Approval, retry, `/cancel`, `/doctor`, and rate limiting shipped. |
| 3 | Roles and instruction-only skills | Done | Roles and instruction-only capability surfacing shipped. |
| 4 | Credentialed and provider-specific skills | Done | Credential capture, encrypted storage, and provider-specific setup shipped. |
| 5 | Skill store and capability distribution | Done | Managed store, registry install/search, and digest verification shipped. |
| 6 | Output, compact mode, and progress UX | Done | Compact/raw/export, expand/collapse, summary-first, and normalized progress shipped. |
| 7 | Durable session state and execution context | Done | Typed session state and authoritative resolved execution context shipped. |
| 8 | Public trust, model profiles, and settings UX | Done | Mixed trust, model profiles, and inline settings UX shipped. |
| 9 | Durable transport, transport idempotency, webhook mode, and restart recovery | Done | Durable queue, webhook path, replay/discard recovery, and polling conflict detection shipped. |
| 10 | Structural hardening, invariants, and test ownership | Done | Invariant coverage, test ownership refactor, and runtime isolation hardening shipped. |
| 11 | Workflow ownership extraction | Planned | Behavior-preserving extraction of transport/recovery and approval/retry owners. |
| 12 | Postgres runtime cutover | Planned | Postgres becomes the sole supported runtime backend after migration. |
| 13 | Postgres queue authority in webhook mode | Planned | Core request transport stays app-owned in Postgres. |
| 14 | Multi-process / multi-worker deployment | Planned | Shared Postgres queue authority expands to cross-process ingress and workers. |
| 15 | Durability confidence phase | Planned | Add crash, lease, webhook, and cross-process confidence coverage. |
| 16 | Product polish on stable foundations | Planned | `/project` inline keyboard and optional verbose progress. |
| 17 | Behavior extensions | Planned | Demand-gated `content dedup` and richer project/policy scope. |
| 18 | Registry trust and governance | Planned | Publisher signing and organizational trust policy on top of digest verification. |
| 19 | Usage accounting, quotas, and billing | Planned | Usage recording, quota enforcement, and billing built last. |

---

## Recent Shipped Work

- Test isolation and safe parallel default: one authoritative test-runtime
  reset path, cache teardown, isolation regression tests, and default
  `pytest -v -n 4`.
- Fresh command ownership race fix: inline handler-owned work items start
  claimed so the background worker cannot steal fresh lock-free commands and
  emit false recovery notices.
- Progress regression fixtures: checked-in Codex and Claude raw traces now
  protect the normalized progress-event/rendering contract.
- Restart recovery hardening: durable `pending_recovery`, replay/discard
  ownership, fresh-message supersession, and `ReclaimBlocked` handling are
  shipped and tested.

---

## Sealed History

These are the shipped phases as sealed historical sections. They stay here so
the current status doc remains readable without deleting the product's build
lineage.

### Phase 1 - Core Telegram Loop

Shipped the core Telegram request/response loop, file handling, basic
formatting, and the foundational `/help`, `/start`, `/new`, and `/session`
commands.

### Phase 2 - Safety, Approvals, and Rate Limiting

Shipped approval and retry flows, stale-context rejection, `/cancel`,
runtime health visibility through `/doctor`, and request throttling.

### Phase 3 - Roles and Instruction-Only Skills

Shipped the first visible capability layer for roles and instruction-only
skills. Detailed implementation history remains in the archived
roles/skills plan and status docs.

### Phase 4 - Credentialed and Provider-Specific Skills

Shipped conversational credential setup, encrypted per-user storage, setup
state ownership in shared chats, and provider-specific skill compatibility
handling.

### Phase 5 - Skill Store and Capability Distribution

Shipped the managed content-addressed store, refs/object model, registry
artifact verification, install/update/search flows, and capability
distribution tooling.

### Phase 6 - Output, Compact Mode, and Progress UX

Shipped table rendering, robust HTML splitting, compact mode, `/raw`,
history export, summary-first output, expand/collapse behavior, heartbeat,
and the shared progress-event/rendering contract.

### Phase 7 - Durable Session State and Execution Context

Shipped typed `SessionState`, `PendingApproval`, and `PendingRetry`
boundaries, the authoritative resolved execution context, per-chat project
binding, file policy, and context-hash invalidation.

### Phase 8 - Public Trust, Model Profiles, and Settings UX

Shipped mixed-trust public mode, resolved-context public restrictions,
stable user-facing model profiles, and inline keyboard settings flows.

### Phase 9 - Durable Transport, Transport Idempotency, Webhook Mode, and Restart Recovery

Shipped the durable `update_id` journal, `updates` and `work_items`
transport state, queued/busy feedback, webhook support, polling-conflict
detection, and explicit replay/discard recovery for interrupted work.

### Phase 10 - Structural Hardening, Invariants, and Test Ownership

Shipped the invariant and owner-suite cleanup that sealed the current
runtime: ownership refactor, duplicate-test removal, recovery and progress
contract coverage, and test-runtime isolation hardening.

---

## Verification Snapshot

- Canonical full-suite runner: `./scripts/test_all.sh`
- Current suite snapshot: 787 pytest tests + 36 bash tests
- Default pytest addopts: `-v -n 4`
- Full suite currently runs on Linux and macOS

Historical deep dives remain available in git history and the owner docs, but
new roadmap work should advance Phases 11-19 rather than reopening the sealed
phases above.
