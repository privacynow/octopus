"""Product vocabulary and interface-boundary guardrails.

These tests deliberately scan source text. They protect the product decision
that skills are the user-facing work noun, while SDK interfaces and concrete
admin operations describe implementation behavior.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _source_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = ROOT / root
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".js", ".html", ".css", ".md", ".json"}
            and "__pycache__" not in path.parts
        )
    return files


def test_registry_ui_uses_skills_not_capabilities_for_product_copy() -> None:
    allowed_legacy = {
        "octopus_registry/ui/js/components/protocol-workspace.js": (
            "new_capability",
            "new-capability",
        ),
    }
    for path in _source_files("octopus_registry/ui"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        for allowed in allowed_legacy.get(relative, ()):
            text = text.replace(allowed, "")
        assert "capability" not in text.lower(), relative


def test_removed_management_buckets_and_retry_interface_do_not_return() -> None:
    forbidden = (
        "ManagementCapability",
        "MANAGEMENT_OPERATION_CAPABILITIES",
        "required_supported_admin_operation",
        "supported_admin_operation_supported",
        "capability_not_available",
        "mirror_retry",
        '"skill_catalog"',
        '"skill_lifecycle"',
        '"conversation_skills"',
        '"agent_runtime"',
    )
    for path in _source_files("app", "octopus_sdk", "octopus_registry"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "app/db/init.sql":
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} leaked into {relative}"


def test_control_plane_command_uses_interface_operation_and_implementation_terms() -> None:
    model = _read("app/control_plane/models.py")
    assert "admin_interface" in model
    assert "admin_operation" in model
    assert "implementation_ref" in model
    assert "\n    capability:" not in model
    assert "\n    operation:" not in model
    assert "\n    authority_ref:" not in model


def test_control_plane_schema_removes_obsolete_command_columns_after_backfill() -> None:
    schema = _read("app/db/init.sql")
    backfill = schema.index("UPDATE bot_runtime.control_plane_commands")
    cleanup = schema.index("DROP COLUMN IF EXISTS capability")
    assert backfill < cleanup
    assert "DROP COLUMN IF EXISTS operation" in schema
    assert "DROP COLUMN IF EXISTS authority_ref" in schema


def test_agent_status_uses_transport_implementations_and_admin_operations() -> None:
    models = _read("octopus_sdk/registry/models.py")
    assert "transport_implementations" in models
    assert "supported_admin_operations" in models
    assert "channel_capabilities" not in models
    assert "management_capabilities" not in models
