// ============================================================================
// ImageSamples.cs — Comprehensive OpenXML image handling reference
// ============================================================================
// EMU (English Metric Unit) is the universal measurement in DrawingML:
//   1 inch   = 914400 EMU
//   1 cm     = 360000 EMU
//   1 px@96dpi = 9525 EMU  (914400 / 96 = 9525)
//
// Image architecture in OpenXML:
//   Paragraph → Run → Drawing → DW.Inline (or DW.Anchor)
//     → A.Graphic → A.GraphicData → PIC.Picture
//       → PIC.BlipFill → A.Blip (references the image part via r:embed)
//       → PIC.ShapeProperties → A.Transform2D → A.Extents (cx, cy)
//
// CRITICAL RULES:
//   1. Extent.Cx/Cy on DW.Inline/DW.Anchor MUST match A.Extents.Cx/Cy
//      on PIC.ShapeProperties. Mismatch causes rendering issues.
//   2. Each Drawing element needs a unique DocProperties.Id within the document.
//   3. ImagePart must be added to the PART that references it:
//      - MainDocumentPart for images in body
//      - HeaderPart for images in headers
//      - FooterPart for images in footers
//   4. Blip.Embed contains the relationship ID (rId) linking to the ImagePart.
// ============================================================================

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

using A = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Reference implementations for every common image operation in OpenXML.
/// All methods produce valid, Word-renderable markup.
/// </summary>
public static class ImageSamples
{
    // ── Constants ──────────────────────────────────────────────────────
    private const long EmuPerInch = 914400L;
    private const long EmuPerCm = 360000L;
    private const long EmuPerPixel96Dpi = 9525L; // 914400 / 96

    // GraphicData URI that tells Word "this is a picture"
    private const string PicGraphicDataUri = "http://schemas.openxmlformats.org/drawingml/2006/picture";

    // ── 1. Inline Image (most common) ──────────────────────────────────

    /// <summary>
    /// Inserts an inline image into the body. Inline images flow with text
    /// and do not float. This is the most common image insertion pattern.
    /// </summary>
    /// <param name="mainPart">The MainDocumentPart to add the image relationship to.</param>
    /// <param name="body">The Body element to append the paragraph to.</param>
    /// <param name="imagePath">Filesystem path to the image file (png, jpg, etc.).</param>
    /// <param name="widthPx">Desired display width in pixels (at 96 dpi).</param>
    /// <param name="heightPx">Desired display height in pixels (at 96 dpi).</param>
    public static void InsertInlineImage(
        MainDocumentPart mainPart, Body body,
        string imagePath, int widthPx, int heightPx)
    {
        // Step 1: Add the image file as a part. The ImagePartType must match
        // the actual file format. AddImagePart returns the ImagePart; we then
        // feed data into it.
        var imageType = GetImagePartType(imagePath);
        ImagePart imagePart = mainPart.AddImagePart(imageType);

        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }

        // Step 2: Get the relationship ID that links the Blip to this ImagePart.
        string relId = mainPart.GetIdOfPart(imagePart);

        // Step 3: Convert pixel dimensions to EMU.
        // Formula: pixels * 9525 = EMU (at 96 dpi, which is Word's assumption)
        long cx = widthPx * EmuPerPixel96Dpi;
        long cy = heightPx * EmuPerPixel96Dpi;

        // Step 4: Build the Drawing element using the reusable helper.
        // docPropId must be unique across the entire document.
        Drawing drawing = BuildDrawingElement(
            relId, cx, cy,
            docPropId: 1U,
            name: "Image1",
            description: null);

        // Step 5: Wrap in Paragraph → Run → Drawing
        Paragraph para = new Paragraph(
            new Run(drawing));

