"""Third-party skill registry — index fetch, artifact download, verification.

Registry index format (JSON at a URL):

    {
      "version": 1,
      "skills": {
        "skill-name": {
          "display_name": "Skill Name",
          "description": "What it does",
          "version": "1.0.0",
          "publisher": "publisher-name",
          "digest": "sha256hex...",
          "artifact_url": "https://example.com/skills/skill-name.tar.gz"
        }
      }
    }

Artifacts are .tar.gz files containing skill directory contents (skill.md, etc.)
at the top level.
"""

import json
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

_INDEX_TIMEOUT = 15  # seconds
_ARTIFACT_TIMEOUT = 60  # seconds
_MAX_INDEX_SIZE = 2 * 1024 * 1024  # 2 MB
_MAX_ARTIFACT_SIZE = 10 * 1024 * 1024  # 10 MB

_HEADERS = {"User-Agent": "telegram-agent-bot/1.0"}


@dataclass(frozen=True)
class RegistrySkill:
    """A skill entry from the registry index."""
    name: str
    display_name: str
    description: str
    version: str
    publisher: str
    digest: str
    artifact_url: str


def fetch_index(registry_url: str) -> dict[str, RegistrySkill]:
    """Fetch and parse the registry index. Returns {name: RegistrySkill}.

    Raises ValueError on parse errors, httpx.HTTPError on network errors.
    """
    with httpx.Client(headers=_HEADERS, timeout=_INDEX_TIMEOUT) as client:
        resp = client.get(registry_url)
        resp.raise_for_status()
        raw = resp.content
        if len(raw) > _MAX_INDEX_SIZE:
            raise ValueError(f"Registry index exceeds {_MAX_INDEX_SIZE} bytes")

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Registry index must be a JSON object")

    index_version = data.get("version", 0)
    if index_version != 1:
        raise ValueError(f"Unsupported registry index version: {index_version}")

    skills_data = data.get("skills", {})
    if not isinstance(skills_data, dict):
        raise ValueError("Registry 'skills' must be a JSON object")

    result: dict[str, RegistrySkill] = {}
    for name, entry in skills_data.items():
        if not isinstance(entry, dict):
            continue
        digest = entry.get("digest", "")
        artifact_url = entry.get("artifact_url", "")
        if not digest or not artifact_url:
            _log.warning("Registry skill '%s' missing digest or artifact_url, skipping", name)
            continue
        result[name] = RegistrySkill(
            name=name,
            display_name=entry.get("display_name", name),
            description=entry.get("description", ""),
            version=entry.get("version", ""),
            publisher=entry.get("publisher", ""),
            digest=digest,
            artifact_url=artifact_url,
        )
    return result


def search_index(index: dict[str, RegistrySkill], query: str) -> list[RegistrySkill]:
    """Substring search on name and description (case-insensitive)."""
    q = query.lower()
    return [
        skill for skill in index.values()
        if q in skill.name.lower() or q in skill.description.lower()
    ]


def download_artifact(artifact_url: str, dest_dir: Path) -> Path:
    """Download a .tar.gz artifact and extract to dest_dir.

    Returns the path to the extracted skill directory.
    Raises ValueError on size/format errors, httpx.HTTPError on network errors.
    """
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with httpx.Client(headers=_HEADERS, timeout=_ARTIFACT_TIMEOUT) as client:
                with client.stream("GET", artifact_url) as resp:
                    resp.raise_for_status()
                    total = 0
                    for chunk in resp.iter_bytes(8192):
                        total += len(chunk)
                        if total > _MAX_ARTIFACT_SIZE:
                            raise ValueError(f"Artifact exceeds {_MAX_ARTIFACT_SIZE} bytes")
                        tmp.write(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp_path, "r:gz") as tf:
            # Security: check for path traversal
            for member in tf.getmembers():
                resolved = (dest_dir / member.name).resolve()
                if not str(resolved).startswith(str(dest_dir.resolve())):
                    raise ValueError(f"Artifact contains path traversal: {member.name}")
            tf.extractall(dest_dir, filter="data")
    finally:
        tmp_path.unlink(missing_ok=True)

    # If tarball extracted a single subdirectory, move its contents up
    entries = list(dest_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        sub = entries[0]
        for item in sub.iterdir():
            shutil.move(str(item), str(dest_dir / item.name))
        sub.rmdir()

    # Verify skill.md exists
    if not (dest_dir / "skill.md").exists():
        raise ValueError("Artifact does not contain skill.md")

    return dest_dir
