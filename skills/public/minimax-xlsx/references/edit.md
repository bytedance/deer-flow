# Minimal-Invasive Editing of Existing xlsx

Make precise, surgical changes to existing xlsx files while preserving everything you do not touch: styles, macros, pivot tables, charts, sparklines, named ranges, data validation, conditional formatting, and all other embedded content.

---

## 1. When to Use This Path

Use the edit (unpack → XML edit → pack) path whenever the task involves **modifying an existing xlsx file**:

- Template filling — populating designated input cells with values or formulas
- Data updates — replacing outdated numbers, text, or dates in a live file
- Content corrections — fixing wrong values, broken formulas, or mistyped labels
- Adding new data rows to an existing table
- Renaming a sheet
- Applying a new style to specific cells

Do NOT use this path for creating a brand-new workbook from scratch. For that, see `create.md`.

---

## 2. Why openpyxl round-trip Is Forbidden for Existing Files

openpyxl `load_workbook()` followed by `workbook.save()` is a **destructive operation** on any file that contains advanced features. The library silently drops content it does not understand:

| Feature | openpyxl behavior | Consequence |
|---------|-------------------|-------------|
| VBA macros (`vbaProject.bin`) | Dropped entirely | All automation is lost; file saved as `.xlsx` not `.xlsm` |
| Pivot tables (`xl/pivotTables/`) | Dropped | Interactive analysis is destroyed |
| Slicers | Dropped | Filter UI is lost |
| Sparklines (`<sparklineGroups>`) | Dropped | In-cell mini-charts disappear |
| Chart formatting details | Partially lost | Series colors, custom axes may revert |
| Print area / page breaks | Sometimes lost | Print layout changes |
| Custom XML parts | Dropped | Third-party data bindings broken |
| Theme-linked colors | May be de-themed | Colors converted to absolute, breaking theme switching |

Even on a "plain" file without these features, openpyxl may normalize whitespace in XML that Excel relies on, alter namespace declarations, or reset `calcMode` flags.

**The rule is absolute: never open an existing file with openpyxl for the purpose of re-saving it.**

The XML direct-edit approach is safe because it operates on the raw bytes. You only change the nodes you touch. Everything else is byte-equivalent to the original.

---

## 3. Standard Operating Procedure

### Step 1 — Unpack

```bash
python3 SKILL_DIR/scripts/xlsx_unpack.py input.xlsx /tmp/xlsx_work/
```

The script unzips the xlsx, pretty-prints every XML and `.rels` file, and prints a categorized inventory of key files plus a warning if high-risk content is detected (VBA, pivot tables, charts).

Read the printed output carefully before proceeding. If the script reports `xl/vbaProject.bin` or `xl/pivotTables/`, follow the constraints in Section 7.

### Step 2 — Reconnaissance

Map the structure before touching anything.

**Identify sheet names and their XML files:**

```
xl/workbook.xml  →  <sheet name="Revenue" sheetId="1" r:id="rId1"/>
xl/_rels/workbook.xml.rels  →  <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
```

The sheet named "Revenue" lives in `xl/worksheets/sheet1.xml`. Always resolve this mapping before editing a worksheet.

**Understand the shared strings table:**

```bash
# Count existing entries in xl/sharedStrings.xml
grep -c "<si>" /tmp/xlsx_work/xl/sharedStrings.xml
```

Every text cell uses a zero-based index into this table. Know the current count before appending.

**Understand the styles table:**

```bash
# Count existing cellXfs entries
grep -c "<xf " /tmp/xlsx_work/xl/styles.xml
```

New style slots are appended after existing ones. The index of the first new slot = current count.

**Scan for high-risk XML regions in the target worksheet:**

Look for these elements in the target `sheet*.xml` before editing:

- `<mergeCell>` — merged cell ranges; row/column insertion shifts these
- `<conditionalFormatting>` — condition ranges; row/column insertion shifts these
- `<dataValidations>` — validation ranges; row/column insertion shifts these
- `<tableParts>` — table definitions; row insertion inside a table needs `<tableColumn>` updates
- `<sparklineGroups>` — sparklines; preserve without modification

### Step 3 — Map Intent to Minimal XML Changes

Before writing a single character, produce a written list of exactly which XML nodes change. This prevents scope creep.

