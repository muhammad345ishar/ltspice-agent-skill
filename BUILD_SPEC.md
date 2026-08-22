# Build Spec — `ltspice` Agent Skill

**Audience:** an LLM coding agent that will build this skill end to end.
**Goal:** a public, GitHub-ready Agent Skill that lets any AI *read, write, and run* LTspice files.
**Status:** format reverse-engineering for `.asc`/`.asy` is **done** — findings below are empirical, not guessed. Everything else is unbuilt.

**Scope, non-negotiable:** the skill must **read, write/edit, and run** LTspice files. A previous build attempt silently reduced this to read-only. If your `SKILL.md` description does not fire on *"change R1 to 10k in this schematic"* and *"simulate this and tell me the output ripple"*, you have built the wrong thing.

**Read order:** Section 9 (build-order amendments) and Section 10 (the `SKILL.md` contract) before you write any code. They exist because a previous attempt failed in specific, avoidable ways, and they override anything earlier in this document that contradicts them.

Do not re-derive Section 2 — it was measured across 4,012 real files. The only re-measurement worth doing is the three items marked unverified in §2.3, §2.1 (`SymbolType` values) and §2.4 (`!` vs `;` split); each is a one-line count. Spend the rest of your effort on Sections 4–10.

---

## 1. Context you need

The repo root contains `examples/` — the full LTspice examples tree, copied from a real installation:

| Extension | Count | Notes |
|---|---|---|
| `.asc` | 3,999 | schematics — your validation corpus |
| `.plt` | 58 | saved plot settings (format not yet analysed) |
| `.asy` | 13 | symbols — small sample, see §7 gap |
| `.lib` | 2 | SPICE model libraries |
| `.raw` / `.log` | **0** | simulation output absent — see §7 gap |

Total ~19 MB. Treat these as read-only fixtures. Never modify a file under `examples/`; copy to a temp dir first.

---

## 2. Confirmed `.asc` / `.asy` grammar

A schematic is a line-oriented text file. Each line is one record whose first whitespace-separated token is the keyword. There is no nesting and no block structure; ordering is loosely significant only in that `WINDOW` and `SYMATTR` records attach to the most recent preceding `SYMBOL`, and `IOPIN` attaches to the preceding `FLAG`.

### 2.1 Record table

Token counts below are exact observed values across the corpus. `n` = occurrences.

| Keyword | Tokens | Form | n | Notes |
|---|---|---|---|---|
| `Version` | 2 | `Version 4` | 4,012 | **Always `4`.** Not a version to branch on; modern LTspice still writes 4. |
| `SHEET` | 4 | `SHEET 1 <w> <h>` | 3,999 | Exactly one per file in this corpus. Multi-sheet files exist in the wild but none here — do not assume single. |
| `WIRE` | 5 | `WIRE x1 y1 x2 y2` | 166,030 | A single orthogonal segment. **Every coordinate is ≡ 0 mod 16.** |
| `FLAG` | 4 | `FLAG x y <label>` | 45,441 | Net label. `label == "0"` means **ground** (32,705 of them). |
| `IOPIN` | 4 | `IOPIN x y <In\|Out\|BiDir>` | 7 | Hierarchy port. Always follows the `FLAG` at the same coordinates. |
| `SYMBOL` | 5 | `SYMBOL <name> x y <rot>` | 49,681 | `name` may contain a path separator (2,725 do) and is resolved against the symbol search path. |
| `WINDOW` | 6 | `WINDOW <id> x y <just> <size>` | 49,591 | Attribute label placement. See §2.3. |
| `SYMATTR` | **3+** | `SYMATTR <key> <value>` | 102,383 | **Value may contain spaces** — observed up to 68 tokens on one line. Split with maxsplit=2. |
| `TEXT` | **6+** | `TEXT x y <just> <size> <body>` | 6,062 | Body starts at token index 5. See §2.4. |
| `LINE` | 6 or 7 | `LINE Normal x1 y1 x2 y2 [style]` | 318 | Cosmetic. Optional trailing style int (only `2` observed). |
| `RECTANGLE` | 6 or 7 | `RECTANGLE Normal x1 y1 x2 y2 [style]` | 145 | Cosmetic. Corners are not normalised — x2 may be < x1. |
| `CIRCLE` | 6 or 7 | `CIRCLE Normal x1 y1 x2 y2 [style]` | 52 | Bounding box, not centre+radius. |
| `ARC` | 10 or 11 | `ARC Normal x1 y1 x2 y2 x3 y3 x4 y4 [style]` | 22 | Bounding box then two endpoints. |
| `DATAFLAG` | 4 | `DATAFLAG x y "<expr>"` | 8 | On-schematic value readout. All 8 had an empty `""`. |
| `SymbolType` | 2 | `SymbolType <CELL\|BLOCK>` | 13 | `.asy` only. **Verify the value set — I counted these lines but did not record their values.** |
| `PIN` | 5 | `PIN x y <orient> <offset>` | 33 | `.asy` only. Only `NONE` observed; `LEFT/RIGHT/TOP/BOTTOM` exist in the full library. |
| `PINATTR` | 3 | `PINATTR <PinName\|SpiceOrder> <v>` | 66 | `.asy` only. Attaches to preceding `PIN`. |

