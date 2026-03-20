"""Typed control-plane command and reply envelopes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


CommandState = Literal["pending", "claimed", "completed", "failed", "dead_letter"]
ReplyStatus = Literal["completed", "failed"]


class ControlCommand(BaseModel):
    command_id: str = Field(..., min_length=1)
    capability: str = Field(..., min_length=1)
    operation: str = Field(..., min_length=1)
    payload_json: str = Field(..., min_length=2)
    claimed_at: str = ""
    priority: int = 0
    correlation_id: str = ""
    authority_ref: str = Field(..., min_length=1)
    idempotency_key: str = ""
    max_retries: int = Field(default=3, ge=0)


class ControlReply(BaseModel):
    command_id: str = Field(..., min_length=1)
    status: ReplyStatus
    result_json: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _validate_terminal_payload(self) -> "ControlReply":
        if self.status == "completed" and self.error:
            raise ValueError("completed replies must not carry an error")
        if self.status == "failed":
            if not self.error:
                raise ValueError("failed replies must carry an error")
            if self.result_json is not None:
                raise ValueError("failed replies must not carry a result payload")
        return self
