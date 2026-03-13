"""Contract tests for the unified progress event system.

Tests the ProgressEvent → render() contract that both providers depend on.
Also tests the Codex _map_event and Claude _consume_stream mapping produce
correct ProgressEvent types from raw CLI events.
"""

import asyncio
import json
from pathlib import Path

from app.progress import (
    CommandFinish, CommandStart, ContentDelta, Denial, DraftReply,
    Liveness, Thinking, ToolFinish, ToolStart,
    render,
)
from app.providers.codex import CodexProvider
from tests.support.config_support import make_config as make_bot_config
from tests.support.handler_support import FakeMessage, FakeProgress


# ---------------------------------------------------------------------------
# Layer 1: render() contract — each event type produces correct HTML
# ---------------------------------------------------------------------------

class TestRenderContract:
    """render() must produce provider-neutral HTML for every event type."""

    def test_thinking_html(self):
        html = render(Thinking())
        assert "Thinking" in html and "<i>" in html

    def test_command_start_with_command(self):
        html = render(CommandStart(command="ls -la"))
        assert "Running" in html and "command" in html
        assert "ls -la" in html

    def test_command_start_without_command(self):
        html = render(CommandStart())
        assert "Running" in html and "command" in html

    def test_command_finish_with_exit_code_and_output(self):
        html = render(CommandFinish(command="ls", exit_code=0, output_preview="file.txt"))
        assert "finished" in html
        assert "exit 0" in html
        assert "file.txt" in html

    def test_command_finish_no_exit_code(self):
        html = render(CommandFinish(command="ls"))
        assert "finished" in html or "finished" in html
        assert "exit" not in html

    def test_tool_start(self):
        html = render(ToolStart(name="read_file"))
        assert "Using tool" in html
        assert "read_file" in html

    def test_tool_finish_with_output(self):
        html = render(ToolFinish(name="read_file", output_preview="contents here"))
        assert "Tool finished" in html
        assert "read_file" in html
        assert "contents here" in html

    def test_tool_finish_without_output(self):
        html = render(ToolFinish(name="read_file"))
        assert "Tool finished" in html
        assert "Output" not in html

    def test_content_delta_with_text(self):
        html = render(ContentDelta(text="Hello world"))
        assert "Hello world" in html

    def test_content_delta_empty_text_shows_thinking(self):
        html = render(ContentDelta(text=""))
        assert "Thinking" in html

    def test_content_delta_with_tool_activity(self):
        html = render(ContentDelta(text="result", tool_activity=("⚙ Read", "⚙ Write")))
        assert "Read" in html
        assert "Write" in html
        assert "result" in html

    def test_content_delta_tool_activity_truncated_to_3(self):
        """Only the last 3 tool activities should be shown."""
        html = render(ContentDelta(
            text="x",
            tool_activity=("a", "b", "c", "d"),
        ))
        # "a" is oldest — should be dropped
        assert "a" not in html
        assert "d" in html

    def test_draft_reply_with_text(self):
        html = render(DraftReply(text="I'll check the files"))
        assert "Draft reply" in html
        assert "check the files" in html

    def test_draft_reply_empty_text(self):
        html = render(DraftReply(text=""))
        assert "Reply received" in html

    def test_denial_with_detail(self):
        html = render(Denial(detail="permission denied"))
        assert "Blocked" in html
        assert "permission denied" in html

    def test_denial_no_detail(self):
        html = render(Denial())
        assert "Action blocked" in html

    def test_liveness(self):
        html = render(Liveness(detail="Compacting context"))
        assert "Compacting context" in html

    def test_all_events_return_string_or_none(self):
        """Every event type must return str (not None) from render()."""
        events = [
            Thinking(),
            CommandStart(command="x"),
            CommandFinish(command="x"),
            ToolStart(name="x"),
            ToolFinish(name="x"),
            ContentDelta(text="x"),
            DraftReply(text="x"),
            Denial(detail="x"),
            Liveness(detail="x"),
        ]
        for evt in events:
            result = render(evt)
            assert isinstance(result, str), f"{type(evt).__name__} returned {type(result)}"
            assert len(result) > 0, f"{type(evt).__name__} returned empty string"


# ---------------------------------------------------------------------------
# Layer 2: render() never leaks provider internals
# ---------------------------------------------------------------------------

