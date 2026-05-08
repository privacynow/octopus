"""Filesystem-backed storage for Registry input resources."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import uuid

from octopus_sdk.resources import ResourceRecord
from octopus_sdk.registry.models import RegistryJsonRecord
from octopus_sdk.time_utils import utc_now_iso


RESOURCE_SCHEME = "registry-resource://resources/"


def safe_resource_root(root: str | Path) -> Path:
    path = Path(str(root or "")).expanduser().resolve() / "resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_resource_name(name: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(name or ""))
    token = token.strip("._")
    return token or "resource"


def resource_storage_path(root: str | Path, resource: ResourceRecord | str) -> Path | None:
    uri = resource.storage_uri if isinstance(resource, ResourceRecord) else str(resource or "")
    if not uri.startswith(RESOURCE_SCHEME):
        return None
    resource_id = uri[len(RESOURCE_SCHEME):].strip().strip("/")
    if not resource_id:
        return None
    base = safe_resource_root(root)
    target = (base / resource_id / "content").resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def create_resource_from_file(
    *,
    resource_store_dir: str | Path,
    source_path: Path,
    original_name: str,
    mime_type: str = "",
    owner_actor_ref: str = "",
    source_surface: str = "registry",
    source_ref: str = "",
    metadata: dict[str, object] | None = None,
) -> ResourceRecord:
    source = Path(source_path).expanduser().resolve(strict=True)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    content_hash = f"sha256:{digest.hexdigest()}"
    resource_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"octopus-resource:{owner_actor_ref}:{source_surface}:{source_ref}:{original_name}:{content_hash}",
    ).hex
    root = safe_resource_root(resource_store_dir)
    target_dir = (root / resource_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "content"
    shutil.copy2(source, target)
    now = utc_now_iso()
    return ResourceRecord(
        resource_id=resource_id,
        owner_actor_ref=owner_actor_ref,
        source_surface=source_surface,
        source_ref=source_ref,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size,
        content_hash=content_hash,
        storage_uri=f"{RESOURCE_SCHEME}{resource_id}",
        lifecycle_state="active",
        metadata_json=RegistryJsonRecord.model_validate(metadata or {}),
        created_at=now,
        updated_at=now,
    )
