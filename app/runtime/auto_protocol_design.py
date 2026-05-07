"""Bot-runtime Auto Protocol semantic planning."""

from __future__ import annotations

import json
import re
from typing import Any

from octopus_sdk.config import BotConfigBase
from octopus_sdk.protocols.auto_design import (
    AUTO_PROTOCOL_RUNTIME_MANIFEST_GUIDANCE,
    ProtocolAutoDesignModelRequestRecord,
    ProtocolAutoDesignModelResponseRecord,
)
from octopus_sdk.providers import PreflightContext, Provider


class _NullProgress:
    async def update(self, html_text: str, *, force: bool = False) -> None:
        del html_text, force


def _planner_prompt(request: ProtocolAutoDesignModelRequestRecord) -> str:
    source_document = request.source_document.as_dict()
    agents = [item.as_dict() for item in request.available_agents]
    skills = [item.as_dict() for item in request.available_skills]
    payload = {
        "mode": request.mode,
        "requirement_text": request.requirement_text,
        "constraints_text": request.constraints_text,
        "source_document": source_document,
        "available_agents": agents,
        "available_skills": skills,
        "workspace_ref": request.workspace_ref,
    }
    return (
        "You are designing an Octopus Auto Protocol plan. Return only valid JSON. "
        "Do not include Markdown fences or commentary.\n\n"
        "Your job is semantic decomposition, not final protocol JSON. Infer the smallest serious workflow that can deliver the requested outcome. "
        "Avoid customer/example-specific shortcuts. Keep the plan under 18 final stages after compilation, so prefer 3-6 supporting work packages plus one primary outcome package. "
        "Each work package must be domain-specific to the requirement, have a strict quality bar, and include an adversarial review rubric. "
        "Do not add several final reviewers after the primary artifact; final acceptance will inspect or exercise the primary outcome. "
        "When the outcome is an app, game, report SPA, API service, backend system, or any other interactive product, the implementation package must produce a user-facing UI/API package, tests/smoke evidence, and an octopus-runtime.json manifest at the package root. "
        "The implementation package must build and smoke-test the package before final acceptance; runtime start commands are launch commands only and must not install dependencies, compile, package, run tests, or use developer-mode commands like mvn spring-boot:run. "
        "The operator UI/API must make the result of core user actions visible in the product itself. A user should not need logs or raw JSON archaeology to know what happened. "
        f"{AUTO_PROTOCOL_RUNTIME_MANIFEST_GUIDANCE} "
        "For static HTML packages, runtime_kind can be static and index.html must be at the package root. "
        "For Java, Python, Node, binary, or process-backed systems, choose coherent public APIs and an operator UI that exercises those APIs through the runtime surface.\n\n"
        "Return this JSON object shape:\n"
        "{\n"
        '  "requirement_summary": "plain summary",\n'
        '  "domain": "requirement-specific domain label",\n'
        '  "risk_assessment": "important risks or empty",\n'
        '  "assumptions": ["..."],\n'
        '  "open_questions": [],\n'
        '  "work_packages": [\n'
        "    {\n"
        '      "package_key": "stable_snake_case_key",\n'
        '      "display_name": "Human name",\n'
        '      "rationale": "why this package is necessary",\n'
        '      "role_key": "stable_snake_case_role",\n'
        '      "role_display_name": "Human role name",\n'
        '      "role_responsibility": "owned responsibility",\n'
        '      "required_skills": ["skill names"],\n'
        '      "purpose": "specific work to perform",\n'
        '      "quality_bar": "strict completion bar",\n'
        '      "artifact_key": "stable_snake_case_artifact",\n'
        '      "artifact_display_name": "Human artifact name",\n'
        '      "artifact_description": "artifact contract, including runtime manifest expectations when runnable",\n'
        '      "review_role_key": "stable_snake_case_reviewer",\n'
        '      "review_display_name": "Human reviewer name",\n'
        '      "review_responsibility": "independent review responsibility",\n'
        '      "review_rubric": "adversarial rubric with revise conditions"\n'
        "    }\n"
        "  ],\n"
        '  "primary_artifact": {"artifact_key": "produced_outcome", "display_name": "Produced Outcome", "produced_by_stage_key": "produce_outcome", "open_behavior": "runtime"},\n'
        '  "review_policy": {"stance": "adversarial", "max_review_rounds": 3, "stage_hard_cap": 18},\n'
        '  "run_inputs": [{"key": "problem_statement", "label": "Run objective", "kind": "textarea", "required": true, "default_value": "..."}],\n'
        '  "acceptance_criteria": ["..."],\n'
        '  "warnings": [{"code": "planner.scope_note", "message": "human-readable warning", "severity": "warning", "section": "planner", "action": "review_generated_protocol"}],\n'
        '  "planner_ref": "provider-semantic-planner"\n'
        "}\n\n"
        "Warnings must be objects with code, message, severity, section, and action. Use an empty list when there are no warnings.\n\n"
        "Required package guidance: include requirement/planning work, requirement review will be added by the compiler, "
        "include focused supporting packages that are truly needed, and include one implementation/outcome package. "
        "For the outcome package use package_key 'implementation' if you include it; otherwise the compiler will create it. "
        "For runnable outcomes, set primary_artifact.open_behavior to 'runtime' and make the implementation artifact contract require a root octopus-runtime.json manifest. "
        "Do not include validation-only or final-review-only packages.\n\n"
        "Planning input JSON:\n"
        f"{json.dumps(payload, sort_keys=True)}"
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        raise ValueError("Planner returned empty output.")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, flags=re.DOTALL)
    if fence:
        value = fence.group(1)
    else:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Planner output did not contain a JSON object.")
        value = value[start : end + 1]
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("Planner JSON root must be an object.")
    return decoded


async def design_auto_protocol_with_provider(
    request: ProtocolAutoDesignModelRequestRecord,
    *,
    config: BotConfigBase,
    provider: Provider,
    provider_state_factory,
) -> ProtocolAutoDesignModelResponseRecord:
    del provider_state_factory
    result = await provider.run_preflight(
        _planner_prompt(request),
        [],
        _NullProgress(),
        context=PreflightContext(
            extra_dirs=[],
            system_prompt=(
                "You are an Octopus protocol design worker. Return structured JSON only. "
                "Do not edit files, start servers, or perform external actions."
            ),
            active_skill_tools_summary="",
            working_dir=str(getattr(config, "working_dir", "") or ""),
            file_policy="inspect",
            effective_model=str(getattr(config, "model", "") or ""),
        ),
    )
    if result.returncode != 0 or result.timed_out or result.cancelled:
        detail = result.text.strip() or f"provider exited with code {result.returncode}"
        raise RuntimeError(f"Auto Protocol planner failed: {detail[:1000]}")
    return ProtocolAutoDesignModelResponseRecord.model_validate(_extract_json_object(result.text))
