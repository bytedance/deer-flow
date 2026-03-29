// ============================================================================
// AestheticRecipeSamples_Batch4.cs — Nature Journal & HBR-style recipes
// ============================================================================
// Recipes 12-13: publication and business editorial formatting systems.
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

using WpColumns = DocumentFormat.OpenXml.Wordprocessing.Columns;
using WpPageSize = DocumentFormat.OpenXml.Wordprocessing.PageSize;

namespace MiniMaxAIDocx.Core.Samples;

public static partial class AestheticRecipeSamples
{
    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 12: NATURE JOURNAL
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Nature Journal Format
    /// Source: Nature formatting guide (nature.com/nature/for-authors/formatting-guide)
    /// Feel: Dense, authoritative, information-rich scientific publication.
    /// Best for: Scientific research articles, peer-reviewed papers.
    ///
    /// Design rationale:
    /// - A4 page (210mm x 297mm): international scientific standard.
    /// - Two-column layout with 5mm gutter: maximizes information density while
    ///   keeping line length short (~88mm / ~45 characters) for rapid scanning.
    ///   Short lines reduce saccade distance, aiding speed-reading of dense text.
    /// - 9pt Times New Roman body: Nature's actual body size. Smaller than typical
    ///   to fit more content per page; serif font maintains readability at this size.
    /// - 14pt bold title spanning full width: clear visual anchor above the columns.
    /// - Section headings bold, flush left, NOT numbered: Nature convention.
    ///   Unnumbered headings create a flowing narrative feel rather than a report feel.
    /// - Single line spacing: tight vertical rhythm matches the dense two-column layout.
    /// - "Figure 1 |" caption format with pipe separator: Nature's distinctive style.
    /// - 7pt references: subordinate to body text, numbered with superscript citations.
    /// - Abstract is full-width, single paragraph, max ~150 words: Nature requirement.
    ///   Placed between title and two-column body via continuous section break.
    /// </summary>
    public static void CreateNatureJournalDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: 9pt Times New Roman, single spacing, no indent
        // 9pt = 18 half-points. Nature body text is compact.
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
                    new FontSize { Val = "18" },              // 9pt body
                    new FontSizeComplexScript { Val = "18" },
                    new Color { Val = "000000" },
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Single spacing: 240 = 1.0x
                        // Nature uses tight spacing to maximize content density
                        Line = "240",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"
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

