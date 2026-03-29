# OpenXML SDK C# Code Encyclopedia
Complete, heavily commented C# code patterns for DocumentFormat.OpenXml 3.x / .NET 8+ / C# 12.

**Namespace aliases used throughout:**
```csharp
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A  = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using M  = DocumentFormat.OpenXml.Math;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;
```

**EMU conversion reference** (used throughout image/shape code):
```
1 inch  = 914400 EMU
1 cm    = 360000 EMU
1 pixel @ 96dpi = 9525 EMU
1 pt    = 12700 EMU
```

---

## Table of Contents

1. [Table of Contents (TOC)](#1-table-of-contents-toc)
2. [Footnotes and Endnotes](#2-footnotes-and-endnotes)
3. [Field Codes — Comprehensive](#3-field-codes--comprehensive)
4. [Track Changes / Revisions](#4-track-changes--revisions)
5. [Comments (4-File System)](#5-comments-4-file-system)
6. [Images — Deep Dive](#6-images--deep-dive)
7. [Drawing Shapes (Non-Image)](#7-drawing-shapes-non-image)
8. [Math / Equations (OMML)](#8-math--equations-omml)
9. [Numbering System — Deep Dive](#9-numbering-system--deep-dive)
10. [Document Protection & Encryption](#10-document-protection--encryption)

---

## 1. Table of Contents (TOC)

### 1.1 Basic TOC Field (SimpleField Pattern)

The simplest way to insert a TOC. Uses `SimpleField` which wraps the entire field in one element.

```csharp
// Creates:
// <w:p>
//   <w:r>
//     <w:fldChar w:fldCharType="begin"/>
//   </w:r>
//   <w:r>
//     <w:instrText xml:space="preserve"> TOC \o "1-3" \h \z \u </w:instrText>
//   </w:r>
//   <w:r>
//     <w:fldChar w:fldCharType="separate"/>
//   </w:r>
//   <w:r>
//     <w:t>Update this field to generate table of contents.</w:t>
//   </w:r>
//   <w:r>
//     <w:fldChar w:fldCharType="end"/>
//   </w:r>
// </w:p>

var tocParagraph = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TOC \\o \"1-3\" \\h \\z \\u ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    // Placeholder text shown before update
    new Run(new Text("Update this field to generate table of contents.") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
body.Append(tocParagraph);
```

**TOC switch reference:**
| Switch | Meaning |
|--------|---------|
| `\o "1-3"` | Include outline levels 1–3 (customize as needed) |
| `\h` | Make entries hyperlinks (clickable) |
| `\z` | Hide tab leader and page numbers in Web Layout view |
| `\u` | Use applied paragraph outline level |
| `\f` | TOC entry from bookmark |
| `\t "style1,style2"` | Use custom styles instead of outline levels |
| `\n "1-2"` | Omit page numbers for levels 1–2 |

### 1.2 TOC Field with SdtBlock Wrapper

Wrapping a TOC in a Structured Document Tag (SdtBlock) enables rich content control features.

```csharp
// SdtBlock wrapper provides:
// - Ability to repeat/remove the entire TOC
// - Richer programmatic control
// - "Content Control" appearance in Word UI

var sdtBlock = new SdtBlock(
    // SdtProperties defines the control's identity and behavior
    new SdtProperties(
        new SdtAlias { Val = "Table of Contents" },
        new Tag { Val = "toc" },
        new SdtContentText()  // Plain text content
    ),
    // SdtContentBlock contains the actual TOC field
    new SdtContentBlock(
        new Paragraph(
            new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
            new Run(new FieldCode(" TOC \\o \"1-2\" \\h \\z ") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
            new Run(new Text("Press F9 or right-click and select 'Update Field'") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.End })
        )
    )
);
body.Append(sdtBlock);
```

### 1.3 TOC with Custom Heading Levels

Use the `\t` switch to build a TOC from arbitrary styles (not just Heading 1–9).

```csharp
// TOC using custom style names instead of outline levels:
// \t switch format: "style1,level1,style2,level2,..."
// This uses CustomHeading1 and CustomHeading2 styles mapped to TOC levels

var customTocPara = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TOC \\t \"CustomHeading1,1,CustomHeading2,2,CustomHeading3,3\" \\h \\z ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Update to see entries from CustomHeading1/2/3 styles.") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

### 1.4 TOC with Hyperlinks (\h switch)

The `\h` switch makes TOC entries clickable hyperlinks. This requires the entries to have a hyperlink anchor.

```csharp
// When \h is used, Word generates internal hyperlinks to each heading.
// The target is the bookmark automatically created by Word for headings.
// This is the standard pattern — no additional work needed in the field code itself.

var tocWithHyperlinks = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TOC \\o \"1-3\" \\h \\z \\u ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    // In Web Layout/Print Layout, Word will populate this with real entries
    // Each entry will be a hyperlink pointing to the heading's internal bookmark
    new Run(new Text("Click to update...") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

### 1.5 Auto-Update TOC on Document Open

You cannot programmatically update a TOC field's content (Word does this on open). Instead, tell Word to update fields automatically.

```csharp
// Method 1: Via DocumentSettingsPart — UpdateFieldsOnOpen
var settingsPart = mainDocumentPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings(
    new UpdateFieldsOnOpen { Val = true }  // Triggers field update on open
);
settingsPart.Settings.Save();

// Method 2: Field code includes \w to preserve formatting changes
// (Field code approach is limited — you still need Word to evaluate it)

// GOTCHA: OpenXML SDK cannot evaluate field codes.
// Word evaluates fields on open. Other readers (e.g., LibreOffice) may not.
// The document opens without content until the user explicitly updates.
```

### 1.6 TOC Styles — Custom TOC1, TOC2, TOC3 Styles with Leaders

Define custom TOC styles with indentation, tab leaders, and proper formatting.

```csharp
// First, add TOC1/TOC2/TOC3 styles to StyleDefinitionsPart
var stylesPart = mainDocumentPart.AddNewPart<StyleDefinitionsPart>();
var styles = new Styles();

// TOC1 — Top-level entry (e.g., "1. Heading")
var toc1Style = new Style(
    new StyleName { Val = "toc 1" },
    new BasedOn { Val = "Normal" },
    new PrimaryStyle(),
    new StyleParagraphProperties(
        new SpacingBetweenLines { Before = "120", After = "60" },
        new Tabs(new TabStop { Val = TabStopValues.Right, Leader = TabStopLeaderCharValues.Dot, Position = 9072 })  // 5 inches right-aligned with dot leader
    ),
    new StyleRunProperties(
        new Bold(),
        new FontSize { Val = "24" },  // 12pt
        new FontSizeComplexScript { Val = "24" }
    )
) { Type = StyleValues.Paragraph, StyleId = "TOC1" };
styles.Append(toc1Style);

// TOC2 — Second-level entry (e.g., "1.1  Subheading")
var toc2Style = new Style(
    new StyleName { Val = "toc 2" },
    new BasedOn { Val = "Normal" },
    new PrimaryStyle(),
    new StyleParagraphProperties(
        new Indentation { Left = "220", Hanging = "220" },  // 0.15" indent, hang to align after number
        new SpacingBetweenLines { Before = "60", After = "40" },
        new Tabs(new TabStop { Val = TabStopValues.Right, Leader = TabStopLeaderCharValues.Dot, Position = 9072 })
    ),
    new StyleRunProperties(
        new FontSize { Val = "20" },  // 10pt
        new FontSizeComplexScript { Val = "20" }
    )
) { Type = StyleValues.Paragraph, StyleId = "TOC2" };
styles.Append(toc2Style);

// TOC3 — Third-level entry
var toc3Style = new Style(
    new StyleName { Val = "toc 3" },
    new BasedOn { Val = "Normal" },
    new PrimaryStyle(),
    new StyleParagraphProperties(
        new Indentation { Left = "440", Hanging = "440" },  // 0.3" indent
        new SpacingBetweenLines { Before = "40", After = "20" },
        new Tabs(new TabStop { Val = TabStopValues.Right, Leader = TabStopLeaderCharValues.Dot, Position = 9072 })
    ),
    new StyleRunProperties(
        new Italic(),
        new FontSize { Val = "20" },
        new FontSizeComplexScript { Val = "20" }
    )
) { Type = StyleValues.Paragraph, StyleId = "TOC3" };
styles.Append(toc3Style);

stylesPart.Styles = styles;
stylesPart.Styles.Save();

// Now use \t switch to reference these styles in the TOC field:
// TOC \t "TOC1,1,TOC2,2,TOC3,3" \h \z
```

**Tab leader options:** `TabStopLeaderCharValues.Dot` (........), `TabStopLeaderCharValues.Dash` (--------), `TabStopLeaderCharValues.Underscore` (________), `TabStopLeaderCharValues.MiddleDot` (·······).

### 1.7 Mini TOC for a Section

A mini TOC covers only a portion of the document using a bookmark-scoped `\f` switch.

```csharp
// Step 1: Define a bookmark around the section to be covered
var sectionStart = new BookmarkStart { Id = "10", Name = "_Section1TOC" };
var sectionEnd = new BookmarkEnd { Id = "10" };

// Step 2: Put heading paragraphs inside the bookmark range
var headingPara = new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
    new Run(new Text("Section A: Introduction"))
);

// Full section wrapped in bookmark
body.Append(sectionStart);
body.Append(headingPara);
body.Append(sectionEnd);

// Step 3: Mini TOC field references that bookmark with \f switch
var miniTocPara = new Paragraph(
    new Run(new Text("In this section: ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TOC \\f _Section1TOC ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Mini TOC placeholder") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

---

## 2. Footnotes and Endnotes

### 2.1 FootnotesPart — Initialization

Footnotes in Word require a dedicated `FootnotesPart`. The first three footnotes are special: separator, continuation separator, and continuation notice.

```csharp
// Initialize the FootnotesPart
var footnotesPart = mainDocumentPart.AddNewPart<FootnotesPart>();
var footnotes = new Footnotes();

// CRITICAL: Footnotes must start with these 3 special footnotes:
// 1. Separator (id="0") — thin line between main text and footnotes
// 2. ContinuationSeparator (id="1") — thick line when footnotes continue to next column/page
// 3. ContinuationNotice (id="2") — "..." text when footnotes overflow

// Footnote ID=0: Separator (appears between main text and first footnote)
var separatorFootnote = new Footnote(
    new Paragraph(
        new ParagraphProperties(
            new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto }
        ),
        // The separator is just a paragraph with a border at the bottom
        new Paragraph(
            new Run(new Separator())
        )
    )
) { Type = FootnoteEndnoteValues.Separator, Id = 0 };
footnotes.Append(separatorFootnote);

// Footnote ID=1: Continuation Separator
var continuationSepFootnote = new Footnote(
    new Paragraph(
        new ParagraphProperties(
            new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto }
        ),
        new Run(new ContinuationSeparator())
    )
) { Type = FootnoteEndnoteValues.ContinuationSeparator, Id = 1 };
footnotes.Append(continuationSepFootnote);

// Footnote ID=2: Continuation Notice (optional, appears when footnotes overflow)
var continuationNoticeFootnote = new Footnote(
    new Paragraph(
        new ParagraphProperties(
            new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto }
        ),
        new Run(new Text("...") { Space = SpaceProcessingModeValues.Preserve })
    )
) { Type = FootnoteEndnoteValues.ContinuationNotice, Id = 2 };
footnotes.Append(continuationNoticeFootnote);

footnotesPart.Footnotes = footnotes;
footnotesPart.Footnotes.Save();
```

### 2.2 Adding a Normal Footnote

Place a `FootnoteReference` in the document body and corresponding `Footnote` content in `FootnotesPart`.

```csharp
// In the document body, at the insertion point:
var footnoteRefRun = new Run(
    new RunProperties(
        new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
    ),
    new FootnoteReference { Id = 3 }  // ID must match the Footnote's Id
);
body.Append(new Paragraph(
    new Run(new Text("Some text with a footnote marker.") { Space = SpaceProcessingModeValues.Preserve }),
    footnoteRefRun
));

// In FootnotesPart, add the corresponding footnote content:
// <w:footnote w:id="3">
//   <w:p>
//     <w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>
//     <w:r><w:footnoteRef/></w:r>
//     <w:r><w:t xml:space="preserve"> This is the footnote text.</w:t></w:r>
//   </w:p>
// </w:footnote>

var newFootnote = new Footnote { Id = 3 };
newFootnote.Append(new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "FootnoteText" }),
    new Run(new FootnoteReferenceMark()),  // Small superscript mark
    new Run(new Text(" This is the footnote text.") { Space = SpaceProcessingModeValues.Preserve })
));
footnotesPart.Footnotes!.Append(newFootnote);
footnotesPart.Footnotes.Save();
```

### 2.3 Footnote with Custom Mark (Asterisk, Symbol)

Override the default auto-numbering with a custom symbol.

```csharp
// Use FootnoteReferenceMark (the automatic symbol) OR provide a custom character.
// For custom marks, use a regular Run with the symbol character instead of FootnoteReferenceMark.

// Footnote ID=4 with custom asterisk mark
var customFootnote = new Footnote { Id = 4 };
customFootnote.Append(new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "FootnoteText" }),
    // Custom mark: use a bold asterisk from Symbol font
    new Run(
        new RunProperties(
            new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
        ),
        new RunFonts { Ascii = "Symbol", HighAnsi = "Symbol" },
        new Text("*")
    ),
    new Run(new Text(" Custom footnote with symbol mark.") { Space = SpaceProcessingModeValues.Preserve })
));
footnotesPart.Footnotes!.Append(customFootnote);

// In document body, at the insertion point:
var customFootnoteRef = new Run(
    new RunProperties(
        new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
    ),
    new FootnoteReference { Id = 4 }
);
```

### 2.4 FootnotePosition — Placement via SectionProperties

Control whether footnotes appear at the bottom of each page or beneath the text.

```csharp
// Add FootnoteProperties to SectionProperties
var sectPr = body.Elements<SectionProperties>().First()
    ?? body.AppendChild(new SectionProperties());

// Footnote placement:
// - BottomOfPage (default) — footnotes appear at bottom of page
// - BeneathText — footnotes appear immediately below the last text on the page
sectPr.Append(new FootnoteProperties(
    new FootnotePosition { Val = FootnotePositionValues.BeneathText }
));

// Footnote numbering restart options:
// - RestartAtSection — restart numbering at each section
// - RestartAtPage — restart at each page (Word default for footnotes)
// - Continuous — don't restart (number sequentially through document)
sectPr.Append(new FootnoteProperties(
    new FootnotePosition { Val = FootnotePositionValues.BottomOfPage },
    new FootnoteNumberingFormat { Val = NumberFormatValues.Decimal },  // 1, 2, 3...
    new FootnoteNumberingStart { Val = 1 },  // Start at 1
    new FootnoteNumberingRestart { Val = FootnoteRestartValues.RestartAtPage }
));
```

### 2.5 EndnotesPart — Same Pattern

Endnotes follow the exact same structure as footnotes but use `EndnotesPart`.

```csharp
var endnotesPart = mainDocumentPart.AddNewPart<EndnotesPart>();
var endnotes = new Endnotes();

// Endnote ID=0: Separator (same pattern as footnotes)
var endnoteSeparator = new Endnote(
    new Paragraph(new Run(new Separator()))
) { Type = FootnoteEndnoteValues.Separator, Id = 0 };
endnotes.Append(endnoteSeparator);

// Endnote ID=1: ContinuationSeparator
var endnoteContSep = new Endnote(
    new Paragraph(new Run(new ContinuationSeparator()))
) { Type = FootnoteEndnoteValues.ContinuationSeparator, Id = 1 };
endnotes.Append(endnoteContSep);

endnotesPart.Endnotes = endnotes;
endnotesPart.Endnotes.Save();

// In document body, use EndnoteReference instead of FootnoteReference
var endnoteRefRun = new Run(
    new RunProperties(
        new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
    ),
    new EndnoteReference { Id = 3 }
);
body.Append(new Paragraph(
    new Run(new Text("An endnote marker.") { Space = SpaceProcessingModeValues.Preserve }),
    endnoteRefRun
));

// Corresponding Endnote content in EndnotesPart
var newEndnote = new Endnote { Id = 3 };
newEndnote.Append(new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "EndnoteText" }),
    new Run(new EndnoteReferenceMark()),
    new Run(new Text(" This is the endnote content.") { Space = SpaceProcessingModeValues.Preserve })
));
endnotesPart.Endnotes!.Append(newEndnote);
```

### 2.6 Endnote Placement via SectionProperties

```csharp
// EndnoteProperties on SectionProperties controls endnote placement
sectPr.Append(new EndnoteProperties(
    new EndnotePosition { Val = EndnotePositionValues.EndOfDocument }  // Default
    // Other options: EndOfSection, BeneathText (rarely used for endnotes)
));
```

---

## 3. Field Codes — Comprehensive

### 3.1 SimpleField vs Complex Field Architecture

**SimpleField** — single element, easier to write but less control:
```csharp
// <w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>
new SimpleField(new Run(new Text("1"))) { Instruction = " PAGE " }
```

**Complex Field (Begin/Separate/End)** — full control over each field component:
```csharp
// <w:r><w:fldChar w:fldCharType="begin"/></w:r>
// <w:r><w:instrText> PAGE </w:instrText></w:r>
// <w:r><w:fldChar w:fldCharType="separate"/></w:r>
// <w:r><w:t>1</w:t></w:r>
// <w:r><w:fldChar w:fldCharType="end"/></w:r>
new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }),
new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
new Run(new Text("1")),  // Cached result shown until update
new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
```

**Key differences:**
- `SimpleField` is one `w:fldSimple` element containing one `w:r`
- Complex field uses `FieldChar` with `FieldCharValues.Begin/Separate/End` to delimit regions
- `FieldCode` is `w:instrText` — contains the field instruction string
- The text between `Separate` and `End` is the "cached result" shown before update
- After `Separate`, `FieldCode` contains the switches that define field behavior

### 3.2 PAGE, NUMPAGES, DATE, TIME

**PAGE — current page number:**
```csharp
// SimpleField version
new SimpleField(new Run(new Text("1"))) { Instruction = " PAGE " }

