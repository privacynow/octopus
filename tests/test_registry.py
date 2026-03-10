"""Tests for skill registry — index parsing, artifact handling, store integration."""

import http.server
import json
import os
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path

from app.registry import RegistrySkill, fetch_index, search_index, download_artifact
from app.store import hash_directory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_tarball(skill_dir: Path, tarball_path: Path) -> None:
    """Create a .tar.gz from a skill directory."""
    with tarfile.open(tarball_path, "w:gz") as tf:
        for item in skill_dir.iterdir():
            tf.add(item, arcname=item.name)


def _serve_dir(directory: str) -> tuple[http.server.HTTPServer, str]:
    """Start a simple HTTP server serving files from directory. Returns (server, base_url)."""
    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.HTTPServer(("127.0.0.1", 0), lambda *args, directory=directory, **kwargs: handler(*args, directory=directory, **kwargs))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Index parsing
# ---------------------------------------------------------------------------

def test_fetch_index_valid():
    """Parse a well-formed registry index."""
    with tempfile.TemporaryDirectory() as tmp:
        index_data = {
            "version": 1,
            "skills": {
                "test-skill": {
                    "display_name": "Test Skill",
                    "description": "A test skill",
                    "version": "1.0.0",
                    "publisher": "test-org",
                    "digest": "abc123",
                    "artifact_url": "https://example.com/test-skill.tar.gz",
                },
                "incomplete": {
                    "display_name": "Missing Digest",
                },
            },
        }
        index_path = Path(tmp) / "index.json"
        index_path.write_text(json.dumps(index_data))

        server, base_url = _serve_dir(tmp)
        try:
            result = fetch_index(f"{base_url}/index.json")
            assert "test-skill" in result
            assert result["test-skill"].display_name == "Test Skill"
            assert result["test-skill"].publisher == "test-org"
            assert result["test-skill"].digest == "abc123"
            # incomplete skill should be skipped (no digest)
            assert "incomplete" not in result
        finally:
            server.shutdown()


def test_fetch_index_bad_version():
    """Reject index with unsupported version."""
    with tempfile.TemporaryDirectory() as tmp:
        index_path = Path(tmp) / "index.json"
        index_path.write_text(json.dumps({"version": 99, "skills": {}}))

        server, base_url = _serve_dir(tmp)
        try:
            try:
                fetch_index(f"{base_url}/index.json")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "version" in str(e).lower()
        finally:
            server.shutdown()


def test_fetch_index_not_json():
    """Reject non-JSON response."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "index.json").write_text("not json at all")
        server, base_url = _serve_dir(tmp)
        try:
            try:
                fetch_index(f"{base_url}/index.json")
                assert False, "Should have raised"
            except json.JSONDecodeError:
                pass
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_index():
    """Search matches name and description."""
    index = {
        "deploy": RegistrySkill("deploy", "Deploy Helper", "Deploy to production", "1.0", "pub", "d1", "url1"),
        "lint": RegistrySkill("lint", "Linter", "Code quality checks", "1.0", "pub", "d2", "url2"),
    }
    results = search_index(index, "deploy")
    assert len(results) == 1
    assert results[0].name == "deploy"

    # Search by description
    results2 = search_index(index, "quality")
    assert len(results2) == 1
    assert results2[0].name == "lint"

    # No match
    assert search_index(index, "xyz") == []


# ---------------------------------------------------------------------------
# Artifact download and extraction
# ---------------------------------------------------------------------------

def test_download_artifact_valid():
    """Download and extract a valid skill tarball."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create a fake skill directory
        skill_src = tmp_path / "src"
        skill_src.mkdir()
        (skill_src / "skill.md").write_text("---\ndisplay_name: Test\n---\nInstructions here")
        (skill_src / "claude.yaml").write_text("allowed_tools: []\n")

        # Create tarball
        tarball = tmp_path / "skill.tar.gz"
        _make_skill_tarball(skill_src, tarball)

        # Serve
        server, base_url = _serve_dir(tmp)
        try:
            dest = tmp_path / "extracted"
            download_artifact(f"{base_url}/skill.tar.gz", dest)
            assert (dest / "skill.md").exists()
            assert (dest / "claude.yaml").exists()
        finally:
            server.shutdown()


