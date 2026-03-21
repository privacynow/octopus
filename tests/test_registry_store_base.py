"""Direct contract tests for shared registry-store helper seams."""

import pytest

from app.registry_service.store_base import delivery_kinds_for_registry_scope
from app.registry_service.store_base import registry_scope_for_agent_row


def test_registry_scope_for_agent_row_requires_explicit_scope() -> None:
    with pytest.raises(PermissionError, match="registry_scope"):
        registry_scope_for_agent_row({})


@pytest.mark.parametrize("scope", ["", "  ", "invalid"])
def test_registry_scope_for_agent_row_rejects_invalid_scope(scope: str) -> None:
    with pytest.raises(PermissionError, match="registry_scope"):
        registry_scope_for_agent_row({"registry_scope": scope})


def test_registry_scope_for_agent_row_returns_valid_scope() -> None:
    assert registry_scope_for_agent_row({"registry_scope": "channel"}) == "channel"


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("channel", ("channel_input", "channel_action")),
        ("coordination", ("routed_task", "routed_result")),
        ("full", None),
    ],
)
def test_delivery_kinds_for_registry_scope_maps_valid_scopes(
    scope: str,
    expected: tuple[str, ...] | None,
) -> None:
    assert delivery_kinds_for_registry_scope(scope) == expected


@pytest.mark.parametrize("scope", ["", "  ", "invalid"])
def test_delivery_kinds_for_registry_scope_rejects_invalid_scope(scope: str) -> None:
    with pytest.raises(ValueError, match="registry_scope"):
        delivery_kinds_for_registry_scope(scope)
