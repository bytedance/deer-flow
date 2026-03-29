# Design Principles for Document Typography

WHY certain typographic choices look good -- the perceptual and psychological
reasons behind professional document design. Use this to make judgment calls
when exact specs are not provided.

## Table of Contents

1. [White Space & Breathing Room](#1-white-space--breathing-room)
2. [Contrast & Scale](#2-contrast--scale)
3. [Proximity & Grouping](#3-proximity--grouping)
4. [Alignment & Grid](#4-alignment--grid)
5. [Repetition & Consistency](#5-repetition--consistency)
6. [Visual Hierarchy & Flow](#6-visual-hierarchy--flow)

---

## 1. White Space & Breathing Room

### Why It Works

The human eye does not read continuously. It jumps in saccades, fixating on
small clusters of words. White space provides landing zones for these fixations
and gives the reader's peripheral vision a "frame" that makes each text block
feel manageable. When a page is packed to the edges, every glance returns more
text than working memory can buffer, triggering fatigue and avoidance.

Research on content density consistently shows:

- **60-70% content coverage** feels comfortable and professional.
- **80%+** starts to feel dense and bureaucratic.
- **90%+** feels oppressive -- the reader unconsciously rushes or skips.
- **Below 50%** feels wasteful or pretentious (unless intentional, like poetry).

Wider margins also carry cultural signals. Academic and luxury documents use
generous margins (1.25-1.5 inches). Internal memos and drafts use narrower
margins (0.75-1.0 inches). The margin width tells the reader how much care
went into the document before they read a single word.

Line spacing has a direct physiological basis: the eye must track back to the
start of the next line after each line break. If lines are too close, the eye
"slips" to the wrong line. If too far apart, the eye loses its sense of
continuity. The sweet spot is 120-145% of the font size.

**Rule of thumb: when in doubt, add more space, not less.**

### Good Example

```
Margins: 1 inch (1440 twips) all sides for business documents.
Line spacing: 1.15 (276 twips at 240 twips-per-line = 115%).
Paragraph spacing after: 8pt (160 twips) between body paragraphs.
```

```xml
<!-- Page margins: 1 inch = 1440 twips on all sides -->
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
         w:header="720" w:footer="720" w:gutter="0"/>

<!-- Body paragraph: 1.15 line spacing, 8pt after -->
<w:pPr>
  <w:spacing w:after="160" w:line="276" w:lineRule="auto"/>
</w:pPr>
```

This produces a page where content occupies roughly 65% of the area. The
reader sees clear top/bottom breathing room, and paragraphs are distinct
without feeling disconnected.

```
  Page layout (good):
  +----------------------------------+
  |           1" margin              |
  |   +------------------------+    |
  |   | Heading                |    |
  |   |                        |    |
  |   | Body text here with    |    |
  |   | comfortable spacing    |    |
  |   | between lines.         |    |
  |   |                        |    |  <- visible gap between paragraphs
  |   | Another paragraph of   |    |
  |   | body text follows.     |    |
  |   |                        |    |
  |   +------------------------+    |
  |           1" margin              |
  +----------------------------------+
```

### Bad Example

```xml
<!-- Cramped margins: 0.5 inch = 720 twips -->
<w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"
         w:header="360" w:footer="360" w:gutter="0"/>

<!-- No paragraph spacing, single line spacing -->
<w:pPr>
  <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
</w:pPr>
```

This fills ~85% of the page. Text runs edge-to-edge with no visual rest stops.
The reader sees a wall of text.

```
  Page layout (bad):
  +----------------------------------+
  | Heading                          |
  | Body text crammed right up to    |
  | the margins with no spacing      |
  | between lines or paragraphs.     |
  | Another paragraph starts here    |
  | and the reader cannot tell where |
  | one idea ends and another begins |
  | because everything blurs into a  |
  | single dense block of text.      |
  +----------------------------------+
```

### Quick Test

1. Zoom out to 50% in your document viewer. If you cannot see clear "channels"
   of white between text blocks, the spacing is too tight.
2. Print a test page. Hold it at arm's length. The text area should look like
   a rectangle floating in white, not filling the page.
3. Check: is the line spacing value at least 264 (`w:line` for 1.1x) for body
   text? If it is 240 (single), it is too tight for anything over 10pt.

---

## 2. Contrast & Scale

### Why It Works

The brain processes visual hierarchy through relative difference, not absolute
size. A 20pt heading above 11pt body text creates a clear "this is important"
signal. But if every heading is 20pt and every sub-heading is 19pt, the brain
cannot distinguish them -- they merge into the same level.

The key insight is **modular scale**: font sizes that grow by a consistent
ratio. This mirrors natural proportions and feels harmonious for the same
reason musical intervals do.

Common scales and their character:

| Ratio | Name           | Character                       | Example progression (from 11pt) |
|-------|----------------|---------------------------------|---------------------------------|
| 1.200 | Minor third    | Subtle, refined                 | 11 → 13.2 → 15.8 → 19.0       |
| 1.250 | Major third    | Balanced, professional          | 11 → 13.75 → 17.2 → 21.5      |
| 1.333 | Perfect fourth | Strong, authoritative           | 11 → 14.7 → 19.5 → 26.0       |
| 1.414 | Augmented 4th  | Dramatic, presentation-style    | 11 → 15.6 → 22.0 → 31.1       |

For most business documents, 1.25 (major third) works best:

```
Body  = 11pt  (w:sz="22")
H3    = 13pt  (w:sz="26")   -- 11 * 1.25 ≈ 13.75, round to 13
H2    = 16pt  (w:sz="32")   -- 13 * 1.25 ≈ 16.25, round to 16
H1    = 20pt  (w:sz="40")   -- 16 * 1.25 = 20
```

Beyond size, **weight contrast** creates hierarchy without consuming vertical
space. Regular (400) vs Bold (700) is visible at any size. Semi-bold (600) vs
Regular is subtle and best avoided unless you also vary size or color.

**Color contrast** adds a third dimension. Dark blue headings (#1F3864) against
softer dark gray body text (#333333) signals "heading" without needing a huge
size jump. Pure black (#000000) body text is harsher than necessary on white
backgrounds -- #333333 or #2D2D2D reduces glare without losing legibility.

### Good Example

```xml
<!-- H1: 20pt, bold, dark navy -->
<w:rPr>
  <w:b/>
  <w:sz w:val="40"/>
  <w:color w:val="1F3864"/>
</w:rPr>

<!-- H2: 16pt, bold, dark navy -->
<w:rPr>
  <w:b/>
  <w:sz w:val="32"/>
  <w:color w:val="1F3864"/>
</w:rPr>

<!-- H3: 13pt, bold, dark navy -->
<w:rPr>
  <w:b/>
  <w:sz w:val="26"/>
  <w:color w:val="1F3864"/>
</w:rPr>

<!-- Body: 11pt, regular, dark gray -->
<w:rPr>
  <w:sz w:val="22"/>
  <w:color w:val="333333"/>
</w:rPr>
```

```
  Visual hierarchy (good):

  [████████████████████]        <- H1: 20pt bold navy (clearly dominant)
                                   (generous space)
  [██████████████]              <- H2: 16pt bold navy (distinct step down)
                                   (moderate space)
  [████████████]                <- H3: 13pt bold navy (smaller but still bold)
  [░░░░░░░░░░░░░░░░░░░░░░]    <- Body: 11pt regular gray
  [░░░░░░░░░░░░░░░░░░░░░░]
  [░░░░░░░░░░░░░░░░░░░░░░]
```

Each level is visually distinct from its neighbors. You can identify the
hierarchy even in peripheral vision.

### Bad Example

```xml
<!-- H1: 14pt bold black -->
<w:rPr>
  <w:b/>
  <w:sz w:val="28"/>
  <w:color w:val="000000"/>
</w:rPr>

<!-- H2: 13pt bold black -->
<w:rPr>
  <w:b/>
  <w:sz w:val="26"/>
  <w:color w:val="000000"/>
</w:rPr>

<!-- H3: 12pt bold black -->
<w:rPr>
  <w:b/>
  <w:sz w:val="24"/>
  <w:color w:val="000000"/>
</w:rPr>

<!-- Body: 12pt regular black -->
<w:rPr>
  <w:sz w:val="24"/>
  <w:color w:val="000000"/>
</w:rPr>
```

Problems:
- H3 (12pt bold) and body (12pt regular) differ only by weight -- too subtle.
- H1 (14pt) to H2 (13pt) is a 1pt step -- invisible at reading distance.
- Everything is pure black so color provides no differentiating signal.
- The ratio between levels is ~1.07, far too flat.

### Quick Test

1. **The squint test**: blur your eyes or step back from the screen. Can you
   count the number of heading levels? If two levels merge, their contrast
   is insufficient.
2. **Ratio check**: divide each heading size by the next smaller size. If any
   ratio is below 1.15, the levels will look too similar.
3. **Color check**: do headings look distinct from body text when you glance
   at the page? If everything is the same color, you are relying solely on
   size/weight, which limits your hierarchy to ~3 effective levels.

---

## 3. Proximity & Grouping

### Why It Works

The Gestalt principle of proximity: items that are close together are perceived
as belonging to the same group. In document typography, this means a heading
must be **closer to the content it introduces** than to the content above it.

If a heading sits equidistant between two paragraphs, it looks orphaned -- the
reader's eye does not know if it belongs to the text above or below. The fix
is asymmetric spacing: **large space before the heading, small space after**.

The recommended ratio is 2:1 or 3:1 (space-before : space-after).

This same principle applies to:
- **List items**: spacing between items should be less than spacing between
  paragraphs. Items in a list are a group and should visually cluster.
- **Captions**: a figure caption should be close to its figure, not floating
  in the middle between the figure and the next paragraph.
- **Table titles**: the title sits close above the table, with more space
  separating the title from preceding text.

### Good Example

```xml
<!-- H2: 18pt before, 6pt after (3:1 ratio) -->
<w:pPr>
  <w:pStyle w:val="Heading2"/>
  <w:spacing w:before="360" w:after="120"/>
</w:pPr>

<!-- Body paragraph: 0pt before, 8pt after -->
<w:pPr>
  <w:spacing w:before="0" w:after="160"/>
</w:pPr>

<!-- List item: 0pt before, 2pt after (tight grouping) -->
<w:pPr>
  <w:pStyle w:val="ListParagraph"/>
  <w:spacing w:before="0" w:after="40"/>
</w:pPr>
```

```
  Proximity (good):

  ...end of previous section text.
                                        <- 18pt gap (w:before="360")
  ## Section Heading
                                        <- 6pt gap (w:after="120")
  First paragraph of new section
  continues here with content.
                                        <- 8pt gap (w:after="160")
  Second paragraph follows.

  The heading clearly "belongs to" the text below it.
```

```
  List grouping (good):

  Consider these factors:
    - First item                        <- 2pt gap between items
    - Second item                       <- items cluster as a group
    - Third item
                                        <- 8pt gap after list
  The next paragraph starts here.
```

### Bad Example

```xml
<!-- H2: 12pt before, 12pt after (1:1 ratio -- orphaned heading) -->
<w:pPr>
  <w:pStyle w:val="Heading2"/>
  <w:spacing w:before="240" w:after="240"/>
</w:pPr>

<!-- List item: same spacing as body (10pt after) -->
<w:pPr>
  <w:pStyle w:val="ListParagraph"/>
  <w:spacing w:before="0" w:after="200"/>
</w:pPr>
```

```
  Proximity (bad):

  ...end of previous section text.
                                        <- 12pt gap
  ## Section Heading
                                        <- 12pt gap (same!)
  First paragraph of new section.

  The heading floats between sections. It is unclear what it belongs to.
```

```
  List grouping (bad):

  Consider these factors:
                                        <- 10pt gap
    - First item
                                        <- 10pt gap (same as paragraphs)
    - Second item
                                        <- 10pt gap
    - Third item
                                        <- 10pt gap
  Next paragraph.

  The list does not feel like a group. Each item looks like a
  separate paragraph that happens to have a bullet.
```

### Quick Test

1. **Cover test**: cover the heading text. Looking only at the whitespace,
   can you tell which block of text the heading belongs to? If the gaps above
   and below are equal, the answer is "no."
2. **Number check**: `w:before` on headings should be at least 2x `w:after`.
   Common good values: before=360 / after=120, or before=240 / after=80.
3. **List check**: `w:after` on list items should be less than half of
   `w:after` on body paragraphs. If body uses 160, list items should use
   40-60.

---

## 4. Alignment & Grid

### Why It Works

Alignment creates invisible lines that the eye follows down the page. When
elements share the same left edge, the reader perceives order and intention.
When elements are slightly misaligned (off by a few twips), the page looks
sloppy even if the reader cannot consciously identify why.

**Left-align vs Justify:**

- **Left-aligned** (ragged right) is best for English and other Latin-script
  languages. The uneven right edge actually helps reading because each line
  has a unique silhouette, making it easier for the eye to find the next line.
  Justified text forces uneven word spacing that creates distracting "rivers"
  of white running vertically through paragraphs.

- **Justified** is best for CJK text. Chinese, Japanese, and Korean characters
  are monospaced by design -- each occupies the same cell in an invisible grid.
  Justification preserves this grid perfectly. Ragged right in CJK text breaks
  the grid and looks untidy.

**Indentation rule:** Use first-line indent OR paragraph spacing to separate
paragraphs -- never both. They serve the same purpose (marking paragraph
boundaries). Using both wastes space and creates visual stutter.

- Western convention: paragraph spacing (no indent) is more modern.
- CJK convention: first-line indent of 2 characters is standard.
- Academic convention: first-line indent of 0.5 inch is traditional.

### Good Example

```xml
<!-- English body: left-aligned, paragraph spacing, no indent -->
<w:pPr>
  <w:jc w:val="left"/>
  <w:spacing w:after="160" w:line="276" w:lineRule="auto"/>
  <!-- No w:ind firstLine -->
</w:pPr>

<!-- CJK body: justified, first-line indent 2 chars, no paragraph spacing -->
<w:pPr>
  <w:jc w:val="both"/>
  <w:spacing w:after="0" w:line="360" w:lineRule="auto"/>
  <w:ind w:firstLineChars="200"/>
</w:pPr>

<!-- Tab stops creating aligned columns -->
<w:pPr>
  <w:tabs>
    <w:tab w:val="left" w:pos="2880"/>   <!-- 2 inches -->
    <w:tab w:val="right" w:pos="9360"/>  <!-- 6.5 inches (right margin) -->
  </w:tabs>
</w:pPr>
```

```
  English paragraph separation (good -- spacing, no indent):

  This is the first paragraph with some text
  that wraps to a second line naturally.

  This is the second paragraph. The gap above
  clearly marks the boundary.


  CJK paragraph separation (good -- indent, no spacing):

  　　第一段正文内容从这里开始，使用两个字符
  的首行缩进来标记段落边界。
  　　第二段紧跟其后，没有段间距，但首行缩进
  清晰地标识了新段落的开始。
```

### Bad Example

```xml
<!-- English body: justified (creates word-spacing rivers) -->
<w:pPr>
  <w:jc w:val="both"/>
  <w:spacing w:after="160" w:line="276" w:lineRule="auto"/>
  <w:ind w:firstLine="720"/>  <!-- BOTH indent AND spacing: redundant -->
</w:pPr>

<!-- CJK body: left-aligned (breaks character grid) -->
<w:pPr>
  <w:jc w:val="left"/>
  <w:spacing w:after="200" w:line="276" w:lineRule="auto"/>
  <!-- No indent, using spacing instead -- unidiomatic for CJK -->
</w:pPr>
```

Problems:
- Justified English text with narrow columns creates uneven word gaps.
- Using both first-line indent AND paragraph spacing is redundant.
- Left-aligned CJK breaks the character grid that CJK readers expect.
- CJK with spacing-based separation looks like translated western layout.

### Quick Test

1. **River test**: in justified English text, squint and look for vertical
   white streaks running through the paragraph. If you see them, switch to
   left-align or increase the column width.
2. **Double signal check**: does the document use BOTH first-line indent AND
   paragraph spacing? If yes, remove one. Choose indent for CJK/academic,
   spacing for modern western.
3. **Tab alignment**: if you use tabs for columns, do all tab stops across
   the document use the same positions? Inconsistent tab stops create jagged
   invisible grid lines.

---

## 5. Repetition & Consistency

### Why It Works

Consistency is a trust signal. When a reader sees that every H2 looks the same,
every table follows the same pattern, and every page number sits in the same
spot, they unconsciously trust that the document was crafted with care. A single
inconsistency -- one H2 that is 15pt instead of 14pt, one table with different
borders -- breaks that trust and makes the reader question the content.

Consistency also reduces cognitive load. Once the reader learns "bold dark blue
= section heading," they stop spending mental effort on identifying structure
and focus entirely on content. Every inconsistency forces them to re-evaluate:
"Is this a different kind of heading, or did someone just forget to apply the
style?"

The implementation rule is simple: **use named styles, not direct formatting.**
If you define Heading2 as a style and apply it everywhere, consistency is
automatic. If you manually set font size, bold, and color on each heading
individually, inconsistency is inevitable.

### Good Example

```xml
<!-- Define styles once in styles.xml -->
<w:style w:type="paragraph" w:styleId="Heading2">
  <w:name w:val="heading 2"/>
  <w:basedOn w:val="Normal"/>
  <w:next w:val="Normal"/>
  <w:pPr>
    <w:keepNext/>
    <w:keepLines/>
    <w:spacing w:before="360" w:after="120"/>
    <w:outlineLvl w:val="1"/>
  </w:pPr>
  <w:rPr>
    <w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi"/>
    <w:b/>
    <w:sz w:val="32"/>
    <w:color w:val="1F3864"/>
  </w:rPr>
</w:style>

<!-- Apply consistently: every H2 references the style -->
<w:p>
  <w:pPr>
    <w:pStyle w:val="Heading2"/>
    <!-- No direct formatting overrides -->
  </w:pPr>
  <w:r><w:t>Market Analysis</w:t></w:r>
</w:p>
```

When using a table style, define it once and reference it for every table:

```xml
<!-- All tables reference the same style -->
<w:tblPr>
  <w:tblStyle w:val="GridTable4Accent1"/>
  <w:tblW w:w="0" w:type="auto"/>
</w:tblPr>
```

### Bad Example

```xml
<!-- First H2: manually formatted -->
<w:p>
  <w:pPr>
    <w:spacing w:before="360" w:after="120"/>
  </w:pPr>
  <w:r>
    <w:rPr>
      <w:b/>
      <w:sz w:val="32"/>
      <w:color w:val="1F3864"/>
    </w:rPr>
    <w:t>Market Analysis</w:t>
  </w:r>
</w:p>

<!-- Second H2: slightly different (16pt instead of 16pt?  No, 15pt!) -->
<w:p>
  <w:pPr>
    <w:spacing w:before="240" w:after="160"/>  <!-- different spacing! -->
  </w:pPr>
  <w:r>
    <w:rPr>
      <w:b/>
      <w:sz w:val="30"/>   <!-- 15pt instead of 16pt! -->
      <w:color w:val="2E74B5"/>  <!-- different shade of blue! -->
    </w:rPr>
    <w:t>Financial Overview</w:t>
  </w:r>
</w:p>
```

Problems:
- No style references -- everything is direct formatting.
- Second H2 has different size (30 vs 32), color, and spacing.
- If there are 20 headings, each could drift slightly differently.
- Changing the design later means editing every heading individually.

### Quick Test

1. **Style audit**: does every paragraph reference a `w:pStyle`? If you find
   paragraphs with only direct formatting and no style, that is a consistency
   risk.
2. **Search for variance**: search the XML for all `w:sz` values used with
   `w:b` (bold). If you find three different sizes for what should be the same
   heading level, there is an inconsistency.
3. **Table check**: do all tables in the document reference the same
   `w:tblStyle`? If some tables have manual border definitions while others
   use a style, the document will look patchy.
4. **Page numbers**: check that header/footer content is defined in the
   default section properties and inherited by all sections, not redefined
   inconsistently in each section.

---

## 6. Visual Hierarchy & Flow

### Why It Works

A well-designed document guides the reader's eye in a predictable path:
title at the top, subtitle below it, section headings as signposts, body text
as the main content, footnotes and captions as supporting details. This flow
mirrors reading priority -- the most important information is the most visually
prominent.

Each level in the hierarchy must be **distinguishable from its adjacent
levels**. It is not enough for H1 to differ from body text; H1 must also
clearly differ from H2, and H2 from H3. If any two adjacent levels are too
similar, the hierarchy collapses at that point.

Effective hierarchy uses **multiple simultaneous signals**:

| Level    | Size  | Weight  | Color   | Spacing above |
|----------|-------|---------|---------|---------------|
| Title    | 26pt  | Bold    | #1F3864 | 0 (top)       |
| Subtitle | 15pt  | Regular | #4472C4 | 4pt           |
| H1       | 20pt  | Bold    | #1F3864 | 24pt          |
| H2       | 16pt  | Bold    | #1F3864 | 18pt          |
| H3       | 13pt  | Bold    | #1F3864 | 12pt          |
| Body     | 11pt  | Regular | #333333 | 0pt           |
| Caption  | 9pt   | Italic  | #666666 | 4pt           |
| Footnote | 9pt   | Regular | #666666 | 0pt           |

Notice how each level differs from its neighbors on at least two dimensions
(size + weight, or size + color, or weight + style). Single-dimension
differences are fragile and can be missed.

**Section breaks** create rhythm in long documents. A page break before each
major section (H1) gives the reader a mental reset. Within sections, consistent
heading + body patterns create a predictable cadence that makes long documents
less intimidating.

### Good Example

```xml
<!-- Title: large, bold, navy, centered -->
<w:style w:type="paragraph" w:styleId="Title">
  <w:pPr>
    <w:jc w:val="center"/>
    <w:spacing w:after="80"/>
  </w:pPr>
  <w:rPr>
    <w:b/>
    <w:sz w:val="52"/>
    <w:color w:val="1F3864"/>
  </w:rPr>
</w:style>

<!-- Subtitle: medium, regular weight, lighter blue, centered -->
<w:style w:type="paragraph" w:styleId="Subtitle">
  <w:pPr>
    <w:jc w:val="center"/>
    <w:spacing w:after="320"/>
  </w:pPr>
  <w:rPr>
    <w:sz w:val="30"/>
    <w:color w:val="4472C4"/>
  </w:rPr>
</w:style>

<!-- H1: page break before, large bold navy -->
<w:style w:type="paragraph" w:styleId="Heading1">
  <w:pPr>
    <w:pageBreakBefore/>
    <w:keepNext/>
    <w:keepLines/>
    <w:spacing w:before="480" w:after="160"/>
    <w:outlineLvl w:val="0"/>
  </w:pPr>
  <w:rPr>
    <w:b/>
    <w:sz w:val="40"/>
    <w:color w:val="1F3864"/>
  </w:rPr>
</w:style>

<!-- Caption: small, italic, gray -->
<w:style w:type="paragraph" w:styleId="Caption">
  <w:pPr>
    <w:spacing w:before="80" w:after="200"/>
  </w:pPr>
  <w:rPr>
    <w:i/>
    <w:sz w:val="18"/>
    <w:color w:val="666666"/>
  </w:rPr>
</w:style>
```

```
  Visual flow (good):

  +----------------------------------+
  |                                  |
  |     ANNUAL REPORT 2025           |  <- Title: 26pt bold navy centered
  |     Acme Corporation             |  <- Subtitle: 15pt regular blue
  |                                  |
  |                                  |
  +----------------------------------+

  +----------------------------------+
  |                                  |
  |  1. Executive Summary            |  <- H1: 20pt bold navy (page break)
  |                                  |
  |  Body text introducing the       |  <- Body: 11pt regular gray
  |  main findings of the year.      |
  |                                  |
  |  1.1 Revenue Highlights          |  <- H2: 16pt bold navy
  |                                  |
  |  Revenue grew by 23% year        |  <- Body
  |  over year, driven by...         |
  |                                  |
  |  Figure 1: Revenue Growth        |  <- Caption: 9pt italic gray
  |                                  |
  +----------------------------------+

  Each level is immediately identifiable. The eye flows naturally
  from title -> heading -> body -> caption.
```

### Bad Example

```xml
<!-- All headings same color as body, minimal size difference -->
<w:style w:type="paragraph" w:styleId="Heading1">
  <w:rPr>
    <w:b/>
    <w:sz w:val="28"/>       <!-- 14pt -- only 3pt above body -->
    <w:color w:val="000000"/> <!-- same color as body -->
  </w:rPr>
</w:style>

<!-- Caption same size as body, not italic -->
<w:style w:type="paragraph" w:styleId="Caption">
  <w:rPr>
    <w:sz w:val="22"/>        <!-- same 11pt as body! -->
    <w:color w:val="000000"/> <!-- same color as body -->
  </w:rPr>
</w:style>

<!-- No page breaks between major sections -->
<!-- H1 has no pageBreakBefore, keepNext, or keepLines -->
```

Problems:
- H1 at 14pt is too close to body at 11pt (ratio 1.27 -- acceptable in
  isolation but with black color matching body, the hierarchy is weak).
- Caption is indistinguishable from body text.
- No page breaks means major sections bleed into each other with no
  visual rhythm.
- Everything is black, so color provides zero hierarchy signal.

### Quick Test

1. **The squint test**: blur your eyes while looking at a full page. You
   should see 3-4 distinct "weight levels" of gray. If the page looks like
   one uniform shade, the hierarchy is too flat.
2. **The scan test**: flip through pages quickly. Can you identify section
   boundaries in under one second per page? If yes, the visual hierarchy is
   working. If pages blur together, you need stronger differentiation at H1.
3. **Adjacent level test**: for each heading level, check that it differs
   from the next level on at least 2 of: size, weight, color, style (italic).
   Single-dimension differences get lost.
4. **Rhythm test**: in a document over 10 pages, do major sections (H1) start
   on new pages? If not, long documents will feel like an undifferentiated
   stream. Add `w:pageBreakBefore` to Heading1.

---

## Summary: Decision Checklist

When you are unsure about a typographic choice, run through these checks:

| Principle | Question | If No... |
|-----------|----------|----------|
| White Space | Does the page have at least 30% white space? | Increase margins or spacing |
| Contrast | Can I count heading levels by squinting? | Increase size ratios (target 1.25x) |
| Proximity | Does each heading clearly belong to text below it? | Make space-before > space-after (2:1) |
| Alignment | Is English left-aligned and CJK justified? | Switch alignment mode |
| Repetition | Do all same-level elements use the same style? | Replace direct formatting with styles |
| Hierarchy | Can I see the document structure at arm's length? | Add more differentiation signals |

**When two principles conflict, prioritize in this order:**

1. **Readability** (white space, line spacing) -- always wins
2. **Hierarchy** (contrast, scale) -- readers must find what they need
3. **Consistency** (repetition) -- builds trust
4. **Aesthetics** (alignment, grouping) -- the finishing touch
