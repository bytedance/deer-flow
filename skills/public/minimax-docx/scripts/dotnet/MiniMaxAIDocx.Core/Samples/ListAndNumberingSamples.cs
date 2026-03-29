// ============================================================================
// ListAndNumberingSamples.cs — OpenXML numbering system deep dive
// ============================================================================
// OpenXML list/numbering architecture (3 layers):
//
//   1. AbstractNum — defines the numbering FORMAT (bullet chars, number formats,
//      indentation, fonts). Contains Level elements (0-8) for multi-level lists.
//
//   2. NumberingInstance (Num) — a concrete "instance" that references an
//      AbstractNum. Multiple paragraphs share the same NumId to form one list.
//      LevelOverride on a NumberingInstance can restart numbering.
//
//   3. NumberingProperties on Paragraph — links a paragraph to a NumberingInstance
//      via NumId + Level (ilvl). This is what makes a paragraph a list item.
//
// CRITICAL RULES:
//   - In the Numbering root element, ALL AbstractNum elements MUST appear
//     BEFORE any NumberingInstance (Num) elements. Violating this order causes
//     Word to report corruption.
//   - LevelText uses %1, %2, %3 etc. as placeholders for the current value
//     at each level. %1 = level 0's value, %2 = level 1's value, etc.
//   - NumberingSymbolRunProperties (rPr inside Level) sets the font for the
//     bullet character or number. Without it, the bullet may render in the
//     paragraph's font, which can produce wrong glyphs.
//   - IsLegalNumberingStyle on a Level forces "legal" flat numbering
//     (e.g., "1.1.1" instead of outline style) regardless of heading level.
//
// Storage: Numbering definitions live in numbering.xml, accessed via
//   NumberingDefinitionsPart on the MainDocumentPart.
// ============================================================================

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using A = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Reference implementations for bullet lists, numbered lists, custom numbering,
/// and all related numbering infrastructure in OpenXML.
/// </summary>
public static class ListAndNumberingSamples
{
    // ── 1. Bullet List (3 levels) ──────────────────────────────────────

    /// <summary>
    /// Creates a 3-level bullet list: bullet (•) → circle (○) → square (■).
    /// Uses Symbol font for standard bullet characters.
    /// </summary>
    public static void CreateBulletList(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 0;
        int numId = 1;

        // Level 0: solid bullet •  (Unicode F0B7 in Symbol font)
        // Level 1: open circle ○   (Unicode F06F in Symbol font = ○, or "o" in Courier New)
        // Level 2: solid square ■  (Unicode F0A7 in Wingdings)
        var levels = new Level[]
        {
            CreateBulletLevel(
                levelIndex: 0,
                bulletChar: "\xF0B7",  // • in Symbol
                font: "Symbol",
                indentLeftDxa: 720,     // 0.5 inch
                hangingDxa: 360),       // bullet hangs 0.25 inch

            CreateBulletLevel(
                levelIndex: 1,
                bulletChar: "o",        // ○ in Courier New
                font: "Courier New",
                indentLeftDxa: 1440,    // 1.0 inch
                hangingDxa: 360),

            CreateBulletLevel(
                levelIndex: 2,
                bulletChar: "\xF0A7",  // ■ in Wingdings
                font: "Wingdings",
                indentLeftDxa: 2160,    // 1.5 inch
                hangingDxa: 360)
        };

        // Build the abstract numbering definition and instance
        SetupAbstractNum(numPart, abstractNumId, levels);
        SetupNumberingInstance(numPart, numId, abstractNumId);

        // Create sample list items at each level
        string[] level0Items = ["First item", "Second item", "Third item"];
        string[] level1Items = ["Sub-item A", "Sub-item B"];
        string[] level2Items = ["Detail 1", "Detail 2"];

        foreach (string text in level0Items)
        {
            Paragraph para = CreateListParagraph(text, numId, level: 0);
            body.AppendChild(para);
        }
        foreach (string text in level1Items)
        {
            Paragraph para = CreateListParagraph(text, numId, level: 1);
            body.AppendChild(para);
        }
        foreach (string text in level2Items)
        {
            Paragraph para = CreateListParagraph(text, numId, level: 2);
            body.AppendChild(para);
        }
    }

