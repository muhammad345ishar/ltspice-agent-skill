"""Corpus round-trip and semantic assertions for LTspice files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ltspice_asc import parse_asc
from ltspice_asy import parse_asy


def run(corpus: str) -> dict:
    root = Path(corpus)
    asc_checked = 0
    asc_failures = 0
    asy_checked = 0
    asy_failures = 0
    failures = []

    for asc in root.rglob("*.asc"):
        asc_checked += 1
        try:
            doc = parse_asc(str(asc))
            doc.assert_semantic_counts()
            if doc.buffer.to_bytes() != doc.buffer.raw:
                asc_failures += 1
                failures.append({"path": str(asc), "kind": "byte_mismatch"})
        except Exception as exc:  # explicit failure surfacing
            asc_failures += 1
            failures.append({"path": str(asc), "kind": "exception", "error": str(exc)})

    for asy in root.rglob("*.asy"):
        asy_checked += 1
        try:
            doc = parse_asy(str(asy))
            if doc.buffer.to_bytes() != doc.buffer.raw:
                asy_failures += 1
                failures.append({"path": str(asy), "kind": "asy_byte_mismatch"})
        except Exception as exc:  # explicit failure surfacing
            asy_failures += 1
            failures.append({"path": str(asy), "kind": "exception", "error": str(exc)})

    return {
        "asc_checked": asc_checked,
        "asc_failures": asc_failures,
        "asy_checked": asy_checked,
        "asy_failures": asy_failures,
        "total_failures": asc_failures + asy_failures,
        "failures": failures[:100],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip harness for LTspice corpus")
    parser.add_argument("corpus", help="Path containing .asc/.asy files")
    args = parser.parse_args()

    result = run(args.corpus)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["total_failures"] else 0)


if __name__ == "__main__":
    main()
