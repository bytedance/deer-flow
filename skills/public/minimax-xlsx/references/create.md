# Build New xlsx from Scratch

Create new, production-quality xlsx files using the XML approach. NEVER use openpyxl
for writing. NEVER hardcode Python-computed values — every derived number must be a
live Excel formula.

---

## When to Use This Path

Use this document when the user wants:
- A brand-new Excel file that does not yet exist
- A generated report, financial model, or data table
- Any "create / build / generate / make" request

If the user provides an existing file to modify, switch to `edit.md` instead.

---

## The Non-Negotiable Rules

Before touching any file, internalize these four rules:

1. **Formula-First**: Every calculated value (`SUM`, growth rate, ratio, subtotal, etc.)
   MUST be written as `<f>SUM(B2:B9)</f>`, not as a hardcoded `<v>5000</v>`. Hardcoded
   numbers go stale when source data changes. Only raw inputs and assumption parameters
   may be hardcoded values.

2. **No openpyxl for writing**: The entire file is built by editing XML directly. Python
   is only allowed for reading/analysis (`pandas.read_excel()`) and for running helper
   scripts (`xlsx_pack.py`, `formula_check.py`).

3. **Style encodes meaning**: Blue font = user input/assumption. Black font = formula
   result. Green font = cross-sheet reference. See `format.md` for the full color system
   and style index table.

4. **Validate before delivery**: Run `formula_check.py` and fix all errors before
   handing the file to the user.

---

## Complete Creation Workflow

### Step 1 — Plan Before Writing

Define the full structure on paper before touching any XML:

- **Sheets**: names, order, purpose (e.g., Assumptions / Model / Summary)
- **Layout per sheet**: which rows are headers, inputs, formulas, totals
- **String inventory**: collect all text labels you will need in sharedStrings
- **Style choices**: what number format each column needs (currency, %, integer, year)
- **Cross-sheet links**: which sheets pull data from other sheets

This planning step prevents the costly cycle of adding strings to sharedStrings
mid-way and recomputing all indices.

---

### Step 2 — Copy Minimal Template

```bash
cp -r SKILL_DIR/templates/minimal_xlsx/ /tmp/xlsx_work/
```

The template gives you a complete, valid 7-file xlsx skeleton:

```
/tmp/xlsx_work/
├── [Content_Types].xml        ← MIME type registry
├── _rels/
│   └── .rels                  ← root relationship (points to workbook.xml)
└── xl/
    ├── workbook.xml            ← sheet list and calc settings
    ├── styles.xml              ← 13 pre-built financial style slots
    ├── sharedStrings.xml       ← text string table (starts empty)
    ├── _rels/
    │   └── workbook.xml.rels  ← maps rId → file paths
    └── worksheets/
        └── sheet1.xml          ← one empty sheet
```

After copying, rename sheets and add content. Do not create files from scratch —
always start from the template.

---

### Step 3 — Configure Sheet Structure

#### Single-Sheet Workbook

The template already has one sheet named "Sheet1". Just change the `name` attribute
in `xl/workbook.xml`:

```xml
<sheets>
  <sheet name="Revenue Model" sheetId="1" r:id="rId1"/>
</sheets>
```

No other files need to change for a single-sheet workbook.

#### Multi-Sheet Workbook

Four files must be kept in sync. Work through them in this order:

**IMPORTANT — rId collision rule**: In the template's `workbook.xml.rels`, the IDs
`rId1`, `rId2`, and `rId3` are already taken:
- `rId1` → `worksheets/sheet1.xml`
- `rId2` → `styles.xml`
- `rId3` → `sharedStrings.xml`

New worksheet entries MUST start at `rId4` and count upward.

**File 1 of 4 — `xl/workbook.xml`** (sheet list):

```xml
<sheets>
  <sheet name="Assumptions" sheetId="1" r:id="rId1"/>
  <sheet name="Model"       sheetId="2" r:id="rId4"/>
  <sheet name="Summary"     sheetId="3" r:id="rId5"/>
</sheets>
```

Special characters in sheet names:
- `&` → `&amp;` in XML: `<sheet name="P&amp;L" .../>`
- Max 31 characters
- Forbidden: `/ \ ? * [ ] :`
- Sheet names with spaces need single quotes in formula references: `'Q1 Data'!B5`

**File 2 of 4 — `xl/_rels/workbook.xml.rels`** (ID → file mapping):