    // ── 2. Numbered List (3 levels) ────────────────────────────────────

    /// <summary>
    /// Creates a 3-level numbered list: 1. → 1.1. → 1.1.1.
    /// Uses NumberFormatValues.Decimal with compound LevelText patterns.
    /// </summary>
    public static void CreateNumberedList(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 1;
        int numId = 2;

        // LevelText explanation:
        //   "%1"       → just the level-0 counter: 1, 2, 3...
        //   "%1.%2"    → level-0.level-1: 1.1, 1.2, 2.1...
        //   "%1.%2.%3" → level-0.level-1.level-2: 1.1.1, 1.1.2...
        var levels = new Level[]
        {
            CreateNumberLevel(
                levelIndex: 0,
                format: NumberFormatValues.Decimal,
                levelText: "%1.",        // "1.", "2.", "3."
                indentLeftDxa: 720,
                hangingDxa: 360,
                start: 1),

            CreateNumberLevel(
                levelIndex: 1,
                format: NumberFormatValues.Decimal,
                levelText: "%1.%2.",     // "1.1.", "1.2.", "2.1."
                indentLeftDxa: 1440,
                hangingDxa: 720,         // wider hanging for "1.1."
                start: 1),

            CreateNumberLevel(
                levelIndex: 2,
                format: NumberFormatValues.Decimal,
                levelText: "%1.%2.%3.",  // "1.1.1.", "1.1.2."
                indentLeftDxa: 2160,
                hangingDxa: 1080,
                start: 1)
        };

        SetupAbstractNum(numPart, abstractNumId, levels);
        SetupNumberingInstance(numPart, numId, abstractNumId);

        // Sample items
        body.AppendChild(CreateListParagraph("Chapter One", numId, level: 0));
        body.AppendChild(CreateListParagraph("Section One", numId, level: 1));
        body.AppendChild(CreateListParagraph("Detail A", numId, level: 2));
        body.AppendChild(CreateListParagraph("Detail B", numId, level: 2));
        body.AppendChild(CreateListParagraph("Section Two", numId, level: 1));
        body.AppendChild(CreateListParagraph("Chapter Two", numId, level: 0));
    }

    // ── 3. Custom Bullet Characters ────────────────────────────────────

    /// <summary>
    /// Creates bullets with custom Unicode characters: ✓ (check), ➢ (arrow), ★ (star).
    /// Uses specific fonts that contain these glyphs.
    /// </summary>
    public static void CreateCustomBullets(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 2;
        int numId = 3;

        // For custom Unicode bullets, the font in NumberingSymbolRunProperties
        // MUST contain the glyph. Common choices:
        //   - "Segoe UI Symbol" — broad Unicode coverage on Windows
        //   - "Arial Unicode MS" — wide coverage
        //   - "Wingdings" / "Webdings" — symbol fonts (use their private codepoints)
        var levels = new Level[]
        {
            CreateBulletLevel(
                levelIndex: 0,
                bulletChar: "\u2713",   // ✓ CHECK MARK
                font: "Segoe UI Symbol",
                indentLeftDxa: 720,
                hangingDxa: 360),

            CreateBulletLevel(
                levelIndex: 1,
                bulletChar: "\u27A2",   // ➢ THREE-D TOP-LIGHTED RIGHTWARDS ARROWHEAD
                font: "Segoe UI Symbol",
                indentLeftDxa: 1440,
                hangingDxa: 360),

            CreateBulletLevel(
                levelIndex: 2,
                bulletChar: "\u2605",   // ★ BLACK STAR
                font: "Segoe UI Symbol",
                indentLeftDxa: 2160,
                hangingDxa: 360)
        };

        SetupAbstractNum(numPart, abstractNumId, levels);
        SetupNumberingInstance(numPart, numId, abstractNumId);

        body.AppendChild(CreateListParagraph("Completed task", numId, level: 0));
        body.AppendChild(CreateListParagraph("Action item", numId, level: 1));
        body.AppendChild(CreateListParagraph("Starred note", numId, level: 2));
    }

    // ── 4. Outline Numbering Linked to Heading Styles ──────────────────

