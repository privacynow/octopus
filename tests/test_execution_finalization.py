import asyncio
import logging

import pytest

from app.session_state import DelegatedTask, PendingDelegation, SessionState
from app.workflows.execution.contracts import RequestExecutionOutcome
from app.workflows.execution.finalization import FinalizationContext, finalize_execution


@pytest.mark.asyncio
async def test_finalization_records_usage_publishes_timeline_and_schedules_webhook() -> None:
    usage_calls: list[dict[str, object]] = []
    timeline_calls: list[dict[str, object]] = []
    webhook_calls: list[dict[str, object]] = []

    async def fake_publish_timeline(config, **kwargs):
        del config
        timeline_calls.append(kwargs)

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
            publish_timeline_event=fake_publish_timeline,
            completion_webhook_sender=fake_webhook,
        ),
    )
    await asyncio.sleep(0)

    assert result.usage_status == "recorded"
    assert result.timeline_status == "published"
    assert result.webhook_status == "scheduled"
    assert len(usage_calls) == 1
    assert usage_calls[0]["work_item_id"] == "item-1"
    assert len(timeline_calls) == 1
    assert timeline_calls[0]["kind"] == "usage"
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
    reported: list[tuple[str, object]] = []

    class FakeClient:
        async def routed_task_result(self, routed_task_id, result):
            reported.append((routed_task_id, result))
            return {"ok": True}

    outcome = RequestExecutionOutcome(
        status="completed_with_denials",
        reply_text="Partial completion with denials.",
    )

    result = await finalize_execution(
        outcome,
        context=FinalizationContext(
            config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
            item_id="item-3",
            conversation_key="registry:conv-3",
            runtime_chat="registry:conv-3",
            conversation_ref="registry:conv-3",
            routed_task_id="task-3",
            registry_client_factory=lambda config: FakeClient(),
        ),
    )

    assert result.routed_result_status == "reported"
    assert len(reported) == 1
    routed_task_id, payload = reported[0]
    assert routed_task_id == "task-3"
    assert payload.status == "completed"
    assert "Partial completion" in payload.full_text


@pytest.mark.asyncio
async def test_finalization_reports_routed_task_result_through_explicit_registry_id() -> None:
    reported: list[tuple[str, object]] = []

    class FakeClient:
        async def routed_task_result(self, routed_task_id, result):
            reported.append((routed_task_id, result))
            return {"ok": True}

    fallback_used: list[bool] = []

    result = await finalize_execution(
        RequestExecutionOutcome(status="completed", reply_text="done"),
        context=FinalizationContext(
            config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
            item_id="item-3b",
            conversation_key="registry:prod:task:task-3b",
            runtime_chat="registry:prod:task:task-3b",
            conversation_ref="registry:prod:task:task-3b",
            routed_task_id="task-3b",
            registry_id="prod",
            registry_client_factory=lambda config: fallback_used.append(True),
            registry_client_for_registry=lambda registry_id: FakeClient() if registry_id == "prod" else None,
        ),
    )

    assert result.routed_result_status == "reported"
    assert fallback_used == []
    assert reported and reported[0][0] == "task-3b"


@pytest.mark.asyncio
async def test_finalization_usage_recording_failure_is_non_blocking() -> None:
    timeline_calls: list[dict[str, object]] = []

    async def fake_publish_timeline(config, **kwargs):
        del config
        timeline_calls.append(kwargs)

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
            publish_timeline_event=fake_publish_timeline,
        ),
    )

    assert result.usage_status == "record_failed_non_blocking"
    assert result.timeline_status == "published"
    assert len(timeline_calls) == 1


@pytest.mark.asyncio
async def test_finalization_report_failure_sets_user_warning(caplog) -> None:
    class FailingClient:
        async def routed_task_result(self, routed_task_id, result):
            del routed_task_id, result
            raise RuntimeError("registry internal stacktrace")

    with caplog.at_level(logging.ERROR):
        result = await finalize_execution(
            RequestExecutionOutcome(
                status="completed",
                reply_text="done",
            ),
            context=FinalizationContext(
                config=type("Cfg", (), {"data_dir": "/tmp/data", "provider_name": "claude", "completion_webhook_url": ""})(),
                item_id="item-5",
                conversation_key="registry:conv-5",
                runtime_chat="registry:conv-5",
                conversation_ref="registry:conv-5",
                routed_task_id="task-5",
                registry_client_factory=lambda config: FailingClient(),
            ),
        )

    assert result.routed_result_status == "report_failed"
    assert "could not be delivered to the requesting conversation" in result.routed_result_warning_text
    assert any("Failed to report routed task result" in record.message for record in caplog.records)
