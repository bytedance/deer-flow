using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Exhaustive reference for every ParagraphProperties (w:pPr) child element in OpenXML.
/// Each method demonstrates one formatting category with full XML doc comments,
/// unit explanations, and gotchas. All code compiles against DocumentFormat.OpenXml 3.5.1.
/// </summary>
public static class ParagraphFormattingSamples
{
    // ──────────────────────────────────────────────────────────────────
    // 1. Justification / Alignment (w:jc)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets paragraph horizontal alignment (justification).
    /// <para>
    /// <b>All JustificationValues:</b>
    /// <list type="bullet">
    ///   <item><b>Left</b> — Left-aligned (default for LTR documents). Ragged right edge.</item>
    ///   <item><b>Center</b> — Centered text.</item>
    ///   <item><b>Right</b> — Right-aligned. Ragged left edge.</item>
    ///   <item><b>Both</b> — Justified: text stretches to fill the full line width.
    ///     The last line is left-aligned. Word adjusts inter-word spacing.</item>
    ///   <item><b>Distribute</b> — Like justify, but also stretches the last line.
    ///     Word adjusts both inter-word AND inter-character spacing. Used in CJK typography.</item>
    ///   <item><b>ThaiDistribute</b> — Special distribute mode for Thai script,
    ///     which has unique spacing rules around vowel marks and tone marks.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> In RTL paragraphs (w:bidi), "Left" actually means the START edge
    /// (right side in RTL) and "Right" means the END edge. Use Start/End values if
    /// you need direction-independent alignment (not all renderers support them).
    /// </para>
    /// </summary>
    public static void ApplyJustification(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Left-aligned (default for Western text)
        pPr.Justification = new Justification { Val = JustificationValues.Left };

        // Center-aligned
        // pPr.Justification = new Justification { Val = JustificationValues.Center };

        // Right-aligned
        // pPr.Justification = new Justification { Val = JustificationValues.Right };

        // Justified (both edges flush, last line left-aligned)
        // pPr.Justification = new Justification { Val = JustificationValues.Both };

        // Distribute (all lines justified including last, with inter-character spacing)
        // pPr.Justification = new Justification { Val = JustificationValues.Distribute };

        // Thai distribute (specialized Thai script distribution)
        // pPr.Justification = new Justification { Val = JustificationValues.ThaiDistribute };
    }

