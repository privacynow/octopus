import asyncio
import logging

import pytest

from app.agents.registry_capabilities import registry_authority_ref
from octopus_sdk.sessions import DelegatedTask, PendingDelegation, SessionState
from octopus_sdk.task_routing import TaskResultReport
from octopus_sdk.execution import RequestExecutionOutcome
from app.workflows.execution.finalization import FinalizationContext, finalize_execution


@pytest.mark.asyncio
async def test_finalization_records_usage_and_schedules_webhook() -> None:
    usage_calls: list[dict[str, object]] = []
    webhook_calls: list[dict[str, object]] = []

    async def fake_webhook(url, **kwargs):
        webhook_calls.append({"url": url, **kwargs})

    class Config:
        data_dir = "/tmp/data"
        provider_name = "claude"
        completion_webhook_url = "https://hooks.example.com/completed"

    outcome = RequestExecutionOutcome(
        status="completed",
        reply_text="All done.",
        prompt_tokens=12,
        completion_tokens=34,
        cost_usd=0.12,
    )

    result = await finalize_execution(
        outcome,
        context=FinalizationContext(
            config=Config(),
            item_id="item-1",
            conversation_key="telegram:123",
            runtime_chat=123,
            conversation_ref="registry:conv-1",
            chat_id=123,
            record_usage=lambda data_dir, **kwargs: usage_calls.append(
                {"data_dir": data_dir, **kwargs}
            ),
            completion_webhook_sender=fake_webhook,
        ),
    )
    await asyncio.sleep(0)

    assert result.usage_status == "recorded"
    assert result.timeline_status == "skipped"
    assert result.webhook_status == "scheduled"
    assert len(usage_calls) == 1
    assert usage_calls[0]["work_item_id"] == "item-1"
    assert len(webhook_calls) == 1
    assert webhook_calls[0]["url"] == "https://hooks.example.com/completed"
    assert webhook_calls[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_finalization_clears_resumed_delegation_after_outcome() -> None:
    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="on",
        pending_delegation=PendingDelegation(
            conversation_ref="registry:conv-2",
            status="completed",
            tasks=[DelegatedTask(routed_task_id="task-1", status="completed")],
        ),
    )
    saved: list[SessionState] = []

    result = await finalize_execution(
        RequestExecutionOutcome(status="completed", reply_text="done"),
        context=FinalizationContext(
            config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
            item_id="item-2",
            conversation_key="registry:conv-2",
            runtime_chat="registry:conv-2",
            conversation_ref="registry:conv-2",
            skip_approval=True,
            load_session=lambda chat: session,
            save_session=lambda chat, updated: saved.append(updated),
        ),
    )

    assert result.delegation_status == "cleared_after_resume"
    assert len(saved) == 1
    assert saved[0].pending_delegation is None


@pytest.mark.asyncio
async def test_finalization_reports_routed_task_result() -> None:
    reported: list[dict[str, object]] = []

    class FakeTaskRouting:
        async def report_routed_task_result(self, *, routed_task_id, authority_ref, result):
            reported.append(
                {
                    "routed_task_id": routed_task_id,
                    "authority_ref": authority_ref,
                    "result": result,
                }
            )
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

    outcome = RequestExecutionOutcome(
        status="completed_with_denials",
        reply_text="Partial completion with denials.",
    )

    result = await finalize_execution(
        outcome,
        context=FinalizationContext(
            config=type(
                "Cfg",
                (),
                {
                    "data_dir": "/tmp/data",
                    "provider_name": "claude",
                    "completion_webhook_url": "",
                },
            )(),
            item_id="item-3",
            conversation_key="registry:conv-3",
            runtime_chat="registry:conv-3",
            conversation_ref="registry:conv-3",
            routed_task_id="task-3",
            authority_ref=registry_authority_ref("default"),
            task_routing=FakeTaskRouting(),
        ),
    )

    assert result.routed_result_status == "reported"
    assert len(reported) == 1
    assert reported[0]["routed_task_id"] == "task-3"
    assert reported[0]["authority_ref"] == registry_authority_ref("default")
    payload = reported[0]["result"]
    assert payload.status == "completed"
    assert "Partial completion" in payload.full_text


@pytest.mark.asyncio
async def test_finalization_reports_routed_task_result_through_explicit_authority_ref() -> None:
    reported: list[dict[str, object]] = []

    class FakeTaskRouting:
        async def report_routed_task_result(self, *, routed_task_id, authority_ref, result):
            reported.append(
                {
                    "routed_task_id": routed_task_id,
                    "authority_ref": authority_ref,
                    "result": result,
                }
            )
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

    result = await finalize_execution(
        RequestExecutionOutcome(status="completed", reply_text="done"),
        context=FinalizationContext(
            config=type(
                "Cfg",
                (),
                {
                    "data_dir": "/tmp/data",
                    "provider_name": "claude",
                    "completion_webhook_url": "",
                },
            )(),
            item_id="item-3b",
            conversation_key="registry:prod:task:task-3b",
            runtime_chat="registry:prod:task:task-3b",
            conversation_ref="registry:prod:task:task-3b",
            routed_task_id="task-3b",
            authority_ref=registry_authority_ref("prod"),
            task_routing=FakeTaskRouting(),
        ),
    )

    assert result.routed_result_status == "reported"
    assert reported and reported[0]["routed_task_id"] == "task-3b"
    assert reported[0]["authority_ref"] == registry_authority_ref("prod")