// Complex field version
new Paragraph(
    new Run(new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("1")),  // Cached value
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

**NUMPAGES — total page count:**
```csharp
new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" NUMPAGES ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("10")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(" pages") { Space = SpaceProcessingModeValues.Preserve })
);
```

**DATE — current date with format switch:**
```csharp
// DATE with custom format: \@ "yyyy-MM-dd"
// The \@ switch specifies the date picture
new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" DATE \\@ \"yyyy-MM-dd\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("2026-03-22")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// DATE with time: \@ "MMMM d, yyyy h:mm AM/PM"
new Run(new FieldCode(" DATE \\@ \"MMMM d, yyyy h:mm AM/PM\" ") { Space = SpaceProcessingModeValues.Preserve }),

// DATE with locale: \* MERGEFORMAT preserves formatting on update
new Run(new FieldCode(" DATE \\@ \"d/M/yyyy\" \\* MERGEFORMAT ") { Space = SpaceProcessingModeValues.Preserve }),
```

**TIME — current time:**
```csharp
new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TIME \\@ \"HH:mm:ss\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("14:30:00")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

### 3.3 FILENAME, AUTHOR, TITLE (Document Properties)

These fields pull from the document's core properties.

```csharp
// FILENAME — document filename
new Run(new FieldCode(" FILENAME ") { Space = SpaceProcessingModeValues.Preserve }),

// FILENAME with path: \* MERGEFORMAT
new Run(new FieldCode(" FILENAME \\* MERGEFORMAT ") { Space = SpaceProcessingModeValues.Preserve }),

// AUTHOR — from document core properties
new Run(new FieldCode(" AUTHOR ") { Space = SpaceProcessingModeValues.Preserve }),

// TITLE — from document core properties
new Run(new FieldCode(" TITLE ") { Space = SpaceProcessingModeValues.Preserve }),

// SUBJECT — from document core properties
new Run(new FieldCode(" SUBJECT ") { Space = SpaceProcessingModeValues.Preserve }),

// Keywords — from document core properties
new Run(new FieldCode(" KEYWORDS ") { Space = SpaceProcessingModeValues.Preserve }),

// All document property fields
new Paragraph(
    new Run(new Text("Title: ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" TITLE ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("My Document")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

**Set document properties programmatically:**
```csharp
// Set core properties via PackageProperties (OfficePackage)
var package = doc.ExtendedFilePropertiesPart?.Properties;
if (package != null)
{
    package.Creator = "Author Name";
    package.Title = "Document Title";
    package.Subject = "Subject";
    package.Description = "Description";
    package.Keywords = "keyword1, keyword2";
    package.Save();
}
```

### 3.4 REF — Cross-Reference to Bookmark

`REF` retrieves the text of a bookmarked paragraph or the value of a REF field.

```csharp
// First, create a bookmark around some content
var bookmarkStart = new BookmarkStart { Id = "100", Name = "Figure1Caption" };
var bookmarkEnd = new BookmarkEnd { Id = "100" };
var captionPara = new Paragraph(
    new Run(new Text("Figure 1: Architecture diagram") { Space = SpaceProcessingModeValues.Preserve })
);
body.Append(new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Caption" }),
    bookmarkStart,
    new Run(new Text("Figure 1: Architecture diagram")),
    bookmarkEnd
));

// Now reference it with REF field
var refField = new Paragraph(
    new Run(new Text("As shown in ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" REF Figure1Caption \\* MERGEFORMAT ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Figure 1: Architecture diagram")),  // Cached result
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(", the system consists of...") { Space = SpaceProcessingModeValues.Preserve })
);
```

**REF switches:**
| Switch | Effect |
|--------|--------|
| `\r` | Insert bookmarked text but as hyperlink |
| `\h` | Make REF a hyperlink to the bookmark |
| `\n` | Suppress paragraph number |
| `\p` | Show relative position (above/below) |
| `\t` | Suppress trailing spaces |
| `\* MERGEFORMAT` | Preserve formatting |

### 3.5 SEQ — Sequence Numbering for Figures/Tables

`SEQ` generates auto-incrementing numbers for elements like figures, tables, and listings.

```csharp
// First figure caption
var fig1Caption = new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Caption" }),
    new Run(new Text("Figure ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" SEQ Figure \\* ARABIC ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("1")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(": System Architecture") { Space = SpaceProcessingModeValues.Preserve })
);

// Second figure (Word auto-increments)
var fig2Caption = new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Caption" }),
    new Run(new Text("Figure ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" SEQ Figure \\* ARABIC ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("2")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(": Data Flow") { Space = SpaceProcessingModeValues.Preserve })
);

// Reference a figure number
var figRef = new Paragraph(
    new Run(new Text("See Figure ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" SEQ Figure \\* ARABIC ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("1")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(" above.") { Space = SpaceProcessingModeValues.Preserve })
);

// SEQ sequence identifier: "Figure" can be any name
// Multiple sequences: SEQ Figure, SEQ Table, SEQ Listing are independent
```

### 3.6 HYPERLINK — Internal and External Links

```csharp
// External hyperlink (to URL)
var extHyperlinkRel = mainDocumentPart.AddHyperlinkRelationship(
    new Uri("https://example.com"), true);
var extHyperlink = new Hyperlink(
    new Run(
        new RunProperties(new Color { Val = "0563C1" }, new Underline { Val = UnderlineValues.Single }),
        new Text("Visit Example.com")
    )
) { Id = extHyperlinkRel.Id };  // Id references the relationship

// Internal hyperlink (to bookmark)
var intHyperlink = new Hyperlink(
    new Run(
        new RunProperties(new Color { Val = "0563C1" }, new Underline { Val = UnderlineValues.Single }),
        new Text("Go to Chapter 1")
    )
) { Anchor = "Chapter1Bookmark" };  // Anchor = bookmark name

// HYPERLINK field for advanced cases (with screen tip)
var hyperlinkedField = new Run(
    new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" HYPERLINK \\l \"Chapter1Bookmark\" \\t \"_top\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Go to Chapter 1")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// \l = target (anchor for internal, URL for external)
// \t = target frame (optional, e.g., "_top" to open in same window)
```

### 3.7 MERGEFIELD — Mail Merge

```csharp
// MERGEFIELD uses a special syntax: MERGEFIELD FieldName
// The field name must match a mail merge data source column name

// Simple MERGEFIELD
var mergeFieldPara = new Paragraph(
    new Run(new Text("Dear ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" MERGEFIELD FirstName ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("«FirstName»")),  // «» are Word's placeholder markers
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    new Run(new Text(",") { Space = SpaceProcessingModeValues.Preserve })
);

// Full name with formatting
var mergeFieldWithFormat = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" MERGEFIELD FullName \\* UPPERCASE ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("«FullName»")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// To actually perform mail merge, use Word's MailMerge settings
var settingsPart = mainDocumentPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings(
    new MailMerge(
        new DataType { Val = MailMergeDataValues.TextFile },
        new DataSourceReference { Id = "rIdForDataSource" }
    )
);
```

### 3.8 IF Field — Conditional Text

The `IF` field evaluates a condition and displays one of two text values. Commonly used with `MERGEFIELD`.

```csharp
// IF Field syntax: IF [expression] [operator] [value] "true_text" "false_text"
// Often combined with MERGEFIELD:

// If the recipient's region equals "USA", show "Dear Customer", otherwise "Dear Valued Customer"
var ifFieldPara = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    // Complex nested: { IF { MERGEFIELD Region } = "USA" "Dear American Customer" "Dear Customer" }
    new Run(new FieldCode(" IF ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),  // Nested MERGEFIELD begin
    new Run(new FieldCode(" MERGEFIELD Region ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("«Region»")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),     // Nested MERGEFIELD end
    new Run(new FieldCode(" = \"USA\" \"Dear American Customer\" \"Dear Customer\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Dear Customer")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// Note: Nested fields within IF are tricky with complex field syntax.
// A simpler approach: use two separate IF fields checking a bookmark value.
```

### 3.9 STYLEREF — Reference Heading Text

`STYLEREF` displays the text of the nearest paragraph with a specified style — useful for running headers.

```csharp
// STYLEREF Heading1 — inserts the text of the most recent Heading1 paragraph
// Great for running headers that show the current chapter

// Running header in footer
var footerPart = mainDocumentPart.AddNewPart<FooterPart>();
footerPart.Footer = new Footer(
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Right }
        ),
        // Left-aligned: chapter heading
        new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
        new Run(new FieldCode(" STYLEREF \"Heading 1\" ") { Space = SpaceProcessingModeValues.Preserve }),
        new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
        new Run(new Text("Chapter Title")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
        new Run(new Text("\t") { Space = SpaceProcessingModeValues.Preserve }),  // Tab
        // Right-aligned: page number
        new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
        new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }),
        new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
        new Run(new Text("1")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.End })
    )
);

// STYLEREF with \n switch to suppress paragraph numbering
new Run(new FieldCode(" STYLEREF \"Heading 1\" \\n ") { Space = SpaceProcessingModeValues.Preserve }),

// STYLEREF with \p switch to show relative position
new Run(new FieldCode(" STYLEREF \"Heading 2\" \\p ") { Space = SpaceProcessingModeValues.Preserve }),
```

### 3.10 SET and ASK Fields

`SET` stores a value in a variable. `ASK` prompts the user and stores their response.

```csharp
// SET — define a document variable (accessed via DOCPROPERTY or REF)
var setField = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" SET MyVariable \"some value\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// REF to read the variable
var refMyVar = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" REF MyVariable ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("some value")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// ASK — prompt user for input when field is updated
// Note: ASK displays a dialog box when updated
var askField = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" ASK AuthorName \"Enter author name:\" ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
    // REF to display the stored value
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" REF AuthorName ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("Author Name")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);
```

### 3.11 Calculated Fields (= Expressions)

The `=` field evaluates arithmetic expressions.

```csharp
// = field with arithmetic
var calcPara = new Paragraph(
    new Run(new Text("Total: $") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" = 100 + 250 - 30 ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("320")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// = with multiplication using SEQ references
var calcWithSeq = new Paragraph(
    new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
    new Run(new FieldCode(" = 3 * 5 ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }),
    new Run(new Text("15")),
    new Run(new FieldChar { FieldCharType = FieldCharValues.End })
);

// Combine with formatting
new Run(new FieldCode(" = 1000 * 1.08 \\# \"#,##0.00\" ") { Space = SpaceProcessingModeValues.Preserve }),
// \# switch applies number format to result
```

### 3.12 UpdateFieldsOnOpen — Automatic Field Updates

```csharp
// Settings that trigger field updates when document opens
var settingsPart = mainDocumentPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings(
    // Update all fields (TOC, REF, PAGE, etc.) on open
    new UpdateFieldsOnOpen { Val = true }
);
settingsPart.Settings.Save();

// Additional field-related settings:
var additionalSettings = new Settings(
    // Auto-format fractions: 1/2 → ½
    new AutomaticAdjustmentOfFontSizesToFitDocument(),

    // True: use field codes instead of cached values on update
    new UseXSLTWhenSaving(),

    // Mail merge settings
    new MailMerge(
        new MainDocumentType { Val = MailMergeDocumentValues.FormLetters }
    )
);
```

---

## 4. Track Changes / Revisions

### 4.1 Enabling Track Changes

Track changes must be explicitly enabled via DocumentSettingsPart.

```csharp
var settingsPart = mainDocumentPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings(
    // Enable track changes — any edit will be tracked
    new TrackRevisions()
);

// Also recommended: prevent fields from being updated during tracking
settingsPart.Settings.Append(new DonNotTrackFormatting());
```

### 4.2 InsertedRun (w:ins) — Tracked Insertion

```csharp
// <w:ins w:id="5" w:author="Alice" w:date="2026-03-22T10:00:00Z">
//   <w:r>
//     <w:t>Inserted text.</w:t>
//   </w:r>
// </w:ins>

var insertedText = new InsertedRun(
    new Run(
        new Text("Inserted text.") { Space = SpaceProcessingModeValues.Preserve }
    )
)
{
    Author = "Alice",
    Date = new DateTime(2026, 3, 22, 10, 0, 0, DateTimeKind.Utc),
    Id = "5"
};

var para = new Paragraph(
    new Run(new Text("Existing text. ") { Space = SpaceProcessingModeValues.Preserve }),
    insertedText,
    new Run(new Text(" More existing text.") { Space = SpaceProcessingModeValues.Preserve })
);
```

### 4.3 DeletedRun (w:del) — Tracked Deletion

**CRITICAL: Inside `w:del`, text MUST be `DeletedText` (`w:delText`), NOT `Text` (`w:t`)!**

```csharp
// <w:del w:id="6" w:author="Alice" w:date="2026-03-22T10:05:00Z">
//   <w:r>
//     <w:rPr><w:b/></w:rPr>
//     <w:delText>Deleted text.</w:delText>
//   </w:r>
// </w:del>

var deletedRun = new DeletedRun(
    new Run(
        new RunProperties(new Bold()),
        new DeletedText("Deleted text.") { Space = SpaceProcessingModeValues.Preserve }
    )
)
{
    Author = "Alice",
    Date = new DateTime(2026, 3, 22, 10, 5, 0, DateTimeKind.Utc),
    Id = "6"
};

var para = new Paragraph(
    new Run(new Text("Keep this. ") { Space = SpaceProcessingModeValues.Preserve }),
    deletedRun,
    new Run(new Text(" Keep this too.") { Space = SpaceProcessingModeValues.Preserve })
);

// GOTCHA: Never use <w:t> inside <w:del> — use <w:delText> only.
// Using w:t inside w:del causes corruption or silent repair by Word.
```

### 4.4 RunPropertiesChange — Formatting Change Tracking

Records that a run's formatting was changed. The `w:rPrChange` goes inside `w:rPr`.

```csharp
// <w:r>
//   <w:rPr>
//     <w:b/>  <!-- New: bold -->
//     <w:rPrChange w:id="7" w:author="Bob" w:date="2026-03-22T11:00:00Z">
//       <w:rPr/>  <!-- Old: no formatting -->
//     </w:rPrChange>
//   </w:rPr>
//   <w:t>Formatted text.</w:t>
// </w:r>

// The current (new) formatting is in the outer w:rPr
// The old (previous) formatting is in the w:rPrChange child
var formattedTextRun = new Run(
    new RunProperties(
        new Bold(),  // New formatting: now bold
        new RunPropertiesChange(  // Records the old formatting (empty = not bold)
            new RunProperties()  // Empty = previously had no formatting
        )
        {
            Author = "Bob",
            Date = new DateTime(2026, 3, 22, 11, 0, 0, DateTimeKind.Utc),
            Id = "7"
        }
    ),
    new Text("Formatted text.") { Space = SpaceProcessingModeValues.Preserve }
);
```

### 4.5 ParagraphPropertiesChange

Records that paragraph-level properties were changed.

```csharp
// <w:pPr>
//   <w:jc w:val="center"/>  <!-- New: centered -->
//   <w:pPrChange w:id="8" w:author="Bob" w:date="2026-03-22T11:05:00Z">
//     <w:pPr>
//       <w:jc w:val="left"/>  <!-- Old: left-aligned -->
//     </w:pPr>
//   </w:pPrChange>
// </w:pPr>

var changedPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },  // New
        new ParagraphPropertiesChange(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Left }  // Old
            )
        )
        {
            Author = "Bob",
            Date = new DateTime(2026, 3, 22, 11, 5, 0, DateTimeKind.Utc),
            Id = "8"
        }
    ),
    new Run(new Text("Centered paragraph."))
);
```

### 4.6 ParagraphMarkRunPropertiesChange

Records that the paragraph mark's formatting (trailing formatting) was changed.

```csharp
// <w:p>
//   <w:pPr>
//     <w:pPrChange .../>
//   </w:pPr>
//   <w:r>
//     <w:rPr>
//       <w:b/>  <!-- New paragraph mark: bold -->
//       <w:rPrChange w:id="9" ...>
//         <w:rPr/>  <!-- Old: no formatting on paragraph mark -->
//       </w:rPrChange>
//     </w:rPr>
//   </w:r>
// </w:r>
```

### 4.7 Table Revision Marks

```csharp
// TableRowInsertionRevision — a row was inserted
// <w:trPr>
//   <w:ins w:id="10" w:author="Alice" w:date="..."/>
// </w:trPr>

var insertedRow = new TableRow(
    new TableRowProperties(
        new TableRowInsertionRevision
        {
            Author = "Alice",
            Date = new DateTime(2026, 3, 22, 12, 0, 0, DateTimeKind.Utc),
            Id = "10"
        }
    ),
    new TableCell(new Paragraph(new Run(new Text("New row cell"))))
);

// TableCellInsertionRevision — a cell was inserted
var insertedCell = new TableCell(
    new TableCellProperties(
        new TableCellInsertionRevision
        {
            Author = "Alice",
            Date = new DateTime(2026, 3, 22, 12, 1, 0, DateTimeKind.Utc),
            Id = "11"
        }
    ),
    new Paragraph(new Run(new Text("New cell")))
);
```

### 4.8 SectionPropertiesChange

```csharp
// <w:sectPr>
//   <w:sectPrChange w:id="12" w:author="Bob" w:date="...">
//     <w:sectPr>
//       <w:pgSz w:w="12240" w:h="15840"/>  <!-- Old: Letter -->
//     </w:sectPr>
//   </w:sectPrChange>
//   <w:pgSz w:w="16838" w:h="11906"/>  <!-- New: A4 -->
// </w:sectPr>

var changedSection = new SectionProperties(
    new PageSize { Width = 16838U, Height = 11906U },  // New: A4
    new SectionPropertiesChange(
        new SectionProperties(
            new PageSize { Width = 12240U, Height = 15840U }  // Old: Letter
        )
    )
    {
        Author = "Bob",
        Date = new DateTime(2026, 3, 22, 12, 30, 0, DateTimeKind.Utc),
        Id = "12"
    }
);
```

### 4.9 NumberingChange

```csharp
// <w:numPr>
//   <w:ilvl w:val="0"/>
//   <w:numId w:val="3"/>
//   <w:numPrChange w:id="13" w:author="Alice" w:date="...">
//     <w:numPr>
//       <w:ilvl w:val="0"/>
//       <w:numId w:val="1"/>  <!-- Old: was numId 1 -->
//     </w:numPr>
//   </w:numPrChange>
// </w:numPr>

var changedNumbering = new NumberingProperties(
    new NumberingLevelReference { Val = 0 },
    new NumberingId { Val = 3 },  // New: numId 3
    new NumberingChange(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 1 }  // Old: numId 1
        )
    )
    {
        Author = "Alice",
        Date = new DateTime(2026, 3, 22, 13, 0, 0, DateTimeKind.Utc),
        Id = "13"
    }
);
```

### 4.10 Accepting All Revisions Programmatically

```csharp
// Accept all revisions: unwrap w:ins (keep content), remove w:del entirely
public static void AcceptAllRevisions(WordprocessingDocument doc)
{
    var body = doc.MainDocumentPart?.Document?.Body;
    if (body == null) return;

    // Accept insertions: remove w:ins wrapper, keep inner runs
    var insertions = body.Descendants<InsertedRun>().ToList();
    foreach (var ins in insertions)
    {
        var parent = ins.Parent;
        if (parent == null) continue;
        var children = ins.ChildElements.ToList();
        foreach (var child in children)
        {
            child.Remove();
            parent.InsertBefore(child, ins);
        }
        ins.Remove();
    }

    // Accept deletions: remove entire w:del element
    var deletions = body.Descendants<DeletedRun>().ToList();
    foreach (var del in deletions)
        del.Remove();
}

// Also accept formatting changes:
// For w:rPrChange: replace the entire RunProperties with the "old" properties inside the change
// For w:pPrChange: replace with the old properties
```

### 4.11 Rejecting All Revisions Programmatically

```csharp
// Reject all revisions: unwrap w:del (restore text), remove w:ins entirely
public static void RejectAllRevisions(WordprocessingDocument doc)
{
    var body = doc.MainDocumentPart?.Document?.Body;
    if (body == null) return;

    // Reject insertions: remove entire w:ins element and its content
    var insertions = body.Descendants<InsertedRun>().ToList();
    foreach (var ins in insertions)
        ins.Remove();

    // Reject deletions: unwrap w:del, convert w:delText back to w:t
    var deletions = body.Descendants<DeletedRun>().ToList();
    foreach (var del in deletions)
    {
        var parent = del.Parent;
        if (parent == null) continue;
        foreach (var run in del.Elements<Run>().ToList())
        {
            foreach (var delText in run.Elements<DeletedText>().ToList())
            {
                var text = new Text(delText.Text) { Space = delText.Space };
                delText.InsertAfterSelf(text);
                delText.Remove();
            }
            run.Remove();
            parent.InsertBefore(run, del);
        }
        del.Remove();
    }
}
```

### 4.12 MoveFrom / MoveTo — Tracked Text Moving

```csharp
// MoveFrom (w:moveFrom) marks the origin of moved text
// MoveTo (w:moveTo) marks the destination
// Both must have the same w:id

// <w:moveFrom w:id="14" w:author="Alice" w:date="...">
//   <w:r><w:t>Text that was moved.</w:t></w:r>
// </w:moveFrom>

// At destination:
// <w:moveTo w:id="14" w:author="Alice" w:date="...">
//   <w:r><w:t>Text that was moved.</w:t></w:r>
// </w:moveTo>

var movedFrom = new MoveFromRun(
    new Run(new Text("Text that was moved.") { Space = SpaceProcessingModeValues.Preserve })
)
{
    Author = "Alice",
    Date = new DateTime(2026, 3, 22, 14, 0, 0, DateTimeKind.Utc),
    Id = "14"
};

var movedTo = new MoveToRun(
    new Run(new Text("Text that was moved.") { Space = SpaceProcessingModeValues.Preserve })
)
{
    Author = "Alice",
    Date = new DateTime(2026, 3, 22, 14, 0, 0, DateTimeKind.Utc),
    Id = "14"
};
```

### 4.13 RevisionId Generation

All revision elements need unique, monotonically increasing integer IDs.

```csharp
public static int GetNextRevisionId(Body body)
{
    int maxId = 0;
    foreach (var elem in body.Descendants<OpenXmlElement>())
    {
        // Check common revision element types for Id attribute
        var idAttr = elem.GetAttributes()
            .FirstOrDefault(a => a.LocalName == "id" &&
                (elem is InsertedRun or DeletedRun or DeletedText or
                 MoveFromRun or MoveToRun or RunPropertiesChange or
                 ParagraphPropertiesChange or SectionPropertiesChange or
                 TableRowInsertionRevision or TableCellInsertionRevision));
        if (idAttr.Value != null && int.TryParse(idAttr.Value, out int id) && id > maxId)
            maxId = id;
    }
    return maxId + 1;
}

// Simpler approach: scan all elements with "id" attribute in the document
public static int GetNextRevisionIdSimple(Body body)
{
    int maxId = 0;
    foreach (var elem in body.Descendants<OpenXmlElement>())
    {
        foreach (var attr in elem.GetAttributes())
        {
            if (attr.LocalName == "id" && int.TryParse(attr.Value, out int id) && id > maxId)
                maxId = id;
        }
    }
    return maxId + 1;
}
```

---

## 5. Comments (4-File System)

### 5.1 Full 4-File Comment System Setup

Comments require four XML files plus markers in `document.xml`.

```csharp
// This method creates a complete comment with all 4 files properly initialized
public static int AddFullComment(
    WordprocessingDocument doc,
    string text,
    string author,
    string initials,
    string rangeText,
    int? existingCommentId = null)
{
    var mainPart = doc.MainDocumentPart
        ?? throw new InvalidOperationException("Document has no MainDocumentPart.");

    int commentId = existingCommentId ?? GetNextCommentId(doc);

    // Generate paraId (8-char hex) and durableId (8-digit hex)
    string paraId = Guid.NewGuid().ToString("N")[..8].ToUpperInvariant();
    string durableId = new Random().Next(0x10000000, 0xFFFFFFFF).ToString("X8");

    var body = mainPart.Document!.Body!;

    // ─────────────────────────────────────────────────────────────
    // FILE 1: word/comments.xml — Main comment content
    // ─────────────────────────────────────────────────────────────
    var commentsPart = mainPart.WordprocessingCommentsPart
        ?? mainPart.AddNewPart<WordprocessingCommentsPart>();

    if (commentsPart.Comments == null)
        commentsPart.Comments = new Comments();

    // Create a paragraph for the comment with a unique paraId (via w14:paraId)
    var commentPara = new Paragraph(
        new ParagraphProperties(
            new ParagraphStyleId { Val = "CommentText" },
            // w14:paraId for modern comment threading
            new乳啜攠嘶嘐呓顾纨asiId { Val = paraId }
        ),
        new Run(
            new RunProperties(new RunStyle { Val = "CommentReference" }),
            new AnnotationReferenceMark()
        ),
        new Run(new Text(text))
    );

    var comment = new Comment
    {
        Id = commentId.ToString(),
        Author = author,
        Date = DateTime.UtcNow,
        Initials = initials
    };
    comment.Append(commentPara);
    commentsPart.Comments.Append(comment);
    commentsPart.Comments.Save();

    // ─────────────────────────────────────────────────────────────
    // FILE 2: word/commentsExtended.xml — W15 extensions (paraId, done status)
    // ─────────────────────────────────────────────────────────────
    var commentsExPart = mainPart.WordprocessingCommentsExPart
        ?? mainPart.AddNewPart<WordprocessingCommentsExPart>();

    if (commentsExPart.CommentsEx == null)
        commentsExPart.CommentsEx = new CommentExCollection();

    // w15:commentEx links the comment to its paragraph and tracks done/resolved
    var commentEx = new CommentEx
    {
        ParaId = new HexBinaryValue(paraId),
        Done = new OnOffValue(false)  // done="0" = not resolved
    };
    commentsExPart.CommentsEx.Append(commentEx);
    commentsExPart.CommentsEx.Save();

    // ─────────────────────────────────────────────────────────────
    // FILE 3: word/commentsIds.xml — Persistent ID mapping
    // ─────────────────────────────────────────────────────────────
    var commentsIdsPart = mainPart.WordprocessingCommentsIdsPart
        ?? mainPart.AddNewPart<WordprocessingCommentsIdsPart>();

    if (commentsIdsPart.CommentsIds == null)
        commentsIdsPart.CommentsIds = new CommentIds();

    // w16cid:commentId maps paraId to a durable (globally unique) ID
    var commentIdEntry = new CommentId
    {
        ParaId = new HexBinaryValue(paraId),
        DurableId = durableId
    };
    commentsIdsPart.CommentsIds.Append(commentIdEntry);
    commentsIdsPart.CommentsIds.Save();

    // ─────────────────────────────────────────────────────────────
    // FILE 4: word/commentsExtensible.xml — W16 extensible
    // ─────────────────────────────────────────────────────────────
    var commentsExtPart = mainPart.WordprocessingCommentsExtensiblePart
        ?? mainPart.AddNewPart<WordprocessingCommentsExtensiblePart>();

    if (commentsExtPart.CommentsExtensible == null)
        commentsExtPart.CommentsExtensible = new CommentExtensibleCollection();

    // w16cex:commentExtensible provides the durable ID with UTC timestamp
    var extensibleEntry = new CommentExtensible
    {
        DurableId = durableId,
        DateUtc = DateTime.UtcNow
    };
    commentsExtPart.CommentsExtensible.Append(extensibleEntry);
    commentsExtPart.CommentsExtensible.Save();

    // ─────────────────────────────────────────────────────────────
    // document.xml — Insert range markers around the target text
    // ─────────────────────────────────────────────────────────────
    // commentRangeStart and commentRangeEnd bracket the commented text
    // commentReference is a run containing the visible superscript number
    var rangeStart = new CommentRangeStart { Id = commentId.ToString() };
    var rangeEnd = new CommentRangeEnd { Id = commentId.ToString() };
    var refRun = new Run(
        new RunProperties(new RunStyle { Val = "CommentReference" }),
        new CommentReference { Id = commentId.ToString() }
    );

    // Find the paragraph containing rangeText and insert markers
    // Simple approach: append at end of body
    body.Append(rangeStart);
    body.Append(new Paragraph(new Run(new Text(rangeText))));
    body.Append(rangeEnd);
    body.Append(new Paragraph(refRun));  // The comment ref must be in its own paragraph

    return commentId;
}

// Helper: get next comment ID
private static int GetNextCommentId(WordprocessingDocument doc)
{
    var commentsPart = doc.MainDocumentPart?.WordprocessingCommentsPart;
    if (commentsPart?.Comments == null) return 1;
    int max = 0;
    foreach (var c in commentsPart.Comments.Elements<Comment>())
        if (c.Id?.Value != null && int.TryParse(c.Id.Value, out int id) && id > max)
            max = id;
    return max + 1;
}
```

**The 4 files at a glance:**

| File | Part Class | Content | Key Attributes |
|------|-----------|---------|----------------|
| `comments.xml` | `WordprocessingCommentsPart` | Comment text | `w:id`, `w:author`, `w:date`, `w:initials` |
| `commentsExtended.xml` | `WordprocessingCommentsExPart` | W15 extensions | `w15:paraId`, `w15:done` |
| `commentsIds.xml` | `WordprocessingCommentsIdsPart` | Persistent IDs | `w16cid:paraId`, `w16cid:durableId` |
| `commentsExtensible.xml` | `WordprocessingCommentsExtensiblePart` | W16 extensible | `w16cex:durableId`, `w16cex:dateUtc` |

### 5.2 Comment Reply (Threaded Comments)

```csharp
// To add a reply, create a new comment and link it to the parent via commentsExtended.xml

public static int AddCommentReply(
    WordprocessingDocument doc,
    int parentCommentId,
    string replyText,
    string author,
    string initials)
{
    var mainPart = doc.MainDocumentPart!;

    // Get parent's paraId from commentsExtended.xml
    var commentsExPart = mainPart.WordprocessingCommentsExPart;
    var parentParaId = "";
    if (commentsExPart?.CommentsEx != null)
    {
        var parentCommentEx = commentsExPart.CommentsEx
            .Elements<CommentEx>()
            .FirstOrDefault(ce =>
                ce.Parent is Comment c &&
                c.Id?.Value == parentCommentId.ToString());
        // Actually need to cross-reference through paraId...
        // Simpler: look up via comments.xml paraId
    }

    // Generate new IDs for the reply
    int replyId = GetNextCommentId(doc);
    string replyParaId = Guid.NewGuid().ToString("N")[..8].ToUpperInvariant();
    string durableId = new Random().Next(0x10000000, 0xFFFFFFFF).ToString("X8");

    // Add to comments.xml (new comment with same structure)
    var commentsPart = mainPart.WordprocessingCommentsPart!;
    var replyComment = new Comment
    {
        Id = replyId.ToString(),
        Author = author,
        Date = DateTime.UtcNow,
        Initials = initials
    };
    replyComment.Append(new Paragraph(
        new ParagraphProperties(new ParagraphStyleId { Val = "CommentText" }),
        new Run(new RunProperties(new RunStyle { Val = "CommentReference" }), new AnnotationReferenceMark()),
        new Run(new Text(replyText))
    ));
    commentsPart.Comments!.Append(replyComment);
    commentsPart.Comments.Save();

    // KEY: In commentsExtended.xml, use paraIdParent to link to parent
    var commentsEx = mainPart.WordprocessingCommentsExPart!;
    var replyEx = new CommentEx
    {
        ParaId = new HexBinaryValue(replyParaId),
        ParaIdParent = new HexBinaryValue(parentParaId),  // Link to parent
        Done = new OnOffValue(false)
    };
    commentsEx.CommentsEx!.Append(replyEx);
    commentsEx.CommentsEx.Save();

    // Add to commentsIds.xml and commentsExtensible.xml (same pattern as parent)
    // ... (same as AddFullComment for these two files)

    // Note: Replies do NOT need range markers in document.xml
    // They appear threaded under the parent in Word's UI

    return replyId;
}
```

### 5.3 Resolving a Comment

```csharp
// To resolve (mark done), set w15:done="1" in commentsExtended.xml
public static void ResolveComment(WordprocessingDocument doc, int commentId)
{
    var mainPart = doc.MainDocumentPart!;

    // Need to find the paraId for this commentId, then update commentsExtended.xml
    // Step 1: Get paraId from comments.xml
    var commentsPart = mainPart.WordprocessingCommentsPart!;
    var comment = commentsPart.Comments!
        .Elements<Comment>()
        .FirstOrDefault(c => c.Id?.Value == commentId.ToString());

    // Find the paragraph and get its paraId
    string? paraId = null;
    if (comment != null)
    {
        var para = comment.Elements<Paragraph>().FirstOrDefault();
        var paraIdElem = para?.ParagraphProperties?
            .Elements<乳啜攠嘶嘐呓顾纨asiId>().FirstOrDefault();
        paraId = paraIdElem?.Val?.Value;
    }

    if (paraId == null) return;

    // Step 2: Update commentsExtended.xml
    var commentsExPart = mainPart.WordprocessingCommentsExPart!;
    var commentEx = commentsExPart.CommentsEx!
        .Elements<CommentEx>()
        .FirstOrDefault(ce => ce.ParaId?.Value == paraId);

    if (commentEx != null)
        commentEx.Done = new OnOffValue(true);  // Sets done="1"

    commentsExPart.CommentsEx!.Save();
}
```

### 5.4 Deleting a Comment (All 4 Files)

```csharp
// Must remove from all 4 files AND from document.xml
public static void DeleteComment(WordprocessingDocument doc, int commentId)
{
    var mainPart = doc.MainDocumentPart!;
    string commentIdStr = commentId.ToString();

    // ── Remove from comments.xml ──
    var commentsPart = mainPart.WordprocessingCommentsPart;
    if (commentsPart?.Comments != null)
    {
        var comment = commentsPart.Comments
            .Elements<Comment>()
            .FirstOrDefault(c => c.Id?.Value == commentIdStr);
        if (comment != null)
        {
            // Get paraId before deletion for other files
            string? paraId = null;
            var para = comment.Elements<Paragraph>().FirstOrDefault();
            var paraIdElem = para?.ParagraphProperties?
                .Elements<乳啜攠嘶嘐呓顾纨asiId>().FirstOrDefault();
            paraId = paraIdElem?.Val?.Value;

            comment.Remove();

            // ── Remove from commentsExtended.xml ──
            var commentsExPart = mainPart.WordprocessingCommentsExPart;
            if (commentsExPart?.CommentsEx != null && paraId != null)
            {
                var commentEx = commentsExPart.CommentsEx
                    .Elements<CommentEx>()
                    .FirstOrDefault(ce => ce.ParaId?.Value == paraId);
                commentEx?.Remove();
                commentsExPart.CommentsEx.Save();
            }

            // ── Remove from commentsIds.xml ──
            var commentsIdsPart = mainPart.WordprocessingCommentsIdsPart;
            if (commentsIdsPart?.CommentsIds != null && paraId != null)
            {
                var cidEntry = commentsIdsPart.CommentsIds
                    .Elements<CommentId>()
                    .FirstOrDefault(ci => ci.ParaId?.Value == paraId);
                cidEntry?.Remove();
                commentsIdsPart.CommentsIds.Save();
            }

            // ── Remove from commentsExtensible.xml ──
            // Need to look up by durableId...
            var commentsExtPart = mainPart.WordprocessingCommentsExtensiblePart;
            if (commentsExtPart?.CommentsExtensible != null)
            {
                // Find by matching durableId (must track separately)
                var extEntry = commentsExtPart.CommentsExtensible
                    .Elements<CommentExtensible>()
                    .FirstOrDefault();  // Match by durableId lookup
                extEntry?.Remove();
                commentsExtPart.CommentsExtensible.Save();
            }
        }
    }

    // ── Remove from document.xml ──
    var body = mainPart.Document!.Body!;

    // Remove CommentRangeStart
    var rangeStart = body.Descendants<CommentRangeStart>()
        .FirstOrDefault(crs => crs.Id?.Value == commentIdStr);
    rangeStart?.Remove();

    // Remove CommentRangeEnd
    var rangeEnd = body.Descendants<CommentRangeEnd>()
        .FirstOrDefault(cre => cre.Id?.Value == commentIdStr);
    rangeEnd?.Remove();

    // Remove CommentReference run (the superscript marker)
    var commentRefs = body.Descendants<CommentReference>()
        .Where(cr => cr.Id?.Value == commentIdStr)
        .ToList();
    foreach (var cr in commentRefs)
    {
        var run = cr.Parent as Run;
        cr.Remove();
        run?.Remove();
    }

    commentsPart?.Comments?.Save();
}
```

---

## 6. Images — Deep Dive

### 6.1 Adding an ImagePart (All Image Types)

```csharp
// All image types supported by AddImagePart:
void AddImageExamples(MainDocumentPart mainPart, string pngPath, string jpegPath,
    string gifPath, string svgPath, string bmpPath, string tiffPath)
{
    // PNG
    var pngPart = mainPart.AddImagePart(ImagePartType.Png);
    using (var s = File.OpenRead(pngPath)) pngPart.FeedData(s);
    string pngRelId = mainPart.GetIdOfPart(pngPart);

    // JPEG
    var jpegPart = mainPart.AddImagePart(ImagePartType.Jpeg);
    using (var s = File.OpenRead(jpegPath)) jpegPart.FeedData(s);
    string jpegRelId = mainPart.GetIdOfPart(jpegPart);

    // GIF
    var gifPart = mainPart.AddImagePart(ImagePartType.Gif);
    using (var s = File.OpenRead(gifPath)) gifPart.FeedData(s);
    string gifRelId = mainPart.GetIdOfPart(gifPart);

    // SVG (may require additional handling for fallback)
    var svgPart = mainPart.AddImagePart(ImagePartType.Svg);
    using (var s = File.OpenRead(svgPath)) svgPart.FeedData(s);
    string svgRelId = mainPart.GetIdOfPart(svgPart);

    // BMP (stored internally as PNG in OOXML)
    var bmpPart = mainPart.AddImagePart(ImagePartType.Bmp);
    using (var s = File.OpenRead(bmpPath)) bmpPart.FeedData(s);
    string bmpRelId = mainPart.GetIdOfPart(bmpPart);

    // TIFF (similarly converted)
    var tiffPart = mainPart.AddImagePart(ImagePartType.Tiff);
    using (var s = File.OpenRead(tiffPath)) tiffPart.FeedData(s);
    string tiffRelId = mainPart.GetIdOfPart(tiffPart);

    // Also available: ImagePartType.Icon, ImagePartType.Emf, ImagePartType.Wmf
}
```

### 6.2 Inline Image (DW.Inline)

Inline images are anchored to a specific character position, not floating.

```csharp
// Dimensions: widthPx * 9525 EMU = EMU width, heightPx * 9525 EMU = EMU height
// Assuming 600x400 pixel image at 96dpi:
//   cx = 600 * 9525 = 5715000 EMU
//   cy = 400 * 9525 = 3810000 EMU

long cx = (long)(widthInches * 914400);    // From inches to EMU
long cy = (long)(heightInches * 914400);   // From inches to EMU

// Or from pixels at 96dpi:
long cxPx = 600, cyPx = 400;
long cx = cxPx * 9525L;  // 5715000 EMU
long cy = cyPx * 9525L;  // 3810000 EMU

// Drawing → DW.Inline → A.Graphic → A.GraphicData → PIC.Picture
var drawing = new Drawing(
    new DW.Inline(
        // Extent: defines the image's display size in EMU
        new DW.Extent { Cx = cx, Cy = cy },
        // EffectExtent: needed for some effects (set to 0 for basic images)
        new DW.EffectExtent { EffectExtentL = 0, EffectExtentT = 0, EffectExtentR = 0, EffectExtentB = 0 },
        // DocProperties: metadata for the image (Id must be unique in document)
        new DW.DocProperties { Id = 1U, Name = "Image_1", Description = "A sample image" },
        // NonVisualGraphicFrameDrawingProperties: locks and frame settings
        new DW.NonVisualGraphicFrameDrawingProperties(
            new A.GraphicFrameLocks { NoChangeAspect = true }
        ),
        // The actual image
        new A.Graphic(
            new A.GraphicData(
                new PIC.Picture(
                    // Non-visual properties
                    new PIC.NonVisualPictureProperties(
                        new PIC.NonVisualDrawingProperties { Id = 0U, Name = "image1" },
                        new PIC.NonVisualPictureDrawingProperties()
                    ),
                    // Fill: how the image is stretched to fill its frame
                    new PIC.BlipFill(
                        // Blip: the actual image data reference
                        new A.Blip { Embed = relId, CompressionState = A.BlipCompressionValues.Print },
                        // Stretch: how to fill if aspect ratio doesn't match
                        new A.Stretch(new A.FillRectangle())
                    ),
                    // ShapeProperties: transform and geometry
                    new PIC.ShapeProperties(
                        new A.Transform2D(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = cx, Cy = cy }
                        ),
                        new A.PresetGeometry(new A.AdjustValueList())
                        { Preset = A.ShapeTypeValues.Rectangle }
                    )
                )
            ) { Uri = "http://schemas.openxmlformats.org/drawingml/2006/picture" }
        )
    )
    {
        DistanceFromTop = 0U,
        DistanceFromBottom = 0U,
        DistanceFromLeft = 0U,
        DistanceFromRight = 0U
    }
);

// Append to a paragraph
var para = new Paragraph(new Run(drawing));
body.Append(para);
```

### 6.3 Floating / Anchored Image (DW.Anchor)

Floating images have text wrapping and can be positioned relative to page, margin, column, or paragraph.

```csharp
// DW.Anchor — positioned floating image with text wrapping
// Key differences from Inline:
//   - DW.Anchor instead of DW.Inline
//   - DW.PositionH / DW.PositionV for positioning
//   - wrapping element (WrapSquare, WrapTight, etc.)
//   - can have extent on the anchor (effect extent)

var floatingDrawing = new Drawing(
    new DW.Anchor(
        // Horizontal positioning
        new DW.SimplePosition { X = 0L, Y = 0L },  // Offset from anchor point
        new DW.HorizontalPosition(
            new DW.PositionOffset((914400L * 2).ToString())  // 2 inches from left
        )
        { RelativeFrom = DW.HorizontalRelativePositionValues.Page },
        // Vertical positioning
        new DW.VerticalPosition(
            new DW.PositionOffset((914400L * 3).ToString())  // 3 inches from top
        )
        { RelativeFrom = DW.VerticalRelativePositionValues.Page },

        // Image extent (size)
        new DW.Extent { Cx = cx, Cy = cy },
        new DW.EffectExtent { EffectExtentL = 0, EffectExtentT = 0, EffectExtentR = 0, EffectExtentB = 0 },

        new DW.DocProperties { Id = 2U, Name = "Floating_Image" },
        new DW.NonVisualGraphicFrameDrawingProperties(
            new A.GraphicFrameLocks { NoChangeAspect = true }
        ),

        // Text wrapping — several options:
        // WrapSquare: text wraps on all sides (default)
        // WrapTight: text wraps close to image shape
        // WrapThrough: text wraps through the image
        // WrapTopAndBottom: image on its own line, text above and below
        // WrapNone: image behind/in front of text
        new DW.WrapSquare { WrapText = DW.WrapTextValues.RightMargin },

        // Layout in table cell (if applicable)
        new DW.DocPart Gallery { Val = DW.DocPartGalleryValues.Default },

        // Change paragraph that the image is anchored to
        // Allow the image to move with the paragraph
        new DW.EditingIndependentFromParagraph { Val = false },

        // Horizontal anchor: anchor to character/column/margin/page
        new DW.HorizontalAnchor { Val = DW.HorizontalAnchorValues.Page },
        // Vertical anchor: anchor to character/line/margin/page/paragraph
        new DW.VerticalAnchor { Val = DW.VerticalAnchorValues.Page },

        // Alignment (if using alignment-based positioning)
        new DW.Aligned { Horizontal = DW.HorizontalAlignmentValues.Left,
                         Vertical = DW.VerticalAlignmentValues.Top },

        new A.Graphic(...)
    )
    {
        // Anchor lock: prevents moving in Word UI
        EditId = "1A2B3C",
        BehindDoc = false,  // true = behind text, false = in front
        Locked = false,
        LayoutInCell = true,  // Allow layout inside table cells
        AllowOverlap = true   // Allow overlap with other floating elements
    }
);
```

### 6.4 Text Wrapping Options

```csharp
// WrapSquare — text surrounds on all sides
new DW.WrapSquare { WrapText = DW.WrapTextValues.RightMargin }

// WrapTight — text follows contour of image (if shape has custom geometry)
new DW.WrapTight { WrapText = DW.WrapTextValues.LeftMargin }

// WrapThrough — text intermingles with image
new DW.WrapThrough(
    new DW.WrapTextValues.LeftMargin,  // Text on left
    new DW.WrapTextValues.RightMargin   // Text on right
)

// WrapTopAndBottom — image on own line
new DW.WrapTopAndBottom()

// WrapNone — image is at anchor position, text overlays (or vice versa)
new DW.WrapNone()

// Behind document text:
var anchor = new DW.Anchor(...){ BehindDoc = true, Locked = false };
```

### 6.5 Image Sizing — EMU Calculations

```csharp
// EMU reference:
//   1 inch = 914400 EMU
//   1 cm   = 360000 EMU
//   1 pixel at 96dpi = 9525 EMU
//   1 pixel at 72dpi = 635 EMU (point, not EMU)

public static class ImageSizing
{
    // From pixel dimensions at given DPI
    public static (long cx, long cy) FromPixels(int widthPx, int heightPx, int dpi = 96)
    {
        long emuPerPixel = 914400L / dpi;  // ~9525 at 96dpi
        return (widthPx * emuPerPixel, heightPx * emuPerPixel);
    }

    // From inches
    public static (long cx, long cy) FromInches(double widthIn, double heightIn)
    {
        return ((long)(widthIn * 914400), (long)(heightIn * 914400));
    }

    // From centimeters
    public static (long cx, long cy) FromCentimeters(double widthCm, double heightCm)
    {
        return ((long)(widthCm * 360000), (long)(heightCm * 360000));
    }

    // Maintain aspect ratio given a target width
    public static (long cx, long cy) ScaleToWidth(long originalCx, long originalCy, long targetCx)
    {
        double ratio = (double)originalCy / originalCx;
        return (targetCx, (long)(targetCx * ratio));
    }

    // Common photo sizes in inches: 4x6, 5x7, 8x10
    public static (long cx, long cy) PhotoSize4x6()
        => FromInches(4, 6);

    public static (long cx, long cy) PhotoSize5x7()
        => FromInches(5, 7);

    public static (long cx, long cy) PhotoSize8x10()
        => FromInches(8, 10);
}
```

### 6.6 Image with Border

```csharp
// Add border to image via PIC.ShapeProperties → A.Outline
new PIC.ShapeProperties(
    new A.Transform2D(
        new A.Offset { X = 0L, Y = 0L },
        new A.Extents { Cx = cx, Cy = cy }
    ),
    new A.PresetGeometry(new A.AdjustValueList())
    { Preset = A.ShapeTypeValues.Rectangle },
    // The border/outline
    new A.Outline(
        new A.SolidFill(new A.RgbColorModelHex { Val = "000000" }),
        new A.PresetDash { Val = A.PresetLineDashValues.Solid }
    )
    { Width = 12700 }  // 12700 EMU = 1pt, so 25400 = 2pt
);
```

### 6.7 Image with Alt Text (DocProperties.Description)

```csharp
// Alt text is set via DocProperties.Description
// Also accessible via Picture's alternative text in Word UI

new DW.DocProperties
{
    Id = 1U,
    Name = "Chart showing growth",
    Description = "Bar chart showing quarterly revenue growth from Q1 to Q4 2025"
    // Title is also available but Description is what Word shows as alt text
};

// Also set via A.Descriptive (for some image types)
```

### 6.8 Image in Header / Footer

```csharp
// Images in headers/footers work the same as in body, just on the respective part
var headerPart = mainPart.AddNewPart<HeaderPart>();

// Logo in header
var logoDrawing = new Drawing(
    new DW.Inline(
        new DW.Extent { Cx = 914400L, Cy = 457200L },  // 1" x 0.5" logo
        new DW.EffectExtent(),
        new DW.DocProperties { Id = 1U, Name = "HeaderLogo" },
        new DW.NonVisualGraphicFrameDrawingProperties(
            new A.GraphicFrameLocks { NoChangeAspect = true }),
        new A.Graphic(
            new A.GraphicData(
                new PIC.Picture(
                    new PIC.NonVisualPictureProperties(
                        new PIC.NonVisualDrawingProperties { Id = 0U, Name = "logo" },
                        new PIC.NonVisualPictureDrawingProperties()),
                    new PIC.BlipFill(
                        new A.Blip { Embed = headerLogoRelId },
                        new A.Stretch(new A.FillRectangle())),
                    new PIC.ShapeProperties(
                        new A.Transform2D(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = 914400L, Cy = 457200L }),
                        new A.PresetGeometry(new A.AdjustValueList())
                        { Preset = A.ShapeTypeValues.Rectangle }))
                )
            ) { Uri = "http://schemas.openxmlformats.org/drawingml/2006/picture" }
        )
    )
    { DistanceFromTop = 0U, DistanceFromBottom = 0U,
      DistanceFromLeft = 0U, DistanceFromRight = 0U }
);

headerPart.Header = new Header(
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Right }),
        new Run(logoDrawing)
    )
);
```

### 6.9 Image in Table Cell

```csharp
// Images in table cells use the same patterns
// With inline: works fine within cell
// With floating/anchor: set LayoutInCell = true

var cellWithImage = new TableCell(
    new TableCellProperties(
        new TableCellWidth { Width = 2000, Type = TableWidthUnitValues.Dxa }
    ),
    new Paragraph(
        new Run(
            new Drawing(
                new DW.Inline(
                    new DW.Extent { Cx = 914400L, Cy = 914400L },  // 1"x1"
                    new DW.EffectExtent(),
                    new DW.DocProperties { Id = 5U, Name = "CellImage" },
                    new DW.NonVisualGraphicFrameDrawingProperties(
                        new A.GraphicFrameLocks { NoChangeAspect = true }),
                    new A.Graphic(
                        new A.GraphicData(
                            new PIC.Picture(...)
                        ) { Uri = "..." }
                    )
                )
                { DistanceFromTop = 0U, DistanceFromBottom = 0U,
                  DistanceFromLeft = 0U, DistanceFromRight = 0U }
            )
        )
    )
);
```

### 6.10 Replacing an Image (Update Blip.Embed)

```csharp
// To replace an existing image, update the Blip's Embed relationship ID
// 1. Get the existing image's relationship ID from Blip.Embed
// 2. Replace the image data in that ImagePart with new data
// 3. Keep the same relationship ID (so all references remain valid)

public static void ReplaceImage(WordprocessingDocument doc, string newImagePath)
{
    var mainPart = doc.MainDocumentPart!;
    var body = mainPart.Document!.Body!;

    foreach (var drawing in body.Descendants<Drawing>())
    {
        // Look for inline or anchor images
        var inline = drawing.Descendants<DW.Inline>().FirstOrDefault();
        var anchor = drawing.Descendants<DW.Anchor>().FirstOrDefault();

        var blipFill = (inline ?? anchor as OpenXmlElement)?
            .Descendants<PIC.BlipFill>().FirstOrDefault();

        if (blipFill == null) continue;

        var blip = blipFill.Blip;
        if (blip?.Embed == null) continue;

        string relId = blip.Embed.Value!;

        // Get the existing ImagePart
        if (mainPart.GetPartById(relId) is ImagePart existingImagePart)
        {
            // Replace the data
            using (var newData = File.OpenRead(newImagePath))
                existingImagePart.FeedData(newData);
            return;  // Replace first found, or loop for all
        }
    }
}
```

### 6.11 SVG with PNG Fallback (SvgBlip)

```csharp
// SVG images use SvgBlip for modern Word apps, with PNG fallback for older versions
// This is handled through the package structure — Word picks the best supported format

// SVG stored as ImagePartType.Svg, but rendered via BlipFill with extension:
// <a:blip xmlns:a="..." r:embed="rId...">
//   <a:extLst>
//     <a:ext uri="http://schemas.openxmlformats.org/drawingml/2006/svg">
//       <asvg:svg xmlns:asvg="..."/>  <!-- SVG-specific data -->
//     </a:ext>
//   </a:extLst>
// </a:blip>

var svgImagePart = mainPart.AddImagePart(ImagePartType.Svg);
using (var s = File.OpenRead("chart.svg")) svgImagePart.FeedData(s);
string svgRelId = mainPart.GetIdOfPart(svgImagePart);

// Word automatically handles SVG→PNG fallback in older versions
// No explicit fallback needed in code — the document format handles it

// Note: SvgBlip class in SDK 3.x provides direct support
new A.SvgBlip { Embed = svgRelId };
```

---

## 7. Drawing Shapes (Non-Image)

### 7.1 WordprocessingShape — Basic Shapes (wsp)

WordprocessingShape uses the `wps` namespace for Word's built-in shape library.

```csharp
// Shapes require:
// - MainDocumentPart.AddNewPart<WordprocessingShapePart>() or
// - Embedded via DrawingML inside a Drawing element
// The most common approach is embedding shapes directly in a Drawing element

// Shapes in WordprocessingDrawing are placed like images (inline or anchored)
var shapeDrawing = new Drawing(
    new DW.Inline(
        new DW.Extent { Cx = 1714500L, Cy = 914400L },  // 1.875" x 1" rectangle
        new DW.EffectExtent(),
        new DW.DocProperties { Id = 10U, Name = "Rectangle 1" },
        new DW.NonVisualGraphicFrameDrawingProperties(
            new A.GraphicFrameLocks()),
        // The shape itself
        new A.Graphic(
            new A.GraphicData(
                // WordprocessingShape = wsp:wsp (rectangle, roundedRect, ellipse, etc.)
                new WSP.WordprocessingShape(
                    // Non-visual properties
                    new WSP.NonVisualDrawingShapeProperties(
                        new A.ShapeLocks { NoChangeAspect = true }
                    ),
                    // Shape properties (fill, outline, geometry)
                    new WSP.ShapeProperties(
                        new A.Transform2D(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = 1714500L, Cy = 914400L }
                        ),
                        // PresetGeometry determines the shape type
                        new A.PresetGeometry(new A.AdjustValueList())
                        {
                            Preset = A.ShapeTypeValues.Rectangle
                            // Other values: RoundedRectangle, Ellipse, Triangle, etc.
                        },
                        // Fill color (solid)
                        new A.SolidFill(
                            new A.RgbColorModelHex { Val = "4472C4" }
                        ),
                        // Outline
                        new A.Outline(
                            new A.NoFill()  // No outline
                            // Or: new A.SolidFill(new A.RgbColorModelHex { Val = "000000" })
                            // { Width = 12700 } for 1pt border
                        )
                    ),
                    // Text box content
                    new WSP.TextBoxInfo2(
                        new TextBoxContent(
                            new Paragraph(
                                new ParagraphProperties(
                                    new Justification { Val = JustificationValues.Center }),
                                new Run(
                                    new RunProperties(
                                        new Color { Val = "FFFFFF" },
                                        new Bold()),
                                    new Text("Hello World"))
                            )
                        )
                    )
                )
            ) { Uri = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape" }
        )
    )
    { DistanceFromTop = 0U, DistanceFromBottom = 0U,
      DistanceFromLeft = 0U, DistanceFromRight = 0U }
);
```

**Preset shape types (`A.ShapeTypeValues`):**
- `Rectangle`, `RoundedRectangle`, `Ellipse`, `Triangle`, `RightTriangle`
- `Parallelogram`, `Trapezoid`, `Pentagon`, `Hexagon`, `Octagon`
- `Star4`, `Star5`, `Star6`, `Star8`, `Star10`, `Star12`
- `Heart`, `ArrowRight`, `ArrowLeft`, `ArrowUp`, `ArrowDown`
- `Callout1`, `Callout2`, `Callout3` (with tail)
- `FlowChartProcess`, `FlowChartDecision`, `FlowChartDocument`

### 7.2 Shape with Gradient Fill

```csharp
new WSP.ShapeProperties(
    new A.Transform2D(...),
    new A.PresetGeometry(new A.AdjustValueList())
    { Preset = A.ShapeTypeValues.RoundedRectangle },
    // Gradient fill
    new A.GradientFill(
        new A.LinearGradientFill(
            new A.Stop { Offset = "0", Color = new A.RgbColorModelHex { Val = "4472C4" } },
            new A.Stop { Offset = "100000", Color = new A.RgbColorModelHex { Val = "2F5496" } }
        )
        { Rotation = 5400000 }  // 54° = diagonal
    )
    // OR: A.RadialGradientFill for radial gradient
);
```

### 7.3 Shape Positioning (Anchored)

```csharp
// Anchored (floating) shapes use DW.Anchor with the shape inside
var anchoredShape = new Drawing(
    new DW.Anchor(
        new DW.SimplePosition { X = 0L, Y = 0L },
        new DW.HorizontalPosition(
            new DW.PositionOffset((914400L * 1).ToString()))  // 1 inch from left
        { RelativeFrom = DW.HorizontalRelativePositionValues.Margin },
        new DW.VerticalPosition(
            new DW.PositionOffset((914400L * 2).ToString()))  // 2 inches from top
        { RelativeFrom = DW.VerticalRelativePositionValues.Page },
        new DW.Extent { Cx = 914400L, Cy = 914400L },
        new DW.EffectExtent(),
        new DW.DocProperties { Id = 11U, Name = "AnchoredShape" },
        new DW.NonVisualGraphicFrameDrawingProperties(new A.GraphicFrameLocks()),
        new DW.WrapSquare(),
        new A.Graphic(new A.GraphicData(
            new WSP.WordprocessingShape(...)
        ) { Uri = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape" })
    )
    { BehindDoc = false, LayoutInCell = true }
);
```

### 7.4 Grouped Shapes (GroupShape)

```csharp
// GroupShape combines multiple shapes into one manipulable unit
// Uses a different URI: "http://schemas.microsoft.com/office/word/2010/wordprocessingGroupShape"

var groupShapeDrawing = new Drawing(
    new DW.Inline(
        new DW.Extent { Cx = 4572000L, Cy = 2286000L },  // 5" x 2.5"
        new DW.EffectExtent(),
        new DW.DocProperties { Id = 12U, Name = "Shape Group" },
        new DW.NonVisualGraphicFrameDrawingProperties(new A.GraphicFrameLocks()),
        new A.Graphic(
            new A.GraphicData(
                new WPG.GroupShape(
                    // Child shapes are positioned relative to group origin
                    // Shape 1 at (0,0)
                    new WSP.WordprocessingShape(
                        new WSP.NonVisualDrawingShapeProperties(
                            new A.ShapeLocks { NoChangeAspect = true }),
                        new WSP.ShapeProperties(
                            new A.Transform2D(
                                new A.Offset { X = 0L, Y = 0L },
                                new A.Extents { Cx = 914400L, Cy = 914400L }),
                            new A.PresetGeometry(new A.AdjustValueList())
                            { Preset = A.ShapeTypeValues.Ellipse },
                            new A.SolidFill(new A.RgbColorModelHex { Val = "FF0000" })),
                        new WSP.TextBoxInfo2(
                            new TextBoxContent(new Paragraph(
                                new Run(new Text("Red Circle")))))
                    ),
                    // Shape 2 offset to the right
                    new WSP.WordprocessingShape(
                        new WSP.NonVisualDrawingShapeProperties(
                            new A.ShapeLocks { NoChangeAspect = true }),
                        new WSP.ShapeProperties(
                            new A.Transform2D(
                                new A.Offset { X = 914400L, Y = 0L },  // 1" to the right
                                new A.Extents { Cx = 914400L, Cy = 914400L }),
                            new A.PresetGeometry(new A.AdjustValueList())
                            { Preset = A.ShapeTypeValues.Rectangle },
                            new A.SolidFill(new A.RgbColorModelHex { Val = "00FF00" })),
                        new WSP.TextBoxInfo2(
                            new TextBoxContent(new Paragraph(
                                new Run(new Text("Green Square")))))
                    )
                )
            ) { Uri = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroupShape" }
        )
    )
    { DistanceFromTop = 0U, DistanceFromBottom = 0U,
      DistanceFromLeft = 0U, DistanceFromRight = 0U }
);
```

### 7.5 Shape Effects — Shadow, Reflection

```csharp
// Shadow effect
new WSP.ShapeProperties(
    new A.Transform2D(...),
    new A.PresetGeometry(new A.AdjustValueList())
    { Preset = A.ShapeTypeValues.RoundedRectangle },
    new A.SolidFill(new A.RgbColorModelHex { Val = "4472C4" }),
    // Shadow via EffectList
    new A.EffectList(
        new A.OuterShadow(
            new A.RgbColorModelHex { Val = "000000" }
        )
        {
            BlurRadius = 50800L,   // 4pt blur (50800 EMU = 4pt at 12700EMU/pt)
            Distance = 38100L,     // 3pt offset
            Direction = 2700000,   // 45° (in 60000ths of a degree)
            Alignment = A.RectangleAlignmentValues.BottomRight
        }
    )
);

// Reflection
new A.EffectList(
    new A.Reflection(
        new A.ReflectionEffect()
        {
            ReflectionBlurRadius = 63500L,  // 5pt
            ReflectionDistance = 76200L,     // 6pt
            ReflectionFade = 50000,         // 50% fade
            ReflectionOverlap = 25000       // 25% overlap
        }
    )
);
```

---

## 8. Math / Equations (OMML)

### 8.1 OfficeMath Container — Basic Setup

```csharp
// All math equations must be inside an OfficeMath container
// OfficeMath can be inline (in a run) or display (in its own paragraph)

// Inline equation in a run
var inlineMathPara = new Paragraph(
    new Run(
        new RunProperties(new RunFonts { Ascii = "Cambria Math", HighAnsi = "Cambria Math" }),
        // Inline math: use OfficeMath directly in Run
        new OfficeMath(
            new M.Fraction(
                new M.Numerator(
                    new M.Run(new M.Text("1"))
                ),
                new M.Denominator(
                    new M.Run(new M.Text("2"))
                )
            )
        )
    )
);

// Display equation (on its own centered paragraph)
var displayMathPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center }
    ),
    new Run(
        new OfficeMath(
            new M.Fraction(
                new M.Numerator(
                    new M.Run(new M.Text("x"))
                ),
                new M.Denominator(
                    new M.Run(new M.Text("y"))
                )
            )
        )
    )
);

// To make a display equation centered with extra spacing:
var displayEquationPara = new Paragraph(
    new ParagraphProperties(
        new SpacingBetweenLines { Before = "240", After = "240" },
        new Justification { Val = JustificationValues.Center }
    ),
    new Run(new OfficeMath(
        // Equation content here
    ))
);
```

### 8.2 Fraction (M.Fraction)

```csharp
// \frac{x}{y} pattern
new M.Fraction(
    new M.Numerator(
        new M.Run(
            new M.RunText("x") { Space = SpaceProcessingModeValues.Preserve }
        )
    ),
    new M.Denominator(
        new M.Run(
            new M.RunText("y") { Space = SpaceProcessingModeValues.Preserve }
        )
    )
);

// Nested fraction: (a+b)/(c+d)
new M.Fraction(
    new M.Numerator(
        new M.Run(new M.Text("a")) { FontSize = 24 },
        new M.Run(new M.Text("+")) { FontSize = 24 },
        new M.Run(new M.Text("b")) { FontSize = 24 }
    ),
    new M.Denominator(
        new M.Run(new M.Text("c")) { FontSize = 24 },
        new M.Run(new M.Text("+")) { FontSize = 24 },
        new M.Run(new M.Text("d")) { FontSize = 24 }
    )
);

// Display fraction (skips 1 as numerator/denominator style)
new M.Fraction(
    new M.Numerator(...),
    new M.Denominator(...),
    new M.FractionPr(
        new M.Type { Val = M.FractionValues.Skewed }  // or Normal, Linear,丝
    )
);
```

### 8.3 Superscript and Subscript

```csharp
// Superscript: x²
new M.Superscript(
    new M.Base(
        new M.Run(new M.Text("x")))
    ),
    new M.SuperscriptOperand(
        new M.Run(new M.Text("2")))
    )
);

// Subscript: x₁
new M.Subscript(
    new M.Base(
        new M.Run(new M.Text("x")))
    ),
    new M.SubscriptOperand(
        new M.Run(new M.Text("1")))
    )
);

// Pre-sub/superscript: _b^a (baseline then super)
// or use M.SubscriptSuperscript for combined

// SubscriptSuperscript (both at once): _b^a C
new M.SubscriptSuperscript(
    new M.Base(new M.Run(new M.Text("C"))),
    new M.Subscript(new M.Run(new M.Text("b"))),
    new M.Superscript(new M.Run(new M.Text("a")))
);
```

### 8.4 Square Root and Nth Root

```csharp
// Square root: √x
new M.Radical(
    new M.Root(
        new M.Run(new M.Text("x")))
    )
);

// Square root with degree hidden (just √)
new M.Radical(
    new M.Root(
        new M.Run(new M.Text("x")))
    ),
    new M.RadicalPr(
        new M.Degree { Val = false }  // Hide the root index
    )
);

// Nth root: ∛(x+1)  — cube root of (x+1)
new M.Radical(
    new M.Root(
        new M.Fraction(
            new M.Numerator(new M.Run(new M.Text("1"))),
            new M.Denominator(new M.Run(new M.Text("3")))
        )
    ),  // This is the "3" for cube root
    new M.Root(
        new M.Run(new M.Text("x"))),
        new M.Run(new M.Text("+"))),
        new M.Run(new M.Text("1")))
    )
);
// Actually, for nth root: first Root is the index (degree), second is the radicand
new M.Radical(
    new M.Root(new M.Run(new M.Text("3"))),  // The index: 3rd root
    new M.Root(
        new M.Run(new M.Text("x")),
        new M.Run(new M.Text("+")),
        new M.Run(new M.Text("1"))
    )
);
```

### 8.5 N-ary Operators — Integral, Summation, Product

```csharp
// Integral ∫ from a to b of f(x) dx
new M.Nary(
    new M.NaryProperties(
        new M.NaryType { Val = M.NaryValues.Integral }  // ∫
    )
    {
        SubSuperscript = M.SubSuperscriptValues.NoSubSuperscript
    },
    new M.Base(
        new M.Run(new M.Text("f(x)")))
    ),
    new M.Subscript(
        new M.Run(new M.Text("a")))
    ),
    new M.Superscript(
        new M.Run(new M.Text("b")))
    )
);

// Summation Σ from i=1 to n of i²
new M.Nary(
    new M.NaryProperties(
        new M.NaryType { Val = M.NaryValues.Sum },  // Σ
        new M.GrowBindings = true
    ),
    new M.Base(
        new M.SubscriptSuperscript(
            new M.Base(new M.Run(new M.Text("i"))),
            new M.Subscript(new M.Run(new M.Text("1"))),
            new M.Superscript(new M.Run(new M.Text("n")))
        )
    ),
    new M.Subscript(
        new M.Run(new M.Text("i")))
    ),
    new M.Superscript(
        new M.Run(new M.Text("2")))
    )
);

// Product ∏ from i=1 to n
new M.Nary(
    new M.NaryProperties(
        new M.NaryType { Val = M.NaryValues.Product }  // ∏
    ),
    new M.Base(
        new M.SubscriptSuperscript(
            new M.Base(new M.Run(new M.Text("i"))),
            new M.Subscript(new M.Run(new M.Text("1"))),
            new M.Superscript(new M.Run(new M.Text("n")))
        )
    ),
    new M.Subscript(
        new M.Run(new M.Text("i")))
    ),
    new M.Superscript(
        new M.Run(new M.Text("2")))
    )
);

// N-ary type values: Integral, Sum, Product, Union, Intersection, etc.
```

### 8.6 Matrix

```csharp
// 2x2 matrix
// [a  b]
// [c  d]
new M.Matrix(
    new M.MatrixRows(
        // Row 1
        new M.MatrixRow(
            new M.MatrixCell(
                new M.Run(new M.Text("a"))
            ),
            new M.MatrixCell(
                new M.Run(new M.Text("b"))
            )
        ),
        // Row 2
        new M.MatrixRow(
            new M.MatrixCell(
                new M.Run(new M.Text("c"))
            ),
            new M.MatrixCell(
                new M.Run(new M.Text("d"))
            )
        )
    ),
    new M.MatrixProperties(
        new M.Jc { Val = M.JustificationValues.Center },  // Centered
        new M.Structure { Val = M.MathStructureValues.SinglePUNCT },
        new M.RowSpacing { Val = 120 },  // Row spacing in twips
        new M.RowSpacing1 { Val = 120 }
    )
)
```

### 8.7 Delimiter (Parentheses/Brackets/Braces)

```csharp
// (a + b) or [a + b] or {a + b}
new M.Delimiter(
    new M.DelimiterProperties(
        new M.Begin(new M.Text("(")),  // Opening char
        new M.End(new M.Text(")")),   // Closing char
        new M.Separator(new M.Text(",")),  // Separator between elements
        new M.Structure { Val = M.MathStructureValues.Minimal }
    ),
    new M.DelimiterContents(
        new M.Run(new M.Text("a")),
        new M.Run(new M.Text("+")),
        new M.Run(new M.Text("b"))
    )
);

// {a, b, c} with curly braces
new M.Delimiter(
    new M.DelimiterProperties(
        new M.Begin(new M.Text("{")),
        new M.End(new M.Text("}")),
        new M.Separator(new M.Text(","))
    ),
    new M.DelimiterContents(
        new M.Run(new M.Text("a")),
        new M.Run(new M.Text("b")),
        new M.Run(new M.Text("c"))
    )
);

// 2x2 matrix in parentheses
new M.Delimiter(
    new M.DelimiterProperties(
        new M.Begin(new M.Text("(")),
        new M.End(new M.Text(")"))
    ),
    new M.DelimiterContents(
        // Inline 2x2 using subscripts
        new M.SubscriptSuperscript(...)
    )
);
```

### 8.8 Equation Array (Aligned Equations)

```csharp
// EquationArray (M.EquationArray) creates a series of equations aligned at markers
// Like \begin{align} in LaTeX

new M.EquationArray(
    new M.EquationArrayProperties(
        new M.Jc { Val = M.JustificationValues.Left },
        new M.RowSpacing { Val = 240 },
        new M.RowSpacing1 { Val = 240 }
    ),
    // Each equation is a Paragraph inside the array
    new Paragraph(new Run(new M.Text("x") { Space = SpaceProcessingModeValues.Preserve })),
    new Paragraph(
        new Run(new M.Text("+") { Space = SpaceProcessingModeValues.Preserve }),
        new Run(new M.Text("y") { Space = SpaceProcessingModeValues.Preserve }),
        new Run(new M.Text("=") { Space = SpaceProcessingModeValues.Preserve }),
        new Run(new M.Text("z") { Space = SpaceProcessingModeValues.Preserve })
    )
);

// Or use M.Break with AlignmentTab for manual alignment points
```

### 8.9 Greek Letters and Math Symbols

```csharp
// Greek letters via M.RunText with Symbol font or Unicode
// Common Greek letters and their uses:

// α (alpha)
new M.Run(new M.Text("\u03B1"))  // or use Unicode directly

// β (beta)
new M.Run(new M.Text("\u03B2"))

// γ (gamma)
new M.Run(new M.Text("\u03B3"))

// π (pi) — use Greek small letter pi
new M.Run(new M.Text("\u03C0"))

// σ (sigma)
new M.Run(new M.Text("\u03C3"))

// Σ (Sigma, capital) — summation symbol
new M.Run(new M.Text("\u03A3"))

// θ (theta)
new M.Run(new M.Text("\u03B8"))

// ∞ (infinity)
new M.Run(new M.Text("\u221E"))

// ≤ (less than or equal)
new M.Run(new M.Text("\u2264"))

// ≥ (greater than or equal)
new M.Run(new M.Text("\u2265"))

// ≠ (not equal)
new M.Run(new M.Text("\u2260"))

// ± (plus-minus)
new M.Run(new M.Text("\u00B1"))

// × (multiplication)
new M.Run(new M.Text("\u00D7"))

// ÷ (division)
new M.Run(new M.Text("\u00F7"))

// For best results, set the font to "Cambria Math" on math runs
new M.Run(
    new RunFonts { Ascii = "Cambria Math", HighAnsi = "Cambria Math" },
    new M.Text("\u03C0")
)
```

---

## 9. Numbering System — Deep Dive

### 9.1 Architecture Overview

```
NumberingDefinitionsPart (numbering.xml)
    └── <w:numbering>
        ├── <w:abstractNum>  (templates)
        │     ├── <w:lvl> × 9 (levels 0-8)
        │     └── <w:pPr><w:numPr> links to this abstractNum
        └── <w:num> (instances)
              └── <w:abstractNumId val="N"/>
```

**Key rule**: `AbstractNum` must appear BEFORE `NumberingInstance` in the XML root.

### 9.2 AbstractNum with Multi-Level Decimal Numbering

```csharp
// AbstractNum: the numbering template (what it looks like)
// NumberingInstance: a specific use of that template (how it's applied)

var numberingPart = mainPart.AddNewPart<NumberingDefinitionsPart>();
var numbering = new Numbering();

// ─────────────────────────────────────────────────────────────
// Step 1: Define AbstractNum (the template)
// ─────────────────────────────────────────────────────────────
var abstractNum = new AbstractNum { AbstractNumberId = 1 };
// MultiLevelType specifies this is a multi-level list
abstractNum.Append(new MultiLevelType { Val = MultiLevelValues.Multilevel });

// Level 0: "1." — decimal, bold number
abstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%1." },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "360", Hanging = "360" }  // 0.25" hanging indent
    ),
    new NumberingSymbolRunProperties(
        new Bold(),
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
        new Color { Val = "2F5496" }
    )
) { LevelIndex = 0 });

// Level 1: "1.1." — indent 0.5"
abstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%1.%2." },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" }
    )
) { LevelIndex = 1 });

// Level 2: "1.1.1."
abstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%1.%2.%3." },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "1080", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" }
    )
) { LevelIndex = 2 });

// ─────────────────────────────────────────────────────────────
// Step 2: Create NumberingInstance (a reference to the template)
// ─────────────────────────────────────────────────────────────
var numInstance = new NumberingInstance(
    new AbstractNumId { Val = 1 }  // Points to abstractNum above
) { NumberID = 1 };

// ─────────────────────────────────────────────────────────────
// Step 3: Assemble — AbstractNum BEFORE NumberingInstance!
// ─────────────────────────────────────────────────────────────
numbering.Append(abstractNum);
numbering.Append(numInstance);
numberingPart.Numbering = numbering;
numberingPart.Numbering.Save();

// ─────────────────────────────────────────────────────────────
// Step 4: Apply to a paragraph
// ─────────────────────────────────────────────────────────────
var numberedPara = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },  // Use level 0 of numId 1
            new NumberingId { Val = 1 }                // Use numbering instance 1
        )
    ),
    new Run(new Text("First item"))
);

// For level 1 sub-item:
var subItemPara = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 1 },  // Use level 1
            new NumberingId { Val = 1 }
        )
    ),
    new Run(new Text("Sub-item"))
);
```

### 9.3 Bullet Lists with Custom Symbols

```csharp
// Bullet numbering uses NumberFormatValues.Bullet
// The bullet character is defined in LevelText and NumberingSymbolRunProperties

var bulletAbstractNum = new AbstractNum { AbstractNumberId = 2 };
bulletAbstractNum.Append(new MultiLevelType { Val = MultiLevelValues.Multilevel });

// Level 0 bullet: ● (Unicode bullet)
bulletAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Bullet },  // Key: Bullet format
    new LevelText { Val = "\u2022" },  // ● bullet character
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Symbol", HighAnsi = "Symbol" }
        // Symbol font maps ● to character 0xD8 in Symbol encoding
    )
) { LevelIndex = 0 });

// Level 1 bullet: ○ (white circle)
bulletAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Bullet },
    new LevelText { Val = "\u25CB" },  // ○ Unicode
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "1080", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Courier New", HighAnsi = "Courier New" }
    )
) { LevelIndex = 1 });

// Level 2 bullet: ■ (black square)
bulletAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Bullet },
    new LevelText { Val = "\u25A0" },  // ■
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "1440", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Arial", HighAnsi = "Arial" }
    )
) { LevelIndex = 2 });

var bulletNumInstance = new NumberingInstance(
    new AbstractNumId { Val = 2 }
) { NumberID = 2 };

numbering.Append(bulletAbstractNum);
numbering.Append(bulletNumInstance);
```

**Common bullet characters:**

| Symbol | Character | Unicode | Common Font |
|--------|-----------|---------|-------------|
| ● Filled circle | Bullet | U+2022 | Symbol |
| ○ Empty circle | White circle | U+25CB | Arial |
| ■ Filled square | Black square | U+25A0 | Arial |
| □ Empty square | White square | U+25A1 | Arial |
| ➢ Right arrow | Right arrow | U+27A2 | Wingdings |
| ✓ Checkmark | Check mark | U+2713 | Wingdings |
| ✗ Cross | Ballot X | U+2717 | Wingdings |
| ▶ Play | Right triangle | U+25B6 | Arial |

### 9.4 Restart Numbering at Specific Point

```csharp
// Method 1: StartOverride on a specific paragraph
// Use LevelOverride + StartOverride to restart at a specific level

var restartNumInstance = new NumberingInstance(
    new AbstractNumId { Val = 1 }
) { NumberID = 3 };

// Override level 0 to start at 5 instead of 1
restartNumInstance.Append(new LevelOverride { LevelIndex = 0 },
    new StartOverrideNumberingValue { Val = 5 }
);

// Apply this to a paragraph — this paragraph starts numbering at 5
var restartPara = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 3 }  // Use the restart instance
        )
    ),
    new Run(new Text("Item 5 (restarted)"))
);
```

### 9.5 Continue Numbering from Previous List

```csharp
// By default, Word continues numbering across lists using the same AbstractNum.
// To force continuation, ensure the list uses the same numId.

// If you need explicit continuation control:
var continuedNumInstance = new NumberingInstance(
    new AbstractNumId { Val = 1 }
) { NumberID = 4 };

// When multiple NumberingInstances share the same AbstractNumId,
// they share the same numbering state (continuation)

// To prevent continuation (start fresh), use a new AbstractNum:
var freshAbstractNum = new AbstractNum { AbstractNumberId = 5 };
freshAbstractNum.Append(new MultiLevelType { Val = MultiLevelValues.Multilevel });
// ... define levels ...
var freshNumInstance = new NumberingInstance(
    new AbstractNumId { Val = 5 }
) { NumberID = 5 };
// This starts at 1 again, independent of the previous list
```

### 9.6 Link Numbering to Heading Styles (Outline Numbering)

```句话说，link numbering to heading styles so that Heading1 starts a new numbering sequence, Heading2 is a sub-item, etc.

```csharp
// This links styles to numbering levels automatically via StyleLink
var abstractNumForOutline = new AbstractNum { AbstractNumberId = 10 };
abstractNumForOutline.Append(new MultiLevelType { Val = MultiLevelValues.Multilevel });
abstractNumForOutline.Append(new StyleLink { Val = "Heading1" });  // Links level 0 to Heading1
abstractNumForOutline.Append(new StyleLink { Val = "Heading2" });  // Links level 1 to Heading2
abstractNumForOutline.Append(new StyleLink { Val = "Heading3" });  // Links level 2 to Heading3

// Level 0 for Heading1
abstractNumForOutline.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "Chapter %1" },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "360", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new Bold(),
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
        new FontSize { Val = "28" }
    )
) { LevelIndex = 0 });

