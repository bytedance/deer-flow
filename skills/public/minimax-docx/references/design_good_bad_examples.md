# GOOD vs BAD Document Design — Concrete OpenXML Examples

A side-by-side reference showing common design mistakes and their fixes, with exact OpenXML parameter values. Use this to develop an intuitive sense of what makes a document look professional versus amateur.

Format: Each comparison shows the **BAD** version first (the mistake), then the **GOOD** version (the fix), with OpenXML markup and a short explanation.

---

## 1. Font Size Disasters

### 1a. No Hierarchy — Everything the Same Size

**BAD: Body=12pt, H1=12pt bold**
```
┌──────────────────────────────────┐
│ INTRODUCTION                     │  ← 12pt bold... same visual weight
│ This is the body text of the     │  ← 12pt regular
│ report. It discusses findings    │
│ from the quarterly review.       │
│ METHODOLOGY                      │  ← Where does the section start?
│ We collected data from three     │
│ sources across the enterprise.   │
└──────────────────────────────────┘
```
```xml
<!-- H1: bold but same size as body — no visual separation -->
<w:rPr><w:b/><w:sz w:val="24"/></w:rPr>
<!-- Body -->
<w:rPr><w:sz w:val="24"/></w:rPr>
```

**GOOD: Modular scale — body=11pt, H3=13pt, H2=16pt, H1=20pt**
```
┌──────────────────────────────────┐
│                                  │
│ Introduction                     │  ← 20pt, clearly a title
│                                  │
│ This is the body text of the     │  ← 11pt, comfortable reading size
│ report. It discusses findings    │
│ from the quarterly review.       │
│                                  │
│ Methodology                      │  ← 20pt, section break is obvious
│                                  │
│ We collected data from three     │
│ sources across the enterprise.   │
└──────────────────────────────────┘
```
```xml
<!-- H1: 20pt = w:sz 40 -->
<w:rPr><w:rFonts w:ascii="Calibri Light"/><w:sz w:val="40"/></w:rPr>
<!-- H2: 16pt = w:sz 32 -->
<w:rPr><w:rFonts w:ascii="Calibri Light"/><w:sz w:val="32"/></w:rPr>
<!-- H3: 13pt = w:sz 26, bold -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:b/><w:sz w:val="26"/></w:rPr>
<!-- Body: 11pt = w:sz 22 -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:sz w:val="22"/></w:rPr>
```
**Why better:** A clear size progression (ratio ~1.25x per step) lets readers instantly identify structure without reading a word.

---

### 1b. Too Much Contrast — Children's Book Look

**BAD: H1=28pt with body=10pt (ratio 2.8x)**
```
┌──────────────────────────────────┐
│                                  │
│ QUARTERLY REPORT                 │  ← 28pt, dominates the page
│                                  │
│ This is body text set very small │  ← 10pt, straining to read
│ and the contrast with the title  │
│ makes it feel like a poster.     │
└──────────────────────────────────┘
```
```xml
<w:rPr><w:b/><w:sz w:val="56"/></w:rPr>  <!-- 28pt heading -->
<w:rPr><w:sz w:val="20"/></w:rPr>         <!-- 10pt body -->
```

**GOOD: H1=20pt with body=11pt (ratio ~1.8x)**
```xml
<w:rPr><w:sz w:val="40"/></w:rPr>  <!-- 20pt heading -->
<w:rPr><w:sz w:val="22"/></w:rPr>  <!-- 11pt body -->
```
**Why better:** A heading-to-body ratio between 1.5x and 2.0x reads as "structured" rather than "shouting."

---

## 2. Spacing Crimes

### 2a. Wall of Text — No Paragraph or Line Spacing

**BAD: Single line spacing, 0pt between paragraphs**
```
┌──────────────────────────────────┐
│The findings indicate a strong    │
│correlation between training hours│
│and performance metrics.          │
│Further analysis revealed that    │  ← No gap — where does the new
│departments with higher budgets   │     paragraph start?
│achieved better outcomes in all   │
│measured categories.              │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:spacing w:line="240" w:lineRule="auto"/>  <!-- 1.0 spacing (240/240) -->
  <w:spacing w:after="0"/>                     <!-- no paragraph gap -->
</w:pPr>
```

