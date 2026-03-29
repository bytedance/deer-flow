using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Exhaustive reference for every RunProperties (w:rPr) child element in OpenXML.
/// Each method demonstrates one formatting category with full XML doc comments,
/// unit explanations, and gotchas. All code compiles against DocumentFormat.OpenXml 3.5.1.
/// </summary>
public static class CharacterFormattingSamples
{
    // ──────────────────────────────────────────────────────────────────
    // 1. Font Family (w:rFonts)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the font family on a run using all four font slots defined in OOXML.
    /// <para>
    /// <b>The four font slots:</b>
    /// <list type="bullet">
    ///   <item><b>Ascii</b> — Used for characters in the Basic Latin range (U+0000–U+007F).
    ///     This is the primary slot for English text.</item>
    ///   <item><b>HighAnsi</b> — Used for characters above U+007F that are NOT East Asian
    ///     and NOT Complex Script. Covers Latin Extended, Greek, Cyrillic, etc.
    ///     Typically set to the same value as Ascii.</item>
    ///   <item><b>EastAsia</b> — Used for CJK Unified Ideographs (U+4E00–U+9FFF),
    ///     Hiragana, Katakana, Hangul, CJK Compatibility, etc.
    ///     Set this for Chinese / Japanese / Korean content.</item>
    ///   <item><b>ComplexScript</b> — Used for Complex Script (BiDi) ranges:
    ///     Arabic (U+0600–U+06FF), Hebrew (U+0590–U+05FF), Thai, Devanagari,
    ///     and other right-to-left or complex-shaping scripts.</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If HighAnsi is not set, Word may fall back to a different font
    /// for characters like accented Latin (e.g., "e" uses Ascii, "e-acute" uses HighAnsi).
    /// Always set both Ascii and HighAnsi together for consistent Western text rendering.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> RunFonts also supports a <c>Hint</c> attribute
    /// (<see cref="FontTypeHintValues"/>) that tells Word which slot to prefer when a
    /// character could belong to multiple ranges. Values: Default, EastAsia, ComplexScript.
    /// </para>
    /// </summary>
    public static void ApplyFontFamily(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        rPr.RunFonts = new RunFonts
        {
            // Basic Latin characters (U+0000–U+007F)
            Ascii = "Calibri",

            // Non-CJK, non-complex characters above U+007F (Latin Extended, Greek, Cyrillic)
            HighAnsi = "Calibri",

            // CJK Ideographs, Hiragana, Katakana, Hangul
            EastAsia = "SimSun",

            // Arabic, Hebrew, Thai, Devanagari and other complex scripts
            ComplexScript = "Arial",

            // Hint tells Word which font slot to prefer for ambiguous characters.
            // FontTypeHintValues.EastAsia makes Word prefer the EastAsia slot.
            Hint = FontTypeHintValues.EastAsia
        };
    }

    // ──────────────────────────────────────────────────────────────────
    // 2. Font Size (w:sz, w:szCs)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the font size on a run.
    /// <para>
    /// <b>Unit:</b> w:sz is in <b>half-points</b>. 12pt = 24 half-points, 10.5pt = 21 half-points.
    /// </para>
    /// <para>
    /// <b>w:szCs</b> (FontSizeComplexScript) controls the size for Complex Script text
    /// (Arabic, Hebrew, etc.). It must be set separately — it does NOT inherit from w:sz.
    /// If you only set w:sz, Arabic/Hebrew text may render at a different size.
    /// </para>
    /// </summary>
    /// <param name="run">The run to modify.</param>
    /// <param name="points">Size in typographic points (e.g., 12.0 for 12pt).</param>
    public static void ApplyFontSize(Run run, double points)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Convert points to half-points: 12pt → "24"
        var halfPoints = ((int)(points * 2)).ToString();

        // w:sz — size for Latin / East Asian text
        rPr.FontSize = new FontSize { Val = halfPoints };

