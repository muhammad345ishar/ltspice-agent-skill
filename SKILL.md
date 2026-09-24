---
name: ltspice
description: "Work with LTspice circuit files — read, edit, create, and simulate. Use when a .asc schematic, .asy symbol, .raw waveform, .log, .net or .plt file is involved, or when asked what a circuit does, to build or create a new schematic from scratch, to list or change component values, to add or modify SPICE directives (.tran, .ac, .step, .meas), to extract a netlist, to run a simulation headless, or to interpret simulation results and measurements. LTspice only — not KiCad, Altium, Eagle or Multisim."
---

Hard warning first: never read `.asc` or `.asy` with a plain `open()` text decode guess. Use [scripts/ltspice_asc.py](scripts/ltspice_asc.py) and [scripts/ltspice_asy.py](scripts/ltspice_asy.py), or manually apply this decode order: BOM, UTF-16LE no-BOM heuristic (`b[1]==0 and b[3]==0`), strict UTF-8, then cp1252. Never use replacement decoding because it corrupts component values containing `µ`.

Second warning: in LTspice, `M` means **milli**, not mega. `1M` is 1/1000 the value of `1Meg`. Before reporting or writing any value with an SI prefix, read [reference/spice-dialect.md](reference/spice-dialect.md).

Routing tree:

1) User has a schematic (`.asc`) and wants to understand or edit it
- Primary script: [scripts/ltspice_asc.py](scripts/ltspice_asc.py)
- Format details: [reference/asc-format.md](reference/asc-format.md)
- Value/prefix rules before quoting or writing numbers: [reference/spice-dialect.md](reference/spice-dialect.md)
- For edits, use semantic operations (`set-value`, directive add/remove), not line-number editing.
- For netlisting, prefer LTspice `-netlist`; if unavailable or timed out, use geometric fallback and report unresolved pins/connections explicitly.
- The fallback's pin offsets for stock parts (`res`, `cap`, `voltage`, …) are **unverified guesses**. Pass `--symbol-dir <LTspice lib/sym>` to resolve them properly. Always read the `warnings` list before quoting connectivity: a `GEOMETRY FAILURE` warning means every pin landed on its own node and the netlist describes a disconnected circuit — report that, do not describe it as the circuit.

2) User wants to create a new schematic (`.asc`) from scratch
- Primary script: [scripts/ltspice_asc.py](scripts/ltspice_asc.py) builder commands — `new`, `add-symbol`, `add-wire`, `add-flag`, `add-directive`. Each appends one valid record and re-parses, so you never hand-place raw coordinate text.
- Read [reference/authoring-asc.md](reference/authoring-asc.md) first: the record grammar, the 16-unit grid, the y-down coordinate/rotation system, and how a component pin only connects when a wire endpoint or flag lands exactly on its absolute pin coordinate.
- Value/prefix rules before writing numbers: [reference/spice-dialect.md](reference/spice-dialect.md).
- Connectivity honesty: stock-part pin offsets are unverified guesses (see branch 1). A schematic built from scratch is not proven wired until you verify — pass `--symbol-dir <LTspice lib/sym>` to `netlist --force-fallback`, or open it in LTspice. Report it as built and structurally checked but not simulated unless you actually verified the nodes.

3) User has a symbol (`.asy`)
- Primary script: [scripts/ltspice_asy.py](scripts/ltspice_asy.py)
- Format details: [reference/asy-format.md](reference/asy-format.md)

4) User has waveform output (`.raw`) or asks for plotted/derived numeric results
- Primary script: [scripts/ltspice_raw.py](scripts/ltspice_raw.py)
- Format details: [reference/raw-format.md](reference/raw-format.md)
- The header's `Offset` field must be **added** to every x value; it is non-zero whenever a transient run delays data collection (`.tran 0 10.02 10` stores times 0..0.02 with `Offset: 10`). `ltspice_raw.py` applies it and reports `x_offset`. If you read the payload by hand instead, times will be wrong by exactly that offset and will still look plausible.
- AC (`Flags: complex`) samples are `[real, imaginary]` pairs. Use `magnitude_phase()` for magnitude/dB/degrees; never report the real part alone as "the value".
- `.step` runs are concatenated in one file. Use the `steps` index ranges to separate them before comparing runs.
- Cross-check measurements with [scripts/ltspice_log.py](scripts/ltspice_log.py) when a `.log` is available, via [scripts/validate_raw_log.py](scripts/validate_raw_log.py).

5) User has a log (`.log`) or asks for `.measure`/solver results
- Primary script: [scripts/ltspice_log.py](scripts/ltspice_log.py)
- Format details: [reference/log-format.md](reference/log-format.md)
- Always check the `errors` list before quoting numbers. A convergence failure invalidates the results that precede it.
- Warnings are not errors: a run with floating-node warnings can still be valid. Do not escalate, but do surface `Less than two connections to node` warnings, which usually indicate a real wiring mistake.
- `settings` carries `temp` and `method`; mention them if the user compares runs.

6) User asks to run simulation or emit authoritative netlist
- Primary script: [scripts/ltspice_run.py](scripts/ltspice_run.py)
- CLI behavior details: [reference/cli-automation.md](reference/cli-automation.md)
- Run `ltspice_run.py probe` first to confirm a usable binary before promising results.

7) User has a netlist (`.net`, `.cir`) or plot settings (`.plt`)
- These are plain text with the same encoding traps as `.asc`. Decode with `read_ltspice_text()` from [scripts/ltspice_common.py](scripts/ltspice_common.py), then read directly. There is no dedicated parser and none is needed.
- A `.net` is the authoritative connectivity when present; prefer it over any geometric netlist inferred from a schematic.
- `.plt` holds plot pane/trace settings only. It contains no circuit or simulation data, so do not infer results from it.

Default schematic summary output:
- Focus on topology and function: power rails, signal path, stages, major component values, and what directives (`.tran`, `.ac`, `.step`, `.meas`) do.
- Include unresolved dependencies (missing symbols, unknown pin mapping, missing binary) explicitly.
- Do not default to record-count telemetry for user-facing answers.

Honest-failure rule:
- If symbol library data is missing and a pin/net cannot be resolved, state that it is unresolved.
- If the LTspice binary is missing, state that simulation or authoritative netlist generation cannot run.
- Never silently omit unresolved connections from a netlist-like answer.
- `.raw` and `.log` reading is verified against one real LTspice 17.2.4 transient run plus spec-derived fixtures. AC/complex, `fastaccess`, `.step` segmentation and `.measure` parsing have **not** been checked against real output — say so if an answer depends on them. `.asc`/`.asy` handling is verified on a 4,013-file corpus.

Write-safety rule:
- Apply targeted semantic edits only.
- Preserve untouched bytes (encoding/BOM/newline style and unchanged lines).
- Never regenerate an entire schematic when changing one component value or one directive.
- When creating a new schematic, build it with the `new`/`add-symbol`/`add-wire`/`add-flag`/`add-directive` commands rather than hand-writing coordinate records; each append re-parses, so structure, encoding and record counts stay correct. See [reference/authoring-asc.md](reference/authoring-asc.md).
- After any edit, confirm the change read back. See [scripts/mutation_gate.py](scripts/mutation_gate.py) for the property an edit must satisfy: exactly one changed line, correct readback, encoding/BOM/newline intact.
