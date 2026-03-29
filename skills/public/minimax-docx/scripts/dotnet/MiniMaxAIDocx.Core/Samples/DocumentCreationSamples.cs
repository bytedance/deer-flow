using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.CustomProperties;
using DocumentFormat.OpenXml.ExtendedProperties;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.VariantTypes;
using DocumentFormat.OpenXml.Wordprocessing;
using MiniMaxAIDocx.Core.OpenXml;
using MiniMaxAIDocx.Core.Typography;
using WpPageSize = DocumentFormat.OpenXml.Wordprocessing.PageSize;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Compilable reference examples for DOCX document creation and setup.
/// Every method is self-contained and demonstrates a specific aspect of
/// document creation using the OpenXML SDK 3.x strongly-typed API.
/// </summary>
public static class DocumentCreationSamples
{
    // ────────────────────────────────────────────────────────────────────
    // 1. MINIMAL DOCUMENT
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates the absolute minimum valid DOCX file: a single empty paragraph
    /// inside a body, with a final section properties element.
    /// This is the smallest file Word/LibreOffice will open without error.
    /// </summary>
    /// <remarks>
    /// Produces this XML in word/document.xml:
    /// <code>
    /// &lt;w:document&gt;
    ///   &lt;w:body&gt;
    ///     &lt;w:p/&gt;
    ///     &lt;w:sectPr&gt;
    ///       &lt;w:pgSz w:w="12240" w:h="15840"/&gt;
    ///       &lt;w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
    ///                w:header="720" w:footer="720" w:gutter="0"/&gt;
    ///     &lt;/w:sectPr&gt;
    ///   &lt;/w:body&gt;
    /// &lt;/w:document&gt;
    /// </code>
    /// </remarks>
    public static void CreateMinimalDocument(string path)
    {
        // IMPORTANT: OpenXML SDK 3.x uses IDisposable — always wrap in using.
        // Never call .Close() — it was removed in SDK 3.x.
        using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);

        // Every DOCX needs exactly one MainDocumentPart
        var mainPart = doc.AddMainDocumentPart();

        // The Document element is the root of word/document.xml
        mainPart.Document = new Document(
            new Body(
                // At least one paragraph is required for a valid document
                new Paragraph(),
                // SectionProperties must be the LAST child of Body
                // WARNING: If sectPr is not last, Word may silently move it or corrupt the file
                new SectionProperties(
                    // PageSize: Letter = 8.5" x 11" = 12240 x 15840 DXA (1 inch = 1440 DXA)
                    new WpPageSize
                    {
                        Width = (UInt32Value)12240U,
                        Height = (UInt32Value)15840U
                    },
                    // PageMargin: 1 inch all sides = 1440 DXA each
                    // Header/footer distance: 0.5 inch = 720 DXA
                    new PageMargin
                    {
                        Top = 1440,
                        Right = (UInt32Value)1440U,
                        Bottom = 1440,
                        Left = (UInt32Value)1440U,
                        Header = (UInt32Value)720U,
                        Footer = (UInt32Value)720U,
                        Gutter = (UInt32Value)0U
                    }
                )
            )
        );

        // Save is called automatically by Dispose, but explicit save ensures
        // all parts are flushed before the stream closes
        mainPart.Document.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 2. FULL DOCUMENT (all parts)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a production-ready DOCX with all standard parts:
    /// styles, settings, numbering definitions, font table, and theme.
    /// This mirrors the structure Word generates for a "New Blank Document".
    /// </summary>
    public static void CreateFullDocument(string path)
    {
        using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);
        var mainPart = doc.AddMainDocumentPart();

        // ── StyleDefinitionsPart ──
        // Contains all named styles (Normal, Heading1, etc.)
        var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles = new Styles();
        // Populate styles using the StyleSystemSamples helper
        StyleSystemSamples.SetupDocDefaults(stylesPart);
        StyleSystemSamples.CreateBasicStyles(stylesPart);
        stylesPart.Styles.Save();

        // ── DocumentSettingsPart ──
        // Contains zoom, compatibility, proofing state, etc.
        var settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
        settingsPart.Settings = new Settings();
        AddDocumentSettings(mainPart);
        settingsPart.Settings.Save();

        // ── NumberingDefinitionsPart ──
        // Required if any paragraph uses numbered/bulleted lists
        var numberingPart = mainPart.AddNewPart<NumberingDefinitionsPart>();
        numberingPart.Numbering = new Numbering();
        // Add a basic bullet list abstract numbering definition
        var abstractNum = new AbstractNum(
            new Level(
                new NumberingFormat { Val = NumberFormatValues.Bullet },
                new LevelText { Val = "\u2022" }, // bullet character
                new LevelJustification { Val = LevelJustificationValues.Left },
                new ParagraphProperties(
                    new Indentation
                    {
                        Left = "720",   // 0.5 inch = 720 DXA
                        Hanging = "360" // 0.25 inch hanging indent
                    }
                )
            )
            { LevelIndex = 0 }
        )
        { AbstractNumberId = 1 };

