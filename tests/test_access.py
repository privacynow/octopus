"""Access policy contracts and SQLite DB-layer helper tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import access
from app.identity import telegram_actor_key
from app.runtime.inbound_types import InboundUser
from app.work_queue_sqlite_impl import (
    _create_new_transport_db,
    get_user_access_override,
    list_user_access,
    set_user_access,
)
from tests.support.config_support import make_config


def _config():
    return make_config(
        data_dir=Path("/tmp/test-access"),
        allow_open=False,
        allowed_actor_keys=frozenset({telegram_actor_key(100)}),
        allowed_usernames=frozenset(),
    )


def test_is_allowed_user_no_override_uses_config_allow():
    cfg = _config()
    user = InboundUser(id=telegram_actor_key(100), username="trusted")
    assert access.is_allowed_user(cfg, user) is True


def test_is_allowed_user_no_override_uses_config_deny():
    cfg = _config()
    user = InboundUser(id=telegram_actor_key(200), username="stranger")
    assert access.is_allowed_user(cfg, user) is False


def test_is_allowed_user_with_override_blocked_beats_config_allow():
    cfg = _config()
    user = InboundUser(id=telegram_actor_key(100), username="trusted")
    assert access.is_allowed_user_with_override(cfg, user, "blocked") is False


def test_is_allowed_user_with_override_allowed_beats_config_deny():
    cfg = _config()
    user = InboundUser(id=telegram_actor_key(200), username="stranger")
    assert access.is_allowed_user_with_override(cfg, user, "allowed") is True


def test_is_allowed_user_with_override_none_falls_through_to_config():
    cfg = _config()
    trusted = InboundUser(id=telegram_actor_key(100), username="trusted")
    stranger = InboundUser(id=telegram_actor_key(200), username="stranger")
    assert access.is_allowed_user_with_override(cfg, trusted, None) is True
    assert access.is_allowed_user_with_override(cfg, stranger, None) is False


def test_get_user_access_override_missing_returns_none():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    assert get_user_access_override(conn, telegram_actor_key(100)) is None
    conn.close()


def test_set_user_access_upserts_and_get_reads_latest_value():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    set_user_access(conn, telegram_actor_key(100), "allowed", "initial allow", telegram_actor_key(1))
    assert get_user_access_override(conn, telegram_actor_key(100)) == "allowed"
    set_user_access(conn, telegram_actor_key(100), "blocked", "reversed", telegram_actor_key(2))
    rows = list_user_access(conn)
    assert len(rows) == 1
    assert rows[0]["actor_key"] == telegram_actor_key(100)
    assert rows[0]["access"] == "blocked"
    assert rows[0]["reason"] == "reversed"
    assert rows[0]["granted_by"] == telegram_actor_key(2)
    conn.close()


def test_list_user_access_returns_rows_ordered_by_latest_grant():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_new_transport_db(conn)
    set_user_access(conn, telegram_actor_key(100), "allowed", "first", telegram_actor_key(1))
    set_user_access(conn, telegram_actor_key(200), "blocked", "second", telegram_actor_key(2))
    rows = list_user_access(conn)
    assert {row["actor_key"] for row in rows} == {
        telegram_actor_key(100),
        telegram_actor_key(200),
    }
    assert rows[0]["granted_at"] >= rows[-1]["granted_at"]
    conn.close()
