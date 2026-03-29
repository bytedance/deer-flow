# OpenXML SDK 3.x Complete Reference Encyclopedia

**Target:** DocumentFormat.OpenXml 3.x / .NET 8+ / C# 12
**Last Updated:** 2026-03-22

This document serves as an exhaustive reference for building DOCX files with the OpenXML SDK. Every code block is ready to copy-paste.

---

## Namespace Aliases Used Throughout

```csharp
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
```

---

## Table of Contents

1. [Document Creation Skeleton](#1-document-creation-skeleton)
2. [Style System Deep Dive](#2-style-system-deep-dive)
3. [Character Formatting (RunProperties)](#3-character-formatting-runproperties--exhaustive)
4. [Paragraph Formatting (ParagraphProperties)](#4-paragraph-formatting-paragraphproperties--exhaustive)

---

## 1. Document Creation Skeleton

### 1.1 Complete Flow: Create to Save

```csharp
// =============================================================================
// DOCUMENT CREATION SKELETON
// =============================================================================
// This is the minimal complete flow for creating a valid DOCX from scratch.
// Follow these steps in order: Create -> AddParts -> AddContent -> Save.
//
// Key insight: WordprocessingDocument.Create() adds MainDocumentPart automatically,
// but all other parts (Styles, Settings, Numbering, Theme) must be added manually.

// --- STEP 1: CREATE THE PACKAGE ---
// The file path can be absolute or relative. WordprocessingDocumentType.Document
// is the standard choice for .docx files (vs. Template, MacroEnabled, etc.)
string outputPath = "C:\\Docs\\MyDocument.docx";

using var doc = WordprocessingDocument.Create(
    outputPath,                          // File path
    WordprocessingDocumentType.Document,  // Document type enum
    new DocumentOptions                    // Optional: AutoSave, etc.
    {
        AutoSave = false                   // true = flush changes automatically
    });

// --- STEP 2: GET OR CREATE THE MAIN DOCUMENT PART ---
// When you call Create(), MainDocumentPart is automatically created and linked.
// You access it via .MainDocumentPart (not .AddMainDocumentPart, which would add
// a SECOND main part — illegal). For a fresh document, just use .MainDocumentPart.
var mainPart = doc.MainDocumentPart!;
var body = mainPart.Document.Body!;  // Body is created automatically with the part

// --- STEP 3: ADD ADDITIONAL PARTS ---
// These are OPTIONAL but recommended for a complete document:
// - StyleDefinitionsPart: required for styles
// - NumberingDefinitionsPart: required for bullets/numbers
// - DocumentSettingsPart: zoom, proof state, tab stops, compatibility
// - ThemePart: color/theme information
// Parts are created fresh and linked via relationships.

// Example: Add styles part (covered in Section 2)
var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
stylesPart.Styles = new Styles();
stylesPart.Styles.Save();

// Example: Add settings part (covered in 1.4)
var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
settingsPart.Settings = new Settings();
settingsPart.Settings.Save();

// --- STEP 4: ADD CONTENT TO BODY ---
// Body accepts: Paragraph (w:p), Table (w:tbl), Structured Document Tag (w:sdt)
// Content is added in document order (no need for explicit index).
// IMPORTANT: SectionProperties (w:sectPr) MUST be the last child of body.
body.Append(new Paragraph(
    new Run(new Text("Hello, World!"))));

// --- STEP 5: SET SECTION PROPERTIES (PAGE LAYOUT) ---
// sectPr defines page size, margins, headers/footers, columns, etc.
// It must be the last child of body. If missing, Word uses defaults (Letter/A4, 1" margins).
var sectPr = new SectionProperties();

// Page Size: Width/Height in DXA (1 inch = 1440 DXA)
// Letter: 12240 x 15840 DXA (8.5" x 11")
// A4: 11906 x 16838 DXA (210mm x 297mm)
sectPr.Append(new PageSize
{
    Width = 12240u,   // 8.5 inches
    Height = 15840u  // 11 inches
});

// Page Margins: all four margins in DXA
// Note: Top+Bottom margins + HeaderDistance = distance from page edge to text
sectPr.Append(new PageMargin
{
    Top = 1440,       // 1 inch
    Bottom = 1440,    // 1 inch
    Left = 1440u,     // 1 inch (uint required)
    Right = 1440u,    // 1 inch
    Header = 720u,    // 0.5 inch from page edge to header
    Footer = 720u     // 0.5 inch from page edge to footer
});

// Attach sectPr to body (must be last)
body.Append(sectPr);

// --- STEP 6: SAVE ---
// Because we use `using`, Dispose() is called automatically when the block exits.
// Dispose() saves the file. If you forget `using`, call doc.Save() explicitly.
```

### 1.2 Opening an Existing Document

```csharp
// =============================================================================
// OPENING EXISTING DOCUMENTS
// =============================================================================
// Open() has multiple overloads:
// 1. Open(string path, bool isEditable, AutoSave)
// 2. Open(Stream, bool isEditable, AutoSave)
// 3. Open(string path, bool isEditable, OpenSettings)
//
// isEditable=true means open for read/write. false = read-only.
// isEditable=false is faster (shared locks avoided) but throws if file is read-only.

// --- OPEN FOR EDITING (READ/WRITE) ---
string inputPath = "C:\\Docs\\Existing.docx";
using var editDoc = WordprocessingDocument.Open(
    inputPath,
    isEditable: true,      // Required for modification
    new OpenSettings
    {
        AutoSave = true     // Automatically save on Dispose
    });

var body = editDoc.MainDocumentPart!.Document.Body!;
// ... make changes ...
// No explicit Save() needed if AutoSave = true

// --- OPEN AS READ-ONLY (FASTER) ---
using var readOnlyDoc = WordprocessingDocument.Open(
    inputPath,
    isEditable: false,     // Read-only mode
    new OpenSettings
    {
        // MarkupDeclarationProcess options
    });

// --- OPEN FROM STREAM ---
byte[] fileBytes = File.ReadAllBytes(inputPath);
using var streamDoc = WordprocessingDocument.Open(
    new MemoryStream(fileBytes),
    isEditable: true,
    new OpenSettings { AutoSave = false });

// After editing, you MUST copy the stream back to file if AutoSave=false:
// streamDoc.MainDocumentPart.Document.Save();
// File.WriteAllBytes(outputPath, streamStream.ToArray());

// --- OPEN FROM HTTP RESPONSE (WEB SCENARIO) ---
using var httpClient = new HttpClient();
var response = await httpClient.GetAsync("https://example.com/document.docx");
using var webStream = await response.Content.ReadAsStreamAsync();
using var webDoc = WordprocessingDocument.Open(webStream, isEditable: true);
```

### 1.3 Stream-Based Creation (MemoryStream for Web)

```csharp
// =============================================================================
// STREAM-BASED DOCUMENT CREATION
// =============================================================================
// Use MemoryStream when you want to:
// 1. Generate a document in memory before sending to a client
// 2. Avoid touching the filesystem (ASP.NET Core scenarios)
// 3. Return a document from an API endpoint
//
// CRITICAL: The stream MUST be seekable when you call .Open().
// After WordprocessingDocument.Create(), the stream position is at the beginning.
// If you write to the stream BEFORE creating the document, seek to 0 first.

// --- CREATE IN MEMORY ---
MemoryStream memStream = new MemoryStream();

// Create directly on a stream (no file path involved)
using (var doc = WordprocessingDocument.Create(
    memStream,
    WordprocessingDocumentType.Document,
    new DocumentOptions { AutoSave = false }))
{
    var mainPart = doc.MainDocumentPart!;
    mainPart.Document = new Document(new Body());
    mainPart.Document.Body!.Append(new Paragraph(
        new Run(new Text("Generated in memory"))));
    mainPart.Document.Save();  // Save to the underlying stream
}
// At this point, memStream contains the complete DOCX

// --- SEND TO HTTP RESPONSE (ASP.NET Core) ---
// In an API controller:
[HttpGet("download")]
public async Task<IActionResult> DownloadDocument()
{
    var memStream = new MemoryStream();

    using (var doc = WordprocessingDocument.Create(
        memStream,
        WordprocessingDocumentType.Document))
    {
        var mainPart = doc.MainDocumentPart!;
        mainPart.Document = new Document(new Body());
        mainPart.Document.Body!.Append(new Paragraph(
            new Run(new Text("Download me!"))));
        mainPart.Document.Save();
    }

    memStream.Position = 0;  // IMPORTANT: Reset position for reading
    return File(memStream,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "GeneratedDocument.docx");
}

// --- CREATE FROM TEMPLATE IN MEMORY ---
// Useful for mail-merge style operations
MemoryStream templateStream = new MemoryStream();
File.WriteAllBytes("template.docx", templateStream.ToArray()); // Save a template first

using var templateSource = new MemoryStream(File.ReadAllBytes("template.docx"));
using var mergedDoc = (WordprocessingDocument)templateSource.Clone();

// Clone() creates an editable copy. Don't forget to set position:
mergedDoc.MainDocumentPart!.Document.Body!.Append(new Paragraph(
    new Run(new Text("Added content"))));
```

### 1.4 Adding All Standard Parts

```csharp
// =============================================================================
// ADDING ALL STANDARD DOCUMENT PARTS
// =============================================================================
// A complete document should have:
// 1. MainDocumentPart (auto-created)
// 2. StyleDefinitionsPart
// 3. NumberingDefinitionsPart
// 4. DocumentSettingsPart
// 5. ThemePart (optional)
// 6. Custom parts (headers, footers, comments, etc.)

// --- COMPLETE SETUP METHOD ---
public static void CreateCompleteDocument(string path)
{
    using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);
    var mainPart = doc.MainDocumentPart!;

    // Initialize document
    mainPart.Document = new Document(new Body());
    var body = mainPart.Document.Body!;

    // Add all parts
    AddStylesPart(mainPart);
    AddNumberingPart(mainPart);
    AddSettingsPart(mainPart);
    AddThemePart(mainPart);
    AddHeadersAndFooters(mainPart);

    // Add sample content
    AddSampleContent(body);

    // Section properties MUST be last
    body.Append(CreateSectionProperties());

    mainPart.Document.Save();
}

// --- STYLES PART ---
// See Section 2 for detailed style creation
private static void AddStylesPart(MainDocumentPart mainPart)
{
    var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
    var styles = new Styles();

    // DocDefaults: document-wide defaults for run and paragraph properties
    // These apply when no explicit style or direct formatting overrides them
    styles.Append(new DocDefaults(
        new RunPropertiesDefault(
            new RunPropertiesBaseStyle(
                new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
                new FontSize { Val = "22" },      // 22 half-points = 11pt
                new FontSizeComplexScript { Val = "22" }
            )
        ),
        new ParagraphPropertiesDefault(
            new ParagraphPropertiesBaseStyle(
                new SpacingBetweenLines { After = "200", Line = "276", LineRule = LineSpacingRuleValues.Auto }
            )
        )
    ));

    // Default Normal style
    styles.Append(new Style(
        new StyleName { Val = "Normal" },
        new PrimaryStyle()
    )
    { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });

    stylesPart.Styles = styles;
    stylesPart.Styles.Save();
}

// --- NUMBERING PART ---
// Required for bulleted and numbered lists
private static void AddNumberingPart(MainDocumentPart mainPart)
{
    var numberingPart = mainPart.AddNewPart<NumberingDefinitionsPart>();
    var numbering = new Numbering();

    // AbstractNum defines the list format (bullet, number, multilevel)
// Creates a bullet list definition with 3 levels
    var abstractNum = new AbstractNum { AbstractNumberId = 1 };

    // Level 0: Bullet (dot)
    abstractNum.Append(new Level(
        new StartNumberingValue { Val = 1 },
        new NumberingFormat { Val = NumberFormatValues.Bullet },
        new LevelText { Val = "•" },
        new LevelJustification { Val = LevelJustificationValues.Left },
        new PreviousParagraphProperties(
            new Indentation { Left = "720", Hanging = "360" })  // 720 DXA indent, 360 DXA hanging
    )
    { LevelIndex = 0 });

    // Level 1: Dash
    abstractNum.Append(new Level(
        new StartNumberingValue { Val = 1 },
        new NumberingFormat { Val = NumberFormatValues.Bullet },
        new LevelText { Val = "–" },
        new LevelJustification { Val = LevelJustificationValues.Left },
        new PreviousParagraphProperties(
            new Indentation { Left = "1440", Hanging = "360" })
    )
    { LevelIndex = 1 });

    // Level 2: Circle
    abstractNum.Append(new Level(
        new StartNumberingValue { Val = 1 },
        new NumberingFormat { Val = NumberFormatValues.Bullet },
        new LevelText { Val = "◦" },
        new LevelJustification { Val = LevelJustificationValues.Left },
        new PreviousParagraphProperties(
            new Indentation { Left = "2160", Hanging = "360" })
    )
    { LevelIndex = 2 });

    numbering.Append(abstractNum);

    // NumberingInstance links to AbstractNum and assigns a numId
    numbering.Append(new NumberingInstance(
        new AbstractNumId { Val = 1 }
    )
    { NumberID = 1 });

    numberingPart.Numbering = numbering;
    numberingPart.Numbering.Save();
}

// --- SETTINGS PART ---
// Contains document-level settings: zoom, proof state, default tab stop, etc.
private static void AddSettingsPart(MainDocumentPart mainPart)
{
    var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
    var settings = new Settings();

    // Zoom: document zoom percentage (default 100%)
    // Val is a percentage value (e.g., "100" = 100%)
    settings.Append(new Zoom { Val = "100", Percent = true, SnapToGrid = true });

    // ProofState: spelling/grammar check state
    // Val combines bits: 1=grammar, 2=spelling, 3=both
    settings.Append(new ProofState { Val = ProofingStateValues.Clean });

    // Default tab stop interval in DXA
    // Word inserts tab stops every 720 DXA (0.5 inch) by default
    settings.Append(new DefaultTabStop { Val = 720 });

    // Character spacing control: automatically adjust character spacing
    // to maintain consistent line spacing (similar to InDesign)
    settings.Append(new CharacterSpacingControl { Val = CharacterSpacingValues.CompressPunctuation });

    // Compatibility settings: controls how Word handles certain formatting
    // to ensure compatibility with different Word versions
    settings.Append(new Compatibility(
        new UseFELayout(),          // Use formatted East Asian layout
        new UseAsianDigraphicLineBreakRules(),  // CJK line breaking rules
        new AllowSpaceOfSameStyleInTable(),     // Table cell spacing
        new DoNotUseIndentAsPercentageForTabStops(), // Legacy tab behavior
        new ProportionalOtherIndents(),         // Proportional indents
        new LayoutTableRawTextInTable()         // Raw text in layout tables
    ));

    // Revision tracking view settings
    settings.Append(new RevisionView { DocPart = false, Formatting = true, Ink = true, Markup = true });

    settingsPart.Settings = settings;
    settingsPart.Settings.Save();
}

// --- THEME PART ---
// Defines color scheme, font scheme, and format scheme for the document theme
private static void AddThemePart(MainDocumentPart mainPart)
{
    var themePart = mainPart.AddNewPart<ThemePart>();
    var theme = new Theme(
        new ThemeElements(
            // Color scheme: 10 predefined theme colors
            new ColorScheme(
                new Dark1Color(new Color { Val = "000000" }),
                new Light1Color(new Color { Val = "FFFFFF" }),
                new Dark2Color(new Color { Val = "1F497D" }),
                new Light2Color(new Color { Val = "EEECE1" }),
                new Accent1Color(new Color { Val = "4F81BD" }),
                new Accent2Color(new Color { Val = "C0504D" }),
                new Accent3Color(new Color { Val = "9BBB59" }),
                new Accent4Color(new Color { Val = "8064A2" }),
                new Accent5Color(new Color { Val = "4BACC6" }),
                new Accent6Color(new Color { Val = "F79646" }),
                new Hyperlink(new Color { Val = "0000FF" }),
                new FollowedHyperlinkColor(new Color { Val = "800080" })
            ),
            // Font scheme: major (headings) and minor (body) fonts
            new FontScheme(
                new MajorFont { Val = "Calibri Light" },
                new MinorFont { Val = "Calibri" }
            ),
            // Format scheme: default fill and effect styles
            new FormatScheme(
                new FillStyleList(
                    new FillStyle { Fill = new PatternFill { PatternType = PatternValues.Solid } }
                ),
                new LineStyleList(
                    new LineStyle { Val = LineValues.Single }
                )
            )
        ),
        new ThemeName { Val = "Office Theme" },
        new ThemeNames(
            new LanguageBasedString { Val = "en-US", LanguageId = "x-none" }
        )
    );

    themePart.Theme = theme;
    themePart.Theme.Save();
}

// --- HEADERS AND FOOTERS ---
private static void AddHeadersAndFooters(MainDocumentPart mainPart)
{
    // Header
    var headerPart = mainPart.AddNewPart<HeaderPart>();
    headerPart.Header = new Header(
        new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Right }),
            new Run(
                new RunProperties(
                    new RunFonts { Ascii = "Calibri Light", HighAnsi = "Calibri Light" },
                    new Italic(),
                    new FontSize { Val = "20" }  // 10pt
                ),
                new Text("Document Header"))
        ));
    var headerId = mainPart.GetIdOfPart(headerPart);

    // Footer
    var footerPart = mainPart.AddNewPart<FooterPart>();
    footerPart.Footer = new Footer(
        new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }),
            new Run(new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
            new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
            new Run(new Text(" of ") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
            new Run(new FieldCode(" NUMPAGES ") { Space = SpaceProcessingModeValues.Preserve }),
            new Run(new FieldChar { FieldCharType = FieldCharValues.End })
        ));
    var footerId = mainPart.GetIdOfPart(footerPart);

    // Reference IDs in section properties
    // (added in CreateSectionProperties below)
}

// --- SECTION PROPERTIES (COMPLETE) ---
private static SectionProperties CreateSectionProperties()
{
    var sectPr = new SectionProperties();

    // Header/Footer references (must come before page size/margins)
    var mainPart = doc.MainDocumentPart; // Note: in real code, pass as parameter
    sectPr.Append(new HeaderReference
    {
        Type = HeaderFooterValues.Default,
        Id = mainPart!.GetIdOfPart(mainPart.HeaderParts.First())
    });
    sectPr.Append(new FooterReference
    {
        Type = HeaderFooterValues.Default,
        Id = mainPart.GetIdOfPart(mainPart.FooterParts.First())
    });

    // Page size
    sectPr.Append(new PageSize { Width = 12240u, Height = 15840u });

    // Page margins
    sectPr.Append(new PageMargin
    {
        Top = 1440,
        Bottom = 1440,
        Left = 1440u,
        Right = 1440u,
        Header = 720u,
        Footer = 720u
    });

    // Page numbering format
    sectPr.Append(new PageNumberType { Start = 1, Format = NumberFormatValues.Decimal });

    // Column settings (default: 1 column)
    sectPr.Append(new Columns { ColumnCount = 1, EqualWidth = true });

    // Paper source (printer tray)
    // sectPr.Append(new PaperSource { Tray = 1, Paper = 7 });

    return sectPr;
}
```

### 1.5 Unit Systems Reference

```csharp
// =============================================================================
// UNIT SYSTEMS IN OPENXML
// =============================================================================
// Understanding units is critical. Wrong unit = wrong formatting.
//
// DXA (Twentieths of a DXA) - "Standard Document Unit"
//   1 DXA = 1/20th of a point
//   1 inch = 1440 DXA
//   1 cm = 567 DXA (approx)
//   Used for: margins, indents, spacing, tab stops, column widths
//
// Half-Points (sz) - Font Size
//   Value is in half-points (1/2 point increments)
//   24 = 12pt, 28 = 14pt, 36 = 18pt, 48 = 24pt
//   Used for: FontSize.Val, FontSizeComplexScript.Val
//
// Points (pt) - Direct Measurements
//   Standard typographic point (72 per inch)
//   Used for: some line spacing values, border widths
//
// EMU (English Metric Units) - Drawing Objects
//   1 inch = 914400 EMU
//   Used for: drawing object sizes, shapes, images
//
// STARS (Special Twips Advanced Right-Left) - CJK Indentation
//   Used for: FirstLineChars, HangingChars (special FirstLine/Hanging for CJK)
//   Converts character counts to DXA based on font metrics
//
// LINE SPACING SPECIAL VALUES:
//   Line = "240" with LineRule = Auto = single spacing (default)
//   Line = "480" with LineRule = Auto = double spacing
//   Line = "360" with LineRule = Auto = 1.5 spacing
//   Line = "240" with LineRule = Exact = exactly 12pt
//   Line = "288" with LineRule = AtLeast = at least 14.4pt (grows with content)

// --- CONVERSION HELPER METHODS ---
public static class OpenXmlUnits
{
    // DXA conversions
    public static int InchesToDxa(double inches) => (int)(inches * 1440);
    public static int CmToDxa(double cm) => (int)(cm * 567.0);
    public static int PtToDxa(double pt) => (int)(pt * 20);
    public static double DxaToInches(int dxa) => dxa / 1440.0;
    public static double DxaToCm(int dxa) => dxa / 567.0;
    public static double DxaToPt(int dxa) => dxa / 20.0;

    // EMU conversions (for drawings)
    public static long InchesToEmu(double inches) => (long)(inches * 914400);
    public static long CmToEmu(double cm) => (long)(cm * 360000);
    public static double EmuToInches(long emu) => emu / 914400.0;

    // Half-point conversions (font sizes)
    public static int PtToHalfPt(double pt) => (int)(pt * 2);
    public static int FontSizeToSz(double ptSize) => (int)(ptSize * 2);
    public static double SzToPt(int sz) => sz / 2.0;

    // Line spacing
    public static int SingleSpacing => 240;
    public static int DoubleSpacing => 480;
    public static int OneAndHalfSpacing => 360;
    public static int LineSpacingPt(double pt) => (int)(pt * 20);  // Convert to DXA
}

// Example usage:
var marginInInches = OpenXmlUnits.DxaToInches(1440);  // 1.0
var fontSizeInSz = OpenXmlUnits.FontSizeToSz(12.0);    // 24
var indentInDxa = OpenXmlUnits.InchesToDxa(0.5);       // 720
```

---

## 2. Style System Deep Dive

### 2.1 Style Types and Structure

```csharp
// =============================================================================
// STYLE TYPES OVERVIEW
// =============================================================================
// OpenXML defines 4 style types (StyleValues enum):
// 1. Paragraph (w:p) - controls paragraph-level formatting
// 2. Character (w:r) - controls inline/run-level formatting
// 3. Table (w:tbl) - controls table-level formatting
// 4. Numbering (w:num) - NOT a style type, but a separate numbering system
//
// Key insight: A style can be BOTH paragraph and character style (linked style).
// The "linkedStyle" element links a paragraph style to a character style.

// --- MINIMAL PARAGRAPH STYLE ---
// A paragraph style controls: pPr (paragraph properties) and optionally rPr
Style minimalParaStyle = new Style(
    new StyleName { Val = "MyParagraphStyle" },
    new PrimaryStyle()     // Primary styles appear in Style gallery
)
{
    Type = StyleValues.Paragraph,
    StyleId = "MyParagraphStyle"
};

// --- MINIMAL CHARACTER STYLE ---
// A character style controls: rPr only (no pPr)
Style minimalCharStyle = new Style(
    new StyleName { Val = "MyCharacterStyle" },
    new PrimaryStyle()
)
{
    Type = StyleValues.Character,
    StyleId = "MyCharacterStyle"
};

// Character style with run properties (fonts, size, bold, etc.)
Style charStyleWithFormatting = new Style(
    new StyleName { Val = "Emphasis" },
    new PrimaryStyle(),
    new StyleRunProperties(
        new Italic(),
        new Color { Val = "C00000" }  // Dark red
    )
)
{
    Type = StyleValues.Character,
    StyleId = "Emphasis"
};

// --- LINKED STYLE (Paragraph + Character) ---
// A linked style combines both: it can be applied to a paragraph OR a run.
// This is how Word's "Heading 1" works — applies to paragraphs, but you can
// also select text within a heading and apply the same style as character formatting.
Style linkedStyle = new Style(
    new StyleName { Val = "LinkedStyle" },
    new PrimaryStyle(),
    new LinkedStyle { Val = "LinkedStyleChar" },  // Links to character style
    new StyleParagraphProperties(
        new SpacingBetweenLines { After = "120" }
    ),
    new StyleRunProperties(
        new Bold(),
        new FontSize { Val = "24" }
    )
)
{
    Type = StyleValues.Paragraph,
    StyleId = "LinkedStyle"
};

// Corresponding character style (normally same name + "Char" suffix by convention)
Style linkedStyleChar = new Style(
    new StyleName { Val = "LinkedStyle Char" },  // Word convention: adds " Char"
    new PrimaryStyle(),
    new StyleRunProperties(
        new Bold(),
        new FontSize { Val = "24" }
    )
)
{
    Type = StyleValues.Character,
    StyleId = "LinkedStyleChar"
};

// --- TABLE STYLE ---
Style tableStyle = new Style(
    new StyleName { Val = "MyTableStyle" },
    new PrimaryStyle(),
    new StyleTableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },  // 50% width
        new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new RightBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
            new InsideHorizontalBorder { Val = BorderValues.Single, Size = 2, Color = "CCCCCC" },
            new InsideVerticalBorder { Val = BorderValues.Single, Size = 2, Color = "CCCCCC" }
        ),
        new TableCellMarginDefault(
            new TopMargin { Width = "0", Type = TableWidthUnitValues.DXA },
            new StartMargin { Width = "108", Type = TableWidthUnitValues.DXA },
            new BottomMargin { Width = "0", Type = TableWidthUnitValues.DXA },
            new EndMargin { Width = "108", Type = TableWidthUnitValues.DXA }
        )
    )
)
{
    Type = StyleValues.Table,
    StyleId = "MyTableStyle"
};
```

### 2.2 DocDefaults and Document-Wide Defaults

```csharp
// =============================================================================
// DOCDEFAULTS: DOCUMENT-WIDE DEFAULTS
// =============================================================================
// DocDefaults lives inside Styles and provides fallback values when:
// 1. No explicit style is applied
// 2. No direct formatting is applied
// It contains RunPropertiesDefault and/or ParagraphPropertiesDefault.
//
// CRITICAL: DocDefaults applies to the entire document. Any explicit style
// or direct formatting will override it.

// --- COMPLETE DOCDEFAULTS SETUP ---
var docDefaults = new DocDefaults(
    // Run properties defaults: default font, size, language for all runs
    new RunPropertiesDefault(
        new RunPropertiesBaseStyle(
            // RunFonts: which font to use for each script
            // Word will fall back through these: ASCII -> HighAnsi -> EastAsia -> ComplexScript
            // Always specify at minimum Ascii and HighAnsi
            new RunFonts
            {
                Ascii = "Calibri",           // Western/Latin font (primary)
                HighAnsi = "Calibri",        // Latin characters (often same as Ascii)
                EastAsia = "SimSun",         // East Asian font (CJK)
                ComplexScript = "Arial",     // Complex scripts (Arabic, Hebrew, Thai)
                ASCIITheme = ThemeFontValues.Minor,
                HighAnsiTheme = ThemeFontValues.Minor,
                EastAsiaTheme = ThemeFontValues.Minor,
                ComplexScriptTheme = ThemeFontValues.Minor
            },
            // FontSize: in HALF-POINTS (24 = 12pt, 22 = 11pt, 20 = 10pt)
            new FontSize { Val = "22" },         // 11pt for body
            new FontSizeComplexScript { Val = "22" },
            // Languages: required for proper hyphenation and spell checking
            new Languages { Val = "en-US" },     // Default language
            new Languages { EastAsia = "zh-CN", Val = "en-US" }  // Can set multiple
        )
    ),
    // Paragraph properties defaults: default spacing, etc.
    new ParagraphPropertiesDefault(
        new ParagraphPropertiesBaseStyle(
            // SpacingBetweenLines: default paragraph spacing
            // After = "200" = 200 DXA = 10pt after each paragraph
            new SpacingBetweenLines
            {
                After = "200",
                Line = "276",
                LineRule = LineSpacingRuleValues.Auto  // Auto = 1.15x line height
            }
        )
    )
);

// --- LAYOUT LUNCTIONS (LATENT STYLES) ---
// Latent styles are hidden styles that exist in Word but aren't in styles.xml.
// They provide fast-access defaults for formatting (e.g., Normal, Heading 1-6, etc.)
// when the user hasn't explicitly customized them.
//
// DocDefaults can define LatentStyleCountOverride to adjust count,
// but true latent styles are controlled by Normal.dotm (Word's global template).
Styles CreateStylesWithDocDefaults()
{
    var styles = new Styles();

    // DocDefaults with run and paragraph properties defaults
    styles.Append(new DocDefaults(
        new RunPropertiesDefault(
            new RunPropertiesBaseStyle(
                new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
                new FontSize { Val = "22" },
                new Languages { Val = "en-US" }
            )
        ),
        new ParagraphPropertiesDefault(
            new ParagraphPropertiesBaseStyle(
                new SpacingBetweenLines { After = "160", Line = "276", LineRule = LineSpacingRuleValues.Auto }
            )
        )
    ));

    // LatentStyles: override defaults for built-in latent styles
    // These control Word's "fast-styles" like Heading 1-6 before they're customized
    styles.Append(new LatentStyles(
        new Count { Val = 159 },                    // Total latent style count
        new FirstLineChars { Val = 352 },          // Default first line char count
        new HorizontalOverflow { Val = HorizontalOverflowValues.Overflow },
        new VerticalOverflow { Val = VerticalOverflowValues.Overflow },
        new KoreanSpaceAdjust { Val = true },
        // Each LatentStyleException overrides ONE attribute of ONE latent style
        // StyleID = the built-in style name (e.g., "Normal", "heading 1")
        // Attribute: what to change (bold, italic, font, color, etc.)
        // The defaults for built-in headings: font=Calibri, size=24, bold
        new LatentStyleException(
            new Primary烙,
            new StyleName { Val = "Normal" },
            new UIPriority { Val = 1 },
            new PrimaryZone(),
            new QuickStyle()
        ),
        new LatentStyleException(
            new Primary烙,
            new StyleName { Val = "heading 1" },
            new UIPriority { Val = 9 },
            new PrimaryZone(),
            new QuickStyle(),
            new Bold(),
            new BoldComplexScript(),
            new FontSize { Val = "48" },  // 24pt = 48 half-pts
            new FontSizeComplexScript { Val = "48" }
        )
    ));

    return styles;
}
```

### 2.3 Complete Heading Styles Hierarchy

```csharp
// =============================================================================
// HEADING STYLES WITH PROPER INHERITANCE CHAIN
// =============================================================================
// Word's built-in heading system uses style inheritance:
// Normal (base) -> Heading1 -> Heading2 -> Heading3 -> Heading4 -> Heading5 -> Heading6
//
// Why this matters:
// - Each heading INHERITS from its parent (basedOn)
// - Define common properties in Normal, override in each heading
// - Change body font once in Normal, all headings inherit it
// - Heading-specific properties override as needed

// --- HEADING STYLE FACTORY ---
public static Style CreateHeadingStyle(int level, FontConfig fonts)
{
    // Validate level (1-9 are valid, 1-6 are standard)
    if (level < 1 || level > 9)
        throw new ArgumentOutOfRangeException(nameof(level));

    double[] headingSizes = [26.0, 20.0, 16.0, 14.0, 12.0, 11.0, 11.0, 11.0, 11.0];
    string[] outlineLevels = ["0", "1", "2", "3", "4", "5", "6", "7", "8"};

    var style = new Style(
        new StyleName { Val = $"heading {level}" },  // Display name
        new BasedOn { Val = level == 1 ? "Normal" : $"Heading{level - 1}" },  // Parent style
        new NextParagraphStyle { Val = "Normal" },   // After heading -> Normal
        new PrimaryStyle(),                          // Show in Styles gallery
        new UIPriority { Val = 9 - level },         // Priority in gallery (H1 = 8, H2 = 7, etc.)
        new QuickStyle(),                           // Appears in Quick Styles gallery
        // Paragraph properties: spacing, keep options, outline level
        new StyleParagraphProperties(
            new KeepNext(),                         // Keep heading with next paragraph
            new KeepLines(),                        // Keep all lines of heading together
            new SpacingBetweenLines                 // Spacing before/after
            {
                Before = level == 1 ? "480" : "240",  // H1 = 240pt before, others = 120pt
                After = "120"
            },
            new OutlineLevel { Val = level - 1 }   // 0-indexed for H1=0, H2=1, etc.
        ),
        // Run properties: font, size, bold
        new StyleRunProperties(
            new RunFonts
            {
                Ascii = fonts.HeadingFont,
                HighAnsi = fonts.HeadingFont,
                EastAsia = "SimHei"  // Bold heading font for CJK
            },
            new FontSize { Val = UnitConverter.FontSizeToSz(headingSizes[level - 1]) },
            new FontSizeComplexScript { Val = UnitConverter.FontSizeToSz(headingSizes[level - 1]) },
            new Bold(),
            new BoldComplexScript()
        )
    )
    {
        Type = StyleValues.Paragraph,
        StyleId = $"Heading{level}"
    };

    return style;
}

// --- ADD ALL HEADING STYLES TO STYLES COLLECTION ---
public static void AddHeadingStyles(Styles styles, FontConfig fonts)
{
    for (int i = 1; i <= 6; i++)
    {
        styles.Append(CreateHeadingStyle(i, fonts));
    }

    // Also add Heading 7-9 (valid in Word, less commonly used)
    for (int i = 7; i <= 9; i++)
    {
        styles.Append(CreateHeadingStyle(i, fonts));
    }
}

// --- HEADING STYLES INHERITANCE VISUALIZATION ---
// When you apply "Heading2" (basedOn="Heading1"):
//
// Normal style:
//   - Font: Calibri 11pt
//   - Spacing: 0 before, 200 after
//   - No bold
//
// Heading1 (basedOn="Normal"):
//   - Inherits: Calibri 11pt
//   - Overrides: Calibri Light 26pt, Bold, Spacing 480 before/120 after
//   - Adds: KeepNext, KeepLines, OutlineLevel=0
//
// Heading2 (basedOn="Heading1"):
//   - Inherits: Calibri Light 26pt, Bold, KeepNext, KeepLines
//   - Overrides: 20pt
//   - Inherits: OutlineLevel=1
//
// Effective result: Heading2 = Calibri Light 20pt Bold, KeepNext+KeepLines, 480/120 spacing, OL=1
```

### 2.4 Style Inheritance Chain Resolution

```csharp
// =============================================================================
// STYLE INHERITANCE RESOLUTION
// =============================================================================
// OpenXML styles resolve properties through the basedOn chain at RENDER TIME.
// The document.xml stores only the styleId, not the resolved properties.
// Word (or this library) walks the chain at load/display time.
//
// Example: Applying "Heading2" to a paragraph
//
// 1. Start with Heading2 style definition
// 2. Walk basedOn chain: Heading2 -> Heading1 -> Normal -> (null)
// 3. Collect properties in reverse order (most generic first):
//    a. Normal: Ascii=Calibri, sz=22, no bold
//    b. Heading1: Ascii=Calibri Light, sz=48, bold (override Calibri, sz, bold)
//    c. Heading2: sz=40 (override sz only)
// 4. Final resolved style: Ascii=Calibri Light, sz=40, bold (bold from H1)
//
// IMPORTANT: Style override is COMPLETE for each element type:
// - If Normal has rPr with Fonts, and Heading1 has pPr only,
//   Heading1 still inherits Normal's rPr fully.
// - StyleRunProperties (rPr) and StyleParagraphProperties (pPr) are separate.

// --- RESOLVING STYLE PROPERTIES MANUALLY ---
// For debugging or custom rendering, you may need to resolve style chains
public static class StyleResolver
{
    public record ResolvedStyle(
        StyleName? Name,
        RunProperties? RunProps,
        ParagraphProperties? ParaProps,
        string? BasedOn,
        string Type);

    public static ResolvedStyle Resolve(Styles styles, string styleId)
    {
        var styleMap = styles.Elements<Style>().ToDictionary(s => s.StyleId?.Value ?? "");

        var resolvedRpr = new List<RunProperties>();
        var resolvedPpr = new List<ParagraphProperties>();
        string? currentId = styleId;
        string? name = null;
        string type = "paragraph";

        // Walk the chain
        while (currentId != null && styleMap.TryGetValue(currentId, out var style))
        {
            name ??= style.Name?.Val?.Value;
            type = style.Type?.Value?.ToString() ?? "paragraph";

            // Collect rPr (style-level run properties)
            var rpr = style.StyleRunProperties;
            if (rpr != null) resolvedRpr.Add(rpr);

            // Collect pPr (style-level paragraph properties)
            var ppr = style.StyleParagraphProperties;
            if (ppr != null) resolvedPpr.Add(ppr);

            // Move to parent
            currentId = style.BasedOn?.Val?.Value;
        }

        // Merge in reverse order (base styles first, derived last)
        // This is a simplified merge — real Word merging is more complex
        var mergedRpr = MergeRunProperties(resolvedRpr);
        var mergedPpr = MergeParagraphProperties(resolvedPpr);

        return new ResolvedStyle(
            name != null ? new StyleName { Val = name } : null,
            mergedRpr,
            mergedPpr,
            styleId,
            type);
    }

    private static RunProperties MergeRunProperties(List<RunProperties> chain)
    {
        var merged = new RunProperties();
        // In real implementation, copy each child element from chain[0] first,
        // then chain[1], etc., overriding as you go
        foreach (var rpr in chain)
        {
            foreach (var child in rpr.ChildElements)
            {
                // Skip duplicates, keep derived class's version
                merged.RemoveAll(child.GetType());
                merged.Append(child.CloneNode(true));
            }
        }
        return merged;
    }

    private static ParagraphProperties MergeParagraphProperties(List<ParagraphProperties> chain)
    {
        var merged = new ParagraphProperties();
        foreach (var ppr in chain)
        {
            foreach (var child in ppr.ChildElements)
            {
                merged.RemoveAll(child.GetType());
                merged.Append(child.CloneNode(true));
            }
        }
        return merged;
    }
}

// --- STYLE ID VS STYLE NAME ---
// StyleId: the machine-readable identifier (used in w:pStyle val="Heading1")
// StyleName.Val: the display name shown in Word UI ("Heading 1")
//
// Word allows StyleId="Heading1" with StyleName.Val="Custom Heading One"
// The Id must be unique within the document; the Name can duplicate others.
//
// Built-in styles use specific Ids:
// "Normal", "Heading1"-"Heading9", "Title", "Subtitle", "Quote", "Quote1",
// "IntenseQuote", "SubtleReference", "Bibliography", "TOC1"-"TOC9", etc.
```

### 2.5 Complete Style Definitions Example

```csharp
// =============================================================================
// COMPLETE STYLE DEFINITIONS FOR A BUSINESS DOCUMENT
// =============================================================================
// This creates a complete styles.xml with all recommended styles for a
// professional document: Normal, Title, Subtitle, Headings 1-6, Quote,
// IntenseQuote, and linked character styles.

public static Styles CreateBusinessDocumentStyles()
{
    var styles = new Styles();

    // --- DOCDEFAULTS ---
    styles.Append(new DocDefaults(
        new RunPropertiesDefault(
            new RunPropertiesBaseStyle(
                new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
                new FontSize { Val = "22" },
                new FontSizeComplexScript { Val = "22" },
                new Languages { Val = "en-US" }
            )
        ),
        new ParagraphPropertiesDefault(
            new ParagraphPropertiesBaseStyle(
                new SpacingBetweenLines { After = "200", Line = "276", LineRule = LineSpacingRuleValues.Auto }
            )
        )
    ));

    // --- NORMAL STYLE (BASE FOR ALL) ---
    styles.Append(new Style(
        new StyleName { Val = "Normal" },
        new PrimaryStyle(),
        new UIPriority { Val = 10 },
        new Primary烙,
        new StyleRunProperties(
            new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
            new FontSize { Val = "22" },
            new FontSizeComplexScript { Val = "22" }
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });

    // --- TITLE STYLE ---
    styles.Append(new Style(
        new StyleName { Val = "Title" },
        new BasedOn { Val = "Normal" },
        new NextParagraphStyle { Val = "Normal" },
        new PrimaryStyle(),
        new UIPriority { Val = 1 },
        new QuickStyle(),
        new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center },
            new SpacingBetweenLines { After = "300", Line = "240", LineRule = LineSpacingRuleValues.Auto },
            new KeepNext(),
            new KeepLines()
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "Calibri Light", HighAnsi = "Calibri Light" },
            new FontSize { Val = "56" },      // 28pt
            new FontSizeComplexScript { Val = "56" },
            new Bold(),
            new BoldComplexScript(),
            new Color { Val = "1F497D" }     // Dark blue
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "Title" });

    // --- SUBTITLE STYLE ---
    styles.Append(new Style(
        new StyleName { Val = "Subtitle" },
        new BasedOn { Val = "Normal" },
        new NextParagraphStyle { Val = "Normal" },
        new PrimaryStyle(),
        new UIPriority { Val = 2 },
        new QuickStyle(),
        new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center },
            new SpacingBetweenLines { After = "200" },
            new KeepNext(),
            new KeepLines()
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
            new FontSize { Val = "26" },      // 13pt
            new Color { Val = "5A5A5A" }     // Gray
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "Subtitle" });

    // --- HEADING 1-6 STYLES ---
    AddHeadingStyles(styles);

    // --- QUOTE STYLES ---
    // Quote (indented, italic)
    styles.Append(new Style(
        new StyleName { Val = "Quote" },
        new BasedOn { Val = "Normal" },
        new NextParagraphStyle { Val = "Normal" },
        new PrimaryStyle(),
        new UIPriority { Val = 29 },
        new QuickStyle(),
        new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Both },
            new Indentation { Left = "720", Right = "720" },
            new SpacingBetweenLines { After = "160" },
            new KeepNext(),
            new KeepLines()
        ),
        new StyleRunProperties(
            new Italic(),
            new ItalicComplexScript()
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "Quote" });

    // Intense Quote (bold, larger indent)
    styles.Append(new Style(
        new StyleName { Val = "Intense Quote" },
        new BasedOn { Val = "Normal" },
        new NextParagraphStyle { Val = "Normal" },
        new PrimaryStyle(),
        new UIPriority { Val = 30 },
        new QuickStyle(),
        new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center },
            new Indentation { Left = "1440", Right = "1440" },
            new SpacingBetweenLines { After = "160" },
            new KeepNext(),
            new KeepLines(),
            new ParagraphBorders(
                new LeftBorder { Val = BorderValues.Single, Size = 24, Color = "4472C4", Space = 4 }
            )
        ),
        new StyleRunProperties(
            new Bold(),
            new Color { Val = "2F5496" }
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "IntenseQuote" });

    // --- LINKED CHARACTER STYLES ---
    // "Emphasis" linked character style (used for <Ctrl+E> in Word)
    styles.Append(new Style(
        new StyleName { Val = "Emphasis" },
        new PrimaryStyle(),
        new StyleRunProperties(
            new Italic()
        )
    )
    { Type = StyleValues.Character, StyleId = "Emphasis", Default = true });

    // "Strong" linked character style
    styles.Append(new Style(
        new StyleName { Val = "Strong" },
        new PrimaryStyle(),
        new StyleRunProperties(
            new Bold()
        )
    )
    { Type = StyleValues.Character, StyleId = "Strong", Default = true });

    // --- TOC STYLES (for Table of Contents) ---
    // TOC1-TOC9 are used by Word's TOC field for different heading levels
    styles.Append(new Style(
        new StyleName { Val = "TOC 1" },
        new BasedOn { Val = "Normal" },
        new Primary烙,
        new StyleParagraphProperties(
            new SpacingBetweenLines { After = "0" }
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "TOC1" });

    styles.Append(new Style(
        new StyleName { Val = "TOC 2" },
        new BasedOn { Val = "Normal" },
        new Primary烙,
        new StyleParagraphProperties(
            new Indentation { Left = "220" },
            new SpacingBetweenLines { After = "0" }
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "TOC2" });

    styles.Append(new Style(
        new StyleName { Val = "TOC 3" },
        new BasedOn { Val = "Normal" },
        new Primary烙,
        new StyleParagraphProperties(
            new Indentation { Left = "440" },
            new SpacingBetweenLines { After = "0" }
        )
    )
    { Type = StyleValues.Paragraph, StyleId = "TOC3" });

    return styles;
}

// --- ADDING STYLES TO A DOCUMENT ---
public static void AddStylesToDocument(WordprocessingDocument doc, Styles styles)
{
    var mainPart = doc.MainDocumentPart!;

    // Get existing or create new styles part
    var stylesPart = mainPart.StyleDefinitionsPart;
    if (stylesPart == null)
    {
        stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = styles;
    }
    else
    {
        // Clear and replace existing styles
        stylesPart.Styles?.RemoveAllChildren();
        stylesPart.Styles = styles;
    }
    stylesPart.Styles.Save();
}
```

### 2.6 Importing Styles from Another Document

```csharp
// =============================================================================
// IMPORTING STYLES FROM ANOTHER DOCUMENT
// =============================================================================
// Word's Organizer functionality allows copying styles between documents.
// This is useful for templates, branding, or style normalization.

public static class StyleImporter
{
    /// <summary>
    /// Imports styles from a source document into a target document.
    /// Can selectively import by type or name.
    /// </summary>
    public static void ImportStyles(
        WordprocessingDocument targetDoc,
        string sourcePath,
        bool overwriteExisting = false,
        Func<Style, bool>? filter = null)
    {
        // Open source as read-only
        using var sourceDoc = WordprocessingDocument.Open(sourcePath, isEditable: false);
        var sourceStylesPart = sourceDoc.MainDocumentPart?.StyleDefinitionsPart;
        if (sourceStylesPart?.Styles == null) return;

        var targetStylesPart = targetDoc.MainDocumentPart!.StyleDefinitionsPart;
        if (targetStylesPart == null)
        {
            targetStylesPart = targetDoc.MainDocumentPart.AddNewPart<StyleDefinitionsPart>();
            targetStylesPart.Styles = new Styles();
        }

        var targetStyles = targetStylesPart.Styles!;
        var existingIds = targetStyles.Elements<Style>()
            .Select(s => s.StyleId?.Value ?? "")
            .ToHashSet();

        foreach (var sourceStyle in sourceStylesPart.Styles.Elements<Style>())
        {
            // Apply filter if provided
            if (filter != null && !filter(sourceStyle))
                continue;

            var styleId = sourceStyle.StyleId?.Value ?? "";
            if (string.IsNullOrEmpty(styleId)) continue;

            // Skip if exists and not overwriting
            if (existingIds.Contains(styleId) && !overwriteExisting)
                continue;

            // Clone the style (deep copy to avoid shared part issues)
            var clonedStyle = (Style)sourceStyle.CloneNode(true);

            // If overwriting, remove existing first
            if (existingIds.Contains(styleId))
            {
                var existing = targetStyles.Elements<Style>()
                    .FirstOrDefault(s => s.StyleId?.Value == styleId);
                existing?.Remove();
            }

            targetStyles.Append(clonedStyle);
            existingIds.Add(styleId);
        }

        targetStylesPart.Styles.Save();
    }

    /// <summary>
    /// Imports only heading styles from source.
    /// </summary>
    public static void ImportHeadingStyles(WordprocessingDocument targetDoc, string sourcePath)
    {
        ImportStyles(
            targetDoc,
            sourcePath,
            overwriteExisting: true,
            filter: style => style.Name?.Val?.Value?.StartsWith("heading") == true ||
                            style.Name?.Val?.Value?.StartsWith("Heading") == true);
    }

    /// <summary>
    /// Imports all paragraph styles (not character, table, or numbering).
    /// </summary>
    public static void ImportParagraphStyles(WordprocessingDocument targetDoc, string sourcePath)
    {
        ImportStyles(
            targetDoc,
            sourcePath,
            overwriteExisting: false,
            filter: style => style.Type?.Value == StyleValues.Paragraph);
    }
}
```

---

## 3. Character Formatting (RunProperties) — EXHAUSTIVE

```csharp
// =============================================================================
// RUN PROPERTIES (CHARACTER FORMATTING) — COMPLETE REFERENCE
// =============================================================================
// RunProperties (w:rPr) controls inline text formatting. It can appear in:
// 1. Style definitions (w:style/w:rPr) — applies to all text using that style
// 2. Direct formatting in runs (w:r/w:rPr) — overrides style for specific text
//
// CHILD ELEMENT ORDER (w:rPr): MUST be in this order per OpenXML schema:
// rStyle, rFonts, b, bCs, i, iCs, caps, smallCaps, strike, dstrike, vanish,
// w:webHidden, color, sz, szCs, highlight, rendition/sz, u, vertAlign, shd,
// baseTextStyle, eastAsianLayout, ligatures, bg, kern, spc, indent, snapToGrid,
// glyphs, activeXfrm, legacy, specStyle, shadow, charsetConvert, iFormat,
// w:templ

// --- MINIMAL RUN WITH FORMATTING ---
// Any run can contain RunProperties to control appearance
Paragraph minimalFormattedPara = new Paragraph(
    new Run(
        new RunProperties(
            new Bold(),
            new FontSize { Val = "28" }  // 14pt (28 half-pts)
        ),
        new Text("Bold 14pt text")
    )
);

// ===========================================================================
// 3.1 RUNFONTS (Ascii, HighAnsi, EastAsia, ComplexScript)
// ===========================================================================
// RunFonts has 4 font "slots" for different scripts. Word uses fallback:
// ASCII -> HighAnsi -> EastAsia -> ComplexScript
// IMPORTANT: Always set at least Ascii and HighAnsi (they're often the same).

// Basic font specification
RunProperties fonts1 = new RunProperties(
    new RunFonts
    {
        Ascii = "Calibri",           // Western European characters (primary)
        HighAnsi = "Calibri",        // Same as ASCII for Western docs
        EastAsia = "SimSun",         // Simplified Chinese / East Asian
        ComplexScript = "Arial"     // Arabic, Hebrew, Thai, Vietnamese
    }
);

// Using theme fonts (references to theme definitions)
RunProperties themeFonts = new RunProperties(
    new RunFonts
    {
        ASCIITheme = ThemeFontValues.Minor,     // Minor font from theme (body)
        HighAnsiTheme = ThemeFontValues.Minor,
        EastAsiaTheme = ThemeFontValues.Major, // Major font from theme (headings)
        ComplexScriptTheme = ThemeFontValues.Minor,
        // When using theme, you can still override specific slots
        Ascii = "Calibri", HighAnsi = "Calibri"  // Override minor with explicit font
    }
);

// Complex script fonts (Arabic example)
RunProperties arabicFonts = new RunProperties(
    new RunFonts
    {
        ComplexScript = "Traditional Arabic",
        // Word automatically handles Arabic shaping with complex script fonts
    }
);

// East Asian with specific fallback
RunProperties cjkFonts = new RunProperties(
    new RunFonts
    {
        Ascii = "Microsoft YaHei",    // Western: Microsoft YaHei for Chinese
        HighAnsi = "Microsoft YaHei",
        EastAsia = "Microsoft YaHei", // East Asian: same font handles both
        ComplexScript = "Microsoft YaHei"
    }
);

// Font substitution hints (rarely needed, for special cases)
RunProperties hintFonts = new RunProperties(
    new RunFonts
    {
        Ascii = "Times New Roman",
        HighAnsi = "Times New Roman",
        Hint = FontStringsValues.EastAsia  // Hint to Word: treat as East Asian font
    }
);

// ===========================================================================
// 3.2 FONTSIZE (sz, szCs) — HALF-POINTS!
// ===========================================================================
// CRITICAL: w:sz stores HALF-POINTS. 24 = 12pt, 48 = 24pt.
// szCs = complex script size (for Arabic, Hebrew, etc.)

// Common font sizes
RunProperties fontSize12pt = new RunProperties(
    new FontSize { Val = "24" },              // 12pt = 24 half-pts
    new FontSizeComplexScript { Val = "24" }
);

RunProperties fontSize14pt = new RunProperties(
    new FontSize { Val = "28" },              // 14pt
    new FontSizeComplexScript { Val = "28" }
);

RunProperties fontSize18pt = new RunProperties(
    new FontSize { Val = "36" },              // 18pt
    new FontSizeComplexScript { Val = "36" }
);

RunProperties fontSize24pt = new RunProperties(
    new FontSize { Val = "48" },              // 24pt
    new FontSizeComplexScript { Val = "48" }
);

// FontSize from double (helper)
double targetPt = 11.0;
int halfPts = (int)(targetPt * 2);  // 22 for 11pt
RunProperties dynamicFontSize = new RunProperties(
    new FontSize { Val = halfPts.ToString() },
    new FontSizeComplexScript { Val = halfPts.ToString() }
);

// Legacy font size (some documents use csSize instead)
// csSize = complex script size only

// ===========================================================================
// 3.3 BOLD (b, bCs, b, bCs)
// ===========================================================================
// b = bold for ASCII/Latin
// bCs = bold for complex script
// Both should usually be set together

RunProperties bold = new RunProperties(
    new Bold(),
    new BoldComplexScript()  // Always include both for consistent rendering
);

// Bold with state control (on/off)
RunProperties unbold = new RunProperties(
    new Bold { Val = OnOffValueValues.Off }  // Explicitly turn off bold
);

// Conditional bold (for complex scripts)
// b={} with val=Off actually means "not bold" even if parent style says bold
// This is how you "unbold" in a bold context

// ===========================================================================
// 3.4 ITALIC (i, iCs)
// ===========================================================================
RunProperties italic = new RunProperties(
    new Italic(),
    new ItalicComplexScript()
);

RunProperties unitalic = new RunProperties(
    new Italic { Val = OnOffValueValues.Off }
);

// Word's "Italic" is the style. ComplexScript italic handles Arabic calligraphy etc.

// ===========================================================================
// 3.5 UNDERLINE (u)
// ===========================================================================
// UnderlineValues enum has MANY options:
// Single, Double, Thick, Wave, Dash, Dotted, DashDot, DashDotDot,
// SingleAccounting, DoubleAccounting, TriWave, Nasized, DotDash, DotDotDash,
// LongDash, ThickDash, LongDashDot, ThickLongDash, ThickDashDot, ThickDashDotDot

// Single underline (most common)
RunProperties underlineSingle = new RunProperties(
    new Underline { Val = UnderlineValues.Single }
);

// Double underline (often for edits/changes)
RunProperties underlineDouble = new RunProperties(
    new Underline { Val = UnderlineValues.Double }
);

// Thick single underline
RunProperties underlineThick = new RunProperties(
    new Underline { Val = UnderlineValues.Thick }
);

// Wave underline (often used for spelling errors in red)
RunProperties underlineWave = new RunProperties(
    new Underline { Val = UnderlineValues.Wave }
);

// Dotted underline
RunProperties underlineDotted = new RunProperties(
    new Underline { Val = UnderlineValues.Dotted }
);

// Dashed underline
RunProperties underlineDashed = new RunProperties(
    new Underline { Val = UnderlineValues.Dash }
);

// Dash-dot underline
RunProperties underlineDashDot = new RunProperties(
    new Underline { Val = UnderlineValues.DotDash }
);

// Accounting double underline (extends to both sides like accounting)
RunProperties underlineAccounting = new RunProperties(
    new Underline { Val = UnderlineValues.DoubleAccounting }
);

// With color specification
RunProperties underlineColored = new RunProperties(
    new Underline { Val = UnderlineValues.Single, Color = "FF0000" }  // Red underline
);

// Without color (color="auto" = black)
// With specific color using hex
RunProperties underlineBlue = new RunProperties(
    new Underline { Val = UnderlineValues.Single, Color = "0000FF" }
);

// Theme color on underline
RunProperties underlineThemeColor = new RunProperties(
    new Underline
    {
        Val = UnderlineValues.Single,
        Color = "auto",  // or omit for auto/black
        ThemeColor = ThemeColorValues.Accent1,
        ThemeTint = "99"  // 60% opacity (hex 99 = 153/255 ≈ 60%)
    }
);

// Turn off underline (in a underlined context)
RunProperties noUnderline = new RunProperties(
    new Underline { Val = UnderlineValues.None }
);

// ===========================================================================
// 3.6 COLOR (color)
// ===========================================================================
// Color.Val is a 6-digit hex color (RRGGBB) WITHOUT the #
// Word also supports 8-digit (AARRGGBB) for transparency

// Basic color
RunProperties redText = new RunProperties(
    new Color { Val = "FF0000" }  // Pure red
);

RunProperties blueText = new RunProperties(
    new Color { Val = "0070C0" }  // Office blue
);

// Theme colors (references to document theme)
RunProperties themeColorText = new RunProperties(
    new Color
    {
        Val = "FFFFFF",  // Fallback
        ThemeColor = ThemeColorValues.Accent1,
        ThemeShade = "BF",  // 75% darker (hex BF = 191/255 ≈ 75%)
        ThemeTint = "99"    // 60% lighter (hex 99 = 153/255 ≈ 60%)
    }
);

// Theme color shorthand
RunProperties accent1Text = new RunProperties(
    new Color { Val = "4472C4" }  // Direct hex is often simpler
);

// With transparency (alpha channel, 8-digit hex)
// AA=fully transparent, FF=fully opaque
RunProperties transparentText = new RunProperties(
    new Color { Val = "80FF0000" }  // 50% transparent red (AA=half, FF=red)
);

// ===========================================================================
// 3.7 HIGHLIGHT (highlight)
// ===========================================================================
// Highlight is a BACKGROUND color applied to the entire run.
// Different from Shading (which is in run properties too).
// Highlight enum values: DarkYellow, Yellow, Green, Cyan, Magenta, Blue,
// DarkBlue, DarkCyan, DarkGreen, DarkMagenta, DarkRed, DarkYellow, LightGray,
// LightGreen, LightOrange, LightPurple, LightRed, LightYellow, Navy, None,
// Orange, Pink, Purple, Red, Teal, Turquoise, Yellow

// Yellow highlight (default for comments)
RunProperties yellowHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.Yellow }
);

// Green highlight (for insertions)
RunProperties greenHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.Green }
);

// Red highlight (for deletions)
RunProperties redHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.Red }
);

// Blue highlight
RunProperties blueHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.Blue }
);

// Cyan highlight (for feedback)
RunProperties cyanHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.Cyan }
);

// Gray highlight (for search)
RunProperties grayHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.LightGray }
);

// No highlight (turn off)
RunProperties noHighlight = new RunProperties(
    new Highlight { Val = HighlightValues.None }
);

// ===========================================================================
// 3.8 STRIKETHROUGH (strike, dstrike)
// ===========================================================================
// strike = single strikethrough
// dstrike = double strikethrough

// Single strikethrough (standard)
RunProperties strikethrough = new RunProperties(
    new Strikethrough()
);

// Double strikethrough (often for legal/editing)
RunProperties doubleStrikethrough = new RunProperties(
    new DoubleStrike()
);

// Turn off strikethrough
RunProperties noStrikethrough = new RunProperties(
    new Strikethrough { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 3.9 SUBSCRIPT/SUPERSCRIPT (verticalAlign)
// ===========================================================================
// VerticalTextAlignment enum: Baseline (normal), Subscript, Superscript
// Subscript: lowers the text and reduces size
// Superscript: raises the text and reduces size

// Superscript (e.g., 2 in X²)
RunProperties superscript = new RunProperties(
    new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
);

// Subscript (e.g., 2 in H₂O)
RunProperties subscript = new RunProperties(
    new VerticalTextAlignment { Val = VerticalPositionValues.Subscript }
);

// Baseline (normal) — explicit
RunProperties baseline = new RunProperties(
    new VerticalTextAlignment { Val = VerticalPositionValues.Baseline }
);

// ===========================================================================
// 3.10 CAPS / ALLCAPS / SMALLCAPS (caps, smallCaps)
// ===========================================================================
// caps = ALL CAPS (converts lowercase to uppercase visually)
// smallCaps = Small Caps (converts lowercase to uppercase but with smaller font)

// ALL CAPS (visual only, underlying text unchanged)
RunProperties allCaps = new RunProperties(
    new Caps()
);

// Small Caps (lowercase appears as smaller uppercase letters)
RunProperties smallCaps = new RunProperties(
    new SmallCaps()
);

// Both properties together (smallcaps takes precedence visually if both set)
RunProperties emphasisCaps = new RunProperties(
    new SmallCaps(),
    new Caps()
);

// Turn off caps
RunProperties noCaps = new RunProperties(
    new Caps { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 3.11 SPACING / KERNING (spacing)
// ===========================================================================
// Spacing.Val is in TWIPS (1/20 of a point, same as DXA)
// Positive = add space, Negative = remove space
// Range: -240 to +240 twips typically

// Add space between characters (letter spacing / kerning)
RunProperties expandedSpacing = new RunProperties(
    new Spacing
    {
        Val = 100,  // +100 twips = +5pt of space between characters
        // Space "100" = 5 points (100/20 = 5)
    }
);

// Compress characters
RunProperties compressedSpacing = new RunProperties(
    new Spacing
    {
        Val = -50,  // -50 twips = -2.5pt (characters closer together)
    }
);

// Normal spacing (remove any spacing adjustments)
RunProperties normalSpacing = new RunProperties(
    new Spacing { Val = 0 }
);

// Combined with other properties
RunProperties spacedBold = new RunProperties(
    new Spacing { Val = 50 },
    new Bold()
);

// ===========================================================================
// 3.12 POSITION (position) — RAISED/LOWERED TEXT
// ===========================================================================
// Position.Val is in HALF-POINTS (not DXA!)
// Positive = raise, Negative = lower
// Range: -1584 to +1584 half-pts (-792pt to +792pt!)

// Raise text 6pt (12 half-points)
RunProperties raised = new RunProperties(
    new Position
    {
        Val = 12  // +12 half-pts = +6pt raised
    }
);

// Lower text 3pt
RunProperties lowered = new RunProperties(
    new Position
    {
        Val = -6  // -6 half-pts = -3pt lowered
    }
);

// Position is often used for:
 // - Footnote references
// - Baseline alignment adjustments
// - Mathematical subscripts/superscripts (though verticalAlign is better for these)

// ===========================================================================
// 3.13 TEXT EFFECTS (textEffect)
// ===========================================================================
// TextEffectValues: shimmer, blinkBackground, etc.
// These are decorative effects for special visual emphasis

// Shimmer effect (sparkle/light animation)
RunProperties shimmerEffect = new RunProperties(
    new TextEffect
    {
        Val = TextEffectValues.Shimmer
    }
);

// Blink background effect
RunProperties blinkEffect = new RunProperties(
    new TextEffect
    {
        Val = TextEffectValues.BlinkBackground
    }
);

// Anti-alias effect (smoother text rendering)
// (usually applied via document settings, not per-run)

// ===========================================================================
// 3.14 SHADING ON RUNS (shd)
// ===========================================================================
// Shading on a run applies a background color/pattern to the text background
// Different from Highlight: Shading uses pattern fills, Highlight is solid colors

// Solid fill shading (run background color)
RunProperties shadedRun = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,  // Clear = solid color
        Color = "auto",                     // auto = no border
        Fill = "FFFF00"                     // Yellow background
    }
);

// Horizontal line pattern shading
RunProperties hLineShading = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.HorizontalLine,  // Horizontal line pattern
        Color = "0000FF",
        Fill = "FFFF00"
    }
);

// Reverse pattern (for special effects)
RunProperties reverseShading = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.ReverseDiagonalStripe,
        Color = "auto",
        Fill = "E0E0E0"
    }
);

// Clear shading (remove)
RunProperties noShading = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Fill = "auto"
    }
);

// Thatch pattern (diagonal lines, like legal document)
RunProperties thatchShading = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.Thatch,
        Color = "000000",
        Fill = "FFFFFF"
    }
);

// Common shading patterns:
// Clear, Solid, HorizStripe, VertStripe, RevDiagStripe, DiagCross, DiagStripe,
// ReverseDiagStripe, DiagHorizCross, ThinHorzStripe, ThinVertStripe,
// ThinReverseDiagStripe, ThinDiagStripe, ThinDiagHorzCross, ThickHorzStripe,
// ThickVertStripe, ThickDiagStripe, ThickDiagCross, ThickReverseDiagStripe,
// ThickDiagonalCross, Shingle, ThickSmallCheck, SmallCheck, LargeCheck,
// SmallConfetti, Confetti, Horizontal, Diagonal, BigConfetti, ZigZag

// ===========================================================================
// 3.15 RUN STYLE (rStyle) — APPLY CHARACTER STYLE
// ===========================================================================
// RunStyle applies a character style to a run
// The style must be defined in styles.xml first

// Apply character style by ID
RunProperties styledRun = new RunProperties(
    new RunStyle { Val = "Emphasis" }  // References a character style
);

// Combined with direct formatting (direct overrides style)
RunProperties styledWithOverride = new RunProperties(
    new RunStyle { Val = "Emphasis" },
    new Bold { Val = OnOffValueValues.Off }  // Override: don't make it bold
);

// ===========================================================================
// 3.16 BORDER ON RUNS (rPr/bdr)
// ===========================================================================
// Run borders apply a border around individual characters (rarely used)

// WordArt-style character border
RunProperties borderedRun = new RunProperties(
    new CharacterBorder(
        new TopBorder { Val = BorderValues.Single, Size = 4, Color = "0000FF", Space = 1 },
        new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "0000FF", Space = 1 },
        new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "0000FF", Space = 1 },
        new RightBorder { Val = BorderValues.Single, Size = 4, Color = "0000FF", Space = 1 }
    )
);

// Single border (typically used)
RunProperties borderTop = new RunProperties(
    new CharacterBorder(
        new TopBorder { Val = BorderValues.Single, Size = 8, Color = "FF0000" }
    )
);

// ===========================================================================
// 3.17 VANISH / HIDDEN TEXT (vanish, webHidden)
// ===========================================================================
// vanish = hidden in both UI and print (like hidden field codes)
// webHidden = hidden in web layout view

// Hidden text (doesn't appear in UI or print)
RunProperties hiddenText = new RunProperties(
    new Vanish()
);

// Hidden in web view only
RunProperties webHiddenText = new RunProperties(
    new WebHidden()
);

// Both combined
RunProperties hiddenBothViews = new RunProperties(
    new Vanish(),
    new WebHidden()
);

// Turn off hide (in a hidden context)
RunProperties visible = new RunProperties(
    new Vanish { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 3.18 RIGHT-TO-LEFT (bidi)
// ===========================================================================
// For bidirectional text (Arabic, Hebrew)

// Right-to-left text
RunProperties rtlRun = new RunProperties(
    new RightToLeftText()
);

// Normal direction
RunProperties ltrRun = new RunProperties(
    new RightToLeftText { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 3.19 LIGATURES (ligatures)
// ===========================================================================
// Ligatures combine adjacent characters for typography (fi, fl, ff, etc.)
// Standard=0 means no ligatures, Standard=1 means common ligatures

// Standard ligatures (fi, fl, ff, ffi, ffl)
RunProperties standardLigatures = new RunProperties(
    new Ligatures { Val = 1 }  // Standard ligatures on
);

// No ligatures
RunProperties noLigatures = new RunProperties(
    new Ligatures { Val = 0 }
);

// Historical ligatures (old-style, for fonts that support them)
RunProperties historicalLigatures = new RunProperties(
    new Ligatures { Val = 2 }  // Historical
);

// ===========================================================================
// 3.20 COMPLEX SCRIPT PROPERTIES (cs, csBdr, csShd, etc.)
// ===========================================================================
// Complex script properties mirror the ASCII properties but for
// complex scripts (Arabic, Hebrew, Thai, etc.)

// Complex script bold
RunProperties csBold = new RunProperties(
    new Bold(),
    new BoldComplexScript()
);

// Complex script italic
RunProperties csItalic = new RunProperties(
    new Italic(),
    new ItalicComplexScript()
);

// Complex script underline
RunProperties csUnderline = new RunProperties(
    new Underline { Val = UnderlineValues.Single },
    new UnderlineComplexScript { Val = UnderlineValues.Single }
);

// Complex script border
RunProperties csBorder = new RunProperties(
    new CharacterBorder(
        new TopBorder { Val = BorderValues.Single, Size = 4, Color = "000080" }
    )
);

// Complex script shading
RunProperties csShading = new RunProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "E6E6E6"
    }
);

// ===========================================================================
// 3.21 LANGUAGE (lang) — HYPHENATION/SPELL CHECK
// ===========================================================================
// Language determines hyphenation, spell-check dictionary, etc.

// English (US)
RunProperties enUsText = new RunProperties(
    new Languages { Val = "en-US" }
);

// English (UK)
RunProperties enGbText = new RunProperties(
    new Languages { Val = "en-GB" }
);

// French
RunProperties frenchText = new RunProperties(
    new Languages { Val = "fr-FR" }
);

// German
RunProperties germanText = new RunProperties(
    new Languages { Val = "de-DE" }
);

// Chinese (Simplified)
RunProperties chineseText = new RunProperties(
    new Languages { Val = "zh-CN" }
);

// Japanese
RunProperties japaneseText = new RunProperties(
    new Languages { Val = "ja-JP" }
);

// Arabic
RunProperties arabicText = new RunProperties(
    new Languages { Val = "ar-SA" }
);

// Hebrew
RunProperties hebrewText = new RunProperties(
    new Languages { Val = "he-IL" }
);

// No language (apply directly)
RunProperties noLangText = new RunProperties(
    new Languages { Val = "" }
);

// ===========================================================================
// 3.22 KERNING (kern)
// ===========================================================================
// Kern adjusts character spacing based on character pairs
// Value is in hundredths of a point (100 = 1pt)

// Enable kerning
RunProperties kerning = new RunProperties(
    new Kern { Val = 20 }  // 20 = 0.2pt minimum kerning threshold
);

// Disable kerning
RunProperties noKerning = new RunProperties(
    new Kern { Val = 0 }
);

// Standard document kerning
RunProperties standardKerning = new RunProperties(
    new Kern { Val = 12 }  // 12 = 0.12pt
);

// ===========================================================================
// 3.23 SNAP TO GRID (snapToGrid)
// ===========================================================================
// SnapToGrid aligns characters to a document grid for consistent line spacing

// Enable snap to grid
RunProperties snapToGrid = new RunProperties(
    new SnapToGrid()
);

// Disable snap to grid
RunProperties noSnapToGrid = new RunProperties(
    new SnapToGrid { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 3.24 COMBINED RUN FORMATTING EXAMPLE
// ===========================================================================
// Complete run properties combining many options

RunProperties complexRunProps = new RunProperties(
    // Style reference (should be first per schema)
    new RunStyle { Val = "Emphasis" },

    // Font
    new RunFonts
    {
        Ascii = "Georgia",
        HighAnsi = "Georgia",
        EastAsia = "SimSun"
    },

    // Bold + Bold Complex Script
    new Bold(),
    new BoldComplexScript(),

    // Italic + Italic Complex Script
    new Italic(),
    new ItalicComplexScript(),

    // Underline
    new Underline { Val = UnderlineValues.Single, Color = "000080" },

    // Font size (14pt)
    new FontSize { Val = "28" },
    new FontSizeComplexScript { Val = "28" },

    // Color
    new Color { Val = "000080" },  // Navy blue

    // Language
    new Languages { Val = "en-US" },

    // Spacing (slightly expanded)
    new Spacing { Val = 50 },

    // Small caps
    new SmallCaps(),

    // Highlight
    new Highlight { Val = HighlightValues.LightGray },

    // Shadow (decorative)
    new Shadow()
);

// ===========================================================================
// 3.25 APPLYING RUN PROPERTIES TO RUNS
// ===========================================================================
// RunProperties can be applied in multiple ways:

// Method 1: Inline in Run (direct formatting)
Paragraph inlineFormatting = new Paragraph(
    new Run(
        new RunProperties(
            new Bold(),
            new Color { Val = "FF0000" }
        ),
        new Text("This is bold red text")
    )
);

// Method 2: Via RunStyle (character style)
Paragraph styleFormatting = new Paragraph(
    new Run(
        new RunStyle { Val = "MyCharStyle" },
        new Text("This uses the MyCharStyle character style")
    )
);

// Method 3: Mix (direct overrides style)
Paragraph mixedFormatting = new Paragraph(
    new Run(
        new RunProperties(
            new RunStyle { Val = "Emphasis" },  // Apply style first
            new Bold { Val = OnOffValueValues.Off }  // Override: unbold
        ),
        new Text("Emphasis style but not bold")
    )
);

// Method 4: Empty RunProperties to clear formatting
Paragraph clearedFormatting = new Paragraph(
    new Run(
        new RunProperties(
            new Bold { Val = OnOffValueValues.Off },
            new Italic { Val = OnOffValueValues.Off },
            new Underline { Val = UnderlineValues.None },
            new Color { Val = "000000" },
            new FontSize { Val = "22" }
        ),
        new Text("Manually reset to defaults")
    )
);
```

---

## 4. Paragraph Formatting (ParagraphProperties) — EXHAUSTIVE

```csharp
// =============================================================================
// PARAGRAPH FORMATTING (PARAGRAPHPROPERTIES) — COMPLETE REFERENCE
// =============================================================================
// ParagraphProperties (w:pPr) controls paragraph-level formatting. It can appear in:
// 1. Style definitions (w:style/w:pPr) — applies to all paragraphs using that style
// 2. Direct formatting in paragraphs (w:p/w:pPr) — overrides style for specific paragraphs
//
// CHILD ELEMENT ORDER (w:pPr): MUST be in this order per OpenXML schema:
// pStyle, keepNext, keepLines, pageBreakBefore, widowControl, numPr, pBdr,
// shd, tabs, suppressAutoHyphens, spacing, ind, contextualSpacing,
// mirrorIndents, oMath, textDirection, textAlignment, textboxTightWrap,
// outlineLvl, divId, cnfStyle, rPr, sectPr, pPrChange
//
// CRITICAL: sectPr must be LAST child of w:body, but LAST BUT ONE in w:pPr context.
// In body, sectPr defines section properties. In pPr, sectPr defines section break before paragraph.

// ===========================================================================
// 4.1 JUSTIFICATION / ALIGNMENT (jc)
// ===========================================================================
// JustificationValues enum: Left, Center, Right, Both (Justify), Distribute,
// ThaiDistribute, Justified (same as Both in most cases)

// Left justification (default for LTR languages)
ParagraphProperties justifyLeft = new ParagraphProperties(
    new Justification { Val = JustificationValues.Left }
);

// Center justification
ParagraphProperties justifyCenter = new ParagraphProperties(
    new Justification { Val = JustificationValues.Center }
);

// Right justification (common in Arabic/Hebrew documents)
ParagraphProperties justifyRight = new ParagraphProperties(
    new Justification { Val = JustificationValues.Right }
);

// Both/Justify (stretches lines to fill width — standard for books/newspapers)
ParagraphProperties justifyBoth = new ParagraphProperties(
    new Justification { Val = JustificationValues.Both }
);

// Distribute (each line individually stretched to fill — no ragging)
// Often used in Asian typography
ParagraphProperties justifyDistribute = new ParagraphProperties(
    new Justification { Val = JustificationValues.Distribute }
);

// ThaiDistribute (special handling for Thai script)
ParagraphProperties justifyThaiDistribute = new ParagraphProperties(
    new Justification { Val = JustificationValues.ThaiDistribute }
);

// Center justification on a line (for titles)
Paragraph titlePara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center }
    ),
    new Run(new Text("Centered Title"))
);

// ===========================================================================
// 4.2 INDENTATION (ind)
// ===========================================================================
// All indentation values in DXA (1 inch = 1440 DXA, 1 cm ≈ 567 DXA)
// Positive = indent rightward, Negative = indent leftward
//
// Left/Right: from page edge
// FirstLine: extra indent for first line (positive = indent right, negative = outdent)
// Hanging: amount to "hang" first line (negative moves first line left of body)
// FirstLineChars: CJK-specific, specifies in character counts

// Basic left indent (1 inch from left edge)
ParagraphProperties indentLeft1Inch = new ParagraphProperties(
    new Indentation { Left = "1440" }  // 1440 DXA = 1 inch
);

// Left indent with hanging first line (negative FirstLine)
ParagraphProperties hangingIndent = new ParagraphProperties(
    new Indentation
    {
        Left = "720",           // Body starts 0.5 inch from left
        FirstLine = "-720"      // First line aligns with body start
    }
);

// FirstLine positive (first line indented more than body)
ParagraphProperties firstLineIndent = new ParagraphProperties(
    new Indentation
    {
        Left = "1440",          // Body at 1 inch
        FirstLine = "720"       // First line at 1.5 inch (additional 0.5 inch)
    }
);

// Right indent
ParagraphProperties indentRight = new ParagraphProperties(
    new Indentation { Right = "1440" }  // 1 inch from right edge
);

// Both left and right indent (centered block)
ParagraphProperties blockIndent = new ParagraphProperties(
    new Indentation
    {
        Left = "1440",   // 1 inch from left
        Right = "1440"   // 1 inch from right
    }
);

// Hanging indent (classic for bibliographies, numbered lists)
// First line hangs to the left of the body
ParagraphProperties hangingIndent720 = new ParagraphProperties(
    new Indentation
    {
        Left = "1440",           // Body indent = 1 inch
        Hanging = "720"          // First line hangs 0.5 inch to the left of body
    }
);

// Outdent (first line starts BEFORE body start)
ParagraphProperties outdent = new ParagraphProperties(
    new Indentation
    {
        Left = "720",            // Body at 0.5 inch
        FirstLine = "-720"       // First line at 0 (page edge)
    }
);

// Line-specific: negative left indent (pull into margin)
ParagraphProperties negativeIndent = new ParagraphProperties(
    new Indentation { Left = "-720" }  // 0.5 inch into left margin
);

// CJK FirstLineChars (character-based first line indent)
// This converts character count to DXA based on font metrics
ParagraphProperties cjkFirstLine = new ParagraphProperties(
    new Indentation
    {
        Left = "567",            // Body at 1 cm
        FirstLineChars = 200     // 2 characters extra indent (200 = 2 chars × 100)
    }
);

// CJK HangingChars
ParagraphProperties cjkHanging = new ParagraphProperties(
    new Indentation
    {
        Left = "567",
        HangingChars = 100       // 1 character hanging
    }
);

// ===========================================================================
// 4.3 SPACING BETWEEN LINES (spacing)
// ===========================================================================
// SpacingBetweenLines has multiple attributes:
// Before: space above paragraph in DXA
// After: space below paragraph in DXA
// Line: line height (in DXA for Exact/AtLeast, or value×240 for Auto)
// LineRule: Auto (multiple of single), Exact (fixed DXA), AtLeast (minimum DXA)
//
// Special Line values for Auto:
// 240 = single spacing
// 360 = 1.5 line spacing
// 480 = double spacing
// 120 = half spacing (rare)
// For other multiples: Line = (desired spacing in points) × 20

// Space before only
ParagraphProperties spaceBefore = new ParagraphProperties(
    new SpacingBetweenLines { Before = "240" }  // 240 DXA = 12pt before
);

// Space after only
ParagraphProperties spaceAfter = new ParagraphProperties(
    new SpacingBetweenLines { After = "200" }  // 200 DXA = 10pt after
);

// Both before and after
ParagraphProperties spaceBoth = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Before = "120",
        After = "120"
    }
);

// SINGLE LINE SPACING (Auto rule)
ParagraphProperties singleSpacing = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Line = "240",
        LineRule = LineSpacingRuleValues.Auto  // 240 = 1.0× line height
    }
);

// DOUBLE LINE SPACING
ParagraphProperties doubleSpacing = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Line = "480",
        LineRule = LineSpacingRuleValues.Auto  // 480 = 2.0× line height
    }
);

// 1.5 LINE SPACING
ParagraphProperties oneAndHalfSpacing = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Line = "360",
        LineRule = LineSpacingRuleValues.Auto  // 360 = 1.5× line height
    }
);

// EXACT LINE HEIGHT (fixed height, regardless of content)
ParagraphProperties exactLineHeight = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Line = "360",            // 360 DXA = 18pt
        LineRule = LineSpacingRuleValues.Exact  // Exactly 18pt, even if text overflows
    }
);

// AT-LEAST LINE HEIGHT (minimum, grows if needed)
ParagraphProperties atLeastLineHeight = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Line = "288",            // At least 14.4pt
        LineRule = LineSpacingRuleValues.AtLeast  // At least 14.4pt, more if content requires
    }
);

// LINE SPACING WITH SPACE BEFORE/AFTER
ParagraphProperties paragraphWithSpacing = new ParagraphProperties(
    new SpacingBetweenLines
    {
        Before = "480",          // 24pt before (for heading paragraphs)
        After = "240",           // 12pt after
        Line = "276",            // 1.15× line spacing
        LineRule = LineSpacingRuleValues.Auto
    }
);

// SPACE BETWEEN LINES EXPLAINED:
// LineRule = Auto:
//   - Line value is a multiple of 240 (single spacing = 240)
//   - Word multiplies by the font size to get actual line height
//   - Example: Line="360" with 11pt font = 11pt × 1.5 = 16.5pt actual
//   - Most common setting for body text
//
// LineRule = Exact:
//   - Line value is in DXA directly
//   - Line="360" = exactly 18pt, period
//   - Text that exceeds will overflow
//   - Used for fixed-height rows in tables
//
// LineRule = AtLeast:
//   - Line value is minimum in DXA
//   - Line="288" = at least 14.4pt, grows if text is taller
//   - Used when you need minimum spacing but content varies

// ===========================================================================
// 4.4 KEEP OPTIONS (keepNext, keepLines, widowControl)
// ===========================================================================
// These control how paragraphs interact with page breaks

// KEEP NEXT: Keep this paragraph on same page as the following paragraph
// Essential for headings (don't separate heading from first paragraph)
ParagraphProperties keepWithNext = new ParagraphProperties(
    new KeepNext()
);

// KEEP LINES: Keep all lines of this paragraph together (no page break inside)
// Used for: table rows, list items, or paragraphs that shouldn't split
ParagraphProperties keepLinesTogether = new ParagraphProperties(
    new KeepLines()
);

// BOTH: Keep next AND keep lines together
ParagraphProperties keepBoth = new ParagraphProperties(
    new KeepNext(),
    new KeepLines()
);

// WIDOW CONTROL: Prevent single lines at page top/bottom (widow/orphan control)
// Default is ON in Word. Only disable if you want orphans/widows.
ParagraphProperties widowControl = new ParagraphProperties(
    new WidowControl()
);

// NO WIDOW CONTROL (allow single lines at page breaks)
ParagraphProperties noWidowControl = new ParagraphProperties(
    new WidowControl { Val = OnOffValueValues.Off }
);

// PAGE BREAK BEFORE: Start this paragraph on a new page
ParagraphProperties pageBreakBefore = new ParagraphProperties(
    new PageBreakBefore()
);

// Combined: Heading style (keep with next, keep lines, page break before)
ParagraphProperties headingProps = new ParagraphProperties(
    new KeepNext(),
    new KeepLines(),
    new PageBreakBefore(),
    new WidowControl(),
    new SpacingBetweenLines { Before = "480", After = "120" }
);

// ===========================================================================
// 4.5 OUTLINE LEVEL (outlineLvl)
// ===========================================================================
// OutlineLevel defines the heading level for document structure (TOC, Navigation)
// Values 0-8 correspond to Heading 1 through Heading 9
// Word uses this to identify headings in the Navigation Pane

// Level 0 = Heading 1
ParagraphProperties outlineLevel1 = new ParagraphProperties(
    new OutlineLevel { Val = 0 }
);

// Level 1 = Heading 2
ParagraphProperties outlineLevel2 = new ParagraphProperties(
    new OutlineLevel { Val = 1 }
);

// Level 5 = Heading 6
ParagraphProperties outlineLevel6 = new ParagraphProperties(
    new OutlineLevel { Val = 5 }
);

// Level 8 = last possible level
ParagraphProperties outlineLevel8 = new ParagraphProperties(
    new OutlineLevel { Val = 8 }
);

// TOC integration: When you insert a TOC field, Word looks for paragraphs
// with outlineLevel to generate entries. Without outlineLevel, TOC won't
// recognize the heading.

// Heading 1 style example (combining with style reference)
Paragraph heading1 = new Paragraph(
    new ParagraphProperties(
        new ParagraphStyleId { Val = "Heading1" },  // Style reference
        new OutlineLevel { Val = 0 }                 // Also set outline level directly
    ),
    new Run(new Text("Chapter One"))
);

// ===========================================================================
// 4.6 PARAGRAPH BORDERS (pBdr)
// ===========================================================================
// Paragraph borders draw lines around/adjacent to paragraphs
// Four borders: Top, Left, Bottom, Right, Between, Bar

// Simple bottom border
ParagraphProperties bottomBorder = new ParagraphProperties(
    new ParagraphBorders(
        new BottomBorder
        {
            Val = BorderValues.Single,
            Size = 4,
            Color = "000000",
            Space = 4  // Space between text and border in DXA
        }
    )
);

// Top border only
ParagraphProperties topBorder = new ParagraphProperties(
    new ParagraphBorders(
        new TopBorder
        {
            Val = BorderValues.Single,
            Size = 8,
            Color = "4472C4",
            Space = 4
        }
    )
);

// Double line bottom border (common for headings)
ParagraphProperties doubleBottomBorder = new ParagraphProperties(
    new ParagraphBorders(
        new BottomBorder
        {
            Val = BorderValues.Double,
            Size = 4,
            Color = "000000",
            Space = 4
        }
    )
);

// All four borders
ParagraphProperties allBorders = new ParagraphProperties(
    new ParagraphBorders(
        new TopBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC", Space = 1 },
        new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC", Space = 4 },
        new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC", Space = 1 },
        new RightBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC", Space = 4 }
    )
);

// Between border (line between adjacent paragraphs)
// Used for paragraph groups with separator lines
ParagraphProperties withBetweenBorder = new ParagraphProperties(
    new ParagraphBorders(
        new BetweenBorder
        {
            Val = BorderValues.Single,
            Size = 2,
            Color = "CCCCCC",
            Space = 4
        }
    )
);

// Bar border (vertical bar on one side)
// Val can be Left or Right — a solid bar in the margin
ParagraphProperties leftBarBorder = new ParagraphProperties(
    new ParagraphBorders(
        new BarBorder { Val = BorderValues.Left, Color = "000080", Size = 12 }
    )
);

// Thick top border with color
ParagraphProperties thickTopBorder = new ParagraphProperties(
    new ParagraphBorders(
        new TopBorder
        {
            Val = BorderValues.Thick,
            Size = 12,
            Color = "2F5496",
            Space = 8
        }
    )
);

// Wave border (decorative)
ParagraphProperties waveBorder = new ParagraphProperties(
    new ParagraphBorders(
        new BottomBorder
        {
            Val = BorderValues.Wave,
            Size = 6,
            Color = "FF0000",
            Space = 4
        }
    )
);

// Border.NONE to explicitly remove borders
ParagraphProperties noBorders = new ParagraphProperties(
    new ParagraphBorders(
        new BottomBorder { Val = BorderValues.None }
    )
);

// ===========================================================================
// 4.7 SHADING / BACKGROUND (shd)
// ===========================================================================
// Shading applies background color/pattern to the paragraph area
// Different from run-level highlight (which only covers the text)

// Solid color shading (paragraph background)
ParagraphProperties shadedBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "E6F2FF"  // Light blue
    }
);

// Gray shading (common for quotes, notes)
ParagraphProperties grayBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "F2F2F2"  // Light gray
    }
);

// Accent1 theme color shading
ParagraphProperties themedBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "D9E2F3",  // Light blue accent
        ThemeColor = ThemeColorValues.Accent1,
        ThemeShade = "80"  // 50% shade
    }
);

// Pattern shading (horizontal lines)
ParagraphProperties stripedBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.HorizStripe,
        Color = "000000",
        Fill = "FFFFFF"
    }
);

// Diagonal stripe shading
ParagraphProperties diagonalBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.ReverseDiagStripe,
        Color = "auto",
        Fill = "FFF2CC"  // Light yellow
    }
);

// Clear shading (remove background)
ParagraphProperties noBackground = new ParagraphProperties(
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Fill = "auto"
    }
);

// Combined shading and border (common for callout boxes)
ParagraphProperties calloutBox = new ParagraphProperties(
    new ParagraphBorders(
        new LeftBorder
        {
            Val = BorderValues.Single,
            Size = 24,
            Color = "4472C4",
            Space = 8
        }
    ),
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "D9E2F3"
    },
    new Indentation { Left = "720" }
);

// ===========================================================================
// 4.8 TABS (tabs)
// ===========================================================================
// TabStops define where tab characters position text
// Each tab has: position (DXA from left margin), alignment, leader

// Single left tab at 1 inch
ParagraphProperties leftTab = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 1440, Val = TabStopValues.Left }
    )
);

// Multiple tabs
ParagraphProperties multipleTabs = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 1440, Val = TabStopValues.Left },              // 1"
        new TabStop { Position = 2880, Val = TabStopValues.Center },            // 2"
        new TabStop { Position = 4320, Val = TabStopValues.Right },             // 3"
        new TabStop { Position = 5760, Val = TabStopValues.Decimal, TabChar = '.' }  // 4" decimal
    )
);

// Tab with dot leader (dots connecting to tab position)
ParagraphProperties dotLeaderTab = new ParagraphProperties(
    new Tabs(
        new TabStop
        {
            Position = 4320,  // 3 inches
            Val = TabStopValues.Left,
            Leader = TabStopLeaderCharValues.Dot
        }
    )
);

// Tab with dash leader
ParagraphProperties dashLeaderTab = new ParagraphProperties(
    new Tabs(
        new TabStop
        {
            Position = 4320,
            Val = TabStopValues.Left,
            Leader = TabStopLeaderCharValues.Dash
        }
    )
);

// Tab with underscore leader
ParagraphProperties underscoreLeaderTab = new ParagraphProperties(
    new Tabs(
        new TabStop
        {
            Position = 4320,
            Val = TabStopValues.Left,
            Leader = TabStopLeaderCharValues.Underscore
        }
    )
);

// Tab with heavy line leader
ParagraphProperties heavyLeaderTab = new ParagraphProperties(
    new TabStop
    {
        Position = 4320,
        Val = TabStopValues.Left,
        Leader = TabStopLeaderCharValues.Heavy
    )
);

// Tab with middle dot leader
ParagraphProperties middleDotLeaderTab = new ParagraphProperties(
    new Tabs(
        new TabStop
        {
            Position = 4320,
            Val = TabStopValues.Left,
            Leader = TabStopLeaderCharValues.MiddleDot
        }
    )
);

// CENTER TAB (text centered at tab position)
ParagraphProperties centerTab = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 4320, Val = TabStopValues.Center }
    )
);

// RIGHT TAB (text right-aligned at tab position)
ParagraphProperties rightTab = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 5760, Val = TabStopValues.Right }
    )
);

// DECIMAL TAB (aligns on decimal point)
ParagraphProperties decimalTab = new ParagraphProperties(
    new Tabs(
        new TabStop
        {
            Position = 5040,  // 3.5 inches
            Val = TabStopValues.Decimal,
            TabChar = '.'    // Align on period (or specify comma for European)
        }
    )
);

// BAR TAB (vertical bar at tab position)
ParagraphProperties barTab = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 2880, Val = TabStopValues.Bar }
    )
);

// CLEAR TAB (removes inherited tab at this position)
ParagraphProperties clearTab = new ParagraphProperties(
    new Tabs(
        new TabStop { Position = 1440, Val = TabStopValues.Clear }
    )
);

// TAB STOP LEADER VALUES (Leader property):
// None = no leader
// Dot = ....... (dots)
// Dash = ------- (dashes)
// Underscore = _______ (underscores)
// Heavy = ═══════ (heavy line)
// MiddleDot = ········ (centered dots, European style)

// ===========================================================================
// 4.9 SUPPRESS AUTO HYPHENS (suppressAutoHyphens)
// ===========================================================================
// When true, Word won't auto-hyphenate this paragraph

// Prevent auto-hyphenation
ParagraphProperties noAutoHyphens = new ParagraphProperties(
    new SuppressAutoHyphens()
);

// Allow hyphenation (default) — explicit
ParagraphProperties allowAutoHyphens = new ParagraphProperties(
    new SuppressAutoHyphens { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 4.10 NUMBERING PROPERTIES (numPr)
// ===========================================================================
// numPr links a paragraph to a numbering definition (bullets or lists)

// Simple bullet list item
Paragraph bulletItem = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },    // Level 0 (top-level)
            new NumberingId { Val = 1 }                  // References numbering definition
        ),
        new Indentation { Left = "720", Hanging = "360" }  // Standard hanging indent
    ),
    new Run(new Text("First bullet item"))
);

// Numbered list item
Paragraph numberedItem = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 2 }
        ),
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new Run(new Text("First numbered item"))
);

// Multi-level list item (level 2)
Paragraph level2Item = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 2 },  // Level 2 (sub-sub-item)
            new NumberingId { Val = 1 }
        ),
        new Indentation { Left = "1440", Hanging = "360" }  // Deeper indent
    ),
    new Run(new Text("Sub-item under sub-item"))
);

// Restart numbering at this paragraph
Paragraph restartNumberedItem = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 3 },
            new NumberingRestart { Val = NumberingRestartValues.Restart }  // Restart
        ),
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new Run(new Text("Item 1 (restarted)"))
);

// Continue numbering (default)
Paragraph continueNumberedItem = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 3 },
            new NumberingRestart { Val = NumberingRestartValues.Continuous }  // Continue
        ),
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new Run(new Text("Item 4 (continued)"))
);

// ===========================================================================
// 4.11 PARAGRAPH STYLE (pStyle)
// ===========================================================================
// pStyle references a paragraph style by ID

// Apply Heading1 style
ParagraphProperties styledPara = new ParagraphProperties(
    new ParagraphStyleId { Val = "Heading1" }
);

// Apply custom style
ParagraphProperties customStyledPara = new ParagraphProperties(
    new ParagraphStyleId { Val = "MyCustomStyle" }
);

// Default paragraph style (Normal)
ParagraphProperties normalPara = new ParagraphProperties(
    new ParagraphStyleId { Val = "Normal" }
);

// ===========================================================================
// 4.12 BIDIRECTIONAL (BiDi, rtl)
// ===========================================================================
// BiDi enables right-to-left paragraph layout for Arabic/Hebrew

// Right-to-left paragraph
ParagraphProperties rtlParagraph = new ParagraphProperties(
    new BiDi()
);

// Left-to-right (default) — explicit
ParagraphProperties ltrParagraph = new ParagraphProperties(
    new BiDi { Val = OnOffValueValues.Off }
);

// When BiDi is on:
// - Text flows right-to-left
// - Justification defaults to right
// - List numbering appears on the right

// ===========================================================================
// 4.13 CONTEXTUAL SPACING (contextualSpacing)
// ===========================================================================
// When true, suppresses space between paragraphs when they share the same style
// Useful for headings followed by body text within the same style

// Enable contextual spacing (suppress space between same-style paragraphs)
ParagraphProperties contextualSpacing = new ParagraphProperties(
    new ContextualSpacing()
);

// Disable contextual spacing (normal space between all paragraphs)
ParagraphProperties noContextualSpacing = new ParagraphProperties(
    new ContextualSpacing { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 4.14 MIRROR IN DENTS (mirrorIndents)
// ===========================================================================
// When enabled, Left/Right indents are mirrored for odd/even pages
// (left indent on even pages becomes right indent on odd pages)
// Used for book-style printing with binding margin

// Enable mirror indents
ParagraphProperties mirrorIndents = new ParagraphProperties(
    new MirrorIndents()
);

// Disable mirror indents (default)
ParagraphProperties noMirrorIndents = new ParagraphProperties(
    new MirrorIndents { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 4.15 TEXT DIRECTION (textDirection)
// ===========================================================================
// Controls text flow direction within the paragraph

// Left-to-right (default)
ParagraphProperties ltrTextFlow = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.LeftToRight }
);

// Right-to-left
ParagraphProperties rtlTextFlow = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.RightToLeft }
);

// Top-to-bottom (vertical, common in East Asian documents)
ParagraphProperties verticalTextFlow = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.TopToBottom }
);

// Bottom-to-top (vertical rotated 180°)
ParagraphProperties bottomToTopTextFlow = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.BottomToTop }
);

// Left-to-right rotated (90° clockwise)
ParagraphProperties leftToRightRotated = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.LeftToRightRotated }
);

// Right-to-left rotated (90° counter-clockwise)
ParagraphProperties rightToLeftRotated = new ParagraphProperties(
    new TextDirection { Val = TextDirectionValues.RightToLeftRotated }
);

// ===========================================================================
// 4.16 SNAP TO GRID (snapToGrid)
// ===========================================================================
// Aligns paragraph to document grid for consistent vertical spacing

// Enable snap to grid
ParagraphProperties snapToGridPara = new ParagraphProperties(
    new SnapToGrid()
);

// Disable snap to grid
ParagraphProperties noSnapToGridPara = new ParagraphProperties(
    new SnapToGrid { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 4.17 TEXT ALIGNMENT (textAlignment)
// ===========================================================================
// Vertical alignment of text within a line box (rarely used)
// Default is Auto (baseline)

// Baseline alignment (default)
ParagraphProperties baselineAlign = new ParagraphProperties(
    new TextAlignment { Val = VerticalTextAlignmentValues.Auto }
);

// Top alignment
ParagraphProperties topAlign = new ParagraphProperties(
    new TextAlignment { Val = VerticalTextAlignmentValues.Top }
);

// Center alignment
ParagraphProperties centerVerticalAlign = new ParagraphProperties(
    new TextAlignment { Val = VerticalTextAlignmentValues.Center }
);

// Bottom alignment
ParagraphProperties bottomAlign = new ParagraphProperties(
    new TextAlignment { Val = VerticalTextAlignmentValues.Bottom }
);

// Baseline alignment (explicit)
ParagraphProperties baselineAlignExplicit = new ParagraphProperties(
    new TextAlignment { Val = VerticalTextAlignmentValues.Baseline }
);

// ===========================================================================
// 4.18 DIV ID (divId)
// ===========================================================================
// Associates paragraph with a div for HTML/CSS mapping (很少使用)
// Used when importing/exporting HTML content

ParagraphProperties divIdPara = new ParagraphProperties(
    new DivId { Val = "myDiv123" }
);

// ===========================================================================
// 4.19 CNF STYLE (cnfStyle)
// ===========================================================================
// Conditional formatting style index (used by Word for table of contents,
// styles pane grouping, etc.) — typically set automatically by Word

ParagraphProperties cnfStylePara = new ParagraphProperties(
    new CnfStyle { Val = 1 }  // Index into style's cnfStyle definitions
);

// ===========================================================================
// 4.20 SECTION PROPERTIES IN PARAGRAPH (sectPr)
// ===========================================================================
// Section properties can appear INSIDE a paragraph to create a section break
// BEFORE that paragraph. This is how you have different page layouts
// in different parts of the document.

// Section break with continuous layout
Paragraph continuousSectionBreak = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new SectionType { Val = SectionMarkValues.Continuous }
        )
    )
);

// Section break starting new page
Paragraph newPageSectionBreak = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new SectionType { Val = SectionMarkValues.NextPage }
        )
    )
);

// Section break with even page
Paragraph evenPageSectionBreak = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new SectionType { Val = SectionMarkValues.EvenPage }
        )
    )
);

// Section break with odd page
Paragraph oddPageSectionBreak = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new SectionType { Val = SectionMarkValues.OddPage }
        )
    )
);

// Section with custom page size
Paragraph customSectionPara = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new PageSize { Width = 12240u, Height = 15840u },  // Letter
            new PageMargin
            {
                Top = 1440,
                Bottom = 1440,
                Left = 1440u,
                Right = 1440u
            }
        )
    )
);

// ===========================================================================
// 4.21 COMBINED PARAGRAPH FORMATTING EXAMPLE
// ===========================================================================
// Complete paragraph properties combining many options

ParagraphProperties complexParaProps = new ParagraphProperties(
    // Style reference
    new ParagraphStyleId { Val = "Normal" },

    // Keep options
    new KeepNext(),
    new KeepLines(),
    new WidowControl(),

    // Spacing
    new SpacingBetweenLines
    {
        Before = "240",
        After = "200",
        Line = "276",
        LineRule = LineSpacingRuleValues.Auto
    },

    // Indentation
    new Indentation
    {
        Left = "0",
        Right = "0",
        FirstLine = "0",
        Hanging = "0"
    },

    // Alignment
    new Justification { Val = JustificationValues.Left },

    // Border (bottom line)
    new ParagraphBorders(
        new BottomBorder
        {
            Val = BorderValues.Single,
            Size = 4,
            Color = "CCCCCC",
            Space = 4
        }
    ),

    // Shading
    new Shading
    {
        Val = ShadingPatternValues.Clear,
        Color = "auto",
        Fill = "auto"
    },

    // Tabs
    new Tabs(
        new TabStop { Position = 1440, Val = TabStopValues.Left },
        new TabStop { Position = 2880, Val = TabStopValues.Center, Leader = TabStopLeaderCharValues.Dot }
    ),

    // Outline level (for TOC)
    new OutlineLevel { Val = 0 },

    // Bidirectional
    new BiDi { Val = OnOffValueValues.Off },

    // Contextual spacing
    new ContextualSpacing(),

    // Snap to grid
    new SnapToGrid(),

    // Suppress auto hyphens
    new SuppressAutoHyphens { Val = OnOffValueValues.Off }
);

// ===========================================================================
// 4.22 APPLYING PARAGRAPH PROPERTIES
// ===========================================================================
// ParagraphProperties can be applied in multiple ways:

// Method 1: Inline in Paragraph (direct formatting)
Paragraph inlineParaProps = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { After = "200" }
    ),
    new Run(new Text("Centered paragraph with space after"))
);

// Method 2: Via ParagraphStyleId (paragraph style)
Paragraph styledParagraph = new Paragraph(
    new ParagraphProperties(
        new ParagraphStyleId { Val = "Heading1" }
    ),
    new Run(new Text("This is Heading 1"))
);

// Method 3: In Style definition (style-level)
Style bodyTextStyle = new Style(
    new StyleName { Val = "BodyText" },
    new BasedOn { Val = "Normal" },
    new StyleParagraphProperties(
        new Justification { Val = JustificationValues.Both },  // Justify
        new SpacingBetweenLines { After = "160", Line = "276", LineRule = LineSpacingRuleValues.Auto },
        new Indentation { FirstLine = "568" }  // First line indent 0.5"
    ),
    new StyleRunProperties(
        new FontSize { Val = "22" }
    )
)
{ Type = StyleValues.Paragraph, StyleId = "BodyText" };

// Method 4: Combination (style + direct overrides)
Paragraph mixedParaProps = new Paragraph(
    new ParagraphProperties(
        new ParagraphStyleId { Val = "BodyText" },  // Apply style
        new Justification { Val = JustificationValues.Left }  // Override justification
    ),
    new Run(new Text("Body text style but left-aligned"))
);

// ===========================================================================
// 4.23 COMMON PATTERNS
// ===========================================================================
// Heading paragraph (with style + keep options)
Paragraph headingPara = new Paragraph(
    new ParagraphProperties(
        new ParagraphStyleId { Val = "Heading1" },
        new KeepNext(),
        new KeepLines(),
        new SpacingBetweenLines { Before = "480", After = "120" },
        new OutlineLevel { Val = 0 }
    ),
    new Run(new Text("Chapter One"))
);

// Quote paragraph (indented, italic)
Paragraph quotePara = new Paragraph(
    new ParagraphProperties(
        new Indentation { Left = "1440", Right = "1440" },
        new SpacingBetweenLines { Before = "240", After = "240" },
        new ParagraphBorders(
            new LeftBorder
            {
                Val = BorderValues.Single,
                Size = 24,
                Color = "4472C4",
                Space = 8
            }
        )
    ),
    new Run(
        new RunProperties(new Italic()),
        new Text("To be, or not to be, that is the question."))
);

// List item paragraph (hanging indent pattern)
Paragraph listItemPara = new Paragraph(
    new ParagraphProperties(
        new NumberingProperties(
            new NumberingLevelReference { Val = 0 },
            new NumberingId { Val = 1 }
        ),
        new Indentation { Left = "720", Hanging = "360" }
    ),
    new Run(new Text("• List item text"))
);

// Block quote / callout (background, left border)
Paragraph blockQuotePara = new Paragraph(
    new ParagraphProperties(
        new Indentation { Left = "720" },
        new Shading
        {
            Val = ShadingPatternValues.Clear,
            Fill = "F5F5F5"
        },
        new ParagraphBorders(
            new LeftBorder
            {
                Val = BorderValues.Single,
                Size = 12,
                Color = "999999",
                Space = 8
            }
        ),
        new SpacingBetweenLines { Before = "120", After = "120" }
    ),
    new Run(new Text("Block quote text"))
);

// Caption (centered, small text, below figure)
Paragraph captionPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "0", After = "240" },
        new ParagraphStyleId { Val = "Caption" }
    ),
    new Run(
        new RunProperties(
            new FontSize { Val = "20" },  // 10pt
            new Italic()
        ),
        new Text("Figure 1: Sample caption"))
);

// Page title (large, centered, space after)
Paragraph pageTitlePara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { After = "480" },
        new KeepLines(),
        new ParagraphBorders(
            new BottomBorder
            {
                Val = BorderValues.Single,
                Size = 4,
                Color = "000000",
                Space = 4
            }
        )
    ),
    new Run(
        new RunProperties(
            new FontSize { Val = "56" },  // 28pt
            new Bold()
        ),
        new Text("Document Title"))
);

// Signature line (right-aligned, with tab for signature)
Paragraph signatureLinePara = new Paragraph(
    new ParagraphProperties(
        new Tabs(
            new TabStop { Position = 5760, Val = TabStopValues.Right }  // 4" right tab
        )
    ),
    new Run(new Text("Name: ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new TabChar()),
    new Run(new Text("Date: ") { Space = SpaceProcessingModeValues.Preserve }),
    new Run(new TabChar()),
    new Run(new Text("Signature: ") { Space = SpaceProcessingModeValues.Preserve })
);

// Bibliography entry (hanging indent, single-spaced)
Paragraph bibliographyEntry = new Paragraph(
    new ParagraphProperties(
        new Indentation { Left = "720", Hanging = "720" },
        new SpacingBetweenLines { Line = "240", LineRule = LineSpacingRuleValues.Auto },
        new Bibliography()
    ),
    new Run(new Text("Smith, J. (2024). The Art of OpenXML. New York: Publisher."))
);

// ===========================================================================
// 4.24 UNIT SYSTEM QUICK REFERENCE
// ===========================================================================
// DXA (Twentieths of a DXA / Twips):
//   1 inch = 1440 DXA
//   1 cm ≈ 567 DXA
//   1 pt = 20 DXA
//   Used for: margins, indents, spacing, tab stops, borders
//
// Half-Points (Font Size):
//   24 = 12pt
//   22 = 11pt
//   20 = 10pt
//   Used for: FontSize.Val
//
// Points (pt):
//   Used for: border widths, some line spacing values
//
// EMU (English Metric Units):
//   1 inch = 914400 EMU
//   Used for: drawing objects, images, shapes
//
// COMMON DXA VALUES:
//   720 = 0.5 inch
//   1440 = 1 inch
//   2160 = 1.5 inches
//   2880 = 2 inches
//   4320 = 3 inches
//   5760 = 4 inches
//   8640 = 6 inches
```

---

## Appendix A: Complete Working Example

```csharp
// =============================================================================
// COMPLETE WORKING EXAMPLE: BUSINESS REPORT
// =============================================================================
// This example demonstrates a complete, professional document with
// all concepts covered in this encyclopedia.

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace OpenXmlExamples;

public static class BusinessReportGenerator
{
    public static void Generate(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(
            outputPath,
            WordprocessingDocumentType.Document);

        var mainPart = doc.MainDocumentPart!;
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // Add all parts
        AddStyles(mainPart);
        AddNumbering(mainPart);
        AddSettings(mainPart);
        AddTheme(mainPart);
        AddHeadersAndFooters(mainPart);

        // Add content
        AddTitle(body);
        AddTableOfContents(body);
        AddExecutiveSummary(body);
        AddSection(body, "Introduction", @"
            This is the introduction section of the business report.
            It contains multiple paragraphs with various formatting.");
        AddSection(body, "Methodology", @"
            Our methodology section describes the approach taken.
            Bulleted lists are used for key points:");
        AddBulletPoints(body, new[]
        {
            "First methodology point",
            "Second methodology point",
            "Third methodology point with more text to demonstrate wrapping"
        });
        AddSection(body, "Results", @"
            The results section presents data in tables:");
        AddSampleTable(body);
        AddSection(body, "Conclusion", @"
            In conclusion, this report demonstrates the capabilities of the OpenXML SDK.
            The formatting options are comprehensive and allow for professional document generation.");

        // Section properties (must be last)
        body.Append(CreateSectionProperties(mainPart));

        mainPart.Document.Save();
    }

    private static void AddStyles(MainDocumentPart mainPart)
    {
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        var styles = CreateBusinessStyles();
        stylesPart.Styles = styles;
        stylesPart.Styles.Save();
    }

    private static Styles CreateBusinessStyles()
    {
        var styles = new Styles();

        // DocDefaults
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
                    new FontSize { Val = "22" },
                    new FontSizeComplexScript { Val = "22" },
                    new Languages { Val = "en-US" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines { After = "200", Line = "276", LineRule = LineSpacingRuleValues.Auto }
                )
            )
        ));

        // Normal
        styles.Append(new Style(
            new StyleName { Val = "Normal" },
            new PrimaryStyle(),
            new StyleRunProperties(
                new RunFonts { Ascii = "Calibri", HighAnsi = "Calibri" },
                new FontSize { Val = "22" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });

        // Title
        styles.Append(new Style(
            new StyleName { Val = "Title" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new PrimaryStyle(),
            new QuickStyle(),
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { After = "300" },
                new KeepNext(),
                new KeepLines()
            ),
            new StyleRunProperties(
                new RunFonts { Ascii = "Calibri Light", HighAnsi = "Calibri Light" },
                new FontSize { Val = "56" },
                new Bold(),
                new Color { Val = "1F497D" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Title" });

        // Heading 1
        styles.Append(new Style(
            new StyleName { Val = "heading 1" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new PrimaryStyle(),
            new QuickStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "480", After = "120" },
                new OutlineLevel { Val = 0 },
                new ParagraphBorders(
                    new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "4472C4", Space = 4 }
                )
            ),
            new StyleRunProperties(
                new RunFonts { Ascii = "Calibri Light", HighAnsi = "Calibri Light" },
                new FontSize { Val = "48" },
                new Bold(),
                new Color { Val = "1F497D" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Heading1" });

        // Heading 2
        styles.Append(new Style(
            new StyleName { Val = "heading 2" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new PrimaryStyle(),
            new QuickStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new SpacingBetweenLines { Before = "240", After = "120" },
                new OutlineLevel { Val = 1 }
            ),
            new StyleRunProperties(
                new FontSize { Val = "32" },
                new Bold(),
                new Color { Val = "2F5496" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Heading2" });

        return styles;
    }

    private static void AddNumbering(MainDocumentPart mainPart)
    {
        var numberingPart = mainPart.AddNewPart<NumberingDefinitionsPart>();
        var numbering = new Numbering();

        var abstractNum = new AbstractNum { AbstractNumberId = 1 };
        abstractNum.Append(new Level(
            new StartNumberingValue { Val = 1 },
            new NumberingFormat { Val = NumberFormatValues.Bullet },
            new LevelText { Val = "•" },
            new LevelJustification { Val = LevelJustificationValues.Left },
            new PreviousParagraphProperties(
                new Indentation { Left = "720", Hanging = "360" })
        )
        { LevelIndex = 0 });

        numbering.Append(abstractNum);
        numbering.Append(new NumberingInstance(
            new AbstractNumId { Val = 1 }
        )
        { NumberID = 1 });

        numberingPart.Numbering = numbering;
        numberingPart.Numbering.Save();
    }

    private static void AddSettings(MainDocumentPart mainPart)
    {
        var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
        settingsPart.Settings = new Settings(
            new Zoom { Val = "100", Percent = true },
            new DefaultTabStop { Val = 720 },
            new CharacterSpacingControl { Val = CharacterSpacingValues.CompressPunctuation }
        );
        settingsPart.Settings.Save();
    }

    private static void AddTheme(MainDocumentPart mainPart)
    {
        var themePart = mainPart.AddNewPart<ThemePart>();
        themePart.Theme = new Theme(
            new ThemeElements(
                new ColorScheme(
                    new Dark1Color(new Color { Val = "000000" }),
                    new Light1Color(new Color { Val = "FFFFFF" }),
                    new Accent1Color(new Color { Val = "4472C4" }),
                    new Accent2Color(new Color { Val = "C0504D" }),
                    new Accent3Color(new Color { Val = "9BBB59" }),
                    new Accent4Color(new Color { Val = "8064A2" }),
                    new Accent5Color(new Color { Val = "4BACC6" }),
                    new Accent6Color(new Color { Val = "F79646" })
                ),
                new FontScheme(
                    new MajorFont { Val = "Calibri Light" },
                    new MinorFont { Val = "Calibri" }
                )
            ),
            new ThemeName { Val = "Office Theme" }
        );
        themePart.Theme.Save();
    }

    private static void AddHeadersAndFooters(MainDocumentPart mainPart)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();
        headerPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(new Justification { Val = JustificationValues.Right }),
                new Run(
                    new RunProperties(new RunFonts { Ascii = "Calibri Light" }, new Italic(), new FontSize { Val = "18" }),
                    new Text("Business Report"))
            ));
        var headerId = mainPart.GetIdOfPart(headerPart);

        var footerPart = mainPart.AddNewPart<FooterPart>();
        footerPart.Footer = new Footer(
            new Paragraph(
                new ParagraphProperties(new Justification { Val = JustificationValues.Center }),
                new Run(new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }),
                new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
                new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }),
                new Run(new FieldChar { FieldCharType = FieldCharValues.End }),
                new Run(new Text(" of ") { Space = SpaceProcessingModeValues.Preserve }),
                new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }),
                new Run(new FieldCode(" NUMPAGES ") { Space = SpaceProcessingModeValues.Preserve }),
                new Run(new FieldChar { FieldCharType = FieldCharValues.End })
            ));
        var footerId = mainPart.GetIdOfPart(footerPart);

        // Store IDs for later use
        mainPart.Document.Body!.Append(new Paragraph());  // Placeholder for sectPr
    }

    private static void AddTitle(Body body)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Title" }),
            new Run(new Text("Business Report"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Subtitle" }),
            new Run(new Text("Quarterly Performance Analysis"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(new SpacingBetweenLines { After = "400" }),
            new Run(
                new RunProperties(new Color { Val = "666666" }),
                new Text("March 2026"))
        ));
    }

    private static void AddTableOfContents(Body body)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text("Table of Contents"))
        ));

        var tocPara = new Paragraph();
        tocPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        tocPara.Append(new Run(new FieldCode(" TOC \\o \"1-2\" \\h \\z \\u ") { Space = SpaceProcessingModeValues.Preserve }));
        tocPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }));
        tocPara.Append(new Run(new Text("Update field to generate Table of Contents")));
        tocPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));
        body.Append(tocPara);

        body.Append(new Paragraph(new Run(new Break { Type = BreakValues.Page })));
    }

    private static void AddExecutiveSummary(Body body)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text("Executive Summary"))
        ));

        body.Append(new Paragraph(
            new Run(new Text("This executive summary provides a high-level overview of the quarterly performance. Key highlights include revenue growth, market expansion, and operational improvements."))
        ));
    }

    private static void AddSection(Body body, string title, string content)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text(title))
        ));

        body.Append(new Paragraph(
            new Run(new Text(content))
        ));
    }

    private static void AddBulletPoints(Body body, string[] points)
    {
        foreach (var point in points)
        {
            body.Append(new Paragraph(
                new ParagraphProperties(
                    new NumberingProperties(
                        new NumberingLevelReference { Val = 0 },
                        new NumberingId { Val = 1 }
                    ),
                    new Indentation { Left = "720", Hanging = "360" }
                ),
                new Run(new Text(point))
            ));
        }
    }

    private static void AddSampleTable(Body body)
    {
        var table = new Table(
            new TableProperties(
                new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
                new TableBorders(
                    new TopBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
                    new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
                    new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
                    new RightBorder { Val = BorderValues.Single, Size = 4, Color = "000000" },
                    new InsideHorizontalBorder { Val = BorderValues.Single, Size = 2, Color = "CCCCCC" },
                    new InsideVerticalBorder { Val = BorderValues.Single, Size = 2, Color = "CCCCCC" }
                ),
                new TableCellMarginDefault(
                    new TopMargin { Width = "50", Type = TableWidthUnitValues.DXA },
                    new BottomMargin { Width = "50", Type = TableWidthUnitValues.DXA },
                    new StartMargin { Width = "100", Type = TableWidthUnitValues.DXA },
                    new EndMargin { Width = "100", Type = TableWidthUnitValues.DXA }
                )
            ),
            new TableGrid(
                new GridColumn { Width = "2000" },
                new GridColumn { Width = "2000" },
                new GridColumn { Width = "2000" }
            )
        );

        // Header row
        var headerRow = new TableRow(
            new TableRowProperties(new TableHeader()),
            CreateTableCell("Metric", bold: true),
            CreateTableCell("Q1 2026", bold: true),
            CreateTableCell("Q4 2025", bold: true)
        );
        table.Append(headerRow);

        // Data rows
        table.Append(CreateTableRow("Revenue", "$2.5M", "$2.1M"));
        table.Append(CreateTableRow("Growth", "19%", "12%"));
        table.Append(CreateTableRow("Customers", "1,250", "1,100"));

        body.Append(table);
    }

    private static TableCell CreateTableCell(string text, bool bold = false)
    {
        var cell = new TableCell(
            new Paragraph(
                new Run(
                    bold
                        ? new RunProperties(new Bold())
                        : new RunProperties(),
                    new Text(text))
            )
        );
        return cell;
    }

    private static TableRow CreateTableRow(string metric, string q1, string q4)
    {
        return new TableRow(
            CreateTableCell(metric),
            CreateTableCell(q1),
            CreateTableCell(q4)
        );
    }

    private static SectionProperties CreateSectionProperties(MainDocumentPart mainPart)
    {
        var sectPr = new SectionProperties();

        // Header/Footer references
        var headerPart = mainPart.HeaderParts.FirstOrDefault();
        var footerPart = mainPart.FooterParts.FirstOrDefault();
        if (headerPart != null)
            sectPr.Append(new HeaderReference { Type = HeaderFooterValues.Default, Id = mainPart.GetIdOfPart(headerPart) });
        if (footerPart != null)
            sectPr.Append(new FooterReference { Type = HeaderFooterValues.Default, Id = mainPart.GetIdOfPart(footerPart) });

        // Page size
        sectPr.Append(new PageSize { Width = 12240u, Height = 15840u });

        // Page margins
        sectPr.Append(new PageMargin
        {
            Top = 1440,
            Bottom = 1440,
            Left = 1440u,
            Right = 1440u,
            Header = 720u,
            Footer = 720u
        });

        return sectPr;
    }
}

// ===========================================================================
// USAGE
// ===========================================================================
/*
public static void Main(string[] args)
{
    BusinessReportGenerator.Generate("C:\\Reports\\BusinessReport.docx");
    Console.WriteLine("Report generated successfully!");
}
*/
```

---

## Appendix B: OpenXmlUnits Helper Class

```csharp
// =============================================================================
// UNIT CONVERSION HELPERS
// =============================================================================
// Copy this class into your project for convenient unit conversions.

public static class OpenXmlUnits
{
    // DXA (Twentieths of a DXA / Twips) conversions
    public static int InchesToDxa(double inches) => (int)(inches * 1440);
    public static int CmToDxa(double cm) => (int)(cm * 567.0);
    public static int PtToDxa(double pt) => (int)(pt * 20);
    public static double DxaToInches(int dxa) => dxa / 1440.0;
    public static double DxaToCm(int dxa) => dxa / 567.0;
    public static double DxaToPt(int dxa) => dxa / 20.0;

    // EMU (English Metric Units) conversions
    public static long InchesToEmu(double inches) => (long)(inches * 914400);
    public static long CmToEmu(double cm) => (long)(cm * 360000);
    public static double EmuToInches(long emu) => emu / 914400.0;
    public static double EmuToCm(long emu) => emu / 360000.0;

    // Half-point conversions (font sizes)
    public static int PtToHalfPt(double pt) => (int)(pt * 2);
    public static int FontSizeToSz(double ptSize) => (int)(ptSize * 2);
    public static double SzToPt(int sz) => sz / 2.0;

    // Line spacing helpers
    public static int SingleSpacing => 240;
    public static int DoubleSpacing => 480;
    public static int OneAndHalfSpacing => 360;
    public static int LineSpacingPt(double pt) => (int)(pt * 20);

    // Common measurements
    public static int HalfInch => 720;
    public static int OneInch => 1440;
    public static int OneAndHalfInches => 2160;
    public static int TwoInches => 2880;
}
```

---

*Document Version: 1.0*
*OpenXML SDK: 3.x*
*.NET Version: 10*
*C# Version: 13*
