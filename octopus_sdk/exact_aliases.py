"""Shared exact alias resolution helpers for operator-facing selectors."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_exact_alias(value: str) -> str:
    """Normalize human-facing aliases without introducing fuzzy semantics."""
    return " ".join(str(value or "").strip().lower().split())


def direct_selector_aliases(
    *,
    slug: str = "",
    display_name: str = "",
) -> tuple[str, ...]:
    values: list[str] = []
    compact_display_name = str(display_name or "").strip()
    normalized_slug = str(slug or "").strip()
    if compact_display_name and " " not in compact_display_name:
        values.append(f"@{compact_display_name}")
    if normalized_slug:
        values.append(f"@{normalized_slug}")
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return tuple(deduped)


def collect_exact_aliases(
    *,
    identifier: str = "",
    slug: str = "",
    display_name: str = "",
    aliases: Iterable[str] = (),
) -> set[str]:
    values = {
        normalize_exact_alias(identifier),
        normalize_exact_alias(slug),
        normalize_exact_alias(display_name),
    }
    values.update(normalize_exact_alias(item) for item in aliases)
    values.discard("")
    return values


def matches_exact_alias(
    selector: str,
    *,
    identifier: str = "",
    slug: str = "",
    display_name: str = "",
    aliases: Iterable[str] = (),
) -> bool:
    normalized = normalize_exact_alias(selector)
    if not normalized:
        return False
    return normalized in collect_exact_aliases(
        identifier=identifier,
        slug=slug,
        display_name=display_name,
        aliases=aliases,
    )
