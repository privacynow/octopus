from pathlib import Path
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.channels.telegram.presenters import (
    TelegramRenderedMessage,
    access_overrides_message,
    admin_sessions_summary_message,
    approval_prompt,
    collapsed_response_message,
    delegation_plan_message,
    discover_results_message,
    extract_summary,
    formatted_reply_messages,
    ingress_setup_prompt_message,
    main_help_message,
    provider_guidance_history_message,
    provider_guidance_mutation_message,
    provider_guidance_preview_message,
    conversation_role_current_message,
    pending_html_outcome_message,
    raw_missing_message,
    raw_usage_message,
    runtime_skill_active_summary_message,
    runtime_skill_history_message,
    session_overview_message,
    settings_overview,
    skill_add_confirmation,
    welcome_message,
)
from app.workflows.provider_guidance.contracts import (
    ProviderGuidanceLifecycleApproval,
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleRevision,
    ProviderGuidancePreview,
)
from app.runtime.inbound_types import InboundUser
from app.session_state import DelegatedTask, PendingDelegation, SessionState
from app.storage import default_session, save_session
from app.workflows.runtime_skills.contracts import (
    RuntimeSkillLifecycleApproval,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillLifecycleRevision,
)
from tests.support.handler_support import (
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeUpdate,
    FakeUser,
    current_runtime,
    fresh_data_dir,
    send_command,
    setup_globals,
    make_config,
    FakeProvider,
)


def test_approval_prompt_renders_expected_buttons():
    rendered = approval_prompt()

    assert rendered.text
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "approval_approve"
    assert rendered.reply_markup.inline_keyboard[0][1].callback_data == "approval_reject"


def test_collapsed_response_message_renders_expand_button():
    rendered = collapsed_response_message("<b>Summary</b>", 42, 7)

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.disable_web_page_preview is True
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "expand:42:7"


def test_settings_overview_renders_channel_buttons():
    rendered = settings_overview(
        project_display="backend",
        working_dir="/tmp/backend",
        policy="edit",
        compact=True,
        approval="off",
        model_display="fast",
        effective_model="gpt-5.4",
        trust_public=False,
        project_names=["backend", "frontend"],
        current_project="backend",
        model_available=["fast", "best"],
        has_model_override=True,
        has_policy_override=True,
    )

    callbacks = [
        button.callback_data
        for row in rendered.reply_markup.inline_keyboard
        for button in row
    ]
    assert "setting_project:backend" in callbacks
    assert "setting_policy:edit" in callbacks
    assert "setting_compact:on" in callbacks
    assert "setting_approval:off" in callbacks


def test_skill_add_confirmation_renders_expected_buttons():
    rendered = skill_add_confirmation("helper", 9000, 8000)

    assert rendered.parse_mode == ParseMode.HTML
    assert "helper" in rendered.text
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "skill_add_confirm:helper"
    assert rendered.reply_markup.inline_keyboard[0][1].callback_data == "skill_add_cancel"


def test_provider_guidance_preview_message_renders_expected_html():
    preview = ProviderGuidancePreview(
        provider="claude",
        effective_guidance="Use careful guidance",
        system_prompt="",
        capability_summary="",
        provider_config={},
        prompt_weight=1,
    )

    rendered = provider_guidance_preview_message("claude", preview)

    assert rendered.parse_mode == ParseMode.HTML
    assert "<b>claude</b>" in rendered.text
    assert "<pre>Use careful guidance</pre>" in rendered.text


def test_provider_guidance_history_message_renders_revisions_and_approvals():
    detail = ProviderGuidanceLifecycleDetail(
        provider="claude",
        scope_kind="system",
        scope_key="",
        body="body",
        lifecycle_status="published",
        active_revision_id="rev-current",
        published_revision_id="rev-current",
        runtime_available=True,
        revisions=(
            ProviderGuidanceLifecycleRevision(
                revision_id="rev-current",
                status="published",
                created_by="admin",
                created_at="2026-03-18T00:00:00+00:00",
                is_published=True,
            ),
        ),
        approvals=(
            ProviderGuidanceLifecycleApproval(
                revision_id="rev-current",
                action="approved",
                actor="admin",
                note="ship it",
                created_at="2026-03-18T00:00:00+00:00",
            ),
        ),
    )

    rendered = provider_guidance_history_message("claude", detail)

    assert rendered.parse_mode == ParseMode.HTML
    assert "Status: <code>published</code>" in rendered.text
    assert "approved by admin" in rendered.text
    assert "[published]" in rendered.text


