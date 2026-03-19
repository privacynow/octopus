import pytest

from app.identity import telegram_actor_key, telegram_conversation_key
from app.channels.telegram.delegation_channel import propose_delegation_plan
from app.channels.telegram.execution import (
    build_dispatch_runtime,
    build_execution_runtime,
    send_compact_reply,
    send_directed_artifacts,
)
from app.summarize import format_provider_error
from app.runtime.dispatch import (
    run_provider_preflight,
    run_provider_request,
)
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    ExecutionChannelContext,
    ExecutionChannelMetadata,
)
from app.workflows.execution.context import build_execution_channel_context
from app.workflows.execution.requests import execute_request, request_approval
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    current_runtime,
    fresh_env,
    load_session_disk,
)


async def _no_op(*args, **kwargs):
    del args, kwargs
    return None


async def test_run_provider_request_uses_explicit_runtime_plumbing():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = build_dispatch_runtime(current_runtime())

        outcome = await run_provider_request(
            chat.id,
            prompt="test prompt",
            image_paths=[],
            message=message,
            provider_state={},
            context=object(),
            label="Working",
            runtime=runtime,
        )

        assert outcome.result.text == "default response"
        assert len(prov.run_calls) == 1


async def test_execute_request_runs_from_explicit_execution_runtime():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = build_execution_runtime(current_runtime())

        outcome = await execute_request(
            chat.id,
            "test prompt",
            [],
            message,
            request_user_id=telegram_actor_key(42),
            runtime=runtime,
        )

        assert outcome is not None
        assert outcome.status == "completed"
        assert len(prov.run_calls) == 1


async def test_request_approval_runs_from_explicit_execution_runtime():
    approval_prompts: list[str] = []

    async def send_approval_prompt(_message) -> None:
        approval_prompts.append("approval")

    with fresh_env() as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = ExecutionRuntime(
            dispatch=build_dispatch_runtime(current_runtime()),
            build_channel_context=lambda _message, _chat_id: ExecutionChannelContext(),
            render_provider_error=lambda text: text,
            show_foreign_setup=_no_op,
            show_setup_prompt=_no_op,
            send_retry_prompt=_no_op,
            send_approval_prompt=send_approval_prompt,
            send_formatted_reply=build_execution_runtime(current_runtime()).send_formatted_reply,
            send_directed_artifacts=lambda chat_id, message, directives, resolved_ctx=None: send_directed_artifacts(
                chat_id,
                message,
                directives,
                resolved_ctx,
                runtime=current_runtime(),
            ),
            send_compact_reply=send_compact_reply,
            propose_delegation_plan=lambda chat_id, message, session, conversation_ref, result: propose_delegation_plan(
                current_runtime(),
                chat_id,
                message,
                session,
                conversation_ref=conversation_ref,
                result=result,
            ),
        )

        await request_approval(
            chat.id,
            "please review files",
            [],
            [],
            message,
            request_user_id=telegram_actor_key(42),
            runtime=runtime,
        )

        session = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        assert session.get("pending_approval") is not None
        assert len(prov.preflight_calls) == 1
        assert approval_prompts == ["approval"]


def test_workflow_context_builder_resolves_registry_conversation_metadata() -> None:
    context = build_execution_channel_context(
        ExecutionChannelMetadata(
            channel_name="telegram",
            message_conversation_ref="",
            routed_task_id="task-9",
            chat_id=12345,
            agent_mode="registry",
        ),
        build_conversation_ref=lambda chat_id: f"registry:{chat_id}",
        timeline_callback_factory=lambda conversation_ref, routed_task_id: (
            lambda html_text, force=False: _no_op(
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )
        ),
    )

    assert context.conversation_ref == "registry:12345"
    assert context.routed_task_id == "task-9"
    assert context.timeline_callback is not None


@pytest.mark.asyncio
async def test_format_provider_error_returns_plain_text() -> None:
    text = await format_provider_error("<boom>", 1)

    assert text == "<boom>"
