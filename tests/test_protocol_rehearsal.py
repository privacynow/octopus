"""E2E coverage for the rehearsal authority (plan §6).

A rehearsal run is a real protocol run whose dispatch selector is rewritten to
target the reserved ``rehearsal`` role. The in-process
:class:`RehearsalSessionManager` enrolls that agent, polls for routed tasks,
and completes them with author-supplied responses — without invoking any
external transport. These tests walk the full flow end to end against the
Postgres store.
"""

from __future__ import annotations

from octopus_sdk.protocols import REHEARSAL_AUTHORITY_REF
from octopus_registry.rehearsal import RehearsalSessionManager, REHEARSAL_AGENT_SLUG
from octopus_registry.store_postgres import RegistryPostgresStore
from tests.support.protocol_support import operator_access, published_protocol


def _enrol_rehearsal_agent(store: RegistryPostgresStore) -> tuple[str, str, RehearsalSessionManager]:
    manager = RehearsalSessionManager(store=store)
    agent_id, token = manager.ensure_agent()
    assert agent_id
    assert token
    return agent_id, token, manager


def _simple_rehearsable_document() -> dict[str, object]:
    """Protocol with non-write-capable stages so rehearsal advance logic can be
    tested independently of artifact contracts. Real rehearsal supports
    write-capable stages too, but the engine then requires artifact
    observations — out of scope for this test."""
    return {
        "metadata": {
            "slug": "rehearsable-protocol",
            "display_name": "Rehearsable Protocol",
            "description": "Simple two-stage protocol for rehearsal coverage.",
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "reviewer", "display_name": "Reviewer"},
        ],
        "artifacts": [],
        "stages": [
            {
                "stage_key": "planning",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "planning"},
                "stage_kind": "work",
                "write_capable": False,
                "inputs": [],
                "outputs": [],
                "transitions": {"completed": "review"},
                "instructions": "Draft a plan description.",
            },
            {
                "stage_key": "review",
                "participant_key": "reviewer",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "review",
                "inputs": [],
                "outputs": [],
                "transitions": {
                    "accept": "__complete__",
                    "revise": "planning",
                    "fail": "__failed__",
                },
                "instructions": "Review the plan.",
            },
        ],
        "policies": {"single_active_writer": False, "max_review_rounds": 3},
    }


def test_rehearsal_run_targets_reserved_agent_and_marks_authority(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    rehearsal_agent_id, _token, _manager = _enrol_rehearsal_agent(store)
    published = published_protocol(store, document=_simple_rehearsable_document())

    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": rehearsal_agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Rehearse the plan.",
            "constraints_json": {},
            "is_rehearsal": True,
        },
        access=operator_access(),
    )
    assert created.ok is True
    assert created.run is not None
    assert created.run.is_rehearsal is True
    assert created.run.entry_authority_ref == REHEARSAL_AUTHORITY_REF

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.run.is_rehearsal is True
    first_stage = detail.stage_executions[0]
    assert first_stage.routed_task_id.startswith("protocol-stage:")

    task = store.get_task(first_stage.routed_task_id)
    assert str(task.target_agent_id or "") == rehearsal_agent_id, (
        "Rehearsal stage dispatch must target the reserved rehearsal agent"
    )


def test_rehearsal_authority_reserved_when_is_rehearsal_is_false(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    rehearsal_agent_id, _token, _manager = _enrol_rehearsal_agent(store)
    published = published_protocol(store, document=_simple_rehearsable_document())

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": rehearsal_agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Must fail.",
            "constraints_json": {},
            "entry_authority_ref": REHEARSAL_AUTHORITY_REF,
            "is_rehearsal": False,
        },
        access=operator_access(),
    )
    assert result.ok is False
    assert result.status == "invalid"
    assert "reserved" in (result.message or "").lower()


def test_rehearsal_manager_queues_and_completes_stage_without_external_egress(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    rehearsal_agent_id, rehearsal_token, manager = _enrol_rehearsal_agent(store)
    published = published_protocol(store, document=_simple_rehearsable_document())

    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": rehearsal_agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Rehearse the plan.",
            "constraints_json": {},
            "is_rehearsal": True,
        },
        access=operator_access(),
    )
    assert created.ok is True
    run_id = created.run.protocol_run_id

    # Polling is the rehearsal bot's only interface to the store; run one
    # tick synchronously to capture the dispatched stage as a pending session.
    manager._poll_once_sync()
    pending = manager.list_pending(protocol_run_id=run_id)
    assert len(pending) == 1, "Rehearsal bot must queue the first dispatched stage"
    first_session = pending[0]
    assert first_session.stage_key == "planning"
    assert first_session.participant_key == "worker"
    assert first_session.routed_task_id.startswith("protocol-stage:")

    # Reject unknown routed task ids — no silent no-ops.
    assert manager.respond(routed_task_id="protocol-stage:unknown", response_text="nope") is False

    # Submitting the response must complete the task and advance the run.
    accepted = manager.respond(
        routed_task_id=first_session.routed_task_id,
        response_text="Plan drafted by the author.",
        decision="completed",
    )
    assert accepted is True
    assert manager.list_pending(protocol_run_id=run_id) == [], (
        "Session must be removed after a successful response"
    )

    advanced = store.get_protocol_run(run_id, access=operator_access())
    assert advanced.run.current_stage_key == "review", (
        "Rehearsal response must drive the engine to the next stage"
    )

    # Rehearsal agent is enrolled with the reserved slug; no real participant
    # bot is ever selected, so external transports cannot fire.
    agents = store.list_agents(for_agent_id=rehearsal_agent_id, limit=1)
    assert agents, "Rehearsal agent must be discoverable in the registry"
    rehearsal_card = agents[0]
    assert str(rehearsal_card.slug or "") == REHEARSAL_AGENT_SLUG
    assert str(rehearsal_card.role or "") == "rehearsal"


def test_protocol_scenarios_round_trip_through_store(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store, document=_simple_rehearsable_document())

    empty = store.list_protocol_scenarios(
        protocol_id=published.protocol.protocol_id,
        access=operator_access(),
    )
    assert empty == []

    created = store.create_protocol_scenario(
        payload={
            "protocol_id": published.protocol.protocol_id,
            "stage_key": "planning",
            "participant_key": "worker",
            "display_name": "Happy path plan",
            "response_text": "Plan drafted; ready for review.",
        },
        access=operator_access(),
    )
    assert created.protocol_scenario_id
    assert created.protocol_id == published.protocol.protocol_id
    assert created.display_name == "Happy path plan"

    listed = store.list_protocol_scenarios(
        protocol_id=published.protocol.protocol_id,
        access=operator_access(),
    )
    assert [s.protocol_scenario_id for s in listed] == [created.protocol_scenario_id]

    deleted = store.delete_protocol_scenario(
        scenario_id=created.protocol_scenario_id,
        access=operator_access(),
    )
    assert deleted is True

    again = store.list_protocol_scenarios(
        protocol_id=published.protocol.protocol_id,
        access=operator_access(),
    )
    assert again == []