@pytest.mark.asyncio
async def test_finalization_skips_completion_webhook_for_routed_task() -> None:
    webhook_calls: list[dict[str, object]] = []

    class FakeTaskRouting:
        async def report_routed_task_result(self, *, routed_task_id, authority_ref, result):
            del authority_ref, result
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

    async def fake_webhook(url, **kwargs):
        webhook_calls.append({"url": url, **kwargs})

    result = await finalize_execution(
        RequestExecutionOutcome(status="completed", reply_text="done"),
        context=FinalizationContext(
            config=type(
                "Cfg",
                (),
                {
                    "data_dir": "/tmp/data",
                    "provider_name": "claude",
                    "completion_webhook_url": "https://hooks.example.com/completed",
                },
            )(),
            item_id="item-3c",
            conversation_key="registry:prod:task:task-3c",
            runtime_chat="registry:prod:task:task-3c",
            conversation_ref="registry:prod:task:task-3c",
            routed_task_id="task-3c",
            authority_ref=registry_authority_ref("prod"),
            task_routing=FakeTaskRouting(),
            completion_webhook_sender=fake_webhook,
        ),
    )
    await asyncio.sleep(0)

    assert result.routed_result_status == "reported"
    assert result.webhook_status == "skipped"
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_finalization_usage_recording_failure_is_non_blocking() -> None:
    def exploding_usage(*args, **kwargs):
        raise RuntimeError("usage store unavailable")

    result = await finalize_execution(
        RequestExecutionOutcome(
            status="completed",
            reply_text="done",
            prompt_tokens=1,
            completion_tokens=2,
        ),
        context=FinalizationContext(
            config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
            item_id="item-4",
            conversation_key="telegram:123",
            runtime_chat=123,
            conversation_ref="registry:conv-4",
            chat_id=123,
            record_usage=exploding_usage,
        ),
    )

    assert result.usage_status == "record_failed_non_blocking"
    assert result.timeline_status == "skipped"


@pytest.mark.asyncio
async def test_finalization_skips_usage_timeline_for_routed_task() -> None:
    result = await finalize_execution(
        RequestExecutionOutcome(
            status="completed",
            reply_text="done",
            prompt_tokens=1,
            completion_tokens=2,
        ),
        context=FinalizationContext(
            config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
            item_id="item-4b",
            conversation_key="registry:prod:task:task-4b",
            runtime_chat="registry:prod:task:task-4b",
            conversation_ref="registry:prod:task:task-4b",
            routed_task_id="task-4b",
            authority_ref=registry_authority_ref("prod"),
        ),
    )

    assert result.timeline_status == "skipped"


@pytest.mark.asyncio
async def test_finalization_report_failure_emits_partialfailed_fallback(caplog) -> None:
    status_updates: list[tuple[str, object]] = []

    class FailingTaskRouting:
        async def report_routed_task_result(self, *, routed_task_id, authority_ref, result):
            del routed_task_id, authority_ref, result
            return TaskResultReport(status="failed", error="registry internal stacktrace")

        async def update_routed_task_status(self, *, update, authority_ref):
            status_updates.append((authority_ref, update))

    with caplog.at_level(logging.ERROR):
        result = await finalize_execution(
            RequestExecutionOutcome(
                status="completed",
                reply_text="done",
            ),
            context=FinalizationContext(
                config=type(
                    "Cfg",
                    (),
                    {
                        "data_dir": "/tmp/data",
                        "provider_name": "claude",
                        "completion_webhook_url": "",
                    },
                )(),
                item_id="item-5",
                conversation_key="registry:conv-5",
                runtime_chat="registry:conv-5",
                conversation_ref="registry:conv-5",
                routed_task_id="task-5",
                authority_ref=registry_authority_ref("default"),
                task_routing=FailingTaskRouting(),
            ),
        )

    assert result.routed_result_status == "report_failed"
    assert any("Failed to report routed task result" in record.message for record in caplog.records)
    assert len(status_updates) == 1
    authority_ref, update = status_updates[0]
    assert authority_ref == registry_authority_ref("default")
    assert update.routed_task_id == "task-5"
    assert update.status == "partialfailed"
    assert "could not be delivered" in update.summary
