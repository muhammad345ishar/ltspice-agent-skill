"""Read/write LTspice .asc schematics with encoding-safe edits."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from .ltspice_common import (
        TextFileBuffer,
        new_ltspice_buffer,
        read_ltspice_text,
        write_ltspice_text,
    )
except ImportError:
    from ltspice_common import (
        TextFileBuffer,
        new_ltspice_buffer,
        read_ltspice_text,
        write_ltspice_text,
    )

try:
    from .ltspice_asy import parse_asy
except ImportError:
    from ltspice_asy import parse_asy


KNOWN_KEYS = {"SYMBOL", "SYMATTR", "WIRE", "FLAG", "TEXT"}
# Rotation/mirror codes LTspice accepts on a SYMBOL line. R = rotate clockwise,
# M = mirror-then-rotate. See reference/authoring-asc.md for the transform.
VALID_ROTATIONS = {"R0", "R90", "R180", "R270", "M0", "M90", "M180", "M270"}
# Approximate pin offsets for stock LTspice primitives, used only when the real
# lib/sym tree is unavailable.
#
# UNVERIFIED: these have NOT been checked against the shipped LTspice symbol
# library. Real res/cap/voltage symbols are drawn vertically with the origin at
# the top-left and pins at offsets like (16, 16) and (16, 80), so these centred
# horizontal offsets are unlikely to be right. Any instance resolved through this
# table therefore gets a warning attached, because a wrong pin coordinate yields
# a wrong-but-plausible net assignment -- the worst kind of failure.
#
# Fix by pointing --symbol-dir at the LTspice lib/sym tree, or by using
# LTspice -netlist for authoritative connectivity.
PRIMITIVE_PIN_OFFSETS = {
    "res": [(-16, 0), (16, 0)],
    "cap": [(-16, 0), (16, 0)],
    "ind": [(-16, 0), (16, 0)],
    "voltage": [(-16, 0), (16, 0)],
    "current": [(-16, 0), (16, 0)],
    "diode": [(-16, 0), (16, 0)],
}


@dataclass
class WireRecord:
    x1: int
    y1: int
    x2: int
    y2: int

    def endpoints(self) -> Iterable[Tuple[int, int]]:
        return ((self.x1, self.y1), (self.x2, self.y2))


@dataclass
class FlagRecord:
    x: int
    y: int
    label: str


@dataclass
class SymbolRecord:
    line_index: int
    symbol_name: str
    x: int
    y: int
    rotation: str
    symattrs: Dict[str, str] = field(default_factory=dict)
    windows: List[dict] = field(default_factory=list)


@dataclass
class AscDocument:
    buffer: TextFileBuffer
    symbols: List[SymbolRecord]
    wires: List[WireRecord]
    flags: List[FlagRecord]
    directives: List[dict]
    net_labels: List[str]
    unknown_records: List[dict]
    counts: Dict[str, int]

    def summary(self) -> dict:
        components = []
        for sym in self.symbols:
            components.append(
                {
                    "inst_name": sym.symattrs.get("InstName"),
                    "symbol": sym.symbol_name,
                    "value": sym.symattrs.get("Value"),
                    "value2": sym.symattrs.get("Value2"),
                    "spiceline": sym.symattrs.get("SpiceLine"),
                    "rotation": sym.rotation,
                }
            )
        directives = []
        for item in self.directives:
            directives.append(
                {
                    "line": item["line_index"] + 1,
                    "raw": item["raw"],
                    "decoded": item["body"],
                }
            )
        return {
            "path": str(self.buffer.path),
            "encoding": self.buffer.encoding,
            "bom": bool(self.buffer.bom),
            "newline": "CRLF" if self.buffer.newline == "\r\n" else "LF",
            "counts": self.counts,
            "components": components,
            "directives": directives,
            "net_labels": sorted(set(self.net_labels)),
            "unresolved": [],
        }

    def semantic_counts_from_text(self) -> Dict[str, int]:
        source = "\n".join(self.buffer.lines)
        counts = {}
        for key in KNOWN_KEYS:
            counts[key] = len(re.findall(rf"(?m)^{re.escape(key)}\b", source))
        return counts

    def assert_semantic_counts(self) -> None:
        measured = self.semantic_counts_from_text()
        for key in KNOWN_KEYS:
            actual = self.counts.get(key, 0)
            if measured[key] != actual:
                raise ValueError(
                    f"Semantic count mismatch for {key}: parsed={actual}, measured={measured[key]}"
                )

    def _find_symbol_by_inst_name(self, inst_name: str) -> SymbolRecord:
        for sym in self.symbols:
            if sym.symattrs.get("InstName") == inst_name:
                return sym
        raise ValueError(f"No component with InstName '{inst_name}'")

    def set_component_value(self, inst_name: str, value: str) -> int:
        symbol = self._find_symbol_by_inst_name(inst_name)
        block_end = len(self.buffer.lines)
        symbol_index = self.symbols.index(symbol)
        if symbol_index + 1 < len(self.symbols):
            block_end = self.symbols[symbol_index + 1].line_index

        value_line_index = None
        last_symattr_index = None
        last_window_index = None
        for line_index in range(symbol.line_index + 1, block_end):
            line = self.buffer.lines[line_index]
            # WINDOW records belong to the symbol block and normally sit between
            # the SYMBOL line and its SYMATTR lines. They must not terminate the
            # scan, or the existing Value is never found and a duplicate is added.
            if line.startswith("WINDOW "):
                last_window_index = line_index
                continue
            if line.startswith("SYMATTR "):
                last_symattr_index = line_index
                parts = line.split(None, 2)
                if len(parts) >= 2 and parts[1] == "Value":
                    value_line_index = line_index
                    break
                continue
            # Any other record type ends this symbol's attribute block.
            break

        if value_line_index is None:
            if last_symattr_index is not None:
                insert_at = last_symattr_index + 1
            elif last_window_index is not None:
                insert_at = last_window_index + 1
            else:
                insert_at = symbol.line_index + 1

        new_line = f"SYMATTR Value {value}"
        if value_line_index is None:
            self.buffer.lines.insert(insert_at, new_line)
            self._reparse()
            return insert_at

        self.buffer.lines[value_line_index] = new_line
        self._reparse()
        return value_line_index

    def add_directive(self, directive: str, x: int = 0, y: int = 0, size: int = 2) -> int:
        escaped = directive.replace("\n", "\\n")
        line = f"TEXT {x} {y} Left {size} !{escaped}"
        self.buffer.lines.append(line)
        self._reparse()
        return len(self.buffer.lines) - 1

    def add_symbol(
        self,
        symbol_name: str,
        x: int,
        y: int,
        rotation: str = "R0",
        inst_name: Optional[str] = None,
        value: Optional[str] = None,
        attrs: Optional[Iterable[Tuple[str, str]]] = None,
    ) -> int:
        """Append a SYMBOL block. WINDOW records are omitted deliberately —
        LTspice regenerates them at their default positions when it opens the
        file, so a minimal block (SYMBOL + SYMATTR lines) is valid and complete.
        """
        if rotation not in VALID_ROTATIONS:
            raise ValueError(
                f"Invalid rotation '{rotation}'. Use one of {sorted(VALID_ROTATIONS)}"
            )
        new_lines = [f"SYMBOL {symbol_name} {int(x)} {int(y)} {rotation}"]
        if inst_name is not None:
            new_lines.append(f"SYMATTR InstName {inst_name}")
        if value is not None:
            new_lines.append(f"SYMATTR Value {value}")
        for key, val in attrs or []:
            new_lines.append(f"SYMATTR {key} {val}")
        insert_at = len(self.buffer.lines)
        self.buffer.lines.extend(new_lines)
        self._reparse()
        return insert_at

    def add_wire(self, x1: int, y1: int, x2: int, y2: int) -> int:
        self.buffer.lines.append(f"WIRE {int(x1)} {int(y1)} {int(x2)} {int(y2)}")
        self._reparse()
        return len(self.buffer.lines) - 1

    def add_flag(self, x: int, y: int, label: str) -> int:
        """Add a net label. Label ``0`` is ground."""
        self.buffer.lines.append(f"FLAG {int(x)} {int(y)} {label}")
        self._reparse()
        return len(self.buffer.lines) - 1

    def remove_directive(self, directive_prefix: str) -> int:
        for idx, directive in enumerate(self.directives):
            if directive["body"].startswith(directive_prefix):
                del self.buffer.lines[directive["line_index"]]
                self._reparse()
                return idx
        raise ValueError(f"No directive starts with '{directive_prefix}'")

    def _reparse(self) -> None:
        refreshed = parse_asc_from_buffer(self.buffer)
        self.symbols = refreshed.symbols
        self.wires = refreshed.wires
        self.flags = refreshed.flags
        self.directives = refreshed.directives
        self.net_labels = refreshed.net_labels
        self.unknown_records = refreshed.unknown_records
        self.counts = refreshed.counts


class DisjointSet:
    def __init__(self) -> None:
        self.parent: Dict[int, int] = {}

    def find(self, item: int) -> int:
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def make(self, item: int) -> None:
        self.parent[item] = item

    def union(self, a: int, b: int) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _parse_text_body(tokens: List[str]) -> str:
    if len(tokens) < 6:
        return ""
    body = " ".join(tokens[5:])
    return body.replace("\\n", "\n")


def parse_asc_from_buffer(buffer: TextFileBuffer) -> AscDocument:
    symbols: List[SymbolRecord] = []
    wires: List[WireRecord] = []
    flags: List[FlagRecord] = []
    directives: List[dict] = []
    net_labels: List[str] = []
    unknown_records: List[dict] = []
    counts: Dict[str, int] = {}
    current_symbol: Optional[SymbolRecord] = None

    for line_index, line in enumerate(buffer.lines):
        if not line.strip():
            continue
        tokens = line.split()
        keyword = tokens[0]
        counts[keyword] = counts.get(keyword, 0) + 1

        if keyword == "SYMBOL" and len(tokens) >= 5:
            record = SymbolRecord(
                line_index=line_index,
                symbol_name=tokens[1],
                x=int(tokens[2]),
                y=int(tokens[3]),
                rotation=tokens[4],
            )
            symbols.append(record)
            current_symbol = record
            continue

        if keyword == "WINDOW" and current_symbol and len(tokens) >= 6:
            current_symbol.windows.append(
                {
                    "id": tokens[1],
                    "x": int(tokens[2]),
                    "y": int(tokens[3]),
                    "justification": tokens[4],
                    "size": tokens[5],
                }
            )
            continue

        if keyword == "SYMATTR" and current_symbol:
            parts = line.split(None, 2)
            if len(parts) >= 3:
                current_symbol.symattrs[parts[1]] = parts[2]
            continue

        if keyword == "WIRE" and len(tokens) >= 5:
            wires.append(
                WireRecord(
                    x1=int(tokens[1]),
                    y1=int(tokens[2]),
                    x2=int(tokens[3]),
                    y2=int(tokens[4]),
                )
            )
            continue

        if keyword == "FLAG" and len(tokens) >= 4:
            flags.append(FlagRecord(x=int(tokens[1]), y=int(tokens[2]), label=tokens[3]))
            net_labels.append(tokens[3])
            continue

        if keyword == "TEXT":
            body = _parse_text_body(tokens)
            if body.startswith("!"):
                directives.append(
                    {"line_index": line_index, "body": body[1:], "raw": body}
                )
            continue

        if keyword in {
            "Version",
            "SHEET",
            "LINE",
            "RECTANGLE",
            "CIRCLE",
            "ARC",
            "DATAFLAG",
            "IOPIN",
        }:
            continue

        unknown_records.append(
            {
                "line": line_index + 1,
                "keyword": keyword,
                "content": line,
            }
        )

    return AscDocument(
        buffer=buffer,
        symbols=symbols,
        wires=wires,
        flags=flags,
        directives=directives,
        net_labels=net_labels,
        unknown_records=unknown_records,
        counts=counts,
    )


def parse_asc(path: str) -> AscDocument:
    return parse_asc_from_buffer(read_ltspice_text(path))


def write_asc(doc: AscDocument, output_path: Optional[str] = None) -> Path:
    return write_ltspice_text(doc.buffer, output_path)


def new_document(
    path: str,
    sheet_w: int = 880,
    sheet_h: int = 680,
    encoding: str = "utf-8",
    newline: str = "\r\n",
) -> AscDocument:
    """Create an empty but valid schematic (``Version 4`` + ``SHEET`` header).

    Defaults produce a file byte-for-byte in the style LTspice writes: CRLF
    endings and ASCII content. Prefer ASCII SI prefixes (``u`` for micro, not
    ``µ``) so the file stays encoding-clean; see reference/spice-dialect.md.
    """
    header = ["Version 4", f"SHEET 1 {int(sheet_w)} {int(sheet_h)}"]
    buffer = new_ltspice_buffer(path, lines=header, encoding=encoding, newline=newline)
    return parse_asc_from_buffer(buffer)


def _rotate(x: int, y: int, deg: int) -> Tuple[int, int]:
    d = deg % 360
    if d == 0:
        return x, y
    if d == 90:
        return y, -x
    if d == 180:
        return -x, -y
    if d == 270:
        return -y, x
    raise ValueError(f"Unsupported rotation {deg}")


def _transform_offset(dx: int, dy: int, rotation: str) -> Tuple[int, int]:
    if rotation.startswith("M"):
        dx, dy = -dx, dy
        return _rotate(dx, dy, int(rotation[1:]))
    if rotation.startswith("R"):
        return _rotate(dx, dy, int(rotation[1:]))
    raise ValueError(f"Unsupported rotation code '{rotation}'")


def _normalize_symbol_name(name: str) -> str:
    return name.replace("\\", "/").lower()


def _build_symbol_index(symbol_dirs: Iterable[Path]) -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for directory in symbol_dirs:
        if not directory.exists():
            continue
        for file_path in directory.rglob("*.asy"):
            rel = str(file_path.relative_to(directory)).replace("\\", "/")
            index[_normalize_symbol_name(rel[:-4])] = file_path
            index[_normalize_symbol_name(file_path.stem)] = file_path
    return index


def _resolve_symbol_pins(
    symbol: SymbolRecord, symbol_index: Dict[str, Path]
) -> Tuple[List[Tuple[int, int, int]], List[str], List[str]]:
    """Return (pins, unresolved, approximate).

    ``approximate`` names instances whose pin coordinates came from the
    unverified primitive table rather than a real .asy, so the caller can warn.
    """
    unresolved: List[str] = []
    approximate: List[str] = []
    normalized = _normalize_symbol_name(symbol.symbol_name)
    candidate = symbol_index.get(normalized)
    if candidate is not None:
        parsed = parse_asy(str(candidate))
        pins: List[Tuple[int, int, int]] = []
        for idx, pin in enumerate(parsed.pins):
            order_txt = pin.attrs.get("SpiceOrder")
            try:
                order = int(order_txt) if order_txt is not None else idx + 1
            except ValueError:
                order = idx + 1
            pins.append((order, pin.x, pin.y))
        if pins:
            return pins, unresolved, approximate
        unresolved.append(
            f"{symbol.symattrs.get('InstName', symbol.symbol_name)}: symbol resolved but no pins in {candidate}"
        )
        return [], unresolved, approximate

    primitive = normalized.split("/")[-1]
    offsets = PRIMITIVE_PIN_OFFSETS.get(primitive)
    if offsets:
        inst = symbol.symattrs.get("InstName", symbol.symbol_name)
        approximate.append(
            f"{inst} ('{symbol.symbol_name}'): pin coordinates came from the "
            "unverified primitive table, not a real .asy -- its connectivity is a guess"
        )
        return (
            [(idx + 1, x, y) for idx, (x, y) in enumerate(offsets)],
            unresolved,
            approximate,
        )

    unresolved.append(
        f"{symbol.symattrs.get('InstName', symbol.symbol_name)}: unresolved symbol pins for '{symbol.symbol_name}'"
    )
    return [], unresolved, approximate


def _build_geometric_netlist(
    doc: AscDocument, symbol_dirs: Optional[List[str]] = None
) -> Dict[str, object]:
    directories = [Path(p) for p in (symbol_dirs or [])]
    symbol_index = _build_symbol_index(directories)

    coord_to_node: Dict[Tuple[int, int], int] = {}
    next_node = 0

    def node_for(coord: Tuple[int, int]) -> int:
        nonlocal next_node
        if coord not in coord_to_node:
            coord_to_node[coord] = next_node
            next_node += 1
        return coord_to_node[coord]

    dsu = DisjointSet()
    wire_nodes: List[Tuple[int, int]] = []
    for wire in doc.wires:
        a = node_for((wire.x1, wire.y1))
        b = node_for((wire.x2, wire.y2))
        wire_nodes.append((a, b))

    for node_id in range(next_node):
        dsu.make(node_id)

    for a, b in wire_nodes:
        dsu.union(a, b)

    label_nodes: Dict[str, List[int]] = {}
    for flag in doc.flags:
        nid = node_for((flag.x, flag.y))
        if nid not in dsu.parent:
            dsu.make(nid)
        label_nodes.setdefault(flag.label, []).append(nid)

    for _label, nodes in label_nodes.items():
        first = nodes[0]
        for other in nodes[1:]:
            dsu.union(first, other)

    component_nets: List[Tuple[SymbolRecord, List[Tuple[int, int]]]] = []
    unresolved: List[str] = []
    approximate: List[str] = []
    for symbol in doc.symbols:
        pin_offsets, pin_unresolved, pin_approximate = _resolve_symbol_pins(
            symbol, symbol_index
        )
        unresolved.extend(pin_unresolved)
        approximate.extend(pin_approximate)
        pin_nodes: List[Tuple[int, int]] = []
        for order, dx, dy in sorted(pin_offsets, key=lambda item: item[0]):
            tx, ty = _transform_offset(dx, dy, symbol.rotation)
            coord = (symbol.x + tx, symbol.y + ty)
            nid = node_for(coord)
            if nid not in dsu.parent:
                dsu.make(nid)
            pin_nodes.append((order, nid))
        if not pin_nodes:
            unresolved.append(
                f"{symbol.symattrs.get('InstName', symbol.symbol_name)}: no resolvable pins"
            )
        component_nets.append((symbol, pin_nodes))

    root_labels: Dict[int, List[str]] = {}
    for label, nodes in label_nodes.items():
        root = dsu.find(nodes[0])
        root_labels.setdefault(root, []).append(label)

    auto_index = 1
    root_name: Dict[int, str] = {}
    for root, labels in root_labels.items():
        unique = sorted(set(labels))
        if "0" in unique:
            root_name[root] = "0"
        else:
            root_name[root] = unique[0]

    def net_name(node_id: int) -> str:
        nonlocal auto_index
        root = dsu.find(node_id)
        if root not in root_name:
            root_name[root] = f"N{auto_index:04d}"
            auto_index += 1
        return root_name[root]

    lines: List[str] = []
    emitted: List[Tuple[str, List[str]]] = []
    for idx, (symbol, pin_nodes) in enumerate(component_nets, start=1):
        inst_name = symbol.symattrs.get("InstName", f"X{idx}")
        value = symbol.symattrs.get("Value", symbol.symbol_name)
        if len(pin_nodes) < 2:
            continue
        pin_nodes_sorted = [node for _, node in sorted(pin_nodes, key=lambda item: item[0])]
        nets = [net_name(node) for node in pin_nodes_sorted]
        line = f"{inst_name} {' '.join(nets)} {value}"
        lines.append(line)
        emitted.append((inst_name, nets))

    warnings: List[str] = list(approximate)

    # Sanity check: a component sharing no net with any other component is
    # almost always a geometry failure (pin coordinates landing off the wire
    # endpoints), not a real circuit. Without this the fallback happily reports
    # a confident netlist in which nothing is connected to anything.
    net_users: Dict[str, int] = {}
    for _inst, nets in emitted:
        for net in set(nets):
            net_users[net] = net_users.get(net, 0) + 1

    isolated = [
        inst
        for inst, nets in emitted
        if all(net_users.get(net, 0) < 2 for net in set(nets))
    ]
    if emitted and len(isolated) == len(emitted):
        warnings.append(
            "GEOMETRY FAILURE: no component shares a net with any other component. "
            "Every pin landed on its own node, so this netlist describes a fully "
            "disconnected circuit and must not be reported as the circuit's "
            "connectivity. Likely cause: pin offsets do not match the symbols "
            "actually used. Supply the LTspice lib/sym tree via --symbol-dir, or "
            "use LTspice -netlist."
        )
    elif isolated:
        warnings.append(
            "Components connected to nothing else: "
            + ", ".join(sorted(isolated))
            + ". Verify their pin coordinates before trusting these nets."
        )

    return {
        "mode": "geometric-fallback",
        "netlist": "\n".join(lines),
        "unresolved": sorted(set(unresolved)),
        "warnings": warnings,
    }


def extract_netlist_with_ltspice(path: str, ltspice_binary: str) -> str:
    schematic = Path(path)
    cmd = [ltspice_binary, "-netlist", str(schematic)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"LTspice netlist generation failed: {stderr}")
    netlist = schematic.with_suffix(".net")
    if not netlist.exists():
        raise RuntimeError("LTspice reported success but no .net file was produced.")
    return netlist.read_text(encoding="utf-8", errors="strict")


def resolve_ltspice_binary(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    candidates = [
        shutil.which("LTspice"),
        shutil.which("ltspice"),
        "/Applications/LTspice.app/Contents/MacOS/LTspice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def build_netlist(
    path: str,
    ltspice_binary: Optional[str] = None,
    force_fallback: bool = False,
    symbol_dirs: Optional[List[str]] = None,
) -> Dict[str, object]:
    doc = parse_asc(path)
    warnings: List[str] = []
    if not force_fallback:
        binary = resolve_ltspice_binary(ltspice_binary)
        if binary:
            try:
                return {
                    "mode": "ltspice",
                    "netlist": extract_netlist_with_ltspice(path, binary),
                    "unresolved": [],
                    "warnings": warnings,
                }
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                warnings.append(str(exc))
        else:
            warnings.append("No LTspice binary found; using geometric fallback.")

    fallback = _build_geometric_netlist(doc, symbol_dirs=symbol_dirs)
    # Extend rather than replace: the fallback reports its own warnings about
    # approximate pin data and disconnected components.
    fallback["warnings"] = warnings + list(fallback.get("warnings", []))
    return fallback


def run_roundtrip(corpus: str) -> int:
    root = Path(corpus)
    failures = 0
    checked = 0
    for path in root.rglob("*.asc"):
        checked += 1
        doc = parse_asc(str(path))
        doc.assert_semantic_counts()
        if doc.buffer.to_bytes() != doc.buffer.raw:
            failures += 1
    print(json.dumps({"checked": checked, "failures": failures}, indent=2))
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice ASC reader/writer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    summary = sub.add_parser("summary", help="Print schematic summary as JSON")
    summary.add_argument("path")

    set_value = sub.add_parser("set-value", help="Set SYMATTR Value by InstName")
    set_value.add_argument("path")
    set_value.add_argument("inst_name")
    set_value.add_argument("value")
    set_value.add_argument("--output")

    add_dir = sub.add_parser("add-directive", help="Add TEXT !directive record")
    add_dir.add_argument("path")
    add_dir.add_argument("directive")
    add_dir.add_argument("--x", type=int, default=0)
    add_dir.add_argument("--y", type=int, default=0)
    add_dir.add_argument("--size", type=int, default=2)
    add_dir.add_argument("--output")

    new_p = sub.add_parser("new", help="Create a new empty schematic (Version 4 + SHEET)")
    new_p.add_argument("output")
    new_p.add_argument("--sheet-w", type=int, default=880)
    new_p.add_argument("--sheet-h", type=int, default=680)
    new_p.add_argument(
        "--encoding", default="utf-8", choices=["utf-8", "cp1252", "utf-16le"]
    )
    new_p.add_argument("--newline", default="crlf", choices=["crlf", "lf"])
    new_p.add_argument("--force", action="store_true", help="Overwrite if the file exists")

    add_sym = sub.add_parser("add-symbol", help="Append a SYMBOL block")
    add_sym.add_argument("path")
    add_sym.add_argument("symbol_name")
    add_sym.add_argument("x", type=int)
    add_sym.add_argument("y", type=int)
    add_sym.add_argument("--rotation", default="R0")
    add_sym.add_argument("--inst", help="SYMATTR InstName (e.g. R1, C1, V1)")
    add_sym.add_argument("--value", help="SYMATTR Value (e.g. 10k, 100n, SINE(0 1 1k))")
    add_sym.add_argument(
        "--attr",
        action="append",
        nargs=2,
        metavar=("KEY", "VALUE"),
        default=[],
        help="Extra SYMATTR, e.g. --attr SpiceLine Rser=1 (repeatable)",
    )
    add_sym.add_argument("--output")

    add_wire = sub.add_parser("add-wire", help="Append a WIRE record")
    add_wire.add_argument("path")
    add_wire.add_argument("x1", type=int)
    add_wire.add_argument("y1", type=int)
    add_wire.add_argument("x2", type=int)
    add_wire.add_argument("y2", type=int)
    add_wire.add_argument("--output")

    add_flag_p = sub.add_parser(
        "add-flag", help="Append a FLAG net label ('0' is ground)"
    )
    add_flag_p.add_argument("path")
    add_flag_p.add_argument("x", type=int)
    add_flag_p.add_argument("y", type=int)
    add_flag_p.add_argument("label")
    add_flag_p.add_argument("--output")

    rm_dir = sub.add_parser("remove-directive", help="Remove first directive by prefix")
    rm_dir.add_argument("path")
    rm_dir.add_argument("prefix")
    rm_dir.add_argument("--output")

    roundtrip = sub.add_parser("roundtrip", help="Run read/write semantic and byte checks")
    roundtrip.add_argument("corpus")

    netlist = sub.add_parser(
        "netlist", help="Emit netlist with LTspice or geometric fallback"
    )
    netlist.add_argument("path")
    netlist.add_argument("--ltspice")
    netlist.add_argument("--force-fallback", action="store_true")
    netlist.add_argument("--symbol-dir", action="append", default=[])

    args = parser.parse_args()

    if args.cmd == "summary":
        doc = parse_asc(args.path)
        doc.assert_semantic_counts()
        print(json.dumps(doc.summary(), indent=2))
        return

    if args.cmd == "set-value":
        doc = parse_asc(args.path)
        doc.set_component_value(args.inst_name, args.value)
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "add-directive":
        doc = parse_asc(args.path)
        doc.add_directive(args.directive, args.x, args.y, args.size)
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "new":
        target = Path(args.output)
        if target.exists() and not args.force:
            raise SystemExit(
                f"Refusing to overwrite existing file: {target} (use --force)"
            )
        newline = "\r\n" if args.newline == "crlf" else "\n"
        doc = new_document(
            args.output,
            sheet_w=args.sheet_w,
            sheet_h=args.sheet_h,
            encoding=args.encoding,
            newline=newline,
        )
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "add-symbol":
        doc = parse_asc(args.path)
        doc.add_symbol(
            args.symbol_name,
            args.x,
            args.y,
            rotation=args.rotation,
            inst_name=args.inst,
            value=args.value,
            attrs=args.attr,
        )
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "add-wire":
        doc = parse_asc(args.path)
        doc.add_wire(args.x1, args.y1, args.x2, args.y2)
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "add-flag":
        doc = parse_asc(args.path)
        doc.add_flag(args.x, args.y, args.label)
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "remove-directive":
        doc = parse_asc(args.path)
        doc.remove_directive(args.prefix)
        output = write_asc(doc, args.output)
        print(output)
        return

    if args.cmd == "roundtrip":
        failures = run_roundtrip(args.corpus)
        raise SystemExit(1 if failures else 0)

    if args.cmd == "netlist":
        result = build_netlist(
            args.path,
            ltspice_binary=args.ltspice,
            force_fallback=args.force_fallback,
            symbol_dirs=args.symbol_dir,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
