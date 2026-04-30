from pathlib import Path


def test_protocol_docs_link_operator_author_and_openapi_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    operator_guide = (repo_root / "docs" / "operator-protocol-guide.md").read_text(encoding="utf-8")
    author_guide = (repo_root / "docs" / "author-protocol-guide.md").read_text(encoding="utf-8")
    telegram_guide = (repo_root / "docs" / "telegram-user-guide.md").read_text(encoding="utf-8")
    registry_guide = (repo_root / "docs" / "registry-user-guide.md").read_text(encoding="utf-8")
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "[docs/operator-protocol-guide.md](docs/operator-protocol-guide.md)" in readme
    assert "[docs/author-protocol-guide.md](docs/author-protocol-guide.md)" in readme
    assert "[docs/registry-openapi.json](docs/registry-openapi.json)" in readme

    assert "/protocol watch <run_id>" in telegram_guide
    assert "/protocol unwatch <run_id>" in telegram_guide
    assert "[operator-protocol-guide.md](operator-protocol-guide.md)" in telegram_guide

    assert "[operator-protocol-guide.md](operator-protocol-guide.md)" in registry_guide
    assert "[author-protocol-guide.md](author-protocol-guide.md)" in registry_guide

    assert "The generated registry OpenAPI artifact is checked in at:" in operator_guide
    assert "[docs/registry-openapi.json]" in operator_guide
    assert "JSON and YAML are two text views over the same canonical protocol document" in author_guide
    assert "`docs/registry-openapi.json`" in architecture
    assert "`octopus_sdk/protocols/engine.py`" in architecture
    assert "`octopus_sdk/protocol_engine.py`" not in architecture
    assert "`octopus_sdk/protocol_bootstrap.py`" not in architecture


def test_architecture_doc_covers_live_system_boundaries_and_flows() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    required_sections = (
        "## Package Boundaries",
        "## Deployment Topology",
        "## Persistence Model",
        "## Registry Service",
        "## SDK",
        "## Bot Runtime",
        "## Conversations, Direct Assignment, And Delegation",
        "## Protocol Architecture",
        "## Artifacts",
        "## Skills And Guidance",
        "## Registry UI",
        "## Telegram Surface",
        "## Control Plane",
        "## Security And Safety",
        "## Testing And Verification",
        "## Extension Model",
        "## Architecture Rules",
    )
    for section in required_sections:
        assert section in architecture

    required_code_refs = (
        "`octopus_registry/server.py`",
        "`octopus_registry/protocol_http.py`",
        "`octopus_registry/protocol_store.py`",
        "`octopus_registry/ui/js/api.js`",
        "`octopus_sdk/bot_runtime.py`",
        "`octopus_sdk/registry/client.py`",
        "`octopus_sdk/registry/models.py`",
        "`octopus_sdk/protocols/engine.py`",
        "`app/runtime/services.py`",
        "`app/runtime/telegram_ingress.py`",
        "`app/channels/registry/delivery_transport.py`",
        "`app/db/init.sql`",
    )
    for code_ref in required_code_refs:
        assert code_ref in architecture

    assert architecture.count("```mermaid") >= 10
    assert "`/ui/templates` and `/ui/gallery` should not be primary protocol surfaces" in architecture
    assert "Standard protocol authoring must not render operator/internal controls" in architecture
    assert "Tasks are an execution substrate" in architecture
    assert "The shipped runtime is Postgres-backed" in architecture