No other keywords appear. `BUS` and `BUSTAP` are documented elsewhere but absent here — parse defensively, don't crash on unknowns, preserve them verbatim.

### 2.2 Rotation / mirror codes

Eight values, all observed: `R0` (32,062), `R90` (8,401), `R270` (4,163), `M180` (1,864), `M90` (934), `M270` (933), `M0` (857), `R180` (467). `R` = rotation in degrees clockwise; `M` = mirrored then rotated. You need these to compute absolute pin positions from symbol-relative ones.

### 2.3 `WINDOW` id → attribute mapping

Observed ids: `0` (18,735), `3` (20,150), `123` (5,407), `39` (5,116), `40` (150), `38` (33). These map to `InstName`, `Value`, `Value2`, `SpiceLine`, `SpiceLine2`, `SpiceModel` respectively — the mapping is inferred from the relative frequency matching the `SYMATTR` key frequencies, so **confirm it** by checking a few files where a symbol has a `Value2` and a `WINDOW 123`.

Justification values (this is a *superset* of the `TEXT` set — note the `V` prefixed variants, which naive parsers miss): `Left`, `VTop`, `VBottom`, `Right`, `VLeft`, `VRight`, `Center`, `Top`, `Invisible`, `Bottom`, `VCenter`. `Invisible` (52) means the attribute is hidden — surface that in any human-readable summary rather than dropping it.

### 2.4 `TEXT` records

Form is `TEXT x y <just> <size> <body>`, so the body begins at token 5. Justification: `Left` (5,307), `Bottom` (553), `Top` (107), `Center` (72), `Right` (23).

The body's first character is the discriminator: `!` = a SPICE directive (`.tran`, `.ac`, `.param`, `.step`, `.meas`, `.include`…), `;` = a plain comment. **I have not measured the `!` vs `;` split — an off-by-one in my analysis captured the font size instead. Re-measure it; it is a one-liner.**

**Multi-line bodies are encoded as a literal backslash-n inside one physical line** — 594 records do this. Example, verbatim from the corpus:

```
TEXT 272 -40 Left 2 ;Elements added to \ncompute current gain\nGi=I(V3)/I(V4)
```

So one `TEXT` record can hold an entire multi-line SPICE directive block. Any writer must re-escape real newlines back to `\n` or it will produce a file LTspice cannot open.

### 2.5 SYMATTR keys

`InstName` (49,681), `Value` (45,130), `SpiceLine` (3,674), `Type` (1,508), `Description` (1,193), `Value2` (1,077), `SpiceLine2` (99), `Prefix` (22), `SpiceModel` (17), `User1` (11), `Def_Sub` (4). Eleven keys, closed set in this corpus.

### 2.6 Symbol name case is inconsistent

The corpus contains both `res` (16,308) and `RES` (876), `voltage` (7,312) and `VOLTAGE` (852), `ind`/`IND`, `nmos`/`NMOS`. **Symbol lookup must be case-insensitive**, because Windows filesystems are and these files were authored there. On Linux/macOS a case-sensitive lookup silently fails to resolve ~2,000 symbols.

