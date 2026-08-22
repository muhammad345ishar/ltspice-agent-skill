"""Parse LTspice .log files for measures, steps, and diagnostics."""

from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List

try:
    from .ltspice_common import read_ltspice_text
except ImportError:
    from ltspice_common import read_ltspice_text


MEASURE_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z_][\w.]*)\s*[:=]\s*(?P<value>[-+0-9.eE]+)(?:\s+from.*)?$"
)
STEP_PATTERN = re.compile(r"^\s*\.step\b(.*)$", re.IGNORECASE)
STEP_TABLE_PATTERN = re.compile(r"^\s*step\s+(.+)$", re.IGNORECASE)
ERROR_PATTERN = re.compile(r"\b(error|fatal)\b", re.IGNORECASE)
WARNING_PATTERN = re.compile(r"\bwarning\b", re.IGNORECASE)


def parse_log(path: str) -> Dict[str, object]:
    lines = read_ltspice_text(path).lines

    measures: List[dict] = []
    steps: List[str] = []
    step_rows: List[str] = []
    op_points: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []

    in_op = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_op:
                in_op = False
            continue

        measure_match = MEASURE_PATTERN.match(stripped)
        if measure_match:
            measures.append(
                {
                    "name": measure_match.group("name"),
                    "value": float(measure_match.group("value")),
                    "raw": stripped,
                }
            )

        step_match = STEP_PATTERN.match(stripped)
        if step_match:
            steps.append(step_match.group(1).strip())

        step_row_match = STEP_TABLE_PATTERN.match(stripped)
        if step_row_match:
            step_rows.append(step_row_match.group(1).strip())

        if stripped.startswith("--- Operating Point ---"):
            in_op = True
            continue
        if in_op:
            op_points.append(stripped)

        if ERROR_PATTERN.search(stripped):
            errors.append(stripped)
        elif WARNING_PATTERN.search(stripped):
            warnings.append(stripped)

    return {
        "path": path,
        "measurements": measures,
        "steps": steps,
        "step_rows": step_rows,
        "operating_point_lines": op_points,
        "warnings": warnings,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice log parser")
    parser.add_argument("path")
    args = parser.parse_args()
    print(json.dumps(parse_log(args.path), indent=2))


if __name__ == "__main__":
    main()
