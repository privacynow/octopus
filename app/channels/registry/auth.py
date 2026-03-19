"""Registry-channel auth and session helpers."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware

log = logging.getLogger(__name__)
_SESSION_TTL_SECONDS = 24 * 60 * 60
_WARNED_MISSING_UI_TOKEN = False
_KNOWN_DEFAULT_TOKENS = {"dev-enroll-token", "dev-ui-token", "changeme"}


@dataclass(frozen=True)
class RegistrySettings:
    db_path: Path
    enroll_token: str
    ui_token: str
    display_name: str
    allow_http: bool


def registry_allows_http() -> bool:
    value = os.environ.get("REGISTRY_ALLOW_HTTP", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def load_settings() -> RegistrySettings:
    db_path = Path(os.environ.get("REGISTRY_DB_PATH", "/tmp/telegram-agent-registry/registry.sqlite3"))
    enroll_token = os.environ.get("REGISTRY_ENROLL_TOKEN", "").strip()
    ui_token = os.environ.get("REGISTRY_UI_TOKEN", "").strip()
    display_name = os.environ.get("REGISTRY_DISPLAY_NAME", "").strip()
    allow_http = registry_allows_http()
    global _WARNED_MISSING_UI_TOKEN
    if not ui_token and not _WARNED_MISSING_UI_TOKEN:
        log.warning(
            "REGISTRY_UI_TOKEN is not set — Registry UI authentication is disabled. "
            "Keep the service bound to localhost only."
        )
        _WARNED_MISSING_UI_TOKEN = True
    return RegistrySettings(
        db_path=db_path,
        enroll_token=enroll_token,
        ui_token=ui_token,
        display_name=display_name,
        allow_http=allow_http,
    )


def validate_settings(settings: RegistrySettings | None = None) -> RegistrySettings:
    current = settings or load_settings()
    if not current.enroll_token:
        raise RuntimeError("REGISTRY_ENROLL_TOKEN must be set before the registry can start.")
    if current.enroll_token in _KNOWN_DEFAULT_TOKENS:
        raise RuntimeError("REGISTRY_ENROLL_TOKEN must not use a known default token.")
    if current.ui_token in _KNOWN_DEFAULT_TOKENS:
        raise RuntimeError("REGISTRY_UI_TOKEN must not use a known default token.")
    if current.allow_http:
        log.warning(
            "REGISTRY_ALLOW_HTTP=1 is enabled — session cookies may be sent over HTTP. "
            "Use this only for local development."
        )
    return current


def configure_session_middleware(app) -> None:
    settings = load_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("REGISTRY_SESSION_SECRET", secrets.token_hex(32)),
        session_cookie="registry_session",
        same_site="strict",
        max_age=_SESSION_TTL_SECONDS,
        https_only=not settings.allow_http,
    )


def require_agent_token(
    authorization: str | None = Header(default=None),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def require_ui_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    require_ui_session_or_token(request, authorization)


def current_ui_csrf_token(request: Request) -> str:
    token = str(request.session.get("ui_csrf_token") or "")
    if not token:
        token = secrets.token_hex(16)
        request.session["ui_csrf_token"] = token
    return token


def require_ui_session_or_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    if ui_session_is_valid(request):
        current_ui_csrf_token(request)
        return "session"
    settings = load_settings()
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if settings.ui_token and hmac.compare_digest(token, settings.ui_token):
        return "bearer"
    raise HTTPException(status_code=401, detail="Invalid UI session or token")


def require_ui_write_access(
    request: Request,
    auth_mode: str = Depends(require_ui_session_or_token),
    x_csrf_token: str | None = Header(default=None),
) -> None:
    if auth_mode == "bearer":
        return
    expected = current_ui_csrf_token(request)
    provided = (x_csrf_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def ui_session_is_valid(request: Request) -> bool:
    settings = load_settings()
    if not settings.ui_token:
        return True
    return request.session.get("ui_authenticated") is True


def require_ui_session(request: Request) -> None:
    if ui_session_is_valid(request):
        return
    raise HTTPException(status_code=302, headers={"Location": "/ui/login"})


def ui_password_matches(password: str, *, settings: RegistrySettings | None = None) -> bool:
    current = settings or load_settings()
    if not current.ui_token:
        return True
    return hmac.compare_digest(password, current.ui_token)


def mark_ui_session_authenticated(request: Request) -> None:
    request.session["ui_authenticated"] = True
    current_ui_csrf_token(request)


def clear_ui_session(request: Request) -> None:
    request.session.clear()
