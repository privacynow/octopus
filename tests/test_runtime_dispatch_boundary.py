from app.channels.telegram.cancellation import get_cancellation_registry
from app.channels.telegram.state import get_channel_state
from app.identity import telegram_actor_key, telegram_conversation_key
from app.runtime.dispatch import (
    RuntimeDispatchRuntime,
    run_provider_preflight,
    run_provider_request,
)
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    ExecutionSurfaceContext,
)
from app.workflows.execution.requests import execute_request, request_approval
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    fresh_env,
    load_session_disk,
)


async def _no_op(*args, **kwargs):
    del args, kwargs
    return None


def _dispatch_runtime(th) -> RuntimeDispatchRuntime:
    state = get_channel_state()
    return RuntimeDispatchRuntime(
        config=state.config,
        provider=state.provider,
        boot_id=state.boot_id,
        cancellations=get_cancellation_registry(),
        progress_factory=th.TelegramProgress,
        keep_typing=th.keep_typing,
        heartbeat=th._heartbeat,
        format_provider_error=th._format_provider_error,
        run_result_was_interrupted=th._run_result_was_interrupted,
    )


def _execution_runtime(th) -> ExecutionRuntime:
    return ExecutionRuntime(
        dispatch=_dispatch_runtime(th),
        build_surface_context=lambda _message, _chat_id: ExecutionSurfaceContext(),
        show_foreign_setup=_no_op,
        show_setup_prompt=_no_op,
        send_retry_prompt=_no_op,
        send_approval_prompt=_no_op,
        send_formatted_reply=th.send_formatted_reply,
        send_directed_artifacts=th.send_directed_artifacts,
        send_compact_reply=th._send_compact_reply,
        propose_delegation_plan=th._propose_delegation_plan,
    )


async def test_run_provider_request_uses_explicit_runtime_plumbing():
    import app.channels.telegram.routing as th

    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = _dispatch_runtime(th)

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
    import app.channels.telegram.routing as th

    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = _execution_runtime(th)

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
    import app.channels.telegram.routing as th

    approval_prompts: list[str] = []

    async def send_approval_prompt(_message) -> None:
        approval_prompts.append("approval")

    with fresh_env() as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = ExecutionRuntime(
            dispatch=_dispatch_runtime(th),
            build_surface_context=lambda _message, _chat_id: ExecutionSurfaceContext(),
            show_foreign_setup=_no_op,
            show_setup_prompt=_no_op,
            send_retry_prompt=_no_op,
            send_approval_prompt=send_approval_prompt,
            send_formatted_reply=th.send_formatted_reply,
            send_directed_artifacts=th.send_directed_artifacts,
            send_compact_reply=th._send_compact_reply,
            propose_delegation_plan=th._propose_delegation_plan,
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
