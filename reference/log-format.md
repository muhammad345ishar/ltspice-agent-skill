# LTspice `.log` format

The log parser extracts:

- `.measure` result lines (`name = value` or `name: value`)
- `.step` directives
- operating point section lines
- warnings and errors

## Why logs matter

- They are lightweight numeric evidence for simulation outcomes.
- They are useful for cross-checking parsed waveform values from `.raw`.
- They are the best first path when a user asks for measurements or solver diagnostics.
