import asyncio

import pytest

from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key, telegram_conversation_ref
from octopus_sdk.channels import ChannelDescriptor
from app.channels.telegram.delegation_channel import propose_delegation_plan
from app.channels.telegram.execution import (
    TelegramExecutionCollaborators,
    build_dispatch_runtime,
    execution_channel_metadata,
    build_execution_runtime,
    send_compact_reply,
    send_directed_artifacts,
)
from app.summarize import format_provider_error
from octopus_sdk.runtime_dispatch import (
    RuntimeDispatchRuntime,
    run_provider_preflight,
    run_provider_request,
)
from octopus_sdk.execution import (
    ExecutionRuntime,
    TransportIdentity,
    ExecutionChannelMetadata,
    RequestExecutionOutcome,
)
from octopus_sdk.execution import build_transport_identity_from_metadata
from octopus_sdk.execution import execute_request, request_approval
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    current_execution_runtime,
    current_runtime,
    fresh_env,
    load_session_disk,
)


async def _no_op(*args, **kwargs):
    del args, kwargs
    return None


class _GenericStatusHandle:
    pass


class _GenericProgress:
    def __init__(self, status_message, timeline_callback):
        self.status_message = status_message
        self.timeline_callback = timeline_callback
        self.content_started = None

    async def update(self, *_args, **_kwargs):
        return None


async def test_run_provider_request_uses_explicit_runtime_plumbing():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = current_execution_runtime().dispatch

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


async def test_run_provider_request_does_not_require_telegram_message_api():
    typing_targets: list[object] = []
    typing_started = asyncio.Event()

    async def fake_send_status(message, label: str):
        message.labels.append(label)
        return _GenericStatusHandle()

    async def fake_keep_typing(target):
        typing_targets.append(target)
        typing_started.set()
        await asyncio.sleep(0)

    with fresh_env() as (_data_dir, cfg, prov):
        target = object()
        original_run = prov.run

        async def delayed_run(provider_state, prompt, image_paths, progress, context=None, cancel=None):
            await typing_started.wait()
            return await original_run(
                provider_state,
                prompt,
                image_paths,
                progress,
                context=context,
                cancel=cancel,
            )

        prov.run = delayed_run

        class GenericMessage:
            def __init__(self):
                self.labels: list[str] = []
                self.target = target

        runtime = RuntimeDispatchRuntime(
            config=cfg,
            provider=prov,
            boot_id="dispatch-test",
            cancellations={},
            progress_factory=lambda status_message, _cfg, timeline_callback=None: _GenericProgress(
                status_message,
                timeline_callback,
            ),
            send_status=fake_send_status,
            typing_target=lambda message: message.target,
            keep_typing=fake_keep_typing,
            heartbeat=_no_op,
            format_provider_error=current_execution_runtime().dispatch.format_provider_error,
            run_result_was_interrupted=lambda _returncode: False,
        )
        message = GenericMessage()

        outcome = await run_provider_request(
            "registry:prod:conversation:conv-1",
            prompt="test prompt",
            image_paths=[],
            message=message,
            provider_state={},
            context=object(),
            label="Working",
            runtime=runtime,
        )

        assert outcome.result.text == "default response"
        assert message.labels == ["Working"]
        assert typing_targets == [target]
        assert runtime.cancellations == {}


