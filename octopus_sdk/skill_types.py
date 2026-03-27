"""Authoritative SDK skill-domain types."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Iterator


@dataclass(frozen=True)
class CredentialValidationSpec(Mapping[str, object]):
    url: str = ""
    method: str = "GET"
    header: str = ""
    expect_status: int | str | None = 200

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def get(self, key: str, default: object = None) -> object:
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, object]:
        expect_status = self.expect_status
        if expect_status is not None:
            expect_status = str(expect_status)
        return {
            "url": self.url,
            "method": self.method,
            "header": self.header,
            "expect_status": expect_status,
        }

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CredentialValidationSpec):
            return self.to_dict() == other.to_dict()
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        return False


def coerce_validation_spec(
    value: Mapping[str, object] | CredentialValidationSpec | None,
) -> CredentialValidationSpec | None:
    if value is None:
        return None
    if isinstance(value, CredentialValidationSpec):
        return value
    return CredentialValidationSpec(
        url=str(value.get("url", "") or ""),
        method=str(value.get("method", "GET") or "GET"),
        header=str(value.get("header", "") or ""),
        expect_status=(
            (
                None
                if value.get("expect_status") is None
                else (
                    int(value.get("expect_status", 200))
                    if isinstance(value.get("expect_status"), int | str)
                    and str(value.get("expect_status", 200)).strip().isdigit()
                    else str(value.get("expect_status", 200))
                )
            )
        ),
    )


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
    validate: CredentialValidationSpec | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "validate", coerce_validation_spec(self.validate))

    def get(self, key: str, default: object = None) -> object:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "help_url": self.help_url,
            "validate": None if self.validate is None else self.validate.to_dict(),
        }
