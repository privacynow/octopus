"""Registry-channel auth and session helpers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware

from octopus_sdk.ratelimit import RateLimiter

from .backend import get_registry_store
from .config import RegistryConfig, load_registry_config, validate_registry_config

log = logging.getLogger(__name__)
_SESSION_TTL_SECONDS = 24 * 60 * 60
_KNOWN_DEFAULT_TOKENS = {"dev-enroll-token", "dev-ui-token", "changeme"}
_AUTH_ATTEMPT_LIMITER = RateLimiter(per_minute=5, per_hour=30)


RegistrySettings = RegistryConfig


def load_settings() -> RegistrySettings:
    return load_registry_config()


def validate_settings(settings: RegistrySettings | None = None) -> RegistrySettings:
    return validate_registry_config(settings)


def _auth_attempt_key(request: Request, endpoint: str) -> str:
    client = request.client
    host = str(client.host if client and client.host else "unknown")
    return f"{endpoint}:{host}"


def enforce_auth_attempt_limit(request: Request, endpoint: str) -> None:
    allowed, retry_after = _AUTH_ATTEMPT_LIMITER.check(_auth_attempt_key(request, endpoint))
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail="Too many authentication attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def clear_auth_attempt_limit(request: Request, endpoint: str) -> None:
    _AUTH_ATTEMPT_LIMITER.clear(_auth_attempt_key(request, endpoint))


def reset_auth_attempt_limits_for_test() -> None:
    _AUTH_ATTEMPT_LIMITER.clear()


def session_secret(*, settings: RegistrySettings | None = None) -> str:
    explicit = os.environ.get("REGISTRY_SESSION_SECRET", "").strip()
    if explicit:
        return explicit
    current = settings or load_settings()
    seed = f"registry-session:{current.ui_token}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def configure_session_middleware(app) -> None:
    settings = load_settings()
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret(settings=settings),
        session_cookie="registry_session",
        same_site="lax",
        max_age=_SESSION_TTL_SECONDS,
        https_only=not settings.allow_http,
    )


@dataclass(frozen=True)
class AuthContext:
    """Resolved auth identity for resource endpoints."""
    is_agent: bool = False
    is_operator: bool = False
    agent_id: str | None = None      # set when is_agent=True; used for scoped reads
    agent_token: str | None = None    # raw token, for passing to store methods that need it
    org_id: str = "local"
    roles: tuple[str, ...] = ()


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
    return request.session.get("ui_authenticated") is True


def require_ui_session(request: Request) -> None:
    if ui_session_is_valid(request):
        return
    raise HTTPException(status_code=302, headers={"Location": "/ui/login"})


def ui_password_matches(password: str, *, settings: RegistrySettings | None = None) -> bool:
    current = settings or load_settings()
    if not current.ui_token:
        return False
    return hmac.compare_digest(password, current.ui_token)


def mark_ui_session_authenticated(request: Request) -> None:
    request.session["ui_authenticated"] = True
    current_ui_csrf_token(request)


def clear_ui_session(request: Request) -> None:
    request.session.clear()


# ---------------------------------------------------------------------------
# Unified auth for resource endpoints (Phase 8 of registry UI rebuild)
# ---------------------------------------------------------------------------

def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract bearer token Authorization header, or None."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip() or None
    return None


def _validate_csrf_for_session_mutation(request: Request, x_csrf_token: str | None) -> None:
    """Enforce CSRF on session-cookie mutating requests. Shared by both auth deps."""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    expected = current_ui_csrf_token(request)
    provided = (x_csrf_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def require_authenticated(
    request: Request,
    authorization: str | None = Header(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> AuthContext:
    """Accept either Bearer agent token or operator session cookie.

    For session-cookie callers on mutation requests (POST/PUT/DELETE),
    validates X-CSRF-Token. Bearer token requests skip CSRF.
    """
    # Try agent token first
    token = _extract_bearer_token(authorization)
    if token:
        store = get_registry_store()
        agent_record = store.resolve_agent_for_token(token)
        if agent_record is None:
            raise HTTPException(status_code=401, detail="Unknown agent token")
        settings = load_settings()
        return AuthContext(
            is_agent=True,
            agent_id=str(agent_record.agent_id),
            agent_token=token,
            org_id=settings.operator_org_id,
            roles=("agent",),
        )
    # Fall back to session cookie
    if ui_session_is_valid(request):
        _validate_csrf_for_session_mutation(request, x_csrf_token)
        current_ui_csrf_token(request)
        settings = load_settings()
        return AuthContext(
            is_operator=True,
            org_id=settings.operator_org_id,
            roles=settings.operator_roles,
        )
    raise HTTPException(status_code=401, detail="Authentication required")


def require_operator_session(
    request: Request,
    authorization: str | None = Header(default=None),
    x_csrf_token: str | None = Header(default=None),
) -> AuthContext:
    """Operator session only. Rejects agent tokens.

    Validates CSRF on mutating methods (shared with require_authenticated).
    """
    # Reject agent tokens explicitly
    if _extract_bearer_token(authorization):
        raise HTTPException(status_code=403, detail="This endpoint requires an operator session, not an agent token")
    if not ui_session_is_valid(request):
        raise HTTPException(status_code=401, detail="Operator session required")
    _validate_csrf_for_session_mutation(request, x_csrf_token)
    current_ui_csrf_token(request)
    settings = load_settings()
    return AuthContext(
        is_operator=True,
        org_id=settings.operator_org_id,
        roles=settings.operator_roles,
    )
