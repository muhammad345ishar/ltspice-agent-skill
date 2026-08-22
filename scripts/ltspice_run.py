"""Run LTspice headless and return produced artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional


def locate_ltspice(explicit: Optional[str] = None) -> str:
    if explicit and Path(explicit).exists():
        return explicit

    candidates = [
        shutil.which("LTspice"),
        shutil.which("ltspice"),
        shutil.which("XVIIx64.exe"),
        shutil.which("LTspice.exe"),
        "/Applications/LTspice.app/Contents/MacOS/LTspice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "No LTspice binary found. Set --ltspice or install LTspice (or Wine on Linux)."
    )


def run_headless(
    schematic: str,
    ltspice_binary: Optional[str] = None,
    ascii_raw: bool = False,
    timeout_s: int = 300,
) -> dict:
    binary = locate_ltspice(ltspice_binary)
    sch = Path(schematic).resolve()
    if not sch.exists():
        raise FileNotFoundError(f"Schematic not found: {sch}")

    cmd: List[str] = [binary, "-b", "-Run", str(sch)]
    if ascii_raw:
        cmd.insert(1, "-ascii")

    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Headless LTspice run timed out after {timeout_s}s for {sch.name}"
        ) from exc

    duration = time.time() - start
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Headless LTspice run failed: {details}")

    raw_path = sch.with_suffix(".raw")
    log_path = sch.with_suffix(".log")
    if not raw_path.exists() and not log_path.exists():
        raise RuntimeError(
            "LTspice reported success but produced neither .raw nor .log output."
        )

    return {
        "ltspice_binary": binary,
        "schematic": str(sch),
        "duration_s": round(duration, 3),
        "raw": str(raw_path) if raw_path.exists() else None,
        "log": str(log_path) if log_path.exists() else None,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def emit_netlist(
    schematic: str, ltspice_binary: Optional[str] = None, timeout_s: int = 120
) -> dict:
    binary = locate_ltspice(ltspice_binary)
    sch = Path(schematic).resolve()
    cmd = [binary, "-netlist", str(sch)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"LTspice netlist generation timed out after {timeout_s}s for {sch.name}"
        ) from exc
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"LTspice netlist generation failed: {details}")
    net_path = sch.with_suffix(".net")
    if not net_path.exists():
        raise RuntimeError("Netlist command returned success but no .net file was produced.")
    return {
        "ltspice_binary": binary,
        "schematic": str(sch),
        "netlist": str(net_path),
    }


def probe_capabilities(ltspice_binary: Optional[str] = None) -> dict:
    binary = locate_ltspice(ltspice_binary)
    results = {"binary": binary, "commands": {}}
    probes = {
        "help": [binary, "-help"],
        "version": [binary, "-version"],
    }
    for name, cmd in probes.items():
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            results["commands"][name] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except subprocess.TimeoutExpired as exc:
            results["commands"][name] = {"error": f"timeout: {exc}"}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="LTspice headless runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("schematic")
    run.add_argument("--ltspice")
    run.add_argument("--ascii", action="store_true")
    run.add_argument("--timeout", type=int, default=300)

    netlist = sub.add_parser("netlist")
    netlist.add_argument("schematic")
    netlist.add_argument("--ltspice")
    netlist.add_argument("--timeout", type=int, default=120)

    probe = sub.add_parser("probe")
    probe.add_argument("--ltspice")

    args = parser.parse_args()
    if args.cmd == "run":
        print(
            json.dumps(
                run_headless(
                    args.schematic,
                    args.ltspice,
                    ascii_raw=args.ascii,
                    timeout_s=args.timeout,
                ),
                indent=2,
            )
        )
        return
    if args.cmd == "netlist":
        print(
            json.dumps(
                emit_netlist(args.schematic, args.ltspice, timeout_s=args.timeout),
                indent=2,
            )
        )
        return
    if args.cmd == "probe":
        print(json.dumps(probe_capabilities(args.ltspice), indent=2))


if __name__ == "__main__":
    main()
