# Scenario B: Editing / Filling Content in Existing DOCX

## Core Principle

**"First, do no harm."** When editing an existing document, minimize changes. Touch only what needs to change. Preserve all formatting, styles, relationships, and structure that are not directly involved in the edit.

---

## When to Use

- Replacing placeholder text (`{{name}}`, `$DATE$`, `[PLACEHOLDER]`)
- Updating specific paragraphs or table cells
- Filling in form fields
- Adding or removing paragraphs in a known location
- Inserting tracked changes for review workflows

Do NOT use when: the user wants to change the look/style of the entire document (→ Scenario C) or create from scratch (→ Scenario A).

---

## Workflow

```
1. Preview   → CLI: analyze <input.docx>
2. Analyze   → Understand structure: sections, styles, headings, tables
3. Identify  → Locate exact edit targets (paragraph index, table index, placeholder text)
4. Edit      → Apply surgical changes via CLI or direct XML
5. Validate  → CLI: validate <output.docx>
6. Diff      → Compare before/after to verify only intended changes were made
```

---

## When to Use API vs Direct XML

### Use CLI Edit Command When:
- Replacing placeholder text (e.g., `{{fieldName}}` → actual value)
- Filling table data from JSON
- Updating document properties (title, author)
- Simple text insertions or deletions

### Use Direct XML Manipulation When:
- Text spans multiple runs with different formatting (run-boundary issues)
- Adding complex structures (nested tables, multi-image layouts)
- Manipulating Track Changes markup
- Modifying header/footer content
- Adjusting section properties

---

## Placeholder Patterns

The CLI natively supports `{{fieldName}}` placeholders:

```bash
# Replace all {{placeholders}} from a JSON map
dotnet run ... edit input.docx --fill-placeholders data.json --output filled.docx
```

Where `data.json`:
```json
{
  "companyName": "Acme Corp",
  "date": "March 21, 2026",
  "amount": "$15,000.00",
  "recipientName": "Jane Smith"
}
```

Other placeholder formats (`$FIELD$`, `[PLACEHOLDER]`) require text replacement:
```bash
dotnet run ... edit input.docx --replace "$DATE$" "March 21, 2026" --output updated.docx
```

---

## Text Replacement Strategies

### Simple Replacement

When the entire search text is within a single `w:r` (run):

```xml
<!-- Before -->
<w:r>
  <w:rPr><w:b /></w:rPr>
  <w:t>{{companyName}}</w:t>
</w:r>

<!-- After — formatting preserved -->
<w:r>
  <w:rPr><w:b /></w:rPr>
  <w:t>Acme Corp</w:t>
</w:r>
```

Direct replacement. The run's `w:rPr` is untouched.

### Complex Replacement (Split Runs)

When the search text is split across multiple runs (common when Word applies spell-check or formatting mid-text):

```xml
<!-- "{{companyName}}" split into 3 runs -->
<w:r><w:rPr><w:b /></w:rPr><w:t>{{company</w:t></w:r>
<w:r><w:rPr><w:b /><w:i /></w:rPr><w:t>Na</w:t></w:r>
<w:r><w:rPr><w:b /></w:rPr><w:t>me}}</w:t></w:r>
```

Strategy:
1. Concatenate text across runs to find the match
2. Place the replacement text in the **first** run (preserving its `w:rPr`)
3. Remove the text from subsequent runs (or remove the runs entirely if empty)

```xml
<!-- After -->
<w:r><w:rPr><w:b /></w:rPr><w:t>Acme Corp</w:t></w:r>
```

**Rule**: Always preserve the formatting of the first run in the match.

---

## Table Editing

### By Index

Tables are 0-indexed in document order:

```bash
dotnet run ... edit input.docx --table-index 0 --table-data data.json --output updated.docx
```

### By Header Matching

Find a table by its header row content:

```bash
dotnet run ... edit input.docx --table-match "Name,Amount,Date" --table-data data.json
```

### Table Data JSON Format

```json
{
  "rows": [
    ["Alice Johnson", "$5,000", "2026-03-15"],
    ["Bob Smith", "$3,200", "2026-03-18"]
  ],
  "appendRows": true
}
```

- `appendRows: true` — add rows after existing data
- `appendRows: false` (default) — replace all data rows (keeps header row)