**GOOD: 1.15x line spacing, 8pt after each paragraph**
```
┌──────────────────────────────────┐
│The findings indicate a strong    │
│correlation between training      │  ← Slightly more air between lines
│hours and performance metrics.    │
│                                  │  ← 8pt gap signals new paragraph
│Further analysis revealed that    │
│departments with higher budgets   │
│achieved better outcomes in all   │
│measured categories.              │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:spacing w:line="276" w:lineRule="auto"/>  <!-- 1.15x (276/240) -->
  <w:spacing w:after="160"/>                   <!-- 8pt = 160 twips -->
</w:pPr>
```
**Why better:** Line spacing gives each line room to breathe; paragraph spacing separates ideas without wasting a full blank line.

---

### 2b. Floating Headings — Same Space Above and Below

**BAD: 12pt before and 12pt after heading**
```
┌──────────────────────────────────┐
│ ...end of previous section.      │
│                                  │  ← 12pt gap
│ Section Two                      │  ← Heading floats in the middle
│                                  │  ← 12pt gap
│ Start of section two content.    │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:spacing w:before="240" w:after="240"/>  <!-- 12pt both sides -->
</w:pPr>
```

**GOOD: 24pt before, 8pt after heading**
```
┌──────────────────────────────────┐
│ ...end of previous section.      │
│                                  │
│                                  │  ← 24pt gap — clear section break
│ Section Two                      │  ← Heading is close to its content
│                                  │  ← 8pt gap
│ Start of section two content.    │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:spacing w:before="480" w:after="160"/>  <!-- 24pt before, 8pt after -->
</w:pPr>
```
**Why better:** Proximity principle: a heading belongs to the text that follows it, so more space above and less space below anchors it to its content.

---

### 2c. Wasteful Gaps — Huge Spacing Everywhere

**BAD: 24pt after every paragraph, including body text**
```
┌──────────────────────────────────┐
│ First paragraph of text here.    │
│                                  │
│                                  │  ← 24pt gap after every paragraph
│                                  │
│ Second paragraph of text here.   │
│                                  │
│                                  │
│                                  │
│ Third paragraph.                 │  ← Document looks mostly white space
└──────────────────────────────────┘
```
```xml
<w:spacing w:after="480"/>  <!-- 24pt = 480 twips after every paragraph -->
```

**GOOD: Proportional spacing — body=8pt, H2=6pt after, H1=10pt after**
```xml
<!-- Body paragraph -->
<w:spacing w:after="160"/>   <!-- 8pt after body -->
<!-- H1 -->
<w:spacing w:before="480" w:after="200"/>  <!-- 24pt before, 10pt after -->
<!-- H2 -->
<w:spacing w:before="320" w:after="120"/>  <!-- 16pt before, 6pt after -->
```
**Why better:** Spacing should vary by element role, creating a visual rhythm rather than uniform gaps.

---

## 3. Margin Mistakes

### 3a. Cramped Margins — Text Running to the Edge

**BAD: 0.5in margins all around**
```
┌────────────────────────────────────────────────┐
│Text starts almost at the paper edge and runs   │
│all the way across making extremely long lines  │
│that are hard to track from end back to start.  │
│The eye loses its place on every line return.   │
└────────────────────────────────────────────────┘
```
```xml
<w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/>
<!-- 720 twips = 0.5in — line length ~7.5in on letter paper -->
```

**GOOD: 1in margins (standard)**
```xml
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
<!-- 1440 twips = 1.0in — line length ~6.5in, ideal for 11pt body -->
```
**Why better:** Optimal line length is 60-75 characters. At 11pt Calibri, 6.5in width achieves roughly 70 characters per line.

---

### 3b. Over-Padded Margins — Looks Like the Content is Hiding

**BAD: 2in margins on a short document**
```xml
<w:pgMar w:top="2880" w:right="2880" w:bottom="2880" w:left="2880"/>
<!-- 2880 twips = 2.0in — only 4.5in of text width, looks padded -->
```

**GOOD: 1in standard, or 1.25in for formal documents**
```xml
<!-- Standard -->
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
<!-- Formal / bound documents with gutter -->
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1800" w:gutter="0"/>
<!-- 1800 twips = 1.25in left for binding margin -->
```
**Why better:** Margins should frame the content, not overwhelm it. 1-1.25in works for virtually all business and academic documents.

---

## 4. Table Ugliness

### 4a. Prison Grid — Full Borders on Every Cell