```xml
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    Target="styles.xml"/>
  <Relationship Id="rId3"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    Target="sharedStrings.xml"/>
  <Relationship Id="rId4"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId5"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet3.xml"/>
</Relationships>
```

**File 3 of 4 — `[Content_Types].xml`** (MIME type declarations):

```xml
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml"  ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/sharedStrings.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
```

**File 4 of 4 — Create new worksheet XML files**

Copy `sheet1.xml` to `sheet2.xml` and `sheet3.xml`, then clear the `<sheetData>` content:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet
  xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0"/>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15" x14ac:dyDescent="0.25"
    xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"/>
  <sheetData>
    <!-- Data rows go here -->
  </sheetData>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>
```

**Sync checklist** — every time you add a sheet, verify all four are consistent:

| Check | What to verify |
|-------|---------------|
| `workbook.xml` | New `<sheet name="..." sheetId="N" r:id="rIdX"/>` exists |
| `workbook.xml.rels` | New `<Relationship Id="rIdX" ... Target="worksheets/sheetN.xml"/>` exists |
| `[Content_Types].xml` | New `<Override PartName="/xl/worksheets/sheetN.xml" .../>` exists |
| Filesystem | `xl/worksheets/sheetN.xml` file actually exists |

---

### Step 4 — Populate sharedStrings

All text values (headers, row labels, category names, any string the user will read)
must be stored in `xl/sharedStrings.xml`. Cells reference them by 0-based index.

**Recommended workflow**: collect ALL text you need first, write the complete table once,
then fill in indices while writing worksheet XML. This avoids re-counting indices mid-way.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
     count="10" uniqueCount="10">
  <si><t>Item</t></si>                  <!-- index 0 -->
  <si><t>FY2023A</t></si>               <!-- index 1 -->
  <si><t>FY2024E</t></si>               <!-- index 2 -->
  <si><t>FY2025E</t></si>               <!-- index 3 -->
  <si><t>YoY Growth</t></si>            <!-- index 4 -->
  <si><t>Revenue</t></si>               <!-- index 5 -->
  <si><t>Cost of Goods Sold</t></si>    <!-- index 6 -->
  <si><t>Gross Profit</t></si>          <!-- index 7 -->
  <si><t>EBITDA</t></si>                <!-- index 8 -->
  <si><t>Net Income</t></si>            <!-- index 9 -->
</sst>
```

**Attribute rules**:
- `uniqueCount` = number of `<si>` elements (unique strings in the table)
- `count` = total number of cell references to strings across the entire workbook
  (if "Revenue" appears in 3 sheets, count is `uniqueCount + 2`)
- For new files where each string appears once, `count == uniqueCount`
- Both attributes MUST be accurate — wrong values trigger warnings in some Excel versions

**Special character escaping**:

```xml
<si><t>R&amp;D Expenses</t></si>          <!-- & must be &amp; -->
<si><t>Revenue &lt; Target</t></si>        <!-- < must be &lt; -->
<si><t xml:space="preserve">  (note)  </t></si>  <!-- preserve leading/trailing spaces -->
```

**Helper script**: use `shared_strings_builder.py` to generate the complete
`sharedStrings.xml` from a plain list of strings:

```bash
python3 SKILL_DIR/scripts/shared_strings_builder.py \
  "Item" "FY2024" "FY2025" "Revenue" "Gross Profit" \
  > /tmp/xlsx_work/xl/sharedStrings.xml
```

Or interactively from a file listing one string per line:

```bash
python3 SKILL_DIR/scripts/shared_strings_builder.py --file strings.txt \
  > /tmp/xlsx_work/xl/sharedStrings.xml
```

---

### Step 5 — Write Worksheet Data

Edit each `xl/worksheets/sheetN.xml`. Replace the empty `<sheetData>` with rows
and cells.

#### Cell XML Anatomy

```
<c r="B5" t="s" s="4">
      ↑     ↑    ↑
   address  type  style index (from cellXfs in styles.xml)

  <v>3</v>
     ↑
  value (for t="s": sharedStrings index; for numbers: the number itself)
```

#### Data Type Reference

