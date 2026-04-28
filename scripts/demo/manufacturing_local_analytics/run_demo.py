#!/usr/bin/env python3
"""Run the manufacturing local analytics demo end to end."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

try:
    from .analyze_manufacturing_quality import analyze_data
    from .generate_sample_data import generate_sample_data
    from .profile_manufacturing_data import profile_data
except ImportError:  # pragma: no cover - direct script execution
    from analyze_manufacturing_quality import analyze_data
    from generate_sample_data import generate_sample_data
    from profile_manufacturing_data import profile_data


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = Path(".tmp/demo/manufacturing-local-analytics")
TEMPLATE_SLUG = "manufacturing-local-analytics"

ARTIFACT_PATHS = {
    "input_contract": "protocol/input_contract.json",
    "profile_script": "scripts/profile_manufacturing_data.py",
    "profile_summary": "reports/profile_summary.md",
    "model_visible_context": "reports/model_visible_context.md",
    "analysis_script": "scripts/analyze_manufacturing_quality.py",
    "quality_flags": "reports/quality_flags.csv",
    "defect_summary": "reports/defect_summary.csv",
    "findings_report": "reports/manufacturing_findings.md",
    "heatmap": "reports/defect_heatmap.html",
    "run_manifest": "reports/run_manifest.json",
}

STAGE_OUTPUTS = {
    "define_input_contract": ["input_contract"],
    "generate_profile_script": ["profile_script"],
    "run_profile_locally": ["profile_summary", "model_visible_context"],
    "generate_analysis_script": ["analysis_script"],
    "run_analysis_locally": ["quality_flags", "defect_summary", "findings_report", "heatmap"],
    "validate_outputs": ["run_manifest"],
    "review_report": [],
}

STAGE_RESPONSES = {
    "define_input_contract": "Defined the local CSV contract, join keys, and privacy boundary.",
    "generate_profile_script": "Generated the local profiler script.",
    "run_profile_locally": "Ran the profiler locally and produced controlled profile artifacts.",
    "generate_analysis_script": "Generated the repeatable local analyzer script.",
    "run_analysis_locally": "Ran the analyzer locally and produced report artifacts.",
    "validate_outputs": "Validated required artifacts and privacy checks.",
    "review_report": "Approved the report for demo use.",
}


class RegistryClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.csrf_token = ""
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_session()
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if method.upper() in {"POST", "PUT", "DELETE", "PATCH"}:
            headers["X-CSRF-Token"] = self.csrf_token
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
        if not text:
            return {}
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise RuntimeError(f"{method} {path} returned non-object JSON")
        return loaded

    def _ensure_session(self) -> None:
        if self.csrf_token:
            return
        login_body = urllib.parse.urlencode({"password": self.token}).encode("utf-8")
        login_request = urllib.request.Request(
            f"{self.base_url}/ui/login",
            data=login_body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            self.opener.open(login_request, timeout=30).read()
            csrf_request = urllib.request.Request(f"{self.base_url}/v1/auth/csrf", method="GET")
            with self.opener.open(csrf_request, timeout=30) as response:
                csrf_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Registry UI login failed with HTTP {exc.code}: {detail}") from exc
        token = str(csrf_payload.get("csrf_token") or csrf_payload.get("token") or "").strip()
        if not token:
            raise RuntimeError("Registry UI login did not return a CSRF token")
        self.csrf_token = token


def build_demo_workspace(workspace: Path) -> dict[str, Any]:
    data_dir = workspace / "data"
    protocol_dir = workspace / "protocol"
    scripts_dir = workspace / "scripts"
    reports_dir = workspace / "reports"
    for directory in (data_dir, protocol_dir, scripts_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    counts = generate_sample_data(data_dir)
    shutil.copy2(SCRIPT_DIR / "profile_manufacturing_data.py", scripts_dir / "profile_manufacturing_data.py")
    shutil.copy2(SCRIPT_DIR / "analyze_manufacturing_quality.py", scripts_dir / "analyze_manufacturing_quality.py")

    profile_data(data_dir, reports_dir)
    findings = analyze_data(data_dir, reports_dir)
    shutil.copy2(reports_dir / "input_contract.json", protocol_dir / "input_contract.json")

    manifest = {
        "demo": "manufacturing-local-analytics",
        "workspace": str(workspace.resolve()),
        "generated_input_rows": counts,
        "artifacts": {key: value for key, value in ARTIFACT_PATHS.items()},
        "known_findings": {
            "vendor_v2_elevated_risk": True,
            "high_lamination_temperature_signal": True,
            "night_shift_missing_final_tests": True,
        },
        "observed_findings": findings,
        "privacy_checks": _privacy_checks(workspace),
        "registry": {},
    }
    _validate_manifest(manifest)
    (reports_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def run_registry_rehearsal(
    *,
    workspace: Path,
    manifest: dict[str, Any],
    registry_url: str,
    registry_token: str,
) -> dict[str, Any]:
    client = RegistryClient(registry_url, registry_token)
    draft = client.request(
        "POST",
        "/v1/protocol-drafts",
        {
            "source_kind": "template",
            "template_slug": TEMPLATE_SLUG,
            "display_name": "Manufacturing Local Analytics Demo",
            "description": "Customer-safe local analytics demo using synthetic manufacturing CSVs.",
        },
    )
    protocol_id = str((draft.get("protocol") or {}).get("protocol_id") or "")
    if not protocol_id:
        raise RuntimeError("Protocol draft creation did not return protocol.protocol_id")
    client.request("POST", f"/v1/protocols/{protocol_id}/publish", {})
    created_run = client.request(
        "POST",
        "/v1/protocol-runs",
        {
            "protocol_id": protocol_id,
            "is_rehearsal": True,
            "entry_authority_ref": "rehearsal",
            "origin_channel": "registry",
            "workspace_ref": workspace.name,
            "problem_statement": (
                "Build a repeatable local analytics workflow for linked manufacturing CSVs without "
                "sending raw rows to the model provider."
            ),
            "constraints_json": {
                "raw_data_boundary": "local_workspace_only",
                "model_visible_context": "schemas_counts_relationships_aggregates",
            },
        },
    )
    run_id = str((created_run.get("run") or {}).get("protocol_run_id") or "")
    if not run_id:
        raise RuntimeError("Protocol run creation did not return run.protocol_run_id")
    manifest["registry"] = {
        "registry_url": registry_url,
        "protocol_id": protocol_id,
        "protocol_run_id": run_id,
        "run_status": "rehearsal_running",
    }
    (workspace / ARTIFACT_PATHS["run_manifest"]).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    for expected_stage in STAGE_OUTPUTS.keys():
        session = _wait_for_stage_session(client, run_id, expected_stage)
        decision = "accept" if expected_stage == "review_report" else "completed"
        client.request(
            "POST",
            f"/v1/protocol-runs/{run_id}/rehearsal/respond",
            {
                "routed_task_id": session["routed_task_id"],
                "response_text": STAGE_RESPONSES[expected_stage],
                "decision": decision,
                "decision_summary": STAGE_RESPONSES[expected_stage],
                "artifact_contents": _artifact_contents(workspace, STAGE_OUTPUTS[expected_stage]),
            },
        )

    detail = _wait_for_run_status(client, run_id, "completed")
    manifest["registry"]["run_status"] = str((detail.get("run") or {}).get("status") or "")
    (workspace / ARTIFACT_PATHS["run_manifest"]).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest["registry"]


def _wait_for_stage_session(client: RegistryClient, run_id: str, stage_key: str) -> dict[str, Any]:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        payload = client.request("GET", f"/v1/protocol-runs/{run_id}/rehearsal/sessions")
        sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
        for session in sessions:
            if isinstance(session, dict) and str(session.get("stage_key") or "") == stage_key:
                if str(session.get("routed_task_id") or ""):
                    return session
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for rehearsal stage {stage_key}")


def _wait_for_run_status(client: RegistryClient, run_id: str, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        detail = client.request("GET", f"/v1/protocol-runs/{run_id}")
        run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
        current = str(run.get("status") or "")
        if current == status:
            return detail
        if current in {"failed", "blocked", "cancelled"}:
            raise RuntimeError(f"Run ended with {current}: {json.dumps(run, sort_keys=True)}")
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for run {run_id} to become {status}")


def _artifact_contents(workspace: Path, keys: list[str]) -> list[dict[str, str]]:
    contents = []
    for key in keys:
        relative_path = ARTIFACT_PATHS[key]
        content = (workspace / relative_path).read_text(encoding="utf-8")
        contents.append(
            {
                "artifact_key": key,
                "artifact_kind": "workspace_file",
                "path": relative_path,
                "content": content,
            }
        )
    return contents


def _privacy_checks(workspace: Path) -> dict[str, bool]:
    raw_tokens = ("PANEL-", "CELL-", "BATCH-")
    model_visible = (workspace / ARTIFACT_PATHS["model_visible_context"]).read_text(encoding="utf-8")
    profile_summary = (workspace / ARTIFACT_PATHS["profile_summary"]).read_text(encoding="utf-8")
    return {
        "model_visible_context_excludes_raw_ids": not any(token in model_visible for token in raw_tokens),
        "profile_summary_excludes_raw_ids": not any(token in profile_summary for token in raw_tokens),
        "findings_report_can_include_selected_output_ids": "PANEL-" in (workspace / ARTIFACT_PATHS["findings_report"]).read_text(encoding="utf-8"),
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    checks = manifest.get("privacy_checks")
    if not isinstance(checks, dict) or not all(bool(value) for value in checks.values()):
        raise RuntimeError(f"Privacy checks failed: {checks}")
    findings = manifest.get("observed_findings")
    if not isinstance(findings, dict):
        raise RuntimeError("Observed findings missing from manifest")
    if int(findings.get("high_risk_panel_count") or 0) < 10:
        raise RuntimeError("Expected at least 10 high-risk panels in the deterministic fixture")
    vendor_summary = findings.get("vendor_summary")
    if not isinstance(vendor_summary, dict) or "V2" not in vendor_summary:
        raise RuntimeError("Expected V2 vendor summary in deterministic fixture")
    if float(vendor_summary["V2"].get("high_risk_rate") or 0.0) <= 0.5:
        raise RuntimeError("Expected V2 high-risk rate above 0.5")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--registry-url", default=os.environ.get("OCTOPUS_REGISTRY_URL", ""))
    parser.add_argument("--registry-token", default=os.environ.get("REGISTRY_UI_TOKEN", ""))
    parser.add_argument("--require-registry", action="store_true", help="Fail if the registry rehearsal cannot be created.")
    args = parser.parse_args()

    workspace = args.workspace
    manifest = build_demo_workspace(workspace)
    registry_result: dict[str, Any] = {}
    if args.registry_url and args.registry_token:
        registry_result = run_registry_rehearsal(
            workspace=workspace,
            manifest=manifest,
            registry_url=str(args.registry_url),
            registry_token=str(args.registry_token),
        )
    elif args.require_registry:
        raise RuntimeError("Registry URL and REGISTRY_UI_TOKEN are required when --require-registry is set")

    print(json.dumps(
        {
            "ok": True,
            "workspace": str(workspace.resolve()),
            "manifest": str((workspace / ARTIFACT_PATHS["run_manifest"]).resolve()),
            "registry": registry_result,
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
