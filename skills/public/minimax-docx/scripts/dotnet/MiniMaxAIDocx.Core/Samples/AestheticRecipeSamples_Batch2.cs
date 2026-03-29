// ============================================================================
// AestheticRecipeSamples_Batch2.cs — Academic citation style recipes (APA 7, MLA 9)
// ============================================================================
// Recipes 8-9: Strict compliance with academic citation style guides.
// These are NOT aesthetic "design" choices — they are codified standards
// mandated by publishers, universities, and professional organizations.
//
// UNIT REFERENCE:
//   Font size: half-points (22 = 11pt, 24 = 12pt, 32 = 16pt)
//   Spacing:   DXA = twentieths of a point (1440 DXA = 1 inch)
//   Borders:   eighth-points (4 = 0.5pt, 8 = 1pt, 12 = 1.5pt)
//   Line spacing "line": 240ths of single spacing (240 = 1.0x, 480 = 2.0x)
// ============================================================================

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using WpPageSize = DocumentFormat.OpenXml.Wordprocessing.PageSize;

namespace MiniMaxAIDocx.Core.Samples;

public static partial class AestheticRecipeSamples
{
    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 8: APA 7TH EDITION (PROFESSIONAL PAPER)
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: APA 7th Edition — Professional Paper
    /// Source: Publication Manual of the American Psychological Association,
    ///         7th edition (2020), Chapters 2 (Paper Elements) and 6 (Mechanics of Style).
    ///
    /// Key APA 7 specifications:
    /// - Font: 12pt Times New Roman (Section 2.19). Also acceptable: 11pt Calibri,
    ///   11pt Arial, 10pt Lucida Sans Unicode, or 11pt Georgia.
    /// - Margins: 1 inch on all sides (Section 2.22).
    /// - Line spacing: Double-spaced throughout, including title page and references (Section 2.21).
    /// - Paragraph indent: 0.5 inch first-line indent for body paragraphs (Section 2.24).
    /// - Heading levels (Section 2.27):
    ///   Level 1: Centered, Bold, Title Case Heading
    ///   Level 2: Flush Left, Bold, Title Case Heading
    ///   Level 3: Flush Left, Bold Italic, Title Case Heading
    ///   Level 4:     Indented, Bold, Title Case Heading, Ending With a Period. (run-in)
    ///   Level 5:     Indented, Bold Italic, Title Case Heading, Ending With a Period. (run-in)
    ///   All headings are 12pt — hierarchy through format, NOT size.
    /// - Page numbers: top right corner on every page including title page (Section 2.18).
    /// - Running head: flush left, ALL CAPS, for professional papers only (Section 2.18).
    /// - Abstract: "Abstract" centered bold; single paragraph, not indented (Section 2.9).
    /// - No numbered headings (APA does not use section numbers).
    ///
    /// Design rationale:
    /// - Every parameter is dictated by the style guide, not aesthetic preference.
    /// - Double spacing with first-line indent (no paragraph spacing) is the
    ///   traditional academic convention — it provides annotation room and
    ///   clear paragraph boundaries without wasting vertical space.
    /// - Uniform 12pt headings ensure the text content is primary; headings
    ///   serve as navigational aids, not visual statements.
    /// </summary>
    public static void CreateAPA7Document(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: 12pt Times New Roman, double spacing, 0.5in first-line indent
        // NOTE: 11pt Calibri and 11pt Arial are also acceptable per APA 7 Section 2.19
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
                    new Color { Val = "000000" },             // Pure black
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Double spacing throughout (APA 7, Section 2.21)
                        // 480 = 2.0x (240 = single spacing)
                        Line = "480",
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"     // No paragraph spacing — APA uses indent, not space
                    },
                    // First-line indent 0.5in = 720 DXA (APA 7, Section 2.24)
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

        // ── APA Level 1: Centered, Bold, Title Case ──
        // Same 12pt as body — hierarchy via format, NOT size (APA 7, Section 2.27)
        styles.Append(CreateAcademicHeadingStyle(
            level: 1,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: true,
            spaceBefore: "480",          // One double-spaced blank line before
            spaceAfter: "0"
        ));

