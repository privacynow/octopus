#!/usr/bin/env python3
"""Generate deterministic manufacturing CSV fixtures for the local analytics demo."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate_sample_data(data_dir: Path) -> dict[str, int]:
    """Create linked CSVs with known, testable quality signals."""

    data_dir.mkdir(parents=True, exist_ok=True)
    panels: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    panel_cells: list[dict[str, object]] = []
    test_results: list[dict[str, object]] = []

    vendors = ["V1", "V2", "V3"]
    lines = ["L1", "L2", "L3"]
    stages = ["incoming", "assembly", "final"]

    for panel_index in range(1, 49):
        panel_id = f"PANEL-{panel_index:03d}"
        shift = "night" if panel_index % 3 == 0 else "day"
        line = lines[(panel_index - 1) % len(lines)]
        temp = 147.5 + ((panel_index % 8) * 0.9)
        if 17 <= panel_index <= 28:
            temp += 2.4
        panels.append(
            {
                "panel_id": panel_id,
                "assembly_line": line,
                "shift": shift,
                "build_date": f"2026-04-{(panel_index % 20) + 1:02d}",
                "lamination_temp_c": f"{temp:.1f}",
            }
        )

        dominant_vendor = "V2" if 13 <= panel_index <= 30 else vendors[(panel_index - 1) % len(vendors)]
        for position in range(1, 13):
            cell_id = f"CELL-{panel_index:03d}-{position:02d}"
            vendor = dominant_vendor if position <= 8 else vendors[(panel_index + position) % len(vendors)]
            resistance = 22.5 + ((panel_index + position) % 9) * 0.42
            if vendor == "V2":
                resistance += 1.1
            cells.append(
                {
                    "cell_id": cell_id,
                    "batch_id": f"BATCH-{((panel_index - 1) // 4) + 1:02d}",
                    "vendor": vendor,
                    "incoming_grade": "B" if resistance > 26.0 else "A",
                    "formation_resistance_mohm": f"{resistance:.2f}",
                }
            )
            panel_cells.append(
                {
                    "panel_id": panel_id,
                    "cell_id": cell_id,
                    "cell_position": position,
                }
            )

        for stage in stages:
            if stage == "final" and shift == "night" and panel_index % 6 == 0:
                continue
            hotspot = 4.0 + (panel_index % 7) * 0.7
            visual_defects = 0
            if dominant_vendor == "V2":
                hotspot += 3.2
                visual_defects += 1
            if temp >= 151.0:
                hotspot += 2.7
                visual_defects += 1
            if shift == "night":
                visual_defects += 1 if panel_index % 9 == 0 else 0
            stage_multiplier = {"incoming": 0.35, "assembly": 0.7, "final": 1.0}[stage]
            test_results.append(
                {
                    "panel_id": panel_id,
                    "test_stage": stage,
                    "insulation_resistance_mohm": f"{960 + panel_index * 3 - visual_defects * 11:.1f}",
                    "hotspot_delta_c": f"{hotspot * stage_multiplier:.2f}",
                    "visual_defects": visual_defects if stage == "final" else max(0, visual_defects - 1),
                    "passed": "false" if stage == "final" and (visual_defects >= 2 or hotspot >= 10.5) else "true",
                }
            )

    _write_csv(data_dir / "panels.csv", panels)
    _write_csv(data_dir / "cells.csv", cells)
    _write_csv(data_dir / "panel_cells.csv", panel_cells)
    _write_csv(data_dir / "test_results.csv", test_results)

    return {
        "panels": len(panels),
        "cells": len(cells),
        "panel_cells": len(panel_cells),
        "test_results": len(test_results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="Directory where CSV fixtures should be written.")
    args = parser.parse_args()
    counts = generate_sample_data(args.data_dir)
    for name, count in counts.items():
        print(f"{name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
