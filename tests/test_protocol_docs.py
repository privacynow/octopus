import re
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
    assert "[SECURITY.md](SECURITY.md)" in readme
    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme
    assert re.search(r"\bplan_(java|auto_protocol)\.md\b", readme) is None
    assert "## Fresh Deployments" in readme
    assert "## Reviewer Path" in readme

    assert "## Mac Setup" in getting_started
    assert "## Windows Setup" in getting_started
    assert "## Linux Or Ubuntu Setup" in getting_started
    assert "## Fresh Public Host Setup" in getting_started
    assert "Python 3.12 through 3.14" in getting_started
    assert ".deploy/bots/.env.example" in getting_started
    assert "`0.0.0.0` is only a listen address" in getting_started
    assert "Diagnose -> Provider auth" in getting_started
    assert "Docker Desktop" in getting_started
    assert "Provider authentication means" in getting_started
    assert "new local agents are created through" in getting_started
    assert "Telegram bot token creates the local agent identity" in getting_started
    assert "Work -> Agents" in getting_started

    assert "## First 20 Minutes" in user_guide
    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in user_guide
    assert "Work -> Conversations" in user_guide
    assert "Build -> Protocols" in user_guide
    assert "## How The Guides Split Responsibilities" in user_guide
    assert "Routing skills" in user_guide
    assert "[PROTOCOLS.md](PROTOCOLS.md)" in user_guide
    assert "[TELEGRAM.md](TELEGRAM.md)" in user_guide
    assert "does not require using Telegram chat" in user_guide
    assert "Good protocols do not rely on one agent producing the final output in one pass" in user_guide

    assert "## Export And Import" in protocol_guide
    assert "## Review Loop Pattern" in protocol_guide
    assert "The highest-quality protocol runs usually have feedback loops." in protocol_guide
    assert "`revise`" in protocol_guide
    assert "Protocol packages are single text documents in JSON or YAML" in protocol_guide
    assert "JSON and YAML are two text views over the same canonical protocol document" in protocol_guide
    assert "`metadata.run_inputs`" in protocol_guide
    assert "Import as copy" in protocol_guide
    assert "Overwrite existing draft" in protocol_guide

    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in operations_guide
    assert "## Deployment State" in operations_guide
    assert "## Fresh Clone Vs Existing Host" in operations_guide
    assert "## Deployment Cleanup Before Public Handoff" in operations_guide
    assert "`Bot workspace cleanup` is the product-safe file cleanup path" in operations_guide
    assert "`Reset registry workspace data` is a Registry-record reset" in operations_guide
    assert "./octopus status" in operations_guide
    assert "./octopus doctor <bot>" in operations_guide
    assert "Diagnose -> Provider auth" in operations_guide
    assert "The generated registry OpenAPI artifact is checked in at:" in operations_guide
    assert "[docs/registry-openapi.json]" in operations_guide

    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in telegram_guide
    assert "creates new local agents as Telegram-backed bot runtimes" in telegram_guide
    assert "/protocol recent" in telegram_guide
    assert "/protocol watch latest|<number|short_id>" in telegram_guide
    assert "/protocol unwatch latest|<number|short_id>" in telegram_guide
    assert "/protocol preview <run> <artifact_number|artifact_key>" in telegram_guide
    assert "[PROTOCOLS.md](PROTOCOLS.md)" in telegram_guide

    assert "[Manufacturing intelligence](manufacturing-intelligence/README.md)" in examples_index
    assert "[Offline CSV analytics](offline-csv-analytics.md)" in examples_index
    manufacturing_walkthrough = repo_root / "docs" / "examples" / "manufacturing-intelligence"
    assert (manufacturing_walkthrough / "README.md").is_file()
    assert (manufacturing_walkthrough / "01-preflight.md").is_file()
    assert (manufacturing_walkthrough / "13-export-import-copy.md").is_file()
    assert (manufacturing_walkthrough / "assets" / "01-protocol-list-wide.png").is_file()
    assert (manufacturing_walkthrough / "assets" / "10-run-started-wide.png").is_file()
    assert (manufacturing_walkthrough / "assets" / "16-artifact-generated-narrow.png").is_file()

    assert "`docs/registry-openapi.json`" in architecture
    assert "`.deploy/` is generated operational state, not source." in architecture
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


def test_publication_metadata_and_live_test_paths_are_portable() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    for rel in (
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "constraints.txt",
        ".github/workflows/ci.yml",
    ):
        assert (repo_root / rel).is_file(), rel

    assert "All rights reserved." in (repo_root / "LICENSE").read_text(encoding="utf-8")
    assert "Bundled browser dependencies" in (repo_root / "NOTICE").read_text(encoding="utf-8")
    assert "Generated `.deploy/` contents are private operational state" in (
        repo_root / "SECURITY.md"
    ).read_text(encoding="utf-8")
    assert "pip install -c constraints.txt" in (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")

    e2e_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo_root / "tests" / "e2e" / "playwright").rglob("*.js")
    )
    assert re.search(r"/Users/[^/\s]+/", e2e_text) is None
    assert re.search(r"lift-and-shift-[a-z0-9-]*bot", e2e_text) is None
    assert "REGISTRY_ENV_FILE" in e2e_text
    assert "PLAYWRIGHT_OUTPUT_DIR" in e2e_text


def test_public_dependency_defaults_are_pinned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    constraints = (repo_root / "constraints.txt").read_text(encoding="utf-8")
    dockerfile = (repo_root / "infra" / "docker" / "Dockerfile.bot").read_text(encoding="utf-8")
    codex_installer = (repo_root / "scripts" / "provider" / "install_provider_codex.sh").read_text(encoding="utf-8")
    claude_installer = (repo_root / "scripts" / "provider" / "install_provider_claude.sh").read_text(encoding="utf-8")

    assert "fastapi==0.135.1" in constraints
    assert "pytest==9.0.2" in constraints
    assert "@openai/codex@0.36.0" in dockerfile
    assert "@openai/codex@0.36.0" in codex_installer
    assert "@anthropic-ai/claude-code@2.1.7" in dockerfile
    assert "@anthropic-ai/claude-code@2.1.7" in claude_installer


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