        // ── APA Level 2: Flush Left, Bold, Title Case ──
        styles.Append(CreateAcademicHeadingStyle(
            level: 2,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: false,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── APA Level 3: Flush Left, Bold Italic, Title Case ──
        styles.Append(CreateAcademicHeadingStyle(
            level: 3,
            sizeHalfPts: "24",           // 12pt — same as body
            bold: true,
            italic: true,
            centered: false,
            spaceBefore: "480",
            spaceAfter: "0"
        ));

        // ── APA Level 4: Indented 0.5in, Bold, Title Case, Ending With Period. ──
        // This is a "run-in" heading in APA — the heading text runs into the paragraph.
        // In OpenXML we approximate by creating an indented bold paragraph.
        styles.Append(CreateAPA7RunInHeadingStyle(
            level: 4,
            bold: true,
            italic: false
        ));

        // ── APA Level 5: Indented 0.5in, Bold Italic, Title Case, Ending With Period. ──
        styles.Append(CreateAPA7RunInHeadingStyle(
            level: 5,
            bold: true,
            italic: true
        ));

        // ── "Abstract" label style: centered, bold, no indent ──
        styles.Append(CreateAPA7NoIndentCenteredStyle(
            styleId: "APAAbstractLabel",
            styleName: "APA Abstract Label",
            bold: true
        ));

        // ── Abstract body style: no first-line indent ──
        styles.Append(CreateAPA7NoIndentStyle(
            styleId: "APAAbstractBody",
            styleName: "APA Abstract Body"
        ));

        // ── Title page style: centered, bold, no indent ──
        styles.Append(CreateAPA7NoIndentCenteredStyle(
            styleId: "APATitlePageTitle",
            styleName: "APA Title Page Title",
            bold: true
        ));

        // ── Title page author/affiliation: centered, no indent, not bold ──
        styles.Append(CreateAPA7NoIndentCenteredStyle(
            styleId: "APATitlePageInfo",
            styleName: "APA Title Page Info",
            bold: false
        ));

        // ── Page setup: US Letter, 1in all sides (APA 7, Section 2.22) ──
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },  // 8.5" x 11"
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Running head + page number in header ──
        // Professional papers: running head flush left (ALL CAPS), page number flush right
        // Both in the same header (APA 7, Section 2.18)
        AddAPA7Header(mainPart, sectPr, "COGNITIVE EFFECTS OF SLEEP DEPRIVATION");

        // ══════════════════════════════════════════════════════════════════
        // SAMPLE CONTENT: Title Page, Abstract, Body with all 5 heading levels
        // ══════════════════════════════════════════════════════════════════

        // ── Title page ──
        // Title: centered, bold, upper half of page (3-4 blank lines before)
        AddAPA7TitlePage(body,
            title: "Cognitive Effects of Sleep Deprivation on Working Memory Performance",
            authorName: "Sarah J. Mitchell",
            affiliation: "Department of Psychology, University of Washington",
            courseLine: "PSY 401: Advanced Cognitive Psychology",
            instructorLine: "Dr. Robert Chen",
            dateLine: "October 15, 2024"
        );

        // ── Abstract page ──
        AddSampleParagraph(body, "Abstract", "APAAbstractLabel");

        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "APAAbstractBody" }
            ),
            new Run(new Text(
                "This study examined the effects of acute sleep deprivation on working memory "
                + "performance in college-aged adults. Participants (N = 48) were randomly assigned "
                + "to either a sleep deprivation condition (24 hours without sleep) or a control "
                + "condition (normal sleep). Working memory was assessed using a dual n-back task. "
                + "Results indicated that sleep-deprived participants showed significantly lower "
                + "accuracy (M = 72.3%, SD = 8.1) compared to controls (M = 89.7%, SD = 5.4), "
                + "t(46) = 9.12, p < .001, d = 2.52. These findings suggest that even a single "
                + "night of sleep deprivation substantially impairs working memory capacity."
            ))
        ));

        // ── Body: Level 1 heading ──
        AddSampleParagraph(body, "Cognitive Effects of Sleep Deprivation on Working Memory Performance", "Heading1");

        AddSampleParagraph(body,
            "Sleep deprivation is increasingly prevalent among college students, with approximately "
            + "50% reporting insufficient sleep on a regular basis (Hershner & Chervin, 2014). The "
            + "consequences of inadequate sleep extend beyond daytime drowsiness, affecting core "
            + "cognitive processes including attention, executive function, and working memory.",
            "Normal");

        // ── Level 2 heading ──
        AddSampleParagraph(body, "Theoretical Framework", "Heading2");

        AddSampleParagraph(body,
            "Working memory, as conceptualized by Baddeley and Hitch (1974), comprises a central "
            + "executive system supported by the phonological loop and visuospatial sketchpad. Sleep "
            + "deprivation has been hypothesized to primarily affect the central executive component, "
            + "which governs attentional control and task coordination.",
            "Normal");

        // ── Level 3 heading ──
        AddSampleParagraph(body, "Neural Mechanisms of Sleep-Related Cognitive Decline", "Heading3");

        AddSampleParagraph(body,
            "Neuroimaging studies have demonstrated that sleep deprivation is associated with "
            + "reduced activation in the prefrontal cortex, the neural substrate most closely linked "
            + "to working memory function (Chee & Chuah, 2007). Additionally, thalamic deactivation "
            + "may impair the relay of sensory information necessary for memory encoding.",
            "Normal");

        // ── Level 4 heading (run-in, bold, ends with period) ──
        // APA Level 4 is a run-in heading: the heading text and paragraph text
        // share the same line. We approximate with a bold indented paragraph.
        body.Append(CreateAPA7RunInParagraph(
            headingText: "Prefrontal Cortex Involvement.",
            bodyText: " The dorsolateral prefrontal cortex (DLPFC) shows the greatest "
            + "susceptibility to sleep loss. Functional MRI studies reveal a dose-dependent "
            + "relationship between hours of wakefulness and DLPFC activation levels during "
            + "working memory tasks.",
            bold: true,
            italic: false
        ));

        // ── Level 5 heading (run-in, bold italic, ends with period) ──
        body.Append(CreateAPA7RunInParagraph(
            headingText: "Glutamatergic Pathways.",
            bodyText: " Recent research has identified glutamatergic signaling in the "
            + "prefrontal cortex as a key mediator of sleep deprivation effects on working "
            + "memory. Antagonism of NMDA receptors produces cognitive deficits similar to "
            + "those observed following 24 hours of sleep loss.",
            bold: true,
            italic: true
        ));

        // ── Level 2: Method section ──
        AddSampleParagraph(body, "Method", "Heading2");

        AddSampleParagraph(body,
            "This experiment used a between-subjects design with sleep condition (deprived vs. "
            + "control) as the independent variable and working memory accuracy as the dependent "
            + "variable. All procedures were approved by the University of Washington Institutional "
            + "Review Board (Protocol #2024-0847).",
            "Normal");

        // ── Level 2: Results ──
        AddSampleParagraph(body, "Results", "Heading2");

        AddSampleParagraph(body,
            "An independent-samples t test revealed a statistically significant difference in "
            + "working memory accuracy between the sleep-deprived group (M = 72.3%, SD = 8.1) "
            + "and the control group (M = 89.7%, SD = 5.4), t(46) = 9.12, p < .001. The effect "
            + "size was large (Cohen's d = 2.52), indicating a substantial practical difference.",
            "Normal");

        // ── Level 2: Discussion ──
        AddSampleParagraph(body, "Discussion", "Heading2");

        AddSampleParagraph(body,
            "The findings of this study are consistent with previous research demonstrating the "
            + "deleterious effects of sleep deprivation on cognitive performance. The magnitude of "
            + "the effect observed here exceeds that reported in meta-analytic reviews, possibly "
            + "due to the use of a more demanding dual n-back paradigm that places greater demands "
            + "on executive control processes.",
            "Normal");

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// Creates an APA 7 "run-in" heading style (Levels 4 and 5).
    /// These headings are indented 0.5in and end with a period;
    /// the paragraph text runs in on the same line as the heading.
    /// In OpenXML, we create a paragraph style with the appropriate formatting.
    /// </summary>
    private static Style CreateAPA7RunInHeadingStyle(int level, bool bold, bool italic)
    {
        var rPr = new StyleRunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                EastAsia = "SimSun",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "24" },              // 12pt — same as body
            new FontSizeComplexScript { Val = "24" },
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
                Before = "480",
                After = "0",
                Line = "480",
                LineRule = LineSpacingRuleValues.Auto
            },
            // Indented 0.5in = 720 DXA (APA 7 Levels 4-5)
            new Indentation { FirstLine = "720" },
            new OutlineLevel { Val = level - 1 }
        );

        return new Style(
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
    }

    /// <summary>
    /// Creates a centered, optionally bold paragraph style with no first-line indent.
    /// Used for APA title page elements and the "Abstract" label.
    /// </summary>
    private static Style CreateAPA7NoIndentCenteredStyle(string styleId, string styleName, bool bold)
    {
        var rPr = new StyleRunProperties(
            new FontSize { Val = "24" },
            new FontSizeComplexScript { Val = "24" }
        );

        if (bold)
            rPr.Append(new Bold());

        return new Style(
            new StyleName { Val = styleName },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            ),
            rPr
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = styleId,
            Default = false
        };
    }

    /// <summary>
    /// Creates a left-aligned paragraph style with no first-line indent.
    /// Used for the abstract body text (APA 7 specifies no indent for abstract).
    /// </summary>
    private static Style CreateAPA7NoIndentStyle(string styleId, string styleName)
    {
        return new Style(
            new StyleName { Val = styleName },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = styleId,
            Default = false
        };
    }

    /// <summary>
    /// Adds the APA 7 professional paper header: running head flush left (ALL CAPS)
    /// and page number flush right, both in the same header line.
    /// Per APA 7, Section 2.18: the running head appears on every page.
    /// </summary>
    private static void AddAPA7Header(MainDocumentPart mainPart, SectionProperties sectPr, string runningHeadText)
    {
        // Use a tab stop at the right margin to position the page number flush right
        // Right margin position: page width (12240) - left margin (1440) - right margin (1440) = 9360 DXA
        var headerParagraph = new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "Normal" },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { Line = "240", LineRule = LineSpacingRuleValues.Auto, After = "0" },
                new Tabs(
                    new TabStop
                    {
                        Val = TabStopValues.Right,
                        Position = 9360   // Flush right at the text area edge
                    }
                )
            ),
            // Running head text (flush left, ALL CAPS)
            new Run(
                new RunProperties(
                    new RunFonts
                    {
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman"
                    },
                    new FontSize { Val = "24" },
                    new FontSizeComplexScript { Val = "24" }
                ),
                new Text(runningHeadText) { Space = SpaceProcessingModeValues.Preserve }
            ),
            // Tab to move to right-aligned position
            new Run(
                new RunProperties(
                    new RunFonts
                    {
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman"
                    },
                    new FontSize { Val = "24" },
                    new FontSizeComplexScript { Val = "24" }
                ),
                new TabChar()
            ),
            // Page number (flush right)
            new SimpleField(
                new Run(
                    new RunProperties(
                        new RunFonts
                        {
                            Ascii = "Times New Roman",
                            HighAnsi = "Times New Roman"
                        },
                        new FontSize { Val = "24" },
                        new FontSizeComplexScript { Val = "24" }
                    ),
                    new Text("1")
                )
            )
            { Instruction = " PAGE " }
        );

        var headerPart = mainPart.AddNewPart<HeaderPart>();
        headerPart.Header = new Header(headerParagraph);
        headerPart.Header.Save();

        string headerPartId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerPartId
        });
    }

    /// <summary>
    /// Adds the APA 7 title page content: title, author, affiliation,
    /// course, instructor, and date — all centered and double-spaced.
    /// Per APA 7, Section 2.3: title should be bold, centered, in upper half of page.
    /// </summary>
    private static void AddAPA7TitlePage(Body body,
        string title, string authorName, string affiliation,
        string courseLine, string instructorLine, string dateLine)
    {
        // Add some blank lines to position title in upper half of page
        for (int i = 0; i < 3; i++)
        {
            body.Append(new Paragraph(
                new ParagraphProperties(
                    new ParagraphStyleId { Val = "APATitlePageInfo" }
                )
            ));
        }

        // Title: centered, bold
        AddSampleParagraph(body, title, "APATitlePageTitle");

        // Author name
        AddSampleParagraph(body, authorName, "APATitlePageInfo");

        // Affiliation
        AddSampleParagraph(body, affiliation, "APATitlePageInfo");

        // Course
        AddSampleParagraph(body, courseLine, "APATitlePageInfo");

        // Instructor
        AddSampleParagraph(body, instructorLine, "APATitlePageInfo");

        // Date
        AddSampleParagraph(body, dateLine, "APATitlePageInfo");

        // Page break after title page
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "APATitlePageInfo" }
            ),
            new Run(new Break { Type = BreakValues.Page })
        ));
    }

    /// <summary>
    /// Creates an APA Level 4 or 5 "run-in" paragraph where the heading text
    /// (bold or bold italic) is followed by the body text on the same line.
    /// The heading ends with a period per APA 7 convention.
    /// </summary>
    private static Paragraph CreateAPA7RunInParagraph(
        string headingText, string bodyText, bool bold, bool italic)
    {
        var headingRunProps = new RunProperties(
            new RunFonts
            {
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                ComplexScript = "Times New Roman"
            },
            new FontSize { Val = "24" },
            new FontSizeComplexScript { Val = "24" }
        );

        if (bold)
            headingRunProps.Append(new Bold());
        if (italic)
            headingRunProps.Append(new Italic());

        return new Paragraph(
            new ParagraphProperties(
                new Indentation { FirstLine = "720" },   // 0.5in indent
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            ),
            // Heading run (bold / bold italic)
            new Run(
                headingRunProps,
                new Text(headingText) { Space = SpaceProcessingModeValues.Preserve }
            ),
            // Body text run (regular)
            new Run(
                new RunProperties(
                    new RunFonts
                    {
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman",
                        ComplexScript = "Times New Roman"
                    },
                    new FontSize { Val = "24" },
                    new FontSizeComplexScript { Val = "24" }
                ),
                new Text(bodyText) { Space = SpaceProcessingModeValues.Preserve }
            )
        );
    }


    // ════════════════════════════════════════════════════════════════════════
    // RECIPE 9: MLA 9TH EDITION
    // ════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Recipe: MLA 9th Edition
    /// Source: MLA Handbook, 9th edition (2021), Part 1 (Principles of Scholarship)
    ///         and Part 2 (Details of MLA Style).
    ///
    /// Key MLA 9 specifications:
    /// - Font: 12pt Times New Roman (or other readable font; Times New Roman is standard).
    /// - Margins: 1 inch on all sides.
    /// - Line spacing: Double-spaced throughout, including block quotes and Works Cited.
    /// - Paragraph indent: 0.5 inch first-line indent for body paragraphs.
    /// - Title: Centered, same size as body text (12pt), NOT bold, italic, or underlined.
    ///   MLA eschews visual hierarchy — the title is distinguished only by centering.
    /// - No mandatory heading system. If headings are used, they should be simple and
    ///   consistent. MLA does not prescribe heading levels like APA does.
    /// - Running header: Author's last name and page number, flush right, 0.5 inch from top.
    /// - First-page header block: Student's name, instructor's name, course title, and
    ///   date — upper left, double-spaced, NO extra spacing.
    /// - Works Cited: title "Works Cited" centered (not bold), entries have hanging indent
    ///   of 0.5 inch (first line flush left, subsequent lines indented).
    /// - No title page required (unless specifically requested by instructor).
    ///
    /// Design rationale:
    /// - MLA's aesthetic is deliberately plain — the writing is the content.
    /// - No bold headings, no size variation, no decorative elements.
    /// - The only structural markers are centering (title, Works Cited label)
    ///   and indentation (paragraphs, hanging indent for citations).
    /// - This uniformity reflects MLA's roots in literary studies, where the
    ///   text itself is paramount and formatting should be invisible.
    /// </summary>
    public static void CreateMLA9Document(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);

        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        // ── Styles ──
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        var styles = stylesPart.Styles;

        // DocDefaults: 12pt Times New Roman, double spacing, 0.5in first-line indent
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
                    new FontSize { Val = "24" },              // 12pt
                    new FontSizeComplexScript { Val = "24" },
                    new Color { Val = "000000" },
                    new Languages { Val = "en-US", EastAsia = "zh-CN" }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        Line = "480",                         // Double spacing throughout
                        LineRule = LineSpacingRuleValues.Auto,
                        After = "0"
                    },
                    new Indentation { FirstLine = "720" }     // 0.5in first-line indent
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

        // ── MLA Title style: centered, NOT bold/italic/underlined ──
        // MLA is distinctive: the title has NO special formatting beyond centering.
        styles.Append(CreateMLA9TitleStyle());

        // ── MLA Header Block style: flush left, no indent ──
        styles.Append(CreateMLA9HeaderBlockStyle());

        // ── MLA Works Cited label style: centered, not bold ──
        styles.Append(CreateMLA9WorksCitedLabelStyle());

        // ── MLA Works Cited entry style: hanging indent 0.5in ──
        styles.Append(CreateMLA9WorksCitedEntryStyle());

        // ── Page setup: US Letter, 1in all sides ──
        var sectPr = new SectionProperties(
            new WpPageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            }
        );

        // ── Running header: "LastName  PageNumber" flush right ──
        AddMLA9Header(mainPart, sectPr, "Mitchell");

        // ══════════════════════════════════════════════════════════════════
        // SAMPLE CONTENT: MLA header block, title, body, Works Cited
        // ══════════════════════════════════════════════════════════════════

        // ── First-page header block (upper left, double-spaced) ──
        AddSampleParagraph(body, "Sarah Mitchell", "MLAHeaderBlock");
        AddSampleParagraph(body, "Professor Johnson", "MLAHeaderBlock");
        AddSampleParagraph(body, "English 201: American Literature", "MLAHeaderBlock");
        AddSampleParagraph(body, "15 October 2024", "MLAHeaderBlock");

        // ── Title: centered, 12pt, plain (not bold) ──
        AddSampleParagraph(body, "The Function of the Unreliable Narrator in Nabokov's Lolita", "MLATitle");

        // ── Body paragraphs ──
        AddSampleParagraph(body,
            "Vladimir Nabokov's Lolita (1955) remains one of the most studied examples of "
            + "unreliable narration in twentieth-century fiction. Humbert Humbert's elaborate, "
            + "self-justifying prose has been analyzed through numerous critical lenses, yet the "
            + "question of how the novel's narrative structure shapes reader complicity continues "
            + "to generate scholarly debate.",
            "Normal");

        AddSampleParagraph(body,
            "The concept of the unreliable narrator, first articulated by Wayne C. Booth in "
            + "The Rhetoric of Fiction (1961), provides a foundational framework for understanding "
            + "Humbert's discourse. Booth argues that unreliable narrators are those whose values "
            + "diverge from those of the implied author (158-59). In Lolita, this divergence is "
            + "particularly complex because Nabokov layers multiple forms of unreliability: "
            + "factual, evaluative, and interpretive.",
            "Normal");

        AddSampleParagraph(body,
            "Michael Wood has observed that \"Nabokov's genius lies in making us forget, "
            + "momentarily, that Humbert is a monster\" (127). This temporary forgetting is not "
            + "a failure of reading but a designed effect of the narrative voice. The luxurious "
            + "prose, the literary allusions, the self-deprecating wit \u2014 all serve to create what "
            + "Nomi Tamir-Ghez calls \"rhetorical seduction\" (42), in which readers find "
            + "themselves sympathizing with a narrator whose actions they would condemn.",
            "Normal");

        AddSampleParagraph(body,
            "The structural implications of Humbert's unreliability extend beyond mere "
            + "factual distortion. As Eric Naiman demonstrates, the novel's famous opening "
            + "paragraph \u2014 with its incantatory repetition of \"Lolita\" \u2014 establishes a "
            + "pattern of linguistic possession that mirrors Humbert's physical possession of "
            + "Dolores Haze (85). The language itself becomes an instrument of control, one "
            + "that operates on the reader as well as on the characters within the narrative.",
            "Normal");

        // ── Works Cited ──
        // Page break before Works Cited
        body.Append(new Paragraph(
            new ParagraphProperties(
                new ParagraphStyleId { Val = "MLAHeaderBlock" }
            ),
            new Run(new Break { Type = BreakValues.Page })
        ));

        AddSampleParagraph(body, "Works Cited", "MLAWorksCitedLabel");

        // Works Cited entries with hanging indent
        AddSampleParagraph(body,
            "Booth, Wayne C. The Rhetoric of Fiction. 2nd ed., U of Chicago P, 1983.",
            "MLAWorksCitedEntry");

        AddSampleParagraph(body,
            "Nabokov, Vladimir. Lolita. 1955. Vintage International, 1989.",
            "MLAWorksCitedEntry");

        AddSampleParagraph(body,
            "Naiman, Eric. Nabokov, Perversely. Cornell UP, 2010.",
            "MLAWorksCitedEntry");

        AddSampleParagraph(body,
            "Tamir-Ghez, Nomi. \"The Art of Persuasion in Nabokov's Lolita.\" Poetics Today, "
            + "vol. 1, no. 1-2, 1979, pp. 65-83.",
            "MLAWorksCitedEntry");

        AddSampleParagraph(body,
            "Wood, Michael. The Magician's Doubts: Nabokov and the Risks of Fiction. "
            + "Princeton UP, 1995.",
            "MLAWorksCitedEntry");

        // Section properties must be last child of body
        body.Append(sectPr);
    }

    /// <summary>
    /// MLA title style: centered, 12pt, NO bold/italic/underline.
    /// MLA's radical plainness — the title is distinguished only by position.
    /// </summary>
    private static Style CreateMLA9TitleStyle()
    {
        return new Style(
            new StyleName { Val = "MLA Title" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "MLATitle",
            Default = false
        };
    }

    /// <summary>
    /// MLA first-page header block style: flush left, no first-line indent, double-spaced.
    /// Used for the student name, instructor, course, and date lines.
    /// </summary>
    private static Style CreateMLA9HeaderBlockStyle()
    {
        return new Style(
            new StyleName { Val = "MLA Header Block" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Left },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "MLAHeaderBlock",
            Default = false
        };
    }

    /// <summary>
    /// MLA Works Cited label style: centered, 12pt, NOT bold.
    /// Like the title, the label is plain — only centering distinguishes it.
    /// </summary>
    private static Style CreateMLA9WorksCitedLabelStyle()
    {
        return new Style(
            new StyleName { Val = "MLA Works Cited Label" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Center },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "MLAWorksCitedLabel",
            Default = false
        };
    }

    /// <summary>
    /// MLA Works Cited entry style: hanging indent of 0.5 inch (720 DXA).
    /// First line is flush left; subsequent lines indent 0.5 inch.
    /// This is the standard format for bibliography entries in MLA style.
    /// </summary>
    private static Style CreateMLA9WorksCitedEntryStyle()
    {
        return new Style(
            new StyleName { Val = "MLA Works Cited Entry" },
            new BasedOn { Val = "Normal" },
            new UIPriority { Val = 1 },
            new StyleParagraphProperties(
                new Justification { Val = JustificationValues.Left },
                // Hanging indent: Left = 720, FirstLine is negative (Hanging = 720)
                new Indentation { Left = "720", Hanging = "720" },
                new SpacingBetweenLines
                {
                    Line = "480",
                    LineRule = LineSpacingRuleValues.Auto,
                    After = "0"
                }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "MLAWorksCitedEntry",
            Default = false
        };
    }

    /// <summary>
    /// Adds the MLA 9 running header: author last name and page number, flush right,
    /// 0.5 inch from top of page. Per MLA convention, this appears on every page.
    /// </summary>
    private static void AddMLA9Header(MainDocumentPart mainPart, SectionProperties sectPr, string authorLastName)
    {
        var headerParagraph = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Right },
                new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { Line = "240", LineRule = LineSpacingRuleValues.Auto, After = "0" }
            ),
            // Author last name
            new Run(
                new RunProperties(
                    new RunFonts
                    {
                        Ascii = "Times New Roman",
                        HighAnsi = "Times New Roman"
                    },
                    new FontSize { Val = "24" },
                    new FontSizeComplexScript { Val = "24" }
                ),
                new Text(authorLastName + " ") { Space = SpaceProcessingModeValues.Preserve }
            ),
            // Page number
            new SimpleField(
                new Run(
                    new RunProperties(
                        new RunFonts
                        {
                            Ascii = "Times New Roman",
                            HighAnsi = "Times New Roman"
                        },
                        new FontSize { Val = "24" },
                        new FontSizeComplexScript { Val = "24" }
                    ),
                    new Text("1")
                )
            )
            { Instruction = " PAGE " }
        );

        var headerPart = mainPart.AddNewPart<HeaderPart>();
        headerPart.Header = new Header(headerParagraph);
        headerPart.Header.Save();

        string headerPartId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerPartId
        });
    }
}
