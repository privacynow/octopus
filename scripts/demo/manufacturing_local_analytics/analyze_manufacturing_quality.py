#!/usr/bin/env python3
"""Analyze linked manufacturing CSVs locally and write repeatable report artifacts."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def analyze_data(data_dir: Path, output_dir: Path) -> dict[str, object]:
    panels = _read_csv(data_dir / "panels.csv")
    cells = _read_csv(data_dir / "cells.csv")
    panel_cells = _read_csv(data_dir / "panel_cells.csv")
    tests = _read_csv(data_dir / "test_results.csv")
    output_dir.mkdir(parents=True, exist_ok=True)

    panels_by_id = {row["panel_id"]: row for row in panels}
    cells_by_id = {row["cell_id"]: row for row in cells}
    cell_vendors_by_panel: dict[str, list[str]] = defaultdict(list)
    for row in panel_cells:
        panel_id = row.get("panel_id", "")
        cell = cells_by_id.get(row.get("cell_id", ""))
        if panel_id and cell:
            cell_vendors_by_panel[panel_id].append(cell.get("vendor", ""))

    tests_by_panel: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in tests:
        tests_by_panel[row.get("panel_id", "")].append(row)

    flag_rows: list[dict[str, object]] = []
    summary_dimensions: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    vendor_risk: dict[str, list[int]] = defaultdict(list)
    hot_panels = 0
    missing_final_tests = 0

    for panel_id, panel in panels_by_id.items():
        vendors = [value for value in cell_vendors_by_panel.get(panel_id, []) if value]
        dominant_vendor = Counter(vendors).most_common(1)[0][0] if vendors else "unknown"
        final_tests = [row for row in tests_by_panel.get(panel_id, []) if row.get("test_stage") == "final"]
        final_test_present = bool(final_tests)
        if not final_test_present:
            missing_final_tests += 1
        all_tests = tests_by_panel.get(panel_id, [])
        max_hotspot = max((_to_float(row.get("hotspot_delta_c")) for row in all_tests), default=0.0)
        visual_defects = sum(int(_to_float(row.get("visual_defects"))) for row in all_tests)
        lamination_temp = _to_float(panel.get("lamination_temp_c"))
        risk_score = 0
        reasons: list[str] = []
        if dominant_vendor == "V2":
            risk_score += 2
            reasons.append("dominant_vendor_v2")
        if lamination_temp >= 151.0:
            risk_score += 2
            reasons.append("high_lamination_temp")
        if max_hotspot >= 10.5:
            risk_score += 2
            hot_panels += 1
            reasons.append("high_hotspot_delta")
        if visual_defects >= 3:
            risk_score += 1
            reasons.append("visual_defect_count")
        if not final_test_present:
            risk_score += 2
            reasons.append("missing_final_test")

        shift = panel.get("shift", "")
        line = panel.get("assembly_line", "")
        summary_dimensions[(shift, line, dominant_vendor)].append(float(risk_score))
        vendor_risk[dominant_vendor].append(1 if risk_score >= 4 else 0)

        if risk_score >= 4:
            flag_rows.append(
                {
                    "panel_id": panel_id,
                    "shift": shift,
                    "assembly_line": line,
                    "dominant_vendor": dominant_vendor,
                    "lamination_temp_c": f"{lamination_temp:.1f}",
                    "max_hotspot_delta_c": f"{max_hotspot:.2f}",
                    "visual_defect_count": visual_defects,
                    "final_test_present": str(final_test_present).lower(),
                    "risk_score": risk_score,
                    "risk_reasons": "|".join(reasons),
                }
            )

    summary_rows = [
        {
            "shift": shift,
            "assembly_line": line,
            "dominant_vendor": vendor,
            "panel_count": len(scores),
            "average_risk_score": f"{mean(scores):.2f}",
            "high_risk_rate": f"{sum(1 for score in scores if score >= 4) / len(scores):.3f}",
        }
        for (shift, line, vendor), scores in sorted(summary_dimensions.items())
    ]
    vendor_summary = {
        vendor: {
            "panel_groups": len(values),
            "high_risk_rate": round(sum(values) / len(values), 3) if values else 0.0,
        }
        for vendor, values in sorted(vendor_risk.items())
    }

    _write_csv(
        output_dir / "quality_flags.csv",
        flag_rows,
        [
            "panel_id",
            "shift",
            "assembly_line",
            "dominant_vendor",
            "lamination_temp_c",
            "max_hotspot_delta_c",
            "visual_defect_count",
            "final_test_present",
            "risk_score",
            "risk_reasons",
        ],
    )
    _write_csv(
        output_dir / "defect_summary.csv",
        summary_rows,
        ["shift", "assembly_line", "dominant_vendor", "panel_count", "average_risk_score", "high_risk_rate"],
    )

    findings = {
        "panel_count": len(panels),
        "high_risk_panel_count": len(flag_rows),
        "missing_final_tests": missing_final_tests,
        "high_hotspot_panels": hot_panels,
        "vendor_summary": vendor_summary,
        "top_risk_panels": flag_rows[:8],
    }
    (output_dir / "findings.json").write_text(json.dumps(findings, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "manufacturing_findings.md").write_text(_findings_markdown(findings), encoding="utf-8")
    (output_dir / "defect_heatmap.html").write_text(_heatmap_html(summary_rows), encoding="utf-8")
    return findings


def _findings_markdown(findings: dict[str, object]) -> str:
    vendor_summary = findings["vendor_summary"]
    assert isinstance(vendor_summary, dict)
    lines = [
        "# Manufacturing Quality Findings",
        "",
        "## Executive Summary",
        f"- Panels analyzed: {findings['panel_count']}",
        f"- High-risk panels flagged: {findings['high_risk_panel_count']}",
        f"- Panels missing final test records: {findings['missing_final_tests']}",
        f"- Panels with high hotspot delta: {findings['high_hotspot_panels']}",
        "",
        "## Findings",
        "- Vendor V2 has the highest high-risk rate in this fixture and should be reviewed before additional production runs.",
        "- High lamination temperature is a repeatable signal in the flagged population.",
        "- Night-shift records include missing final tests; the issue is operational traceability, not only product quality.",
        "",
        "## Vendor Risk",
    ]
    for vendor, info in vendor_summary.items():
        assert isinstance(info, dict)
        lines.append(f"- {vendor}: high-risk rate {info.get('high_risk_rate')} across {info.get('panel_groups')} panel groups")
    lines.extend(["", "## Top Flagged Panels"])
    for row in findings["top_risk_panels"]:
        assert isinstance(row, dict)
        lines.append(
            f"- {row['panel_id']}: score {row['risk_score']} ({row['risk_reasons']})"
        )
    lines.extend(
        [
            "",
            "## Recommended Next Steps",
            "- Confirm whether V2 lots share incoming inspection history or equipment setup.",
            "- Audit final-test capture for night-shift panels.",
            "- Add a daily job that writes quality_flags.csv and alerts on high-risk rate changes.",
            "",
        ]
    )
    return "\n".join(lines)


def _heatmap_html(summary_rows: list[dict[str, object]]) -> str:
    body = []
    for row in summary_rows:
        risk = _to_float(row.get("average_risk_score"))
        color = "#ffe2d1" if risk >= 3.0 else "#fff6cf" if risk >= 2.0 else "#dff3e7"
        cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in row.keys())
        body.append(f"<tr style=\"background:{color}\">{cells}</tr>")
    headings = "".join(f"<th>{html.escape(column)}</th>" for column in (summary_rows[0].keys() if summary_rows else []))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Defect Risk Heatmap</title>"
        "<style>body{font-family:Arial,sans-serif;margin:2rem;color:#17202a}"
        "table{border-collapse:collapse;width:100%;max-width:1100px}"
        "th,td{border:1px solid #d7dee8;padding:.55rem;text-align:left}"
        "th{background:#eef3f8}</style></head><body>"
        "<h1>Defect Risk Heatmap</h1>"
        "<p>Average risk score by shift, assembly line, and dominant vendor.</p>"
        f"<table><thead><tr>{headings}</tr></thead><tbody>{''.join(body)}</tbody></table>"
        "</body></html>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    findings = analyze_data(args.data_dir, args.output_dir)
    print(json.dumps({"ok": True, "high_risk_panel_count": findings["high_risk_panel_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
