# Scenario A: Creating a New DOCX from Scratch

## When to Use

Use Scenario A when:
- The user has no existing file and wants a brand new document
- The user provides content (text, tables, images) and wants it assembled into a DOCX
- The user specifies a document type (report, letter, memo, academic) or describes a custom layout

Do NOT use when: the user already has a DOCX they want to modify (→ Scenario B) or wants to restyle an existing document (→ Scenario C).

---

## Step-by-Step Workflow

### 1. Determine Document Type

Ask or infer the document type from the user's request:

| Type | Typical Signals |
|------|----------------|
| Report | "report", "analysis", "whitepaper", sections with headings |
| Letter | "letter", "dear", address block, salutation |
| Memo | "memo", "memorandum", To/From/Subject fields |
| Academic | "paper", "essay", "thesis", APA/MLA/Chicago mention |
| Custom | None of the above, or user specifies exact formatting |

### 2. Gather Content Requirements

Collect from the user:
- Title and subtitle (if any)
- Author / organization
- Section structure (headings and nesting)
- Body content per section
- Tables (headers + rows)
- Images (file paths or placeholders)
- Special elements: TOC, page numbers, watermark, headers/footers

### 3. Select Style Set

Based on document type, load the matching styles XML asset:
- Report → `assets/styles/default_styles.xml` or `assets/styles/corporate_styles.xml`
- Academic → `assets/styles/academic_styles.xml`
- Letter / Memo / Custom → `assets/styles/default_styles.xml` (with overrides)

### 4. Configure Page Setup

Set `w:sectPr` values based on document type defaults (see below) or user overrides.

```xml
<w:sectPr>
  <w:pgSz w:w="11906" w:h="16838" />  <!-- A4 -->
  <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
           w:header="720" w:footer="720" w:gutter="0" />
</w:sectPr>
```

### 5. Build Document Structure

Assemble `word/document.xml` with:
1. `w:body` as root container
2. Paragraphs (`w:p`) with heading styles for section titles
3. Body paragraphs with `Normal` style
4. Tables, images, and other elements as needed
5. Final `w:sectPr` as last child of `w:body`

### 6. Apply Typography Defaults

Set document-level defaults in `styles.xml` under `w:docDefaults`:
```xml
<w:docDefaults>
  <w:rPrDefault>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="SimSun" w:cs="Arial" />
      <w:sz w:val="22" />  <!-- 11pt -->
      <w:szCs w:val="22" />
    </w:rPr>
  </w:rPrDefault>
  <w:pPrDefault>
    <w:pPr>
      <w:spacing w:after="160" w:line="259" w:lineRule="auto" />
    </w:pPr>
  </w:pPrDefault>
</w:docDefaults>
```

### 7. Add Complex Elements

See the Complex Elements Guide section below.

### 8. Run Validation Pipeline

```
dotnet run ... validate --xsd wml-subset.xsd
dotnet run ... validate --xsd business-rules.xsd   # if applying a template
```

---

## Document Type Defaults

### Report
| Property | Value |
|----------|-------|
| Body font | Calibri 11pt |
| Heading font | Calibri Light |
| H1 / H2 / H3 / H4 size | 28pt / 24pt / 18pt / 14pt |
| Heading color | #2F5496 (corporate blue) |
| Margins | 1 inch (1440 DXA) all sides |
| Page size | A4 (11906 × 16838 DXA) |
| Line spacing | Single (line="240") |
| Paragraph spacing | 0pt before, 8pt after body |

### Letter
| Property | Value |
|----------|-------|
| Font | Calibri 11pt |
| Page size | Letter (12240 × 15840 DXA) |
| Margins | 1 inch all sides |
| Structure | Date → Address → Salutation → Body → Closing → Signature |
| Line spacing | Single |

### Memo
| Property | Value |
|----------|-------|
| Font | Arial 11pt |
| Page size | Letter |
| Margins | 0.75 inch (1080 DXA) |
| Header | "MEMO" centered, bold, 16pt |
| Fields | To, From, Date, Subject (bold labels, tab-aligned values) |