// Level 1 for Heading2
abstractNumForOutline.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%1.%2" },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" }
    )
) { LevelIndex = 1 });

// Level 2 for Heading3
abstractNumForOutline.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%1.%2.%3" },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "1080", Hanging = "360" }
    ),
    new NumberingSymbolRunProperties(
        new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" }
    )
) { LevelIndex = 2 });

// Now when you apply Heading1/2/3 styles, numbering follows automatically
var heading1Para = new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
    new Run(new Text("Introduction"))  // Automatically gets "Chapter 1" prefix
);
var heading2Para = new Paragraph(
    new ParagraphProperties(new ParagraphStyleId { Val = "Heading2" }),
    new Run(new Text("Background"))  // Automatically gets "1.1" prefix
);
```

### 9.7 NumberingFormat Values Reference

```csharp
// NumberFormatValues enum — all supported numbering formats:
NumberFormatValues.Decimal          // 1, 2, 3...
NumberFormatValues.LowerRoman       // i, ii, iii...
NumberFormatValues.UpperRoman       // I, II, III...
NumberFormatValues.LowerLetter      // a, b, c...
NumberFormatValues.UpperLetter      // A, B, C...
NumberFormatValues.Ordinal          // 1st, 2nd, 3rd... (locale-dependent)
NumberFormatValues.OrdinalText      // First, Second, Third... (locale-dependent)
NumberFormatValues.Hex              // 0, 1, 2... F, 10, 11... (hexadecimal)
NumberFormatValues.ChicagoManual    // Chapter numbering (I, A, 1, a)
NumberFormatValues.Kanji           // 漢数字
NumberFormatValues.KanjiDigit      // 一, 二, 三...
NumberFormatValues.DoubleByte      // Ideographic: 一, 二, 三
NumberFormatValues.ArabicFullWidth // Full-width: １, ２, ３
NumberFormatValues.Bullet          // Custom symbol (●, ✓, etc.)
NumberFormatValues.None            // No number
```

### 9.8 IsLegalNumberingStyle — Using Arabic with Nested Levels

```csharp
// IsLegalNumberingStyle=false (default): each level can have its own format
// IsLegalNumberingStyle=true: forces all sub-levels to use Arabic numerals

