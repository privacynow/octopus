"""Exact alias helpers local to the registry package."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_exact_alias(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


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
