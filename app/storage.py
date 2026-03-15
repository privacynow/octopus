"""Session CRUD: backend-neutral facade. Delegates to runtime_backend.session_store()."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Callable

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

from app.session_defaults import default_session  # re-export for callers


# ---------------------------------------------------------------------------
# Pure directory / path helpers (no backend)
# ---------------------------------------------------------------------------

def ensure_data_dirs(data_dir: Path, *, database_url: str = "") -> None:
    """Create data_dir and subdirs. When database_url is set, skip SQLite init (backend uses Postgres)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (data_dir / "credentials").mkdir(parents=True, exist_ok=True)
    if database_url:
        return
    # First use of session/transport store will create SQLite DBs on demand


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


# ---------------------------------------------------------------------------
# Session CRUD (delegate to selected backend)
# ---------------------------------------------------------------------------

def session_exists(data_dir: Path, chat_id: int) -> bool:
    from app import runtime_backend
    return runtime_backend.session_store().session_exists(data_dir, chat_id)


def load_session(
    data_dir: Path,
    chat_id: int,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    from app import runtime_backend
    return runtime_backend.session_store().load_session(
        data_dir, chat_id, provider_name, provider_state_factory,
        approval_mode, role, default_skills,
    )


def save_session(data_dir: Path, chat_id: int, session: dict[str, Any]) -> None:
    from app import runtime_backend
    runtime_backend.session_store().save_session(data_dir, chat_id, session)


def delete_session(data_dir: Path, chat_id: int) -> None:
    from app import runtime_backend
    runtime_backend.session_store().delete_session(data_dir, chat_id)


def list_sessions(data_dir: Path) -> list[dict[str, Any]]:
    from app import runtime_backend
    return runtime_backend.session_store().list_sessions(data_dir)


def close_db(data_dir: Path) -> None:
    from app import runtime_backend
    runtime_backend.session_store().close_db(data_dir)


def close_all_db() -> None:
    from app import runtime_backend
    runtime_backend.session_store().close_all_db()


def _reset_db(data_dir: Path) -> None:
    """Tests only: close and delete the session database."""
    from app import runtime_backend
    runtime_backend.session_store()._reset_db(data_dir)
