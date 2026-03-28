"""SDK workflow contracts for runtime-skill catalog, activation, setup, import, and lifecycle flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)
from octopus_sdk.credential_types import CredentialValidator
from octopus_sdk.providers import CredentialEnvRecord, ProviderStateRecord
from octopus_sdk.sessions import AwaitingSkillSetup, SessionState
from octopus_sdk.skill_types import SkillRequirement


@dataclass(frozen=True)
class RuntimeSkillCatalogItem:
    name: str
    display_name: str
    description: str
    source_kind: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]
    has_custom_override: bool
    can_activate: bool
    can_update: bool
    can_uninstall: bool
    lifecycle_status: str = ""


@dataclass(frozen=True)
class RuntimeSkillDetail:
    name: str
    display_name: str
    description: str
    body: str
    source_kind: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]
    has_custom_override: bool
    can_activate: bool
    can_update: bool
    can_uninstall: bool
    lifecycle_status: str = ""


@dataclass(frozen=True)
class RuntimeSkillDraftRecord:
    name: str
    visibility: str


@dataclass(frozen=True)
class RuntimeSkillInfoRecord:
    display_name: str
    description: str
    body: str
    source_kind: str
    providers: tuple[str, ...]
    requirement_keys: tuple[str, ...]


@dataclass(frozen=True)
class RegistrySkillSearchRecord:
    name: str
    display_name: str
    description: str
    publisher: str
    version: str


@dataclass(frozen=True)
class SkillMutationResult:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class SkillUpdateStatus:
    name: str
    status: str
    has_custom_override: bool


class SkillCatalogServicePort(Protocol):
    def catalog(self) -> dict[str, object]: ...
    def list_tracks(self, skill_name: str) -> list[RuntimeSkillTrackRecord]: ...
    def resolve_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None: ...
    def resolve_runtime_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None: ...
    def has_skill(self, skill_name: str) -> bool: ...
    def has_runtime_skill(self, skill_name: str) -> bool: ...
    def requirements(self, skill_name: str) -> list[SkillRequirement]: ...
    def runtime_requirements(self, skill_name: str) -> list[SkillRequirement]: ...
    def resolve_info(self, skill_name: str) -> RuntimeSkillInfoRecord | None: ...
    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillTrackRecord: ...
    def filter_resolvable(self, names: list[str]) -> list[str]: ...
    def validate_active(self, skill_names: list[str]) -> list[str]: ...


class SkillActivationServicePort(Protocol):
    def normalize(self, session: SessionState) -> list[str]: ...
    def list_active(self, session: SessionState) -> list[str]: ...
    def activate(self, session: SessionState, skill_name: str) -> bool: ...
    def deactivate(self, session: SessionState, skill_name: str) -> bool: ...
    def clear(self, session: SessionState) -> None: ...


class SkillImportServicePort(Protocol):
    def registry_search(self, registry_url: str, query: str) -> list[RegistrySkillSearchRecord]: ...
    def install_from_registry(self, name: str, registry_url: str) -> SkillMutationResult: ...
    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()) -> SkillMutationResult: ...
    def update(self, name: str) -> SkillMutationResult: ...
    def update_all(self) -> list[SkillMutationResult]: ...
    def diff(self, name: str, *, max_chars: int = 4000) -> SkillMutationResult: ...
    def has_custom_override(self, name: str) -> bool: ...
    def list_updates(self) -> list[SkillUpdateStatus]: ...


class RuntimeSkillCatalogPort(Protocol):
    def list_skills(self, query: str = "") -> list[RuntimeSkillCatalogItem]: ...
    def get_skill(self, skill_name: str) -> RuntimeSkillDetail | None: ...
    def has_skill(self, skill_name: str) -> bool: ...
    def has_runtime_skill(self, skill_name: str) -> bool: ...
    def resolve_runtime_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None: ...
    def filter_resolvable(self, names: list[str]) -> list[str]: ...
    def requirements(self, skill_name: str) -> tuple[SkillRequirement, ...]: ...
    def missing_requirements(
        self,
        skill_name: str,
        credential_values: dict[str, str],
    ) -> tuple[SkillRequirement, ...]: ...
    def create_custom_draft(
        self,
        skill_name: str,
        *,
        owner_actor: str = "",
    ) -> RuntimeSkillDraftRecord: ...


@dataclass(frozen=True)
class ConversationSkillItem:
    name: str
    display_name: str
    description: str
    source_kind: str
    has_custom_override: bool


@dataclass(frozen=True)
class ConversationSkillListing:
    active_skills: tuple[str, ...]
    active_skill_details: tuple[ConversationSkillItem, ...]


@dataclass(frozen=True)
class ConversationSkillMutationOutcome:
    status: str
    mutated: bool = False
    first_requirement: SkillRequirement | None = None
    projected_size: int = 0
    prompt_size_threshold: int = 0
    foreign_setup_user: str = ""
    foreign_setup: AwaitingSkillSetup | None = None


class RuntimeSkillActivationPort(Protocol):
    def list_conversation_skills(self, active_skills: list[str]) -> ConversationSkillListing: ...
    def begin_activate(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
        confirm: bool = False,
    ) -> ConversationSkillMutationOutcome: ...
    def confirm_activate(
        self,
        session: SessionState,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...
    def begin_setup(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...
    def deactivate(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...
    def clear(
        self,
        session: SessionState,
        *,
        actor_key: str,
    ) -> ConversationSkillMutationOutcome: ...


@dataclass(frozen=True)
class PromptWarningContext:
    data_dir: Path
    provider_name: str
    provider_state_factory: Callable[[str], ProviderStateRecord]
    approval_mode: str


@dataclass(frozen=True)
class RegistryRuntimeSkillSearchHit:
    name: str
    display_name: str
    description: str
    publisher: str
    version: str
    can_import: bool


@dataclass(frozen=True)
class RuntimeSkillSearchResults:
    catalog: tuple[RuntimeSkillCatalogItem, ...]
    registry: tuple[RegistryRuntimeSkillSearchHit, ...]
    registry_error: str = ""


@dataclass(frozen=True)
class RuntimeSkillMutationOutcome:
    name: str
    ok: bool
    message: str
    prompt_size_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeSkillUpdateStatusItem:
    name: str
    status: str
    has_custom_override: bool


class RuntimeSkillImportPort(Protocol):
    def search(self, query: str, *, registry_url: str = "") -> RuntimeSkillSearchResults: ...
    def install_from_registry(
        self,
        skill_name: str,
        registry_url: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome: ...
    def uninstall(
        self,
        skill_name: str,
        *,
        default_skills: tuple[str, ...] = (),
    ) -> RuntimeSkillMutationOutcome: ...
    def update(
        self,
        skill_name: str,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> RuntimeSkillMutationOutcome: ...
    def update_all(
        self,
        *,
        warning_context: PromptWarningContext | None = None,
    ) -> tuple[RuntimeSkillMutationOutcome, ...]: ...
    def diff(self, skill_name: str) -> RuntimeSkillMutationOutcome: ...
    def list_updates(self) -> tuple[RuntimeSkillUpdateStatusItem, ...]: ...


@dataclass(frozen=True)
class RuntimeSkillSetupState:
    status: str
    setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupCancellationOutcome:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupAdvanceOutcome:
    status: str
    mutated: bool = False
    validation_key: str = ""
    validation_error: str = ""
    next_requirement: SkillRequirement | None = None
    skill_name: str = ""


@dataclass(frozen=True)
class RuntimeSkillCredentialSatisfactionOutcome:
    status: str
    mutated: bool = False
    credential_env: CredentialEnvRecord | None = None
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    missing_skill: str = ""
    first_requirement: SkillRequirement | None = None


@dataclass(frozen=True)
class RuntimeSkillCredentialClearOutcome:
    mutated: bool
    setup_cleared: bool
    deactivated_skills: tuple[str, ...]


class RuntimeSkillSetupPort(Protocol):
    def begin_setup(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
        requirements: list[SkillRequirement],
    ) -> RuntimeSkillCredentialSatisfactionOutcome: ...
    def foreign_setup(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str | None = None,
    ) -> RuntimeSkillSetupState: ...
    def cancel(
        self,
        session: SessionState,
        *,
        actor_key: str,
        allow_override: bool = False,
    ) -> RuntimeSkillSetupCancellationOutcome: ...
    def check_satisfaction(
        self,
        session: SessionState,
        *,
        actor_key: str,
        active_skills: list[str],
    ) -> RuntimeSkillCredentialSatisfactionOutcome: ...
    async def submit_credential_value(
        self,
        session: SessionState,
        *,
        actor_key: str,
        raw_value: str,
        validator: CredentialValidator | None = None,
    ) -> RuntimeSkillSetupAdvanceOutcome: ...
    def apply_cleared_credentials(
        self,
        session: SessionState,
        *,
        actor_key: str,
        removed_skills: list[str],
        skill_name: str | None,
    ) -> RuntimeSkillCredentialClearOutcome: ...


@dataclass(frozen=True)
class RuntimeSkillLifecycleRevision:
    revision_id: str
    version_label: str
    status: str
    changelog: str
    created_by: str
    created_at: str
    is_published: bool


@dataclass(frozen=True)
class RuntimeSkillLifecycleApproval:
    revision_id: str
    action: str
    actor: str
    note: str
    created_at: str


@dataclass(frozen=True)
class RuntimeSkillLifecycleDetail:
    name: str
    display_name: str
    description: str
    visibility: str
    body: str
    lifecycle_status: str
    active_revision_id: str
    published_revision_id: str
    runtime_available: bool
    revisions: tuple[RuntimeSkillLifecycleRevision, ...]
    approvals: tuple[RuntimeSkillLifecycleApproval, ...]


@dataclass(frozen=True)
class RuntimeSkillLifecycleMutation:
    status: str
    ok: bool
    message: str
    detail: RuntimeSkillLifecycleDetail | None = None


class RuntimeSkillAuthoringPort(Protocol):
    def detail(self, skill_name: str) -> RuntimeSkillLifecycleDetail | None: ...
    def create_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillLifecycleMutation: ...
    def edit_draft(
        self,
        skill_name: str,
        *,
        actor_key: str,
        body: str,
        description: str | None = None,
        changelog: str = "",
    ) -> RuntimeSkillLifecycleMutation: ...
    def submit(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation: ...
    def publish(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation: ...
    def archive(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation: ...


class RuntimeSkillApprovalPort(Protocol):
    def approve(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation: ...
    def reject(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation: ...
