// ============================================================================
// AestheticRecipeSamples_Batch1.cs — IEEE & ACM conference paper recipes
// ============================================================================
// Two-column academic conference styles faithfully reproducing the typographic
// conventions of IEEEtran.cls and acmart.cls for DOCX output.
//
// UNIT REFERENCE:
//   Font size: half-points (20 = 10pt, 18 = 9pt, 16 = 8pt)
//   Spacing:   DXA = twentieths of a point (1440 DXA = 1 inch)
//   Borders:   eighth-points (4 = 0.5pt, 8 = 1pt, 12 = 1.5pt)
//   Line spacing "line": 240ths of single spacing (240 = 1.0x)
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
    // RECIPE 6: IEEE CONFERENCE (IEEEtran)
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: IEEE Conference Paper (IEEEtran.cls v1.8b)
    /// Source: IEEEtran.cls v1.8b — the standard LaTeX class for IEEE transactions
    /// and conference proceedings.
    ///
    /// Feel: Dense, formal, information-rich two-column layout.
    /// Best for: IEEE conference submissions, transactions papers, technical reports
    /// following IEEE style.
    ///
    /// Design rationale (all values from IEEEtran.cls source):
    /// - US Letter, narrow margins (0.625in L/R): maximizes text area for the
    ///   two-column layout. IEEE papers prioritize information density.
    /// - Two columns with 0.25in (360 DXA) gutter: standard IEEE column separation.
    ///   Narrow gutter is feasible because the small font creates short line lengths.
    /// - 10pt Times New Roman body (sz=20): IEEE's standard body size. TNR is the
    ///   required typeface. 10pt in two columns yields ~40 characters per line —
    ///   optimal for rapid technical reading.
    /// - 24pt title, centered, NOT bold (sz=48): IEEEtran titles are large but
    ///   use regular weight. The size alone provides hierarchy.
    /// - Section headings (H1): 10pt small caps, centered, Roman numeral prefix
    ///   convention (sz=20). Small caps at body size creates subtle hierarchy
    ///   without disrupting the dense layout.
    /// - Subsection headings (H2): 10pt italic, flush left (sz=20). Italic at
    ///   body size is the minimal viable distinction from body text.
    /// - Single spacing (line=240): mandatory for IEEE camera-ready format.
    /// - First-line indent 0.125in (180 DXA): very small indent suits the narrow
    ///   column width.
    /// - 0pt paragraph spacing: IEEE uses no inter-paragraph space; the first-line
    ///   indent is the sole paragraph separator.
    /// - Captions: 8pt (sz=16) — subordinate to body, centered under figures/tables.
    /// </summary>
    public static void CreateIEEEConferenceDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Times New Roman 10pt, single spacing, 0.125in first-line indent
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
                    new FontSize { Val = "20" },              // 10pt body (IEEEtran standard)
                    new FontSizeComplexScript { Val = "20" },
                    new Color { Val = "000000" },             // Pure black
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Single spacing: mandatory for IEEE camera-ready
                        Line = "240",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0",
                        Before = "0"
                    },
                    // First-line indent: 0.125in = 180 DXA (very small, suits narrow columns)
                    new Indentation { FirstLine = "180" }
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

        // ── Title style: 24pt centered, NOT bold ──
        // IEEEtran.cls \maketitle: \LARGE (24pt at 10pt base), centered, no bold
        var titleRPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "48" },              // 24pt
            new FontSizeComplexScript { Val = "48" },
            new Color { Val = "000000" }
            // No Bold — IEEEtran titles are NOT bold
        );

        styles.Append(new Style(
            new StyleName { Val = "Title" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = "0", After = "240" },
                new Indentation { FirstLine = "0" }           // No indent for title
            ),
            titleRPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Title",
            Default = false
        });

        // ── Heading 1: 10pt small caps, centered ──
        // IEEEtran \section: \centering\scshape at body size, Roman numeral prefix
        var h1RPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "20" },              // 10pt — same as body
            new FontSizeComplexScript { Val = "20" },
            new Color { Val = "000000" },
            new SmallCaps()                           // Small caps for section headings
        );

        styles.Append(new Style(
            new StyleName { Val = "heading 1" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = "240", After = "120" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 0 }
            ),
            h1RPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading1",
            Default = false
        });

        // ── Heading 2: 10pt italic, flush left ──
        // IEEEtran \subsection: \itshape at body size, flush left
        var h2RPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "20" },              // 10pt — same as body
            new FontSizeComplexScript { Val = "20" },
            new Color { Val = "000000" },
            new Italic()                              // Italic for subsection headings
        );

        styles.Append(new Style(
            new StyleName { Val = "heading 2" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "180", After = "60" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 1 }
            ),
            h2RPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading2",
            Default = false
        });

        // ── Abstract style: 9pt bold "Abstract" label convention ──
        styles.Append(CreateParagraphStyle(
            styleId: "Abstract",
            styleName: "Abstract",
            basedOn: "Normal",
            uiPriority: 11
        ));

        // ── Caption style: 8pt (sz=16) ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "16",        // 8pt — IEEE standard caption size
            color: "000000",
            italic: false                 // IEEE captions are not italic
        ));

        // ── Page setup: US Letter, IEEE margins, two-column ──
        // IEEEtran.cls: top=0.75in, bottom=1in, left=right=0.625in
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },  // US Letter
            new PageMargin
            {
                Top = 1080,               // 0.75in
                Bottom = 1440,            // 1in
                Left = 900U,              // 0.625in
                Right = 900U,             // 0.625in
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            // Two-column layout: 0.25in gutter = 360 DXA
            new WpColumns { ColumnCount = 2, Space = "360" }
        );

        // ── Page numbers: bottom center, 8pt ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "16",        // 8pt
            color: "000000",
            format: PageNumberFormat.Plain
        );

        // ── Sample content: IEEE paper structure ──

        // Title (spans both columns via the Title style)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Title" }
            ),
            new Run(new Text("Deep Learning Approaches for Automated Document Layout Analysis"))
        ));

        // Author line (centered, no indent)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { After = "120" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(new FontSize { Val = "20" }, new FontSizeComplexScript { Val = "20" }),
                new Text("Jane A. Smith, John B. Doe, and Alice C. Johnson")
            )
        ));

        // Affiliation (centered, italic, smaller)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { After = "240" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" }, new FontSizeComplexScript { Val = "18" },
                    new Italic()
                ),
                new Text("Department of Computer Science, Example University, City, Country")
            )
        ));

        // Abstract
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Abstract" },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { After = "120" }
            ),
            new Run(
                new RunProperties(new Bold(), new Italic(), new FontSize { Val = "18" }, new FontSizeComplexScript { Val = "18" }),
                new Text("Abstract") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(new FontSize { Val = "18" }, new FontSizeComplexScript { Val = "18" }),
                new Text("\u2014This paper presents a comprehensive framework for automated document "
                    + "layout analysis using deep learning. We propose a novel architecture that "
                    + "combines convolutional neural networks with transformer-based attention "
                    + "mechanisms to accurately segment and classify document regions. Experimental "
                    + "results on benchmark datasets demonstrate state-of-the-art performance.")
                { Space = SpaceProcessingModeValues.Preserve }
            )
        ));

        // I. INTRODUCTION (Roman numeral convention rendered in text)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("I. Introduction"))
        ));

        AddSampleParagraph(body, "Document layout analysis is a fundamental step in document "
            + "understanding pipelines. The ability to automatically identify and classify "
            + "regions within a document image has applications in digitization, information "
            + "extraction, and accessibility.", "Normal");

        AddSampleParagraph(body, "Recent advances in deep learning have significantly improved "
            + "the accuracy of layout analysis systems. However, challenges remain in handling "
            + "complex multi-column layouts and heterogeneous document types.", "Normal");

        // II. RELATED WORK
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("II. Related Work"))
        ));

        // A. Subsection
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" }
            ),
            new Run(new Text("A. Traditional Methods"))
        ));

        AddSampleParagraph(body, "Early approaches to document layout analysis relied on "
            + "rule-based methods and connected component analysis. These methods perform well "
            + "on structured documents but struggle with complex layouts.", "Normal");

        // B. Subsection
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" }
            ),
            new Run(new Text("B. Deep Learning Methods"))
        ));

        AddSampleParagraph(body, "Convolutional neural networks have been successfully applied "
            + "to document layout analysis, achieving significant improvements over traditional "
            + "methods on standard benchmarks.", "Normal");

        // III. PROPOSED METHOD
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("III. Proposed Method"))
        ));

        AddSampleParagraph(body, "Our proposed framework integrates a feature pyramid network "
            + "backbone with a transformer decoder module. The architecture processes document "
            + "images at multiple scales to capture both fine-grained character-level features "
            + "and coarse layout structures.", "Normal");

        // Table
        body.Append(CreateThreeLineTable(
            new[] { "Method", "Precision", "Recall", "F1" },
            new[]
            {
                new[] { "Rule-based", "0.823", "0.791", "0.807" },
                new[] { "CNN-only", "0.912", "0.887", "0.899" },
                new[] { "Ours", "0.956", "0.943", "0.949" }
            }
        ));

        AddSampleParagraph(body, "TABLE I: Comparison of layout analysis methods on PubLayNet.", "Caption");

        // IV. CONCLUSION
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("IV. Conclusion"))
        ));

        AddSampleParagraph(body, "We have presented a novel deep learning framework for document "
            + "layout analysis that achieves state-of-the-art results. Future work will explore "
            + "extending the approach to handle more diverse document types.", "Normal");

        // Section properties must be last child of body
        body.Append(sectPr);
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 7: ACM CONFERENCE (acmart)
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: ACM Conference Paper (acmart.cls v2.x, ACM Author Guide)
    /// Source: acmart.cls v2.x — the consolidated ACM master article template,
    /// and the ACM Author Guide for typographic specifications.
    ///
    /// Feel: Clean, structured, slightly more open than IEEE.
    /// Best for: ACM conference proceedings (SIGCHI, SIGMOD, SIGGRAPH, etc.),
    /// ACM journal submissions.
    ///
    /// Design rationale (all values from acmart.cls and ACM Author Guide):
    /// - US Letter, 1.25in top/bottom, 0.75in L/R: more generous vertical margins
    ///   than IEEE, giving a less cramped appearance.
    /// - Two columns with 0.33in (480 DXA) gutter: slightly wider than IEEE's
    ///   0.25in, providing better visual separation between columns.
    /// - 9pt Times New Roman body (sz=18): ACM's standard body size. The original
    ///   acmart uses Linux Libertine, but TNR is the accessible fallback specified
    ///   in the ACM Author Guide for systems without Libertine.
    /// - 14.4pt bold title, flush left (sz=29): ACM titles are bold and left-aligned,
    ///   unlike IEEE's centered unbolded titles. The 14.4pt size (1.6x body) creates
    ///   strong but not overwhelming hierarchy.
    /// - H1: 10pt bold ALL CAPS, flush left, arabic numbered (sz=20). ALL CAPS at
    ///   body size with bold creates definitive section breaks.
    /// - H2: 10pt bold title case, flush left (sz=20). Bold without caps is the
    ///   minimal step down from H1.
    /// - H3: 10pt bold italic, flush left (sz=20). Adding italic distinguishes
    ///   from H2 while maintaining the same weight.
    /// - Single spacing: required for ACM camera-ready format.
    /// - First-line indent ~10pt (200 DXA): slightly larger than IEEE's 0.125in,
    ///   matching ACM's convention of a roughly 1em indent at 9pt.
    /// - Captions: 8pt (sz=16) — consistent with ACM figure/table caption style.
    /// - References: 7.5pt (sz=15) — ACM uses a smaller font for the bibliography
    ///   to maximize space for content.
    /// </summary>
    public static void CreateACMConferenceDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Times New Roman 9pt (TNR as Libertine fallback), single spacing
        styles.Append(new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    new RunFonts
                    {
                        // ACM specifies Linux Libertine; TNR is the accessible fallback
                        // per ACM Author Guide for systems without Libertine installed
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman",
                        EastAsia = "SimSun",
                        ComplexScript = "Times New Roman"
                    },
                    new FontSize { Val = "18" },              // 9pt body (acmart standard)
                    new FontSizeComplexScript { Val = "18" },
                    new Color { Val = "000000" },             // Pure black
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Single spacing: ACM camera-ready requirement
                        Line = "240",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0",
                        Before = "0"
                    },
                    // First-line indent: ~10pt = 200 DXA (roughly 1em at 9pt)
                    new Indentation { FirstLine = "200" }
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

        // ── Title style: 14.4pt bold, flush left ──
        // acmart \maketitle: \LARGE\bfseries, left-aligned
        var titleRPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "29" },              // 14.4pt (≈29 half-points)
            new FontSizeComplexScript { Val = "29" },
            new Color { Val = "000000" },
            new Bold()                                // ACM titles ARE bold
        );

        styles.Append(new Style(
            new StyleName { Val = "Title" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                // Flush left — ACM titles are NOT centered
                new SpacingBetweenLines { Before = "0", After = "200" },
                new Indentation { FirstLine = "0" }
            ),
            titleRPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Title",
            Default = false
        });

        // ── Heading 1: 10pt bold ALL CAPS, flush left ──
        // acmart \section: \bfseries at body size, uppercase
        var h1RPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "20" },              // 10pt
            new FontSizeComplexScript { Val = "20" },
            new Color { Val = "000000" },
            new Bold(),
            new Caps()                                // ALL CAPS for H1
        );

        styles.Append(new Style(
            new StyleName { Val = "heading 1" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "240", After = "120" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 0 }
            ),
            h1RPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading1",
            Default = false
        });

        // ── Heading 2: 10pt bold title case, flush left ──
        // acmart \subsection: \bfseries, no case change
        var h2RPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "20" },              // 10pt
            new FontSizeComplexScript { Val = "20" },
            new Color { Val = "000000" },
            new Bold()                                // Bold, no caps
        );

        styles.Append(new Style(
            new StyleName { Val = "heading 2" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "200", After = "80" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 1 }
            ),
            h2RPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading2",
            Default = false
        });

        // ── Heading 3: 10pt bold italic, flush left ──
        // acmart \subsubsection: \bfseries\itshape
        var h3RPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "20" },              // 10pt
            new FontSizeComplexScript { Val = "20" },
            new Color { Val = "000000" },
            new Bold(),
            new Italic()                              // Bold italic for H3
        );

        styles.Append(new Style(
            new StyleName { Val = "heading 3" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "160", After = "60" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 2 }
            ),
            h3RPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading3",
            Default = false
        });

        // ── Caption style: 8pt (sz=16) ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "16",        // 8pt — ACM standard caption size
            color: "000000",
            italic: false
        ));

        // ── References style: 7.5pt (sz=15) ──
        var refsRPr = new StyleRunProperties(
            new FontSize { Val = "15" },              // 7.5pt
            new FontSizeComplexScript { Val = "15" }
        );

        styles.Append(new Style(
            new StyleName { Val = "References" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 37 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { After = "40" },
                new Indentation { FirstLine = "0", Left = "360", Hanging = "360" }
            ),
            refsRPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "References",
            Default = false
        });

        // ── Page setup: US Letter, ACM margins, two-column ──
        // acmart.cls: top=1.25in, bottom=1.25in, left=right=0.75in
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },  // US Letter
            new PageMargin
            {
                Top = 1800,               // 1.25in
                Bottom = 1800,            // 1.25in
                Left = 1080U,             // 0.75in
                Right = 1080U,            // 0.75in
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            // Two-column layout: 0.33in gutter = 480 DXA
            new WpColumns { ColumnCount = 2, Space = "480" }
        );

        // ── Page numbers: bottom center, 8pt ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "16",        // 8pt
            color: "000000",
            format: PageNumberFormat.Plain
        );

        // ── Sample content: ACM paper structure ──

        // Title (flush left, bold)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Title" }
            ),
            new Run(new Text("Towards Scalable Graph Neural Networks for Heterogeneous Document Understanding"))
        ));

        // Author block (flush left)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "60" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(new FontSize { Val = "18" }, new FontSizeComplexScript { Val = "18" }),
                new Text("Maria R. Garcia")
            )
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "60" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" },
                    new Italic()
                ),
                new Text("Example University, City, Country")
            )
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new SpacingBetweenLines { After = "200" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" }
                ),
                new Text("garcia@example.edu")
            )
        ));

        // Abstract section
        body.Append(new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { After = "80" }
            ),
            new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "18" }, new FontSizeComplexScript { Val = "18" }
                ),
                new Text("ABSTRACT")
            )
        ));

        AddSampleParagraph(body, "Graph neural networks (GNNs) have emerged as a powerful tool for "
            + "document understanding tasks that require modeling relationships between document "
            + "elements. We present a scalable GNN architecture that processes heterogeneous "
            + "document graphs containing text, table, and figure nodes. Our approach achieves "
            + "competitive results while reducing computational costs by 40%.", "Normal");

        // CCS Concepts / Keywords (ACM-specific metadata)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { Before = "120", After = "120" }
            ),
            new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" }
                ),
                new Text("Keywords: ") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "16" }, new FontSizeComplexScript { Val = "16" }
                ),
                new Text("graph neural networks, document understanding, scalability")
            )
        ));

        // 1 INTRODUCTION (arabic numbered, ALL CAPS via style)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("1 Introduction"))
        ));

        AddSampleParagraph(body, "Document understanding encompasses a broad set of tasks including "
            + "layout analysis, information extraction, and document classification. Recent work "
            + "has demonstrated that modeling the structural relationships between document "
            + "elements can significantly improve performance on these tasks.", "Normal");

        AddSampleParagraph(body, "Graph neural networks provide a natural framework for representing "
            + "and reasoning about document structure. However, existing GNN-based approaches face "
            + "scalability challenges when processing large or complex documents.", "Normal");

        // 2 RELATED WORK
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("2 Related Work"))
        ));

        // 2.1 Subsection
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" }
            ),
            new Run(new Text("2.1 Document Representation Learning"))
        ));

        AddSampleParagraph(body, "Pre-trained language models have been adapted for document "
            + "understanding by incorporating layout information. LayoutLM and its successors "
            + "demonstrate the value of multi-modal pre-training for document tasks.", "Normal");

        // 2.1.1 Sub-subsection
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading3" }
            ),
            new Run(new Text("2.1.1 Multi-Modal Approaches"))
        ));

        AddSampleParagraph(body, "Multi-modal approaches jointly model text, layout, and visual "
            + "features. This integration has proven critical for tasks where visual appearance "
            + "carries semantic meaning, such as form understanding.", "Normal");

        // 3 METHOD
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("3 Proposed Method"))
        ));

        AddSampleParagraph(body, "We propose HetDocGNN, a heterogeneous graph neural network "
            + "designed specifically for document understanding. The architecture operates on "
            + "a document graph where nodes represent text blocks, tables, and figures, and "
            + "edges encode spatial and logical relationships.", "Normal");

        // Results table
        body.Append(CreateThreeLineTable(
            new[] { "Model", "DocVQA", "InfoVQA", "Params" },
            new[]
            {
                new[] { "LayoutLMv3", "83.4", "45.1", "133M" },
                new[] { "UDOP", "84.7", "47.4", "770M" },
                new[] { "HetDocGNN", "85.2", "48.9", "89M" }
            }
        ));

        AddSampleParagraph(body, "Table 1: Comparison on document understanding benchmarks.", "Caption");

        // 4 CONCLUSION
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("4 Conclusion"))
        ));

        AddSampleParagraph(body, "We have presented HetDocGNN, a scalable graph neural network "
            + "for heterogeneous document understanding. Our approach achieves state-of-the-art "
            + "results with significantly fewer parameters than competing methods.", "Normal");

        // REFERENCES section
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" }
            ),
            new Run(new Text("References"))
        ));

        // Sample references in ACM style (7.5pt)
        AddSampleParagraph(body, "[1] Yiheng Xu, et al. 2020. LayoutLM: Pre-training of Text and "
            + "Layout for Document Image Understanding. In KDD '20. ACM, 1192\u20131200.", "References");

        AddSampleParagraph(body, "[2] Zhiliang Peng, et al. 2023. UDOP: Unifying Vision, Text, "
            + "and Layout for Universal Document Processing. In CVPR '23. 19254\u201319264.", "References");

        AddSampleParagraph(body, "[3] Zilong Wang, et al. 2022. DocFormer: End-to-End Transformer "
            + "for Document Understanding. In ICCV '22. 993\u20131003.", "References");

        // Section properties must be last child of body
        body.Append(sectPr);
    }
}
