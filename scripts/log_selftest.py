#!/usr/bin/env python3
"""Self-test for the .log reader using realistic synthetic logs.

Same caveat as raw_selftest.py: these fixtures reproduce the log shapes
LTspice is documented and observed to emit, so passing proves the reader
handles those shapes -- not that the shapes are exhaustive. A real .log from
a simulation run is still wanted to confirm coverage.

The case that matters most is the standard single-run .meas line, where the
value follows "=" rather than the colon. A reader that misses it returns an
empty measurement list for a healthy log, which looks like "no measurements
were requested" instead of "the parser failed".

Usage:
    python scripts/log_selftest.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ltspice_log  # noqa: E402

FAILURES: List[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{label}: {detail}")


def close(a: Optional[float], b: float, tol: float = 1e-9) -> bool:
    if a is None:
        return False
    return abs(float(a) - b) <= tol * max(1.0, abs(b))


def write_log(directory: str, name: str, text: str, encoding: str = "utf-8") -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(text.encode(encoding))
    return path


def by_name(parsed: Dict[str, object], name: str) -> Optional[dict]:
    for entry in parsed["measurements"]:  # type: ignore[index]
        if entry["name"].lower() == name.lower():
            return entry
    return None


SINGLE_RUN = """Circuit: * rc_lowpass.asc

Direct Newton iteration for .op point succeeded.

vpp: MAX(v(out))-MIN(v(out))=2.5 FROM 0 TO 0.001
vmid: v(out)=2.49999 at 0.0005
tr: trig=1.4999 at 1.0055e-05
\ttarg=3.4999 at 2.7069e-05
\ttr=1.7014e-05

Total elapsed time: 0.043 seconds.
"""

OP_POINT = """Circuit: * divider.asc

       --- Operating Point ---

V(out):\t2.5\tvoltage
V(in):\t5\tvoltage
I(R1):\t0.0025\tdevice_current

Total elapsed time: 0.012 seconds.
"""

STEPPED = """Circuit: * rc_lowpass.asc

.step r=1000
.step r=2000

Measurement: vpp
  step\tMAX(v(out))-MIN(v(out))\tvpp
     1\t2.5\t2.5
     2\t1.25\t1.25

Total elapsed time: 0.128 seconds.
"""

FAILING = """Circuit: * boost.asc

