from types import SimpleNamespace

from app.presentation import telegram as telegram_presenters
from app.runtime import telegram_protocols
from octopus_sdk.identity import telegram_conversation_key
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    current_bot_instance,
    current_runtime,
    fresh_data_dir,
    last_reply,
    load_session_disk,
    make_config,
    send_command,
    setup_globals,
)


def _protocol_item(**overrides):
    base = {
        "protocol_id": "protocol-1",
        "slug": "software-engineering",
        "display_name": "Software Engineering",
        "lifecycle_state": "published",
        "current_version_id": "version-1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _run_detail(*, run_id="run-1", status="running", version=2, stage_key="planning"):
    run = SimpleNamespace(
        protocol_run_id=run_id,
        protocol_id="protocol-1",
        status=status,
        version=version,
        current_stage_key=stage_key,
        workspace_ref="workspace-a",
        root_conversation_id="conv-1",
        blocked_detail="",
        termination_summary="done" if status == "completed" else "",
    )
    definition = SimpleNamespace(slug="software-engineering")
    latest_stage = SimpleNamespace(
        stage_key=stage_key,
        status="completed" if status == "completed" else "running",
        decision_summary="Plan updated." if status != "failed" else "",
        failure_detail="",
    )
    participant = SimpleNamespace(
        participant_key="planner",
        state="running" if status == "running" else "completed",
        resolution_outcome="ok",
    )
    artifact = SimpleNamespace(
        artifact_key="plan",
        verification_state="verified" if status != "failed" else "missing",
        state="available" if status != "failed" else "missing",
    )
    return SimpleNamespace(
        run=run,
        definition=definition,
        participants=[participant],
        artifacts=[artifact],
        stage_executions=[latest_stage],
    )


async def test_protocol_start_persists_watch_and_includes_registry_link(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def list_protocols(self):
                return [_protocol_item()]

            async def create_conversation(self, **kwargs):
                return SimpleNamespace(conversation_id="conv-1")

            async def create_protocol_run(self, payload):
                assert payload["protocol_id"] == "protocol-1"
                return SimpleNamespace(
                    run=SimpleNamespace(
                        protocol_run_id="run-1",
                        protocol_id="protocol-1",
                        version=1,
                        status="running",
                        current_stage_key="planning",
                    )
                )

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol start software-engineering Build the feature",
            args=["start", "software-engineering", "Build", "the", "feature"],
        )

        reply = last_reply(msg)
        assert "Protocol run started" in reply
        assert "Open in registry" in reply
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        watches = session.get("protocol_run_watches") or []
        assert watches
        assert watches[0]["run_id"] == "run-1"
        assert watches[0]["registry_url"] == "http://registry.local"


async def test_protocol_cancel_requires_confirmation_before_mutation(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)
        calls: list[tuple[str, str]] = []

        class _Client:
            async def get_protocol_run(self, run_id):
                return _run_detail(run_id=run_id, version=4)

            async def act_on_protocol_run(self, run_id, *, action, reason, expected_version=None):
                calls.append((action, reason))
                return SimpleNamespace(
                    run=SimpleNamespace(
                        protocol_run_id=run_id,
                        protocol_id="protocol-1",
                        status="cancelled",
                        version=5,
                        current_stage_key="planning",
                    )
                )

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        preview = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol cancel run-1 wrong output",
            args=["cancel", "run-1", "wrong", "output"],
        )
        assert "Confirm protocol action" in last_reply(preview)
        assert not calls

        confirmed = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol cancel run-1 confirm wrong output",
            args=["cancel", "run-1", "confirm", "wrong", "output"],
        )
        assert calls == [("cancel", "wrong output")]
        assert "Protocol run updated" in last_reply(confirmed)


async def test_protocol_status_reports_watch_state(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        runtime = current_runtime()
        telegram_protocols.persist_protocol_run_watch(
            runtime,
            chat_id=1001,
            run_id="run-1",
            protocol_id="protocol-1",
            protocol_slug="software-engineering",
            version=2,
            status="running",
            stage_key="planning",
            registry_url="http://registry.local",
            last_notified_at="2026-04-16T00:00:00+00:00",
        )

        class _Client:
            async def get_protocol_run(self, run_id):
                return _run_detail(run_id=run_id, version=2, stage_key="planning")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol status run-1",
            args=["status", "run-1"],
        )

        reply = last_reply(msg)
        assert "Notifications: <code>watching</code>" in reply
        assert "Open in registry" in reply


async def test_protocol_watch_and_unwatch_commands_toggle_persisted_watch(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_protocol_run(self, run_id):
                return _run_detail(run_id=run_id, version=3, stage_key="review")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        watched = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol watch run-1",
            args=["watch", "run-1"],
        )
        assert "Protocol notifications <b>enabled</b>." in last_reply(watched)
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("protocol_run_watches")[0]["run_id"] == "run-1"

        unwatched = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol unwatch run-1",
            args=["unwatch", "run-1"],
        )
        assert "Protocol notifications <b>disabled</b>." in last_reply(unwatched)
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("protocol_run_watches") == []


async def test_protocol_watch_loop_notifies_and_clears_terminal_runs(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        runtime = current_runtime()
        telegram_protocols.persist_protocol_run_watch(
            runtime,
            chat_id=1001,
            run_id="run-1",
            protocol_id="protocol-1",
            protocol_slug="software-engineering",
            version=1,
            status="running",
            stage_key="planning",
            registry_url="http://registry.local",
            last_notified_at="2026-04-16T00:00:00+00:00",
        )

        class _Client:
            async def get_protocol_run(self, run_id):
                return _run_detail(run_id=run_id, status="completed", version=2, stage_key="acceptance")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        await telegram_protocols.notify_protocol_run_watches(
            runtime,
            render_notification=telegram_presenters.protocol_run_notification_message,
        )

        sent = current_bot_instance().sent_messages
        assert sent
        assert "Protocol run update" in str(sent[-1].get("text", ""))
        assert "Open in registry" in str(sent[-1].get("text", ""))
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("protocol_run_watches") == []


async def test_protocol_watch_loop_debounces_non_terminal_updates(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        runtime = current_runtime()
        telegram_protocols.persist_protocol_run_watch(
            runtime,
            chat_id=1001,
            run_id="run-1",
            protocol_id="protocol-1",
            protocol_slug="software-engineering",
            version=1,
            status="running",
            stage_key="planning",
            registry_url="http://registry.local",
            last_notified_at=telegram_protocols.datetime.now(telegram_protocols.timezone.utc).isoformat(),
        )

        class _Client:
            async def get_protocol_run(self, run_id):
                return _run_detail(run_id=run_id, status="running", version=2, stage_key="review")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        await telegram_protocols.notify_protocol_run_watches(
            runtime,
            render_notification=telegram_presenters.protocol_run_notification_message,
        )

        assert current_bot_instance().sent_messages == []
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("protocol_run_watches")[0]["run_id"] == "run-1"
