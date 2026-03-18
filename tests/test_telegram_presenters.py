from pathlib import Path
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.channels.telegram.presenters import (
    TelegramRenderedMessage,
    approval_prompt,
    collapsed_response_message,
    provider_guidance_history_message,
    provider_guidance_mutation_message,
    provider_guidance_preview_message,
    settings_overview,
    skill_add_confirmation,
)
from app.workflows.provider_guidance.contracts import (
    ProviderGuidanceLifecycleApproval,
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleRevision,
    ProviderGuidancePreview,
)
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeUpdate,
    FakeUser,
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