        // IMPORTANT: AbstractNum elements must come BEFORE NumberingInstance elements
        // in the Numbering part, or Word will report corruption
        numberingPart.Numbering.Append(abstractNum);
        numberingPart.Numbering.Append(
            new NumberingInstance(
                new AbstractNumId { Val = 1 }
            )
            { NumberID = 1 }
        );
        numberingPart.Numbering.Save();

        // ── FontTablePart ──
        // Declares fonts used in the document; Word auto-populates on save,
        // but pre-creating it avoids a repair prompt
        var fontTablePart = mainPart.AddNewPart<FontTablePart>();
        fontTablePart.Fonts = new Fonts(
            new Font(
                new Panose1Number { Val = "020B0604020202020204" },
                new FontCharSet { Val = "00" },
                new FontFamily { Val = FontFamilyValues.Swiss }
            )
            { Name = "Calibri" },
            new Font(
                new Panose1Number { Val = "020B0604020202020204" },
                new FontCharSet { Val = "00" },
                new FontFamily { Val = FontFamilyValues.Swiss }
            )
            { Name = "Calibri Light" }
        );
        fontTablePart.Fonts.Save();

        // ── ThemePart ──
        // Defines the document's theme colors and fonts.
        // IMPORTANT: We use a minimal theme; for full Office themes, copy from a .docx template
        var themePart = mainPart.AddNewPart<ThemePart>();
        // Write minimal theme XML directly since the strongly-typed API for themes
        // lives in DocumentFormat.OpenXml.Drawing and is very verbose
        using (var writer = new System.IO.StreamWriter(themePart.GetStream()))
        {
            writer.Write("""
                <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                <a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">
                  <a:themeElements>
                    <a:clrScheme name="Office">
                      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
                      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
                      <a:dk2><a:srgbClr val="44546A"/></a:dk2>
                      <a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
                      <a:accent1><a:srgbClr val="4472C4"/></a:accent1>
                      <a:accent2><a:srgbClr val="ED7D31"/></a:accent2>
                      <a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>
                      <a:accent4><a:srgbClr val="FFC000"/></a:accent4>
                      <a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>
                      <a:accent6><a:srgbClr val="70AD47"/></a:accent6>
                      <a:hlink><a:srgbClr val="0563C1"/></a:hlink>
                      <a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
                    </a:clrScheme>
                    <a:fontScheme name="Office">
                      <a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
                      <a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
                    </a:fontScheme>
                    <a:fmtScheme name="Office">
                      <a:fillStyleLst>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                      </a:fillStyleLst>
                      <a:lnStyleLst>
                        <a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
                        <a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
                        <a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
                      </a:lnStyleLst>
                      <a:effectStyleLst>
                        <a:effectStyle><a:effectLst/></a:effectStyle>
                        <a:effectStyle><a:effectLst/></a:effectStyle>
                        <a:effectStyle><a:effectLst/></a:effectStyle>
                      </a:effectStyleLst>
                      <a:bgFillStyleLst>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
                      </a:bgFillStyleLst>
                    </a:fmtScheme>
                  </a:themeElements>
                </a:theme>
                """);
        }

        // ── Document body ──
        mainPart.Document = new Document(
            new Body(
                new Paragraph(
                    new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                    new Run(new Text("Sample Document"))
                ),
                new Paragraph(
                    new Run(new Text("This document includes all standard parts."))
                ),
                // Final section properties
                new SectionProperties(
                    new WpPageSize
                    {
                        Width = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                        Height = (UInt32Value)(uint)PageSizes.A4.HeightDxa
                    },
                    new PageMargin
                    {
                        Top = PageSizes.StandardMargins.TopDxa,
                        Right = (UInt32Value)(uint)PageSizes.StandardMargins.RightDxa,
                        Bottom = PageSizes.StandardMargins.BottomDxa,
                        Left = (UInt32Value)(uint)PageSizes.StandardMargins.LeftDxa,
                        Header = (UInt32Value)720U,
                        Footer = (UInt32Value)720U,
                        Gutter = (UInt32Value)0U
                    }
                )
            )
        );

        // Set document-level metadata
        SetDocumentProperties(doc);