---

## 3. Encoding rules — the part that breaks every naive parser

Measured across the corpus. Get this wrong and roughly 73% of real files either crash your reader or come back mojibake.

**Three coexisting encodings:**

- 2,916 `.asc` files contain bytes above 0x7F that are **not** valid UTF-8. They are cp1252 / latin-1.
- 1,077 `.asc` and all 13 `.asy` files are pure ASCII.
- **6 `.asc` files are UTF-16LE with no BOM** (`examples/Applications/` — `ADG5462F`, `LT6370`, `LT6372-1`, `LTC7132`, `LTC3889`, `LTC3888`). A UTF-8 read of these yields NUL-riddled garbage; a line-split still "works", which is worse, because it fails silently.

**Non-ASCII byte histogram** — the whole set is just eight bytes:

| Byte | Char | n | Where |
|---|---|---|---|
| `0xB5` | `µ` | **10,195** | micro prefix in component values, e.g. `10µ` |
| `0xB0` | `°` | 36 | degrees, in comments |
| `0xB1` | `±` | 31 | tolerances |
| `0xA9` | `©` | 9 | copyright in comments |
| `0xB8` | `¸` | 8 | — |
| `0xFC` | `ü` | 3 | names |
| `0xBC` | `¼` | 2 | — |
| `0xD7` | `×` | 1 | — |

`µ` alone accounts for 99% of it, and it appears in *values you must parse numerically*. `10µ` must become 10e-6.

**Required detection order:**

1. BOM check: `FF FE` → UTF-16LE, `FE FF` → UTF-16BE, `EF BB BF` → UTF-8 with BOM.
2. No BOM but `b[1] == 0 and b[3] == 0` → UTF-16LE. (This is what catches the 6 files. It is a heuristic; it is reliable here because every file starts with the ASCII word `Version`.)
3. Try strict UTF-8.
4. Fall back to cp1252. Never to UTF-8-with-`errors="replace"` — that destroys `µ`.

**Line endings are mixed:** 3,003 CRLF, 1,009 LF. Do not normalise silently.

**Round-trip requirement:** record the detected encoding, the line-ending style, and whether a BOM was present on read, and reuse all three on write. An agent asked to change one resistor value must not rewrite the other 200 lines, flip the file's encoding, or turn `µ` into `?`. This is the single most important correctness property in the whole skill — an AI that corrupts a user's schematic is worse than no tool at all.

---

## 4. Deliverable: repo layout

```
ltspice-skill/
├── SKILL.md                  # entry point, progressive disclosure, < 500 lines
├── README.md                 # GitHub landing page + install instructions
├── LICENSE                   # MIT
├── reference/
│   ├── asc-format.md         # from §2 + §3 of this spec
│   ├── asy-format.md         # symbol files, pin geometry, SpiceOrder
│   ├── raw-format.md         # waveform binary format
│   ├── log-format.md         # .log, .measure results, .step tables, op point
│   ├── spice-dialect.md      # LTspice-specific SPICE syntax and unit suffixes
│   └── cli-automation.md     # headless invocation per platform
├── scripts/
│   ├── ltspice_asc.py        # read/write schematics, extract netlist
│   ├── ltspice_asy.py        # read/write symbols
│   ├── ltspice_raw.py        # read waveform data, export CSV
│   ├── ltspice_log.py        # parse logs and .measure output
│   └── ltspice_run.py        # locate binary, run headless
└── examples/
    └── (2–3 small hand-made .asc files, not the 19 MB corpus)
```

**Constraints on the scripts:** Python 3.8+, **standard library only** — no numpy, no pip install. A skill that needs dependencies fails in half the environments it lands in. Every script must be usable both as an importable module and as a CLI (`python ltspice_raw.py foo.raw --csv out.csv`). Keep each under ~400 lines and readable; an AI will read this code as documentation.

**SKILL.md:** governed entirely by Section 10. Read it before writing the file.

---

## 5. Scripts — required behaviour

### `ltspice_asc.py`
Parse to a structured object model preserving unknown records verbatim. Emit byte-identical output for an unmodified read→write cycle. Provide: list components with instance name, symbol type, value, and any `SpiceLine`; list directives (decoding the `\n` escapes); list net labels; and edit operations (change a value, add/remove a directive) that touch only the affected line.

