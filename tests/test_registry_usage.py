from __future__ import annotations

from octopus_registry.store_shared.usage import aggregate_usage_rows, aggregate_usage_totals
from octopus_sdk.registry.models import UsageSummaryRecord


def test_usage_daily_total_matches_total_aggregator() -> None:
    rows = [
        UsageSummaryRecord(
            conversation_id="conv-a",
            title="A",
            metadata={
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "cached_prompt_tokens": 2,
                "provider": "codex",
                "cost_usd": 0.5,
            },
        ),
        UsageSummaryRecord(
            conversation_id="conv-b",
            title="B",
            metadata={
                "prompt_tokens": 5,
                "completion_tokens": 4,
                "cached_completion_tokens": 1,
                "provider": "claude",
                "cost_usd": 0.25,
            },
        ),
    ]

    rolled = aggregate_usage_rows(rows)
    total = aggregate_usage_totals(rows)

    assert rolled["daily_total"] == total
    assert total == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "cached_prompt_tokens": 2,
        "cached_completion_tokens": 1,
        "cached_prompt_tokens_available": True,
        "cached_completion_tokens_available": True,
        "cost_usd": 0.25,
        "cost_available": True,
    }
