import asyncio
from dataclasses import fields, replace

import pytest

from octopus_sdk.config import BotConfigBase
from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key, telegram_conversation_ref
from octopus_sdk.providers import DenialRecord, ProviderStateRecord, RunResult
from octopus_sdk.sessions import SessionState
from octopus_sdk.skill_types import SkillRequirement
from octopus_sdk.transport import TransportBindingRecord, TransportDescriptor
from octopus_sdk.transport import EditableHandle, TransportEgressFeatures, TransportEgress
from app.runtime.telegram_execution import (
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
from octopus_sdk.agent_awareness import AgentAwarenessRecord
from octopus_sdk.execution import (
    ExecutionRuntime,
    TransportIdentity,
    ExecutionChannelMetadata,
    RequestExecutionOutcome,
)
from octopus_sdk.execution_context import ResolvedExecutionContext
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
    async def edit_text(self, text: str, **kwargs: object):
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: object | None = None, **kwargs: object):
        del reply_markup, kwargs


class _DispatchEgress(TransportEgress):
    def __init__(self, *, target: object) -> None:
        self.labels: list[str] = []
        self.actions: list[str] = []
        self.formatted_replies: list[str] = []
        self.target = target
        self.typing_targets: list[object] = []
        self.typing_started = asyncio.Event()

    @property
    def egress_features(self) -> TransportEgressFeatures:
        return TransportEgressFeatures(transport_implementation="dispatch-test")

    async def send_text(self, text: str, **kwargs: object) -> EditableHandle:
        del text, kwargs
        return _GenericStatusHandle()

    async def send_status(self, label: str, **kwargs: object):
        del kwargs
        self.labels.append(label)
        return _GenericStatusHandle()

    async def send_photo(self, photo, **kwargs: object) -> None:
        del photo, kwargs

    async def send_document(self, document, **kwargs: object) -> None:
        del document, kwargs

    async def send_action(self, action: str) -> None:
        self.actions.append(action)
        self.typing_targets.append(self.target)
        self.typing_started.set()

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        del text, show_alert

    def typing_target(self) -> TransportEgress:
        return self

    async def sync_binding(self, binding: TransportBindingRecord) -> None:
        del binding

    async def bind(self, *, title: str, config: BotConfigBase) -> None:
        del title, config

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        recovery_id: str,
    ) -> None:
        del preview, prompt, run_again_label, skip_label, recovery_id

    async def show_foreign_setup(self, foreign_setup) -> None:
        del foreign_setup

    async def show_setup_prompt(self, missing_skill: str, first_requirement: SkillRequirement) -> None:
        del missing_skill, first_requirement

    async def send_retry_prompt(self, denials: tuple[DenialRecord, ...], callback_token: str) -> None:
        del denials, callback_token

    async def send_approval_prompt(self, callback_token: str) -> None:
        del callback_token

    async def send_formatted_reply(self, text: str) -> None:
        self.formatted_replies.append(text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: ResolvedExecutionContext | None = None,
    ) -> None:
        del conversation_key_value, directives, resolved_ctx

    async def send_compact_reply(self, text: str, conversation_key_value: str, slot: int) -> None:
        del text, conversation_key_value, slot

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: SessionState,
        *,
        conversation_ref: str,
        result: RunResult,
    ) -> RequestExecutionOutcome | None:
        del conversation_key_value, session, conversation_ref, result
        return None



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
            provider_state=ProviderStateRecord(),
            context=object(),
            label="Working",
            runtime=runtime,
        )

        assert outcome.result.text == "default response"
        assert len(prov.run_calls) == 1


async def test_run_provider_request_does_not_require_telegram_message_api():
    with fresh_env() as (_data_dir, cfg, prov):
        target = object()
        original_run = prov.run

        async def delayed_run(provider_state, prompt, image_paths, progress, context=None, cancel=None):
            await message.typing_started.wait()
            return await original_run(
                provider_state,
                prompt,
                image_paths,
                progress,
                context=context,
                cancel=cancel,
            )

        prov.run = delayed_run

        runtime = ProviderDispatchRuntime(
            config=cfg,
            provider=prov,
            boot_id="dispatch-test",
            cancellations={},
            execution_inflight=set(),
        )
        message = _DispatchEgress(target=target)

        outcome = await run_provider_request(
            "registry:prod:conversation:conv-1",
            prompt="test prompt",
            image_paths=[],
            message=message,
            provider_state=ProviderStateRecord(),
            context=object(),
            label="Working",
            runtime=runtime,
        )

        assert outcome.result.text == "default response"
        assert message.labels == ["Working"]
        assert message.typing_targets == [target]
        assert runtime.cancellations == {}


def test_dispatch_runtime_has_no_callable_constructor_fields() -> None:
    with fresh_env():
        runtime = build_dispatch_runtime(current_runtime())
        assert [field.name for field in fields(ProviderDispatchRuntime)] == [
            "config",
            "provider",
            "boot_id",
            "cancellations",
            "execution_inflight",
        ]
        assert runtime.boot_id == current_runtime().boot_id


