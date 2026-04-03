from pathlib import Path

import pytest

import app.credential_store as credential_store
from tests.support.config_support import make_config


@pytest.fixture(autouse=True)
def _reset_credential_store_state():
    credential_store.reset_for_test()
    yield
    credential_store.reset_for_test()


def test_init_credential_store_for_config_prefers_bot_credential_key(tmp_path: Path, postgres_db_url: str):
    cfg = make_config(
        data_dir=tmp_path,
        telegram_token="telegram-token-a",
        credential_key="credential-key-a",
        database_url=postgres_db_url,
    )

    store = credential_store.init_credential_store_for_config(cfg)
    store.save("tg:42", "alpha", "API_TOKEN", "secret-value")

    credential_store.reset_for_test()

    rotated_cfg = make_config(
        data_dir=tmp_path,
        telegram_token="telegram-token-b",
        credential_key="credential-key-a",
        database_url=postgres_db_url,
    )
    rotated_store = credential_store.init_credential_store_for_config(rotated_cfg)

    assert rotated_store.load("tg:42") == {"alpha": {"API_TOKEN": "secret-value"}}


def test_init_credential_store_for_config_with_explicit_key_emits_no_fallback_error(
    tmp_path: Path,
    caplog,
    postgres_db_url: str,
):
    cfg = make_config(
        data_dir=tmp_path,
        telegram_token="telegram-token-a",
        credential_key="credential-key-a",
        database_url=postgres_db_url,
    )

    with caplog.at_level("ERROR"):
        credential_store.init_credential_store_for_config(cfg)

    assert not any(
        "Credential encryption is using TELEGRAM_BOT_TOKEN" in record.message
        for record in caplog.records
    )


def test_init_credential_store_for_config_falls_back_to_telegram_token_and_logs_error_guidance(
    tmp_path: Path,
    caplog,
    postgres_db_url: str,
):
    cfg = make_config(
        data_dir=tmp_path,
        telegram_token="telegram-token-a",
        credential_key="",
        database_url=postgres_db_url,
    )

    with caplog.at_level("ERROR"):
        store = credential_store.init_credential_store_for_config(cfg)
        store.save("tg:42", "alpha", "API_TOKEN", "secret-value")
        credential_store.reset_for_test()
        reloaded = credential_store.init_credential_store_for_config(cfg)

    warnings = [
        record.message
        for record in caplog.records
        if "Credential encryption is using TELEGRAM_BOT_TOKEN" in record.message
    ]
    assert len(warnings) == 2
    assert all(
        "Set BOT_CREDENTIAL_KEY in the bot env file before rotating the Telegram bot token."
        in message
        for message in warnings
    )
    assert reloaded.load("tg:42") == {"alpha": {"API_TOKEN": "secret-value"}}


def test_get_credential_store_requires_credential_key_or_telegram_token(monkeypatch):
    monkeypatch.delenv("BOT_CREDENTIAL_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("BOT_DATA_DIR", "/tmp/credential-store-test")

    with pytest.raises(RuntimeError) as exc:
        credential_store.get_credential_store()

    assert "BOT_CREDENTIAL_KEY or TELEGRAM_BOT_TOKEN is required" in str(exc.value)


def test_credential_store_logs_recovery_hint_on_decrypt_failure(
    tmp_path: Path,
    caplog,
    postgres_db_url: str,
):
    original = credential_store.build_credential_store(
        data_dir=tmp_path,
        secret_material="credential-key-a",
        database_url=postgres_db_url,
    )
    original.save("tg:42", "alpha", "API_TOKEN", "secret-value")

    rotated = credential_store.build_credential_store(
        data_dir=tmp_path,
        secret_material="credential-key-b",
        database_url=postgres_db_url,
    )

    with caplog.at_level("ERROR"):
        loaded = rotated.load("tg:42")

    assert loaded == {}
    assert any(
        "set BOT_CREDENTIAL_KEY to the previous key material to recover" in record.message
        for record in caplog.records
    )
