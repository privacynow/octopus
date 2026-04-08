from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.skill_inspection_service import SkillInspectionService
from octopus_sdk.agent_directory import AgentSearchResult
from octopus_sdk.registry.models import ConversationRecord, EventPageRecord, EventRecord, TaskRecord
from octopus_sdk.registry_inspection import NoOpRegistryInspection
from octopus_sdk.runtime.skills import (
    SkillFollowUpSubject,
    SkillQuestionIntent,
    parse_skill_question,
)
from tests.support.config_support import make_config
from tests.support.service_support import build_test_bot_services


@dataclass
class _FakeAgentDirectory:
    agents: list[dict[str, object]]
    queries: list[object] = field(default_factory=list)

    async def search_agents(self, *, query) -> AgentSearchResult:
        self.queries.append(query)
        return AgentSearchResult(
            status="complete",
            agents=[
                {
                    "authority_ref": "registry:default",
                    "agent_id": str(item.get("agent_id", "")),
                    "display_name": str(item.get("display_name", "")),
                    "slug": str(item.get("slug", "")),
                    "role": str(item.get("role", "")),
                    "routing_skills": list(item.get("routing_skills", [])),
                    "tags": list(item.get("tags", [])),
                    "description": str(item.get("description", "")),
                    "connectivity_state": "connected",
                    "current_capacity": 0,
                    "max_capacity": 1,
                }
                for item in self.agents
            ],
        )