def test_provider_guidance_mutation_message_escapes_html():
    rendered = provider_guidance_mutation_message("<saved>")

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.text == "&lt;saved&gt;"


def test_conversation_role_current_message_renders_expected_html():
    rendered = conversation_role_current_message("Python expert")

    assert rendered.parse_mode == ParseMode.HTML
    assert "<code>Python expert</code>" in rendered.text


def test_pending_html_outcome_message_renders_expected_html():
    rendered = pending_html_outcome_message("<b>Replay queued</b>")

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.text == "<b>Replay queued</b>"


def test_ingress_setup_prompt_message_renders_expected_html():
    rendered = ingress_setup_prompt_message(
        "planner",
        {"kind": "token", "key": "API_TOKEN", "prompt": "Enter API_TOKEN"},
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "planner" in rendered.text
    assert "API_TOKEN" in rendered.text


def test_formatted_reply_messages_render_html_chunks():
    rendered = formatted_reply_messages("**hello**")

    assert rendered
    assert all(item.parse_mode == ParseMode.HTML for item in rendered)
    assert any("hello" in item.text for item in rendered)


def test_extract_summary_splits_at_line_boundary():
    summary, rest = extract_summary(
        "Line one\nLine two\nLine three\nLine four\nLine five\nLine six",
        max_lines=3,
    )

    assert "Line one" in summary
    assert "Line three" in summary
    assert "Line five" in rest


def test_delegation_plan_message_renders_expected_html():
    rendered = delegation_plan_message(
        PendingDelegation(
            conversation_ref="conv-1",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    title="Review docs",
                    target_agent_id="agent-reviewer",
                ),
            ],
        )
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Delegation plan" in rendered.text
    assert "Review docs" in rendered.text
    assert "agent-reviewer" in rendered.text


def test_welcome_message_mentions_current_modes():
    rendered = welcome_message(approval_mode="on", compact_mode=True)

    assert "Approval mode is on" in rendered.text
    assert "Compact mode is on" in rendered.text


def test_raw_messages_render_expected_text():
    assert "Usage: /raw [N]" in raw_usage_message().text
    assert raw_missing_message().text == "No stored responses found."


