"""Shared resource records for user-provided files and channel attachments."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel


ResourceLifecycleState = Literal["active", "archived", "deleted"]


class ResourceRecord(RegistryRecordModel):
    resource_id: str = ""
    owner_actor_ref: str = ""
    source_surface: str = ""
    source_ref: str = ""
    original_name: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    content_hash: str = ""
    storage_uri: str = ""
    lifecycle_state: ResourceLifecycleState = "active"
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = ""
    updated_at: str = ""
    deleted_at: str = ""
    deleted_by: str = ""


class ResourceAttachmentRecord(RegistryRecordModel):
    attachment_id: str = ""
    resource_id: str = ""
    target_kind: str = ""
    target_ref: str = ""
    relation: str = "context"
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_by: str = ""
    created_at: str = ""
    detached_at: str = ""
    detached_by: str = ""


class ResourceUploadRequestRecord(RegistryRecordModel):
    owner_actor_ref: str = ""
    source_surface: str = "registry"
    source_ref: str = ""
    original_name: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    content_hash: str = ""
    storage_uri: str = ""
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ResourceAttachRequestRecord(RegistryRecordModel):
    resource_id: str = ""
    target_kind: str = ""
    target_ref: str = ""
    relation: str = "context"
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_by: str = ""


__all__ = [
    "ResourceAttachRequestRecord",
    "ResourceAttachmentRecord",
    "ResourceLifecycleState",
    "ResourceRecord",
    "ResourceUploadRequestRecord",
]