### Academic
| Property | Value |
|----------|-------|
| Font | Times New Roman 12pt |
| Line spacing | Double (line="480") |
| Margins | 1 inch all sides |
| Page size | Letter |
| Headings | Bold, same font, 14/13/12pt for H1/H2/H3 |
| First line indent | 0.5 inch (720 DXA) |
| Heading color | Black (no color) |

---

## Content Configuration JSON Format

The CLI `create` command accepts a JSON config:

```json
{
  "type": "report",
  "title": "Quarterly Revenue Analysis",
  "subtitle": "Q1 2026",
  "author": "Finance Team",
  "pageSize": "A4",
  "margins": { "top": 1440, "right": 1440, "bottom": 1440, "left": 1440 },
  "sections": [
    {
      "heading": "Executive Summary",
      "level": 1,
      "content": [
        { "type": "paragraph", "text": "Revenue grew 12% year-over-year..." },
        {
          "type": "table",
          "headers": ["Region", "Revenue", "Growth"],
          "rows": [
            ["North America", "$4.2M", "+15%"],
            ["Europe", "$2.8M", "+8%"],
            ["Asia Pacific", "$1.9M", "+18%"]
          ]
        },
        { "type": "image", "path": "charts/revenue.png", "width": "5in", "alt": "Revenue chart" }
      ]
    },
    {
      "heading": "Detailed Analysis",
      "level": 1,
      "content": [
        { "type": "paragraph", "text": "Breaking down by product line..." }
      ]
    }
  ]
}
```

Supported content types:
- `paragraph` — body text (applies Normal style)
- `table` — headers + rows (applies TableGrid style)
- `image` — inline image with width/height control
- `list` — bulleted or numbered list items
- `pageBreak` — forces a page break

---

## Complex Elements Guide

### Table of Contents

Insert a TOC field code. Word will update the actual entries when the file is opened:

```xml
<w:p>
  <w:pPr><w:pStyle w:val="TOCHeading" /></w:pPr>
  <w:r><w:t>Table of Contents</w:t></w:r>
</w:p>
<w:p>
  <w:r>
    <w:fldChar w:fldCharType="begin" />
  </w:r>
  <w:r>
    <w:instrText xml:space="preserve"> TOC \o "1-3" \h \z \u </w:instrText>
  </w:r>
  <w:r>
    <w:fldChar w:fldCharType="separate" />
  </w:r>
  <w:r>
    <w:t>[Table of contents — update to populate]</w:t>
  </w:r>
  <w:r>
    <w:fldChar w:fldCharType="end" />
  </w:r>
</w:p>
```

### Page Numbers in Footer

Add a footer part (`word/footer1.xml`) and reference it in `w:sectPr`:

```xml
<!-- In footer1.xml -->
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="center" /></w:pPr>
    <w:r>
      <w:fldChar w:fldCharType="begin" />
    </w:r>
    <w:r>
      <w:instrText>PAGE</w:instrText>
    </w:r>
    <w:r>
      <w:fldChar w:fldCharType="separate" />
    </w:r>
    <w:r><w:t>1</w:t></w:r>
    <w:r>
      <w:fldChar w:fldCharType="end" />
    </w:r>
  </w:p>
</w:ftr>

<!-- In sectPr -->
<w:footerReference w:type="default" r:id="rId8" />
```

### Watermark

Add a header part with a shape behind the text:

```xml
<w:hdr>
  <w:p>
    <w:r>
      <w:pict>
        <v:shape style="position:absolute;margin-left:0;margin-top:0;width:468pt;height:180pt;
                        z-index:-251657216;mso-position-horizontal:center;
                        mso-position-vertical:center"
                 fillcolor="silver" stroked="f">
          <v:textpath style="font-family:'Calibri';font-size:1pt" string="DRAFT" />
        </v:shape>
      </w:pict>
    </w:r>
  </w:p>
</w:hdr>
```

---

## Post-Creation Checklist

1. **Validate** against `wml-subset.xsd` — all elements in correct order, required attributes present
2. **Merge adjacent runs** with identical formatting to keep XML clean
3. **Verify relationships** — every `r:id` in document.xml has a matching entry in `document.xml.rels`
4. **Check content types** — every part in the package is registered in `[Content_Types].xml`
5. **Preview** — open in Word or LibreOffice to visually confirm layout
6. **File size** — confirm images are reasonably sized (compress if > 2MB each)
