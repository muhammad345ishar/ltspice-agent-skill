# LTspice `.raw` waveform format

Binary (usually) waveform output written next to the schematic:
`rc.asc` → `rc.raw`. Parsed by `scripts/ltspice_raw.py`.

## File structure

A text header, a marker line, then the payload:

```
Title: * C:\path\to\rc_lowpass.asc
Date: Sun Aug 23 00:00:00 2026
Plotname: Transient Analysis
Flags: real
No. Variables: 3
No. Points: 1024
Offset: 0.0000000000000000e+000
Command: Linear Technology Corporation LTspice
Variables:
	0	time	time
	1	V(out)	voltage
	2	I(R1)	device_current
Binary:
<payload bytes>
```

The header is **often UTF-16LE**, frequently with a BOM but not always. Only the
header is text — decoding the whole file will fail on the payload, so detect the
encoding from a bounded prefix and decode only up to the marker.

The marker is `Binary:` or `Values:`, terminated by CRLF or LF. Take whichever
terminator comes **first**; a CRLF byte pair occurring later inside binary data
must not win over the LF that actually ends the marker line.

## Header fields

| Field | Notes |
|---|---|
| `Title` | usually the source schematic path |
| `Plotname` | `Transient Analysis`, `AC Analysis`, `DC transfer characteristic`, `Operating Point`, `Noise Spectral Density`, `Transfer Function` |
| `Flags` | space-separated; see below |
| `No. Variables` | column count, including the x-axis |
| `No. Points` | **total** points; for a `.step` run this is the sum across all steps |
| `Offset` | **must be added to every x value** — see below. Not informational. |
| `Command` | writer version string |

### `Offset` is load-bearing

`Offset` is the constant that was **subtracted** from the x axis before storage:

```
true_x = stored_x + Offset
```

It is non-zero whenever a transient run delays data collection. A real
LTspice 17.2.4 run of `.tran 0 10.02 10` — simulate to 10.02 s, start saving at
10 s — produced:

```
Flags: real forward
No. Points:          484
Offset:    1.0000000000000000e+01
```

with stored times running `0.0 .. 0.02`. The true waveform spans
`10.000 .. 10.020 s`. A reader that ignores `Offset` reports every event 10
seconds early, and the numbers look completely plausible while being wrong — the
failure is silent. This is the single most dangerous field in the header.

Apply the offset **after** the sign-bit `abs()` (the sign quirk is in the stored
bits, not the true value) and regardless of axis type, since the offset is a
property of the x axis rather than of time specifically.

`scripts/ltspice_raw.py` applies it and reports both `x_offset` and a human
readable `x_offset_note`. The fixture
`examples/skill_samples/real_transient_offset.raw` is the trimmed real file and
locks this behaviour in.

`Variables:` is followed by one indented row per variable:
`<index><tab><name><tab><type>`. Types include `time`, `frequency`, `voltage`,
`device_current`, `subckt_current`. Variable 0 is the x-axis.

## Flags

| Flag | Meaning |
|---|---|
| `real` | real-valued samples (transient, DC, op) |
| `complex` | complex samples — AC analysis |
| `stepped` | multiple `.step` runs concatenated in one file |
| `fastaccess` | payload is **transposed** |
| `forward` | sweep direction, informational |
| `double` | all columns stored as float64 |

## Payload layouts

**Interleaved (default).** One point at a time, all columns:

```
[x₀][v1₀][v2₀][x₁][v1₁][v2₁]…
```

**fastaccess (transposed).** Each variable's entire array, contiguously:

```
[x₀…xₙ][v1₀…v1ₙ][v2₀…v2ₙ]
```

Reading a transposed file as interleaved does **not** raise — it returns
plausible-looking nonsense (values like `-5.19e11` for a 1.5 V node). Always
check the flag.

