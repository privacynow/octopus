from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = REPO_ROOT / "docs" / "registry-guide.md"
README_PATH = REPO_ROOT / "README.md"

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _image_refs(path: Path) -> set[str]:
    return set(IMAGE_RE.findall(path.read_text(encoding="utf-8")))


def test_registry_guide_references_at_least_one_png() -> None:
    """The guide should reference at least one image."""
    refs = _image_refs(GUIDE_PATH)
    png_refs = {ref for ref in refs if ref.endswith(".png")}
    assert len(png_refs) > 0, "Registry guide has no PNG references"


def test_registry_guide_referenced_assets_exist() -> None:
    """Every image referenced in the registry guide should exist on disk."""
    for ref in _image_refs(GUIDE_PATH):
        assert (GUIDE_PATH.parent / ref).exists(), f"Guide references {ref} but file is missing"


def test_readme_image_refs_resolve() -> None:
    """Every image referenced in README.md should exist on disk."""
    refs = _image_refs(README_PATH)
    for ref in refs:
        assert (REPO_ROOT / ref).exists(), f"README references {ref} but file is missing"
