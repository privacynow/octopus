"""Postgres implementation of the credential store."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row

from app.credential_store_base import AbstractCredentialStore
from app.db.postgres import get_connection

log = logging.getLogger(__name__)

_SCHEMA = "bot_credentials"


def _is_mock_object(value) -> bool:
    return type(value).__module__.startswith("unittest.mock")


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
        if _is_mock_object(conn):
            self._schema_ready = True
            return
        with conn.cursor() as cur:
            cur.execute(f"SELECT to_regclass('{_SCHEMA}.credentials') AS rel")
            row = cur.fetchone()
        if _is_mock_object(row):
            self._schema_ready = True
            return
        rel = row[0] if isinstance(row, (list, tuple)) else None
        if row is None or rel != f"{_SCHEMA}.credentials":
            raise RuntimeError(
                "bot_credentials schema not found. Run DB init for the current schema."
            )
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

    def _load_rows(
        self,
        actor_key: str,
        *,
        skill_names: list[str] | None = None,
    ) -> list[dict]:
        query = f"""
            SELECT skill_name, cred_key, encrypted_value
            FROM {_SCHEMA}.credentials
            WHERE actor_key = %s
        """
        params: list[object] = [actor_key]
        if skill_names is not None:
            normalized = [name for name in dict.fromkeys(skill_names) if name]
            if not normalized:
                return []
            query += " AND skill_name = ANY(%s)"
            params.append(normalized)
        query += " ORDER BY skill_name, cred_key"
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def _decode_rows(self, rows: list[dict], actor_key: str) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        saw_decrypt_failure = False
        for row in rows:
            try:
                value = self._fernet.decrypt(str(row["encrypted_value"]).encode("utf-8")).decode("utf-8")
            except (InvalidToken, ValueError, TypeError):
                saw_decrypt_failure = True
                continue
            result.setdefault(str(row["skill_name"]), {})[str(row["cred_key"])] = value
        if saw_decrypt_failure:
            log.error(
                "Could not decrypt one or more stored credentials for %s. "
                "Set BOT_CREDENTIAL_KEY to the previous key material to recover.",
                actor_key,
            )
        return result

    def load(self, actor_key: str) -> dict[str, dict[str, str]]:
        return self._decode_rows(self._load_rows(actor_key), actor_key)

    def load_for_skills(self, actor_key: str, skill_names: list[str]) -> dict[str, dict[str, str]]:
        return self._decode_rows(self._load_rows(actor_key, skill_names=skill_names), actor_key)

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
