from __future__ import annotations

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from octopus_sdk.identity import parse_actor_key
from octopus_sdk.registry.management import SkillFileRecord, SkillRequirementRecord
from octopus_sdk.registry.models import RegistryJsonRecord

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


class AgentExecutionResetRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor resetting the agent execution fault")


class ProviderGuidancePreviewRequest(BaseModel):
    role: str = Field(default="", description="Role/persona text to include")
    active_skills: list[str] = Field(default_factory=list, description="Active runtime skill slugs")
    compact_mode: bool = Field(default=False, description="Whether compact-mode instructions should be appended")
    use_draft: bool = Field(default=False, description="Whether to preview the current draft instead of the published policy")
    body_override: str = Field(default="", description="Optional transient guidance text to preview without saving")


class LifecycleActionRequest(BaseModel):
    actor_key: str = Field(default="", description="Actor performing the lifecycle action")
    note: str = Field(default="", description="Optional lifecycle note")


class RuntimeSkillDraftUpdateRequest(LifecycleActionRequest):
    body: str | None = Field(default=None, description="Draft instruction body override")
    display_name: str | None = Field(default=None, description="Optional display name override")
    description: str | None = Field(default=None, description="Optional skill description override")
    skill_kind: str | None = Field(default=None, description="Optional skill kind override")
    requirements: list[SkillRequirementRecord] | None = Field(default=None, description="Optional requirement list override")
    provider_config: RegistryJsonRecord | None = Field(default=None, description="Optional provider config override")
    files: list[SkillFileRecord] | None = Field(default=None, description="Optional draft file list override")
    changelog: str = Field(default="", description="Optional changelog entry")


class RuntimeSkillPackageImportRequest(LifecycleActionRequest):
    target_skill_name: str = Field(default="", description="Optional existing custom draft to replace")
    file_name: str = Field(default="", description="Original uploaded file name")
    package_base64: str = Field(..., min_length=1, description="Base64-encoded skill package archive")


class ProviderGuidanceDraftUpdateRequest(LifecycleActionRequest):
    body: str = Field(..., min_length=1, description="Draft provider-guidance body")
    scope_kind: str = Field(default="system", description="Guidance scope kind")
    scope_key: str = Field(default="", description="Guidance scope key")


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