// This is important for legal/formal numbering where you want:
// 1. level 1 = A, B, C (alphabetic)
// 2. level 2 = 1, 2, 3 (Arabic) — NOT a, b, c
// Without IsLegalNumberingStyle=false, level 2 would inherit alphabetic

var legalAbstractNum = new AbstractNum { AbstractNumberId = 20 };
legalAbstractNum.Append(new MultiLevelType { Val = MultiLevelValues.Multilevel });
legalAbstractNum.Append(new IsLegalNumberingStyle());  // No val = true (default when element present)

// Level 0: A. B. C.
legalAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.UpperLetter },
    new LevelText { Val = "%1." },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "360", Hanging = "360" }
    )
) { LevelIndex = 0 });

// Level 1: 1. 2. 3. (NOT a. b. c.)
legalAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.Decimal },
    new LevelText { Val = "%2." },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "720", Hanging = "360" }
    )
) { LevelIndex = 1 });

// Level 2: (a) (b) (c)
legalAbstractNum.Append(new Level(
    new StartNumberingValue { Val = 1 },
    new NumberingFormat { Val = NumberFormatValues.LowerLetter },
    new LevelText { Val = "(%3)" },
    new LevelJustification { Val = LevelJustificationValues.Left },
    new ParagraphProperties(
        new Indentation { Left = "1080", Hanging = "360" }
    )
) { LevelIndex = 2 });
```

---

## 10. Document Protection & Encryption

### 10.1 DocumentProtection — Basic Forms

```csharp
// DocumentProtection is placed in DocumentSettingsPart
var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings();