class TestRenderNoInternals:
    """Rendered output must not contain provider names or internal IDs."""

    def _assert_no_internals(self, html: str):
        lower = html.lower()
        for term in ("codex", "claude", "thread_id", "session_id", "thread-"):
            assert term not in lower, f"Leaked internal term '{term}' in: {html}"

    def test_command_start_no_internals(self):
        self._assert_no_internals(render(CommandStart(command="git status")))

    def test_command_finish_no_internals(self):
        self._assert_no_internals(render(CommandFinish(command="git status", exit_code=0)))

    def test_thinking_no_internals(self):
        self._assert_no_internals(render(Thinking()))

    def test_draft_reply_no_internals(self):
        self._assert_no_internals(render(DraftReply(text="I found the issue")))

    def test_tool_start_no_internals(self):
        self._assert_no_internals(render(ToolStart(name="read_file")))


# ---------------------------------------------------------------------------
# Layer 3: Codex _map_event produces correct ProgressEvent types
# ---------------------------------------------------------------------------

class TestCodexMapEvent:
    """Codex _map_event must produce the right event type for each CLI event shape."""

    def test_turn_started_produces_thinking(self):
        evt = CodexProvider._map_event({"type": "turn.started"}, False)
        assert isinstance(evt, Thinking)

    def test_task_started_produces_thinking(self):
        evt = CodexProvider._map_event({"type": "task.started"}, False)
        assert isinstance(evt, Thinking)

    def test_reasoning_payload_produces_thinking(self):
        evt = CodexProvider._map_event(
            {"type": "event_msg", "payload": {"type": "reasoning"}}, False,
        )
        assert isinstance(evt, Thinking)

    def test_command_execution_started(self):
        evt = CodexProvider._map_event(
            {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}},
            False,
        )
        assert isinstance(evt, CommandStart)
        assert evt.command == "ls"

    def test_command_execution_completed(self):
        evt = CodexProvider._map_event(
            {"type": "item.completed", "item": {
                "type": "command_execution", "command": "ls",
                "aggregated_output": "file.txt", "exit_code": 0,
            }},
            False,
        )
        assert isinstance(evt, CommandFinish)
        assert evt.command == "ls"
        assert evt.exit_code == 0
        assert evt.output_preview == "file.txt"

    def test_agent_message_produces_draft_reply(self):
        evt = CodexProvider._map_event(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}},
            False,
        )
        assert isinstance(evt, DraftReply)
        assert evt.text == "Done!"

    def test_exec_command_function_call_produces_command_start(self):
        tool_calls = {}
        evt = CodexProvider._map_event(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "c1",
                    "arguments": '{"cmd":"git status"}',
                },
            },
            False,
            tool_calls,
        )
        assert isinstance(evt, CommandStart)
        assert "git status" in evt.command
        assert "c1" in tool_calls

    def test_non_exec_function_call_produces_tool_start(self):
        evt = CodexProvider._map_event(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "read_file",
                    "call_id": "c2",
                    "arguments": "{}",
                },
            },
            False,
            {},
        )
        assert isinstance(evt, ToolStart)
        assert evt.name == "read_file"

    def test_function_call_output_produces_command_finish(self):
        tool_calls = {"c1": {"name": "exec_command", "command": "git status"}}
        evt = CodexProvider._map_event(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": "M file.py",
                },
            },
            False,
            tool_calls,
        )
        assert isinstance(evt, CommandFinish)
        assert evt.command == "git status"
        assert "M file.py" in evt.output_preview
        assert tool_calls == {}  # consumed

    def test_function_call_output_produces_tool_finish(self):
        tool_calls = {"c2": {"name": "read_file", "command": ""}}
        evt = CodexProvider._map_event(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c2",
                    "output": "file contents",
                },
            },
            False,
            tool_calls,
        )
        assert isinstance(evt, ToolFinish)
        assert evt.name == "read_file"

    def test_thread_started_suppressed(self):
        assert CodexProvider._map_event(
            {"type": "thread.started", "thread_id": "t-123"}, False,
        ) is None

    def test_session_meta_suppressed(self):
        assert CodexProvider._map_event(
            {"type": "session_meta", "payload": {"id": "s-456"}}, False,
        ) is None

    def test_session_configured_suppressed(self):
        assert CodexProvider._map_event(
            {"type": "event_msg", "payload": {"type": "session_configured", "thread_id": "t"}},
            True,
        ) is None

    def test_unknown_event_suppressed(self):
        assert CodexProvider._map_event({"type": "unknown"}, False) is None


