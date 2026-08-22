---
name: ltspice
description: "Work with LTspice circuit files — read, edit, and simulate. Use when a .asc schematic, .asy symbol, .raw waveform, .log, .net or .plt file is involved, or when asked what a circuit does, to list or change component values, to add or modify SPICE directives (.tran, .ac, .step, .meas), to extract a netlist, to run a simulation headless, or to interpret simulation results and measurements. LTspice only — not KiCad, Altium, Eagle or Multisim."
---

Hard warning first: never read `.asc` or `.asy` with a plain `open()` text decode guess. Use [scripts/ltspice_asc.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asc.py) and [scripts/ltspice_asy.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asy.py), or manually apply this decode order: BOM, UTF-16LE no-BOM heuristic (`b[1]==0 and b[3]==0`), strict UTF-8, then cp1252. Never use replacement decoding because it corrupts component values containing `µ`.

Routing tree:

1) User has a schematic (`.asc`) and wants to understand or edit it
- Primary script: [scripts/ltspice_asc.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asc.py)
- Format details: [reference/asc-format.md](/Users/muhammadishar/Projects/Skills/reference/asc-format.md)
- For edits, use semantic operations (`set-value`, directive add/remove), not line-number editing.
- For netlisting, prefer LTspice `-netlist`; if unavailable or timed out, use geometric fallback and report unresolved pins/connections explicitly.

2) User has a symbol (`.asy`)
- Primary script: [scripts/ltspice_asy.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asy.py)
- Format details: [reference/asy-format.md](/Users/muhammadishar/Projects/Skills/reference/asy-format.md)

3) User has waveform output (`.raw`) or asks for plotted/derived numeric results
- Primary script: [scripts/ltspice_raw.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_raw.py)
- Format details: [reference/raw-format.md](/Users/muhammadishar/Projects/Skills/reference/raw-format.md)
- Cross-check measurements with [scripts/ltspice_log.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_log.py) when `.log` is available.
- Validation helper: [scripts/validate_raw_log.py](/Users/muhammadishar/Projects/Skills/scripts/validate_raw_log.py).

4) User has a log (`.log`) or asks for `.measure`/solver results
- Primary script: [scripts/ltspice_log.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_log.py)
- Format details: [reference/log-format.md](/Users/muhammadishar/Projects/Skills/reference/log-format.md)

5) User asks to run simulation or emit authoritative netlist
- Primary script: [scripts/ltspice_run.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_run.py)
- CLI behavior details: [reference/cli-automation.md](/Users/muhammadishar/Projects/Skills/reference/cli-automation.md)

Default schematic summary output:
- Focus on topology and function: power rails, signal path, stages, major component values, and what directives (`.tran`, `.ac`, `.step`, `.meas`) do.
- Include unresolved dependencies (missing symbols, unknown pin mapping, missing binary) explicitly.
- Do not default to record-count telemetry for user-facing answers.

Honest-failure rule:
- If symbol library data is missing and a pin/net cannot be resolved, state that it is unresolved.
- If LTspice binary is missing, state that simulation or authoritative netlist generation cannot run.
- Never silently omit unresolved connections from a netlist-like answer.

Write-safety rule:
- Apply targeted semantic edits only.
- Preserve untouched bytes (encoding/BOM/newline style and unchanged lines).
- Never regenerate an entire schematic when changing one component value or one directive.