**BAD: Every cell with 1pt borders on all four sides**
```
┌───────┬───────┬───────┬───────┐
│ Name  │ Dept  │ Score │ Grade │
├───────┼───────┼───────┼───────┤
│ Alice │ Eng   │ 92    │ A     │
├───────┼───────┼───────┼───────┤
│ Bob   │ Sales │ 85    │ B     │
├───────┼───────┼───────┼───────┤
│ Carol │ Eng   │ 78    │ C+    │
└───────┴───────┴───────┴───────┘
```
```xml
<w:tcBorders>
  <w:top w:val="single" w:sz="4" w:color="000000"/>
  <w:left w:val="single" w:sz="4" w:color="000000"/>
  <w:bottom w:val="single" w:sz="4" w:color="000000"/>
  <w:right w:val="single" w:sz="4" w:color="000000"/>
</w:tcBorders>
```

**GOOD: Three-line table (三线表) — top thick, header-bottom medium, table-bottom thick**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ← 1.5pt top border
  Name    Dept    Score   Grade
──────────────────────────────────  ← 0.75pt header separator
  Alice   Eng     92      A
  Bob     Sales   85      B
  Carol   Eng     78      C+
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ← 1.5pt bottom border
```
```xml
<!-- Top border of header row cells -->
<w:top w:val="single" w:sz="12" w:color="000000"/>    <!-- 1.5pt -->
<w:left w:val="nil"/><w:right w:val="nil"/>
<w:bottom w:val="single" w:sz="6" w:color="000000"/>  <!-- 0.75pt -->

<!-- Data row cells: no left/right/top borders -->
<w:top w:val="nil"/><w:left w:val="nil"/><w:right w:val="nil"/>
<w:bottom w:val="nil"/>

<!-- Last row bottom border -->
<w:bottom w:val="single" w:sz="12" w:color="000000"/> <!-- 1.5pt -->
```
**Why better:** Removing inner borders lets the eye scan data freely. Three lines provide structure without visual clutter.

---

### 4b. Text Touching Borders — No Cell Padding

**BAD: Zero cell margins**
```
┌──────────┬──────────┐
│Name      │Department│  ← Text cramped against borders
├──────────┼──────────┤
│Alice     │Engineering│
└──────────┴──────────┘
```
```xml
<w:tcMar>
  <w:top w:w="0" w:type="dxa"/>
  <w:start w:w="0" w:type="dxa"/>
  <w:bottom w:w="0" w:type="dxa"/>
  <w:end w:w="0" w:type="dxa"/>
</w:tcMar>
```

**GOOD: 0.08in vertical, 0.12in horizontal padding**
```xml
<w:tcMar>
  <w:top w:w="115" w:type="dxa"/>      <!-- ~0.08in = 115 twips -->
  <w:start w:w="173" w:type="dxa"/>    <!-- ~0.12in = 173 twips -->
  <w:bottom w:w="115" w:type="dxa"/>
  <w:end w:w="173" w:type="dxa"/>
</w:tcMar>
```
**Why better:** Padding gives text breathing room inside cells, making every value easier to read.

---

### 4c. Invisible Headers — Header Row Same Style as Data

**BAD: Header row indistinguishable from data**
```xml
<!-- Header cell run properties — identical to data -->
<w:rPr><w:sz w:val="22"/></w:rPr>
```

**GOOD: Bold header text, subtle background fill, bottom border**
```xml
<!-- Header cell run properties -->
<w:rPr><w:b/><w:sz w:val="22"/><w:color w:val="333333"/></w:rPr>

<!-- Header cell shading -->
<w:tcPr>
  <w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>  <!-- light gray bg -->
  <w:tcBorders>
    <w:bottom w:val="single" w:sz="8" w:color="666666"/>  <!-- 1pt separator -->
  </w:tcBorders>
</w:tcPr>

