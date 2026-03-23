"""Every image embedded in docs/manual/**/*.md must exist on disk."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANUAL_DIR = REPO_ROOT / "docs" / "manual"
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _refs_in_file(path: Path) -> list[str]:
    return IMAGE_RE.findall(path.read_text(encoding="utf-8"))


def test_manual_markdown_image_refs_exist() -> None:
    missing: list[str] = []
    for md in sorted(MANUAL_DIR.rglob("*.md")):
        for raw in _refs_in_file(md):
            target = _resolve_with_base(md, raw)
            if target is None:
                continue
            if not target.is_file():
                missing.append(f"{md.relative_to(REPO_ROOT)} -> {raw}")
    assert not missing, "Missing manual image files:\n  " + "\n  ".join(missing)


def _resolve_with_base(md_path: Path, ref: str) -> Path | None:
    ref = ref.strip()
    if ref.startswith("http://") or ref.startswith("https://"):
        return None
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref:
        return None
    p = (md_path.parent / ref).resolve()
    return p


def test_manual_dir_has_chapters() -> None:
    names = {p.name for p in MANUAL_DIR.glob("*.md")}
    assert "README.md" in names
    assert "01-setup.md" in names
    assert "03-operator-registry.md" in names
    reg_ui = MANUAL_DIR / "registry-ui"
    assert (reg_ui / "sign-in.md").is_file()
    assert (reg_ui / "deep-links.md").is_file()
