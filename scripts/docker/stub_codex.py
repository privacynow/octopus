#!/usr/bin/env python3
"""Stub 'codex' provider for Docker E2E and runnable image.

Supports the same deterministic hold/release prompt markers as stub_claude.py:
- ``E2E_BLOCK:<key>`` waits for ``$TELEGRAM_AGENT_STUB_CONTROL_DIR/release/<key>``
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_BLOCK_RE = re.compile(r"E2E_BLOCK:([A-Za-z0-9_.-]+)")


def _prompt_from_argv(argv: list[str]) -> str:
    return argv[-1].strip() if argv else ""


def _ensure_marker(path: Path, value: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _maybe_wait_for_release(prompt: str) -> None:
    control_dir = os.environ.get("TELEGRAM_AGENT_STUB_CONTROL_DIR", "").strip()
    if not control_dir:
        return
    match = _BLOCK_RE.search(prompt)
    if match is None:
        return
    key = match.group(1)
    base = Path(control_dir)
    _ensure_marker(base / "started" / key, prompt)
    release_path = base / "release" / key
    while not release_path.exists():
        time.sleep(0.1)


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv:
        print("codex 1.0.0 (stub)")
        sys.exit(0)

    if "exec" in argv:
        prompt = _prompt_from_argv(argv)
        _maybe_wait_for_release(prompt)
        print(json.dumps({"type": "command_finish", "exit_code": 0}), flush=True)
        sys.exit(0)

    print("(stub: no real provider)")
    sys.exit(0)


if __name__ == "__main__":
    main()
