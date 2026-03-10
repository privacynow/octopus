"""Mobile-friendly response summarization and raw-response ring buffer."""

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Responses shorter than this are already mobile-friendly — skip summarization.
_SHORT_THRESHOLD = 800

# Ring buffer capacity per chat.
_RING_SIZE = 50

_SUMMARY_PROMPT = """\
Summarize the following AI assistant response for a mobile chat screen.

Rules:
- Preserve: code snippets, file paths, commands, action items, errors, key decisions.
- Drop: step-by-step reasoning, caveats, verbose explanations, obvious context.
- Target: under 600 characters for plans/reviews/status; code-only responses returned unchanged.
- Output plain markdown. No preamble.

Response to summarize:
"""


# -- Ring buffer ---------------------------------------------------------------

def _ring_dir(data_dir: Path, chat_id: int) -> Path:
    d = data_dir / "raw" / str(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_raw(
    data_dir: Path,
    chat_id: int,
    prompt: str,
    raw_text: str,
    kind: str = "request",
) -> int:
    """Append a conversation turn to the ring buffer, rotating old entries.

    *kind* distinguishes turn types: "request" (normal user->model),
    "approval" (approval plan or approved execution), "system" (bot-
    generated messages worth preserving such as setup or credential flow).
    """
    d = _ring_dir(data_dir, chat_id)
    entries = sorted(d.glob("*.json"))

    # Rotate: delete oldest if at capacity
    while len(entries) >= _RING_SIZE:
        entries.pop(0).unlink(missing_ok=True)

    # Sequential numbering based on latest
    if entries:
        last_num = int(entries[-1].stem)
    else:
        last_num = 0
    new_num = last_num + 1

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "raw_text": raw_text,
        "kind": kind,
    }
    target = d / f"{new_num:06d}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.rename(target)
    return new_num


def load_raw(data_dir: Path, chat_id: int, n: int = 1) -> str | None:
    """Load the Nth most recent raw response (1 = latest). Returns None if not found."""
    d = _ring_dir(data_dir, chat_id)
    entries = sorted(d.glob("*.json"))
    if not entries or n < 1 or n > len(entries):
        return None
    target = entries[-n]
    try:
        return json.loads(target.read_text()).get("raw_text")
    except (json.JSONDecodeError, OSError):
        return None


def load_raw_by_slot(data_dir: Path, chat_id: int, slot: int) -> str | None:
    """Load a raw response by its ring-buffer slot number. Returns None if evicted."""
    target = _ring_dir(data_dir, chat_id) / f"{slot:06d}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text()).get("raw_text")
    except (json.JSONDecodeError, OSError):
        return None



def export_chat_history(data_dir: Path, chat_id: int) -> str | None:
    """Export all ring buffer entries for a chat as plain text.

    Returns formatted text, or None if no history exists.
    """
    d = _ring_dir(data_dir, chat_id)
    entries = sorted(d.glob("*.json"))
    if not entries:
        return None
    parts: list[str] = []
    for entry_path in entries:
        try:
            data = json.loads(entry_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        ts = data.get("timestamp", "unknown")[:19]
        kind = data.get("kind", "request")
        prompt = data.get("prompt", "")
        response = data.get("raw_text", "")
        label = {"approval": "[approval] ", "system": "[system] "}.get(kind, "")
        parts.append(f"--- {label}{ts} ---")
        if prompt:
            parts.append(f"User: {prompt}")
        parts.append(f"Assistant: {response}")
        parts.append("")
    return "\n".join(parts) if parts else None

# -- Summarization -------------------------------------------------------------

async def summarize(text: str, model: str, timeout: int = 30) -> str:
    """Run text through a cheap Claude model for mobile summarization.

    Returns the summary, or the original text on any failure.
    """
    if len(text) <= _SHORT_THRESHOLD:
        return text

    if not shutil.which("claude"):
        return text

    prompt = _SUMMARY_PROMPT + text

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--model", model,
            "--output-format", "text",
            "--", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError, OSError) as e:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        log.warning("summarization failed: %s", e)
        return text

    if proc.returncode != 0:
        log.warning("summarization non-zero rc=%d", proc.returncode)
        return text

    result = stdout.decode("utf-8", errors="replace").strip()
    return result if result else text


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env
