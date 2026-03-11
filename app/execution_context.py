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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import BotConfig
    from app.session_state import ProjectBinding, SessionState


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
    config: "BotConfig",
    trust_tier: str = "trusted",
) -> str:
    """Resolve the effective model ID from session profile + config.

    Resolution order: session.model_profile → config.default_model_profile → config.model.
    Public users may be restricted to a subset of profiles.
    """
    profile = session.model_profile or config.default_model_profile

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


def _compute_execution_config_digest(config: "BotConfig", effective_model: str = "") -> str:
    """Hash the BotConfig fields that affect CLI command construction.

    Covers model selection and all codex execution flags.  If any of
    these change, pending approvals must be invalidated.
    Uses effective_model (resolved from profile) instead of raw config.model.
    """
    payload = json.dumps({
        "model": effective_model or config.model,
        "codex_sandbox": config.codex_sandbox,
        "codex_full_auto": config.codex_full_auto,
        "codex_dangerous": config.codex_dangerous,
        "codex_profile": config.codex_profile,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def resolve_execution_context(
    session: "SessionState",
    config: "BotConfig",
    provider_name: str,
    trust_tier: str = "trusted",
) -> ResolvedExecutionContext:
    """Build the authoritative execution context from session + config.

    This is the ONLY builder.  All call sites — execute, preflight, approve,
    retry, /session display, thread invalidation — must use this.

    trust_tier: "trusted" (full access) or "public" (restricted scope).
    Public trust enforcement happens here so it flows into context hash,
    approval validation, and provider context automatically.
    """
    from app.session_state import ProjectBinding
    from app.skills import get_provider_config_digest, get_skill_digests

    # Resolve effective model from session profile
    effective_model = resolve_effective_model(session, config, trust_tier)

    # Resolve project binding (disabled for public users)
    project_binding: ProjectBinding | None = None
    if trust_tier != "public" and session.project_id:
        for name, root_dir, extra_dirs in config.projects:
            if name == session.project_id:
                project_binding = ProjectBinding(name=name, root_dir=root_dir, extra_dirs=extra_dirs)
                break

    # Working dir: public users get forced public root
    if trust_tier == "public" and config.public_working_dir:
        working_dir = config.public_working_dir
    elif project_binding:
        working_dir = project_binding.root_dir
    else:
        working_dir = str(config.working_dir)

    # File policy: public users forced to inspect
    file_policy = "inspect" if trust_tier == "public" else session.file_policy

    # Extra dirs: public users get none (no operator extra dirs).
    # Project extra_dirs are folded in alongside config extra_dirs.
    if trust_tier == "public":
        base_extra_dirs: list[str] = []
    else:
        dirs = sorted(str(d) for d in config.extra_dirs)
        if project_binding and project_binding.extra_dirs:
            dirs.extend(sorted(project_binding.extra_dirs))
        base_extra_dirs = dirs

    # Skills: public users get no active skills
    active_skills = [] if trust_tier == "public" else session.active_skills

    return ResolvedExecutionContext(
        role=session.role,
        active_skills=active_skills,
        skill_digests=get_skill_digests(active_skills),
        provider_config_digest=get_provider_config_digest(
            active_skills, provider_name=provider_name,
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