// ReadOnly: prevents editing, allows reading
settingsPart.Settings.Append(new DocumentProtection
{
    Edit = DocumentProtectionValues.ReadOnly,
    Enforcement = true
});

// Comments: can only add/edit comments (not modify body text)
settingsPart.Settings.Append(new DocumentProtection
{
    Edit = DocumentProtectionValues.Comments,
    Enforcement = true
});

// TrackedChanges: can only edit with track changes ON
settingsPart.Settings.Append(new DocumentProtection
{
    Edit = DocumentProtectionValues.TrackedChanges,
    Enforcement = true
});

// Forms: only form fields are editable
settingsPart.Settings.Append(new DocumentProtection
{
    Edit = DocumentProtectionValues.Forms,
    Enforcement = true
});
```

### 10.2 Password Hashing for DocumentProtection

Modern Word uses SHA-512 with salt for password hashing (ECMA-376 standard).

```csharp
// SHA-512 password hashing for strong protection
// CryptographicProviderType must be "rsaAES" or "rsaAES" for SHA-512

settingsPart.Settings.Append(new DocumentProtection
{
    Edit = DocumentProtectionValues.ReadOnly,
    Enforcement = true,
    CryptographicProviderType = CryptProviderValues.RsaAES,
    CryptographicAlgorithmClass = CryptAlgorithmClassValues.Hash,
    CryptographicAlgorithmType = CryptAlgorithmValues.TypeAny,
    CryptographicAlgorithmSid = 14,  // SHA-512
    CryptographicSpinCount = 100000U,
    Hash = "base64-encoded-hash-here",
    Salt = "base64-encoded-salt-here"
});

