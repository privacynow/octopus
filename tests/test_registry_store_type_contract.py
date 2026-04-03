from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, get_args, get_origin, get_type_hints

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
