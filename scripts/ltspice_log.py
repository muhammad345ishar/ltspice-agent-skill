"""Parse LTspice .log files for measurements, steps, and diagnostics.

The formats LTspice actually emits, which drive the patterns below:

Single-run ``.meas`` result -- the value follows ``=``, not the colon::

    vpp: MAX(v(out))-MIN(v(out))=2.5 FROM 0 TO 0.001
    vout: v(out)=2.49999 at 0.0005

Multi-line ``.meas`` (trig/targ), where the final line repeats the name::

    tr: trig=1.4999 at 1.0055e-05
        targ=3.4999 at 2.7069e-05
        tr=1.7014e-05

Stepped run -- one table per measurement, one row per step::

    Measurement: tr
      step    trig         targ         tr
         1    1.0055e-05   2.7069e-05   1.7014e-05

Operating point, tab separated::

           --- Operating Point ---
    V(out):  2.5   voltage

A parser that only matches ``name: <number>`` finds none of these and
returns an empty measurement list for a healthy log, so each shape is
handled explicitly.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Dict, List, Optional

try:
    from .ltspice_common import read_ltspice_text
except ImportError:
    from ltspice_common import read_ltspice_text


NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

# name: <expression>=<value> [FROM a TO b] | [AT t]
MEASURE_EXPR = re.compile(
    rf"^(?P<name>[A-Za-z_][\w.]*)\s*:\s*(?P<expr>.*?)=\s*(?P<value>{NUMBER})"
    rf"(?:\s+FROM\s+(?P<from>{NUMBER})\s+TO\s+(?P<to>{NUMBER}))?"
    rf"(?:\s+AT\s+(?P<at>{NUMBER}))?\s*$",
    re.IGNORECASE,
)
# name: <value>   (plain form, optionally followed by a type word)
MEASURE_PLAIN = re.compile(
    rf"^(?P<name>[A-Za-z_][\w.()\[\]]*)\s*:\s*(?P<value>{NUMBER})\s*(?P<unit>[A-Za-z_]\w*)?\s*$"
)
# continuation line inside a multi-line measure: key=value [at t]
CONTINUATION = re.compile(
    rf"^(?P<key>[A-Za-z_][\w.]*)\s*=\s*(?P<value>{NUMBER})"
    rf"(?:\s+AT\s+(?P<at>{NUMBER}))?\s*$",
    re.IGNORECASE,
)
MEASUREMENT_HEADER = re.compile(r"^Measurement:\s*(?P<name>\S+)\s*$", re.IGNORECASE)
STEP_DIRECTIVE = re.compile(r"^\.step\b(?P<body>.*)$", re.IGNORECASE)
STEP_ROW = re.compile(r"^(?P<step>\d+)\s+(?P<rest>.+)$")
OP_HEADER = re.compile(r"^-+\s*Operating Point\s*-+$", re.IGNORECASE)
ELAPSED = re.compile(rf"Total elapsed time:\s*(?P<seconds>{NUMBER})", re.IGNORECASE)
ERROR_PATTERN = re.compile(r"\b(error|fatal|aborted|failed to converge)\b", re.IGNORECASE)
WARNING_PATTERN = re.compile(r"\bwarning\b", re.IGNORECASE)
THD = re.compile(rf"Total Harmonic Distortion:\s*(?P<value>{NUMBER})", re.IGNORECASE)
# Run-context lines, all observed in a real LTspice 17.2.4 log:
#   "LTspice 17.2.4 for MacOS"
#   "Circuit: * /path/to/circuit.asc"
#   "solver = Normal" / "tnom = 27" / "method = modified trap"
#   "Maximum thread count: 12"
VERSION_BANNER = re.compile(r"^LTspice\s+\S+.*$", re.IGNORECASE)
CIRCUIT_LINE = re.compile(r"^Circuit:\s*(?P<value>.+)$", re.IGNORECASE)
SETTING = re.compile(r"^(?P<key>[A-Za-z][\w .]*?)\s*[=:]\s*(?P<value>.+?)\s*$")
# Lines that look like settings but are handled elsewhere or are not settings.
_SETTING_SKIP = {
    "circuit",
    "title",
    "date",
    "start time",
    "total elapsed time",
    "measurement",
    "total harmonic distortion",
}


def _to_float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_log(path: str) -> Dict[str, object]:
    buffer = read_ltspice_text(path)
    lines = buffer.lines

    measurements: List[dict] = []
    stepped: List[dict] = []
    step_directives: List[str] = []
    step_rows: List[str] = []
    op_point: Dict[str, dict] = {}
    op_point_lines: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    notes: List[str] = []
    elapsed: Optional[float] = None
    thd: Optional[float] = None
    version: Optional[str] = None
    circuit: Optional[str] = None
    settings: Dict[str, str] = {}

    in_op = False
    # State for a "Measurement: name" table.
    table_name: Optional[str] = None
    table_columns: List[str] = []
    table_rows: List[dict] = []
    # Name of the measure whose continuation lines we may be reading.
    pending_measure: Optional[str] = None
    pending_parts: Dict[str, object] = {}

    def flush_table() -> None:
        nonlocal table_name, table_columns, table_rows
        if table_name is not None and table_rows:
            stepped.append(
                {"name": table_name, "columns": table_columns, "rows": table_rows}
            )
            for row in table_rows:
                measurements.append(
                    {
                        "name": table_name,
                        "value": row.get("value"),
                        "step": row.get("step"),
                        "expression": None,
                        "raw": row.get("raw", ""),
                    }
                )
        table_name = None
        table_columns = []
        table_rows = []

    def flush_pending() -> None:
        nonlocal pending_measure, pending_parts
        if pending_measure is not None and pending_parts:
            for entry in measurements:
                if entry["name"] == pending_measure and entry.get("parts") is None:
                    entry["parts"] = dict(pending_parts)
                    break
        pending_measure = None
        pending_parts = {}

    for line in lines:
        stripped = line.strip()
        indented = bool(line[:1] in ("\t", " ")) and bool(stripped)

        if not stripped:
            # A blank line follows the "--- Operating Point ---" header in real
            # logs, so it must not end the block; only a non-matching line does.
            flush_table()
            flush_pending()
            continue

        if OP_HEADER.match(stripped):
            in_op = True
            flush_table()
            flush_pending()
            continue

        match = ELAPSED.search(stripped)
        if match:
            elapsed = _to_float(match.group("seconds"))
        match = THD.search(stripped)
        if match:
            thd = _to_float(match.group("value"))

        # Run context. Real logs open with a version banner and a block of
        # `key = value` / `key: value` settings. `temp` and `method` in
        # particular change how results should be read (a run at temp = 27 is
        # not comparable to one at 85), so capture them rather than discarding.
        match = VERSION_BANNER.match(stripped)
        if match and version is None:
            version = stripped
        match = CIRCUIT_LINE.match(stripped)
        if match:
            circuit = match.group("value").strip()
        if not in_op and table_name is None:
            match = SETTING.match(stripped)
            if (
                match
                and not WARNING_PATTERN.search(stripped)
                and not ERROR_PATTERN.search(stripped)
            ):
                key = match.group("key").strip()
                if key.lower() not in _SETTING_SKIP:
                    settings[key] = match.group("value").strip()

        if ERROR_PATTERN.search(stripped):
            errors.append(stripped)
        elif WARNING_PATTERN.search(stripped):
            warnings.append(stripped)

        # Operating-point block: "V(out):<tab>2.5<tab>voltage"
        if in_op:
            plain = MEASURE_PLAIN.match(stripped)
            if plain:
                op_point_lines.append(stripped)
                op_point[plain.group("name")] = {
                    "value": _to_float(plain.group("value")),
                    "type": plain.group("unit"),
                }
                continue
            # First line that is not an op-point entry closes the block; fall
            # through so it still gets its normal handling.
            in_op = False

        header = MEASUREMENT_HEADER.match(stripped)
        if header:
            flush_table()
            flush_pending()
            table_name = header.group("name")
            table_columns = []
            table_rows = []
            continue

        if table_name is not None:
            row = STEP_ROW.match(stripped)
            if row:
                tokens = row.group("rest").split()
                values = [_to_float(token) for token in tokens]
                record: Dict[str, object] = {
                    "step": int(row.group("step")),
                    "raw": stripped,
                }
                if table_columns:
                    # Skip the leading "step" label when zipping columns.
                    names = [c for c in table_columns if c.lower() != "step"]
                    for name, value in zip(names, values):
                        record[name] = value
                    # The column named after the measure holds its result.
                    if table_name in record:
                        record["value"] = record[table_name]
                if "value" not in record:
                    record["value"] = values[-1] if values else None
                table_rows.append(record)
                step_rows.append(stripped)
                continue
            if not table_columns and stripped.lower().startswith("step"):
                table_columns = stripped.split()
                continue

        directive = STEP_DIRECTIVE.match(stripped)
        if directive:
            step_directives.append(directive.group("body").strip())
            continue

        expr = MEASURE_EXPR.match(stripped)
        if expr and not indented:
            flush_pending()
            measurements.append(
                {
                    "name": expr.group("name"),
                    "value": _to_float(expr.group("value")),
                    "expression": expr.group("expr").strip() or None,
                    "from": _to_float(expr.group("from")),
                    "to": _to_float(expr.group("to")),
                    "at": _to_float(expr.group("at")),
                    "step": None,
                    "parts": None,
                    "raw": stripped,
                }
            )
            pending_measure = expr.group("name")
            pending_parts = {}
            # "tr: trig=1.5 at 1e-05" carries a part, not a final value.
            key = expr.group("expr").strip().lower()
            if key in ("trig", "targ"):
                pending_parts[key] = _to_float(expr.group("value"))
                measurements[-1]["value"] = None
            continue

        if pending_measure is not None and indented:
            cont = CONTINUATION.match(stripped)
            if cont:
                key = cont.group("key")
                value = _to_float(cont.group("value"))
                if key.lower() == pending_measure.lower():
                    for entry in reversed(measurements):
                        if entry["name"] == pending_measure:
                            entry["value"] = value
                            break
                else:
                    pending_parts[key] = value
                continue

        plain = MEASURE_PLAIN.match(stripped)
        if plain and not indented:
            flush_pending()
            measurements.append(
                {
                    "name": plain.group("name"),
                    "value": _to_float(plain.group("value")),
                    "expression": None,
                    "from": None,
                    "to": None,
                    "at": None,
                    "step": None,
                    "parts": None,
                    "unit": plain.group("unit"),
                    "raw": stripped,
                }
            )
            continue

        if "iteration" in stripped.lower() or "solver" in stripped.lower():
            notes.append(stripped)

    flush_table()
    flush_pending()

    return {
        "path": path,
        "encoding": buffer.encoding,
        "ltspice_version": version,
        "circuit": circuit,
        "settings": settings,
        "measurements": measurements,
        "measurement_count": len(measurements),
        "stepped_measurements": stepped,
        "step_directives": step_directives,
        # Retained for compatibility with earlier callers.
        "steps": step_directives,
        "step_rows": step_rows,
        "operating_point": op_point,
        "operating_point_lines": op_point_lines,
        "total_harmonic_distortion_percent": thd,
        "elapsed_seconds": elapsed,
        "solver_notes": notes,
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
