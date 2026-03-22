#!/usr/bin/env python3
"""Draw highlights on screenshots using Playwright-generated *.meta.json.

Outlines stay on the UI; callout text is placed in a bottom margin strip so labels
do not cover the captured content.
"""
from __future__ import annotations

import json
import math
import sys
import textwrap
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
    color: str = "#c62828",
    width: int = 2,
) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    ah = 10
    for da in (0.45, -0.45):
        ax = x2 - ah * math.cos(ang + da)
        ay = y2 - ah * math.sin(ang + da)
        draw.line([(x2, y2), (ax, ay)], fill=color, width=width)


def annotate_with_meta(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: dict,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sm: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> Image.Image:
    """Return image with outlines; legend in bottom margin when labels exist."""
    rects = meta.get("rects", [])
    arrows = meta.get("arrows", [])
    labeled = [r for r in rects if r.get("label")]

    ow, oh = im.size
    # ~100 chars per line at 13px for typical screenshot width
    max_chars = max(48, min(110, (ow - 24) // 7))

    footer_h = 0
    if labeled:
        total_lines = 0
        for r in labeled:
            label = r.get("label", "")
            wrapped = textwrap.wrap(label, width=max_chars) or [label]
            total_lines += len(wrapped)
        footer_h = 14 + total_lines * 18 + 18

    if footer_h <= 0:
        _draw_annotations_on_image(draw, im.size[0], im.size[1], rects, arrows)
        return im

    out = Image.new("RGBA", (ow, oh + footer_h), (38, 50, 56, 255))
    out.paste(im, (0, 0))
    draw2 = ImageDraw.Draw(out, "RGBA")
    _draw_annotations_on_image(draw2, ow, oh, rects, arrows)

    y = oh + 10
    pad_x = 14
    for idx, r in enumerate(labeled, start=1):
        label = r.get("label", "")
        parts = textwrap.wrap(label, width=max_chars) or [label]
        for li, part in enumerate(parts):
            prefix = f"{idx}. " if li == 0 else "   "
            draw2.text((pad_x, y), prefix + part, fill=(236, 239, 241, 255), font=font_sm)
            bbox = draw2.textbbox((0, 0), prefix + part, font=font_sm)
            y += (bbox[3] - bbox[1]) + 4
    return out


def _draw_annotations_on_image(
    draw: ImageDraw.ImageDraw,
    ow: int,
    oh: int,
    rects: list,
    arrows: list,
) -> None:
    """Draw outline rectangles and arrows (coordinates relative to screenshot height oh)."""
    for rect in rects:
        x, y = rect["x"], rect["y"]
        w, h = rect["width"], rect["height"]
        color = rect.get("color", "#ff9800")
        draw.rounded_rectangle([x, y, x + w, y + h], radius=8, outline=color, width=2)

    for ar in arrows:
        _draw_arrow(draw, ar["x1"], ar["y1"], ar["x2"], ar["y2"], color="#b71c1c", width=2)


def annotate_fallback(
    draw: ImageDraw.ImageDraw,
    name: str,
    w: int,
    h: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_sm: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Minimal fallback when .meta.json is missing."""
    if name == "00-login.png":
        draw.text((8, max(0, h - 28)), "Sign in (meta missing — re-run capture)", fill=(80, 80, 80), font=font_sm)


def annotate(path: Path, out: Path) -> None:
    im = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(im, "RGBA")
    font = _font(17)
    font_sm = _font(14)
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        im = annotate_with_meta(im, draw, meta, font, font_sm)
    else:
        annotate_fallback(ImageDraw.Draw(im, "RGBA"), path.name, im.size[0], im.size[1], font, font_sm)

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
