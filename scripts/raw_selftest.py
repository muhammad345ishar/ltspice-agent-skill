#!/usr/bin/env python3
"""Self-test for the .raw reader using synthetic fixtures.

IMPORTANT -- what this does and does not prove: these fixtures are built from
the documented .raw layout, so passing shows the reader is self-consistent
with the spec. It is NOT ground truth from LTspice. A file produced by a real
LTspice run is still required to confirm the spec itself. Until then, treat
.raw results as spec-validated, not hardware-validated.

Every sample is compared, not just the first row -- an earlier version of this
check only looked at row 0, where a transient's t=0 hides sign-bit bugs.

Usage:
    python scripts/raw_selftest.py
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ltspice_raw  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "examples", "skill_samples")

FAILURES: List[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{label}: {detail}")


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def header(plotname: str, flags: str, variables: Sequence[Sequence[str]], points: int) -> str:
    rows = "".join(
        f"\t{index}\t{name}\t{kind}\n" for index, (name, kind) in enumerate(variables)
    )
    return (
        "Title: * synthetic fixture\n"
        "Date: Sun Aug 23 00:00:00 2026\n"
        f"Plotname: {plotname}\n"
        f"Flags: {flags}\n"
        f"No. Variables: {len(variables)}\n"
        f"No. Points: {points}\n"
        "Offset: 0.0000000000000000e+000\n"
        "Command: Linear Technology Corporation LTspice\n"
        "Variables:\n" + rows
    )


def write_fixture(
    directory: str,
    name: str,
    head: str,
    payload: bytes,
    encoding: str = "ascii",
    marker: str = "Binary:\n",
) -> str:
    text = head + marker
    head_bytes = text.encode("utf-16-le") if encoding == "utf-16-le" else text.encode(encoding)
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(head_bytes + payload)
    return path


def pack_interleaved(rows: Sequence[Sequence[float]], x_size: int, var_size: int) -> bytes:
    out = b""
    for row in rows:
        for column, value in enumerate(row):
            size = x_size if column == 0 else var_size
            out += struct.pack("<d" if size == 8 else "<f", value)
    return out


def pack_fastaccess(rows: Sequence[Sequence[float]], x_size: int, var_size: int) -> bytes:
    out = b""
    for column in range(len(rows[0])):
        size = x_size if column == 0 else var_size
        for row in rows:
            out += struct.pack("<d" if size == 8 else "<f", row[column])
    return out


def compare_real(label: str, parsed: dict, expected: Sequence[Sequence[float]]) -> None:
    values = parsed["values"]
    check(f"{label}/points", len(values) == len(expected), f"{len(values)} != {len(expected)}")
    if len(values) != len(expected):
        return
    for row_index, (got_row, want_row) in enumerate(zip(values, expected)):
        check(
            f"{label}/row{row_index}/width",
            len(got_row) == len(want_row),
            f"{len(got_row)} != {len(want_row)}",
        )
        for column, (got, want) in enumerate(zip(got_row, want_row)):
            check(
                f"{label}/row{row_index}/col{column}",
                close(got, want),
                f"got {got!r} want {want!r}",
            )


TRANSIENT = [("time", "time"), ("V(out)", "voltage"), ("I(R1)", "device_current")]
AC_VARS = [("frequency", "frequency"), ("V(out)", "voltage"), ("I(R1)", "device_current")]
DC_VARS = [("v(vin)", "voltage"), ("V(out)", "voltage"), ("I(R1)", "device_current")]

# Chosen to be exactly representable as float32 so rounding cannot mask a bug.
POINTS = [
    [0.0, 1.5, 0.25],
    [1.0e-3, 2.5, 0.5],
    [2.0e-3, -3.25, 0.75],
]


def run() -> None:
    directory = tempfile.mkdtemp(prefix="ltspice_raw_selftest_")

    # 1. Interleaved real, ASCII header, float64 x + float32 variables.
    path = write_fixture(
        directory, "real_ascii.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        pack_interleaved(POINTS, 8, 4),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("real_ascii", parsed, POINTS)
    check(
        "real_ascii/layout",
        parsed["binary_layout"] == "float64_x_float32_vars",
        str(parsed["binary_layout"]),
    )

    # 2. Same payload, UTF-16LE header (LTspice XVII default).
    path = write_fixture(
        directory, "real_utf16.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        pack_interleaved(POINTS, 8, 4), encoding="utf-16-le",
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("real_utf16", parsed, POINTS)
    check("real_utf16/encoding", parsed["header_encoding"] == "utf-16le", parsed["header_encoding"])

    # 3. Sign bit set on every time value -- must come back positive.
    signed = [[-row[0] if row[0] else row[0], row[1], row[2]] for row in POINTS]
    path = write_fixture(
        directory, "real_signbit.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        pack_interleaved(signed, 8, 4),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("real_signbit", parsed, POINTS)

    # 4. A negative DC-sweep x-axis is real data and must survive untouched.
    dc = [[-5.0, 1.5, 0.25], [0.0, 2.5, 0.5], [5.0, -3.25, 0.75]]
    path = write_fixture(
        directory, "dc_negative_x.raw", header("DC transfer characteristic", "real", DC_VARS, 3),
        pack_interleaved(dc, 8, 4),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("dc_negative_x", parsed, dc)

    # 5. All-float64 payload: layout must be inferred from the byte count.
    path = write_fixture(
        directory, "real_all64.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        pack_interleaved(POINTS, 8, 8),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("real_all64", parsed, POINTS)
    check("real_all64/layout", parsed["binary_layout"] == "float64_all", str(parsed["binary_layout"]))

    # 6. fastaccess (transposed) must yield the same numbers as interleaved.
    path = write_fixture(
        directory, "real_fastaccess.raw",
        header("Transient Analysis", "real fastaccess", TRANSIENT, 3),
        pack_fastaccess(POINTS, 8, 4),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("fastaccess", parsed, POINTS)
    check("fastaccess/flag", parsed["fastaccess"] is True, str(parsed["fastaccess"]))

    # 7. Complex (AC): imaginary parts must be preserved, not dropped.
    ac_rows = [
        [1.0e3, 0.0, 0.5, -0.25, 0.1, 0.2],
        [1.0e4, 0.0, 0.05, -0.5, 0.01, 0.02],
    ]
    payload = b"".join(struct.pack("<dddddd", *row) for row in ac_rows)
    path = write_fixture(
        directory, "complex.raw", header("AC Analysis", "complex", AC_VARS, 2), payload,
    )
    parsed = ltspice_raw.parse_raw(path)
    check("complex/flag", parsed["complex"] is True, str(parsed["complex"]))
    check("complex/points", parsed["points_parsed"] == 2, str(parsed["points_parsed"]))
    first = parsed["values"][0]
    check("complex/freq", close(ltspice_raw._x_scalar(first[0]), 1.0e3), str(first[0]))
    check("complex/re", close(first[1][0], 0.5), str(first[1]))
    check("complex/im", close(first[1][1], -0.25), str(first[1]))
    magnitude, decibels, degrees = ltspice_raw.magnitude_phase(first[1])
    check("complex/mag", close(magnitude, 0.5590169943749475), str(magnitude))
    check("complex/deg", close(degrees, -26.56505117707799), str(degrees))
    check("complex/db", close(decibels, -5.0514997831990675), str(decibels))

    # 8. ASCII Values: payload -- continuation lines carry one token each.
    lines = []
    for index, row in enumerate(POINTS):
        lines.append(f"{index}\t{row[0]:.15e}\n")
        for value in row[1:]:
            lines.append(f"\t{value:.15e}\n")
    path = write_fixture(
        directory, "ascii_values.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        "".join(lines).encode(), marker="Values:\n",
    )
    parsed = ltspice_raw.parse_raw(path)
    check("ascii_values/mode", parsed["mode"] == "values", str(parsed["mode"]))
    compare_real("ascii_values", parsed, POINTS)

    # 9. ASCII complex values are written "real,imag".
    ac_lines = []
    for index, row in enumerate(ac_rows):
        ac_lines.append(f"{index}\t{row[0]:.15e},{row[1]:.15e}\n")
        for pair in ((row[2], row[3]), (row[4], row[5])):
            ac_lines.append(f"\t{pair[0]:.15e},{pair[1]:.15e}\n")
    path = write_fixture(
        directory, "ascii_complex.raw", header("AC Analysis", "complex", AC_VARS, 2),
        "".join(ac_lines).encode(), marker="Values:\n",
    )
    parsed = ltspice_raw.parse_raw(path)
    check("ascii_complex/points", parsed["points_parsed"] == 2, str(parsed["points_parsed"]))
    got = parsed["values"][0][1]
    check("ascii_complex/re", close(got[0], 0.5), str(got))
    check("ascii_complex/im", close(got[1], -0.25), str(got))

    # 10. .step runs are concatenated; the x-axis restart marks the boundary.
    stepped = POINTS + [[0.0, 9.0, 9.5], [1.0e-3, 8.0, 8.5], [2.0e-3, 7.0, 7.5]]
    path = write_fixture(
        directory, "stepped.raw",
        header("Transient Analysis", "real stepped", TRANSIENT, 6),
        pack_interleaved(stepped, 8, 4),
    )
    parsed = ltspice_raw.parse_raw(path)
    compare_real("stepped", parsed, stepped)
    check("stepped/step_count", parsed["step_count"] == 2, str(parsed["step_count"]))
    check("stepped/segments", parsed["steps"] == [[0, 3], [3, 6]], str(parsed["steps"]))

    # 11. A truncated payload must raise, never return partial garbage.
    path = write_fixture(
        directory, "truncated.raw", header("Transient Analysis", "real", TRANSIENT, 3),
        pack_interleaved(POINTS, 8, 4)[:-7],
    )
    raised = False
    try:
        ltspice_raw.parse_raw(path)
    except ValueError:
        raised = True
    check("truncated/raises", raised, "parsed a truncated file without complaint")

    # 12. CSV export keeps magnitude and phase for AC data.
    path = write_fixture(
        directory, "complex_csv.raw", header("AC Analysis", "complex", AC_VARS, 2), payload,
    )
    csv_path = os.path.join(directory, "out.csv")
    ltspice_raw.export_csv(path, csv_path)
    with open(csv_path, encoding="utf-8") as handle:
        csv_lines = handle.read().strip().splitlines()
    check("csv/header_has_db", "V(out)_db" in csv_lines[0], csv_lines[0])
    check("csv/rows", len(csv_lines) == 3, str(len(csv_lines)))

    real_file_checks()

    print(f"raw self-test: {CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print("  FAIL", failure)
    print(
        "\nNOTE: most fixtures above are spec-derived. The real_file/* checks run "
        "against real LTspice 17.2.4 output (examples/skill_samples/"
        "real_transient_offset.raw), which validates the binary layout, the UTF-16LE "
        "no-BOM header and the Offset: shift. Still unvalidated against real output: "
        "AC/complex, fastaccess, all-float64, ASCII Values:, and .step."
    )
    if FAILURES:
        sys.exit(1)


def real_file_checks() -> None:
    """Ground truth: a real transient .raw from LTspice 17.2.4 for MacOS.

    Produced by `.tran 0 10.02 10` -- data collection delayed to t=10 s -- and
    trimmed to the first 12 points with the author's path scrubbed from Title.
    Nothing else was altered, so the bytes are LTspice's own.

    This is the fixture that caught the Offset: bug: LTspice stored the times as
    0 .. 0.02 and put the 10 s in the `Offset:` header, so a reader that ignores
    Offset reports every event 10 seconds early while looking perfectly plausible.
    """
    path = os.path.join(SAMPLES, "real_transient_offset.raw")
    if not os.path.exists(path):
        check("real_file/present", False, f"missing fixture {path}")
        return

    data = ltspice_raw.parse_raw(path)

    # Header: UTF-16LE with no BOM, which a plain text open() would mangle.
    check("real_file/encoding", data["header_encoding"] == "utf-16le", str(data["header_encoding"]))
    # "real forward" -- the flags field carries tokens beyond the layout keyword.
    check("real_file/flags", data["metadata"]["Flags"] == "real forward", str(data["metadata"]["Flags"]))
    check("real_file/not_complex", data["complex"] is False, str(data["complex"]))
    check("real_file/not_fastaccess", data["fastaccess"] is False, str(data["fastaccess"]))

    # Layout was inferred from payload length alone: 12 * (8 + 4*28) = 1440 bytes.
    check(
        "real_file/layout",
        data["binary_layout"] == "float64_x_float32_vars",
        str(data["binary_layout"]),
    )
    check("real_file/variable_count", len(data["variables"]) == 29, str(len(data["variables"])))
    check("real_file/points", data["points_parsed"] == 12, str(data["points_parsed"]))

    # Variables block is tab-separated with a var_type column; device_current is
    # a real LTspice type that synthetic fixtures never exercised.
    types = sorted({v["var_type"] for v in data["variables"]})
    check("real_file/var_types", types == ["device_current", "time", "voltage"], str(types))

    # The Offset: shift. Without it t[0] would read 0.0.
    check("real_file/offset_value", data["x_offset"] == 10.0, str(data["x_offset"]))
    check("real_file/offset_reported", bool(data["x_offset_note"]), str(data["x_offset_note"]))
    check("real_file/t0_is_tstart", data["x_values"][0] == 10.0, repr(data["x_values"][0]))
    check(
        "real_file/t1_shifted",
        close(data["x_values"][1], 10.000007464483632, 1e-15),
        repr(data["x_values"][1]),
    )
    check("real_file/t_monotonic", all(b >= a for a, b in zip(data["x_values"], data["x_values"][1:])), "")
    # The row itself must be shifted too, not just the x_values list, or callers
    # reading values[i][0] would silently get the unshifted time.
    check("real_file/row_shifted", data["values"][0][0] == 10.0, repr(data["values"][0][0]))

    names = [v["name"] for v in data["variables"]]
    # float32 var payload: 15 V rail must survive the narrower float exactly.
    check(
        "real_file/vcc_rail",
        data["values"][0][names.index("V(vcc)")] == 15.0,
        repr(data["values"][0][names.index("V(vcc)")]),
    )
    # A device current, checked to float32 precision.
    check(
        "real_file/device_current",
        close(data["values"][0][names.index("Ic(Q1)")], 0.0004710095818154514, 1e-12),
        repr(data["values"][0][names.index("Ic(Q1)")]),
    )
    # Single unstepped run.
    check("real_file/single_step", data["steps"] == [[0, 12]], str(data["steps"]))


if __name__ == "__main__":
    run()
