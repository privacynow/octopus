from app.channels.telegram.session_io import (
    actor_key,
    conversation_key,
    event_key,
    load,
    save,
    telegram_chat_id,
)
from tests.support.handler_support import current_runtime, fresh_env


def test_session_io_key_helpers_round_trip() -> None:
    assert conversation_key(12345) == "tg:12345"
    assert conversation_key("tg:12345") == "tg:12345"
    assert actor_key(42) == "tg:42"
    assert actor_key("tg:42") == "tg:42"
    assert event_key(99) == "tg:99"
    assert event_key("tg:99") == "tg:99"
    assert telegram_chat_id(12345) == 12345
    assert telegram_chat_id("tg:12345") == 12345


def test_session_io_load_save_round_trip() -> None:
    with fresh_env() as (_data_dir, _cfg, _prov):
        runtime = current_runtime()
        session = load(runtime, 12345)
        session.role = "reviewer"
        session.active_skills = ["github-integration"]
        save(runtime, 12345, session)

        restored = load(runtime, 12345)

        assert restored.role == "reviewer"
        assert restored.active_skills == ["github-integration"]
