"""Claude CLI provider — stream-json, session-id based sessions."""

import asyncio
import html
import json
import logging
import os
import shutil
import uuid
from typing import Any

from app.config import BotConfig
from app.formatting import md_to_telegram_html, trim_text
from app.providers.base import ProgressSink, RunResult

log = logging.getLogger(__name__)


class ClaudeProvider:
    name = "claude"

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def new_provider_state(self) -> dict[str, Any]:
        return {"session_id": str(uuid.uuid4()), "started": False}

    def check_health(self) -> list[str]:
        errors: list[str] = []
        if not shutil.which("claude"):
            errors.append("'claude' binary not found in PATH")
            return errors
        # Verify the binary actually works
        import subprocess
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"'claude --version' failed (rc={result.returncode}): {result.stderr.strip()[:200]}")
            else:
                log.info("claude version: %s", result.stdout.strip())
        except subprocess.TimeoutExpired:
            errors.append("'claude --version' timed out")
        except OSError as e:
            errors.append(f"'claude' binary not executable: {e}")
        return errors

    # -- subprocess env ----------------------------------------------------

    @staticmethod
    def _clean_env() -> dict[str, str]:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    # -- command building --------------------------------------------------

    def _base_cmd(self) -> list[str]:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        return cmd

    def _extra_dir_args(self, extra_dirs: list[str] | None = None) -> list[str]:
        args: list[str] = []
        for d in self.config.extra_dirs:
            args.extend(["--add-dir", str(d)])
        for d in extra_dirs or []:
            args.extend(["--add-dir", d])
        return args

    def _build_run_cmd(
        self,
        provider_state: dict[str, Any],
        prompt: str,
        extra_dirs: list[str] | None = None,
    ) -> list[str]:
        cmd = self._base_cmd()
        sid = provider_state["session_id"]
        if provider_state.get("started"):
            cmd.extend(["--resume", sid])
        else:
            cmd.extend(["--session-id", sid])
        cmd.extend(self._extra_dir_args(extra_dirs))
        cmd.extend(["--", prompt])
        return cmd

    def _build_preflight_cmd(self, prompt: str) -> list[str]:
        cmd = self._base_cmd()
        cmd.extend(["--permission-mode", "plan"])
        cmd.extend(self._extra_dir_args())
        cmd.extend(["--", prompt])
        return cmd

    # -- stream parsing & progress -----------------------------------------

    async def _consume_stream(
        self,
        proc: asyncio.subprocess.Process,
        progress: ProgressSink,
    ) -> tuple[str, dict, list[str]]:
        """Read stdout, update progress, return (accumulated_text, result_data, tool_activity)."""
        accumulated_text = ""
        tool_activity: list[str] = []
        result_data: dict = {}

        def build_display() -> str:
            parts = []
            if tool_activity:
                parts.append(
                    "<i>" + html.escape(" \u2192 ".join(tool_activity[-3:])) + "</i>"
                )
            if accumulated_text:
                parts.append(md_to_telegram_html(trim_text(accumulated_text, 3200)))
            else:
                parts.append("<i>thinking\u2026</i>")
            return "\n".join(parts)

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.warning("non-JSON from claude: %s", line[:200])
                continue

            etype = event.get("type", "")

            if etype == "stream_event":
                inner = event.get("event", {})
                itype = inner.get("type", "")
                if itype == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        accumulated_text += delta.get("text", "")
                        await progress.update(build_display())
                elif itype == "content_block_start":
                    cb = inner.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        tool_activity.append(f"\u2699 {cb.get('name', '?')}")
                        await progress.update(build_display(), force=True)

            elif etype == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        accumulated_text = block.get("text", "")

            elif etype == "user":
                for block in event.get("message", {}).get("content", []):
                    if block.get("is_error") and "permission" in str(
                        block.get("content", "")
                    ).lower():
                        tool_activity.append("\u26d4 denied")
                        await progress.update(build_display(), force=True)

            elif etype == "result":
                result_data = event
                break

        # Drain remaining stdout so the process can exit cleanly
        async for _ in proc.stdout:
            pass
        await proc.wait()

        return accumulated_text, result_data, tool_activity

    # -- execution ---------------------------------------------------------

    async def _run_process(
        self,
        cmd: list[str],
        progress: ProgressSink,
        timeout: int | None = None,
    ) -> tuple[str, dict, int]:
        """Spawn claude, consume output, return (accumulated_text, result_data, returncode)."""
        log.info("claude: %s", " ".join(cmd[:-1] + ["<prompt>"]))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.working_dir),
            env=self._clean_env(),
            limit=1024 * 1024,
        )

        stderr_task = asyncio.create_task(proc.stderr.read())
        effective_timeout = timeout or self.config.timeout_seconds

        try:
            accumulated, result_data, _ = await asyncio.wait_for(
                self._consume_stream(proc, progress),
                timeout=effective_timeout,
            )
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            await stderr_task
            return "", {}, -1  # sentinel for timeout

        if proc.returncode and proc.returncode != 0:
            log.error("claude error (rc=%d): %s", proc.returncode, stderr[:300])

        return accumulated, result_data, proc.returncode or 0

    async def run(
        self,
        provider_state: dict[str, Any],
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        extra_dirs: list[str] | None = None,
    ) -> RunResult:
        # Claude doesn't have -i flags; images are referenced by path in the prompt
        cmd = self._build_run_cmd(provider_state, prompt, extra_dirs=extra_dirs)

        accumulated, result_data, rc = await self._run_process(cmd, progress)

        if rc == -1:
            return RunResult(text="", timed_out=True, returncode=124)

        if rc != 0:
            return RunResult(
                text=f"[Claude error (rc={rc})]",
                returncode=rc,
            )

        final_text = result_data.get("result", accumulated) or accumulated
        denials = result_data.get("permission_denials", [])

        return RunResult(
            text=final_text,
            denials=denials,
            provider_state_updates={"started": True},
        )

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
    ) -> RunResult:
        cmd = self._build_preflight_cmd(prompt)

        accumulated, result_data, rc = await self._run_process(
            cmd, progress, timeout=120
        )

        if rc == -1:
            return RunResult(text="", timed_out=True, returncode=124)

        if rc != 0:
            return RunResult(
                text=f"[Preflight error (rc={rc})]",
                returncode=rc,
            )

        final_text = result_data.get("result", accumulated) or accumulated
        return RunResult(text=final_text)
