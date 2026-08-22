#!/usr/bin/env python3
"""Mutation gate: proves semantic edits touch exactly the lines they must.

Byte-identical round-trip alone is a gameable check -- an implementation that
echoes stored raw lines back passes it while parsing nothing. This gate closes
that hole by requiring that a semantic edit (a) changes exactly one line,
(b) is actually readable back, and (c) leaves encoding, BOM and newline style
intact.

Usage:
    python scripts/mutation_gate.py /path/to/corpus
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ltspice_asc  # noqa: E402
import ltspice_asy  # noqa: E402
import ltspice_common  # noqa: E402

SENTINEL = "12k34"

# ascii / utf-8 / cp1252 are byte-compatible for pure-ASCII content, so an edit
# that removes a file's last non-ASCII byte legitimately changes the *detected*
# label without changing any surviving byte. Only a shift between single-byte and
# UTF-16 families indicates real corruption.
_SINGLE_BYTE = {"ascii", "utf-8", "utf-8-sig", "cp1252", "latin-1"}


def encoding_family(name: str) -> str:
    lowered = (name or "").lower()
    if lowered in _SINGLE_BYTE:
        return "single-byte"
    if lowered.startswith("utf-16"):
        return "utf-16"
    return lowered


def collect(corpus: str) -> Tuple[List[str], List[str]]:
    asc: List[str] = []
    asy: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(corpus):
        for name in filenames:
            path = os.path.join(dirpath, name)
            lower = name.lower()
            if lower.endswith(".asc"):
                asc.append(path)
            elif lower.endswith(".asy"):
                asy.append(path)
    return sorted(asc), sorted(asy)


def roundtrip(paths: List[str], parse, write, tmp: str) -> Dict[str, object]:
    ok = mismatch = exc = 0
    examples: List[str] = []
    for path in paths:
        original = Path(path).read_bytes()
        try:
            doc = parse(path)
            write(doc, tmp)
            if Path(tmp).read_bytes() == original:
                ok += 1
            else:
                mismatch += 1
                if len(examples) < 5:
                    examples.append(f"MISMATCH {path}")
        except Exception as error:  # noqa: BLE001
            exc += 1
            if len(examples) < 5:
                examples.append(f"{type(error).__name__} {path}: {error}")
    return {"ok": ok, "mismatch": mismatch, "exceptions": exc, "examples": examples}


def semantic(paths: List[str], tmp: str) -> Dict[str, object]:
    ok = bad = 0
    examples: List[str] = []
    for path in paths:
        try:
            doc = ltspice_asc.parse_asc(path)
            doc.assert_semantic_counts()
            ok += 1
        except Exception as error:  # noqa: BLE001
            bad += 1
            if len(examples) < 5:
                examples.append(f"{type(error).__name__} {path}: {error}")
    return {"ok": ok, "bad": bad, "examples": examples}


def mutate(paths: List[str], tmp: str) -> Dict[str, object]:
    checked = skipped = ok = 0
    wrong_count = 0
    not_readback = 0
    meta_broken = 0
    examples: List[str] = []
    for path in paths:
        try:
            doc = ltspice_asc.parse_asc(path)
            target = None
            for component in doc.summary()["components"]:
                if component["inst_name"] and component["value"] is not None:
                    target = component["inst_name"]
                    break
            if target is None:
                skipped += 1
                continue

            before_lines = list(doc.buffer.lines)
            before_encoding = doc.buffer.encoding
            before_bom = bool(doc.buffer.bom)
            before_newline = doc.buffer.newline

            doc.set_component_value(target, SENTINEL)
            ltspice_asc.write_asc(doc, tmp)
            reread = ltspice_asc.parse_asc(tmp)
            after_lines = list(reread.buffer.lines)

            checked += 1
            failed = False

            if len(before_lines) != len(after_lines):
                wrong_count += 1
                failed = True
                if len(examples) < 5:
                    examples.append(
                        f"LINE-COUNT {path}: {len(before_lines)} -> {len(after_lines)}"
                    )
            else:
                changed = [
                    index
                    for index, (a, b) in enumerate(zip(before_lines, after_lines))
                    if a != b
                ]
                if len(changed) != 1:
                    wrong_count += 1
                    failed = True
                    if len(examples) < 5:
                        examples.append(f"CHANGED={len(changed)} {path}")

            value_now = None
            for component in reread.summary()["components"]:
                if component["inst_name"] == target:
                    value_now = component["value"]
                    break
            if value_now != SENTINEL:
                not_readback += 1
                failed = True
                if len(examples) < 5:
                    examples.append(f"READBACK {path}: got {value_now!r}")

            if (
                encoding_family(reread.buffer.encoding) != encoding_family(before_encoding)
                or bool(reread.buffer.bom) != before_bom
                or reread.buffer.newline != before_newline
            ):
                meta_broken += 1
                failed = True
                if len(examples) < 5:
                    examples.append(f"META {path}")

            if not failed:
                ok += 1
        except Exception as error:  # noqa: BLE001
            checked += 1
            if len(examples) < 5:
                examples.append(f"{type(error).__name__} {path}: {error}")
    return {
        "checked": checked,
        "skipped": skipped,
        "ok": ok,
        "wrong_line_count": wrong_count,
        "not_readback": not_readback,
        "metadata_broken": meta_broken,
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", help="directory to walk for .asc/.asy files")
    parser.add_argument("--tmp", default="/tmp/_mutation_gate_out")
    args = parser.parse_args()

    asc, asy = collect(args.corpus)
    print(f"corpus: {len(asc)} .asc, {len(asy)} .asy")

    print("\n[1] .asc byte-identical round-trip")
    result = roundtrip(asc, ltspice_asc.parse_asc, ltspice_asc.write_asc, args.tmp)
    print(f"    ok={result['ok']} mismatch={result['mismatch']} exceptions={result['exceptions']}")
    for line in result["examples"]:
        print("      ", line)

    print("\n[2] .asy byte-identical round-trip")
    result = roundtrip(asy, ltspice_asy.parse_asy, ltspice_asy.write_asy, args.tmp)
    print(f"    ok={result['ok']} mismatch={result['mismatch']} exceptions={result['exceptions']}")
    for line in result["examples"]:
        print("      ", line)

    print("\n[3] semantic count assertion (reader understood the file)")
    result = semantic(asc, args.tmp)
    print(f"    ok={result['ok']} failed={result['bad']}")
    for line in result["examples"]:
        print("      ", line)

    print("\n[4] mutation gate (edit changes exactly one line and reads back)")
    result = mutate(asc, args.tmp)
    print(
        f"    checked={result['checked']} passed={result['ok']} "
        f"skipped_no_value={result['skipped']}"
    )
    print(
        f"    wrong_line_count={result['wrong_line_count']} "
        f"not_readback={result['not_readback']} metadata_broken={result['metadata_broken']}"
    )
    for line in result["examples"]:
        print("      ", line)


if __name__ == "__main__":
    main()