**Netlist extraction — read this before designing it.** Connectivity is geometric, not declared. Nets form from: coincident `WIRE` endpoints, `WIRE` endpoints touching a symbol pin's absolute position, and `FLAG` labels merging otherwise-separate nets by name. Computing a pin's absolute position needs the pin offsets from the symbol's `.asy` file plus the instance's rotation/mirror code from §2.2. **The stock symbol library (`lib/sym`, ~1,500 files) is not in this repo**, so you cannot resolve pins for most parts.

Two acceptable strategies, in order of preference:
1. If an LTspice binary is available, have it emit the authoritative netlist and parse that. Ground truth beats reimplementation.
2. Otherwise, geometric analysis with a small built-in offset table for the primitives that dominate the corpus — `res`, `cap`, `ind`, `voltage`, `current`, `diode` cover ~85% of all instances. Anything unresolved must be reported as unresolved, not silently dropped. **Silence here is a correctness bug**: a netlist that omits a connection looks just like a netlist that has one.

Also note a subtlety worth documenting: two wires crossing at a point are only connected if there is a junction there. Verify how LTspice treats a T versus an X crossing before asserting either way.

### `ltspice_asy.py`
Symmetric read/write. Extract pins with `PinName` and `SpiceOrder` — `SpiceOrder` is what maps a pin to its position in the generated SPICE card, so it, not the drawing order, defines terminal order.

### `ltspice_raw.py`
**Unvalidated — no `.raw` file exists in this repo.** Write from documented format, then validate against a real file before shipping (§7). Known shape: text header (`Title:`, `Date:`, `Plotname:`, `Flags:`, `No. Variables:`, `No. Points:`, `Offset:`, `Command:`), then a `Variables:` block of tab-indented `index name type` rows, then either `Values:` (ASCII) or `Binary:` followed by the data block.

Quirks to handle and then confirm empirically, each of which produces plausible-looking wrong numbers if missed: the header is often UTF-16LE while ASCII-mode files are not; with `Flags: real` the x-axis variable is float64 while all others are float32 (mixed-width rows — not a uniform array); `Flags: complex` (AC analysis) stores each value as two float64s; some x-axis values come back with the sign bit set and need an absolute value; `fastaccess` transposes the layout to variable-major instead of point-major; and a `.step` run concatenates segments end to end, detectable by the x-axis going non-monotonic.

### `ltspice_log.py`
Parse `.measure` results, `.step` parameter tables, operating-point dumps, solver errors and warnings. The log is the cheapest path to numeric answers and doubles as the cross-check for the raw reader.

### `ltspice_run.py`
Locate the binary and run headless. Windows: `XVIIx64.exe` / `LTspice.exe`, flags `-b -Run`, plus `-ascii` to force a text raw file and `-netlist` to emit a netlist without simulating. macOS: `/Applications/LTspice.app/Contents/MacOS/LTspice`, which supports fewer flags than the Windows build — verify which. Linux: via Wine. Return the paths to the produced `.raw` and `.log`, surface a clear error when no binary is found, and never leave a partial `.raw` looking like a successful run.

---

## 6. Reference docs

`asc-format.md` and `asy-format.md` are largely a rewrite of §2–§3 here, expanded with worked examples pulled from the corpus. `spice-dialect.md` must cover LTspice's unit suffixes and their traps: **`M` means milli, not mega — mega is `Meg`**, and `1M` versus `1Meg` is a thousand-fold error that simulates happily and silently. Also `k`, `u`/`µ`, `n`, `p`, `f`, `g`, `t`, `mil`; suffixes are case-insensitive; trailing junk after a suffix is ignored (`1kohm` parses as 1000). Cover the component letter prefixes, behavioural sources (`B` elements), `.param`/`.step`/`.meas` syntax, and `.include`/`.lib` resolution. `cli-automation.md` covers the per-platform invocation and exit-code behaviour.

---

## 7. Two known gaps — resolve before shipping

