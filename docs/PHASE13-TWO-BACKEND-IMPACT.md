# Phase 13 two-backend Local Runtime — impact statement

## Contracts
- **Session store contract**: backend-neutral behavior (session_exists, default load, save/load roundtrip, delete, list ordering, lazy creation, JSON migration if kept). Exercised via storage.* facade only.
- **Transport store contract**: update journal idempotency, payload persistence, enqueue/claim semantics, per-chat serialization, complete/fail, pending recovery, replay/discard, stale claim recovery, backend-neutral corruption boundaries. Exercised via work_queue.* facade only.

## Owners
- Backend selection: `app/runtime_backend.py`
- Session facade: `app/storage.py`; implementations: `storage_sqlite.py`, `storage_postgres.py`
- Transport facade: `app/work_queue.py`; implementations: `work_queue_sqlite.py` + `work_queue_sqlite_impl.py`, `work_queue_postgres.py` + `work_queue_pg.py`

## Entry points
- New: `tests/contracts/test_session_store_contract.py`, `tests/contracts/test_transport_store_contract.py` (parameterized by backend: sqlite, postgres).
- Existing tests: rationalize test_storage.py, test_work_queue.py, test_sqlite_integration.py, test_workitem_integration.py, test_storage_pg.py, test_work_queue_pg.py so contract suites own backend-neutral behavior; impl tests own backend-specific details.

## Durable state
- Session/transport stores (SQLite files or Postgres tables). Contract tests use temp dirs (SQLite) or truncated Postgres DB (postgres_truncated fixture).

## Failure paths
- Postgres contract tests skip when Docker/Postgres harness unavailable (same as existing postgres_truncated).
- No new branches above the seam; failures indicate backend or contract bug.

## Invariants
- One backend seam; facades delegate only; no SQLite-only symbols in facade.
- SQLite = default path (startup, docs, E2E); Postgres = supported alternate.
- Both backends satisfy the same contract suites.

## Tests
- Add: contract suites (session + transport), parameterized sqlite | postgres.
- Rationalize: move backend-neutral assertions into contract suites; keep impl-specific tests in test_storage.py, test_work_queue.py, test_storage_pg.py, test_work_queue_pg.py or remove duplicates.
- E2E: primary = SQLite Local Runtime; bounded Postgres coverage.
