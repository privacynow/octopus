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
    provider_config_digest: str
    base_extra_dirs: list[str]  # from config only (not uploads, not denial dirs)
    project_id: str
    working_dir: str  # resolved from project binding; empty = config default
    file_policy: str  # "inspect", "edit", or ""
    provider_name: str

    # Derived / display (do NOT affect context_hash)
    project_binding: "ProjectBinding | None" = field(default=None, hash=False, compare=False)

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
            "extra_dirs": sorted(self.base_extra_dirs),
            "project_id": self.project_id,
            "file_policy": self.file_policy,
            "working_dir": self.working_dir,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def resolve_execution_context(
    session: "SessionState",
    config: "BotConfig",
    provider_name: str,
) -> ResolvedExecutionContext:
    """Build the authoritative execution context from session + config.

    This is the ONLY builder.  All call sites — execute, preflight, approve,
    retry, /session display, thread invalidation — must use this.
    """
    from app.session_state import ProjectBinding
    from app.skills import get_provider_config_digest, get_skill_digests

    # Resolve project binding
    project_binding: ProjectBinding | None = None
    if session.project_id:
        for name, root_dir, extra_dirs in config.projects:
            if name == session.project_id:
                project_binding = ProjectBinding(name=name, root_dir=root_dir, extra_dirs=extra_dirs)
                break

    working_dir = project_binding.root_dir if project_binding else ""

    return ResolvedExecutionContext(
        role=session.role,
        active_skills=session.active_skills,
        skill_digests=get_skill_digests(session.active_skills),
        provider_config_digest=get_provider_config_digest(
            session.active_skills, provider_name=provider_name,
        ),
        base_extra_dirs=sorted(str(d) for d in config.extra_dirs),
        project_id=session.project_id,
        working_dir=working_dir,
        file_policy=session.file_policy,
        provider_name=provider_name,
        project_binding=project_binding,
    )
