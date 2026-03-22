"""Credential-store contract: backend-neutral encrypted credential behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.credential_store import derive_credential_encryption_key
from app.credential_store_postgres import PostgresCredentialStore
from app.credential_store_sqlite import SQLiteCredentialStore

_TEST_KEY = derive_credential_encryption_key("credential-store-contracts")


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path: Path):
    if request.param == "sqlite":
        yield SQLiteCredentialStore(tmp_path / "credentials.db", encryption_key=_TEST_KEY)
        return

    postgres_url = request.getfixturevalue("postgres_credentials_truncated")
    yield PostgresCredentialStore(postgres_url, encryption_key=_TEST_KEY)


def test_roundtrip_save_and_load(store):
    store.save("tg:42", "github", "GITHUB_TOKEN", "ghp_test")
    store.save("tg:42", "github", "GITHUB_ORG", "acme")

    loaded = store.load("tg:42")

    assert loaded == {"github": {"GITHUB_ORG": "acme", "GITHUB_TOKEN": "ghp_test"}}


def test_load_for_skills_filters_to_requested_skill_names(store):
    store.save("tg:42", "alpha", "ALPHA_TOKEN", "a")
    store.save("tg:42", "beta", "BETA_TOKEN", "b")

    loaded = store.load_for_skills("tg:42", ["beta", "missing", "beta"])

    assert loaded == {"beta": {"BETA_TOKEN": "b"}}


def test_per_user_isolation(store):
    store.save("tg:100", "alpha", "API_TOKEN", "alice")
    store.save("tg:200", "alpha", "API_TOKEN", "bob")

    assert store.load("tg:100") == {"alpha": {"API_TOKEN": "alice"}}
    assert store.load("tg:200") == {"alpha": {"API_TOKEN": "bob"}}


def test_delete_one_skill_preserves_others(store):
    store.save("tg:42", "alpha", "ALPHA_TOKEN", "a")
    store.save("tg:42", "beta", "BETA_TOKEN", "b")

    removed = store.delete("tg:42", "alpha")

    assert removed == ["alpha"]
    assert store.load("tg:42") == {"beta": {"BETA_TOKEN": "b"}}


def test_delete_all_returns_complete_skill_list(store):
    store.save("tg:42", "alpha", "ALPHA_TOKEN", "a")
    store.save("tg:42", "beta", "BETA_TOKEN", "b")

    removed = store.delete("tg:42")

    assert removed == ["alpha", "beta"]
    assert store.load("tg:42") == {}
    assert store.list_skill_names("tg:42") == []


def test_missing_actor_loads_empty(store):
    assert store.load("tg:404") == {}
    assert store.list_skill_names("tg:404") == []


def test_list_skill_names_does_not_require_decryption(store):
    store.save("tg:42", "alpha", "ALPHA_TOKEN", "a")
    store.save("tg:42", "beta", "BETA_TOKEN", "b")

    assert store.list_skill_names("tg:42") == ["alpha", "beta"]


def test_corrupted_entry_is_skipped(tmp_path: Path):
    db_path = tmp_path / "credentials.db"
    store = SQLiteCredentialStore(db_path, encryption_key=_TEST_KEY)
    store.save("tg:42", "alpha", "ALPHA_TOKEN", "good")

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO credentials (actor_key, skill_name, cred_key, encrypted_value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(actor_key, skill_name, cred_key) DO UPDATE SET
                encrypted_value = excluded.encrypted_value
            """,
            ("tg:42", "beta", "BETA_TOKEN", json.dumps({"bad": True})),
        )
        conn.commit()

    loaded = store.load("tg:42")

    assert loaded == {"alpha": {"ALPHA_TOKEN": "good"}}