        mainPart.Document.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 3. CREATE FROM STREAM (for web/API)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a DOCX entirely in memory, returning a MemoryStream.
    /// Ideal for ASP.NET / Web API scenarios where you return FileStreamResult.
    /// </summary>
    /// <remarks>
    /// Usage in ASP.NET:
    /// <code>
    /// var stream = DocumentCreationSamples.CreateFromStream();
    /// return File(stream, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "report.docx");
    /// </code>
    /// </remarks>
    public static MemoryStream CreateFromStream()
    {
        // IMPORTANT: The MemoryStream must remain open after WordprocessingDocument is disposed.
        // Do NOT wrap the stream in a using statement here — the caller owns its lifetime.
        var stream = new MemoryStream();

        // WARNING: You MUST pass 'true' for the 'leaveOpen' parameter (via the overload that
        // accepts a stream) so that disposing the WordprocessingDocument does NOT close the stream.
        // The Create overload with Stream does this correctly in SDK 3.x.
        using (var doc = WordprocessingDocument.Create(stream, WordprocessingDocumentType.Document))
        {
            var mainPart = doc.AddMainDocumentPart();
            mainPart.Document = new Document(
                new Body(
                    new Paragraph(
                        new Run(new Text("Generated in memory"))
                    ),
                    new SectionProperties(
                        new WpPageSize
                        {
                            Width = (UInt32Value)(uint)PageSizes.Letter.WidthDxa,
                            Height = (UInt32Value)(uint)PageSizes.Letter.HeightDxa
                        },
                        new PageMargin
                        {
                            Top = 1440,
                            Right = (UInt32Value)1440U,
                            Bottom = 1440,
                            Left = (UInt32Value)1440U,
                            Header = (UInt32Value)720U,
                            Footer = (UInt32Value)720U,
                            Gutter = (UInt32Value)0U
                        }
                    )
                )
            );
            mainPart.Document.Save();
        }
        // Disposing the WordprocessingDocument flushes all data to the stream.

        // IMPORTANT: Reset position so the caller can read from the beginning.
        stream.Position = 0;
        return stream;
    }

