"""Access control contracts: config baseline plus DB override precedence."""

from __future__ import annotations

import sqlite3

from app import access
from app.transport import InboundUser
from app.work_queue_sqlite_impl import (
    _create_new_transport_db,
    get_user_access_override,
    list_user_access,
    set_user_access,
)
from tests.support.config_support import make_config


def _init_user_access_db(db_path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE user_access (
            user_id INTEGER PRIMARY KEY,
            access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')),
            reason TEXT NOT NULL DEFAULT '',
            granted_by INTEGER NOT NULL DEFAULT 0,
            granted_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_override(db_path, user_id: int, value: str, reason: str = "") -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO user_access (user_id, access, reason, granted_by, granted_at) VALUES (?, ?, ?, 1, 1.0)",
        (user_id, value, reason),
    )
    conn.commit()
    conn.close()


def test_is_allowed_user_no_override_uses_config_allow(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        allow_open=False,
        allowed_user_ids=frozenset({100}),
        allowed_usernames=frozenset(),
    )
    user = InboundUser(id=100, username="trusted")
    assert access.is_allowed_user(cfg, user) is True


def test_is_allowed_user_no_override_uses_config_deny(tmp_path):
    cfg = make_config(
        data_dir=tmp_path,
        allow_open=False,
        allowed_user_ids=frozenset({100}),
        allowed_usernames=frozenset(),
    )
    user = InboundUser(id=200, username="stranger")
    assert access.is_allowed_user(cfg, user) is False


def test_is_allowed_user_block_override_wins_over_config_allow(tmp_path):
    db_path = tmp_path / "transport.db"
    _init_user_access_db(db_path)
    _insert_override(db_path, 100, "blocked", "manual block")
    cfg = make_config(
        data_dir=tmp_path,
        allow_open=False,
        allowed_user_ids=frozenset({100}),
        allowed_usernames=frozenset(),
    )
    user = InboundUser(id=100, username="trusted")
    assert access.is_allowed_user(cfg, user) is False


def test_is_allowed_user_allow_override_wins_over_config_deny(tmp_path):
    db_path = tmp_path / "transport.db"
    _init_user_access_db(db_path)
    _insert_override(db_path, 200, "allowed", "temporary allow")
    cfg = make_config(
        data_dir=tmp_path,
        allow_open=False,
        allowed_user_ids=frozenset({100}),
        allowed_usernames=frozenset(),
    )
    user = InboundUser(id=200, username="stranger")
    assert access.is_allowed_user(cfg, user) is True


def test_db_access_override_returns_none_when_transport_db_missing(tmp_path):
    assert access._db_access_override(tmp_path, 100) is None


def test_get_user_access_override_missing_returns_none():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    assert get_user_access_override(conn, 100) is None
    conn.close()


def test_set_user_access_upserts_and_get_reads_latest_value():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    set_user_access(conn, 100, "allowed", "initial allow", 1)
    assert get_user_access_override(conn, 100) == "allowed"
    set_user_access(conn, 100, "blocked", "reversed", 2)
    rows = list_user_access(conn)
    assert len(rows) == 1
    assert rows[0]["user_id"] == 100
    assert rows[0]["access"] == "blocked"
    assert rows[0]["reason"] == "reversed"
    assert rows[0]["granted_by"] == 2
    conn.close()


def test_list_user_access_returns_rows_ordered_by_latest_grant():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    set_user_access(conn, 100, "allowed", "first", 1)
    set_user_access(conn, 200, "blocked", "second", 2)
    rows = list_user_access(conn)
    assert {row["user_id"] for row in rows} == {100, 200}
    assert rows[0]["granted_at"] >= rows[-1]["granted_at"]
    conn.close()
