#!/usr/bin/env python3
"""Stub 'claude' provider for Docker E2E and runnable image.

Supports:
- provider health/startup checks
- deterministic stream-json runs for Compose E2E
- optional hold/release behavior keyed by prompt markers

Control markers embedded in the prompt:
- ``E2E_BLOCK:<key>``: hold until ``$TELEGRAM_AGENT_STUB_CONTROL_DIR/release/<key>`` exists
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_BLOCK_RE = re.compile(r"E2E_BLOCK:([A-Za-z0-9_.-]+)")


def _arg_value(argv: list[str], flag: str) -> str:
    try:
        idx = argv.index(flag)
    except ValueError:
        return ""
    if idx + 1 >= len(argv):
        return ""
    return argv[idx + 1]


def _prompt_from_argv(argv: list[str]) -> str:
    if "--" in argv:
        idx = argv.index("--")
        return " ".join(argv[idx + 1 :]).strip()
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


def _stream_result(text: str) -> None:
    payload = {
        "type": "result",
        "result": text,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "total_cost_usd": 0.0,
    }
    print(json.dumps(payload), flush=True)


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv:
        print("claude 1.0.0 (stub)")
        sys.exit(0)

    output_format = _arg_value(argv, "--output-format")
    if "-p" in argv and output_format != "stream-json":
        print("ok")
        sys.exit(0)

    prompt = _prompt_from_argv(argv)
    _maybe_wait_for_release(prompt)
    if output_format == "stream-json":
        _stream_result("(stub response)")
    else:
        print("ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