| Data | `t` attr | XML Example | Notes |
|------|---------|-------------|-------|
| Shared string (text) | `s` | `<c r="A1" t="s" s="4"><v>0</v></c>` | `<v>` = sharedStrings index |
| Number | omit | `<c r="B2" s="5"><v>1000000</v></c>` | default type, `t` omitted |
| Percentage (as decimal) | omit | `<c r="C2" s="7"><v>0.125</v></c>` | 12.5% stored as 0.125 |
| Boolean | `b` | `<c r="D1" t="b"><v>1</v></c>` | 1=TRUE, 0=FALSE |
| Formula | omit | `<c r="B4" s="2"><f>SUM(B2:B3)</f><v></v></c>` | `<v>` left empty |
| Cross-sheet formula | omit | `<c r="C1" s="3"><f>Assumptions!B2</f><v></v></c>` | use s=3 (green) |

#### A Full Sheet Data Example

```xml
<cols>
  <col min="1" max="1" width="26" customWidth="1"/>   <!-- A: label column -->
  <col min="2" max="5" width="14" customWidth="1"/>   <!-- B-E: data columns -->
</cols>
<sheetData>

  <!-- Row 1: headers (style 4 = bold header) -->
  <row r="1" ht="18" customHeight="1">
    <c r="A1" t="s" s="4"><v>0</v></c>   <!-- "Item" -->
    <c r="B1" t="s" s="4"><v>1</v></c>   <!-- "FY2023A" -->
    <c r="C1" t="s" s="4"><v>2</v></c>   <!-- "FY2024E" -->
    <c r="D1" t="s" s="4"><v>3</v></c>   <!-- "FY2025E" -->
    <c r="E1" t="s" s="4"><v>4</v></c>   <!-- "YoY Growth" -->
  </row>

  <!-- Row 2: Revenue — actual value (input) + formula (computed) -->
  <row r="2">
    <c r="A2" t="s" s="1"><v>5</v></c>    <!-- "Revenue", blue input label -->
    <c r="B2" s="5"><v>85000000</v></c>   <!-- FY2023A actual: $85M, currency input -->
    <c r="C2" s="6"><f>B2*(1+Assumptions!C3)</f><v></v></c>   <!-- formula, currency -->
    <c r="D2" s="6"><f>C2*(1+Assumptions!D3)</f><v></v></c>
    <c r="E2" s="8"><f>D2/C2-1</f><v></v></c>   <!-- YoY growth, percentage formula -->
  </row>

  <!-- Row 3: Gross Profit -->
  <row r="3">
    <c r="A3" t="s" s="2"><v>7</v></c>    <!-- "Gross Profit", black formula label -->
    <c r="B3" s="6"><f>B2*Assumptions!B4</f><v></v></c>
    <c r="C3" s="6"><f>C2*Assumptions!C4</f><v></v></c>
    <c r="D3" s="6"><f>D2*Assumptions!D4</f><v></v></c>
    <c r="E3" s="8"><f>D3/C3-1</f><v></v></c>
  </row>

  <!-- Row 5: SUM total row -->
  <row r="5">
    <c r="A5" t="s" s="4"><v>8</v></c>    <!-- "EBITDA" -->
    <c r="B5" s="6"><f>SUM(B2:B4)</f><v></v></c>
    <c r="C5" s="6"><f>SUM(C2:C4)</f><v></v></c>
    <c r="D5" s="6"><f>SUM(D2:D4)</f><v></v></c>
    <c r="E5" s="8"><f>D5/C5-1</f><v></v></c>
  </row>

</sheetData>
```

#### Column Width and Freeze Pane

Column widths go **before** `<sheetData>`, freeze pane goes inside `<sheetView>`:

```xml
<!-- Inside <sheetViews><sheetView ...> — freeze the header row -->
<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>

<!-- Before <sheetData> — set column widths -->
<cols>
  <col min="1" max="1" width="28" customWidth="1"/>
  <col min="2" max="8" width="14" customWidth="1"/>
</cols>
```

---

### Step 6 — Apply Styles

The template's `xl/styles.xml` has 13 pre-built semantic style slots (indices 0–12).
**Read `format.md` for the complete style index table, color system, and how to add new styles.**

Quick reference for the most common slots:

| `s` | Role | Example |
|-----|------|---------|
| 4 | Header (bold) | Column/row titles |
| 5 / 6 | Currency input (blue) / formula (black) | `$#,##0` |
| 7 / 8 | Percentage input / formula | `0.0%` |
| 11 | Year (no comma) | 2024 not 2,024 |

Design principle: Blue = human sets this. Black = Excel computes this. Green = cross-sheet.

If you need a style not in the 13 pre-built slots, follow the append-only procedure in `format.md` section 3.2.

---

### Step 7 — Formula Cookbook

#### XML Formula Syntax Reminder

Formulas in XML have **no leading `=`**:

