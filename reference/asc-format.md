# LTspice `.asc` format

## Core shape

- Line-oriented text records.
- First token is the record keyword.
- Common records: `Version`, `SHEET`, `WIRE`, `FLAG`, `SYMBOL`, `WINDOW`, `SYMATTR`, `TEXT`.
- `WINDOW` and `SYMATTR` attach to the nearest preceding `SYMBOL`.
- `IOPIN` attaches to the nearest preceding `FLAG`.

## Parsing rules that must not be relaxed

- `SYMATTR` must be split with `maxsplit=2` because value text can contain spaces.
- `TEXT` body starts after token index 4 and may contain escaped `\n` sequences.
- `TEXT` body starts with:
  - `!` => SPICE directive
  - `;` => comment
- In the bundled corpus, `TEXT` discriminator counts are `! = 4655`, `; = 1411`.

## Encoding detection order

1. BOM:
   - `FF FE` => UTF-16LE
   - `FE FF` => UTF-16BE
   - `EF BB BF` => UTF-8 BOM
2. No BOM and bytes look like ASCII-with-NUL (`b[1]==0 and b[3]==0`) => UTF-16LE.
3. Strict UTF-8.
4. Fallback cp1252.

Never use replacement decoding (`errors="replace"`).

## Write safety requirements

- Preserve encoding, BOM presence, and line endings (`CRLF`/`LF`) on write.
- For intent-level edits (for example, change `R1` value), change only affected lines.
- Preserve unknown records verbatim.
