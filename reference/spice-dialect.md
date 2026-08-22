# LTspice SPICE dialect: values, prefixes, directives

## The one that silently costs you 1000x

LTspice number parsing is **case-insensitive**, so `M` and `m` are the same
prefix — and that prefix is **milli**.

| Written | Means | Not |
|---|---|---|
| `1M`, `1m` | 1e-3 | ❌ not 1e6 |
| `1Meg`, `1meg`, `1MEG` | 1e6 | |
| `1MHz` | **1e-3** Hz | ❌ not 1 megahertz |
| `1MegHz` | 1e6 Hz | |

`1MHz` parses as one millihertz. This is the single most common misreading of
an LTspice file. When a schematic says `1MHz` the author may well have *meant*
megahertz and written a bug; report the value as LTspice will interpret it, and
flag the ambiguity rather than silently "correcting" it.

## Full prefix table

| Prefix | Multiplier |
|---|---|
| `T` | 1e12 |
| `G` | 1e9 |
| `Meg` | 1e6 |
| `K` | 1e3 |
| *(none)* | 1 |
| `m` / `M` | 1e-3 |
| `u` / `µ` | 1e-6 |
| `n` | 1e-9 |
| `p` | 1e-12 |
| `f` | 1e-15 |

`mil` is a special case: 25.4e-6 (thousandth of an inch).

Trailing characters after a valid prefix are **ignored**, not validated. So
`1kOhm`, `1k`, `1kFoo` and `1kΩ` are all 1000. This means a typo cannot be
detected from the suffix — `1x` is simply 1.

The `µ` character (U+00B5, byte `0xB5` in cp1252) appears in real files. It is
the reason replacement-character decoding is banned: `1µF` decoded with
`errors="replace"` becomes `1?F`, which parses as 1 farad — a 1e6 error.

## Value syntax

A `SYMATTR Value` field may hold more than a number:

- Plain value: `10k`, `4.7u`, `1Meg`
- Model or part name: `2N2222`, `1N4148`, `LT1763`
- Source function: `SINE(0 1 1k)`, `PULSE(0 5 0 1n 1n 1u 2u)`, `PWL(0 0 1m 5)`
- Expression in braces: `{R_load}`, `{2*pi*f0}` — resolved from `.param`
- Behavioural: `V=I(R1)*100`, `I=V(a)*1e-3`

Never assume the field is numeric. Parse defensively and pass unrecognised
forms through verbatim on a write.

## Directives (`TEXT` records beginning `!`)

In a `.asc` file, `TEXT` records starting with `!` are SPICE directives and
those starting with `;` are comments. Measured across the 4,012-file corpus:
4,655 directive records vs 1,411 comment records.

Common directives:

| Directive | Purpose |
|---|---|
| `.tran <tstop>` / `.tran <tstep> <tstop> <tstart> <tmax>` | transient |
| `.ac dec <pts/decade> <fstart> <fstop>` | AC sweep (`dec`, `oct`, `lin`) |
| `.dc <src> <start> <stop> <incr>` | DC sweep |
| `.op` | operating point |
| `.noise <out> <src> dec <pts> <f1> <f2>` | noise |
| `.tf <out> <src>` | transfer function |
| `.step param <name> <start> <stop> <incr>` | parameter sweep |
| `.step param <name> list <v1> <v2> ...` | explicit list |
| `.step temp <start> <stop> <incr>` | temperature sweep |
| `.param <name>=<value>` | define a parameter |
| `.meas` / `.measure` | extract a scalar from results |
| `.include` / `.inc`, `.lib` | pull in models |
| `.model <name> <type>(...)` | define a model |
| `.subckt` / `.ends` | subcircuit |
| `.save <node>` / `.probe` | limit saved data |
| `.options <opt>=<val>` | solver options |
| `.four <freq> <node>` | Fourier / THD |
| `.backanno`, `.end` | housekeeping |

`.step` changes the shape of every result: the `.raw` file becomes several
concatenated runs and `.log` measurements become one row per step. Detect it
before interpreting output.

## `.meas` forms

```
.meas TRAN vpp PP v(out)                       ; peak-to-peak
.meas TRAN vmax MAX v(out) FROM 1m TO 2m       ; windowed
.meas TRAN t_rise TRIG v(out)=1.5 TARG v(out)=3.5
.meas AC gain_db MAX 20*log10(mag(v(out)))
.meas TRAN avg_i AVG I(R1)
.meas vout FIND v(out) AT 500u
```

The analysis keyword (`TRAN`, `AC`, `DC`, `OP`, `NOISE`, `TF`) is optional in
some versions. Results land in the `.log`, not the `.raw`.

## Node naming

- `0` and `GND` are ground. A `FLAG` record with value `0` is a ground symbol.
- Unlabelled nets get auto names `N001`, `N002`, … assigned by LTspice at
  netlist time. These are **not stable** across edits, so never cite an `Nxxx`
  name as a durable identifier.
- Labels are case-insensitive but preserved as written.
- A `FLAG` at a wire endpoint names that net; the same label elsewhere joins
  the two nets without a drawn wire. Missing this is the classic cause of a
  wrong hand-built netlist.

## Expressions

Braces `{}` mark an expression evaluated at parse time, e.g. `{R*2}` or
`{if(x>0, 1, 0)}`. Available functions include `abs`, `sqrt`, `exp`, `ln`,
`log10`, `sin`, `cos`, `tan`, `atan2`, `min`, `max`, `limit`, `if`, `pow`,
`floor`, `ceil`, `table`, `uplim`, `ddt`, `idt`.

`pi` and `e` are predefined. `time` is available in transient expressions.

## Cautions when writing

- Preserve the author's spelling and prefix exactly unless asked to change the
  value. Rewriting `4k7` to `4700` is a semantic no-op but a diff the author
  did not ask for.
- `4k7`-style embedded-prefix notation is **not** valid LTspice; it parses as
  4000. If you see it, flag it as a probable authoring error.
- When adding a directive, add a new `TEXT` record rather than appending to an
  existing one — LTspice treats each `TEXT` as a separate block.