```xml
<!-- Excel UI: =SUM(B2:B9)   →   XML: -->
<c r="B10" s="6"><f>SUM(B2:B9)</f><v></v></c>
```

#### Basic Aggregations

```xml
<c r="B10" s="6"><f>SUM(B2:B9)</f><v></v></c>
<c r="B11" s="6"><f>AVERAGE(B2:B9)</f><v></v></c>
<c r="B12" s="10"><f>COUNT(B2:B9)</f><v></v></c>
<c r="B13" s="10"><f>COUNTA(A2:A100)</f><v></v></c>
<c r="B14" s="6"><f>MAX(B2:B9)</f><v></v></c>
<c r="B15" s="6"><f>MIN(B2:B9)</f><v></v></c>
```

#### Financial Calculations

```xml
<!-- YoY growth rate: current / prior - 1 -->
<c r="E5" s="8"><f>D5/C5-1</f><v></v></c>

<!-- Gross profit: revenue × gross margin -->
<c r="B6" s="6"><f>B4*B3</f><v></v></c>

<!-- EBITDA margin: EBITDA / Revenue -->
<c r="B9" s="8"><f>B8/B4</f><v></v></c>

<!-- Suppress #DIV/0! when denominator may be zero -->
<c r="E5" s="8"><f>IF(C5=0,0,D5/C5-1)</f><v></v></c>

<!-- NPV and IRR (cash flows in B2:B7, discount rate in B1) -->
<c r="C1" s="6"><f>NPV(B1,B3:B7)+B2</f><v></v></c>
<c r="C2" s="8"><f>IRR(B2:B7)</f><v></v></c>
```

#### Cross-Sheet References

```xml
<!-- No spaces in name: no quotes needed -->
<c r="B3" s="3"><f>Assumptions!B5</f><v></v></c>

<!-- Space in sheet name: single quotes required -->
<c r="B3" s="3"><f>'Q1 Data'!B5</f><v></v></c>

<!-- Ampersand in sheet name (XML-escaped in workbook.xml, but in formula: literal &) -->
<c r="B3" s="3"><f>'R&amp;D'!B5</f><v></v></c>

<!-- Cross-sheet range: SUM of a range in another sheet -->
<c r="B10" s="6"><f>SUM(Data!C2:C1000)</f><v></v></c>

<!-- 3D reference: sum same cell across multiple sheets -->
<c r="B5" s="6"><f>SUM(Jan:Dec!B5)</f><v></v></c>
```

Cross-sheet formula cells should use `s="3"` (green) to signal the data origin.

#### Shared Formulas (Same Pattern Repeated Down a Column)

When many consecutive cells share the same formula structure with only the row number
changing, use shared formulas to keep the XML compact:

```xml
<!-- D2: defines the shared group (si="0", ref="D2:D11") -->
<c r="D2" s="8"><f t="shared" ref="D2:D11" si="0">C2/B2-1</f><v></v></c>

<!-- D3 through D11: reference the same group, no formula text needed -->
<c r="D3" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D4" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D5" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D6" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D7" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D8" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D9" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D10" s="8"><f t="shared" si="0"/><v></v></c>
<c r="D11" s="8"><f t="shared" si="0"/><v></v></c>
```

Excel adjusts relative references automatically (D3 computes `C3/B3-1`, etc.).
If you have multiple shared formula groups, assign sequential `si` values (0, 1, 2, …).

#### Absolute References

```xml
<!-- $B$2 locks to that cell when the formula is copied -->
<c r="C5" s="8"><f>B5/$B$2</f><v></v></c>
```

The `$` character needs no XML escaping — write it literally.

#### Lookup Formulas

```xml
<!-- VLOOKUP: exact match (last arg 0) -->
<c r="C5" s="6"><f>VLOOKUP(A5,Assumptions!A:C,2,0)</f><v></v></c>

<!-- INDEX/MATCH: more flexible -->
<c r="C5" s="6"><f>INDEX(B:B,MATCH(A5,A:A,0))</f><v></v></c>

<!-- XLOOKUP (Excel 2019+) -->
<c r="C5" s="6"><f>XLOOKUP(A5,A:A,B:B)</f><v></v></c>
```

---

### Step 8 — Pack and Validate

**Pack**:

```bash
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ /path/to/output.xlsx
```

`xlsx_pack.py` will:
1. Check that `[Content_Types].xml` exists at the root
2. Parse every `.xml` and `.rels` file for well-formedness — abort if any fail
3. Create the ZIP archive with correct compression

