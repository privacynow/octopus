"""Session CRUD, upload paths, directory management."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def ensure_data_dirs(data_dir: Path) -> None:
    (data_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)


def session_file(data_dir: Path, chat_id: int) -> Path:
    return data_dir / "sessions" / f"{chat_id}.json"


def default_session(
    provider_name: str,
    provider_state: dict[str, Any],
    approval_mode: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "provider": provider_name,
        "provider_state": provider_state,
        "approval_mode": approval_mode,
        "pending_request": None,
        "created_at": now,
        "updated_at": now,
    }


def load_session(
    data_dir: Path,
    chat_id: int,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    approval_mode: str,
) -> dict[str, Any]:
    path = session_file(data_dir, chat_id)
    session = default_session(provider_name, provider_state_factory(), approval_mode)
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            # Restore chat-level settings (approval_mode, pending_request, timestamps)
            for key in ("approval_mode", "pending_request", "created_at", "updated_at"):
                if key in saved:
                    session[key] = saved[key]
            # Only restore provider_state if the saved provider matches;
            # a provider switch means the old state is meaningless.
            if saved.get("provider") == provider_name:
                fresh_state = provider_state_factory()
                fresh_state.update(saved.get("provider_state", {}))
                session["provider_state"] = fresh_state
        except (json.JSONDecodeError, KeyError):
            pass
    return session


def save_session(data_dir: Path, chat_id: int, session: dict[str, Any]) -> None:
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    target = session_file(data_dir, chat_id)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, indent=2, sort_keys=True))
    tmp.rename(target)  # atomic on POSIX


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or "attachment"


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def chat_upload_dir(data_dir: Path, chat_id: int) -> Path:
    d = data_dir / "uploads" / str(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_upload_path(data_dir: Path, chat_id: int, original_name: str) -> Path:
    return (
        chat_upload_dir(data_dir, chat_id)
        / f"{uuid.uuid4().hex}_{sanitize_filename(original_name)}"
    )


def resolve_allowed_path(raw_path: str, allowed_roots: list[Path]) -> Path | None:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        if allowed_roots:
            candidate = allowed_roots[0] / candidate
        else:
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    return None
