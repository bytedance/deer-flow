// ============================================================================
// AestheticRecipeSamples_Batch3.cs — Recipes 10-11: Academic style guides
// ============================================================================
// Recipe 10: Chicago/Turabian (humanities dissertations, history papers)
// Recipe 11: Springer LNCS (computer science conference proceedings)
// ============================================================================

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using WpPageSize = DocumentFormat.OpenXml.Wordprocessing.PageSize;

namespace MiniMaxAIDocx.Core.Samples;

public static partial class AestheticRecipeSamples
{
    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 10: CHICAGO / TURABIAN
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Chicago/Turabian Academic Document
    /// Source: Turabian 9th edition (2018), Chicago Manual of Style 17th edition.
    /// Best for: Humanities dissertations, history papers, theology, philosophy.
    ///
    /// Design rationale:
    /// - Times New Roman 12pt: standard for all Turabian submissions.
    /// - Double spacing (line=480) throughout body text, as required by Turabian 9th ed. A.1.
    /// - First-line indent 0.5in (720 DXA): Turabian A.1.3 — paragraphs separated by
    ///   indentation, not extra spacing.
    /// - Left margin 1.5in (2160 DXA) for binding; all others 1in (1440 DXA):
    ///   Turabian A.1.1 specifies 1in minimum on all sides, 1.5in left for binding.
    /// - Heading hierarchy (Turabian A.2.2):
    ///   H1: Centered, Bold, Title Case (first-level subheading)
    ///   H2: Centered, Regular (not bold), Title Case — this is the distinctive
    ///       Turabian feature: an unbold centered heading.
    ///   H3: Flush Left, Bold, Title Case
    ///   H4: Flush Left, Regular (not bold), Title Case
    ///   H5: Indented, Bold, run-in with period, sentence case (run-in = inline with text)
    ///   All headings are 12pt — the same size as body text.
    /// - Page numbers: centered at bottom of page (Turabian A.1.5).
    /// - Footnotes: 10pt (sz=20), single-spaced within, double-spaced between.
    ///   Turabian uses footnotes (not endnotes) as the primary citation system.
    /// - Block quotes: indented 0.5in from left margin, single-spaced within,
    ///   used for quotations of 5+ lines (Turabian 25.2.2).
    /// </summary>
    public static void CreateChicagoTurabianDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Times New Roman 12pt, double spacing, first-line indent
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
                    new FontSize { Val = "24" },              // 12pt (half-points)
                    new FontSizeComplexScript { Val = "24" },
                    new Color { Val = "000000" },
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Double spacing: 480 = 2.0x (240 = single)
                        // Required throughout by Turabian A.1.2
                        Line = "480",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"     // No space after — indent separates paragraphs
                    },
                    // First-line indent: 0.5in = 720 DXA (Turabian A.1.3)
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

        // ── Heading 1: 12pt Bold, Centered, Title Case ──
        // Turabian first-level subheading: centered and bold
        styles.Append(CreateAcademicHeadingStyle(
            level: 1,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: true,
            spaceBefore: "480",          // One blank double-spaced line before
            spaceAfter: "0"
        ));

        // ── Heading 2: 12pt Regular (NOT bold), Centered, Title Case ──
        // Turabian second-level subheading: centered but NOT bold.
        // This is the distinctive Turabian feature — an unbold centered heading.
        // It contrasts with APA which makes all centered headings bold.
        styles.Append(CreateAcademicHeadingStyle(
            level: 2,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: false,                 // NOT bold — distinctive Turabian feature
            italic: false,
            centered: true,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── Heading 3: 12pt Bold, Flush Left, Title Case ──
        // Turabian third-level subheading: flush left and bold
        styles.Append(CreateAcademicHeadingStyle(
            level: 3,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── Heading 4: 12pt Regular (NOT bold), Flush Left, Title Case ──
        // Turabian fourth-level subheading: flush left, not bold
        styles.Append(CreateAcademicHeadingStyle(
            level: 4,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: false,                 // NOT bold
            italic: false,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── Heading 5 style: 12pt Bold, Indented, run-in with period ──
        // Turabian fifth-level: indented like a paragraph, bold, followed by a period,
        // then the text runs in on the same line. We approximate with a style
        // that has the indent but the run-in behavior is manual.
        styles.Append(CreateTurabianHeading5Style());

        // ── Block Quote style ──
        // Turabian 25.2.2: quotations of 5+ lines are block-quoted.
        // Indented 0.5in from left margin, single-spaced within.
        styles.Append(CreateTurabianBlockQuoteStyle());

        // ── Caption style ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "24",        // 12pt — same as body
            color: "000000",
            italic: false
        ));

        // ── Page setup: US Letter, 1in margins except 1.5in left for binding ──
        // Turabian A.1.1: at least 1in on all sides, left may be 1.5in for binding
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,        // 1in
                Left = 2160U,                     // 1.5in for binding
                Right = 1440U,                    // 1in
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: centered bottom (Turabian A.1.5) ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "24",        // 12pt — same as body
            color: "000000",
            format: PageNumberFormat.Plain
        );

        // ── Footnotes part setup ──
        // Turabian uses footnotes as the primary citation system.
        // Footnote text: 10pt (sz=20), single-spaced within, double-spaced between.
        var footnotesPart = mainPart.AddNewPart<FootnotesPart>();
        footnotesPart.Footnotes = new Footnotes(
            // Required separator and continuation separator footnotes
            new Footnote(
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto }
                    ),
                    new Run(new SeparatorMark())
                )
            )
            { Type = FootnoteEndnoteValues.Separator, Id = -1 },
            new Footnote(
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto }
                    ),
                    new Run(new ContinuationSeparatorMark())
                )
            )
            { Type = FootnoteEndnoteValues.ContinuationSeparator, Id = 0 },
            // Actual footnote (id=1): 10pt, single-spaced
            new Footnote(
                new Paragraph(
                    new ParagraphProperties(
                        new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto },
                        new Indentation { FirstLine = "720" }
                    ),
                    new Run(
                        new RunProperties(
                            new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
                        ),
                        new FootnoteReferenceMark()
                    ),
                    new Run(
                        new RunProperties(
                            new FontSize { Val = "20" },              // 10pt footnote text
                            new FontSizeComplexScript { Val = "20" }
                        ),
                        new Text(" Kate L. Turabian, ") { Space = SpaceProcessingModeValues.Preserve }
                    ),
                    new Run(
                        new RunProperties(
                            new FontSize { Val = "20" },
                            new FontSizeComplexScript { Val = "20" },
                            new Italic()
                        ),
                        new Text("A Manual for Writers of Research Papers, Theses, and Dissertations")
                    ),
                    new Run(
                        new RunProperties(
                            new FontSize { Val = "20" },
                            new FontSizeComplexScript { Val = "20" }
                        ),
                        new Text(", 9th ed. (Chicago: University of Chicago Press, 2018), 1.")
                    )
                )
            )
            { Id = 1 }
        );
        footnotesPart.Footnotes.Save();

        // ── Sample content ──

        // Title — centered, no indent
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("The Influence of Typographic Conventions on Scholarly Communication"))
        ));

        // Body paragraph
        AddAcademicParagraph(body, "The conventions governing the physical presentation of scholarly "
            + "writing have evolved considerably since the advent of the printing press. What began as "
            + "pragmatic considerations of legibility and economy have become codified standards that "
            + "signal disciplinary identity and methodological rigor.");

        // Body paragraph with footnote reference
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" }
            ),
            new Run(new Text("The Chicago Manual of Style, now in its seventeenth edition, remains the "
                + "authoritative guide for humanities publishing.")),
            new Run(
                new RunProperties(
                    new VerticalTextAlignment { Val = VerticalPositionValues.Superscript }
                ),
                new FootnoteReference { Id = 1 }
            ),
            new Run(new Text(" Its companion volume for students, commonly known as Turabian, "
                + "translates these standards into practical formatting requirements for academic papers "
                + "and dissertations.") { Space = SpaceProcessingModeValues.Preserve })
        ));

        // Heading 2 — centered, NOT bold (distinctive Turabian feature)
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("Historical Development of Style Guides"))
        ));

        AddAcademicParagraph(body, "The emergence of standardized formatting guidelines in the early "
            + "twentieth century reflected a growing professionalization of academic writing. "
            + "Universities increasingly required uniform presentation of theses and dissertations, "
            + "driven by the practical needs of library cataloguing and microfilm reproduction.");

        // Heading 3 — flush left, bold
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading3" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("The University of Chicago Tradition"))
        ));

        AddAcademicParagraph(body, "Kate Turabian served as the dissertation secretary at the "
            + "University of Chicago from 1930 to 1958. During this period, she developed a set of "
            + "formatting guidelines that would eventually become the standard reference for student "
            + "writers across the humanities.");

        // Heading 4 — flush left, NOT bold
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading4" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("Margin Requirements and Binding Considerations"))
        ));

        AddAcademicParagraph(body, "The requirement for a wider left margin originated in the physical "
            + "binding process. Theses submitted for library archiving were typically bound on the left "
            + "edge, necessitating additional space to ensure that text near the spine remained legible.");

        // Heading 5 — indented, bold, run-in with period
        // In Turabian, H5 runs into the paragraph text. We simulate by putting the
        // heading and body text in the same paragraph.
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading5" }
            ),
            new Run(
                new RunProperties(new Bold()),
                new Text("Modern adaptations.") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new Text(" Contemporary editions of Turabian have adapted these physical requirements "
                    + "for digital submission, though many programs still require the wider left margin "
                    + "as a nod to tradition and to accommodate printed copies.") { Space = SpaceProcessingModeValues.Preserve }
            )
        ));

        // Block quote — indented 0.5in, single-spaced
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "BlockQuote" }
            ),
            new Run(new Text("A writer who undertakes a research project joins an ongoing conversation. "
                + "To enter that conversation, you must understand what others have written, consider "
                + "their claims, and respond with your own interpretation of the evidence. The format "
                + "of your paper — its margins, spacing, notes, and bibliography — signals your "
                + "participation in that scholarly community."))
        ));

        AddAcademicParagraph(body, "This passage illustrates the centrality of formatting conventions "
            + "to the scholarly enterprise. The visual presentation of a document communicates not only "
            + "the content but also the author's membership in a disciplinary community.");

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// Creates the Turabian fifth-level heading style.
    /// Turabian H5: Indented (same as paragraph indent, 0.5in), Bold, run-in with period.
    /// The heading text is bold and followed by a period, then body text continues
    /// on the same line in regular weight. This "run-in" behavior is unique to Turabian
    /// and requires manual composition (bold run + regular run in same paragraph).
    /// </summary>
    private static Style CreateTurabianHeading5Style()
    {
        var rPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "24" },
            new FontSizeComplexScript { Val = "24" },
            new Color { Val = "000000" },
            new Bold()
        );

        var pPr = new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new SpacingBetweenLines
            {
                Before = "480",
                After = "0",
                Line = "480",
                LineRule = LineSpacingRuleValues.Auto
            },
            // Indented same as paragraph first-line indent (0.5in)
            new Indentation { FirstLine = "720" },
            new OutlineLevel { Val = 4 }   // OutlineLevel is 0-based: level 5 = 4
        );

        return new Style(
            new StyleName { Val = "heading 5" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            pPr,
            rPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading5",
            Default = false
        };
    }

    /// <summary>
    /// Creates a Turabian block quote style.
    /// Turabian 25.2.2: prose quotations of five or more lines should be set off
    /// as block quotations. Block quotes are indented 0.5in from the left margin,
    /// single-spaced within (line=240), with no first-line indent, and with a blank
    /// line (double-spaced) before and after.
    /// </summary>
    private static Style CreateTurabianBlockQuoteStyle()
    {
        return new Style(
            new StyleName { Val = "Block Quote" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 29 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines
                {
                    Before = "240",
                    After = "240",
                    Line = "240",             // Single-spaced within block quote
                    LineRule = LineSpacingRuleValues.Auto
                },
                new Indentation
                {
                    Left = "720",             // 0.5in from left margin
                    FirstLine = "0"           // No first-line indent in block quotes
                }
            ),
            new StyleRunProperties(
                new FontSize { Val = "24" },              // 12pt — same as body
                new FontSizeComplexScript { Val = "24" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "BlockQuote",
            Default = false
        };
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 11: SPRINGER LNCS
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: Springer LNCS (Lecture Notes in Computer Science)
    /// Source: llncs.cls class file, Springer LNCS author instructions (2024).
    /// Best for: Computer science conference proceedings, workshop papers, Springer volumes.
    ///
    /// Design rationale:
    /// - Times New Roman 10pt body (sz=20): LNCS uses a compact 10pt body to fit
    ///   more content per page. Conference proceedings have strict page limits
    ///   (typically 12-16 pages), so density matters.
    /// - Text area: 122mm x 193mm on US Letter. This creates generous margins
    ///   (~44mm left/right, ~47mm top, ~55mm bottom) that give the dense text
    ///   breathing room. The narrow text column improves readability at 10pt.
    ///   Margins: Top=47mm(2669 DXA), Bottom=55mm(3118 DXA), Left=44mm(2494 DXA),
    ///   Right=44mm(2494 DXA).
    /// - Title: 14pt bold centered (sz=28) — the only large element on the page.
    /// - Author: 12pt centered (sz=24) — subordinate to title but clearly visible.
    /// - H1 (Section): 12pt bold flush left, arabic numbered ("1 Introduction").
    /// - H2 (Subsection): 10pt bold flush left, numbered "1.1".
    /// - H3 (Subsubsection): 10pt bold italic run-in, numbered but discouraged.
    /// - H4 (Paragraph): 10pt italic run-in, unnumbered.
    /// - Single spacing (line=240) throughout — maximizes content density.
    /// - First-line indent: ~15pt (283 DXA, ~0.5cm) — notably smaller than the
    ///   typical 0.5in, reflecting European typographic conventions.
    /// - Paragraph spacing: 0pt — paragraphs separated only by indent.
    /// - Abstract: "Abstract." bold prefix, 9pt body (sz=18).
    /// - Captions and references: 9pt (sz=18).
    /// - Page numbers: centered at bottom of page.
    /// </summary>
    public static void CreateSpringerLNCSDocument(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: Times New Roman 10pt, single spacing, small first-line indent
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
                    new FontSize { Val = "20" },              // 10pt body (half-points)
                    new FontSizeComplexScript { Val = "20" },
                    new Color { Val = "000000" },
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Single spacing: compact layout for proceedings
                        Line = "240",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"
                    },
                    // First-line indent: ~15pt = 283 DXA (~0.5cm)
                    // Smaller than the Anglo-American 0.5in, following European convention
                    new Indentation { FirstLine = "283" }
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

        // ── LNCS Title style: 14pt bold centered ──
        styles.Append(CreateLNCSTitleStyle());

        // ── LNCS Author style: 12pt centered ──
        styles.Append(CreateLNCSAuthorStyle());

        // ── LNCS Abstract style: 9pt, for the abstract body text ──
        styles.Append(CreateLNCSAbstractStyle());

        // ── Heading 1 (Section): 12pt bold flush left ──
        // LNCS sections are numbered "1 Introduction", "2 Related Work", etc.
        // Numbering is manual in the sample content for simplicity.
        styles.Append(CreateHeadingStyle(
            level: 1,
            fontAscii: "Times New Roman",
            fontHAnsi: "Times New Roman",
            sizeHalfPts: "24",            // 12pt
            color: "000000",
            bold: true,
            spaceBefore: "240",           // 12pt before
            spaceAfter: "120",            // 6pt after
            uiPriority: 9
        ));

        // ── Heading 2 (Subsection): 10pt bold flush left ──
        // Numbered "1.1", "1.2", etc.
        styles.Append(CreateHeadingStyle(
            level: 2,
            fontAscii: "Times New Roman",
            fontHAnsi: "Times New Roman",
            sizeHalfPts: "20",            // 10pt — same as body
            color: "000000",
            bold: true,
            spaceBefore: "200",           // 10pt before
            spaceAfter: "100",            // 5pt after
            uiPriority: 9
        ));

        // ── Heading 3 (Subsubsection): 10pt bold italic, run-in ──
        // LNCS discourages subsubsections but allows them.
        // Run-in headings are composed manually (bold italic run + regular run).
        styles.Append(CreateLNCSHeading3Style());

        // ── Heading 4 (Paragraph): 10pt italic, run-in, unnumbered ──
        styles.Append(CreateLNCSHeading4Style());

        // ── Caption style: 9pt (sz=18) ──
        styles.Append(CreateCaptionStyle(
            fontSizeHalfPts: "18",        // 9pt
            color: "000000",
            italic: false
        ));

        // ── References style: 9pt (sz=18) ──
        styles.Append(CreateLNCSReferencesStyle());

        // ── Page setup: US Letter with LNCS text area 122x193mm ──
        // US Letter = 215.9mm x 279.4mm = 12240 x 15840 DXA
        // Text area = 122mm x 193mm centered on page
        // Left/Right margin: (215.9-122)/2 ≈ 47mm ≈ 2669 DXA — but LNCS specifies ~44mm
        // Top margin: ~47mm = 2669 DXA, Bottom: ~55mm = 3118 DXA
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 2669, Bottom = 3118,
                Left = 2494U, Right = 2494U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Page numbers: centered bottom ──
        AddPageNumberFooter(mainPart, sectPr,
            alignment: JustificationValues.Center,
            fontSizeHalfPts: "20",        // 10pt
            color: "000000",
            format: PageNumberFormat.Plain
        );

        // ── Sample content ──

        // Title — 14pt bold centered
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "LNCSTitle" }
            ),
            new Run(new Text("Efficient Algorithms for Document Layout Analysis"))
        ));

        // Author — 12pt centered
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "LNCSAuthor" }
            ),
            new Run(new Text("Jane Smith"))
        ));

        // Author affiliation — 9pt centered
        body.Append(new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { After = "240" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text("Department of Computer Science, Example University, City, Country")
            )
        ));

        // Abstract — "Abstract." bold prefix + 9pt body
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "LNCSAbstract" }
            ),
            new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text("Abstract.") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text(" This paper presents efficient algorithms for analyzing the layout structure "
                    + "of digitally typeset documents. We propose a novel approach based on hierarchical "
                    + "decomposition that achieves O(n log n) complexity while maintaining high accuracy "
                    + "on standard benchmarks. Experimental results on the ICDAR dataset demonstrate "
                    + "a 12% improvement over existing methods.") { Space = SpaceProcessingModeValues.Preserve }
            )
        ));

        // Section 1 — numbered manually
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("1   Introduction"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" },
                new Indentation { FirstLine = "0" }           // First para after heading: no indent
            ),
            new Run(new Text("Document layout analysis is a fundamental task in document image processing. "
                + "Given a document page, the goal is to identify and classify regions such as text blocks, "
                + "figures, tables, and captions. Accurate layout analysis is a prerequisite for downstream "
                + "tasks including optical character recognition and information extraction."))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" }
            ),
            new Run(new Text("Previous approaches to this problem can be broadly categorized into "
                + "rule-based methods, which rely on hand-crafted heuristics, and learning-based methods, "
                + "which train classifiers on annotated datasets. While learning-based methods have shown "
                + "superior accuracy, their computational cost often limits practical deployment."))
        ));

        // Section 2
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("2   Related Work"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("The literature on document layout analysis spans several decades. "
                + "Early systems employed top-down recursive decomposition, while more recent work "
                + "has explored bottom-up aggregation of connected components."))
        ));

        // Subsection 2.1
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading2" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("2.1   Top-Down Approaches"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("Top-down methods recursively partition the document page into smaller "
                + "regions. The X-Y cut algorithm is the canonical example, splitting the page "
                + "alternately along horizontal and vertical whitespace gaps."))
        ));

        // Section 3
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("3   Proposed Method"))
        ));

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("We propose a hierarchical decomposition algorithm that combines the "
                + "efficiency of top-down splitting with the accuracy of bottom-up region growing."))
        ));

        // Table — three-line style, common in CS papers
        body.Append(CreateThreeLineTable(
            new[] { "Method", "Precision", "Recall", "F1", "Time (ms)" },
            new[]
            {
                new[] { "X-Y Cut", "0.82", "0.79", "0.80", "12" },
                new[] { "RLSA", "0.85", "0.83", "0.84", "45" },
                new[] { "Ours", "0.94", "0.91", "0.92", "18" }
            }
        ));

        // Caption — 9pt
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Caption" },
                new Justification { Val = JustificationValues.Center },
                new Indentation { FirstLine = "0" }
            ),
            new Run(
                new RunProperties(new Bold()),
                new Text("Table 1.") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(new Text(" Comparison of layout analysis methods on the ICDAR 2019 dataset.") { Space = SpaceProcessingModeValues.Preserve })
        ));

        // References section
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Heading1" },
                new Indentation { FirstLine = "0" }
            ),
            new Run(new Text("References"))
        ));

        // Reference entries — 9pt, numbered [1], [2], etc.
        AddLNCSReference(body, "1", "Smith, J., Doe, A.: Document layout analysis using recursive decomposition. "
            + "In: Proceedings of ICDAR, pp. 112\u2013120 (2019)");
        AddLNCSReference(body, "2", "Johnson, R.: A survey of page segmentation algorithms. "
            + "Pattern Recognition 45(3), 234\u2013251 (2018)");
        AddLNCSReference(body, "3", "Williams, K., Brown, L.: Hierarchical methods for structured document "
            + "understanding. Int. J. Document Analysis 12(1), 45\u201367 (2020)");

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// LNCS Title style: 14pt bold centered, with spacing after for author line.
    /// The title is the largest element in an LNCS paper — everything else is compact.
    /// </summary>
    private static Style CreateLNCSTitleStyle()
    {
        return new Style(
            new StyleName { Val = "LNCS Title" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = "0", After = "240" },
                new Indentation { FirstLine = "0" }
            ),
            new StyleRunProperties(
                new Bold(),
                new FontSize { Val = "28" },              // 14pt
                new FontSizeComplexScript { Val = "28" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "LNCSTitle",
            Default = false
        };
    }

    /// <summary>
    /// LNCS Author style: 12pt centered, no bold.
    /// Authors are listed below the title, followed by affiliations in smaller text.
    /// </summary>
    private static Style CreateLNCSAuthorStyle()
    {
        return new Style(
            new StyleName { Val = "LNCS Author" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = "0", After = "60" },
                new Indentation { FirstLine = "0" }
            ),
            new StyleRunProperties(
                new FontSize { Val = "24" },              // 12pt
                new FontSizeComplexScript { Val = "24" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "LNCSAuthor",
            Default = false
        };
    }

    /// <summary>
    /// LNCS Abstract style: 9pt body, slightly indented from both margins.
    /// The abstract in LNCS papers is preceded by "Abstract." in bold.
    /// </summary>
    private static Style CreateLNCSAbstractStyle()
    {
        return new Style(
            new StyleName { Val = "LNCS Abstract" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { Before = "120", After = "240" },
                new Indentation { Left = "283", Right = "283", FirstLine = "0" }
            ),
            new StyleRunProperties(
                new FontSize { Val = "18" },              // 9pt
                new FontSizeComplexScript { Val = "18" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "LNCSAbstract",
            Default = false
        };
    }

    /// <summary>
    /// LNCS Heading 3 (Subsubsection): 10pt bold italic.
    /// Run-in style — the heading is followed by body text on the same line.
    /// Numbering (e.g., "1.1.1") is manual. LNCS discourages deep nesting.
    /// </summary>
    private static Style CreateLNCSHeading3Style()
    {
        return new Style(
            new StyleName { Val = "heading 3" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "200", After = "100" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 2 }
            ),
            new StyleRunProperties(
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
                new Bold(),
                new Italic()
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading3",
            Default = false
        };
    }

    /// <summary>
    /// LNCS Heading 4 (Paragraph level): 10pt italic, run-in, unnumbered.
    /// The lowest heading level in LNCS — used for paragraph-level subdivisions.
    /// </summary>
    private static Style CreateLNCSHeading4Style()
    {
        return new Style(
            new StyleName { Val = "heading 4" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 9 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines { Before = "200", After = "100" },
                new Indentation { FirstLine = "0" },
                new OutlineLevel { Val = 3 }
            ),
            new StyleRunProperties(
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
                new Italic()                              // Italic only, no bold
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Heading4",
            Default = false
        };
    }

    /// <summary>
    /// LNCS References style: 9pt (sz=18), with hanging indent for numbered entries.
    /// References in LNCS use numbered format [1], [2], etc.
    /// </summary>
    private static Style CreateLNCSReferencesStyle()
    {
        return new Style(
            new StyleName { Val = "LNCS Reference" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 30 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { After = "40" },
                new Indentation
                {
                    Left = "360",             // Hanging indent body
                    Hanging = "360"           // Hanging amount (overrides first-line indent)
                }
            ),
            new StyleRunProperties(
                new FontSize { Val = "18" },              // 9pt
                new FontSizeComplexScript { Val = "18" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "LNCSReference",
            Default = false
        };
    }

    /// <summary>
    /// Helper to add an LNCS-formatted reference entry with [N] numbering.
    /// </summary>
    private static void AddLNCSReference(Body body, string number, string text)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "LNCSReference" }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text($"[{number}] ") { Space = SpaceProcessingModeValues.Preserve }
            ),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new FontSizeComplexScript { Val = "18" }
                ),
                new Text(text)
            )
        ));
    }
}
