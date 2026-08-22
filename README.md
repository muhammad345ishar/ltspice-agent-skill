# ltspice Agent Skill

An Agent Skill for working with LTspice files: **read, edit, and run**.

GitHub repository: https://github.com/muhammad345ishar/ltspice-agent-skill

## What this repository provides

- [SKILL.md](/Users/muhammadishar/Projects/Skills/SKILL.md) routing instructions for AI agents.
- Standard-library Python scripts in [scripts/](/Users/muhammadishar/Projects/Skills/scripts):
  - [ltspice_asc.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asc.py): parse/edit `.asc`.
  - [ltspice_asy.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_asy.py): parse `.asy`.
  - [ltspice_raw.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_raw.py): parse/export `.raw` (**implemented, unvalidated without fixtures**).
  - [ltspice_log.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_log.py): parse `.log`.
  - [ltspice_run.py](/Users/muhammadishar/Projects/Skills/scripts/ltspice_run.py): headless simulation and netlist emission.
  - [roundtrip_harness.py](/Users/muhammadishar/Projects/Skills/scripts/roundtrip_harness.py): corpus-wide round-trip and semantic checks.
  - [validate_raw_log.py](/Users/muhammadishar/Projects/Skills/scripts/validate_raw_log.py): RAW/LOG structural validation helper.
- Format references in [reference/](/Users/muhammadishar/Projects/Skills/reference).

## Quick start

```bash
python scripts/ltspice_asc.py summary path/to/circuit.asc
python scripts/ltspice_asc.py set-value path/to/circuit.asc R1 10k --output /tmp/circuit.asc
python scripts/ltspice_asc.py add-directive path/to/circuit.asc ".tran 10m" --output /tmp/circuit.asc
python scripts/ltspice_asc.py netlist path/to/circuit.asc --force-fallback
python scripts/ltspice_log.py path/to/circuit.log
python scripts/ltspice_raw.py summary path/to/circuit.raw --no-values
python scripts/ltspice_run.py probe
python scripts/ltspice_run.py run path/to/circuit.asc --timeout 300
```

## Validation

Run the harness on your local LTspice corpus:

```bash
python scripts/roundtrip_harness.py /path/to/examples
```

This reports exact parse/round-trip failure counts for `.asc` and `.asy`.

## Known validation gaps

1. `.raw` parser should be validated with real fixtures (`.raw` + matching `.log`) from your LTspice installation:

```bash
python scripts/validate_raw_log.py path/to/circuit.raw path/to/circuit.log
```
2. Full pin-resolution netlisting quality improves when the stock LTspice symbol library (`lib/sym`) is available locally.

## Important encoding behavior

`.asc`/`.asy` files can be UTF-16LE (including no-BOM), UTF-8, or cp1252. Scripts preserve:

- detected encoding,
- BOM presence,
- original line endings (`CRLF` vs `LF`).

This prevents silent schematic corruption during targeted edits.

## Corpus note

If you publish this repository, do not redistribute third-party LTspice example/model corpora. Keep validation corpora local and ship only hand-written sample schematics, like those under [examples/skill_samples/](/Users/muhammadishar/Projects/Skills/examples/skill_samples).
