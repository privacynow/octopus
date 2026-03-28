"""App wiring for SDK-owned workflow composition."""

from __future__ import annotations

from functools import lru_cache

from app import runtime_backend
from app import user_messages as _msg
from app.config import BotConfig, load_config
from app.content_store import get_content_store
from app.credential_service import get_credential_service
from app.credential_validation import validate_credential
import app.formatting as formatting
import app.webhook as webhook
from app.provider_guidance_service import (
    PROMPT_SIZE_WARNING_THRESHOLD,
    get_provider_guidance_service,
)
from app.runtime.deferred_notifications import LocalDeferredNotifications
from app.runtime.session_runtime import LocalSessionRuntime
from app.skill_activation_service import get_skill_activation_service
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.runtime.work_admission import trust_tier_for_ref
from octopus_sdk.bot_runtime import SessionRuntimePort, WorkflowComposition
from octopus_sdk.composition import WorkflowComposer


async def _send_completion_webhook(
    url: str,
    *,
    chat_id: int,
    conversation_ref: str,
    status: str,
    summary: str,
    completed_at: str,
) -> None:
    await webhook.fire_completion_webhook(
        url,
        chat_id=chat_id,
        conversation_ref=conversation_ref,
        status=status,
        summary=summary,
        completed_at=completed_at,
    )


def compose_workflows(
    *,
    config: BotConfig,
    sessions: SessionRuntimePort,
) -> WorkflowComposition:
    return (
        WorkflowComposer()
        .with_messages(_msg)
        .with_config(config)
        .with_sessions(sessions)
        .with_catalog_service(get_skill_catalog_service())
        .with_import_service(get_skill_import_service())
        .with_skill_activation(get_skill_activation_service())
        .with_credentials(get_credential_service())
        .with_provider_guidance(get_provider_guidance_service())
        .with_content_store(get_content_store())
        .with_credential_validator(validate_credential)
        .with_work_queue(runtime_backend.transport_store())
        .with_trust_tier_resolver(trust_tier_for_ref)
        .with_text_formatting(formatting)
        .with_completion_webhook(_send_completion_webhook)
        .with_deferred_notifications(LocalDeferredNotifications())
        .with_prompt_size_warning_threshold(PROMPT_SIZE_WARNING_THRESHOLD)
        .build()
    )


@lru_cache(maxsize=1)
def workflows() -> WorkflowComposition:
    config = load_config()
    holder: dict[str, WorkflowComposition] = {}
    sessions = LocalSessionRuntime(
        config,
        catalog=lambda: holder["workflows"].runtime_skills.catalog,
    )
    holder["workflows"] = compose_workflows(config=config, sessions=sessions)
    return holder["workflows"]


def reset_for_test() -> None:
    workflows.cache_clear()