**Validate**:

```bash
python3 SKILL_DIR/scripts/formula_check.py /path/to/output.xlsx
```

`formula_check.py` will:
1. Scan every cell for `<c t="e">` entries (cached error values) — all 7 error types
2. Extract sheet name references from every `<f>` formula
3. Verify each referenced sheet exists in `workbook.xml`

Fix every reported error before delivery. Exit code 0 = safe to deliver.

---

## Pre-Delivery Checklist

Run through this list before handing the file to the user:

- [ ] `formula_check.py` reports 0 errors
- [ ] Every calculated cell has `<f>` — not just `<v>` with a number
- [ ] `sharedStrings.xml` `count` and `uniqueCount` match actual `<si>` count
- [ ] Every cell `s` attribute value is in range `0` to `cellXfs count - 1`
- [ ] Every sheet in `workbook.xml` has a matching entry in `workbook.xml.rels`
- [ ] Every `worksheets/sheetN.xml` file has a matching `<Override>` in `[Content_Types].xml`
- [ ] Year columns use `s="11"` (format `0`, no thousands separator)
- [ ] Cross-sheet reference formulas use `s="3"` (green font)
- [ ] Assumption inputs use `s="1"` or `s="5"` or `s="7"` (blue font)

---

## Common Mistakes and Fixes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Formula has leading `=` | Cell shows `=SUM(...)` as text | Remove `=` from `<f>` content |
| sharedStrings `count` not updated | Excel warning or blank cells | Count `<si>` elements, update both `count` and `uniqueCount` |
| Style index out of range | File corruption / Excel repair | Ensure `s` < `cellXfs count`; append new `<xf>` if needed |
| New sheet rId conflicts with styles/sharedStrings rId | Sheet missing or styles lost | New sheets use rId4, rId5, … (rId1-3 are reserved in template) |
| Sheet name has `&` unescaped in XML | XML parse error | Use `&amp;` in `workbook.xml` name attribute |
| Cross-sheet ref to sheet with space, no quotes | `#REF!` error | Wrap sheet name in single quotes: `'Sheet Name'!B5` |
| Cross-sheet ref to non-existent sheet | `#REF!` error | Check `workbook.xml` sheet list vs formula |
| Number stored as text (`t="s"`) | Left-aligned, can't sum | Remove `t` attribute from number cells |
| Year displayed as `2,024` | Readability issue | Use `s="11"` (numFmtId=1, format `0`) |
| Hardcoded Python result instead of formula | "Dead table" — won't update | Replace `<v>N</v>` with `<f>formula</f><v></v>` |

---

## Column Letter Reference

| Col # | Letter | Col # | Letter | Col # | Letter |
|-------|--------|-------|--------|-------|--------|
| 1 | A | 26 | Z | 27 | AA |
| 28 | AB | 52 | AZ | 53 | BA |
| 54 | BB | 78 | BZ | 79 | CA |

Python conversion (use when building formulas programmatically):

```python
def col_letter(n: int) -> str:
    """Convert 1-based column number to Excel letter (A, B, ..., Z, AA, AB, ...)."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result

def col_number(s: str) -> int:
    """Convert Excel column letter to 1-based number."""
    n = 0
    for c in s.upper():
        n = n * 26 + (ord(c) - 64)
    return n
```

---

## Typical Scenario Walkthroughs

### Scenario A — Three-Year Financial Model (Single Sheet)

Layout: rows 1-12 = Assumptions (blue inputs) / rows 14-30 = Model (black formulas).