| User intent | Files to change | Nodes to change |
|-------------|----------------|-----------------|
| Change a cell's numeric value | `xl/worksheets/sheetN.xml` | `<v>` inside target `<c>` |
| Change a cell's text | `xl/sharedStrings.xml` (append) + `xl/worksheets/sheetN.xml` | New `<si>`, update cell `<v>` index |
| Change a cell's formula | `xl/worksheets/sheetN.xml` | `<f>` text inside target `<c>` |
| Add a new data row at the bottom | `xl/worksheets/sheetN.xml` + possibly `xl/sharedStrings.xml` | Append `<row>` element |
| Apply a new style to cells | `xl/styles.xml` + `xl/worksheets/sheetN.xml` | Append `<xf>` in `<cellXfs>`, update `s` attribute on `<c>` |
| Rename a sheet | `xl/workbook.xml` | `name` attribute on `<sheet>` element |
| Rename a sheet (with cross-sheet formulas) | `xl/workbook.xml` + all `xl/worksheets/*.xml` | `name` attribute + `<f>` text referencing old name |

### Step 4 — Execute Changes

Use the Edit tool. Edit the minimum. Never rewrite whole files.

See Section 4 for precise XML patterns for each operation type.

### Step 5 — Cascade Check

After any change that shifts row or column positions, audit all affected XML regions. See Section 5.

### Step 6 — Pack and Validate

```bash
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
python3 SKILL_DIR/scripts/formula_check.py output.xlsx
```

The pack script validates XML well-formedness before creating the ZIP. Fix any reported parse errors before packing. After packing, run `formula_check.py` to confirm no formula errors were introduced.

---

## 4. Precise XML Patterns for Common Edits

### 4.1 Changing a Numeric Cell Value

Find the `<c r="B5">` element in the worksheet XML and replace the `<v>` text.

**Before:**
```xml
<c r="B5">
  <v>1000</v>
</c>
```

**After (new value 1500):**
```xml
<c r="B5">
  <v>1500</v>
</c>
```

Rules:
- Do not add or remove the `s` attribute (style) unless explicitly changing the style.
- Do not add a `t` attribute — numbers omit `t` or use `t="n"`.
- Do not change the `r` attribute (cell reference).

---

### 4.2 Changing a Text Cell Value

Text cells reference the shared strings table by index (`t="s"`). You cannot edit the string in-place without affecting every other cell that uses the same index. The safe approach is to append a new entry.

**Before — shared strings file (`xl/sharedStrings.xml`):**
```xml
<sst count="4" uniqueCount="4">
  <si><t>Revenue</t></si>
  <si><t>Cost</t></si>
  <si><t>Margin</t></si>
  <si><t>Old Label</t></si>
</sst>
```

**After — append new string, increment counts:**
```xml
<sst count="5" uniqueCount="5">
  <si><t>Revenue</t></si>
  <si><t>Cost</t></si>
  <si><t>Margin</t></si>
  <si><t>Old Label</t></si>
  <si><t>New Label</t></si>
</sst>
```

New string is at index 4 (zero-based).

**Before — cell in worksheet XML:**
```xml
<c r="A7" t="s">
  <v>3</v>
</c>
```

**After — point to new index:**
```xml
<c r="A7" t="s">
  <v>4</v>
</c>
```

Rules:
- Never modify or delete existing `<si>` entries. Only append.
- Both `count` and `uniqueCount` must be incremented together.
- If the new string contains `&`, `<`, or `>`, escape them: `&amp;`, `&lt;`, `&gt;`.
- If the string has leading or trailing spaces, add `xml:space="preserve"` to `<t>`:
  ```xml
  <si><t xml:space="preserve">  indented text  </t></si>
  ```

---

### 4.3 Changing a Formula

