"""Read/write LTspice .asy symbol files."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from .ltspice_common import TextFileBuffer, read_ltspice_text, write_ltspice_text
except ImportError:
    from ltspice_common import TextFileBuffer, read_ltspice_text, write_ltspice_text


@dataclass
class PinRecord:
    line_index: int
    x: int
    y: int
    orient: str
    offset: int
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class AsyDocument:
    buffer: TextFileBuffer
    symbol_type: Optional[str]
    pins: List[PinRecord]
    attrs: Dict[str, str]
    counts: Dict[str, int]
    unknown_records: List[dict]

    def summary(self) -> dict:
        return {
            "path": str(self.buffer.path),
            "encoding": self.buffer.encoding,
            "bom": bool(self.buffer.bom),
            "newline": "CRLF" if self.buffer.newline == "\r\n" else "LF",
            "symbol_type": self.symbol_type,
            "pins": [
                {
                    "x": p.x,
                    "y": p.y,
                    "orientation": p.orient,
                    "offset": p.offset,
                    "pin_name": p.attrs.get("PinName"),
                    "spice_order": p.attrs.get("SpiceOrder"),
                }
                for p in self.pins
            ],
            "attrs": self.attrs,
            "counts": self.counts,
            "unknown_records": self.unknown_records,
        }


def parse_asy_from_buffer(buffer: TextFileBuffer) -> AsyDocument:
    symbol_type = None
    pins: List[PinRecord] = []
    attrs: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    unknown_records: List[dict] = []
    current_pin: Optional[PinRecord] = None

    for line_index, line in enumerate(buffer.lines):
        if not line.strip():
            continue
        tokens = line.split()
        keyword = tokens[0]
        counts[keyword] = counts.get(keyword, 0) + 1

        if keyword == "SymbolType" and len(tokens) >= 2:
            symbol_type = tokens[1]
            continue

        if keyword == "PIN" and len(tokens) >= 5:
            pin = PinRecord(
                line_index=line_index,
                x=int(tokens[1]),
                y=int(tokens[2]),
                orient=tokens[3],
                offset=int(tokens[4]),
            )
            pins.append(pin)
            current_pin = pin
            continue

        if keyword == "PINATTR" and current_pin:
            parts = line.split(None, 2)
            if len(parts) >= 3:
                current_pin.attrs[parts[1]] = parts[2]
            continue

        if keyword == "SYMATTR":
            parts = line.split(None, 2)
            if len(parts) >= 3:
                attrs[parts[1]] = parts[2]
            continue

        if keyword in {"Version", "LINE", "RECTANGLE", "CIRCLE", "ARC", "WINDOW", "TEXT"}:
            continue

        unknown_records.append(
            {"line": line_index + 1, "keyword": keyword, "content": line}
        )

    return AsyDocument(
        buffer=buffer,
        symbol_type=symbol_type,
        pins=pins,
        attrs=attrs,
        counts=counts,
        unknown_records=unknown_records,
    )


def parse_asy(path: str) -> AsyDocument:
    return parse_asy_from_buffer(read_ltspice_text(path))


def write_asy(doc: AsyDocument, output_path: Optional[str] = None) -> None:
    write_ltspice_text(doc.buffer, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice ASY reader/writer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    summary = sub.add_parser("summary")
    summary.add_argument("path")

    roundtrip = sub.add_parser("roundtrip")
    roundtrip.add_argument("path")
    roundtrip.add_argument("--output")

    args = parser.parse_args()

    if args.cmd == "summary":
        doc = parse_asy(args.path)
        print(json.dumps(doc.summary(), indent=2))
        return

    if args.cmd == "roundtrip":
        doc = parse_asy(args.path)
        write_asy(doc, args.output)
        print(args.output or args.path)


if __name__ == "__main__":
    main()
