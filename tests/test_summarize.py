"""Tests for summarize.py — ring buffer and summarization."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.summarize import _RING_SIZE, _SHORT_THRESHOLD, export_chat_history, load_raw, save_raw, summarize
from tests.support.assertions import Checks

checks = Checks()
check = checks.check
check_contains = checks.check_contains


# -- ring buffer --
print("\n=== ring buffer ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)

    # Empty buffer
    check("load empty returns None", load_raw(data_dir, 1), None)

    # Save and load
    save_raw(data_dir, 1, "prompt one", "response one")
    check("load latest", load_raw(data_dir, 1, 1), "response one")

    save_raw(data_dir, 1, "prompt two", "response two")
    check("load latest after two", load_raw(data_dir, 1, 1), "response two")
    check("load second most recent", load_raw(data_dir, 1, 2), "response one")

    # Out of range
    check("load out of range", load_raw(data_dir, 1, 99), None)
    check("load zero", load_raw(data_dir, 1, 0), None)

    # Different chat IDs are isolated
    save_raw(data_dir, 2, "other chat", "other response")
    check("chat isolation", load_raw(data_dir, 2, 1), "other response")
    check("original chat unchanged", load_raw(data_dir, 1, 1), "response two")

# -- ring buffer rotation --
print("\n=== ring buffer rotation ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)

    # Fill beyond capacity
    for i in range(_RING_SIZE + 3):
        save_raw(data_dir, 1, f"prompt {i}", f"response {i}")

    # Should only have _RING_SIZE entries
    ring_dir = data_dir / "raw" / "1"
    entries = list(ring_dir.glob("*.json"))
    check("rotation keeps max entries", len(entries), _RING_SIZE)

    # Latest should be the last one saved
    check("latest after rotation", load_raw(data_dir, 1, 1), f"response {_RING_SIZE + 2}")

    # Oldest available should be offset by 3
    oldest = load_raw(data_dir, 1, _RING_SIZE)
    check("oldest after rotation", oldest, f"response 3")

# -- ring buffer JSON format --
print("\n=== ring buffer JSON format ===")

with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    save_raw(data_dir, 1, "test prompt preview", "test raw text")
    ring_dir = data_dir / "raw" / "1"
    entry = next(ring_dir.glob("*.json"))
    payload = json.loads(entry.read_text())
    check("has timestamp", "timestamp" in payload, True)
    check("has prompt", payload["prompt"], "test prompt preview")
    check("has raw_text", payload["raw_text"], "test raw text")
    check("has kind", payload["kind"], "request")

# -- short threshold constant --
print("\n=== short threshold ===")
check("short threshold is 800", _SHORT_THRESHOLD, 800)


class _FakeProc:
    def __init__(self, stdout: bytes, returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""


print("\n=== summarize ===")
check(
    "short text returned unchanged",
    asyncio.run(summarize("short text", "fake-model")),
    "short text",
)

long_text = "Long output block. " * 60
with patch("app.summarize.shutil.which", return_value=None):
    check(
        "missing claude binary returns original",
        asyncio.run(summarize(long_text, "fake-model")),
        long_text,
    )

with patch("app.summarize.shutil.which", return_value="/usr/bin/claude"), patch(
    "app.summarize.asyncio.create_subprocess_exec",
    side_effect=OSError("no cli"),
):
    check(
        "subprocess error returns original",
        asyncio.run(summarize(long_text, "fake-model")),
        long_text,
    )

with patch("app.summarize.shutil.which", return_value="/usr/bin/claude"), patch(
    "app.summarize.asyncio.create_subprocess_exec",
    return_value=_FakeProc(b"Short mobile summary"),
):
    check(
        "successful summarize returns summary",
        asyncio.run(summarize(long_text, "fake-model")),
        "Short mobile summary",
    )


# -- export_chat_history --
print("\n=== export_chat_history ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    check("no history returns None", export_chat_history(data_dir, 999), None)

    save_raw(data_dir, 42, "hello", "Hi there!")
    save_raw(data_dir, 42, "2+2", "4")

    result = export_chat_history(data_dir, 42)
    check("returns string", isinstance(result, str), True)
    check_contains("contains prompt", result, "User: hello")
    check_contains("contains response", result, "Assistant: Hi there!")
    check_contains("contains second", result, "Assistant: 4")

    # Different chat has no history
    check("other chat empty", export_chat_history(data_dir, 999), None)


# -- full prompt storage (no truncation) --
print("\n=== full prompt storage ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    long_prompt = "x" * 500
    save_raw(data_dir, 1, long_prompt, "response")
    ring_dir = data_dir / "raw" / "1"
    entry = next(ring_dir.glob("*.json"))
    payload = json.loads(entry.read_text())
    check("full prompt stored", len(payload["prompt"]), 500)
    check("prompt not truncated", payload["prompt"], long_prompt)

# -- kind field --
print("\n=== kind field ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    save_raw(data_dir, 1, "test", "response", kind="approval")
    ring_dir = data_dir / "raw" / "1"
    entry = next(ring_dir.glob("*.json"))
    payload = json.loads(entry.read_text())
    check("kind stored", payload["kind"], "approval")

    save_raw(data_dir, 2, "test", "response")
    ring_dir2 = data_dir / "raw" / "2"
    entry2 = next(ring_dir2.glob("*.json"))
    payload2 = json.loads(entry2.read_text())
    check("default kind is request", payload2["kind"], "request")

# -- export with kind labels --
print("\n=== export kind labels ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    save_raw(data_dir, 1, "do something", "here is the plan", kind="approval")
    save_raw(data_dir, 1, "do something", "done, executed")
    result = export_chat_history(data_dir, 1)
    check_contains("approval label", result, "[approval]")
    check_contains("request has no label", result, "--- 20")


# -- ring size is 50 --
print("\n=== ring size ===")
check("ring size is 50", _RING_SIZE, 50)

checks.run_and_exit()
