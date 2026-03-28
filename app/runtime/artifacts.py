"""Artifact-store wiring for runtime execution services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import BotConfig
from app.storage import chat_upload_dir
from app.summarize import save_raw


@dataclass(frozen=True)
class RuntimeArtifactStore:
    config: BotConfig

    def upload_dir(self, conversation_key: str) -> Path:
        return chat_upload_dir(self.config.data_dir, conversation_key)

    def save_raw(
        self,
        conversation_key: str,
        prompt: str,
        raw_text: str,
        *,
        kind: str = "request",
    ) -> int:
        return save_raw(self.config.data_dir, conversation_key, prompt, raw_text, kind=kind)