@dataclass
class _FakeRegistryInspection:
    conversation: ConversationRecord | None = None
    task: TaskRecord | None = None
    events: EventPageRecord | None = None

    async def get_conversation(self, authority_ref: str, conversation_id: str) -> ConversationRecord:
        del authority_ref, conversation_id
        if self.conversation is None:
            raise RuntimeError("missing conversation")
        return self.conversation

    async def get_task(self, authority_ref: str, routed_task_id: str) -> TaskRecord:
        del authority_ref, routed_task_id
        if self.task is None:
            raise RuntimeError("missing task")
        return self.task

    async def list_events(
        self,
        authority_ref: str,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        del authority_ref, conversation_id, kind, before_seq, after_seq, limit
        return self.events or EventPageRecord(events=[])


async def test_skill_inspection_separates_local_state_from_reachable_routing(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    directory = _FakeAgentDirectory(
        agents=[
            {
                "agent_id": "agent-self",
                "slug": config.agent_slug,
                "display_name": config.agent_display_name,
                "role": "generalist",
                "routing_skills": [],
            },
            {
                "agent_id": "agent-m3",
                "slug": "m3",
                "display_name": "M3",
                "role": "specialist",
                "routing_skills": ["architecture"],
            },
        ]
    )
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=directory,
        registry_inspection=NoOpRegistryInspection(),
    )

    response = await service.inspect_text(
        text="is architecture available?",
        conversation_key="stub:conversation:status",
        conversation_ref="stub:conversation:status",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.intent.kind == "skill_status"
    assert response.installed_on_current_bot is True
    assert response.runtime_available_on_current_bot is True
    assert response.active_in_current_conversation is False
    assert response.advertised_for_routing_on_current_bot is False
    assert [item.label for item in response.reachable_bots] == ["m3"]


async def test_skill_inspection_remote_target_reports_routing_advertisement_only(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(
            agents=[
                {
                    "agent_id": "agent-m1",
                    "slug": "m1",
                    "display_name": "Lift and Shift M1",
                    "role": "specialist",
                    "routing_skills": ["wisdom"],
                }
            ]
        ),
        registry_inspection=NoOpRegistryInspection(),
    )

    response = await service.inspect_text(
        text="is wisdom available on @m1?",
        conversation_key="stub:conversation:remote-status",
        conversation_ref="stub:conversation:remote-status",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.status_scope == "reachable_bot"
    assert response.remote_target_label == "m1"
    assert response.remote_advertised_for_routing is True


async def test_skill_inspection_usage_reads_cross_bot_manifest_from_registry(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(
            agents=[
                {
                    "agent_id": "agent-m1",
                    "slug": "m1",
                    "display_name": "Lift and Shift M1",
                    "role": "specialist",
                    "routing_skills": ["wisdom"],
                }
            ]
        ),
        registry_inspection=_FakeRegistryInspection(
            conversation=ConversationRecord(
                conversation_id="parent-1",
                linked_routed_tasks=[
                    TaskRecord(
                        routed_task_id="task-1",
                        target_agent_id="agent-m1",
                        target_display_name="Lift and Shift M1",
                        recipient_conversation_id="task-thread-1",
                        updated_at="2026-04-03T22:27:00+00:00",
                        created_at="2026-04-03T22:27:00+00:00",
                    )
                ],
            ),
            events=EventPageRecord(
                events=[
                    EventRecord(
                        seq=9,
                        event_id="evt-request",
                        conversation_id="task-thread-1",
                        kind="provider.request",
                        metadata={
                            "skill_manifest": {
                                "schema_version": 1,
                                "routed_task_id": "task-1",
                                "conversation_key": "delegation:parent-1",
                                "bot_slug": "m1",
                                "requested_skills": ["wisdom"],
                                "active_skills": ["wisdom"],
                                "composed_skill_slugs": ["wisdom"],
                                "composed_track_revision_ids": ["rev-1"],
                                "invoked_skill_slugs": [],
                                "skill_kind_map": {"wisdom": "prompt"},
                                "prompt_manifest_hash": "hash-1",
                            }
                        },
                    )
                ]
            ),
        ),
    )

    response = await service.inspect_text(
        text="did @m1 use wisdom skill?",
        conversation_key="registry:conversation:parent-1",
        conversation_ref="registry:default:conversation:parent-1",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.evidence_status == "found"
    assert response.requested_for_run is True
    assert response.active_for_run is True
    assert response.composed_for_run is True
    assert response.skill_kind == "prompt"


async def test_skill_inspection_usage_prefers_manifest_matching_routed_task_id(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(
            agents=[
                {
                    "agent_id": "agent-m1",
                    "slug": "m1",
                    "display_name": "Lift and Shift M1",
                    "role": "specialist",
                    "routing_skills": ["wisdom"],
                }
            ]
        ),
        registry_inspection=_FakeRegistryInspection(
            conversation=ConversationRecord(
                conversation_id="parent-1",
                linked_routed_tasks=[
                    TaskRecord(
                        routed_task_id="task-1",
                        target_agent_id="agent-m1",
                        target_display_name="Lift and Shift M1",
                        recipient_conversation_id="task-thread-1",
                        updated_at="2026-04-03T22:27:00+00:00",
                        created_at="2026-04-03T22:27:00+00:00",
                    )
                ],
            ),
            events=EventPageRecord(
                events=[
                    EventRecord(
                        seq=11,
                        event_id="evt-other",
                        conversation_id="task-thread-1",
                        kind="provider.request",
                        metadata={
                            "skill_manifest": {
                                "schema_version": 1,
                                "routed_task_id": "task-2",
                                "conversation_key": "delegation:parent-1",
                                "bot_slug": "m1",
                                "requested_skills": [],
                                "active_skills": [],
                                "composed_skill_slugs": [],
                                "composed_track_revision_ids": [],
                                "invoked_skill_slugs": [],
                                "skill_kind_map": {},
                                "prompt_manifest_hash": "hash-2",
                            }
                        },
                    ),
                    EventRecord(
                        seq=9,
                        event_id="evt-target",
                        conversation_id="task-thread-1",
                        kind="provider.request",
                        metadata={
                            "skill_manifest": {
                                "schema_version": 1,
                                "routed_task_id": "task-1",
                                "conversation_key": "delegation:parent-1",
                                "bot_slug": "m1",
                                "requested_skills": ["wisdom"],
                                "active_skills": ["wisdom"],
                                "composed_skill_slugs": ["wisdom"],
                                "composed_track_revision_ids": ["rev-1"],
                                "invoked_skill_slugs": [],
                                "skill_kind_map": {"wisdom": "prompt"},
                                "prompt_manifest_hash": "hash-1",
                            }
                        },
                    ),
                ]
            ),
        ),
    )

    response = await service.inspect_text(
        text="did @m1 use wisdom skill?",
        conversation_key="registry:conversation:parent-1",
        conversation_ref="registry:default:conversation:parent-1",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.routed_task_id == "task-1"
    assert response.requested_for_run is True
    assert response.composed_for_run is True


async def test_skill_inspection_usage_does_not_make_claim_without_manifest(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(
            agents=[
                {
                    "agent_id": "agent-m1",
                    "slug": "m1",
                    "display_name": "Lift and Shift M1",
                    "role": "specialist",
                    "routing_skills": ["wisdom"],
                }
            ]
        ),
        registry_inspection=_FakeRegistryInspection(
            conversation=ConversationRecord(
                conversation_id="parent-1",
                linked_routed_tasks=[
                    TaskRecord(
                        routed_task_id="task-1",
                        target_agent_id="agent-m1",
                        target_display_name="Lift and Shift M1",
                        recipient_conversation_id="task-thread-1",
                    )
                ],
            ),
            events=EventPageRecord(
                events=[
                    EventRecord(
                        seq=9,
                        event_id="evt-request",
                        conversation_id="task-thread-1",
                        kind="provider.request",
                        metadata={},
                    )
                ]
            ),
        ),
    )

    response = await service.inspect_text(
        text="did @m1 use wisdom skill?",
        conversation_key="registry:conversation:parent-1",
        conversation_ref="registry:default:conversation:parent-1",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.evidence_status == "missing"
    assert response.requested_for_run is None
    assert response.composed_for_run is None


async def test_skill_inspection_returns_ambiguity_for_pronoun_without_subject(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(agents=[]),
        registry_inspection=NoOpRegistryInspection(),
    )

    response = await service.inspect_text(
        text="is it active right now?",
        conversation_key="stub:conversation:pronoun",
        conversation_ref="stub:conversation:pronoun",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.status == "ambiguous"
    assert response.skill_name == ""
    assert response.note == "Which skill do you mean?"


async def test_skill_inspection_resolves_pronoun_from_last_subject(tmp_path) -> None:
    config = make_config(data_dir=tmp_path)
    services = build_test_bot_services(config=config)
    conversation_key = "stub:conversation:pronoun-follow-up"
    session = services.sessions.load(
        conversation_key,
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
        approval_mode=config.approval_mode,
        default_role=config.role,
        default_skills=config.default_skills,
    )
    session.last_skill_subject = SkillFollowUpSubject(skill_name="wisdom", target_agent="m1", routed_task_id="task-1")
    services.sessions.save(conversation_key, session)
    service = SkillInspectionService(
        config=config,
        workflows=services.workflows,
        agent_directory=_FakeAgentDirectory(
            agents=[
                {
                    "agent_id": "agent-m1",
                    "slug": "m1",
                    "display_name": "Lift and Shift M1",
                    "role": "specialist",
                    "routing_skills": ["wisdom"],
                }
            ]
        ),
        registry_inspection=NoOpRegistryInspection(),
    )

    response = await service.inspect_text(
        text="is it active right now?",
        conversation_key=conversation_key,
        conversation_ref="stub:conversation:pronoun-follow-up",
        provider_name=config.provider_name,
        provider_state_factory=lambda key: {"conversation_key": key},
    )

    assert response is not None
    assert response.skill_name == "wisdom"
    assert response.status_scope == "reachable_bot"
    assert response.remote_target_label == "m1"


def test_parse_skill_question_handles_common_paraphrase() -> None:
    intent = parse_skill_question(
        "do we have architecture available here right now",
        known_skill_names=("architecture", "wisdom"),
    )

    assert intent is not None
    assert intent.kind == "skill_status"
    assert intent.skill_name == "architecture"
    assert intent.status_focus == "available"


@pytest.mark.parametrize(
    "text",
    [
        "which skill is active here",
        "which skill is active in this conversation",
        "what skill is active",
        "what skill am I using in this conversation",
        "I activated a skill for this conversation, which one is it?",
        "which skill did I just activate",
        "what did I just activate here",
        "which one did I activate",
    ],
)
def test_parse_skill_question_handles_active_skill_meta_questions(text: str) -> None:
    intent = parse_skill_question(
        text,
        known_skill_names=("architecture", "wisdom"),
    )

    assert intent is not None
    assert intent.kind == "skill_list"
    assert intent.status_focus == "active"
