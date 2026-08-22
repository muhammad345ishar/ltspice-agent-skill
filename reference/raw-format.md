# LTspice `.raw` waveform format

`ltspice_raw.py` is implemented from documented structure and should be validated against real fixtures.

## Documented structure

1. Header lines, typically including:
   - `Title:`
   - `Date:`
   - `Plotname:`
   - `Flags:`
   - `No. Variables:`
   - `No. Points:`
   - `Offset:`
   - `Command:`
2. `Variables:` block with tab-indented rows:
   - `index name type`
3. Data section:
   - `Values:` (ASCII)
   - or `Binary:` (binary payload)

## Important quirks to verify with fixtures

- Some files store header text as UTF-16LE.
- `Flags: real` commonly uses mixed width (x-axis float64, others float32).
- `Flags: complex` stores complex values as two float64 numbers.
- `fastaccess` changes data layout.
- `.step` runs may concatenate multiple segments.

## Current script behavior

- Parses metadata + variables.
- Supports ASCII values parsing.
- Supports binary parsing for documented `real` and `complex` paths.
- Exports parsed rows to CSV.
- Includes structural validation command with matching log:
  - `python scripts/validate_raw_log.py foo.raw foo.log`
