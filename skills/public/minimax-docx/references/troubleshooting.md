# Troubleshooting Guide — Symptom-Driven

## How to Use This Guide

Search by the **SYMPTOM** you observe, not the technical concept. Each entry follows:
- **Symptom** — what you see or what the user reports
- **Diagnosis** — how to confirm the root cause
- **Fix** — exact steps, commands, or code
- **Prevention** — how to avoid it next time

**Quick search keywords:** headings wrong, body text, repair, corrupt, font, tables missing, images missing, TOC broken, update table, page break, section break, hyperlink, numbered list, bullets, margins, page size, Chinese tofu, cover page, track changes, revision marks

---

## 1. "All headings look like body text" (Heading Styles Not Applied)

**Symptom:** After template application, headings have no formatting — they look like Normal paragraphs. Font size, bold, spacing are all wrong.

**Diagnosis:** The `pStyle` values in `document.xml` don't match the `styleId` values in `styles.xml`.

Common mismatches:
- Source uses `Heading1` but template defines the style as `1` (Chinese templates often use numeric styleIds)
- Source uses `heading1` (lowercase) but template has `Heading1` (case-sensitive!)
- `pStyle` references a style that simply doesn't exist in the output's `styles.xml`

Check with:
```bash
# List all pStyle values used in the document
$CLI analyze --input output.docx | grep -i "pStyle"

# List all styleIds defined in styles.xml
$CLI analyze --input template.docx --part styles | grep "styleId"
```

**Fix:** Build a styleId mapping table before applying the template. Update every `pStyle` value in the document content.

```csharp
// Build mapping: source styleId → template styleId
var mapping = new Dictionary<string, string>();
// Compare by style name (w:name), not by styleId
foreach (var srcStyle in sourceStyles)
{
    var templateStyle = templateStyles.FirstOrDefault(
        s => s.StyleName?.Val?.Value == srcStyle.StyleName?.Val?.Value);
    if (templateStyle != null)
        mapping[srcStyle.StyleId!] = templateStyle.StyleId!;
}

// Apply mapping to all paragraphs
foreach (var para in body.Descendants<Paragraph>())
{
    var pStyle = para.ParagraphProperties?.ParagraphStyleId;
    if (pStyle != null && mapping.TryGetValue(pStyle.Val!, out var newId))
        pStyle.Val = newId;
}
```

**Prevention:** ALWAYS extract and compare styleIds from both source and template before template application. Never assume styleIds are the same across documents.

---

## 2. "Document opens with repair warnings" (XML Corruption)

**Symptom:** Word says "We found a problem with some content" or "Word found unreadable content" when opening.

**Diagnosis:** Element ordering is wrong. OpenXML is strict about child element order.

Common violations:
- `pPr` must come before runs in `w:p`
- `tblPr` must come before `tblGrid` in `w:tbl`
- `rPr` must come before `t`/`br`/`tab` in `w:r`
- `trPr` must come before `tc` in `w:tr`
- `tcPr` must come before content in `w:tc`

```bash
# Validate to find ordering issues
$CLI validate --input doc.docx --xsd assets/xsd/wml-subset.xsd

# Auto-fix element ordering
$CLI fix-order --input doc.docx

# Re-validate
$CLI validate --input doc.docx --xsd assets/xsd/wml-subset.xsd
```

**Fix:**
```bash
$CLI fix-order --input doc.docx
```

If auto-fix doesn't resolve it, unpack and inspect manually:
```bash
$CLI unpack --input doc.docx --output unpacked/
# Check word/document.xml for ordering issues
# Fix, then repack:
$CLI pack --input unpacked/ --output fixed.docx
```

**Prevention:** Read `references/openxml_element_order.md` before writing any XML manipulation code. Always append properties elements first, then content elements.

---

## 3. "All text is in wrong font" (Font Contamination)

**Symptom:** Template specifies 宋体/Times New Roman but document shows Google Sans, Arial, Calibri, or whatever font the source document used.

**Diagnosis:** Source document's `rPr` contains inline `rFonts` declarations that override template styles. Direct formatting always wins over style-based formatting in OpenXML.

```bash
# Check for font contamination
$CLI analyze --input output.docx | grep -i "font"
# Look for rFonts in the content — if present, they're overriding styles
```

**Fix:** Strip `rFonts` from `rPr` when copying content, but KEEP `w:eastAsia` for CJK text:

```csharp
foreach (var rPr in body.Descendants<RunProperties>())
{
    var rFonts = rPr.GetFirstChild<RunFonts>();
    if (rFonts != null)
    {
        // Preserve EastAsia font for CJK — removing it causes tofu (□□□)
        var eastAsia = rFonts.EastAsia?.Value;
        rFonts.Remove();

        // Re-add only eastAsia if it was set and text contains CJK
        if (!string.IsNullOrEmpty(eastAsia))
        {
            rPr.Append(new RunFonts { EastAsia = eastAsia });
        }
    }
}
```

