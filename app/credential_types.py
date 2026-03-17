"""Authoritative credential-domain type definitions."""

from __future__ import annotations

from typing import Awaitable, Callable

from app.skill_types import SkillRequirement


CredentialValidator = Callable[[SkillRequirement, str], Awaitable[tuple[bool, str]]]
