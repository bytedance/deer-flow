using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Reference implementations for field codes and Table of Contents (TOC).
///
/// KEY CONCEPTS:
/// - SimpleField: single-element shorthand, e.g. &lt;w:fldSimple w:instr="PAGE"/&gt;
/// - Complex field: three FieldChar elements (Begin / Separate / End) with FieldCode between them.
///   Word always writes complex fields; SimpleField is only used for trivial cases.
/// - TOC is a structured document tag (SdtBlock) wrapping a complex field.
/// - UpdateFieldsOnOpen tells Word to recalculate all fields when opening.
/// </summary>
public static class FieldAndTocSamples
{
    // ──────────────────────────────────────────────
    // 1. InsertToc — TOC levels 1-3 inside SdtBlock
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a Table of Contents covering heading levels 1-3.
    /// Uses an SdtBlock wrapper with a complex field code:
    ///   TOC \o "1-3" \h \z \u
    ///
    /// Switches:
    ///   \o "1-3" — outline levels 1-3
    ///   \h       — hyperlinks
    ///   \z       — hide tab leaders / page numbers in Web Layout
    ///   \u       — use applied paragraph outline level
    /// </summary>
    public static SdtBlock InsertToc(Body body)
    {
        var sdtBlock = new SdtBlock();

        // SdtProperties — mark as TOC
        var sdtPr = new SdtProperties();
        sdtPr.Append(new SdtContentDocPartObject(
            new DocPartGallery { Val = "Table of Contents" },
            new DocPartUnique()));
        sdtBlock.Append(sdtPr);

        // SdtContent — contains the field code paragraph(s)
        var sdtContent = new SdtContentBlock();

        // TOC title paragraph
        var titlePara = new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "TOCHeading" }),
            new Run(new Text("Table of Contents")));
        sdtContent.Append(titlePara);

        // Complex field paragraph for TOC
        var fieldPara = new Paragraph();
        InsertComplexFieldInline(fieldPara, " TOC \\o \"1-3\" \\h \\z \\u ");
        sdtContent.Append(fieldPara);

        sdtBlock.Append(sdtContent);
        body.Append(sdtBlock);
        return sdtBlock;
    }

    // ──────────────────────────────────────────────
    // 2. InsertTocWithCustomLevels — TOC 1-4 levels
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a TOC covering heading levels 1-4.
    /// Identical structure to <see cref="InsertToc"/> but with "\o 1-4".
    /// </summary>
    public static SdtBlock InsertTocWithCustomLevels(Body body)
    {
        var sdtBlock = new SdtBlock();

        var sdtPr = new SdtProperties();
        sdtPr.Append(new SdtContentDocPartObject(
            new DocPartGallery { Val = "Table of Contents" },
            new DocPartUnique()));
        sdtBlock.Append(sdtPr);

        var sdtContent = new SdtContentBlock();

        var titlePara = new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "TOCHeading" }),
            new Run(new Text("Table of Contents")));
        sdtContent.Append(titlePara);

        // 1-4 levels instead of 1-3
        var fieldPara = new Paragraph();
        InsertComplexFieldInline(fieldPara, " TOC \\o \"1-4\" \\h \\z \\u ");
        sdtContent.Append(fieldPara);

        sdtBlock.Append(sdtContent);
        body.Append(sdtBlock);
        return sdtBlock;
    }

    // ──────────────────────────────────────────────
    // 3. InsertSimpleField — PAGE, NUMPAGES, DATE, etc.
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a SimpleField element into a paragraph.
    ///
    /// SimpleField is the compact form: &lt;w:fldSimple w:instr=" PAGE "&gt;&lt;w:r&gt;...&lt;/w:r&gt;&lt;/w:fldSimple&gt;
    ///
    /// Common instructions: "PAGE", "NUMPAGES", "DATE", "TIME", "FILENAME".
    /// The run inside is the cached display value; Word recalculates on open.
    /// </summary>
    public static SimpleField InsertSimpleField(Paragraph para, string instruction)
    {
        var simpleField = new SimpleField { Instruction = $" {instruction} " };

        // Cached display value — Word replaces this on recalculation
        simpleField.Append(new Run(
            new RunProperties(new NoProof()),
            new Text("«" + instruction + "»")));

        para.Append(simpleField);
        return simpleField;
    }

    // ──────────────────────────────────────────────
    // 4. InsertComplexField — Begin/Separate/End
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a complex field into a paragraph using the FieldChar Begin/Separate/End pattern.
    ///
    /// Structure:
    ///   Run1: FieldChar(Begin) + FieldCode(" PAGE ")
    ///   Run2: FieldChar(Separate)
    ///   Run3: Text("1")              ← cached display value
    ///   Run4: FieldChar(End)
    ///
    /// Use complex fields when you need dirty flags, lock, or nested fields.
    /// </summary>
    public static void InsertComplexField(Paragraph para, string instruction)
    {
        InsertComplexFieldInline(para, $" {instruction} ");
    }

    // ──────────────────────────────────────────────
    // 5. InsertDateField — DATE with format switch
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a DATE field with a format switch: DATE \@ "yyyy-MM-dd"
    ///
    /// The \@ switch specifies the date/time picture.
    /// Common formats:
    ///   \@ "yyyy-MM-dd"         → 2026-03-22
    ///   \@ "MMMM d, yyyy"      → March 22, 2026
    ///   \@ "M/d/yyyy h:mm am/pm" → 3/22/2026 2:30 PM
    /// </summary>
    public static void InsertDateField(Paragraph para, string format)
    {
        // Field instruction with date-time picture switch
        string instruction = $" DATE \\@ \"{format}\" ";
        InsertComplexFieldInline(para, instruction);
    }

    // ──────────────────────────────────────────────
    // 6. InsertCrossReference — REF field
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a REF cross-reference field that refers to a bookmark.
    ///
    /// Instruction: REF bookmarkName \h
    ///   \h — creates a hyperlink to the bookmark
    ///   \p — inserts "above" or "below" relative position
    ///   \n — inserts paragraph number of the bookmark
    /// </summary>
    public static void InsertCrossReference(Paragraph para, string bookmarkName)
    {
        string instruction = $" REF {bookmarkName} \\h ";
        InsertComplexFieldInline(para, instruction);
    }

    // ──────────────────────────────────────────────
    // 7. InsertSequenceField — SEQ for numbering
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a SEQ (sequence) field for auto-numbering figures, tables, etc.
    ///
    /// Usage pattern for "Figure 1":
    ///   1. Append a run with text "Figure " to the paragraph
    ///   2. Call InsertSequenceField(para, "Figure")
    ///
    /// Usage pattern for "Table 1":
    ///   1. Append a run with text "Table " to the paragraph
    ///   2. Call InsertSequenceField(para, "Table")
    ///
    /// Each unique seqName maintains its own counter across the document.
    /// </summary>
    public static void InsertSequenceField(Paragraph para, string seqName)
    {
        string instruction = $" SEQ {seqName} \\* ARABIC ";
        InsertComplexFieldInline(para, instruction);
    }

    // ──────────────────────────────────────────────
    // 8. InsertMergeField — MERGEFIELD for mail merge
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a MERGEFIELD for mail merge scenarios.
    ///
    /// Instruction: MERGEFIELD fieldName \* MERGEFORMAT
    ///   \* MERGEFORMAT — preserves formatting applied to the field result
    ///   \b "text"     — text before if field is non-empty
    ///   \f "text"     — text after if field is non-empty
    ///
    /// The cached display shows «fieldName» as a placeholder.
    /// </summary>
    public static void InsertMergeField(Paragraph para, string fieldName)
    {
        string instruction = $" MERGEFIELD {fieldName} \\* MERGEFORMAT ";

        // Begin
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Begin }));

        // Field code
        para.Append(new Run(
            new FieldCode(instruction) { Space = SpaceProcessingModeValues.Preserve }));

        // Separate
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Separate }));

        // Cached value — shows merge field placeholder
        para.Append(new Run(
            new RunProperties(new NoProof()),
            new Text($"\u00AB{fieldName}\u00BB") { Space = SpaceProcessingModeValues.Preserve }));

        // End
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.End }));
    }

    // ──────────────────────────────────────────────
    // 9. InsertConditionalField — IF field
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts an IF conditional field.
    ///
    /// Syntax: IF expression1 operator expression2 "true-text" "false-text"
    /// Example: IF { MERGEFIELD Gender } = "Male" "Mr." "Ms."
    ///
    /// This example checks if MERGEFIELD Amount > 1000 and displays different text.
    /// Nested fields (MERGEFIELD inside IF) require nested Begin/End pairs.
    /// </summary>
    public static void InsertConditionalField(Paragraph para)
    {
        // Outer IF field Begin
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Begin }));

        para.Append(new Run(
            new FieldCode(" IF ") { Space = SpaceProcessingModeValues.Preserve }));

        // Nested MERGEFIELD inside the IF condition
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Begin }));
        para.Append(new Run(
            new FieldCode(" MERGEFIELD Amount ") { Space = SpaceProcessingModeValues.Preserve }));
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Separate }));
        para.Append(new Run(
            new Text("0") { Space = SpaceProcessingModeValues.Preserve }));
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.End }));

        // Continuation of IF instruction
        para.Append(new Run(
            new FieldCode(" > \"1000\" \"High Value\" \"Standard\" ") { Space = SpaceProcessingModeValues.Preserve }));

        // Separate — cached result
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Separate }));
        para.Append(new Run(
            new RunProperties(new NoProof()),
            new Text("Standard") { Space = SpaceProcessingModeValues.Preserve }));

        // End
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.End }));
    }

    // ──────────────────────────────────────────────
    // 10. InsertStyleRef — STYLEREF for running headers
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts a STYLEREF field, commonly used in headers/footers
    /// to display the current chapter or section title.
    ///
    /// Instruction: STYLEREF "Heading 1"
    ///   Displays the text of the nearest paragraph with style "Heading 1".
    ///   \l — search from bottom of page up (for last instance on page)
    ///   \n — insert the paragraph number, not text
    /// </summary>
    public static void InsertStyleRef(Paragraph para)
    {
        string instruction = " STYLEREF \"Heading 1\" ";
        InsertComplexFieldInline(para, instruction);
    }

    // ──────────────────────────────────────────────
    // 11. EnableUpdateFieldsOnOpen
    // ──────────────────────────────────────────────

    /// <summary>
    /// Sets the UpdateFieldsOnOpen property so Word recalculates
    /// all fields (PAGE, TOC, SEQ, etc.) when the document is opened.
    ///
    /// Without this, TOC and cross-references show stale cached values
    /// until the user manually presses Ctrl+A, F9 to update.
    /// </summary>
    public static void EnableUpdateFieldsOnOpen(DocumentSettingsPart settingsPart)
    {
        settingsPart.Settings ??= new Settings();
        var existing = settingsPart.Settings.GetFirstChild<UpdateFieldsOnOpen>();
        if (existing != null)
        {
            existing.Val = true;
        }
        else
        {
            settingsPart.Settings.Append(new UpdateFieldsOnOpen { Val = true });
        }
        settingsPart.Settings.Save();
    }

    // ──────────────────────────────────────────────
    // 12. CreateTocStyles — TOC1/2/3 with tab leaders
    // ──────────────────────────────────────────────

    /// <summary>
    /// Creates TOC1, TOC2, TOC3 paragraph styles with right-aligned tab stops
    /// and dot leaders (the "....." between entry text and page number).
    ///
    /// Each TOC level is indented further:
    ///   TOC1 — 0 indent
    ///   TOC2 — 240 twips (1/6 inch)
    ///   TOC3 — 480 twips (1/3 inch)
    ///
    /// Tab leader: dot-filled right tab at 9360 twips (6.5 inches for letter paper).
    /// </summary>
    public static void CreateTocStyles(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        string[] tocStyleIds = ["TOC1", "TOC2", "TOC3"];
        string[] tocStyleNames = ["toc 1", "toc 2", "toc 3"];
        int[] indents = [0, 240, 480]; // twips

        // Right tab position: 6.5 inches = 9360 twips (standard for US Letter)
        const int tabPosition = 9360;

        for (int i = 0; i < tocStyleIds.Length; i++)
        {
            var style = new Style
            {
                Type = StyleValues.Paragraph,
                StyleId = tocStyleIds[i],
                CustomStyle = false
            };

            style.Append(new StyleName { Val = tocStyleNames[i] });
            style.Append(new BasedOn { Val = "Normal" });
            style.Append(new NextParagraphStyle { Val = "Normal" });
            style.Append(new UIPriority { Val = 39 });

            var pPr = new StyleParagraphProperties();

            // Indentation for nested levels
            if (indents[i] > 0)
            {
                pPr.Append(new Indentation { Left = indents[i].ToString() });
            }

            // Spacing: no space after for compact TOC
            pPr.Append(new SpacingBetweenLines { After = "0", Line = "276", LineRule = LineSpacingRuleValues.Auto });

            // Right-aligned tab with dot leader
            var tabs = new Tabs();
            tabs.Append(new TabStop
            {
                Val = TabStopValues.Right,
                Leader = TabStopLeaderCharValues.Dot,
                Position = tabPosition
            });
            pPr.Append(tabs);

            style.Append(pPr);
            stylesPart.Styles.Append(style);
        }

        stylesPart.Styles.Save();
    }

    // ──────────────────────────────────────────────
    // 13. CreateMixedTocStructure — Real-world TOC
    // ──────────────────────────────────────────────

    /// <summary>
    /// Real-world TOC structure: Mixed SDT block + static entries + field code.
    ///
    /// IMPORTANT: Most templates do NOT have a clean TOC field code alone.
    /// Instead, they contain:
    /// 1. An SDT (Structured Document Tag) wrapper with alias "TOC"
    /// 2. Inside the SDT: a field code BEGIN + SEPARATE + static example entries + END
    /// 3. The static entries are placeholder text (e.g., "第1章 绪论...........1")
    ///    that Word replaces when user presses "Update Fields"
    ///
    /// When applying a template (Scenario C), you should:
    /// - KEEP the entire SDT block from the template (don't rebuild it)
    /// - DO NOT replace static entries with programmatic content
    /// - The entries will auto-update when the user opens in Word and updates fields
    /// - If you must update entries programmatically, replace the content INSIDE
    ///   the SDT between fldChar separate and fldChar end
    ///
    /// Common mistake: Treating TOC as pure field code and rebuilding it from scratch,
    /// which destroys the SDT wrapper and breaks Word's "Update Table" functionality.
    /// </summary>
    public static void CreateMixedTocStructure(string outputPath)
    {
        using var doc = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);
        var mainPart = doc.AddMainDocumentPart();
        mainPart.Document = new Document();
        var body = new Body();
        mainPart.Document.Append(body);

        // Add styles part with TOC styles
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        CreateTocStyles(stylesPart);

        // ─── SDT Block wrapping the entire TOC ───
        var sdtBlock = new SdtBlock();

        // SDT Properties: alias "TOC", tag, and DocPartGallery
        var sdtPr = new SdtProperties();
        sdtPr.Append(new SdtAlias { Val = "TOC" });
        sdtPr.Append(new Tag { Val = "TOC" });
        sdtPr.Append(new SdtContentDocPartObject(
            new DocPartGallery { Val = "Table of Contents" },
            new DocPartUnique()));
        sdtBlock.Append(sdtPr);

        // SDT Content: field code + static entries
        var sdtContent = new SdtContentBlock();

        // ─── TOC title paragraph ───
        var titlePara = new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "TOCHeading" }),
            new Run(new Text("目  录")));
        sdtContent.Append(titlePara);

        // ─── Field code BEGIN paragraph ───
        var fieldBeginPara = new Paragraph();

        // fldChar Begin
        fieldBeginPara.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Begin }));

        // instrText: TOC \o "1-3" \h \z \u
        fieldBeginPara.Append(new Run(
            new FieldCode(" TOC \\o \"1-3\" \\h \\z \\u ") { Space = SpaceProcessingModeValues.Preserve }));

        // fldChar Separate
        fieldBeginPara.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Separate }));

        sdtContent.Append(fieldBeginPara);

        // ─── Static placeholder entries (TOC1/TOC2/TOC3) ───
        // These are the example entries that Word will replace when user clicks "Update Table".
        // In real templates, these show example chapter titles with dot leaders and page numbers.

        // TOC level 1 entry: "第1章 绪论...........1"
        sdtContent.Append(CreateStaticTocEntry("TOC1", "第1章 绪论", "1"));

        // TOC level 2 entry: "1.1 研究背景...........1"
        sdtContent.Append(CreateStaticTocEntry("TOC2", "1.1 研究背景", "1"));

        // TOC level 2 entry: "1.2 研究目的...........2"
        sdtContent.Append(CreateStaticTocEntry("TOC2", "1.2 研究目的", "2"));

        // TOC level 1 entry: "第2章 文献综述...........3"
        sdtContent.Append(CreateStaticTocEntry("TOC1", "第2章 文献综述", "3"));

        // TOC level 2 entry: "2.1 国内研究现状...........3"
        sdtContent.Append(CreateStaticTocEntry("TOC2", "2.1 国内研究现状", "3"));

        // TOC level 3 entry: "2.1.1 早期研究...........4"
        sdtContent.Append(CreateStaticTocEntry("TOC3", "2.1.1 早期研究", "4"));

        // TOC level 1 entry: "第3章 研究方法...........5"
        sdtContent.Append(CreateStaticTocEntry("TOC1", "第3章 研究方法", "5"));

        // ─── Field code END paragraph ───
        var fieldEndPara = new Paragraph();
        fieldEndPara.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.End }));
        sdtContent.Append(fieldEndPara);

        sdtBlock.Append(sdtContent);
        body.Append(sdtBlock);

        // ─── Actual heading paragraphs (what the TOC references) ───
        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text("第1章 绪论"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading2" }),
            new Run(new Text("1.1 研究背景"))));

        body.Append(new Paragraph(
            new Run(new Text("本研究旨在探讨……"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading2" }),
            new Run(new Text("1.2 研究目的"))));

        body.Append(new Paragraph(
            new Run(new Text("研究目的包括……"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text("第2章 文献综述"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading2" }),
            new Run(new Text("2.1 国内研究现状"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading3" }),
            new Run(new Text("2.1.1 早期研究"))));

        body.Append(new Paragraph(
            new Run(new Text("早期研究表明……"))));

        body.Append(new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
            new Run(new Text("第3章 研究方法"))));

        body.Append(new Paragraph(
            new Run(new Text("本章介绍研究方法……"))));

        // ─── Enable UpdateFieldsOnOpen so TOC auto-refreshes ───
        var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
        EnableUpdateFieldsOnOpen(settingsPart);

        mainPart.Document.Save();
    }

    /// <summary>
    /// Helper: creates a single static TOC entry paragraph with style, text, tab leader, and page number.
    /// This mirrors what Word generates inside a TOC SDT block.
    /// </summary>
    private static Paragraph CreateStaticTocEntry(string tocStyleId, string entryText, string pageNumber)
    {
        var para = new Paragraph();

        // Paragraph properties: TOC style + right-aligned tab with dot leader
        var pPr = new ParagraphProperties();
        pPr.Append(new ParagraphStyleId { Val = tocStyleId });
        para.Append(pPr);

        // Run with entry text
        para.Append(new Run(
            new RunProperties(new NoProof()),
            new Text(entryText) { Space = SpaceProcessingModeValues.Preserve }));

        // Tab character (creates the dot leader between text and page number)
        para.Append(new Run(new TabChar()));

        // Page number
        para.Append(new Run(
            new RunProperties(new NoProof()),
            new Text(pageNumber)));

        return para;
    }

    // ──────────────────────────────────────────────
    // Private helper: insert complex field inline
    // ──────────────────────────────────────────────

    /// <summary>
    /// Shared helper that appends Begin / FieldCode / Separate / CachedValue / End
    /// runs to a paragraph.
    /// </summary>
    private static void InsertComplexFieldInline(Paragraph para, string instruction)
    {
        // Run 1: FieldChar Begin
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Begin }));

        // Run 2: FieldCode (the instruction text)
        para.Append(new Run(
            new FieldCode(instruction) { Space = SpaceProcessingModeValues.Preserve }));

        // Run 3: FieldChar Separate
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.Separate }));

        // Run 4: Cached display value (placeholder until Word recalculates)
        para.Append(new Run(
            new RunProperties(new NoProof()),
            new Text("1") { Space = SpaceProcessingModeValues.Preserve }));

        // Run 5: FieldChar End
        para.Append(new Run(
            new FieldChar { FieldCharType = FieldCharValues.End }));
    }
}
