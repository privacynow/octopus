#!/usr/bin/env python3
"""Profile linked manufacturing CSVs without exposing raw rows to the model."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean


REQUIRED_FILES = {
    "panels": "panels.csv",
    "cells": "cells.csv",
    "panel_cells": "panel_cells.csv",
    "test_results": "test_results.csv",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _missing_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    if not rows:
        return {}
    counts = {column: 0 for column in rows[0].keys()}
    for row in rows:
        for column, value in row.items():
            if str(value or "").strip() == "":
                counts[column] += 1
    return counts


def _numeric_summary(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    if not rows:
        return {}
    summaries: dict[str, dict[str, float]] = {}
    for column in rows[0].keys():
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row.get(column, "")))
            except (TypeError, ValueError):
                continue
        if values and len(values) >= max(3, len(rows) // 3):
            summaries[column] = {
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "mean": round(mean(values), 3),
            }
    return summaries


def profile_data(data_dir: Path, output_dir: Path) -> dict[str, object]:
    tables = {name: _read_csv(data_dir / filename) for name, filename in REQUIRED_FILES.items()}
    output_dir.mkdir(parents=True, exist_ok=True)

    panel_ids = {row["panel_id"] for row in tables["panels"]}
    cell_ids = {row["cell_id"] for row in tables["cells"]}
    panel_cell_rows = tables["panel_cells"]
    test_rows = tables["test_results"]
    relationship_checks = {
        "panel_cells_missing_panel": sum(1 for row in panel_cell_rows if row.get("panel_id") not in panel_ids),
        "panel_cells_missing_cell": sum(1 for row in panel_cell_rows if row.get("cell_id") not in cell_ids),
        "tests_missing_panel": sum(1 for row in test_rows if row.get("panel_id") not in panel_ids),
    }

    stage_counts = Counter(row.get("test_stage", "") for row in test_rows)
    shift_counts = Counter(row.get("shift", "") for row in tables["panels"])
    vendor_counts = Counter(row.get("vendor", "") for row in tables["cells"])

    contract = {
        "data_dir": str(data_dir),
        "tables": {
            name: {
                "file": REQUIRED_FILES[name],
                "row_count": len(rows),
                "columns": list(rows[0].keys()) if rows else [],
                "missing_counts": _missing_counts(rows),
                "numeric_summary": _numeric_summary(rows),
            }
            for name, rows in tables.items()
        },
        "relationships": {
            "panels.panel_id": ["panel_cells.panel_id", "test_results.panel_id"],
            "cells.cell_id": ["panel_cells.cell_id"],
        },
        "relationship_checks": relationship_checks,
        "aggregates": {
            "test_stage_counts": dict(sorted(stage_counts.items())),
            "panel_shift_counts": dict(sorted(shift_counts.items())),
            "cell_vendor_counts": dict(sorted(vendor_counts.items())),
        },
        "privacy_boundary": {
            "raw_rows_in_profile": False,
            "model_visible": "schema, counts, relationship checks, and aggregates only",
        },
    }

    (output_dir / "input_contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "model_visible_context.md").write_text(_model_context_markdown(contract), encoding="utf-8")
    (output_dir / "profile_summary.md").write_text(_profile_markdown(contract), encoding="utf-8")
    return contract


def _profile_markdown(contract: dict[str, object]) -> str:
    lines = [
        "# Manufacturing Data Profile",
        "",
        "This profile is safe to share with an assistant because it contains schema, counts, and aggregates only.",
        "",
        "## Tables",
    ]
    tables = contract["tables"]
    assert isinstance(tables, dict)
    for name, info in tables.items():
        assert isinstance(info, dict)
        lines.extend(
            [
                f"### {name}",
                f"- File: `{info.get('file')}`",
                f"- Rows: {info.get('row_count')}",
                f"- Columns: {', '.join(str(item) for item in info.get('columns', []))}",
                f"- Missing values: {json.dumps(info.get('missing_counts', {}), sort_keys=True)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Relationship Checks",
            f"- Invalid panel references in panel_cells: {contract['relationship_checks']['panel_cells_missing_panel']}",
            f"- Invalid cell references in panel_cells: {contract['relationship_checks']['panel_cells_missing_cell']}",
            f"- Invalid panel references in test_results: {contract['relationship_checks']['tests_missing_panel']}",
            "",
            "## Aggregate Counts",
            f"- Test stages: {json.dumps(contract['aggregates']['test_stage_counts'], sort_keys=True)}",
            f"- Panel shifts: {json.dumps(contract['aggregates']['panel_shift_counts'], sort_keys=True)}",
            f"- Cell vendors: {json.dumps(contract['aggregates']['cell_vendor_counts'], sort_keys=True)}",
            "",
        ]
    )
    return "\n".join(lines)


def _model_context_markdown(contract: dict[str, object]) -> str:
    tables = contract["tables"]
    assert isinstance(tables, dict)
    lines = [
        "# Model-Visible Context",
        "",
        "Do not ask for raw CSV rows. Use this controlled profile to design scripts that run locally.",
        "",
    ]
    for name, info in tables.items():
        assert isinstance(info, dict)
        lines.append(f"- `{name}` has {info.get('row_count')} rows and columns: {', '.join(str(item) for item in info.get('columns', []))}.")
    lines.extend(
        [
            f"- Relationship check failures: {json.dumps(contract['relationship_checks'], sort_keys=True)}.",
            f"- Aggregate counts: {json.dumps(contract['aggregates'], sort_keys=True)}.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    contract = profile_data(args.data_dir, args.output_dir)
    print(json.dumps({"ok": True, "tables": list(contract["tables"].keys())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
