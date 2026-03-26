import asyncio
from dataclasses import fields

import pytest

from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key, telegram_conversation_ref
from octopus_sdk.transport import TransportDescriptor
from app.channels.telegram.execution import (
    TelegramExecutionCollaborators,
    TelegramExecutionMessage,
    build_transport_identity as build_telegram_transport_identity,
    build_dispatch_runtime,
    execution_channel_metadata,
    build_execution_runtime,
)
from app.summarize import format_provider_error
from octopus_sdk.bot_runtime import (
    ProviderDispatchRuntime,
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
    async def edit_text(self, text: str, **kwargs):
        del text, kwargs

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        del reply_markup, kwargs


class _GenericProgress:
    def __init__(self, status_message, _config, timeline_callback=None):
        self.status_message = status_message
        self.timeline_callback = timeline_callback
        self.content_started = None

    async def update(self, *_args, **_kwargs):
        return None


async def test_run_provider_request_uses_explicit_runtime_plumbing():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="hello"))
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
                self.actions: list[str] = []
                self.target = target

            async def send_status(self, label: str):
                self.labels.append(label)
                return _GenericStatusHandle()

            def typing_target(self):
                return self

            async def send_action(self, action: str) -> None:
                self.actions.append(action)
                typing_targets.append(target)
                typing_started.set()
                del action

        runtime = ProviderDispatchRuntime(
            config=cfg,
            provider=prov,
            boot_id="dispatch-test",
            cancellations={},
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


def test_dispatch_runtime_has_no_callable_constructor_fields() -> None:
    with fresh_env():
        collaborators = TelegramExecutionCollaborators(
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
        )
        runtime = build_dispatch_runtime(current_runtime(), collaborators=collaborators)
        assert [field.name for field in fields(ProviderDispatchRuntime)] == [
            "config",
            "provider",
            "boot_id",
            "cancellations",
        ]
        assert runtime.boot_id == current_runtime().boot_id


def test_execution_runtime_uses_injected_timeline_and_delegation_callbacks() -> None:
    async def fake_timeline(*args, **kwargs):
        del args, kwargs
        return None

    async def fake_routed_task(*args, **kwargs):
        del args, kwargs
        return None

    with fresh_env():
        collaborators = TelegramExecutionCollaborators(
            build_conversation_progress_callback=lambda _conversation_ref, _routed_task_id: fake_timeline,
            build_routed_task_progress_callback=lambda _routed_task_id, _authority_ref: fake_routed_task,
        )

        runtime = build_execution_runtime(current_runtime(), collaborators=collaborators)
        message = FakeMessage(chat=FakeChat(12345))
        message.conversation_ref = telegram_conversation_ref(current_runtime().config, 12345)
        context = build_telegram_transport_identity(
            current_runtime(),
            message,
            12345,
            collaborators=collaborators,
        )

        assert context.timeline_callback is fake_timeline


async def test_execute_request_runs_from_explicit_execution_runtime():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="hello"))
        runtime = current_execution_runtime()

        outcome = await execute_request(
            build_telegram_transport_identity(
                current_runtime(),
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
    with fresh_env() as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="hello"))
        base_runtime = current_execution_runtime()
        runtime = ExecutionRuntime(
            dispatch=base_runtime.dispatch,
            services=base_runtime.services,
            interrupted_exc=base_runtime.interrupted_exc,
        )

        await request_approval(
            TransportIdentity(
                conversation_key=f"tg:{chat.id}",
                origin_channel="telegram",
                external_conversation_ref=str(chat.id),
                actor=telegram_actor_key(42),
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
        assert len(message.chat.sent_messages) == 1
        assert message.chat.sent_messages[0]["reply_markup"] is not None


def test_workflow_context_builder_resolves_registry_conversation_metadata() -> None:
    context = build_transport_identity_from_metadata(
        ExecutionChannelMetadata(
            conversation_key="registry:conversation:12345",
            origin_channel="registry",
            actor="registry:operator",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name="Registry",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                contributes_transport_capability=True,
                accepts_transport_input=True,
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
            origin_channel="registry",
            actor="registry:operator",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name="Registry Tasks",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                contributes_transport_capability=False,
                accepts_transport_input=False,
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
            origin_channel="registry",
            actor="registry:operator",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name="Registry Tasks",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                contributes_transport_capability=False,
                accepts_transport_input=False,
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


def test_execution_channel_metadata_uses_registry_external_conversation_ref_from_bound_egress() -> None:
    with fresh_env():
        runtime = current_runtime()
        message = FakeMessage(chat=FakeChat(12345), text="hello")
        message.conversation_ref = "registry:ops:conversation:conv-1"
        message.external_id = "registry-ui-conv-1"

        metadata = execution_channel_metadata(
            runtime,
            message,
            "registry:conversation:conv-1",
        )

    assert metadata.origin_channel == "registry"
    assert metadata.external_conversation_ref == "registry-ui-conv-1"


@pytest.mark.asyncio
async def test_format_provider_error_returns_plain_text() -> None:
    text = await format_provider_error("<boom>", 1)

    assert text == "<boom>"