<!-- Mark row as header (repeats on page break) -->
<w:trPr><w:tblHeader/></w:trPr>
```
**Why better:** Distinct header styling lets readers instantly locate column meanings, especially in long tables that span pages. The `w:tblHeader` element ensures the header row repeats on every page.

---

## 5. Font Pairing Failures

### 5a. Visual Chaos — Too Many Fonts

**BAD: 4+ fonts in one document**
```xml
<!-- H1 in Impact -->
<w:rPr><w:rFonts w:ascii="Impact"/><w:sz w:val="40"/></w:rPr>
<!-- H2 in Georgia -->
<w:rPr><w:rFonts w:ascii="Georgia"/><w:sz w:val="32"/></w:rPr>
<!-- Body in Verdana -->
<w:rPr><w:rFonts w:ascii="Verdana"/><w:sz w:val="22"/></w:rPr>
<!-- Captions in Courier New -->
<w:rPr><w:rFonts w:ascii="Courier New"/><w:sz w:val="18"/></w:rPr>
```

**GOOD: One font family with weight variation, or two complementary families**
```xml
<!-- H1: Calibri Light (thin weight of Calibri family) -->
<w:rPr><w:rFonts w:ascii="Calibri Light"/><w:sz w:val="40"/></w:rPr>
<!-- H2: Calibri Light -->
<w:rPr><w:rFonts w:ascii="Calibri Light"/><w:sz w:val="32"/></w:rPr>
<!-- Body: Calibri (regular weight) -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:sz w:val="22"/></w:rPr>
<!-- Captions: Calibri -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:sz w:val="18"/></w:rPr>
```
**Why better:** Limiting to one or two font families creates visual coherence. Vary by size and weight, not by font.

---

### 5b. Mismatched Personality — Comic Sans Meets Times New Roman

**BAD:**
```xml
<w:rPr><w:rFonts w:ascii="Comic Sans MS"/><w:sz w:val="36"/></w:rPr>  <!-- heading -->
<w:rPr><w:rFonts w:ascii="Times New Roman"/><w:sz w:val="24"/></w:rPr> <!-- body -->
```

**GOOD: Fonts with compatible character**
```xml
<w:rPr><w:rFonts w:ascii="Calibri Light"/><w:sz w:val="36"/></w:rPr>   <!-- heading -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:sz w:val="22"/></w:rPr>          <!-- body -->
```
**Why better:** Paired fonts should share a similar level of formality and geometric character. Comic Sans is playful/informal; Times New Roman is formal/traditional. They clash.

---

### 5c. Everything Bold — Nothing Stands Out

**BAD: Bold on body, headings, captions, everything**
```xml
<w:rPr><w:b/><w:sz w:val="40"/></w:rPr>  <!-- heading: bold -->
<w:rPr><w:b/><w:sz w:val="22"/></w:rPr>  <!-- body: also bold -->
<w:rPr><w:b/><w:sz w:val="18"/></w:rPr>  <!-- caption: still bold -->
```

**GOOD: Bold reserved for headings and key terms only**
```xml
<w:rPr><w:b/><w:sz w:val="40"/></w:rPr>   <!-- H1: bold -->
<w:rPr><w:sz w:val="32"/></w:rPr>          <!-- H2: size alone is enough -->
<w:rPr><w:sz w:val="22"/></w:rPr>          <!-- body: regular weight -->
<w:rPr><w:b/><w:sz w:val="22"/></w:rPr>    <!-- key term inline: bold -->
<w:rPr><w:sz w:val="18"/></w:rPr>          <!-- caption: regular, small -->
```
**Why better:** When everything is emphasized, nothing is emphasized. Bold should be a signal, not a default.

---

## 6. Color Abuse

### 6a. Rainbow Headings

**BAD: Each heading level a different bright color**
```xml
<w:rPr><w:color w:val="FF0000"/><w:sz w:val="40"/></w:rPr>  <!-- H1: red -->
<w:rPr><w:color w:val="00AA00"/><w:sz w:val="32"/></w:rPr>  <!-- H2: green -->
<w:rPr><w:color w:val="0000FF"/><w:sz w:val="26"/></w:rPr>  <!-- H3: blue -->
```

**GOOD: Single accent color for headings, black or dark gray for body**
```xml
<!-- All headings use the same muted accent -->
<w:rPr><w:color w:val="1F4E79"/><w:sz w:val="40"/></w:rPr>  <!-- H1: dark blue -->
<w:rPr><w:color w:val="1F4E79"/><w:sz w:val="32"/></w:rPr>  <!-- H2: same blue -->
<w:rPr><w:color w:val="1F4E79"/><w:sz w:val="26"/></w:rPr>  <!-- H3: same blue -->
<!-- Body in near-black -->
<w:rPr><w:color w:val="333333"/><w:sz w:val="22"/></w:rPr>
```
**Why better:** A single accent color establishes brand consistency. Multiple bright colors compete for attention and look unprofessional.

---

### 6b. Low Contrast — Light Gray on White

**BAD: #CCCCCC text on white background**
```xml
<w:rPr><w:color w:val="CCCCCC"/></w:rPr>
<!-- Contrast ratio: ~1.6:1 — fails WCAG AA (minimum 4.5:1) -->
```

**GOOD: #333333 text on white**
```xml
<w:rPr><w:color w:val="333333"/></w:rPr>
<!-- Contrast ratio: ~12:1 — passes WCAG AAA -->
```
**Why better:** Sufficient contrast is not just an accessibility requirement; it makes text physically easier to read for everyone, especially in printed documents.

---

### 6c. Bright Body Text

**BAD: Body text in a saturated color**
```xml
<w:rPr><w:color w:val="0066FF"/><w:sz w:val="22"/></w:rPr>  <!-- blue body text -->
```

**GOOD: Color reserved for headings and inline accents only**
```xml
<!-- Body: neutral dark -->
<w:rPr><w:color w:val="333333"/><w:sz w:val="22"/></w:rPr>
<!-- Hyperlink: color is functional here -->
<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr>
```
**Why better:** Colored body text causes eye fatigue over long reading. Reserve color for elements that need to attract attention (headings, links, warnings).

---

## 7. List Formatting Issues

### 7a. Bullet at the Margin — No Indent

**BAD: List items start at the left margin**
```
┌──────────────────────────────────┐
│Here is a paragraph of text.     │
│• First item                      │  ← Bullet at margin, no indent
│• Second item                     │
│• Third item                      │
│Next paragraph continues here.    │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:ind w:left="0" w:hanging="0"/>
</w:pPr>
```

**GOOD: 0.25in left indent with hanging indent for the bullet**
```
┌──────────────────────────────────┐
│Here is a paragraph of text.     │
│   • First item                   │  ← Indented, clearly a list
│   • Second item                  │
│   • Third item                   │
│Next paragraph continues here.    │
└──────────────────────────────────┘
```
```xml
<w:pPr>
  <w:ind w:left="360" w:hanging="360"/>  <!-- 0.25in = 360 twips -->
  <w:numPr>
    <w:ilvl w:val="0"/>
    <w:numId w:val="1"/>
  </w:numPr>