# ---------------------------------------------------------------------------
# Layer 4: End-to-end — raw event → _map_event → render → HTML
# ---------------------------------------------------------------------------

class TestCodexEndToEnd:
    """The full pipeline from raw Codex event to user-visible HTML."""

    def test_command_start_pipeline(self):
        evt = CodexProvider._map_event(
            {"type": "item.started", "item": {"type": "command_execution", "command": "make test"}},
            False,
        )
        html = render(evt)
        assert "Running" in html and "command" in html
        assert "make test" in html

    def test_command_finish_pipeline(self):
        evt = CodexProvider._map_event(
            {"type": "item.completed", "item": {
                "type": "command_execution", "command": "make test",
                "exit_code": 1, "aggregated_output": "FAILED",
            }},
            False,
        )
        html = render(evt)
        assert "finished" in html
        assert "exit 1" in html
        assert "FAILED" in html

    def test_internal_events_produce_no_html(self):
        """Internal events must produce None from _map_event, never reaching render."""
        internal_events = [
            {"type": "thread.started", "thread_id": "t-1"},
            {"type": "session_meta", "payload": {"id": "s-1"}},
            {"type": "event_msg", "payload": {"type": "session_configured"}},
            {"type": "unknown"},
        ]
        for raw in internal_events:
            evt = CodexProvider._map_event(raw, False)
            assert evt is None, f"Expected None for {raw['type']}, got {type(evt).__name__}"


# ---------------------------------------------------------------------------
# Layer 5: Claude _consume_stream — progress events reach the sink
# ---------------------------------------------------------------------------

