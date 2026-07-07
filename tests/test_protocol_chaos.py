from __future__ import annotations

from datetime import datetime, timedelta, timezone

from octopus_registry.postgres import get_connection
from octopus_registry.store_postgres import RegistryPostgresStore
from tests.support.protocol_support import operator_access, protocol_document, running_protocol_run


def test_protocol_timeout_and_duplicate_late_results_keep_one_terminal_run(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
            ],
        },
    )
    stage = detail.stage_executions[0]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET timeout_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    first_maintenance = store.run_protocol_maintenance()
    before = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    before_transition_ids = [item.protocol_transition_id for item in before.transitions]
    before_stage_ids = [item.protocol_stage_execution_id for item in before.stage_executions]

    payload = {
        "status": "completed",
        "transition_id": "late-duplicate",
        "summary": "Late completion.",
        "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Late completion.",
        "artifacts": [
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "protocol/plan.md",
                "exists": True,
                "size_bytes": 128,
                "content_hash": "late123",
                "modified_at": "2026-04-16T00:00:00+00:00",
                "verification_state": "verified",
            }
        ],
    }

    store.update_routed_task_result(enroll.agent_token, stage.routed_task_id, payload)
    store.update_routed_task_result(enroll.agent_token, stage.routed_task_id, payload)
    second_maintenance = store.run_protocol_maintenance()

    after = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert first_maintenance.swept_count == 1
    assert second_maintenance.swept_count == 0
    assert after.run.status == "failed"
    after_transition_ids = [item.protocol_transition_id for item in after.transitions]
    assert after_transition_ids[1:] == before_transition_ids
    assert after.transitions[0].transition_kind == "late_result"
    assert after.transitions[0].decision == "late_result_preserved"
    assert [item.protocol_stage_execution_id for item in after.stage_executions] == before_stage_ids
