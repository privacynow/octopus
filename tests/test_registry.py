"""Tests for registry index parsing, artifact handling, and import integration."""

import http.server
import json
import tarfile
import tempfile
import threading
from pathlib import Path

import pytest

import app.content_store as content_store_mod
from app.content_store import get_content_store, init_content_store_for_config
from app.registry import (
    RegistrySkill,
    download_artifact,
    fetch_index,
    search_index,
    skill_artifact_digest,
)
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.storage import close_db, ensure_data_dirs
from tests.support.config_support import make_config


def _make_skill_tarball(skill_dir: Path, tarball_path: Path) -> None:
    with tarfile.open(tarball_path, "w:gz") as tf:
        for item in skill_dir.iterdir():
            tf.add(item, arcname=item.name)


def _serve_dir(directory: str) -> tuple[http.server.HTTPServer, str]:
    handler = http.server.SimpleHTTPRequestHandler
    try:
        server = http.server.HTTPServer(
            ("127.0.0.1", 0),
            lambda *args, directory=directory, **kwargs: handler(*args, directory=directory, **kwargs),
        )
    except PermissionError as exc:
        pytest.skip(f"Local HTTPServer bind not permitted in this environment: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _init_runtime_content(tmp_path: Path, *, registry_url: str):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url=registry_url)
    init_content_store_for_config(cfg)
    return cfg, data_dir


def test_fetch_index_valid():
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
                "incomplete": {"display_name": "Missing Digest"},
            },
        }
        index_path = Path(tmp) / "index.json"
        index_path.write_text(json.dumps(index_data), encoding="utf-8")

        server, base_url = _serve_dir(tmp)
        try:
            result = fetch_index(f"{base_url}/index.json")
            assert "test-skill" in result
            assert result["test-skill"].display_name == "Test Skill"
            assert result["test-skill"].publisher == "test-org"
            assert result["test-skill"].digest == "abc123"
            assert "incomplete" not in result
        finally:
            server.shutdown()


def test_fetch_index_bad_version():
    with tempfile.TemporaryDirectory() as tmp:
        index_path = Path(tmp) / "index.json"
        index_path.write_text(json.dumps({"version": 99, "skills": {}}), encoding="utf-8")

        server, base_url = _serve_dir(tmp)
        try:
            with pytest.raises(ValueError):
                fetch_index(f"{base_url}/index.json")
        finally:
            server.shutdown()


def test_fetch_index_not_json():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "index.json").write_text("not json at all", encoding="utf-8")
        server, base_url = _serve_dir(tmp)
        try:
            with pytest.raises(json.JSONDecodeError):
                fetch_index(f"{base_url}/index.json")
        finally:
            server.shutdown()


def test_search_index():
    index = {
        "deploy": RegistrySkill("deploy", "Deploy Helper", "Deploy to production", "1.0", "pub", "d1", "url1"),
        "lint": RegistrySkill("lint", "Linter", "Code quality checks", "1.0", "pub", "d2", "url2"),
    }
    assert [item.name for item in search_index(index, "deploy")] == ["deploy"]
    assert [item.name for item in search_index(index, "quality")] == ["lint"]
    assert search_index(index, "xyz") == []


def test_download_artifact_valid_and_digest_stable():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        skill_src = tmp_path / "src"
        skill_src.mkdir()
        (skill_src / "skill.md").write_text("---\ndisplay_name: Test\n---\nInstructions here", encoding="utf-8")
        (skill_src / "claude.yaml").write_text("allowed_tools: []\n", encoding="utf-8")
        expected_digest = skill_artifact_digest(skill_src)

        tarball = tmp_path / "skill.tar.gz"
        _make_skill_tarball(skill_src, tarball)

        server, base_url = _serve_dir(tmp)
        try:
            dest = tmp_path / "extracted"
            download_artifact(f"{base_url}/skill.tar.gz", dest)
            assert (dest / "skill.md").exists()
            assert (dest / "claude.yaml").exists()
            assert skill_artifact_digest(dest) == expected_digest
        finally:
            server.shutdown()


