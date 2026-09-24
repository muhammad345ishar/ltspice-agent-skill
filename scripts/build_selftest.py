#!/usr/bin/env python3
"""Self-test for building .asc schematics from scratch.

Runs from a fresh clone with no external corpus: it uses only the shipped
examples/skill_samples/my_resistor.asy, whose pin geometry is known exactly, so
the connectivity assertions are real ground truth rather than self-consistent
guesses.

What it proves:
  * ``new_document`` emits a valid, byte-clean header (LTspice-style CRLF).
  * The append builders (add_flag/add_wire/add_symbol/add_directive) produce a
    file that parses back with the exact record counts intended.
  * A schematic built entirely from scratch resolves to the correct netlist
    against a real symbol -- i.e. the wires actually connect the pins.
  * Writing is stable (parse -> bytes is idempotent) and a later value edit is a
    one-line change, so the builder output is safe to keep editing.
  * Bad rotations are rejected, and a non-default encoding round-trips.

Usage:
    python scripts/build_selftest.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ltspice_asc  # noqa: E402
from ltspice_common import read_ltspice_text  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "examples", "skill_samples")

FAILURES = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{label}: {detail}")


def run() -> None:
    scratch = tempfile.mkdtemp(prefix="ltspice_build_selftest_")

    # 1. Empty schematic: valid header, no records, LTspice-style bytes.
    empty_path = os.path.join(scratch, "empty.asc")
    doc = ltspice_asc.new_document(empty_path)
    check("new/lines", doc.buffer.lines == ["Version 4", "SHEET 1 880 680"],
          str(doc.buffer.lines))
    check("new/encoding", doc.buffer.encoding == "utf-8", doc.buffer.encoding)
    check("new/crlf", doc.buffer.newline == "\r\n", repr(doc.buffer.newline))
    check("new/no_bom", doc.buffer.bom == b"", repr(doc.buffer.bom))
    for key in ("SYMBOL", "WIRE", "FLAG", "TEXT"):
        check(f"new/no_{key}", doc.counts.get(key, 0) == 0, str(doc.counts))
    doc.assert_semantic_counts()

    # 2. Rebuild the connected_ladder fixture entirely from scratch.
    ladder_path = os.path.join(scratch, "ladder.asc")
    doc = ltspice_asc.new_document(ladder_path)
    for x, y, label in [(116, 100, "in"), (116, 196, "mid"), (116, 292, "0"),
                        (396, 180, "out")]:
        doc.add_flag(x, y, label)
    doc.add_wire(300, 180, 116, 196)
    doc.add_symbol("my_resistor", 100, 100, inst_name="R1", value="1k")
    doc.add_symbol("my_resistor", 100, 196, inst_name="R2", value="2k")
    doc.add_symbol("my_resistor", 300, 196, rotation="R90", inst_name="R3", value="3k")
    doc.assert_semantic_counts()
    check("ladder/symbols", len(doc.symbols) == 3, str(len(doc.symbols)))
    check("ladder/wires", len(doc.wires) == 1, str(len(doc.wires)))
    check("ladder/flags", len(doc.flags) == 4, str(len(doc.flags)))
    ltspice_asc.write_asc(doc, ladder_path)

    # 2a. Connectivity is correct against the real symbol -> real ground truth.
    result = ltspice_asc.build_netlist(
        ladder_path, force_fallback=True, symbol_dirs=[SAMPLES]
    )
    expected = "R1 in mid 1k\nR2 mid 0 2k\nR3 mid out 3k"
    check("ladder/netlist", result["netlist"] == expected, repr(result["netlist"]))
    check("ladder/no_warnings", result["warnings"] == [], str(result["warnings"]))

    # 2b. Writing is idempotent: re-reading and re-writing is byte-identical.
    on_disk = open(ladder_path, "rb").read()
    reparsed = ltspice_asc.parse_asc(ladder_path)
    check("ladder/write_stable", reparsed.buffer.to_bytes() == on_disk)
    check("ladder/crlf_on_disk", b"\r\n" in on_disk and b"\n\r" not in on_disk)

    # 3. A directive appends as one TEXT record with the right body.
    doc.add_directive(".op")
    check("directive/count", doc.counts.get("TEXT", 0) == 1, str(doc.counts))
    check("directive/body", doc.directives[0]["body"] == ".op",
          str(doc.directives[0]))

    # 4. Editing a freshly built file is a one-line, read-back change.
    before = list(reparsed.buffer.lines)
    reparsed.set_component_value("R1", "4.7k")
    after = reparsed.buffer.lines
    changed = [i for i in range(min(len(before), len(after))) if before[i] != after[i]]
    check("edit/one_line", len(changed) == 1 and len(before) == len(after),
          f"changed={changed}")
    check("edit/reads_back",
          reparsed._find_symbol_by_inst_name("R1").symattrs.get("Value") == "4.7k")

    # 5. Bad rotation is rejected, not silently written.
    try:
        ltspice_asc.new_document(os.path.join(scratch, "bad.asc")).add_symbol(
            "res", 0, 0, rotation="R45"
        )
        check("rotation/rejected", False, "R45 was accepted")
    except ValueError:
        check("rotation/rejected", True)

    # 6. A non-default encoding round-trips (BOM written and detected back).
    u16_path = os.path.join(scratch, "u16.asc")
    doc = ltspice_asc.new_document(u16_path, encoding="utf-16le")
    doc.add_symbol("res", 100, 100, inst_name="R1", value="1k")
    check("utf16/bom", doc.buffer.bom == b"\xff\xfe", repr(doc.buffer.bom))
    ltspice_asc.write_asc(doc, u16_path)
    back = read_ltspice_text(u16_path)
    check("utf16/detected", back.encoding == "utf-16le" and bool(back.bom))
    check("utf16/content", "SYMATTR Value 1k" in back.lines, str(back.lines))

    print(f"build self-test: {CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print("  FAIL", failure)
    if FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    run()
