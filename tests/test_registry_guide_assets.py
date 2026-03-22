from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = REPO_ROOT / "docs" / "registry-guide.md"
README_PATH = REPO_ROOT / "README.md"
ASSET_DIR = REPO_ROOT / "docs" / "assets" / "registry"

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

EXPECTED_GUIDE_PNGS = {
    "assets/registry/00-full-dashboard.png",
    "assets/registry/03-registry-login.png",
    "assets/registry/05-registry-dashboard.png",
    "assets/registry/10-agent-detail.png",
    "assets/registry/12-routed-task-detail.png",
    "assets/registry/13-conversation-detail.png",
    "assets/registry/runtime-skills-tab.png",
    "assets/registry/capabilities-tab.png",
    "assets/registry/guidance-tab.png",
}


def _image_refs(path: Path) -> set[str]:
    return set(IMAGE_RE.findall(path.read_text(encoding="utf-8")))


def test_registry_guide_png_references_match_regenerated_set() -> None:
    refs = _image_refs(GUIDE_PATH)
    png_refs = {ref for ref in refs if ref.endswith(".png")}
    assert png_refs == EXPECTED_GUIDE_PNGS


def test_registry_guide_referenced_assets_exist() -> None:
    for ref in _image_refs(GUIDE_PATH):
        assert (GUIDE_PATH.parent / ref).exists(), ref


def test_registry_asset_directory_has_no_unreferenced_pngs() -> None:
    expected_names = {Path(ref).name for ref in EXPECTED_GUIDE_PNGS}
    actual_names = {path.name for path in ASSET_DIR.glob("*.png")}
    assert actual_names == expected_names


def test_readme_registry_screenshot_exists() -> None:
    refs = _image_refs(README_PATH)
    assert "registry-ui-screenshot.png" in refs
    assert (REPO_ROOT / "registry-ui-screenshot.png").exists()