def test_download_artifact_no_skill_md():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "src"
        src.mkdir()
        (src / "readme.txt").write_text("not a skill", encoding="utf-8")

        tarball = tmp_path / "bad.tar.gz"
        _make_skill_tarball(src, tarball)

        server, base_url = _serve_dir(tmp)
        try:
            with pytest.raises(ValueError):
                download_artifact(f"{base_url}/bad.tar.gz", tmp_path / "extracted")
        finally:
            server.shutdown()


def test_install_from_registry_success(tmp_path: Path):
    skill_src = tmp_path / "skill_src"
    skill_src.mkdir()
    (skill_src / "skill.md").write_text(
        "---\nname: reg-test\ndisplay_name: Registry Test\ndescription: registry fixture\n---\n\nDo things\n",
        encoding="utf-8",
    )
    expected_digest = skill_artifact_digest(skill_src)
    tarball = tmp_path / "skill.tar.gz"
    _make_skill_tarball(skill_src, tarball)
    index_data = {
        "version": 1,
        "skills": {
            "reg-test": {
                "display_name": "Registry Test",
                "description": "registry fixture",
                "version": "1.0.0",
                "publisher": "test-pub",
                "digest": expected_digest,
                "artifact_url": "ARTIFACT_URL_PLACEHOLDER",
            }
        },
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index_data), encoding="utf-8")

    server, base_url = _serve_dir(str(tmp_path))
    try:
        index_data["skills"]["reg-test"]["artifact_url"] = f"{base_url}/skill.tar.gz"
        index_path.write_text(json.dumps(index_data), encoding="utf-8")
        registry_url = f"{base_url}/index.json"
        cfg, data_dir = _init_runtime_content(tmp_path, registry_url=registry_url)
        try:
            result = get_skill_import_service().install_from_registry("reg-test", cfg.registry_url)
            assert result.ok is True

            resolved = get_skill_catalog_service().resolve_track("reg-test")
            assert resolved is not None
            assert resolved.source_kind == "imported"
            assert resolved.source_uri == f"{registry_url}#reg-test"
            assert resolved.revision.instruction_body == "Do things"
            assert any(item.slug == "reg-test" for item in get_content_store().list_skill_summaries())
        finally:
            close_db(data_dir)
            content_store_mod.reset_for_test()
    finally:
        server.shutdown()


def test_install_from_registry_digest_mismatch(tmp_path: Path):
    skill_src = tmp_path / "skill_src"
    skill_src.mkdir()
    (skill_src / "skill.md").write_text(
        "---\nname: bad-digest\ndisplay_name: Bad\n---\n\nWrong digest\n",
        encoding="utf-8",
    )
    tarball = tmp_path / "skill.tar.gz"
    _make_skill_tarball(skill_src, tarball)
    index_path = tmp_path / "index.json"
    index_data = {
        "version": 1,
        "skills": {
            "bad-digest": {
                "display_name": "Bad",
                "description": "Wrong digest",
                "version": "1.0.0",
                "publisher": "evil",
                "digest": "0" * 64,
                "artifact_url": "ARTIFACT_URL_PLACEHOLDER",
            }
        },
    }
    index_path.write_text(json.dumps(index_data), encoding="utf-8")

    server, base_url = _serve_dir(str(tmp_path))
    try:
        index_data["skills"]["bad-digest"]["artifact_url"] = f"{base_url}/skill.tar.gz"
        index_path.write_text(json.dumps(index_data), encoding="utf-8")
        registry_url = f"{base_url}/index.json"
        cfg, data_dir = _init_runtime_content(tmp_path, registry_url=registry_url)
        try:
            before = {item.slug for item in get_content_store().list_skill_summaries()}
            result = get_skill_import_service().install_from_registry("bad-digest", cfg.registry_url)
            assert result.ok is False
            assert result.message == "Could not fetch skill from registry. Try again later."
            assert get_skill_catalog_service().resolve_track("bad-digest") is None
            assert get_content_store().list_skill_tracks("bad-digest") == []
            assert {item.slug for item in get_content_store().list_skill_summaries()} == before
        finally:
            close_db(data_dir)
            content_store_mod.reset_for_test()
    finally:
        server.shutdown()
