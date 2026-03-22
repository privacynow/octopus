#!/usr/bin/env python3
"""Draw teacher-style highlights on registry UI screenshots. Requires Pillow."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        p = Path(name)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    color: str = "#e53935",
    width: int = 4,
) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    # Arrow head
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    ah = 14
    for da in (0.45, -0.45):
        ax = x2 - ah * math.cos(ang + da)
        ay = y2 - ah * math.sin(ang + da)
        draw.line([(x2, y2), (ax, ay)], fill=color, width=width)


def _label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    fg: str = "#111",
    bg: str = "#ffeb3b",
) -> None:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 8
    draw.rounded_rectangle(
        [x - pad, y - pad, x + tw + pad, y + th + pad],
        radius=6,
        fill=bg,
        outline="#f57f17",
        width=2,
    )
    draw.text((x, y), text, fill=fg, font=font)


def annotate(path: Path, out: Path) -> None:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    draw = ImageDraw.Draw(im, "RGBA")
    font = _font(18)
    font_sm = _font(15)
    name = path.name

    # Percentage helpers
    def px(xp: float, yp: float) -> tuple[float, float]:
        return (xp * w, yp * h)

    if name == "00-login.png":
        _draw_arrow(draw, *px(0.55, 0.35), *px(0.48, 0.48))
        _label(draw, px(0.08, 0.12), "Operator login — password only", font)
        _label(draw, px(0.08, 0.2), "Use REGISTRY_UI_TOKEN from .deploy/registry/.env", font_sm)
    elif name == "01-agents.png":
        draw.rounded_rectangle(
            [*px(0.02, 0.08), *px(0.18, 0.55)],
            radius=8,
            outline="#ff9800",
            width=4,
        )
        _label(draw, px(0.2, 0.1), "Sidebar: every major screen", font)
        _draw_arrow(draw, *px(0.22, 0.18), *px(0.12, 0.28))
        draw.rounded_rectangle(
            [*px(0.22, 0.35), *px(0.95, 0.75)],
            radius=8,
            outline="#2196f3",
            width=3,
        )
        _label(draw, px(0.25, 0.78), "Click a card → agent detail", font_sm)
    elif name == "02-agent-detail.png":
        _label(draw, px(0.22, 0.12), "Identity, scope, heartbeat, skills", font)
        _draw_arrow(draw, *px(0.5, 0.28), *px(0.5, 0.42))
        _label(draw, px(0.22, 0.62), '"Conversations →" = filter to this agent', font_sm)
    elif name == "03-agent-conversations.png":
        _label(draw, px(0.22, 0.12), "Same data as All conversations, scoped to agent", font)
        _draw_arrow(draw, *px(0.45, 0.45), *px(0.5, 0.52))
    elif name == "04-conversations.png":
        _label(draw, px(0.22, 0.2), "Search after 3+ characters", font_sm)
        _draw_arrow(draw, *px(0.5, 0.22), *px(0.5, 0.28))
        _label(draw, px(0.22, 0.72), "Open a row → timeline", font)
    elif name == "05-conversation-detail.png":
        _label(draw, px(0.22, 0.08), "Header: title, channel, status", font_sm)
        _label(draw, px(0.22, 0.88), "Chat bubbles = user/bot; cards = other event kinds", font)
        _draw_arrow(draw, *px(0.35, 0.85), *px(0.45, 0.55))
    elif name == "06-tasks.png":
        _label(draw, px(0.22, 0.12), "Routed tasks (delegation). Row → parent conversation", font)
        _draw_arrow(draw, *px(0.4, 0.42), *px(0.55, 0.48))
    elif name == "07-capabilities.png":
        _label(draw, px(0.22, 0.12), "Global coordination toggles (operator)", font)
        _label(draw, px(0.22, 0.2), "POST requires CSRF when using session cookies", font_sm)
    elif name == "08-skills.png":
        _label(draw, px(0.22, 0.12), "Catalog / lifecycle lives in registry store", font)
    elif name == "09-usage.png":
        _label(draw, px(0.22, 0.12), "Token & cost rollups (when bots publish usage metadata)", font)

    im.convert("RGB").save(out, quality=92)


def main() -> None:
    base = Path(__file__).resolve().parent.parent / "assets" / "registry" / "ui"
    if not base.is_dir():
        print(f"Missing {base}", file=sys.stderr)
        sys.exit(1)
    for png in sorted(base.glob("*.png")):
        if "-annotated" in png.stem:
            continue
        out = png.with_name(png.stem + "-annotated.png")
        annotate(png, out)
        print(out)


if __name__ == "__main__":
    main()
