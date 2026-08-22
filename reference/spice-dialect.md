# LTspice SPICE dialect notes

## Unit suffixes

- `f` femto, `p` pico, `n` nano, `u` or `µ` micro, `m` milli, `k` kilo, `Meg` mega, `g` giga, `t` tera.
- In LTspice, `M` is milli unless explicitly `Meg`.
- `1M` and `1Meg` differ by 1000x.

## Other practical rules

- Suffix parsing is case-insensitive.
- Trailing letters after a valid suffix may be ignored by SPICE.
- Common directives: `.tran`, `.ac`, `.step`, `.meas`, `.param`, `.include`, `.lib`.
- Behavioral sources (`B` elements) are LTspice-specific and should be passed through without rewriting.
