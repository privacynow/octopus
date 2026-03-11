"""Normalized progress events and shared renderer.

Providers map raw CLI events to ProgressEvent instances.  The renderer
owns all user-facing HTML wording and formatting for the progress/status
message.  Providers never build display HTML directly — they emit events,
and the renderer decides what the user sees.

This is Layer 2 of the progress UX contract (PLAN III.5).
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field

from app.formatting import md_to_telegram_html, trim_text


# ---------------------------------------------------------------------------
# Progress event family
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Thinking:
    """Model is reasoning internally — no visible output yet."""


@dataclass(frozen=True, slots=True)
class ToolStart:
    """A non-command tool invocation has started."""
    name: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ToolFinish:
    """A non-command tool invocation has finished."""
    name: str
    output_preview: str = ""


@dataclass(frozen=True, slots=True)
class CommandStart:
    """A shell command is being executed."""
    command: str = ""


@dataclass(frozen=True, slots=True)
class CommandFinish:
    """A shell command has finished."""
    command: str = ""
    exit_code: int | None = None
    output_preview: str = ""


@dataclass(frozen=True, slots=True)
class ContentDelta:
    """Visible reply text arriving from the model.

    The provider should set ``content_started`` on the first instance.
    ``tool_activity`` carries recent tool names for display context.
    """
    text: str
    tool_activity: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DraftReply:
    """Intermediate agent commentary or draft response text."""
    text: str


@dataclass(frozen=True, slots=True)
class Denial:
    """A tool call or action was blocked/denied."""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Liveness:
    """Provider-owned liveness signal for states the generic heartbeat
    cannot explain (e.g. long compaction)."""
    detail: str


# Union type for all progress events.
ProgressEvent = (
    Thinking | ToolStart | ToolFinish | CommandStart | CommandFinish
    | ContentDelta | DraftReply | Denial | Liveness
)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render(event: ProgressEvent) -> str | None:
    """Render a progress event to Telegram HTML.

    Returns None if the event should not produce a visible update
    (e.g. suppressed internal detail).
    """
    if isinstance(event, Thinking):
        return "<i>Thinking...</i>"

    if isinstance(event, CommandStart):
        if event.command:
            return (
                f"<i>Running command:</i>\n"
                f"<pre>{_html.escape(trim_text(event.command, 600))}</pre>"
            )
        return "<i>Running command...</i>"

    if isinstance(event, CommandFinish):
        if event.exit_code is None:
            header = "<i>Command finished.</i>"
        else:
            header = f"<i>Command finished (exit {_html.escape(str(event.exit_code))}):</i>"
        if event.command:
            header += f"\n<pre>{_html.escape(trim_text(event.command, 400))}</pre>"
        parts = [header]
        if event.output_preview:
            parts.append(
                f"<i>Output:</i>\n<pre>{_html.escape(trim_text(event.output_preview, 700))}</pre>"
            )
        return "\n\n".join(parts)

    if isinstance(event, ToolStart):
        return (
            f"<i>Using tool:</i>\n"
            f"<code>{_html.escape(trim_text(event.name, 120))}</code>"
        )

    if isinstance(event, ToolFinish):
        parts = [
            f"<i>Tool finished:</i>\n"
            f"<code>{_html.escape(trim_text(event.name, 120))}</code>"
        ]
        if event.output_preview:
            parts.append(
                f"<i>Output:</i>\n<pre>{_html.escape(trim_text(event.output_preview, 700))}</pre>"
            )
        return "\n\n".join(parts)

    if isinstance(event, ContentDelta):
        parts = []
        if event.tool_activity:
            parts.append(
                "<i>" + _html.escape(" → ".join(event.tool_activity[-3:])) + "</i>"
            )
        if event.text:
            parts.append(md_to_telegram_html(trim_text(event.text, 3200)))
        else:
            parts.append("<i>Thinking...</i>")
        return "\n".join(parts)

    if isinstance(event, DraftReply):
        preview = trim_text(event.text.strip(), 700)
        if preview:
            return f"<i>Draft reply received:</i>\n\n{md_to_telegram_html(preview)}"
        return "<i>Reply received.</i>"

    if isinstance(event, Denial):
        if event.detail:
            return f"<i>Blocked:</i> {_html.escape(trim_text(event.detail, 200))}"
        return "<i>Action blocked.</i>"

    if isinstance(event, Liveness):
        return f"<i>{_html.escape(event.detail)}</i>"

    return None
