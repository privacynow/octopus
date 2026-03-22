"""Registry ref formatting and parsing helpers."""

from __future__ import annotations


def registry_conversation_ref(registry_id: str, conversation_id: str) -> str:
    return f"registry:{registry_id}:conversation:{conversation_id}"


def registry_task_ref(registry_id: str, routed_task_id: str) -> str:
    return f"registry:{registry_id}:task:{routed_task_id}"


def parse_registry_ref(conversation_ref: str) -> tuple[str, str, str] | None:
    if not conversation_ref.startswith("registry:"):
        return None
    parts = conversation_ref.split(":", 3)
    if len(parts) != 4:
        return None
    _, registry_id, ref_kind, external_id = parts
    if ref_kind not in {"conversation", "task"}:
        return None
    if not registry_id or not external_id:
        return None
    return registry_id, ref_kind, external_id


def binding_external_id_for_ref(conversation_ref: str) -> str:
    parsed = parse_registry_ref(conversation_ref)
    if parsed is None:
        return conversation_ref
    return parsed[2]


def qualify_registry_conversation_ref(registry_id: str, conversation_ref: str) -> str:
    if not conversation_ref:
        return ""
    if ":" in conversation_ref:
        return conversation_ref
    return registry_conversation_ref(registry_id, conversation_ref)
