---
name: minimax-xlsx
description: "Open, create, read, analyze, edit, or validate Excel/spreadsheet files (.xlsx, .xlsm, .csv, .tsv). Use when the user asks to create, build, modify, analyze, read, validate, or format any Excel spreadsheet, financial model, pivot table, or tabular data file. Covers: creating new xlsx from scratch, reading and analyzing existing files, editing existing xlsx with zero format loss, formula recalculation and validation, and applying professional financial formatting standards. Triggers on 'spreadsheet', 'Excel', '.xlsx', '.csv', 'pivot table', 'financial model', 'formula', or any request to produce tabular data in Excel format."
license: MIT
metadata:
  version: "1.0"
  category: productivity
  sources:
    - ECMA-376 Office Open XML File Formats
    - Microsoft Open XML SDK documentation
name_zh: Excel表格处理
description_zh: 打开、创建、读取、分析、编辑或验证Excel/电子表格文件。支持通过XML模板从零创建xlsx、使用pandas读取分析、零格式损失编辑现有文件、公式重算与验证。
---
# MiniMax XLSX Skill

Handle the request directly. Do NOT spawn sub-agents. Always write the output file the user requests.

## Task Routing

| Task | Method | Guide |
|------|--------|-------|
| **READ** — analyze existing data | `xlsx_reader.py` + pandas | `references/read-analyze.md` |
| **CREATE** — new xlsx from scratch | XML template | `references/create.md` + `references/format.md` |
| **EDIT** — modify existing xlsx | XML unpack→edit→pack | `references/edit.md` (+ `format.md` if styling needed) |
| **FIX** — repair broken formulas in existing xlsx | XML unpack→fix `<f>` nodes→pack | `references/fix.md` |
| **VALIDATE** — check formulas | `formula_check.py` | `references/validate.md` |

## READ — Analyze data (read `references/read-analyze.md` first)

Start with `xlsx_reader.py` for structure discovery, then pandas for custom analysis. Never modify the source file.

**Formatting rule**: When the user specifies decimal places (e.g. "2 decimal places"), apply that format to ALL numeric values — use `f'{v:.2f}'` on every number. Never output `12875` when `12875.00` is required.

**Aggregation rule**: Always compute sums/means/counts directly from the DataFrame column — e.g. `df['Revenue'].sum()`. Never re-derive column values before aggregation.

## CREATE — XML template (read `references/create.md` + `references/format.md`)

Copy `templates/minimal_xlsx/` → edit XML directly → pack with `xlsx_pack.py`. Every derived value MUST be an Excel formula (`<f>SUM(B2:B9)</f>`), never a hardcoded number. Apply font colors per `format.md`.

## EDIT — XML direct-edit (read `references/edit.md` first)

**CRITICAL — EDIT INTEGRITY RULES:**
1. **NEVER create a new `Workbook()`** for edit tasks. Always load the original file.
2. The output MUST contain the **same sheets** as the input (same names, same data).
3. Only modify the specific cells the task asks for — everything else must be untouched.
4. **After saving output.xlsx, verify it**: open with `xlsx_reader.py` or `pandas` and confirm the original sheet names and a sample of original data are present. If verification fails, you wrote the wrong file — fix it before delivering.

Never use openpyxl round-trip on existing files (corrupts VBA, pivots, sparklines). Instead: unpack → use helper scripts → repack.

**"Fill cells" / "Add formulas to existing cells" = EDIT task.** If the input file already exists and you are told to fill, update, or add formulas to specific cells, you MUST use the XML edit path. Never create a new `Workbook()`. Example — fill B3 with a cross-sheet SUM formula:
```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
# Find the target sheet's XML via xl/workbook.xml → xl/_rels/workbook.xml.rels
# Then use the Edit tool to add <f> inside the target <c> element:
#   <c r="B3"><f>SUM('Sales Data'!D2:D13)</f><v></v></c>
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
```

**Add a column** (formulas, numfmt, styles auto-copied from adjacent column):
```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
python3 SKILL_DIR/scripts/xlsx_add_column.py /tmp/xlsx_work/ --col G \
    --sheet "Sheet1" --header "% of Total" \
    --formula '=F{row}/$F$10' --formula-rows 2:9 \
    --total-row 10 --total-formula '=SUM(G2:G9)' --numfmt '0.0%' \
    --border-row 10 --border-style medium
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
```
The `--border-row` flag applies a top border to ALL cells in that row (not just the new column). Use it when the task requires accounting-style borders on total rows.

