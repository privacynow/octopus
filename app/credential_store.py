"""Factory helpers and runtime singleton for the shared credential store."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.credential_store_base import AbstractCredentialStore

log = logging.getLogger(__name__)

_store: AbstractCredentialStore | None = None
_store_key: tuple[str, str, str, int, int, int] | None = None
_fallback_warning_emitted = False

_HKDF_SALT = b"telegram-agent-bot.credentials.v1"
_HKDF_INFO = b"telegram-agent-bot.fernet-key"


def derive_credential_encryption_key(secret_material: str) -> bytes:
    """Derive a Fernet-compatible key from runtime secret material using HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    raw = hkdf.derive(secret_material.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def build_credential_store(
    *,
    data_dir: Path,
    secret_material: str,
    database_url: str = "",
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> AbstractCredentialStore:
    encryption_key = derive_credential_encryption_key(secret_material)
    if database_url:
        from app.credential_store_postgres import PostgresCredentialStore

        return PostgresCredentialStore(
            database_url,
            encryption_key=encryption_key,
            pool_min=pool_min,
            pool_max=pool_max,
            connect_timeout=connect_timeout,
        )

    from app.credential_store_sqlite import SQLiteCredentialStore

    return SQLiteCredentialStore(data_dir / "credentials.db", encryption_key=encryption_key)


def init_credential_store(
    *,
    data_dir: Path,
    secret_material: str,
    database_url: str = "",
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> AbstractCredentialStore:
    global _store, _store_key
    key = (str(data_dir), secret_material, database_url, pool_min, pool_max, connect_timeout)
    if _store is None or _store_key != key:
        _store = build_credential_store(
            data_dir=data_dir,
            secret_material=secret_material,
            database_url=database_url,
            pool_min=pool_min,
            pool_max=pool_max,
            connect_timeout=connect_timeout,
        )
        _store_key = key
    return _store


def resolve_credential_secret_material(
    *,
    credential_key: str,
    telegram_token: str,
) -> str:
    """Return the credential-store key material with backwards-compatible fallback."""
    global _fallback_warning_emitted
    explicit_key = credential_key.strip()
    if explicit_key:
        return explicit_key

    fallback = telegram_token.strip()
    if not fallback:
        raise RuntimeError(
            "BOT_CREDENTIAL_KEY or TELEGRAM_BOT_TOKEN is required before using the credential store"
        )

    if not _fallback_warning_emitted:
        log.error(
            "Credential encryption is using TELEGRAM_BOT_TOKEN as the key material. "
            "Set BOT_CREDENTIAL_KEY in the bot env file before rotating the Telegram bot token."
        )
        _fallback_warning_emitted = True
    return fallback


def init_credential_store_for_config(config) -> AbstractCredentialStore:
    return init_credential_store(
        data_dir=config.data_dir,
        secret_material=resolve_credential_secret_material(
            credential_key=getattr(config, "credential_key", ""),
            telegram_token=config.telegram_token,
        ),
        database_url=config.database_url,
        pool_min=config.db_pool_min_size,
        pool_max=config.db_pool_max_size,
        connect_timeout=config.db_connect_timeout_seconds,
    )


def get_credential_store() -> AbstractCredentialStore:
    if _store is not None:
        return _store
    data_dir = Path(os.environ.get("BOT_DATA_DIR", "/tmp/telegram-agent-credentials")).expanduser()
    secret_material = resolve_credential_secret_material(
        credential_key=os.environ.get("BOT_CREDENTIAL_KEY", ""),
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    )
    database_url = os.environ.get("BOT_DATABASE_URL", "").strip()
    pool_min = int(os.environ.get("BOT_DB_POOL_MIN_SIZE", "1") or "1")
    pool_max = int(os.environ.get("BOT_DB_POOL_MAX_SIZE", "10") or "10")
    connect_timeout = int(os.environ.get("BOT_DB_CONNECT_TIMEOUT_SECONDS", "10") or "10")
    return init_credential_store(
        data_dir=data_dir,
        secret_material=secret_material,
        database_url=database_url,
        pool_min=pool_min,
        pool_max=pool_max,
        connect_timeout=connect_timeout,
    )


def reset_for_test() -> None:
    global _store, _store_key, _fallback_warning_emitted
    _store = None
    _store_key = None
    _fallback_warning_emitted = False
