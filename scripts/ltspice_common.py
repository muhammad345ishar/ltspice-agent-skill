"""Shared utilities for LTspice text files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class TextFileBuffer:
    path: Path
    raw: bytes
    text: str
    encoding: str
    bom: bytes
    newline: str
    lines: List[str]
    has_trailing_newline: bool

    def to_bytes(self) -> bytes:
        content = self.newline.join(self.lines)
        if self.has_trailing_newline:
            content += self.newline
        encoded = content.encode(self.encoding)
        return self.bom + encoded


def detect_encoding(raw: bytes) -> Tuple[str, bytes]:
    if raw.startswith(b"\xff\xfe"):
        return "utf-16le", b"\xff\xfe"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16be", b"\xfe\xff"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8", b"\xef\xbb\xbf"
    if len(raw) > 3 and raw[1] == 0 and raw[3] == 0:
        return "utf-16le", b""
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8", b""
    except UnicodeDecodeError:
        return "cp1252", b""


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def split_lines(text: str) -> List[str]:
    lines = text.splitlines()
    return lines


def read_ltspice_text(path: str) -> TextFileBuffer:
    p = Path(path)
    raw = p.read_bytes()
    encoding, bom = detect_encoding(raw)
    payload = raw[len(bom) :] if bom else raw
    text = payload.decode(encoding, errors="strict")
    newline = detect_newline(text)
    has_trailing_newline = text.endswith("\r\n") or text.endswith("\n")
    lines = split_lines(text)
    return TextFileBuffer(
        path=p,
        raw=raw,
        text=text,
        encoding=encoding,
        bom=bom,
        newline=newline,
        lines=lines,
        has_trailing_newline=has_trailing_newline,
    )


def write_ltspice_text(buffer: TextFileBuffer, output_path: Optional[str] = None) -> Path:
    target = Path(output_path) if output_path else buffer.path
    target.write_bytes(buffer.to_bytes())
    return target
