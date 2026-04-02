from __future__ import annotations

import asyncio
from collections.abc import Mapping

from app.formatting import trim_text


async def run_health_command(
    *cmd: str,
    timeout: int,
    env: Mapping[str, str],
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, stdout.decode(), stderr.decode()


def combined_output(stdout: str = "", stderr: str = "") -> str:
    return "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()


def health_detail(output: str, *, limit: int = 200) -> str:
    parts: list[str] = []
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("Volume ", "Container ")):
            continue
        parts.append(stripped)
    return trim_text(" ".join(parts).strip(), limit)


def command_failure(label: str, returncode: int, *, stdout: str = "", stderr: str = "", fallback: str = "") -> str:
    detail = health_detail(combined_output(stdout, stderr))
    suffix = detail or fallback
    if suffix:
        return f"{label} failed (rc={returncode}): {suffix}"
    return f"{label} failed (rc={returncode})"
