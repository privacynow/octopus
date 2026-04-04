"""CLI for DB init and doctor."""

from __future__ import annotations

import os
import sys

from app.db.postgres import get_connection
from app.db.postgres_init import run_init
from app.db.postgres_doctor import run_doctor
from app.startup_diagnostics import (
    format_database_startup_exception,
    redact_sensitive_startup_text,
)


def _get_url() -> str:
    url = os.environ.get("OCTOPUS_DATABASE_URL", "").strip()
    if not url:
        print(
            "OCTOPUS_DATABASE_URL is not set. For Docker: Compose sets it for the container. "
            "For host-run: set it in the bot env file (for example postgresql://bot:bot@localhost:5432/bot).",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def _cmd_init() -> None:
    url = _get_url()
    try:
        with get_connection(url) as conn:
            errors = run_init(conn)
    except Exception as e:
        for line in format_database_startup_exception(e):
            print(line, file=sys.stderr)
        sys.exit(1)
    if errors:
        _print_sanitized_failures(errors)
        sys.exit(1)
    print("Init complete.")


def _cmd_doctor() -> None:
    url = _get_url()
    try:
        with get_connection(url) as conn:
            errors = run_doctor(conn)
    except Exception as e:
        for line in format_database_startup_exception(e):
            print(line, file=sys.stderr)
        sys.exit(1)
    if errors:
        _print_sanitized_failures(errors)
        sys.exit(1)
    print("All checks passed.")


def _print_sanitized_failures(errors: list[str]) -> None:
    for error in errors:
        print(f"  FAIL: {redact_sensitive_startup_text(str(error))}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.db.cli init|doctor", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "init":
        _cmd_init()
    elif cmd == "doctor":
        _cmd_doctor()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
