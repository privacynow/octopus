from __future__ import annotations

import pytest

from app.runtime.process import validate_required_runtime_profile
from tests.support.config_support import make_config
from tests.support.config_support import make_registry_connection


def test_telegram_runtime_requires_registry_agent_mode() -> None:
    config = make_config(
        agent_mode="standalone",
        agent_registries=(make_registry_connection(),),
    )

    with pytest.raises(RuntimeError, match="BOT_AGENT_MODE=registry"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_requires_registry_connections() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(),
    )

    with pytest.raises(RuntimeError, match="configured registry connections"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_requires_full_registry_participant_coverage() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(make_registry_connection(registry_scope="channel"),),
    )

    with pytest.raises(RuntimeError, match="channel and coordination capabilities"):
        validate_required_runtime_profile(config)


def test_telegram_runtime_accepts_split_channel_and_coordination_profiles() -> None:
    config = make_config(
        agent_mode="registry",
        agent_registries=(
            make_registry_connection(registry_id="chan", registry_scope="channel"),
            make_registry_connection(registry_id="coord", registry_scope="coordination"),
        ),
    )

    validate_required_runtime_profile(config)