    // ────────────────────────────────────────────────────────────────────
    // 4. OPEN AND EDIT EXISTING DOCUMENT
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Opens an existing DOCX, modifies its content, and saves.
    /// Demonstrates the read-modify-write pattern.
    /// </summary>
    public static void OpenAndEdit(string path)
    {
        // Open for editing (isEditable = true)
        // WARNING: If the file is read-only on disk, this will throw IOException.
        // For read-only access, pass false and use a copy-to-stream pattern instead.
        using var doc = WordprocessingDocument.Open(path, isEditable: true);

        var body = doc.MainDocumentPart?.Document.Body;
        if (body is null)
            return;

        // Add a new paragraph at the end, BEFORE the final SectionProperties
        // WARNING: Always insert before sectPr — it must remain the last child of Body
        var sectPr = body.Elements<SectionProperties>().FirstOrDefault();

        var newParagraph = new Paragraph(
            new ParagraphProperties(
                // Apply Normal style explicitly (usually inherited, but being explicit is safer)
                new ParagraphStyleId { Val = "Normal" },
                new Justification { Val = JustificationValues.Left }
            ),
            new Run(
                new RunProperties(
                    new Bold(),
                    new Color { Val = "FF0000" } // red, RGB hex without #
                ),
                // IMPORTANT: When text has leading/trailing whitespace, you must set
                // SpaceProcessingModeValues.Preserve or Word will strip it
                new Text("This paragraph was added programmatically.") { Space = SpaceProcessingModeValues.Preserve }
            )
        );

        if (sectPr is not null)
        {
            // Insert before the final section properties
            body.InsertBefore(newParagraph, sectPr);
        }
        else
        {
            // No sectPr found (unusual but possible); just append
            body.Append(newParagraph);
        }

        // Modify an existing paragraph — change the text of the first paragraph
        var firstPara = body.Elements<Paragraph>().FirstOrDefault();
        if (firstPara is not null)
        {
            var firstRun = firstPara.Elements<Run>().FirstOrDefault();
            if (firstRun is not null)
            {
                var textElement = firstRun.Elements<Text>().FirstOrDefault();
                if (textElement is not null)
                {
                    textElement.Text = "Modified: " + textElement.Text;
                }
            }
        }

        // Save is called automatically on Dispose, but calling explicitly
        // ensures errors surface at a known point
        doc.MainDocumentPart!.Document.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 5. DOCUMENT DEFAULTS (DocDefaults)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets RunPropertiesDefault and ParagraphPropertiesDefault in the styles part.
    /// These defaults apply to ALL paragraphs and runs unless overridden by a style or direct formatting.
    /// </summary>
    /// <remarks>
    /// Produces in styles.xml:
    /// <code>
    /// &lt;w:docDefaults&gt;
    ///   &lt;w:rPrDefault&gt;
    ///     &lt;w:rPr&gt;
    ///       &lt;w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="SimSun" w:cs="Arial"/&gt;
    ///       &lt;w:sz w:val="22"/&gt;
    ///       &lt;w:szCs w:val="22"/&gt;
    ///       &lt;w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/&gt;
    ///     &lt;/w:rPr&gt;
    ///   &lt;/w:rPrDefault&gt;
    ///   &lt;w:pPrDefault&gt;
    ///     &lt;w:pPr&gt;
    ///       &lt;w:spacing w:after="160" w:line="259" w:lineRule="auto"/&gt;
    ///     &lt;/w:pPr&gt;
    ///   &lt;/w:pPrDefault&gt;
    /// &lt;/w:docDefaults&gt;
    /// </code>
    /// </remarks>
    public static void SetDocDefaults(MainDocumentPart mainPart)
    {
        // Ensure StyleDefinitionsPart exists
        var stylesPart = mainPart.StyleDefinitionsPart
            ?? mainPart.AddNewPart<StyleDefinitionsPart>();
        stylesPart.Styles ??= new Styles();

        var docDefaults = new DocDefaults();

        // ── Run Properties Default ──
        // These become the "base" formatting for all text in the document
        var runPropsDefault = new RunPropertiesDefault(
            new RunPropertiesBaseStyle(
                // RunFonts has 4 slots for different Unicode ranges:
                //   Ascii    — Latin characters (U+0000–U+007F)
                //   HighAnsi — extended Latin (U+0080–U+FFFF, non-EastAsian)
                //   EastAsia — CJK characters
                //   ComplexScript — RTL scripts (Arabic, Hebrew, etc.)
                new RunFonts
                {
                    Ascii = "Calibri",
                    HighAnsi = "Calibri",
                    EastAsia = "SimSun",        // 宋体 — standard CJK body font
                    ComplexScript = "Arial"
                },
                // Font size is in HALF-POINTS: 22 half-pt = 11pt
                new FontSize { Val = "22" },
                // Complex script size (for Arabic/Hebrew text)
                new FontSizeComplexScript { Val = "22" },
                // Language tags control spell-check and hyphenation
                new Languages
                {
                    Val = "en-US",
                    EastAsia = "zh-CN",
                    Bidi = "ar-SA"
                }
            )
        );

        // ── Paragraph Properties Default ──
        // Spacing that applies to all paragraphs unless overridden
        var paraPropsDefault = new ParagraphPropertiesDefault(
            new ParagraphPropertiesBaseStyle(
                new SpacingBetweenLines
                {
                    // After = space after paragraph in DXA twentieths-of-a-point
                    // 160 DXA = 8pt after each paragraph (Word 2016+ default)
                    After = "160",
                    // Line = line spacing:
                    //   For "auto" rule: value is in 240ths of a line
                    //   259 = 1.0791... ≈ 1.08 line spacing (Word's "single" with body text font)
                    //   For "exact"/"atLeast": value is in DXA twentieths-of-a-point
                    Line = "259",
                    LineRule = LineSpacingRuleValues.Auto
                }
            )
        );

        docDefaults.Append(runPropsDefault);
        docDefaults.Append(paraPropsDefault);

        // IMPORTANT: DocDefaults must be the FIRST child of w:styles.
        // If there are existing children, prepend it.
        var existingDocDefaults = stylesPart.Styles.DocDefaults;
        if (existingDocDefaults is not null)
        {
            existingDocDefaults.Remove();
        }
        stylesPart.Styles.PrependChild(docDefaults);
        stylesPart.Styles.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 6. DOCUMENT SETTINGS
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Adds document-level settings: zoom, default tab stop, proofing,
    /// compatibility options, field update behavior, and character spacing control.
    /// </summary>
    /// <remarks>
    /// Produces in word/settings.xml:
    /// <code>
    /// &lt;w:settings&gt;
    ///   &lt;w:zoom w:percent="100"/&gt;
    ///   &lt;w:defaultTabStop w:val="720"/&gt;
    ///   &lt;w:characterSpacingControl w:val="doNotCompress"/&gt;
    ///   &lt;w:proofState w:spelling="clean" w:grammar="clean"/&gt;
    ///   &lt;w:updateFields w:val="true"/&gt;
    ///   &lt;w:compat&gt;
    ///     &lt;w:compatSetting w:name="compatibilityMode" w:uri="..." w:val="15"/&gt;
    ///   &lt;/w:compat&gt;
    /// &lt;/w:settings&gt;
    /// </code>
    /// </remarks>
    public static void AddDocumentSettings(MainDocumentPart mainPart)
    {
        var settingsPart = mainPart.DocumentSettingsPart
            ?? mainPart.AddNewPart<DocumentSettingsPart>();
        settingsPart.Settings ??= new Settings();
        var settings = settingsPart.Settings;

        // ── Zoom level ──
        // 100 = 100%. Word remembers this for the next open.
        settings.Append(new Zoom { Percent = "100" });

        // ── Default tab stop ──
        // 720 DXA = 0.5 inch. This is the interval for default tab stops
        // across the entire document. Common values:
        //   720 = 0.5 inch (US default)
        //   420 = ~0.74cm (common in Chinese docs)
        settings.Append(new DefaultTabStop { Val = 720 });

        // ── Character spacing control ──
        // Controls how CJK character spacing is handled
        //   DoNotCompress — no compression of punctuation
        //   CompressPunctuation — compress CJK punctuation at line start/end
        //   CompressPunctuationAndJapaneseKanaWhitespace — full CJK compression
        settings.Append(new CharacterSpacingControl
        {
            Val = CharacterSpacingValues.DoNotCompress
        });

        // ── Proofing state ──
        // Tells Word that spell/grammar check is clean; avoids the squiggly-line
        // check running immediately on open
        settings.Append(new ProofState
        {
            Spelling = ProofingStateValues.Clean,
            Grammar = ProofingStateValues.Clean
        });

        // ── Update fields on open ──
        // WARNING: Setting this to true causes Word to prompt "This document contains
        // fields that may refer to other files. Do you want to update the fields?"
        // Useful for TOC/TOF fields that need refreshing
        settings.Append(new UpdateFieldsOnOpen { Val = true });

        // ── Compatibility settings ──
        // compatibilityMode = 15 means "Word 2013+ mode" — the highest stable mode.
        // This controls layout behavior: line breaking, table widths, spacing, etc.
        // WARNING: Using a lower value (e.g., 11 for Word 2003) changes layout
        // significantly and is almost never what you want.
        var compat = new Compatibility();
        compat.Append(new CompatibilitySetting
        {
            Name = CompatSettingNameValues.CompatibilityMode,
            Uri = "http://schemas.microsoft.com/office/word",
            Val = "15"
        });
        // Additional CJK compatibility settings
        compat.Append(new CompatibilitySetting
        {
            Name = CompatSettingNameValues.OverrideTableStyleFontSizeAndJustification,
            Uri = "http://schemas.microsoft.com/office/word",
            Val = "1"
        });
        compat.Append(new CompatibilitySetting
        {
            Name = CompatSettingNameValues.EnableOpenTypeFeatures,
            Uri = "http://schemas.microsoft.com/office/word",
            Val = "1"
        });
        settings.Append(compat);

        settings.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 7. DOCUMENT PROPERTIES (metadata)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Sets core properties (Dublin Core: title, author, dates),
    /// extended properties (company, application name),
    /// and custom properties (arbitrary key-value pairs).
    /// </summary>
    /// <remarks>
    /// Core properties go into docProps/core.xml (Dublin Core + CP namespaces).
    /// Extended properties go into docProps/app.xml.
    /// Custom properties go into docProps/custom.xml.
    /// </remarks>
    public static void SetDocumentProperties(WordprocessingDocument doc)
    {
        // ── Core Properties ──
        // These map to Dublin Core metadata elements in docProps/core.xml
        doc.PackageProperties.Title = "Quarterly Report";
        doc.PackageProperties.Subject = "Financial Summary";
        doc.PackageProperties.Creator = "MiniMax AI";          // Author
        doc.PackageProperties.Keywords = "report, finance, Q4";
        doc.PackageProperties.Description = "Auto-generated financial report";
        doc.PackageProperties.Category = "Reports";
        doc.PackageProperties.ContentStatus = "Draft";

        // Dates — PackageProperties uses DateTimeOffset?
        doc.PackageProperties.Created = DateTimeOffset.UtcNow.DateTime;
        doc.PackageProperties.Modified = DateTimeOffset.UtcNow.DateTime;
        doc.PackageProperties.LastModifiedBy = "DocBuilder Agent";

        // ── Extended Properties ──
        // These go into docProps/app.xml
        var extendedProps = doc.AddExtendedFilePropertiesPart();
        extendedProps.Properties = new DocumentFormat.OpenXml.ExtendedProperties.Properties
        {
            Company = new Company("MiniMax Inc."),
            Application = new Application("MiniMaxAIDocx"),
            ApplicationVersion = new ApplicationVersion("1.0.0")
        };
        extendedProps.Properties.Save();

        // ── Custom Properties ──
        // Arbitrary key-value pairs; visible in File > Properties > Custom in Word
        var customProps = doc.AddCustomFilePropertiesPart();
        customProps.Properties = new DocumentFormat.OpenXml.CustomProperties.Properties();

        // Each custom property needs a unique PID starting at 2
        // (PID 0 and 1 are reserved by the system)
        int pid = 2;

        // String property
        customProps.Properties.Append(new CustomDocumentProperty
        {
            FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            PropertyId = pid++,
            Name = "Department",
            VTLPWSTR = new VTLPWSTR("Engineering")
        });

        // Integer property
        customProps.Properties.Append(new CustomDocumentProperty
        {
            FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            PropertyId = pid++,
            Name = "ReviewCount",
            VTInt32 = new VTInt32("3")
        });

        // Boolean property
        customProps.Properties.Append(new CustomDocumentProperty
        {
            FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            PropertyId = pid++,
            Name = "IsApproved",
            VTBool = new VTBool("true")
        });

        // Date property
        customProps.Properties.Append(new CustomDocumentProperty
        {
            FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            PropertyId = pid++,
            Name = "ReviewDate",
            VTFileTime = new VTFileTime(DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
        });

        customProps.Properties.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 8. PAGE SETUP (sizes, margins, orientation)
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a document demonstrating various page setups:
    /// A4/Letter sizes, standard/narrow/wide/公文 margins,
    /// and both portrait and landscape orientations (as separate sections).
    /// </summary>
    public static void CreateDocumentWithPageSetup(string path)
    {
        using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);
        var mainPart = doc.AddMainDocumentPart();

        var body = new Body();

        // ════════════════════════════════════════════════════════════
        // SECTION 1: A4 Portrait with Standard Margins (1 inch all)
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Section 1: A4 Portrait, Standard Margins"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text("Standard 1-inch margins all around.")))
        );

        // IMPORTANT: This is a "continuous" section break that ends section 1.
        // The sectPr inside a pPr defines the properties FOR THE PRECEDING section.
        // The FINAL section's properties are in the body-level sectPr.
        body.Append(
            new Paragraph(
                new ParagraphProperties(
                    new SectionProperties(
                        new WpPageSize
                        {
                            // A4: 210mm x 297mm = 11906 x 16838 DXA
                            Width = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                            Height = (UInt32Value)(uint)PageSizes.A4.HeightDxa
                            // IMPORTANT: No Orient attribute = portrait (default)
                        },
                        new PageMargin
                        {
                            Top = PageSizes.StandardMargins.TopDxa,     // 1440 = 1 inch
                            Right = (UInt32Value)(uint)PageSizes.StandardMargins.RightDxa,
                            Bottom = PageSizes.StandardMargins.BottomDxa,
                            Left = (UInt32Value)(uint)PageSizes.StandardMargins.LeftDxa,
                            Header = (UInt32Value)720U,
                            Footer = (UInt32Value)720U,
                            Gutter = (UInt32Value)0U
                        }
                    )
                )
            )
        );

        // ════════════════════════════════════════════════════════════
        // SECTION 2: Letter Portrait with Narrow Margins
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Section 2: Letter Portrait, Narrow Margins"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text("Narrow 0.5-inch margins for maximum content area.")))
        );

        body.Append(
            new Paragraph(
                new ParagraphProperties(
                    new SectionProperties(
                        new WpPageSize
                        {
                            // US Letter: 8.5" x 11" = 12240 x 15840 DXA
                            Width = (UInt32Value)(uint)PageSizes.Letter.WidthDxa,
                            Height = (UInt32Value)(uint)PageSizes.Letter.HeightDxa
                        },
                        new PageMargin
                        {
                            Top = PageSizes.NarrowMargins.TopDxa,       // 720 = 0.5 inch
                            Right = (UInt32Value)(uint)PageSizes.NarrowMargins.RightDxa,
                            Bottom = PageSizes.NarrowMargins.BottomDxa,
                            Left = (UInt32Value)(uint)PageSizes.NarrowMargins.LeftDxa,
                            Header = (UInt32Value)720U,
                            Footer = (UInt32Value)720U,
                            Gutter = (UInt32Value)0U
                        }
                    )
                )
            )
        );

        // ════════════════════════════════════════════════════════════
        // SECTION 3: A4 Landscape with Wide Margins
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Section 3: A4 Landscape, Wide Margins"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text("Landscape orientation — width and height are SWAPPED.")))
        );

        body.Append(
            new Paragraph(
                new ParagraphProperties(
                    new SectionProperties(
                        new WpPageSize
                        {
                            // IMPORTANT: For landscape, SWAP width and height values
                            // AND set Orient = Landscape
                            Width = (UInt32Value)(uint)PageSizes.A4.HeightDxa,   // 16838 (was height)
                            Height = (UInt32Value)(uint)PageSizes.A4.WidthDxa,   // 11906 (was width)
                            Orient = PageOrientationValues.Landscape
                        },
                        new PageMargin
                        {
                            // Wide margins: 1" top/bottom, 1.5" left/right
                            Top = PageSizes.WideMargins.TopDxa,        // 1440
                            Right = (UInt32Value)(uint)PageSizes.WideMargins.RightDxa, // 2160
                            Bottom = PageSizes.WideMargins.BottomDxa,  // 1440
                            Left = (UInt32Value)(uint)PageSizes.WideMargins.LeftDxa,   // 2160
                            Header = (UInt32Value)720U,
                            Footer = (UInt32Value)720U,
                            Gutter = (UInt32Value)0U
                        }
                    )
                )
            )
        );

        // ════════════════════════════════════════════════════════════
        // SECTION 4 (FINAL): A4 Portrait with Chinese 公文 Margins
        // ════════════════════════════════════════════════════════════
        // Chinese government document standard (GB/T 9704-2012):
        //   Page: A4 (210mm x 297mm)
        //   Top: 37mm ≈ 2098 DXA    Bottom: 35mm ≈ 1984 DXA
        //   Left: 28mm ≈ 1587 DXA   Right: 26mm ≈ 1474 DXA
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Section 4: A4 Portrait, 公文 Margins (GB/T 9704)"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text("Chinese government document standard margins.")))
        );

        // The FINAL section's SectionProperties goes as a direct child of Body (not in pPr)
        body.Append(
            new SectionProperties(
                new WpPageSize
                {
                    Width = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                    Height = (UInt32Value)(uint)PageSizes.A4.HeightDxa
                },
                new PageMargin
                {
                    // 公文 margins per GB/T 9704-2012
                    Top = UnitConverter.CmToDxa(3.7),        // 37mm top
                    Right = (UInt32Value)(uint)UnitConverter.CmToDxa(2.6),  // 26mm right
                    Bottom = UnitConverter.CmToDxa(3.5),     // 35mm bottom
                    Left = (UInt32Value)(uint)UnitConverter.CmToDxa(2.8),   // 28mm left
                    Header = (UInt32Value)(uint)UnitConverter.CmToDxa(1.5), // 15mm header
                    Footer = (UInt32Value)(uint)UnitConverter.CmToDxa(1.75),// 17.5mm footer
                    Gutter = (UInt32Value)0U
                },
                // Document grid for Chinese text layout:
                // 28 lines per page, 28 characters per line (公文 standard)
                new DocGrid
                {
                    Type = DocGridValues.LinesAndChars,
                    LinePitch = 579,       // vertical pitch in DXA: ~28 lines on A4
                    CharacterSpace = 210   // character spacing adjustment
                }
            )
        );

        mainPart.Document = new Document(body);
        mainPart.Document.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // 9. MULTI-SECTION DOCUMENT
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a document with three sections demonstrating:
    /// - Portrait intro with "first page" header
    /// - Landscape table section with different header
    /// - Portrait conclusion with page number restart
    /// Each section has its own headers and page numbering.
    /// </summary>
    public static void CreateMultiSectionDocument(string path)
    {
        using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);
        var mainPart = doc.AddMainDocumentPart();

        // ── Create headers for each section ──
        // Each section can reference its own header/footer parts.

        // --- Section 1 headers: "first page" + "default" ---
        var header1Default = CreateHeaderPart(mainPart, "Introduction — Page ");
        var header1FirstPage = CreateHeaderPart(mainPart, "CONFIDENTIAL DRAFT");

        // --- Section 2 header: landscape section ---
        var header2Default = CreateHeaderPart(mainPart, "Data Tables — Landscape View");

        // --- Section 3 header: conclusion ---
        var header3Default = CreateHeaderPart(mainPart, "Conclusion — Page ");

        var body = new Body();

        // ════════════════════════════════════════════════════════════
        // SECTION 1: Portrait Introduction
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Introduction"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text(
                "This section uses portrait orientation with a special first-page header.")))
        );
        body.Append(
            new Paragraph(new Run(new Text(
                "The first page shows 'CONFIDENTIAL DRAFT', subsequent pages show the section name.")))
        );

        // Section 1 properties (embedded in paragraph = section break)
        var sect1Props = new SectionProperties(
            // Header references link to header parts via relationship IDs
            // HeaderFooterType: Default = all pages, First = first page only, Even = even pages
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header1Default)
            },
            new HeaderReference
            {
                Type = HeaderFooterValues.First,
                Id = mainPart.GetIdOfPart(header1FirstPage)
            },
            // IMPORTANT: SectionType controls how the section break renders:
            //   NextPage — starts on a new page (default if omitted)
            //   Continuous — no page break, flows on same page
            //   EvenPage / OddPage — starts on next even/odd page
            new SectionType { Val = SectionMarkValues.NextPage },
            new WpPageSize
            {
                Width = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                Height = (UInt32Value)(uint)PageSizes.A4.HeightDxa
            },
            new PageMargin
            {
                Top = 1440, Right = (UInt32Value)1440U, Bottom = 1440,
                Left = (UInt32Value)1440U, Header = (UInt32Value)720U,
                Footer = (UInt32Value)720U, Gutter = (UInt32Value)0U
            },
            // PageNumberType: start numbering from 1
            new PageNumberType { Start = 1 },
            // TitlePage: enables the "Different First Page" header/footer
            // Without this, the First header reference is ignored!
            new TitlePage()
        );

        body.Append(new Paragraph(new ParagraphProperties(sect1Props)));

        // ════════════════════════════════════════════════════════════
        // SECTION 2: Landscape Data Tables
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Data Tables"))
            )
        );

        // Add a simple table to justify landscape orientation
        var table = new Table(
            new TableProperties(
                new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
                new TableBorders(
                    new TopBorder { Val = BorderValues.Single, Size = 4 },
                    new BottomBorder { Val = BorderValues.Single, Size = 4 },
                    new LeftBorder { Val = BorderValues.Single, Size = 4 },
                    new RightBorder { Val = BorderValues.Single, Size = 4 },
                    new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4 },
                    new InsideVerticalBorder { Val = BorderValues.Single, Size = 4 }
                )
            ),
            new TableGrid(
                new GridColumn { Width = "3000" },
                new GridColumn { Width = "3000" },
                new GridColumn { Width = "3000" }
            ),
            // Header row
            new TableRow(
                new TableCell(new Paragraph(new Run(new Text("Column A")))),
                new TableCell(new Paragraph(new Run(new Text("Column B")))),
                new TableCell(new Paragraph(new Run(new Text("Column C"))))
            ),
            // Data row
            new TableRow(
                new TableCell(new Paragraph(new Run(new Text("Data 1")))),
                new TableCell(new Paragraph(new Run(new Text("Data 2")))),
                new TableCell(new Paragraph(new Run(new Text("Data 3"))))
            )
        );
        body.Append(table);

        // Section 2 properties (landscape)
        var sect2Props = new SectionProperties(
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header2Default)
            },
            new SectionType { Val = SectionMarkValues.NextPage },
            new WpPageSize
            {
                // IMPORTANT: Landscape = swap width/height AND set Orient
                Width = (UInt32Value)(uint)PageSizes.A4.HeightDxa,
                Height = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                Orient = PageOrientationValues.Landscape
            },
            new PageMargin
            {
                Top = 1440, Right = (UInt32Value)1440U, Bottom = 1440,
                Left = (UInt32Value)1440U, Header = (UInt32Value)720U,
                Footer = (UInt32Value)720U, Gutter = (UInt32Value)0U
            },
            // Continue page numbering from previous section (no Start attribute)
            new PageNumberType()
        );

        body.Append(new Paragraph(new ParagraphProperties(sect2Props)));

        // ════════════════════════════════════════════════════════════
        // SECTION 3 (FINAL): Portrait Conclusion with Restart Numbering
        // ════════════════════════════════════════════════════════════
        body.Append(
            new Paragraph(
                new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }),
                new Run(new Text("Conclusion"))
            )
        );
        body.Append(
            new Paragraph(new Run(new Text(
                "This section restarts page numbering from 1.")))
        );

        // Final section: SectionProperties as direct child of Body
        body.Append(
            new SectionProperties(
                new HeaderReference
                {
                    Type = HeaderFooterValues.Default,
                    Id = mainPart.GetIdOfPart(header3Default)
                },
                new WpPageSize
                {
                    Width = (UInt32Value)(uint)PageSizes.A4.WidthDxa,
                    Height = (UInt32Value)(uint)PageSizes.A4.HeightDxa
                },
                new PageMargin
                {
                    Top = 1440, Right = (UInt32Value)1440U, Bottom = 1440,
                    Left = (UInt32Value)1440U, Header = (UInt32Value)720U,
                    Footer = (UInt32Value)720U, Gutter = (UInt32Value)0U
                },
                // Restart page numbering from 1 for this section
                new PageNumberType { Start = 1 }
            )
        );

        mainPart.Document = new Document(body);
        mainPart.Document.Save();
    }

    // ────────────────────────────────────────────────────────────────────
    // HELPER: Create a header part with text and optional page number field
    // ────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Creates a HeaderPart with the given text. If the text ends with a space,
    /// a PAGE field is appended to show the page number.
    /// </summary>
    private static HeaderPart CreateHeaderPart(MainDocumentPart mainPart, string text)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();
        var header = new Header();

        var para = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }
            )
        );

        // Add the text run
        para.Append(new Run(
            new RunProperties(
                new FontSize { Val = "18" } // 9pt for header text
            ),
            new Text(text) { Space = SpaceProcessingModeValues.Preserve }
        ));

        // If text ends with space, add a PAGE field (auto page number)
        if (text.EndsWith(' '))
        {
            // PAGE field uses three runs: begin, instruction, end
            // This is the "complex field" pattern used by Word
            para.Append(new Run(
                new RunProperties(new FontSize { Val = "18" }),
                new FieldChar { FieldCharType = FieldCharValues.Begin }
            ));
            para.Append(new Run(
                new RunProperties(new FontSize { Val = "18" }),
                new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }
            ));
            para.Append(new Run(
                new RunProperties(new FontSize { Val = "18" }),
                new FieldChar { FieldCharType = FieldCharValues.End }
            ));
        }

        header.Append(para);
        headerPart.Header = header;
        headerPart.Header.Save();
        return headerPart;
    }
}
