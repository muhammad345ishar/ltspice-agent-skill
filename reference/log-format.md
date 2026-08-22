# LTspice `.log` format

Written next to the schematic after a run (`rc.asc` → `rc.log`). Plain text,
but subject to the **same encoding traps as `.asc`**: LTspice may write UTF-16LE
with no BOM. Decode with `read_ltspice_text()` from `scripts/ltspice_common.py`,
never a bare `open()`.

Parsed by `scripts/ltspice_log.py`.

## Overall shape

A real LTspice 17.2.4 transient log, complete and verbatim apart from the path:

```
LTspice 17.2.4 for MacOS
Circuit: * diffamp_delayed_window.asc
Start Time: Sun Aug 23 01:51:48 2026
Warning: Multiple definitions of model "bc847b" Type: BJT
solver = Normal
Maximum thread count: 12
tnom = 27
temp = 27
method = modified trap
CompressWinPoints = 1024
WARNING: Node VO2 is floating.

WARNING: Less than two connections to node vo2.  This node is used by c3.
Direct Newton iteration for .op point succeeded.
Total elapsed time: 2.386 seconds.
```

Order is not guaranteed. Parse by line shape, not by position.

## Run context

The banner and the `key = value` / `key: value` block are worth capturing, not
discarding: `temp` and `method` change how the results must be read (a run at
`temp = 27` is not comparable to one at 85, and `modified trap` versus `gear`
affects damping of ringing). `scripts/ltspice_log.py` returns these as
`ltspice_version`, `circuit` and a `settings` dict.

**Trap:** several diagnostic lines are shaped exactly like a setting —
`WARNING: Node VO2 is floating.` parses as key `WARNING`, value
`Node VO2 is floating.` A naive `key: value` sweep files warnings as settings.
Classify diagnostics first, or exclude any line matching the warning/error
patterns from the settings sweep.

## `.measure` results — four distinct shapes

This is where naive parsers fail. The value is usually **after `=`**, not after
the colon.

**1. Windowed / expression measure.** The standard single-run form:

```
vpp: MAX(v(out))-MIN(v(out))=2.5 FROM 0 TO 0.001
```

Name before `:`, expression next, value after `=`, then an optional
`FROM a TO b` window. A pattern of `name: <number>` matches nothing here and
yields an empty measurement list for a perfectly healthy log.

**2. Point measure**, with `at` instead of a window:

```
vmid: v(out)=2.49999 at 0.0005
```

**3. Multi-line TRIG/TARG measure.** The first line is *not* the result — the
final indented line repeats the measure name and carries the answer:

```
tr: trig=1.4999 at 1.0055e-05
	targ=3.4999 at 2.7069e-05
	tr=1.7014e-05
```

Reading `1.4999` as `tr` is a real trap: it is a trigger threshold, not a time.

**4. Stepped table.** With `.step` active, each measure becomes a table with one
row per step:

```
Measurement: vpp
  step	MAX(v(out))-MIN(v(out))	vpp
     1	2.5	2.5
     2	1.25	1.25
```

Columns are named by the header row; the column matching the measure name holds
the result. `ltspice_log.py` returns these under `stepped_measurements` and also
flattens them into `measurements` with a `step` number set.

## Operating point block

Emitted by `.op`. Note the blank line **after** the header — a parser that ends
the block on the first blank line captures nothing:

```
       --- Operating Point ---

V(out):	2.5	voltage
V(in):	5	voltage
I(R1):	0.0025	device_current
```

Format is `name:<tab>value<tab>type`. Types seen: `voltage`,
`device_current`, `subckt_current`. Returned as the `operating_point` dict.

## Step directives

Echoed when `.step` is present:

```
.step r=1000
.step r=2000
```

The step numbers in measurement tables correspond to these in order, so
row `step 1` is the first echoed parameter set. Use this to label results —
`vpp = 2.5` alone is useless without knowing which `r` produced it.

## Fourier / THD

Present when `.four` is used:

```
Fourier components of V(out)
...
Total Harmonic Distortion: 0.123456%
```

Returned as `total_harmonic_distortion_percent`.

## Warnings and errors

Check `errors` **before** quoting any number. A convergence failure invalidates
the results printed before it.

Strings that indicate a failed or degraded run:

- `Fatal error:` — run did not complete
- `Time step too small` — convergence failure, results untrustworthy
- `Analysis aborted`
- `failed to converge`
- `Iteration limit reached`
- `Singular matrix` — usually a floating node or missing ground
- `WARNING: Less than two connections to node <N>` — dangling net; often the
  actual bug in the user's schematic and worth surfacing unprompted
- `WARNING: Node <N> is floating`
- `Missing model` / `Unknown subcircuit` — netlist will be incomplete

`ltspice_log.py` classifies lines containing `error`, `fatal`, `aborted` or
`failed to converge` as errors, and lines containing `warning` as warnings.
This is deliberately broad; read the `raw` text before drawing conclusions.

**Casing is inconsistent.** The same real log contains both `Warning: Multiple
definitions of model ...` and `WARNING: Node VO2 is floating.` Match
case-insensitively.

Note that a floating-node warning is not an error — the run above completed with
eight warnings and produced valid output. Do not escalate warnings to failure,
but do surface dangling-net warnings, since they are usually the real bug in the
schematic.

## Timing

```
Total elapsed time: 0.043 seconds.
```

Returned as `elapsed_seconds`. A suspiciously long time next to few output
points suggests convergence trouble even without an explicit error.

## Validation status

`scripts/log_selftest.py` runs 42 assertions.

**Against a real LTspice 17.2.4 log** (`real_transient_offset.log`): UTF-16LE
no-BOM decoding, the version banner, the `settings` block (`temp`, `method`,
`solver`), warnings in both casings, the absence of false errors, the `.op`
success note, elapsed time, and an honest zero measurement count.

**Against spec-derived fixtures only:** all four `.measure` shapes, the
operating-point block, stepped `Measurement:` tables and the failure strings —
the real log has no `.meas` statements. Coverage of exotic analyses (`.noise`,
`.tf`, distortion summaries) remains unproven.
