"""Authoritative runtime-skill type definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillMeta:
    name: str
    display_name: str
    description: str
    is_custom: bool = False


@dataclass(frozen=True)
class SkillRequirement:
    key: str
    prompt: str
    help_url: str | None = None
    validate: dict | None = None
