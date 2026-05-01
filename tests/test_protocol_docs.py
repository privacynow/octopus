from pathlib import Path


def test_public_docs_are_progressive_and_link_current_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    getting_started = (repo_root / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
    user_guide = (repo_root / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    protocol_guide = (repo_root / "docs" / "PROTOCOLS.md").read_text(encoding="utf-8")
    operations_guide = (repo_root / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    telegram_guide = (repo_root / "docs" / "TELEGRAM.md").read_text(encoding="utf-8")
    examples_index = (repo_root / "docs" / "examples" / "README.md").read_text(encoding="utf-8")
    architecture = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)" in readme
    assert "[docs/USER_GUIDE.md](docs/USER_GUIDE.md)" in readme
    assert "[docs/PROTOCOLS.md](docs/PROTOCOLS.md)" in readme
    assert "[docs/OPERATIONS.md](docs/OPERATIONS.md)" in readme
    assert "[docs/TELEGRAM.md](docs/TELEGRAM.md)" in readme
    assert "[docs/examples/README.md](docs/examples/README.md)" in readme
    assert "[docs/SDK_BOT_DEVELOPMENT.md](docs/SDK_BOT_DEVELOPMENT.md)" in readme
    assert "[docs/SKILLS_MODEL.md](docs/SKILLS_MODEL.md)" in readme
    assert "[docs/PROTOCOL_ASSIGNMENT_AUDIT.md](docs/PROTOCOL_ASSIGNMENT_AUDIT.md)" in readme
    assert "[docs/registry-openapi.json](docs/registry-openapi.json)" in readme

    assert "## Mac Setup" in getting_started
    assert "## Windows Setup" in getting_started
    assert "## Linux Or Ubuntu Setup" in getting_started
    assert "Diagnose -> Provider auth" in getting_started
    assert "Docker Desktop" in getting_started
    assert "Provider authentication means" in getting_started
    assert "Work -> Agents" in getting_started

    assert "## First 20 Minutes" in user_guide
    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in user_guide
    assert "Work -> Conversations" in user_guide
    assert "Build -> Protocols" in user_guide
    assert "Routing skills" in user_guide
    assert "[PROTOCOLS.md](PROTOCOLS.md)" in user_guide
    assert "[TELEGRAM.md](TELEGRAM.md)" in user_guide

    assert "## Export And Import" in protocol_guide
    assert "Protocol packages are single text documents in JSON or YAML" in protocol_guide
    assert "JSON and YAML are two text views over the same canonical protocol document" in protocol_guide
    assert "`metadata.run_inputs`" in protocol_guide
    assert "Import as copy" in protocol_guide
    assert "Overwrite existing draft" in protocol_guide

    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in operations_guide
    assert "./octopus status" in operations_guide
    assert "./octopus doctor <bot>" in operations_guide
    assert "Diagnose -> Provider auth" in operations_guide
    assert "The generated registry OpenAPI artifact is checked in at:" in operations_guide
    assert "[docs/registry-openapi.json]" in operations_guide

    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in telegram_guide
    assert "/protocol recent" in telegram_guide
    assert "/protocol watch latest|<number|short_id>" in telegram_guide
    assert "/protocol unwatch latest|<number|short_id>" in telegram_guide
    assert "/protocol preview <run> <artifact_number|artifact_key>" in telegram_guide
    assert "[PROTOCOLS.md](PROTOCOLS.md)" in telegram_guide

    assert "[Manufacturing intelligence](manufacturing-intelligence.md)" in examples_index
    assert "[Offline CSV analytics](offline-csv-analytics.md)" in examples_index

    assert "`docs/registry-openapi.json`" in architecture
    assert "`docs/GETTING_STARTED.md`" in architecture
    assert "`octopus_sdk/protocols/engine.py`" in architecture
    assert "kind = \"octopus.protocol_package\"" in architecture
    assert "Protocol package export/import flow" in architecture
    assert "`docs/USER_GUIDE.md`" in architecture
    assert "`docs/PROTOCOLS.md`" in architecture
    assert "`docs/SDK_BOT_DEVELOPMENT.md`" in architecture
    assert "`docs/SKILLS_MODEL.md`" in architecture
    assert "`docs/PROTOCOL_ASSIGNMENT_AUDIT.md`" in architecture
    assert "`octopus_sdk/protocol_engine.py`" not in architecture
    assert "`octopus_sdk/protocol_bootstrap.py`" not in architecture


def test_top_level_doc_names_are_consistent() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    docs_dir = repo_root / "docs"

    expected_top_level = {
        "ARCHITECTURE.md",
        "GETTING_STARTED.md",
        "OPERATIONS.md",
        "PROTOCOLS.md",
        "PROTOCOL_ASSIGNMENT_AUDIT.md",
        "SDK_BOT_DEVELOPMENT.md",
        "SKILLS_MODEL.md",
        "TELEGRAM.md",
        "USER_GUIDE.md",
    }
    actual_top_level = {path.name for path in docs_dir.glob("*.md")}

    assert actual_top_level == expected_top_level
    assert all(path.stem == path.stem.upper() for path in docs_dir.glob("*.md"))
    assert (docs_dir / "registry-openapi.json").is_file()
    assert (docs_dir / "examples" / "README.md").is_file()


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
        "## Documentation Architecture",
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
