"""Tests for summarize.py — ring buffer and summarization."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.summarize import _RING_SIZE, _SHORT_THRESHOLD, export_chat_history, load_raw, save_raw, summarize


class _FakeProc:
    def __init__(self, stdout: bytes, returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""


# -- ring buffer --

def test_ring_buffer_empty():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        assert load_raw(data_dir, 1) is None

def test_ring_buffer_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "prompt one", "response one")
        assert load_raw(data_dir, 1, 1) == "response one"

        save_raw(data_dir, 1, "prompt two", "response two")
        assert load_raw(data_dir, 1, 1) == "response two"
        assert load_raw(data_dir, 1, 2) == "response one"

def test_ring_buffer_out_of_range():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "prompt one", "response one")
        save_raw(data_dir, 1, "prompt two", "response two")
        assert load_raw(data_dir, 1, 99) is None
        assert load_raw(data_dir, 1, 0) is None

def test_ring_buffer_chat_isolation():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "prompt one", "response one")
        save_raw(data_dir, 1, "prompt two", "response two")
        save_raw(data_dir, 2, "other chat", "other response")
        assert load_raw(data_dir, 2, 1) == "other response"
        assert load_raw(data_dir, 1, 1) == "response two"


# -- ring buffer rotation --

def test_ring_buffer_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)

        # Fill beyond capacity
        for i in range(_RING_SIZE + 3):
            save_raw(data_dir, 1, f"prompt {i}", f"response {i}")

        # Should only have _RING_SIZE entries
        ring_dir = data_dir / "raw" / "1"
        entries = list(ring_dir.glob("*.json"))
        assert len(entries) == _RING_SIZE

        # Latest should be the last one saved
        assert load_raw(data_dir, 1, 1) == f"response {_RING_SIZE + 2}"

        # Oldest available should be offset by 3
        oldest = load_raw(data_dir, 1, _RING_SIZE)
        assert oldest == f"response 3"


# -- ring buffer JSON format --

def test_ring_buffer_json_format():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "test prompt preview", "test raw text")
        ring_dir = data_dir / "raw" / "1"
        entry = next(ring_dir.glob("*.json"))
        payload = json.loads(entry.read_text())
        assert "timestamp" in payload
        assert payload["prompt"] == "test prompt preview"
        assert payload["raw_text"] == "test raw text"
        assert payload["kind"] == "request"


# -- short threshold constant --

def test_short_threshold():
    assert _SHORT_THRESHOLD == 800


# -- summarize --

def test_short_text_returned_unchanged():
    assert asyncio.run(summarize("short text", "fake-model")) == "short text"

def test_missing_claude_binary_returns_original():
    long_text = "Long output block. " * 60
    with patch("app.summarize.shutil.which", return_value=None):
        assert asyncio.run(summarize(long_text, "fake-model")) == long_text

def test_subprocess_error_returns_original():
    long_text = "Long output block. " * 60
    with patch("app.summarize.shutil.which", return_value="/usr/bin/claude"), patch(
        "app.summarize.asyncio.create_subprocess_exec",
        side_effect=OSError("no cli"),
    ):
        assert asyncio.run(summarize(long_text, "fake-model")) == long_text

def test_successful_summarize_returns_summary():
    long_text = "Long output block. " * 60
    with patch("app.summarize.shutil.which", return_value="/usr/bin/claude"), patch(
        "app.summarize.asyncio.create_subprocess_exec",
        return_value=_FakeProc(b"Short mobile summary"),
    ):
        assert asyncio.run(summarize(long_text, "fake-model")) == "Short mobile summary"


# -- export_chat_history --

def test_export_no_history():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        assert export_chat_history(data_dir, 999) is None

def test_export_chat_history():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 42, "hello", "Hi there!")
        save_raw(data_dir, 42, "2+2", "4")

        result = export_chat_history(data_dir, 42)
        assert isinstance(result, str)
        assert "User: hello" in result
        assert "Assistant: Hi there!" in result
        assert "Assistant: 4" in result

        # Different chat has no history
        assert export_chat_history(data_dir, 999) is None


# -- full prompt storage (no truncation) --

def test_full_prompt_storage():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        long_prompt = "x" * 500
        save_raw(data_dir, 1, long_prompt, "response")
        ring_dir = data_dir / "raw" / "1"
        entry = next(ring_dir.glob("*.json"))
        payload = json.loads(entry.read_text())
        assert len(payload["prompt"]) == 500
        assert payload["prompt"] == long_prompt


# -- kind field --

def test_kind_field_stored():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "test", "response", kind="approval")
        ring_dir = data_dir / "raw" / "1"
        entry = next(ring_dir.glob("*.json"))
        payload = json.loads(entry.read_text())
        assert payload["kind"] == "approval"

def test_kind_field_default():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 2, "test", "response")
        ring_dir2 = data_dir / "raw" / "2"
        entry2 = next(ring_dir2.glob("*.json"))
        payload2 = json.loads(entry2.read_text())
        assert payload2["kind"] == "request"


# -- export with kind labels --

def test_export_kind_labels():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        save_raw(data_dir, 1, "do something", "here is the plan", kind="approval")
        save_raw(data_dir, 1, "do something", "done, executed")
        result = export_chat_history(data_dir, 1)
        assert "[approval]" in result
        assert "--- 20" in result


# -- ring size is 50 --

def test_ring_size():
    assert _RING_SIZE == 50