def test_main_help_message_renders_expected_sections():
    rendered = main_help_message(
        instance="prod",
        provider_name="Claude",
        has_model_profiles=True,
        agent_mode="registry",
        is_public=False,
        has_projects=True,
        is_admin=True,
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Agent Bot" in rendered.text
    assert "/discover" in rendered.text
    assert "/admin sessions" in rendered.text


def test_session_overview_message_renders_expected_html():
    rendered = session_overview_message(
        provider_name="claude",
        instance="prod",
        working_dir_display="/tmp/project",
        file_policy="edit",
        model_profile="fast",
        model_id="gpt-5.4",
        compact_display="on",
        prompt_weight="~123 chars",
        session_label="Session",
        session_value="abc123…",
        session_active="True",
        approval_mode="on",
        approval_source="chat override",
        role_display="Python expert",
        skills_display="planner, reviewer",
        pending="no",
        trust_public=False,
        session_commands=["/settings", "/project"],
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Working dir" in rendered.text
    assert "Python expert" in rendered.text
    assert "/settings or /project" in rendered.text


def test_discover_results_message_renders_matching_agents():
    rendered = discover_results_message(
        [
            {
                "display_name": "Reviewer",
                "role": "developer",
                "connectivity_state": "connected",
                "current_capacity": 1,
                "max_capacity": 4,
                "capabilities": ["python", "review"],
                "tags": ["backend"],
                "description": "Reviews code changes.",
            }
        ]
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Matching agents" in rendered.text
    assert "Reviewer" in rendered.text
    assert "backend" in rendered.text


def test_access_overrides_message_renders_expected_html():
    rendered = access_overrides_message(
        [
            {"actor_key": "telegram:42", "access": "allowed", "reason": "trusted"},
            {"actor_key": "telegram:99", "access": "blocked", "reason": ""},
        ]
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Access overrides" in rendered.text
    assert "telegram:42" in rendered.text
    assert "allowed" in rendered.text


def test_admin_sessions_summary_message_renders_expected_html():
    rendered = admin_sessions_summary_message(
        total=3,
        pending=1,
        setup=1,
        top_skills=[("planner", 2)],
        most_recent_key="telegram:123",
        most_recent_updated_at="2026-03-18T00:00:00+00:00",
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Sessions: 3" in rendered.text
    assert "planner: 2" in rendered.text
    assert "telegram:123" in rendered.text


def test_runtime_skill_active_summary_message_renders_expected_html():
    rendered = runtime_skill_active_summary_message(["Planner", "Reviewer"], 7)

    assert rendered.parse_mode == ParseMode.HTML
    assert "<b>Active skills (2):</b>" in rendered.text
    assert "Planner" in rendered.text
    assert "7 skill(s) available" in rendered.text


def test_runtime_skill_history_message_renders_revisions_and_approvals():
    detail = RuntimeSkillLifecycleDetail(
        name="release-notes",
        display_name="Release Notes",
        description="Summarize releases",
        visibility="private",
        body="body",
        lifecycle_status="published",
        active_revision_id="rev-current",
        published_revision_id="rev-current",
        runtime_available=True,
        revisions=(
            RuntimeSkillLifecycleRevision(
                revision_id="rev-current",
                version_label="v1",
                status="published",
                changelog="First version",
                created_by="owner",
                created_at="2026-03-18T00:00:00+00:00",
                is_published=True,
            ),
        ),
        approvals=(
            RuntimeSkillLifecycleApproval(
                revision_id="rev-current",
                action="approved",
                actor="admin",
                note="ship it",
                created_at="2026-03-18T00:00:00+00:00",
            ),
        ),
    )

    rendered = runtime_skill_history_message(detail)

    assert rendered.parse_mode == ParseMode.HTML
    assert "Status: <code>published</code>" in rendered.text
    assert "approved by admin" in rendered.text
    assert "[published]" in rendered.text


async def test_cmd_compact_status_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th
    import app.channels.telegram.conversation as conversation

    rendered = TelegramRenderedMessage(
        text="patched compact presenter",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("patched", callback_data="patched:compact")]]),
    )
    monkeypatch.setattr(conversation.telegram_presenters, "compact_mode_status", lambda current: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_compact, chat, user, "/compact")

        assert msg.replies[-1]["text"] == "patched compact presenter"
        assert msg.replies[-1]["reply_markup"].inline_keyboard[0][0].callback_data == "patched:compact"


async def test_skills_add_confirmation_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th
    import app.channels.telegram.runtime_skills as runtime_skills
    from tests.support import skill_test_helpers as skills_mod

    rendered = TelegramRenderedMessage(
        text="patched skill confirmation",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("patched", callback_data="patched:skill")]]),
    )
    monkeypatch.setattr(runtime_skills.telegram_presenters, "skill_add_confirmation", lambda *args, **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            skill_dir = custom_dir / "big-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: big-skill\ndisplay_name: Big\n"
                "description: test\n---\n\n" + "x" * 9000 + "\n"
            )

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1)
            user = FakeUser(42)

            msg = await send_command(th.cmd_skills, chat, user, "/skills add big-skill", args=["add", "big-skill"])

            assert msg.replies[-1]["text"] == "patched skill confirmation"
            assert msg.replies[-1]["reply_markup"].inline_keyboard[0][0].callback_data == "patched:skill"
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


async def test_send_approval_prompt_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(
        text="patched approval presenter",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("patched", callback_data="patched:approval")]]),
    )
    monkeypatch.setattr(th.telegram_presenters, "approval_prompt", lambda: rendered)

    chat = FakeChat(12345)
    message = FakeMessage(chat=chat, text="hello")

    await th._send_approval_prompt(message)

    assert chat.sent_messages[-1]["text"] == "patched approval presenter"
    assert chat.sent_messages[-1]["reply_markup"].inline_keyboard[0][0].callback_data == "patched:approval"


