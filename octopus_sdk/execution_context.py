"""Authoritative resolved execution context.

Built once per request from SessionState + BotConfig + provider.
Every path that needs context state — execution, preflight, hash
computation, stale-context checks, /session display — reads from
this object.

Design rules:
- One builder, one object, one hash method.
- No loose-argument-bag hash functions anywhere else.
- Provider-facing RunContext/PreflightContext are derived from this
  object via adapter methods, not built independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

from octopus_sdk.content_models import RuntimeSkillTrackRecord

if TYPE_CHECKING:
    from octopus_sdk.config import BotConfigBase
    from octopus_sdk.sessions import ProjectBinding, SessionState


class SkillCatalogView(Protocol):
    def has_runtime_skill(self, name: str) -> bool: ...

    def resolve_runtime_track(self, name: str) -> RuntimeSkillTrackRecord | None: ...


@dataclass(frozen=True)
class ResolvedExecutionContext:
    """Single authoritative snapshot of the execution identity.

    Every field that affects context-hash, thread invalidation, preflight,
    or execution must live here.  Adding a field here + updating the hash
    payload is the ONLY way to extend the execution identity.
    """
    # Identity fields (all affect context_hash)
    role: str
    active_skills: list[str]
    skill_digests: dict[str, str]
    provider_config_digest: str  # hash of skill YAML content
    execution_config_digest: str  # hash of BotConfig execution fields (model, codex_*)
    base_extra_dirs: list[str]  # from config only (not uploads, not denial dirs)
    project_id: str
    working_dir: str  # resolved: project root_dir, or config.working_dir
    file_policy: str  # "inspect", "edit", or ""
    provider_name: str
    skill_revision_ids: dict[str, str] = field(default_factory=dict, hash=False, compare=False)
    skill_kinds: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    # Derived / display (do NOT affect context_hash — already covered by execution_config_digest)
    project_binding: "ProjectBinding | None" = field(default=None, hash=False, compare=False)
    effective_model: str = field(default="", hash=False, compare=False)

    @property
    def context_hash(self) -> str:
        """SHA-256 fingerprint of the execution identity.

        This is the ONLY place context hashes are computed.
        """
        payload = json.dumps({
            "role": self.role,
            "active_skills": sorted(self.active_skills),
            "skill_digests": {k: self.skill_digests[k] for k in sorted(self.skill_digests)},
            "provider_config_digest": self.provider_config_digest,
            "execution_config_digest": self.execution_config_digest,
            "extra_dirs": sorted(self.base_extra_dirs),
            "project_id": self.project_id,
            "file_policy": self.file_policy,
            "working_dir": self.working_dir,
            "provider_name": self.provider_name,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def resolve_effective_model(
    session: "SessionState",
    config: "BotConfigBase",
    trust_tier: str = "trusted",
    project_binding: "ProjectBinding | None" = None,
) -> str:
    """Resolve the effective model ID from session profile + config.

    Resolution order: session.model_profile → project.model_profile → config.default_model_profile → config.model.
    Public users may be restricted to a subset of profiles.
    """
    project_profile = project_binding.model_profile if project_binding else ""
    profile = session.model_profile or project_profile or config.default_model_profile

    if profile and config.model_profiles:
        # Public users restricted to allowed profiles
        if trust_tier == "public" and config.public_model_profiles:
            if profile not in config.public_model_profiles:
                # Fall back to first allowed profile, or config.model
                for allowed in sorted(config.public_model_profiles):
                    if allowed in config.model_profiles:
                        return config.model_profiles[allowed]
                return config.model
        if profile in config.model_profiles:
            return config.model_profiles[profile]

    return config.model


def _compute_execution_config_digest(config: "BotConfigBase", effective_model: str = "") -> str:
    """Hash the BotConfig fields that affect CLI command construction.

    Covers model selection and all codex/claude execution flags.  If any
    of these change, pending approvals must be invalidated.
    Uses effective_model (resolved from profile) instead of raw config.model.
    """
    payload_fields: dict[str, object] = {
        "model": effective_model or config.model,
        "codex_sandbox": config.codex_sandbox,
        "codex_full_auto": config.codex_full_auto,
        "codex_dangerous": config.codex_dangerous,
        "codex_profile": config.codex_profile,
        "codex_reasoning_effort": config.codex_reasoning_effort,
    }
    # Claude knobs join the digest only when set, so introducing them does
    # not invalidate pending approvals for bots that never used them.
    if config.claude_effort:
        payload_fields["claude_effort"] = config.claude_effort
    if config.claude_ultracode:
        payload_fields["claude_ultracode"] = True
    payload = json.dumps(payload_fields, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _resolved_skill_digests(skill_names: list[str], catalog: SkillCatalogView | None) -> dict[str, str]:
    if catalog is None:
        return {}
    digests: dict[str, str] = {}
    for name in skill_names:
        if (record := catalog.resolve_runtime_track(name)) is not None:
            digests[name] = record.revision.digest
    return digests


def _resolved_skill_revision_ids(skill_names: list[str], catalog: SkillCatalogView | None) -> dict[str, str]:
    if catalog is None:
        return {}
    revision_ids: dict[str, str] = {}
    for name in skill_names:
        if (record := catalog.resolve_runtime_track(name)) is not None:
            revision_ids[name] = record.revision.revision_id
    return revision_ids


def _resolved_skill_kinds(skill_names: list[str], catalog: SkillCatalogView | None) -> dict[str, str]:
    if catalog is None:
        return {}
    kinds: dict[str, str] = {}
    for name in skill_names:
        if (record := catalog.resolve_runtime_track(name)) is not None:
            kinds[name] = str(record.revision.skill_kind or "prompt")
    return kinds


def _resolved_provider_config_digest(
    skill_names: list[str],
    *,
    provider_name: str = "",
    catalog: SkillCatalogView | None,
) -> str:
    if catalog is None:
        return ""
    providers = (provider_name,) if provider_name else ("claude", "codex")
    parts: list[str] = []
    for name in sorted(skill_names):
        record = catalog.resolve_runtime_track(name)
        if record is None:
            continue
        for provider in providers:
            config = record.revision.provider_config.get(provider)
            if config:
                parts.append(f"{name}/{provider}:{json.dumps(config, sort_keys=True, separators=(',', ':'))}")
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _resolved_active_skills(
    session: "SessionState",
    trust_tier: str = "trusted",
    *,
    catalog: SkillCatalogView | None,
) -> list[str]:
    if trust_tier == "public":
        return []
    seen: set[str] = set()
    active: list[str] = []
    for name in session.active_skills:
        if name in seen:
            continue
        seen.add(name)
        if catalog is None or catalog.has_runtime_skill(name):
            active.append(name)
    return active


def resolve_execution_context(
    session: "SessionState",
    config: "BotConfigBase",
    provider_name: str,
    trust_tier: str = "trusted",
    *,
    catalog: SkillCatalogView | None = None,
) -> ResolvedExecutionContext:
    """Build the authoritative execution context from session + config.

    This is the ONLY builder.  All call sites — execute, preflight, approve,
    retry, /session display, thread invalidation — must use this.

    trust_tier: "trusted" (full access) or "public" (restricted scope).
    Public trust enforcement happens here so it flows into context hash,
    approval validation, and provider context automatically.
    """
    from octopus_sdk.sessions import ProjectBinding

    # Resolve project binding first (needed for model and policy inheritance).
    # Disabled for public users.
    project_binding: ProjectBinding | None = None
    if trust_tier != "public" and session.project_id:
        for proj in config.projects:
            if proj.name == session.project_id:
                project_binding = proj
                break

    # Resolve effective model: session > project > global default
    effective_model = resolve_effective_model(session, config, trust_tier, project_binding)

    # Working dir: public users get forced public root
    if trust_tier == "public" and config.public_working_dir:
        working_dir = config.public_working_dir
    elif project_binding:
        working_dir = project_binding.root_dir
    else:
        working_dir = str(config.working_dir)

    # File policy: session explicit > project default > "" (inherit)
    # Public users always forced to inspect.
    if trust_tier == "public":
        file_policy = "inspect"
    elif session.file_policy:
        file_policy = session.file_policy
    elif project_binding and project_binding.file_policy:
        file_policy = project_binding.file_policy
    else:
        file_policy = ""

    # Extra dirs: public users get none (no operator extra dirs).
    # Project extra_dirs are folded in alongside config extra_dirs.
    if trust_tier == "public":
        base_extra_dirs: list[str] = []
    else:
        dirs = sorted(str(d) for d in config.extra_dirs)
        if project_binding and project_binding.extra_dirs:
            dirs.extend(sorted(project_binding.extra_dirs))
        base_extra_dirs = dirs

    # Skills: trust shaping and resolvable filtering happen here.
    active_skills = _resolved_active_skills(session, trust_tier=trust_tier, catalog=catalog)

    return ResolvedExecutionContext(
        role=session.role,
        active_skills=active_skills,
        skill_digests=_resolved_skill_digests(active_skills, catalog),
        skill_revision_ids=_resolved_skill_revision_ids(active_skills, catalog),
        skill_kinds=_resolved_skill_kinds(active_skills, catalog),
        provider_config_digest=_resolved_provider_config_digest(
            active_skills,
            provider_name=provider_name,
            catalog=catalog,
        ),
        execution_config_digest=_compute_execution_config_digest(config, effective_model),
        base_extra_dirs=base_extra_dirs,
        project_id="" if trust_tier == "public" else session.project_id,
        working_dir=working_dir,
        file_policy=file_policy,
        provider_name=provider_name,
        project_binding=project_binding,
        effective_model=effective_model,
    )
