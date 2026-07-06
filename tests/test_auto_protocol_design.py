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


class _CapturingPlannerProvider:
    def __init__(self):
        self.context = None

    async def run_preflight(self, prompt, image_paths, progress, context=None, cancel=None):
        del image_paths, progress, cancel
        self.context = context
        return RunResult(
            text=(
                '{"requirement_summary":"Build a small browser app.",'
                '"domain":"browser app","risk_assessment":"medium",'
                '"assumptions":[],"open_questions":[],'
                '"work_packages":[{"package_key":"implementation","display_name":"Implementation",'
                '"rationale":"The app must be built before review.",'
                '"role_key":"builder","role_display_name":"Builder",'
                '"role_responsibility":"Build the requested app.",'
                '"required_skills":["implementation"],'
                '"purpose":"Build the requested app.","quality_bar":"App works.",'
                '"artifact_key":"app","artifact_display_name":"Runnable app",'
                '"artifact_description":"Browser app package.","artifact_path":"artifacts/app"}]}'
            )
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


async def test_design_auto_protocol_uses_configured_heavyweight_timeout():
    provider = _CapturingPlannerProvider()

    await design_auto_protocol_with_provider(
        ProtocolAutoDesignModelRequestRecord(
            requirement_text="Build a small browser app.",
        ),
        config=make_config(timeout_seconds=1800),
        provider=provider,
        provider_state_factory=lambda conversation_key: {},
    )

    assert provider.context is not None
    assert provider.context.timeout_seconds == 1800