</w:pPr>
```
For nested lists, increment by 360 twips per level:
```xml
<!-- Level 1 -->
<w:ind w:left="720" w:hanging="360"/>   <!-- 0.5in left -->
<!-- Level 2 -->
<w:ind w:left="1080" w:hanging="360"/>  <!-- 0.75in left -->
```
**Why better:** Indentation visually separates lists from body text and makes nesting levels clear.

---

### 7b. List Items with Full Paragraph Spacing

**BAD: List items have the same 8-10pt spacing as body paragraphs**
```
┌──────────────────────────────────┐
│   • First item                   │
│                                  │  ← 10pt gap — looks like separate
│   • Second item                  │     paragraphs, not a list
│                                  │
│   • Third item                   │
└──────────────────────────────────┘
```
```xml
<w:spacing w:after="200"/>  <!-- 10pt after each list item -->
```

**GOOD: Tight spacing between list items (2-4pt)**
```
┌──────────────────────────────────┐
│   • First item                   │
│   • Second item                  │  ← 2pt gap — cohesive list
│   • Third item                   │
└──────────────────────────────────┘
```
```xml
<w:spacing w:after="40" w:line="276" w:lineRule="auto"/>  <!-- 2pt after -->
<!-- Or 4pt: -->
<w:spacing w:after="80"/>
```
**Why better:** Tight spacing groups list items as a single unit, matching how readers expect a list to behave.

---

## 8. Header/Footer Problems

### 8a. Header Text Too Large — Competes with Body

**BAD: Header in 12pt, same as body**
```
┌──────────────────────────────────┐
│ Quarterly Report - Q3 2025       │  ← 12pt header, same as body
│──────────────────────────────────│
│ Introduction                     │
│ This is the body text...         │  ← 12pt body — header distracts
└──────────────────────────────────┘
```
```xml
<!-- Header paragraph -->
<w:rPr><w:sz w:val="24"/></w:rPr>  <!-- 12pt, same as body -->
```

**GOOD: Header in 9pt, gray color, subtle**
```
┌──────────────────────────────────┐
│ Quarterly Report - Q3 2025       │  ← 9pt, gray — present but quiet
│──────────────────────────────────│
│ Introduction                     │
│ This is the body text...         │  ← Body stands out as primary
└──────────────────────────────────┘
```
```xml
<!-- Header paragraph -->
<w:rPr>
  <w:sz w:val="18"/>                <!-- 9pt -->
  <w:color w:val="808080"/>         <!-- medium gray -->
