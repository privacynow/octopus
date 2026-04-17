"""Canonical protocol bootstrap helpers shared by DB init paths."""

from __future__ import annotations

import uuid
from typing import Protocol

from psycopg.types.json import Jsonb

from .core import (
    PROTOCOL_DEFAULT_RUN_ORG_ID,
    builtin_protocol_documents,
    default_protocol_document_slug,
    protocol_definition_content_hash,
)
from octopus_sdk.registry.models import utcnow_iso

_SCHEMA = "agent_registry"


class _BootstrapCursor(Protocol):
    def __enter__(self) -> "_BootstrapCursor": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> object: ...
    def execute(self, query: str, params: tuple[object, ...]) -> object: ...
    def fetchone(self) -> object: ...


class SupportsBootstrapCursor(Protocol):
    def cursor(self) -> _BootstrapCursor: ...


def ensure_builtin_protocols(conn: SupportsBootstrapCursor) -> None:
    """Seed builtin published protocols into the registry if missing."""
    now = utcnow_iso()
    with conn.cursor() as cur:
        for document in builtin_protocol_documents():
            slug = default_protocol_document_slug(document)
            cur.execute(
                f"SELECT protocol_id FROM {_SCHEMA}.protocol_definitions WHERE slug = %s",
                (slug,),
            )
            if cur.fetchone() is not None:
                continue
            protocol_id = uuid.uuid4().hex
            version_id = uuid.uuid4().hex
            payload = document.model_dump(mode="json")
            content_hash = protocol_definition_content_hash(document)
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_definitions (
                    protocol_id, slug, display_name, description, lifecycle_state,
                    current_version_id, owner_org_id, visibility, created_by, updated_by,
                    draft_definition_json, draft_content_hash, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, 'published', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    protocol_id,
                    slug,
                    document.display_name or slug,
                    document.description,
                    version_id,
                    PROTOCOL_DEFAULT_RUN_ORG_ID,
                    "registry_template",
                    "bootstrap",
                    "bootstrap",
                    Jsonb(payload),
                    content_hash,
                    now,
                    now,
                ),
            )
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_definition_versions (
                    protocol_definition_version_id, protocol_id, version, definition_json,
                    content_hash, validation_status, published_at, published_by, created_at
                ) VALUES (%s, %s, 1, %s, %s, 'valid', %s, %s, %s)
                """,
                (
                    version_id,
                    protocol_id,
                    Jsonb(payload),
                    content_hash,
                    now,
                    "bootstrap",
                    now,
                ),
            )
