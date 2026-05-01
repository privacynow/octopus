from types import SimpleNamespace

from app.presentation import telegram as telegram_presenters
from app.runtime import telegram_protocols
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.protocols.models import ProtocolDefinitionRecord, ProtocolRunMutationRecord, ProtocolRunRecord
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    current_bot_instance,
    current_runtime,
    fresh_data_dir,
    get_callback_data_values,
    last_reply,
    load_session_disk,
    make_config,
    send_callback,
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
    return ProtocolDefinitionRecord.model_validate(base)


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
        exists=status != "failed",
        workspace_path="plan.md",
        location="plan.md",
        size_bytes=128 if status != "failed" else 0,
    )
    return SimpleNamespace(
        run=run,
        definition=definition,
        participants=[participant],
        artifacts=[artifact],
        stage_executions=[latest_stage],
    )


def test_protocol_run_url_targets_protocol_runs_route():
    runtime = SimpleNamespace(config=SimpleNamespace(agent_registries=[]))
    url = telegram_protocols.protocol_run_url(runtime, "run-1", registry_url="http://registry.local")
    assert url == "http://registry.local/ui/runs?run_id=run-1"


def test_protocol_urls_translate_local_registry_for_humans(monkeypatch):
    monkeypatch.delenv("BOT_REGISTRY_PUBLIC_URL", raising=False)
    monkeypatch.delenv("OCTOPUS_REGISTRY_PUBLIC_URL", raising=False)
    monkeypatch.delenv("REGISTRY_PUBLIC_URL", raising=False)
    runtime = SimpleNamespace(config=SimpleNamespace(agent_registries=[]))

    url = telegram_protocols.protocol_artifact_url(
        runtime,
        "run-1",
        "report",
        registry_url="http://registry:8787",
        download=True,
    )

    assert url == "http://127.0.0.1:8787/v1/protocol-runs/run-1/artifacts/report/content?download=1"


def test_protocol_urls_prefer_configured_public_registry_url(monkeypatch):
    monkeypatch.setenv("BOT_REGISTRY_PUBLIC_URL", "http://mybox.local:9000")
    runtime = SimpleNamespace(config=SimpleNamespace(agent_registries=[]))

    url = telegram_protocols.protocol_run_url(runtime, "run-1", registry_url="http://registry:8787")

    assert url == "http://mybox.local:9000/ui/runs?run_id=run-1"


def test_protocol_start_args_parse_rich_launch_fields():
    slug, inputs = telegram_protocols.parse_protocol_start_args(
        [
            "manufacturing",
            "Build",
            "the",
            "package",
            "--context",
            "Use",
            "synthetic",
            "data",
            "--constraints=offline",
            "only",
            "--expected-outputs",
            "package",
            "directory",
            "--workspace",
            "demo",
        ]
    )

    assert slug == "manufacturing"
    assert inputs == {
        "problem_statement": "Build the package",
        "context": "Use synthetic data",
        "constraints": "offline only",
        "expected_outputs": "package directory",
        "workspace_ref": "demo",
    }