class _FakeStreamProcess:
    """Minimal fake of asyncio.subprocess.Process with canned stdout lines."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.returncode = 0

    @property
    def stdout(self):
        return self

    async def readline(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        return b""

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        raise StopAsyncIteration

    async def wait(self):
        pass


def _stream_event(inner_type: str, delta: dict | None = None, content_block: dict | None = None) -> str:
    """Build a Claude stream-json line."""
    inner = {"type": inner_type}
    if delta:
        inner["delta"] = delta
    if content_block:
        inner["content_block"] = content_block
    return json.dumps({"type": "stream_event", "event": inner})


def _result_event(result_text: str = "final") -> str:
    return json.dumps({"type": "result", "result": result_text})


class TestClaudeConsumeStream:
    """Claude _consume_stream must emit progress updates through render_progress."""

    async def test_text_delta_produces_content_update(self):
        from app.providers.claude import ClaudeProvider
        prov = ClaudeProvider(make_bot_config())

        lines = [
            _stream_event("content_block_delta", delta={"type": "text_delta", "text": "Hello"}),
            _result_event("Hello"),
        ]
        progress = FakeProgress()
        proc = _FakeStreamProcess(lines)
        text, result_data, tool_activity = await prov._consume_stream(proc, progress)

        assert text == "Hello"
        assert len(progress.updates) >= 1
        # The update should contain rendered ContentDelta HTML, not raw event JSON
        assert "Hello" in progress.updates[-1]
        # Should NOT contain provider internals
        for u in progress.updates:
            assert "claude" not in u.lower()

    async def test_tool_use_produces_tool_activity_update(self):
        from app.providers.claude import ClaudeProvider
        prov = ClaudeProvider(make_bot_config())

        lines = [
            _stream_event("content_block_start", content_block={"type": "tool_use", "name": "Read"}),
            _stream_event("content_block_delta", delta={"type": "text_delta", "text": "result"}),
            _result_event("result"),
        ]
        progress = FakeProgress()
        proc = _FakeStreamProcess(lines)
        text, result_data, tool_activity = await prov._consume_stream(proc, progress)

        assert "Read" in tool_activity[0]
        # The tool activity should appear in rendered progress
        tool_update = progress.updates[0]  # First update is the tool_use event
        assert "Read" in tool_update

    async def test_denial_produces_denied_activity(self):
        from app.providers.claude import ClaudeProvider
        prov = ClaudeProvider(make_bot_config())

        lines = [
            json.dumps({
                "type": "user",
                "message": {"content": [{"is_error": True, "content": "Permission denied: Write"}]},
            }),
            _result_event("blocked"),
        ]
        progress = FakeProgress()
        proc = _FakeStreamProcess(lines)
        text, result_data, tool_activity = await prov._consume_stream(proc, progress)

        assert any("denied" in a for a in tool_activity)
        # Should produce a progress update
        assert len(progress.updates) >= 1

    async def test_content_started_set_on_text(self):
        from app.providers.claude import ClaudeProvider
        prov = ClaudeProvider(make_bot_config())

        lines = [
            _stream_event("content_block_delta", delta={"type": "text_delta", "text": "hi"}),
            _result_event("hi"),
        ]
        progress = FakeProgress()
        proc = _FakeStreamProcess(lines)
        await prov._consume_stream(proc, progress)

        assert progress.content_started.is_set()

    async def test_no_provider_internals_in_any_update(self):
        """No progress update from Claude should contain provider names or IDs."""
        from app.providers.claude import ClaudeProvider
        prov = ClaudeProvider(make_bot_config())

        lines = [
            _stream_event("content_block_start", content_block={"type": "tool_use", "name": "Bash"}),
            _stream_event("content_block_delta", delta={"type": "text_delta", "text": "done"}),
            _result_event("done"),
        ]
        progress = FakeProgress()
        proc = _FakeStreamProcess(lines)
        await prov._consume_stream(proc, progress)

        for u in progress.updates:
            lower = u.lower()
            assert "claude" not in lower, f"Leaked 'claude' in: {u}"
            assert "session_id" not in lower, f"Leaked 'session_id' in: {u}"


# ---------------------------------------------------------------------------
# Progress heartbeat and rate-limit (Priority 3a / 3b)
# ---------------------------------------------------------------------------

async def test_heartbeat_does_not_overwrite_provider_liveness():
    """Heartbeat and provider Liveness both update progress; they must not fight.

    Simulates long Codex resume: handler heartbeat is active while provider
    emits Liveness (e.g. 'Still working — this may take a moment...').
    Heartbeat must not overwrite a recent Liveness update (same as for
    tool/command updates). Proves only one visible update per interval.
    """
    import app.telegram_handlers as th
    from unittest.mock import patch

    progress = FakeProgress()
    content_started = progress.content_started

    # Use same cadence as test_heartbeat_stops_when_content_starts so first beat fires
    with patch.object(th, "_HEARTBEAT_FIRST", 0.05), \
         patch.object(th, "_HEARTBEAT_SUBSEQUENT", 0.05):
        task = asyncio.create_task(th._heartbeat(progress, content_started))

        await asyncio.sleep(0.10)  # First beat at 0.05s
        count_after_first_beat = len(progress.updates)
        assert count_after_first_beat >= 1, (
            f"First heartbeat should have fired; got {progress.updates}"
        )

        # Simulate provider Liveness (e.g. Codex long resume timeout path)
        liveness_html = render(Liveness(detail="Still working — this may take a moment..."))
        await progress.update(liveness_html)
        count_after_liveness = len(progress.updates)
        assert progress.last_text == liveness_html

        # Wait less than HEARTBEAT_SUBSEQUENT — heartbeat must NOT overwrite Liveness
        await asyncio.sleep(0.03)
        heartbeat_after_liveness = [
            u for u in progress.updates[count_after_liveness:]
            if "Still working... (" in u and "s)" in u
        ]
        assert len(heartbeat_after_liveness) == 0, (
            f"Heartbeat overwrote provider Liveness: {progress.updates}"
        )

        task.cancel()
        await task


async def test_rate_limit_preserves_semantic_command_events():
    """Rate-limited progress sink must not suppress meaningful Codex semantic events.

    Integration test: real rate limiter (TelegramProgress) + Codex-style
    command/tool events. Sends a burst so that some updates are suppressed;
    asserts CommandStart and CommandFinish still appear (plan Priority 3b).
    """
    import app.telegram_handlers as th

    msg = FakeMessage()
    cfg = make_bot_config(stream_update_interval_seconds=0.2)
    progress = th.TelegramProgress(msg, cfg)
    progress.content_started = asyncio.Event()  # do not trigger content-first bypass

    # Burst: CommandStart (first update goes through), then filler within same interval
    # so they are suppressed; then after interval, CommandFinish goes through.
    await progress.update(render(CommandStart(command="ls -la")))
    await progress.update(render(Thinking()))       # rate-limited out
    await progress.update(render(ToolStart(name="read_file", detail="")))  # rate-limited out
    await asyncio.sleep(0.25)
    await progress.update(render(CommandFinish(command="ls -la", exit_code=0, output_preview="")))

    edits = [r["edit_text"] for r in msg.replies if "edit_text" in r]
    combined = " ".join(edits)
    assert "Running" in combined and "command" in combined and "finished" in combined, (
        f"Rate limiting must preserve command start/finish; got edits: {edits}"
    )
    # Prove suppression: in-window filler (Thinking, ToolStart) must not have leaked through
    assert "Thinking..." not in combined, (
        f"In-window Thinking update should have been suppressed; got edits: {edits}"
    )
    assert "Using tool" not in combined, (
        f"In-window ToolStart update should have been suppressed; got edits: {edits}"
    )
    assert len(edits) == 2, (
        f"Exactly two edits (command start + finish) should survive; got {len(edits)}: {edits}"
    )


# ---------------------------------------------------------------------------
# Raw fixture regression (Priority 3c)
# ---------------------------------------------------------------------------

def _progress_fixture_path(name: str) -> Path:
    """Path to a checked-in progress fixture (NDJSON)."""
    return Path(__file__).parent / "fixtures" / "progress" / name


def test_codex_raw_fixture_mapping_and_render():
    """Feed checked-in Codex NDJSON through _map_event and render; exact expected sequence and output."""
    path = _progress_fixture_path("codex_trace.ndjson")
    assert path.exists(), f"Checked-in fixture required (Priority 3c): {path}"
    lines = path.read_text().strip().splitlines()
    provider = CodexProvider(make_bot_config())
    tool_calls: dict = {}
    events = []
    rendered = []
    for line in lines:
        if not line.strip():
            continue
        raw = json.loads(line)
        evt = provider._map_event(raw, is_resume=False, tool_calls=tool_calls)
        if evt is not None:
            events.append(evt)
            html = render(evt)
            if html:
                rendered.append(html)
    # Fixture yields this exact sequence: Thinking, CommandStart, CommandFinish, DraftReply, CommandStart, CommandFinish
    expected_types = [Thinking, CommandStart, CommandFinish, DraftReply, CommandStart, CommandFinish]
    assert len(events) == len(expected_types), (
        f"Expected {len(expected_types)} mapped events; got {len(events)}: {[type(e).__name__ for e in events]}"
    )
    for i, (evt, expected) in enumerate(zip(events, expected_types)):
        assert isinstance(evt, expected), (
            f"Event {i}: expected {expected.__name__}, got {type(evt).__name__}"
        )
    combined = " ".join(rendered)
    assert "Running" in combined and "command" in combined and "finished" in combined
    assert "ls -la" in combined, "First command from fixture must appear in rendered output"
    assert "echo done" in combined or "echo" in combined, "Second command from fixture must appear"
    assert "Listing complete" in combined or "Draft reply" in combined, "Commentary from fixture must appear"
    for html in rendered:
        assert "codex" not in html.lower(), f"Rendered must not leak provider name: {html}"


async def test_claude_raw_fixture_consume_stream():
    """Feed checked-in Claude NDJSON through _consume_stream; exact expected update count and content."""
    from app.providers.claude import ClaudeProvider

    path = _progress_fixture_path("claude_trace.ndjson")
    assert path.exists(), f"Checked-in fixture required (Priority 3c): {path}"
    lines = path.read_text().strip().splitlines()
    prov = ClaudeProvider(make_bot_config())
    progress = FakeProgress()
    proc = _FakeStreamProcess(lines)
    text, result_data, tool_activity = await prov._consume_stream(proc, progress)
    assert "result" in result_data, "Stream should terminate on result event"
    # Fixture: tool_use Read, then two text_delta lines -> exactly 3 progress updates
    assert len(progress.updates) == 3, (
        f"Expected exactly 3 progress updates from fixture; got {len(progress.updates)}: {progress.updates}"
    )
    combined = " ".join(progress.updates)
    assert "Read" in combined, "Tool name from fixture must appear in updates"
    assert "File contents here" in combined, "First text delta from fixture must appear"
    assert "Hello world" in combined, "Second text delta from fixture must appear"
    for u in progress.updates:
        assert "claude" not in u.lower(), f"Must not leak provider name: {u}"
        assert "session_id" not in u.lower(), f"Must not leak internal ID: {u}"
