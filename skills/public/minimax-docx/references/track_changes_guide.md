# Track Changes Guide

## Overview

Track Changes in OpenXML uses revision markup elements to record insertions, deletions, and formatting changes. Each revision has a unique ID, author, and timestamp.

---

## Insertion: `<w:ins>`

Wraps runs that were inserted during tracking:

```xml
<w:ins w:id="1" w:author="John Smith" w:date="2026-03-21T10:30:00Z">
  <w:r>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" />
      <w:sz w:val="22" />
    </w:rPr>
    <w:t>This text was inserted.</w:t>
  </w:r>
</w:ins>
```

- `w:id` — unique revision ID (integer, must be unique across document)
- `w:author` — free text string identifying the author
- `w:date` — ISO 8601 format with timezone: `YYYY-MM-DDTHH:MM:SSZ`
- Content inside is normal runs (`w:r`) with optional formatting

---

## Deletion: `<w:del>`

Wraps runs that were deleted during tracking:

```xml
<w:del w:id="2" w:author="John Smith" w:date="2026-03-21T10:31:00Z">
  <w:r>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" />
      <w:sz w:val="22" />
    </w:rPr>
    <w:delText xml:space="preserve">This text was deleted.</w:delText>
  </w:r>
</w:del>
```

**CRITICAL**: Inside `<w:del>`, text MUST use `<w:delText>`, NOT `<w:t>`. Using `<w:t>` inside a deletion is invalid and will cause corruption or unexpected behavior. Word may silently repair it, but other consumers will fail.

---

## Formatting Change: `<w:rPrChange>`

Records that a run's formatting was changed. Placed inside `w:rPr`, it stores the **previous** formatting:

```xml
<w:r>
  <w:rPr>
    <w:b />  <!-- Current: bold -->
    <w:rPrChange w:id="3" w:author="Jane Doe" w:date="2026-03-21T11:00:00Z">
      <w:rPr>
        <!-- Previous: not bold (empty rPr means no formatting) -->
      </w:rPr>
    </w:rPrChange>
  </w:rPr>
  <w:t>This text was made bold.</w:t>
</w:r>
```

The outer `w:rPr` holds the **new** (current) formatting. The `w:rPrChange` child holds the **old** (previous) formatting.

---

## Paragraph Property Change: `<w:pPrChange>`

Records paragraph-level formatting changes (alignment, spacing, style):

```xml
<w:pPr>
  <w:jc w:val="center" />  <!-- Current: centered -->
  <w:pPrChange w:id="4" w:author="Jane Doe" w:date="2026-03-21T11:05:00Z">
    <w:pPr>
      <w:jc w:val="left" />  <!-- Previous: left-aligned -->
    </w:pPr>
  </w:pPrChange>
</w:pPr>
```

---

## Revision ID Management

- Every revision element (`w:ins`, `w:del`, `w:rPrChange`, `w:pPrChange`, `w:tblPrChange`, etc.) requires a `w:id` attribute
- IDs must be **unique integers** across the entire document
- IDs should be **monotonically increasing** (not strictly required, but expected by Word)
- When adding revisions, scan for the current maximum `w:id` and increment from there

```
Existing max ID: 47
New insertion: w:id="48"
New deletion: w:id="49"
```

---

## Author and Date

- **Author**: Free text. Use consistent strings (e.g., `"MiniMaxAI"` for all automated edits)
- **Date**: ISO 8601 with UTC timezone marker: `2026-03-21T10:30:00Z`
  - Must include the `T` separator and `Z` suffix (or `+HH:MM` offset)
  - Omitting the date is allowed but not recommended

---

## Operations

### Propose Insertion

Add `<w:ins>` wrapper around new content at the target location:

```xml
<w:p>
  <w:r><w:t>Existing text. </w:t></w:r>
  <w:ins w:id="5" w:author="MiniMaxAI" w:date="2026-03-21T12:00:00Z">
    <w:r><w:t>Proposed new text. </w:t></w:r>
  </w:ins>
  <w:r><w:t>More existing text.</w:t></w:r>
</w:p>
```

### Propose Deletion

Wrap existing content in `<w:del>` and change `<w:t>` to `<w:delText>`:

```xml
<w:p>
  <w:r><w:t>Keep this. </w:t></w:r>
  <w:del w:id="6" w:author="MiniMaxAI" w:date="2026-03-21T12:01:00Z">
    <w:r>
      <w:rPr><w:b /></w:rPr>
      <w:delText>Remove this.</w:delText>
    </w:r>
  </w:del>
  <w:r><w:t> Keep this too.</w:t></w:r>
</w:p>
```

### Accept a Tracked Change

- **Accept insertion**: Remove the `<w:ins>` wrapper, keep the inner runs as normal content
- **Accept deletion**: Remove the entire `<w:del>` element and its content

### Reject a Tracked Change

- **Reject insertion**: Remove the entire `<w:ins>` element and its content
- **Reject deletion**: Remove the `<w:del>` wrapper, change `<w:delText>` back to `<w:t>`

---

## Cross-Paragraph Operations

### Deleting a Paragraph Break (Merging Paragraphs)

When tracked deletion spans a paragraph boundary, use `<w:pPrChange>` on the merged paragraph:

```xml
<w:p>
  <w:pPr>
    <w:pPrChange w:id="7" w:author="MiniMaxAI" w:date="2026-03-21T12:05:00Z">
      <w:pPr>
        <w:pStyle w:val="Normal" />
      </w:pPr>
    </w:pPrChange>
  </w:pPr>
  <w:r><w:t>First paragraph text. </w:t></w:r>
  <w:del w:id="8" w:author="MiniMaxAI" w:date="2026-03-21T12:05:00Z">
    <w:r><w:delText> </w:delText></w:r>
  </w:del>
  <w:r><w:t>Second paragraph text (now merged).</w:t></w:r>
</w:p>
```

### Inserting a New Paragraph

The entire new paragraph is wrapped in `<w:ins>`:

```xml
<w:p>
  <w:pPr>
    <w:rPr>
      <w:ins w:id="9" w:author="MiniMaxAI" w:date="2026-03-21T12:10:00Z" />
    </w:rPr>
  </w:pPr>
  <w:ins w:id="10" w:author="MiniMaxAI" w:date="2026-03-21T12:10:00Z">
    <w:r><w:t>Entirely new paragraph.</w:t></w:r>
  </w:ins>
</w:p>
```

The paragraph mark itself is marked as inserted via `w:ins` inside `w:pPr > w:rPr`.
