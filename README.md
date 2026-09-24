# ltspice Agent Skill

An Agent Skill that lets an AI **read, edit, create, and run** LTspice files —
schematics (`.asc`), symbols (`.asy`), waveforms (`.raw`), logs (`.log`) and
netlists (`.net`). It edits existing schematics without disturbing their bytes, and
builds new ones from scratch record by record.

Pure Python standard library, no dependencies. Python 3.8+.

GitHub: https://github.com/muhammad345ishar/ltspice-agent-skill

## Why this exists

LTspice files break naive tooling in specific, repeatable ways:

- `.asc` files may be **UTF-16LE with no BOM**. A plain `open()` either throws or
  silently mangles the file.
- Component values contain `µ` (`0xB5` in cp1252). Decoding with
  `errors="replace"` turns `1µF` into `1?F` — a 1e6 error that still parses.
- In LTspice, **`M` means milli, not mega**. `1MHz` is one millihertz.
- Editing a schematic by line number corrupts it, because a `SYMBOL` block's
  attributes are interleaved with `WINDOW` records.

Every script here preserves encoding, BOM and line endings byte-for-byte, and
edits are semantic rather than positional.

## Contents

- [SKILL.md](SKILL.md) — routing instructions the agent reads.
- [scripts/](scripts) — the implementation:
  - [ltspice_asc.py](scripts/ltspice_asc.py) — parse, summarise, edit, build and netlist `.asc`
  - [ltspice_asy.py](scripts/ltspice_asy.py) — parse and write `.asy` symbols
  - [ltspice_raw.py](scripts/ltspice_raw.py) — parse and CSV-export `.raw` waveforms
  - [ltspice_log.py](scripts/ltspice_log.py) — parse `.log` measurements and errors
  - [ltspice_run.py](scripts/ltspice_run.py) — headless simulation and netlist emission
  - [ltspice_common.py](scripts/ltspice_common.py) — encoding-safe text I/O
- [reference/](reference) — format documentation, loaded on demand:
  [asc](reference/asc-format.md) ·
  [asy](reference/asy-format.md) ·
  [raw](reference/raw-format.md) ·
  [log](reference/log-format.md) ·
  [SPICE dialect](reference/spice-dialect.md) ·
  [authoring a new .asc](reference/authoring-asc.md) ·
  [CLI](reference/cli-automation.md)
- Test harnesses:
  [mutation_gate.py](scripts/mutation_gate.py) ·
  [roundtrip_harness.py](scripts/roundtrip_harness.py) ·
  [build_selftest.py](scripts/build_selftest.py) ·
  [raw_selftest.py](scripts/raw_selftest.py) ·
  [log_selftest.py](scripts/log_selftest.py) ·
  [netlist_selftest.py](scripts/netlist_selftest.py) ·
  [validate_raw_log.py](scripts/validate_raw_log.py)

## Install

**Step-by-step, per-platform instructions live in [INSTALL.md](INSTALL.md)** —
Claude (desktop/web/Code), ChatGPT / OpenAI, Google Gemini, agentic coding tools
(Copilot, Cursor, Windsurf, Codex), and a universal fallback for any AI that can run
Python and read files.

The short version — clone into wherever your agent looks for skills:

```bash
git clone https://github.com/muhammad345ishar/ltspice-agent-skill.git ltspice
```

For Claude Code / Claude Desktop, that means a `skills/` directory; the agent
reads `SKILL.md` and pulls in `reference/` files only when it needs them. The
scripts also work standalone from the command line.

## Quick start

```bash
# understand a schematic
python scripts/ltspice_asc.py summary path/to/circuit.asc

# edit it — one line changes, encoding preserved
python scripts/ltspice_asc.py set-value path/to/circuit.asc R1 10k --output out.asc
python scripts/ltspice_asc.py add-directive path/to/circuit.asc ".tran 10m" --output out.asc

# build a new one from scratch — each command appends one valid record
python scripts/ltspice_asc.py new circuit.asc
python scripts/ltspice_asc.py add-symbol circuit.asc res 160 96 --inst R1 --value 10k
python scripts/ltspice_asc.py add-wire   circuit.asc 176 96 176 160
python scripts/ltspice_asc.py add-flag   circuit.asc 176 160 0
python scripts/ltspice_asc.py add-directive circuit.asc ".tran 10m"
# see reference/authoring-asc.md for coordinates, the 16-unit grid and verifying connectivity

# connectivity
python scripts/ltspice_asc.py netlist path/to/circuit.asc          # uses LTspice if present
python scripts/ltspice_asc.py netlist path/to/circuit.asc --force-fallback

# run it
python scripts/ltspice_run.py probe
python scripts/ltspice_run.py run path/to/circuit.asc --timeout 300

# read results
python scripts/ltspice_log.py path/to/circuit.log
python scripts/ltspice_raw.py summary path/to/circuit.raw --no-values
python scripts/ltspice_raw.py csv path/to/circuit.raw --output waves.csv
```

## Validation

`.asc` and `.asy` handling is verified against a local corpus of **4,013 real
LTspice files**:

```bash
python scripts/mutation_gate.py /path/to/your/ltspice/examples
python scripts/roundtrip_harness.py /path/to/your/ltspice/examples
```

Results on that corpus:

