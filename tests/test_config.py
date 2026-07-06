"""Tests for config.py — env parsing, validation, webhook mode."""

import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import InvalidToken, NetworkError

from octopus_sdk.config import BotConfigBase, RegistryConnectionConfig
from app.config import BotConfig, PUBLISH_LEVEL_KINDS, _parse_projects, load_config, load_dotenv_file, parse_allowed_users, should_publish_event, validate_config
from app.runtime.services import BotServices
from octopus_sdk.sessions import ProjectBinding
from tests.support.config_support import make_config, make_registry_connection


@pytest.fixture(autouse=True)
def _normalize_codex_sandbox_env(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX", "workspace-write")


def test_bot_config_extends_sdk_base() -> None:
    assert issubclass(BotConfig, BotConfigBase)


# -- load_dotenv_file --

def test_load_dotenv_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("KEY1=value1\n")
        f.write("KEY2='quoted'\n")
        f.write('KEY3="double"\n')
        f.write("# comment\n")
        f.write("\n")
        f.write("KEY4=has=equals\n")
        f.name
    result = load_dotenv_file(Path(f.name))
    assert result.get("KEY1") == "value1"
    assert result.get("KEY2") == "quoted"
    assert result.get("KEY3") == "double"
    assert ("comment" in result) == False
    assert result.get("KEY4") == "has=equals"
    os.unlink(f.name)

def test_load_dotenv_missing_file():
    assert load_dotenv_file(Path("/nonexistent/.env")) == {}


# -- parse_allowed_users --

def test_parse_allowed_users():
    ids, names = parse_allowed_users("123,456,@alice,bob")
    assert ids == {"tg:123", "tg:456"}
    assert names == {"alice", "bob"}

def test_parse_allowed_users_empty():
    ids2, names2 = parse_allowed_users("")
    assert (ids2, names2) == (set(), set())

def test_parse_allowed_users_only_commas():
    ids3, names3 = parse_allowed_users("  , ,")
    assert (ids3, names3) == (set(), set())


# -- validate_config --

def test_validate_config_valid():
    errors = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_actor_keys=frozenset({"tg:123"}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    # May have "claude not found" if not installed, that's ok
    token_errors = [e for e in errors if "TOKEN" in e]
    assert token_errors == []

def test_validate_config_missing_token():
    errors2 = validate_config(
        make_config(
            telegram_token="",
            allow_open=False,
            allowed_actor_keys=frozenset({"tg:123"}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("TOKEN" in e for e in errors2)
    assert any("env file" in e or "./octopus" in e for e in errors2)

def test_validate_config_accepts_channel_capable_registry_without_telegram():
    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="channel",
        poll_interval_seconds=5.0,
    )
    errors = validate_config(
        make_config(
            telegram_token="",
            agent_mode="registry",
            agent_registries=(registry,),
        )
    )

    assert not any("ingress-capable channel" in error for error in errors)

def test_validate_config_rejects_coordination_only_registry_without_telegram():
    registry = RegistryConnectionConfig(
        registry_id="ops",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="coordination",
        poll_interval_seconds=5.0,
    )
    errors = validate_config(
        make_config(
            telegram_token="",
            agent_mode="registry",
            agent_registries=(registry,),
        )
    )

    assert any("ingress-capable channel" in error for error in errors)
    assert any("TELEGRAM_BOT_TOKEN" in error or "BOT_AGENT_REGISTRY_SCOPE" in error for error in errors)

def test_validate_config_bad_provider():
    errors3 = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_actor_keys=frozenset({"tg:123"}),
            provider_name="invalid",
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("BOT_PROVIDER" in e for e in errors3)

def test_validate_config_no_users_no_open():
    errors4 = validate_config(
        make_config(
            telegram_token="fake-token",
            allowed_actor_keys=frozenset(),
            allow_open=False,
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert any("BOT_ALLOWED_USERS" in e for e in errors4)
    assert any("BOT_ALLOW_OPEN" in e or "env file" in e for e in errors4)


def test_startup_fails_with_clear_config_error():
    """Startup exits with CONFIG ERROR and points to the missing setting (Docker/onboarding)."""
    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = ""
    env["BOT_PROVIDER"] = "claude"
    env["BOT_ALLOW_OPEN"] = "1"
    env.pop("OCTOPUS_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "app.main"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    assert result.returncode == 1
    assert "CONFIG ERROR" in result.stderr
    assert "TELEGRAM_BOT_TOKEN" in result.stderr
    assert "env file" in result.stderr or "./octopus" in result.stderr

def test_validate_config_open_access():
    errors5 = validate_config(
        make_config(
            telegram_token="fake-token",
            allowed_actor_keys=frozenset(),
            allow_open=True,
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
        )
    )
    assert [e for e in errors5 if "ALLOWED" in e] == []

def test_validate_config_codex_mutual_exclusion():
    errors6 = validate_config(
        make_config(
            telegram_token="fake-token",
            allow_open=False,
            allowed_actor_keys=frozenset({"tg:123"}),
            working_dir=Path.home(),
            data_dir=Path("/tmp/test-agent-bot"),
            codex_full_auto=True,
            codex_dangerous=True,
        )
    )
    assert any("CODEX_FULL_AUTO" in e for e in errors6)


def test_validate_config_rejects_invalid_codex_sandbox():
    errors = validate_config(make_config(codex_sandbox="off"))
    assert any("CODEX_SANDBOX" in e for e in errors)


def test_validate_config_rejects_invalid_codex_reasoning_effort():
    errors = validate_config(make_config(codex_reasoning_effort="maximum"))
    assert any("CODEX_REASONING_EFFORT" in e for e in errors)


def test_validate_config_accepts_xhigh_codex_reasoning_effort(tmp_path: Path):
    assert validate_config(make_config(codex_reasoning_effort="xhigh", working_dir=tmp_path)) == []


def test_load_config_rejects_invalid_codex_sandbox(tmp_path: Path):
    env_path = tmp_path / "invalid-codex.env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=test-token\n"
        "BOT_PROVIDER=codex\n"
        "BOT_ALLOW_OPEN=1\n"
        "CODEX_SANDBOX=off\n",
        encoding="utf-8",
    )

    with patch("app.config.env_path_for_instance", return_value=env_path):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit, match="CODEX_SANDBOX"):
                load_config("test-invalid-codex")


# -- BOT_SKILLS validation --

def test_validate_config_unknown_skill():
    errors_bad_skill = validate_config(make_config(default_skills=("nonexistent-skill-xyz",), provider_name="claude"))
    assert len([e for e in errors_bad_skill if "nonexistent-skill-xyz" in e]) > 0

def test_validate_config_valid_skill():
    errors_good_skill = validate_config(make_config(default_skills=("github-integration",), provider_name="claude"))
    assert len([e for e in errors_good_skill if "BOT_SKILLS" in e and "github-integration" in e]) == 0


def test_validate_config_reports_builtin_skill_catalog_load_failure(monkeypatch):
    import app.content_seed as content_seed

    def _raise_catalog_error():
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(content_seed, "builtin_skill_tracks", _raise_catalog_error)
    errors = validate_config(make_config(default_skills=("github-integration",), provider_name="claude"))
    assert any("could not be validated" in e for e in errors)


def test_validate_config_no_skills():
    errors_no_skills = validate_config(make_config(default_skills=(), provider_name="claude"))
    assert len([e for e in errors_no_skills if "BOT_SKILLS" in e]) == 0


# -- Webhook / transport mode --

def test_validate_config_invalid_bot_mode():
    errors = validate_config(make_config(bot_mode="invalid"))
    assert any("BOT_MODE" in e for e in errors)

def test_validate_config_webhook_mode_requires_url():
    errors = validate_config(make_config(bot_mode="webhook", webhook_url=""))
    assert any("BOT_WEBHOOK_URL" in e for e in errors)

def test_validate_config_database_url_must_be_postgres():
    """OCTOPUS_DATABASE_URL when set must be a postgresql:// URL."""
    errors = validate_config(make_config(database_url="mysql://localhost/db"))
    assert any("OCTOPUS_DATABASE_URL" in e and "postgresql" in e for e in errors)
    errors_empty = validate_config(make_config(database_url=""))
    assert not any("OCTOPUS_DATABASE_URL" in e for e in errors_empty)
    errors_ok = validate_config(make_config(database_url="postgresql://localhost/bot"))
    assert not any("OCTOPUS_DATABASE_URL" in e for e in errors_ok)


def test_validate_config_rejects_malformed_registry_url():
    errors = validate_config(
        make_config(agent_registries=(make_registry_connection(url="http://"),))
    )
    assert any("valid http" in e and "default" in e for e in errors)


def test_validate_config_rejects_remote_http_registry_url(tmp_path: Path):
    errors = validate_config(
        make_config(
            agent_registries=(make_registry_connection(url="http://registry.example.com"),),
            working_dir=tmp_path,
        )
    )
    assert any(
        "uses plain HTTP over a non-local address" in error
        for error in errors
    )


def test_validate_config_rejects_malformed_postgres_url():
    errors = validate_config(make_config(database_url="postgresql://"))
    assert any("OCTOPUS_DATABASE_URL" in e and "valid postgresql" in e for e in errors)


def test_validate_config_webhook_mode_with_url():
    errors = validate_config(make_config(
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    ))
    webhook_errors = [e for e in errors if "webhook" in e.lower()]
    assert webhook_errors == []

def test_validate_config_poll_mode_no_webhook_errors():
    errors = validate_config(make_config(bot_mode="poll", webhook_url=""))
    webhook_errors = [e for e in errors if "webhook" in e.lower()]
    assert webhook_errors == []


def test_validate_config_rejects_malformed_completion_webhook_url():
    errors = validate_config(make_config(completion_webhook_url="http://"))
    assert any("BOT_COMPLETION_WEBHOOK_URL" in e for e in errors)


def test_validate_config_rejects_remote_plain_http_completion_webhook():
    errors = validate_config(make_config(completion_webhook_url="http://hooks.example.com/completed"))
    assert any("BOT_COMPLETION_WEBHOOK_URL" in e and "plain HTTP over a non-local address" in e for e in errors)


def test_validate_config_allows_local_plain_http_completion_webhook():
    errors = validate_config(make_config(completion_webhook_url="http://127.0.0.1:9999/completed"))
    assert not any("BOT_COMPLETION_WEBHOOK_URL" in e for e in errors)


def test_validate_config_rejects_completion_webhook_when_host_resolution_fails(monkeypatch):
    import socket

    def _boom(*args, **kwargs):
        raise socket.gaierror("dns failed")

    monkeypatch.setattr("app.config.socket.getaddrinfo", _boom)

    errors = validate_config(make_config(completion_webhook_url="https://hooks.example.com/completed"))

    assert any("BOT_COMPLETION_WEBHOOK_URL" in e and "host resolution failed" in e for e in errors)


def test_validate_config_allows_completion_webhook_with_public_dns_target(monkeypatch):
    monkeypatch.setattr(
        "app.config.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (0, 0, 0, "", ("93.184.216.34", 443)),
        ],
    )

    errors = validate_config(make_config(completion_webhook_url="https://hooks.example.com/completed"))

    assert not any("BOT_COMPLETION_WEBHOOK_URL" in e for e in errors)


def test_validate_config_rejects_remote_plain_http_bot_webhook_url():
    errors = validate_config(
        make_config(
            bot_mode="webhook",
            webhook_url="http://bot.example.com/webhook",
        )
    )
    assert any("BOT_WEBHOOK_URL" in e and "plain HTTP over a non-local address" in e for e in errors)


def test_validate_config_allows_local_plain_http_bot_webhook_url():
    errors = validate_config(
        make_config(
            bot_mode="webhook",
            webhook_url="http://localhost:8080/webhook",
        )
    )
    assert not any("BOT_WEBHOOK_URL" in e for e in errors)

def test_config_defaults_to_poll():
    cfg = make_config()
    assert cfg.bot_mode == "poll"
    assert cfg.webhook_port == 8443


# -- main.py mode selection --


def _runtime_ok_provider(name: str = "claude"):
    """Provider double that matches main()'s startup health contract."""
    provider = MagicMock()
    provider.name = name
    provider.check_auth_health = AsyncMock(return_value=[])
    provider.check_runtime_health = AsyncMock(return_value=[])
    return provider


@contextmanager
def _patched_main_runtime(
    cfg,
    mock_app,
    provider=None,
    *,
    skip_database_startup_checks: bool = True,
):
    """Patch main() dependencies for mode-selection tests.

    main() now validates provider auth before starting, so the provider double
    must expose awaitable auth/runtime health checks.
    """
    provider = provider or _runtime_ok_provider()

    dispatcher = MagicMock()
    mock_app.bot_data = {}
    mock_app.post_init = AsyncMock(return_value=None)
    mock_app.post_shutdown = AsyncMock(return_value=None)
    bus = SimpleNamespace(reconcile_orphans=AsyncMock(return_value=0))
    processor_runner = SimpleNamespace(
        register=MagicMock(),
        run=AsyncMock(return_value=None),
        stop=AsyncMock(return_value=None),
    )
    bootstrap = SimpleNamespace(
        application=mock_app,
        runtime=SimpleNamespace(
            boot_id="test-boot",
            transport_dispatcher=dispatcher,
            cancellation_registry={},
        ),
        execution_runtime=MagicMock(),
    )
    telegram_transport_instance = SimpleNamespace(
        transport_id="telegram",
        boot_id="test-boot",
    )
    delivery_transport = SimpleNamespace(transport_id="registry-delivery")
    transport_store = MagicMock(name="transport_store")
    content_store = MagicMock(name="content_store")

    with ExitStack() as stack:
        stack.enter_context(patch("app.main.load_config", return_value=cfg))
        stack.enter_context(patch("app.main.make_provider", return_value=provider))
        stack.enter_context(patch("app.main.fail_fast"))
        if skip_database_startup_checks:
            stack.enter_context(patch("app.runtime.startup.run_database_startup_checks"))
        stack.enter_context(patch("app.runtime.startup.runtime_backend.init"))
        stack.enter_context(patch("app.runtime_backend.transport_store", return_value=transport_store))
        stack.enter_context(patch("app.runtime.startup.ensure_data_dirs"))
        stack.enter_context(patch("app.runtime.startup.init_content_store_for_config"))
        stack.enter_context(patch("app.runtime.startup.init_credential_store_for_config"))
        stack.enter_context(
            patch("app.runtime.composition.get_content_store", return_value=content_store)
        )
        stack.enter_context(patch("app.runtime.transport_builders.TransportDispatcher", return_value=dispatcher))
        stack.enter_context(patch("app.runtime.services.ControlPlaneBus", return_value=bus))
        register_registry_channels = stack.enter_context(
            patch("app.runtime.transport_builders.register_registry_channels")
        )
        build_bootstrap = stack.enter_context(
            patch("app.runtime.transport_builders.build_bootstrap", return_value=bootstrap)
        )
        telegram_bootstrap = stack.enter_context(
            patch("app.runtime.transport_builders.TelegramTransport")
        )
        telegram_bootstrap.return_value = telegram_transport_instance
        build_registry_delivery_transport = stack.enter_context(
            patch(
                "app.runtime.transport_builders.build_registry_delivery_transport",
                return_value=delivery_transport,
            )
        )
        bot_runtime_runner = stack.enter_context(
            patch("app.runtime.services.BotRuntime.run", autospec=True)
        )
        bot_runtime_runner.return_value = None
        stack.enter_context(patch("app.runtime.startup.close_db"))
        stack.enter_context(patch("app.runtime.startup.close_transport_db"))
        stack.enter_context(patch("sys.argv", ["bot"]))
        yield SimpleNamespace(
            provider=provider,
            dispatcher=dispatcher,
            build_bootstrap=build_bootstrap,
            bootstrap=bootstrap,
            telegram_bootstrap=telegram_bootstrap,
            telegram_transport=telegram_transport_instance,
            bus=bus,
            processor_runner=processor_runner,
            register_registry_channels=register_registry_channels,
            build_registry_delivery_transport=build_registry_delivery_transport,
            delivery_transport=delivery_transport,
            content_store=content_store,
            transport_store=transport_store,
            bot_runtime_runner=bot_runtime_runner,
        )


def _telegram_registry_runtime_config(**overrides):
    defaults = dict(
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    defaults.update(overrides)
    return make_config(**defaults)


def _assert_dispatcher_runner_called(runtime) -> None:
    runtime.bot_runtime_runner.assert_awaited_once()


def _assert_registry_channels_registered(runtime, cfg) -> None:
    runtime.register_registry_channels.assert_called_once()
    call = runtime.register_registry_channels.call_args
    assert call is not None
    assert call.args == (cfg, cfg.agent_registries, runtime.dispatcher)
    assert "services" in call.kwargs

def test_main_calls_run_polling_in_poll_mode():
    """When BOT_MODE=poll, main() runs the dispatcher-owned ingress process."""
    cfg = _telegram_registry_runtime_config(
        bot_mode="poll",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main
        main()
    runtime.provider.check_auth_health.assert_awaited_once()
    runtime.provider.check_runtime_health.assert_not_awaited()
    _assert_dispatcher_runner_called(runtime)
    call = runtime.build_bootstrap.call_args
    assert call is not None
    assert call.args[:2] == (cfg, runtime.provider)
    assert isinstance(call.kwargs["services"], BotServices)
    assert call.kwargs["dispatcher"] is runtime.dispatcher


def test_main_polling_invalid_token_exits_with_operator_message(capsys):
    cfg = _telegram_registry_runtime_config(
        bot_mode="poll",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        runtime.bot_runtime_runner.side_effect = InvalidToken("The token was rejected")
        from app.main import main

        with pytest.raises(SystemExit) as excinfo:
            main()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "Telegram rejected TELEGRAM_BOT_TOKEN" in err
    assert "@BotFather" in err


def test_main_polling_network_error_exits_with_connectivity_message(capsys):
    cfg = _telegram_registry_runtime_config(
        bot_mode="poll",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        runtime.bot_runtime_runner.side_effect = NetworkError("timeout")
        from app.main import main

        with pytest.raises(SystemExit) as excinfo:
            main()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "could not reach Telegram during startup" in err
    assert "DNS" in err or "network" in err.lower()


def test_main_database_error_is_sanitized(capsys):
    class OperationalError(RuntimeError):
        pass

    cfg = make_config(bot_mode="poll", database_url="postgresql://bot:secret@localhost:5432/bot")
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app, skip_database_startup_checks=False):
        with patch(
            "app.db.postgres.get_connection",
            side_effect=OperationalError("postgresql://bot:secret@localhost:5432/bot refused connection"),
        ):
            from app.main import main

            with pytest.raises(SystemExit) as excinfo:
                main()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "could not connect to the configured database" in err
    assert "postgresql://bot:secret@localhost:5432/bot" not in err


def test_main_calls_run_webhook_in_webhook_mode():
    """When BOT_MODE=webhook, main() runs the dispatcher-owned ingress process."""
    cfg = make_config(
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_listen="0.0.0.0",
        webhook_port=8443,
        webhook_secret="my-secret",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main
        main()
    runtime.provider.check_auth_health.assert_awaited_once()
    runtime.provider.check_runtime_health.assert_not_awaited()
    _assert_dispatcher_runner_called(runtime)


def test_main_allows_shared_runtime_in_webhook_mode():
    cfg = _telegram_registry_runtime_config(
        runtime_mode="shared",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main

        main()
    runtime.provider.check_auth_health.assert_awaited_once()
    runtime.provider.check_runtime_health.assert_not_awaited()
    _assert_dispatcher_runner_called(runtime)


def test_main_worker_role_runs_worker_process_only():
    cfg = _telegram_registry_runtime_config(
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main

        main()
    runtime.provider.check_auth_health.assert_awaited_once()
    runtime.provider.check_runtime_health.assert_not_awaited()
    _assert_dispatcher_runner_called(runtime)


def test_main_registry_runtime_starts_and_stops_with_dispatcher_lifecycle():
    cfg = make_config(
        agent_mode="registry",
        runtime_mode="shared",
        process_role="webhook",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        agent_registries=(make_registry_connection(),),
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main

        main()

    _assert_dispatcher_runner_called(runtime)
    _assert_registry_channels_registered(runtime, cfg)
    runtime.build_registry_delivery_transport.assert_called_once()
    runtime.dispatcher.register.assert_any_call(runtime.delivery_transport)


def test_main_registry_only_starts_without_telegram_ingress():
    registry = RegistryConnectionConfig(
        registry_id="prod",
        url="http://registry.test",
        enroll_token="enroll-secret",
        registry_scope="channel",
        poll_interval_seconds=5.0,
    )
    cfg = make_config(
        telegram_token="",
        credential_key="credential-secret",
        agent_mode="registry",
        agent_registries=(registry,),
        runtime_mode="shared",
        process_role="webhook",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    provider = _runtime_ok_provider()
    dispatcher = MagicMock()
    bootstrap = SimpleNamespace(
        application=None,
        runtime=SimpleNamespace(
            boot_id="registry-only-boot",
            transport_dispatcher=dispatcher,
            cancellation_registry={},
        ),
        execution_runtime=MagicMock(),
    )
    async def _run_runtime(bot_runtime):
        assert bot_runtime.boot_id == "registry-only-boot"
        assert bot_runtime.transport is dispatcher

    with ExitStack() as stack:
        stack.enter_context(patch("app.main.load_config", return_value=cfg))
        stack.enter_context(patch("app.main.make_provider", return_value=provider))
        stack.enter_context(patch("app.main.fail_fast"))
        stack.enter_context(patch("app.runtime.startup.run_database_startup_checks"))
        stack.enter_context(patch("app.runtime.startup.runtime_backend.init"))
        stack.enter_context(patch("app.runtime_backend.transport_store", return_value=MagicMock(name="transport_store")))
        stack.enter_context(patch("app.runtime.startup.ensure_data_dirs"))
        stack.enter_context(patch("app.runtime.startup.init_content_store_for_config"))
        stack.enter_context(patch("app.runtime.startup.init_credential_store_for_config"))
        stack.enter_context(patch("app.runtime.composition.get_content_store", return_value=MagicMock(name="content_store")))
        stack.enter_context(patch("app.runtime.transport_builders.TransportDispatcher", return_value=dispatcher))
        control_plane_bus_cls = stack.enter_context(patch("app.runtime.services.ControlPlaneBus"))
        register_registry_channels = stack.enter_context(
            patch("app.runtime.transport_builders.register_registry_channels")
        )
        build_bootstrap_mock = stack.enter_context(
            patch("app.runtime.transport_builders.build_bootstrap", return_value=bootstrap)
        )
        telegram_bootstrap = stack.enter_context(
            patch("app.runtime.transport_builders.TelegramTransport")
        )
        telegram_transport_instance = SimpleNamespace(
            transport_id="telegram",
            boot_id="registry-only-boot",
        )
        telegram_bootstrap.return_value = telegram_transport_instance
        build_registry_delivery_transport = stack.enter_context(
            patch(
                "app.runtime.transport_builders.build_registry_delivery_transport",
                return_value=SimpleNamespace(transport_id="registry-delivery"),
            )
        )
        bot_runtime_runner = stack.enter_context(
            patch("app.runtime.services.BotRuntime.run", autospec=True)
        )
        bot_runtime_runner.side_effect = _run_runtime
        stack.enter_context(patch("app.runtime.startup.close_db"))
        stack.enter_context(patch("app.runtime.startup.close_transport_db"))
        stack.enter_context(patch("sys.argv", ["bot"]))
        bus = SimpleNamespace(reconcile_orphans=AsyncMock(return_value=0))
        control_plane_bus_cls.return_value = bus
        from app.main import main

        main()

    build_bootstrap_call = build_bootstrap_mock.call_args
    assert build_bootstrap_call is not None
    assert build_bootstrap_call.args == (cfg, provider)
    assert isinstance(build_bootstrap_call.kwargs["services"], BotServices)
    assert build_bootstrap_call.kwargs["dispatcher"] is dispatcher
    telegram_bootstrap.assert_called_once()
    dispatcher.build_all_ingresses.assert_not_called()
    register_registry_channels.assert_called_once()
    register_call = register_registry_channels.call_args
    assert register_call is not None
    assert register_call.args == (cfg, cfg.agent_registries, dispatcher)
    assert "services" in register_call.kwargs
    build_registry_delivery_transport.assert_called_once()
    bot_runtime_runner.assert_awaited_once()
    await_args = bot_runtime_runner.await_args
    assert await_args is not None
    assert len(await_args.args) == 1


def test_main_shared_worker_with_registries_skips_control_plane_processor_startup():
    cfg = make_config(
        agent_mode="registry",
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        agent_registries=(make_registry_connection(),),
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()

    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main

        main()

    _assert_dispatcher_runner_called(runtime)
    _assert_registry_channels_registered(runtime, cfg)
    runtime.bus.reconcile_orphans.assert_not_awaited()


def test_main_webhook_role_skips_provider_runtime_validation():
    cfg = _telegram_registry_runtime_config(
        process_role="webhook",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    provider = _runtime_ok_provider()
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app, provider=provider) as runtime:
        from app.main import main

        main()
    assert provider.check_auth_health.await_count == 0
    assert provider.check_runtime_health.await_count == 0
    _assert_dispatcher_runner_called(runtime)


def test_main_doctor_defaults_to_startup_safe_provider_checks():
    cfg = make_config()
    provider = _runtime_ok_provider()
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app, provider=provider):
        with patch("app.main.run_doctor", side_effect=SystemExit(0)) as run_doctor:
            with patch("sys.argv", ["bot", "--doctor"]):
                from app.main import main

                with pytest.raises(SystemExit) as excinfo:
                    main()

    assert excinfo.value.code == 0

    run_doctor.assert_called_once_with(
        cfg,
        provider,
        include_provider_runtime_probe=False,
    )


def test_main_doctor_live_provider_opt_in_enables_runtime_probe():
    cfg = make_config()
    provider = _runtime_ok_provider()
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app, provider=provider):
        with patch("app.main.run_doctor", side_effect=SystemExit(0)) as run_doctor:
            with patch("sys.argv", ["bot", "--doctor", "--doctor-live-provider"]):
                from app.main import main

                with pytest.raises(SystemExit) as excinfo:
                    main()

    assert excinfo.value.code == 0

    run_doctor.assert_called_once_with(
        cfg,
        provider,
        include_provider_runtime_probe=True,
    )


def test_runs_registry_transport_moves_to_webhook_role_in_shared_mode():
    from app.runtime.startup import runs_registry_transport

    cfg = make_config(
        agent_mode="registry",
        runtime_mode="shared",
        process_role="webhook",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    assert runs_registry_transport(cfg) is True


def test_runs_registry_transport_is_disabled_for_shared_worker_role():
    from app.runtime.startup import runs_registry_transport

    cfg = make_config(
        agent_mode="registry",
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    assert runs_registry_transport(cfg) is False


def test_main_webhook_empty_secret_passes_none():
    """Empty BOT_WEBHOOK_SECRET is still accepted by the dispatcher-owned ingress path."""
    cfg = _telegram_registry_runtime_config(
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_secret="",
        database_url="postgresql://bot:bot@localhost:5432/bot",
    )
    mock_app = MagicMock()
    with _patched_main_runtime(cfg, mock_app) as runtime:
        from app.main import main
        main()
    _assert_dispatcher_runner_called(runtime)


def test_load_config_reads_webhook_env_vars():
    """load_config picks up BOT_MODE and webhook env vars .env file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOWED_USERS=123\n")
        f.write("BOT_MODE=webhook\n")
        f.write("BOT_WEBHOOK_URL=https://example.com/hook\n")
        f.write("BOT_WEBHOOK_LISTEN=0.0.0.0\n")
        f.write("BOT_WEBHOOK_PORT=9443\n")
        f.write("BOT_WEBHOOK_SECRET=s3cret\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-wh")
        assert cfg.bot_mode == "webhook"
        assert cfg.webhook_url == "https://example.com/hook"
        assert cfg.webhook_listen == "0.0.0.0"
        assert cfg.webhook_port == 9443
        assert cfg.webhook_secret == "s3cret"
    finally:
        os.unlink(env_path)


def test_load_config_reads_telegram_api_base_urls():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_TELEGRAM_API_BASE_URL=http://telegram-api-stub:8081/bot\n")
        f.write("BOT_TELEGRAM_FILE_API_BASE_URL=http://telegram-api-stub:8081/file/bot\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-telegram-api")
        assert cfg.telegram_api_base_url == "http://telegram-api-stub:8081/bot"
        assert cfg.telegram_file_api_base_url == "http://telegram-api-stub:8081/file/bot"
    finally:
        os.unlink(env_path)


def test_load_config_reads_completion_webhook_url():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_COMPLETION_WEBHOOK_URL=https://hooks.example.com/completed\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-webhook")
        assert cfg.completion_webhook_url == "https://hooks.example.com/completed"
    finally:
        os.unlink(env_path)


def test_load_config_reads_bot_credential_key():
    with tempfile.TemporaryDirectory() as tmp:
        envdir = Path(tmp)
        envfile = envdir / "test-credential-key.env"
        envfile.write_text(
            "TELEGRAM_BOT_TOKEN=tok\n"
            "BOT_PROVIDER=claude\n"
            "BOT_ALLOWED_USERS=1\n"
            "BOT_CREDENTIAL_KEY=credential-key-123\n"
        )
        with patch("app.config.env_path_for_instance", return_value=envfile):
            cfg = load_config("test-credential-key")
        assert cfg.credential_key == "credential-key-123"


def test_load_config_reads_indexed_agent_registries():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_AGENT_REGISTRY_1_ID=default\n")
        f.write("BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n")
        f.write("BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=enroll-secret\n")
        f.write("BOT_AGENT_REGISTRY_1_SCOPE=full\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-registry-single")
        assert cfg.agent_registries == (
            RegistryConnectionConfig(
                registry_id="default",
                url="http://registry:8787",
                enroll_token="enroll-secret",
                registry_scope="full",
                poll_interval_seconds=5.0,
            ),
        )
    finally:
        os.unlink(env_path)


def test_load_config_reads_multiple_indexed_agent_registries():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_AGENT_REGISTRY_1_ID=prod\n")
        f.write("BOT_AGENT_REGISTRY_1_URL=https://registry-prod.example.com\n")
        f.write("BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=prod-secret\n")
        f.write("BOT_AGENT_REGISTRY_1_SCOPE=full\n")
        f.write("BOT_AGENT_REGISTRY_2_ID=analytics\n")
        f.write("BOT_AGENT_REGISTRY_2_URL=https://registry-analytics.example.com\n")
        f.write("BOT_AGENT_REGISTRY_2_ENROLL_TOKEN=analytics-secret\n")
        f.write("BOT_AGENT_REGISTRY_2_SCOPE=channel\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-registry-indexed")
        assert cfg.agent_registries == (
            RegistryConnectionConfig(
                registry_id="prod",
                url="https://registry-prod.example.com",
                enroll_token="prod-secret",
                registry_scope="full",
                poll_interval_seconds=5.0,
            ),
            RegistryConnectionConfig(
                registry_id="analytics",
                url="https://registry-analytics.example.com",
                enroll_token="analytics-secret",
                registry_scope="channel",
                poll_interval_seconds=5.0,
            ),
        )
        assert cfg.agent_mode == "registry"
    finally:
        os.unlink(env_path)


def test_validate_config_shared_runtime_requires_webhook_mode():
    errors = validate_config(make_config(runtime_mode="shared", bot_mode="poll"))
    assert any("shared" in e.lower() and "requires bot_mode=webhook" in e.lower() for e in errors)


def test_validate_config_accepts_shared_runtime_with_webhook_without_database_url():
    errors = validate_config(
        make_config(
            runtime_mode="shared",
            bot_mode="webhook",
            webhook_url="https://bot.example.com/webhook",
            database_url="",
        )
    )
    runtime_errors = [e for e in errors if "runtime" in e.lower()]
    assert runtime_errors == []


def test_validate_config_accepts_shared_runtime_with_webhook_and_database_url():
    errors = validate_config(
        make_config(
            runtime_mode="shared",
            bot_mode="webhook",
            webhook_url="https://bot.example.com/webhook",
            database_url="postgresql://bot:bot@localhost:5432/bot",
        )
    )
    runtime_errors = [e for e in errors if "runtime" in e.lower()]
    assert runtime_errors == []


def test_validate_config_accepts_local_runtime_mode():
    """Phase 13: BOT_RUNTIME_MODE=local is valid (default)."""
    errors = validate_config(make_config(runtime_mode="local"))
    runtime_errors = [e for e in errors if "RUNTIME" in e or "runtime" in e]
    assert runtime_errors == []


def test_validate_config_invalid_process_role():
    errors = validate_config(make_config(process_role="invalid"))
    assert any("BOT_PROCESS_ROLE" in e for e in errors)


def test_validate_config_webhook_process_role_requires_webhook_mode():
    errors = validate_config(make_config(process_role="webhook", bot_mode="poll"))
    assert any("BOT_PROCESS_ROLE=webhook requires BOT_MODE=webhook" in e for e in errors)


def test_validate_config_webhook_process_role_requires_shared_runtime():
    errors = validate_config(make_config(process_role="webhook", runtime_mode="local", bot_mode="webhook"))
    assert any("BOT_PROCESS_ROLE=webhook requires BOT_RUNTIME_MODE=shared" in e for e in errors)


def test_validate_config_worker_process_role_requires_shared_runtime():
    errors = validate_config(make_config(process_role="worker", runtime_mode="local"))
    assert any("BOT_PROCESS_ROLE=worker requires BOT_RUNTIME_MODE=shared" in e for e in errors)


def test_process_role_defaults_to_all():
    cfg = make_config()
    assert cfg.process_role == "all"


def test_load_config_reads_process_role():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_PROCESS_ROLE=worker\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-role")
        assert cfg.process_role == "worker"
    finally:
        os.unlink(env_path)


def test_claim_lease_ttl_defaults_to_300():
    cfg = make_config()
    assert cfg.claim_lease_ttl_seconds == 300


def test_claim_lease_ttl__env():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("BOT_CLAIM_LEASE_TTL=45\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            cfg = load_config("test-lease")
        assert cfg.claim_lease_ttl_seconds == 45
    finally:
        os.unlink(env_path)


def test_claim_lease_ttl_must_be_positive():
    errors = validate_config(make_config(claim_lease_ttl_seconds=0))
    assert any("BOT_CLAIM_LEASE_TTL must be greater than 0" in e for e in errors)


def test_claim_sweep_interval_must_be_positive():
    errors = validate_config(make_config(claim_sweep_interval_seconds=0))
    assert any("BOT_CLAIM_SWEEP_INTERVAL_SECONDS must be greater than 0" in e for e in errors)


def test_delegation_timeout_defaults_to_3600():
    cfg = make_config()
    assert cfg.delegation_timeout_seconds == 3600


def test_delegation_timeout_must_be_positive():
    errors = validate_config(make_config(delegation_timeout_seconds=0))
    assert any("BOT_DELEGATION_TIMEOUT_SECONDS must be greater than 0" in e for e in errors)


def test_validate_config_rejects_invalid_telegram_api_base_url():
    errors = validate_config(make_config(telegram_api_base_url="ftp://telegram-api-stub:8081/bot"))
    assert any("BOT_TELEGRAM_API_BASE_URL" in e for e in errors)


def test_load_config_reads_database_url_and_pool_settings():
    """load_config picks up OCTOPUS_DATABASE_URL and pool settings .env."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=tok\n")
        f.write("BOT_PROVIDER=claude\n")
        f.write("BOT_ALLOW_OPEN=1\n")
        f.write("OCTOPUS_DATABASE_URL=postgresql://localhost:5432/botdb\n")
        f.write("BOT_DB_POOL_MIN_SIZE=2\n")
        f.write("BOT_DB_POOL_MAX_SIZE=20\n")
        f.write("BOT_DB_CONNECT_TIMEOUT=15\n")
        env_path = f.name
    try:
        with patch("app.config.env_path_for_instance", return_value=Path(env_path)):
            with patch.dict(os.environ, {}, clear=True):
                cfg = load_config("test-db")
        assert cfg.database_url == "postgresql://localhost:5432/botdb"
        assert cfg.db_pool_min_size == 2
        assert cfg.db_pool_max_size == 20
        assert cfg.db_connect_timeout_seconds == 15
    finally:
        os.unlink(env_path)


# -- Config validation edge cases (test_high_risk.py) --


def test_config_bad_timeout():
    """Non-integer BOT_TIMEOUT_SECONDS must produce a friendly SystemExit."""
    old_env = os.environ.get("BOT_TIMEOUT_SECONDS")
    old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    old_provider = os.environ.get("BOT_PROVIDER")
    old_working_dir = os.environ.get("BOT_WORKING_DIR")
    old_data_dir = os.environ.get("BOT_DATA_DIR")
    old_allow_open = os.environ.get("BOT_ALLOW_OPEN")
    os.environ["TELEGRAM_BOT_TOKEN"] = "x"
    os.environ["BOT_PROVIDER"] = "claude"
    os.environ["BOT_WORKING_DIR"] = tempfile.gettempdir()
    os.environ["BOT_DATA_DIR"] = tempfile.gettempdir()
    os.environ["BOT_ALLOW_OPEN"] = "1"
    os.environ["BOT_TIMEOUT_SECONDS"] = "not_a_number"
    try:
        load_config("test")
        assert False, "bad timeout should raise SystemExit"
    except SystemExit as exc:
        assert "BOT_TIMEOUT_SECONDS must be an integer" in str(exc)
    finally:
        if old_env is not None:
            os.environ["BOT_TIMEOUT_SECONDS"] = old_env
        else:
            os.environ.pop("BOT_TIMEOUT_SECONDS", None)
        for key, value in (
            ("TELEGRAM_BOT_TOKEN", old_token),
            ("BOT_PROVIDER", old_provider),
            ("BOT_WORKING_DIR", old_working_dir),
            ("BOT_DATA_DIR", old_data_dir),
            ("BOT_ALLOW_OPEN", old_allow_open),
        ):
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


def test_data_dir_writable():
    cfg_writable = make_config(data_dir=Path("/tmp"))
    errors_writable = [e for e in validate_config(cfg_writable) if "DATA_DIR" in e]
    assert errors_writable == []


def test_data_dir_unwritable():
    cfg_bad = make_config(data_dir=Path("/root/impossible/path"))
    errors_bad = [e for e in validate_config(cfg_bad) if "DATA_DIR" in e]
    assert len(errors_bad) > 0


def test_data_dir_is_file():
    with tempfile.NamedTemporaryFile() as f:
        cfg_file = make_config(data_dir=Path(f.name))
        errors_file = [e for e in validate_config(cfg_file) if "DATA_DIR" in e]
        assert len(errors_file) > 0


def test_extra_dirs_valid():
    cfg_good_dirs = make_config(extra_dirs=(Path("/tmp"),))
    errors_good = [e for e in validate_config(cfg_good_dirs) if "EXTRA_DIRS" in e]
    assert errors_good == []


def test_extra_dirs_nonexistent():
    cfg_bad_dirs = make_config(extra_dirs=(Path("/nonexistent/fake/dir"),))
    errors_bad = [e for e in validate_config(cfg_bad_dirs) if "EXTRA_DIRS" in e]
    assert len(errors_bad) > 0


def test_extra_dirs_mixed():
    cfg_mixed = make_config(extra_dirs=(Path("/tmp"), Path("/no/such/path")))
    errors_mixed = [e for e in validate_config(cfg_mixed) if "EXTRA_DIRS" in e]
    assert len(errors_mixed) == 1


def test_config_isolation():
    """load_config() must not leak state across instances."""
    import app.config as config_mod

    env_a = {
        "TELEGRAM_BOT_TOKEN": "token-a",
        "BOT_PROVIDER": "claude",
        "BOT_WORKING_DIR": tempfile.gettempdir(),
        "BOT_DATA_DIR": tempfile.gettempdir(),
        "BOT_ALLOW_OPEN": "1",
        "BOT_MODEL": "model-a",
    }
    env_b = {
        "TELEGRAM_BOT_TOKEN": "token-b",
        "BOT_PROVIDER": "codex",
        "BOT_WORKING_DIR": tempfile.gettempdir(),
        "BOT_DATA_DIR": tempfile.gettempdir(),
        "BOT_ALLOW_OPEN": "1",
        "BOT_MODEL": "model-b",
    }

    orig_env_path = config_mod.env_path_for_instance
    try:
        # Instance A
        config_mod.env_path_for_instance = lambda name: Path("/dev/null")
        saved = {k: os.environ.get(k) for k in env_a}
        os.environ.update(env_a)
        cfg_a = load_config("inst-a")

        # Instance B — different env
        os.environ.update(env_b)
        cfg_b = load_config("inst-b")

        assert cfg_a.model == "model-a"
        assert cfg_b.model == "model-b"
        assert cfg_a.provider_name == "claude"
        assert cfg_b.provider_name == "codex"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        config_mod.env_path_for_instance = orig_env_path


# -- _parse_projects (Phase 15: ProjectBinding with | separator) --


def test_parse_projects_minimal():
    """Name and path only — no optional fields."""
    result = _parse_projects("frontend:/home/app/frontend")
    assert len(result) == 1
    assert result[0] == ProjectBinding(name="frontend", root_dir="/home/app/frontend")
    assert result[0].file_policy == ""
    assert result[0].model_profile == ""


def test_parse_projects_with_policy():
    """Name, path, and file_policy via | separator."""
    result = _parse_projects("frontend:/home/app/frontend|inspect")
    assert len(result) == 1
    assert result[0].name == "frontend"
    assert result[0].root_dir == "/home/app/frontend"
    assert result[0].file_policy == "inspect"
    assert result[0].model_profile == ""


def test_parse_projects_with_policy_and_profile():
    """Full format: name:/path|policy|profile."""
    result = _parse_projects("frontend:/home/app/frontend|edit|fast")
    assert len(result) == 1
    assert result[0].file_policy == "edit"
    assert result[0].model_profile == "fast"


def test_parse_projects_multiple():
    """Multiple projects comma-separated."""
    result = _parse_projects(
        "fe:/home/fe|inspect, be:/home/be|edit|best"
    )
    assert len(result) == 2
    assert result[0].name == "fe"
    assert result[0].file_policy == "inspect"
    assert result[1].name == "be"
    assert result[1].model_profile == "best"


def test_parse_projects_empty_and_whitespace():
    """Empty string and whitespace-only produce no projects."""
    assert _parse_projects("") == ()
    assert _parse_projects("   ") == ()


def test_parse_projects_skip_malformed():
    """Entries missing ':' or missing name/path are skipped."""
    result = _parse_projects("good:/tmp, bad-no-colon, :/no-name, empty:, good2:/tmp")
    names = [p.name for p in result]
    assert names == ["good", "good2"]


def test_parse_projects_empty_policy_placeholder():
    """Empty policy field with profile: name:/path||fast."""
    result = _parse_projects("fe:/home/fe||fast")
    assert result[0].file_policy == ""
    assert result[0].model_profile == "fast"


# -- validate_config: project field validation --


def test_validate_config_rejects_invalid_file_policy():
    """file_policy must be 'inspect', 'edit', or empty."""
    cfg = make_config(projects=(
        ProjectBinding(name="bad", root_dir="/tmp", file_policy="write"),
    ))
    errors = validate_config(cfg)
    assert any("file_policy" in e and "'bad'" in e for e in errors)


def test_validate_config_accepts_valid_file_policies():
    """inspect, edit, and empty are all valid."""
    for policy in ("inspect", "edit", ""):
        cfg = make_config(projects=(
            ProjectBinding(name="ok", root_dir="/tmp", file_policy=policy),
        ))
        errors = validate_config(cfg)
        policy_errors = [e for e in errors if "file_policy" in e]
        assert policy_errors == [], f"Unexpected error for policy '{policy}': {policy_errors}"


def test_validate_config_rejects_unknown_model_profile():
    """model_profile must exist in model_profiles when profiles are configured."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="nonexistent"),
        ),
        model_profiles={"fast": "claude-haiku-4-5-20251001"},
    )
    errors = validate_config(cfg)
    assert any("model_profile" in e and "'proj'" in e for e in errors)


def test_validate_config_rejects_model_profile_when_no_profiles_configured():
    """model_profile set but no BOT_MODEL_PROFILES configured is an error."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="anything"),
        ),
        model_profiles={},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert len(profile_errors) == 1
    assert "no BOT_MODEL_PROFILES" in profile_errors[0]


def test_validate_config_allows_empty_model_profile_when_no_profiles_configured():
    """Empty model_profile with no BOT_MODEL_PROFILES is fine (no default to resolve)."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile=""),
        ),
        model_profiles={},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert profile_errors == []


def test_validate_config_accepts_known_model_profile():
    """Profile that exists in model_profiles is valid."""
    cfg = make_config(
        projects=(
            ProjectBinding(name="proj", root_dir="/tmp", model_profile="fast"),
        ),
        model_profiles={"fast": "claude-haiku-4-5-20251001"},
    )
    errors = validate_config(cfg)
    profile_errors = [e for e in errors if "model_profile" in e]
    assert profile_errors == []


def test_validate_config_duplicate_project_names():
    """Duplicate project names are rejected."""
    cfg = make_config(projects=(
        ProjectBinding(name="dup", root_dir="/tmp"),
        ProjectBinding(name="dup", root_dir="/tmp"),
    ))
    errors = validate_config(cfg)
    assert any("Duplicate" in e and "'dup'" in e for e in errors)


# -- should_publish_event / PUBLISH_LEVEL_KINDS --


def test_should_publish_event_returns_true_for_included_kind():
    cfg = make_config(registry_publish_level="standard")
    assert should_publish_event(cfg, "message.user") is True
    assert should_publish_event(cfg, "message.bot") is True


def test_should_publish_event_returns_false_for_excluded_kind():
    cfg = make_config(registry_publish_level="minimal")
    assert should_publish_event(cfg, "approval.requested") is False
    assert should_publish_event(cfg, "delegation.proposed") is False
    assert should_publish_event(cfg, "provider.response") is False


def test_should_publish_event_returns_false_for_unknown_level():
    cfg = make_config(registry_publish_level="nonexistent")
    assert should_publish_event(cfg, "message.user") is False


def test_all_levels_include_message_user_and_message_bot():
    for level in ("minimal", "standard", "full"):
        kinds = PUBLISH_LEVEL_KINDS[level]
        assert "message.user" in kinds, f"{level} missing message.user"
        assert "message.bot" in kinds, f"{level} missing message.bot"


def test_full_level_only_includes_live_detailed_event_kinds():
    kinds = PUBLISH_LEVEL_KINDS["full"]
    assert "provider.request" in kinds
    assert "provider.response" in kinds
    assert "tool.execution" in kinds
    assert "approval.requested" in kinds
    assert "approval.decided" in kinds
    assert "delegation.completed" in kinds
    assert "file.change" not in kinds


def test_minimal_level_excludes_approval_delegation_provider_response():
    kinds = PUBLISH_LEVEL_KINDS["minimal"]
    assert "provider.request" not in kinds
    assert "approval.requested" not in kinds
    assert "approval.decided" not in kinds
    assert "delegation.proposed" not in kinds
    assert "delegation.submitted" not in kinds
    assert "provider.response" not in kinds
