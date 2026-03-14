# Phase 13 follow-up — impact statement

## Contracts
- E2E: Postgres-bounded test must run bot with BOT_DATABASE_URL set (real Postgres backend).
- E2E: One module-scoped image build; no duplicate build for same tag.
- README: Troubleshooting must state BOT_DATABASE_URL optional, SQLite default.

## Owner
- tests/e2e/test_compose_flows.py: fixture shape, Postgres override, image build.
- tests/e2e/test_compose_flows_probe.py: harness contract tests.
- README.md: troubleshooting section.

## Entry points
- compose_ctx (unchanged env; no BOT_DATABASE_URL).
- New: postgres_bot_override_path(ctx) + compose_ctx_postgres_bot fixture.
- bot_image_built: single build; bot_image_built_sqlite_only removed.
- test_compose_bot_startup_with_postgres uses compose_ctx_postgres_bot so bot gets BOT_DATABASE_URL.

## Failure paths
- Postgres test fails if override file not applied or URL wrong.
- Probe test fails if override content does not contain BOT_DATABASE_URL.

## Invariants
- Primary gate remains SQLite (no BOT_DATABASE_URL). Bounded Postgres test proves Postgres backend when override applied.
- Image built once per module run.

## Tests
- Add: probe test that Postgres override content contains BOT_DATABASE_URL and postgresql://.
- Update: test_compose_bot_startup_with_postgres to use compose_ctx_postgres_bot; test_compose_sqlite_local_runtime_primary to use bot_image_built.
- Run: test_compose_flows_probe.py, test_compose_flows.py (E2E_COMPOSE=1).