    // ──────────────────────────────────────────────────────────────────
    // 2. Indentation (w:ind)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets paragraph indentation: left, right, first-line, and hanging.
    /// <para>
    /// <b>Units:</b> All values are in <b>DXA</b> (twentieths of a point).
    /// 1 inch = 1440 DXA, 1 cm ≈ 567 DXA, 1 pt = 20 DXA.
    /// </para>
    /// <para>
    /// <b>Properties:</b>
    /// <list type="bullet">
    ///   <item><b>Left</b> — Left indent for the entire paragraph (shifts all lines right).</item>
    ///   <item><b>Right</b> — Right indent (shifts the right boundary left).</item>
    ///   <item><b>FirstLine</b> — Additional indent for the FIRST line only (added to Left).
    ///     720 DXA = 0.5 inch first-line indent.</item>
    ///   <item><b>Hanging</b> — The first line hangs LEFT of the paragraph body.
    ///     Used for numbered/bulleted lists. Mutually exclusive with FirstLine.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>CJK character units:</b>
    /// <list type="bullet">
    ///   <item><b>FirstLineChars</b> — First-line indent in hundredths of a character width.
    ///     200 = 2 character widths. Takes precedence over FirstLine when set.</item>
    ///   <item><b>LeftChars</b> — Left indent in hundredths of a character width.</item>
    ///   <item><b>RightChars</b> — Right indent in hundredths of a character width.</item>
    ///   <item><b>HangingChars</b> — Hanging indent in hundredths of a character width.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> FirstLine and Hanging are mutually exclusive. If both are set,
    /// behavior is undefined. Setting one should clear the other.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> When using character-based units (FirstLineChars, etc.),
    /// the corresponding DXA value (FirstLine, etc.) should also be set as a fallback
    /// for renderers that do not support character-based indentation.
    /// </para>
    /// </summary>
    public static void ApplyIndentation(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Standard indentation in DXA
        pPr.Indentation = new Indentation
        {
            Left = "720",         // 0.5 inch left indent (720 DXA)
            Right = "360",        // 0.25 inch right indent (360 DXA)
            FirstLine = "720"     // 0.5 inch first-line indent (720 DXA)
        };

        // Hanging indent (commonly used with bullets/numbering)
        // pPr.Indentation = new Indentation
        // {
        //     Left = "720",      // Overall paragraph indent
        //     Hanging = "360"    // First line hangs back 0.25 inch
        //     // Effective first line position: 720 - 360 = 360 DXA from margin
        // };

        // CJK character-based indent
        // pPr.Indentation = new Indentation
        // {
        //     FirstLineChars = 200,   // 2 character widths (200 hundredths)
        //     FirstLine = "480"       // DXA fallback (approx 2 chars at ~10.5pt SimSun)
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 3. Line Spacing (w:spacing — line, lineRule)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the spacing between lines within a paragraph.
    /// <para>
    /// <b>LineRule values and their Line units:</b>
    /// <list type="bullet">
    ///   <item><b>Auto</b> — Line is in <b>240ths of a line</b> (proportional).
    ///     240 = single spacing (1.0), 276 = 1.15 (Word default), 360 = 1.5, 480 = 2.0.
    ///     Formula: value = desiredMultiplier * 240.</item>
    ///   <item><b>Exact</b> — Line is in <b>DXA</b> (twentieths of a point).
    ///     The line height is fixed at exactly this value. Text may be clipped if too tall.
    ///     Example: 240 DXA = 12pt exact line height.</item>
    ///   <item><b>AtLeast</b> — Line is in <b>DXA</b>. The line height is at least this
    ///     value, but can grow larger to accommodate tall content (images, large fonts).
    ///     Example: 240 DXA = at least 12pt.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> The unit of "Line" changes depending on LineRule!
    /// Auto = 240ths of a line, Exact/AtLeast = DXA (twips). This is a very common
    /// source of bugs. If you set Line="360" with LineRule=Auto, you get 1.5x spacing.
    /// If you set Line="360" with LineRule=Exact, you get 18pt fixed height.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If LineRule is omitted, it defaults to Auto.
    /// </para>
    /// </summary>
    public static void ApplyLineSpacing(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Single spacing (1.0x) — Auto mode, 240/240 = 1.0
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Line = "240",
        //     LineRule = LineSpacingRuleValues.Auto
        // };

        // 1.15x spacing (Word's default) — Auto mode, 276/240 = 1.15
        pPr.SpacingBetweenLines = new SpacingBetweenLines
        {
            Line = "276",
            LineRule = LineSpacingRuleValues.Auto
        };

        // 1.5x spacing — Auto mode, 360/240 = 1.5
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Line = "360",
        //     LineRule = LineSpacingRuleValues.Auto
        // };

        // Double spacing (2.0x) — Auto mode, 480/240 = 2.0
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Line = "480",
        //     LineRule = LineSpacingRuleValues.Auto
        // };

        // Exact 14pt line height — no growing for tall content
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Line = "280",                               // 14pt × 20 DXA/pt = 280 DXA
        //     LineRule = LineSpacingRuleValues.Exact
        // };

        // At-least 12pt — minimum height, can grow
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Line = "240",                               // 12pt × 20 = 240 DXA
        //     LineRule = LineSpacingRuleValues.AtLeast
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 4. Paragraph Spacing — Before/After (w:spacing — before, after)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the space before and after a paragraph.
    /// <para>
    /// <b>Unit:</b> Before and After are in <b>DXA</b> (twentieths of a point).
    /// 1pt = 20 DXA. Common values: 0 DXA = 0pt, 120 DXA = 6pt, 200 DXA = 10pt,
    /// 240 DXA = 12pt.
    /// </para>
    /// <para>
    /// <b>CJK line units:</b>
    /// <list type="bullet">
    ///   <item><b>BeforeLines</b> — Space before in hundredths of a line.
    ///     100 = 1 line of space. Takes precedence over Before when set.</item>
    ///   <item><b>AfterLines</b> — Space after in hundredths of a line.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Paragraph spacing collapses: when two paragraphs are adjacent,
    /// the space between them is the LARGER of paragraph1.After and paragraph2.Before,
    /// NOT the sum. This is standard Word behavior.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> <see cref="ApplyContextualSpacing"/> can suppress spacing between
    /// paragraphs of the same style, overriding Before/After.
    /// </para>
    /// <para>
    /// <b>BeforeAutoSpacing / AfterAutoSpacing:</b> When set to true, Word auto-calculates
    /// the spacing (typically 14pt for HTML-imported paragraphs). Overrides Before/After.
    /// </para>
    /// </summary>
    public static void ApplyParagraphSpacing(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // 6pt before, 10pt after (typical body text spacing)
        pPr.SpacingBetweenLines = new SpacingBetweenLines
        {
            Before = "120",       // 6pt × 20 = 120 DXA
            After = "200"         // 10pt × 20 = 200 DXA
        };

        // Combined with line spacing
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     Before = "240",                              // 12pt before
        //     After = "120",                               // 6pt after
        //     Line = "276",                                // 1.15x line spacing
        //     LineRule = LineSpacingRuleValues.Auto
        // };

        // CJK line-based spacing
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     BeforeLines = 50,                            // 0.5 line before
        //     AfterLines = 100,                            // 1 line after
        //     Before = "120",                              // DXA fallback
        //     After = "240"                                // DXA fallback
        // };

        // Auto spacing (used in HTML imports)
        // pPr.SpacingBetweenLines = new SpacingBetweenLines
        // {
        //     BeforeAutoSpacing = true,                    // Word decides (typically 14pt)
        //     AfterAutoSpacing = true
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 5. Pagination Control (w:keepNext, w:keepLines, w:widowControl,
    //    w:pageBreakBefore)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Controls how a paragraph interacts with page breaks.
    /// <para>
    /// <b>Properties:</b>
    /// <list type="bullet">
    ///   <item><b>KeepNext</b> — Keeps this paragraph on the same page as the NEXT paragraph.
    ///     Essential for headings (so a heading is never orphaned at the bottom of a page
    ///     while its body text starts on the next page).</item>
    ///   <item><b>KeepLines</b> — Prevents a page break within this paragraph.
    ///     All lines of the paragraph stay on the same page. If it doesn't fit, the entire
    ///     paragraph moves to the next page.</item>
    ///   <item><b>WidowControl</b> — Prevents widows (a single last line of a paragraph at
    ///     the top of a page) and orphans (a single first line at the bottom of a page).
    ///     Default is ON. Set Val=false to allow widows/orphans.</item>
    ///   <item><b>PageBreakBefore</b> — Forces a page break immediately before this paragraph.
    ///     Used for chapter headings and section starts.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> These properties can cause unexpected pagination behavior.
    /// A chain of KeepNext paragraphs can push an entire group to the next page.
    /// KeepLines on a very long paragraph can cause a full blank page.
    /// </para>
    /// </summary>
    public static void ApplyKeepTogether(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Keep with next paragraph (typical for headings)
        pPr.KeepNext = new KeepNext();

        // Keep all lines of this paragraph together
        pPr.KeepLines = new KeepLines();

        // Widow/orphan control (on by default, explicitly setting here)
        pPr.WidowControl = new WidowControl();

        // Force page break before this paragraph
        // pPr.PageBreakBefore = new PageBreakBefore();

        // Disable widow/orphan control (allow widows/orphans)
        // pPr.WidowControl = new WidowControl { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 6. Outline Level (w:outlineLvl)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the outline level for Table of Contents (TOC) integration
    /// and Navigation Pane display.
    /// <para>
    /// <b>Values:</b> 0–8 (where 0 = top-level heading, 8 = deepest level).
    /// Level 9 (BodyTextLevel) means "body text" (not included in TOC).
    /// </para>
    /// <para>
    /// <b>Relationship to heading styles:</b> Word's built-in Heading 1 through Heading 9
    /// styles have outlineLvl 0–8 respectively. You can assign an outline level to ANY
    /// paragraph style, making it appear in the TOC without using a Heading style.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If you set outlineLvl directly on paragraphs (not in a style),
    /// each paragraph needs the property. It is more maintainable to define a style
    /// with the outline level and apply the style.
    /// </para>
    /// </summary>
    public static void ApplyOutlineLevel(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Level 0 = equivalent to Heading 1 in TOC
        pPr.OutlineLevel = new OutlineLevel { Val = 0 };

        // Level 1 = Heading 2 equivalent
        // pPr.OutlineLevel = new OutlineLevel { Val = 1 };

        // Level 2 = Heading 3 equivalent
        // pPr.OutlineLevel = new OutlineLevel { Val = 2 };

        // Body text (explicitly not in TOC)
        // pPr.OutlineLevel = new OutlineLevel { Val = 9 };
    }

    // ──────────────────────────────────────────────────────────────────
    // 7. Paragraph Borders (w:pBdr)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies borders to a paragraph (top, bottom, left, right, between, bar).
    /// <para>
    /// <b>Border properties:</b>
    /// <list type="bullet">
    ///   <item><b>Val</b> — Border style. Common values: Single, Double, Dotted, Dashed,
    ///     DotDash, DotDotDash, Triple, ThickThinSmallGap, ThinThickSmallGap,
    ///     ThickThinMediumGap, ThinThickMediumGap, ThickThinLargeGap, ThinThickLargeGap,
    ///     Wave, DoubleWave, DashSmallGap, DashDotStroked, ThreeDEmboss, ThreeDEngrave,
    ///     Outset, Inset, None, Nil.</item>
    ///   <item><b>Size</b> — Width in eighths of a point. 4 = 0.5pt, 8 = 1pt, 12 = 1.5pt.
    ///     Range: 2–96.</item>
    ///   <item><b>Space</b> — Distance from text to border in points. Range: 0–31.</item>
    ///   <item><b>Color</b> — Hex RGB color (e.g., "000000") or "auto".</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Between border:</b> Renders between consecutive paragraphs that BOTH have the
    /// "between" border set. This is how Word creates a visually grouped block of bordered
    /// paragraphs without doubling up borders between them.
    /// </para>
    /// <para>
    /// <b>Bar border:</b> A vertical line at the start edge of the paragraph (left for LTR,
    /// right for RTL). Not the same as the left border — the bar appears in the margin area.
    /// </para>
    /// </summary>
    public static void ApplyParagraphBorders(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        pPr.ParagraphBorders = new ParagraphBorders(
            // Top border
            new TopBorder
            {
                Val = BorderValues.Single,
                Size = 4,                    // 0.5pt
                Space = 1,                   // 1pt from text
                Color = "000000"
            },
            // Bottom border
            new BottomBorder
            {
                Val = BorderValues.Single,
                Size = 4,
                Space = 1,
                Color = "000000"
            },
            // Left border
            new LeftBorder
            {
                Val = BorderValues.Single,
                Size = 4,
                Space = 4,                   // 4pt from text
                Color = "000000"
            },
            // Right border
            new RightBorder
            {
                Val = BorderValues.Single,
                Size = 4,
                Space = 4,
                Color = "000000"
            }
        );

        // Add "between" border for consecutive bordered paragraphs
        // pPr.ParagraphBorders.AppendChild(new BetweenBorder
        // {
        //     Val = BorderValues.Single,
        //     Size = 4,
        //     Space = 1,
        //     Color = "000000"
        // });

        // Add "bar" border (vertical bar in the margin)
        // pPr.ParagraphBorders.AppendChild(new BarBorder
        // {
        //     Val = BorderValues.Single,
        //     Size = 4,
        //     Space = 0,
        //     Color = "FF0000"               // Red bar
        // });
    }

    // ──────────────────────────────────────────────────────────────────
    // 8. Paragraph Shading (w:shd)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies a background color or pattern to the entire paragraph.
    /// <para>
    /// <b>Properties:</b>
    /// <list type="bullet">
    ///   <item><b>Val</b> — Shading pattern. Use <c>ShadingPatternValues.Clear</c> for a
    ///     solid background (most common). Other patterns: HorizontalStripe, VerticalStripe,
    ///     ReverseDiagonalStripe, DiagonalStripe, DiagonalCross, HorizontalCross,
    ///     ThinHorizontalStripe, ThinVerticalStripe, Percent5 through Percent95, etc.</item>
    ///   <item><b>Fill</b> — Background color as hex RGB (e.g., "FFFF00"). "auto" = no fill.</item>
    ///   <item><b>Color</b> — Foreground/pattern color. Only visible with non-Clear patterns.
    ///     "auto" = automatic.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Theme-based shading:</b> Use ThemeFill, ThemeFillTint, ThemeFillShade for
    /// theme-aware background colors. The Fill attribute serves as a fallback.
    /// </para>
    /// </summary>
    public static void ApplyParagraphShading(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Solid light yellow background
        pPr.Shading = new Shading
        {
            Val = ShadingPatternValues.Clear,    // Solid fill
            Fill = "FFFFCC",                     // Light yellow
            Color = "auto"
        };

        // Theme-based background
        // pPr.Shading = new Shading
        // {
        //     Val = ShadingPatternValues.Clear,
        //     Fill = "D9E2F3",                  // Hex fallback
        //     ThemeFill = ThemeColorValues.Accent1,
        //     ThemeFillTint = "33"              // Light tint
        // };

        // Patterned shading (rare, but valid)
        // pPr.Shading = new Shading
        // {
        //     Val = ShadingPatternValues.Percent10,  // 10% dot pattern
        //     Fill = "FFFFFF",                        // White background
        //     Color = "000000"                        // Black dots
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 9. Tab Stops (w:tabs)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Defines custom tab stops with alignment and leader characters.
    /// <para>
    /// <b>Tab alignment values:</b>
    /// <list type="bullet">
    ///   <item><b>Left</b> — Text starts at the tab position (default).</item>
    ///   <item><b>Center</b> — Text is centered on the tab position.</item>
    ///   <item><b>Right</b> — Text ends at the tab position (text flows leftward).</item>
    ///   <item><b>Decimal</b> — Aligns on the decimal point (for numbers like 1,234.56).</item>
    ///   <item><b>Bar</b> — Draws a vertical bar at the tab position (text is not affected).</item>
    ///   <item><b>Clear</b> — Clears an inherited tab stop at this position.</item>
    ///   <item><b>Number</b> — Tab position for list numbering.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Tab leader values:</b> The character that fills the space before the tab stop.
    /// <list type="bullet">
    ///   <item><b>None</b> — Blank space (default).</item>
    ///   <item><b>Dot</b> — Dots (. . . . . .) — common in TOC.</item>
    ///   <item><b>Hyphen</b> — Hyphens (- - - - -).</item>
    ///   <item><b>Underscore</b> — Continuous underline (__________).</item>
    ///   <item><b>Heavy</b> — Thick underline.</item>
    ///   <item><b>MiddleDot</b> — Middle dots (· · · · ·).</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Position unit:</b> Tab stop position is in <b>DXA</b> (twentieths of a point).
    /// 1440 DXA = 1 inch, 720 DXA = 0.5 inch.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Tab stops are cumulative with style-defined tabs unless you use
    /// a Clear tab to remove an inherited one. Order tab stops by position.
    /// </para>
    /// </summary>
    public static void ApplyTabStops(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        pPr.Tabs = new Tabs(
            // Left tab at 1 inch
            new TabStop
            {
                Val = TabStopValues.Left,
                Position = 1440                  // 1 inch = 1440 DXA
            },
            // Center tab at 3 inches
            new TabStop
            {
                Val = TabStopValues.Center,
                Position = 4320                  // 3 inches = 4320 DXA
            },
            // Right tab at 6 inches with dot leader (TOC style)
            new TabStop
            {
                Val = TabStopValues.Right,
                Position = 8640,                 // 6 inches = 8640 DXA
                Leader = TabStopLeaderCharValues.Dot
            },
            // Decimal tab at 4 inches (for aligning numbers)
            new TabStop
            {
                Val = TabStopValues.Decimal,
                Position = 5760                  // 4 inches = 5760 DXA
            }
        );

        // Clear an inherited tab stop at 2 inches
        // pPr.Tabs.AppendChild(new TabStop
        // {
        //     Val = TabStopValues.Clear,
        //     Position = 2880
        // });

        // Bar tab at 0.5 inch (draws a vertical line, does not move text)
        // pPr.Tabs.AppendChild(new TabStop
        // {
        //     Val = TabStopValues.Bar,
        //     Position = 720
        // });
    }

    // ──────────────────────────────────────────────────────────────────
    // 10. Numbering / List (w:numPr)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Associates a paragraph with a numbering definition (bulleted or numbered list).
    /// <para>
    /// <b>NumberingId (w:numId):</b> References a numbering definition instance
    /// in the numbering.xml part (NumberingDefinitionsPart). This ID links to an
    /// AbstractNum that defines the list format.
    /// </para>
    /// <para>
    /// <b>NumberingLevelReference (w:ilvl):</b> The nesting level (0-based).
    /// 0 = top-level item, 1 = first sub-level, etc. Maximum depth: 8 (9 levels total).
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> The numbering definition must exist in numbering.xml.
    /// Creating a paragraph with numPr that references a non-existent numId will cause
    /// Word to show an error or ignore the numbering.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> To remove numbering from a paragraph that inherits it from a style,
    /// set NumberingId to 0: <c>new NumberingId { Val = 0 }</c>
    /// </para>
    /// <para>
    /// <b>NumberingChange:</b> For tracked changes, wrap numPr changes in a
    /// NumberingChange element to record the revision.
    /// </para>
    /// </summary>
    public static void ApplyNumbering(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Associate with numbering definition #1, level 0 (top-level)
        pPr.NumberingProperties = new NumberingProperties
        {
            NumberingLevelReference = new NumberingLevelReference { Val = 0 },
            NumberingId = new NumberingId { Val = 1 }
        };

        // Sub-level item (indented bullet/number)
        // pPr.NumberingProperties = new NumberingProperties
        // {
        //     NumberingLevelReference = new NumberingLevelReference { Val = 1 },
        //     NumberingId = new NumberingId { Val = 1 }
        // };

        // Remove numbering inherited from style
        // pPr.NumberingProperties = new NumberingProperties
        // {
        //     NumberingId = new NumberingId { Val = 0 }   // 0 = no numbering
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 11. Bidirectional (w:bidi, w:textDirection)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the paragraph as right-to-left (for Arabic/Hebrew text).
    /// <para>
    /// <b>BiDi (w:bidi):</b> When set, the paragraph direction is right-to-left.
    /// This affects: text flow direction, default alignment (right becomes default),
    /// indentation sides (left/right swap meaning), tab stop behavior.
    /// </para>
    /// <para>
    /// <b>TextDirection (w:textDirection):</b> Controls text flow direction within
    /// the paragraph's text area. Values include LrTb (left-to-right, top-to-bottom,
    /// default), TbRl (top-to-bottom, right-to-left — vertical CJK), BtLr
    /// (bottom-to-top, left-to-right — rotated).
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> For RTL paragraphs, also set Justification to Right
    /// (which visually aligns to the RIGHT = start edge in RTL context).
    /// </para>
    /// </summary>
    public static void ApplyBidirectional(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Set paragraph as right-to-left
        pPr.BiDi = new BiDi();

        // Also set right-alignment (the "start" edge for RTL)
        pPr.Justification = new Justification { Val = JustificationValues.Right };

        // Text direction for vertical CJK layout
        // pPr.TextDirection = new TextDirection
        // {
        //     Val = TextDirectionValues.TopToBottomRightToLeft  // Vertical CJK
        // };

        // Text direction for rotated layout
        // pPr.TextDirection = new TextDirection
        // {
        //     Val = TextDirectionValues.BottomToTopLeftToRight  // 90° rotation
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 12. Contextual Spacing (w:contextualSpacing)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Suppresses Before/After spacing between consecutive paragraphs that
    /// share the same paragraph style.
    /// <para>
    /// <b>Use case:</b> List items. When multiple "List Paragraph" items follow each other,
    /// contextual spacing removes the gap between them while preserving spacing when
    /// the list meets a different style (e.g., body text).
    /// </para>
    /// <para>
    /// <b>How it works:</b> When two adjacent paragraphs have the same ParagraphStyleId
    /// AND both have ContextualSpacing set, the Before spacing of the second paragraph
    /// and the After spacing of the first paragraph are suppressed (set to 0).
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Both paragraphs must have the same style AND contextual spacing
    /// enabled. If only one has it, the spacing is NOT suppressed.
    /// </para>
    /// </summary>
    public static void ApplyContextualSpacing(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        pPr.ContextualSpacing = new ContextualSpacing();

        // Disable (override a style that enables it):
        // pPr.ContextualSpacing = new ContextualSpacing { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 13. Mirror Indents (w:mirrorIndents)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Swaps left and right indentation on even/odd pages for book-style layouts.
    /// <para>
    /// <b>Use case:</b> In bound documents (books, reports), you want wider inner margins
    /// (the binding side). On odd pages the binding is on the left; on even pages it's
    /// on the right. MirrorIndents makes "Left" become "Inside" and "Right" become "Outside".
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> This property works in conjunction with the section's mirror margins
    /// setting (w:mirrorMargins in sectPr). If the section does not have mirror margins
    /// enabled, this property has limited effect.
    /// </para>
    /// </summary>
    public static void ApplyMirrorIndents(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        pPr.MirrorIndents = new MirrorIndents();
    }

    // ──────────────────────────────────────────────────────────────────
    // 14. Snap to Grid (w:snapToGrid)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Controls whether paragraph text aligns to the document grid.
    /// <para>
    /// <b>Document grid:</b> Defined in the section properties (w:docGrid), the grid
    /// specifies a fixed layout for character and line placement. This is primarily
    /// used in CJK documents where characters should align to a uniform grid.
    /// </para>
    /// <para>
    /// <b>Val = true (default):</b> Text snaps to the grid positions, ensuring uniform
    /// character spacing and line heights across the page.
    /// </para>
    /// <para>
    /// <b>Val = false:</b> Text ignores the document grid. Useful for paragraphs
    /// that contain only Western text in a CJK document, where grid alignment
    /// would create too much spacing.
    /// </para>
    /// </summary>
    public static void ApplySnapToGrid(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Disable grid snapping for this paragraph
        pPr.SnapToGrid = new SnapToGrid { Val = false };

        // Re-enable (explicit, same as default)
        // pPr.SnapToGrid = new SnapToGrid { Val = true };
    }

    // ──────────────────────────────────────────────────────────────────
    // 15. Suppress Auto-Hyphenation (w:suppressAutoHyphens)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Disables automatic hyphenation for this paragraph.
    /// <para>
    /// <b>Background:</b> When document-level auto-hyphenation is enabled
    /// (in document settings), Word breaks long words at line endings with hyphens.
    /// This property overrides that for specific paragraphs.
    /// </para>
    /// <para>
    /// <b>Use case:</b> Disable hyphenation for headings, proper nouns, code blocks,
    /// or any text where breaking words would be inappropriate.
    /// </para>
    /// </summary>
    public static void ApplySuppressAutoHyphens(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        pPr.SuppressAutoHyphens = new SuppressAutoHyphens();

        // Re-enable auto-hyphenation (override style that suppresses):
        // pPr.SuppressAutoHyphens = new SuppressAutoHyphens { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 16. Paragraph Style (w:pStyle)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies a named paragraph style.
    /// <para>
    /// <b>Val:</b> The style ID (not the display name). Built-in style IDs include:
    /// "Normal", "Heading1" through "Heading9", "Title", "Subtitle",
    /// "ListParagraph", "NoSpacing", "Quote", "IntenseQuote",
    /// "TOCHeading", "TOC1" through "TOC9", "Header", "Footer",
    /// "FootnoteText", "EndnoteText", "Caption", "Bibliography", etc.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Style IDs are locale-independent (always English) even in
    /// non-English installations of Word. The display name is localized, but the
    /// ID stays the same. "Heading1" is always "Heading1" regardless of language.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Custom styles use whatever ID was assigned at creation time.
    /// The ID may contain spaces or special characters. Always verify the actual
    /// style ID in styles.xml rather than guessing from the display name.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If the referenced style does not exist in styles.xml, Word
    /// falls back to the "Normal" style silently.
    /// </para>
    /// </summary>
    public static void ApplyParagraphStyle(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Apply Heading 1 style
        pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Heading1" };

        // Other common built-in style IDs:
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Normal" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Heading2" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Title" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Subtitle" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "ListParagraph" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "NoSpacing" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Quote" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "TOC1" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Header" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Footer" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "FootnoteText" };
        // pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Caption" };
    }

    // ──────────────────────────────────────────────────────────────────
    // 17. Frame Properties (w:framePr) — positioned paragraph
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Makes a paragraph into a positioned text frame (an anchored box of text).
    /// <para>
    /// <b>Use case:</b> Drop caps, pull quotes, sidebar text, positioned labels.
    /// FrameProperties turns a paragraph into a floating frame that can be positioned
    /// relative to the page, margin, or text.
    /// </para>
    /// <para>
    /// <b>Properties:</b>
    /// <list type="bullet">
    ///   <item><b>Width (w)</b> — Frame width in DXA. 0 = auto (fit content).</item>
    ///   <item><b>Height (h)</b> — Frame height in DXA. 0 = auto.</item>
    ///   <item><b>HeightRule (hRule)</b> — Auto, AtLeast, or Exact.</item>
    ///   <item><b>HorizontalPosition (x)</b> — Horizontal offset in DXA.</item>
    ///   <item><b>VerticalPosition (y)</b> — Vertical offset in DXA.</item>
    ///   <item><b>HorizontalSpace (hSpace)</b> — Horizontal clearance in DXA.</item>
    ///   <item><b>VerticalSpace (vSpace)</b> — Vertical clearance in DXA.</item>
    ///   <item><b>Anchor</b> — Vertical anchor: Text, Margin, or Page.</item>
    ///   <item><b>AnchorLock</b> — Prevents repositioning in Word UI.</item>
    ///   <item><b>DropCap</b> — DropCapLocationValues: None, Drop, Margin.</item>
    ///   <item><b>Lines</b> — Number of lines for a drop cap (typically 2–4).</item>
    ///   <item><b>Wrap</b> — Text wrapping: Auto, NotBeside, Around, Tight, Through, None.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Frame properties are a legacy positioning mechanism. For modern
    /// documents, consider using DrawingML text boxes instead. However, framePr is still
    /// the standard way to create drop caps in OOXML.
    /// </para>
    /// </summary>
    public static void ApplyFrameProperties(Paragraph para)
    {
        var pPr = para.GetOrCreateParagraphProperties();

        // Drop cap: 3-line dropped initial capital
        pPr.FrameProperties = new FrameProperties
        {
            DropCap = DropCapLocationValues.Drop,
            Lines = 3,                              // Span 3 lines of body text
            HorizontalSpace = "72",                 // 72 DXA = ~3.6pt clearance
            Wrap = TextWrappingValues.Around         // Body text wraps around
        };

        // Positioned frame (floating text box)
        // pPr.FrameProperties = new FrameProperties
        // {
        //     Width = "2880",                       // 2 inches wide
        //     Height = "1440",                      // 1 inch tall
        //     HeightRule = HeightRuleValues.AtLeast,
        //     X = "4320",                           // 3 inches from anchor
        //     Y = "1440",                           // 1 inch from anchor
        //     HorizontalSpace = "144",              // 0.1 inch horizontal clearance
        //     VerticalSpace = "72",                 // ~3.6pt vertical clearance
        //     VerticalAnchor = VerticalAnchorValues.Text,
        //     Wrap = TextWrappingValues.Around,
        //     AnchorLock = true
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 18. Fully Formatted Paragraph (combining multiple properties)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a fully formatted paragraph combining multiple paragraph properties.
    /// Demonstrates the correct construction order and element nesting.
    /// <para>
    /// <b>Structure:</b>
    /// <c>&lt;w:p&gt;&lt;w:pPr&gt;...&lt;/w:pPr&gt;&lt;w:r&gt;...&lt;/w:r&gt;&lt;/w:p&gt;</c>
    /// </para>
    /// <para>
    /// <b>Key principle:</b> ParagraphProperties must be the FIRST child of the paragraph.
    /// Runs, hyperlinks, and other content follow after.
    /// </para>
    /// </summary>
    public static Paragraph CreateFullyFormattedParagraph()
    {
        // Build ParagraphProperties first
        var pPr = new ParagraphProperties();

        // 1. Style (must be first child per schema)
        pPr.ParagraphStyleId = new ParagraphStyleId { Val = "Heading1" };

        // 2. Pagination
        pPr.KeepNext = new KeepNext();
        pPr.KeepLines = new KeepLines();

        // 3. Page break
        // pPr.PageBreakBefore = new PageBreakBefore();

        // 4. Widow/orphan control
        pPr.WidowControl = new WidowControl();

        // 5. Numbering
        // pPr.NumberingProperties = new NumberingProperties
        // {
        //     NumberingLevelReference = new NumberingLevelReference { Val = 0 },
        //     NumberingId = new NumberingId { Val = 1 }
        // };

        // 6. Borders
        pPr.ParagraphBorders = new ParagraphBorders(
            new BottomBorder
            {
                Val = BorderValues.Single,
                Size = 8,
                Space = 4,
                Color = "4472C4"
            }
        );

        // 7. Shading
        pPr.Shading = new Shading
        {
            Val = ShadingPatternValues.Clear,
            Fill = "F2F2F2"
        };

        // 8. Tab stops
        pPr.Tabs = new Tabs(
            new TabStop
            {
                Val = TabStopValues.Right,
                Position = 9360,                         // Right margin tab
                Leader = TabStopLeaderCharValues.Dot
            }
        );

        // 9. Suppress hyphenation
        pPr.SuppressAutoHyphens = new SuppressAutoHyphens();

        // 10. Spacing (before/after + line spacing)
        pPr.SpacingBetweenLines = new SpacingBetweenLines
        {
            Before = "240",                              // 12pt before
            After = "120",                               // 6pt after
            Line = "276",                                // 1.15x line spacing
            LineRule = LineSpacingRuleValues.Auto
        };

        // 11. Indentation
        pPr.Indentation = new Indentation
        {
            Left = "360",                                // 0.25 inch left indent
            FirstLine = "0"                              // No additional first-line indent
        };

        // 12. Justification
        pPr.Justification = new Justification { Val = JustificationValues.Both };

        // 13. Outline level (for TOC)
        pPr.OutlineLevel = new OutlineLevel { Val = 0 };

        // 14. Paragraph-level run properties (default formatting for runs in this para)
        // This sets the DEFAULT run formatting — individual runs can override.
        pPr.ParagraphMarkRunProperties = new ParagraphMarkRunProperties(
            new RunFonts { Ascii = "Georgia", HighAnsi = "Georgia" },
            new Bold(),
            new FontSize { Val = "28" },                 // 14pt
            new Color { Val = "2F5496" }
        );

        // Build the paragraph
        var para = new Paragraph();
        para.ParagraphProperties = pPr;

        // Add a run with text
        var run = new Run(
            new RunProperties(
                new RunFonts { Ascii = "Georgia", HighAnsi = "Georgia" },
                new Bold(),
                new FontSize { Val = "28" },
                new Color { Val = "2F5496" }
            ),
            new Text("Chapter 1: Introduction") { Space = SpaceProcessingModeValues.Preserve }
        );
        para.AppendChild(run);

        return para;
    }

    // ──────────────────────────────────────────────────────────────────
    // 19. BuildParagraphProperties helper — recommended property order
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Helper that constructs ParagraphProperties with elements in the correct schema order.
    /// <para>
    /// <b>OOXML schema order for w:pPr children (ISO 29500-1, section 17.3.1.26):</b>
    /// <list type="number">
    ///   <item>w:pStyle — Paragraph style reference</item>
    ///   <item>w:keepNext — Keep with next paragraph</item>
    ///   <item>w:keepLines — Keep lines together</item>
    ///   <item>w:pageBreakBefore — Page break before</item>
    ///   <item>w:framePr — Frame/text-box properties</item>
    ///   <item>w:widowControl — Widow/orphan control</item>
    ///   <item>w:numPr — Numbering properties</item>
    ///   <item>w:suppressLineNumbers — Suppress line numbers</item>
    ///   <item>w:pBdr — Paragraph borders</item>
    ///   <item>w:shd — Shading</item>
    ///   <item>w:tabs — Tab stops</item>
    ///   <item>w:suppressAutoHyphens — Suppress auto-hyphenation</item>
    ///   <item>w:kinsoku — CJK line-breaking rules</item>
    ///   <item>w:wordWrap — Allow word-level wrapping (CJK)</item>
    ///   <item>w:overflowPunct — Allow overflow punctuation (CJK)</item>
    ///   <item>w:topLinePunct — Top-line punctuation compression (CJK)</item>
    ///   <item>w:autoSpaceDE — Auto-space between CJK and Western text</item>
    ///   <item>w:autoSpaceDN — Auto-space between CJK text and numbers</item>
    ///   <item>w:bidi — Bidirectional (RTL paragraph)</item>
    ///   <item>w:adjustRightInd — Auto-adjust right indent for grid</item>
    ///   <item>w:snapToGrid — Snap to document grid</item>
    ///   <item>w:spacing — Line and paragraph spacing</item>
    ///   <item>w:ind — Indentation</item>
    ///   <item>w:contextualSpacing — Contextual spacing</item>
    ///   <item>w:mirrorIndents — Mirror indents for odd/even pages</item>
    ///   <item>w:suppressOverlap — Suppress frame overlap</item>
    ///   <item>w:jc — Justification (alignment)</item>
    ///   <item>w:textDirection — Text direction</item>
    ///   <item>w:textAlignment — Text vertical alignment within line</item>
    ///   <item>w:textboxTightWrap — Text box tight wrap</item>
    ///   <item>w:outlineLvl — Outline level</item>
    ///   <item>w:divId — HTML div ID</item>
    ///   <item>w:cnfStyle — Conditional formatting style</item>
    ///   <item>w:rPr — Paragraph mark run properties</item>
    ///   <item>w:sectPr — Section properties (last pPr in section)</item>
    ///   <item>w:pPrChange — Revision tracking for paragraph properties</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Like RunProperties, when using strongly-typed SDK properties
    /// (e.g., <c>pPr.Justification = new Justification { ... }</c>), the SDK handles
    /// serialization order automatically. If using <c>AppendChild()</c>, you must
    /// maintain the schema order yourself.
    /// </para>
    /// </summary>
    /// <param name="styleId">Paragraph style ID. Null to skip.</param>
    /// <param name="justification">Alignment. Null to skip.</param>
    /// <param name="spacingBeforePt">Space before in points. Null to skip.</param>
    /// <param name="spacingAfterPt">Space after in points. Null to skip.</param>
    /// <param name="lineSpacingMultiplier">Line spacing multiplier (e.g., 1.0, 1.15, 1.5, 2.0).
    /// Null to skip. Only applies Auto line rule.</param>
    /// <param name="leftIndentDxa">Left indent in DXA. Null to skip.</param>
    /// <param name="firstLineIndentDxa">First line indent in DXA. Null to skip.
    /// Use negative value for hanging indent (will be set as Hanging).</param>
    /// <returns>A well-ordered ParagraphProperties element.</returns>
    public static ParagraphProperties BuildParagraphProperties(
        string? styleId = null,
        JustificationValues? justification = null,
        double? spacingBeforePt = null,
        double? spacingAfterPt = null,
        double? lineSpacingMultiplier = null,
        int? leftIndentDxa = null,
        int? firstLineIndentDxa = null)
    {
        var pPr = new ParagraphProperties();

        // Style reference (schema position 1)
        if (styleId is not null)
        {
            pPr.ParagraphStyleId = new ParagraphStyleId { Val = styleId };
        }

        // Spacing (schema position 22) — combines para spacing and line spacing
        if (spacingBeforePt is not null || spacingAfterPt is not null || lineSpacingMultiplier is not null)
        {
            var spacing = new SpacingBetweenLines();

            if (spacingBeforePt is not null)
            {
                // Points to DXA: 1pt = 20 DXA
                spacing.Before = ((int)(spacingBeforePt.Value * 20)).ToString();
            }

            if (spacingAfterPt is not null)
            {
                spacing.After = ((int)(spacingAfterPt.Value * 20)).ToString();
            }

            if (lineSpacingMultiplier is not null)
            {
                // Auto mode: multiplier × 240 = value
                spacing.Line = ((int)(lineSpacingMultiplier.Value * 240)).ToString();
                spacing.LineRule = LineSpacingRuleValues.Auto;
            }

            pPr.SpacingBetweenLines = spacing;
        }

        // Indentation (schema position 23)
        if (leftIndentDxa is not null || firstLineIndentDxa is not null)
        {
            var ind = new Indentation();

            if (leftIndentDxa is not null)
            {
                ind.Left = leftIndentDxa.Value.ToString();
            }

            if (firstLineIndentDxa is not null)
            {
                if (firstLineIndentDxa.Value >= 0)
                {
                    ind.FirstLine = firstLineIndentDxa.Value.ToString();
                }
                else
                {
                    // Negative value → hanging indent (positive DXA stored in Hanging)
                    ind.Hanging = Math.Abs(firstLineIndentDxa.Value).ToString();
                }
            }

            pPr.Indentation = ind;
        }

        // Justification (schema position 26)
        if (justification is not null)
        {
            pPr.Justification = new Justification { Val = justification };
        }

        return pPr;
    }

    // ──────────────────────────────────────────────────────────────────
    // Internal helper: get or create ParagraphProperties
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Gets the existing ParagraphProperties or creates and attaches a new one.
    /// Ensures ParagraphProperties is always the first child of the paragraph.
    /// </summary>
    private static ParagraphProperties GetOrCreateParagraphProperties(this Paragraph para)
    {
        if (para.ParagraphProperties is not null)
            return para.ParagraphProperties;

        var pPr = new ParagraphProperties();
        para.ParagraphProperties = pPr;
        return pPr;
    }
}
