#!/usr/bin/env python3
"""Ground-truth tests for geometric netlist extraction.

Unlike the .raw/.log self-tests, these assertions are real ground truth: the
symbol (examples/skill_samples/my_resistor.asy) is hand-written and shipped, so
its pin coordinates are known exactly and the correct netlist can be derived by
hand rather than assumed.

Covers the four things that make geometric netlisting go wrong silently:
wire-endpoint union, FLAG label merging (including ground), the rotation
transform, and SpiceOrder terminal ordering.

Usage:
    python scripts/netlist_selftest.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ltspice_asc  # noqa: E402

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
    # 1. Known-good ladder. my_resistor.asy pins are (16,0) and (16,96), so:
    #      R1 at (100,100) R0  -> (116,100) and (116,196)
    #      R2 at (100,196) R0  -> (116,196) and (116,292)   [shares mid with R1]
    #      R3 at (300,196) R90 -> (300,180) and (396,180)   [wire joins to mid]
    #    FLAGs name in/mid/0/out, so the netlist is fully determined.
    result = ltspice_asc.build_netlist(
        os.path.join(SAMPLES, "connected_ladder.asc"),
        force_fallback=True,
        symbol_dirs=[SAMPLES],
    )
    expected = "R1 in mid 1k\nR2 mid 0 2k\nR3 mid out 3k"
    check("ladder/netlist", result["netlist"] == expected, repr(result["netlist"]))
    check("ladder/unresolved", result["unresolved"] == [], str(result["unresolved"]))
    check("ladder/warnings", result["warnings"] == [], str(result["warnings"]))

    netlist = result["netlist"]
    # Ground must be named "0", never an auto-generated Nxxxx.
    check("ladder/ground_named_0", " 0 " in netlist, netlist)
    # A shared coordinate must collapse to one net, not two.
    check("ladder/mid_shared", netlist.count("mid") == 3, netlist)
    # The R90 instance must land on the wire endpoint; if the rotation transform
    # were the textbook (-dy, dx) instead of LTspice's y-down (dy, -dx), R3
    # would be isolated and get an Nxxxx net instead of "mid".
    check("ladder/rotation", "R3 mid out" in netlist, netlist)
    check("ladder/no_auto_nets", "N000" not in netlist, netlist)

    # 2. Stock primitives with no lib/sym must be flagged, not silently trusted.
    result = ltspice_asc.build_netlist(
        os.path.join(SAMPLES, "windowed_rc.asc"), force_fallback=True
    )
    warnings = " ".join(result["warnings"])
    check("stock/geometry_failure_flagged", "GEOMETRY FAILURE" in warnings, warnings)
    check(
        "stock/approximate_flagged",
        "unverified primitive table" in warnings,
        warnings,
    )
    check(
        "stock/all_three_named",
        all(f"{inst} (" in warnings for inst in ("R1", "C1", "V1")),
        warnings,
    )

    # 3. An unknown symbol must be reported as unresolved.
    #    Written to a temp dir, not the samples dir, so a failed run cannot
    #    leave a stray fixture behind that later self-tests would pick up.
    scratch = tempfile.mkdtemp(prefix="ltspice_netlist_selftest_")
    unknown = os.path.join(scratch, "unknown_part.asc")
    with open(unknown, "w", encoding="ascii") as handle:
        handle.write(
            "Version 4\nSHEET 1 880 680\n"
            "SYMBOL totally_made_up_part 100 100 R0\n"
            "SYMATTR InstName U1\nSYMATTR Value XYZ\n"
        )
    result = ltspice_asc.build_netlist(unknown, force_fallback=True)
    joined = " ".join(result["unresolved"])
    check("unknown/reported", "U1" in joined, joined)
    check("unknown/says_unresolved", "unresolved symbol pins" in joined, joined)
    check("unknown/no_invented_nets", result["netlist"] == "", repr(result["netlist"]))

    print(f"netlist self-test: {CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    for failure in FAILURES:
        print("  FAIL", failure)
    if FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    run()
