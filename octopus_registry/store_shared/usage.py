from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from octopus_sdk.registry.models import UsageSummaryRecord


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def provider_reports_cost(metadata: Mapping[str, Any] | None) -> bool:
    provider = str((metadata or {}).get("provider") or "").strip().lower()
    if provider == "codex":
        return False
    if provider:
        return True
    return float_value((metadata or {}).get("cost_usd")) > 0.0


def empty_usage_total() -> dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_prompt_tokens": 0,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": False,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.0,
        "cost_available": False,
    }


def _usage_row_parts(row: UsageSummaryRecord | Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any]]:
    if isinstance(row, UsageSummaryRecord):
        return row.conversation_id, row.title or "", row.metadata or {}
    metadata = row.get("metadata") or {}
    return str(row.get("conversation_id") or ""), str(row.get("title") or ""), metadata


def _apply_usage_row(target: dict[str, Any], metadata: Mapping[str, Any]) -> None:
    prompt_tokens = int_value(metadata.get("prompt_tokens"))
    completion_tokens = int_value(metadata.get("completion_tokens"))
    cached_prompt_tokens = int_value(metadata.get("cached_prompt_tokens"))
    cached_completion_tokens = int_value(metadata.get("cached_completion_tokens"))
    cached_prompt_available = "cached_prompt_tokens" in metadata
    cached_completion_available = "cached_completion_tokens" in metadata
    cost_usd = float_value(metadata.get("cost_usd"))
    cost_available = provider_reports_cost(metadata)

    target["prompt_tokens"] += prompt_tokens
    target["completion_tokens"] += completion_tokens
    if cached_prompt_available:
        target["cached_prompt_tokens"] += cached_prompt_tokens
        target["cached_prompt_tokens_available"] = True
    if cached_completion_available:
        target["cached_completion_tokens"] += cached_completion_tokens
        target["cached_completion_tokens_available"] = True
    if cost_available:
        target["cost_usd"] += cost_usd
        target["cost_available"] = True


def aggregate_usage_totals(rows: Iterable[UsageSummaryRecord | Mapping[str, Any]]) -> dict[str, Any]:
    total = empty_usage_total()
    for row in rows:
        _, _, metadata = _usage_row_parts(row)
        _apply_usage_row(total, metadata)
    return total


def aggregate_usage_rows(rows: Iterable[UsageSummaryRecord | Mapping[str, Any]]) -> dict[str, Any]:
    daily_total = empty_usage_total()
    by_conversation: dict[str, dict[str, Any]] = {}
    for row in rows:
        conversation_id, title, metadata = _usage_row_parts(row)
        _apply_usage_row(daily_total, metadata)
        item = by_conversation.setdefault(
            conversation_id,
            {
                "conversation_id": conversation_id,
                "title": title,
                **empty_usage_total(),
            },
        )
        _apply_usage_row(item, metadata)
    return {
        "daily_total": daily_total,
        "by_conversation": sorted(
            by_conversation.values(),
            key=lambda item: (
                -(item["prompt_tokens"] + item["completion_tokens"]),
                item["conversation_id"],
            ),
        ),
    }