    /// <summary>
    /// Creates outline numbering (Article 1, Section 1.1, etc.) linked to
    /// Heading1, Heading2, Heading3 styles. This is how Word's built-in
    /// "List Number" styles work for legal/technical documents.
    /// </summary>
    /// <remarks>
    /// When a Level has ParagraphStyleIdInLevel, any paragraph with that
    /// style ID automatically gets numbered. The numbering is "linked" to
    /// the style — you don't need NumberingProperties on each paragraph
    /// (though it's also valid to add them explicitly).
    /// </remarks>
    public static void CreateOutlineNumbering(
        NumberingDefinitionsPart numPart,
        StyleDefinitionsPart stylesPart)
    {
        int abstractNumId = 3;
        int numId = 4;

        var abstractNum = new AbstractNum(
            // Level 0: "1" — linked to Heading1
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "%1" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new ParagraphStyleIdInLevel { Val = "Heading1" },
                new PreviousParagraphProperties(
                    new Indentation { Left = "432", Hanging = "432" })
            )
            { LevelIndex = 0 },

            // Level 1: "1.1" — linked to Heading2
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "%1.%2" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new ParagraphStyleIdInLevel { Val = "Heading2" },
                new PreviousParagraphProperties(
                    new Indentation { Left = "576", Hanging = "576" })
            )
            { LevelIndex = 1 },

