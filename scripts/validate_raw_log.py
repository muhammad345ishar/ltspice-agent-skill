"""Validate RAW parsing against a matching LTspice LOG."""

from __future__ import annotations

import argparse
import json

try:
    from .ltspice_log import parse_log
    from .ltspice_raw import parse_raw
except ImportError:
    from ltspice_log import parse_log
    from ltspice_raw import parse_raw


def validate(raw_path: str, log_path: str) -> dict:
    raw = parse_raw(raw_path)
    log = parse_log(log_path)

    errors = []
    if raw["points_parsed"] == 0:
        errors.append("RAW parser produced zero points.")
    if log["errors"]:
        errors.append("LOG contains simulation errors.")
    if not raw["variables"]:
        errors.append("RAW has no variable table.")

    measure_count = len(log["measurements"])
    note = (
        "Structural validation passed; numerical .measure-to-waveform equivalence "
        "depends on measure expression complexity."
    )
    if errors:
        note = "Validation failed."

    return {
        "raw_path": raw_path,
        "log_path": log_path,
        "raw_points_parsed": raw["points_parsed"],
        "raw_variables": len(raw["variables"]),
        "log_measurements": measure_count,
        "log_errors": log["errors"],
        "validated": not errors,
        "validation_note": note,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate RAW parser using matching LOG")
    parser.add_argument("raw")
    parser.add_argument("log")
    args = parser.parse_args()
    result = validate(args.raw, args.log)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["validated"] else 1)


if __name__ == "__main__":
    main()
