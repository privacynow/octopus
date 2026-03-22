#!/usr/bin/env python3
"""Draw highlights on registry UI screenshots using Playwright-generated *.meta.json when present."""
from __future__ import annotations

import json
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
    import math

    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
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
    bg: str = "#fff9c4",
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


def annotate_with_meta(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: dict,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sm: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    for rect in meta.get("rects", []):
        x, y = rect["x"], rect["y"]
        w, h = rect["width"], rect["height"]
        color = rect.get("color", "#ff9800")
        draw.rounded_rectangle([x, y, x + w, y + h], radius=10, outline=color, width=4)
        label = rect.get("label")
        if label:
            # Place label above box, clamped to image
            lx = max(4, min(x, im.size[0] - 280))
            ly = max(4, y - 36)
            _label(draw, (lx, ly), label, font_sm, bg="#fff9c4")

    for ar in meta.get("arrows", []):
        _draw_arrow(draw, ar["x1"], ar["y1"], ar["x2"], ar["y2"], color="#e53935", width=4)


def annotate_fallback(
    draw: ImageDraw.ImageDraw,
    name: str,
    w: int,
    h: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sm: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Minimal fallback when .meta.json is missing."""
    def px(xp: float, yp: float) -> tuple[float, float]:
        return (xp * w, yp * h)

    if name == "00-login.png":
        _label(draw, px(0.06, 0.08), "Operator login (password only)", font)
    elif name == "01-agents.png":
        _label(draw, px(0.06, 0.08), "See .meta.json + re-run capture for aligned overlays", font_sm)


def annotate(path: Path, out: Path) -> None:
    im = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(im, "RGBA")
    font = _font(17)
    font_sm = _font(14)
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        annotate_with_meta(im, draw, meta, font, font_sm)
    else:
        annotate_fallback(draw, path.name, im.size[0], im.size[1], font, font_sm)

    im.convert("RGB").save(out, quality=92)


def _default_asset_dirs() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "assets"
    return [root / "registry" / "ui", root / "manual"]


def main() -> None:
    dirs = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else _default_asset_dirs()
    any_ok = False
    for base in dirs:
        if not base.is_dir():
            print(f"Skip (missing): {base}", file=sys.stderr)
            continue
        any_ok = True
        for png in sorted(base.glob("*.png")):
            if "-annotated" in png.stem:
                continue
            out = png.with_name(png.stem + "-annotated.png")
            annotate(png, out)
            print(out)
    if not any_ok:
        print("No asset directories found to annotate.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
