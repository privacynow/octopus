from pathlib import Path


def test_protocol_docs_link_operator_author_and_openapi_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    operator_guide = (repo_root / "docs" / "protocol-operator-guide.md").read_text(encoding="utf-8")
    author_guide = (repo_root / "docs" / "protocol-author-guide.md").read_text(encoding="utf-8")
    telegram_guide = (repo_root / "docs" / "telegram-user-guide.md").read_text(encoding="utf-8")
    registry_guide = (repo_root / "docs" / "registry-user-guide.md").read_text(encoding="utf-8")
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "[docs/protocol-operator-guide.md](docs/protocol-operator-guide.md)" in readme
    assert "[docs/protocol-author-guide.md](docs/protocol-author-guide.md)" in readme
    assert "[docs/registry-openapi.json](docs/registry-openapi.json)" in readme

    assert "/protocol watch <run_id>" in telegram_guide
    assert "/protocol unwatch <run_id>" in telegram_guide
    assert "[protocol-operator-guide.md](protocol-operator-guide.md)" in telegram_guide

    assert "[protocol-operator-guide.md](protocol-operator-guide.md)" in registry_guide
    assert "[protocol-author-guide.md](protocol-author-guide.md)" in registry_guide

    assert "The generated registry OpenAPI artifact is checked in at:" in operator_guide
    assert "[docs/registry-openapi.json]" in operator_guide
    assert "JSON and YAML are two text views over the same canonical protocol document" in author_guide
    assert "`docs/registry-openapi.json`" in architecture
