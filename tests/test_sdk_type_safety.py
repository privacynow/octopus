from __future__ import annotations

import re
from typing import Any, get_type_hints
from dataclasses import MISSING, fields
from pathlib import Path

from octopus_sdk.bot_runtime import BotRuntime, BotServicesPort
from octopus_sdk.execution import ExecutionChannelMetadata, TransportIdentity
from octopus_sdk.transport import TransportEgress, TransportImplementation


def _contains_any(value: object) -> bool:
    if value is Any:
        return True
    args = getattr(value, "__args__", ())
    return any(_contains_any(arg) for arg in args)


def test_octopus_sdk_has_no_any_or_dict_any_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sdk_root = repo_root / "octopus_sdk"
    forbidden_patterns = (
        re.compile(r"\bAny\b"),
        re.compile(r"dict\s*\[\s*str\s*,\s*Any\s*\]"),
        re.compile(r"Callable\s*\[\s*\.\.\.\s*,\s*Any\s*\]"),
        re.compile(r'extra\s*=\s*"allow"'),
        re.compile(r"extra\s*=\s*'allow'"),
    )
    for path in sorted(sdk_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern.search(text) is None, f"{pattern.pattern} still present in {path}"


def test_required_transport_identity_fields_have_no_empty_string_defaults() -> None:
    required = {
        "conversation_key",
        "origin_channel",
        "actor",
        "external_conversation_ref",
        "target_agent_id",
        "conversation_ref",
        "routed_task_id",
        "authority_ref",
    }
    field_map = {field.name: field for field in fields(TransportIdentity)}
    for name in required:
        assert name in field_map
        assert field_map[name].default is MISSING, f"{name} still has a default"


def test_required_execution_channel_metadata_fields_have_no_empty_string_defaults() -> None:
    required = {
        "conversation_key",
        "origin_channel",
        "actor",
        "message_conversation_ref",
        "routed_task_id",
        "authority_ref",
        "external_conversation_ref",
        "target_agent_id",
    }
    field_map = {field.name: field for field in fields(ExecutionChannelMetadata)}
    for name in required:
        assert name in field_map
        assert field_map[name].default is MISSING, f"{name} still has a default"


def test_sdk_composition_classes_have_no_any_annotations() -> None:
    runtime_hints = get_type_hints(BotRuntime)
    assert runtime_hints["transport"] is TransportImplementation
    assert not any(_contains_any(hint) for hint in runtime_hints.values())

    services_hints = get_type_hints(BotServicesPort)
    assert not any(_contains_any(hint) for hint in services_hints.values())


def test_transport_egress_operator_experience_methods_are_abstract() -> None:
    required = {
        "send_recovery_notice",
        "show_foreign_setup",
        "show_setup_prompt",
        "send_retry_prompt",
        "send_approval_prompt",
        "send_formatted_reply",
        "send_directed_artifacts",
        "send_compact_reply",
        "propose_delegation_plan",
    }
    abstract_methods = getattr(TransportEgress, "__abstractmethods__", set())
    for name in required:
        assert name in abstract_methods, f"{name} is not abstract on TransportEgress"


def test_transport_egress_binding_methods_are_abstract() -> None:
    abstract_methods = getattr(TransportEgress, "__abstractmethods__", set())
    for name in {"bind", "sync_binding"}:
        assert name in abstract_methods, f"{name} is not abstract on TransportEgress"


def test_transport_egress_progress_methods_are_abstract() -> None:
    abstract_methods = getattr(TransportEgress, "__abstractmethods__", set())
    for name in {"send_status", "typing_target"}:
        assert name in abstract_methods, f"{name} is not abstract on TransportEgress"


def test_sdk_protocol_test_doubles_use_typed_boundary_signatures() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    targeted = (
        repo_root / "tests" / "test_channel_dispatcher.py",
        repo_root / "tests" / "test_runtime_dispatch_boundary.py",
        repo_root / "tests" / "test_sdk_reference_transport.py",
    )
    forbidden_patterns = (
        re.compile(r"def build_egress\(.*config:\s*Any"),
        re.compile(r"def can_build_egress\(.*config:\s*Any"),
        re.compile(r"async def health_check\(self\)\s*->\s*dict\s*\[\s*str\s*,\s*Any\s*\]"),
        re.compile(r"def typing_target\(self\)\s*:"),
    )
    for path in targeted:
        text = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern.search(text) is None, f"{pattern.pattern} still present in {path}"


def test_sdk_boundary_tests_do_not_pass_raw_dicts_into_sdk_records() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    forbidden_patterns = (
        re.compile(r"default_session\([^,\n]+,\s*\{"),
        re.compile(r"RunContext\([\s\S]{0,300}?provider_config\s*=\s*\{"),
        re.compile(r"RunContext\([\s\S]{0,300}?credential_env\s*=\s*\{"),
        re.compile(r"ProviderGuidancePreview\([\s\S]{0,300}?provider_config\s*=\s*\{"),
        re.compile(r"RunResult\([\s\S]{0,300}?provider_state_updates\s*=\s*\{"),
        re.compile(r"RunResult\([\s\S]{0,300}?denials\s*=\s*\[\s*\{"),
        re.compile(r"\.run\(\s*\{"),
    )
    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        for pattern in forbidden_patterns:
            assert pattern.search(text) is None, f"{pattern.pattern} still present in {path}"


def test_registry_store_protocol_uses_no_any_or_dict_any_signatures() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    store_protocol_path = repo_root / "app" / "registry_service" / "store_base.py"
    text = store_protocol_path.read_text()
    forbidden_patterns = (
        re.compile(r"typing import .*Any"),
        re.compile(r"\bAny\b"),
        re.compile(r"dict\s*\[\s*str\s*,\s*Any\s*\]"),
        re.compile(r"Mapping\s*\[\s*str\s*,\s*Any\s*\]"),
        re.compile(r"list\s*\[\s*dict\s*\[\s*str\s*,\s*Any\s*\]\s*\]"),
    )
    for pattern in forbidden_patterns:
        assert pattern.search(text) is None, f"{pattern.pattern} still present in {store_protocol_path}"
