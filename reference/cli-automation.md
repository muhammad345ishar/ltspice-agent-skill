# LTspice CLI automation

## Windows

- Common binaries: `XVIIx64.exe`, `LTspice.exe`
- Typical flags:
  - `-b -Run <schematic.asc>`: headless run
  - `-ascii`: text raw output
  - `-netlist <schematic.asc>`: emit netlist

## macOS

- Typical binary: `/Applications/LTspice.app/Contents/MacOS/LTspice`
- Supports headless run; option support can differ from Windows build.

## Linux

- Run LTspice under Wine.
- Ensure produced `.raw`/`.log` files are checked after process success.

## Failure handling

- Missing binary must be surfaced as an explicit error.
- Success return with no `.raw`/`.log` is treated as failure.
- Long-running or blocked invocations must timeout with a clear error.
