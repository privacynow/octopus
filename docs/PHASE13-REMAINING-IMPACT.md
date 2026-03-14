# Phase 13 remaining work — impact statement

## Contracts being changed
- **Transport facade:** `work_queue.py` public surface becomes product/runtime API only; no SQLite-only helpers.
- **Test reset:** Single owner for backend lifecycle; handler reset only clears handler globals.
- **Session/transport behavior:** New contract suites define backend-neutral behavior; existing suites rationalized.

## Authoritative owners
- Backend selection: `app/runtime_backend.py`
- Session facade: `app/storage.py` (delegates to `runtime_backend.session_store()`)
- Transport facade: `app/work_queue.py` (delegates to `runtime_backend.transport_store()`)
- SQLite session impl: `app/storage_sqlite.py`
- SQLite transport impl: `app/work_queue_sqlite.py` + `app/work_queue_sqlite_impl.py`
- Test reset: `runtime_backend.reset_for_test()`; handler_support clears only handler state.

## Affected entry points (rg)
- `app/work_queue.py`: remove re-exports; callers that used `_transport_db`, `_reset_transport_db`, `_write_tx`, `_validate_work_item_row`, `_SCHEMA_VERSION`, `_assert_no_invalid_rows_for_chat`, `_claim_queued_item`, `_load_work_item_by_id`, `_insert_initial_work_item` must use store or sqlite_impl.
- Tests: `tests/test_work_queue.py`, `tests/test_workitem_integration.py`, `tests/test_invariants.py` (any import from work_queue of the above).
- `tests/support/handler_support.py`: remove redundant close_all_db / close_all_transport_db after reset_for_test.

## Durable state touched
- None for 1A/1B. Contract suites and E2E touch session/transport stores via existing APIs.

## Failure paths
- Tests that assumed facade re-exports break until updated to use `runtime_backend.transport_store()` or `work_queue_sqlite_impl`.
- Reset: if close_all is removed and something still holds references, isolation could change; reset_for_test() already closes old backend.

## Invariants
- Facade exports no SQLite-only symbols.
- One backend reset owner; handler reset does not duplicate store cleanup.
- Contract suites run against SQLite and define backend-neutral behavior.
- Local Runtime is the default path in main, scripts, compose, README, E2E.

## Tests to add/move/update/delete
- Add: `tests/contracts/test_session_store_contract.py`, `tests/contracts/test_transport_store_contract.py`.
- Update: `test_work_queue.py` — use store or `work_queue_sqlite_impl` for any SQLite-internal use; keep facade-level tests.
- Update: `test_workitem_integration.py`, `test_invariants.py` — replace work_queue._transport_db with `runtime_backend.transport_store()._transport_db` where needed.
- E2E: primary flow is Local Runtime (no BOT_DATABASE_URL).
