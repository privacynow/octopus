"""SQLite implementation of the credential store."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.credential_store_base import AbstractCredentialStore

log = logging.getLogger(__name__)

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS credentials (
    actor_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    cred_key TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    PRIMARY KEY(actor_key, skill_name, cred_key)
)
"""


class SQLiteCredentialStore(AbstractCredentialStore):
    def __init__(self, db_path: Path, *, encryption_key: bytes) -> None:
        self._db_path = db_path
        self._fernet = Fernet(encryption_key)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_INIT_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def list_skill_names(self, actor_key: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT skill_name
                FROM credentials
                WHERE actor_key = ?
                ORDER BY skill_name
                """,
                (actor_key,),
            ).fetchall()
        return [str(row["skill_name"]) for row in rows]

    def load(self, actor_key: str) -> dict[str, dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT skill_name, cred_key, encrypted_value
                FROM credentials
                WHERE actor_key = ?
                ORDER BY skill_name, cred_key
                """,
                (actor_key,),
            ).fetchall()
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
                "If TELEGRAM_BOT_TOKEN recently changed, set BOT_CREDENTIAL_KEY "
                "to the previous key material to recover.",
                actor_key,
            )
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
            conn.execute(
                """
                INSERT INTO credentials (actor_key, skill_name, cred_key, encrypted_value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(actor_key, skill_name, cred_key) DO UPDATE SET
                    encrypted_value = excluded.encrypted_value
                """,
                (actor_key, skill_name, cred_key, encrypted),
            )
            conn.commit()

    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]:
        with self._connect() as conn:
            if skill_name:
                rows = conn.execute(
                    "SELECT DISTINCT skill_name FROM credentials WHERE actor_key = ? AND skill_name = ?",
                    (actor_key, skill_name),
                ).fetchall()
                removed = [str(row["skill_name"]) for row in rows]
                if removed:
                    conn.execute(
                        "DELETE FROM credentials WHERE actor_key = ? AND skill_name = ?",
                        (actor_key, skill_name),
                    )
                    conn.commit()
                return removed

            rows = conn.execute(
                "SELECT DISTINCT skill_name FROM credentials WHERE actor_key = ? ORDER BY skill_name",
                (actor_key,),
            ).fetchall()
            removed = [str(row["skill_name"]) for row in rows]
            if removed:
                conn.execute("DELETE FROM credentials WHERE actor_key = ?", (actor_key,))
                conn.commit()
            return removed
