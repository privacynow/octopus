from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, get_args, get_origin, get_type_hints

from octopus_registry.protocol_store import ProtocolPostgresAdapter
from octopus_registry.store_base import AbstractRegistryStore
from octopus_registry.store_postgres import RegistryPostgresStore


def _contains_forbidden_boundary(annotation: object) -> bool:
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is dict and args == (str, Any):
        return True
    if origin in {dict, list, tuple, set, frozenset, Mapping}:
        return any(_contains_forbidden_boundary(arg) for arg in args)
    return any(_contains_forbidden_boundary(arg) for arg in args)


def _public_protocol_methods() -> list[str]:
    return [
        name
        for name, value in AbstractRegistryStore.__dict__.items()
        if inspect.isfunction(value) and not name.startswith("_")
    ]


def test_abstract_registry_store_public_methods_use_typed_sdk_boundaries() -> None:
    for method_name in _public_protocol_methods():
        hints = get_type_hints(getattr(AbstractRegistryStore, method_name))
        assert hints, f"missing type hints on AbstractRegistryStore.{method_name}"
        offenders = [
            name
            for name, annotation in hints.items()
            if _contains_forbidden_boundary(annotation)
        ]
        assert not offenders, (
            f"AbstractRegistryStore.{method_name} still exposes forbidden "
            f"boundary types in {', '.join(offenders)}"
        )


def test_registry_store_implementations_match_typed_public_contract() -> None:
    for method_name in _public_protocol_methods():
        method = getattr(RegistryPostgresStore, method_name, None)
        assert method is not None, f"{RegistryPostgresStore.__name__}.{method_name} missing"
        hints = get_type_hints(method)
        assert hints, f"missing type hints on {RegistryPostgresStore.__name__}.{method_name}"
        offenders = [
            name
            for name, annotation in hints.items()
            if _contains_forbidden_boundary(annotation)
        ]
        assert not offenders, (
            f"{RegistryPostgresStore.__name__}.{method_name} still exposes forbidden "
            f"boundary types in {', '.join(offenders)}"
        )


def test_registry_store_protocol_delegates_match_adapter_signatures() -> None:
    delegated_methods = [
        "run_protocol_maintenance",
        "list_protocols",
        "get_protocol_template",
        "list_protocol_templates",
        "get_protocol_authoring_options",
        "get_protocol",
        "get_protocol_version",
        "parse_protocol_document_text",
        "export_protocol_draft",
        "diff_protocol_draft",
        "save_protocol_draft",
        "create_protocol_draft",
        "delete_protocol",
        "validate_protocol",
        "publish_protocol",
        "publish_protocol_template",
        "archive_protocol",
        "list_protocol_runs",
        "list_protocol_issues",
        "create_protocol_run",
        "get_protocol_run",
        "get_protocol_run_participants",
        "get_protocol_run_artifacts",
        "get_protocol_run_timeline",
        "export_protocol_run",
        "act_on_protocol_run",
    ]

    def _signature_shape(method) -> list[tuple[str, inspect._ParameterKind, str]]:
        signature = inspect.signature(method)
        shape: list[tuple[str, inspect._ParameterKind, str]] = []
        for name, parameter in signature.parameters.items():
            if name == "self":
                continue
            default = "<required>" if parameter.default is inspect._empty else repr(parameter.default)
            shape.append((name, parameter.kind, default))
        return shape

    for method_name in delegated_methods:
        wrapper = getattr(RegistryPostgresStore, method_name, None)
        adapter = getattr(ProtocolPostgresAdapter, method_name, None)
        assert wrapper is not None, f"{RegistryPostgresStore.__name__}.{method_name} missing"
        assert adapter is not None, f"{ProtocolPostgresAdapter.__name__}.{method_name} missing"
        assert _signature_shape(wrapper) == _signature_shape(adapter), (
            f"{RegistryPostgresStore.__name__}.{method_name} drifted from "
            f"{ProtocolPostgresAdapter.__name__}.{method_name}"
        )
