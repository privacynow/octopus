import pytest

from app.runtime.auto_protocol_design import design_auto_protocol_with_provider
from octopus_sdk.protocols.auto_design import ProtocolAutoDesignModelRequestRecord
from octopus_sdk.providers import RunResult
from tests.support.config_support import make_config


class _FailingPlannerProvider:
    async def run_preflight(self, prompt, image_paths, progress, context=None, cancel=None):
        del prompt, image_paths, progress, context, cancel
        return RunResult(
            text=(
                "Codex authentication failed while refreshing the stored token. "
                "Run './octopus' and choose Diagnose -> Provider auth for codex, then retry."
            ),
            returncode=1,
        )


async def test_design_auto_protocol_reports_provider_failure_before_json_parse():
    with pytest.raises(RuntimeError) as exc:
        await design_auto_protocol_with_provider(
            ProtocolAutoDesignModelRequestRecord(
                requirement_text="Build a small browser app.",
            ),
            config=make_config(),
            provider=_FailingPlannerProvider(),
            provider_state_factory=lambda conversation_key: {},
        )

    message = str(exc.value)
    assert "Auto Protocol planner failed" in message
    assert "Codex authentication failed" in message
    assert "Planner output did not contain a JSON object" not in message
