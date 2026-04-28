from __future__ import annotations

import json
from pathlib import Path

from scripts.demo.manufacturing_local_analytics.run_demo import (
    ARTIFACT_PATHS,
    TEMPLATE_SLUG,
    build_demo_workspace,
)


def test_manufacturing_local_analytics_demo_generates_expected_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    manifest = build_demo_workspace(workspace)

    assert manifest["demo"] == TEMPLATE_SLUG
    for relative_path in ARTIFACT_PATHS.values():
        assert (workspace / relative_path).is_file(), relative_path

    findings = json.loads((workspace / "reports" / "findings.json").read_text(encoding="utf-8"))
    assert findings["panel_count"] == 48
    assert findings["high_risk_panel_count"] >= 20
    assert findings["missing_final_tests"] == 8
    assert findings["vendor_summary"]["V2"]["high_risk_rate"] > findings["vendor_summary"]["V1"]["high_risk_rate"]


def test_manufacturing_demo_model_visible_context_excludes_raw_source_ids(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    build_demo_workspace(workspace)

    model_visible = (workspace / "reports" / "model_visible_context.md").read_text(encoding="utf-8")
    profile_summary = (workspace / "reports" / "profile_summary.md").read_text(encoding="utf-8")
    for raw_token in ("PANEL-", "CELL-", "BATCH-"):
        assert raw_token not in model_visible
        assert raw_token not in profile_summary

    findings_report = (workspace / "reports" / "manufacturing_findings.md").read_text(encoding="utf-8")
    assert "PANEL-" in findings_report
    assert "Vendor V2 has the highest high-risk rate" in findings_report


def test_manufacturing_demo_scripts_are_rerunnable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    first = build_demo_workspace(workspace)
    second = build_demo_workspace(workspace)

    assert first["observed_findings"]["high_risk_panel_count"] == second["observed_findings"]["high_risk_panel_count"]
    manifest = json.loads((workspace / "reports" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["privacy_checks"]["model_visible_context_excludes_raw_ids"] is True
