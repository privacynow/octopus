"""Shared Postgres store support for registry persistence modules."""

from __future__ import annotations

from contextlib import contextmanager

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


def jsonb(value: object) -> Jsonb:
    return Jsonb(json_ready(value))
