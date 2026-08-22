# LTspice `.asy` symbol format

A `.asy` file defines one schematic symbol: its drawing, its pins, and the SPICE
card it expands to. Same line-oriented structure and same encoding traps as
`.asc` — decode with `read_ltspice_text()`, never a bare `open()`.

Parsed by `scripts/ltspice_asy.py`.

## Records

Measured across the 13 `.asy` files in the validation corpus:

| Record | Count | Purpose |
|---|---|---|
| `Version` | 13 | format version, first line |
| `SymbolType` | 13 | `CELL` (11) or `BLOCK` (2) |
| `LINE` | 242 | drawing |
| `CIRCLE` | 39 | drawing |
| `ARC` | 20 | drawing |
| `RECTANGLE` | 3 | drawing |
| `PIN` | 33 | pin geometry |
| `PINATTR` | 66 | pin metadata, 2 per pin |
| `SYMATTR` | 33 | symbol metadata |
| `WINDOW` | 9 | attribute text placement |

Every `PIN` in the corpus is followed by exactly one `PINATTR PinName` and one
`PINATTR SpiceOrder` — hence 66 = 2 × 33. Treat that as the expected pairing and
report a symbol that breaks it rather than guessing.

`SymbolType CELL` is an ordinary primitive or model-backed part. `BLOCK` is a
hierarchical block backed by another schematic.

## Pins

```
PIN <x> <y> <orientation> <label_offset>
PINATTR PinName <name>
PINATTR SpiceOrder <n>
```

`x`/`y` are in symbol-local coordinates, relative to the symbol origin, on the
same 16-unit grid as `.asc`.

**`SpiceOrder` determines terminal order in the generated SPICE card, not drawing
order and not file order.** For a `SYMBOL npn` the emitter may be listed first in
the file yet be terminal 3. Sorting pins by anything other than `SpiceOrder`
produces a netlist that is wrong in a way that still simulates.

`orientation` controls where the pin *label* is drawn, not where the pin sits.
Only `NONE` appears in the corpus (33/33), which is what LTspice writes when the
label is hidden. LTspice also accepts `LEFT`, `RIGHT`, `TOP`, `BOTTOM` and the
`V`-prefixed vertical variants, but those are unobserved here — handle them
defensively rather than assuming the set is complete.

## Mapping a pin to an absolute schematic coordinate

This is what netlist extraction depends on. A `SYMBOL` record in the `.asc`
supplies an instance origin and a rotation code:

```
SYMBOL res 240 96 R90
```

The absolute position of each pin is the instance origin plus the pin's local
offset **after applying the instance transform**. As implemented in
`_transform_offset` / `_rotate` in `scripts/ltspice_asc.py`:

| Code | Transform applied to local `(dx, dy)` |
|---|---|
| `R0` | `(dx, dy)` |
| `R90` | `(dy, −dx)` |
| `R180` | `(−dx, −dy)` |
| `R270` | `(−dy, dx)` |
| `M0` | mirror `dx → −dx`, then `R0` |
| `M90` | mirror `dx → −dx`, then `R90` |
| `M180` | mirror `dx → −dx`, then `R180` |
| `M270` | mirror `dx → −dx`, then `R270` |

So a mirror code is "flip in x, then rotate". Note the y-axis points **down** in
LTspice, which is why `R90` maps to `(dy, −dx)` rather than the textbook
`(−dy, dx)`; using the textbook form silently reflects every rotated part.

Two symbol pins land on the same net when their absolute coordinates coincide, or
when a `WIRE` endpoint touches both. Wires only connect at endpoints — a wire
crossing another wire mid-span is **not** a connection.

## Symbol attributes

`SYMATTR <key> <value>` carries the symbol's SPICE identity. Keys that matter:

| Key | Meaning |
|---|---|
| `Prefix` | SPICE element letter (`R`, `C`, `L`, `V`, `Q`, `X`, …) — determines the card type |
| `SpiceModel` | model name to reference |
| `Value` | default value or model name |
| `Value2` | second value field |
| `SpiceLine`, `SpiceLine2` | extra parameters appended to the card |
| `Description` | human-readable text |
| `ModelFile` | `.lib`/`.include` file providing the model |

`Prefix X` means the part expands to a subcircuit call and needs a matching
`.subckt`, usually via `ModelFile`. If that file is not present locally, the pin
mapping cannot be fully resolved — say so rather than guessing.

## Resolving a symbol name from a schematic

`SYMBOL <name> ...` references a `.asy` by relative path without extension, e.g.
`SYMBOL Opamps/opamp2 ...`. Resolution is **case-insensitive**, and `\` and `/`
are interchangeable as separators (files authored on Windows use `\`).
`_normalize_symbol_name()` lowercases and converts separators for this reason.

Search order: the schematic's own directory first, then the LTspice `lib/sym`
tree. Without `lib/sym` present, stock parts resolve to nothing and pin positions
for those instances are unknown — the geometric netlist must report them as
unresolved.

## Writing

- Preserve encoding, BOM and newline style exactly as for `.asc`.
- Preserve unknown record types verbatim; the format has keywords this corpus
  does not exercise.
- Round-trip is verified byte-identical on all 13 corpus symbols
  (`scripts/mutation_gate.py`, check `[2]`).
