# Authoring a `.asc` from scratch

Use this when the task is to **create a new LTspice schematic**, not edit an existing
one. Read [asc-format.md](asc-format.md) for the record grammar and
[spice-dialect.md](spice-dialect.md) for value/prefix rules first.

## Build with the script, not by hand

Do not free-hand raw coordinate records into a file with a text editor — that is the
positional editing this skill exists to avoid. Use the builder commands in
[../scripts/ltspice_asc.py](../scripts/ltspice_asc.py); each one appends a valid record
and re-parses the file so structure, encoding and record counts stay correct:

```bash
python scripts/ltspice_asc.py new circuit.asc                    # Version 4 + SHEET header
python scripts/ltspice_asc.py add-symbol circuit.asc res 160 96 --inst R1 --value 10k
python scripts/ltspice_asc.py add-wire   circuit.asc 144 112 64 112
python scripts/ltspice_asc.py add-flag   circuit.asc 64 160 0     # label 0 = ground
python scripts/ltspice_asc.py add-directive circuit.asc ".tran 10m"
```

`new` writes LTspice-style bytes (CRLF, ASCII). It refuses to overwrite an existing
file unless `--force`. `--encoding {utf-8,cp1252,utf-16le}` and `--newline {crlf,lf}`
are available but the defaults are what you want.

## Minimal file anatomy

```
Version 4
SHEET 1 880 680
<WIRE / FLAG / SYMBOL / TEXT records, in any order>
```

- `Version 4` and one `SHEET 1 <w> <h>` line are the whole header. `880 680` is the
  usual starting sheet; it grows automatically.
- Record order does not matter — LTspice re-sorts on its next save.
- A `SYMBOL` block needs only the `SYMBOL` line plus its `SYMATTR` lines. **Omit
  `WINDOW` records** — LTspice regenerates them at default positions on open. The
  builder omits them for this reason.

## Coordinate system

- Integer units, origin top-left, **+x is right, +y is DOWN** (screen coordinates,
  not math). A pin above another has the smaller `y`.
- Everything snaps to a **16-unit grid**. Keep symbol origins, wire endpoints and
  flags on multiples of 16 or pins will not meet wires.

## Records you place

| Record | Form | Notes |
|---|---|---|
| Component | `SYMBOL <name> <x> <y> <rot>` | `<name>` is the symbol path under LTspice `lib/sym` without `.asy` (e.g. `res`, `cap`, `ind`, `voltage`, `current`, `diode`, `sw`, `npn`, `nmos`, `UniversalOpamp2`). `<rot>` ∈ R0/R90/R180/R270/M0/M90/M180/M270. |
| Name/value | `SYMATTR InstName R1` / `SYMATTR Value 10k` | The **first letter of InstName must match the device** (R/C/L/V/I/D/Q/M/…) or the netlist is wrong. |
| Wire | `WIRE <x1> <y1> <x2> <y2>` | Endpoints join anything sharing that exact coordinate. |
| Net label | `FLAG <x> <y> <label>` | `label` `0` is ground. Same label anywhere = same net. |
| Directive | `TEXT <x> <y> Left <size> !<directive>` | `!` = SPICE directive, `;` = comment. Use `add-directive`. |
## Connectivity: pins must land on wire endpoints

Two things share a node when their coordinates coincide (unioned across wires) or when
they carry the same `FLAG` label. A **component pin connects only when a wire endpoint
or a flag sits exactly on the pin's absolute coordinate**:

```
pin_abs = (symbol_x, symbol_y) + transform(pin_offset, rotation)
```

The rotation transform is y-down (see `_transform_offset` / `_rotate` in the script):

| rot | (dx, dy) → |
|---|---|
| R0 | (dx, dy) |
| R90 | (dy, −dx) |
| R180 | (−dx, −dy) |
| R270 | (−dy, dx) |
| M0 | mirror x (−dx, dy), then rotate |

So you must know each symbol's pin offsets. Read them from the symbol's `.asy`:

```bash
python scripts/ltspice_asy.py summary /path/to/lib/sym/res.asy   # x, y, SpiceOrder per pin
```

Example — the shipped [my_resistor.asy](../examples/skill_samples/my_resistor.asy) has
pins at offsets `(16,0)` and `(16,96)`: placed at `SYMBOL my_resistor 100 100 R0` its
pins are at `(116,100)` and `(116,196)`; rotated `R90` at `(300,196)` they are at
`(300,180)` and `(396,180)`.