Also strip these common direct formatting overrides:
- `w:sz` / `w:szCs` (font size)
- `w:color` (text color)
- `w:b` / `w:i` when they contradict the style

**Prevention:** Always clean direct formatting when copying content between documents. Keep only `pStyle`/`rStyle` references and `w:t` text.

---

## 4. "Tables are missing" (Tables Lost During Copy)

**Symptom:** Source had 5 tables but output only has 2 (or 0).

**Diagnosis:** Code used `body.findall('w:p')` or `body.Descendants<Paragraph>()` at the top level instead of iterating all children. This skips `w:tbl` elements.

```bash
# Verify table count
$CLI analyze --input source.docx | grep -i "table"
$CLI analyze --input output.docx | grep -i "table"
```

**Fix:** Use `list(body)` or `body.ChildElements` to get ALL top-level children including tables:

```csharp
// WRONG — skips tables, section properties, and other non-paragraph elements
var paragraphs = body.Elements<Paragraph>();

// CORRECT — gets everything: paragraphs, tables, SDT blocks, etc.
var allElements = body.ChildElements.ToList();
```

In Python with lxml:
```python
# WRONG
elements = body.findall('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')

# CORRECT
elements = list(body)  # all direct children
```

**Prevention:** Always use `list(body)` or `body.ChildElements` for iteration, never filter by a single element type alone when copying content.

---

## 5. "Images are missing or show broken icon"

**Symptom:** Image placeholders appear but images don't render. Or images are completely absent.

**Diagnosis:** The `r:embed` rId in `w:drawing` doesn't match any relationship in `document.xml.rels`, or the media file wasn't copied to the output ZIP.

```bash
# Check relationships
$CLI analyze --input output.docx --part rels | grep -i "image"

# Check if media files exist
$CLI unpack --input output.docx --output unpacked/
ls unpacked/word/media/
```

**Fix:**
1. Check source rels for image file paths
2. Copy media files from source to output
3. Add/update relationships in output rels
4. Update `r:embed` values in drawing elements

```csharp
// When copying content with images between documents:
foreach (var drawing in body.Descendants<Drawing>())
{
    var blip = drawing.Descendants<DocumentFormat.OpenXml.Drawing.Blip>().FirstOrDefault();
    if (blip?.Embed?.Value != null)
    {
        var sourceRel = sourcePart.GetReferenceRelationship(blip.Embed.Value);
        // Copy the image part to the target document
        var imagePart = targetPart.AddImagePart(ImagePartType.Png);
        using var stream = sourcePart.GetPartById(blip.Embed.Value).GetStream();
        imagePart.FeedData(stream);
        // Update the rId reference
        blip.Embed = targetPart.GetIdOfPart(imagePart);
    }
}
```

**Prevention:** Always do rId remapping + media file copy when moving content between documents. Never assume rIds are portable across documents.

---

## 6. "TOC shows stale/wrong entries" or "Update Table doesn't work"

**Symptom:** Table of contents shows the template's example entries (e.g., "第1章 绪论...1") instead of actual headings. Or clicking "Update Table" in Word does nothing.

**Diagnosis:**
- **Stale entries (normal):** TOC entries are static text cached inside the field. They don't auto-update until the user explicitly updates in Word.
- **Update Table fails:** The SDT wrapper or field code structure is damaged. The TOC in real templates is a mixed structure: SDT block + field code + static entries.

```bash
# Check if TOC SDT exists
$CLI analyze --input output.docx | grep -i "sdt\|toc"
```

**Fix:**
- **If entries are just stale:** This is expected behavior. The user must right-click TOC, then "Update Field" in Word. Or enable auto-update:
  ```csharp
  // See FieldAndTocSamples.EnableUpdateFieldsOnOpen()
  FieldAndTocSamples.EnableUpdateFieldsOnOpen(settingsPart);
  ```
- **If SDT is damaged:** Keep the entire SDT block from the template intact. Do not modify it.
- **If field code is missing:** Ensure the TOC contains: `fldChar begin` + `instrText` + `fldChar separate` + static entries + `fldChar end`. See `FieldAndTocSamples.CreateMixedTocStructure()` for the complete pattern.
- **If you rebuilt TOC from scratch (common mistake):** You likely destroyed the SDT wrapper. Use the template's original SDT block instead. See `Samples/FieldAndTocSamples.cs` method `CreateMixedTocStructure` for how real-world TOC is structured.

