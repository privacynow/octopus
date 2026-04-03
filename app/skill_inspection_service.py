"""Deterministic runtime skill inspection for NL factual turns."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.registry_capabilities import registry_authority_ref
from app.channels.registry.refs import parse_registry_ref
from octopus_sdk.bot_runtime import WorkflowComposition
from octopus_sdk.config import BotConfigBase
from octopus_sdk.exact_aliases import matches_exact_alias
from octopus_sdk.registry.models import AgentDiscoveryQuery, DiscoveredAgentRef
from octopus_sdk.registry_inspection import RegistryInspectionPort
from octopus_sdk.runtime.skills import (
    ReachableSkillRecord,
    SkillInspectionPort,
    SkillInspectionResponse,
    SkillQuestionIntent,
    normalize_skill_kind,
    parse_skill_execution_manifest,
    parse_skill_question,
)
from octopus_sdk.workflows.skills import RuntimeSkillCatalogItem


@dataclass(frozen=True)
class SkillInspectionService(SkillInspectionPort):
    config: BotConfigBase
    workflows: WorkflowComposition
    agent_directory: object | None = None
    registry_inspection: RegistryInspectionPort | None = None

    async def inspect_text(
        self,
        *,
        text: str,
        conversation_key: str,
        conversation_ref: str,
        actor_key: str = "",
        provider_name: str,
        provider_state_factory,
    ) -> SkillInspectionResponse | None:
        del actor_key
        intent = parse_skill_question(text)
        if intent is None:
            return None
        catalog = self.workflows.runtime_skills.catalog
        items = tuple(catalog.list_skills())
        item_by_name = {item.name: item for item in items}
        session = self.workflows.sessions.load(
            conversation_key,
            provider_name=provider_name,
            provider_state_factory=provider_state_factory,
            approval_mode=self.config.approval_mode,
            default_role=self.config.role,
            default_skills=self.config.default_skills,
        )
        resolved = self.workflows.sessions.resolve_context(
            session,
            config=self.config,
            provider_name=provider_name,
            trust_tier="trusted",
        )
        reachable_agents = await self._search_reachable_agents()
        if intent.kind == "skill_list":
            return self._skill_list_response(intent, items, resolved.active_skills)
        if intent.kind == "routing_agents":
            return self._routing_agents_response(intent, reachable_agents)
        if intent.kind == "skill_status":
            return await self._skill_status_response(
                intent,
                item_by_name=item_by_name,
                active_skill_names=tuple(resolved.active_skills),
                reachable_agents=reachable_agents,
            )
        if intent.kind == "skill_usage":
            return await self._skill_usage_response(
                intent,
                conversation_ref=conversation_ref,
                reachable_agents=reachable_agents,
            )
        return None

    def _skill_list_response(
        self,
        intent: SkillQuestionIntent,
        items: tuple[RuntimeSkillCatalogItem, ...],
        active_skill_names: list[str],
    ) -> SkillInspectionResponse:
        available = tuple(item.name for item in items if item.can_activate and item.runtime_available)
        defaults = tuple(item.name for item in items if item.default_for_new_conversations)
        return SkillInspectionResponse(
            status="ok",
            intent=intent,
            current_bot_slug=self.config.agent_slug,
            current_bot_display_name=self.config.agent_display_name,
            available_skill_names=available,
            default_skill_names=defaults,
            active_skill_names=tuple(active_skill_names),
        )

    def _routing_agents_response(
        self,
        intent: SkillQuestionIntent,
        reachable_agents: tuple[DiscoveredAgentRef, ...],
    ) -> SkillInspectionResponse:
        records = tuple(
            ReachableSkillRecord(
                agent_id=agent.agent_id,
                slug=agent.slug,
                display_name=agent.display_name,
                advertised_for_routing=True,
            )
            for agent in reachable_agents
            if intent.skill_name in {
                str(skill).strip().lower()
                for skill in (agent.routing_skills or [])
                if str(skill).strip()
            }
        )
        return SkillInspectionResponse(
            status="ok",
            intent=intent,
            current_bot_slug=self.config.agent_slug,
            current_bot_display_name=self.config.agent_display_name,
            skill_name=intent.skill_name,
            reachable_bots=records,
        )

    async def _skill_status_response(
        self,
        intent: SkillQuestionIntent,
        *,
        item_by_name: dict[str, RuntimeSkillCatalogItem],
        active_skill_names: tuple[str, ...],
        reachable_agents: tuple[DiscoveredAgentRef, ...],
    ) -> SkillInspectionResponse:
        target_agent = str(intent.target_agent or "").strip()
        if target_agent and not self._is_current_bot_target(target_agent):
            target = self._resolve_target_agent(target_agent, reachable_agents)
            if target is None:
                return SkillInspectionResponse(
                    status="missing",
                    intent=intent,
                    status_scope="reachable_bot",
                    skill_name=intent.skill_name,
                    remote_target_label=target_agent,
                    note="No reachable bot matches that target selector.",
                )
            advertised = intent.skill_name in {
                str(skill).strip().lower()
                for skill in (target.routing_skills or [])
                if str(skill).strip()
            }
            return SkillInspectionResponse(
                status="ok",
                intent=intent,
                status_scope="reachable_bot",
                skill_name=intent.skill_name,
                remote_target_label=target.slug or target.display_name or target.agent_id,
                remote_advertised_for_routing=advertised,
                note=(
                    "This reflects registry routing advertisement on that reachable bot, "
                    "not its current conversation state."
                ),
            )

        local = item_by_name.get(intent.skill_name)
        reachable = tuple(
            ReachableSkillRecord(
                agent_id=agent.agent_id,
                slug=agent.slug,
                display_name=agent.display_name,
                advertised_for_routing=True,
            )
            for agent in reachable_agents
            if intent.skill_name in {
                str(skill).strip().lower()
                for skill in (agent.routing_skills or [])
                if str(skill).strip()
            }
        )
        return SkillInspectionResponse(
            status="ok",
            intent=intent,
            current_bot_slug=self.config.agent_slug,
            current_bot_display_name=self.config.agent_display_name,
            skill_name=intent.skill_name,
            skill_kind=normalize_skill_kind(local.skill_kind) if local is not None else "",
            installed_on_current_bot=(local is not None),
            runtime_available_on_current_bot=(local.runtime_available if local is not None else False),
            default_for_new_conversations=(local.default_for_new_conversations if local is not None else False),
            active_in_current_conversation=(intent.skill_name in active_skill_names),
            advertised_for_routing_on_current_bot=(
                (local.can_activate and local.runtime_available) if local is not None else False
            ),
            reachable_bots=reachable,
        )

    async def _skill_usage_response(
        self,
        intent: SkillQuestionIntent,
        *,
        conversation_ref: str,
        reachable_agents: tuple[DiscoveredAgentRef, ...],
    ) -> SkillInspectionResponse:
        target_label = str(intent.target_agent or "").strip()
        inspect_current_bot = not target_label or self._is_current_bot_target(target_label)
        target = None
        if not inspect_current_bot:
            target = self._resolve_target_agent(target_label, reachable_agents)
            if target is None:
                return SkillInspectionResponse(
                    status="missing",
                    intent=intent,
                    skill_name=intent.skill_name,
                    target_agent_label=target_label,
                    evidence_status="missing",
                    note="No reachable bot matches that target selector.",
                )
        manifest_response = await self._execution_manifest_response(
            intent,
            conversation_ref=conversation_ref,
            inspect_current_bot=inspect_current_bot,
            target=target,
        )
        return manifest_response

    async def _execution_manifest_response(
        self,
        intent: SkillQuestionIntent,
        *,
        conversation_ref: str,
        inspect_current_bot: bool,
        target: DiscoveredAgentRef | None,
    ) -> SkillInspectionResponse:
        if self.registry_inspection is None:
            return SkillInspectionResponse(
                status="missing",
                intent=intent,
                skill_name=intent.skill_name,
                target_agent_label=self._usage_target_label(target),
                evidence_status="missing",
                note="Registry execution evidence is unavailable on this bot.",
            )
        parsed_ref = parse_registry_ref(conversation_ref)
        if parsed_ref is None:
            return SkillInspectionResponse(
                status="missing",
                intent=intent,
                skill_name=intent.skill_name,
                target_agent_label=self._usage_target_label(target),
                evidence_status="missing",
                note="This conversation does not have registry-backed execution evidence.",
            )
        try:
            authority_ref = registry_authority_ref(parsed_ref[0])
            task_record = None
            if inspect_current_bot:
                recipient_conversation_id = await self._current_registry_conversation_id(
                    parsed_ref,
                    authority_ref=authority_ref,
                )
            else:
                task_record = await self._match_task_for_target(parsed_ref, authority_ref=authority_ref, target=target)
                if task_record is None:
                    return SkillInspectionResponse(
                        status="missing",
                        intent=intent,
                        skill_name=intent.skill_name,
                        target_agent_label=self._usage_target_label(target),
                        evidence_status="missing",
                        note="No matching routed task was found for that bot in this conversation.",
                    )
                recipient_conversation_id = str(task_record.recipient_conversation_id or "").strip()
            if not recipient_conversation_id:
                return SkillInspectionResponse(
                    status="missing",
                    intent=intent,
                    skill_name=intent.skill_name,
                    target_agent_label=self._usage_target_label(target) if not inspect_current_bot else self._usage_target_label(None),
                    evidence_status="missing",
                    note="No registry conversation with execution evidence is available to inspect.",
                )
            events = await self.registry_inspection.list_events(
                authority_ref,
                recipient_conversation_id,
                kind="provider.request",
                limit=100,
            )
        except Exception:
            return SkillInspectionResponse(
                status="missing",
                intent=intent,
                skill_name=intent.skill_name,
                target_agent_label=self._usage_target_label(target) if not inspect_current_bot else self._usage_target_label(None),
                evidence_status="missing",
                note="Registry execution evidence could not be loaded.",
            )
        event = max(events.events, key=lambda item: int(item.seq or 0), default=None)
        manifest = parse_skill_execution_manifest(
            (event.metadata if event is not None else {}).get("skill_manifest")
            if event is not None
            else None
        )
        if manifest is None:
            return SkillInspectionResponse(
                status="missing",
                intent=intent,
                skill_name=intent.skill_name,
                target_agent_label=(
                    self._usage_target_label(target, fallback=task_record.target_display_name)
                    if task_record is not None
                    else self._usage_target_label(None)
                ),
                routed_task_id=str(task_record.routed_task_id or "") if task_record is not None else "",
                evidence_status="missing",
                note="No structured skill execution manifest was recorded for the matching run.",
            )
        skill_kind = normalize_skill_kind(manifest.skill_kind_map.get(intent.skill_name, "prompt"))
        return SkillInspectionResponse(
            status="ok",
            intent=intent,
            skill_name=intent.skill_name,
            skill_kind=skill_kind,
            routed_task_id=str(task_record.routed_task_id or "") if task_record is not None else "",
            target_agent_label=(
                self._usage_target_label(target, fallback=task_record.target_display_name)
                if task_record is not None
                else self._usage_target_label(None)
            ),
            evidence_status="found",
            requested_for_run=(intent.skill_name in manifest.requested_skills),
            active_for_run=(intent.skill_name in manifest.active_skills),
            composed_for_run=(intent.skill_name in manifest.composed_skill_slugs),
            invoked_for_run=(
                intent.skill_name in manifest.invoked_skill_slugs
                if manifest.invoked_skill_slugs
                else None
            ),
            note=(
                "Prompt skills can be proven as requested, active, and composed into the provider prompt. "
                "Behavioral adherence cannot be proven exactly from runtime telemetry."
                if skill_kind == "prompt"
                else ""
            ),
        )

    async def _match_task_for_target(
        self,
        parsed_ref: tuple[str, str, str],
        *,
        authority_ref: str,
        target: DiscoveredAgentRef | None,
    ):
        _, ref_kind, external_id = parsed_ref
        if ref_kind == "task":
            task = await self.registry_inspection.get_task(authority_ref, external_id)
            if target is None or not target.agent_id or target.agent_id == task.target_agent_id:
                return task
            return None
        conversation = await self.registry_inspection.get_conversation(authority_ref, external_id)
        tasks = tuple(conversation.linked_routed_tasks or ())
        if not tasks:
            return None
        if target is None or not target.agent_id:
            return max(tasks, key=lambda item: (str(item.updated_at or ""), str(item.created_at or ""), str(item.routed_task_id or "")))
        matching = [item for item in tasks if str(item.target_agent_id or "") == target.agent_id]
        if not matching:
            return None
        return max(matching, key=lambda item: (str(item.updated_at or ""), str(item.created_at or ""), str(item.routed_task_id or "")))

    async def _current_registry_conversation_id(
        self,
        parsed_ref: tuple[str, str, str],
        *,
        authority_ref: str,
    ) -> str:
        _, ref_kind, external_id = parsed_ref
        if ref_kind == "conversation":
            return external_id
        task = await self.registry_inspection.get_task(authority_ref, external_id)
        return str(task.recipient_conversation_id or "").strip()

    async def _search_reachable_agents(self) -> tuple[DiscoveredAgentRef, ...]:
        agent_directory = self.agent_directory
        if agent_directory is None or not hasattr(agent_directory, "search_agents"):
            return ()
        try:
            result = await agent_directory.search_agents(query=AgentDiscoveryQuery())
        except Exception:
            return ()
        agents = []
        for agent in result.agents:
            if str(agent.slug or "").strip() == str(self.config.agent_slug or "").strip():
                continue
            agents.append(agent)
        return tuple(agents)

    def _resolve_target_agent(
        self,
        target: str,
        reachable_agents: tuple[DiscoveredAgentRef, ...],
    ) -> DiscoveredAgentRef | None:
        for agent in reachable_agents:
            if matches_exact_alias(
                target,
                identifier=agent.agent_id,
                slug=agent.slug,
                display_name=agent.display_name,
            ):
                return agent
        return None

    def _is_current_bot_target(self, target: str) -> bool:
        return matches_exact_alias(
            target,
            identifier="",
            slug=self.config.agent_slug,
            display_name=self.config.agent_display_name,
        )

    def _usage_target_label(
        self,
        target: DiscoveredAgentRef | None,
        *,
        fallback: str = "",
    ) -> str:
        if target is None:
            return self.config.agent_slug or self.config.agent_display_name or fallback
        return target.slug or target.display_name or target.agent_id or fallback