</w:rPr>
<w:pPr>
  <w:pBdr>
    <w:bottom w:val="single" w:sz="4" w:color="D9D9D9"/>  <!-- subtle separator -->
  </w:pBdr>
</w:pPr>
```
**Why better:** Headers are reference information, not primary content. They should be legible but visually subordinate.

---

### 8b. No Page Numbers on a Long Document

**BAD: 20-page document with no page numbers**
```xml
<!-- Footer section: empty or missing -->
```

**GOOD: Page numbers in footer, right-aligned or centered**
```xml
<!-- Footer paragraph with page number field -->
<w:p>
  <w:pPr>
    <w:jc w:val="center"/>
    <w:rPr><w:sz w:val="18"/><w:color w:val="808080"/></w:rPr>
  </w:pPr>
  <w:r>
    <w:rPr><w:sz w:val="18"/><w:color w:val="808080"/></w:rPr>
    <w:fldChar w:fldCharType="begin"/>
  </w:r>
  <w:r>
    <w:instrText> PAGE </w:instrText>
  </w:r>
  <w:r>
    <w:fldChar w:fldCharType="separate"/>
  </w:r>
  <w:r>
    <w:t>1</w:t>
  </w:r>
  <w:r>
    <w:fldChar w:fldCharType="end"/>
  </w:r>
</w:p>
```
**Why better:** Page numbers are essential for navigation in any document over ~3 pages. Readers need to reference specific pages, and printed documents need an ordering mechanism.

---

## 9. CJK-Specific Mistakes

### 9a. Using Italic for Chinese Emphasis

**BAD: Italic applied to Chinese text**
```xml
<w:rPr>
  <w:i/>
  <w:rFonts w:eastAsia="SimSun"/>
  <w:sz w:val="24"/>
</w:rPr>
```
CJK glyphs have no true italic form. The renderer applies a synthetic slant that looks broken and ugly — characters appear to lean awkwardly.

**GOOD: Use bold or emphasis dots (着重号) for Chinese emphasis**
```xml
<!-- Option A: Bold emphasis -->
<w:rPr>
  <w:b/>
  <w:rFonts w:eastAsia="SimHei"/>  <!-- Switch to bold-capable font -->
  <w:sz w:val="24"/>
</w:rPr>

<!-- Option B: Emphasis marks (dots under characters) -->
<w:rPr>
  <w:em w:val="dot"/>
  <w:rFonts w:eastAsia="SimSun"/>
  <w:sz w:val="24"/>
</w:rPr>
```
**Why better:** Chinese typography has its own emphasis traditions. Bold and emphasis dots are native CJK conventions; italic is a Latin-script concept that does not translate.

---

### 9b. Latin Font for Chinese Characters

**BAD: Only ASCII font set, no EastAsia font specified**
```xml
<w:rPr>
  <w:rFonts w:ascii="Arial"/>  <!-- No eastAsia attribute -->
  <w:sz w:val="24"/>
</w:rPr>
<!-- Word falls back to a random font. Chinese characters may render
     with wrong metrics, inconsistent stroke widths, or missing glyphs. -->
```

**GOOD: Explicit EastAsia font alongside ASCII font**
```xml
<w:rPr>
  <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/>
  <w:sz w:val="22"/>
</w:rPr>
```
For formal/academic Chinese documents:
```xml
<w:rPr>
  <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"
            w:eastAsia="SimSun"/>
  <w:sz w:val="24"/>  <!-- 小四 12pt -->
</w:rPr>
```
**Why better:** Setting `w:eastAsia` ensures Chinese characters render in a font designed for CJK glyphs, with correct stroke widths, spacing, and metrics.

---

### 9c. English Line Spacing for Dense CJK Text

**BAD: 1.15x line spacing for Chinese body text**
```xml
<w:spacing w:line="276" w:lineRule="auto"/>  <!-- 1.15x — too tight for CJK -->
```
CJK characters are taller and denser than Latin letters. At 1.15x, lines of Chinese text feel cramped and hard to read.

**GOOD: 1.5x line spacing or fixed 28pt for CJK body at 12pt (小四)**
```xml
<!-- Option A: 1.5x proportional -->
<w:spacing w:line="360" w:lineRule="auto"/>  <!-- 360/240 = 1.5x -->

