"""Shared Postgres store support for registry persistence modules."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
import time

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .store_dialect import StoreDialect
from .store_shared.common import json_ready

SCHEMA = "agent_registry"


class PostgresStoreDialect(StoreDialect):
    def placeholder(self, index: int) -> str:
        return "%s"

    def qualify(self, table: str) -> str:
        return f"{SCHEMA}.{table}"

    def json_text(self, json_expr: str, key: str) -> str:
        return f"{json_expr}->>'{key}'"

    def json_path_text(self, json_expr: str, *path: str) -> str:
        if not path:
            raise ValueError("json_path_text requires at least one path component")
        *parents, leaf = path
        expr = json_expr
        for key in parents:
            expr = f"{expr}->'{key}'"
        return f"{expr}->>'{leaf}'"

    def usage_token_predicate(self, metadata_expr: str) -> str:
        return f"{metadata_expr} ? 'prompt_tokens'"

    def execute(self, conn, sql: str, params=()):
        with cur(conn) as db_cur:
            db_cur.execute(sql, params)
            return db_cur.rowcount

    def fetchone(self, conn, sql: str, params=()):
        with cur(conn) as db_cur:
            db_cur.execute(sql, params)
            row = db_cur.fetchone()
        return None if row is None else dict(row)

    def fetchall(self, conn, sql: str, params=()):
        with cur(conn) as db_cur:
            db_cur.execute(sql, params)
            rows = db_cur.fetchall()
        return [dict(row) for row in rows]


POSTGRES_STORE_DIALECT = PostgresStoreDialect()


@contextmanager
def cur(conn):
    db_cur = conn.cursor(row_factory=dict_row)
    try:
        yield db_cur
    finally:
        db_cur.close()


@contextmanager
def write_tx(conn):
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def is_retryable_tx_error(exc: BaseException) -> bool:
    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    return isinstance(exc, (errors.DeadlockDetected, errors.SerializationFailure)) or sqlstate in {"40P01", "40001"}


def run_write_tx_with_retry(connect: Callable[[], object], operation: Callable[[object], object], *, attempts: int = 3) -> object:
    last_error: BaseException | None = None
    for attempt in range(max(1, int(attempts or 1))):
        try:
            with connect() as conn, write_tx(conn):
                return operation(conn)
        except BaseException as exc:
            if not is_retryable_tx_error(exc):
                raise
            last_error = exc
            if attempt >= max(1, int(attempts or 1)) - 1:
                break
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Transaction retry helper exited without running operation.")


def jsonb(value: object) -> Jsonb:
    return Jsonb(json_ready(value))
