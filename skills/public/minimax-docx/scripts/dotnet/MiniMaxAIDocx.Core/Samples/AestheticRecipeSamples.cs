// ============================================================================
// AestheticRecipeSamples.cs — Complete aesthetic recipes for document styling
// ============================================================================
// Each recipe is a self-contained, coordinated design system where fonts,
// sizes, spacing, colors, margins, and table styles all work in harmony.
//
// DESIGN PHILOSOPHY: Beauty comes from harmony, not individual choices.
// A 14pt heading is not inherently good or bad — it depends on body size,
// line spacing, margins, and color all working together.
//
// UNIT REFERENCE:
//   Font size: half-points (22 = 11pt, 24 = 12pt, 32 = 16pt)
//   Spacing:   DXA = twentieths of a point (1440 DXA = 1 inch)
//   Borders:   eighth-points (4 = 0.5pt, 8 = 1pt, 12 = 1.5pt)
//   Line spacing "line": 240ths of single spacing (240 = 1.0x, 276 = 1.15x)
// ============================================================================

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using WpPageSize = DocumentFormat.OpenXml.Wordprocessing.PageSize;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Complete aesthetic recipes — coordinated design systems where all parameters
/// work together. Each recipe is a full document style that can be applied as-is.
///
/// DESIGN PHILOSOPHY: Beauty comes from harmony, not individual choices.
/// A 14pt heading is not inherently good or bad — it depends on body size,
/// line spacing, margins, and color all working together.
///
/// These recipes encode tested, harmonious combinations.
/// </summary>
public static partial class AestheticRecipeSamples
{
    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 1: MODERN CORPORATE
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Modern Corporate
    /// Feel: Clean, confident, contemporary.
    /// Best for: Business reports, proposals, internal documents.
    ///
    /// Design rationale:
    /// - 1.25x modular scale creates clear but not aggressive hierarchy
    ///   (body 11pt → H3 13pt → H2 16pt → H1 20pt, each step ~1.25x)
    /// - Dark navy headings (#1F3864) convey authority without being harsh
    /// - 1.15 line spacing is the sweet spot for sans-serif readability:
    ///   tight enough to look professional, open enough for comfortable scanning
    /// - 8pt paragraph spacing creates rhythm without wasting vertical space
    /// - Body text #333333 (not pure black) reduces eye strain on screens
    /// - Sans-serif font family (Aptos/Calibri) signals modernity and clarity
    /// - Light banded table rows (#F2F2F2) aid scanning without visual noise
    /// </summary>
    public static void CreateModernCorporateDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: the foundation everything inherits from.
        // Aptos is Word's new default (2023+); Calibri is the fallback for older systems.
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        Ascii = "Aptos",
                        HighAnsi = "Aptos",
                        EastAsia = "SimSun",
                        ComplexScript = "Calibri"
                    },
                    new FontSize { Val = "22" },              // 11pt body default
                    new FontSizeComplexScript { Val = "22" },
                    new Color { Val = "333333" },             // Soft black — easier on eyes than #000000
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // 1.15x line spacing: the modern standard for sans-serif.
                        // 240 = single, so 276 = 1.15x. Word's default since 2013.
                        Line = "276",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "160"   // 8pt after — enough rhythm, not too airy
                    }
                )
            )
        ));

        // ── Normal style ──
        styles.Append(CreateParagraphStyle(
            styleId: "Normal",
            styleName: "Normal",
            isDefault: true,
            uiPriority: 0
        ));

        // ── Heading 1: 20pt Aptos Display, dark navy ──
        // 20pt = 40 half-points. The 1.25x scale from 11pt body gives:
        //   11 → 13.75 → 17.2 → 21.5. We round to 13, 16, 20 for clean numbers.
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Aptos Display",
            fontHAnsi: "Aptos Display",
            sizeHalfPts: "40",            // 20pt
            color: "1F3864",              // Dark navy — authority without aggression
            bold: false,                  // Large Display font doesn't need bold
            spaceBefore: "480",           // 24pt before — creates a clear section break
            spaceAfter: "120",            // 6pt after — tight coupling to content below
            uiPriority: 9
        ));

        // ── Heading 2: 16pt, dark navy, semi-bold ──
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Aptos Display",
            fontHAnsi: "Aptos Display",
            sizeHalfPts: "32",            // 16pt
            color: "1F3864",
            bold: false,
            spaceBefore: "360",           // 18pt before
            spaceAfter: "80",             // 4pt after
            uiPriority: 9
        ));

        // ── Heading 3: 13pt, dark navy, bold ──
        styles.Append(CreateHeadingStyle(
            level: 3,
            fontAscii: "Aptos",
            fontHAnsi: "Aptos",
            sizeHalfPts: "26",            // 13pt
            color: "1F3864",
            bold: true,                   // Bold compensates for smaller size
            spaceBefore: "240",           // 12pt before
            spaceAfter: "80",             // 4pt after
            uiPriority: 9
        ));

        // ── ListBullet style ──
        styles.Append(CreateParagraphStyle(
            styleId: "ListBullet",
            styleName: "List Bullet",
            basedOn: "Normal",
            uiPriority: 36
        ));

        // ── Caption style: 9pt italic gray ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "18",        // 9pt
            color: "595959",
            italic: true
        ));

        // ── Page setup: Letter, 1in margins ──
        // 1 inch = 1440 DXA. Letter = 8.5" x 11" = 12240 x 15840 DXA.
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: bottom right, 9pt gray ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Right,
            fontSizeHalfPts: "18",        // 9pt — subordinate to body text
            color: "808080",              // Gray — page numbers are reference, not content
            format: PageNumberFormat.Plain
        );

        // ── Sample content ──
        AddSampleParagraph(body, "Modern Corporate Report", "Heading1");

        AddSampleParagraph(body, "This document demonstrates the Modern Corporate aesthetic. "
            + "The clean sans-serif typography, dark navy headings, and generous but not "
            + "excessive spacing create a professional appearance suitable for business contexts.",
            "Normal");

        AddSampleParagraph(body, "Executive Summary", "Heading2");

        AddSampleParagraph(body, "Key findings from our analysis indicate strong performance "
            + "across all divisions. Revenue grew 12% year-over-year while maintaining healthy "
            + "margins. The integration of new systems has improved operational efficiency.",
            "Normal");

        AddSampleParagraph(body, "Detailed Findings", "Heading2");

        AddSampleParagraph(body, "Revenue Analysis", "Heading3");

        AddSampleParagraph(body, "Quarter-over-quarter growth remained consistent, with Q3 "
            + "showing particularly strong performance in the enterprise segment.",
            "Normal");

        // ── Table: light top/bottom borders, banded rows, no vertical lines ──
        body.Append(CreateModernCorporateTable(
            new[] { "Division", "Revenue", "Growth", "Margin" },
            new[]
            {
                new[] { "Enterprise", "$45.2M", "+15%", "42%" },
                new[] { "Mid-Market", "$28.7M", "+11%", "38%" },
                new[] { "SMB", "$12.1M", "+8%", "35%" }
            }
        ));

        AddSampleParagraph(body, "Table 1: Division Performance Summary", "Caption");

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// Modern Corporate table aesthetic: horizontal lines only, banded rows.
    /// Design: top and bottom borders frame the data. Header has a bottom border.
    /// No vertical lines — the eye follows horizontal rows naturally.
    /// Subtle #F2F2F2 banding on alternate rows aids scanning without adding noise.
    /// </summary>
    private static Table CreateModernCorporateTable(string[] headers, string[][] data)
    {
        var table = new Table();

        // Table properties: full width, horizontal-only borders
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "BFBFBF" },
                new BottomBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "BFBFBF" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                // Horizontal inside borders for row separation
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "D9D9D9" },
                // No vertical inside borders — cleaner look
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            // Cell padding: 28 DXA minimum each side for breathing room
            new TableCellMarginDefault(
                new TopMargin { Width = "28", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "57", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "28", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "57", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid columns
        var grid = new TableGrid();
        int colWidth = 9360 / headers.Length;
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Header row
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            headerRow.Append(new TableCell(
                new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                    // Header bottom border slightly heavier to separate from data
                    new TableCellBorders(
                        new BottomBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "999999" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0" }
                    ),
                    new Run(
                        new RunProperties(new Bold()),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows with subtle banding
        for (int i = 0; i < data.Length; i++)
        {
            var row = new TableRow();
            foreach (var cell in data[i])
            {
                var tcPr = new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto }
                );
                // Banded rows: every other row gets a very light gray background
                // #F2F2F2 is subtle enough to not compete with content
                if (i % 2 == 1)
                {
                    tcPr.Append(new Shading
                    {
                        Val = ShadingPatternValues.Clear,
                        Color = "auto",
                        Fill = "F2F2F2"
                    });
                }

                row.Append(new TableCell(
                    tcPr,
                    new Paragraph(
                        new ParagraphProperties(
                            new SpacingBetweenLines { After = "0" }
                        ),
                        new Run(new Text(cell))
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 2: ACADEMIC THESIS
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Academic Thesis (APA-style)
    /// Feel: Traditional, scholarly, readable for sustained long-form reading.
    /// Best for: Dissertations, research papers, academic reports.
    ///
    /// Design rationale:
    /// - Times New Roman 12pt: the universal academic standard, optimized for
    ///   print legibility at reading distance. Serif fonts aid reading flow in
    ///   long-form text by creating horizontal "rails" for the eye.
    /// - APA-style headings: size is UNIFORM (all 12pt) — hierarchy is expressed
    ///   through bold, italic, centering, and indentation rather than size change.
    ///   This is intentional: in academic writing, the text IS the content, and
    ///   headings are navigational aids, not visual statements.
    /// - Double spacing (480 line units): required by most style guides for
    ///   annotation/editing room. Also improves readability for dense content.
    /// - 0.5in first-line indent, no paragraph spacing: the classical paragraph
    ///   separator. Space-after is a modern convention; indent is the scholarly one.
    /// - Left margin 1.5in for binding: physical theses are bound on the left.
    /// - Three-line table (三线表): the academic standard — top rule, header rule,
    ///   bottom rule. No vertical lines. Clean and information-focused.
    /// </summary>
    public static void CreateAcademicThesisDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Times New Roman 12pt, double spacing
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman",
                        EastAsia = "SimSun",
                        ComplexScript = "Times New Roman"
                    },
                    new FontSize { Val = "24" },              // 12pt (in half-points)
                    new FontSizeComplexScript { Val = "24" },
                    new Color { Val = "000000" },             // Pure black — academic standard
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Double spacing: 480 = 2.0x (240 = single)
                        // This is the fundamental academic formatting requirement
                        Line = "480",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"     // No space after — use first-line indent instead
                    },
                    // First-line indent: 0.5in = 720 DXA
                    // The traditional paragraph separator in academic writing
                    new Indentation { FirstLine = "720" }
                )
            )
        ));

        // ── Normal style ──
        styles.Append(CreateParagraphStyle(
            styleId: "Normal",
            styleName: "Normal",
            isDefault: true,
            uiPriority: 0
        ));

        // ── APA Heading 1: 12pt bold, centered ──
        // APA Level 1: Centered, Bold, Title Case
        // Note: ALL headings are 12pt — hierarchy through formatting, not size.
        styles.Append(CreateAcademicHeadingStyle(
            level: 1,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: true,
            spaceBefore: "480",          // One blank double-spaced line before
            spaceAfter: "0"
        ));

        // ── APA Heading 2: 12pt bold, left-aligned ──
        // APA Level 2: Flush Left, Bold, Title Case
        styles.Append(CreateAcademicHeadingStyle(
            level: 2,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── APA Heading 3: 12pt bold italic, left-aligned ──
        // APA Level 3: Flush Left, Bold Italic, Title Case
        styles.Append(CreateAcademicHeadingStyle(
            level: 3,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: true,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── ListBullet style ──
        styles.Append(CreateParagraphStyle(
            styleId: "ListBullet",
            styleName: "List Bullet",
            basedOn: "Normal",
            uiPriority: 36
        ));

        // ── Caption style ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "24",        // 12pt — same as body (APA requirement)
            color: "000000",
            italic: true
        ));

        // ── Page setup: Letter, 1in margins, 1.5in left for binding ──
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 2160U,             // 1.5in for binding margin
                Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: top right (APA style) ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Right,
            fontSizeHalfPts: "24",        // 12pt — APA requires same size
            color: "000000",
            format: PageNumberFormat.Plain,
            isHeader: true                // APA puts page numbers in header
        );

        // ── Sample content ──
        // Title page heading — no first-line indent
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }           // Override indent for headings
            ),
            new Run(new Text("The Effects of Typography on Reading Comprehension"))
        ));

        AddAcademicParagraph(body, "This study examines the relationship between typographic "
            + "choices and reading comprehension in academic documents. Previous research has "
            + "established that serif fonts facilitate sustained reading in printed materials, "
            + "though recent evidence suggests this advantage diminishes on high-resolution screens.");

        AddAcademicParagraph(body, "The present investigation extends this work by examining "
            + "how the interaction of font choice, line spacing, and margin width affects both "
            + "comprehension accuracy and reading speed across different document lengths.");

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("Method"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading3" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("Participants"))
        ));

        AddAcademicParagraph(body, "A total of 120 undergraduate students (M age = 21.3, "
            + "SD = 2.1) participated in exchange for course credit. All participants reported "
            + "normal or corrected-to-normal vision.");

        // ── Three-line table (三线表) ──
        body.Append(CreateThreeLineTable(
            new[] { "Condition", "n", "M (RT)", "SD", "Accuracy %" },
            new[]
            {
                new[] { "Serif / Double", "30", "142.3", "18.7", "94.2" },
                new[] { "Serif / Single", "30", "156.8", "21.3", "91.8" },
                new[] { "Sans / Double", "30", "148.1", "19.4", "92.7" },
                new[] { "Sans / Single", "30", "161.2", "23.1", "89.4" }
            }
        ));

        body.Append(sectPr);
    }

    /// <summary>
    /// Three-line table (三线表): the gold standard for academic data presentation.
    /// Only three horizontal lines: top rule (1.5pt), header-bottom rule (0.75pt),
    /// bottom rule (1.5pt). No vertical lines whatsoever.
    /// This style focuses the reader on the data, not the grid.
    /// </summary>
    private static Table CreateThreeLineTable(string[] headers, string[][] data)
    {
        var table = new Table();

        // Table properties: three horizontal rules only
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                // Top rule: 1.5pt (Size=12 in eighth-points)
                new TopBorder { Val = BorderValues.Single, Size = 12, Space = 0, Color = "000000" },
                // Bottom rule: 1.5pt
                new BottomBorder { Val = BorderValues.Single, Size = 12, Space = 0, Color = "000000" },
                // No left, right, or inside borders
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            new TableCellMarginDefault(
                new TopMargin { Width = "28", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "57", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "28", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "57", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid
        var grid = new TableGrid();
        int colWidth = 9360 / headers.Length;
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Header row: bottom border is the header rule (0.75pt = Size 6)
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            headerRow.Append(new TableCell(
                new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                    new TableCellBorders(
                        new BottomBorder { Val = BorderValues.Single, Size = 6, Space = 0, Color = "000000" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto },
                        new Indentation { FirstLine = "0" },
                        new Justification { Val = JustificationValues.Center }
                    ),
                    new Run(
                        new RunProperties(new Bold()),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows: no borders (only the table-level top/bottom apply)
        foreach (var rowData in data)
        {
            var row = new TableRow();
            foreach (var cell in rowData)
            {
                row.Append(new TableCell(
                    new TableCellProperties(
                        new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto }
                    ),
                    new Paragraph(
                        new ParagraphProperties(
                            new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto },
                            new Indentation { FirstLine = "0" },
                            new Justification { Val = JustificationValues.Center }
                        ),
                        new Run(new Text(cell))
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }

    /// <summary>Helper to add a body paragraph with first-line indent (academic style).</summary>
    private static void AddAcademicParagraph(Body body, string text)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" }
            ),
            new Run(new Text(text))
        ));
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 3: EXECUTIVE BRIEF
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Executive Brief
    /// Feel: Premium, minimal, high white-space.
    /// Best for: Board summaries, investor updates, C-suite communications.
    ///
    /// Design rationale:
    /// - Georgia (serif) body with Helvetica Neue/Arial headings: the serif/sans
    ///   contrast creates natural visual hierarchy. Georgia was designed specifically
    ///   for screen readability while maintaining elegance.
    /// - 1.4x line spacing (336 line units): more generous than corporate, reflecting
    ///   the premium feel. Executives scan quickly; more air helps their eyes jump.
    /// - 10pt generous paragraph spacing: creates distinct "thought blocks" that
    ///   support quick scanning without deep reading.
    /// - 1.25in margins: extra breathing room signals "we can afford to waste paper."
    ///   White space IS the luxury. Content-to-margin ratio conveys status.
    /// - #2C3E50 (dark blue-gray) for all text: sophisticated alternative to black.
    ///   Warm enough to not feel clinical, dark enough for print legibility.
    /// - #E74C3C accent red: used sparingly for table headers, creates a single
    ///   focal point. The contrast draws the eye to data.
    /// - Dark header table style: inverted header row makes the table structure
    ///   immediately scannable even in peripheral vision.
    /// </summary>
    public static void CreateExecutiveBriefDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Georgia 11pt, generous spacing
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        // Georgia: designed by Matthew Carter for Microsoft.
                        // Optimized for screen clarity while retaining serif elegance.
                        Ascii = "Georgia",
                        HighAnsi = "Georgia",
                        EastAsia = "SimSun",
                        ComplexScript = "Arial"
                    },
                    new FontSize { Val = "22" },              // 11pt
                    new FontSizeComplexScript { Val = "22" },
                    new Color { Val = "2C3E50" },             // Dark blue-gray — sophisticated
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // 1.4x line spacing: the "executive reading" sweet spot.
                        // More air than corporate (1.15), less than academic (2.0).
                        // Facilitates scanning behavior common in executive reading.
                        Line = "336",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "200"   // 10pt after — generous blocks
                    }
                )
            )
        ));

        // ── Normal style ──
        styles.Append(CreateParagraphStyle(
            styleId: "Normal",
            styleName: "Normal",
            isDefault: true,
            uiPriority: 0
        ));

        // ── Heading 1: 22pt Helvetica Neue/Arial, bold ──
        // Serif body + sans heading = natural hierarchy through font contrast
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Helvetica Neue",
            fontHAnsi: "Helvetica Neue",
            sizeHalfPts: "44",            // 22pt
            color: "2C3E50",
            bold: false,                  // Large size is enough; bold would be heavy
            spaceBefore: "480",
            spaceAfter: "120",
            uiPriority: 9
        ));

        // ── Heading 2: 16pt Helvetica Neue/Arial ──
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Helvetica Neue",
            fontHAnsi: "Helvetica Neue",
            sizeHalfPts: "32",            // 16pt
            color: "2C3E50",
            bold: false,
            spaceBefore: "360",
            spaceAfter: "80",
            uiPriority: 9
        ));

        // ── Heading 3: 12pt Helvetica Neue/Arial, bold ──
        styles.Append(CreateHeadingStyle(
            level: 3,
            fontAscii: "Helvetica Neue",
            fontHAnsi: "Helvetica Neue",
            sizeHalfPts: "24",            // 12pt
            color: "2C3E50",
            bold: true,
            spaceBefore: "240",
            spaceAfter: "80",
            uiPriority: 9
        ));

        // ── ListBullet style ──
        styles.Append(CreateParagraphStyle(
            styleId: "ListBullet",
            styleName: "List Bullet",
            basedOn: "Normal",
            uiPriority: 36
        ));

        // ── Caption style ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "18",        // 9pt
            color: "7F8C8D",
            italic: true
        ));

        // ── Page setup: Letter, 1.25in margins ──
        // Extra-wide margins = premium feel. The white space says "confidence."
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1800, Bottom = 1800,       // 1.25in
                Left = 1800U, Right = 1800U,     // 1.25in
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: bottom center, 8pt ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "16",        // 8pt — nearly invisible, as intended
            color: "BFBFBF",             // Very light gray — page numbers are utility
            format: PageNumberFormat.Plain
        );

        // ── Sample content ──
        AddSampleParagraph(body, "Q3 Performance Summary", "Heading1");

        AddSampleParagraph(body, "Revenue exceeded targets across all segments. The strategic "
            + "realignment initiated in Q1 is now delivering measurable results. Key metrics "
            + "are trending positively with strong forward indicators.",
            "Normal");

        AddSampleParagraph(body, "Key Metrics", "Heading2");

        AddSampleParagraph(body, "The following table summarizes performance against targets. "
            + "All figures are in millions USD unless otherwise noted.",
            "Normal");

        // ── Executive table: dark header row (#2C3E50 + white text), no other borders ──
        body.Append(CreateExecutiveTable(
            new[] { "Metric", "Target", "Actual", "Variance" },
            new[]
            {
                new[] { "Revenue", "$52.0M", "$54.8M", "+5.4%" },
                new[] { "EBITDA", "$12.5M", "$13.1M", "+4.8%" },
                new[] { "Net Margin", "24%", "23.9%", "-0.1pp" }
            }
        ));

        AddSampleParagraph(body, "Strategic Outlook", "Heading2");

        AddSampleParagraph(body, "Market conditions remain favorable heading into Q4. "
            + "The pipeline is robust with several high-value opportunities expected to close "
            + "before year-end.",
            "Normal");

        AddSampleParagraph(body, "Risk Factors", "Heading3");

        AddSampleParagraph(body, "Currency headwinds and supply chain constraints represent "
            + "the primary downside risks. Mitigation strategies are in place for both scenarios.",
            "Normal");

        body.Append(sectPr);
    }

    /// <summary>
    /// Executive table style: dark header row with white text, no other borders.
    /// The inverted header creates immediate scanability. The borderless body
    /// lets data breathe. This is the "less is more" school of data presentation.
    /// </summary>
    private static Table CreateExecutiveTable(string[] headers, string[][] data)
    {
        var table = new Table();

        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            // No table-level borders at all — the header shading does the work
            new TableBorders(
                new TopBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "E0E0E0" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            new TableCellMarginDefault(
                new TopMargin { Width = "57", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "85", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "57", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "85", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid
        var grid = new TableGrid();
        int colWidth = 9360 / headers.Length;
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Header row: dark background (#2C3E50) + white text
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            headerRow.Append(new TableCell(
                new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                    new Shading
                    {
                        Val = ShadingPatternValues.Clear,
                        Color = "auto",
                        Fill = "2C3E50"   // Dark blue-gray header
                    },
                    // Override borders for header cells
                    new TableCellBorders(
                        new TopBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                        new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                        new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                        new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0" }
                    ),
                    new Run(
                        new RunProperties(
                            new Bold(),
                            new Color { Val = "FFFFFF" },     // White text on dark header
                            new RunFonts { Ascii = "Helvetica Neue", HighAnsi = "Helvetica Neue" }
                        ),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows: clean, no borders (only inside-H from table properties)
        foreach (var rowData in data)
        {
            var row = new TableRow();
            foreach (var cell in rowData)
            {
                row.Append(new TableCell(
                    new TableCellProperties(
                        new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto }
                    ),
                    new Paragraph(
                        new ParagraphProperties(
                            new SpacingBetweenLines { After = "0" }
                        ),
                        new Run(new Text(cell))
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 4: CHINESE GOVERNMENT (公文 GB/T 9704)
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Chinese Government Document (公文)
    /// Feel: Formal, standardized, authoritative.
    /// Best for: Government announcements, official communications, regulatory documents.
    ///
    /// Design rationale (based on GB/T 9704-2012 standard):
    /// - 仿宋_GB2312 三号 (16pt): the mandated body font. FangSong is a calligraphic
    ///   style that balances formality with readability in Chinese typography.
    /// - 小标宋 二号 (22pt): the mandated title font. 小标宋体 is a specialized display
    ///   serif used exclusively in government documents for titles.
    /// - Fixed 28pt line spacing (line="560"): government standard ensures uniform
    ///   page density of 22 lines per page. Every page looks identical.
    /// - Margins T:37mm B:35mm L:28mm R:26mm: per GB/T 9704 specification.
    ///   Asymmetric left-right margins account for binding.
    /// - Page size A4: Chinese government standard (unlike US Letter).
    /// - All black text, no decorative elements: government documents derive
    ///   authority from standardization, not from visual design.
    /// - Page numbers: bottom center, "-X-" format (e.g., "-3-") per standard.
    /// - 28 chars per line, 22 lines per page: the density specification.
    /// </summary>
    public static void CreateChineseGovernmentDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: 仿宋 16pt (三号), fixed 28pt line spacing
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        // 仿宋_GB2312 is the standard; 仿宋 is the fallback on modern systems
                        Ascii = "FangSong",
                        HighAnsi = "FangSong",
                        EastAsia = "FangSong_GB2312",
                        ComplexScript = "FangSong"
                    },
                    new FontSize { Val = "32" },              // 16pt = 三号 (in half-points)
                    new FontSizeComplexScript { Val = "32" },
                    new Color { Val = "000000" },
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Fixed 28pt line spacing per GB/T 9704
                        // 28pt * 20 = 560 DXA (line units in exact mode)
                        Line = "560",
                        LineRule = LineSpacingRuleValues.Exact,
                        After = "0",
                        Before = "0"
                    }
                )
            )
        ));

        // ── Normal style ──
        styles.Append(CreateParagraphStyle(
            styleId: "Normal",
            styleName: "Normal",
            isDefault: true,
            uiPriority: 0
        ));

        // ── Title style (小标宋 二号 22pt) ──
        // Government document title uses a specialized display serif font.
        // 二号 = 22pt = 44 half-points.
        var titleStyle = new Style(
            new StyleName { Val = "heading 1" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines
                {
                    Line = "560", LineRule = LineSpacingRuleValues.Exact,
                    Before = "0", After = "0"
                },
                new OutlineLevel { Val = 0 }
            ),
            new StyleRunProperties(
                new RunFonts
                {
                    // 小标宋体 is the government standard for titles.
                    // Falls back to 华文中宋 or SimSun on systems without it.
                    Ascii = "SimSun",
                    HighAnsi = "SimSun",
                    EastAsia = "FZXiaoBiaoSong-B05S",
                    ComplexScript = "SimSun"
                },
                new FontSize { Val = "44" },              // 22pt = 二号
                new FontSizeComplexScript { Val = "44" },
                new Color { Val = "000000" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Heading1", Default = false };
        styles.Append(titleStyle);

        // ── Heading 2: 黑体 三号 (16pt) ──
        // 黑体 (SimHei) is the standard sans-serif for first-level section headings.
        var h2Style = new Style(
            new StyleName { Val = "heading 2" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines
                {
                    Line = "560", LineRule = LineSpacingRuleValues.Exact,
                    Before = "0", After = "0"
                },
                new OutlineLevel { Val = 1 }
            ),
            new StyleRunProperties(
                new RunFonts
                {
                    Ascii = "SimHei",
                    HighAnsi = "SimHei",
                    EastAsia = "SimHei",
                    ComplexScript = "SimHei"
                },
                new FontSize { Val = "32" },              // 16pt = 三号
                new FontSizeComplexScript { Val = "32" },
                new Color { Val = "000000" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Heading2", Default = false };
        styles.Append(h2Style);

        // ── Heading 3: 楷体 三号 (16pt) ──
        // 楷体 (KaiTi) for second-level section headings.
        var h3Style = new Style(
            new StyleName { Val = "heading 3" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines
                {
                    Line = "560", LineRule = LineSpacingRuleValues.Exact,
                    Before = "0", After = "0"
                },
                new OutlineLevel { Val = 2 }
            ),
            new StyleRunProperties(
                new RunFonts
                {
                    Ascii = "KaiTi",
                    HighAnsi = "KaiTi",
                    EastAsia = "KaiTi_GB2312",
                    ComplexScript = "KaiTi"
                },
                new FontSize { Val = "32" },              // 16pt = 三号
                new FontSizeComplexScript { Val = "32" },
                new Color { Val = "000000" }
            )
        )
        { Type = StyleValues.Paragraph, StyleId = "Heading3", Default = false };
        styles.Append(h3Style);

        // ── ListBullet style ──
        styles.Append(CreateParagraphStyle(
            styleId: "ListBullet",
            styleName: "List Bullet",
            basedOn: "Normal",
            uiPriority: 36
        ));

        // ── Caption style ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "32",        // 三号 per standard
            color: "000000",
            italic: false                 // Chinese government docs do not use italic
        ));

        // ── Page setup: A4, GB/T 9704 margins ──
        // A4 = 210mm x 297mm = 11906 x 16838 DXA
        // Margins per GB/T 9704: T:37mm B:35mm L:28mm R:26mm
        //   T: 37mm = 37 * 56.7 ≈ 2098 DXA
        //   B: 35mm = 35 * 56.7 ≈ 1984 DXA
        //   L: 28mm = 28 * 56.7 ≈ 1588 DXA
        //   R: 26mm = 26 * 56.7 ≈ 1474 DXA
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 11906U, Height = 16838U },
            new PageMargin
            {
                Top = 2098, Bottom = 1984,
                Left = 1588U, Right = 1474U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: bottom center, "-X-" format, 宋体 四号 (14pt) ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "28",        // 14pt = 四号
            color: "000000",
            format: PageNumberFormat.DashSurrounded,  // -X- format
            fontName: "SimSun"            // 宋体 for page numbers
        );

        // ── Sample content ──
        // Government document title
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("关于加强文档排版规范化管理的通知"))
        ));

        // Body text
        body.Append(new Paragraph(
            new Run(new Text("各有关单位：") { Space = SpaceProcessingModeValues.Preserve })
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "640" }   // 2 Chinese characters = 640 DXA at 16pt
            ),
            new Run(new Text("为进一步规范公文格式，提高公文质量，根据《党政机关公文格式》"
                + "（GB/T 9704-2012）的有关规定，现就加强文档排版规范化管理有关事项通知如下。"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" }
            ),
            new Run(new Text("一、总体要求"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "640" }
            ),
            new Run(new Text("各单位应严格按照国家标准规定的格式要求制作公文，"
                + "确保公文格式统一、规范、美观。公文用纸统一采用A4型纸，"
                + "正文使用仿宋体三号字，行间距为固定值28磅。"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading3" }
            ),
            new Run(new Text("（一）字体要求"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "640" }
            ),
            new Run(new Text("标题使用小标宋体二号字，一级标题使用黑体三号字，"
                + "二级标题使用楷体三号字，正文使用仿宋体三号字。"))
        ));

        // ── Three-line table (三线表 is also used in Chinese government documents) ──
        body.Append(CreateThreeLineTable(
            new[] { "项目", "要求", "字体", "字号" },
            new[]
            {
                new[] { "标题", "居中", "小标宋体", "二号" },
                new[] { "一级标题", "左对齐", "黑体", "三号" },
                new[] { "二级标题", "左对齐", "楷体", "三号" },
                new[] { "正文", "两端对齐", "仿宋体", "三号" }
            }
        ));

        body.Append(sectPr);
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 5: MINIMAL MODERN
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Minimal Modern
    /// Feel: Scandinavian-inspired, lots of white space, geometric.
    /// Best for: Design documents, creative briefs, tech company communications.
    ///
    /// Design rationale:
    /// - Inter/Segoe UI 10.5pt body: a geometric sans-serif designed for screens.
    ///   10.5pt is slightly smaller than standard, creating a more designed, intentional
    ///   feel. The precision of geometric sans-serifs communicates clarity of thought.
    /// - H1 24pt light weight: large but thin creates a "whisper, don't shout" hierarchy.
    ///   The size difference does the work; bold weight would be crude.
    /// - 1.5x line spacing (360 line units): very generous. Combined with 10.5pt body,
    ///   this creates the characteristic "Scandinavian" feel of lots of air.
    /// - 12pt paragraph spacing: each paragraph is a distinct visual block separated
    ///   by substantial white space. This supports the "one idea per paragraph" pattern.
    /// - 1.5in left/right margins: extreme horizontal compression creates a narrow
    ///   text column (~5.5in wide, ~65 characters per line). This is the optimal
    ///   line length for comfortable reading (60-75 chars).
    /// - #111111 headings, #444444 body: very slight differentiation. The hierarchy
    ///   comes from size and weight, not color. This is the "less contrast, more
    ///   sophistication" school.
    /// - #0066CC accent blue: a single accent color for interactive elements or emphasis.
    /// - Tables: header-only bottom border, nothing else. Maximum minimalism.
    /// </summary>
    public static void CreateMinimalModernDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Inter/Segoe UI 10.5pt, very generous spacing
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        // Inter is a Google Fonts geometric sans-serif designed for screens.
                        // Segoe UI is the Windows system font fallback.
                        Ascii = "Inter",
                        HighAnsi = "Inter",
                        EastAsia = "Microsoft YaHei",
                        ComplexScript = "Segoe UI"
                    },
                    new FontSize { Val = "21" },              // 10.5pt — intentionally precise
                    new FontSizeComplexScript { Val = "21" },
                    new Color { Val = "444444" },             // Medium gray body — soft and modern
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // 1.5x line spacing: generous air for the minimal aesthetic.
                        // Combined with narrow column width, this creates comfortable reading.
                        Line = "360",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "240"   // 12pt after — very generous paragraph separation
                    }
                )
            )
        ));

        // ── Normal style ──
        styles.Append(CreateParagraphStyle(
            styleId: "Normal",
            styleName: "Normal",
            isDefault: true,
            uiPriority: 0
        ));

        // ── Heading 1: 24pt light ──
        // "Light" weight creates elegant, airy hierarchy. The size alone does the work.
        // Since OpenXML doesn't have a "light" weight, we achieve this by not using bold.
        // On systems with Inter, the regular weight already appears relatively light.
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Inter",
            fontHAnsi: "Inter",
            sizeHalfPts: "48",            // 24pt — large but not bold = "whispering loudly"
            color: "111111",              // Near-black — just barely softened
            bold: false,                  // NO bold: the key to the minimal aesthetic
            spaceBefore: "480",
            spaceAfter: "120",
            uiPriority: 9
        ));

        // ── Heading 2: 16pt regular ──
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Inter",
            fontHAnsi: "Inter",
            sizeHalfPts: "32",            // 16pt
            color: "111111",
            bold: false,
            spaceBefore: "360",
            spaceAfter: "80",
            uiPriority: 9
        ));

        // ── Heading 3: 12pt medium ──
        // "Medium" is between regular and bold. We use bold here as the closest
        // approximation in OpenXML (true medium weight requires theme fonts).
        styles.Append(CreateHeadingStyle(
            level: 3,
            fontAscii: "Inter",
            fontHAnsi: "Inter",
            sizeHalfPts: "24",            // 12pt
            color: "111111",
            bold: true,                   // Approximates "medium" weight
            spaceBefore: "240",
            spaceAfter: "80",
            uiPriority: 9
        ));

        // ── ListBullet style ──
        styles.Append(CreateParagraphStyle(
            styleId: "ListBullet",
            styleName: "List Bullet",
            basedOn: "Normal",
            uiPriority: 36
        ));

        // ── Caption style ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "18",        // 9pt
            color: "999999",
            italic: false                 // Minimal style avoids italic
        ));

        // ── Page setup: Letter, wide left/right margins, normal top/bottom ──
        // Wide L/R margins create a narrow text column (~5.5in = ~65 chars per line).
        // This is the optimal line length for comfortable reading.
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,       // 1in top/bottom
                Left = 2160U, Right = 2160U,     // 1.5in left/right — narrow column
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── No page numbers for the minimal aesthetic ──
        // In production, add page numbers only if document exceeds 5 pages.
        // For this sample, we omit them entirely — the cleanest look.

        // ── Sample content ──
        AddSampleParagraph(body, "Design System", "Heading1");

        AddSampleParagraph(body, "A design system is a collection of reusable components "
            + "and clear standards that can be assembled to build any number of applications. "
            + "It reduces redundancy, creates consistency, and enables teams to build faster.",
            "Normal");

        AddSampleParagraph(body, "Typography", "Heading2");

        AddSampleParagraph(body, "Typography is the foundation of any design system. "
            + "The type scale, spacing, and color choices establish the visual rhythm "
            + "that all other elements follow.",
            "Normal");

        AddSampleParagraph(body, "Type Scale", "Heading3");

        AddSampleParagraph(body, "Our type scale uses a 1.5x ratio, creating clear "
            + "hierarchy without excessive size variation. Each level is visually distinct "
            + "yet feels part of a cohesive family.",
            "Normal");

        // ── Minimal table: header bottom border only ──
        body.Append(CreateMinimalTable(
            new[] { "Token", "Value", "Usage" },
            new[]
            {
                new[] { "font-size-xs", "10.5pt", "Captions, metadata" },
                new[] { "font-size-sm", "12pt", "Secondary text" },
                new[] { "font-size-base", "10.5pt", "Body text" },
                new[] { "font-size-lg", "16pt", "Section headings" },
                new[] { "font-size-xl", "24pt", "Page titles" }
            }
        ));

        AddSampleParagraph(body, "Table 1 — Type scale tokens", "Caption");

        AddSampleParagraph(body, "Color", "Heading2");

        AddSampleParagraph(body, "Our palette is intentionally restrained. Two grays "
            + "for text hierarchy, one accent blue for interactive elements, and generous "
            + "white space as the primary design element.",
            "Normal");

        body.Append(sectPr);
    }

    /// <summary>
    /// Minimal table: only the header row gets a bottom border.
    /// Everything else is borderless. Maximum restraint.
    /// The alignment and spacing do all the structural work.
    /// </summary>
    private static Table CreateMinimalTable(string[] headers, string[][] data)
    {
        var table = new Table();

        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            // No borders at all at the table level
            new TableBorders(
                new TopBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            new TableCellMarginDefault(
                new TopMargin { Width = "40", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "57", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "40", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "57", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid
        var grid = new TableGrid();
        int colWidth = 7920 / headers.Length;   // narrower text area due to wide margins
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Header row: only element with a visible border (bottom only)
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            headerRow.Append(new TableCell(
                new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                    new TableCellBorders(
                        // Single thin bottom border — the only line in the entire table
                        new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "CCCCCC" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0" }
                    ),
                    new Run(
                        new RunProperties(
                            new Color { Val = "111111" }      // Slightly darker than body
                        ),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows: completely borderless
        foreach (var rowData in data)
        {
            var row = new TableRow();
            foreach (var cell in rowData)
            {
                row.Append(new TableCell(
                    new TableCellProperties(
                        new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto }
                    ),
                    new Paragraph(
                        new ParagraphProperties(
                            new SpacingBetweenLines { After = "0" }
                        ),
                        new Run(new Text(cell))
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }


    // ════════════════════════════════════════════════════════════════════════
    // SHARED HELPER METHODS
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Creates a basic paragraph style with minimal configuration.
    /// Used for Normal, ListBullet, and other simple styles.
    /// </summary>
    private static Style CreateParagraphStyle(
        string styleId,
        string styleName,
        bool isDefault = false,
        string? basedOn = null,
        int uiPriority = 0)
    {
        var style = new Style(
            new StyleName { Val = styleName },
            new UIPriority { Val = uiPriority },
            new PrimaryStyle()
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = styleId,
            Default = isDefault ? true : false
        };

        if (basedOn != null)
            style.Append(new BasedOn { Val = basedOn });

        return style;
    }

    /// <summary>
    /// Creates a heading style with full formatting configuration.
    /// All heading styles are based on "Normal" (not chained H2→H1)
    /// because each heading level has completely different formatting.
    /// </summary>
    private static Style CreateHeadingStyle(
        int level,
        string fontAscii,
        string fontHAnsi,
        string sizeHalfPts,
        string color,
        bool bold,
        string spaceBefore,
        string spaceAfter,
        int uiPriority)
    {
        var rPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = fontAscii,
                HighAnsi = fontHAnsi,
                EastAsia = "SimSun",
                ComplexScript = fontAscii
            },
            new FontSize { Val = sizeHalfPts },
            new FontSizeComplexScript { Val = sizeHalfPts },
            new Color { Val = color }
        );

        if (bold)
            rPr.Append(new Bold());

        var style = new Style(
            new StyleName { Val = $"heading {level}" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = uiPriority },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),               // Don't orphan a heading at page bottom
                new KeepLines(),              // Don't split a heading across pages
                new SpacingBetweenLines
                {
                    Before = spaceBefore,
                    After = spaceAfter
                },
                new OutlineLevel { Val = level - 1 }  // OutlineLevel is 0-based
            ),
            rPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = $"Heading{level}",
            Default = false
        };

        return style;
    }

    /// <summary>
    /// Creates an APA-style heading where hierarchy is expressed through
    /// bold/italic/centering rather than font size changes.
    /// All headings remain 12pt — the same as body text.
    /// </summary>
    private static Style CreateAcademicHeadingStyle(
        int level,
        string sizeHalfPts,
        bool bold,
        bool italic,
        bool centered,
        string spaceBefore,
        string spaceAfter)
    {
        var rPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = sizeHalfPts },
            new FontSizeComplexScript { Val = sizeHalfPts },
            new Color { Val = "000000" }
        );

        if (bold)
            rPr.Append(new Bold());
        if (italic)
            rPr.Append(new Italic());

        var pPr = new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new SpacingBetweenLines
            {
                Before = spaceBefore,
                After = spaceAfter,
                Line = "480",
                LineRule = LineSpacingRuleValues.Auto
            },
            // No first-line indent for headings
            new Indentation { FirstLine = "0" },
            new OutlineLevel { Val = level - 1 }
        );

        if (centered)
            pPr.Append(new Justification { Val = JustificationValues.Center });

        var style = new Style(
            new StyleName { Val = $"heading {level}" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            pPr,
            rPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = $"Heading{level}",
            Default = false
        };

        return style;
    }

    /// <summary>
    /// Creates a Caption style used below tables and figures.
    /// Captions are typically smaller and/or italic to visually subordinate them.
    /// </summary>
    private static Style CreateCaptionStyle(
        string fontSizeHalfPts,
        string color,
        bool italic)
    {
        var rPr = new StyleRunProperties(
            new FontSize { Val = fontSizeHalfPts },
            new FontSizeComplexScript { Val = fontSizeHalfPts },
            new Color { Val = color }
        );

        if (italic)
            rPr.Append(new Italic());

        return new Style(
            new StyleName { Val = "caption" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 35 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { After = "120" }
            ),
            rPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Caption",
            Default = false
        };
    }

    /// <summary>
    /// Page number format options.
    /// </summary>
    private enum PageNumberFormat
    {
        /// <summary>Plain number: "1", "2", "3"</summary>
        Plain,
        /// <summary>Dash-surrounded: "-1-", "-2-", "-3-" (Chinese government standard)</summary>
        DashSurrounded
    }

    /// <summary>
    /// Adds a footer (or header) with page numbers to the document.
    ///
    /// Page numbers use the PAGE simple field code. The footer/header is linked
    /// to the section via a FooterReference/HeaderReference in SectionProperties.
    ///
    /// Architecture:
    ///   1. Create a FooterPart (or HeaderPart) on the MainDocumentPart
    ///   2. Add the page number content (Paragraph with SimpleField)
    ///   3. Get the relationship ID
    ///   4. Add FooterReference (or HeaderReference) to SectionProperties
    /// </summary>
    private static void AddPageNumberFooter(
        MainDocumentPart mainPart,
        SectionProperties sectPr,
        JustificationValues alignment,
        string fontSizeHalfPts,
        string color,
        PageNumberFormat format,
        bool isHeader = false,
        string? fontName = null)
    {
        var runProps = new RunProperties(
            new FontSize { Val = fontSizeHalfPts },
            new FontSizeComplexScript { Val = fontSizeHalfPts },
            new Color { Val = color }
        );

        if (fontName != null)
            runProps.Append(new RunFonts { Ascii = fontName, HighAnsi = fontName, EastAsia = fontName });

        // Build the paragraph content based on format
        var paragraph = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = alignment }
            )
        );

        if (format == PageNumberFormat.DashSurrounded)
        {
            // "-X-" format: literal dash + PAGE field + literal dash
            paragraph.Append(new Run(
                (RunProperties)runProps.CloneNode(true),
                new Text("-") { Space = SpaceProcessingModeValues.Preserve }
            ));
        }

        // PAGE field — inserts the current page number
        paragraph.Append(new SimpleField(
            new Run((RunProperties)runProps.CloneNode(true), new Text("1"))
        )
        { Instruction = " PAGE " });

        if (format == PageNumberFormat.DashSurrounded)
        {
            paragraph.Append(new Run(
                (RunProperties)runProps.CloneNode(true),
                new Text("-") { Space = SpaceProcessingModeValues.Preserve }
            ));
        }

        if (isHeader)
        {
            // Add as header
            var headerPart = mainPart.AddNewPart<HeaderPart>();
            headerPart.Header = new Header(paragraph);
            headerPart.Header.Save();

            string headerPartId = mainPart.GetIdOfPart(headerPart);
            sectPr.Append(new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = headerPartId
            });
        }
        else
        {
            // Add as footer
            var footerPart = mainPart.AddNewPart<FooterPart>();
            footerPart.Footer = new Footer(paragraph);
            footerPart.Footer.Save();

            string footerPartId = mainPart.GetIdOfPart(footerPart);
            sectPr.Append(new FooterReference
            {
                Type = HeaderFooterValues.Default,
                Id = footerPartId
            });
        }
    }

    /// <summary>
    /// Helper to add a paragraph with a specific style.
    /// </summary>
    private static void AddSampleParagraph(Body body, string text, string styleId)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = styleId }
            ),
            new Run(new Text(text))
        ));
    }
}