// Generate hash in .NET:
public static (string hash, string salt) GeneratePasswordHash(string password, int spinCount = 100000)
{
    byte[] saltBytes = new byte[16];
    using (var rng = System.Security.Cryptography.RandomNumberGenerator.Create())
        rng.GetBytes(saltBytes);

    // PBKDF2 with SHA-512, 100000 iterations
    using var pbkdf2 = new System.Security.Cryptography.Rfc2898DeriveBytes(
        password, saltBytes, spinCount, System.Security.Cryptography.HashAlgorithmName.SHA512);
    byte[] hash = pbkdf2.GetBytes(64);  // 512 bits

    return (Convert.ToBase64String(hash), Convert.ToBase64String(saltBytes));
}
```

### 10.3 WriteProtection — Recommend Opening as Read-Only

```csharp
// WriteProtection is different from DocumentProtection
// It recommends (but doesn't enforce) that users open as read-only
// Found in extended properties (docProps/custom.xml or settings)

settingsPart.Settings.Append(new WriteProtection
{
    Recommended = true  // "Recommend opening as read-only"
});

// Or force read-only recommendation with a specific application name
settingsPart.Settings.Append(new WriteProtection
{
    Recommended = true,
    ApplicationName = "Microsoft Word"
});
```

### 10.4 Restrict Editing to Form Fields Only

```csharp
// This protects the document but allows editing in form field content controls
settingsPart.Settings = new Settings(
    new DocumentProtection
    {
        Edit = DocumentProtectionValues.Forms,
        Enforcement = true
    },
    // Also set to allow editing only in form fields
    new EditingRestrictions { Val = EditingRestrictionValues.Forms }
);
```

### 10.5 PermStart / PermEnd — Editable Regions in Protected Document

Allow specific regions (ranges) to be edited even when the document is protected.

```csharp
// <w:permStart w:id="1" w:editor="everyone"/>
// <w:r><w:t>Editable text</w:t></w:r>
// <w:permEnd w:id="1"/>

