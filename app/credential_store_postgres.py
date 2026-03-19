"""Postgres implementation of the credential store."""

from __future__ import annotations

from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row

from app.credential_store_base import AbstractCredentialStore
from app.db.postgres import get_connection

_SCHEMA = "bot_credentials"
_INIT_SQL = f"""\
CREATE SCHEMA IF NOT EXISTS {_SCHEMA};
CREATE TABLE IF NOT EXISTS {_SCHEMA}.credentials (
    actor_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    cred_key TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    PRIMARY KEY(actor_key, skill_name, cred_key)
);
"""


class PostgresCredentialStore(AbstractCredentialStore):
    def __init__(
        self,
        database_url: str,
        *,
        encryption_key: bytes,
        pool_min: int = 1,
        pool_max: int = 10,
        connect_timeout: int = 10,
    ) -> None:
        self._database_url = database_url
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._connect_timeout = connect_timeout
        self._fernet = Fernet(encryption_key)
        self._schema_ready = False

    @contextmanager
    def _connect(self):
        with get_connection(
            self._database_url,
            min_size=self._pool_min,
            max_size=self._pool_max,
            connect_timeout=self._connect_timeout,
        ) as conn:
            self._ensure_schema(conn)
            yield conn

    def _ensure_schema(self, conn) -> None:
        if self._schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(_INIT_SQL)
        conn.commit()
        self._schema_ready = True

    def list_skill_names(self, actor_key: str) -> list[str]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT skill_name
                    FROM {_SCHEMA}.credentials
                    WHERE actor_key = %s
                    ORDER BY skill_name
                    """,
                    (actor_key,),
                )
                rows = cur.fetchall()
        return [str(row["skill_name"]) for row in rows]

    def load(self, actor_key: str) -> dict[str, dict[str, str]]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT skill_name, cred_key, encrypted_value
                    FROM {_SCHEMA}.credentials
                    WHERE actor_key = %s
                    ORDER BY skill_name, cred_key
                    """,
                    (actor_key,),
                )
                rows = cur.fetchall()
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            try:
                value = self._fernet.decrypt(str(row["encrypted_value"]).encode("utf-8")).decode("utf-8")
            except (InvalidToken, ValueError, TypeError):
                continue
            result.setdefault(str(row["skill_name"]), {})[str(row["cred_key"])] = value
        return result

    def save(
        self,
        actor_key: str,
        skill_name: str,
        cred_key: str,
        value: str,
    ) -> None:
        encrypted = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.credentials (actor_key, skill_name, cred_key, encrypted_value)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(actor_key, skill_name, cred_key) DO UPDATE SET
                        encrypted_value = EXCLUDED.encrypted_value
                    """,
                    (actor_key, skill_name, cred_key, encrypted),
                )
            conn.commit()

    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if skill_name:
                    cur.execute(
                        f"""
                        SELECT DISTINCT skill_name
                        FROM {_SCHEMA}.credentials
                        WHERE actor_key = %s AND skill_name = %s
                        """,
                        (actor_key, skill_name),
                    )
                    rows = cur.fetchall()
                    removed = [str(row["skill_name"]) for row in rows]
                    if removed:
                        cur.execute(
                            f"DELETE FROM {_SCHEMA}.credentials WHERE actor_key = %s AND skill_name = %s",
                            (actor_key, skill_name),
                        )
                        conn.commit()
                    return removed

                cur.execute(
                    f"""
                    SELECT DISTINCT skill_name
                    FROM {_SCHEMA}.credentials
                    WHERE actor_key = %s
                    ORDER BY skill_name
                    """,
                    (actor_key,),
                )
                rows = cur.fetchall()
                removed = [str(row["skill_name"]) for row in rows]
                if removed:
                    cur.execute(
                        f"DELETE FROM {_SCHEMA}.credentials WHERE actor_key = %s",
                        (actor_key,),
                    )
                    conn.commit()
                return removed