**Prevention:** When doing Base-Replace (C-2), keep the template's TOC zone completely untouched. Do not strip, rebuild, or modify the SDT block. The TOC will auto-update when the user opens in Word.

---

## 7. "Chapters don't start on new pages" (Missing Section Breaks)

**Symptom:** Content flows continuously without page breaks between chapters. Chapter 2 starts right after Chapter 1's last paragraph on the same page.

**Diagnosis:** No `sectPr` elements or page break paragraphs between chapters.

**Fix:** Insert a paragraph with `sectPr` in its `pPr` before each chapter heading, or insert a page break:

```csharp
// Option 1: Section break (preserves per-section settings like headers/margins)
var breakPara = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new SectionType { Val = SectionMarkValues.NextPage })));

// Option 2: Simple page break (lighter weight)
var breakPara = new Paragraph(
    new Run(new Break { Type = BreakValues.Page }));

// Insert before each Heading1
body.InsertBefore(breakPara, heading1Paragraph);
```

**Prevention:** When copying content, insert page/section breaks before Heading1 paragraphs as needed. Check source document's section structure before copying.

---

## 8. "Hyperlinks don't work" (Broken Links)

**Symptom:** Clicking a hyperlink in the output document does nothing, or it navigates to the wrong URL.

**Diagnosis:** `w:hyperlink r:id` points to a relationship that doesn't exist in `document.xml.rels`.

```bash
# Check hyperlink relationships
$CLI analyze --input output.docx --part rels | grep -i "hyperlink"
```

**Fix:** Merge source document's hyperlink relationships into output's rels file. Update rId references.

```csharp
foreach (var hyperlink in body.Descendants<Hyperlink>())
{
    if (hyperlink.Id?.Value != null)
    {
        var sourceRel = sourcePart.HyperlinkRelationships
            .FirstOrDefault(r => r.Id == hyperlink.Id.Value);
        if (sourceRel != null)
        {
            targetPart.AddHyperlinkRelationship(sourceRel.Uri, sourceRel.IsExternal);
            var newRel = targetPart.HyperlinkRelationships.Last();
            hyperlink.Id = newRel.Id;
        }
    }
}
```

**Prevention:** Always merge ALL relationship types (images, hyperlinks, headers, footers) when combining documents. Never assume source rIds work in the target.

---

## 9. "Numbered lists show wrong numbers" or "Bullets disappeared"

**Symptom:** Lists that were numbered 1, 2, 3 now show 1, 1, 1 or have no numbers/bullets at all.

**Diagnosis:** `numId` in `pPr` references a numbering definition that doesn't exist in `numbering.xml`, or `abstractNumId` mapping is broken.

```bash
# Check numbering definitions
$CLI analyze --input output.docx --part numbering
```

**Fix:** Map source numIds to template numIds, or merge numbering definitions:

```csharp
// 1. Copy abstractNum definitions from source to target numbering.xml
// 2. Create new num entries pointing to the copied abstractNum
// 3. Update all numId references in document content

var sourceNumbering = sourceNumberingPart.Numbering;
var targetNumbering = targetNumberingPart.Numbering;

// Get max existing IDs to avoid collisions
int maxAbstractNumId = targetNumbering.Elements<AbstractNum>()
    .Max(a => a.AbstractNumberId?.Value ?? 0) + 1;
int maxNumId = targetNumbering.Elements<NumberingInstance>()
    .Max(n => n.NumberID?.Value ?? 0) + 1;
```

**Prevention:** Include `numbering.xml` reconciliation in template application workflow. See `Samples/ListAndNumberingSamples.cs` for correct numbering setup.

---

## 10. "Page margins/size are wrong"

**Symptom:** Output has different margins, page size, or orientation than the template.

**Diagnosis:** Source document's `sectPr` is overriding the template's `sectPr`. The final `sectPr` (child of `body`) controls the last section's layout.

```bash
# Compare section properties
$CLI analyze --input template.docx | grep -i "sectPr\|margin\|pgSz"
$CLI analyze --input output.docx | grep -i "sectPr\|margin\|pgSz"
```

**Fix:** Use the template's final `sectPr`. For intermediate `sectPr` elements (multi-section documents), merge carefully.

```csharp
// Replace output's final sectPr with template's
var templateSectPr = templateBody.Elements<SectionProperties>().LastOrDefault();
var outputSectPr = outputBody.Elements<SectionProperties>().LastOrDefault();

if (templateSectPr != null)
{
    var cloned = templateSectPr.CloneNode(true) as SectionProperties;
    if (outputSectPr != null)
        outputBody.ReplaceChild(cloned!, outputSectPr);
    else
        outputBody.Append(cloned!);
}
```

**Prevention:** Always use the template's `sectPr` as authority for page layout. Strip source document's `sectPr` before copying content.

---