def test_execution_runtime_binds_runtime_timeline_callbacks() -> None:
    with fresh_env():
        runtime = build_execution_runtime(current_runtime())
        message = FakeMessage(chat=FakeChat(12345))
        message.conversation_ref = telegram_conversation_ref(current_runtime().config, 12345)
        context = build_telegram_transport_identity(
            current_runtime(),
            message,
            12345,
        )

        assert runtime.dispatch.boot_id == current_runtime().boot_id
        assert context.timeline_callback is not None


async def test_execute_request_runs__explicit_execution_runtime():
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


class _StaticAwareness:
    def __init__(self, protocol_name: str = "Payments Risk Engine") -> None:
        self.protocol_name = protocol_name

    async def build_awareness(self, request):
        return AgentAwarenessRecord(
            origin_channel=request.origin_channel,
            agent_slug="m2",
            agent_display_name="M2",
            provider_name=request.provider_name,
            protocols=[
                {
                    "protocol_id": "protocol-risk",
                    "slug": "risk-engine",
                    "display_name": self.protocol_name,
                    "description": "Build and operate a risk decision system.",
                    "lifecycle_state": "published",
                }
            ],
        )


async def test_execute_request_injects_sdk_agent_awareness_into_telegram_context():
    with fresh_env() as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="what protocols can you run?"))
        base_runtime = current_execution_runtime()
        runtime = ExecutionRuntime(
            dispatch=base_runtime.dispatch,
            services=replace(base_runtime.services, agent_awareness=_StaticAwareness()),
            interrupted_exc=base_runtime.interrupted_exc,
        )

        outcome = await execute_request(
            build_telegram_transport_identity(
                current_runtime(),
                message,
                chat.id,
                actor_key=telegram_actor_key(42),
            ),
            "what protocols can you run?",
            [],
            message,
            runtime=runtime,
        )

        assert outcome is not None
        assert outcome.status == "completed"
        assert len(prov.run_calls) == 1
        system_prompt = prov.run_calls[0]["context"].system_prompt
        assert "Octopus Agent Awareness" in system_prompt
        assert "Payments Risk Engine" in system_prompt
        assert "Telegram shortcuts" in system_prompt


async def test_execute_request_resets_codex_thread_when_agent_awareness_changes():
    with fresh_env(provider_name="codex") as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        conversation_key = telegram_conversation_key(chat.id)
        base_runtime = current_execution_runtime()
        session = base_runtime.services.sessions.load(
            conversation_key,
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            approval_mode="off",
        )
        resolved = base_runtime.services.sessions.resolve_context(
            session,
            config=base_runtime.dispatch.config,
            provider_name=prov.name,
            trust_tier="trusted",
        )
        session.provider_state["thread_id"] = "stale-thread"
        session.provider_state["context_hash"] = resolved.context_hash
        session.provider_state["boot_id"] = base_runtime.dispatch.boot_id
        session.provider_state["agent_awareness_digest"] = "stale-awareness"
        base_runtime.services.sessions.save(conversation_key, session)

        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="what protocols can you run?"))
        runtime = ExecutionRuntime(
            dispatch=base_runtime.dispatch,
            services=replace(base_runtime.services, agent_awareness=_StaticAwareness("Updated Protocol Catalog")),
            interrupted_exc=base_runtime.interrupted_exc,
        )

        outcome = await execute_request(
            build_telegram_transport_identity(
                current_runtime(),
                message,
                chat.id,
                actor_key=telegram_actor_key(42),
            ),
            "what protocols can you run?",
            [],
            message,
            runtime=runtime,
        )

        assert outcome is not None
        assert outcome.status == "completed"
        assert prov.run_calls[0]["provider_state"].get("thread_id") is None
        stored = load_session_disk(_data_dir, conversation_key, prov)
        provider_state = stored.get("provider_state", {})
        assert provider_state.get("agent_awareness_digest")
        assert provider_state.get("agent_awareness_digest") != "stale-awareness"


async def test_execute_request_latches_irrecoverable_provider_failure_and_blocks_retry():
    with fresh_env() as (_data_dir, _cfg, prov):
        prov.run_results = [
            RunResult(text="Not logged in · Please run /login", returncode=1),
        ]
        chat = FakeChat(12345)
        message = TelegramExecutionMessage(current_runtime(), FakeMessage(chat=chat, text="hello"))
        runtime = current_execution_runtime()
        transport = build_telegram_transport_identity(
            current_runtime(),
            message,
            chat.id,
            actor_key=telegram_actor_key(42),
        )

        first = await execute_request(
            transport,
            "test prompt",
            [],
            message,
            runtime=runtime,
        )
        second = await execute_request(
            transport,
            "test prompt",
            [],
            message,
            runtime=runtime,
        )

        assert first is not None
        assert first.status == "failed"
        assert "Execution fault latched" in first.error_text
        assert second is not None
        assert second.status == "failed"
        assert "Bot execution is faulted" in second.error_text
        assert len(prov.run_calls) == 1
        assert runtime.services.execution_faults is not None
        assert runtime.services.execution_faults.load().state == "faulted"