WARNING: Less than two connections to node N002.
Fatal error: Time step too small; trouble with node N003.
Analysis aborted.
"""


def run() -> None:
    directory = tempfile.mkdtemp(prefix="ltspice_log_selftest_")

    # 1. Standard single-run .meas lines.
    parsed = ltspice_log.parse_log(write_log(directory, "single.log", SINGLE_RUN))
    vpp = by_name(parsed, "vpp")
    check("single/vpp_found", vpp is not None, "measurement missing entirely")
    if vpp:
        check("single/vpp_value", close(vpp["value"], 2.5), str(vpp["value"]))
        check(
            "single/vpp_expr",
            vpp["expression"] == "MAX(v(out))-MIN(v(out))",
            str(vpp["expression"]),
        )
        check("single/vpp_from", close(vpp["from"], 0.0), str(vpp["from"]))
        check("single/vpp_to", close(vpp["to"], 0.001), str(vpp["to"]))

    vmid = by_name(parsed, "vmid")
    check("single/vmid_found", vmid is not None)
    if vmid:
        check("single/vmid_value", close(vmid["value"], 2.49999), str(vmid["value"]))
        check("single/vmid_at", close(vmid["at"], 0.0005), str(vmid["at"]))

    # 2. Multi-line trig/targ measure: final value comes from the last line.
    tr = by_name(parsed, "tr")
    check("single/tr_found", tr is not None)
    if tr:
        check("single/tr_value", close(tr["value"], 1.7014e-05), str(tr["value"]))
        parts = tr.get("parts") or {}
        check("single/tr_trig", close(parts.get("trig"), 1.4999), str(parts))
        check("single/tr_targ", close(parts.get("targ"), 3.4999), str(parts))

    check("single/elapsed", close(parsed["elapsed_seconds"], 0.043), str(parsed["elapsed_seconds"]))
    check("single/no_errors", parsed["errors"] == [], str(parsed["errors"]))

    # 3. Operating point block.
    parsed = ltspice_log.parse_log(write_log(directory, "op.log", OP_POINT))
    op = parsed["operating_point"]
    check("op/count", len(op) == 3, str(sorted(op)))
    check("op/vout", close(op.get("V(out)", {}).get("value"), 2.5), str(op.get("V(out)")))
    check("op/vout_type", op.get("V(out)", {}).get("type") == "voltage", str(op.get("V(out)")))
    check("op/current", close(op.get("I(R1)", {}).get("value"), 0.0025), str(op.get("I(R1)")))

    # 4. Stepped measurement table.
    parsed = ltspice_log.parse_log(write_log(directory, "stepped.log", STEPPED))
    check("stepped/directives", len(parsed["step_directives"]) == 2, str(parsed["step_directives"]))
    tables = parsed["stepped_measurements"]
    check("stepped/tables", len(tables) == 1, str(len(tables)))
    if tables:
        rows = tables[0]["rows"]
        check("stepped/rows", len(rows) == 2, str(len(rows)))
        if len(rows) == 2:
            check("stepped/step1", rows[0]["step"] == 1, str(rows[0]))
            check("stepped/value1", close(rows[0]["value"], 2.5), str(rows[0]))
            check("stepped/value2", close(rows[1]["value"], 1.25), str(rows[1]))
    check(
        "stepped/flattened",
        len([m for m in parsed["measurements"] if m["name"] == "vpp"]) == 2,
        str(parsed["measurement_count"]),
    )

    # 5. A failed run must surface as an error, not silence.
    parsed = ltspice_log.parse_log(write_log(directory, "fail.log", FAILING))
    check("fail/errors", len(parsed["errors"]) >= 2, str(parsed["errors"]))
    check("fail/warnings", len(parsed["warnings"]) == 1, str(parsed["warnings"]))
    check(
        "fail/mentions_timestep",
        any("Time step too small" in e for e in parsed["errors"]),
        str(parsed["errors"]),
    )

    # 6. UTF-16LE logs must decode (LTspice writes these on some systems).
    parsed = ltspice_log.parse_log(
        write_log(directory, "utf16.log", SINGLE_RUN, encoding="utf-16-le")
    )
    vpp = by_name(parsed, "vpp")
    check("utf16/vpp_value", vpp is not None and close(vpp["value"], 2.5), str(vpp))

    real_file_checks()

    print(f"log self-test: {CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print("  FAIL", failure)
    print(
        "\nNOTE: most fixtures above are spec-derived. The real_file/* checks run "
        "against a real LTspice 17.2.4 log (examples/skill_samples/"
        "real_transient_offset.log). That log contains no .meas statements, so the "
        "measurement, stepped-table and operating-point paths are still validated "
        "only against spec-derived fixtures."
    )
    if FAILURES:
        sys.exit(1)


def real_file_checks() -> None:
    """Ground truth: a real transient log from LTspice 17.2.4 for MacOS.

    Only the author's file path was scrubbed; every other byte is LTspice's own.
    This is what the diagnostic paths look like in practice -- note that LTspice
    mixes "Warning:" and "WARNING:" casing in the same file, and that several
    warning lines are shaped exactly like `key: value` settings, which is the
    trap that briefly put them in the settings dict.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(
        os.path.dirname(here), "examples", "skill_samples", "real_transient_offset.log"
    )
    if not os.path.exists(path):
        check("real_file/present", False, f"missing fixture {path}")
        return

    parsed = ltspice_log.parse_log(path)

    # UTF-16LE with no BOM -- a plain text open() mangles or rejects this.
    check("real_file/encoding", parsed["encoding"] == "utf-16le", str(parsed["encoding"]))
    check(
        "real_file/version",
        parsed["ltspice_version"] == "LTspice 17.2.4 for MacOS",
        str(parsed["ltspice_version"]),
    )

    # Settings that change how results must be interpreted.
    settings = parsed["settings"]
    check("real_file/temp", settings.get("temp") == "27", str(settings))
    check("real_file/method", settings.get("method") == "modified trap", str(settings))
    check("real_file/solver", settings.get("solver") == "Normal", str(settings))
    # Diagnostics must not be filed as settings.
    check(
        "real_file/no_warning_in_settings",
        not any(k.lower().startswith("warning") for k in settings),
        str(list(settings)),
    )

    # Eight diagnostics, in both casings, and none misread as a hard error.
    check("real_file/warning_count", len(parsed["warnings"]) == 8, str(len(parsed["warnings"])))
    joined = " ".join(parsed["warnings"])
    check("real_file/lowercase_warning", "Multiple definitions of model" in joined, joined[:80])
    check("real_file/uppercase_warning", "is floating" in joined, joined[:80])
    check("real_file/no_false_errors", parsed["errors"] == [], str(parsed["errors"]))

    check(
        "real_file/op_succeeded_note",
        any("Newton iteration" in note for note in parsed["solver_notes"]),
        str(parsed["solver_notes"]),
    )
    check(
        "real_file/elapsed",
        isinstance(parsed["elapsed_seconds"], float) and parsed["elapsed_seconds"] > 0,
        str(parsed["elapsed_seconds"]),
    )
    # No .meas in this run: the count must be honestly zero, not a stray parse.
    check("real_file/no_measurements", parsed["measurement_count"] == 0, str(parsed["measurements"]))


if __name__ == "__main__":
    run()
