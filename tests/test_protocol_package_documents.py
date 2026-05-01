"""Protocol and skill package document tests."""

import json

from octopus_sdk.content_models import SkillFileRecord
from octopus_sdk.protocols import (
    protocol_package_from_text,
    protocol_package_hash,
    protocol_package_required_skill_names,
    protocol_package_to_text,
    protocol_package_document,
)
from octopus_sdk.skill_packages import (
    SkillPackageRecord,
    parse_skill_package_document,
    skill_document_to_text,
    skill_package_document,
    skill_package_hash,
)
from octopus_sdk.skill_types import SkillRequirement


def _protocol_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "metadata": {
            "slug": "customer-handoff",
            "display_name": "Customer Handoff",
            "description": "Prepare customer handoff materials.",
        },
        "participants": [
            {
                "participant_key": "worker",
                "display_name": "Worker",
                "instructions": "Prepare the package.",
            }
        ],
        "artifacts": [
            {
                "artifact_key": "handoff",
                "display_name": "Handoff",
                "kind": "workspace_file",
                "path": "handoff.md",
                "verify": True,
            }
        ],
        "stages": [
            {
                "stage_key": "prepare",
                "display_name": "Prepare",
                "participant_key": "worker",
                "selector": {
                    "kind": "skill",
                    "value": "customer-handoff-skill",
                },
                "stage_kind": "work",
                "instructions": "Write the handoff.",
                "inputs": [],
                "outputs": ["handoff"],
                "transitions": {"completed": "__complete__"},
                "write_capable": True,
            }
        ],
        "policies": {
            "single_active_writer": True,
            "max_review_rounds": 3,
        },
    }


def _skill_document() -> dict[str, object]:
    return skill_package_document(
        SkillPackageRecord(
            skill_name="customer-handoff-skill",
            display_name="Customer Handoff Skill",
            description="Create customer-ready handoff notes.",
            body="Write concise customer handoff material.",
            skill_kind="prompt",
            requirements=(SkillRequirement(key="CUSTOMER", prompt="Customer name"),),
            files=(
                SkillFileRecord(
                    relative_path="templates/handoff.md",
                    content_text="# Handoff\n",
                    content_type="text/markdown",
                ),
            ),
        )
    )


def test_skill_package_json_and_yaml_round_trip_to_same_hash() -> None:
    document = _skill_document()
    json_text = skill_document_to_text(document, format="json")
    yaml_text = skill_document_to_text(document, format="yaml")

    json_package = parse_skill_package_document(json_text, format="json")
    yaml_package = parse_skill_package_document(yaml_text, format="yaml")

    assert json_package.skill_name == "customer-handoff-skill"
    assert yaml_package.skill_name == "customer-handoff-skill"
    assert skill_package_hash(json_package) == skill_package_hash(yaml_package)


def test_protocol_package_json_and_yaml_round_trip_to_same_hash() -> None:
    package = protocol_package_document(
        protocol=_protocol_document(),
        skills=[_skill_document()],
        bindings={"source_agents": [], "stage_bindings": []},
    )

    json_text = protocol_package_to_text(package, format="json")
    yaml_text = protocol_package_to_text(package, format="yaml")
    json_package = protocol_package_from_text(json_text, format="json")
    yaml_package = protocol_package_from_text(yaml_text, format="yaml")

    assert protocol_package_required_skill_names(json_package.protocol) == ("customer-handoff-skill",)
    assert protocol_package_hash(json_package) == protocol_package_hash(yaml_package)


def test_protocol_package_rejects_missing_required_skill() -> None:
    package = protocol_package_document(
        protocol=_protocol_document(),
        skills=[_skill_document()],
    )
    payload = package.model_dump(mode="json")
    payload["protocol"]["stages"][0]["selector"]["value"] = "missing-skill"

    try:
        protocol_package_from_text(json.dumps(payload), format="json")
    except ValueError as exc:
        assert "missing-skill" in str(exc)
    else:
        raise AssertionError("Expected missing embedded skill to be rejected.")
