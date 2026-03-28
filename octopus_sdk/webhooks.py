"""SDK webhook contracts."""

from __future__ import annotations

from typing import Protocol


class CompletionWebhookPort(Protocol):
    async def __call__(
        self,
        url: str,
        *,
        chat_id: int,
        conversation_ref: str,
        status: str,
        summary: str,
        completed_at: str,
    ) -> None: ...
