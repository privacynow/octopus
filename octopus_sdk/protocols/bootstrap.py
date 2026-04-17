"""Canonical protocol bootstrap helpers shared by DB init paths."""

from __future__ import annotations

from typing import Protocol
from .core import builtin_protocol_documents, default_protocol_document_slug

_SCHEMA = "agent_registry"


class _BootstrapCursor(Protocol):
    def __enter__(self) -> "_BootstrapCursor": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> object: ...
    def execute(self, query: str, params: tuple[object, ...]) -> object: ...
    def fetchone(self) -> object: ...


class SupportsBootstrapCursor(Protocol):
    def cursor(self) -> _BootstrapCursor: ...


def ensure_builtin_protocols(conn: SupportsBootstrapCursor) -> None:
    """Ensure builtin examples are not re-seeded into authored protocol rows."""

    with conn.cursor() as cur:
        for document in builtin_protocol_documents():
            slug = default_protocol_document_slug(document)
            cur.execute(
                f"SELECT protocol_id FROM {_SCHEMA}.protocol_definitions WHERE slug = %s",
                (slug,),
            )
            # Builtin protocol examples now live in the Gallery/template manifest,
            # not in authored protocol rows. Existing rows are left intact so
            # historical runs can still reference them safely.
            cur.fetchone()
