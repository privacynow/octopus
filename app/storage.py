"""Session CRUD: backend-neutral facade. Delegates to runtime_backend.session_store()."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Callable

from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.identity import filesystem_component_for_key
from octopus_sdk.workflows.delegation import DelegationUpdateOutcome

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

from octopus_sdk.sessions import default_session  # re-export for callers


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


def chat_upload_dir(data_dir: Path, conversation_key: str) -> Path:
    d = data_dir / "uploads" / filesystem_component_for_key(conversation_key)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_upload_path(data_dir: Path, conversation_key: str, original_name: str) -> Path:
    return (
        chat_upload_dir(data_dir, conversation_key)
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

def session_exists(data_dir: Path, conversation_key: str) -> bool:
    from app import runtime_backend
    return runtime_backend.session_store().session_exists(data_dir, conversation_key)


def load_session(
    data_dir: Path,
    conversation_key: str,
    provider_name: str,
    provider_state_factory: Callable[[str], dict[str, Any]],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    from app import runtime_backend
    return runtime_backend.session_store().load_session(
        data_dir, conversation_key, provider_name, provider_state_factory,
        approval_mode, role, default_skills,
    )


def save_session(data_dir: Path, conversation_key: str, session: dict[str, Any]) -> None:
    from app import runtime_backend
    runtime_backend.session_store().save_session(data_dir, conversation_key, session)


def apply_delegation_result_atomically(
    data_dir: Path,
    conversation_key: str,
    *,
    routed_task_id: str,
    authority_ref: str,
    result: RoutedTaskResult,
) -> DelegationUpdateOutcome:
    from app import runtime_backend
    return runtime_backend.session_store().apply_delegation_result_atomically(
        data_dir,
        conversation_key,
        routed_task_id=routed_task_id,
        authority_ref=authority_ref,
        result=result,
    )


def delete_session(data_dir: Path, conversation_key: str) -> None:
    from app import runtime_backend
    runtime_backend.session_store().delete_session(data_dir, conversation_key)


def list_sessions(data_dir: Path) -> list[dict[str, Any]]:
    from app import runtime_backend
    return runtime_backend.session_store().list_sessions(data_dir)


def close_db(data_dir: Path) -> None:
    from app import runtime_backend
    runtime_backend.session_store().close_db(data_dir)


def close_all_db() -> None:
    from app import runtime_backend
    runtime_backend.session_store().close_all_db()


def debug_session_connection(data_dir: Path):
    """Return a backend-specific session-store inspection handle. Tests only."""
    from app import runtime_backend
    return runtime_backend.session_store().debug_connection(data_dir)


def reset_db_for_test(data_dir: Path) -> None:
    """Tests only: close and reset the session store for this data dir."""
    from app import runtime_backend
    runtime_backend.session_store().reset_db_for_test(data_dir)