        body.AppendChild(para);
    }

    // ── 2. Floating Image (Anchor) ─────────────────────────────────────

    /// <summary>
    /// Inserts a floating image with absolute positioning using DW.Anchor.
    /// Floating images are positioned relative to a reference point (page,
    /// column, paragraph, etc.) and text wraps around them.
    /// </summary>
    public static void InsertFloatingImage(
        MainDocumentPart mainPart, Body body, string imagePath)
    {
        ImagePart imagePart = mainPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }
        string relId = mainPart.GetIdOfPart(imagePart);

        long cx = (long)(3.0 * EmuPerInch); // 3 inches wide
        long cy = (long)(2.0 * EmuPerInch); // 2 inches tall

        // DW.Anchor is used instead of DW.Inline for floating images.
        // Key differences from Inline:
        //   - Has positioning (SimplePos, HorizontalPosition, VerticalPosition)
        //   - Has wrapping mode (WrapSquare, WrapTight, WrapNone, etc.)
        //   - Has BehindDoc and LayoutInCell flags
        DW.Anchor anchor = new DW.Anchor(
            // SimplePosition: when SimplePos=true, uses SimplePosition x/y directly.
            // Normally false; we use HorizontalPosition/VerticalPosition instead.
            new DW.SimplePosition { X = 0L, Y = 0L },

            // HorizontalPosition: where the image sits horizontally.
            // RelativeFrom can be: Column, Page, Margin, Character, LeftMargin, etc.
            new DW.HorizontalPosition(
                new DW.PositionOffset("914400") // 1 inch from reference
            )
            { RelativeFrom = DW.HorizontalRelativePositionValues.Column },

            // VerticalPosition: where the image sits vertically.
            new DW.VerticalPosition(
                new DW.PositionOffset("457200") // 0.5 inch from reference
            )
            { RelativeFrom = DW.VerticalRelativePositionValues.Paragraph },

            // Extent: overall size of the drawing object
            new DW.Extent { Cx = cx, Cy = cy },

            // EffectExtent: extra space for shadows, glow, etc. (0 if none)
            new DW.EffectExtent
            {
                LeftEdge = 0L,
                TopEdge = 0L,
                RightEdge = 0L,
                BottomEdge = 0L
            },

            // WrapSquare: text wraps in a square around the image bounding box.
            new DW.WrapSquare { WrapText = DW.WrapTextValues.BothSides },

            // DocProperties: unique ID + name for the drawing object
            new DW.DocProperties { Id = 2U, Name = "FloatingImage1" },

            // Non-visual graphic frame properties (required but usually empty)
            new DW.NonVisualGraphicFrameDrawingProperties(
                new A.GraphicFrameLocks { NoChangeAspect = true }),

            // The actual graphic content
            new A.Graphic(
                new A.GraphicData(
                    new PIC.Picture(
                        new PIC.NonVisualPictureProperties(
                            new PIC.NonVisualDrawingProperties
                            {
                                Id = 0U,
                                Name = "FloatingImage1.png"
                            },
                            new PIC.NonVisualPictureDrawingProperties()),
                        new PIC.BlipFill(
                            new A.Blip { Embed = relId },
                            new A.Stretch(new A.FillRectangle())),
                        new PIC.ShapeProperties(
                            new A.Transform2D(
                                new A.Offset { X = 0L, Y = 0L },
                                // CRITICAL: These cx/cy MUST match the Extent above
                                new A.Extents { Cx = cx, Cy = cy }),
                            new A.PresetGeometry(
                                new A.AdjustValueList())
                            { Preset = A.ShapeTypeValues.Rectangle }))
                )
                { Uri = PicGraphicDataUri })
        )
        {
            // Anchor attributes
            DistanceFromTop = 0U,
            DistanceFromBottom = 0U,
            DistanceFromLeft = 114300U,  // ~0.125 inch gap between text and image
            DistanceFromRight = 114300U,
            SimplePos = false,
            RelativeHeight = 251658240U, // z-order; higher = in front
            BehindDoc = false,           // true = behind text (like a watermark)
            Locked = false,
            LayoutInCell = true,
            AllowOverlap = true
        };

        Paragraph para = new Paragraph(new Run(new Drawing(anchor)));
        body.AppendChild(para);
    }

    // ── 3. Image with Various Text Wrapping ────────────────────────────

    /// <summary>
    /// Demonstrates the four main text wrapping modes for floating images.
    /// Each wrapping mode controls how body text flows around the image.
    /// </summary>
    public static void InsertImageWithTextWrapping(
        MainDocumentPart mainPart, Body body, string imagePath)
    {
        // All wrapping modes require DW.Anchor (not DW.Inline).
        // The wrapping element is a direct child of the Anchor element.

        ImagePart imagePart = mainPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }
        string relId = mainPart.GetIdOfPart(imagePart);

        long cx = (long)(2.5 * EmuPerInch);
        long cy = (long)(2.0 * EmuPerInch);

        // ── WrapSquare ──
        // Text wraps in a rectangular bounding box around the image.
        // WrapText controls which sides text appears on.
        var wrapSquare = new DW.WrapSquare
        {
            WrapText = DW.WrapTextValues.BothSides
            // Other options: Left, Right, Largest
        };

        // ── WrapTight ──
        // Text wraps tightly around the actual contour of the image.
        // Uses a WrapPolygon to define the outline; Word can auto-generate this.
        // The coordinates are in EMU relative to the image's top-left.
        var wrapTight = new DW.WrapTight(
            new DW.WrapPolygon(
                new DW.StartPoint { X = 0L, Y = 0L },
                new DW.LineTo { X = 0L, Y = 21600L },
                new DW.LineTo { X = 21600L, Y = 21600L },
                new DW.LineTo { X = 21600L, Y = 0L },
                new DW.LineTo { X = 0L, Y = 0L }
            )
            { Edited = false }
        )
        {
            WrapText = DW.WrapTextValues.BothSides
        };

        // ── WrapTopAndBottom ──
        // No text appears beside the image. Text only above and below.
        // This effectively makes the image act as a block-level element
        // but still floating (not inline).
        var wrapTopAndBottom = new DW.WrapTopBottom
        {
            DistanceFromTop = 0U,
            DistanceFromBottom = 0U
        };

        // ── WrapNone ──
        // No text wrapping at all. Image floats over or behind text.
        // Combined with BehindDoc=true, this creates a watermark effect.
        var wrapNone = new DW.WrapNone();

        // Example: build anchor with WrapSquare (swap in any wrapping element above)
        DW.Anchor anchor = BuildAnchorElement(
            relId, cx, cy,
            docPropId: 3U,
            name: "WrappedImage",
            wrapElement: wrapSquare,
            behindDoc: false);

        body.AppendChild(new Paragraph(new Run(new Drawing(anchor))));
    }

    // ── 4. Image with Border ───────────────────────────────────────────

    /// <summary>
    /// Inserts an image with a visible outline/border. The border is applied
    /// via A.Outline on the PIC.ShapeProperties element.
    /// </summary>
    public static void InsertImageWithBorder(
        MainDocumentPart mainPart, Body body, string imagePath)
    {
        ImagePart imagePart = mainPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }
        string relId = mainPart.GetIdOfPart(imagePart);

        long cx = (long)(3.0 * EmuPerInch);
        long cy = (long)(2.0 * EmuPerInch);

        // Build PIC.ShapeProperties with an Outline element for the border.
        // Outline width is in EMU. 1pt = 12700 EMU.
        var shapeProperties = new PIC.ShapeProperties(
            new A.Transform2D(
                new A.Offset { X = 0L, Y = 0L },
                new A.Extents { Cx = cx, Cy = cy }),
            new A.PresetGeometry(
                new A.AdjustValueList())
            { Preset = A.ShapeTypeValues.Rectangle },
            // The Outline element defines the border
            new A.Outline(
                // SolidFill sets the border color
                new A.SolidFill(
                    new A.RgbColorModelHex { Val = "2F5496" }), // Dark blue
                // PresetDash sets the line style (solid, dash, dot, etc.)
                new A.PresetDash { Val = A.PresetLineDashValues.Solid }
            )
            {
                Width = 25400, // 2pt border (12700 EMU per pt)
                CompoundLineType = A.CompoundLineValues.Single
            }
        );

        var picture = new PIC.Picture(
            new PIC.NonVisualPictureProperties(
                new PIC.NonVisualDrawingProperties { Id = 0U, Name = "BorderedImage.png" },
                new PIC.NonVisualPictureDrawingProperties()),
            new PIC.BlipFill(
                new A.Blip { Embed = relId },
                new A.Stretch(new A.FillRectangle())),
            shapeProperties);

        var drawing = new Drawing(
            new DW.Inline(
                new DW.Extent { Cx = cx, Cy = cy },
                new DW.EffectExtent
                {
                    // Must account for border width in effect extent so it is not clipped
                    LeftEdge = 25400L,
                    TopEdge = 25400L,
                    RightEdge = 25400L,
                    BottomEdge = 25400L
                },
                new DW.DocProperties { Id = 4U, Name = "BorderedImage" },
                new DW.NonVisualGraphicFrameDrawingProperties(
                    new A.GraphicFrameLocks { NoChangeAspect = true }),
                new A.Graphic(
                    new A.GraphicData(picture)
                    { Uri = PicGraphicDataUri })
            )
            {
                DistanceFromTop = 0U,
                DistanceFromBottom = 0U,
                DistanceFromLeft = 0U,
                DistanceFromRight = 0U
            });

        body.AppendChild(new Paragraph(new Run(drawing)));
    }

    // ── 5. Image with Alt Text ─────────────────────────────────────────

    /// <summary>
    /// Inserts an image with alt text for accessibility. The alt text is set
    /// on the DocProperties.Description attribute. Screen readers use this.
    /// Word also shows it in the "Alt Text" pane.
    /// </summary>
    public static void InsertImageWithAltText(
        MainDocumentPart mainPart, Body body, string imagePath)
    {
        ImagePart imagePart = mainPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }
        string relId = mainPart.GetIdOfPart(imagePart);

        long cx = (long)(3.0 * EmuPerInch);
        long cy = (long)(2.0 * EmuPerInch);

        // DocProperties.Description is the standard alt text field.
        // DocProperties.Title is an optional short title shown in some UIs.
        Drawing drawing = BuildDrawingElement(
            relId, cx, cy,
            docPropId: 5U,
            name: "AccessibleImage",
            description: "A chart showing quarterly revenue growth from Q1 to Q4 2025");

        body.AppendChild(new Paragraph(new Run(drawing)));
    }

    // ── 6. Image in Header ─────────────────────────────────────────────

    /// <summary>
    /// Inserts an image into a header part. The image relationship MUST be
    /// added to the HeaderPart, NOT the MainDocumentPart. If you add it
    /// to MainDocumentPart, Word will show a broken image in the header
    /// because relationship IDs are scoped to their containing part.
    /// </summary>
    public static void InsertImageInHeader(HeaderPart headerPart, string imagePath)
    {
        // CRITICAL: AddImagePart to headerPart, not mainDocumentPart!
        // Each OpenXML part has its own relationship namespace.
        // An rId in the header must point to a relationship in the header's .rels file.
        ImagePart imagePart = headerPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }

        // GetIdOfPart must also be called on headerPart
        string relId = headerPart.GetIdOfPart(imagePart);

        long cx = (long)(1.5 * EmuPerInch); // Company logo, typically small
        long cy = (long)(0.5 * EmuPerInch);

        Drawing drawing = BuildDrawingElement(
            relId, cx, cy,
            docPropId: 6U,
            name: "HeaderLogo",
            description: "Company logo");

        // Headers use the Header element with Paragraph children (same as Body)
        Header header = headerPart.Header;
        Paragraph para = new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }),
            new Run(drawing));

        header.AppendChild(para);
    }

    // ── 7. Image in Table Cell ─────────────────────────────────────────

    /// <summary>
    /// Inserts an image into a table cell, sized to fit. Table cells constrain
    /// content width, so we calculate appropriate dimensions to avoid overflow.
    /// The image part is still added to MainDocumentPart (the cell is in the body).
    /// </summary>
    /// <param name="mainPart">MainDocumentPart (owns the relationship).</param>
    /// <param name="cell">The TableCell to insert the image into.</param>
    /// <param name="imagePath">Path to the image file.</param>
    public static void InsertImageInTableCell(
        MainDocumentPart mainPart, TableCell cell, string imagePath)
    {
        ImagePart imagePart = mainPart.AddImagePart(GetImagePartType(imagePath));
        using (FileStream stream = new FileStream(imagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }
        string relId = mainPart.GetIdOfPart(imagePart);

        // Determine cell width from TableCellWidth if available.
        // TableCellWidth.Width is in DXA (twentieths of a point).
        // If not set, use a reasonable default (e.g., 2 inches).
        long maxWidthEmu = (long)(2.0 * EmuPerInch); // default

        TableCellProperties? tcPr = cell.GetFirstChild<TableCellProperties>();
        TableCellWidth? tcWidth = tcPr?.GetFirstChild<TableCellWidth>();
        if (tcWidth?.Width is not null && tcWidth.Type?.Value == TableWidthUnitValues.Dxa)
        {
            // Convert DXA to EMU: 1 DXA = 1/20 pt = 1/1440 inch = 914400/1440 EMU
            int dxa = int.Parse(tcWidth.Width);
            maxWidthEmu = (long)(dxa * (EmuPerInch / 1440.0));
        }

        // Calculate image dimensions to fit within the cell width
        (long cx, long cy) = CalculateImageDimensions(imagePath, maxWidthEmu / (double)EmuPerInch);

        Drawing drawing = BuildDrawingElement(
            relId, cx, cy,
            docPropId: 7U,
            name: "CellImage",
            description: null);

        // A TableCell MUST contain at least one Paragraph.
        // We add the image inside that paragraph.
        Paragraph para = cell.GetFirstChild<Paragraph>() ?? cell.AppendChild(new Paragraph());
        para.AppendChild(new Run(drawing));
    }

    // ── 8. Replace Existing Image ──────────────────────────────────────

    /// <summary>
    /// Replaces an existing image by updating the ImagePart data behind a
    /// known relationship ID. The Blip.Embed attribute (rId) stays the same;
    /// only the binary content changes. This avoids needing to rebuild the
    /// entire Drawing XML tree.
    /// </summary>
    /// <param name="mainPart">The MainDocumentPart containing the image relationship.</param>
    /// <param name="oldRelId">The existing relationship ID (e.g., "rId5") of the image to replace.</param>
    /// <param name="newImagePath">Path to the replacement image file.</param>
    public static void ReplaceExistingImage(
        MainDocumentPart mainPart, string oldRelId, string newImagePath)
    {
        // Look up the existing ImagePart by its relationship ID
        OpenXmlPart part = mainPart.GetPartById(oldRelId);
        if (part is not ImagePart imagePart)
        {
            throw new InvalidOperationException(
                $"Relationship {oldRelId} does not point to an ImagePart.");
        }

        // Feed new image data into the existing part.
        // This replaces the binary content while keeping the same rId.
        using (FileStream stream = new FileStream(newImagePath, FileMode.Open))
        {
            imagePart.FeedData(stream);
        }

        // NOTE: If the new image has different dimensions, you should also
        // update the Extent.Cx/Cy and A.Extents.Cx/Cy in the Drawing element.
        // Find all Blip elements referencing this relId:
        //
        //   var blips = mainPart.Document.Descendants<A.Blip>()
        //       .Where(b => b.Embed == oldRelId);
        //   foreach (var blip in blips)
        //   {
        //       // Navigate up to find the Extent and A.Extents to update dimensions
        //   }
    }

    // ── 9. SVG with PNG Fallback ───────────────────────────────────────

    /// <summary>
    /// Inserts an SVG image with a PNG fallback for compatibility.
    /// Word 2019+ supports SVG natively; older versions show the PNG.
    /// The SVG is referenced via an extension element (SvgBlip) inside the Blip,
    /// while the Blip.Embed itself points to the PNG fallback.
    /// </summary>
    public static void InsertSvgWithPngFallback(
        MainDocumentPart mainPart, Body body,
        string svgPath, string pngFallbackPath)
    {
        // Add PNG fallback as the primary image part
        ImagePart pngPart = mainPart.AddImagePart(ImagePartType.Png);
        using (FileStream pngStream = new FileStream(pngFallbackPath, FileMode.Open))
        {
            pngPart.FeedData(pngStream);
        }
        string pngRelId = mainPart.GetIdOfPart(pngPart);

        // Add SVG as a separate image part
        ImagePart svgPart = mainPart.AddImagePart(ImagePartType.Svg);
        using (FileStream svgStream = new FileStream(svgPath, FileMode.Open))
        {
            svgPart.FeedData(svgStream);
        }
        string svgRelId = mainPart.GetIdOfPart(svgPart);

        long cx = (long)(3.0 * EmuPerInch);
        long cy = (long)(3.0 * EmuPerInch);

        // The Blip.Embed points to the PNG fallback.
        // The SVG is added as an extension element (asvg:svgBlip) inside the Blip.
        // Namespace: http://schemas.microsoft.com/office/drawing/2016/SVG/main
        var blip = new A.Blip { Embed = pngRelId };

        // Add SVG extension to the Blip using BlipExtensionList
        var svgExtension = new A.BlipExtensionList(
            new A.BlipExtension(
                // The SVG blip element references the SVG image part
                new OpenXmlUnknownElement(
                    "asvg", "svgBlip",
                    "http://schemas.microsoft.com/office/drawing/2016/SVG/main")
                // NOTE: In production, set the r:embed attribute on this element
                // to svgRelId. OpenXmlUnknownElement requires manual attribute setting.
            )
            { Uri = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}" }
        );
        blip.Append(svgExtension);

        var picture = new PIC.Picture(
            new PIC.NonVisualPictureProperties(
                new PIC.NonVisualDrawingProperties { Id = 0U, Name = "SvgImage.svg" },
                new PIC.NonVisualPictureDrawingProperties()),
            new PIC.BlipFill(
                blip,
                new A.Stretch(new A.FillRectangle())),
            new PIC.ShapeProperties(
                new A.Transform2D(
                    new A.Offset { X = 0L, Y = 0L },
                    new A.Extents { Cx = cx, Cy = cy }),
                new A.PresetGeometry(new A.AdjustValueList())
                { Preset = A.ShapeTypeValues.Rectangle }));

        var drawing = new Drawing(
            new DW.Inline(
                new DW.Extent { Cx = cx, Cy = cy },
                new DW.EffectExtent
                {
                    LeftEdge = 0L, TopEdge = 0L,
                    RightEdge = 0L, BottomEdge = 0L
                },
                new DW.DocProperties { Id = 9U, Name = "SvgImage" },
                new DW.NonVisualGraphicFrameDrawingProperties(
                    new A.GraphicFrameLocks { NoChangeAspect = true }),
                new A.Graphic(
                    new A.GraphicData(picture)
                    { Uri = PicGraphicDataUri })
            )
            {
                DistanceFromTop = 0U,
                DistanceFromBottom = 0U,
                DistanceFromLeft = 0U,
                DistanceFromRight = 0U
            });

        body.AppendChild(new Paragraph(new Run(drawing)));
    }

    // ── 10. Calculate Image Dimensions ─────────────────────────────────

    /// <summary>
    /// Reads the actual pixel dimensions of an image file (PNG or JPEG) and
    /// calculates EMU values that fit within a maximum width while maintaining
    /// the original aspect ratio. Uses raw byte reading to avoid a dependency
    /// on System.Drawing (which is Windows-only on modern .NET).
    /// </summary>
    /// <param name="imagePath">Path to a PNG or JPEG image file.</param>
    /// <param name="maxWidthInches">Maximum allowed width in inches.</param>
    /// <returns>Tuple of (cx, cy) in EMU, scaled to fit maxWidthInches.</returns>
    /// <remarks>
    /// For production use, consider SkiaSharp or SixLabors.ImageSharp for
    /// cross-platform image metadata reading with broader format support.
    /// This implementation handles PNG and JPEG only.
    /// </remarks>
    public static (long cx, long cy) CalculateImageDimensions(
        string imagePath, double maxWidthInches)
    {
        // Read pixel dimensions from the image file header.
        // We parse PNG IHDR or JPEG SOF0 markers directly to avoid
        // pulling in System.Drawing.Common (Windows-only on .NET 6+).
        (int widthPx, int heightPx, double dpiX, double dpiY) = ReadImageMetadata(imagePath);

        // Calculate actual size in inches based on pixel count and DPI
        double widthInches = widthPx / dpiX;
        double heightInches = heightPx / dpiY;

        // Scale down if wider than maxWidthInches, preserving aspect ratio
        if (widthInches > maxWidthInches)
        {
            double scale = maxWidthInches / widthInches;
            widthInches = maxWidthInches;
            heightInches *= scale;
        }

        long cx = (long)(widthInches * EmuPerInch);
        long cy = (long)(heightInches * EmuPerInch);

        return (cx, cy);
    }

    /// <summary>
    /// Reads width, height, and DPI from a PNG or JPEG file header.
    /// Returns 96 DPI as default if DPI metadata is not found.
    /// </summary>
    private static (int widthPx, int heightPx, double dpiX, double dpiY) ReadImageMetadata(
        string imagePath)
    {
        const double DefaultDpi = 96.0;
        byte[] header = new byte[32];

        using var fs = new FileStream(imagePath, FileMode.Open, FileAccess.Read);
        int bytesRead = fs.Read(header, 0, header.Length);

        // PNG: starts with 0x89 0x50 0x4E 0x47 (‰PNG)
        // IHDR chunk is always first; width and height are at bytes 16-23 (big-endian)
        if (bytesRead >= 24 &&
            header[0] == 0x89 && header[1] == 0x50 &&
            header[2] == 0x4E && header[3] == 0x47)
        {
            int width = (header[16] << 24) | (header[17] << 16) |
                        (header[18] << 8) | header[19];
            int height = (header[20] << 24) | (header[21] << 16) |
                         (header[22] << 8) | header[23];
            // PNG DPI is in the pHYs chunk (not in IHDR); use default for simplicity
            return (width, height, DefaultDpi, DefaultDpi);
        }

        // JPEG: starts with 0xFF 0xD8
        // Scan for SOF0 (0xFF 0xC0) marker to find dimensions
        if (bytesRead >= 2 && header[0] == 0xFF && header[1] == 0xD8)
        {
            fs.Position = 2;
            while (fs.Position < fs.Length - 1)
            {
                int b = fs.ReadByte();
                if (b != 0xFF) continue;

                int marker = fs.ReadByte();
                if (marker == -1) break;

                // SOF0 (0xC0) or SOF2 (0xC2, progressive)
                if (marker == 0xC0 || marker == 0xC2)
                {
                    byte[] sof = new byte[7];
                    if (fs.Read(sof, 0, 7) == 7)
                    {
                        // SOF structure: length(2) + precision(1) + height(2) + width(2)
                        int height = (sof[3] << 8) | sof[4];
                        int width = (sof[5] << 8) | sof[6];
                        return (width, height, DefaultDpi, DefaultDpi);
                    }
                    break;
                }

                // Skip other markers: read 2-byte length and advance
                if (marker is not (0xD0 or 0xD1 or 0xD2 or 0xD3 or 0xD4 or
                    0xD5 or 0xD6 or 0xD7 or 0xD8 or 0xD9 or 0x01))
                {
                    byte[] lenBytes = new byte[2];
                    if (fs.Read(lenBytes, 0, 2) < 2) break;
                    int len = (lenBytes[0] << 8) | lenBytes[1];
                    if (len < 2) break;
                    fs.Position += len - 2;
                }
            }
        }

        // Fallback: cannot determine dimensions; return a reasonable default
        // Caller should handle this gracefully.
        return (300, 200, DefaultDpi, DefaultDpi);
    }

    // ── 11. Reusable Drawing Builder (Inline) ──────────────────────────

    /// <summary>
    /// Builds a complete Drawing element for an inline image. This is the
    /// reusable core that most insertion methods delegate to.
    /// </summary>
    /// <param name="relId">Relationship ID pointing to the ImagePart (e.g., "rId4").</param>
    /// <param name="cx">Image width in EMU. Must be positive.</param>
    /// <param name="cy">Image height in EMU. Must be positive.</param>
    /// <param name="docPropId">Unique ID for DocProperties within the document.
    /// Each Drawing in a document must have a distinct DocProperties.Id.</param>
    /// <param name="name">Name for DocProperties (shows in Word selection pane).</param>
    /// <param name="description">Alt text for accessibility. Null if not needed.</param>
    /// <returns>A fully constructed Drawing element ready to append to a Run.</returns>
    public static Drawing BuildDrawingElement(
        string relId, long cx, long cy,
        uint docPropId, string name, string? description)
    {
        // ── Complete element hierarchy ──
        // Drawing
        //   └─ DW.Inline
        //        ├─ DW.Extent (cx, cy)              ← bounding box size
        //        ├─ DW.EffectExtent                  ← extra space for effects
        //        ├─ DW.DocProperties (id, name, descr) ← identity + alt text
        //        ├─ DW.NonVisualGraphicFrameDrawingProperties
        //        │    └─ A.GraphicFrameLocks          ← lock aspect ratio
        //        └─ A.Graphic
        //             └─ A.GraphicData (uri = picture namespace)
        //                  └─ PIC.Picture
        //                       ├─ PIC.NonVisualPictureProperties
        //                       │    ├─ PIC.NonVisualDrawingProperties
        //                       │    └─ PIC.NonVisualPictureDrawingProperties
        //                       ├─ PIC.BlipFill
        //                       │    ├─ A.Blip (embed = relId)
        //                       │    └─ A.Stretch → A.FillRectangle
        //                       └─ PIC.ShapeProperties
        //                            ├─ A.Transform2D
        //                            │    ├─ A.Offset (0, 0)
        //                            │    └─ A.Extents (cx, cy)  ← MUST match DW.Extent!
        //                            └─ A.PresetGeometry (rect)

        var docProps = new DW.DocProperties
        {
            Id = docPropId,
            Name = name
        };
        if (description is not null)
        {
            docProps.Description = description;
        }

        var picture = new PIC.Picture(
            new PIC.NonVisualPictureProperties(
                new PIC.NonVisualDrawingProperties
                {
                    Id = 0U,
                    Name = name
                },
                new PIC.NonVisualPictureDrawingProperties()),
            new PIC.BlipFill(
                new A.Blip
                {
                    Embed = relId,
                    // CompressionState controls image quality vs file size.
                    // Print = high quality, Screen = medium, Email = low, None = original
                    CompressionState = A.BlipCompressionValues.Print
                },
                new A.Stretch(new A.FillRectangle())),
            new PIC.ShapeProperties(
                new A.Transform2D(
                    new A.Offset { X = 0L, Y = 0L },
                    new A.Extents { Cx = cx, Cy = cy }), // MUST match DW.Extent
                new A.PresetGeometry(
                    new A.AdjustValueList())
                { Preset = A.ShapeTypeValues.Rectangle }));

        var inline = new DW.Inline(
            new DW.Extent { Cx = cx, Cy = cy }, // MUST match A.Extents
            new DW.EffectExtent
            {
                LeftEdge = 0L,
                TopEdge = 0L,
                RightEdge = 0L,
                BottomEdge = 0L
            },
            docProps,
            new DW.NonVisualGraphicFrameDrawingProperties(
                new A.GraphicFrameLocks { NoChangeAspect = true }),
            new A.Graphic(
                new A.GraphicData(picture)
                { Uri = PicGraphicDataUri }))
        {
            DistanceFromTop = 0U,
            DistanceFromBottom = 0U,
            DistanceFromLeft = 0U,
            DistanceFromRight = 0U
        };

        return new Drawing(inline);
    }

    // ── Private Helpers ────────────────────────────────────────────────

    /// <summary>
    /// Builds a DW.Anchor element for floating images with configurable wrapping.
    /// </summary>
    private static DW.Anchor BuildAnchorElement(
        string relId, long cx, long cy,
        uint docPropId, string name,
        OpenXmlElement wrapElement,
        bool behindDoc)
    {
        return new DW.Anchor(
            new DW.SimplePosition { X = 0L, Y = 0L },
            new DW.HorizontalPosition(
                new DW.PositionOffset("0"))
            { RelativeFrom = DW.HorizontalRelativePositionValues.Column },
            new DW.VerticalPosition(
                new DW.PositionOffset("0"))
            { RelativeFrom = DW.VerticalRelativePositionValues.Paragraph },
            new DW.Extent { Cx = cx, Cy = cy },
            new DW.EffectExtent
            {
                LeftEdge = 0L,
                TopEdge = 0L,
                RightEdge = 0L,
                BottomEdge = 0L
            },
            wrapElement,
            new DW.DocProperties { Id = docPropId, Name = name },
            new DW.NonVisualGraphicFrameDrawingProperties(
                new A.GraphicFrameLocks { NoChangeAspect = true }),
            new A.Graphic(
                new A.GraphicData(
                    new PIC.Picture(
                        new PIC.NonVisualPictureProperties(
                            new PIC.NonVisualDrawingProperties
                            {
                                Id = 0U,
                                Name = name
                            },
                            new PIC.NonVisualPictureDrawingProperties()),
                        new PIC.BlipFill(
                            new A.Blip { Embed = relId },
                            new A.Stretch(new A.FillRectangle())),
                        new PIC.ShapeProperties(
                            new A.Transform2D(
                                new A.Offset { X = 0L, Y = 0L },
                                new A.Extents { Cx = cx, Cy = cy }),
                            new A.PresetGeometry(
                                new A.AdjustValueList())
                            { Preset = A.ShapeTypeValues.Rectangle }))
                )
                { Uri = PicGraphicDataUri })
        )
        {
            DistanceFromTop = 0U,
            DistanceFromBottom = 0U,
            DistanceFromLeft = 114300U,
            DistanceFromRight = 114300U,
            SimplePos = false,
            RelativeHeight = 251658240U,
            BehindDoc = behindDoc,
            Locked = false,
            LayoutInCell = true,
            AllowOverlap = true
        };
    }

    /// <summary>
    /// Maps file extensions to OpenXML PartTypeInfo values via ImagePartType.
    /// In SDK 3.x, ImagePartType is a static class whose members return PartTypeInfo.
    /// </summary>
    private static PartTypeInfo GetImagePartType(string imagePath)
    {
        string ext = Path.GetExtension(imagePath).ToLowerInvariant();
        return ext switch
        {
            ".png" => ImagePartType.Png,
            ".jpg" or ".jpeg" => ImagePartType.Jpeg,
            ".gif" => ImagePartType.Gif,
            ".bmp" => ImagePartType.Bmp,
            ".tif" or ".tiff" => ImagePartType.Tiff,
            ".svg" => ImagePartType.Svg,
            ".emf" => ImagePartType.Emf,
            ".wmf" => ImagePartType.Wmf,
            ".ico" => ImagePartType.Icon,
            _ => throw new NotSupportedException(
                $"Image format '{ext}' is not supported by OpenXML.")
        };
    }
}
