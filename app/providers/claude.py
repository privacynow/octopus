"""Claude CLI provider — stream-json, session-id based sessions."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.config import BotConfig
from app.formatting import trim_text
from app.provider_auth import auth_artifact_errors, runtime_auth_root
from app.provider_health import command_failure, run_health_command
from app.progress import (
    CommandFinish, ContentDelta, Denial, ToolFinish, ToolStart,
    Thinking, render as render_progress,
)
from octopus_sdk.providers import (
    PreflightContext,
    ProgressSink,
    RunContext,
    RunResult,
    ToolExecutionRecord,
)
from app.subprocess_env import build_subprocess_env

log = logging.getLogger(__name__)

_CLAUDE_ENV_KEYS = ("ANTHROPIC_API_KEY",)

# Claude CLI maps settings.ultracode=true to xhigh effort and enables
# multi-agent workflow orchestration; an explicit --effort flag still wins.
_ULTRACODE_SETTINGS = '{"ultracode": true}'


class ClaudeProvider:
    name = "claude"

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def new_provider_state(self, conversation_key: str) -> dict[str, Any]:
        sid = str(uuid.uuid5(uuid.NAMESPACE_URL, conversation_key))
        return {"session_id": sid, "started": False}

    @staticmethod
    def _should_resume(provider_state: dict[str, Any]) -> bool:
        return bool(provider_state.get("started"))

    @staticmethod
    def _continuity_updates(provider_state: dict[str, Any]) -> dict[str, Any]:
        # Claude keeps one deterministic session lineage per conversation.
        # After the first launched attempt, retries must switch to --resume
        # rather than reusing --session-id for the same conversation.
        if provider_state.get("session_id") or provider_state.get("started"):
            return {"started": True}
        return {}

    def check_health(self) -> list[str]:
        errors: list[str] = []
        if not shutil.which("claude"):
            errors.append("'claude' binary not found in PATH")
        return errors

    async def check_auth_health(self) -> list[str]:
        errors: list[str] = []
        try:
            returncode, stdout, stderr = await run_health_command(
                "claude",
                "--version",
                timeout=10,
                env=self._clean_env(),
            )
            if returncode != 0:
                errors.append(
                    command_failure("'claude --version'", returncode, stdout=stdout, stderr=stderr)
                )
            else:
                log.info("claude version: %s", stdout.strip())
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("'claude --version' timed out")
        except OSError as e:
            errors.append(f"'claude' binary not executable: {e}")
        if errors:
            return errors

        return auth_artifact_errors("claude", runtime_auth_root("claude"))

    async def check_runtime_health(self) -> list[str]:
        errors = await self.check_auth_health()
        if errors:
            return errors
        try:
            returncode, stdout, stderr = await run_health_command(
                "claude",
                "-p",
                "--output-format",
                "text",
                "--max-turns",
                "1",
                "--",
                "reply with ok",
                timeout=15,
                env=self._clean_env(),
            )
            if returncode != 0:
                errors.append(
                    command_failure(
                        "Claude runtime probe",
                        returncode,
                        stdout=stdout,
                        stderr=stderr,
                        fallback="Claude runtime probe failed.",
                    )
                )
            else:
                log.info("claude runtime probe ok")
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("Claude runtime probe timed out")
        except OSError as e:
            errors.append(f"Claude runtime probe failed: {e}")
        return errors

    # -- subprocess env ----------------------------------------------------

    @staticmethod
    def _clean_env() -> dict[str, str]:
        return build_subprocess_env(
            allowed_keys=_CLAUDE_ENV_KEYS,
            blocked_keys=("CLAUDECODE",),
        )

    # -- command building --------------------------------------------------

    def _base_cmd(self, effective_model: str = "") -> list[str]:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            # Required on Claude CLI 2.x for stream_event lines; without it
            # no text deltas or tool_use boundaries reach _consume_stream.
            "--include-partial-messages",
        ]
        model = effective_model or self.config.model
        if model:
            cmd.extend(["--model", model])
        if self.config.claude_effort:
            cmd.extend(["--effort", self.config.claude_effort])
        if self.config.claude_ultracode:
            cmd.extend(["--settings", _ULTRACODE_SETTINGS])
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
        if self._should_resume(provider_state):
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
        cancel: asyncio.Event | None = None,
    ) -> tuple[str, dict, list[str]]:
        """Read stdout, update progress, return (accumulated_text, result_data, tool_activity).

        If *cancel* is set, kills the subprocess and returns immediately
        with whatever text has been accumulated so far.
        """
        accumulated_text = ""
        tool_activity: list[str] = []
        current_tool: str = ""
        current_tool_id: str = ""
        current_tool_started_at: float | None = None
        tool_counter = 0
        tool_records: list[ToolExecutionRecord] = []
        tool_record_index: dict[str, int] = {}
        result_data: dict = {}
        saw_stream_text = False
        last_delta_emit = 0.0
        delta_pending = False

        async def _emit(evt, *, force: bool = False) -> None:
            rendered = render_progress(evt)
            if rendered:
                await progress.update(rendered, force=force)

        async def _emit_accumulated() -> None:
            active = (f"⚙ {current_tool}",) if current_tool else ()
            await _emit(ContentDelta(
                text=accumulated_text,
                tool_activity=active,
            ))

        cancel_fut: asyncio.Future | None = None
        while True:
            if cancel is not None:
                if cancel_fut is None:
                    cancel_fut = asyncio.ensure_future(cancel.wait())
                read_fut = asyncio.ensure_future(proc.stdout.readline())
                await asyncio.wait(
                    [read_fut, cancel_fut],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel.is_set():
                    read_fut.cancel()
                    cancel_fut.cancel()
                    proc.kill()
                    await proc.wait()
                    return accumulated_text, {"_tool_executions": tool_records}, tool_activity
                line = read_fut.result()
            else:
                line = await proc.stdout.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.warning("non-JSON claude: %s", line[:200])
                continue

            etype = event.get("type", "")
            log.debug("claude raw event: %s", line[:500])

            if etype == "stream_event":
                inner = event.get("event", {})
                itype = inner.get("type", "")
                if itype == "message_start":
                    # Keep multi-turn progress/cancel text readable.
                    if accumulated_text and not accumulated_text.endswith("\n"):
                        accumulated_text += "\n\n"
                elif itype == "message_stop":
                    if delta_pending:
                        delta_pending = False
                        await _emit_accumulated()
                elif itype == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        accumulated_text += delta.get("text", "")
                        saw_stream_text = True
                        # Signal that real content is streaming — stops heartbeat
                        cs = getattr(progress, "content_started", None)
                        if cs and not cs.is_set():
                            cs.set()
                        # Deltas arrive per token; rendering each one would do
                        # a full markdown pass the sink throttle then discards,
                        # so gate here and flush the tail on message_stop.
                        now = time.monotonic()
                        if now - last_delta_emit >= self.config.stream_update_interval_seconds:
                            last_delta_emit = now
                            delta_pending = False
                            await _emit_accumulated()
                        else:
                            delta_pending = True
                elif itype == "content_block_start":
                    cb = inner.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        tool_name = cb.get("name", "?")
                        current_tool = tool_name
                        current_tool_id = str(cb.get("id", "") or "")
                        current_tool_started_at = time.monotonic()
                        tool_activity.append(f"\u2699 {tool_name}")
                        await _emit(ToolStart(name=tool_name), force=True)
                elif itype == "content_block_stop":
                    if current_tool:
                        duration_ms: int | None = None
                        if current_tool_started_at is not None:
                            duration_ms = max(0, int((time.monotonic() - current_tool_started_at) * 1000))
                        # The tool_use block finishing means its INPUT streamed
                        # fully; execution happens after. A later tool_result
                        # (e.g. permission denial) corrects this record by id.
                        call_id = current_tool_id or f"claude-tool-{tool_counter}"
                        tool_record_index[call_id] = len(tool_records)
                        tool_records.append(
                            ToolExecutionRecord(
                                tool_name=current_tool,
                                call_id=call_id,
                                status="completed",
                                input_summary=current_tool,
                                output_summary="completed",
                                duration_ms=duration_ms,
                            )
                        )
                        tool_counter += 1
                        await _emit(ToolFinish(name=current_tool))
                        current_tool = ""
                        current_tool_id = ""
                        current_tool_started_at = None

            elif etype == "assistant":
                # With --include-partial-messages the deltas above are
                # authoritative; only fall back to full assistant messages
                # when no stream text arrived (older CLIs, degraded streams).
                if not saw_stream_text:
                    msg = event.get("message", {})
                    message_text = "".join(
                        block.get("text", "")
                        for block in msg.get("content", [])
                        if block.get("type") == "text"
                    )
                    if message_text:
                        accumulated_text = (
                            f"{accumulated_text}\n\n{message_text}"
                            if accumulated_text
                            else message_text
                        )

            elif etype == "user":
                for block in event.get("message", {}).get("content", []):
                    if block.get("is_error") and "permission" in str(
                        block.get("content", "")
                    ).lower():
                        denied_detail = trim_text(str(block.get("content", "") or "Permission denied"), 300)
                        denied_name = current_tool
                        # Records are finalized when the tool_use block stops
                        # streaming, before execution; a denial arriving in the
                        # matching tool_result retroactively corrects that record.
                        record_idx = tool_record_index.get(str(block.get("tool_use_id", "") or ""))
                        if record_idx is not None:
                            record = tool_records[record_idx]
                            denied_name = denied_name or record.tool_name
                            tool_records[record_idx] = replace(
                                record, status="denied", output_summary=denied_detail,
                            )
                        elif current_tool:
                            duration_ms: int | None = None
                            if current_tool_started_at is not None:
                                duration_ms = max(0, int((time.monotonic() - current_tool_started_at) * 1000))
                            tool_records.append(
                                ToolExecutionRecord(
                                    tool_name=current_tool,
                                    call_id=f"claude-tool-{tool_counter}",
                                    status="denied",
                                    input_summary=current_tool,
                                    output_summary=denied_detail,
                                    duration_ms=duration_ms,
                                )
                            )
                            tool_counter += 1
                        tool_activity.append("\u26d4 denied")
                        await _emit(Denial(detail=denied_name or ""), force=True)
                        current_tool = ""
                        current_tool_id = ""
                        current_tool_started_at = None

            elif etype == "result":
                if delta_pending:
                    delta_pending = False
                    await _emit_accumulated()
                result_data = event
                result_data["_tool_executions"] = tool_records
                break

        if cancel_fut is not None:
            cancel_fut.cancel()

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
        cancel: asyncio.Event | None = None,
    ) -> tuple[str, dict, int, str, list[ToolExecutionRecord]]:
        """Spawn claude, consume output, return (accumulated_text, result_data, returncode, stderr, tool_executions)."""
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
                self._consume_stream(proc, progress, cancel=cancel),
                timeout=effective_timeout,
            )
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            await stderr_task
            return "", {}, -1, "", []  # sentinel for timeout

        if proc.returncode and proc.returncode != 0:
            detail = self._build_failure_text(stderr, result_data, accumulated)
            log.error("claude error (rc=%d): %s", proc.returncode, trim_text(detail, 300))

        tool_executions = list(result_data.pop("_tool_executions", []) or [])
        return accumulated, result_data, proc.returncode or 0, stderr, tool_executions

    @staticmethod
    def _build_failure_text(stderr: str, result_data: dict, accumulated: str) -> str:
        error_text = str(stderr or "").strip()
        result_text = str(result_data.get("result", "") or "").strip()
        error_kind = str(result_data.get("error", "") or "").strip()
        if result_data.get("errors"):
            joined = " ".join(str(item) for item in result_data["errors"])
            error_text = f"{error_text} {joined}".strip()
        if result_text:
            error_text = f"{error_text} {result_text}".strip()
        if error_kind and error_kind not in error_text:
            error_text = f"{error_text} ({error_kind})".strip()
        if accumulated and accumulated not in error_text:
            error_text = f"{error_text} {accumulated}".strip()
        return error_text

    @staticmethod
    def _is_resume_failure(stderr: str) -> bool:
        """Return True when stderr indicates the --resume target is dead/invalid.

        We look for specific phrases the Claude CLI emits when a session
        cannot be resumed.  A generic API error during a healthy resumed
        session must NOT match — it should be retried on the same session.
        """
        lower = stderr.lower()
        markers = [
            "session not found",
            "invalid session",
            "could not resume",
            "no such session",
            "unable to resume",
            "conversation not found",
            "resume failed",
        ]
        return any(m in lower for m in markers)

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
            os.chmod(mcp_tmp, 0o600)
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
        cancel: asyncio.Event | None = None,
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

        try:
            # Inject credential env
            extra_env = context.credential_env if context else {}

            working_dir = context.working_dir if context else ""
            effective_working_dir = working_dir or str(self.config.working_dir)
            is_resume = self._should_resume(provider_state)
            continuity_updates = self._continuity_updates(provider_state)
            log.info(
                "claude session mode=%s session_id=%s",
                "resume" if is_resume else "fresh",
                str(provider_state.get("session_id", "") or ""),
            )
            timeout_seconds = int(getattr(context, "timeout_seconds", 0) or 0) if context else 0
            accumulated, result_data, rc, stderr, tool_executions = await self._run_process(
                cmd,
                progress,
                timeout=timeout_seconds if timeout_seconds > 0 else None,
                extra_env=extra_env,
                working_dir=working_dir,
                cancel=cancel,
            )
        finally:
            if mcp_tmp:
                try:
                    os.unlink(mcp_tmp)
                except OSError:
                    pass

        # User-initiated cancel: _consume_stream killed the process.
        if cancel is not None and cancel.is_set():
            return RunResult(
                text=accumulated,
                working_dir=effective_working_dir,
                cancelled=True,
                provider_state_updates=continuity_updates,
                tool_executions=tool_executions,
            )

        if rc == -1:
            # A timeout during a resumed session is strong evidence the session
            # is dead — the CLI hangs silently instead of emitting an error.
            # Fresh-session timeouts are just slow API; do NOT reset those.
            return RunResult(
                text="", working_dir=effective_working_dir, timed_out=True, returncode=124,
                resume_failed=is_resume,
                provider_state_updates=continuity_updates,
                tool_executions=tool_executions,
            )

        if rc != 0:
            error_text = self._build_failure_text(stderr, result_data, accumulated)
            detail = trim_text(error_text, 300) if error_text else ""
            text = f"[Claude error (rc={rc})]"
            if detail:
                text = f"{text}\n{detail}"
            return RunResult(
                text=text,
                working_dir=effective_working_dir,
                returncode=rc,
                resume_failed=is_resume and self._is_resume_failure(error_text),
                provider_state_updates=continuity_updates,
                tool_executions=tool_executions,
            )

        final_text = result_data.get("result", accumulated) or accumulated
        denials = result_data.get("permission_denials", [])
        usage = result_data.get("usage", {})
        cached_prompt_tokens = None
        cached_completion_tokens = None
        if isinstance(usage, dict):
            if "cache_read_input_tokens" in usage:
                cached_prompt_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
            elif "cached_input_tokens" in usage:
                cached_prompt_tokens = int(usage.get("cached_input_tokens", 0) or 0)
            if "cache_read_output_tokens" in usage:
                cached_completion_tokens = int(usage.get("cache_read_output_tokens", 0) or 0)
            elif "cached_output_tokens" in usage:
                cached_completion_tokens = int(usage.get("cached_output_tokens", 0) or 0)

        return RunResult(
            text=final_text,
            working_dir=effective_working_dir,
            denials=denials,
            provider_state_updates=continuity_updates,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            cached_prompt_tokens=cached_prompt_tokens,
            cached_completion_tokens=cached_completion_tokens,
            cost_usd=float(result_data.get("total_cost_usd") or 0.0),
            tool_executions=tool_executions,
        )

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: PreflightContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        extra_dirs = context.extra_dirs if context else None
        effective_model = getattr(context, 'effective_model', '') if context else ""
        cmd = self._build_preflight_cmd(prompt, extra_dirs=extra_dirs, effective_model=effective_model)
        system_prompt = ""
        if context and context.system_prompt:
            system_prompt = context.system_prompt
        # Include active skill tool surface in the system prompt for preflight awareness
        if context and context.active_skill_tools_summary:
            cap = f"\n\n## Active skill tools\n\n{context.active_skill_tools_summary}"
            system_prompt = (system_prompt + cap) if system_prompt else cap
        if system_prompt:
            idx = cmd.index("--")
            cmd[idx:idx] = ["--append-system-prompt", system_prompt]

        working_dir = context.working_dir if context else ""
        effective_working_dir = working_dir or str(self.config.working_dir)
        timeout_seconds = int(getattr(context, "timeout_seconds", 0) or 0) if context else 0
        accumulated, result_data, rc, _stderr, _tool_executions = await self._run_process(
            cmd,
            progress,
            timeout=timeout_seconds if timeout_seconds > 0 else 120,
            working_dir=working_dir,
            cancel=cancel,
        )

        if cancel is not None and cancel.is_set():
            return RunResult(text="", working_dir=effective_working_dir, cancelled=True)

        if rc == -1:
            return RunResult(text="", working_dir=effective_working_dir, timed_out=True, returncode=124)

        if rc != 0:
            return RunResult(
                text=f"[Approval check error (rc={rc})]",
                working_dir=effective_working_dir,
                returncode=rc,
            )

        final_text = result_data.get("result", accumulated) or accumulated
        usage = result_data.get("usage", {})
        return RunResult(
            text=final_text,
            working_dir=effective_working_dir,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            cached_prompt_tokens=(
                int(usage.get("cache_read_input_tokens", 0) or 0)
                if isinstance(usage, dict) and "cache_read_input_tokens" in usage
                else (
                    int(usage.get("cached_input_tokens", 0) or 0)
                    if isinstance(usage, dict) and "cached_input_tokens" in usage
                    else None
                )
            ),
            cached_completion_tokens=(
                int(usage.get("cache_read_output_tokens", 0) or 0)
                if isinstance(usage, dict) and "cache_read_output_tokens" in usage
                else (
                    int(usage.get("cached_output_tokens", 0) or 0)
                    if isinstance(usage, dict) and "cached_output_tokens" in usage
                    else None
                )
            ),
            cost_usd=float(result_data.get("total_cost_usd") or 0.0),
        )
