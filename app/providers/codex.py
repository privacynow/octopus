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
from app.providers.base import ProgressSink, RunResult

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
        # Verify the binary actually works
        import subprocess
        try:
            result = subprocess.run(
                ["codex", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"'codex --version' failed (rc={result.returncode}): {result.stderr.strip()[:200]}")
            else:
                log.info("codex version: %s", result.stdout.strip())
        except subprocess.TimeoutExpired:
            errors.append("'codex --version' timed out")
        except OSError as e:
            errors.append(f"'codex' binary not executable: {e}")
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
    def _progress_html(event: dict, is_resume: bool) -> str | None:
        etype = event.get("type")
        if etype == "thread.started":
            tid = html.escape(str(event.get("thread_id", "")))
            label = "Resumed" if is_resume else "Started"
            return f"<i>{label} Codex thread</i>\n<code>{tid}</code>"
        if etype == "turn.started":
            return "<i>Thinking...</i>"

        item = event.get("item", {})
        itype = item.get("type")

        if etype == "item.started" and itype == "command_execution":
            command = html.escape(trim_text(item.get("command", ""), 600))
            return f"<i>Running command:</i>\n<pre>{command}</pre>"

        if etype == "item.completed" and itype == "command_execution":
            command = html.escape(trim_text(item.get("command", ""), 400))
            exit_code = html.escape(str(item.get("exit_code", "?")))
            output = item.get("aggregated_output", "").strip()
            parts = [f"<i>Command finished (exit {exit_code}):</i>\n<pre>{command}</pre>"]
            if output:
                parts.append(f"<i>Output:</i>\n<pre>{html.escape(trim_text(output, 700))}</pre>")
            return "\n\n".join(parts)

        if etype == "item.completed" and itype == "agent_message":
            preview = trim_text(item.get("text", "").strip(), 700)
            if preview:
                return f"<i>Draft reply received:</i>\n\n{md_to_telegram_html(preview)}"
            return "<i>Reply received.</i>"

        return None

    # -- execution ---------------------------------------------------------

    async def _run_cmd(
        self,
        cmd: list[str],
        progress: ProgressSink,
        is_resume: bool = False,
    ) -> RunResult:
        log.info("codex: %s", " ".join(cmd[:-1] + ["<prompt>"]))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.working_dir),
            env=os.environ.copy(),
        )

        thread_id: str | None = None
        messages: list[str] = []

        async def consume_stdout() -> None:
            nonlocal thread_id
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

                if event.get("type") == "thread.started":
                    thread_id = event.get("thread_id") or thread_id

                item = event.get("item", {})
                if (
                    event.get("type") == "item.completed"
                    and item.get("type") == "agent_message"
                ):
                    text = item.get("text", "").strip()
                    if text:
                        messages.append(text)

                html_update = self._progress_html(event, is_resume)
                if html_update:
                    await progress.update(html_update)

            await proc.wait()

        stderr_task = asyncio.create_task(proc.stderr.read())

        try:
            await asyncio.wait_for(consume_stdout(), timeout=self.config.timeout_seconds)
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
            return RunResult(text="", timed_out=True, returncode=124)

        state_updates: dict[str, Any] = {}
        if thread_id:
            state_updates["thread_id"] = thread_id

        reply = "\n\n".join(messages).strip() or "[empty response]"

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
        extra_dirs: list[str] | None = None,
    ) -> RunResult:
        thread_id = provider_state.get("thread_id")
        is_resume = bool(thread_id)

        if thread_id:
            cmd = self._build_resume_cmd(thread_id, prompt, image_paths)
        else:
            cmd = self._build_new_cmd(prompt, image_paths, extra_dirs=extra_dirs)

        return await self._run_cmd(cmd, progress, is_resume=is_resume)

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
    ) -> RunResult:
        cmd = self._build_new_cmd(
            prompt, image_paths, sandbox="read-only", ephemeral=True, safe_mode=True
        )
        return await self._run_cmd(cmd, progress)
