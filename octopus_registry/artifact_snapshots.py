"""Durable filesystem-backed snapshots for protocol artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
from typing import Mapping
import uuid

from octopus_sdk.protocols import ProtocolArtifactSnapshotRecord, RegistryJsonRecord, utcnow_iso


SNAPSHOT_SCHEME = "registry-artifact://snapshots/"


def _safe_snapshot_root(root: str | Path) -> Path:
    path = Path(str(root or "")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _hash_directory(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or not child.is_file():
            continue
        resolved = child.resolve()
        resolved.relative_to(path.resolve())
        relative = resolved.relative_to(path.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}", size


def inspect_artifact_snapshot_source(path: Path) -> tuple[str, int, str]:
    resolved = Path(path).expanduser().resolve()
    if resolved.is_dir():
        content_hash, size = _hash_directory(resolved)
        return "directory", size, content_hash
    if resolved.is_file():
        content_hash, size = _hash_file(resolved)
        return "file", size, content_hash
    raise FileNotFoundError(str(resolved))


def artifact_snapshot_storage_path(root: str | Path, snapshot: ProtocolArtifactSnapshotRecord) -> Path | None:
    uri = str(snapshot.storage_uri or "").strip()
    if not uri.startswith(SNAPSHOT_SCHEME):
        return None
    snapshot_id = uri[len(SNAPSHOT_SCHEME):].strip().strip("/")
    if not snapshot_id:
        return None
    base = (_safe_snapshot_root(root) / snapshot_id).resolve()
    try:
        base.relative_to(_safe_snapshot_root(root))
    except ValueError:
        return None
    manifest = snapshot.manifest_json.as_dict()
    relative = str(manifest.get("content_path") or "content").strip().strip("/") or "content"
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def create_artifact_snapshot(
    *,
    artifact_store_dir: str | Path,
    source_path: Path,
    protocol_artifact_id: str,
    protocol_run_id: str,
    artifact_key: str,
    created_by: str = "",
    retention_until: str = "",
) -> ProtocolArtifactSnapshotRecord:
    source = Path(source_path).expanduser().resolve()
    snapshot_kind, size_bytes, content_hash = inspect_artifact_snapshot_source(source)
    snapshot_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"octopus-artifact-snapshot:{protocol_run_id}:{artifact_key}:{content_hash}",
    ).hex
    root = _safe_snapshot_root(artifact_store_dir)
    snapshot_root = (root / snapshot_id).resolve()
    snapshot_root.mkdir(parents=True, exist_ok=True)
    content_root = snapshot_root / "content"
    if source.is_dir():
        if content_root.exists():
            shutil.rmtree(content_root)
        shutil.copytree(source, content_root, symlinks=False)
        content_path = "content"
        source_name = source.name
    else:
        content_root.mkdir(parents=True, exist_ok=True)
        target = content_root / source.name
        shutil.copy2(source, target)
        content_path = f"content/{source.name}"
        source_name = source.name
    manifest: Mapping[str, object] = {
        "source_name": source_name,
        "source_path": str(source),
        "content_path": content_path,
    }
    return ProtocolArtifactSnapshotRecord(
        artifact_snapshot_id=snapshot_id,
        protocol_artifact_id=protocol_artifact_id,
        protocol_run_id=protocol_run_id,
        artifact_key=artifact_key,
        snapshot_kind=snapshot_kind,
        storage_uri=f"{SNAPSHOT_SCHEME}{snapshot_id}",
        content_hash=content_hash,
        size_bytes=size_bytes,
        manifest_json=RegistryJsonRecord(dict(manifest)),
        retention_state="active",
        retention_until=retention_until,
        created_at=utcnow_iso(),
        created_by=created_by,
    )

