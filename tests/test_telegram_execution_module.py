from app.channels.telegram.execution import build_user_prompt, resolve_context
from app.session_state import session_from_dict
from app.storage import load_session
from tests.support.handler_support import current_runtime, fresh_env


def test_build_user_prompt_collects_image_paths() -> None:
    class Attachment:
        def __init__(self, path: str, original_name: str, is_image: bool) -> None:
            self.path = path
            self.original_name = original_name
            self.is_image = is_image

    prompt, image_paths = build_user_prompt(
        "Review these files",
        [
            Attachment("/tmp/design.png", "design.png", True),
            Attachment("/tmp/notes.txt", "notes.txt", False),
        ],
    )

    assert "Review these files" in prompt
    assert "/tmp/design.png" in prompt
    assert "/tmp/notes.txt" in prompt
    assert image_paths == ["/tmp/design.png"]


def test_resolve_context_uses_runtime_provider_name() -> None:
    with fresh_env() as (_data_dir, _cfg, prov):
        runtime = current_runtime()
        session = session_from_dict(
            load_session(
                runtime.config.data_dir,
                "telegram:12345",
                runtime.provider.name,
                runtime.provider.new_provider_state,
                runtime.config.approval_mode,
            )
        )

        resolved = resolve_context(runtime, session)

        assert resolved.provider_name == prov.name
