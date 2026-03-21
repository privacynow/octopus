"""Contract tests for registry ref helper invariants."""

from app.channels.registry.refs import (
    parse_registry_ref,
    qualify_registry_conversation_ref,
    registry_ref_external_id,
)


def test_qualify_registry_conversation_ref_wraps_bare_id() -> None:
    result = qualify_registry_conversation_ref("prod", "conv-abc-123")

    assert result == "registry:prod:conversation:conv-abc-123"


def test_qualify_registry_conversation_ref_returns_empty_for_empty() -> None:
    assert qualify_registry_conversation_ref("prod", "") == ""


def test_qualify_registry_conversation_ref_preserves_telegram_ref() -> None:
    qualified_ref = "telegram:bot123:12345"

    assert qualify_registry_conversation_ref("prod", qualified_ref) == qualified_ref


def test_qualify_registry_conversation_ref_preserves_registry_conversation_ref() -> None:
    qualified_ref = "registry:prod:conversation:conv-1"

    assert qualify_registry_conversation_ref("any-registry", qualified_ref) == qualified_ref


def test_qualify_registry_conversation_ref_preserves_registry_task_ref() -> None:
    qualified_ref = "registry:prod:task:task-1"

    assert qualify_registry_conversation_ref("any-registry", qualified_ref) == qualified_ref


def test_qualify_registry_conversation_ref_preserves_future_surface_ref() -> None:
    qualified_ref = "slack:eng:C0123ABC"

    assert qualify_registry_conversation_ref("prod", qualified_ref) == qualified_ref


def test_qualify_registry_conversation_ref_preserves_second_future_surface_ref() -> None:
    qualified_ref = "whatsapp:biz:+1234567890"

    assert qualify_registry_conversation_ref("prod", qualified_ref) == qualified_ref


def test_parse_registry_ref_parses_conversation_ref() -> None:
    result = parse_registry_ref("registry:prod:conversation:conv-1")

    assert result == ("prod", "conversation", "conv-1")


def test_parse_registry_ref_parses_task_ref() -> None:
    result = parse_registry_ref("registry:prod:task:task-1")

    assert result == ("prod", "task", "task-1")


def test_parse_registry_ref_returns_none_for_non_registry_ref() -> None:
    assert parse_registry_ref("telegram:bot:123") is None


def test_parse_registry_ref_returns_none_for_bare_id() -> None:
    assert parse_registry_ref("conv-abc") is None


def test_parse_registry_ref_returns_none_for_malformed_registry_ref() -> None:
    assert parse_registry_ref("registry:prod:invalid") is None


def test_registry_ref_external_id_returns_parsed_external_id() -> None:
    assert registry_ref_external_id("registry:prod:conversation:conv-1") == "conv-1"


def test_registry_ref_external_id_returns_original_for_unknown_ref() -> None:
    assert registry_ref_external_id("slack:eng:C0123ABC") == "slack:eng:C0123ABC"
