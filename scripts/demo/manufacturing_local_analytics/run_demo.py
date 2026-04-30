#!/usr/bin/env python3
"""Run the manufacturing local analytics demo end to end."""

from __future__ import annotations

import argparse
import json
import shutil
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
DEMO_KEY = "manufacturing-local-analytics"

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
        "demo": DEMO_KEY,
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
    args = parser.parse_args()

    workspace = args.workspace
    build_demo_workspace(workspace)

    print(json.dumps(
        {
            "ok": True,
            "workspace": str(workspace.resolve()),
            "manifest": str((workspace / ARTIFACT_PATHS["run_manifest"]).resolve()),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