        // w:szCs — size for Complex Script text (Arabic, Hebrew, Thai, etc.)
        // Must be set independently; does NOT inherit from w:sz.
        rPr.FontSizeComplexScript = new FontSizeComplexScript { Val = halfPoints };
    }

    // ──────────────────────────────────────────────────────────────────
    // 3. Bold and Italic (w:b, w:bCs, w:i, w:iCs)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies bold and italic formatting to a run.
    /// <para>
    /// <b>Complex Script variants:</b> w:bCs and w:iCs control bold/italic for Complex
    /// Script text (Arabic, Hebrew). They must be set independently.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> <c>Bold</c> with no <c>Val</c> attribute means "true".
    /// To explicitly disable bold (override a style), set <c>Val = false</c>.
    /// An absent element means "inherit from style".
    /// </para>
    /// </summary>
    public static void ApplyBoldItalic(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Bold for Latin / East Asian text
        // <w:b/> (no val) is equivalent to <w:b w:val="true"/>
        rPr.Bold = new Bold();

        // Bold for Complex Script (Arabic, Hebrew, etc.)
        rPr.BoldComplexScript = new BoldComplexScript();

        // Italic for Latin / East Asian text
        rPr.Italic = new Italic();

        // Italic for Complex Script
        rPr.ItalicComplexScript = new ItalicComplexScript();

        // To DISABLE bold (e.g., override a bold style), explicitly set Val = false:
        // rPr.Bold = new Bold { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 4. Underline (w:u) — ALL UnderlineValues
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Demonstrates every underline style available in OOXML.
    /// <para>
    /// <b>Underline color:</b> By default, the underline color matches the text color.
    /// Override with <c>Color</c> (hex) and/or <c>ThemeColor</c>.
    /// </para>
    /// <para>
    /// <b>All 18 styles:</b> Single, Words, Double, Thick, Dotted, DottedHeavy,
    /// Dash, DashedHeavy, DashLong, DashLongHeavy, DotDash, DashDotHeavy,
    /// DotDotDash, DashDotDotHeavy, Wave, WavyHeavy, WavyDouble, None.
    /// </para>
    /// </summary>
    public static void ApplyAllUnderlineStyles(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // ── Standard underlines ──
        // Single: standard single underline (most common)
        rPr.Underline = new Underline { Val = UnderlineValues.Single };

        // Words: underlines words only, not spaces
        // rPr.Underline = new Underline { Val = UnderlineValues.Words };

        // Double: two parallel lines
        // rPr.Underline = new Underline { Val = UnderlineValues.Double };

        // Thick: single thick line
        // rPr.Underline = new Underline { Val = UnderlineValues.Thick };

        // ── Dotted variants ──
        // Dotted: dots
        // rPr.Underline = new Underline { Val = UnderlineValues.Dotted };

        // DottedHeavy: thick dots
        // rPr.Underline = new Underline { Val = UnderlineValues.DottedHeavy };

        // ── Dash variants ──
        // Dash: short dashes
        // rPr.Underline = new Underline { Val = UnderlineValues.Dash };

        // DashedHeavy: thick short dashes
        // rPr.Underline = new Underline { Val = UnderlineValues.DashedHeavy };

        // DashLong: long dashes
        // rPr.Underline = new Underline { Val = UnderlineValues.DashLong };

        // DashLongHeavy: thick long dashes
        // rPr.Underline = new Underline { Val = UnderlineValues.DashLongHeavy };

        // ── Dash-dot combinations ──
        // DotDash: alternating dot-dash (._._.)
        // rPr.Underline = new Underline { Val = UnderlineValues.DotDash };

        // DashDotHeavy: thick dot-dash
        // rPr.Underline = new Underline { Val = UnderlineValues.DashDotHeavy };

        // DotDotDash: dot-dot-dash (.._.._)
        // rPr.Underline = new Underline { Val = UnderlineValues.DotDotDash };

        // DashDotDotHeavy: thick dot-dot-dash
        // rPr.Underline = new Underline { Val = UnderlineValues.DashDotDotHeavy };

        // ── Wave variants ──
        // Wave: wavy line
        // rPr.Underline = new Underline { Val = UnderlineValues.Wave };

        // WavyHeavy: thick wavy line
        // rPr.Underline = new Underline { Val = UnderlineValues.WavyHeavy };

        // WavyDouble: double wavy line
        // rPr.Underline = new Underline { Val = UnderlineValues.WavyDouble };

        // ── Remove underline ──
        // None: explicitly remove underline (override style)
        // rPr.Underline = new Underline { Val = UnderlineValues.None };

        // ── Underline with custom color ──
        // rPr.Underline = new Underline
        // {
        //     Val = UnderlineValues.Single,
        //     Color = "FF0000",        // Red underline, independent of text color
        //     ThemeColor = ThemeColorValues.Accent1  // Or use theme color
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 5. Text Color (w:color)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the text color on a run using hex value and/or theme colors.
    /// <para>
    /// <b>Val:</b> 6-digit hex RGB string WITHOUT the "#" prefix (e.g., "FF0000" for red).
    /// The special value "auto" means the application decides (usually black).
    /// </para>
    /// <para>
    /// <b>ThemeColor:</b> References a theme color slot. When set alongside Val, the
    /// theme color takes precedence in theme-aware applications, but Val is the fallback.
    /// </para>
    /// <para>
    /// <b>ThemeShade:</b> Darkens the theme color. Value is a 2-digit hex string (00–FF).
    /// 00 = no change, FF = fully darkened. Applied as a multiplier.
    /// </para>
    /// <para>
    /// <b>ThemeTint:</b> Lightens the theme color. Value is a 2-digit hex string (00–FF).
    /// 00 = no change, FF = fully lightened (white). Applied as a multiplier.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> ThemeShade and ThemeTint are mutually exclusive — only one should
    /// be set. If both are present, behavior is undefined.
    /// </para>
    /// </summary>
    public static void ApplyColor(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Simple hex color (no theme)
        rPr.Color = new Color { Val = "FF0000" }; // Red

        // Theme-based color with fallback hex value
        rPr.Color = new Color
        {
            Val = "2F5496",                           // Fallback hex for non-theme-aware renderers
            ThemeColor = ThemeColorValues.Accent1,    // Theme color slot
            ThemeTint = "99"                          // Lighten: 99 hex → ~60% tint
        };

        // Theme color darkened
        rPr.Color = new Color
        {
            Val = "1F3864",
            ThemeColor = ThemeColorValues.Accent1,
            ThemeShade = "BF"                         // Darken: BF hex → ~75% shade
        };

        // Auto color (application-determined, typically black on white)
        rPr.Color = new Color { Val = "auto" };
    }

    // ──────────────────────────────────────────────────────────────────
    // 6. Highlight (w:highlight)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies text highlighting (the "marker pen" effect in Word's UI).
    /// <para>
    /// <b>All HighlightColorValues:</b> Yellow, Green, Cyan, Magenta, Blue, Red,
    /// DarkBlue, DarkCyan, DarkGreen, DarkMagenta, DarkRed, DarkYellow,
    /// DarkGray, LightGray, Black, White, None.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Highlighting is limited to the 17 preset colors above.
    /// For arbitrary background colors, use <see cref="ApplyShading"/> on RunProperties
    /// instead — it supports any hex color.
    /// </para>
    /// </summary>
    public static void ApplyHighlight(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Standard yellow highlight (most common for "tracked" or "review" marks)
        rPr.Highlight = new Highlight { Val = HighlightColorValues.Yellow };

        // All available highlight colors for reference:
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Green };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Cyan };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Magenta };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Blue };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Red };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkBlue };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkCyan };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkGreen };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkMagenta };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkRed };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkYellow };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.DarkGray };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.LightGray };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Black };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.White };
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.None };  // Remove
    }

    // ──────────────────────────────────────────────────────────────────
    // 7. Strikethrough (w:strike, w:dstrike)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies strikethrough or double-strikethrough formatting.
    /// <para>
    /// <b>Gotcha:</b> w:strike and w:dstrike are mutually exclusive.
    /// If both are present, behavior is undefined (Word typically uses the last one set).
    /// </para>
    /// </summary>
    public static void ApplyStrikethrough(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Single strikethrough: a single horizontal line through the text
        rPr.Strike = new Strike(); // No Val = true

        // Double strikethrough: two horizontal lines through the text
        // rPr.DoubleStrike = new DoubleStrike();

        // To explicitly disable (override a style that has strikethrough):
        // rPr.Strike = new Strike { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 8. Superscript / Subscript (w:vertAlign)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies superscript or subscript vertical alignment.
    /// <para>
    /// <b>Values:</b>
    /// <list type="bullet">
    ///   <item><b>Superscript</b> — raised text, reduced size (e.g., x²)</item>
    ///   <item><b>Subscript</b> — lowered text, reduced size (e.g., H₂O)</item>
    ///   <item><b>Baseline</b> — normal position (use to override style)</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> This is NOT the same as <see cref="ApplyPosition"/>.
    /// VerticalTextAlignment changes both position AND size (like Word's superscript button).
    /// Position (w:position) only shifts the baseline without changing font size.
    /// </para>
    /// </summary>
    public static void ApplySuperSubscript(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Superscript (raised + smaller font)
        rPr.VerticalTextAlignment = new VerticalTextAlignment
        {
            Val = VerticalPositionValues.Superscript
        };

        // Subscript (lowered + smaller font)
        // rPr.VerticalTextAlignment = new VerticalTextAlignment
        // {
        //     Val = VerticalPositionValues.Subscript
        // };

        // Baseline — explicitly reset to normal (override a style)
        // rPr.VerticalTextAlignment = new VerticalTextAlignment
        // {
        //     Val = VerticalPositionValues.Baseline
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 9. Caps / Small Caps (w:caps, w:smallCaps)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies ALL CAPS or Small Caps display formatting.
    /// <para>
    /// <b>Caps (w:caps):</b> Displays all characters as uppercase. The underlying text
    /// is NOT modified — it remains lowercase in the XML. This is a display-only transform.
    /// </para>
    /// <para>
    /// <b>SmallCaps (w:smallCaps):</b> Displays lowercase letters as smaller uppercase
    /// glyphs. Original uppercase letters remain full size. Common in legal and academic
    /// documents for author names and section references.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> w:caps and w:smallCaps are mutually exclusive.
    /// If both are present, w:caps wins.
    /// </para>
    /// </summary>
    public static void ApplyCapsSmallCaps(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // ALL CAPS display (text stored as-is, displayed uppercase)
        rPr.Caps = new Caps();

        // Small Caps display (lowercase → small uppercase glyphs)
        // rPr.SmallCaps = new SmallCaps();

        // Disable (override a style):
        // rPr.Caps = new Caps { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 10. Character Spacing (w:spacing)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Adjusts the spacing between characters (tracking / character spacing).
    /// <para>
    /// <b>Unit:</b> Value is in <b>twips</b> (1/20 of a point).
    /// Positive values = expanded (letters spread apart).
    /// Negative values = condensed (letters squeezed together).
    /// </para>
    /// <para>
    /// Examples: 20 twips = 1pt expanded, -10 twips = 0.5pt condensed,
    /// 40 twips = 2pt expanded.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> This is NOT the same as kerning (w:kern).
    /// Spacing applies a uniform offset between ALL characters.
    /// Kerning adjusts spacing between specific character PAIRS based on font metrics.
    /// </para>
    /// </summary>
    public static void ApplyCharacterSpacing(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Expanded by 1pt (20 twips)
        rPr.Spacing = new Spacing { Val = 20 };

        // Condensed by 0.5pt (-10 twips)
        // rPr.Spacing = new Spacing { Val = -10 };
    }

    // ──────────────────────────────────────────────────────────────────
    // 11. Position — raised/lowered baseline (w:position)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Raises or lowers the text position relative to the baseline.
    /// <para>
    /// <b>Unit:</b> Value is in <b>half-points</b>.
    /// Positive values = raised above baseline.
    /// Negative values = lowered below baseline.
    /// </para>
    /// <para>
    /// Examples: 6 half-points = 3pt raised, -4 half-points = 2pt lowered.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Unlike <see cref="ApplySuperSubscript"/>, Position does NOT change
    /// the font size. It only shifts the vertical position. Use this for fine-tuning
    /// baseline alignment (e.g., aligning inline images with text).
    /// </para>
    /// </summary>
    public static void ApplyPosition(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Raise text by 3pt (6 half-points)
        rPr.Position = new Position { Val = "6" };

        // Lower text by 2pt (-4 half-points)
        // rPr.Position = new Position { Val = "-4" };
    }

    // ──────────────────────────────────────────────────────────────────
    // 12. Run Shading (w:shd) — arbitrary background color on text
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies shading (background color) to a run.
    /// <para>
    /// <b>Use case:</b> When you need a background color that is NOT one of the 17
    /// preset highlight colors. Shading supports any hex RGB value.
    /// </para>
    /// <para>
    /// <b>Fill:</b> The background color (hex RGB, e.g., "FFFF00" for yellow).
    /// <b>Val:</b> The shading pattern. Use <c>ShadingPatternValues.Clear</c> for a
    /// solid background fill (most common). Other patterns overlay a foreground color.
    /// <b>Color:</b> The foreground/pattern color (only meaningful for non-Clear patterns).
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If Val is omitted or set to Nil, the shading may not render.
    /// Always set Val = Clear for solid backgrounds.
    /// </para>
    /// </summary>
    public static void ApplyShading(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Solid light-blue background
        rPr.Shading = new Shading
        {
            Val = ShadingPatternValues.Clear,    // Solid fill (no pattern)
            Fill = "DAEEF3",                     // Background color: light blue
            Color = "auto"                       // Foreground/pattern color: auto
        };

        // Theme-colored shading
        // rPr.Shading = new Shading
        // {
        //     Val = ShadingPatternValues.Clear,
        //     Fill = "auto",
        //     ThemeFill = ThemeColorValues.Accent1,
        //     ThemeFillTint = "33"               // Light tint of accent1
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 13. Text Border (w:bdr)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies a border around a run of text.
    /// <para>
    /// <b>Val:</b> Border style — Single, Double, Dotted, Dashed, DotDash, DotDotDash,
    /// Triple, ThickThinSmallGap, ThinThickSmallGap, ThickThinMediumGap, etc.
    /// Use <c>BorderValues.None</c> to remove.
    /// </para>
    /// <para>
    /// <b>Size:</b> Border width in <b>eighths of a point</b>. 4 = 0.5pt, 8 = 1pt, 12 = 1.5pt.
    /// Valid range: 2–96 (0.25pt–12pt).
    /// </para>
    /// <para>
    /// <b>Space:</b> Padding between text and border in <b>points</b>. Range: 0–31.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Run borders look like "boxed text" in Word. Adjacent runs with
    /// borders will have separate boxes — they do NOT merge into one box.
    /// </para>
    /// </summary>
    public static void ApplyBorder(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        rPr.Border = new Border
        {
            Val = BorderValues.Single,     // Single-line border
            Size = 4,                      // 0.5pt wide (4 eighths of a point)
            Space = 1,                     // 1pt padding between text and border
            Color = "4472C4"               // Border color (blue)
        };

        // Double border
        // rPr.Border = new Border
        // {
        //     Val = BorderValues.Double,
        //     Size = 4,
        //     Space = 1,
        //     Color = "auto"
        // };

        // Theme-colored border
        // rPr.Border = new Border
        // {
        //     Val = BorderValues.Single,
        //     Size = 8,
        //     Space = 1,
        //     Color = "auto",
        //     ThemeColor = ThemeColorValues.Accent1
        // };
    }

    // ──────────────────────────────────────────────────────────────────
    // 14. Run Style Reference (w:rStyle)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies a named character style to a run.
    /// <para>
    /// <b>Val:</b> The style ID (not the display name). For example, Word's built-in
    /// "Strong" style has ID "Strong", "Emphasis" has ID "Emphasis".
    /// Custom styles use their internal ID which may differ from the display name.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> The style must exist in the document's styles.xml (StyleDefinitionsPart).
    /// Referencing a non-existent style ID will not cause an error, but the formatting
    /// defined by that style will not be applied — Word silently ignores unknown style IDs.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> RunProperties set directly on the run override properties from the
    /// style (direct formatting wins). To inherit everything from the style, do not set
    /// additional properties on the RunProperties.
    /// </para>
    /// </summary>
    public static void ApplyRunStyle(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Reference the built-in "Strong" character style (bold)
        rPr.RunStyle = new RunStyle { Val = "Strong" };

        // Common built-in character style IDs:
        // "Strong"               — Bold
        // "Emphasis"             — Italic
        // "IntenseEmphasis"      — Bold + Italic + Accent color
        // "SubtleEmphasis"       — Italic + gray color
        // "BookTitle"            — Small caps + spacing
        // "IntenseReference"     — Bold + Small caps + Accent color + Underline
        // "SubtleReference"      — Small caps + Accent color
        // "Hyperlink"            — Blue + Underline
        // "FollowedHyperlink"    — Purple + Underline
        // "FootnoteReference"    — Superscript
    }

    // ──────────────────────────────────────────────────────────────────
    // 15. Hidden Text (w:vanish)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Makes text hidden (invisible in normal view, shown with dotted underline
    /// when "Show/Hide" is toggled in Word).
    /// <para>
    /// <b>Use cases:</b> Hidden text for internal notes, index entries, TOC field codes.
    /// Hidden text is NOT printed by default (controlled by Word's print settings).
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Hidden text still participates in page layout calculations in some
    /// modes. It can affect pagination when revealed.
    /// </para>
    /// </summary>
    public static void ApplyHiddenText(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Make text hidden
        rPr.Vanish = new Vanish();

        // Explicitly un-hide (override a style that hides text):
        // rPr.Vanish = new Vanish { Val = false };
    }

    // ──────────────────────────────────────────────────────────────────
    // 16. Right-to-Left / Complex Script (w:rtl, w:cs)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Marks a run as right-to-left and/or complex script.
    /// <para>
    /// <b>RightToLeft (w:rtl):</b> Indicates the run contains right-to-left text.
    /// This affects character ordering and cursor movement. Required for Arabic/Hebrew text.
    /// </para>
    /// <para>
    /// <b>ComplexScript (w:cs):</b> Marks the run as containing complex script text.
    /// When set, Word uses the ComplexScript variants of font properties:
    /// w:szCs instead of w:sz, w:bCs instead of w:b, rFonts@cs instead of rFonts@ascii.
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> For Arabic/Hebrew content, you typically need BOTH w:rtl and w:cs.
    /// Thai text needs w:cs but NOT w:rtl (Thai is left-to-right but uses complex shaping).
    /// </para>
    /// </summary>
    public static void ApplyRightToLeft(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Mark as right-to-left (for Arabic/Hebrew)
        rPr.RightToLeftText = new RightToLeftText();

        // Mark as complex script (use CS font/size/bold/italic variants)
        rPr.ComplexScript = new ComplexScript();
    }

    // ──────────────────────────────────────────────────────────────────
    // 17. Emphasis Mark (w:em) — CJK emphasis dots
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Applies emphasis marks (dots/circles above or below characters).
    /// Primarily used in CJK (Chinese, Japanese, Korean) typography.
    /// <para>
    /// <b>Values:</b>
    /// <list type="bullet">
    ///   <item><b>Dot</b> — small filled dot above each character (Japanese: 傍点)</item>
    ///   <item><b>Comma</b> — small comma-like mark above (used in some CJK styles)</item>
    ///   <item><b>Circle</b> — small open circle above each character</item>
    ///   <item><b>UnderDot</b> — small filled dot below each character (Chinese style)</item>
    ///   <item><b>None</b> — remove emphasis marks</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Emphasis marks are distinct from underlines. They appear as individual
    /// marks above/below each character, not as a continuous line.
    /// </para>
    /// </summary>
    public static void ApplyEmphasisMark(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Dot emphasis (most common in Japanese)
        rPr.Emphasis = new Emphasis { Val = EmphasisMarkValues.Dot };

        // Other emphasis mark styles:
        // rPr.Emphasis = new Emphasis { Val = EmphasisMarkValues.Comma };
        // rPr.Emphasis = new Emphasis { Val = EmphasisMarkValues.Circle };
        // rPr.Emphasis = new Emphasis { Val = EmphasisMarkValues.UnderDot };
        // rPr.Emphasis = new Emphasis { Val = EmphasisMarkValues.None };
    }

    // ──────────────────────────────────────────────────────────────────
    // 18. Kerning (w:kern)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets the kerning threshold for automatic font-based kerning.
    /// <para>
    /// <b>Unit:</b> Value is in <b>half-points</b>. Characters at or above this size
    /// will have kerning applied (the font's kern table adjusts spacing between
    /// specific character pairs, e.g., "AV", "To", "WA").
    /// </para>
    /// <para>
    /// <b>Common values:</b>
    /// <list type="bullet">
    ///   <item>0 — Disable kerning entirely</item>
    ///   <item>2 (1pt) — Kern all text (including body text)</item>
    ///   <item>28 (14pt) — Kern only headings (Word's typical default threshold)</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> Kerning only works if the font contains a kern table.
    /// Most professional fonts (Times New Roman, Calibri, Arial) include kern data.
    /// </para>
    /// </summary>
    public static void ApplyKerning(Run run)
    {
        var rPr = run.GetOrCreateRunProperties();

        // Kern text at 14pt and above (28 half-points)
        rPr.Kern = new Kern { Val = 28 };

        // Kern all text regardless of size (0 half-points is "no threshold"
        // but some renderers interpret 0 as "off". Use 1 or 2 to be safe.)
        // rPr.Kern = new Kern { Val = 2 };
    }

    // ──────────────────────────────────────────────────────────────────
    // 19. Fully Formatted Run (combining multiple properties)
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a fully formatted run combining multiple character properties.
    /// Demonstrates the correct way to build a run with RunProperties.
    /// <para>
    /// <b>Key principle:</b> Create RunProperties first, add all child elements,
    /// then set it on the run BEFORE adding text. The run's XML structure must be:
    /// <c>&lt;w:r&gt;&lt;w:rPr&gt;...&lt;/w:rPr&gt;&lt;w:t&gt;text&lt;/w:t&gt;&lt;/w:r&gt;</c>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> If you add RunProperties AFTER the Text element, it will appear
    /// after w:t in the XML, which is technically invalid OOXML ordering. Word tolerates
    /// it but some third-party parsers may not. Always add rPr first.
    /// </para>
    /// </summary>
    public static Run CreateFullyFormattedRun()
    {
        // Build RunProperties with all desired formatting
        var rPr = new RunProperties();

        // 1. Style reference (must be first child per schema order)
        rPr.RunStyle = new RunStyle { Val = "Strong" };

        // 2. Font family
        rPr.RunFonts = new RunFonts
        {
            Ascii = "Georgia",
            HighAnsi = "Georgia",
            EastAsia = "SimSun",
            ComplexScript = "Times New Roman"
        };

        // 3. Bold
        rPr.Bold = new Bold();
        rPr.BoldComplexScript = new BoldComplexScript();

        // 4. Italic
        rPr.Italic = new Italic();
        rPr.ItalicComplexScript = new ItalicComplexScript();

        // 5. Caps — omitted here (mutually exclusive with SmallCaps)
        // rPr.Caps = new Caps();

        // 6. SmallCaps
        rPr.SmallCaps = new SmallCaps();

        // 7. Strikethrough
        rPr.Strike = new Strike();

        // 8. Hidden — typically NOT combined with visible formatting
        // rPr.Vanish = new Vanish();

        // 9. Color
        rPr.Color = new Color { Val = "2F5496" };

        // 10. Font size
        rPr.FontSize = new FontSize { Val = "28" };               // 14pt
        rPr.FontSizeComplexScript = new FontSizeComplexScript { Val = "28" };

        // 11. Underline
        rPr.Underline = new Underline { Val = UnderlineValues.Single };

        // 12. Shading (text background)
        rPr.Shading = new Shading
        {
            Val = ShadingPatternValues.Clear,
            Fill = "FFFFCC"
        };

        // 13. Highlight (preset colors only)
        // rPr.Highlight = new Highlight { Val = HighlightColorValues.Yellow };

        // 14. Character spacing
        rPr.Spacing = new Spacing { Val = 10 };                   // 0.5pt expanded

        // 15. Kerning threshold
        rPr.Kern = new Kern { Val = 2 };

        // 16. Position (raised/lowered)
        // rPr.Position = new Position { Val = "4" };              // 2pt raised

        // 17. Vertical alignment (super/subscript)
        // rPr.VerticalTextAlignment = new VerticalTextAlignment
        // {
        //     Val = VerticalPositionValues.Superscript
        // };

        // 18. Border
        rPr.Border = new Border
        {
            Val = BorderValues.Single,
            Size = 4,
            Space = 1,
            Color = "auto"
        };

        // Build the Run: RunProperties MUST come before Text content
        var run = new Run();
        run.RunProperties = rPr;

        // Add text content
        // PreserveSpace is needed when text has leading/trailing spaces
        run.AppendChild(new Text("Fully formatted text")
        {
            Space = SpaceProcessingModeValues.Preserve
        });

        return run;
    }

    // ──────────────────────────────────────────────────────────────────
    // 20. BuildRunProperties helper — recommended property order
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Helper that constructs a RunProperties with elements in the correct schema order.
    /// <para>
    /// <b>OOXML schema order for w:rPr children (ISO 29500-1, section 17.3.2.28):</b>
    /// <list type="number">
    ///   <item>w:rStyle — Character style reference</item>
    ///   <item>w:rFonts — Font family</item>
    ///   <item>w:b — Bold</item>
    ///   <item>w:bCs — Bold Complex Script</item>
    ///   <item>w:i — Italic</item>
    ///   <item>w:iCs — Italic Complex Script</item>
    ///   <item>w:caps — All Caps</item>
    ///   <item>w:smallCaps — Small Caps</item>
    ///   <item>w:strike — Strikethrough</item>
    ///   <item>w:dstrike — Double Strikethrough</item>
    ///   <item>w:outline — Outline effect</item>
    ///   <item>w:shadow — Shadow effect</item>
    ///   <item>w:emboss — Emboss effect</item>
    ///   <item>w:imprint — Imprint/Engrave effect</item>
    ///   <item>w:noProof — Skip proofing</item>
    ///   <item>w:snapToGrid — Snap to document grid</item>
    ///   <item>w:vanish — Hidden text</item>
    ///   <item>w:webHidden — Hidden in web view</item>
    ///   <item>w:color — Text color</item>
    ///   <item>w:spacing — Character spacing</item>
    ///   <item>w:w — Character width scaling (%)</item>
    ///   <item>w:kern — Kerning threshold</item>
    ///   <item>w:position — Raised/lowered position</item>
    ///   <item>w:sz — Font size</item>
    ///   <item>w:szCs — Font size Complex Script</item>
    ///   <item>w:highlight — Highlight color</item>
    ///   <item>w:u — Underline</item>
    ///   <item>w:effect — Animation effect (deprecated)</item>
    ///   <item>w:bdr — Text border</item>
    ///   <item>w:shd — Shading</item>
    ///   <item>w:fitText — Fit text to width</item>
    ///   <item>w:vertAlign — Vertical alignment (super/subscript)</item>
    ///   <item>w:rtl — Right-to-left</item>
    ///   <item>w:cs — Complex Script</item>
    ///   <item>w:em — Emphasis mark</item>
    ///   <item>w:lang — Language</item>
    ///   <item>w:eastAsianLayout — East Asian typography</item>
    ///   <item>w:specVanish — Special vanish</item>
    ///   <item>w:oMath — Math formatting</item>
    ///   <item>w:rPrChange — Revision tracking for run properties</item>
    /// </list>
    /// </para>
    /// <para>
    /// <b>Gotcha:</b> When using the strongly-typed SDK (setting properties like
    /// <c>rPr.Bold = new Bold()</c>), the SDK handles ordering automatically when
    /// serializing. However, if you use <c>rPr.AppendChild()</c>, you must add
    /// elements in the correct order yourself, or call
    /// <c>rPr.SetElement()</c> which inserts at the correct position.
    /// </para>
    /// </summary>
    /// <param name="fontFamily">Font name for Ascii and HighAnsi slots. Null to skip.</param>
    /// <param name="sizePoints">Font size in points. Null to skip.</param>
    /// <param name="bold">True to apply bold, false to explicitly disable, null to inherit.</param>
    /// <param name="italic">True to apply italic, false to explicitly disable, null to inherit.</param>
    /// <param name="colorHex">Six-digit hex color (e.g., "FF0000"). Null to skip.</param>
    /// <param name="underline">Underline style. Null to skip.</param>
    /// <returns>A well-ordered RunProperties element ready to attach to a Run.</returns>
    public static RunProperties BuildRunProperties(
        string? fontFamily = null,
        double? sizePoints = null,
        bool? bold = null,
        bool? italic = null,
        string? colorHex = null,
        UnderlineValues? underline = null)
    {
        var rPr = new RunProperties();

        // Using the strongly-typed properties ensures the SDK serializes
        // child elements in the correct schema order automatically.

        if (fontFamily is not null)
        {
            rPr.RunFonts = new RunFonts
            {
                Ascii = fontFamily,
                HighAnsi = fontFamily
            };
        }

        if (bold == true)
        {
            rPr.Bold = new Bold();
            rPr.BoldComplexScript = new BoldComplexScript();
        }
        else if (bold == false)
        {
            rPr.Bold = new Bold { Val = false };
            rPr.BoldComplexScript = new BoldComplexScript { Val = false };
        }

        if (italic == true)
        {
            rPr.Italic = new Italic();
            rPr.ItalicComplexScript = new ItalicComplexScript();
        }
        else if (italic == false)
        {
            rPr.Italic = new Italic { Val = false };
            rPr.ItalicComplexScript = new ItalicComplexScript { Val = false };
        }

        if (colorHex is not null)
        {
            rPr.Color = new Color { Val = colorHex };
        }

        if (sizePoints is not null)
        {
            var halfPts = ((int)(sizePoints.Value * 2)).ToString();
            rPr.FontSize = new FontSize { Val = halfPts };
            rPr.FontSizeComplexScript = new FontSizeComplexScript { Val = halfPts };
        }

        if (underline is not null)
        {
            rPr.Underline = new Underline { Val = underline };
        }

        return rPr;
    }

    // ──────────────────────────────────────────────────────────────────
    // Internal helper: get or create RunProperties on a Run
    // ──────────────────────────────────────────────────────────────────

    /// <summary>
    /// Gets the existing RunProperties from a run or creates and attaches a new one.
    /// Ensures RunProperties is always the first child element of the run.
    /// </summary>
    private static RunProperties GetOrCreateRunProperties(this Run run)
    {
        if (run.RunProperties is not null)
            return run.RunProperties;

        var rPr = new RunProperties();
        run.RunProperties = rPr;
        return rPr;
    }
}