**Insert a row** (shifts existing rows, updates SUM formulas, fixes circular refs):
```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
# IMPORTANT: Find the correct --at row by searching for the label text
# in the worksheet XML, NOT by using the row number from the prompt.
# The prompt may say "row 5 (Office Rent)" but Office Rent might actually
# be at row 4. Always locate the row by its text label first.
python3 SKILL_DIR/scripts/xlsx_insert_row.py /tmp/xlsx_work/ --at 5 \
    --sheet "Budget FY2025" --text A=Utilities \
    --values B=3000 C=3000 D=3500 E=3500 \
    --formula 'F=SUM(B{row}:E{row})' --copy-style-from 4
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
```
**Row lookup rule**: When the task says "after row N (Label)", always find the row by searching for "Label" in the worksheet XML (`grep -n "Label" /tmp/xlsx_work/xl/worksheets/sheet*.xml` or check sharedStrings.xml). Use the actual row number + 1 for `--at`. Do NOT call `xlsx_shift_rows.py` separately — `xlsx_insert_row.py` calls it internally.

**Apply row-wide borders** (e.g. accounting line on a TOTAL row):
After running helper scripts, apply borders to ALL cells in the target row, not just newly added cells. In `xl/styles.xml`, append a new `<border>` with the desired style, then append a new `<xf>` in `<cellXfs>` that clones each cell's existing `<xf>` but sets the new `borderId`. Apply the new style index to every `<c>` in the row via the `s` attribute:
```xml
<!-- In xl/styles.xml, append to <borders>: -->
<border>
  <left/><right/><top style="medium"/><bottom/><diagonal/>
</border>
<!-- Then append to <cellXfs> an xf clone with the new borderId for each existing style -->
```
**Key rule**: When a task says "add a border to row N", iterate over ALL cells A through the last column, not just newly added cells.

**Manual XML edit** (for anything the helper scripts don't cover):
```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
# ... edit XML with the Edit tool ...
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
```

## FIX — Repair broken formulas (read `references/fix.md` first)

This is an EDIT task. Unpack → fix broken `<f>` nodes → pack. Preserve all original sheets and data.

## VALIDATE — Check formulas (read `references/validate.md` first)

Run `formula_check.py` for static validation. Use `libreoffice_recalc.py` for dynamic recalculation when available.

## Financial Color Standard

| Cell Role | Font Color | Hex Code |
|-----------|-----------|----------|
| Hard-coded input / assumption | Blue | `0000FF` |
| Formula / computed result | Black | `000000` |
| Cross-sheet reference formula | Green | `00B050` |

## Key Rules

1. **Formula-First**: Every calculated cell MUST use an Excel formula, not a hardcoded number
2. **CREATE → XML template**: Copy minimal template, edit XML directly, pack with `xlsx_pack.py`
3. **EDIT → XML**: Never openpyxl round-trip. Use unpack/edit/pack scripts
4. **Always produce the output file** — this is the #1 priority
5. **Validate before delivery**: `formula_check.py` exit code 0 = safe

## Utility Scripts

```bash
python3 SKILL_DIR/scripts/xlsx_reader.py input.xlsx                 # structure discovery
python3 SKILL_DIR/scripts/formula_check.py file.xlsx --json         # formula validation
python3 SKILL_DIR/scripts/formula_check.py file.xlsx --report      # standardized report
python3 SKILL_DIR/scripts/xlsx_unpack.py in.xlsx /tmp/work/         # unpack for XML editing
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/work/ out.xlsx          # repack after editing
python3 SKILL_DIR/scripts/xlsx_shift_rows.py /tmp/work/ insert 5 1  # shift rows for insertion
python3 SKILL_DIR/scripts/xlsx_add_column.py /tmp/work/ --col G ... # add column with formulas
python3 SKILL_DIR/scripts/xlsx_insert_row.py /tmp/work/ --at 6 ...  # insert row with data
```