## Pin geometry for stock parts is NOT verified here

`PRIMITIVE_PIN_OFFSETS` in the script is an **unverified guess** — real `res`/`cap`/
`voltage` symbols are drawn vertically, not as the centred horizontal pair the table
assumes. Do not trust auto-derived connectivity for stock parts on its own. To build
stock circuits whose wiring is real:

1. Pass `--symbol-dir <LTspice lib/sym>` so pins come from the actual `.asy`, **or**
2. open the finished file in LTspice to confirm the nodes, **or**
3. define your own symbol whose geometry you know (see [asy-format.md](asy-format.md)).

Never report connectivity you did not verify. A `GEOMETRY FAILURE` warning from
`netlist` means every pin landed on its own node — the wiring is wrong, not the circuit.

## Values: prefer ASCII prefixes

Values use SPICE metric prefixes, and the one that bites everyone is `M`:

- **`M` means milli, not mega.** `10M` is 10 milliohms. For megohms write `10Meg`.
- Prefixes: `f p n u µ m k Meg g t` — `u` and `µ` are both micro; prefer plain ASCII
  `u` so the file stays clean under either cp1252 or utf-8. `add-symbol --value 100n`,
  not `100 nano`.
- Function values are literal strings: `--value "SINE(0 1 1k)"`, `--value "AC 1"`,
  `--value "PULSE(0 5 0 1n 1n 1u 2u)"`. Quote them so the shell keeps the parentheses.

See [spice-dialect.md](spice-dialect.md) for the full prefix/number grammar.

## Worked example: built and verified against a real symbol

Everything below runs against the shipped
[my_resistor.asy](../examples/skill_samples/my_resistor.asy), whose pin offsets
`(16,0)`/`(16,96)` are known — so the netlist that comes back is real ground truth, not
a guess. This is exactly what [../scripts/build_selftest.py](../scripts/build_selftest.py)
proves.

```bash
python scripts/ltspice_asc.py new ladder.asc
python scripts/ltspice_asc.py add-symbol ladder.asc my_resistor 100 100 --inst R1 --value 1k
python scripts/ltspice_asc.py add-symbol ladder.asc my_resistor 100 196 --inst R2 --value 2k
python scripts/ltspice_asc.py add-symbol ladder.asc my_resistor 300 196 --rotation R90 --inst R3 --value 3k
python scripts/ltspice_asc.py add-wire  ladder.asc 300 180 116 196
python scripts/ltspice_asc.py add-flag  ladder.asc 116 100 in
python scripts/ltspice_asc.py add-flag  ladder.asc 116 196 mid
python scripts/ltspice_asc.py add-flag  ladder.asc 116 292 0
python scripts/ltspice_asc.py add-flag  ladder.asc 396 180 out
```

Then confirm the wiring resolved the way you intended — point `netlist` at the folder
holding the real symbol and force the in-process fallback (there is no LTspice binary in
a chat sandbox):

```bash
python scripts/ltspice_asc.py netlist ladder.asc --force-fallback --symbol-dir examples/skill_samples
```

It prints JSON; the `"netlist"` field is the resolved circuit, and `"warnings"` is empty
when every pin found its node:

```json
{ "mode": "geometric-fallback",
  "netlist": "R1 in mid 1k\nR2 mid 0 2k\nR3 mid out 3k",
  "unresolved": [], "warnings": [] }
```

Build with stock `res`/`cap`/`voltage` instead and that same call cannot be trusted from
`PRIMITIVE_PIN_OFFSETS` alone — point `--symbol-dir` at a real LTspice `lib/sym`, or open
the file in LTspice, before you believe the nodes.

## After building — checklist

- [ ] Every pin sits on a wire endpoint or a flag (`netlist` shows no `GEOMETRY FAILURE`).
- [ ] `InstName` first letter matches the device (R/C/L/V/I/D/Q/M/…).
- [ ] Exactly one net is labelled `0` (ground); analyses need a ground reference.
- [ ] Origins, wire endpoints and flags are all on the 16-unit grid.
- [ ] Coordinates and connectivity were verified against a real `.asy` or LTspice — say
      so honestly: state that the file was built and structurally checked but not simulated.