async def test_execute_request_rejects_same_conversation_while_inflight():
    with fresh_env() as (_data_dir, _cfg, prov):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_run(provider_state, prompt, image_paths, progress, context=None, cancel=None):
            prov.run_calls.append({
                "provider_state": dict(provider_state),
                "prompt": prompt,
                "image_paths": image_paths,
                "context": context,
            })
            del cancel
            started.set()
            await progress.update("working…", force=True)
            await release.wait()
            return RunResult(text="done")

        prov.run = delayed_run
        runtime = current_execution_runtime()
        transport = TransportIdentity(
            conversation_key="registry:prod:conversation:conv-1",
            origin_channel="registry",
            actor="registry:operator",
            external_conversation_ref="conv-1",
            target_agent_id="",
            conversation_ref="registry:conv-1",
            routed_task_id="",
            authority_ref="",
        )
        first_message = _DispatchEgress(target=object())
        second_message = _DispatchEgress(target=object())

        first_task = asyncio.create_task(
            execute_request(
                transport,
                "first prompt",
                [],
                first_message,
                runtime=runtime,
            )
        )
        await started.wait()
        second = await execute_request(
            transport,
            "second prompt",
            [],
            second_message,
            runtime=runtime,
        )
        release.set()
        first = await first_task

        assert first is not None
        assert first.status == "completed"
        assert second is not None
        assert second.status == "failed"
        assert "Another request is in progress" in second.error_text
        assert second_message.formatted_replies == ["Another request is in progress. Try again in a moment."]
        assert len(prov.run_calls) == 1


async def test_request_approval_runs__explicit_execution_runtime():
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
                actor=telegram_actor_key(42),
                external_conversation_ref=str(chat.id),
                target_agent_id="",
                conversation_ref="",
                routed_task_id="",
                authority_ref="",
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
                report_in_agent_status=True,
                accepts_transport_input=True,
                supports_conversation_binding=True,
                supports_timeline=True,
            ),
            message_conversation_ref="registry:12345",
            routed_task_id="task-9",
            authority_ref="",
            external_conversation_ref="registry:conversation:12345",
            target_agent_id="",
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
                report_in_agent_status=False,
                accepts_transport_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            message_conversation_ref="registry:ops:task:task-1",
            routed_task_id="task-1",
            authority_ref="registry:ops",
            external_conversation_ref="registry:ops:task:task-1",
            target_agent_id="",
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


def test_workflow_context_builder_derives_registry_external_conversation_ref_when_missing() -> None:
    context = build_transport_identity_from_metadata(
        ExecutionChannelMetadata(
            conversation_key="registry:conversation:conv-1",
            origin_channel="registry",
            actor="registry:operator",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name="Registry",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                report_in_agent_status=True,
                accepts_transport_input=True,
                supports_conversation_binding=True,
                supports_timeline=True,
            ),
            message_conversation_ref="registry:ops:conversation:conv-1",
            routed_task_id="",
            authority_ref="",
            external_conversation_ref="",
            target_agent_id="",
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

    assert context.external_conversation_ref == "conv-1"


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
                report_in_agent_status=False,
                accepts_transport_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            message_conversation_ref="registry:ops:task:task-1",
            routed_task_id="task-1",
            authority_ref="registry:ops",
            external_conversation_ref="registry:ops:task:task-1",
            target_agent_id="",
        ),
        conversation_callback_factory=lambda _conversation_ref, _routed_task_id: fake_conversation,
        routed_task_callback_factory=lambda _routed_task_id, _authority_ref: fake_routed_task,
    )

    assert context.timeline_callback is fake_routed_task
    await context.timeline_callback("working…", force=True)
    assert observed == [("routed_task", "working…", "True")]


def test_execution_channel_metadata_copies_authority_ref__inbound_message() -> None:
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


def test_execution_channel_metadata_does_not_infer_authority_ref__registry_ref() -> None:
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


def test_execution_channel_metadata_uses_registry_external_conversation_ref__bound_egress() -> None:
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


def test_execution_channel_metadata_derives_registry_external_conversation_ref_from_ref() -> None:
    with fresh_env():
        runtime = current_runtime()
        message = FakeMessage(chat=FakeChat(12345), text="hello")
        message.conversation_ref = "registry:ops:conversation:conv-1"

        metadata = execution_channel_metadata(
            runtime,
            message,
            "registry:conversation:conv-1",
        )

    assert metadata.origin_channel == "registry"
    assert metadata.external_conversation_ref == "conv-1"


def test_execution_channel_metadata_honors_telegram_transport_for_string_chat_id() -> None:
    with fresh_env():
        runtime = current_runtime()
        message = FakeMessage(chat=FakeChat(12345), text="hello")
        message.transport = "telegram"
        message.source = "telegram"
        message.conversation_ref = "telegram:test-bot:12345"

        metadata = execution_channel_metadata(
            runtime,
            message,
            "12345",
        )

    assert metadata.origin_channel == "telegram"
    assert metadata.conversation_key == "tg:12345"
    assert metadata.external_conversation_ref == "12345"


@pytest.mark.asyncio
async def test_format_provider_error_returns_plain_text() -> None:
    text = await format_provider_error("<boom>", 1)

    assert text == "<boom>"
