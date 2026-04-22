from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class StoreDialect(Protocol):
    def placeholder(self, index: int) -> str: ...

    def qualify(self, table: str) -> str: ...

    def json_text(self, json_expr: str, key: str) -> str: ...

    def json_path_text(self, json_expr: str, *path: str) -> str: ...

    def usage_token_predicate(self, metadata_expr: str) -> str: ...

    def execute(
        self,
        conn: Any,
        sql: str,
        params: Sequence[object] = (),
    ) -> int | None: ...

    def fetchone(
        self,
        conn: Any,
        sql: str,
        params: Sequence[object] = (),
    ) -> Mapping[str, Any] | None: ...

    def fetchall(
        self,
        conn: Any,
        sql: str,
        params: Sequence[object] = (),
    ) -> list[Mapping[str, Any]]: ...
