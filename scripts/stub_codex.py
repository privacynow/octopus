#!/usr/bin/env python3
"""Stub 'codex' provider for Docker E2E and runnable image.

Satisfies config validation and doctor/startup so the bot container can start
without the real Codex CLI. Used only by the runnable image built from
Dockerfile.runnable. For production, use an image that includes the real
Codex CLI.
"""
from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    # --version: pass config/health check
    if "--version" in argv:
        print("codex 1.0.0 (stub)")
        sys.exit(0)
    # exec (API ping or run): pass doctor and runtime health; minimal NDJSON
    if "exec" in argv:
        # Minimal valid-looking output so health check passes
        print('{"type":"command_finish","exit_code":0}')
        sys.exit(0)
    # Unknown
    print("(stub: no real provider)")
    sys.exit(0)


if __name__ == "__main__":
    main()
