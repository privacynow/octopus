"""App wiring for the SDK-owned provider guidance service."""

from __future__ import annotations

from app.content_seed import default_provider_guidance_tracks
from app.content_store import get_content_store
from app.storage import list_sessions, load_session
from app.skill_catalog_service import get_skill_catalog_service
from octopus_sdk.provider_guidance_service import (
    PROMPT_SIZE_WARNING_THRESHOLD,
    ProviderGuidanceService as SdkProviderGuidanceService,
)
from octopus_sdk.content_models import ProviderGuidanceTrackRecord


class ProviderGuidanceService(SdkProviderGuidanceService):
    """Runtime singleton wrapper that binds SDK guidance logic to app services."""

    def __init__(self) -> None:
        super().__init__(
            catalog_factory=get_skill_catalog_service,
            content_store_factory=get_content_store,
            list_sessions=list_sessions,
            load_session=load_session,
        )

    def default_seed_tracks(self) -> list[ProviderGuidanceTrackRecord]:
        return default_provider_guidance_tracks()


_SERVICE = ProviderGuidanceService()


def get_provider_guidance_service() -> ProviderGuidanceService:
    return _SERVICE
