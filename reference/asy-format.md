# LTspice `.asy` symbol format

## Core records

- `SymbolType <CELL|BLOCK>`
- `PIN x y orient offset`
- `PINATTR PinName <name>`
- `PINATTR SpiceOrder <n>`
- Geometry helpers: `LINE`, `RECTANGLE`, `CIRCLE`, `ARC`, `WINDOW`, `TEXT`

## Pin semantics

- `PIN` defines geometry location.
- `PINATTR PinName` labels the pin.
- `PINATTR SpiceOrder` defines terminal ordering used in generated SPICE cards.
- Terminal order must come from `SpiceOrder`, not drawing order.

## Compatibility notes

- In the bundled `.asy` sample set, `SymbolType` values observed are `CELL` and `BLOCK`.
- Parse unknown records defensively and preserve them on write.
- Preserve original encoding/newline/BOM exactly like `.asc` handling.
