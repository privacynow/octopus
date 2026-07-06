from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_provider_auth_scripts_export_runtime_image_for_compose_interpolation() -> None:
    for script_name in ("provider_login.sh", "provider_status.sh", "provider_logout.sh"):
        script = REPO_ROOT / "scripts" / "provider" / script_name
        text = script.read_text(encoding="utf-8")

        assert 'OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\' in text
        assert text.index('OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\') < text.index("docker compose")