async def test_show_setup_prompt_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched setup prompt", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "ingress_setup_prompt_message", lambda *args, **kwargs: rendered)

    message = FakeMessage(chat=FakeChat(12345), text="setup")

    await th._show_setup_prompt(message, "planner", {"kind": "token", "key": "API_TOKEN"})

    assert message.replies[-1]["text"] == "patched setup prompt"


async def test_send_formatted_reply_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched formatted chunk", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "formatted_reply_messages", lambda text: [rendered])

    message = FakeMessage(chat=FakeChat(12345), text="reply")

    await th.send_formatted_reply(message, "ignored")

    assert message.replies[-1]["text"] == "patched formatted chunk"


async def test_send_compact_reply_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched compact reply", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "compact_reply_blockquote_message", lambda text: rendered)

    message = FakeMessage(chat=FakeChat(12345), text="reply")

    await th._send_compact_reply(message, "ignored", 12345, 7)

    assert message.replies[-1]["text"] == "patched compact reply"


async def test_propose_delegation_plan_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th
    from app.channels.telegram.state import build_telegram_runtime

    async def _noop_publish(*args, **kwargs):
        return None

    rendered = TelegramRenderedMessage(text="patched delegation plan", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th, "_publish_delegation_proposed_event", _noop_publish)
    monkeypatch.setattr(th, "save_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(th.telegram_presenters, "delegation_plan_message", lambda delegation: rendered)

    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state={}, approval_mode="off")
    result = SimpleNamespace(
        delegation_title="Delegate this",
        text="delegate this work",
        delegation_resume_instruction="resume",
        delegation_tasks=[
            {
                "routed_task_id": "task-1",
                "title": "Review docs",
                "target_agent_id": "agent-reviewer",
                "instructions": "Review the current docs",
            },
        ],
    )
    runtime = build_telegram_runtime(make_config(Path("/tmp/telegram-presenters")), FakeProvider("codex"))

    outcome = await th._propose_delegation_plan(
        runtime,
        12345,
        message,
        session,
        conversation_ref="conv-1",
        result=result,
    )

    assert outcome.status == "delegation_proposed"
    assert message.replies[-1]["text"] == "patched delegation plan"


async def test_cmd_raw_usage_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched raw usage")
    monkeypatch.setattr(th.telegram_presenters, "raw_usage_message", lambda: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_raw, chat, user, "/raw nope", args=["nope"])

        assert msg.replies[-1]["text"] == "patched raw usage"


async def test_handle_message_welcome_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched welcome")
    monkeypatch.setattr(th.telegram_presenters, "welcome_message", lambda **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=FakeUser(42), chat=chat)

        await th.handle_message(update, FakeContext())

        assert chat.sent_messages[-1]["text"] == "patched welcome"


async def test_cmd_help_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched help presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "main_help_message", lambda **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_help, chat, user, "/help")

        assert msg.replies[-1]["text"] == "patched help presenter"


async def test_cmd_session_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched session presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "session_overview_message", lambda **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_session, chat, user, "/session")

        assert msg.replies[-1]["text"] == "patched session presenter"


async def test_cmd_discover_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    class _FakeClient:
        async def search(self, query):
            del query
            return [{"display_name": "Reviewer"}]

    rendered = TelegramRenderedMessage(text="patched discover presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "discover_results_message", lambda agents: rendered)
    monkeypatch.setattr(
        th,
        "load_agent_runtime_state",
        lambda data_dir: SimpleNamespace(
            connectivity_state="connected",
            last_error="",
            agent_id="agent-1",
        ),
    )
    monkeypatch.setattr(th, "registry_client", lambda cfg: _FakeClient())

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, agent_mode="registry")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_discover, chat, user, "/discover role:developer", ["role:developer"])

        assert msg.replies[-1]["text"] == "patched discover presenter"


async def test_cmd_admin_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched admin presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(th.telegram_presenters, "admin_sessions_summary_message", lambda **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, "telegram:12345", session)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_admin, chat, user, "/admin sessions", ["sessions"])

        assert msg.replies[-1]["text"] == "patched admin presenter"


async def test_cmd_guidance_admin_only_uses_presenter(monkeypatch):
    import app.channels.telegram.ingress as th

    rendered = TelegramRenderedMessage(text="patched guidance admin presenter")
    monkeypatch.setattr(th.telegram_presenters, "guidance_admin_only_message", lambda action: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, admin_user_ids=frozenset(), admin_usernames=frozenset())
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(42)

        msg = await send_command(th.cmd_guidance, chat, user, "/guidance approve claude", ["approve", "claude"])

        assert msg.replies[-1]["text"] == "patched guidance admin presenter"


