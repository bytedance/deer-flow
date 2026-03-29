using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using MiniMaxAIDocx.Core.OpenXml;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Compilable reference examples for the OpenXML style system.
/// Demonstrates style creation, inheritance, CJK styles, academic formatting,
/// style import, and effective formatting resolution.
///
/// KEY CONCEPT — Style Inheritance Chain:
///   docDefaults → basedOn chain → style rPr/pPr → direct formatting (in paragraph/run)
///   Each level overrides only the properties it explicitly sets.
///   "StyleRunProperties" (rPr inside a style) vs "RunProperties" (rPr inside a run) are
///   different classes that produce the same XML element name but at different tree positions.
/// </summary>
public static class StyleSystemSamples
{
    // ────────────────────────────────────────────────────────────────────
    // 1. BASIC STYLES (Normal + Headings + Title + Subtitle)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates the core set of paragraph styles: Normal (default), Heading1–6, Title, Subtitle.
    /// Demonstrates the basedOn inheritance chain and outlineLevel for TOC integration.
    /// </summary>
    /// <remarks>
    /// Style inheritance for headings:
    ///   Normal (default paragraph style)
    ///     └─ Heading1 (basedOn: Normal, outlineLevel: 0)
    ///         └─ Heading2 (basedOn: Heading1? NO — basedOn: Normal, outlineLevel: 1)
    ///
    /// WARNING: Word's built-in headings all use basedOn="Normal", NOT a chain like
    /// Heading2→Heading1. This is because each heading level has completely different
    /// formatting. Using a chain would cause unwanted inheritance.
    ///
    /// XML produced for Heading1:
    /// <code>
    /// &lt;w:style w:type="paragraph" w:styleId="Heading1"&gt;
    ///   &lt;w:name w:val="heading 1"/&gt;
    ///   &lt;w:basedOn w:val="Normal"/&gt;
    ///   &lt;w:next w:val="Normal"/&gt;
    ///   &lt;w:link w:val="Heading1Char"/&gt;
    ///   &lt;w:uiPriority w:val="9"/&gt;
    ///   &lt;w:qFormat/&gt;
    ///   &lt;w:pPr&gt;
    ///     &lt;w:keepNext/&gt;
    ///     &lt;w:keepLines/&gt;
    ///     &lt;w:spacing w:before="240"/&gt;
    ///     &lt;w:outlineLvl w:val="0"/&gt;
    ///   &lt;/w:pPr&gt;
    ///   &lt;w:rPr&gt;
    ///     &lt;w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi"/&gt;
    ///     &lt;w:color w:val="2F5496" w:themeColor="accent1" w:themeShade="BF"/&gt;
    ///     &lt;w:sz w:val="32"/&gt;
    ///   &lt;/w:rPr&gt;
    /// &lt;/w:style&gt;
    /// </code>
    /// </remarks>
    public static void CreateBasicStyles(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();
        var styles = stylesPart.Styles;

        // ── "Normal" — the default paragraph style ──
        // IMPORTANT: Exactly one paragraph style should have Default="1".
        // All other paragraph styles inherit from Normal unless they specify a different basedOn.
        styles.Append(new Style(
            new StyleName { Val = "Normal" },
            // UiPriority controls the sort order in Word's Styles pane
            new UIPriority { Val = 0 },
            // qFormat makes the style appear in the Quick Styles gallery
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines
                {
                    After = "160",             // 8pt after paragraph (in DXA twentieths-of-a-point)
                    Line = "259",              // ~1.08 line spacing (in 240ths for auto rule)
                    LineRule = LineSpacingRuleValues.Auto
                }
            ),
            new StyleRunProperties(
                // IMPORTANT: StyleRunProperties (w:rPr inside w:style) is different from
                // RunProperties (w:rPr inside w:r). They produce the same XML tag name
                // but are different C# classes. Using the wrong one will compile but
                // may place elements in the wrong location.
                new RunFonts
                {
                    Ascii = "Calibri",
                    HighAnsi = "Calibri",
                    EastAsia = "SimSun",
                    ComplexScript = "Arial"
                },
                new FontSize { Val = "22" },              // 11pt (in half-points)
                new FontSizeComplexScript { Val = "22" },
                new Languages { Val = "en-US", EastAsia = "zh-CN" }
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Normal",
            Default = true  // This is THE default paragraph style
        });

        // ── Heading styles 1–6 ──
        // Each heading has:
        //   - basedOn: Normal (inherit base formatting)
        //   - next: Normal (pressing Enter after heading returns to Normal)
        //   - outlineLvl: 0–5 (determines TOC level; outlineLvl 0 = TOC level 1)
        //   - keepNext + keepLines (prevent orphaned headings)
        //   - link to a character style for inline use

        var headingConfigs = new[]
        {
            // (StyleId, Name, SizePt, outlineLevel, Color, Bold, SpaceBefore)
            ("Heading1", "heading 1", 16.0, 0, "2F5496", true,  240),
            ("Heading2", "heading 2", 13.0, 1, "2F5496", true,  40),
            ("Heading3", "heading 3", 12.0, 2, "1F3864", true,  40),
            ("Heading4", "heading 4", 11.0, 3, "2F5496", true,  40),
            ("Heading5", "heading 5", 11.0, 4, "2F5496", false, 40),
            ("Heading6", "heading 6", 11.0, 5, "1F3864", false, 40),
        };

        foreach (var (id, name, sizePt, level, color, bold, spaceBefore) in headingConfigs)
        {
            var style = new Style
            {
                Type = StyleValues.Paragraph,
                StyleId = id
            };

            style.Append(new StyleName { Val = name });
            // basedOn: all headings inherit from Normal
            style.Append(new BasedOn { Val = "Normal" });
            // next: pressing Enter after this style creates a Normal paragraph
            style.Append(new NextParagraphStyle { Val = "Normal" });
            // link: connects this paragraph style to its character style counterpart
            style.Append(new LinkedStyle { Val = id + "Char" });
            // uiPriority 9 = high visibility in Styles pane
            style.Append(new UIPriority { Val = 9 });
            // qFormat = show in Quick Styles gallery on the Home ribbon
            style.Append(new PrimaryStyle());

            // Paragraph properties for headings
            var pPr = new StyleParagraphProperties(
                // keepNext: don't allow a page break between this heading and the next paragraph
                new KeepNext(),
                // keepLines: don't split this paragraph across pages
                new KeepLines(),
                new SpacingBetweenLines
                {
                    Before = spaceBefore.ToString(), // space before in DXA
                    After = "0"                      // no space after heading
                },
                // outlineLvl: 0-based; determines the heading's level in:
                //   - Table of Contents (TOC)
                //   - Navigation Pane
                //   - Document outline
                // IMPORTANT: outlineLvl 0 = "Level 1" in Word's UI
                new OutlineLevel { Val = level }
            );
            style.Append(pPr);

            // Run properties for the heading text appearance
            var rPr = new StyleRunProperties(
                new RunFonts
                {
                    // "majorHAnsi" theme font slot = the theme's heading font (e.g. Calibri Light)
                    AsciiTheme = ThemeFontValues.MajorHighAnsi,
                    HighAnsiTheme = ThemeFontValues.MajorHighAnsi,
                    EastAsiaTheme = ThemeFontValues.MajorEastAsia,
                    ComplexScriptTheme = ThemeFontValues.MajorBidi
                },
                new Color
                {
                    Val = color,
                    // themeColor + themeShade: if a theme is applied, Word uses these
                    // instead of the literal Val. The Val acts as a fallback.
                    ThemeColor = ThemeColorValues.Accent1,
                    ThemeShade = "BF"
                },
                // Font size in half-points
                new FontSize { Val = ((int)(sizePt * 2)).ToString() },
                new FontSizeComplexScript { Val = ((int)(sizePt * 2)).ToString() }
            );

            if (bold)
            {
                // IMPORTANT: For Bold in a style, just include the element with no Val.
                // <w:b/> means true. <w:b w:val="false"/> means explicitly NOT bold.
                rPr.Append(new Bold());
                rPr.Append(new BoldComplexScript());
            }

            style.Append(rPr);
            styles.Append(style);

            // ── Linked character style ──
            // A "linked" character style lets users apply heading formatting to
            // inline text without changing the paragraph style.
            // It must have the same rPr as the paragraph style.
            var charStyle = new Style
            {
                Type = StyleValues.Character,
                StyleId = id + "Char",
                CustomStyle = true
            };
            charStyle.Append(new StyleName { Val = name + " Char" });
            charStyle.Append(new BasedOn { Val = "DefaultParagraphFont" });
            charStyle.Append(new LinkedStyle { Val = id });
            charStyle.Append(new UIPriority { Val = 9 });
            charStyle.Append((StyleRunProperties)rPr.CloneNode(true));
            styles.Append(charStyle);
        }

        // ── "Title" style ──
        styles.Append(new Style(
            new StyleName { Val = "Title" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 10 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { After = "0", Line = "240", LineRule = LineSpacingRuleValues.Auto },
                new Justification { Val = JustificationValues.Center }
            ),
            new StyleRunProperties(
                new RunFonts
                {
                    AsciiTheme = ThemeFontValues.MajorHighAnsi,
                    HighAnsiTheme = ThemeFontValues.MajorHighAnsi,
                    EastAsiaTheme = ThemeFontValues.MajorEastAsia,
                    ComplexScriptTheme = ThemeFontValues.MajorBidi
                },
                new FontSize { Val = "56" },              // 28pt
                new FontSizeComplexScript { Val = "56" },
                // Spacing = character spacing expansion in DXA twentieths-of-a-point
                // Negative = condensed, Positive = expanded
                new Spacing { Val = -10 },                // slight condensing
                new Kern { Val = (UInt32Value)28U }       // kern at 28 half-pt (14pt) and above
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Title"
        });

        // ── "Subtitle" style ──
        styles.Append(new Style(
            new StyleName { Val = "Subtitle" },
            new BasedOn { Val = "Normal" },
            new NextParagraphStyle { Val = "Normal" },
            new UIPriority { Val = 11 },
            new PrimaryStyle(),
            new StyleParagraphProperties(
                new SpacingBetweenLines { After = "160" },
                new Justification { Val = JustificationValues.Center }
            ),
            new StyleRunProperties(
                new RunFonts
                {
                    EastAsiaTheme = ThemeFontValues.MinorEastAsia
                },
                new Color
                {
                    Val = "5A5A5A",
                    ThemeColor = ThemeColorValues.Text1,
                    ThemeTint = "A6"
                },
                new FontSize { Val = "24" },              // 12pt
                new FontSizeComplexScript { Val = "24" },
                new Spacing { Val = 15 }                  // slight expansion
            )
        )
        {
            Type = StyleValues.Paragraph,
            StyleId = "Subtitle"
        });

        styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 2. CHARACTER STYLE (bold + red, linked to paragraph style)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a character style "StrongAccent" that applies bold + red formatting.
    /// Also creates a linked paragraph style to show the link mechanism.
    /// </summary>
    /// <remarks>
    /// Character styles:
    ///   - Type = StyleValues.Character
    ///   - Only contain rPr (run properties), never pPr
    ///   - Applied via &lt;w:rPr&gt;&lt;w:rStyle w:val="StrongAccent"/&gt;&lt;/w:rPr&gt; on a Run
    ///   - Can be "linked" to a paragraph style: when the entire paragraph uses the para
    ///     style, Word shows the char style name; when only a run uses it, same formatting
    ///
    /// XML produced:
    /// <code>
    /// &lt;w:style w:type="character" w:styleId="StrongAccent"&gt;
    ///   &lt;w:name w:val="Strong Accent"/&gt;
    ///   &lt;w:basedOn w:val="DefaultParagraphFont"/&gt;
    ///   &lt;w:uiPriority w:val="22"/&gt;
    ///   &lt;w:qFormat/&gt;
    ///   &lt;w:rPr&gt;
    ///     &lt;w:b/&gt;
    ///     &lt;w:bCs/&gt;
    ///     &lt;w:color w:val="FF0000"/&gt;
    ///   &lt;/w:rPr&gt;
    /// &lt;/w:style&gt;
    /// </code>
    /// </remarks>
    public static void CreateCharacterStyle(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        // ── Character style ──
        var charStyle = new Style
        {
            Type = StyleValues.Character,
            StyleId = "StrongAccent",
            // CustomStyle = true means this is not a built-in Word style.
            // Built-in styles (like "Strong") have this as false/omitted.
            CustomStyle = true
        };

        charStyle.Append(new StyleName { Val = "Strong Accent" });
        // IMPORTANT: Character styles should be basedOn "DefaultParagraphFont"
        // (the implicit base for all character styles), NOT on another named style,
        // unless you specifically want to inherit from it.
        charStyle.Append(new BasedOn { Val = "DefaultParagraphFont" });
        charStyle.Append(new UIPriority { Val = 22 });
        charStyle.Append(new PrimaryStyle()); // show in Quick Styles gallery
        // Link to the paragraph style counterpart
        charStyle.Append(new LinkedStyle { Val = "StrongAccentPara" });

        charStyle.Append(new StyleRunProperties(
            new Bold(),
            new BoldComplexScript(),
            new Color { Val = "FF0000" },  // pure red; no # prefix in OpenXML
            new Underline { Val = UnderlineValues.None } // explicitly no underline
        ));

        stylesPart.Styles.Append(charStyle);

        // ── Linked paragraph style ──
        // When a paragraph style and character style are "linked", Word treats them
        // as two views of the same formatting. If a whole paragraph uses the para
        // style, Word displays it as the char style in the UI.
        var paraStyle = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "StrongAccentPara",
            CustomStyle = true
        };

        paraStyle.Append(new StyleName { Val = "Strong Accent Paragraph" });
        paraStyle.Append(new BasedOn { Val = "Normal" });
        paraStyle.Append(new LinkedStyle { Val = "StrongAccent" });
        paraStyle.Append(new UIPriority { Val = 22 });

        // The paragraph style carries the same rPr as the character style
        paraStyle.Append(new StyleRunProperties(
            new Bold(),
            new BoldComplexScript(),
            new Color { Val = "FF0000" }
        ));

        stylesPart.Styles.Append(paraStyle);
        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 3. TABLE STYLE (header row, banded rows)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a table style with conditional formatting for header row,
    /// banded (alternating) rows, and first column highlighting.
    /// </summary>
    /// <remarks>
    /// Table styles use "conditional formatting" (tblStylePr) to vary appearance
    /// by region. Each region type is identified by a TableStyleOverrideValues enum:
    ///   FirstRow, LastRow, FirstColumn, LastColumn,
    ///   Band1Vertical, Band2Vertical, Band1Horizontal, Band2Horizontal,
    ///   NorthEastCell, NorthWestCell, SouthEastCell, SouthWestCell
    ///
    /// The table must opt-in to conditional formatting via w:tblLook:
    /// <code>
    /// &lt;w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0"
    ///   w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/&gt;
    /// </code>
    /// </remarks>
    public static void CreateTableStyle(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        var tableStyle = new Style
        {
            Type = StyleValues.Table,
            StyleId = "CustomGrid",
            CustomStyle = true
        };

        tableStyle.Append(new StyleName { Val = "Custom Grid" });
        tableStyle.Append(new UIPriority { Val = 59 });
        // BasedOn "TableNormal" — the implicit base for all table styles
        tableStyle.Append(new BasedOn { Val = "TableNormal" });

        // ── Base table properties (apply to all cells by default) ──
        var baseTblPr = new StyleTableProperties(
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" },
                new LeftBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" },
                new RightBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" },
                new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Color = "BFBFBF" }
            ),
            // Default cell margins (in DXA)
            new TableCellMarginDefault(
                new TopMargin { Width = "0", Type = TableWidthUnitValues.Dxa },
                new StartMargin { Width = "108", Type = TableWidthUnitValues.Dxa }, // ~0.075 inch
                new BottomMargin { Width = "0", Type = TableWidthUnitValues.Dxa },
                new EndMargin { Width = "108", Type = TableWidthUnitValues.Dxa }
            )
        );
        tableStyle.Append(baseTblPr);

        // ── Header row override (firstRow) ──
        // Dark background, white bold text
        var firstRowStyle = new TableStyleProperties { Type = TableStyleOverrideValues.FirstRow };
        firstRowStyle.Append(new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center }
        ));
        firstRowStyle.Append(new RunPropertiesBaseStyle(
            new Bold(),
            new BoldComplexScript(),
            new Color { Val = "FFFFFF" },                // white text
            new FontSize { Val = "22" },
            new FontSizeComplexScript { Val = "22" }
        ));
        firstRowStyle.Append(new TableStyleConditionalFormattingTableCellProperties(
            new Shading
            {
                Val = ShadingPatternValues.Clear,
                Color = "auto",
                Fill = "4472C4"                          // accent blue background
            }
        ));
        tableStyle.Append(firstRowStyle);

        // ── Banded rows (Band1Horizontal = odd data rows) ──
        // Light gray background for visual distinction
        var band1Style = new TableStyleProperties { Type = TableStyleOverrideValues.Band1Horizontal };
        band1Style.Append(new TableStyleConditionalFormattingTableCellProperties(
            new Shading
            {
                Val = ShadingPatternValues.Clear,
                Color = "auto",
                Fill = "D9E2F3"                          // light blue-gray
            }
        ));
        tableStyle.Append(band1Style);
        // Band2Horizontal (even data rows) inherits the base style (no shading)

        // ── First column override ──
        var firstColStyle = new TableStyleProperties { Type = TableStyleOverrideValues.FirstColumn };
        firstColStyle.Append(new RunPropertiesBaseStyle(
            new Bold(),
            new BoldComplexScript()
        ));
        tableStyle.Append(firstColStyle);

        stylesPart.Styles.Append(tableStyle);
        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 4. LIST STYLE (paragraph style linked to numbering)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a paragraph style "ListBullet1" that is linked to a numbering definition.
    /// When this style is applied to a paragraph, the numbering automatically appears.
    /// </summary>
    /// <remarks>
    /// The link between a paragraph style and numbering works as follows:
    /// 1. An AbstractNum defines the list format (bullet/number, indent, etc.)
    /// 2. The AbstractNum can reference a styleLink to connect to a list style
    /// 3. The paragraph style's pPr contains numPr with numId + ilvl
    ///
    /// WARNING: The NumberingDefinitionsPart must exist and contain the referenced
    /// AbstractNum/NumberingInstance, or Word will strip the numPr on open.
    /// </remarks>
    public static void CreateListStyle(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        var listStyle = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "ListBullet1",
            CustomStyle = true
        };

        listStyle.Append(new StyleName { Val = "List Bullet 1" });
        listStyle.Append(new BasedOn { Val = "Normal" });
        listStyle.Append(new UIPriority { Val = 34 });
        listStyle.Append(new PrimaryStyle());

        // The numPr in the style's pPr links this style to a numbering definition
        listStyle.Append(new StyleParagraphProperties(
            new NumberingProperties(
                // numId = the NumberingInstance ID (not the AbstractNum ID)
                // IMPORTANT: This must match a <w:num w:numId="1"> in the numbering part
                new NumberingId { Val = 1 },
                // ilvl = indent level (0-based); level 0 = first level bullet
                new NumberingLevelReference { Val = 0 }
            ),
            // Contextual spacing: suppress space between consecutive list items
            // that use the same style (Word collapses the after-spacing)
            new ContextualSpacing()
        ));

        stylesPart.Styles.Append(listStyle);
        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 5. DOC DEFAULTS (comprehensive)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets up DocDefaults with all 4 font slots, complex-script sizes,
    /// language tags, and paragraph-level default spacing.
    /// DocDefaults is the absolute base of the style inheritance chain —
    /// everything inherits from it unless explicitly overridden.
    /// </summary>
    /// <remarks>
    /// Inheritance resolution order (highest priority last):
    ///   1. DocDefaults (w:docDefaults) — base for everything
    ///   2. Table style (w:tblStyle) — if inside a table
    ///   3. Paragraph style (w:pStyle basedOn chain)
    ///   4. Character style (w:rStyle basedOn chain)
    ///   5. Direct formatting (rPr/pPr directly on the paragraph/run)
    ///
    /// IMPORTANT: DocDefaults must be the FIRST child of w:styles.
    /// </remarks>
    public static void SetupDocDefaults(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        var docDefaults = new DocDefaults(
            new RunPropertiesDefault(
                new RunPropertiesBaseStyle(
                    // ── The 4 font slots ──
                    // These cover all Unicode ranges a document might encounter:
                    new RunFonts
                    {
                        // Ascii: Basic Latin (U+0000–U+007F)
                        Ascii = "Calibri",
                        // HighAnsi: Latin Extended + other non-EastAsian scripts
                        HighAnsi = "Calibri",
                        // EastAsia: CJK Unified Ideographs, Hiragana, Katakana, Hangul
                        EastAsia = "SimSun",       // 宋体
                        // ComplexScript: Arabic, Hebrew, Thai, Devanagari, etc.
                        ComplexScript = "Arial"
                    },
                    // ── Font sizes ──
                    // IMPORTANT: Font sizes are in HALF-POINTS throughout OpenXML
                    //   22 half-pt = 11pt (Word's default body size)
                    //   24 half-pt = 12pt (common for academic papers)
                    new FontSize { Val = "22" },
                    new FontSizeComplexScript { Val = "22" },
                    // ── Language tags ──
                    // Control spell-check dictionary, hyphenation rules, and
                    // font fallback behavior for each script
                    new Languages
                    {
                        Val = "en-US",       // Latin script language
                        EastAsia = "zh-CN",  // CJK language (Simplified Chinese)
                        Bidi = "ar-SA"       // BiDi language (Arabic, Saudi Arabia)
                    },
                    // ── Kerning ──
                    // Kern font pairs at this size (in half-points) and above
                    // 0 = no kerning; 2 = kern at 1pt+ (aggressive); 28 = kern at 14pt+ (typical)
                    new Kern { Val = (UInt32Value)2U }
                )
            ),
            new ParagraphPropertiesDefault(
                new ParagraphPropertiesBaseStyle(
                    new SpacingBetweenLines
                    {
                        // Before = space before paragraph (DXA twentieths-of-a-point)
                        Before = "0",
                        // After = space after paragraph
                        After = "160",         // 8pt = Word 2016+ default
                        // Line spacing:
                        //   For Auto rule: units are 240ths of a line
                        //     240 = exactly single spacing
                        //     259 = ~1.08 (Word's default "single")
                        //     360 = 1.5 spacing
                        //     480 = double spacing
                        //   For Exact/AtLeast rules: units are DXA (twentieths-of-a-point)
                        Line = "259",
                        LineRule = LineSpacingRuleValues.Auto
                    },
                    // WidowControl: prevent single lines at top/bottom of page
                    new WidowControl()
                )
            )
        );

        // Remove any existing DocDefaults and prepend the new one
        stylesPart.Styles.DocDefaults?.Remove();
        stylesPart.Styles.PrependChild(docDefaults);
        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 6. LATENT STYLES
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Configures latent styles — the built-in styles that Word knows about
    /// but doesn't include in styles.xml until they're used.
    /// Controls visibility, priority, and quick-format status of all 375+ built-in styles.
    /// </summary>
    /// <remarks>
    /// Latent styles serve two purposes:
    /// 1. Performance: Word doesn't serialize all 375+ built-in styles into styles.xml
    /// 2. UI: Controls which styles appear in the Styles pane and Quick Styles gallery
    ///
    /// The LatentStyles element sets defaults, then LatentStyleExceptionInfo overrides
    /// specific styles. If a built-in style is used in the document but not in styles.xml,
    /// Word uses the latent style definition to determine its formatting.
    /// </remarks>
    public static void SetupLatentStyles(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        var latentStyles = new LatentStyles
        {
            // Default values for ALL built-in styles not explicitly listed
            DefaultLockedState = false,
            DefaultUiPriority = 99,        // 99 = low priority (sorted last in Styles pane)
            DefaultSemiHidden = true,       // hidden from Styles pane by default
            DefaultUnhideWhenUsed = true,   // auto-show when used in the document
            DefaultPrimaryStyle = false,    // don't show in Quick Styles gallery by default
            Count = 376                     // total number of built-in styles in Word 2019+
        };

        // Override specific styles to make them visible and high-priority
        // These are the styles users commonly need in the Styles pane

        // Core paragraph styles — always visible
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Normal",
            UiPriority = 0,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });

        // Heading styles
        for (int i = 1; i <= 6; i++)
        {
            latentStyles.Append(new LatentStyleExceptionInfo
            {
                Name = $"heading {i}",
                UiPriority = 9,
                SemiHidden = i > 2,              // only H1-H2 visible by default
                UnhideWhenUsed = true,
                PrimaryStyle = i <= 3             // H1-H3 in Quick Styles
            });
        }

        // Title and Subtitle
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Title",
            UiPriority = 10,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Subtitle",
            UiPriority = 11,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });

        // Inline styles
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Strong",
            UiPriority = 22,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Emphasis",
            UiPriority = 20,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });

        // Table styles
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "Table Grid",
            UiPriority = 39,
            SemiHidden = false,
            UnhideWhenUsed = false
        });

        // List styles
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "List Paragraph",
            UiPriority = 34,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });

        // No Spacing (popular alternative to Normal)
        latentStyles.Append(new LatentStyleExceptionInfo
        {
            Name = "No Spacing",
            UiPriority = 1,
            SemiHidden = false,
            UnhideWhenUsed = false,
            PrimaryStyle = true
        });

        // Remove existing LatentStyles and add new one
        // IMPORTANT: LatentStyles should come after DocDefaults but before Style elements
        stylesPart.Styles.Elements<LatentStyles>().ToList().ForEach(ls => ls.Remove());
        var docDefaults = stylesPart.Styles.DocDefaults;
        if (docDefaults is not null)
            docDefaults.InsertAfterSelf(latentStyles);
        else
            stylesPart.Styles.PrependChild(latentStyles);

        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 7. CJK STYLES (Chinese 公文)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates Chinese government document (公文) styles per GB/T 9704-2012:
    ///   - GongWenTitle: 方正小标宋简体 (FZXiaoBiaoSong) 二号 (22pt) — document title
    ///   - GongWenBody: 仿宋 (FangSong) 三号 (16pt) — body text
    ///   - L1Heading: 黑体 (SimHei) 三号 (16pt) — first-level heading
    ///   - L2Heading: 楷体 (KaiTi) 三号 (16pt) — second-level heading
    /// </summary>
    /// <remarks>
    /// Chinese font size names to point sizes:
    ///   初号 = 42pt    小初 = 36pt
    ///   一号 = 26pt    小一 = 24pt
    ///   二号 = 22pt    小二 = 18pt
    ///   三号 = 16pt    小三 = 15pt
    ///   四号 = 14pt    小四 = 12pt
    ///   五号 = 10.5pt  小五 = 9pt
    ///   六号 = 7.5pt   小六 = 6.5pt
    ///   七号 = 5.5pt   八号 = 5pt
    ///
    /// CJK font usage in 公文:
    ///   方正小标宋简体 (FZXiaoBiaoSong-B13S) — titles, rarely available; fallback: 华文中宋 or SimSun
    ///   仿宋 (FangSong / FangSong_GB2312) — body text
    ///   黑体 (SimHei) — first-level headings (bold-like appearance)
    ///   楷体 (KaiTi / KaiTi_GB2312) — second-level headings (calligraphic)
    ///   宋体 (SimSun) — fallback for everything
    ///
    /// IMPORTANT: The EastAsia font slot controls which font is used for CJK characters.
    /// The Ascii/HighAnsi slots only affect Latin characters within CJK paragraphs.
    /// </remarks>
    public static void CreateCjkStyles(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        // ── 公文标题 (Document Title) ──
        // 方正小标宋简体 二号 (22pt), centered, 行距固定值 (exact line spacing)
        var titleStyle = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "GongWenTitle",
            CustomStyle = true
        };
        titleStyle.Append(new StyleName { Val = "公文标题" });
        titleStyle.Append(new BasedOn { Val = "Normal" });
        titleStyle.Append(new NextParagraphStyle { Val = "GongWenBody" });
        titleStyle.Append(new UIPriority { Val = 1 });
        titleStyle.Append(new PrimaryStyle());
        titleStyle.Append(new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center },
            new SpacingBetweenLines
            {
                // 公文 title uses exact line spacing, typically ~32pt = 640 DXA
                Line = "640",
                LineRule = LineSpacingRuleValues.Exact,
                Before = "0",
                After = "0"
            },
            new KeepNext(),
            new KeepLines(),
            // outlineLvl 0 makes this appear as "Level 1" in navigation / TOC
            new OutlineLevel { Val = 0 }
        ));
        titleStyle.Append(new StyleRunProperties(
            new RunFonts
            {
                // EastAsia = the CJK font that renders Chinese characters
                // 方正小标宋简体 is the standard 公文 title font
                // Fallback: 华文中宋 (STZhongsong) → SimSun
                EastAsia = "方正小标宋简体",
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                ComplexScript = "Times New Roman"
            },
            // 二号 = 22pt = 44 half-points
            new FontSize { Val = "44" },
            new FontSizeComplexScript { Val = "44" }
        ));
        stylesPart.Styles.Append(titleStyle);

        // ── 公文正文 (Body Text) ──
        // 仿宋 三号 (16pt), justified, 28pt exact line spacing
        var bodyStyle = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "GongWenBody",
            CustomStyle = true
        };
        bodyStyle.Append(new StyleName { Val = "公文正文" });
        bodyStyle.Append(new BasedOn { Val = "Normal" });
        bodyStyle.Append(new UIPriority { Val = 2 });
        bodyStyle.Append(new PrimaryStyle());
        bodyStyle.Append(new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Both },
            new SpacingBetweenLines
            {
                // 28pt line spacing (exact) = 560 DXA, standard for 公文 body
                Line = "560",
                LineRule = LineSpacingRuleValues.Exact,
                Before = "0",
                After = "0"
            },
            // First-line indent of 2 characters for Chinese body text
            // For 三号 (16pt) font: 2 chars ≈ 640 DXA (16pt * 20 DXA/pt * 2)
            new Indentation { FirstLine = "640" },
            // CJK paragraph settings
            new WordWrap { Val = true },
            new AutoSpaceDE { Val = true },
            new AutoSpaceDN { Val = true }
        ));
        bodyStyle.Append(new StyleRunProperties(
            new RunFonts
            {
                EastAsia = "仿宋",
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman",
                ComplexScript = "Times New Roman"
            },
            // 三号 = 16pt = 32 half-points
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ));
        stylesPart.Styles.Append(bodyStyle);

        // ── 一级标题 (Level 1 Heading) ──
        // 黑体 三号 (16pt), bold by nature of the font
        var l1Style = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "L1Heading",
            CustomStyle = true
        };
        l1Style.Append(new StyleName { Val = "一级标题" });
        l1Style.Append(new BasedOn { Val = "GongWenBody" });
        l1Style.Append(new NextParagraphStyle { Val = "GongWenBody" });
        l1Style.Append(new UIPriority { Val = 3 });
        l1Style.Append(new PrimaryStyle());
        l1Style.Append(new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            // Remove the first-line indent from headings
            new Indentation { FirstLine = "0" },
            new Justification { Val = JustificationValues.Center },
            new OutlineLevel { Val = 1 }
        ));
        l1Style.Append(new StyleRunProperties(
            new RunFonts
            {
                // 黑体 (SimHei) — a sans-serif CJK font that looks inherently bold
                // IMPORTANT: Do NOT add w:b (Bold) — SimHei is already visually bold,
                // and adding Bold makes it too thick
                EastAsia = "黑体",
                Ascii = "Arial",
                HighAnsi = "Arial"
            },
            // Same size as body: 三号 = 16pt
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ));
        stylesPart.Styles.Append(l1Style);

        // ── 二级标题 (Level 2 Heading) ──
        // 楷体 三号 (16pt), also not bold by convention
        var l2Style = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "L2Heading",
            CustomStyle = true
        };
        l2Style.Append(new StyleName { Val = "二级标题" });
        l2Style.Append(new BasedOn { Val = "GongWenBody" });
        l2Style.Append(new NextParagraphStyle { Val = "GongWenBody" });
        l2Style.Append(new UIPriority { Val = 4 });
        l2Style.Append(new PrimaryStyle());
        l2Style.Append(new StyleParagraphProperties(
            new KeepNext(),
            new KeepLines(),
            new Indentation { FirstLine = "0" },
            new Justification { Val = JustificationValues.Left },
            new OutlineLevel { Val = 2 }
        ));
        l2Style.Append(new StyleRunProperties(
            new RunFonts
            {
                // 楷体 (KaiTi) — calligraphic script font
                EastAsia = "楷体",
                Ascii = "Times New Roman",
                HighAnsi = "Times New Roman"
            },
            new FontSize { Val = "32" },
            new FontSizeComplexScript { Val = "32" }
        ));
        stylesPart.Styles.Append(l2Style);

        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 8. ACADEMIC STYLES (APA 7th Edition)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates styles conforming to APA 7th edition formatting guidelines:
    ///   - APATitle: centered, bold, 12pt Times New Roman
    ///   - APAHeading1–5: the five APA heading levels
    ///   - APABody: double-spaced, first-line indent 0.5", 12pt TNR
    ///   - APAAbstract: single paragraph, no indent, 12pt
    ///   - APABlockQuote: 0.5" left indent, no first-line indent, double-spaced
    /// </summary>
    /// <remarks>
    /// APA 7th edition heading levels:
    ///   Level 1: Centered, Bold, Title Case          (like a chapter title)
    ///   Level 2: Flush Left, Bold, Title Case
    ///   Level 3: Flush Left, Bold Italic, Title Case
    ///   Level 4: Indented 0.5", Bold, Title Case, Period.  (run-in heading)
    ///   Level 5: Indented 0.5", Bold Italic, Title Case, Period.
    ///
    /// All text: Times New Roman 12pt, double-spaced (480 in 240ths units).
    /// </remarks>
    public static void CreateAcademicStyles(StyleDefinitionsPart stylesPart)
    {
        stylesPart.Styles ??= new Styles();

        const string font = "Times New Roman";
        const string sizeVal = "24";    // 12pt in half-points
        // Double spacing: 480 = 2.0 * 240 (240ths of a line)
        const string doubleSpace = "480";

        // ── APA Body (base for all APA styles) ──
        var apaBody = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "APABody",
            CustomStyle = true
        };
        apaBody.Append(new StyleName { Val = "APA Body" });
        apaBody.Append(new BasedOn { Val = "Normal" });
        apaBody.Append(new UIPriority { Val = 1 });
        apaBody.Append(new PrimaryStyle());
        apaBody.Append(new StyleParagraphProperties(
            new SpacingBetweenLines
            {
                Line = doubleSpace,
                LineRule = LineSpacingRuleValues.Auto,
                Before = "0",
                After = "0"  // APA: no extra space between paragraphs
            },
            // APA 7: 0.5-inch first-line indent = 720 DXA
            new Indentation { FirstLine = "720" },
            new Justification { Val = JustificationValues.Left },
            // WARNING: APA explicitly says do NOT use justified alignment.
            // Always use left (ragged right).
            new WidowControl()
        ));
        apaBody.Append(new StyleRunProperties(
            new RunFonts
            {
                Ascii = font,
                HighAnsi = font,
                EastAsia = font,
                ComplexScript = font
            },
            new FontSize { Val = sizeVal },
            new FontSizeComplexScript { Val = sizeVal }
        ));
        stylesPart.Styles.Append(apaBody);

        // ── APA Title (paper title on title page) ──
        var apaTitle = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "APATitle",
            CustomStyle = true
        };
        apaTitle.Append(new StyleName { Val = "APA Title" });
        apaTitle.Append(new BasedOn { Val = "APABody" });
        apaTitle.Append(new NextParagraphStyle { Val = "APABody" });
        apaTitle.Append(new UIPriority { Val = 2 });
        apaTitle.Append(new PrimaryStyle());
        apaTitle.Append(new StyleParagraphProperties(
            new Justification { Val = JustificationValues.Center },
            new Indentation { FirstLine = "0" },
            // Extra space before the title block
            new SpacingBetweenLines
            {
                Line = doubleSpace,
                LineRule = LineSpacingRuleValues.Auto,
                Before = "0",
                After = "0"
            },
            new OutlineLevel { Val = 0 }
        ));
        apaTitle.Append(new StyleRunProperties(
            new Bold(),
            new BoldComplexScript()
        ));
        stylesPart.Styles.Append(apaTitle);

        // ── APA Heading Levels 1–5 ──
        var apaHeadings = new (string Id, string Name, int Level, bool Bold, bool Italic, JustificationValues Jc, string Indent, bool RunIn)[]
        {
            ("APAHeading1", "APA Heading 1", 1, true,  false, JustificationValues.Center, "0",   false),
            ("APAHeading2", "APA Heading 2", 2, true,  false, JustificationValues.Left,   "0",   false),
            ("APAHeading3", "APA Heading 3", 3, true,  true,  JustificationValues.Left,   "0",   false),
            ("APAHeading4", "APA Heading 4", 4, true,  false, JustificationValues.Left,   "720", true),
            ("APAHeading5", "APA Heading 5", 5, true,  true,  JustificationValues.Left,   "720", true),
        };

        foreach (var (id, name, level, bold, italic, jc, indent, runIn) in apaHeadings)
        {
            var style = new Style
            {
                Type = StyleValues.Paragraph,
                StyleId = id,
                CustomStyle = true
            };
            style.Append(new StyleName { Val = name });
            style.Append(new BasedOn { Val = "APABody" });
            style.Append(new NextParagraphStyle { Val = runIn ? id : "APABody" });
            style.Append(new UIPriority { Val = 9 });
            style.Append(new PrimaryStyle());

            var pPr = new StyleParagraphProperties(
                new KeepNext(),
                new KeepLines(),
                new SpacingBetweenLines
                {
                    Line = doubleSpace,
                    LineRule = LineSpacingRuleValues.Auto,
                    Before = "0",
                    After = "0"
                },
                new Justification { Val = jc },
                // Remove or set first-line indent based on APA level
                new Indentation
                {
                    Left = indent,
                    FirstLine = "0"
                },
                // outlineLvl is 0-based, APA level 1 = outlineLvl 0
                new OutlineLevel { Val = level - 1 }
            );
            style.Append(pPr);

            var rPr = new StyleRunProperties();
            if (bold)
            {
                rPr.Append(new Bold());
                rPr.Append(new BoldComplexScript());
            }
            if (italic)
            {
                rPr.Append(new Italic());
                rPr.Append(new ItalicComplexScript());
            }
            style.Append(rPr);

            stylesPart.Styles.Append(style);
        }

        // ── APA Abstract ──
        var apaAbstract = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "APAAbstract",
            CustomStyle = true
        };
        apaAbstract.Append(new StyleName { Val = "APA Abstract" });
        apaAbstract.Append(new BasedOn { Val = "APABody" });
        apaAbstract.Append(new UIPriority { Val = 5 });
        apaAbstract.Append(new StyleParagraphProperties(
            // APA Abstract: single paragraph, NO first-line indent
            new Indentation { FirstLine = "0" }
        ));
        stylesPart.Styles.Append(apaAbstract);

        // ── APA Block Quote ──
        // For quotes of 40+ words: 0.5" left indent, no first-line indent, double-spaced
        var apaBlock = new Style
        {
            Type = StyleValues.Paragraph,
            StyleId = "APABlockQuote",
            CustomStyle = true
        };
        apaBlock.Append(new StyleName { Val = "APA Block Quote" });
        apaBlock.Append(new BasedOn { Val = "APABody" });
        apaBlock.Append(new UIPriority { Val = 6 });
        apaBlock.Append(new StyleParagraphProperties(
            // 0.5-inch left indent = 720 DXA
            new Indentation { Left = "720", FirstLine = "0" }
        ));
        stylesPart.Styles.Append(apaBlock);

        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 9. IMPORT STYLES FROM ANOTHER DOCUMENT
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Imports styles, numbering definitions, and theme from a source DOCX
    /// into the target document's MainDocumentPart by stream-copying the parts.
    /// This is the standard "apply template" pattern.
    /// </summary>
    /// <remarks>
    /// WARNING: This replaces the ENTIRE styles/numbering/theme parts.
    /// Any existing styles in the target that aren't in the source will be lost.
    /// For a merge approach (keeping both), you would need to deserialize both
    /// Styles objects and merge individual Style elements, resolving ID conflicts.
    ///
    /// Parts copied:
    ///   - StyleDefinitionsPart (word/styles.xml)
    ///   - NumberingDefinitionsPart (word/numbering.xml)
    ///   - ThemePart (word/theme/theme1.xml)
    /// </remarks>
    public static void ImportStylesFromDocument(string sourcePath, MainDocumentPart target)
    {
        // Open source as read-only
        using var sourceDoc = WordprocessingDocument.Open(sourcePath, isEditable: false);
        var sourceMain = sourceDoc.MainDocumentPart;
        if (sourceMain is null) return;

        // ── Copy StyleDefinitionsPart ──
        if (sourceMain.StyleDefinitionsPart is not null)
        {
            // Delete existing styles part if present
            if (target.StyleDefinitionsPart is not null)
                target.DeletePart(target.StyleDefinitionsPart);

            // Add a fresh part and stream-copy the content
            var newStylesPart = target.AddNewPart<StyleDefinitionsPart>();
            using (var sourceStream = sourceMain.StyleDefinitionsPart.GetStream())
            using (var targetStream = newStylesPart.GetStream(FileMode.Create))
            {
                sourceStream.CopyTo(targetStream);
            }
        }

        // ── Copy NumberingDefinitionsPart ──
        if (sourceMain.NumberingDefinitionsPart is not null)
        {
            if (target.NumberingDefinitionsPart is not null)
                target.DeletePart(target.NumberingDefinitionsPart);

            var newNumPart = target.AddNewPart<NumberingDefinitionsPart>();
            using (var sourceStream = sourceMain.NumberingDefinitionsPart.GetStream())
            using (var targetStream = newNumPart.GetStream(FileMode.Create))
            {
                sourceStream.CopyTo(targetStream);
            }
        }

        // ── Copy ThemePart ──
        if (sourceMain.ThemePart is not null)
        {
            if (target.ThemePart is not null)
                target.DeletePart(target.ThemePart);

            var newThemePart = target.AddNewPart<ThemePart>();
            using (var sourceStream = sourceMain.ThemePart.GetStream())
            using (var targetStream = newThemePart.GetStream(FileMode.Create))
            {
                sourceStream.CopyTo(targetStream);
            }
        }

        // IMPORTANT: After importing, you may need to update style references
        // in the document body if the source uses different style IDs.
        // Also check that numbering numId references in paragraphs match the
        // imported NumberingInstance IDs.
    }

    // ────────────────────────────────────────────────────────────────────
    // 10. APPLY STYLE TO EXISTING PARAGRAPHS
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Finds all paragraphs in the body and applies (or changes) their paragraph style.
    /// Demonstrates how to set/replace the pStyle element on existing paragraphs.
    /// </summary>
    /// <remarks>
    /// To apply a style to a paragraph:
    /// <code>
    /// &lt;w:p&gt;
    ///   &lt;w:pPr&gt;
    ///     &lt;w:pStyle w:val="Heading1"/&gt;
    ///   &lt;/w:pPr&gt;
    ///   ...
    /// &lt;/w:p&gt;
    /// </code>
    ///
    /// IMPORTANT: pStyle must be the FIRST child of pPr.
    /// If you Append it, it may end up after other elements, which technically
    /// violates the schema (though Word tolerates it).
    /// </remarks>
    public static void ApplyStyleToExistingParagraphs(Body body, string styleId)
    {
        foreach (var para in body.Elements<Paragraph>())
        {
            // Get or create ParagraphProperties
            var pPr = para.ParagraphProperties;
            if (pPr is null)
            {
                pPr = new ParagraphProperties();
                // IMPORTANT: pPr must be the FIRST child of the paragraph
                para.PrependChild(pPr);
            }

            // Get or create ParagraphStyleId
            var pStyle = pPr.ParagraphStyleId;
            if (pStyle is not null)
            {
                // Update existing style reference
                pStyle.Val = styleId;
            }
            else
            {
                // Create new style reference
                // IMPORTANT: pStyle must be the FIRST child of pPr
                pPr.PrependChild(new ParagraphStyleId { Val = styleId });
            }
        }
    }

    // ────────────────────────────────────────────────────────────────────
    // 11. RESOLVE EFFECTIVE FORMATTING
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Walks the style inheritance chain to resolve the effective (computed)
    /// formatting for a paragraph's first run. Returns a summary of the resolved
    /// font, size, bold, and italic properties.
    /// </summary>
    /// <remarks>
    /// Resolution order (later overrides earlier):
    ///   1. DocDefaults → rPrDefault
    ///   2. basedOn chain (walk from the root ancestor down to the paragraph's style)
    ///   3. Paragraph style's rPr (StyleRunProperties)
    ///   4. Character style's rPr (if w:rStyle is set on the run)
    ///   5. Direct formatting (RunProperties on the run itself)
    ///
    /// Each level only overrides properties it explicitly sets; unset properties
    /// are inherited from the previous level.
    ///
    /// IMPORTANT: This is a simplified resolution. Full resolution must also handle:
    ///   - Table style conditional formatting
    ///   - Numbering level rPr
    ///   - Toggle properties (bold, italic) which XOR rather than override
    ///   - Theme font resolution (majorHAnsi → actual font name from theme)
    /// </remarks>
    public static ResolvedFormatting ResolveEffectiveFormatting(
        Paragraph para,
        StyleDefinitionsPart stylesPart)
    {
        var result = new ResolvedFormatting();
        var styles = stylesPart.Styles;
        if (styles is null) return result;

        // ── Step 1: DocDefaults ──
        var docDefaults = styles.DocDefaults;
        if (docDefaults?.RunPropertiesDefault?.RunPropertiesBaseStyle is RunPropertiesBaseStyle defaultRPr)
        {
            ApplyRunProps(result, defaultRPr);
        }

        // ── Step 2–3: Walk basedOn chain for the paragraph style ──
        var pStyleId = para.ParagraphProperties?.ParagraphStyleId?.Val?.Value;
        // If no explicit style, use the default paragraph style
        pStyleId ??= styles.Elements<Style>()
            .FirstOrDefault(s => s.Type?.Value == StyleValues.Paragraph && s.Default?.Value == true)
            ?.StyleId?.Value;

        if (pStyleId is not null)
        {
            // Build the chain: [root ancestor, ..., grandparent, parent, style]
            var chain = BuildBasedOnChain(pStyleId, styles);

            // Apply each style's rPr in order (root first, most specific last)
            foreach (var styleInChain in chain)
            {
                var styleRPr = styleInChain.StyleRunProperties;
                if (styleRPr is not null)
                {
                    ApplyRunProps(result, styleRPr);
                }
            }
        }

        // ── Step 4: Character style (rStyle on the run) ──
        var firstRun = para.Elements<Run>().FirstOrDefault();
        var rStyleId = firstRun?.RunProperties?.RunStyle?.Val?.Value;
        if (rStyleId is not null)
        {
            var charChain = BuildBasedOnChain(rStyleId, styles);
            foreach (var styleInChain in charChain)
            {
                var styleRPr = styleInChain.StyleRunProperties;
                if (styleRPr is not null)
                {
                    ApplyRunProps(result, styleRPr);
                }
            }
        }

        // ── Step 5: Direct formatting on the run ──
        if (firstRun?.RunProperties is RunProperties directRPr)
        {
            ApplyRunProps(result, directRPr);
        }

        return result;
    }

    /// <summary>
    /// Builds the basedOn chain for a style, from root ancestor to the style itself.
    /// Returns a list ordered [root, ..., parent, style].
    /// </summary>
    private static List<Style> BuildBasedOnChain(string styleId, Styles styles)
    {
        var chain = new List<Style>();
        var visited = new HashSet<string>(); // guard against circular references

        var currentId = styleId;
        while (currentId is not null && visited.Add(currentId))
        {
            var style = styles.Elements<Style>()
                .FirstOrDefault(s => s.StyleId?.Value == currentId);

            if (style is null) break;

            chain.Add(style);
            currentId = style.BasedOn?.Val?.Value;
        }

        // Reverse so root ancestor is first
        chain.Reverse();
        return chain;
    }

    /// <summary>
    /// Applies run properties from any source (DocDefaults, StyleRunProperties, or RunProperties)
    /// to the resolved formatting result. Only overrides properties that are explicitly set.
    /// </summary>
    private static void ApplyRunProps(ResolvedFormatting result, OpenXmlCompositeElement rPr)
    {
        // Font name — check all slots
        var fonts = rPr.GetFirstChild<RunFonts>();
        if (fonts is not null)
        {
            if (fonts.Ascii?.Value is not null) result.FontAscii = fonts.Ascii.Value;
            if (fonts.HighAnsi?.Value is not null) result.FontHighAnsi = fonts.HighAnsi.Value;
            if (fonts.EastAsia?.Value is not null) result.FontEastAsia = fonts.EastAsia.Value;
            if (fonts.ComplexScript?.Value is not null) result.FontComplexScript = fonts.ComplexScript.Value;

            // Theme font references (these override explicit names when a theme is active)
            if (fonts.AsciiTheme?.Value is not null) result.ThemeFontAscii = fonts.AsciiTheme.Value.ToString();
            if (fonts.EastAsiaTheme?.Value is not null) result.ThemeFontEastAsia = fonts.EastAsiaTheme.Value.ToString();
        }

        // Font size
        var sz = rPr.GetFirstChild<FontSize>();
        if (sz?.Val?.Value is not null)
        {
            if (int.TryParse(sz.Val.Value, out var halfPts))
                result.SizePoints = halfPts / 2.0;
        }

        // Bold — toggle property
        var bold = rPr.GetFirstChild<Bold>();
        if (bold is not null)
        {
            // <w:b/> means true; <w:b w:val="false"/> means false
            // WARNING: Bold is a "toggle" property in OpenXML.
            // In theory, if a parent style sets bold=true and a child style sets bold=true,
            // they XOR to false. In practice, most implementations treat it as a simple override.
            result.IsBold = bold.Val is null || bold.Val.Value;
        }

        // Italic — also a toggle property
        var italic = rPr.GetFirstChild<Italic>();
        if (italic is not null)
        {
            result.IsItalic = italic.Val is null || italic.Val.Value;
        }

        // Color
        var color = rPr.GetFirstChild<Color>();
        if (color?.Val?.Value is not null)
        {
            result.ColorHex = color.Val.Value;
        }

        // Underline
        var underline = rPr.GetFirstChild<Underline>();
        if (underline?.Val is not null)
        {
            result.UnderlineStyle = underline.Val.Value.ToString();
        }
    }

    /// <summary>
    /// Represents the fully resolved formatting after walking the inheritance chain.
    /// </summary>
    public class ResolvedFormatting
    {
        public string? FontAscii { get; set; }
        public string? FontHighAnsi { get; set; }
        public string? FontEastAsia { get; set; }
        public string? FontComplexScript { get; set; }
        public string? ThemeFontAscii { get; set; }
        public string? ThemeFontEastAsia { get; set; }
        public double SizePoints { get; set; }
        public bool IsBold { get; set; }
        public bool IsItalic { get; set; }
        public string? ColorHex { get; set; }
        public string? UnderlineStyle { get; set; }

        public override string ToString() =>
            $"Font: {FontAscii ?? ThemeFontAscii ?? "?"}, " +
            $"EastAsia: {FontEastAsia ?? ThemeFontEastAsia ?? "?"}, " +
            $"Size: {SizePoints}pt, " +
            $"Bold: {IsBold}, Italic: {IsItalic}, " +
            $"Color: {ColorHex ?? "auto"}, " +
            $"Underline: {UnderlineStyle ?? "none"}";
    }
}
