"""Realtime registry websocket and progress contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel


CollectionTopic = Literal[
    "summary",
    "agents",
    "conversations",
    "tasks",
    "approvals",
    "usage",
]


class ConversationProgressUpdate(BaseModel):
    """Ephemeral operator-visible progress for one conversation."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)
    created_at: str = Field(..., min_length=1)


class RealtimeJsonPayload(RootModel[dict[str, JsonValue]], Mapping[str, JsonValue]):
    root: dict[str, JsonValue] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> JsonValue:
        return self.root[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.root.get(key, default)


class RealtimeEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["event"]
    data: RealtimeJsonPayload


class RealtimeHeartbeatEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["heartbeat"]
    data: RealtimeJsonPayload


class RealtimeProgressEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["progress"]
    data: ConversationProgressUpdate


class RealtimeInvalidationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    conversation_id: str = ""
    agent_id: str = ""
    routed_task_id: str = ""


class RealtimeInvalidationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["invalidate"]
    data: RealtimeInvalidationPayload