// Even when document protection is on, this range can be edited by everyone

var editableRegion = new Paragraph(
    new ParagraphProperties(
        new PermStart { Id = 1, EditorGroup = RangePermissionEditingGroupValues.Everyone }
    ),
    new Run(new Text("This text can be edited even in a protected document.") { Space = SpaceProcessingModeValues.Preserve }),
    new ParagraphProperties(
        new PermEnd { Id = 1 }
    )
);

// EditorGroup values:
// Everyone         — anyone can edit
// Administrators   — only administrators
// Contributors     — only contributors
// Editors          — only editors
// Owners           — only document owners
// Nobody           — nobody can edit (use with w:perm sbz="1" for "does not include")

// Use specific user name:
// <w:permStart w:id="2" w:author="Alice"/>

// For tracked changes review scenario (allow comments but not direct editing):
var commentableRegion = new Paragraph(
    new ParagraphProperties(
        new PermStart { Id = 2, EditorGroup = RangePermissionEditingGroupValues.Everyone }
    ),
    new Run(new Text("This region allows comments and tracked changes.") { Space = SpaceProcessingModeValues.Preserve }),
    new ParagraphProperties(
        new PermEnd { Id = 2 }
    )
);
```

### 10.6 Full Document Protection with Password and Salt

```csharp
public static void ProtectDocument(
    WordprocessingDocument doc,
    string password,
    DocumentProtectionValues protectionType)
{
    var settingsPart = doc.MainDocumentPart!.AddNewPart<DocumentSettingsPart>();
    if (settingsPart.Settings == null)
        settingsPart.Settings = new Settings();

    // Generate password hash
    byte[] salt = new byte[16];
    using (var rng = System.Security.Cryptography.RandomNumberGenerator.Create())
        rng.GetBytes(salt);

    int spinCount = 100000;
    using var pbkdf2 = new System.Security.Cryptography.Rfc2898DeriveBytes(
        password, salt, spinCount, System.Security.Cryptography.HashAlgorithmName.SHA512);
    byte[] hash = pbkdf2.GetBytes(64);

    var protection = new DocumentProtection
    {
        Edit = protectionType,
        Enforcement = true,
        CryptographicProviderType = CryptProviderValues.RsaAES,
        CryptographicAlgorithmClass = CryptAlgorithmClassValues.Hash,
        CryptographicAlgorithmType = CryptAlgorithmValues.TypeAny,
        CryptographicAlgorithmSid = 14,  // SHA-512
        CryptographicSpinCount = (UInt32Value)spinCount,
        Hash = Convert.ToBase64String(hash),
        Salt = Convert.ToBase64String(salt)
    };

    settingsPart.Settings.Append(protection);
    settingsPart.Settings.Save();
}
```

---

## Quick Reference: Common Element Order in OpenXML

When building complex elements, remember these ordering rules:

### Run Elements Order (inside RunProperties):
`RunFonts` → `Bold`/`Italic` → `Color` → `FontSize` → `Underline` → `VerticalTextAlignment` → `Emphasis` → (any other)

### Paragraph Elements Order (inside ParagraphProperties):
`ParagraphStyleId` → `KeepNext` → `KeepLines` → `PageBreakBefore` → `FrameProperties` → `WidowControl` → `NumPr` → `Indentation` → `SpacingBetweenLines` → `Justification` → `SectionProperties`

### Table Properties Order:
`TableWidth` → `TextDirection` → `Borders` → `Shading` → `TableLayout` → `TableCellMarginDefault`

### SectionProperties Order:
`FootnotePr` → `EndnotePr` → `Type` → `PageSize` → `PageMargin` → `PaperSource` → `PageBorders` → `LineNumberRestart` → `PageNumberFormat` → `TitlePage` → `TextDirection`

---

*Generated for DocumentFormat.OpenXml 3.x / .NET 8+ / C# 12*
*Last updated: 2026-03-22*
