using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Comprehensive reference for OpenXML headers, footers, and page numbers.
///
/// Architecture:
/// - Headers/footers live in separate HeaderPart/FooterPart containers.
/// - They are linked to sections via HeaderReference/FooterReference in SectionProperties.
/// - Each reference has a Type: Default, First, Even.
/// - The relationship ID (r:id) connects the reference to the part.
///
/// XML structure in SectionProperties:
/// <w:sectPr>
///   <w:headerReference w:type="default" r:id="rId7"/>
///   <w:footerReference w:type="default" r:id="rId8"/>
///   <w:headerReference w:type="first" r:id="rId9"/>
///   <w:titlePg/>   <!-- needed to activate first-page header/footer -->
/// </w:sectPr>
///
/// Header/Footer XML (in separate part):
/// <w:hdr>           (or <w:ftr>)
///   <w:p>
///     <w:pPr>...</w:pPr>
///     <w:r><w:t>Header text</w:t></w:r>
///   </w:p>
/// </w:hdr>
///
/// Page number fields use complex field codes:
///   PAGE     — current page number
///   NUMPAGES — total page count
/// </summary>
public static class HeaderFooterSamples
{
    // ──────────────────────────────────────────────────────────────
    // 1. AddSimpleHeader — basic text header
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a simple text header to the default header slot.
    ///
    /// Steps:
    ///   1. Create a HeaderPart on the MainDocumentPart
    ///   2. Set its Header content (must contain at least one Paragraph)
    ///   3. Get the relationship ID
    ///   4. Add HeaderReference to SectionProperties with type="default"
    ///
    /// XML in header part:
    /// <w:hdr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="right"/></w:pPr>
    ///     <w:r>
    ///       <w:rPr><w:color w:val="808080"/><w:sz w:val="18"/></w:rPr>
    ///       <w:t>My Document Header</w:t>
    ///     </w:r>
    ///   </w:p>
    /// </w:hdr>
    ///
    /// XML in sectPr:
    /// <w:headerReference w:type="default" r:id="rIdXX"/>
    /// </summary>
    public static void AddSimpleHeader(MainDocumentPart mainPart, SectionProperties sectPr, string text)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();

        headerPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Right }),
                new Run(
                    new RunProperties(
                        new Color { Val = "808080" },
                        new FontSize { Val = "18" }),   // 9pt (half-points)
                    new Text(text) { Space = SpaceProcessingModeValues.Preserve })));
        headerPart.Header.Save();

        var headerRefId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 2. AddSimpleFooter — basic text footer
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a simple text footer to the default footer slot.
    ///
    /// XML in footer part:
    /// <w:ftr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="center"/></w:pPr>
    ///     <w:r><w:t>Confidential</w:t></w:r>
    ///   </w:p>
    /// </w:ftr>
    ///
    /// XML in sectPr:
    /// <w:footerReference w:type="default" r:id="rIdXX"/>
    /// </summary>
    public static void AddSimpleFooter(MainDocumentPart mainPart, SectionProperties sectPr, string text)
    {
        var footerPart = mainPart.AddNewPart<FooterPart>();

        footerPart.Footer = new Footer(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center }),
                new Run(
                    new RunProperties(
                        new Color { Val = "808080" },
                        new FontSize { Val = "18" }),
                    new Text(text) { Space = SpaceProcessingModeValues.Preserve })));
        footerPart.Footer.Save();

        var footerRefId = mainPart.GetIdOfPart(footerPart);
        sectPr.Append(new FooterReference
        {
            Type = HeaderFooterValues.Default,
            Id = footerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 3. AddPageNumberFooter — centered page number
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a centered page number footer using the PAGE field code.
    ///
    /// Field code pattern (3 runs):
    ///   Run 1: FieldChar Begin
    ///   Run 2: FieldCode " PAGE "
    ///   Run 3: FieldChar End
    ///
    /// XML:
    /// <w:ftr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="center"/></w:pPr>
    ///     <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    ///     <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    ///     <w:r><w:fldChar w:fldCharType="end"/></w:r>
    ///   </w:p>
    /// </w:ftr>
    ///
    /// GOTCHA: FieldCode text MUST have leading/trailing spaces: " PAGE ", not "PAGE".
    /// GOTCHA: Use Space = SpaceProcessingModeValues.Preserve on FieldCode to keep spaces.
    /// </summary>
    public static void AddPageNumberFooter(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        var footerPart = mainPart.AddNewPart<FooterPart>();

        var paragraph = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }));

        // PAGE field: Begin → InstrText → End
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        paragraph.Append(new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }));
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));

        footerPart.Footer = new Footer(paragraph);
        footerPart.Footer.Save();

        var footerRefId = mainPart.GetIdOfPart(footerPart);
        sectPr.Append(new FooterReference
        {
            Type = HeaderFooterValues.Default,
            Id = footerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 4. AddPageXofYFooter — "Page X of Y"
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a footer with "Page X of Y" format using PAGE and NUMPAGES field codes.
    ///
    /// XML:
    /// <w:ftr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="center"/></w:pPr>
    ///     <w:r><w:t xml:space="preserve">Page </w:t></w:r>
    ///     <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    ///     <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    ///     <w:r><w:fldChar w:fldCharType="end"/></w:r>
    ///     <w:r><w:t xml:space="preserve"> of </w:t></w:r>
    ///     <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    ///     <w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>
    ///     <w:r><w:fldChar w:fldCharType="end"/></w:r>
    ///   </w:p>
    /// </w:ftr>
    /// </summary>
    public static void AddPageXofYFooter(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        var footerPart = mainPart.AddNewPart<FooterPart>();

        var paragraph = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }));

        // "Page "
        paragraph.Append(new Run(new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }));

        // PAGE field
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        paragraph.Append(new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }));
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));

        // " of "
        paragraph.Append(new Run(new Text(" of ") { Space = SpaceProcessingModeValues.Preserve }));

        // NUMPAGES field
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        paragraph.Append(new Run(new FieldCode(" NUMPAGES ") { Space = SpaceProcessingModeValues.Preserve }));
        paragraph.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));

        footerPart.Footer = new Footer(paragraph);
        footerPart.Footer.Save();

        var footerRefId = mainPart.GetIdOfPart(footerPart);
        sectPr.Append(new FooterReference
        {
            Type = HeaderFooterValues.Default,
            Id = footerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 5. AddDifferentFirstPageHeader — TitlePage element
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a different header for the first page vs. subsequent pages.
    ///
    /// Requires:
    ///   1. <w:titlePg/> in SectionProperties to enable first-page header/footer
    ///   2. HeaderReference with Type="first" for the first page header
    ///   3. HeaderReference with Type="default" for subsequent pages
    ///
    /// XML in sectPr:
    /// <w:sectPr>
    ///   <w:headerReference w:type="first" r:id="rIdFirst"/>
    ///   <w:headerReference w:type="default" r:id="rIdDefault"/>
    ///   <w:titlePg/>   <!-- CRITICAL: without this, first-page header is ignored -->
    /// </w:sectPr>
    ///
    /// GOTCHA: Without <w:titlePg/>, the "first" type header is completely ignored.
    /// GOTCHA: If you want a blank first-page header, you still need a HeaderPart
    /// with an empty Paragraph — just don't add text to it.
    /// </summary>
    public static void AddDifferentFirstPageHeader(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        // First page header: e.g., cover page with large title
        var firstHeaderPart = mainPart.AddNewPart<HeaderPart>();
        firstHeaderPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center }),
                new Run(
                    new RunProperties(
                        new Bold(),
                        new FontSize { Val = "32" }),   // 16pt
                    new Text("COMPANY CONFIDENTIAL"))));
        firstHeaderPart.Header.Save();

        // Default header for subsequent pages
        var defaultHeaderPart = mainPart.AddNewPart<HeaderPart>();
        defaultHeaderPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Right }),
                new Run(
                    new RunProperties(
                        new FontSize { Val = "18" }),   // 9pt
                    new Text("Internal Document"))));
        defaultHeaderPart.Header.Save();

        // Link both headers to section
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.First,
            Id = mainPart.GetIdOfPart(firstHeaderPart)
        });
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = mainPart.GetIdOfPart(defaultHeaderPart)
        });

        // CRITICAL: Enable first page header/footer
        sectPr.Append(new TitlePage());
    }

    // ──────────────────────────────────────────────────────────────
    // 6. AddEvenOddHeaders — EvenAndOddHeaders in Settings
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates different headers for even and odd pages (e.g., for book-style printing).
    ///
    /// Requires:
    ///   1. <w:evenAndOddHeaders/> in document Settings (DocumentSettingsPart)
    ///   2. HeaderReference with Type="default" for odd pages
    ///   3. HeaderReference with Type="even" for even pages
    ///
    /// XML in settings.xml:
    /// <w:settings>
    ///   <w:evenAndOddHeaders/>
    /// </w:settings>
    ///
    /// XML in sectPr:
    /// <w:sectPr>
    ///   <w:headerReference w:type="default" r:id="rIdOdd"/>
    ///   <w:headerReference w:type="even" r:id="rIdEven"/>
    /// </w:sectPr>
    ///
    /// GOTCHA: "default" means ODD pages when evenAndOddHeaders is enabled.
    /// GOTCHA: Without the Settings flag, the "even" header is ignored entirely.
    /// </summary>
    public static void AddEvenOddHeaders(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        // Enable even/odd header distinction in document settings
        var settingsPart = mainPart.DocumentSettingsPart
                           ?? mainPart.AddNewPart<DocumentSettingsPart>();
        if (settingsPart.Settings == null)
            settingsPart.Settings = new Settings();

        // Add EvenAndOddHeaders if not already present
        if (settingsPart.Settings.GetFirstChild<EvenAndOddHeaders>() == null)
        {
            settingsPart.Settings.Append(new EvenAndOddHeaders());
        }
        settingsPart.Settings.Save();

        // Odd page header (Type="default" means odd when even/odd is enabled)
        var oddHeaderPart = mainPart.AddNewPart<HeaderPart>();
        oddHeaderPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Right }),
                new Run(new Text("Chapter Title — Odd Page"))));
        oddHeaderPart.Header.Save();

        // Even page header
        var evenHeaderPart = mainPart.AddNewPart<HeaderPart>();
        evenHeaderPart.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Left }),
                new Run(new Text("Book Title — Even Page"))));
        evenHeaderPart.Header.Save();

        // Link to section
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,  // = odd pages
            Id = mainPart.GetIdOfPart(oddHeaderPart)
        });
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Even,
            Id = mainPart.GetIdOfPart(evenHeaderPart)
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 7. AddHeaderWithLogo — image in header
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a header containing an image (logo).
    ///
    /// Steps:
    ///   1. Create HeaderPart
    ///   2. Add ImagePart to the HeaderPart (NOT to MainDocumentPart)
    ///   3. Feed the image stream
    ///   4. Build Drawing element with inline image
    ///   5. Link HeaderPart to sectPr
    ///
    /// Image sizing uses EMU (English Metric Units):
    ///   914400 EMU = 1 inch
    ///   360000 EMU = 1 cm
    ///
    /// XML for inline image:
    /// <w:drawing>
    ///   <wp:inline distT="0" distB="0" distL="0" distR="0">
    ///     <wp:extent cx="914400" cy="457200"/>
    ///     <wp:docPr id="1" name="Logo"/>
    ///     <a:graphic>
    ///       <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
    ///         <pic:pic>
    ///           <pic:nvPicPr>...</pic:nvPicPr>
    ///           <pic:blipFill><a:blip r:embed="rIdImg"/></pic:blipFill>
    ///           <pic:spPr>...</pic:spPr>
    ///         </pic:pic>
    ///       </a:graphicData>
    ///     </a:graphic>
    ///   </wp:inline>
    /// </w:drawing>
    ///
    /// GOTCHA: The ImagePart must be added to the HeaderPart, not the MainDocumentPart.
    /// If you add it to MainDocumentPart, the relationship ID won't resolve in the header.
    /// </summary>
    public static void AddHeaderWithLogo(MainDocumentPart mainPart, SectionProperties sectPr, string imagePath)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();

        // Add image part to the HEADER part (not main document part)
        var imagePart = headerPart.AddImagePart(ImagePartType.Png);
        using (var stream = new FileStream(imagePath, FileMode.Open, FileAccess.Read))
        {
            imagePart.FeedData(stream);
        }
        var imageRelId = headerPart.GetIdOfPart(imagePart);

        // Image dimensions in EMU: 1 inch wide x 0.5 inch tall
        long widthEmu = 914400;    // 1 inch
        long heightEmu = 457200;   // 0.5 inch

        // Build the Drawing element with inline image
        var drawing = new Drawing(
            new DW.Inline(
                new DW.Extent { Cx = widthEmu, Cy = heightEmu },
                new DW.EffectExtent { LeftEdge = 0, TopEdge = 0, RightEdge = 0, BottomEdge = 0 },
                new DW.DocProperties { Id = 1U, Name = "Logo" },
                new A.Graphic(
                    new A.GraphicData(
                        new PIC.Picture(
                            new PIC.NonVisualPictureProperties(
                                new PIC.NonVisualDrawingProperties { Id = 0U, Name = "logo.png" },
                                new PIC.NonVisualPictureDrawingProperties()),
                            new PIC.BlipFill(
                                new A.Blip { Embed = imageRelId },
                                new A.Stretch(new A.FillRectangle())),
                            new PIC.ShapeProperties(
                                new A.Transform2D(
                                    new A.Offset { X = 0, Y = 0 },
                                    new A.Extents { Cx = widthEmu, Cy = heightEmu }),
                                new A.PresetGeometry(
                                    new A.AdjustValueList())
                                { Preset = A.ShapeTypeValues.Rectangle }))
                    ) { Uri = "http://schemas.openxmlformats.org/drawingml/2006/picture" })
            )
            {
                DistanceFromTop = 0U,
                DistanceFromBottom = 0U,
                DistanceFromLeft = 0U,
                DistanceFromRight = 0U
            });

        headerPart.Header = new Header(
            new Paragraph(new Run(drawing)));
        headerPart.Header.Save();

        var headerRefId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 8. AddTableLayoutHeader — 3-column invisible table
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a header with a 3-column invisible table for precise layout:
    ///   Left cell:   Logo placeholder text
    ///   Center cell: Document title (centered)
    ///   Right cell:  Page number (right-aligned)
    ///
    /// The table has no borders, so it's invisible but provides column alignment.
    ///
    /// XML structure:
    /// <w:hdr>
    ///   <w:tbl>
    ///     <w:tblPr>
    ///       <w:tblW w:w="5000" w:type="pct"/>
    ///       <w:tblBorders>
    ///         <w:top w:val="none"/> <w:left w:val="none"/> ...
    ///       </w:tblBorders>
    ///     </w:tblPr>
    ///     <w:tblGrid>
    ///       <w:gridCol w:w="3120"/> <w:gridCol w:w="3120"/> <w:gridCol w:w="3120"/>
    ///     </w:tblGrid>
    ///     <w:tr>
    ///       <w:tc> <!-- left: logo text -->  </w:tc>
    ///       <w:tc> <!-- center: title -->    </w:tc>
    ///       <w:tc> <!-- right: page num -->  </w:tc>
    ///     </w:tr>
    ///   </w:tbl>
    /// </w:hdr>
    /// </summary>
    public static void AddTableLayoutHeader(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();

        // Invisible table (no borders)
        var table = new Table();
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new BottomBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ),
            // Fixed layout so columns don't shift
            new TableLayout { Type = TableLayoutValues.Fixed });
        table.Append(tblPr);

        var grid = new TableGrid(
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" });
        table.Append(grid);

        var row = new TableRow();

        // Left cell: logo/company name
        var leftCell = new TableCell(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Left }),
                new Run(
                    new RunProperties(new Bold(), new FontSize { Val = "18" }),
                    new Text("ACME Corp"))));
        row.Append(leftCell);

        // Center cell: document title
        var centerCell = new TableCell(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center }),
                new Run(
                    new RunProperties(new FontSize { Val = "18" }),
                    new Text("Technical Report"))));
        row.Append(centerCell);

        // Right cell: page number
        var pageNumPara = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Right }));
        pageNumPara.Append(new Run(
            new RunProperties(new FontSize { Val = "18" }),
            new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }));
        pageNumPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        pageNumPara.Append(new Run(new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }));
        pageNumPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));

        var rightCell = new TableCell(pageNumPara);
        row.Append(rightCell);

        table.Append(row);

        headerPart.Header = new Header(table);
        headerPart.Header.Save();

        var headerRefId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 9. AddChineseGongWenFooter — "-X-" format, SimSun 14pt
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a Chinese government document (公文) style footer:
    ///   - Page number in "-X-" format (e.g., "- 1 -")
    ///   - Centered at bottom
    ///   - SimSun (宋体) font, 14pt (Chinese 四号)
    ///
    /// XML:
    /// <w:ftr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="center"/></w:pPr>
    ///     <w:r>
    ///       <w:rPr>
    ///         <w:rFonts w:ascii="SimSun" w:eastAsia="SimSun"/>
    ///         <w:sz w:val="28"/>
    ///       </w:rPr>
    ///       <w:t xml:space="preserve">- </w:t>
    ///     </w:r>
    ///     <w:r>..PAGE field..</w:r>
    ///     <w:r>
    ///       <w:rPr>...</w:rPr>
    ///       <w:t xml:space="preserve"> -</w:t>
    ///     </w:r>
    ///   </w:p>
    /// </w:ftr>
    ///
    /// Chinese font size reference:
    ///   四号 = 14pt = sz val="28" (half-points)
    ///   小四 = 12pt = sz val="24"
    ///   五号 = 10.5pt = sz val="21"
    /// </summary>
    public static void AddChineseGongWenFooter(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        var footerPart = mainPart.AddNewPart<FooterPart>();

        // Common run properties for the footer: SimSun 14pt (四号)
        // 14pt = 28 half-points
        RunProperties MakeGongWenRunProps() => new RunProperties(
            new RunFonts { Ascii = "SimSun", EastAsia = "SimSun", HighAnsi = "SimSun" },
            new FontSize { Val = "28" },
            new FontSizeComplexScript { Val = "28" });

        var paragraph = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }));

        // "- " prefix
        paragraph.Append(new Run(
            MakeGongWenRunProps(),
            new Text("- ") { Space = SpaceProcessingModeValues.Preserve }));

        // PAGE field with same formatting
        paragraph.Append(new Run(
            MakeGongWenRunProps(),
            new FieldChar { FieldCharType = FieldCharValues.Begin }));
        paragraph.Append(new Run(
            MakeGongWenRunProps(),
            new FieldCode(" PAGE ") { Space = SpaceProcessingModeValues.Preserve }));
        paragraph.Append(new Run(
            MakeGongWenRunProps(),
            new FieldChar { FieldCharType = FieldCharValues.End }));

        // " -" suffix
        paragraph.Append(new Run(
            MakeGongWenRunProps(),
            new Text(" -") { Space = SpaceProcessingModeValues.Preserve }));

        footerPart.Footer = new Footer(paragraph);
        footerPart.Footer.Save();

        var footerRefId = mainPart.GetIdOfPart(footerPart);
        sectPr.Append(new FooterReference
        {
            Type = HeaderFooterValues.Default,
            Id = footerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 10. AddHeaderWithHorizontalLine — bottom border line
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Adds a header with a horizontal line (bottom border) beneath the text.
    /// This is a common style: header text with a line separating it from content.
    ///
    /// The line is achieved via a paragraph bottom border in the header, NOT a
    /// separate drawing element.
    ///
    /// XML:
    /// <w:hdr>
    ///   <w:p>
    ///     <w:pPr>
    ///       <w:pBdr>
    ///         <w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/>
    ///       </w:pBdr>
    ///       <w:jc w:val="center"/>
    ///     </w:pPr>
    ///     <w:r><w:t>Document Header</w:t></w:r>
    ///   </w:p>
    /// </w:hdr>
    ///
    /// Border space attribute: space between text and border line, in points.
    /// Border size: in eighth-points (6 = 0.75pt).
    /// </summary>
    public static void AddHeaderWithHorizontalLine(MainDocumentPart mainPart, SectionProperties sectPr)
    {
        var headerPart = mainPart.AddNewPart<HeaderPart>();

        var paragraph = new Paragraph(
            new ParagraphProperties(
                new ParagraphBorders(
                    new BottomBorder
                    {
                        Val = BorderValues.Single,
                        Size = 6,            // 0.75pt line (in eighth-points)
                        Space = 1,           // 1pt spacing between text and line
                        Color = "000000"
                    }),
                new Justification { Val = JustificationValues.Center }),
            new Run(
                new RunProperties(
                    new Bold(),
                    new FontSize { Val = "20" }),   // 10pt
                new Text("Document Header")));

        headerPart.Header = new Header(paragraph);
        headerPart.Header.Save();

        var headerRefId = mainPart.GetIdOfPart(headerPart);
        sectPr.Append(new HeaderReference
        {
            Type = HeaderFooterValues.Default,
            Id = headerRefId
        });
    }

    // ──────────────────────────────────────────────────────────────
    // 11. ChangeHeaderPerSection — different headers per section
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a document with multiple sections, each having its own header.
    ///
    /// In OOXML, sections are delimited by SectionProperties:
    ///   - Inner sections: sectPr inside a Paragraph's ParagraphProperties (section break)
    ///   - Last section: sectPr as direct child of Body
    ///
    /// Each sectPr can reference different HeaderPart/FooterPart via its own
    /// HeaderReference/FooterReference elements.
    ///
    /// XML structure for multi-section document:
    /// <w:body>
    ///   <!-- Section 1 content -->
    ///   <w:p><w:r><w:t>Section 1 content</w:t></w:r></w:p>
    ///   <w:p>
    ///     <w:pPr>
    ///       <w:sectPr>                              <!-- Section 1 break -->
    ///         <w:headerReference w:type="default" r:id="rId_hdr1"/>
    ///         <w:type w:val="nextPage"/>
    ///       </w:sectPr>
    ///     </w:pPr>
    ///   </w:p>
    ///
    ///   <!-- Section 2 content -->
    ///   <w:p><w:r><w:t>Section 2 content</w:t></w:r></w:p>
    ///
    ///   <!-- Final section properties (last child of body) -->
    ///   <w:sectPr>
    ///     <w:headerReference w:type="default" r:id="rId_hdr2"/>
    ///   </w:sectPr>
    /// </w:body>
    ///
    /// GOTCHA: A section break sectPr is placed inside a paragraph's ParagraphProperties.
    /// The paragraph that contains the sectPr is the LAST paragraph of that section.
    ///
    /// GOTCHA: If a section does not have its own HeaderReference, it inherits
    /// the header from the previous section. To have NO header in a section,
    /// you must explicitly link to an empty HeaderPart.
    /// </summary>
    public static void ChangeHeaderPerSection(MainDocumentPart mainPart, Body body)
    {
        // --- Create two different header parts ---

        // Header for Section 1
        var header1Part = mainPart.AddNewPart<HeaderPart>();
        header1Part.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Left }),
                new Run(new Text("Section 1 — Introduction"))));
        header1Part.Header.Save();

        // Header for Section 2
        var header2Part = mainPart.AddNewPart<HeaderPart>();
        header2Part.Header = new Header(
            new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Left }),
                new Run(new Text("Section 2 — Analysis"))));
        header2Part.Header.Save();

        // --- Section 1 content ---
        body.Append(new Paragraph(
            new Run(new Text("This is content in Section 1."))));
        body.Append(new Paragraph(
            new Run(new Text("More Section 1 content..."))));

        // --- Section 1 break: sectPr inside a paragraph's pPr ---
        // This paragraph is the LAST paragraph of Section 1.
        var sect1Pr = new SectionProperties(
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header1Part)
            },
            // Section break type: start next section on a new page
            new SectionType { Val = SectionMarkValues.NextPage });

        // Page size and margins for section 1 (required for valid sectPr)
        sect1Pr.Append(new DocumentFormat.OpenXml.Wordprocessing.PageSize
        {
            Width = (UInt32Value)12240U,   // Letter width: 8.5" = 12240 DXA
            Height = (UInt32Value)15840U   // Letter height: 11" = 15840 DXA
        });
        sect1Pr.Append(new PageMargin
        {
            Top = 1440,
            Bottom = 1440,
            Left = (UInt32Value)1440U,
            Right = (UInt32Value)1440U
        });

        // Wrap the sectPr in a paragraph's ParagraphProperties
        var sectionBreakPara = new Paragraph(
            new ParagraphProperties(sect1Pr));
        body.Append(sectionBreakPara);

        // --- Section 2 content ---
        body.Append(new Paragraph(
            new Run(new Text("This is content in Section 2."))));
        body.Append(new Paragraph(
            new Run(new Text("More Section 2 content..."))));

        // --- Final section: sectPr as last child of Body ---
        // This is the sectPr for the LAST section of the document.
        var finalSectPr = new SectionProperties(
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header2Part)
            });
        finalSectPr.Append(new DocumentFormat.OpenXml.Wordprocessing.PageSize
        {
            Width = (UInt32Value)12240U,
            Height = (UInt32Value)15840U
        });
        finalSectPr.Append(new PageMargin
        {
            Top = 1440,
            Bottom = 1440,
            Left = (UInt32Value)1440U,
            Right = (UInt32Value)1440U
        });
        body.Append(finalSectPr);
    }
}
