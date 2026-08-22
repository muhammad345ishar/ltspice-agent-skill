"""Parse LTspice .raw waveform files.

Layout notes that drive this implementation:

* The header is text (often UTF-16LE from LTspice XVII), terminated by a
  ``Binary:`` or ``Values:`` marker line. Everything after it is payload.
* ``Flags: real`` interleaves one point at a time. The x-axis column is a
  float64; remaining columns are usually float32.
* ``Flags: complex`` (AC analysis) stores every value as two float64s
  (real, imaginary) -- including the frequency column.
* ``Flags: fastaccess`` transposes the payload: each variable's complete
  array is stored contiguously instead of point-by-point.
* LTspice sometimes sets the sign bit on the x-axis float64. Time and
  frequency are physically non-negative, so the magnitude is taken for
  those axes only -- a DC sweep's x-axis may legitimately be negative and
  must not be touched.

Rather than trusting the column-width convention, the payload length is
matched against the candidate layouts. If none matches exactly the file is
rejected with the arithmetic, because returning plausible-looking garbage
from a misread waveform is worse than failing.
"""

from __future__ import annotations

import argparse
import cmath
import csv
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# x-axis types that are physically non-negative, so a set sign bit is a
# storage quirk rather than data.
_UNSIGNED_AXES = {"time", "frequency"}


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
    # Only the header is text; decoding the whole file will trip over the
    # payload, so probe a bounded prefix.
    probe = raw[:4096]
    try:
        probe.decode("utf-8", errors="strict")
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
    end_lf = raw.find(lf, pos)
    # Take whichever terminator comes first; a CRLF later in the payload
    # must not win over the LF that actually ends the marker line.
    candidates = [p + len(t) for p, t in ((end_crlf, crlf), (end_lf, lf)) if p >= 0]
    if candidates:
        return min(candidates)
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
    metadata: Dict[str, str] = {}
    variables: List[RawVariable] = []
    in_vars = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "Variables:":
            in_vars = True
            continue
        if not stripped:
            continue
        # Variable rows are indented. Accept tabs or spaces, and accept a
        # missing type column rather than dropping the variable silently.
        if in_vars and line[:1] in ("\t", " "):
            parts = stripped.split(None, 2)
            if parts and parts[0].isdigit():
                variables.append(
                    RawVariable(
                        index=int(parts[0]),
                        name=parts[1] if len(parts) > 1 else f"V{parts[0]}",
                        var_type=parts[2] if len(parts) > 2 else "unknown",
                    )
                )
                continue
        if ":" in line and line[:1] not in ("\t", " "):
            in_vars = False
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata, variables


def _infer_layout(
    payload_len: int, variable_count: int, point_count: int, complex_mode: bool
) -> Tuple[str, int, int]:
    """Pick the column widths whose total size matches the payload exactly."""
    if variable_count <= 0 or point_count <= 0:
        raise ValueError(
            f"RAW header unusable: No. Variables={variable_count}, No. Points={point_count}."
        )

    if complex_mode:
        candidates = [("complex128", 16, 16)]
    else:
        candidates = [
            ("float64_x_float32_vars", 8, 4),
            ("float64_all", 8, 8),
            ("float32_all", 4, 4),
        ]

    sizes = []
    for name, x_size, var_size in candidates:
        need = point_count * (x_size + var_size * (variable_count - 1))
        sizes.append((name, x_size, var_size, need))
        if need == payload_len:
            return name, x_size, var_size

    # LTspice may leave a trailing newline after the payload.
    for name, x_size, var_size, need in sizes:
        if 0 <= payload_len - need <= 4:
            return name, x_size, var_size

    detail = ", ".join(f"{name} needs {need}" for name, _x, _v, need in sizes)
    raise ValueError(
        f"RAW payload is {payload_len} bytes, which matches no known layout "
        f"for {variable_count} variables x {point_count} points ({detail}). "
        "The file may be truncated or use an unrecognised format."
    )


def _read_scalar(payload: bytes, offset: int, size: int) -> float:
    fmt = "<d" if size == 8 else "<f"
    return struct.unpack_from(fmt, payload, offset)[0]