<!-- Option B: Fixed 28pt (standard for 小四/12pt CJK body) -->
<w:spacing w:line="560" w:lineRule="exact"/>  <!-- 28pt = 560 twips -->
```
For 公文 (government documents) at 三号/16pt body:
```xml
<w:spacing w:line="580" w:lineRule="exact"/>  <!-- 29pt fixed line spacing -->
```
**Why better:** CJK characters occupy a full em square with no ascenders/descenders providing natural gaps. Extra line spacing compensates, improving readability of dense text blocks.

---

## 10. Overall Document Feel

### Student Homework vs Professional Document

**BAD: "Student homework" — every setting is Word's default, no intentional choices**
```xml
<!-- Default everything: Calibri 11pt, no heading styles, 1.08 spacing -->
<w:rPr><w:rFonts w:ascii="Calibri"/><w:sz w:val="22"/></w:rPr>
<w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr>
<!-- Headings: just bold body text, no style applied -->
<w:rPr><w:b/><w:sz w:val="22"/></w:rPr>
<!-- No section breaks, no headers/footers, no page numbers -->
<!-- Tables with default full grid borders -->
<!-- No intentional color or spacing variations -->
```

**GOOD: Intentional design at every level**
```xml
<!-- Theme fonts defined -->
<w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi"/>

<!-- H1: Calibri Light 20pt, dark blue, generous spacing -->
<w:pPr>
  <w:pStyle w:val="Heading1"/>
  <w:spacing w:before="480" w:after="200"/>
</w:pPr>
<w:rPr>
  <w:rFonts w:ascii="Calibri Light"/>
  <w:color w:val="1F4E79"/>
  <w:sz w:val="40"/>
</w:rPr>

<!-- H2: Calibri Light 16pt, same blue -->
<w:pPr>
  <w:pStyle w:val="Heading2"/>
  <w:spacing w:before="320" w:after="120"/>
</w:pPr>
<w:rPr>
  <w:rFonts w:ascii="Calibri Light"/>
  <w:color w:val="1F4E79"/>
  <w:sz w:val="32"/>
</w:rPr>

<!-- Body: Calibri 11pt, dark gray, 1.15 spacing, 8pt after -->
<w:pPr>
  <w:spacing w:after="160" w:line="276" w:lineRule="auto"/>
</w:pPr>
<w:rPr>
  <w:rFonts w:ascii="Calibri"/>
  <w:color w:val="333333"/>
  <w:sz w:val="22"/>
</w:rPr>

<!-- Tables: three-line style, padded cells, repeated headers -->
<!-- Headers/footers: 9pt gray with page numbers -->
<!-- Margins: 1in all around -->
<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
```
**Why better:** Professional documents result from deliberate, consistent choices across all design dimensions. Each element reinforces the same visual language. The reader may not consciously notice good typography, but they feel the difference in credibility and readability.

---

## Quick Reference: Safe Defaults

A cheat sheet of values that produce a professional result for most Western business documents:

| Element | Value | OpenXML |
|---------|-------|---------|
| Body font | Calibri 11pt | `w:sz="22"` |
| H1 | Calibri Light 20pt | `w:sz="40"` |
| H2 | Calibri Light 16pt | `w:sz="32"` |
| H3 | Calibri 13pt bold | `w:sz="26"`, `w:b` |
| Body color | #333333 | `w:color="333333"` |
| Heading color | #1F4E79 | `w:color="1F4E79"` |
| Line spacing | 1.15x | `w:line="276" w:lineRule="auto"` |
| Para spacing after | 8pt | `w:after="160"` |
| H1 spacing | 24pt before, 10pt after | `w:before="480" w:after="200"` |
| H2 spacing | 16pt before, 6pt after | `w:before="320" w:after="120"` |
| Margins | 1in all around | `w:pgMar` all `"1440"` |
| Table cell padding | 0.08in / 0.12in | `w:w="115"` / `w:w="173"` |
| Header/footer size | 9pt gray | `w:sz="18" w:color="808080"` |
| List indent | 0.25in per level | `w:left="360" w:hanging="360"` |
| List item spacing | 2pt after | `w:after="40"` |

For CJK documents, adjust: body font to SimSun/YaHei, line spacing to 1.5x (`w:line="360"`), and set `w:eastAsia` on all `w:rFonts`.