async def test_guidance_preview_uses_presenter(monkeypatch):
    import app.channels.telegram.guidance as guidance

    rendered = TelegramRenderedMessage(text="patched guidance preview", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(guidance.telegram_presenters, "provider_guidance_preview_message", lambda *args, **kwargs: rendered)

    preview = ProviderGuidancePreview(
        provider="claude",
        effective_guidance="Use careful guidance",
        system_prompt="",
        capability_summary="",
        provider_config={},
        prompt_weight=1,
    )
    monkeypatch.setattr(
        guidance,
        "_flows",
        lambda: type(
            "Flows",
            (),
            {
                "provider_guidance": type(
                    "ProviderGuidanceFlows",
                    (),
                    {"preview": type("PreviewFlows", (), {"preview": lambda *args, **kwargs: preview})()},
                )(),
            },
        )(),
    )

    update = FakeUpdate(message=FakeMessage(chat=FakeChat(), user=FakeUser(42)), user=FakeUser(42))

    await guidance.guidance_preview(SimpleNamespace(user=FakeUser(42)), update, "claude")

    assert update.effective_message.replies[-1]["text"] == "patched guidance preview"


async def test_runtime_skills_show_uses_presenter(monkeypatch):
    import contextlib

    import app.channels.telegram.runtime_skills as runtime_skills
    from app.credential_validation import validate_credential

    @contextlib.asynccontextmanager
    async def _noop_chat_lock(*args, **kwargs):
        del args, kwargs
        yield False

    rendered = TelegramRenderedMessage(text="patched skill summary", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(runtime_skills.telegram_presenters, "runtime_skill_active_summary_message", lambda *args, **kwargs: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="/skills")
        update = FakeUpdate(message=message, chat=chat)
        event = SimpleNamespace(chat_id=chat.id, user=InboundUser(id="telegram:42", username="testuser"))
        runtime = runtime_skills.TelegramRuntimeSkillsRuntime(
            state=current_runtime(),
            chat_lock=_noop_chat_lock,
            validate_credential=validate_credential,
            check_prompt_size_cross_chat=lambda data_dir, skill_name: [],
        )

        await runtime_skills.skills_show(event, update, runtime=runtime)

        assert message.replies[-1]["text"] == "patched skill summary"


async def test_runtime_skills_history_uses_presenter(monkeypatch):
    import app.channels.telegram.runtime_skills as runtime_skills

    rendered = TelegramRenderedMessage(text="patched history presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(runtime_skills.telegram_presenters, "runtime_skill_history_message", lambda detail: rendered)

    detail = RuntimeSkillLifecycleDetail(
        name="release-notes",
        display_name="Release Notes",
        description="Summarize releases",
        visibility="private",
        body="body",
        lifecycle_status="draft",
        active_revision_id="rev-current",
        published_revision_id="",
        runtime_available=False,
        revisions=(),
        approvals=(),
    )
    monkeypatch.setattr(
        runtime_skills,
        "_flows",
        lambda: type(
            "Flows",
            (),
            {
                "runtime_skills": type(
                    "RuntimeSkillFlows",
                    (),
                    {"authoring": type("AuthoringFlows", (), {"detail": lambda *args, **kwargs: detail})()},
                )(),
            },
        )(),
    )

    message = FakeMessage(chat=FakeChat(), text="/skills history release-notes")
    update = FakeUpdate(message=message, user=FakeUser(42))

    await runtime_skills.skills_history(SimpleNamespace(user=FakeUser(42)), update, "release-notes", runtime=None)

    assert message.replies[-1]["text"] == "patched history presenter"


async def test_runtime_skills_setup_uses_presenter(monkeypatch):
    import contextlib

    import app.channels.telegram.runtime_skills as runtime_skills
    from app.credential_validation import validate_credential

    @contextlib.asynccontextmanager
    async def _noop_chat_lock(*args, **kwargs):
        del args, kwargs
        yield False

    rendered = TelegramRenderedMessage(text="patched setup presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(runtime_skills.telegram_presenters, "runtime_skill_setup_started_message", lambda *args, **kwargs: rendered)
    monkeypatch.setattr(
        runtime_skills,
        "_flows",
        lambda: type(
            "Flows",
            (),
            {
                "runtime_skills": type(
                    "RuntimeSkillFlows",
                    (),
                    {
                        "catalog": type("CatalogFlows", (), {"has_skill": lambda *args, **kwargs: True})(),
                        "activation": type(
                            "ActivationFlows",
                            (),
                            {
                                "begin_setup": lambda *args, **kwargs: SimpleNamespace(
                                    status="needs_setup",
                                    first_requirement={"kind": "token", "key": "API_TOKEN"},
                                    mutated=False,
                                )
                            },
                        )(),
                    },
                )(),
            },
        )(),
    )

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="/skills setup helper")
        update = FakeUpdate(message=message, chat=chat, user=FakeUser(42))
        event = SimpleNamespace(chat_id=chat.id, user=FakeUser(42))
        runtime = runtime_skills.TelegramRuntimeSkillsRuntime(
            state=current_runtime(),
            chat_lock=_noop_chat_lock,
            validate_credential=validate_credential,
            check_prompt_size_cross_chat=lambda data_dir, skill_name: [],
        )

        await runtime_skills.skills_setup(event, update, "helper", runtime=runtime)

        assert message.replies[-1]["text"] == "patched setup presenter"


async def test_conversation_cmd_role_uses_presenter(monkeypatch):
    import contextlib

    import app.channels.telegram.conversation as conversation

    @contextlib.asynccontextmanager
    async def _noop_chat_lock(*args, **kwargs):
        del args, kwargs
        yield False

    rendered = TelegramRenderedMessage(text="patched role presenter", parse_mode=ParseMode.HTML)
    monkeypatch.setattr(conversation.telegram_presenters, "conversation_role_current_message", lambda role: rendered)

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, allow_open=False)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="/role")
        update = FakeUpdate(message=message, chat=chat, user=FakeUser(42))
        event = SimpleNamespace(chat_id=chat.id, user=InboundUser(id="telegram:42", username="testuser"), args=[])
        runtime = conversation.TelegramConversationRuntime(
            state=current_runtime(),
            cancellations=current_runtime().cancellation_registry,
            chat_lock=_noop_chat_lock,
            edit_or_reply_text=lambda *args, **kwargs: None,
        )

        session = conversation._load(runtime, chat.id)
        session.role = "Python expert"
        conversation._save(runtime, chat.id, session)

        await conversation.cmd_role(event, update, None, runtime=runtime)

        assert message.replies[-1]["text"] == "patched role presenter"


async def test_pending_reject_uses_presenter(monkeypatch):
    import contextlib

    import app.channels.telegram.pending as pending

    @contextlib.asynccontextmanager
    async def _noop_chat_lock(*args, **kwargs):
        del args, kwargs
        yield False

    async def _noop_edit_or_reply_text(message, text: str, **kwargs):
        await message.reply_text(text, **kwargs)

    rendered = TelegramRenderedMessage(text="patched pending presenter")
    monkeypatch.setattr(pending.telegram_presenters, "pending_plain_outcome_message", lambda message: rendered)
    monkeypatch.setattr(
        pending,
        "_flows",
        lambda: type(
            "Flows",
            (),
            {
                "pending": type(
                    "PendingFlows",
                    (),
                    {
                        "requests": type(
                            "RequestFlows",
                            (),
                            {"reject": lambda *args, **kwargs: SimpleNamespace(mutated=False, message="rejected")},
                        )(),
                    },
                )(),
            },
        )(),
    )

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        message = FakeMessage(chat=chat, text="pending")
        runtime = pending.TelegramPendingRuntime(
            state=current_runtime(),
            chat_lock=_noop_chat_lock,
            edit_or_reply_text=_noop_edit_or_reply_text,
            execute_request=lambda *args, **kwargs: None,
            request_approval=lambda *args, **kwargs: None,
            build_user_prompt=lambda *args, **kwargs: ("", []),
        )

        await pending.reject_pending(chat.id, message, runtime=runtime)

        assert message.replies[-1]["text"] == "patched pending presenter"