def _parse_binary(
    payload: bytes,
    variable_count: int,
    point_count: int,
    x_size: int,
    var_size: int,
    complex_mode: bool,
    fastaccess: bool,
) -> List[List[object]]:
    rows: List[List[object]] = [[None] * variable_count for _ in range(point_count)]

    def value_at(offset: int, size: int) -> object:
        if complex_mode:
            real_v, imag_v = struct.unpack_from("<dd", payload, offset)
            return [real_v, imag_v]
        return _read_scalar(payload, offset, size)

    if fastaccess:
        # Transposed: variable 0's whole array, then variable 1's, ...
        offset = 0
        for col in range(variable_count):
            size = x_size if col == 0 else var_size
            for point in range(point_count):
                rows[point][col] = value_at(offset, size)
                offset += size
    else:
        offset = 0
        for point in range(point_count):
            for col in range(variable_count):
                size = x_size if col == 0 else var_size
                rows[point][col] = value_at(offset, size)
                offset += size
    return rows


def _parse_ascii_values(
    payload: bytes, variable_count: int, encoding: str, complex_mode: bool
) -> List[List[object]]:
    """Read the ``Values:`` text payload.

    Layout is one block per point: the first line is ``index<TAB>xvalue``
    and each following line holds one further value, indented. Continuation
    lines therefore carry a single token and must not be skipped.
    """
    text = payload.decode(encoding, errors="strict")

    def convert(token: str) -> object:
        if complex_mode:
            # Complex samples are written as "real,imag".
            if "," in token:
                real_part, imag_part = token.split(",", 1)
                return [float(real_part), float(imag_part)]
            return [float(token), 0.0]
        return float(token)

    rows: List[List[object]] = []
    row: List[object] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        indented = line[:1] in ("\t", " ")
        parts = line.split()
        if not indented:
            # Start of a new point block: drop the leading point index.
            if len(parts) < 2:
                continue
            if row:
                rows.append(row)
            row = []
            tokens = parts[1:]
        else:
            tokens = parts
        for token in tokens:
            try:
                row.append(convert(token))
            except ValueError:
                continue
        if len(row) == variable_count:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _x_scalar(value: object) -> float:
    if isinstance(value, list):
        return float(value[0])
    return float(value)


def _find_steps(x_values: Sequence[float]) -> List[List[int]]:
    """Split a concatenated .step run into segments where the x-axis restarts."""
    if not x_values:
        return []
    boundaries = [0]
    for index in range(1, len(x_values)):
        if x_values[index] < x_values[index - 1]:
            boundaries.append(index)
    boundaries.append(len(x_values))
    return [
        [boundaries[i], boundaries[i + 1]] for i in range(len(boundaries) - 1)
    ]


