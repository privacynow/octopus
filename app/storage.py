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
    (data_dir / "credentials").mkdir(parents=True, exist_ok=True)


def session_file(data_dir: Path, chat_id: int) -> Path:
    return data_dir / "sessions" / f"{chat_id}.json"


def default_session(
    provider_name: str,
    provider_state: dict[str, Any],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "provider": provider_name,
        "provider_state": provider_state,
        "approval_mode": approval_mode,
        "active_skills": list(default_skills),
        "role": role,
        "pending_request": None,
        "awaiting_skill_setup": None,
        "created_at": now,
        "updated_at": now,
    }


def load_session(
    data_dir: Path,
    chat_id: int,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    path = session_file(data_dir, chat_id)
    session = default_session(provider_name, provider_state_factory(), approval_mode, role, default_skills)
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            # Restore chat-level settings (skills, role, pending_request, timestamps)
            for key in ("active_skills", "role", "pending_request", "awaiting_skill_setup", "compact_mode", "created_at", "updated_at"):
                if key in saved:
                    session[key] = saved[key]
            # Only restore approval_mode if the user explicitly set it
            # via /approval (indicated by approval_mode_explicit flag).
            # Otherwise, always use the instance config default so that
            # BOT_APPROVAL_MODE changes propagate to existing chats.
            if saved.get("approval_mode_explicit"):
                session["approval_mode"] = saved["approval_mode"]
                session["approval_mode_explicit"] = True
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


def list_sessions(data_dir: Path) -> list[dict[str, Any]]:
    """Return summary info for all stored sessions.

    Each dict has: chat_id, provider, active_skills, has_pending,
    has_setup, updated_at, created_at.
    """
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for sf in sessions_dir.glob("*.json"):
        try:
            data = json.loads(sf.read_text())
            chat_id = int(sf.stem)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        results.append({
            "chat_id": chat_id,
            "provider": data.get("provider", "unknown"),
            "active_skills": data.get("active_skills", []),
            "has_pending": data.get("pending_request") is not None,
            "has_setup": data.get("awaiting_skill_setup") is not None,
            "approval_mode": data.get("approval_mode", "off"),
            "updated_at": data.get("updated_at", ""),
            "created_at": data.get("created_at", ""),
        })
    results.sort(key=lambda s: s["updated_at"], reverse=True)
    return results


def sweep_skill_from_sessions(data_dir: Path, skill_name: str) -> int:
    """Remove a skill from active_skills in all session files.

    Returns the number of sessions modified.
    """
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.is_dir():
        return 0
    modified = 0
    for session_path in sessions_dir.glob("*.json"):
        try:
            session = json.loads(session_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        active = session.get("active_skills", [])
        if skill_name in active:
            active.remove(skill_name)
            session["active_skills"] = active
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp = session_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(session, indent=2, sort_keys=True))
            tmp.rename(session_path)
            modified += 1
    return modified