```xml
<!-- sharedStrings.xml (excerpt) -->
<sst count="8" uniqueCount="8">
  <si><t>Metric</t></si>           <!-- 0 -->
  <si><t>FY2023A</t></si>          <!-- 1 -->
  <si><t>FY2024E</t></si>          <!-- 2 -->
  <si><t>FY2025E</t></si>          <!-- 3 -->
  <si><t>Revenue Growth</t></si>   <!-- 4 -->
  <si><t>Gross Margin</t></si>     <!-- 5 -->
  <si><t>Revenue</t></si>          <!-- 6 -->
  <si><t>Gross Profit</t></si>     <!-- 7 -->
</sst>

<!-- sheet1.xml (excerpt) -->
<sheetData>
  <!-- Header -->
  <row r="1">
    <c r="A1" t="s" s="4"><v>0</v></c>
    <c r="B1" t="s" s="4"><v>1</v></c>
    <c r="C1" t="s" s="4"><v>2</v></c>
    <c r="D1" t="s" s="4"><v>3</v></c>
  </row>
  <!-- Assumptions (rows 2-3) -->
  <row r="2">
    <c r="A2" t="s" s="1"><v>4</v></c>    <!-- "Revenue Growth", blue -->
    <c r="B2" s="7"><v>0</v></c>          <!-- FY2023A: n/a, 0% placeholder -->
    <c r="C2" s="7"><v>0.12</v></c>       <!-- FY2024E: 12.0% input -->
    <c r="D2" s="7"><v>0.15</v></c>       <!-- FY2025E: 15.0% input -->
  </row>
  <row r="3">
    <c r="A3" t="s" s="1"><v>5</v></c>    <!-- "Gross Margin", blue -->
    <c r="B3" s="7"><v>0.45</v></c>
    <c r="C3" s="7"><v>0.46</v></c>
    <c r="D3" s="7"><v>0.47</v></c>
  </row>
  <!-- Model (rows 14-15) -->
  <row r="14">
    <c r="A14" t="s" s="2"><v>6</v></c>      <!-- "Revenue", black -->
    <c r="B14" s="5"><v>85000000</v></c>     <!-- actual, currency input -->
    <c r="C14" s="6"><f>B14*(1+C2)</f><v></v></c>
    <c r="D14" s="6"><f>C14*(1+D2)</f><v></v></c>
  </row>
  <row r="15">
    <c r="A15" t="s" s="2"><v>7</v></c>      <!-- "Gross Profit", black -->
    <c r="B15" s="6"><f>B14*B3</f><v></v></c>
    <c r="C15" s="6"><f>C14*C3</f><v></v></c>
    <c r="D15" s="6"><f>D14*D3</f><v></v></c>
  </row>
</sheetData>
```

### Scenario B — Data + Summary (Two Sheets)

The `Summary` sheet pulls from `Data` using cross-sheet formulas (green, `s="3"`):

```xml
<!-- Summary/sheet2.xml sheetData excerpt -->
<sheetData>
  <row r="1">
    <c r="A1" t="s" s="4"><v>0</v></c>   <!-- "Metric" -->
    <c r="B1" t="s" s="4"><v>1</v></c>   <!-- "Value" -->
  </row>
  <row r="2">
    <c r="A2" t="s" s="0"><v>2</v></c>   <!-- "Total Revenue" -->
    <c r="B2" s="3"><f>SUM(Data!C2:C10000)</f><v></v></c>
  </row>
  <row r="3">
    <c r="A3" t="s" s="0"><v>3</v></c>   <!-- "Deal Count" -->
    <c r="B3" s="3"><f>COUNTA(Data!A2:A10000)</f><v></v></c>
  </row>
  <row r="4">
    <c r="A4" t="s" s="0"><v>4</v></c>   <!-- "Avg Deal Size" -->
    <c r="B4" s="3"><f>IF(B3=0,0,B2/B3)</f><v></v></c>
  </row>
</sheetData>
```

### Scenario C — Multi-Department Consolidation

`Consolidated` sheet sums the same cells from multiple department sheets:

```xml
<!-- Consolidated/sheet4.xml — summing across Dept_Eng and Dept_Mkt -->
<sheetData>
  <row r="5">
    <c r="A5" t="s" s="2"><v>0</v></c>
    <!-- No spaces in sheet names → no quotes needed -->
    <c r="B5" s="3"><f>Dept_Engineering!B5+Dept_Marketing!B5</f><v></v></c>
  </row>
  <row r="6">
    <c r="A6" t="s" s="2"><v>1</v></c>
    <c r="B6" s="3"><f>SUM(Dept_Engineering!B6,Dept_Marketing!B6)</f><v></v></c>
  </row>
</sheetData>
```

---

## What You Must NOT Do

- Do NOT use openpyxl or any Python library to write the final xlsx file
- Do NOT hardcode any calculated value — use `<f>` formulas for every derived number
- Do NOT deliver without running `formula_check.py` first
- Do NOT set a cell's `s` attribute to a value >= `cellXfs count`
- Do NOT modify an existing `<xf>` entry in `styles.xml` — only append new ones
- Do NOT add a new sheet without updating all four sync points (workbook.xml,
  workbook.xml.rels, [Content_Types].xml, actual .xml file)
- Do NOT assign new worksheet rIds that overlap with rId1, rId2, or rId3 (reserved
  for sheet1, styles, sharedStrings in the template)
