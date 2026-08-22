"""Parse LTspice .raw waveform files."""

from __future__ import annotations

import argparse
import csv
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class RawVariable:
    index: int
    name: str
    var_type: str


def _detect_header_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe"):
        return "utf-16le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    if len(raw) > 3 and raw[1] == 0 and raw[3] == 0:
        return "utf-16le"
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _find_marker_split(raw: bytes, encoding: str, marker: str) -> int:
    marker_bytes = marker.encode(encoding, errors="strict")
    pos = raw.find(marker_bytes)
    if pos < 0:
        return -1
    if encoding.startswith("utf-16"):
        crlf = "\r\n".encode(encoding)
        lf = "\n".encode(encoding)
    else:
        crlf = b"\r\n"
        lf = b"\n"
    end_crlf = raw.find(crlf, pos)
    if end_crlf >= 0:
        return end_crlf + len(crlf)
    end_lf = raw.find(lf, pos)
    if end_lf >= 0:
        return end_lf + len(lf)
    return pos + len(marker_bytes)


def _split_header_payload(raw: bytes, encoding: str) -> Tuple[bytes, bytes, str]:
    binary_split = _find_marker_split(raw, encoding, "Binary:")
    if binary_split >= 0:
        return raw[:binary_split], raw[binary_split:], "binary"
    values_split = _find_marker_split(raw, encoding, "Values:")
    if values_split >= 0:
        return raw[:values_split], raw[values_split:], "values"
    raise ValueError("RAW data missing Values:/Binary: delimiter.")


def _parse_header(text: str) -> Tuple[Dict[str, str], List[RawVariable]]:
    lines = text.splitlines()
    metadata: Dict[str, str] = {}
    variables: List[RawVariable] = []
    in_vars = False
    for line in lines:
        if line.strip() == "Variables:":
            in_vars = True
            continue
        if in_vars and line.startswith("\t"):
            parts = line.strip().split(None, 2)
            if len(parts) == 3:
                variables.append(
                    RawVariable(index=int(parts[0]), name=parts[1], var_type=parts[2])
                )
            continue
        if ":" in line and not line.startswith("\t"):
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata, variables


def _parse_ascii_values(payload: bytes, var_count: int, encoding: str) -> List[List[float]]:
    text = payload.decode(encoding, errors="strict")
    values: List[List[float]] = []
    row: List[float] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            row.append(float(parts[-1]))
        except ValueError:
            continue
        if len(row) == var_count:
            values.append(row)
            row = []
    return values


def _parse_binary_values(
    payload: bytes, variable_count: int, point_count: int, flags: str
) -> List[List[float]]:
    rows: List[List[float]] = []
    cursor = 0
    flags_l = flags.lower()
    complex_mode = "complex" in flags_l
    real_mode = "real" in flags_l

    for _ in range(point_count):
        row: List[float] = []
        for col in range(variable_count):
            if complex_mode:
                if cursor + 16 > len(payload):
                    raise ValueError("RAW binary truncated for complex sample.")
                real_v, _imag_v = struct.unpack_from("<dd", payload, cursor)
                cursor += 16
                row.append(real_v)
                continue

            if col == 0 or not real_mode:
                if cursor + 8 > len(payload):
                    raise ValueError("RAW binary truncated for float64 sample.")
                value = struct.unpack_from("<d", payload, cursor)[0]
                cursor += 8
            else:
                if cursor + 4 > len(payload):
                    raise ValueError("RAW binary truncated for float32 sample.")
                value = struct.unpack_from("<f", payload, cursor)[0]
                cursor += 4
            row.append(value)
        rows.append(row)
    return rows


def parse_raw(path: str) -> Dict[str, object]:
    raw = Path(path).read_bytes()
    encoding = _detect_header_encoding(raw)
    header_bytes, payload, mode = _split_header_payload(raw, encoding)
    header_text = header_bytes.decode(encoding, errors="strict")
    metadata, variables = _parse_header(header_text)

    variable_count = int(metadata.get("No. Variables", len(variables) or 0))
    point_count = int(metadata.get("No. Points", 0))
    flags = metadata.get("Flags", "")

    if mode == "values":
        rows = _parse_ascii_values(payload, variable_count, encoding)
    else:
        rows = _parse_binary_values(payload, variable_count, point_count, flags)

    return {
        "path": path,
        "validated": False,
        "validation_note": "Parsed successfully; numeric validation against matching .log is required.",
        "header_encoding": encoding,
        "mode": mode,
        "metadata": metadata,
        "variables": [v.__dict__ for v in variables],
        "points_expected": point_count,
        "points_parsed": len(rows),
        "values_preview": rows[:10],
        "values": rows,
    }


def export_csv(path: str, csv_path: str) -> None:
    parsed = parse_raw(path)
    variables = parsed["variables"]
    values = parsed["values"]
    if not variables:
        raise ValueError("No variable table found in RAW header.")
    with Path(csv_path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([v["name"] for v in variables])
        for row in values:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice RAW parser")
    sub = parser.add_subparsers(dest="cmd", required=True)

    summary = sub.add_parser("summary")
    summary.add_argument("path")
    summary.add_argument("--no-values", action="store_true")

    to_csv = sub.add_parser("csv")
    to_csv.add_argument("path")
    to_csv.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.cmd == "summary":
        data = parse_raw(args.path)
        if args.no_values:
            data.pop("values", None)
        print(json.dumps(data, indent=2))
        return
    if args.cmd == "csv":
        export_csv(args.path, args.output)
        print(args.output)


if __name__ == "__main__":
    main()
