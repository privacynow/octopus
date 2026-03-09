"""Codex CLI provider — codex exec --json, thread-id based sessions."""

import asyncio
import html
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.config import BotConfig
from app.formatting import md_to_telegram_html, trim_text
from app.providers.base import PreflightContext, ProgressSink, RunContext, RunResult

log = logging.getLogger(__name__)


class CodexProvider:
    name = "codex"

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def new_provider_state(self) -> dict[str, Any]:
        return {"thread_id": None}

    def check_health(self) -> list[str]:
        errors: list[str] = []
        if not shutil.which("codex"):
            errors.append("'codex' binary not found in PATH")
        return errors

    async def check_runtime_health(self) -> list[str]:
        errors: list[str] = []
        # Version check
        try:
            proc = await asyncio.create_subprocess_exec(
                "codex", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                errors.append(f"'codex --version' failed (rc={proc.returncode}): {stderr.decode()[:200]}")
            else:
                log.info("codex version: %s", stdout.decode().strip())
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("'codex --version' timed out")
        except OSError as e:
            errors.append(f"'codex' binary not executable: {e}")
        # API ping (mirrors real execution flags)
        if not errors:
            try:
                ping_cmd = ["codex", "exec", "--json", "--ephemeral",
                            "--sandbox", self.config.codex_sandbox]
                if self.config.codex_skip_git_repo_check:
                    ping_cmd.append("--skip-git-repo-check")
                if self.config.model:
                    ping_cmd.extend(["--model", self.config.model])
                if self.config.codex_profile:
                    ping_cmd.extend(["--profile", self.config.codex_profile])
                ping_cmd.extend(["-C", str(self.config.working_dir), "reply with ok"])
                proc = await asyncio.create_subprocess_exec(
                    *ping_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    errors.append(f"API ping failed (rc={proc.returncode}): {stderr.decode()[:200]}")
                else:
                    log.info("codex API ping ok")
            except (asyncio.TimeoutError, TimeoutError):
                errors.append("API ping timed out (30s)")
            except OSError as e:
                errors.append(f"API ping error: {e}")
        return errors

    # -- command building --------------------------------------------------

    def _common_args(self) -> list[str]:
        args: list[str] = []
        if self.config.model:
            args.extend(["--model", self.config.model])
        if self.config.codex_profile:
            args.extend(["--profile", self.config.codex_profile])
        if self.config.codex_dangerous:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.config.codex_full_auto:
            args.append("--full-auto")
        return args

    def _extra_dir_args(self, extra_dirs: list[str] | None = None) -> list[str]:
        args: list[str] = []
        for d in self.config.extra_dirs:
            args.extend(["--add-dir", str(d)])
        for d in extra_dirs or []:
            args.extend(["--add-dir", d])
        return args

    def _build_new_cmd(
        self,
        prompt: str,
        image_paths: list[str],
        *,
        sandbox: str | None = None,
        ephemeral: bool = False,
        safe_mode: bool = False,
        extra_dirs: list[str] | None = None,
    ) -> list[str]:
        cmd = ["codex", "exec", "--json"]
        if safe_mode:
            # Preflight: model and profile only, no --full-auto or --dangerous
            if self.config.model:
                cmd.extend(["--model", self.config.model])
            if self.config.codex_profile:
                cmd.extend(["--profile", self.config.codex_profile])
        else:
            cmd.extend(self._common_args())
        cmd.extend(["--sandbox", sandbox or self.config.codex_sandbox])
        if self.config.codex_skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        if ephemeral:
            cmd.append("--ephemeral")
        cmd.extend(self._extra_dir_args(extra_dirs))
        for p in image_paths:
            cmd.extend(["-i", p])
        cmd.extend(["-C", str(self.config.working_dir), prompt])
        return cmd

    def _build_resume_cmd(
        self,
        thread_id: str,
        prompt: str,
        image_paths: list[str],
        *,
        ephemeral: bool = False,
    ) -> list[str]:
        # NOTE: codex exec resume does NOT support --add-dir (verified on
        # codex-cli 0.111.0).  Extra dirs are only passed on initial exec.
        cmd = ["codex", "exec", "resume", "--json"]
        cmd.extend(self._common_args())
        if self.config.codex_skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        if ephemeral:
            cmd.append("--ephemeral")
        for p in image_paths:
            cmd.extend(["-i", p])
        cmd.extend([thread_id, prompt])
        return cmd

    # -- event parsing & progress ------------------------------------------

    @staticmethod
    def _normalize_type(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.replace(".", "_").replace("/", "_").lower()

    @staticmethod
    def _trimmed_text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _extract_thread_id(cls, event: dict[str, Any]) -> str | None:
        payload = event.get("payload")
        candidates: list[dict[str, Any]] = [event]
        if isinstance(payload, dict):
            candidates.append(payload)
        for source in candidates:
            for key in ("thread_id", "new_thread_id", "assigned_thread_id"):
                value = source.get(key)
                if value:
                    return str(value)
        return None

    @classmethod
    def _assistant_output_text(cls, payload: dict[str, Any]) -> str:
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            return ""
        parts: list[str] = []
        for item in payload.get("content", []):
            if not isinstance(item, dict):
                continue
            if cls._normalize_type(item.get("type")) in {"output_text", "text"}:
                text = cls._trimmed_text(item.get("text"))
                if text:
                    parts.append(text)
        return "\n\n".join(parts).strip()

    @classmethod
    def _parse_command(cls, arguments: Any) -> str:
        parsed = arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return ""
        if not isinstance(parsed, dict):
            return ""
        for key in ("cmd", "command"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return " ".join(str(part) for part in value)
        return ""

    @classmethod
    def _extract_assistant_text(cls, event: dict[str, Any]) -> tuple[str | None, str]:
        etype = cls._normalize_type(event.get("type"))
        item = event.get("item")
        if etype == "item_completed" and isinstance(item, dict):
            if cls._normalize_type(item.get("type")) == "agent_message":
                text = cls._trimmed_text(item.get("text"))
                return (text or None, cls._normalize_type(item.get("phase")))

        payload = event.get("payload")
        if not isinstance(payload, dict):
            return (None, "")
        ptype = cls._normalize_type(payload.get("type"))

        if etype == "event_msg" and ptype == "agent_message":
            text = cls._trimmed_text(payload.get("message"))
            phase = cls._normalize_type(payload.get("phase")) or "commentary"
            return (text or None, phase)

        if etype == "response_item" and ptype == "message" and payload.get("role") == "assistant":
            text = cls._assistant_output_text(payload)
            return (text or None, cls._normalize_type(payload.get("phase")))

        if etype == "event_msg" and ptype == "task_complete":
            text = cls._trimmed_text(payload.get("last_agent_message"))
            return (text or None, "task_complete")

        return (None, "")

    @classmethod
    def _render_agent_preview(cls, text: str) -> str:
        preview = trim_text(text.strip(), 700)
        if preview:
            return f"<i>Draft reply received:</i>\n\n{md_to_telegram_html(preview)}"
        return "<i>Reply received.</i>"

    @classmethod
    def _render_command_start(cls, command: str) -> str:
        if command:
            return f"<i>Running command:</i>\n<pre>{html.escape(trim_text(command, 600))}</pre>"
        return "<i>Running command...</i>"

    @classmethod
    def _render_command_finish(
        cls,
        command: str,
        *,
        output: str = "",
        exit_code: Any = None,
    ) -> str:
        if exit_code is None:
            parts = ["<i>Command finished.</i>"]
        else:
            parts = [f"<i>Command finished (exit {html.escape(str(exit_code))}):</i>"]
        if command:
            parts[0] += f"\n<pre>{html.escape(trim_text(command, 400))}</pre>"
        if output:
            parts.append(f"<i>Output:</i>\n<pre>{html.escape(trim_text(output, 700))}</pre>")
        return "\n\n".join(parts)

    @classmethod
    def _progress_html(
        cls,
        event: dict[str, Any],
        is_resume: bool,
        tool_calls: dict[str, dict[str, str]] | None = None,
    ) -> str | None:
        etype = cls._normalize_type(event.get("type"))
        if etype in {"thread_started", "session_configured"}:
            tid = html.escape(str(cls._extract_thread_id(event) or ""))
            label = "Resumed" if is_resume else "Started"
            if tid:
                return f"<i>{label} Codex thread</i>\n<code>{tid}</code>"
            return f"<i>{label} Codex thread</i>"
        if etype == "session_meta":
            tid = html.escape(str(event.get("payload", {}).get("id", "")))
            if tid:
                label = "Resumed" if is_resume else "Started"
                return f"<i>{label} Codex thread</i>\n<code>{tid}</code>"
            return None
        if etype in {"turn_started", "task_started"}:
            return "<i>Thinking...</i>"

        item = event.get("item", {})
        itype = cls._normalize_type(item.get("type")) if isinstance(item, dict) else ""

        if etype == "item_started" and itype == "command_execution":
            return cls._render_command_start(cls._trimmed_text(item.get("command")))

        if etype == "item_completed" and itype == "command_execution":
            return cls._render_command_finish(
                cls._trimmed_text(item.get("command")),
                output=cls._trimmed_text(item.get("aggregated_output")),
                exit_code=item.get("exit_code"),
            )

        if etype == "item_completed" and itype == "agent_message":
            return cls._render_agent_preview(cls._trimmed_text(item.get("text")))

        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None

        ptype = cls._normalize_type(payload.get("type"))

        if ptype in {"task_started", "turn_started", "reasoning", "agent_reasoning", "agent_reasoning_delta"}:
            return "<i>Thinking...</i>"

        if etype == "event_msg" and ptype == "agent_message":
            return cls._render_agent_preview(cls._trimmed_text(payload.get("message")))

        if etype == "event_msg" and ptype == "session_configured":
            tid = cls._extract_thread_id(event)
            if tid:
                label = "Resumed" if is_resume else "Started"
                return f"<i>{label} Codex thread</i>\n<code>{html.escape(tid)}</code>"
            return None

        if etype == "event_msg" and ptype == "exec_command_begin":
            command = (
                cls._trimmed_text(payload.get("command"))
                or cls._trimmed_text(payload.get("cmd"))
                or cls._parse_command(payload.get("arguments"))
            )
            return cls._render_command_start(command)

        if etype == "event_msg" and ptype == "exec_command_end":
            command = (
                cls._trimmed_text(payload.get("command"))
                or cls._trimmed_text(payload.get("cmd"))
                or cls._parse_command(payload.get("arguments"))
            )
            return cls._render_command_finish(
                command,
                output=cls._trimmed_text(payload.get("output")),
                exit_code=payload.get("exit_code"),
            )

        if etype == "response_item" and ptype in {"function_call", "custom_tool_call"}:
            raw_name = str(payload.get("name") or "tool")
            name = cls._normalize_type(raw_name)
            call_id = str(payload.get("call_id") or "")
            arguments = payload.get("arguments") if ptype == "function_call" else payload.get("input")
            command = cls._parse_command(arguments)
            if tool_calls is not None and call_id:
                tool_calls[call_id] = {"name": raw_name, "command": command}
            if name == "exec_command":
                return cls._render_command_start(command)
            return f"<i>Using tool:</i>\n<code>{html.escape(trim_text(raw_name, 120))}</code>"

        if etype == "response_item" and ptype == "function_call_output":
            call_id = str(payload.get("call_id") or "")
            call_info = tool_calls.pop(call_id, {}) if tool_calls is not None and call_id else {}
            raw_name = call_info.get("name", "")
            output = cls._trimmed_text(payload.get("output"))
            if cls._normalize_type(raw_name) == "exec_command":
                return cls._render_command_finish(call_info.get("command", ""), output=output)
            if raw_name:
                parts = [f"<i>Tool finished:</i>\n<code>{html.escape(trim_text(raw_name, 120))}</code>"]
                if output:
                    parts.append(f"<i>Output:</i>\n<pre>{html.escape(trim_text(output, 700))}</pre>")
                return "\n\n".join(parts)
            if output:
                return f"<i>Tool output:</i>\n<pre>{html.escape(trim_text(output, 700))}</pre>"

        if etype == "response_item" and ptype == "message":
            text = cls._assistant_output_text(payload)
            phase = cls._normalize_type(payload.get("phase"))
            if text and phase not in {"final_answer", "task_complete"}:
                return cls._render_agent_preview(text)

        return None

    # -- execution ---------------------------------------------------------

    async def _run_cmd(
        self,
        cmd: list[str],
        progress: ProgressSink,
        is_resume: bool = False,
        extra_env: dict[str, str] | None = None,
    ) -> RunResult:
        log.info("codex: %s", " ".join(cmd[:-1] + ["<prompt>"]))

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.working_dir),
            env=env,
        )

        thread_id: str | None = None
        messages: list[str] = []
        final_text = ""
        draft_text = ""
        tool_calls: dict[str, dict[str, str]] = {}

        def append_unique(values: list[str], value: str) -> None:
            if value and value not in values:
                values.append(value)

        async def consume_stdout() -> None:
            nonlocal thread_id, final_text, draft_text
            while True:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                thread_id = self._extract_thread_id(event) or thread_id
                if self._normalize_type(event.get("type")) == "session_meta":
                    thread_id = event.get("payload", {}).get("id") or thread_id

                text, phase = self._extract_assistant_text(event)
                if text:
                    if phase == "commentary":
                        draft_text = text
                    else:
                        append_unique(messages, text)
                        final_text = text

                html_update = self._progress_html(event, is_resume, tool_calls)
                if html_update:
                    await progress.update(html_update)

            await proc.wait()

        stderr_task = asyncio.create_task(proc.stderr.read())
        stdout_task = asyncio.create_task(consume_stdout())

        try:
            # shield() keeps the reader alive if the first timeout fires,
            # so we can extend the deadline when codex is compacting context.
            await asyncio.wait_for(
                asyncio.shield(stdout_task), timeout=self.config.timeout_seconds,
            )
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, TimeoutError):
            if is_resume and proc.returncode is None:
                # Codex is still running — likely compacting context.
                # Warn the user and give it one more timeout period.
                log.info("codex resume still running after %ds — extending for compaction",
                         self.config.timeout_seconds)
                await progress.update("<i>Still working — possible context compaction…</i>")
                try:
                    await asyncio.wait_for(stdout_task, timeout=self.config.timeout_seconds)
                    stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
                except (asyncio.TimeoutError, TimeoutError):
                    proc.kill()
                    await proc.wait()
                    stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
                    return RunResult(text="", timed_out=True, returncode=124)
            else:
                stdout_task.cancel()
                proc.kill()
                await proc.wait()
                stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
                return RunResult(text="", timed_out=True, returncode=124)

        state_updates: dict[str, Any] = {}
        if thread_id:
            state_updates["thread_id"] = thread_id

        reply = final_text or "\n\n".join(messages).strip() or draft_text or "[empty response]"

        if proc.returncode and proc.returncode != 0:
            return RunResult(
                text=f"[Codex error: {trim_text(stderr or 'unknown', 2000)}]",
                returncode=proc.returncode,
                provider_state_updates=state_updates,
            )

        return RunResult(
            text=reply,
            provider_state_updates=state_updates,
        )

    async def run(
        self,
        provider_state: dict[str, Any],
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: RunContext | None = None,
    ) -> RunResult:
        extra_dirs = context.extra_dirs if context else None

        thread_id = provider_state.get("thread_id")
        is_resume = bool(thread_id)

        # Prepend system prompt to user prompt for Codex
        effective_prompt = prompt
        if context and context.system_prompt:
            effective_prompt = context.system_prompt + "\n\n---\n\n" + prompt

        # Apply provider_config: sandbox override, config overrides
        sandbox_override = None
        if context and context.provider_config:
            pc = context.provider_config
            if "sandbox" in pc:
                sandbox_override = pc["sandbox"]

        if thread_id:
            cmd = self._build_resume_cmd(thread_id, effective_prompt, image_paths)
        else:
            cmd = self._build_new_cmd(
                effective_prompt, image_paths, extra_dirs=extra_dirs,
                sandbox=sandbox_override,
            )

        # Preserve resume semantics after a bot-level approval. Changing a resumed
        # thread to --dangerously-bypass-approvals-and-sandbox can break continuity.
        # Retry flows that truly need permission bypass already clear thread_id and
        # therefore come through here as a fresh exec.
        if context and context.skip_permissions and not is_resume:
            if "--dangerously-bypass-approvals-and-sandbox" not in cmd:
                cmd.insert(3, "--dangerously-bypass-approvals-and-sandbox")

        # Inject config_overrides as -c flags
        if context and context.provider_config:
            for override in context.provider_config.get("config_overrides", []):
                cmd.insert(-1, "-c")  # Insert before the prompt (last arg)
                cmd.insert(-1, override)

        extra_env = context.credential_env if context else {}
        return await self._run_cmd(cmd, progress, is_resume=is_resume, extra_env=extra_env)

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: PreflightContext | None = None,
    ) -> RunResult:
        system_prompt = ""
        if context and context.system_prompt:
            system_prompt = context.system_prompt
        if context and context.capability_summary:
            cap = f"\n\n## Available capabilities\n\n{context.capability_summary}"
            system_prompt = (system_prompt + cap) if system_prompt else cap
        effective_prompt = prompt
        if system_prompt:
            effective_prompt = system_prompt + "\n\n---\n\n" + prompt
        extra_dirs = context.extra_dirs if context else None
        cmd = self._build_new_cmd(
            effective_prompt, image_paths, sandbox="read-only", ephemeral=True, safe_mode=True,
            extra_dirs=extra_dirs,
        )
        return await self._run_cmd(cmd, progress)
