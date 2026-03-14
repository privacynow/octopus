# Phase 13 redo: contract-first preamble

## Contract being changed

Backend selection for session store and transport store. Replacing three mutable sources of truth (`runtime_backend._database_url`, `storage._pg_url`, `work_queue._pg_url`) and 25+ branch points in facades with a single owner and zero backend conditionals in facades.

## Authoritative owner

`app/runtime_backend.py` owns the one selected backend object (exposing `session_store` and `transport_store`). No backend-selection state remains in `storage.py` or `work_queue.py`.

## Affected entry points (from rg)

- `app/main.py`: init, ensure_data_dirs, close_db, close_transport_db, recover_stale_claims, purge_old
- `app/telegram_handlers.py`: storage.*, work_queue.*
- `app/worker.py`: work_queue.*
- `app/doctor.py`: storage.list_sessions, storage.load_session
- `app/transport.py`: storage.build_upload_path, storage.is_image_path
- `tests/support/handler_support.py`: reset, storage/work_queue imports
- All tests importing app.storage or app.work_queue

## Durable state touched

Session and transport tables (SQLite or Postgres). No schema or semantics change; only who selects the backend and how facades delegate.

## Failure paths

- init() not called before first use: accessors raise or lazy-init to SQLite.
- reset_for_test(): close current backend’s resources, set backend to fresh SQLite.
- Connection/DB errors propagate from concrete backends unchanged.

## Required invariants

1. After init(config), session_store() and transport_store() return the backend’s stores and do not change until reset.
2. Exported facade functions in storage.py and work_queue.py contain zero backend conditionals.
3. Test reset clears one selection only (one call to runtime_backend.reset_for_test()).

## Exact tests to run

- tests/test_config.py
- tests/test_storage.py
- tests/test_work_queue.py
- tests/test_sqlite_integration.py
- tests/test_workitem_integration.py
- tests/test_storage_pg.py (if Postgres wired)
- tests/test_work_queue_pg.py (if Postgres wired)
