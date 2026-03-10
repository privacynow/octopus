"""Claude CLI provider — stream-json, session-id based sessions."""

import asyncio
import html
import json
import logging
import os
import shutil
import tempfile
import uuid
from typing import Any

from app.config import BotConfig
from app.formatting import md_to_telegram_html, trim_text
from app.providers.base import PreflightContext, ProgressSink, RunContext, RunResult

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

    async def check_runtime_health(self) -> list[str]:
        errors: list[str] = []
        # Version check
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                errors.append(f"'claude --version' failed (rc={proc.returncode}): {stderr.decode()[:200]}")
            else:
                log.info("claude version: %s", stdout.decode().strip())
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            errors.append("'claude --version' timed out")
        except OSError as e:
            errors.append(f"'claude' binary not executable: {e}")
        # API ping
        if not errors:
            try:
                model = self.config.model or "claude-sonnet-4-20250514"
                proc = await asyncio.create_subprocess_exec(
                    "claude", "-p", "--model", model, "--max-turns", "1",
                    "--output-format", "text", "reply with ok",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode != 0:
                    errors.append(f"API ping failed (rc={proc.returncode}): {stderr.decode()[:200]}")
                else:
                    log.info("claude API ping ok")
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
                await proc.wait()
                errors.append("API ping timed out (15s)")
            except OSError as e:
                errors.append(f"API ping error: {e}")
        return errors

    # -- subprocess env ----------------------------------------------------

    @staticmethod
    def _clean_env() -> dict[str, str]:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    # -- command building --------------------------------------------------

    def _base_cmd(self, effective_model: str = "") -> list[str]:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
        ]
        model = effective_model or self.config.model
        if model:
            cmd.extend(["--model", model])
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
        effective_model: str = "",
    ) -> list[str]:
        cmd = self._base_cmd(effective_model)
        sid = provider_state["session_id"]
        if provider_state.get("started"):
            cmd.extend(["--resume", sid])
        else:
            cmd.extend(["--session-id", sid])
        cmd.extend(self._extra_dir_args(extra_dirs))
        cmd.extend(["--", prompt])
        return cmd

    def _build_preflight_cmd(self, prompt: str, extra_dirs: list[str] | None = None, effective_model: str = "") -> list[str]:
        cmd = self._base_cmd(effective_model)
        cmd.extend(["--permission-mode", "plan"])
        cmd.extend(self._extra_dir_args(extra_dirs))
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
                parts.append("<i>Thinking...</i>")
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
                        # Signal that real content is streaming — stops heartbeat
                        cs = getattr(progress, "content_started", None)
                        if cs and not cs.is_set():
                            cs.set()
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
        extra_env: dict[str, str] | None = None,
        working_dir: str = "",
    ) -> tuple[str, dict, int]:
        """Spawn claude, consume output, return (accumulated_text, result_data, returncode)."""
        log.info("claude: %s", " ".join(cmd[:-1] + ["<prompt>"]))

        env = self._clean_env()
        if extra_env:
            env.update(extra_env)

        cwd = working_dir or str(self.config.working_dir)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
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

    def _apply_provider_config(self, cmd: list[str], provider_config: dict) -> str | None:
        """Apply provider_config to command. Returns temp MCP config path or None."""
        mcp_tmp = None
        if "mcp_servers" in provider_config:
            # Write MCP server config to a temp file
            mcp_data = {"mcpServers": provider_config["mcp_servers"]}
            f = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="mcp_", delete=False,
            )
            json.dump(mcp_data, f)
            f.close()
            mcp_tmp = f.name
            idx = cmd.index("--")
            cmd[idx:idx] = ["--mcp-config", mcp_tmp]

        if "allowed_tools" in provider_config:
            for tool in provider_config["allowed_tools"]:
                idx = cmd.index("--")
                cmd[idx:idx] = ["--allowedTools", tool]

        if "disallowed_tools" in provider_config:
            for tool in provider_config["disallowed_tools"]:
                idx = cmd.index("--")
                cmd[idx:idx] = ["--disallowedTools", tool]

        return mcp_tmp

    async def run(
        self,
        provider_state: dict[str, Any],
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: RunContext | None = None,
    ) -> RunResult:
        extra_dirs = context.extra_dirs if context else None
        effective_model = context.effective_model if context else ""
        cmd = self._build_run_cmd(provider_state, prompt, extra_dirs=extra_dirs, effective_model=effective_model)
        if context and context.skip_permissions:
            idx = cmd.index("--")
            cmd[idx:idx] = ["--dangerously-skip-permissions"]
        system_prompt_parts = []
        if context and context.system_prompt:
            system_prompt_parts.append(context.system_prompt)
        if context and context.file_policy == "inspect":
            system_prompt_parts.append(
                "IMPORTANT: This session is in INSPECT (read-only) mode. "
                "Do NOT create, modify, delete, or rename any files. "
                "Only read and analyze code. Refuse any request that would change files."
            )
        if system_prompt_parts:
            idx = cmd.index("--")
            cmd[idx:idx] = ["--append-system-prompt", "\n\n".join(system_prompt_parts)]

        mcp_tmp = None
        if context and context.provider_config:
            mcp_tmp = self._apply_provider_config(cmd, context.provider_config)

        # Inject credential env
        extra_env = context.credential_env if context else {}

        working_dir = context.working_dir if context else ""
        accumulated, result_data, rc = await self._run_process(
            cmd, progress, extra_env=extra_env, working_dir=working_dir,
        )

        # Cleanup temp MCP config
        if mcp_tmp:
            try:
                os.unlink(mcp_tmp)
            except OSError:
                pass

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
        context: PreflightContext | None = None,
    ) -> RunResult:
        extra_dirs = context.extra_dirs if context else None
        effective_model = getattr(context, 'effective_model', '') if context else ""
        cmd = self._build_preflight_cmd(prompt, extra_dirs=extra_dirs, effective_model=effective_model)
        system_prompt = ""
        if context and context.system_prompt:
            system_prompt = context.system_prompt
        # Include capability summary in system prompt for preflight awareness
        if context and context.capability_summary:
            cap = f"\n\n## Available capabilities\n\n{context.capability_summary}"
            system_prompt = (system_prompt + cap) if system_prompt else cap
        if system_prompt:
            idx = cmd.index("--")
            cmd[idx:idx] = ["--append-system-prompt", system_prompt]

        working_dir = context.working_dir if context else ""
        accumulated, result_data, rc = await self._run_process(
            cmd, progress, timeout=120, working_dir=working_dir,
        )

        if rc == -1:
            return RunResult(text="", timed_out=True, returncode=124)

        if rc != 0:
            return RunResult(
                text=f"[Approval check error (rc={rc})]",
                returncode=rc,
            )

        final_text = result_data.get("result", accumulated) or accumulated
        return RunResult(text=final_text)
