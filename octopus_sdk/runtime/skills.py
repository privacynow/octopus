"""Runtime-owned skill facts, provenance, and NL inspection helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

SkillKind = Literal["prompt", "executable"]
SkillQuestionKind = Literal["skill_status", "skill_list", "routing_agents", "skill_usage"]
SkillStatusScope = Literal["current_bot", "reachable_bot"]

_SKILL_TOKEN = r"(?P<skill>[a-z0-9][a-z0-9_-]*)"
_AGENT_TOKEN = r"(?P<agent>@?[a-z0-9][a-z0-9_-]*)"
_USE_SKILL_RE = re.compile(
    rf"^\s*did\s+(?P<target>you|this bot|the current bot|{_AGENT_TOKEN})\s+use\s+{_SKILL_TOKEN}(?:\s+skill)?(?:\b.*)?$",
    re.IGNORECASE,
)
_AVAILABLE_SKILL_RE = re.compile(
    rf"^\s*(?:is|was)\s+{_SKILL_TOKEN}(?:\s+skill)?\s+(?P<focus>available|active)(?:\s+(?:on|here|in)\s+(?P<target>this bot|this conversation|{_AGENT_TOKEN}))?(?:\b.*)?$",
    re.IGNORECASE,
)
_ROUTING_SKILL_RE = re.compile(
    rf"^\s*(?:who|which bots?)\s+(?:advertises?|has)\s+{_SKILL_TOKEN}(?:\s+skill)?(?:\b.*)?$",
    re.IGNORECASE,
)
_ACTIVE_LIST_RE = re.compile(
    r"^\s*(?:what|which)\s+skills?\s+are\s+active(?:\s+in\s+this\s+conversation)?(?:\b.*)?$",
    re.IGNORECASE,
)
_AVAILABLE_LIST_RE = re.compile(
    r"^\s*(?:what|which)\s+skills?\s+are\s+available(?:\s+on\s+this\s+bot)?(?:\b.*)?$",
    re.IGNORECASE,
)
_DEFAULT_LIST_RE = re.compile(
    r"^\s*(?:what|which)\s+skills?\s+are\s+defaults?(?:\s+for\s+new\s+conversations)?(?:\b.*)?$",
    re.IGNORECASE,
)


def normalize_skill_kind(value: str | None) -> SkillKind:
    return "executable" if str(value or "").strip().lower() == "executable" else "prompt"


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SkillExecutionManifestRecord:
    schema_version: int = 1
    routed_task_id: str = ""
    conversation_key: str = ""
    bot_slug: str = ""
    requested_skills: tuple[str, ...] = ()
    active_skills: tuple[str, ...] = ()
    composed_skill_slugs: tuple[str, ...] = ()
    composed_track_revision_ids: tuple[str, ...] = ()
    invoked_skill_slugs: tuple[str, ...] = ()
    skill_kind_map: dict[str, SkillKind] = field(default_factory=dict)
    prompt_manifest_hash: str = ""

    def bounded_payload(self) -> dict[str, object]:
        skill_kind_map = {
            key: normalize_skill_kind(value)
            for key, value in sorted(self.skill_kind_map.items())
            if str(key or "").strip()
        }
        return {
            "schema_version": int(self.schema_version or 1),
            "routed_task_id": str(self.routed_task_id or ""),
            "conversation_key": str(self.conversation_key or ""),
            "bot_slug": str(self.bot_slug or ""),
            "requested_skills": list(self.requested_skills),
            "active_skills": list(self.active_skills),
            "composed_skill_slugs": list(self.composed_skill_slugs),
            "composed_track_revision_ids": list(self.composed_track_revision_ids),
            "invoked_skill_slugs": list(self.invoked_skill_slugs),
            "skill_kind_map": skill_kind_map,
            "prompt_manifest_hash": str(self.prompt_manifest_hash or ""),
        }


def skill_execution_manifest_hash(
    *,
    routed_task_id: str,
    conversation_key: str,
    bot_slug: str,
    requested_skills: tuple[str, ...],
    active_skills: tuple[str, ...],
    composed_skill_slugs: tuple[str, ...],
    composed_track_revision_ids: tuple[str, ...],
    invoked_skill_slugs: tuple[str, ...],
    skill_kind_map: dict[str, SkillKind],
) -> str:
    payload = {
        "schema_version": 1,
        "routed_task_id": routed_task_id,
        "conversation_key": conversation_key,
        "bot_slug": bot_slug,
        "requested_skills": list(requested_skills),
        "active_skills": list(active_skills),
        "composed_skill_slugs": list(composed_skill_slugs),
        "composed_track_revision_ids": list(composed_track_revision_ids),
        "invoked_skill_slugs": list(invoked_skill_slugs),
        "skill_kind_map": {
            key: normalize_skill_kind(value)
            for key, value in sorted(skill_kind_map.items())
        },
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SkillQuestionIntent:
    kind: SkillQuestionKind
    skill_name: str = ""
    target_agent: str = ""
    status_focus: str = ""


def parse_skill_question(text: str) -> SkillQuestionIntent | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if (match := _USE_SKILL_RE.match(raw)):
        target = _normalized_target_agent(str(match.group("target") or ""))
        return SkillQuestionIntent(
            kind="skill_usage",
            target_agent=target,
            skill_name=str(match.group("skill") or "").strip().lower(),
        )
    if (match := _AVAILABLE_SKILL_RE.match(raw)):
        target = _normalized_target_agent(str(match.group("target") or ""))
        return SkillQuestionIntent(
            kind="skill_status",
            skill_name=str(match.group("skill") or "").strip().lower(),
            target_agent=target,
            status_focus=str(match.group("focus") or "").strip().lower(),
        )
    if (match := _ROUTING_SKILL_RE.match(raw)):
        return SkillQuestionIntent(
            kind="routing_agents",
            skill_name=str(match.group("skill") or "").strip().lower(),
        )
    if _ACTIVE_LIST_RE.match(raw):
        return SkillQuestionIntent(kind="skill_list", status_focus="active")
    if _AVAILABLE_LIST_RE.match(raw):
        return SkillQuestionIntent(kind="skill_list", status_focus="available")
    if _DEFAULT_LIST_RE.match(raw):
        return SkillQuestionIntent(kind="skill_list", status_focus="default")
    return None


@dataclass(frozen=True)
class ReachableSkillRecord:
    agent_id: str = ""
    slug: str = ""
    display_name: str = ""
    advertised_for_routing: bool = False

    @property
    def label(self) -> str:
        return self.slug or self.display_name or self.agent_id


@dataclass(frozen=True)
class SkillInspectionResponse:
    status: str
    intent: SkillQuestionIntent
    current_bot_slug: str = ""
    current_bot_display_name: str = ""
    status_scope: SkillStatusScope = "current_bot"
    skill_name: str = ""
    skill_kind: str = ""
    installed_on_current_bot: bool | None = None
    runtime_available_on_current_bot: bool | None = None
    default_for_new_conversations: bool | None = None
    active_in_current_conversation: bool | None = None
    advertised_for_routing_on_current_bot: bool | None = None
    reachable_bots: tuple[ReachableSkillRecord, ...] = ()
    available_skill_names: tuple[str, ...] = ()
    default_skill_names: tuple[str, ...] = ()
    active_skill_names: tuple[str, ...] = ()
    remote_target_label: str = ""
    remote_advertised_for_routing: bool | None = None
    routed_task_id: str = ""
    target_agent_label: str = ""
    evidence_status: str = ""
    requested_for_run: bool | None = None
    active_for_run: bool | None = None
    composed_for_run: bool | None = None
    invoked_for_run: bool | None = None
    note: str = ""


def render_skill_inspection_response(response: SkillInspectionResponse) -> str:
    intent = response.intent
    if intent.kind == "skill_list":
        if response.intent.status_focus == "active":
            values = ", ".join(response.active_skill_names) if response.active_skill_names else "none"
            return f"Active in this conversation: {values}"
        if response.intent.status_focus == "default":
            values = ", ".join(response.default_skill_names) if response.default_skill_names else "none"
            return f"Default for new conversations on this bot: {values}"
        values = ", ".join(response.available_skill_names) if response.available_skill_names else "none"
        return f"Runtime-available on this bot: {values}"

    if intent.kind == "routing_agents":
        labels = ", ".join(item.label for item in response.reachable_bots if item.advertised_for_routing)
        if not labels:
            return f"No reachable bots currently advertise `{response.skill_name}` for routing."
        return f"Reachable bots advertising `{response.skill_name}` for routing: {labels}"

    if intent.kind == "skill_usage":
        lines = [
            f"Skill execution evidence for `{response.skill_name}` on {response.target_agent_label or 'the selected bot'}:",
        ]
        if response.routed_task_id:
            lines.append(f"Routed task id: {response.routed_task_id}")
        if response.evidence_status == "missing":
            if response.note:
                lines.append(response.note)
            return "\n".join(lines)
        lines.append(f"Requested for run: {_yn(response.requested_for_run)}")
        lines.append(f"Active for run: {_yn(response.active_for_run)}")
        lines.append(f"Composed for run: {_yn(response.composed_for_run)}")
        lines.append(f"Skill kind: {response.skill_kind or 'unknown'}")
        if response.invoked_for_run is not None:
            lines.append(f"Invoked for run: {_yn(response.invoked_for_run)}")
        elif response.skill_kind == "prompt":
            lines.append("Invoked for run: n/a (prompt skill)")
        if response.note:
            lines.append(response.note)
        return "\n".join(lines)

    if intent.kind == "skill_status" and response.status_scope == "reachable_bot":
        lines = [
            f"Routing availability for `{response.skill_name}` on {response.remote_target_label or 'the selected reachable bot'}:",
            f"Advertised for routing on that bot: {_yn(response.remote_advertised_for_routing)}",
        ]
        if response.note:
            lines.append(response.note)
        return "\n".join(lines)

    lines = [f"Skill state for `{response.skill_name}`:"]
    lines.append(f"Installed on this bot: {_yn(response.installed_on_current_bot)}")
    lines.append(f"Runtime-available on this bot: {_yn(response.runtime_available_on_current_bot)}")
    lines.append(f"Default for new conversations on this bot: {_yn(response.default_for_new_conversations)}")
    lines.append(f"Active in this conversation: {_yn(response.active_in_current_conversation)}")
    lines.append(f"Advertised for routing on this bot: {_yn(response.advertised_for_routing_on_current_bot)}")
    if response.skill_kind:
        lines.append(f"Skill kind on this bot: {response.skill_kind}")
    if response.reachable_bots:
        labels = ", ".join(item.label for item in response.reachable_bots if item.advertised_for_routing) or "none"
        lines.append(f"Reachable bots advertising this skill for routing: {labels}")
    if response.note:
        lines.append(response.note)
    return "\n".join(lines)


def _yn(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _normalized_target_agent(value: str) -> str:
    text = str(value or "").strip()
    lower = text.lower()
    if lower in {"", "you", "this bot", "the current bot", "this conversation"}:
        return ""
    if text.startswith("@"):
        return text[1:]
    return text


def parse_skill_execution_manifest(value: object) -> SkillExecutionManifestRecord | None:
    if not isinstance(value, dict):
        return None
    payload = dict(value)
    return SkillExecutionManifestRecord(
        schema_version=int(payload.get("schema_version") or 1),
        routed_task_id=str(payload.get("routed_task_id", "") or ""),
        conversation_key=str(payload.get("conversation_key", "") or ""),
        bot_slug=str(payload.get("bot_slug", "") or ""),
        requested_skills=tuple(
            str(item).strip().lower()
            for item in (payload.get("requested_skills", []) or [])
            if str(item).strip()
        ),
        active_skills=tuple(
            str(item).strip().lower()
            for item in (payload.get("active_skills", []) or [])
            if str(item).strip()
        ),
        composed_skill_slugs=tuple(
            str(item).strip().lower()
            for item in (payload.get("composed_skill_slugs", []) or [])
            if str(item).strip()
        ),
        composed_track_revision_ids=tuple(
            str(item).strip()
            for item in (payload.get("composed_track_revision_ids", []) or [])
            if str(item).strip()
        ),
        invoked_skill_slugs=tuple(
            str(item).strip().lower()
            for item in (payload.get("invoked_skill_slugs", []) or [])
            if str(item).strip()
        ),
        skill_kind_map={
            str(key).strip().lower(): normalize_skill_kind(str(kind))
            for key, kind in dict(payload.get("skill_kind_map", {}) or {}).items()
            if str(key).strip()
        },
        prompt_manifest_hash=str(payload.get("prompt_manifest_hash", "") or ""),
    )


@runtime_checkable
class SkillInspectionPort(Protocol):
    async def inspect_text(
        self,
        *,
        text: str,
        conversation_key: str,
        conversation_ref: str,
        actor_key: str = "",
        provider_name: str,
        provider_state_factory,
    ) -> SkillInspectionResponse | None: ...