        // ── Title style: 14pt bold, full width ──
        // Title is placed before the two-column section so it spans full width
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Times New Roman",
            fontHAnsi: "Times New Roman",
            sizeHalfPts: "28",            // 14pt
            color: "000000",
            bold: true,
            spaceBefore: "0",
            spaceAfter: "120",            // 6pt after title
            uiPriority: 9
        ));

        // ── Section headings: bold, flush left, not numbered ──
        // Nature uses bold headings at body size — hierarchy through weight, not size
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Times New Roman",
            fontHAnsi: "Times New Roman",
            sizeHalfPts: "18",            // 9pt — same as body
            color: "000000",
            bold: true,
            spaceBefore: "200",           // 10pt before section
            spaceAfter: "80",             // 4pt after
            uiPriority: 9
        ));

        // ── Caption style: 8pt for figure/table captions ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "16",        // 8pt (sz=16)
            color: "000000",
            italic: false                 // Nature captions are not italic
        ));

        // ══════════════════════════════════════════════════════════════════
        // FULL-WIDTH SECTION: Title + Abstract
        // In OpenXML, to switch from single-column to two-column, we place
        // a continuous section break after the full-width content.
        // The section break carries the single-column page setup.
        // ══════════════════════════════════════════════════════════════════

        // ── Title (full width) ──
        AddSampleParagraph(body,
            "Quantum entanglement distillation in noisy intermediate-scale devices",
            "Heading1");

        // ── Authors (full width, 9pt, not a heading) ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "60" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text("A. Chen, B. Kumar, C. Nakamura & D. Okonkwo")
            )
        ));

        // ── Affiliations ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "120" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "14" },              // 7pt
                    new FontSizeComplexScript { Val = "14" },
                    new Italic(),
                    new Color { Val = "444444" }
                ),
                new Text("Department of Physics, University of Oxford, Oxford OX1 3PU, UK")
            )
        ));

        // ── Abstract heading ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { Before = "120", After = "60" }
            ),
            new Run(
                new RunProperties(new Bold()),
                new Text("Abstract")
            )
        ));

        // ── Abstract body (full width, single paragraph) ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "120" }
            ),
            new Run(new Text(
                "Entanglement distillation is essential for practical quantum communication "
                + "and distributed quantum computing. Here we demonstrate a protocol that achieves "
                + "high-fidelity entanglement distillation on noisy intermediate-scale quantum (NISQ) "
                + "devices using adaptive error mitigation. Our approach reduces resource overhead by "
                + "63% compared to conventional recurrence protocols while maintaining a fidelity above "
                + "0.97 for Bell pairs subject to depolarizing noise up to 15%. We validate the protocol "
                + "on a 127-qubit superconducting processor and present a theoretical framework for "
                + "scaling to multi-party entanglement. These results establish a practical pathway "
                + "toward noise-resilient quantum networks."
            ))
        ));

        // ── Continuous section break: ends the full-width section ──
        // This SectionProperties defines the PRECEDING content as single-column.
        // A4: Width=11906, Height=16838 (DXA).
        // Margins: Top/Bottom=1in(1440), Left/Right=0.75in(1080).
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SectionProperties(
                    new SectionType { Val = SectionMarkValues.Continuous },
                    new WpPageSize { Width = 11906U, Height = 16838U },
                    new PageMargin
                    {
                        Top = 1440, Bottom = 1440,
                        Left = 1080U, Right = 1080U,
                        Header = 720U, Footer = 720U, Gutter = 0U
                    }
                    // Single column (default) — no Columns element needed
                )
            )
        ));

        // ══════════════════════════════════════════════════════════════════
        // TWO-COLUMN SECTION: Body text
        // All content after the continuous break until the final section
        // properties will be rendered in two columns.
        // ══════════════════════════════════════════════════════════════════

        // ── Body sections (two-column) ──
        AddSampleParagraph(body, "Introduction", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "Quantum entanglement is a fundamental resource for quantum information processing, "
            + "enabling applications ranging from quantum key distribution to distributed quantum "
            + "computation. However, entanglement is fragile and degrades rapidly under environmental "
            + "noise, necessitating distillation protocols that extract high-fidelity entangled states "
            + "from multiple noisy copies."
        ))));

        // Superscript citation example
        body.Append(new Paragraph(
            new Run(new Text(
                "Previous approaches to entanglement distillation have relied on recurrence protocols"
            ) { Space = SpaceProcessingModeValues.Preserve }),
            new Run(
                new RunProperties(new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }),
                new Text("1,2")
            ),
            new Run(new Text(
                " or hashing protocols"
            ) { Space = SpaceProcessingModeValues.Preserve }),
            new Run(
                new RunProperties(new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }),
                new Text("3")
            ),
            new Run(new Text(
                ", both of which require significant quantum resources that exceed the capabilities "
                + "of current hardware."
            ))
        ));

        AddSampleParagraph(body, "Results", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "We implemented our adaptive distillation protocol on a 127-qubit IBM Eagle processor. "
            + "The protocol operates in three stages: initial Bell pair preparation, syndrome-based "
            + "error detection, and adaptive recurrence with dynamically adjusted thresholds."
        ))));

        // ── Table with Nature "Table 1 |" format ──
        body.Append(CreateNatureTable(
            "Table 1 | Distillation performance metrics",
            new[] { "Noise level", "Input fidelity", "Output fidelity", "Success rate" },
            new[]
            {
                new[] { "5%", "0.912", "0.991", "72%" },
                new[] { "10%", "0.847", "0.983", "58%" },
                new[] { "15%", "0.781", "0.971", "41%" }
            }
        ));

        AddSampleParagraph(body, "Discussion", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "Our results demonstrate that adaptive error mitigation can substantially reduce the "
            + "resource overhead of entanglement distillation. The key insight is that by monitoring "
            + "syndrome patterns in real time, the protocol can dynamically adjust its acceptance "
            + "thresholds, avoiding unnecessary rounds of distillation when noise is below expected levels."
        ))));

        // ── Figure caption in Nature style: "Figure 1 |" ──
        body.Append(CreateNatureFigureCaption(1,
            "Distillation fidelity as a function of input noise level. "
            + "Blue circles show experimental data from the 127-qubit processor; "
            + "solid line shows theoretical prediction. Error bars represent one standard deviation "
            + "over 1,000 shots per data point."));

        AddSampleParagraph(body, "Methods", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "Bell pairs were prepared using the standard CNOT-Hadamard circuit. Depolarizing noise "
            + "was introduced via randomized Pauli rotations calibrated to target error rates. "
            + "Each experimental configuration was repeated 10,000 times to ensure statistical "
            + "significance."
        ))));

        // ── References section ──
        AddSampleParagraph(body, "References", "Heading2");

        AddNatureReference(body, 1, "Bennett, C. H. et al. Purification of noisy entanglement "
            + "and faithful teleportation via noisy channels. Phys. Rev. Lett. 76, 722\u2013725 (1996).");
        AddNatureReference(body, 2, "Deutsch, D. et al. Quantum privacy amplification and the security "
            + "of quantum cryptography over noisy channels. Phys. Rev. Lett. 77, 2818\u20132821 (1996).");
        AddNatureReference(body, 3, "Bennett, C. H. et al. Mixed-state entanglement and quantum error "
            + "correction. Phys. Rev. A 54, 3824\u20133851 (1996).");
        AddNatureReference(body, 4, "Pan, J.-W. et al. Entanglement purification for quantum "
            + "communication. Nature 410, 1067\u20131070 (2001).");

        // ── Final section properties: two-column layout ──
        // This defines the formatting for the body section.
        var finalSectPr = new SectionProperties(
            new SectionType { Val = SectionMarkValues.Continuous },
            new WpPageSize { Width = 11906U, Height = 16838U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1080U, Right = 1080U,
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            new WpColumns
            {
                ColumnCount = 2,
                Space = "283"             // ~5mm gutter between columns
            }
        );

        // Page numbers: bottom center, 8pt
        AddPageNumberFooter(mainPart, finalSectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "16",        // 8pt
            color: "000000",
            format: PageNumberFormat.Plain
        );

        body.Append(finalSectPr);
    }

    /// <summary>
    /// Creates a Nature-style table with caption above.
    /// Nature tables use "Table N |" format for the caption label, followed by
    /// a description. The table itself has a clean three-line style (top rule,
    /// header rule, bottom rule) with no vertical borders.
    /// </summary>
    private static Table CreateNatureTable(string captionText, string[] headers, string[][] data)
    {
        // The caption is placed as a paragraph before the table in the calling code,
        // but here we embed it as part of the table structure for cohesion.
        var table = new Table();

        // Table properties: full width, three-line borders
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "000000" },
                new BottomBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "000000" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            new TableCellMarginDefault(
                new TopMargin { Width = "20", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "40", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "20", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "40", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid columns
        var grid = new TableGrid();
        int colWidth = 9746 / headers.Length;  // A4 minus margins
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Caption row spanning all columns
        var captionRow = new TableRow();
        var captionCell = new TableCell(
            new TableCellProperties(
                new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                new GridSpan { Val = headers.Length },
                new TableCellBorders(
                    new TopBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                    new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
                )
            )
        );

        // Parse "Table 1 |" from the caption text — bold the label part
        var captionPara = new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "40" }
            )
        );
        int pipeIdx = captionText.IndexOf('|');
        if (pipeIdx > 0)
        {
            // Bold "Table 1 |"
            captionPara.Append(new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "16" },
                    new FontSizeComplexScript { Val = "16" }
                ),
                new Text(captionText.Substring(0, pipeIdx + 1)) { Space = SpaceProcessingModeValues.Preserve }
            ));
            // Regular description
            captionPara.Append(new Run(
                new RunProperties(
                    new FontSize { Val = "16" },
                    new FontSizeComplexScript { Val = "16" }
                ),
                new Text(captionText.Substring(pipeIdx + 1))
            ));
        }
        else
        {
            captionPara.Append(new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "16" },
                    new FontSizeComplexScript { Val = "16" }
                ),
                new Text(captionText)
            ));
        }

        captionCell.Append(captionPara);
        captionRow.Append(captionCell);
        table.Append(captionRow);

        // Header row with bottom border (the second "line" of three-line table)
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            headerRow.Append(new TableCell(
                new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                    new TableCellBorders(
                        new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0" }
                    ),
                    new Run(
                        new RunProperties(new Bold(), new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" }),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows — no internal borders
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
                        new Run(
                            new RunProperties(new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" }),
                            new Text(cell)
                        )
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }

    /// <summary>
    /// Creates a Nature-style figure caption: "Figure N |" with bold label and pipe separator.
    /// 8pt (sz=16), placed below the figure placeholder.
    /// </summary>
    private static Paragraph CreateNatureFigureCaption(int figureNumber, string description)
    {
        return new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { Before = "120", After = "120" }
            ),
            new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "16" },
                    new FontSizeComplexScript { Val = "16" }
                ),
                new Text($"Figure {figureNumber} | ") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "16" },
                    new FontSizeComplexScript { Val = "16" }
                ),
                new Text(description)
            )
        );
    }

    /// <summary>
    /// Adds a Nature-style numbered reference in 7pt (sz=14).
    /// References are numbered sequentially and appear in a compact list.
    /// </summary>
    private static void AddNatureReference(Body body, int number, string referenceText)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "20" },
                new Indentation { Left = "240", Hanging = "240" }  // Hanging indent for number
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "14" },              // 7pt
                    new FontSizeComplexScript { Val = "14" }
                ),
                new Text($"{number}. ") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "14" },
                    new FontSizeComplexScript { Val = "14" }
                ),
                new Text(referenceText)
            )
        ));
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 13: HARVARD BUSINESS REVIEW STYLE
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Harvard Business Review (HBR) Published Format
    /// Source: Analysis of Harvard Business Review published article formatting
    /// Feel: Premium, editorial, executive-level business content.
    /// Best for: Business strategy articles, thought leadership, executive presentations.
    ///
    /// Design rationale:
    /// - US Letter with generous 1.25in margins (1800 DXA): creates a luxurious
    ///   text block width (~6in / 390pt) that signals premium editorial content.
    ///   Wider margins = shorter lines = more deliberate, executive-level reading pace.
    /// - 11pt Georgia body (#333333): Georgia was designed specifically for screen
    ///   and print readability. Its larger x-height and open counters make it more
    ///   readable than Times New Roman at the same size. The warm serif conveys
    ///   authority and thoughtfulness appropriate for business strategy content.
    /// - 24pt Georgia bold title (#1A1A1A): commanding but not aggressive.
    ///   Near-black (#1A1A1A) is softer than pure black while maintaining authority.
    /// - 14pt subtitle/deck in #666666: the "deck" (magazine term) summarizes the
    ///   article's thesis. Medium gray subordinates it to the title without losing it.
    /// - NO first-line indent: HBR uses block paragraphs with space-after (10pt/200 DXA).
    ///   This is the modern editorial convention — cleaner than academic indentation.
    /// - 1.3x line spacing (line=312): slightly more open than 1.15x corporate standard,
    ///   signaling a more considered, editorial reading experience.
    /// - "Exhibit" labels (not "Table"): HBR's distinctive terminology that signals
    ///   business/consulting context rather than academic/scientific.
    /// - Pull quotes: 16pt italic Georgia in #666666, indented — a magazine convention
    ///   that breaks up long text and highlights key insights for scanning executives.
    /// - Minimal section numbering: HBR uses a flowing narrative style, not a
    ///   numbered outline. Headings are signposts, not a hierarchy to navigate.
    /// </summary>
    public static void CreateHBRStyleDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: 11pt Georgia, 1.3x spacing, no first-line indent
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        Ascii = "Georgia",
                        HighAnsi = "Georgia",
                        EastAsia = "SimSun",
                        ComplexScript = "Georgia"
                    },
                    new FontSize { Val = "22" },              // 11pt (sz=22)
                    new FontSizeComplexScript { Val = "22" },
                    new Color { Val = "333333" },             // Warm dark gray — premium feel
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // 1.3x line spacing: 240 * 1.3 = 312
                        // More open than corporate 1.15x — signals editorial content
                        Line = "312",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "200"   // 10pt after — block paragraph separation
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

        // ── Title: 24pt Georgia bold, near-black ──
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Georgia",
            fontHAnsi: "Georgia",
            sizeHalfPts: "48",            // 24pt (sz=48)
            color: "1A1A1A",              // Near-black — authoritative but soft
            bold: true,
            spaceBefore: "0",
            spaceAfter: "120",            // 6pt after title
            uiPriority: 9
        ));

        // ── H1: 18pt Georgia bold ──
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Georgia",
            fontHAnsi: "Georgia",
            sizeHalfPts: "36",            // 18pt (sz=36)
            color: "1A1A1A",
            bold: true,
            spaceBefore: "480",           // 24pt before — clear section break
            spaceAfter: "120",            // 6pt after
            uiPriority: 9
        ));

        // ── H2: 14pt Georgia bold ──
        styles.Append(CreateHeadingStyle(
            level: 3,
            fontAscii: "Georgia",
            fontHAnsi: "Georgia",
            sizeHalfPts: "28",            // 14pt (sz=28)
            color: "1A1A1A",
            bold: true,
            spaceBefore: "360",           // 18pt before
            spaceAfter: "80",             // 4pt after
            uiPriority: 9
        ));

        // ── Caption style: 9pt Georgia, gray ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "18",        // 9pt
            color: "666666",
            italic: false
        ));

        // ── Page setup: US Letter, 1.25in margins ──
        // Letter = 8.5" x 11" = 12240 x 15840 DXA
        // 1.25in = 1800 DXA on all sides
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1800, Bottom = 1800,
                Left = 1800U, Right = 1800U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // Page numbers: bottom center, 9pt gray
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "18",
            color: "999999",
            format: PageNumberFormat.Plain
        );

        // ══════════════════════════════════════════════════════════════════
        // SAMPLE CONTENT
        // ══════════════════════════════════════════════════════════════════

        // ── Title ──
        AddSampleParagraph(body,
            "The Hidden Architecture of Market-Creating Innovation",
            "Heading1");

        // ── Subtitle/deck: 14pt Georgia regular, #666666 ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "360" }     // Extra space after deck
            ),
            new Run(
                new RunProperties(
                    new RunFonts { Ascii = "Georgia", HighAnsi = "Georgia" },
                    new FontSize { Val = "28" },              // 14pt (sz=28)
                    new FontSizeComplexScript { Val = "28" },
                    new Color { Val = "666666" }
                ),
                new Text("Why the most transformative companies don't compete on existing metrics "
                    + "-- and what leaders can learn from their approach to creating entirely new markets.")
            )
        ));

        // ── Author byline ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "360" }
            ),
            new Run(
                new RunProperties(
                    new Italic(),
                    new Color { Val = "666666" }
                ),
                new Text("by Margaret Chen and Robert Stavros")
            )
        ));

        // ── Opening paragraph ──
        body.Append(new Paragraph(new Run(new Text(
            "In the decade since Clayton Christensen's theory of disruptive innovation reshaped "
            + "corporate strategy, a more nuanced pattern has emerged. The most transformative "
            + "companies of the past five years have not merely disrupted existing markets. They "
            + "have created entirely new ones, establishing value networks that their predecessors "
            + "could not have imagined, let alone competed in."
        ))));

        body.Append(new Paragraph(new Run(new Text(
            "Our research, spanning 47 companies across 12 industries over seven years, reveals "
            + "a consistent architectural pattern in how these market-creating innovations unfold. "
            + "The pattern is not about technology or timing. It is about the deliberate construction "
            + "of what we call demand infrastructure: the ecosystem of complementary capabilities, "
            + "customer behaviors, and institutional arrangements that make a new market viable."
        ))));

        // ── H1 section ──
        AddSampleParagraph(body, "The Demand Infrastructure Framework", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "Traditional frameworks for analyzing innovation focus on supply-side dynamics: "
            + "technological capability, cost structure, and competitive positioning. These "
            + "frameworks work well for sustaining innovations, where the market already exists "
            + "and the question is how to serve it better or more cheaply."
        ))));

        body.Append(new Paragraph(new Run(new Text(
            "Market-creating innovations, however, require a fundamentally different analytical "
            + "lens. The central challenge is not building a better product but constructing the "
            + "conditions under which demand for an entirely new category can emerge and sustain itself."
        ))));

        // ── Pull quote ──
        AddHBRPullQuote(body,
            "The most common strategic error is optimizing for a market that doesn't yet exist "
            + "using metrics designed for markets that already do.");

        // ── H2 section ──
        AddSampleParagraph(body, "Three Pillars of Demand Infrastructure", "Heading3");

        body.Append(new Paragraph(new Run(new Text(
            "Our analysis identifies three structural pillars that distinguish successful "
            + "market-creating innovations from those that fail despite strong technology and ample funding."
        ))));

        body.Append(new Paragraph(new Run(new Text(
            "The first pillar is behavioral scaffolding: the creation of transitional products, "
            + "services, or experiences that help potential customers develop the habits, skills, "
            + "and mental models necessary to adopt the new category. The second is institutional "
            + "alignment: the cultivation of regulatory frameworks, industry standards, and professional "
            + "norms that legitimize the new market. The third is complementary supply: the development "
            + "of adjacent products and services that make the core offering more valuable."
        ))));

        // ── Exhibit (HBR's term for tables) ──
        body.Append(CreateHBRExhibit(
            "Exhibit 1: Market-Creating Innovation Success Factors",
            new[] { "Factor", "High success", "Low success", "Impact" },
            new[]
            {
                new[] { "Behavioral scaffolding", "Present in 89%", "Present in 23%", "3.9x" },
                new[] { "Institutional alignment", "Present in 76%", "Present in 31%", "2.5x" },
                new[] { "Complementary supply", "Present in 82%", "Present in 44%", "1.9x" },
                new[] { "All three pillars", "Present in 64%", "Present in 8%", "8.0x" }
            }
        ));

        // ── Exhibit caption ──
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Caption" }
            ),
            new Run(new Text(
                "Source: Authors' analysis of 47 market-creating innovations, 2018\u20132025. "
                + "Success defined as achieving >$1B category revenue within five years of launch."
            ))
        ));

        // ── More body text ──
        AddSampleParagraph(body, "Implications for Leaders", "Heading2");

        body.Append(new Paragraph(new Run(new Text(
            "The demand infrastructure framework has profound implications for how leaders allocate "
            + "resources and evaluate innovation investments. Rather than asking \"Is this technology "
            + "superior?\" the critical question becomes \"Are we building the conditions under which "
            + "customers can adopt this?\""
        ))));

        body.Append(new Paragraph(new Run(new Text(
            "This shift in perspective explains why some of the most successful market creators "
            + "invested as much in customer education, ecosystem development, and regulatory engagement "
            + "as they did in product development. It also explains why technically superior solutions "
            + "frequently lose to inferior ones that invest more heavily in demand infrastructure."
        ))));

        // ── Another pull quote ──
        AddHBRPullQuote(body,
            "Leaders who build demand infrastructure are not merely selling products. "
            + "They are constructing the conditions under which entirely new forms of value become possible.");

        AddSampleParagraph(body, "A Path Forward", "Heading3");

        body.Append(new Paragraph(new Run(new Text(
            "For organizations seeking to create new markets rather than compete in existing ones, "
            + "we recommend a three-phase approach. First, map the behavioral, institutional, and "
            + "complementary gaps that stand between your innovation and viable demand. Second, "
            + "design a sequenced investment strategy that addresses these gaps in order of "
            + "dependency. Third, establish metrics that track demand infrastructure development, "
            + "not just product performance."
        ))));

        body.Append(new Paragraph(new Run(new Text(
            "The organizations that master this approach will not merely win in existing markets. "
            + "They will define the markets of the future."
        ))));

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// Creates an HBR-style pull quote: 16pt italic Georgia, #666666, indented.
    /// Pull quotes are a magazine editorial convention that breaks up long text
    /// and highlights key insights for scanning executives.
    /// Left and right indentation creates visual distinction from body text.
    /// </summary>
    private static void AddHBRPullQuote(Body body, string text)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines
                {
                    Before = "360",       // 18pt before
                    After = "360",        // 18pt after
                    Line = "360",         // 1.5x line spacing for pull quotes
                    LineRule = LineSpacingRuleValues.Auto
                },
                new Indentation
                {
                    Left = "720",         // 0.5in left indent
                    Right = "720"         // 0.5in right indent
                }
            ),
            new Run(
                new RunProperties(
                    new RunFonts { Ascii = "Georgia", HighAnsi = "Georgia" },
                    new FontSize { Val = "32" },              // 16pt (sz=32)
                    new FontSizeComplexScript { Val = "32" },
                    new Italic(),
                    new Color { Val = "666666" }
                ),
                new Text(text)
            )
        ));
    }

    /// <summary>
    /// Creates an HBR-style exhibit (table) with clean header-accent formatting.
    /// HBR uses "Exhibit" terminology rather than "Table" to signal business/consulting context.
    /// Design: bold exhibit label above, clean header with accent color, minimal borders.
    /// </summary>
    private static Table CreateHBRExhibit(string exhibitLabel, string[] headers, string[][] data)
    {
        var table = new Table();

        // Table properties: full width, subtle borders
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 8, Space = 0, Color = "1A1A1A" },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "CCCCCC" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "E0E0E0" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            new TableCellMarginDefault(
                new TopMargin { Width = "40", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "60", Type = TableWidthUnitValues.Dxa },
                new BottomMargin { Width = "40", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "60", Type = TableWidthUnitValues.Dxa }
            )
        );
        table.Append(tblPr);

        // Grid columns
        var grid = new TableGrid();
        int colWidth = 8640 / headers.Length;  // Letter width minus 1.25in margins each side
        foreach (var _ in headers)
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        table.Append(grid);

        // Exhibit label row spanning all columns
        var labelRow = new TableRow();
        var labelCell = new TableCell(
            new TableCellProperties(
                new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto },
                new GridSpan { Val = headers.Length },
                new TableCellBorders(
                    new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
                )
            ),
            new Paragraph(
                new ParagraphProperties(
                    new SpacingBetweenLines { After = "80" }
                ),
                new Run(
                    new RunProperties(
                        new Bold(),
                        new RunFonts { Ascii = "Georgia", HighAnsi = "Georgia" },
                        new FontSize { Val = "20" },          // 10pt
                        new FontSizeComplexScript { Val = "20" },
                        new Color { Val = "1A1A1A" }
                    ),
                    new Text(exhibitLabel)
                )
            )
        );
        labelRow.Append(labelCell);
        table.Append(labelRow);

        // Header row with accent background
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
                        Fill = "F5F5F0"           // Warm off-white header background
                    },
                    new TableCellBorders(
                        new BottomBorder { Val = BorderValues.Single, Size = 6, Space = 0, Color = "1A1A1A" }
                    )
                ),
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0" }
                    ),
                    new Run(
                        new RunProperties(
                            new Bold(),
                            new FontSize { Val = "20" },      // 10pt header text
                            new FontSizeComplexScript { Val = "20" },
                            new Color { Val = "1A1A1A" }
                        ),
                        new Text(h)
                    )
                )
            ));
        }
        table.Append(headerRow);

        // Data rows
        for (int i = 0; i < data.Length; i++)
        {
            var row = new TableRow();
            foreach (var cell in data[i])
            {
                var tcPr = new TableCellProperties(
                    new TableCellWidth { Width = "0", Type = TableWidthUnitValues.Auto }
                );

                row.Append(new TableCell(
                    tcPr,
                    new Paragraph(
                        new ParagraphProperties(
                            new SpacingBetweenLines { After = "0" }
                        ),
                        new Run(
                            new RunProperties(
                                new FontSize { Val = "20" },
                                new FontSizeComplexScript { Val = "20" },
                                new Color { Val = "333333" }
                            ),
                            new Text(cell)
                        )
                    )
                ));
            }
            table.Append(row);
        }

        return table;
    }
}