            // Level 2: "1.1.1" — linked to Heading3
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "%1.%2.%3" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new ParagraphStyleIdInLevel { Val = "Heading3" },
                new PreviousParagraphProperties(
                    new Indentation { Left = "720", Hanging = "720" })
            )
            { LevelIndex = 2 }
        )
        {
            AbstractNumberId = abstractNumId,
            // MultiLevelType controls how Word treats level transitions:
            //   - HybridMultilevel: each level is somewhat independent (most common)
            //   - Multilevel: true outline numbering where sub-levels nest under parents
            //   - SingleLevel: only one level
            MultiLevelType = new MultiLevelType
            {
                Val = MultiLevelValues.Multilevel
            }
        };

        // Ensure AbstractNum appears first, then NumberingInstance
        EnsureNumberingRoot(numPart);
        numPart.Numbering.Append(abstractNum);

        var numInstance = new NumberingInstance(
            new AbstractNumId { Val = abstractNumId })
        { NumberID = numId };
        numPart.Numbering.Append(numInstance);

        // Link the styles to the numbering definition.
        // Each heading style gets a NumberingProperties pointing to this numId.
        Styles styles = stylesPart.Styles ?? (stylesPart.Styles = new Styles());

        LinkStyleToNumbering(styles, "Heading1", numId, level: 0);
        LinkStyleToNumbering(styles, "Heading2", numId, level: 1);
        LinkStyleToNumbering(styles, "Heading3", numId, level: 2);
    }

    // ── 5. Legal Numbering ─────────────────────────────────────────────

    /// <summary>
    /// Creates a legal document numbering pattern:
    ///   Article I, Article II  (Roman numerals)
    ///   Section 1, Section 2   (Decimal)
    ///   (a), (b), (c)          (Lowercase letters)
    /// </summary>
    public static void CreateLegalNumbering(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 4;
        int numId = 5;

        var abstractNum = new AbstractNum(
            // Level 0: "Article I" — Upper Roman
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.UpperRoman },
                new LevelText { Val = "Article %1" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "720", Hanging = "720" }),
                new NumberingSymbolRunProperties(
                    new Bold(),
                    new RunFonts { Ascii = "Times New Roman", HighAnsi = "Times New Roman" })
            )
            { LevelIndex = 0 },

            // Level 1: "Section 1" — Decimal
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "Section %2" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "1440", Hanging = "720" })
            )
            { LevelIndex = 1 },

            // Level 2: "(a)" — Lowercase letter
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.LowerLetter },
                new LevelText { Val = "(%3)" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "2160", Hanging = "720" })
            )
            { LevelIndex = 2 }
        )
        {
            AbstractNumberId = abstractNumId,
            MultiLevelType = new MultiLevelType { Val = MultiLevelValues.Multilevel }
        };

        EnsureNumberingRoot(numPart);
        numPart.Numbering.Append(abstractNum);
        SetupNumberingInstance(numPart, numId, abstractNumId);

        // Sample legal document structure
        body.AppendChild(CreateListParagraph("Definitions", numId, level: 0));
        body.AppendChild(CreateListParagraph("General Terms", numId, level: 1));
        body.AppendChild(CreateListParagraph(
            "\"Agreement\" means this document and all exhibits.", numId, level: 2));
        body.AppendChild(CreateListParagraph(
            "\"Party\" means any signatory to this Agreement.", numId, level: 2));
        body.AppendChild(CreateListParagraph("Scope of Work", numId, level: 1));
        body.AppendChild(CreateListParagraph("Obligations", numId, level: 0));
    }

    // ── 6. Chinese Numbering ───────────────────────────────────────────

    /// <summary>
    /// Creates a Chinese document numbering hierarchy:
    ///   Level 0: 一、二、三、          (Chinese ideographic, followed by 、)
    ///   Level 1: （一）（二）（三）    (Chinese ideographic in parentheses)
    ///   Level 2: 1. 2. 3.              (Decimal, Arabic numerals)
    ///   Level 3: (1) (2) (3)           (Decimal in parentheses)
    ///
    /// Chinese numbering uses NumberFormatValues.ChineseCounting or
    /// ChineseCountingThousand for 一二三 style characters.
    /// The font for Chinese number characters should be a CJK font like SimSun or SimHei.
    /// </summary>
    public static void CreateChineseNumbering(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 5;
        int numId = 6;

        var abstractNum = new AbstractNum(
            // Level 0: 一、 二、 三、
            // ChineseCountingThousand produces 一 二 三 四 五 六 七 八 九 十
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.ChineseCountingThousand },
                new LevelText { Val = "%1\u3001" }, // 、 is the Chinese enumeration comma
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "840", Hanging = "420" }),
                // NumberingSymbolRunProperties MUST specify a CJK font
                // so the Chinese number renders correctly
                new NumberingSymbolRunProperties(
                    new RunFonts
                    {
                        Ascii = "SimSun",
                        HighAnsi = "SimSun",
                        EastAsia = "SimSun",      // Critical for CJK rendering
                        ComplexScript = "SimSun"
                    })
            )
            { LevelIndex = 0 },

            // Level 1: （一）（二）（三）
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.ChineseCountingThousand },
                new LevelText { Val = "\uFF08%2\uFF09" }, // （ and ） are fullwidth parens
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "1260", Hanging = "420" }),
                new NumberingSymbolRunProperties(
                    new RunFonts
                    {
                        Ascii = "SimSun",
                        HighAnsi = "SimSun",
                        EastAsia = "SimSun",
                        ComplexScript = "SimSun"
                    })
            )
            { LevelIndex = 1 },

            // Level 2: 1. 2. 3.
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "%3." },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "1680", Hanging = "420" })
            )
            { LevelIndex = 2 },

            // Level 3: (1) (2) (3)
            new Level(
                new StartNumberingValue { Val = 1 },
                new NumberingFormat { Val = NumberFormatValues.Decimal },
                new LevelText { Val = "(%4)" },
                new LevelJustification { Val = LevelJustificationValues.Left },
                new PreviousParagraphProperties(
                    new Indentation { Left = "2100", Hanging = "420" })
            )
            { LevelIndex = 3 }
        )
        {
            AbstractNumberId = abstractNumId,
            MultiLevelType = new MultiLevelType { Val = MultiLevelValues.Multilevel }
        };

        EnsureNumberingRoot(numPart);
        numPart.Numbering.Append(abstractNum);
        SetupNumberingInstance(numPart, numId, abstractNumId);

        body.AppendChild(CreateListParagraph("总则", numId, level: 0));
        body.AppendChild(CreateListParagraph("目的和依据", numId, level: 1));
        body.AppendChild(CreateListParagraph("本办法适用于全体员工。", numId, level: 2));
        body.AppendChild(CreateListParagraph("自发布之日起施行。", numId, level: 3));
        body.AppendChild(CreateListParagraph("适用范围", numId, level: 1));
        body.AppendChild(CreateListParagraph("职责与权限", numId, level: 0));
    }

    // ── 7. Restart Numbering ───────────────────────────────────────────

    /// <summary>
    /// Demonstrates how to restart a numbered list at 1 using LevelOverride
    /// with StartOverride. This creates a new NumberingInstance that shares
    /// the same AbstractNum but overrides the start value.
    /// </summary>
    /// <remarks>
    /// Scenario: You have items 1-5 in one list, then want a separate list
    /// that starts again at 1 with the same formatting. You need a new
    /// NumberingInstance (new NumId) with LevelOverride.
    /// </remarks>
    public static void RestartNumbering(
        NumberingDefinitionsPart numPart, Body body)
    {
        int abstractNumId = 6;
        int numId1 = 7;
        int numId2 = 8; // Second instance for restarted list

        // Simple single-level numbered list
        var levels = new Level[]
        {
            CreateNumberLevel(
                levelIndex: 0,
                format: NumberFormatValues.Decimal,
                levelText: "%1.",
                indentLeftDxa: 720,
                hangingDxa: 360,
                start: 1)
        };

        SetupAbstractNum(numPart, abstractNumId, levels);
        SetupNumberingInstance(numPart, numId1, abstractNumId);

        // First list: 1, 2, 3
        body.AppendChild(CreateListParagraph("First list item 1", numId1, level: 0));
        body.AppendChild(CreateListParagraph("First list item 2", numId1, level: 0));
        body.AppendChild(CreateListParagraph("First list item 3", numId1, level: 0));

        // Non-list paragraph between the lists
        body.AppendChild(new Paragraph(
            new Run(new Text("Some text between lists."))));

        // Create a NEW NumberingInstance with LevelOverride to restart at 1.
        // LevelOverride on a NumberingInstance overrides a specific level's
        // start value WITHOUT creating a new AbstractNum.
        var restartedInstance = new NumberingInstance(
            new AbstractNumId { Val = abstractNumId },
            // LevelOverride resets level 0 to start at 1
            new LevelOverride(
                new StartOverrideNumberingValue { Val = 1 }
            )
            { LevelIndex = 0 }
        )
        { NumberID = numId2 };

        numPart.Numbering.Append(restartedInstance);

        // Second list uses numId2: starts at 1 again
        body.AppendChild(CreateListParagraph("Restarted item 1", numId2, level: 0));
        body.AppendChild(CreateListParagraph("Restarted item 2", numId2, level: 0));
        body.AppendChild(CreateListParagraph("Restarted item 3", numId2, level: 0));
    }

    // ── 8. Continue Numbering ──────────────────────────────────────────

    /// <summary>
    /// Continues numbering from a previous list by using the same NumId.
    /// All paragraphs sharing a NumId form a single continuous sequence.
    /// Inserting non-list paragraphs between them does NOT break the sequence.
    /// </summary>
    /// <param name="body">The Body to append paragraphs to.</param>
    /// <param name="existingNumId">The NumId of the list to continue.</param>
    public static void ContinueNumbering(Body body, int existingNumId)
    {
        // Simply use the SAME numId as the existing list.
        // Word automatically continues the counter from wherever it left off.
        // Even if there are non-list paragraphs in between, the numbering
        // picks up seamlessly.

        body.AppendChild(new Paragraph(
            new Run(new Text("(Non-list paragraph — numbering continues after this.)"))));

        // These will be numbered 4, 5 (assuming previous list ended at 3)
        body.AppendChild(CreateListParagraph(
            "Continued item", existingNumId, level: 0));
        body.AppendChild(CreateListParagraph(
            "Another continued item", existingNumId, level: 0));
    }

    // ── 9. Setup AbstractNum (Helper) ──────────────────────────────────

    /// <summary>
    /// Builds an AbstractNum from an array of Level definitions and appends
    /// it to the Numbering root. AbstractNum defines the *format* of a list
    /// (bullet characters, number format, indentation, fonts).
    /// </summary>
    /// <param name="numPart">The NumberingDefinitionsPart to append to.</param>
    /// <param name="abstractNumId">Unique ID for this abstract definition.</param>
    /// <param name="levels">Array of Level elements (one per nesting level, max 9).</param>
    public static void SetupAbstractNum(
        NumberingDefinitionsPart numPart, int abstractNumId, Level[] levels)
    {
        EnsureNumberingRoot(numPart);

        var abstractNum = new AbstractNum
        {
            AbstractNumberId = abstractNumId,
            // MultiLevelType:
            //   HybridMultilevel — most common; each level can have independent formatting
            //   Multilevel — true outline; sub-levels inherit parent context
            //   SingleLevel — only level 0 is used
            MultiLevelType = new MultiLevelType
            {
                Val = levels.Length > 1
                    ? MultiLevelValues.HybridMultilevel
                    : MultiLevelValues.SingleLevel
            }
        };

        foreach (Level level in levels)
        {
            abstractNum.Append(level.CloneNode(true));
        }

        // IMPORTANT: AbstractNum must be inserted BEFORE any NumberingInstance
        // elements in the Numbering root. Find the right position.
        NumberingInstance? firstNumInstance =
            numPart.Numbering.GetFirstChild<NumberingInstance>();

        if (firstNumInstance is not null)
        {
            numPart.Numbering.InsertBefore(abstractNum, firstNumInstance);
        }
        else
        {
            numPart.Numbering.Append(abstractNum);
        }
    }

    // ── 10. Setup NumberingInstance (Helper) ────────────────────────────

    /// <summary>
    /// Creates a NumberingInstance (Num element) that references an AbstractNum.
    /// The NumberingInstance is what paragraphs actually point to via NumId.
    /// Multiple paragraphs with the same NumId form one continuous list.
    /// </summary>
    /// <param name="numPart">The NumberingDefinitionsPart to append to.</param>
    /// <param name="numId">Unique instance ID (referenced by paragraphs).
    /// Must be &gt;= 1; value 0 is reserved for "no numbering".</param>
    /// <param name="abstractNumId">The AbstractNum this instance uses.</param>
    public static void SetupNumberingInstance(
        NumberingDefinitionsPart numPart, int numId, int abstractNumId)
    {
        EnsureNumberingRoot(numPart);

        // NumberingInstance (w:num) links to AbstractNum via AbstractNumId child
        var numInstance = new NumberingInstance(
            new AbstractNumId { Val = abstractNumId })
        {
            // NumberID is the w:numId attribute; this is what paragraphs reference
            NumberID = numId
        };

        // NumberingInstance MUST come after all AbstractNum elements
        numPart.Numbering.Append(numInstance);
    }

    // ── 11. Apply Numbering to Paragraph (Helper) ──────────────────────

    /// <summary>
    /// Applies numbering to an existing paragraph by setting NumberingProperties
    /// in the ParagraphProperties. This is the final link that makes a
    /// paragraph display as a list item.
    /// </summary>
    /// <param name="para">The paragraph to make into a list item.</param>
    /// <param name="numId">The NumberingInstance ID to use.</param>
    /// <param name="level">The indentation level (0 = top level, max 8).</param>
    public static void ApplyNumberingToParagraph(Paragraph para, int numId, int level)
    {
        // NumberingProperties contains:
        //   - NumberingLevelReference (w:ilvl) — which level (0-8)
        //   - NumberingId (w:numId) — which NumberingInstance to use
        var numberingProperties = new NumberingProperties(
            new NumberingLevelReference { Val = level },
            new NumberingId { Val = numId });

        // Ensure ParagraphProperties exists
        ParagraphProperties pPr = para.GetFirstChild<ParagraphProperties>()
            ?? para.PrependChild(new ParagraphProperties());

        // Replace existing NumberingProperties if present
        NumberingProperties? existing = pPr.GetFirstChild<NumberingProperties>();
        if (existing is not null)
        {
            pPr.ReplaceChild(numberingProperties, existing);
        }
        else
        {
            // NumberingProperties should appear early in ParagraphProperties
            // (after ParagraphStyleId if present)
            ParagraphStyleId? styleId = pPr.GetFirstChild<ParagraphStyleId>();
            if (styleId is not null)
            {
                pPr.InsertAfter(numberingProperties, styleId);
            }
            else
            {
                pPr.PrependChild(numberingProperties);
            }
        }
    }

    // ── Private Helper Methods ─────────────────────────────────────────

    /// <summary>
    /// Creates a bullet-type Level definition.
    /// </summary>
    private static Level CreateBulletLevel(
        int levelIndex,
        string bulletChar,
        string font,
        int indentLeftDxa,
        int hangingDxa)
    {
        return new Level(
            // Bullets don't increment, but StartNumberingValue is still required
            new StartNumberingValue { Val = 1 },
            // NumberFormatValues.Bullet tells Word this is a bullet, not a number
            new NumberingFormat { Val = NumberFormatValues.Bullet },
            // LevelText.Val is the actual bullet character
            new LevelText { Val = bulletChar },
            new LevelJustification { Val = LevelJustificationValues.Left },
            // PreviousParagraphProperties controls indentation of the text
            // (confusingly named; it's the paragraph indent for THIS level)
            new PreviousParagraphProperties(
                new Indentation
                {
                    Left = indentLeftDxa.ToString(),
                    Hanging = hangingDxa.ToString()
                }),
            // NumberingSymbolRunProperties sets the font for the bullet character.
            // Without this, the bullet renders in the paragraph's body font,
            // which may not contain the glyph (e.g., Symbol characters).
            new NumberingSymbolRunProperties(
                new RunFonts
                {
                    Ascii = font,
                    HighAnsi = font,
                    Hint = FontTypeHintValues.Default
                })
        )
        { LevelIndex = levelIndex };
    }

    /// <summary>
    /// Creates a number-type Level definition.
    /// </summary>
    private static Level CreateNumberLevel(
        int levelIndex,
        NumberFormatValues format,
        string levelText,
        int indentLeftDxa,
        int hangingDxa,
        int start)
    {
        return new Level(
            new StartNumberingValue { Val = start },
            new NumberingFormat { Val = format },
            new LevelText { Val = levelText },
            new LevelJustification { Val = LevelJustificationValues.Left },
            new PreviousParagraphProperties(
                new Indentation
                {
                    Left = indentLeftDxa.ToString(),
                    Hanging = hangingDxa.ToString()
                })
        )
        { LevelIndex = levelIndex };
    }

    /// <summary>
    /// Creates a paragraph with text and numbering properties applied.
    /// </summary>
    private static Paragraph CreateListParagraph(string text, int numId, int level)
    {
        var para = new Paragraph(
            new ParagraphProperties(
                new NumberingProperties(
                    new NumberingLevelReference { Val = level },
                    new NumberingId { Val = numId })),
            new Run(new Text(text)));
        return para;
    }

    /// <summary>
    /// Ensures the Numbering root element exists on the NumberingDefinitionsPart.
    /// </summary>
    private static void EnsureNumberingRoot(NumberingDefinitionsPart numPart)
    {
        if (numPart.Numbering is null)
        {
            numPart.Numbering = new Numbering();
        }
    }

    /// <summary>
    /// Links a named style to a numbering definition by adding NumberingProperties
    /// to the style's ParagraphProperties.
    /// </summary>
    private static void LinkStyleToNumbering(
        Styles styles, string styleId, int numId, int level)
    {
        // Find existing style or create it
        Style? style = styles.Elements<Style>()
            .FirstOrDefault(s => s.StyleId?.Value == styleId);

        if (style is null)
        {
            style = new Style
            {
                Type = StyleValues.Paragraph,
                StyleId = styleId,
                StyleName = new StyleName { Val = styleId }
            };
            styles.Append(style);
        }

        // Ensure StyleParagraphProperties exists
        StyleParagraphProperties? spPr = style.GetFirstChild<StyleParagraphProperties>();
        if (spPr is null)
        {
            spPr = new StyleParagraphProperties();
            style.Append(spPr);
        }

        // Set NumberingProperties on the style
        NumberingProperties? existingNumPr = spPr.GetFirstChild<NumberingProperties>();
        var newNumPr = new NumberingProperties(
            new NumberingLevelReference { Val = level },
            new NumberingId { Val = numId });

        if (existingNumPr is not null)
        {
            spPr.ReplaceChild(newNumPr, existingNumPr);
        }
        else
        {
            spPr.Append(newNumPr);
        }
    }
}