### Direct XML Table Editing

To modify a specific cell, locate it by row/column index:

```xml
<!-- Row 2 (0-indexed), Column 1 -->
<w:tr>  <!-- tr[2] -->
  <w:tc>...</w:tc>
  <w:tc>  <!-- tc[1] — target cell -->
    <w:p>
      <w:r><w:t>Old Value</w:t></w:r>
    </w:p>
  </w:tc>
</w:tr>
```

Replace the `w:t` content. Do NOT modify `w:tcPr` (cell properties) or `w:tblPr` (table properties).

---

## Track Changes Guidance

### When to Add Revision Marks
- User explicitly requests tracked changes
- Document already has tracking enabled (`w:trackChanges` in settings)
- Collaborative review workflow

### When NOT to Add Revision Marks
- Form filling / placeholder replacement (these are "completing" the document, not "revising" it)
- Direct edits where the user wants a clean result
- Batch data filling operations

### Adding Tracked Changes

See `references/track_changes_guide.md` for full XML examples.

Quick reference — inserting text with tracking:
```xml
<w:ins w:id="1" w:author="MiniMaxAI" w:date="2026-03-21T10:00:00Z">
  <w:r>
    <w:t>New text here</w:t>
  </w:r>
</w:ins>
```

Deleting text with tracking:
```xml
<w:del w:id="2" w:author="MiniMaxAI" w:date="2026-03-21T10:00:00Z">
  <w:r>
    <w:delText>Removed text</w:delText>  <!-- MUST use delText, not t -->
  </w:r>
</w:del>
```

---

## Common Pitfalls

### 1. Breaking Run Boundaries

**Problem**: Replacing text that spans runs by naively modifying individual runs destroys inline formatting.

**Fix**: Concatenate run text, find match boundaries, consolidate into the first run, remove consumed runs.

### 2. Hyperlink Content

**Problem**: Replacing text inside a `w:hyperlink` element without preserving the hyperlink wrapper removes the link.

```xml
<w:hyperlink r:id="rId5">
  <w:r>
    <w:rPr><w:rStyle w:val="Hyperlink" /></w:rPr>
    <w:t>Click here</w:t>  <!-- Only replace this text -->
  </w:r>
</w:hyperlink>
```

**Fix**: Only modify the `w:t` inside the hyperlink's run. Never remove or replace the `w:hyperlink` element itself.

### 3. Tracked Change Context

**Problem**: Replacing text that is inside a `w:ins` or `w:del` element without understanding the revision context creates invalid markup.

**Fix**: If the target text is inside a revision mark, either:
- Replace within the revision context (preserving the `w:ins`/`w:del` wrapper)
- Or delete the old revision and create a new one

### 4. Style Preservation

**Problem**: Adding new paragraphs without specifying a style causes them to inherit `Normal`, which may not match the surrounding context.

**Fix**: When inserting paragraphs, copy the `w:pStyle` from an adjacent paragraph of the same type.

### 5. Numbering Continuity

**Problem**: Inserting a new list item breaks numbering sequence.

**Fix**: Ensure the new paragraph has the same `w:numId` and `w:ilvl` as adjacent list items. If continuing a sequence, set `w:numPr` to match.

### 6. XML Special Characters

**Problem**: User content contains `&`, `<`, `>`, `"`, `'` — these must be escaped in XML.

**Fix**: Always XML-escape user-provided text before inserting into `w:t` elements:
- `&` → `&amp;`
- `<` → `&lt;`
- `>` → `&gt;`
- `"` → `&quot;`
- `'` → `&apos;`

### 7. Whitespace Preservation

**Problem**: Leading/trailing spaces in `w:t` are stripped by XML parsers.

**Fix**: Add `xml:space="preserve"` attribute:
```xml
<w:t xml:space="preserve"> text with leading space</w:t>
```

---

## Diff Verification

After editing, always compare the before and after states:

```bash
# Structural diff — shows only changed elements
dotnet run ... diff original.docx modified.docx

# Text-only diff — shows content changes
dotnet run ... diff original.docx modified.docx --text-only
```

Verify:
- Only intended text changed
- No styles were modified
- No relationships were added/removed unexpectedly
- Table structure intact (same number of rows/columns unless intentionally changed)
- Images and other media unchanged
