# SWEB-MINI-001

`tinycalc.merge_intervals()` currently returns sorted intervals without merging.

Expected behavior:
- Overlapping intervals are merged.
- Adjacent integer intervals are also merged, so `(1, 3)` and `(4, 5)` become `(1, 5)`.
- Disjoint intervals remain separate.
