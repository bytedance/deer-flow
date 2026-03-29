# OpenXML Unit Conversion Quick Reference

## Master Conversion Table

| Unit | 1 inch | 1 cm | 1 mm | 1 pt | Description |
|------|--------|------|------|------|-------------|
| DXA (twips) | 1440 | 567 | 56.7 | 20 | 1/20 of a point. Used for margins, indents, spacing, page size. |
| EMU | 914400 | 360000 | 36000 | 12700 | English Metric Unit. Used for images, drawings, shapes. |
| Half-points | 144 | 56.7 | 5.67 | 2 | Used for font sizes (`w:sz`, `w:szCs`). |
| Points | 72 | 28.35 | 2.835 | 1 | Standard typographic unit. Not used directly in most attributes. |
| Eighths of a point | 576 | 226.8 | 22.68 | 8 | Used for `w:spacing` character spacing. |

## Common Page Sizes

| Size | Width (DXA) | Height (DXA) | Width (mm) | Height (mm) |
|------|-------------|--------------|------------|-------------|
| A4 | 11906 | 16838 | 210 | 297 |
| Letter | 12240 | 15840 | 215.9 | 279.4 |
| Legal | 12240 | 20160 | 215.9 | 355.6 |
| A3 | 16838 | 23811 | 297 | 420 |
| A5 | 8391 | 11906 | 148 | 210 |

## Common Margin Values

| Margin | DXA | Inches | cm |
|--------|-----|--------|----|
| 0.5 inch | 720 | 0.5 | 1.27 |
| 0.75 inch | 1080 | 0.75 | 1.91 |
| 1 inch | 1440 | 1.0 | 2.54 |
| 1.25 inch | 1800 | 1.25 | 3.18 |
| 1.5 inch | 2160 | 1.5 | 3.81 |

## Font Size Values (`w:sz`)

| Display Size | w:sz value | Notes |
|-------------|-----------|-------|
| 8pt | 16 | |
| 9pt | 18 | |
| 10pt | 20 | |
| 10.5pt | 21 | Common CJK body size |
| 11pt | 22 | Default Calibri body |
| 12pt | 24 | Default TNR body |
| 14pt | 28 | Small heading |
| 16pt | 32 | |
| 18pt | 36 | |
| 20pt | 40 | |
| 24pt | 48 | |
| 28pt | 56 | |
| 36pt | 72 | |

## Line Spacing Values

Line spacing in `w:spacing` uses the `w:line` attribute in 240ths of a line (when `w:lineRule="auto"`):

| Spacing | w:line value | w:lineRule |
|---------|-------------|-----------|
| Single | 240 | auto |
| 1.15 (Word default) | 276 | auto |
| 1.5 | 360 | auto |
| Double | 480 | auto |
| Exact 12pt | 240 | exact |
| At least 12pt | 240 | atLeast |

Note: When `lineRule="exact"` or `"atLeast"`, `w:line` is in **twips** (DXA), not 240ths. So `line="240"` with `lineRule="exact"` means exactly 12pt (240/20 = 12pt).

## Conversion Formulas

```
DXA     = inches × 1440  = cm × 567     = pt × 20
EMU     = inches × 914400 = cm × 360000 = pt × 12700
sz      = pt × 2          (half-points)
```
