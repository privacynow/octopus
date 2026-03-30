from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from octopus_sdk.identity import parse_actor_key

from .auth import AuthContext


class ConversationSkillMutationRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor performing the skill mutation")
    confirm: bool = Field(default=False, description="Confirm activation when the prompt budget warning has already been acknowledged")


class ConversationSkillCredentialRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor submitting the skill credential value")
    value: str = Field(..., min_length=1, description="Credential value to submit for the current setup step")


class ConversationSettingUpdateRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor updating the conversation setting")
    setting: str = Field(..., min_length=1, description="Conversation setting name")
    value: str = Field(default="", description="Requested setting value")


class ConversationResetRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor resetting the conversation")


class ProviderGuidancePreviewRequest(BaseModel):
    role: str = Field(default="", description="Role/persona text to include")
    active_skills: list[str] = Field(default_factory=list, description="Active runtime skill slugs")
    compact_mode: bool = Field(default=False, description="Whether compact-mode instructions should be appended")


class LifecycleActionRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor performing the lifecycle action")
    note: str = Field(default="", description="Optional lifecycle note")


class RuntimeSkillDraftUpdateRequest(LifecycleActionRequest):
    body: str = Field(..., min_length=1, description="Draft instruction body")
    description: str = Field(default="", description="Optional skill description override")
    changelog: str = Field(default="", description="Optional changelog entry")


class ProviderGuidanceDraftUpdateRequest(LifecycleActionRequest):
    body: str = Field(..., min_length=1, description="Draft provider-guidance body")
    scope_kind: str = Field(default="system", description="Guidance scope kind")
    scope_key: str = Field(default="", description="Guidance scope key")


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def provider_reports_cost(metadata: dict[str, Any] | None) -> bool:
    provider = str((metadata or {}).get("provider") or "").strip().lower()
    if provider == "codex":
        return False
    if provider:
        return True
    return float_value((metadata or {}).get("cost_usd")) > 0.0


def aggregate_usage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    daily_total = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_prompt_tokens": 0,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": False,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.0,
        "cost_available": False,
    }
    by_conversation: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = row.get("metadata") or {}
        prompt_tokens = int_value(metadata.get("prompt_tokens"))
        completion_tokens = int_value(metadata.get("completion_tokens"))
        cached_prompt_tokens = int_value(metadata.get("cached_prompt_tokens"))
        cached_completion_tokens = int_value(metadata.get("cached_completion_tokens"))
        cached_prompt_available = "cached_prompt_tokens" in metadata
        cached_completion_available = "cached_completion_tokens" in metadata
        cost_usd = float_value(metadata.get("cost_usd"))
        cost_available = provider_reports_cost(metadata)
        daily_total["prompt_tokens"] += prompt_tokens
        daily_total["completion_tokens"] += completion_tokens
        if cached_prompt_available:
            daily_total["cached_prompt_tokens"] += cached_prompt_tokens
            daily_total["cached_prompt_tokens_available"] = True
        if cached_completion_available:
            daily_total["cached_completion_tokens"] += cached_completion_tokens
            daily_total["cached_completion_tokens_available"] = True
        if cost_available:
            daily_total["cost_usd"] += cost_usd
            daily_total["cost_available"] = True
        item = by_conversation.setdefault(
            row["conversation_id"],
            {
                "conversation_id": row["conversation_id"],
                "title": row.get("title", ""),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cached_prompt_tokens": 0,
                "cached_completion_tokens": 0,
                "cached_prompt_tokens_available": False,
                "cached_completion_tokens_available": False,
                "cost_usd": 0.0,
                "cost_available": False,
            },
        )
        item["prompt_tokens"] += prompt_tokens
        item["completion_tokens"] += completion_tokens
        if cached_prompt_available:
            item["cached_prompt_tokens"] += cached_prompt_tokens
            item["cached_prompt_tokens_available"] = True
        if cached_completion_available:
            item["cached_completion_tokens"] += cached_completion_tokens
            item["cached_completion_tokens_available"] = True
        if cost_available:
            item["cost_usd"] += cost_usd
            item["cost_available"] = True
    return {
        "daily_total": daily_total,
        "by_conversation": sorted(
            by_conversation.values(),
            key=lambda item: (
                -(item["prompt_tokens"] + item["completion_tokens"]),
                item["conversation_id"],
            ),
        ),
    }


def operator_actor_key(raw: str = "") -> str:
    token = parse_actor_key(raw)
    return token or "reg:registry-ui"


def secure_html_response(content: str, *, headers: dict[str, str], status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        content,
        status_code=status_code,
        headers=dict(headers),
    )


def require_own_resource(auth: AuthContext, owner_agent_id: str) -> None:
    if auth.is_agent and auth.agent_id != owner_agent_id:
        raise HTTPException(status_code=403, detail="Not authorized for this agent resource.")


def scoped_agent_id(auth: AuthContext) -> str | None:
    return auth.agent_id if auth.is_agent else None


def paginated_response(key: str, items: list[Any], cursor: int, limit: int) -> dict[str, Any]:
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    return {
        key: items,
        "next_cursor": cursor + limit if has_more else None,
        "has_more": has_more,
    }


def json_payload(value: Any) -> Any:
    return jsonable_encoder(value)
