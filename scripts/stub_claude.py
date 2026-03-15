#!/usr/bin/env python3
"""Stub 'claude' provider for Docker E2E and runnable image.

Satisfies config validation and doctor/startup so the bot container can start
without the real Claude CLI. Used only by the runnable image built from
Dockerfile.runnable. For production, use an image that includes the real
Claude Code CLI.
"""
from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    # --version: pass config/health check
    if "--version" in argv:
        print("claude 1.0.0 (stub)")
        sys.exit(0)
    # -p (preflight/API ping): pass doctor and runtime health
    if "-p" in argv:
        print("ok")
        sys.exit(0)
    # Any other invocation (e.g. run): minimal response so bot does not crash
    # Stream-json would be multiple lines; one line is enough for stub
    print('{"type":"text_delta","delta":"(stub: no real provider)"}')
    sys.exit(0)


if __name__ == "__main__":
    main()