**Column widths.** Conventionally the x-axis is float64 and the remaining
columns are float32; with `double` set, everything is float64. Complex files
store every value as two float64s (real, imaginary) — including the frequency
column, whose imaginary part is 0.

Rather than trusting the convention, `ltspice_raw.py` computes the total size of
each candidate layout and selects the one matching the payload length exactly:

| Layout | Bytes per point |
|---|---|
| `float64_x_float32_vars` | `8 + 4·(nvars−1)` |
| `float64_all` | `8·nvars` |
| `float32_all` | `4·nvars` |
| `complex128` | `16·nvars` |

These totals are distinct for any `nvars > 1`, so the layout is inferred rather
than assumed, and a truncated or unrecognised file raises with the arithmetic
instead of returning partial data. Up to 4 trailing bytes are tolerated.

## The x-axis sign bit

LTspice sometimes sets the sign bit on the x-axis float64, so a time value reads
back negative. Time and frequency are physically non-negative, so the magnitude
is taken — **but only for those axis types**.

A DC sweep's x-axis is a `voltage` and may legitimately be negative (sweeping
−5 V to +5 V). Applying `abs()` unconditionally silently mirrors the left half
of every DC transfer curve onto the right. `ltspice_raw.py` keys this on the
x-axis variable type for that reason.

## Complex (AC) data

For `Flags: complex`, each sample is returned as a `[real, imaginary]` pair and
`parse_raw()["complex"]` is `True`. Reporting the real part alone as "the value"
is wrong: `0.5 − 0.25j` has magnitude 0.559, not 0.5.

Use `magnitude_phase(value)` → `(magnitude, dB, degrees)`. `export_csv()` emits
`name_re`, `name_im`, `name_mag`, `name_db`, `name_deg` per variable.

## Stepped runs

With `.step`, runs are concatenated and `No. Points` is the total. There is no
per-step marker in the payload; boundaries are found where the x-axis
**decreases** (each run restarts at its own t=0).

`parse_raw()` returns `steps` as a list of `[start, end)` index ranges and
`step_count`. Compare runs by slicing with these; treating the file as one
continuous sweep produces a sawtooth that looks like an oscillation artifact.

Match step indices to parameter values using the `.step` echo lines in the
matching `.log`.

## ASCII `Values:` payload

Written when LTspice is asked for an ASCII raw file. One block per point: the
first line is `index<TAB>xvalue`, and each following value sits on its own
indented line:

```
0	0.000000000000000e+00
	1.500000000000000e+00
	2.500000000000000e-01
1	1.000000000000000e-03
	2.500000000000000e+00
	5.000000000000000e-01
```

Continuation lines carry a **single** token, so a parser that skips lines with
fewer than two tokens discards every value except the x-axis — and then groups
consecutive x-axis values into one bogus "row". Complex samples are written
`real,imag` in a single token.

## Validation status

`scripts/raw_selftest.py` runs 154 assertions.

**Against real LTspice 17.2.4 output** (`real_transient_offset.raw`, a trimmed
real transient run): UTF-16LE no-BOM header decoding, the `Flags: real forward`
token set, the tab-separated `Variables:` block including the `device_current`
type, payload-length layout inference selecting `float64_x_float32_vars`
(12 × (8 + 4×28) = 1440 bytes), exact float32 recovery of a 15 V rail, and the
`Offset` shift.

**Against spec-derived fixtures only:** complex/AC magnitude and phase,
`fastaccess` transposition, all-float64 and all-float32 layouts, the ASCII
`Values:` payload, `.step` segmentation, truncation rejection and CSV export.
These prove the reader is self-consistent with this document, not that the
document is right for those cases. An AC run and a `.step` run would close the
gap; pair them with `scripts/validate_raw_log.py` when a matching `.log` exists.

The `Offset` bug is the cautionary tale here: it survived 137 passing
spec-derived assertions and was caught within minutes of seeing one real file,
because the spec these fixtures were built from described the field as
"informational".
