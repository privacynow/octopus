# Raw provider event regression fixtures (Priority 3c)

These files are checked-in traces used to prove the mapping/render path handles real CLI-shaped output.

- **codex_trace.ndjson** — One JSON object per line (NDJSON). Representative Codex CLI stdout: `session_meta`, `turn.started`, `item.started` / `item.completed` (command_execution), `event_msg` (agent_message), `response_item` (message). Codex normalizes event types (e.g. `item.started` → `item_started`).
- **claude_trace.ndjson** — One JSON object per line. Representative Claude CLI stdout: `stream_event` (content_block_start for tool_use, content_block_delta for text_delta), then `result`.

## Capturing real traces

To refresh or add fixtures from a real run:

1. **Codex:** Run a short prompt that triggers at least one command and one assistant message. Redirect stdout to a file (stderr can be discarded or kept). One line per JSON object.
2. **Claude:** Same idea; run a short prompt and capture stdout. Ensure the trace includes at least one `stream_event` and a terminating `result` line.

Keep traces minimal (a few dozen lines) so regressions stay fast and readable. Sanitize any user- or environment-specific content if needed.
