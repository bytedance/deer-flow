# Column Spacing Inference

Use this bundled reference when the user does not provide column spacing.

## Inference Strategy

- Prefer a symmetric distribution.
- prefer `6.0m` to `9.5m` spacing when auto-distributing portal-frame column bays.
- Prefer integers or `0.5m` increments.
- If the user gives a preferred spacing and it fits exactly, repeat that spacing.
- If the preferred spacing does not fit exactly, keep most middle bays near that spacing and adjust edge bays symmetrically.
- If the preferred spacing is not usable, fall back to symmetric auto-distribution rather than failing.