1. **No `.raw` or `.log` fixture.** Ask the user to open any schematic in LTspice, run it, and drop the resulting `.raw` and `.log` in. One transient run is enough; a second `.ac` run and one `.step` run would let you validate the complex and stepped paths too. Until then, `ltspice_raw.py` ships marked unvalidated, and the README should say so.
2. **No stock symbol library.** Ask the user to copy `lib/sym` from their LTspice installation (on macOS it is under `~/Library/Application Support/LTspice/`, which is why it wasn't included — that path is not mountable by the agent, so it must be copied manually). This unlocks real pin resolution and gives ~1,500 extra `.asy` files to validate against instead of 13.

Do not paper over either gap by guessing values and presenting them as verified. Mark unvalidated code as unvalidated.

---

## 8. Acceptance criteria

The build is done when:

- Every one of the 3,999 `.asc` files parses with zero exceptions.
- Every one round-trips **byte-identically** through read→write, including the 6 UTF-16LE files, all 2,916 cp1252 files, both line-ending styles, and all 594 escaped-newline `TEXT` records. This is a hard gate; report the exact count that fails rather than an approximation.
- A targeted edit (change one resistor value) alters exactly one line, verified by diff.
- All 13 `.asy` files round-trip byte-identically.
- The raw reader's numbers agree with the `.measure` values in the matching `.log`, once a fixture exists.
- `SKILL.md` triggers on an LTspice question and stays dormant on an unrelated one — test both directions.
- `SKILL.md` contains **zero dangling routes**: every file it names exists in the repo.
- `SKILL.md` contains **zero build-time leakage** — no instructions addressed to the person who commissioned it, no references to the validation corpus, no "say which one to begin with".
- No third-party imports anywhere. `python -c "import ltspice_asc"` works on a bare interpreter.

Report results as counts against this corpus, not as prose claims of success.

---

## 9. Build-order amendments

These correct a plan that was structurally reasonable but sequenced wrong.

**Build the round-trip harness before the parser.** Corpus-wide byte-identical round-trip is not a final exam to run once at the end; it is the inner development loop. Wire up "walk all 3,999 files, read, write, compare bytes, print failure count" *first*, against a stub parser, then develop the real parser until the number reaches zero. Discovering a systematic encoding fault after everything is built wastes the whole build. Same principle for netlisting: if an LTspice binary is available, diff against its emitted netlist continuously, not in one batch at the end.

**The round-trip gate is gameable — close it.** An implementation that stores each line's raw bytes and echoes them back passes byte-identical round-trip with a 100% score while parsing nothing whatsoever. The gate is therefore meaningless alone and must be paired with a semantic assertion on every file: parse it, then independently count `SYMBOL`, `SYMATTR`, `WIRE`, `FLAG` and `TEXT` occurrences with a dumb regex over the decoded text, and assert the object model contains exactly those numbers. Byte-fidelity proves the writer is safe; the count assertion proves the reader actually understood the file. Ship both or neither.

**Mutation API must be semantic, not line-addressed.** Do not expose `edit_line(path, line_no, new_text)`. Line numbers are a fragile handle: any agent using it must first compute the number, and an off-by-one silently corrupts a schematic. Expose intent-level operations — `set_component_value("R1", "10k")`, `add_directive(".tran 10m")`, `remove_directive(...)`, `rename_net(...)` — and keep the line-level surgery private, where the round-trip guarantee protects it. Each operation must alter exactly the lines it needs to and leave every other byte untouched, verified by diff.

**Do not redistribute the corpus.** The 3,999 schematics and the `.lib` models under `examples/` are Analog Devices files that ship with LTspice. They are not ours to republish, and 19 MB of third-party material does not belong in an MIT-licensed public repo. Keep the corpus strictly local as a validation fixture. Ship only two or three small schematics written from scratch for this repo. The README must tell users to point the validation script at their own LTspice installation. This also constrains CI: a fresh clone has no corpus, so any CI job can only exercise the hand-made examples — do not wire up a green badge that appears to prove corpus-wide correctness when it cannot.

**Ignore multi-week estimates.** Prior planning put this at two to three weeks of phases. That is a human-team figure. The corpus is fixed and local, the formats are documented above, and the feedback loop is a single script; padded schedules here tend to produce padded output rather than better code.

---

## 10. The `SKILL.md` contract

A previous attempt produced a plausible-looking `SKILL.md` that was unusable. Every failure below is real and was observed; do not reproduce them. **If a `SKILL.md` is present in this repo when you start, it is that failed attempt — delete it and start from §10.2 rather than editing it.**

### 10.1 What went wrong last time

1. **Dangling routes.** Every branch ended in "route to `scripts/ltspice_asc.py`" or "see `reference/asc-format.md`" while the repo contained neither. An agent following those instructions fails, or worse, quietly improvises its own parser — the precise outcome this skill exists to prevent.
2. **Scope regression in the trigger.** The description read "Read and summarize LTspice files", and the body stated the skill "does not execute simulations by default". Editing disappeared entirely. Since the description is the only text an agent sees before loading, the skill became unreachable for half its intended jobs.
3. **Build-conversation leakage.** The file ended with "To implement: scaffold scripts…" and "say which one to begin with", plus "do not modify files in `examples/`" and a note that numeric validation needs someone to produce a fixture. These address the builder, not the consumer, and make no sense to a stranger who installs the skill from GitHub.
4. **Activation examples in the body.** Fifteen lines of positive and negative trigger examples were placed in the body. The body is only read *after* the agent has decided to load the skill, on the strength of the frontmatter description. Trigger discrimination in the body is dead weight; it must live in the description string.
5. **The critical warning was non-actionable.** The file said "preserve encodings, do not substitute µ" without ever stating what to do. The detection order was absent.
6. **Wrong default output.** It instructed the model to report "counts of records by keyword (WIRE, FLAG, SYMBOL…)". Nobody asks how many wire segments a schematic contains. That is reverse-engineering telemetry leaking into the product.

### 10.2 Required frontmatter

`name` and `description` only. The description is the entire trigger surface, so it must cover all three verbs (read, edit, run), name the concrete extensions, include the phrasings a real user types, and exclude neighbouring tools. Use this as the baseline and improve only if you can do so without losing coverage:

```yaml
---
name: ltspice
description: "Work with LTspice circuit files — read, edit, and simulate. Use when a .asc schematic, .asy symbol, .raw waveform, .log, .net or .plt file is involved, or when asked what a circuit does, to list or change component values, to add or modify SPICE directives (.tran, .ac, .step, .meas), to extract a netlist, to run a simulation headless, or to interpret simulation results and measurements. LTspice only — not KiCad, Altium, Eagle or Multisim."
---
```

### 10.3 Required body

Keep it under roughly 120 lines. It is a router, not a manual: the grammar tables live in `reference/` and must load only when a schematic is actually in play. It must contain, and contain nothing else:

- **One hard warning, stated first, in actionable form:** never read a `.asc`/`.asy` with a plain text `open()`. Use `scripts/ltspice_asc.py`, or if reading manually, apply the detection order from §3 — BOM, then the UTF-16LE no-BOM heuristic, then strict UTF-8, then cp1252 — and never `errors="replace"`, which destroys the `µ` in 10,195 component values. This belongs in `SKILL.md` itself and not only in `reference/`, because a naive `open()` is the mistake an agent makes *before* it thinks to consult a reference file.
- **A routing tree** keyed on what the user has and wants: schematic, symbol, waveform, log, edit request, run request. Each branch names the script to invoke and the reference file for deeper detail. Every named path must exist.
- **A statement of what the default schematic summary should be:** topology and function — supply rails, signal path and stages, component values, what the analysis directives will actually do, and anything unresolved. Explicitly *not* record counts.
- **The honest-failure rule:** when the stock symbol library is missing, when a pin cannot be resolved, or when no LTspice binary is found, say so explicitly. A netlist with a silently omitted connection is indistinguishable from a correct one, which makes silence here a correctness bug.
- **The write-safety rule:** edits go through the semantic API in §9 so untouched bytes stay untouched; never regenerate a schematic wholesale to change one value.

### 10.4 Ordering consequence

Because §8 forbids dangling routes, `SKILL.md` is written **last**, after `scripts/` and `reference/` exist. Sketch the routing tree early as a design aid if useful, but the committed file comes at the end.
