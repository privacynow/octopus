"""Codex CLI provider — codex exec --json, thread-id based sessions."""

import asyncio
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from app.config import BotConfig
from app.formatting import trim_text
from app.provider_auth import auth_artifact_errors, runtime_auth_root
from app.provider_health import command_failure, combined_output, run_health_command
from app.progress import (
    CommandFinish, CommandStart, DraftReply, Liveness, Thinking,
    ToolFinish, ToolStart, render as render_progress,
)
from app.progress import ProgressEvent
from octopus_sdk.providers import (
    FileChangeRecord,
    PreflightContext,
    ProgressSink,
    RunContext,
    RunResult,
    ToolExecutionRecord,
)
from app.providers.codex_security import (
    validate_codex_sandbox,
    validated_codex_config_overrides,
)
from app.subprocess_env import build_subprocess_env

log = logging.getLogger(__name__)

_CODEX_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_HOME")
_PATCH_PATH_RE = re.compile(r"^\*\*\* (Update|Add|Delete) File: (.+)$", re.MULTILINE)


class CodexProvider:
    name = "codex"

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def new_provider_state(self, conversation_key: str) -> dict[str, Any]:
        del conversation_key
        return {"thread_id": None}

    @staticmethod
    def _safe_failure_text(returncode: int) -> str:
        return f"Codex exited with code {returncode} before completing the request."

    def check_health(self) -> list[str]:
        errors: list[str] = []
        if not shutil.which("codex"):
            errors.append("'codex' binary not found in PATH")
        return errors

    async def check_auth_health(self) -> list[str]:
        errors: list[str] = []
        combined = ""
        try:
            returncode, stdout, stderr = await run_health_command(
                "codex",
                "--version",
                timeout=10,
                env=build_subprocess_env(allowed_keys=_CODEX_ENV_KEYS),
            )
            if returncode != 0:
                errors.append(
                    command_failure("'codex --version'", returncode, stdout=stdout, stderr=stderr)
                )
            else:
                log.info("codex version: %s", stdout.strip())
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("'codex --version' timed out")
        except OSError as e:
            errors.append(f"'codex' binary not executable: {e}")
        if errors:
            return errors

        try:
            returncode, stdout, stderr = await run_health_command(
                "codex",
                "login",
                "status",
                timeout=10,
                env=build_subprocess_env(allowed_keys=_CODEX_ENV_KEYS),
            )
            combined = combined_output(stdout, stderr)
            if returncode != 0:
                errors.append(command_failure("'codex login status'", returncode, stdout=stdout, stderr=stderr))
            else:
                if combined:
                    log.info("codex login status: %s", trim_text(combined, 200))
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("'codex login status' timed out")
        except OSError as e:
            errors.append(f"'codex login status' failed: {e}")
        artifact_errors = auth_artifact_errors("codex", runtime_auth_root("codex"))
        if artifact_errors:
            errors.extend(artifact_errors)
        elif not errors and "logged in" not in combined.lower():
            errors.append(
                "Codex login status did not confirm an authenticated session. "
                "Run './octopus' and choose Diagnose -> Provider auth."
            )
        return errors

    async def check_runtime_health(self) -> list[str]:
        errors = await self.check_auth_health()
        if errors:
            return errors
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
            returncode, stdout, stderr = await run_health_command(
                *ping_cmd,
                timeout=30,
                env=build_subprocess_env(allowed_keys=_CODEX_ENV_KEYS),
            )
            if returncode != 0:
                errors.append(
                    command_failure(
                        "Codex runtime probe",
                        returncode,
                        stdout=stdout,
                        stderr=stderr,
                        fallback="Codex runtime probe failed.",
                    )
                )
            else:
                log.info("codex API ping ok")
        except (asyncio.TimeoutError, TimeoutError):
            errors.append("Codex runtime probe timed out (30s)")
        except OSError as e:
            errors.append(f"Codex runtime probe failed: {e}")
        return errors

    # -- command building --------------------------------------------------

    def _common_args(self, effective_model: str = "") -> list[str]:
        args: list[str] = []
        model = effective_model or self.config.model
        if model:
            args.extend(["--model", model])
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

    def _resolved_working_dir(self, working_dir: str | None = None) -> str:
        return str(working_dir or self.config.working_dir)

    def _build_new_cmd(
        self,
        prompt: str,
        image_paths: list[str],
        *,
        sandbox: str | None = None,
        ephemeral: bool = False,
        safe_mode: bool = False,
        extra_dirs: list[str] | None = None,
        effective_model: str = "",
        working_dir: str = "",
    ) -> list[str]:
        cmd = ["codex", "exec", "--json"]
        if safe_mode:
            # Preflight: model and profile only, no --full-auto or --dangerous
            model = effective_model or self.config.model
            if model:
                cmd.extend(["--model", model])
            if self.config.codex_profile:
                cmd.extend(["--profile", self.config.codex_profile])
        else:
            cmd.extend(self._common_args(effective_model))
        cmd.extend(["--sandbox", sandbox or self.config.codex_sandbox])
        if self.config.codex_skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        if ephemeral:
            cmd.append("--ephemeral")
        cmd.extend(self._extra_dir_args(extra_dirs))
        for p in image_paths:
            cmd.extend(["-i", p])
        cmd.extend(["-C", self._resolved_working_dir(working_dir), prompt])
        return cmd

    def _build_resume_cmd(
        self,
        thread_id: str,
        prompt: str,
        image_paths: list[str],
        *,
        ephemeral: bool = False,
        effective_model: str = "",
        working_dir: str = "",
    ) -> list[str]:
        # NOTE: codex exec resume does NOT support --add-dir (verified on
        # codex-cli 0.116.0). Extra dirs are only passed on initial exec.
        # Working root still matters for workspace-write sandboxing, so pass
        # it via the global -C flag that applies to all codex subcommands.
        cmd = ["codex", "-C", self._resolved_working_dir(working_dir), "exec", "resume", "--json"]
        cmd.extend(self._common_args(effective_model))
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
    def _parse_arguments_object(cls, arguments: Any) -> dict[str, Any]:
        parsed = arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @classmethod
    def _tool_input_summary(cls, raw_name: str, arguments: Any) -> str:
        command = cls._parse_command(arguments)
        if command:
            return trim_text(command, 300)
        parsed = cls._parse_arguments_object(arguments)
        if parsed:
            try:
                return trim_text(json.dumps(parsed, sort_keys=True), 300)
            except TypeError:
                pass
        return raw_name or "tool call"

    @classmethod
    def _tool_file_changes(cls, raw_name: str, arguments: Any) -> tuple[FileChangeRecord, ...]:
        parsed = cls._parse_arguments_object(arguments)
        normalized = cls._normalize_type(raw_name)

        def _path(*keys: str) -> str:
            for key in keys:
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        if normalized in {"write_file", "edit_file", "str_replace_editor", "replace_file"}:
            path = _path("path", "file_path", "file")
            if path:
                return (FileChangeRecord(path=path, change_type="modified", summary="Updated file"),)
        if normalized in {"create_file"}:
            path = _path("path", "file_path", "file")
            if path:
                return (FileChangeRecord(path=path, change_type="created", summary="Created file"),)
        if normalized in {"delete_file", "remove_file"}:
            path = _path("path", "file_path", "file")
            if path:
                return (FileChangeRecord(path=path, change_type="deleted", summary="Deleted file"),)
        if normalized in {"rename_file", "move_file"}:
            src = _path("path", "src", "source_path", "old_path")
            dst = _path("dest", "destination_path", "new_path", "target_path")
            if src and dst:
                return (FileChangeRecord(path=src, change_type="renamed", summary=f"Renamed to {dst}"),)
        if normalized == "apply_patch":
            patch_text = parsed.get("patch")
            if isinstance(patch_text, str) and patch_text.strip():
                changes: list[FileChangeRecord] = []
                for change_type, path in _PATCH_PATH_RE.findall(patch_text):
                    mapped = {
                        "Update": "modified",
                        "Add": "created",
                        "Delete": "deleted",
                    }.get(change_type, "modified")
                    changes.append(
                        FileChangeRecord(
                            path=path.strip(),
                            change_type=mapped,
                            summary=f"{change_type.lower()} file via patch",
                        )
                    )
                return tuple(changes)
        return ()

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
    def _map_event(
        cls,
        event: dict[str, Any],
        is_resume: bool,
        tool_calls: dict[str, dict[str, str]] | None = None,
    ) -> ProgressEvent | None:
        """Map a raw Codex CLI event to a normalized ProgressEvent.

        Returns None for events that should not produce visible output
        (internal IDs, session meta, etc.).
        """
        etype = cls._normalize_type(event.get("type"))
        if etype in {"thread_started", "session_configured"}:
            tid = cls._extract_thread_id(event)
            if tid:
                log.debug("Codex thread: %s", tid)
            return None
        if etype == "session_meta":
            tid = event.get("payload", {}).get("id")
            if tid:
                log.debug("Codex session: %s", tid)
            return None
        if etype in {"turn_started", "task_started"}:
            return Thinking()

        item = event.get("item", {})
        itype = cls._normalize_type(item.get("type")) if isinstance(item, dict) else ""

        if etype == "item_started" and itype == "command_execution":
            return CommandStart(command=cls._trimmed_text(item.get("command")))

        if etype == "item_completed" and itype == "command_execution":
            return CommandFinish(
                command=cls._trimmed_text(item.get("command")),
                output_preview=cls._trimmed_text(item.get("aggregated_output")),
                exit_code=item.get("exit_code"),
            )

        if etype == "item_completed" and itype == "agent_message":
            text = cls._trimmed_text(item.get("text"))
            return DraftReply(text=text) if text else None

        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None

        ptype = cls._normalize_type(payload.get("type"))

        if ptype in {"task_started", "turn_started", "reasoning", "agent_reasoning", "agent_reasoning_delta"}:
            return Thinking()

        if etype == "event_msg" and ptype == "agent_message":
            text = cls._trimmed_text(payload.get("message"))
            return DraftReply(text=text) if text else None

        if etype == "event_msg" and ptype == "session_configured":
            tid = cls._extract_thread_id(event)
            if tid:
                log.debug("Codex session configured: %s", tid)
            return None

        if etype == "event_msg" and ptype == "exec_command_begin":
            command = (
                cls._trimmed_text(payload.get("command"))
                or cls._trimmed_text(payload.get("cmd"))
                or cls._parse_command(payload.get("arguments"))
            )
            return CommandStart(command=command)

        if etype == "event_msg" and ptype == "exec_command_end":
            command = (
                cls._trimmed_text(payload.get("command"))
                or cls._trimmed_text(payload.get("cmd"))
                or cls._parse_command(payload.get("arguments"))
            )
            return CommandFinish(
                command=command,
                output_preview=cls._trimmed_text(payload.get("output")),
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
                return CommandStart(command=command)
            return ToolStart(name=raw_name)

        if etype == "response_item" and ptype == "function_call_output":
            call_id = str(payload.get("call_id") or "")
            call_info = tool_calls.pop(call_id, {}) if tool_calls is not None and call_id else {}
            raw_name = call_info.get("name", "")
            output = cls._trimmed_text(payload.get("output"))
            if cls._normalize_type(raw_name) == "exec_command":
                return CommandFinish(command=call_info.get("command", ""), output_preview=output)
            if raw_name:
                return ToolFinish(name=raw_name, output_preview=output)
            # Anonymous tool output — render as ToolFinish with empty name
            if output:
                return ToolFinish(name="", output_preview=output)

        if etype == "response_item" and ptype == "message":
            text = cls._assistant_output_text(payload)
            phase = cls._normalize_type(payload.get("phase"))
            if text and phase not in {"final_answer", "task_complete"}:
                return DraftReply(text=text)

        return None

    # -- execution ---------------------------------------------------------

    async def _run_cmd(
        self,
        cmd: list[str],
        progress: ProgressSink,
        is_resume: bool = False,
        extra_env: dict[str, str] | None = None,
        working_dir: str = "",
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        log.info("codex: %s", " ".join(cmd[:-1] + ["<prompt>"]))

        env = build_subprocess_env(
            allowed_keys=_CODEX_ENV_KEYS,
            extra_env=extra_env,
        )

        cwd = working_dir or str(self.config.working_dir)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            limit=1024 * 1024,
        )

        thread_id: str | None = None
        messages: list[str] = []
        final_text = ""
        draft_text = ""
        tool_calls: dict[str, dict[str, str]] = {}
        pending_tool_records: dict[str, dict[str, Any]] = {}
        tool_records: list[ToolExecutionRecord] = []
        tool_counter = 0
        usage_input = 0
        usage_output = 0
        cached_usage_input: int | None = None
        cached_usage_output: int | None = None

        def append_unique(values: list[str], value: str) -> None:
            if value and value not in values:
                values.append(value)

        async def consume_stdout() -> None:
            nonlocal thread_id, final_text, draft_text
            nonlocal usage_input, usage_output
            nonlocal cached_usage_input, cached_usage_output
            while True:
                read_coro = proc.stdout.readline()
                if cancel is not None:
                    cancel_fut = asyncio.ensure_future(cancel.wait())
                    done, pending = await asyncio.wait(
                        [asyncio.ensure_future(read_coro), cancel_fut],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for fut in pending:
                        fut.cancel()
                    if cancel.is_set():
                        proc.kill()
                        await proc.wait()
                        return
                    raw_line = done.pop().result()
                else:
                    raw_line = await read_coro
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = self._normalize_type(event.get("type"))
                payload = event.get("payload")
                if isinstance(payload, dict):
                    ptype = self._normalize_type(payload.get("type"))
                    if etype == "response_item" and ptype in {"function_call", "custom_tool_call"}:
                        raw_name = str(payload.get("name") or "tool")
                        call_id = str(payload.get("call_id") or f"tool-{tool_counter}")
                        if not payload.get("call_id"):
                            tool_counter += 1
                        arguments = (
                            payload.get("arguments")
                            if ptype == "function_call"
                            else payload.get("input")
                        )
                        pending_tool_records[call_id] = {
                            "tool_name": raw_name,
                            "call_id": call_id,
                            "input_summary": self._tool_input_summary(raw_name, arguments),
                            "file_changes": self._tool_file_changes(raw_name, arguments),
                            "started_at": time.monotonic(),
                        }
                    elif etype == "response_item" and ptype == "function_call_output":
                        call_id = str(payload.get("call_id") or "")
                        pending = pending_tool_records.pop(call_id, None)
                        if pending is not None:
                            output = self._trimmed_text(payload.get("output")) or "completed"
                            duration_ms: int | None = None
                            started_at = pending.get("started_at")
                            if isinstance(started_at, (int, float)):
                                duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
                            tool_records.append(
                                ToolExecutionRecord(
                                    tool_name=str(pending["tool_name"]),
                                    call_id=str(pending["call_id"]),
                                    status="completed",
                                    input_summary=str(pending["input_summary"]),
                                    output_summary=trim_text(output, 300),
                                    duration_ms=duration_ms,
                                    file_changes=tuple(pending["file_changes"]),
                                )
                            )

                msg = event.get("msg")
                if isinstance(msg, dict) and msg.get("type") == "token_count":
                    total = msg.get("info", {}).get("total_token_usage", {})
                    usage_input = int(total.get("input_tokens", 0) or 0)
                    usage_output = int(total.get("output_tokens", 0) or 0)
                    if "cached_input_tokens" in total:
                        cached_usage_input = int(total.get("cached_input_tokens", 0) or 0)
                    if "cached_output_tokens" in total:
                        cached_usage_output = int(total.get("cached_output_tokens", 0) or 0)
                elif etype == "turn_completed":
                    usage = event.get("usage", {})
                    if isinstance(usage, dict):
                        usage_input = int(usage.get("input_tokens", 0) or 0)
                        usage_output = int(usage.get("output_tokens", 0) or 0)
                        if "cached_input_tokens" in usage:
                            cached_usage_input = int(usage.get("cached_input_tokens", 0) or 0)
                        if "cached_output_tokens" in usage:
                            cached_usage_output = int(usage.get("cached_output_tokens", 0) or 0)

                thread_id = self._extract_thread_id(event) or thread_id
                if self._normalize_type(event.get("type")) == "session_meta":
                    thread_id = event.get("payload", {}).get("id") or thread_id

                text, phase = self._extract_assistant_text(event)
                if text:
                    # Signal that visible content is streaming — stops heartbeat.
                    # Fires on any text (including draft/commentary) since those
                    # produce visible progress updates.
                    cs = getattr(progress, "content_started", None)
                    if cs and not cs.is_set():
                        cs.set()
                    if phase == "commentary":
                        draft_text = text
                    else:
                        append_unique(messages, text)
                        final_text = text

                evt = self._map_event(event, is_resume, tool_calls)
                if evt is not None:
                    rendered = render_progress(evt)
                    if rendered:
                        await progress.update(rendered)

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
                await progress.update(render_progress(Liveness(detail="Still working — this may take a moment...")))
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

        # User-initiated cancel: consume_stdout killed the process.
        if cancel is not None and cancel.is_set():
            state_updates: dict[str, Any] = {}
            if thread_id:
                state_updates["thread_id"] = thread_id
            return RunResult(text=final_text or "", cancelled=True,
                             provider_state_updates=state_updates,
                             tool_executions=tool_records)

        state_updates: dict[str, Any] = {}
        if thread_id:
            state_updates["thread_id"] = thread_id

        reply = final_text or "\n\n".join(messages).strip() or draft_text or "[empty response]"

        if proc.returncode and proc.returncode != 0:
            log.warning("codex run failed with rc=%d", proc.returncode)
            return RunResult(
                text=self._safe_failure_text(proc.returncode),
                returncode=proc.returncode,
                provider_state_updates=state_updates,
                tool_executions=tool_records,
            )

        return RunResult(
            text=reply,
            provider_state_updates=state_updates,
            prompt_tokens=usage_input,
            completion_tokens=usage_output,
            cached_prompt_tokens=cached_usage_input,
            cached_completion_tokens=cached_usage_output,
            tool_executions=tool_records,
        )

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

        thread_id = provider_state.get("thread_id")
        is_resume = bool(thread_id)

        # Prepend system prompt to user prompt for Codex
        effective_prompt = prompt
        if context and context.system_prompt:
            effective_prompt = context.system_prompt + "\n\n---\n\n" + prompt

        # Apply provider_config: sandbox override, config overrides.
        # inspect mode is authoritative — skill/provider configs cannot weaken it.
        sandbox_override = None
        inspect_mode = context and context.file_policy == "inspect"
        if inspect_mode:
            sandbox_override = "read-only"
        elif context and context.provider_config:
            pc = context.provider_config
            if "sandbox" in pc:
                raw_sandbox = str(pc["sandbox"])
                try:
                    sandbox_override = validate_codex_sandbox(raw_sandbox)
                except ValueError:
                    log.warning(
                        "Rejected invalid Codex sandbox override %r; using configured default",
                        raw_sandbox,
                    )
                    sandbox_override = None

        effective_model = context.effective_model if context else ""
        working_dir = context.working_dir if context else ""
        if thread_id:
            cmd = self._build_resume_cmd(
                thread_id,
                effective_prompt,
                image_paths,
                effective_model=effective_model,
                working_dir=working_dir,
            )
        else:
            cmd = self._build_new_cmd(
                effective_prompt,
                image_paths,
                extra_dirs=extra_dirs,
                sandbox=sandbox_override,
                effective_model=effective_model,
                working_dir=working_dir,
            )

        # Preserve resume semantics after a bot-level approval. Changing a resumed
        # thread to --dangerously-bypass-approvals-and-sandbox can break continuity.
        # Fresh execs only need the dangerous flag when full-auto is not already
        # enabled; codex-cli 0.111.0 rejects the combination of both flags.
        if context and context.skip_permissions and not is_resume:
            if (
                "--dangerously-bypass-approvals-and-sandbox" not in cmd
                and "--full-auto" not in cmd
            ):
                cmd.insert(3, "--dangerously-bypass-approvals-and-sandbox")

        # Inject config_overrides as -c flags
        if context and context.provider_config:
            for override in validated_codex_config_overrides(
                context.provider_config.get("config_overrides", []),
                logger=log,
            ):
                cmd.insert(-1, "-c")  # Insert before the prompt (last arg)
                cmd.insert(-1, override)

        extra_env = context.credential_env if context else {}
        return await self._run_cmd(cmd, progress, is_resume=is_resume, extra_env=extra_env, working_dir=working_dir, cancel=cancel)

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: PreflightContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        system_prompt = ""
        if context and context.system_prompt:
            system_prompt = context.system_prompt
        if context and context.capability_summary:
            cap = f"\n\n## Active skill tool surface\n\n{context.capability_summary}"
            system_prompt = (system_prompt + cap) if system_prompt else cap
        effective_prompt = prompt
        if system_prompt:
            effective_prompt = system_prompt + "\n\n---\n\n" + prompt
        extra_dirs = context.extra_dirs if context else None
        effective_model = getattr(context, 'effective_model', '') if context else ""
        cmd = self._build_new_cmd(
            effective_prompt, image_paths, sandbox="read-only", ephemeral=True, safe_mode=True,
            extra_dirs=extra_dirs, effective_model=effective_model, working_dir=working_dir,
        )
        return await self._run_cmd(cmd, progress, working_dir=working_dir, cancel=cancel)
