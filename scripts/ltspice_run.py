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


def _is_fresh(path: Path, started_at: float) -> bool:
    """True if the file exists and was written by the run that began at started_at.

    Existence alone is not enough: LTspice writes output next to the schematic,
    so a previous run's .raw/.log is usually already sitting there. Combined with
    LTspice's habit of returning exit code 0 even when it produced nothing, an
    existence-only check hands back last run's results as if they were current.
    The 2 s slack absorbs filesystem timestamp granularity.
    """
    if not path.exists():
        return False
    return path.stat().st_mtime >= started_at - 2.0


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

    raw_path = sch.with_suffix(".raw")
    log_path = sch.with_suffix(".log")
    pre_existing = [p.name for p in (raw_path, log_path) if p.exists()]

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

    raw_fresh = _is_fresh(raw_path, start)
    log_fresh = _is_fresh(log_path, start)
    if not raw_fresh and not log_fresh:
        if pre_existing:
            raise RuntimeError(
                "LTspice reported success but wrote no new output. Files "
                f"{', '.join(pre_existing)} exist but predate this run, so they are "
                "results from an earlier simulation and must not be reported as "
                "current. Check the .log for a convergence or model error."
            )
        raise RuntimeError(
            "LTspice reported success but produced neither .raw nor .log output."
        )

    return {
        "ltspice_binary": binary,
        "schematic": str(sch),
        "duration_s": round(duration, 3),
        "raw": str(raw_path) if raw_fresh else None,
        "log": str(log_path) if log_fresh else None,
        # Output LTspice did not refresh this run; stale, do not read as current.
        "stale_outputs": [
            p.name
            for p, fresh in ((raw_path, raw_fresh), (log_path, log_fresh))
            if p.exists() and not fresh
        ],
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def emit_netlist(
    schematic: str, ltspice_binary: Optional[str] = None, timeout_s: int = 120
) -> dict:
    binary = locate_ltspice(ltspice_binary)
    sch = Path(schematic).resolve()
    cmd = [binary, "-netlist", str(sch)]
    net_path = sch.with_suffix(".net")
    existed = net_path.exists()
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"LTspice netlist generation timed out after {timeout_s}s for {sch.name}"
        ) from exc
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"LTspice netlist generation failed: {details}")
    if not _is_fresh(net_path, start):
        if existed:
            raise RuntimeError(
                f"LTspice returned success but did not rewrite {net_path.name}; the "
                "existing file is from an earlier run and would be a stale netlist."
            )
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
