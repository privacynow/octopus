"""CLI for DB bootstrap, update, and doctor (Phase 12)."""

from __future__ import annotations

import os
import sys

from app.db.postgres import get_connection
from app.db.postgres_migrate import run_bootstrap, run_update
from app.db.postgres_doctor import run_doctor


def _get_url() -> str:
    url = os.environ.get("BOT_DATABASE_URL", "").strip()
    if not url:
        print(
            "BOT_DATABASE_URL is not set. For Docker: Compose sets it for the container. "
            "For host-run: set it in .env.bot (e.g. postgresql://bot:bot@localhost:5432/bot).",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def _cmd_bootstrap() -> None:
    url = _get_url()
    try:
        with get_connection(url) as conn:
            errors = run_bootstrap(conn)
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("Bootstrap complete.")


def _cmd_update() -> None:
    url = _get_url()
    try:
        with get_connection(url) as conn:
            errors = run_update(conn)
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("Update complete.")


def _cmd_doctor() -> None:
    url = _get_url()
    try:
        with get_connection(url) as conn:
            errors = run_doctor(conn)
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("All checks passed.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.db.cli bootstrap|update|doctor", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "bootstrap":
        _cmd_bootstrap()
    elif cmd == "update":
        _cmd_update()
    elif cmd == "doctor":
        _cmd_doctor()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