def test_download_artifact_no_skill_md():
    """Reject artifact that lacks skill.md."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create dir without skill.md
        src = tmp_path / "src"
        src.mkdir()
        (src / "readme.txt").write_text("not a skill")

        tarball = tmp_path / "bad.tar.gz"
        _make_skill_tarball(src, tarball)

        server, base_url = _serve_dir(tmp)
        try:
            dest = tmp_path / "extracted"
            try:
                download_artifact(f"{base_url}/bad.tar.gz", dest)
                assert False, "Should have raised"
            except ValueError as e:
                assert "skill.md" in str(e)
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# Store integration: install_from_registry
# ---------------------------------------------------------------------------

def test_install_from_registry_success():
    """Install a registry skill: download, verify digest, create ref."""
    from app.store import (
        install_from_registry, read_ref, object_dir,
        ensure_managed_dirs, OBJECTS_DIR, REFS_DIR, _store_lock, gc,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create skill source
        skill_src = tmp_path / "skill_src"
        skill_src.mkdir()
        (skill_src / "skill.md").write_text("---\ndisplay_name: Registry Test\n---\nDo things")

        # Create tarball
        tarball = tmp_path / "skill.tar.gz"
        _make_skill_tarball(skill_src, tarball)

        # Compute expected digest by extracting the tarball (same as install will do)
        verify_dir = tmp_path / "verify"
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(verify_dir, filter="data")
        expected_digest = hash_directory(verify_dir)

        server, base_url = _serve_dir(tmp)
        try:
            ensure_managed_dirs()
            reg_skill = RegistrySkill(
                name="reg-test",
                display_name="Registry Test",
                description="A registry skill",
                version="1.0.0",
                publisher="test-pub",
                digest=expected_digest,
                artifact_url=f"{base_url}/skill.tar.gz",
            )
            ok, msg = install_from_registry("reg-test", reg_skill)
            assert ok, msg
            assert "installed" in msg

            # Verify ref was created
            ref = read_ref("reg-test")
            assert ref is not None
            assert ref.source == "registry"
            assert ref.publisher == "test-pub"
            assert ref.version == "1.0.0"
            assert ref.digest == expected_digest

            # Verify object exists
            obj = object_dir(ref.digest)
            assert obj.is_dir()
            assert (obj / "skill.md").exists()
        finally:
            server.shutdown()
            # Cleanup managed store refs/objects
            ref_file = REFS_DIR / "reg-test.json"
            if ref_file.exists():
                ref_file.unlink()
            obj_dir = OBJECTS_DIR / expected_digest
            if obj_dir.exists():
                shutil.rmtree(obj_dir)


def test_install_from_registry_digest_mismatch():
    """Reject artifact with wrong digest and leave no orphan objects."""
    from app.store import install_from_registry, ensure_managed_dirs, OBJECTS_DIR, read_ref

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        skill_src = tmp_path / "skill_src"
        skill_src.mkdir()
        (skill_src / "skill.md").write_text("---\ndisplay_name: Bad\n---\nWrong digest")

        tarball = tmp_path / "skill.tar.gz"
        _make_skill_tarball(skill_src, tarball)

        # Compute the real digest so we can check it does NOT appear in objects/
        verify_dir = tmp_path / "verify"
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(verify_dir, filter="data")
        real_digest = hash_directory(verify_dir)

        server, base_url = _serve_dir(tmp)
        try:
            ensure_managed_dirs()
            objects_before = set(OBJECTS_DIR.iterdir()) if OBJECTS_DIR.is_dir() else set()
            reg_skill = RegistrySkill(
                name="bad-digest",
                display_name="Bad",
                description="Wrong digest",
                version="1.0",
                publisher="evil",
                digest="0000000000000000000000000000000000000000000000000000000000000000",
                artifact_url=f"{base_url}/skill.tar.gz",
            )
            ok, msg = install_from_registry("bad-digest", reg_skill)
            assert not ok
            assert "mismatch" in msg.lower()

            # No ref should have been written
            assert read_ref("bad-digest") is None

            # No new objects should have been created by this install attempt
            objects_after = set(OBJECTS_DIR.iterdir()) if OBJECTS_DIR.is_dir() else set()
            new_objects = objects_after - objects_before
            assert len(new_objects) == 0, (
                f"Digest mismatch should not leave orphan objects, found: {new_objects}"
            )
        finally:
            server.shutdown()