Formulas are stored in `<f>` elements **without a leading `=`** (unlike what you type in Excel's UI).

**Before:**
```xml
<c r="C10">
  <f>SUM(C2:C9)</f>
  <v>4800</v>
</c>
```

**After (extended range):**
```xml
<c r="C10">
  <f>SUM(C2:C11)</f>
  <v></v>
</c>
```

Rules:
- Clear `<v>` to an empty string when changing the formula. The cached value is now stale.
- Do not add `t="s"` or any type attribute to formula cells. The `t` attribute is absent or uses a result-type value, not a formula marker.
- Cross-sheet references use `SheetName!CellRef`. If the sheet name contains spaces, wrap in single quotes: `'Q1 Data'!B5`.
- The `<f>` text must not include the leading `=`.

**Before (converting a hardcoded value to a live formula):**
```xml
<c r="D15">
  <v>95000</v>
</c>
```

**After:**
```xml
<c r="D15">
  <f>SUM(D2:D14)</f>
  <v></v>
</c>
```

---

### 4.4 Adding a New Data Row

Append after the last `<row>` element inside `<sheetData>`. Row numbers in OOXML are 1-based and must be sequential.

**Before (last row is row 10):**
```xml
  <row r="10">
    <c r="A10" t="s"><v>3</v></c>
    <c r="B10"><v>2023</v></c>
    <c r="C10"><v>88000</v></c>
    <c r="D10"><f>C10*1.1</f><v></v></c>
  </row>
</sheetData>
```

**After (new row 11 appended):**
```xml
  <row r="10">
    <c r="A10" t="s"><v>3</v></c>
    <c r="B10"><v>2023</v></c>
    <c r="C10"><v>88000</v></c>
    <c r="D10"><f>C10*1.1</f><v></v></c>
  </row>
  <row r="11">
    <c r="A11" t="s"><v>4</v></c>
    <c r="B11"><v>2024</v></c>
    <c r="C11"><v>96000</v></c>
    <c r="D11"><f>C11*1.1</f><v></v></c>
  </row>
</sheetData>
```

Rules:
- Every `<c>` inside the row must have `r` set to the correct cell address (e.g., `A11`).
- Text cells need `t="s"` and a sharedStrings index in `<v>`. Numeric cells omit `t`.
- Formula cells use `<f>` and an empty `<v>`.
- Copy the `s` attribute from the row above if you want matching styles. Do not invent a style index that does not exist in `styles.xml`.
- If the sheet contains a `<dimension>` element (e.g., `<dimension ref="A1:D10"/>`), update it to include the new row: `<dimension ref="A1:D11"/>`.
- If the sheet contains a `<tableparts>` referencing a table, update the table's `ref` attribute in the corresponding `xl/tables/tableN.xml` file.

---

### 4.5 Adding a New Column

Append new `<c>` elements to each existing `<row>` and, if present, update the `<cols>` section.

**Before (rows have columns A–C):**
```xml
<cols>
  <col min="1" max="3" width="14" customWidth="1"/>
</cols>
<sheetData>
  <row r="1">
    <c r="A1" t="s"><v>0</v></c>
    <c r="B1" t="s"><v>1</v></c>
    <c r="C1" t="s"><v>2</v></c>
  </row>
  <row r="2">
    <c r="A2"><v>100</v></c>
    <c r="B2"><v>200</v></c>
    <c r="C2"><v>300</v></c>
  </row>
</sheetData>
```

**After (adding column D):**
```xml
<cols>
  <col min="1" max="3" width="14" customWidth="1"/>
  <col min="4" max="4" width="14" customWidth="1"/>
</cols>
<sheetData>
  <row r="1">
    <c r="A1" t="s"><v>0</v></c>
    <c r="B1" t="s"><v>1</v></c>
    <c r="C1" t="s"><v>2</v></c>
    <c r="D1" t="s"><v>5</v></c>
  </row>
  <row r="2">
    <c r="A2"><v>100</v></c>
    <c r="B2"><v>200</v></c>
    <c r="C2"><v>300</v></c>
    <c r="D2"><f>A2+B2+C2</f><v></v></c>
  </row>
</sheetData>
```

Rules:
- Adding a column at the end (after the last existing column) is safe — no existing formula references shift.
- Inserting a column in the middle shifts all columns to the right, which requires the same cascade updates as row insertion (see Section 5).
- Update the `<dimension>` element if present.

---

### 4.6 Modifying or Adding Styles

Styles use a multi-level indirect reference chain. Read `ooxml-cheatsheet.md` for the full chain. The key rule: **only append new entries, never modify existing ones**.

**Scenario:** Add a blue-font style (for hardcoded input cells) that doesn't yet exist.

**Step 1 — Check if a matching font already exists in `xl/styles.xml`:**
```xml
<!-- Look inside <fonts> for an existing blue font -->
<font>
  <color rgb="000000FF"/>
  <!-- other attributes -->
</font>
```

If found, note its index (zero-based position in the `<fonts>` list). If not found, append.

**Step 2 — Append the new font if needed:**

Before:
```xml
<fonts count="3">
  <font>...</font>   <!-- index 0 -->
  <font>...</font>   <!-- index 1 -->
  <font>...</font>   <!-- index 2 -->
</fonts>
```

After:
```xml
<fonts count="4">
  <font>...</font>   <!-- index 0 -->
  <font>...</font>   <!-- index 1 -->
  <font>...</font>   <!-- index 2 -->
  <font>
    <b/>
    <sz val="11"/>
    <color rgb="000000FF"/>
    <name val="Calibri"/>
  </font>             <!-- index 3 (new) -->
</fonts>
```

**Step 3 — Append a new `<xf>` in `<cellXfs>`:**

Before:
```xml
<cellXfs count="5">
  <xf .../>   <!-- index 0 -->
  <xf .../>   <!-- index 1 -->
  <xf .../>   <!-- index 2 -->
  <xf .../>   <!-- index 3 -->
  <xf .../>   <!-- index 4 -->
</cellXfs>
```

After:
```xml
<cellXfs count="6">
  <xf .../>   <!-- index 0 -->
  <xf .../>   <!-- index 1 -->
  <xf .../>   <!-- index 2 -->
  <xf .../>   <!-- index 3 -->
  <xf .../>   <!-- index 4 -->
  <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0"
      applyFont="1"/>   <!-- index 5 (new) -->
</cellXfs>
```

**Step 4 — Apply to target cells:**

Before:
```xml
<c r="B3">
  <v>0.08</v>
</c>
```

After:
```xml
<c r="B3" s="5">
  <v>0.08</v>
</c>
```

Rules:
- Never delete or reorder existing entries in `<fonts>`, `<fills>`, `<borders>`, `<cellXfs>`.
- Always update the `count` attribute when appending.
- The new `cellXfs` index = the old `count` value before appending (zero-based: if count was 5, new index is 5).
- Custom `numFmt` IDs must be 164 or above. IDs 0–163 are built-in and must not be re-declared.
- If the desired style already exists elsewhere in the file (on a similar cell), reuse its `s` index rather than creating a duplicate.

---

### 4.7 Renaming a Sheet

**Only `xl/workbook.xml` needs to change** — unless cross-sheet formulas reference the old name.

**Before (`xl/workbook.xml`):**
```xml
<sheet name="Sheet1" sheetId="1" r:id="rId1"/>
```

**After:**
```xml
<sheet name="Revenue" sheetId="1" r:id="rId1"/>
```

**If any formula in any worksheet references the old name, update those too:**

Before (`xl/worksheets/sheet2.xml`):
```xml
<c r="B5"><f>Sheet1!C10</f><v></v></c>
```

After:
```xml
<c r="B5"><f>Revenue!C10</f><v></v></c>
```

If the new name contains spaces:
```xml
<c r="B5"><f>'Q1 Revenue'!C10</f><v></v></c>
```

Scan all worksheet XML files for the old name:
```bash
grep -r "Sheet1!" /tmp/xlsx_work/xl/worksheets/
```

Rules:
- The `.rels` file and `[Content_Types].xml` do NOT need to change — they reference the XML file path, not the sheet name.
- `sheetId` must not change; it is a stable internal identifier.
- Sheet names are case-sensitive in formula references.

---

## 5. High-Risk Operations — Cascade Effects

### 5.1 Inserting a Row in the Middle

Inserting a row at position N shifts all rows from N downward. Every reference to those rows in every XML file must be updated.

**Files to check and update:**

| XML region | What to update | Example shift |
|------------|---------------|---------------|
| Worksheet `<row r="...">` attributes | Increment row number for all rows >= N | `r="7"` → `r="8"` |
| All `<c r="...">` within those rows | Increment row number in cell address | `r="A7"` → `r="A8"` |
| All `<f>` formula text in any sheet | Shift absolute row references >= N | `B7` → `B8` |
| `<mergeCell ref="...">` | Shift start and end rows | `A7:C7` → `A8:C8` |
| `<conditionalFormatting sqref="...">` | Shift range | `A5:D20` → `A5:D21` |
| `<dataValidations sqref="...">` | Shift range | `B6:B50` → `B7:B51` |
| `xl/charts/chartN.xml` data source ranges | Shift series ranges | `Sheet1!$B$5:$B$20` → `Sheet1!$B$6:$B$21` |
| `xl/pivotTables/*.xml` source ranges | Shift source data range | Handle with extreme care — see Section 7 |
| `<dimension ref="...">` | Expand to include new extent | `A1:D20` → `A1:D21` |
| `xl/tables/tableN.xml` `ref` attribute | Expand table boundary | `A1:D20` → `A1:D21` |

**Do not attempt row insertion manually in large or formula-heavy files.** Use the dedicated shift script instead:

```bash
# Insert 1 row at row 5: all rows 5 and below shift down by 1
python3 SKILL_DIR/scripts/xlsx_shift_rows.py /tmp/xlsx_work/ insert 5 1

# Delete 1 row at row 8: all rows 9 and above shift up by 1
python3 SKILL_DIR/scripts/xlsx_shift_rows.py /tmp/xlsx_work/ delete 8 1
```

The script updates in one pass: `<row r="...">` attributes, `<c r="...">` cell addresses, all `<f>` formula text across every worksheet, `<mergeCell>` ranges, `<conditionalFormatting sqref="...">`, `<dataValidation sqref="...">`, `<dimension ref="...">`, table `ref` attributes in `xl/tables/`, chart series ranges in `xl/charts/`, and pivot cache source ranges in `xl/pivotCaches/`.

**After running the shift script, always repack and validate:**
```bash
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx
python3 SKILL_DIR/scripts/formula_check.py output.xlsx
```

**What the script does NOT update (review manually):**
- Named ranges in `xl/workbook.xml` `<definedNames>` — check and update if they reference shifted rows.
- Structured table references (`Table[@Column]`) inside formulas.
- External workbook links in `xl/externalLinks/`.

### 5.2 Inserting a Column in the Middle

Same cascade logic as row insertion, but for columns. Column references in formulas (`B`, `$C`, etc.) and in merged cell ranges, conditional formatting ranges, and chart data sources all need updating.

Column letter shifting is harder to automate safely. Prefer **appending columns at the end** whenever possible.

### 5.3 Deleting a Row or Column

Deletion is more dangerous than insertion because any formula that referenced a deleted row or column will become `#REF!`. Before deleting:

1. Search all `<f>` elements for references to the deleted range.
2. If any formula references a cell in the deleted row/column, do not delete — instead, either clear the row's data or consult the user.
3. After deletion, shift all references to rows/columns beyond the deletion point downward/leftward.

---

## 6. Template Filling — Identifying and Populating Input Cells

Templates designate certain cells as input zones. Common patterns to recognize them:

### 6.1 How Templates Signal Input Zones

| Signal | XML manifestation | What to look for |
|--------|-------------------|-----------------|
| Blue font color | `s` attribute pointing to a `cellXfs` entry with `fontId` → `<color rgb="000000FF"/>` | Check `styles.xml` to decode `s` values |
| Yellow fill (highlight) | `s` → `fillId` → `<fill><patternFill><fgColor rgb="00FFFF00"/>` | |
| Empty `<v>` element | `<c r="B5"><v></v></c>` or cell entirely absent from `<row>` | The cell has no value yet |
| Comment/annotation near cell | `xl/comments1.xml` with `ref="B5"` | Comments often label input fields |
| Named ranges | `xl/workbook.xml` `<definedName>` elements | Template may define `InputRevenue` etc. |

### 6.2 Filling a Template Cell

Do not change `s` attributes. Do not change `t` attributes unless you must change from empty to typed. Only change `<v>` or add `<f>`.

**Before (empty input cell with style preserved):**
```xml
<c r="C5" s="3">
  <v></v>
</c>
```

**After (filled with a number, style unchanged):**
```xml
<c r="C5" s="3">
  <v>125000</v>
</c>
```

**After (filled with text — requires shared string entry first):**
```xml
<!-- 1. Append to sharedStrings.xml: <si><t>North Region</t></si> at index 7 -->
<c r="C5" t="s" s="3">
  <v>7</v>
</c>
```

**After (filled with a formula, preserving style):**
```xml
<c r="C5" s="3">
  <f>Assumptions!D12</f>
  <v></v>
</c>
```

### 6.3 Locating Input Zones Without Opening the File in Excel

After unpacking, decode the style index on suspected input cells to determine if they have the template's input color:

1. Note the `s` value on the cell (e.g., `s="4"`).
2. In `xl/styles.xml`, find `<cellXfs>` and look at the 5th entry (index 4).
3. Note its `fontId` (e.g., `fontId="2"`).
4. In `<fonts>`, look at the 3rd entry (index 2) and check for `<color rgb="000000FF"/>` (blue) or other input marker.

If the template uses named ranges as input fields, read them from `xl/workbook.xml`:
```xml
<definedNames>
  <definedName name="InputGrowthRate">Assumptions!$B$5</definedName>
  <definedName name="InputDiscountRate">Assumptions!$B$6</definedName>
</definedNames>
```

Fill the target cells (`Assumptions!B5`, `Assumptions!B6`) directly.

### 6.4 Template Filling Rules

- Fill only cells the template designated as inputs. Do not fill cells that are formula-driven.
- Do not apply new styles when filling. The template's formatting is the deliverable.
- Do not add or remove rows inside the template's data area unless the template explicitly has an "append here" zone.
- After filling, verify that no formula errors were introduced: some templates have input-validation formulas that produce `#VALUE!` if the wrong data type is entered.

---

## 7. Files You Must Never Modify

### 7.1 Absolute no-touch list

| File / location | Why |
|-----------------|-----|
| `xl/vbaProject.bin` | Binary VBA bytecode. Any byte modification corrupts the macro project. Editing even one bit makes the macros fail to load. |
| `xl/pivotCaches/pivotCacheDefinition*.xml` | The cache definition ties the pivot table to its source data. Editing it without also updating the corresponding `pivotTable*.xml` will corrupt the pivot. |
| `xl/pivotTables/*.xml` | Pivot table XML is tightly coupled with the cache definition and with internal state Excel rebuilds on load. Do not edit. If you shifted rows and the pivot's source range now points to wrong data, update only the `<cacheSource>` range in the cache definition, and only the `ref` attribute in the pivot table — no other changes. |
| `xl/slicers/*.xml` | Slicers are connected to specific cache IDs and pivot fields. Breaking these connections silently corrupts the file. |
| `xl/connections.xml` | External data connections. Editing breaks live data refresh. |
| `xl/externalLinks/` | External workbook links. The binary `.bin` files in here must not be modified. |

### 7.2 Conditionally safe files (update only specific attributes)

| File | What you may update | What to leave alone |
|------|--------------------|--------------------|
| `xl/charts/chartN.xml` | Data series range references (`<numRef><f>`) after a row/column shift | Chart type, formatting, layout |
| `xl/tables/tableN.xml` | `ref` attribute on `<table>` after adding rows | Column definitions, style info |
| `xl/pivotCaches/pivotCacheDefinition*.xml` | `ref` attribute on `<cacheSource><worksheetSource>` after shifting source data | All other content |

---

## 8. Validation After Every Edit

Never skip validation. Even a one-character change in a formula can cause cascading errors.

```bash
# Pack
python3 SKILL_DIR/scripts/xlsx_pack.py /tmp/xlsx_work/ output.xlsx

# Static formula validation (always run)
python3 SKILL_DIR/scripts/formula_check.py output.xlsx

# Dynamic validation (if LibreOffice available)
python3 SKILL_DIR/scripts/libreoffice_recalc.py output.xlsx /tmp/recalc.xlsx
python3 SKILL_DIR/scripts/formula_check.py /tmp/recalc.xlsx
```

If `formula_check.py` reports any error:
1. Unpack the output file again (it is the packed version).
2. Locate the reported cell in the worksheet XML.
3. Fix the `<f>` element.
4. Repack and re-validate.

Do not deliver the file until `formula_check.py` reports zero errors.

---

## 9. Absolute Rules Summary

| Rule | Rationale |
|------|-----------|
| Never use openpyxl `load_workbook` + `save` on an existing file | Round-trip destroys pivot tables, VBA, sparklines, slicers |
| Never delete or reorder existing `<si>` entries in sharedStrings | Breaks every cell referencing that index |
| Never delete or reorder existing `<xf>` entries in `<cellXfs>` | Breaks every cell using that style index |
| Never modify `vbaProject.bin` | Binary file; any change corrupts VBA |
| Never change `sheetId` when renaming a sheet | Internal ID is stable; changing it breaks relationships |
| Never skip post-edit validation | Leaves broken references undetected |
| Never edit more XML nodes than required | Extra changes risk introducing subtle corruption |
| Clear `<v>` to empty string when changing a formula | Prevents stale cached value from misleading downstream consumers |
| Append-only to sharedStrings | Existing indexes must remain valid |
| Append-only to styles collections | Existing style indexes must remain valid |