def test_dispatch_runtime_uses_injected_collaborators() -> None:
    async def fake_heartbeat(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_propose(*args, **kwargs):
        del args, kwargs
        return RequestExecutionOutcome(status="completed")

    with fresh_env():
        collaborators = TelegramExecutionCollaborators(
            progress_factory=FakeChat,
            keep_typing=lambda chat: ("typing", chat),
            heartbeat=fake_heartbeat,
            build_conversation_progress_callback=lambda conversation_ref, routed_task_id: (
                lambda html_text, force=False: _no_op(
                    conversation_ref,
                    routed_task_id,
                    html_text,
                    force=force,
                )
            ),
            build_routed_task_progress_callback=lambda routed_task_id, authority_ref: (
                lambda html_text, force=False: _no_op(
                    routed_task_id,
                    authority_ref,
                    html_text,
                    force=force,
                )
            ),
            propose_delegation_plan=fake_propose,
        )

        runtime = build_dispatch_runtime(current_runtime(), collaborators=collaborators)

        assert runtime.progress_factory is FakeChat
        assert runtime.keep_typing("chat-1") == ("typing", "chat-1")
        assert runtime.heartbeat is fake_heartbeat


def test_execution_runtime_uses_injected_timeline_and_delegation_callbacks() -> None:
    async def fake_timeline(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_routed_task(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_propose(*args, **kwargs):
        del args, kwargs
        return RequestExecutionOutcome(status="completed")

    with fresh_env():
        collaborators = TelegramExecutionCollaborators(
            progress_factory=FakeChat,
            keep_typing=lambda chat: chat,
            heartbeat=_no_op,
            build_conversation_progress_callback=lambda _conversation_ref, _routed_task_id: fake_timeline,
            build_routed_task_progress_callback=lambda _routed_task_id, _authority_ref: fake_routed_task,
            propose_delegation_plan=fake_propose,
        )

        runtime = build_execution_runtime(current_runtime(), collaborators=collaborators)
        message = FakeMessage(chat=FakeChat(12345))
        message.conversation_ref = telegram_conversation_ref(current_runtime().config, 12345)
        context = runtime.build_transport_identity(message, 12345)

        assert context.timeline_callback is fake_timeline
        assert runtime.propose_delegation_plan is fake_propose


async def test_execute_request_runs_from_explicit_execution_runtime():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        runtime = current_execution_runtime()

        outcome = await execute_request(
            runtime.build_transport_identity(
                message,
                chat.id,
                actor_key=telegram_actor_key(42),
            ),
            "test prompt",
            [],
            message,
            runtime=runtime,
        )

        assert outcome is not None
        assert outcome.status == "completed"
        assert len(prov.run_calls) == 1


async def test_request_approval_runs_from_explicit_execution_runtime():
    approval_prompts: list[str] = []

    async def send_approval_prompt(_message, callback_token: str) -> None:
        approval_prompts.append(callback_token)

    with fresh_env() as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="hello")
        from octopus_sdk.event_sink import NoOpEventSink
        _noop = NoOpEventSink()
        base_runtime = current_execution_runtime()
        runtime = ExecutionRuntime(
            dispatch=base_runtime.dispatch,
            services=base_runtime.services,
            interrupted_exc=base_runtime.interrupted_exc,
            build_transport_identity=lambda _message, _chat_id, *, actor_key="": TransportIdentity(
                conversation_key=f"tg:{_chat_id}" if isinstance(_chat_id, int) else str(_chat_id),
                origin_channel="telegram" if isinstance(_chat_id, int) else "registry",
                external_conversation_ref=str(_chat_id),
                actor=actor_key or "tg:42",
            ),
            build_event_sink=lambda _transport: _noop,
            render_provider_error=lambda text: text,
            show_foreign_setup=_no_op,
            show_setup_prompt=_no_op,
            send_retry_prompt=_no_op,
            send_approval_prompt=send_approval_prompt,
            send_formatted_reply=current_execution_runtime().send_formatted_reply,
            send_directed_artifacts=lambda conversation_key_value, message, directives, resolved_ctx=None: send_directed_artifacts(
                conversation_key_value,
                message,
                directives,
                resolved_ctx,
                runtime=current_runtime(),
            ),
            send_compact_reply=send_compact_reply,
            propose_delegation_plan=lambda conversation_key_value, message, session, conversation_ref, result: propose_delegation_plan(
                current_runtime(),
                conversation_key_value,
                message,
                session,
                conversation_ref=conversation_ref,
                result=result,
            ),
        )

        await request_approval(
            runtime.build_transport_identity(
                message,
                chat.id,
                actor_key=telegram_actor_key(42),
            ),
            "please review files",
            [],
            [],
            message,
            runtime=runtime,
        )

        session = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        assert session.get("pending_approval") is not None
        assert len(prov.preflight_calls) == 1
        assert len(approval_prompts) == 1
        assert approval_prompts[0]


def test_workflow_context_builder_resolves_registry_conversation_metadata() -> None:
    context = build_transport_identity_from_metadata(
        ExecutionChannelMetadata(
            conversation_key="registry:conversation:12345",
            descriptor=ChannelDescriptor(
                channel_type="registry",
                display_name="Registry",
                supports_multiple=True,
                requires_polling=True,
                trust_tier="trusted",
                contributes_channel_capability=True,
                accepts_channel_input=True,
                supports_conversation_binding=True,
                supports_timeline=True,
            ),
            message_conversation_ref="registry:12345",
            routed_task_id="task-9",
        ),
        conversation_callback_factory=lambda conversation_ref, routed_task_id: (
            lambda html_text, force=False: _no_op(
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )
        ),
        routed_task_callback_factory=lambda routed_task_id, authority_ref: (
            lambda html_text, force=False: _no_op(
                routed_task_id,
                authority_ref,
                html_text,
                force=force,
            )
        ),
    )

    assert context.conversation_ref == "registry:12345"
    assert context.routed_task_id == "task-9"
    assert context.authority_ref == ""
    assert context.timeline_callback is not None


def test_workflow_context_builder_keeps_registry_task_without_timeline_callback() -> None:
    context = build_transport_identity_from_metadata(
        ExecutionChannelMetadata(
            conversation_key="registry:ops:task:task-1",
            descriptor=ChannelDescriptor(
                channel_type="registry",
                display_name="Registry Tasks",
                supports_multiple=True,
                requires_polling=True,
                trust_tier="trusted",
                contributes_channel_capability=False,
                accepts_channel_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            message_conversation_ref="registry:ops:task:task-1",
            routed_task_id="task-1",
            authority_ref="registry:ops",
        ),
        conversation_callback_factory=lambda conversation_ref, routed_task_id: (
            lambda html_text, force=False: _no_op(
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )
        ),
        routed_task_callback_factory=lambda routed_task_id, authority_ref: (
            lambda html_text, force=False: _no_op(
                routed_task_id,
                authority_ref,
                html_text,
                force=force,
            )
        ),
    )

    assert context.conversation_ref == "registry:ops:task:task-1"
    assert context.routed_task_id == "task-1"
    assert context.authority_ref == "registry:ops"
    assert context.timeline_callback is not None


async def test_workflow_context_builder_chooses_routed_task_callback_by_concern() -> None:
    observed: list[tuple[str, str, str]] = []

    async def fake_routed_task(html_text: str, force: bool = False) -> None:
        observed.append(("routed_task", html_text, str(force)))

    async def fake_conversation(html_text: str, force: bool = False) -> None:
        observed.append(("conversation", html_text, str(force)))

    context = build_transport_identity_from_metadata(
        ExecutionChannelMetadata(
            conversation_key="registry:ops:task:task-1",
            descriptor=ChannelDescriptor(
                channel_type="registry",
                display_name="Registry Tasks",
                supports_multiple=True,
                requires_polling=True,
                trust_tier="trusted",
                contributes_channel_capability=False,
                accepts_channel_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            message_conversation_ref="registry:ops:task:task-1",
            routed_task_id="task-1",
            authority_ref="registry:ops",
        ),
        conversation_callback_factory=lambda _conversation_ref, _routed_task_id: fake_conversation,
        routed_task_callback_factory=lambda _routed_task_id, _authority_ref: fake_routed_task,
    )

    assert context.timeline_callback is fake_routed_task
    await context.timeline_callback("working…", force=True)
    assert observed == [("routed_task", "working…", "True")]


def test_execution_channel_metadata_copies_authority_ref_from_inbound_message() -> None:
    with fresh_env():
        runtime = current_runtime()
        message = FakeMessage(chat=FakeChat(12345), text="hello")
        message.conversation_ref = "registry:ops:task:task-1"
        message.routed_task_id = "task-1"
        message.authority_ref = "registry:ops"

        metadata = execution_channel_metadata(runtime, message, 12345)

    assert metadata.message_conversation_ref == "registry:ops:task:task-1"
    assert metadata.routed_task_id == "task-1"
    assert metadata.authority_ref == "registry:ops"


def test_execution_channel_metadata_does_not_infer_authority_ref_from_registry_ref() -> None:
    with fresh_env():
        runtime = current_runtime()
        message = FakeMessage(chat=FakeChat(12345), text="hello")
        message.conversation_ref = "registry:ops:task:task-1"
        message.routed_task_id = "task-1"
        message.authority_ref = ""

        metadata = execution_channel_metadata(runtime, message, 12345)

    assert metadata.message_conversation_ref == "registry:ops:task:task-1"
    assert metadata.routed_task_id == "task-1"
    assert metadata.authority_ref == ""


@pytest.mark.asyncio
async def test_format_provider_error_returns_plain_text() -> None:
    text = await format_provider_error("<boom>", 1)

    assert text == "<boom>"