## 11. "Chinese text renders as boxes/tofu"

**Symptom:** Chinese characters display as square boxes (□□□) or missing glyphs.

**Diagnosis:** `rFonts w:eastAsia` is set to a font that doesn't exist on the system, or is missing entirely. Without an East Asian font declaration, the rendering engine may fall back to a font without CJK coverage.

**Fix:** Ensure all CJK text has `w:eastAsia` set to an available font:

```csharp
foreach (var run in body.Descendants<Run>())
{
    var text = run.InnerText;
    if (ContainsCjk(text))
    {
        var rPr = run.RunProperties ?? new RunProperties();
        var rFonts = rPr.GetFirstChild<RunFonts>();
        if (rFonts == null)
        {
            rFonts = new RunFonts();
            rPr.Append(rFonts);
        }
        // Set to a universally available CJK font
        rFonts.EastAsia = "SimSun"; // 宋体 — safest default
        if (run.RunProperties == null) run.PrependChild(rPr);
    }
}

static bool ContainsCjk(string text)
{
    return text.Any(c => c >= 0x4E00 && c <= 0x9FFF);
}
```

Common safe CJK fonts: 宋体 (SimSun), 黑体 (SimHei), 仿宋 (FangSong), 楷体 (KaiTi).

**Prevention:** When cleaning `rPr` formatting, ALWAYS preserve `w:eastAsia` font declarations. See also `references/cjk_typography.md`.

---

## 12. "Template's cover page / declaration page is missing"

**Symptom:** Output document starts directly with body content — no cover page, no declaration, no abstract, no table of contents. The template's structural front matter was discarded.

**Diagnosis:** Used Overlay (C-1) strategy when Base-Replace (C-2) was needed. Overlay applies styles to the source document but discards the template's structural content (cover, declaration, abstract, TOC).

```bash
# Check template structure
$CLI analyze --input template.docx
# If template has >50 paragraphs with cover/TOC/declaration, C-2 is needed
```

**Fix:** Use Base-Replace (C-2) strategy — template is the base, only replace the example body content zone with the user's content:

1. Identify the template's "body zone" (everything between TOC and final sectPr)
2. Remove the template's example body content
3. Insert the user's content into the body zone
4. Keep everything else from the template (cover, declaration, abstract, TOC, sectPr)

```bash
$CLI apply-template --input source.docx --template template.docx --output out.docx --strategy base-replace
```

**Prevention:** Analyze template structure FIRST. If template has structural content (cover, TOC, declaration sections), always use C-2 (Base-Replace). Read `references/scenario_c_apply_template.md` for detailed decision criteria.

---

## 13. "Track changes markers appear unexpectedly"

**Symptom:** Output shows red/green revision marks (insertions, deletions) that weren't in the source document.

**Diagnosis:** Template had track changes enabled, or content was inserted as revisions rather than normal text.

```bash
# Check for revision marks
$CLI analyze --input output.docx | grep -i "revision\|ins\|del\|track"
```

**Fix:** Accept all revisions by flattening `w:ins` and `w:del` elements:

```csharp
// Accept insertions: unwrap w:ins, keep content
foreach (var ins in body.Descendants<InsertedRun>().ToList())
{
    var parent = ins.Parent!;
    foreach (var child in ins.ChildElements.ToList())
    {
        parent.InsertBefore(child.CloneNode(true), ins);
    }
    ins.Remove();
}

// Accept deletions: remove w:del and its content entirely
foreach (var del in body.Descendants<DeletedRun>().ToList())
{
    del.Remove();
}
```

Or disable tracking in settings:
```csharp
var settings = settingsPart.Settings;
var trackChanges = settings.GetFirstChild<TrackChanges>();
trackChanges?.Remove();
```

**Prevention:** Check template's `settings.xml` for `trackChanges` before starting. If present, accept all revisions in the template first.

---

## Recovery Strategy — When Multiple Issues Exist

When a document has multiple problems, fix them in this priority order:

```
1. [Content_Types].xml  — without this, nothing opens
2. _rels/.rels          — package relationships
3. word/_rels/document.xml.rels — part relationships (images, hyperlinks)
4. word/document.xml    — element ordering (fix-order)
5. word/styles.xml      — style definitions and styleId mapping
6. word/numbering.xml   — list/numbering definitions
7. Everything else      — headers, footers, comments, settings
```

```bash
# Full recovery pipeline
$CLI unpack --input broken.docx --output unpacked/
$CLI validate --input broken.docx --xsd assets/xsd/wml-subset.xsd  # find all errors
$CLI fix-order --input broken.docx                                   # fix element ordering
$CLI validate --input broken.docx --business                         # check business rules
scripts/docx_preview.sh broken.docx                                  # visual check
```