async def test_protocol_start_persists_watch_and_includes_registry_link(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def list_protocols(self, **kwargs):
                assert kwargs.get("lifecycle_state") == "published"
                return [_protocol_item()]

            async def create_conversation(self, **kwargs):
                return SimpleNamespace(conversation_id="conv-1")

            async def invoke_protocol(self, payload, *, origin="", idempotency_key=""):
                assert payload["protocol_id"] == "protocol-1"
                assert payload["entry_agent_id"] == "agent-1"
                assert payload["root_conversation_id"] == "conv-1"
                assert payload["origin_channel"] == "telegram"
                assert payload["problem_statement"] == "Build the feature"
                assert payload["constraints_json"] == {
                    "context": "Use synthetic data",
                    "constraints": "offline only",
                    "expected_outputs": "report",
                }
                assert payload["workspace_ref"] == "demo"
                return ProtocolRunMutationRecord.model_validate(
                    {
                        "ok": True,
                        "status": "created",
                        "run": {
                            "protocol_run_id": "run-1",
                            "protocol_id": "protocol-1",
                            "protocol_definition_version_id": "version-1",
                            "entry_agent_id": "agent-1",
                            "root_conversation_id": "conv-1",
                            "origin_channel": "telegram",
                            "workspace_ref": "demo",
                            "run_org_id": "local",
                            "status": "running",
                            "problem_statement": "Build the feature",
                            "constraints_json": {},
                            "created_at": "2026-04-23T00:00:00+00:00",
                            "updated_at": "2026-04-23T00:00:00+00:00",
                            "current_stage_key": "planning",
                            "version": 1,
                        },
                    }
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
            "/protocol start software-engineering Build the feature --context Use synthetic data --constraints offline only --expected-outputs report --workspace demo",
            args=[
                "start",
                "software-engineering",
                "Build",
                "the",
                "feature",
                "--context",
                "Use",
                "synthetic",
                "data",
                "--constraints",
                "offline",
                "only",
                "--expected-outputs",
                "report",
                "--workspace",
                "demo",
            ],
        )

        reply = last_reply(msg)
        assert "Protocol run started" in reply
        assert "Open the run in Registry" in reply
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
            async def get_run(self, run_id):
                return _run_detail(run_id=run_id, version=4)

            async def act_on_protocol_run(
                self,
                run_id,
                *,
                action,
                reason,
                idempotency_key="",
                expected_version=None,
            ):
                del idempotency_key
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
            async def get_run(self, run_id):
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
        assert "Open the run in Registry" in reply


async def test_protocol_recent_and_latest_avoid_full_run_id_copying(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def list_runs(self, **kwargs):
                assert kwargs["limit"] == 10
                return [
                    ProtocolRunRecord(
                        protocol_run_id="abcdef1234567890",
                        protocol_id="protocol-1",
                        status="running",
                        current_stage_key="build",
                    )
                ]

            async def get_run(self, run_id):
                assert run_id == "abcdef1234567890"
                return _run_detail(run_id=run_id, version=3, stage_key="build")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        recent = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol recent",
            args=["recent"],
        )
        recent_reply = last_reply(recent)
        assert "Recent protocol runs" in recent_reply
        assert "Tap a run action below" in recent_reply
        assert "abcdef12" in recent_reply
        assert "abcdef1234567890" not in recent_reply

        status = await send_command(
            th.cmd_protocol,
            chat,
            user,
            "/protocol status latest",
            args=["status", "latest"],
        )
        status_reply = last_reply(status)
        assert "Run: <code>abcdef12</code>" in status_reply
        assert "abcdef1234567890" not in status_reply


async def test_protocol_artifacts_lists_downloadable_outputs(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_run(self, run_id):
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
            "/protocol artifacts run-1",
            args=["artifacts", "run-1"],
        )

        reply = last_reply(msg)
        assert "Protocol artifacts" in reply
        assert "1. plan.md: <code>verified</code>" in reply
        assert ">Preview</a>" in reply
        assert ">Download</a>" in reply
        assert ">http://registry.local" not in reply
        assert "Open the full run in Registry" in reply
        callbacks = get_callback_data_values(msg.replies[-1])
        assert "protocol:download:run-1:1" in callbacks
        buttons = [
            button.text
            for row in msg.replies[-1]["reply_markup"].inline_keyboard
            for button in row
        ]
        assert "Preview plan.md" in buttons
        assert "Open plan.md" in buttons
        assert "Send plan.md" in buttons


async def test_protocol_artifacts_download_sends_requested_document(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_run(self, run_id):
                return _run_detail(run_id=run_id, version=2, stage_key="planning")

            async def get_run_artifact_content(self, run_id, artifact_key, *, download=False):
                assert run_id == "run-1"
                assert artifact_key == "plan"
                assert download is True
                return b"# Plan\n"

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
            "/protocol artifacts run-1 download plan",
            args=["artifacts", "run-1", "download", "plan"],
        )

        assert msg.replies[-1]["document_sent"] is True
        assert msg.replies[-1]["caption"] == "Protocol artifact: plan.md"
        assert msg.replies[-1]["document"].name == "plan.md"
        assert msg.replies[-1]["document"].getvalue() == b"# Plan\n"


async def test_protocol_artifact_download_callback_uses_shared_service(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_run(self, run_id):
                assert run_id == "run-1"
                return _run_detail(run_id=run_id, version=2, stage_key="planning")

            async def get_run_artifact_content(self, run_id, artifact_key, *, download=False):
                assert run_id == "run-1"
                assert artifact_key == "plan"
                assert download is True
                return b"# Plan\n"

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        query, msg = await send_callback(
            th.handle_protocol_callback,
            chat,
            user,
            "protocol:download:run-1:1",
        )

        assert query.answered
        assert msg.replies[-1]["document_sent"] is True
        assert msg.replies[-1]["caption"] == "Protocol artifact: plan.md"
        assert msg.replies[-1]["document"].name == "plan.md"


async def test_protocol_artifacts_callback_shows_action_buttons(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_run(self, run_id):
                assert run_id == "run-1"
                return _run_detail(run_id=run_id, version=2, stage_key="planning")

        monkeypatch.setattr(
            telegram_protocols,
            "registry_client_for_runtime",
            lambda runtime: (_Client(), "agent-1", "http://registry.local"),
        )

        import app.runtime.telegram_ingress as th

        chat = FakeChat(1001)
        user = FakeUser(42)
        query, msg = await send_callback(
            th.handle_protocol_callback,
            chat,
            user,
            "protocol:artifacts:run-1",
        )

        assert query.answered
        reply = last_reply(msg)
        assert "Protocol artifacts" in reply
        callbacks = get_callback_data_values(msg.replies[-1])
        assert "protocol:download:run-1:1" in callbacks
        buttons = [
            button.text
            for row in msg.replies[-1]["reply_markup"].inline_keyboard
            for button in row
        ]
        assert "Preview plan.md" in buttons
        assert "Open plan.md" in buttons
        assert "Send plan.md" in buttons


async def test_protocol_artifacts_download_names_package_zip(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        def _detail():
            detail = _run_detail(run_id="run-1", version=2, stage_key="build")
            detail.artifacts = [
                SimpleNamespace(
                    artifact_key="manufacturing_intelligence_package",
                    verification_state="verified",
                    state="available",
                    exists=True,
                    workspace_path="artifacts/manufacturing-intelligence/package",
                    location="artifacts/manufacturing-intelligence/package",
                    size_bytes=4096,
                )
            ]
            return detail

        class _Client:
            async def get_run(self, run_id):
                return _detail()

            async def get_run_artifact_content(self, run_id, artifact_key, *, download=False):
                assert artifact_key == "manufacturing_intelligence_package"
                assert download is True
                return b"PK\x03\x04"

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
            "/protocol artifacts run-1 download manufacturing_intelligence_package",
            args=["artifacts", "run-1", "download", "manufacturing_intelligence_package"],
        )

        assert msg.replies[-1]["document_sent"] is True
        assert msg.replies[-1]["document"].name == "package.zip"


async def test_protocol_export_sends_json_document(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)
        run_id = "abcdef1234567890abcdef1234567890"

        class _Export:
            def model_dump(self, **kwargs):
                return {
                    "run": {"protocol_run_id": run_id, "status": "completed"},
                    "artifacts": [{"artifact_key": "plan", "workspace_path": "plan.md"}],
                }

        class _Client:
            async def export_run(self, run_id):
                assert run_id == "abcdef1234567890abcdef1234567890"
                return _Export()

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
            f"/protocol export {run_id}",
            args=["export", run_id],
        )

        assert msg.replies[-1]["document_sent"] is True
        assert msg.replies[-1]["caption"] == "Protocol run export: abcdef12"
        assert msg.replies[-1]["document"].name == f"protocol_run_{run_id}.json"


async def test_protocol_watch_and_unwatch_commands_toggle_persisted_watch(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        class _Client:
            async def get_run(self, run_id):
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
            async def get_run(self, run_id):
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
            async def get_run(self, run_id):
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