| Check | Result |
|---|---|
| `.asc` byte-identical round-trip | 4000 / 4000 |
| `.asy` byte-identical round-trip | 13 / 13 |
| Semantic count assertion | 4000 / 4000 |
| Mutation gate (edit touches exactly one line and reads back) | 3998 / 3998 |

The mutation gate exists because a byte-identical round-trip is on its own a
**gameable** check — an implementation that stores raw lines and echoes them back
passes it while parsing nothing. The gate additionally requires that a semantic
edit changes exactly one line, reads back correctly, and leaves encoding, BOM and
newline style intact. It caught a real bug during development: `set_component_value`
aborted its scan on `WINDOW` records, so on almost every real file it appended a
second `SYMATTR Value` instead of editing the existing one, and the edit silently
did nothing.

`.raw`, `.log` and netlist extraction are covered by self-tests that need no
corpus — they run straight from a fresh clone:

```bash
python scripts/raw_selftest.py      # 154 checks
python scripts/log_selftest.py      #  42 checks
python scripts/netlist_selftest.py  #  13 checks
python scripts/build_selftest.py    #  23 checks — builds a schematic from scratch
python scripts/mutation_gate.py examples/skill_samples
```

`build_selftest.py` is the ground truth for creating files from nothing: it emits a
byte-clean header, appends symbols/wires/flags with the builder commands, and then
rebuilds the `connected_ladder` circuit from scratch and asserts its netlist against
the shipped `my_resistor.asy` — whose pin geometry is known exactly, so the wiring is
checked for real rather than against a self-consistent guess.

The shipped samples under [examples/skill_samples/](examples/skill_samples) are
deliberately chosen to carry the traps that broke earlier versions:
`windowed_rc.asc` has `WINDOW` records, CRLF endings and a cp1252 `µ`;
`utf16_divider.asc` is UTF-16LE with a BOM; `connected_ladder.asc` plus
`my_resistor.asy` form a netlist fixture whose correct output is known by hand,
including a rotated instance. `real_transient_offset.raw` and `.log` are real
LTspice 17.2.4 output — a transient run trimmed to 12 points with the author's
file path scrubbed, otherwise byte-for-byte as LTspice wrote it.

### What real output caught

The `.raw` reader passed 137 spec-derived assertions and was still wrong. The
header carries an `Offset` field that must be **added** to every x value; it is
non-zero whenever a transient run delays data collection. A real run of
`.tran 0 10.02 10` stores times `0 .. 0.02` and puts the missing 10 s in
`Offset`, so the reader reported every event ten seconds early — plausible
numbers, silently wrong. The spec the fixtures were built from described the
field as "informational". One real file exposed it immediately.

That is the argument for shipping real bytes as fixtures rather than only
synthetic ones, and for treating "our tests pass" as weaker evidence than
"it agrees with the tool".

## Known gaps

1. **`.raw`/`.log` are validated against one real run, not all analysis types.**
   A real transient run (`real_transient_offset.raw`/`.log`) covers the binary
   layout, the UTF-16LE no-BOM header, the `Offset` shift, warning classification
   and the settings block. Still checked only against spec-derived fixtures:
   **AC/complex data, `fastaccess`, `.step` segmentation, the ASCII `Values:`
   payload, and `.measure` parsing** — the real log contains no `.meas`
   statements. To close those, run an AC sweep and a `.step` run locally and
   check each pair:

   ```bash
   python scripts/validate_raw_log.py path/to/circuit.raw path/to/circuit.log
   ```
2. **Pin offsets for stock parts are guesses.** `PRIMITIVE_PIN_OFFSETS` in
   `scripts/ltspice_asc.py` has not been checked against the shipped LTspice
   symbol library, and is probably wrong — real `res`/`cap`/`voltage` symbols are
   drawn vertically rather than centred horizontally. Any instance resolved that
   way is reported in `warnings`, and a netlist in which nothing connects to
   anything raises a `GEOMETRY FAILURE` warning rather than being presented as
   the circuit. For trustworthy connectivity, either pass
   `--symbol-dir <path to LTspice lib/sym>` or let LTspice generate the netlist.
   The extraction logic itself — wire-endpoint union, `FLAG` label merging,
   ground naming, the rotation transform and `SpiceOrder` ordering — is verified
   against a known-good fixture by `netlist_selftest.py`.
3. `fastaccess` and all-float64 payload layouts are inferred from payload length
   and exercised synthetically, but have not been seen in a file from disk.

## Encoding behaviour

`.asc`/`.asy` files may be UTF-16LE (with or without BOM), UTF-8 (with or without
BOM), or cp1252. Detection order is: BOM, UTF-16LE no-BOM heuristic
(`b[1]==0 and b[3]==0`), strict UTF-8, then cp1252. Replacement decoding is never
used. Writes preserve the detected encoding, BOM presence and original line
endings, so a one-value edit produces a one-line diff.

## Corpus note

Do not redistribute third-party LTspice example or model libraries — those files
belong to Analog Devices and are not covered by this repository's licence. Keep
validation corpora local; only the hand-written samples under
[examples/skill_samples/](examples/skill_samples) are shipped.

## Licence

MIT — see [LICENSE](LICENSE). Applies to the code and documentation in this
repository only, not to any LTspice file you point it at.
