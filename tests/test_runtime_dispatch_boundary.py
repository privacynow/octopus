from app.channels.telegram.cancellation import get_cancellation_registry
from app.channels.telegram.state import get_channel_state
from app.identity import telegram_actor_key
from app.runtime.dispatch import RuntimeDispatchRuntime, execute_request
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeProvider,
    fresh_env,
)


async def test_execute_request_runs_from_explicit_dispatch_runtime():
    import app.channels.telegram.ingress as th

    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        state = get_channel_state()
        runtime = RuntimeDispatchRuntime(
            config=state.config,
            provider=prov,
            boot_id=state.boot_id,
            cancellations=get_cancellation_registry(),
            progress_factory=th.TelegramProgress,
            keep_typing=th.keep_typing,
            heartbeat=th._heartbeat,
            format_provider_error=th._format_provider_error,
            run_result_was_interrupted=th._run_result_was_interrupted,
            progress_timeline_callback=th._progress_timeline_callback,
            send_formatted_reply=th.send_formatted_reply,
            send_directed_artifacts=th.send_directed_artifacts,
            send_compact_reply=th._send_compact_reply,
            propose_delegation_plan=th._propose_delegation_plan,
        )

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
