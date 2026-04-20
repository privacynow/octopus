"""Registry UI/login HTTP routes and static mounts."""

from __future__ import annotations

from pathlib import Path
from os import PathLike
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    clear_auth_attempt_limit,
    clear_ui_session,
    enforce_auth_attempt_limit,
    load_settings,
    mark_ui_session_authenticated,
    require_ui_session,
    ui_password_matches,
    ui_session_is_valid,
)
from .http_support import secure_html_response

_UI_DIR = Path(__file__).resolve().parent / "ui"
_UI_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _ui_asset_version() -> str:
    latest_mtime = 0
    for path in _UI_DIR.rglob("*"):
        if path.is_file():
            latest_mtime = max(latest_mtime, int(path.stat().st_mtime_ns))
    return str(latest_mtime)


_UI_ASSET_VERSION = _ui_asset_version()
_INDEX_HTML = (_UI_DIR / "index.html").read_text()


def _render_ui_shell() -> str:
    return _INDEX_HTML.replace("__UI_ASSET_VERSION__", _UI_ASSET_VERSION)


class _NoStoreStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: str | PathLike[str],
        stat_result: Any,
        scope: dict[str, Any],
        status_code: int = 200,
    ):
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        response.headers.update(_UI_CACHE_HEADERS)
        return response


def _render_login_html(title: str, error: str = "") -> str:
    error_block = f'<p class="error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Login</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #f5f5f5; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .box {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.12); padding: 2rem; min-width: 320px; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1.5rem; }}
  label {{ display: block; margin-bottom: .4rem; font-size: .875rem; font-weight: 500; }}
  input[type=password] {{ width: 100%; box-sizing: border-box; padding: .5rem .75rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; margin-bottom: 1rem; }}
  button {{ width: 100%; padding: .6rem; background: #1a73e8; color: #fff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }}
  button:hover {{ background: #1558b0; }}
  .error {{ color: #c62828; font-size: .875rem; margin-bottom: .75rem; }}
</style>
</head>
<body>
<div class="box">
  <h1>{title}</h1>
  {error_block}
  <form method="post" action="/ui/login">
    <label for="password">Password</label>
    <input type="password" id="password" name="password" autofocus required>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""


def register_ui_routes(app: FastAPI, *, security_headers: dict[str, str]) -> None:
    shell_headers = dict(security_headers)
    shell_headers.update(_UI_CACHE_HEADERS)

    @app.get("/ui/login", response_class=HTMLResponse)
    def ui_login_page(request: Request):
        settings = load_settings()
        if ui_session_is_valid(request):
            return RedirectResponse("/ui", status_code=303)
        return secure_html_response(
            _render_login_html(settings.display_name or "Agent Registry"),
            headers=shell_headers,
        )

    @app.post("/ui/login")
    async def ui_login(request: Request, password: str = Form(default="")):
        settings = load_settings()
        if ui_session_is_valid(request):
            return RedirectResponse("/ui", status_code=303)
        enforce_auth_attempt_limit(request, "registry-ui-login")
        if not ui_password_matches(password, settings=settings):
            return secure_html_response(
                _render_login_html(settings.display_name or "Agent Registry", error="Incorrect password."),
                headers=shell_headers,
            )
        clear_auth_attempt_limit(request, "registry-ui-login")
        mark_ui_session_authenticated(request)
        return RedirectResponse("/ui", status_code=303)

    @app.get("/ui/logout")
    def ui_logout(request: Request):
        clear_ui_session(request)
        return RedirectResponse("/ui/login", status_code=303)

    @app.get("/ui", response_class=HTMLResponse)
    def ui_shell(request: Request) -> HTMLResponse:
        require_ui_session(request)
        return HTMLResponse(
            _render_ui_shell(),
            headers=dict(shell_headers),
        )

    if _UI_DIR.is_dir():
        app.mount("/ui/css", _NoStoreStaticFiles(directory=str(_UI_DIR / "css")), name="ui-css")
        app.mount("/ui/js", _NoStoreStaticFiles(directory=str(_UI_DIR / "js")), name="ui-js")
        if (_UI_DIR / "vendor").is_dir():
            app.mount("/ui/vendor", _NoStoreStaticFiles(directory=str(_UI_DIR / "vendor")), name="ui-vendor")

        @app.get("/ui/{path:path}", response_class=HTMLResponse)
        def ui_spa_subpath(request: Request, path: str) -> HTMLResponse:
            if path == "login":
                raise HTTPException(status_code=404)
            require_ui_session(request)
            return HTMLResponse(
                _render_ui_shell(),
                headers=dict(shell_headers),
            )

        @app.get("/ui/spa/{path:path}", response_class=HTMLResponse)
        def ui_spa_catchall(request: Request, path: str = ""):
            del path
            require_ui_session(request)
            return HTMLResponse(
                _render_ui_shell(),
                headers=dict(shell_headers),
            )