def parse_raw(path: str) -> Dict[str, object]:
    raw = Path(path).read_bytes()
    encoding = _detect_header_encoding(raw)
    header_bytes, payload, mode = _split_header_payload(raw, encoding)
    header_text = header_bytes.decode(encoding, errors="strict")
    metadata, variables = _parse_header(header_text)

    variable_count = int(metadata.get("No. Variables", len(variables) or 0))
    point_count = int(metadata.get("No. Points", 0))
    flags = metadata.get("Flags", "")
    flags_lower = flags.lower()
    complex_mode = "complex" in flags_lower
    fastaccess = "fastaccess" in flags_lower

    layout: Optional[str] = None
    if mode == "values":
        rows = _parse_ascii_values(payload, variable_count, encoding, complex_mode)
    else:
        layout, x_size, var_size = _infer_layout(
            len(payload), variable_count, point_count, complex_mode
        )
        rows = _parse_binary(
            payload,
            variable_count,
            point_count,
            x_size,
            var_size,
            complex_mode,
            fastaccess,
        )

    # LTspice may set the sign bit on a non-negative x-axis.
    x_type = variables[0].var_type.lower() if variables else ""
    x_values = [_x_scalar(row[0]) for row in rows if row]
    if x_type in _UNSIGNED_AXES:
        x_values = [abs(value) for value in x_values]

    # The `Offset:` header is the constant that was SUBTRACTED from the x axis
    # before storage, so true_x = stored_x + Offset. LTspice writes it when a
    # transient run delays data collection: `.tran 0 10.02 10` saves the window
    # t = 10 s .. 10.02 s but stores 0 .. 0.02 with `Offset: 1.0e+01`. Ignoring
    # it silently reports every time 10 s early -- verified against a real
    # LTspice 17.2.4 run, which is the only reason this is here.
    #
    # Applied after the sign-bit abs() above (the quirk is in the stored bits,
    # not the true value) and regardless of axis type, because the offset is a
    # property of the x axis rather than of time specifically.
    x_offset = 0.0
    offset_text = metadata.get("Offset")
    offset_note: Optional[str] = None
    if offset_text:
        try:
            x_offset = float(offset_text)
        except ValueError:
            offset_note = (
                f"Offset header {offset_text!r} is not a number; x values are as "
                "stored and may be shifted from true simulation time."
            )
    if x_offset:
        x_values = [value + x_offset for value in x_values]
        offset_note = (
            f"x values shifted by Offset {x_offset!r} to give true "
            f"{x_type or 'x'} values."
        )

    for row, value in zip(rows, x_values):
        if isinstance(row[0], list):
            row[0][0] = value
        else:
            row[0] = value

    steps = _find_steps(x_values)

    return {
        "path": path,
        "header_encoding": encoding,
        "mode": mode,
        "binary_layout": layout,
        "complex": complex_mode,
        "fastaccess": fastaccess,
        "metadata": metadata,
        "variables": [v.__dict__ for v in variables],
        "points_expected": point_count,
        "points_parsed": len(rows),
        "x_offset": x_offset,
        "x_offset_note": offset_note,
        "x_values": x_values,
        "steps": steps,
        "step_count": len(steps),
        "values_preview": rows[:10],
        "values": rows,
        "value_shape": (
            "each value is [real, imaginary]" if complex_mode else "each value is a float"
        ),
    }


def magnitude_phase(value: object) -> Tuple[float, float, float]:
    """Return (magnitude, dB, degrees) for a complex ``[re, im]`` sample."""
    if isinstance(value, list):
        number = complex(value[0], value[1])
    else:
        number = complex(float(value), 0.0)
    magnitude = abs(number)
    decibels = 20.0 * cmath.log10(magnitude).real if magnitude > 0 else float("-inf")
    degrees = cmath.phase(number) * 180.0 / cmath.pi
    return magnitude, decibels, degrees


def export_csv(path: str, csv_path: str) -> None:
    parsed = parse_raw(path)
    variables = parsed["variables"]
    values = parsed["values"]
    if not variables:
        raise ValueError("No variable table found in RAW header.")

    is_complex = bool(parsed["complex"])
    header: List[str] = [variables[0]["name"]]
    for variable in variables[1:]:
        name = variable["name"]
        if is_complex:
            header.extend([f"{name}_re", f"{name}_im", f"{name}_mag", f"{name}_db", f"{name}_deg"])
        else:
            header.append(name)

    with Path(csv_path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in values:
            out: List[object] = [_x_scalar(row[0])]
            for value in row[1:]:
                if is_complex:
                    magnitude, decibels, degrees = magnitude_phase(value)
                    real_part = value[0] if isinstance(value, list) else value
                    imag_part = value[1] if isinstance(value, list) else 0.0
                    out.extend([real_part, imag_part, magnitude, decibels, degrees])
                else:
                    out.append(value)
            writer.writerow(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice RAW parser")
    sub = parser.add_subparsers(dest="cmd", required=True)

    summary = sub.add_parser("summary")
    summary.add_argument("path")
    summary.add_argument(
        "--no-values",
        action="store_true",
        help="omit the sample arrays (default prints a 10-point preview only)",
    )
    summary.add_argument(
        "--all-values", action="store_true", help="include every sample in the JSON"
    )

    to_csv = sub.add_parser("csv")
    to_csv.add_argument("path")
    to_csv.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.cmd == "summary":
        data = parse_raw(args.path)
        # Full waveform arrays are huge; keep stdout usable by default.
        if not args.all_values:
            data.pop("values", None)
            data.pop("x_values", None)
        if args.no_values:
            data.pop("values", None)
            data.pop("values_preview", None)
            data.pop("x_values", None)
        print(json.dumps(data, indent=2))
        return
    if args.cmd == "csv":
        export_csv(args.path, args.output)
        print(args.output)


if __name__ == "__main__":
    main()
