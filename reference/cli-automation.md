# LTspice CLI automation

Behaviour documented here matches [../scripts/ltspice_run.py](../scripts/ltspice_run.py).
Read that script rather than guessing flags: LTspice's command line is
undocumented by Analog Devices and differs between builds.

## Locating the binary

`locate_ltspice(explicit)` tries, in order:

1. the path passed as `--ltspice` (used only if it exists on disk)
2. `LTspice` / `ltspice` on `PATH`
3. `XVIIx64.exe` / `LTspice.exe` on `PATH` (Windows, and Wine shims on Linux)
4. `/Applications/LTspice.app/Contents/MacOS/LTspice` (macOS)

If none exist it raises `FileNotFoundError`. Do not fall back to "probably
installed" behaviour — a missing binary must be reported, because the only
alternative to a real run is the geometric netlist fallback, which is a weaker
answer and must be labelled as such.

Run `python scripts/ltspice_run.py probe` before promising results. It invokes
`-help` and `-version` and returns each return code and output verbatim. Some
builds return non-zero for `-help` or print nothing at all; that is not itself a
failure, it just means capability cannot be confirmed in advance.

## Flags actually used

| Invocation | Purpose |
|---|---|
| `<binary> -b -Run <schematic.asc>` | headless batch simulation |
| `<binary> -ascii -b -Run <schematic.asc>` | same, but write a text `.raw` |
| `<binary> -netlist <schematic.asc>` | emit `<schematic>.net` and exit |

`-b` is batch (no GUI). `-Run` starts the simulation immediately. `-ascii` is
inserted **before** `-b`, matching what the script does; it makes the `.raw`
human-readable at a large size cost, so prefer binary `.raw` unless you need to
inspect the file by eye.

Output always lands **next to the schematic**, not in the working directory:
`circuit.asc` produces `circuit.raw`, `circuit.log`, `circuit.net`. There is no
flag to redirect this, so copy the schematic to a scratch directory first if the
source tree must stay clean.

## Platform notes

Windows uses `XVIIx64.exe` (LTspice XVII) or `LTspice.exe` (LTspice 24+).

macOS ships the app bundle above. The macOS build accepts `-b -Run`, but option
coverage lags the Windows build; if a flag appears to be ignored, verify by
checking whether the expected output file was actually written rather than by
trusting the return code.

Linux has no native build — run the Windows executable under Wine. Path
translation applies: Wine sees the schematic through its own drive mapping, so
pass a path Wine can resolve, and expect the output files to appear at the
Linux-side location of that same path.

## Failure handling

Three failure modes matter, and only the first is obvious.

**Missing binary.** Surfaced as `FileNotFoundError` from `locate_ltspice`. State
plainly that simulation and authoritative netlist generation cannot run.

**Hang.** Every invocation runs under a `subprocess.run(timeout=...)` — 300 s
default for a run, 120 s for a netlist. A blocked LTspice (modal error dialog,
missing model prompting for input) never returns on its own, so the timeout is
what turns a hang into a reportable error rather than a stalled agent.

**Success with no fresh output — the dangerous one.** LTspice frequently returns
exit code 0 after failing to simulate. Because output is written next to the
schematic, a previous run's `.raw`/`.log`/`.net` is usually already sitting
there, so *checking that the file exists proves nothing*. An existence-only
check hands back last run's numbers as if they were current, which is worse than
an error: the results look plausible and are wrong.

`_is_fresh(path, started_at)` therefore requires `st_mtime >= started_at - 2.0`
(the slack absorbs filesystem timestamp granularity). Consequences:

- `run_headless` returns `None` for `raw` or `log` that was not refreshed, and
  lists the file under `stale_outputs`. **Always check `stale_outputs` before
  reading any result file.**
- If neither `.raw` nor `.log` is fresh it raises. The message distinguishes "no
  output at all" from "output exists but predates this run", because the latter
  means a real simulation error is described in a `.log` you must not quote.
- `emit_netlist` raises rather than returning a `.net` path that LTspice did not
  rewrite, for the same reason.

A non-zero return code raises with `stderr`, falling back to `stdout` — LTspice
sometimes reports errors on stdout.

## Return shapes

`run_headless` returns `ltspice_binary`, `schematic`, `duration_s`, `raw`,
`log`, `stale_outputs`, `stdout`, `stderr`.

`emit_netlist` returns `ltspice_binary`, `schematic`, `netlist`.

`probe_capabilities` returns `binary` and a `commands` map of `help`/`version`
to `{returncode, stdout, stderr}` or `{error}` on timeout.
