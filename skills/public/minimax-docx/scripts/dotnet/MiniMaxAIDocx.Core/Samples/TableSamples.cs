using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Comprehensive reference for OpenXML table creation and formatting.
///
/// KEY GOTCHA: Every TableCell MUST contain at least one Paragraph, even if empty.
/// Omitting it produces a corrupt document that Word will attempt to repair.
///
/// Border size units: eighth-points (1/8 pt). Size="12" = 1.5pt line.
/// Width units: DXA (twentieths of a point). 1440 DXA = 1 inch.
/// Pct width: fiftieths of a percent. 5000 = 100%.
///
/// XML structure:
/// <w:tbl>
///   <w:tblPr>         — table-level properties (width, alignment, borders, layout)
///   <w:tblGrid>       — column definitions
///   <w:tr>            — table row
///     <w:trPr>        — row properties (height, header repeat)
///     <w:tc>          — table cell
///       <w:tcPr>      — cell properties (width, merge, shading, borders)
///       <w:p>         — paragraph (REQUIRED, at least one)
/// </summary>
public static class TableSamples
{
    // ──────────────────────────────────────────────────────────────
    // 1. CreateSimpleTable — basic table with single-line borders
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a simple table with uniform single borders.
    ///
    /// XML produced:
    /// <w:tbl>
    ///   <w:tblPr>
    ///     <w:tblBorders>
    ///       <w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>
    ///       <w:left w:val="single" .../>  <w:bottom .../> <w:right .../>
    ///       <w:insideH .../> <w:insideV .../>
    ///     </w:tblBorders>
    ///     <w:tblW w:w="5000" w:type="pct"/>
    ///   </w:tblPr>
    ///   <w:tblGrid> <w:gridCol w:w="..."/> ... </w:tblGrid>
    ///   <w:tr> <w:tc> <w:p><w:r><w:t>Header1</w:t></w:r></w:p> </w:tc> ... </w:tr>
    ///   ...
    /// </w:tbl>
    /// </summary>
    /// <param name="body">The document body to append the table to.</param>
    /// <param name="headers">Column header strings.</param>
    /// <param name="data">Rows of data; each inner array matches headers length.</param>
    public static Table CreateSimpleTable(Body body, string[] headers, string[][] data)
    {
        var table = new Table();

        // -- Table Properties --
        var tblPr = new TableProperties();

        // Full-width table: Pct 5000 = 100%
        tblPr.Append(new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct });

        // Single borders all around + inside gridlines
        // Border Size is in eighth-points: 4 = 0.5pt (thin), 12 = 1.5pt, 24 = 3pt
        var borders = new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new LeftBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new RightBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" }
        );
        tblPr.Append(borders);
        table.Append(tblPr);

        // -- Table Grid: equal column widths --
        // Grid columns define the default width in DXA.
        // Total page width ~9360 DXA for letter with 1" margins (8.5" - 2" = 6.5" = 9360 DXA)
        var grid = new TableGrid();
        int colWidth = 9360 / headers.Length;
        foreach (var _ in headers)
        {
            grid.Append(new GridColumn { Width = colWidth.ToString() });
        }
        table.Append(grid);

        // -- Header Row --
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            var cell = new TableCell();
            // GOTCHA: every cell MUST have at least one Paragraph
            cell.Append(new Paragraph(
                new Run(
                    new RunProperties(new Bold()),
                    new Text(h) { Space = SpaceProcessingModeValues.Preserve })));
            headerRow.Append(cell);
        }
        table.Append(headerRow);

        // -- Data Rows --
        foreach (var rowData in data)
        {
            var row = new TableRow();
            foreach (var cellText in rowData)
            {
                var cell = new TableCell();
                cell.Append(new Paragraph(
                    new Run(new Text(cellText) { Space = SpaceProcessingModeValues.Preserve })));
                row.Append(cell);
            }
            table.Append(row);
        }

        body.Append(table);
        // Add an empty paragraph after the table (Word best practice)
        body.Append(new Paragraph());
        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 2. CreateStyledTable — header shading, zebra striping, totals
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a professionally styled table with:
    ///   - Dark header row (navy background, white bold text)
    ///   - Alternating row shading (zebra striping)
    ///   - Bold totals row at the bottom
    ///
    /// XML for shaded cell:
    /// <w:tc>
    ///   <w:tcPr>
    ///     <w:shd w:val="clear" w:color="auto" w:fill="1F3864"/>
    ///   </w:tcPr>
    ///   <w:p>
    ///     <w:pPr><w:jc w:val="center"/></w:pPr>
    ///     <w:r>
    ///       <w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr>
    ///       <w:t>Header</w:t>
    ///     </w:r>
    ///   </w:p>
    /// </w:tc>
    /// </summary>
    public static Table CreateStyledTable(Body body)
    {
        var table = new Table();

        // Table properties: full width, single borders
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" },
                new LeftBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" },
                new RightBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" },
                new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "1F3864" }
            ));
        table.Append(tblPr);

        // Grid: 3 columns
        var grid = new TableGrid(
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" });
        table.Append(grid);

        string[] headers = ["Item", "Quantity", "Price"];
        string[][] data =
        [
            ["Widget A", "10", "$5.00"],
            ["Widget B", "25", "$3.50"],
            ["Widget C", "15", "$7.25"],
        ];

        // -- Header row: dark navy background, white bold text --
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            var cell = new TableCell(
                new TableCellProperties(
                    new Shading
                    {
                        Val = ShadingPatternValues.Clear,
                        Color = "auto",
                        Fill = "1F3864"  // Dark navy
                    }),
                new Paragraph(
                    new ParagraphProperties(
                        new Justification { Val = JustificationValues.Center }),
                    new Run(
                        new RunProperties(
                            new Bold(),
                            new Color { Val = "FFFFFF" }),  // White text
                        new Text(h))));
            headerRow.Append(cell);
        }
        table.Append(headerRow);

        // -- Data rows with zebra striping --
        for (int i = 0; i < data.Length; i++)
        {
            var row = new TableRow();
            // Alternate rows get light gray background
            string? fillColor = (i % 2 == 1) ? "D9E2F3" : null;

            foreach (var cellText in data[i])
            {
                var tcPr = new TableCellProperties();
                if (fillColor != null)
                {
                    tcPr.Append(new Shading
                    {
                        Val = ShadingPatternValues.Clear,
                        Color = "auto",
                        Fill = fillColor
                    });
                }
                var cell = new TableCell(
                    tcPr,
                    new Paragraph(
                        new Run(new Text(cellText) { Space = SpaceProcessingModeValues.Preserve })));
                row.Append(cell);
            }
            table.Append(row);
        }

        // -- Totals row: bold text, top border emphasis --
        var totalsRow = new TableRow();
        string[] totals = ["Total", "50", "$257.50"];
        foreach (var t in totals)
        {
            var cell = new TableCell(
                new TableCellProperties(
                    new Shading
                    {
                        Val = ShadingPatternValues.Clear,
                        Color = "auto",
                        Fill = "1F3864"
                    }),
                new Paragraph(
                    new Run(
                        new RunProperties(
                            new Bold(),
                            new Color { Val = "FFFFFF" }),
                        new Text(t) { Space = SpaceProcessingModeValues.Preserve })));
            totalsRow.Append(cell);
        }
        table.Append(totalsRow);

        body.Append(table);
        body.Append(new Paragraph());
        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 3. CreateThreeLineTable — academic 三线表
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates an academic three-line table (三线表):
    ///   - Thick top border (1.5pt = Size 12)
    ///   - Thin border below header row (0.75pt = Size 6)
    ///   - Thick bottom border (1.5pt = Size 12)
    ///   - NO vertical borders, NO inside vertical borders
    ///   - NO left/right borders
    ///
    /// This is the standard table style for Chinese academic papers (GB/T 7713).
    ///
    /// XML produced:
    /// <w:tbl>
    ///   <w:tblPr>
    ///     <w:tblBorders>
    ///       <w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>
    ///       <w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>
    ///       <!-- No left, right, insideV borders -->
    ///       <w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>
    ///       <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>
    ///     </w:tblBorders>
    ///   </w:tblPr>
    ///   ...
    ///   <!-- Header row uses per-cell bottom border for the thin line -->
    /// </w:tbl>
    /// </summary>
    public static Table CreateThreeLineTable(Body body)
    {
        var table = new Table();

        // Table borders: only top and bottom (thick), no sides, no inside
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 12, Space = 0, Color = "000000" },
                new BottomBorder { Val = BorderValues.Single, Size = 12, Space = 0, Color = "000000" },
                // Explicitly set left/right/insideH/insideV to none
                new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideHorizontalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
                new InsideVerticalBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
            ));
        table.Append(tblPr);

        var grid = new TableGrid(
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" });
        table.Append(grid);

        string[] headers = ["Variable", "Mean", "SD"];

        // -- Header row: centered, bold, with thin bottom border on each cell --
        var headerRow = new TableRow();
        foreach (var h in headers)
        {
            // Per-cell bottom border creates the thin "second line" of the three-line table
            var tcPr = new TableCellProperties(
                new TableCellBorders(
                    new BottomBorder { Val = BorderValues.Single, Size = 6, Space = 0, Color = "000000" }
                ));

            var cell = new TableCell(
                tcPr,
                new Paragraph(
                    new ParagraphProperties(
                        new Justification { Val = JustificationValues.Center }),
                    new Run(
                        new RunProperties(new Bold()),
                        new Text(h))));
            headerRow.Append(cell);
        }
        table.Append(headerRow);

        // -- Data rows: centered text, no borders --
        string[][] data =
        [
            ["Age", "25.3", "4.2"],
            ["Height", "170.5", "8.1"],
            ["Weight", "65.2", "10.3"],
        ];
        foreach (var rowData in data)
        {
            var row = new TableRow();
            foreach (var cellText in rowData)
            {
                var cell = new TableCell(
                    new Paragraph(
                        new ParagraphProperties(
                            new Justification { Val = JustificationValues.Center }),
                        new Run(new Text(cellText))));
                row.Append(cell);
            }
            table.Append(row);
        }

        body.Append(table);
        body.Append(new Paragraph());
        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 4. CreateBorderedTable — multiple border styles
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a table demonstrating different border styles.
    ///
    /// Border Val options:
    ///   BorderValues.Single      — normal single line
    ///   BorderValues.Double      — double line
    ///   BorderValues.Thick       — thick single line
    ///   BorderValues.Dashed      — dashed line
    ///   BorderValues.DashSmallGap — dashed with small gaps
    ///   BorderValues.DotDash     — dot-dash pattern
    ///   BorderValues.Dotted      — dotted line
    ///   BorderValues.Wave        — wavy line
    ///   BorderValues.None        — no border
    ///
    /// Size is in eighth-points: 4 = 0.5pt, 8 = 1pt, 12 = 1.5pt, 24 = 3pt
    /// </summary>
    public static Table CreateBorderedTable(Body body)
    {
        var table = new Table();

        // Use different border styles on each side to demonstrate the options
        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Double, Size = 4, Space = 0, Color = "000000" },
                new BottomBorder { Val = BorderValues.Double, Size = 4, Space = 0, Color = "000000" },
                new LeftBorder { Val = BorderValues.Thick, Size = 12, Space = 0, Color = "333333" },
                new RightBorder { Val = BorderValues.Thick, Size = 12, Space = 0, Color = "333333" },
                new InsideHorizontalBorder { Val = BorderValues.Dashed, Size = 4, Space = 0, Color = "999999" },
                new InsideVerticalBorder { Val = BorderValues.Dotted, Size = 4, Space = 0, Color = "999999" }
            ));
        table.Append(tblPr);

        var grid = new TableGrid(
            new GridColumn { Width = "4680" },
            new GridColumn { Width = "4680" });
        table.Append(grid);

        // Sample data
        string[][] rows =
        [
            ["Double top / Thick sides", "Dotted vertical inside"],
            ["Dashed horizontal inside", "Double bottom"],
        ];
        foreach (var rowData in rows)
        {
            var row = new TableRow();
            foreach (var cellText in rowData)
            {
                var cell = new TableCell(
                    new Paragraph(new Run(new Text(cellText))));
                row.Append(cell);
            }
            table.Append(row);
        }

        body.Append(table);
        body.Append(new Paragraph());
        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 5. SetTableWidth — Pct, DXA, Auto
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Demonstrates three table width modes:
    ///
    /// 1. Pct (percentage): Value in fiftieths of a percent. 5000 = 100%, 2500 = 50%.
    ///    XML: <w:tblW w:w="5000" w:type="pct"/>
    ///
    /// 2. Dxa (absolute): Value in twentieths of a point. 1440 = 1 inch, 9360 = 6.5 inches.
    ///    XML: <w:tblW w:w="9360" w:type="dxa"/>
    ///
    /// 3. Auto: Word determines width from content.
    ///    XML: <w:tblW w:w="0" w:type="auto"/>
    /// </summary>
    public static void SetTableWidth(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        // --- Option A: Percentage width (100%) ---
        // Pct value is in fiftieths of a percent: 5000 = 100%
        tblPr.TableWidth = new TableWidth
        {
            Width = "5000",
            Type = TableWidthUnitValues.Pct
        };

        // --- Option B: Absolute width (6.5 inches = 9360 DXA) ---
        // tblPr.TableWidth = new TableWidth
        // {
        //     Width = "9360",                       // 6.5 * 1440 = 9360 DXA
        //     Type = TableWidthUnitValues.Dxa
        // };

        // --- Option C: Auto width ---
        // tblPr.TableWidth = new TableWidth
        // {
        //     Width = "0",
        //     Type = TableWidthUnitValues.Auto
        // };
    }

    // ──────────────────────────────────────────────────────────────
    // 6. SetTableLayout — Fixed vs AutoFit
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Controls whether the table uses fixed column widths or auto-fits to content.
    ///
    /// Fixed layout: columns keep their exact width from TableGrid; content wraps.
    ///   XML: <w:tblLayout w:type="fixed"/>
    ///
    /// AutoFit layout: Word adjusts column widths based on content. This is the default.
    ///   XML: <w:tblLayout w:type="autofit"/>
    ///
    /// GOTCHA: Fixed layout is required for predictable column widths; AutoFit
    /// may override your GridColumn values.
    /// </summary>
    public static void SetTableLayout(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        // Fixed layout — columns respect GridColumn widths exactly
        tblPr.TableLayout = new TableLayout
        {
            Type = TableLayoutValues.Fixed
        };

        // AutoFit layout (default) — Word adjusts widths to content
        // tblPr.TableLayout = new TableLayout
        // {
        //     Type = TableLayoutValues.Autofit
        // };
    }

    // ──────────────────────────────────────────────────────────────
    // 7. SetTableAlignment — center, right, left with indent
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Controls horizontal alignment of the table on the page.
    ///
    /// XML: <w:jc w:val="center"/>
    ///
    /// For left alignment with indent:
    /// XML: <w:tblInd w:w="720" w:type="dxa"/>
    ///
    /// GOTCHA: TableJustification (w:jc) inside tblPr is DIFFERENT from paragraph Justification.
    /// </summary>
    public static void SetTableAlignment(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        // --- Option A: Center the table ---
        tblPr.TableJustification = new TableJustification
        {
            Val = TableRowAlignmentValues.Center
        };

        // --- Option B: Right-align ---
        // tblPr.TableJustification = new TableJustification
        // {
        //     Val = TableRowAlignmentValues.Right
        // };

        // --- Option C: Left with indent (0.5 inch = 720 DXA) ---
        // tblPr.TableJustification = new TableJustification
        // {
        //     Val = TableRowAlignmentValues.Left
        // };
        // tblPr.TableIndentation = new TableIndentation
        // {
        //     Width = 720,
        //     Type = TableWidthUnitValues.Dxa
        // };
    }

    // ──────────────────────────────────────────────────────────────
    // 8. ConfigureTableGrid — column widths
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Sets explicit column widths via TableGrid / GridColumn elements.
    ///
    /// GridColumn.Width is in DXA (twentieths of a point).
    /// 1440 DXA = 1 inch. Common page width = 9360 DXA (6.5" printable on letter).
    ///
    /// XML:
    /// <w:tblGrid>
    ///   <w:gridCol w:w="1440"/>   <!-- 1 inch -->
    ///   <w:gridCol w:w="4680"/>   <!-- 3.25 inches -->
    ///   <w:gridCol w:w="3240"/>   <!-- 2.25 inches -->
    /// </w:tblGrid>
    ///
    /// GOTCHA: The number of GridColumn elements should match the maximum number
    /// of cells in any row (before merging). Merged cells still correspond to
    /// multiple grid columns via GridSpan.
    /// </summary>
    public static void ConfigureTableGrid(Table table)
    {
        // Remove existing grid if present
        var existingGrid = table.GetFirstChild<TableGrid>();
        existingGrid?.Remove();

        // 3 columns: narrow (1"), wide (3.25"), medium (2.25") = 6.5" total
        var grid = new TableGrid(
            new GridColumn { Width = "1440" },   // 1 inch
            new GridColumn { Width = "4680" },   // 3.25 inches
            new GridColumn { Width = "3240" }    // 2.25 inches
        );

        // Grid must come after TableProperties, before any TableRow
        var tblPr = table.GetFirstChild<TableProperties>();
        if (tblPr != null)
            tblPr.InsertAfterSelf(grid);
        else
            table.PrependChild(grid);
    }

    // ──────────────────────────────────────────────────────────────
    // 9. SetCellProperties — width, vAlign, text direction, no-wrap, shading
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Demonstrates the key TableCellProperties settings.
    ///
    /// XML:
    /// <w:tcPr>
    ///   <w:tcW w:w="2880" w:type="dxa"/>
    ///   <w:vAlign w:val="center"/>
    ///   <w:textDirection w:val="btLr"/>
    ///   <w:noWrap/>
    ///   <w:shd w:val="clear" w:color="auto" w:fill="E2EFDA"/>
    /// </w:tcPr>
    ///
    /// Vertical alignment values:
    ///   TableVerticalAlignmentValues.Top     — default
    ///   TableVerticalAlignmentValues.Center  — vertically centered
    ///   TableVerticalAlignmentValues.Bottom  — bottom-aligned
    ///
    /// Text direction values:
    ///   TextDirectionValues.LefToRightTopToBottom  — normal horizontal (default)
    ///   TextDirectionValues.TopToBottomRightToLeft  — vertical (CJK style)
    ///   TextDirectionValues.BottomToTopLeftToRight  — rotated 90 CCW
    /// </summary>
    public static void SetCellProperties(TableCell cell)
    {
        var tcPr = cell.GetFirstChild<TableCellProperties>()
                   ?? cell.PrependChild(new TableCellProperties());

        // Cell width: 2 inches = 2880 DXA
        tcPr.TableCellWidth = new TableCellWidth
        {
            Width = "2880",
            Type = TableWidthUnitValues.Dxa
        };

        // Vertical alignment: center content vertically in cell
        tcPr.TableCellVerticalAlignment = new TableCellVerticalAlignment
        {
            Val = TableVerticalAlignmentValues.Center
        };

        // Text direction: bottom-to-top (rotated 90 degrees counterclockwise)
        // Useful for narrow column headers
        tcPr.TextDirection = new TextDirection
        {
            Val = TextDirectionValues.BottomToTopLeftToRight
        };

        // No-wrap: prevent text wrapping, force cell to expand horizontally
        tcPr.NoWrap = new NoWrap();

        // Shading (background color): light green
        // Fill is the background color; Color is the pattern color (usually "auto")
        tcPr.Shading = new Shading
        {
            Val = ShadingPatternValues.Clear,
            Color = "auto",
            Fill = "E2EFDA"
        };
    }

    // ──────────────────────────────────────────────────────────────
    // 10. SetTableCellMargins — table-level default cell margins
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Sets default cell margins (padding) for the entire table.
    /// These apply to ALL cells unless overridden per-cell.
    ///
    /// XML:
    /// <w:tblPr>
    ///   <w:tblCellMar>
    ///     <w:top w:w="72" w:type="dxa"/>
    ///     <w:start w:w="115" w:type="dxa"/>
    ///     <w:bottom w:w="72" w:type="dxa"/>
    ///     <w:end w:w="115" w:type="dxa"/>
    ///   </w:tblCellMar>
    /// </w:tblPr>
    ///
    /// Units: DXA. Default Word margins are approximately top/bottom=0, left/right=108 DXA.
    ///
    /// GOTCHA: Use StartMargin/EndMargin (not LeftMargin/RightMargin) for OOXML Strict
    /// compliance, but Word also accepts Left/Right.
    /// </summary>
    public static void SetTableCellMargins(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        tblPr.TableCellMarginDefault = new TableCellMarginDefault(
            new TopMargin { Width = "72", Type = TableWidthUnitValues.Dxa },          // ~0.05 inch
            new StartMargin { Width = "115", Type = TableWidthUnitValues.Dxa },       // ~0.08 inch
            new BottomMargin { Width = "72", Type = TableWidthUnitValues.Dxa },
            new EndMargin { Width = "115", Type = TableWidthUnitValues.Dxa }
        );
    }

    // ──────────────────────────────────────────────────────────────
    // 11. SetPerCellMargins — per-cell override
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Overrides the table-level cell margins for a specific cell.
    ///
    /// XML:
    /// <w:tcPr>
    ///   <w:tcMar>
    ///     <w:top w:w="144" w:type="dxa"/>
    ///     <w:start w:w="216" w:type="dxa"/>
    ///     <w:bottom w:w="144" w:type="dxa"/>
    ///     <w:end w:w="216" w:type="dxa"/>
    ///   </w:tcMar>
    /// </w:tcPr>
    ///
    /// GOTCHA: Per-cell margins fully replace the table defaults for that cell.
    /// You must specify all four sides; omitted sides get zero margin (not the table default).
    /// </summary>
    public static void SetPerCellMargins(TableCell cell)
    {
        var tcPr = cell.GetFirstChild<TableCellProperties>()
                   ?? cell.PrependChild(new TableCellProperties());

        tcPr.TableCellMargin = new TableCellMargin(
            new TopMargin { Width = "144", Type = TableWidthUnitValues.Dxa },          // 0.1 inch
            new StartMargin { Width = "216", Type = TableWidthUnitValues.Dxa },        // 0.15 inch
            new BottomMargin { Width = "144", Type = TableWidthUnitValues.Dxa },
            new EndMargin { Width = "216", Type = TableWidthUnitValues.Dxa }
        );
    }

    // ──────────────────────────────────────────────────────────────
    // 12. SetRowHeight — exact, atLeast, auto
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Controls the height of a table row.
    ///
    /// XML: <w:trPr><w:trHeight w:val="720" w:hRule="exact"/></w:trPr>
    ///
    /// Height rule values:
    ///   HeightRuleValues.Exact   — row is exactly the specified height; content may clip
    ///   HeightRuleValues.AtLeast — row is at least the specified height; expands for content
    ///   HeightRuleValues.Auto    — row height determined by content (default)
    ///
    /// Height value is in DXA (twentieths of a point). 1440 DXA = 1 inch.
    /// </summary>
    public static void SetRowHeight(TableRow row)
    {
        var trPr = row.GetFirstChild<TableRowProperties>()
                   ?? row.PrependChild(new TableRowProperties());

        // Option A: Exact height of 0.5 inch (720 DXA)
        trPr.Append(new TableRowHeight
        {
            Val = 720,                            // 0.5 inch in DXA
            HeightType = HeightRuleValues.Exact
        });

        // Option B: Minimum height (grows if content needs more)
        // trPr.Append(new TableRowHeight
        // {
        //     Val = 360,                         // 0.25 inch minimum
        //     HeightType = HeightRuleValues.AtLeast
        // });
    }

    // ──────────────────────────────────────────────────────────────
    // 13. SetHeaderRowRepeat — repeat on each page
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Marks a row as a header row that repeats at the top of each page
    /// when the table spans multiple pages.
    ///
    /// XML:
    /// <w:trPr>
    ///   <w:tblHeader/>
    /// </w:trPr>
    ///
    /// GOTCHA: Only works on contiguous rows starting from the FIRST row of the table.
    /// If row 1 and row 2 are both headers, both must have TableHeader set.
    /// You cannot make row 3 a repeating header if row 2 is not.
    /// </summary>
    public static void SetHeaderRowRepeat(TableRow row)
    {
        var trPr = row.GetFirstChild<TableRowProperties>()
                   ?? row.PrependChild(new TableRowProperties());

        trPr.Append(new TableHeader());
    }

    // ──────────────────────────────────────────────────────────────
    // 14. SetPerCellBorders — override table borders on specific cells
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Overrides the table-level borders for a specific cell.
    /// Per-cell borders take precedence over table-level borders.
    ///
    /// XML:
    /// <w:tcPr>
    ///   <w:tcBorders>
    ///     <w:top w:val="double" w:sz="4" w:space="0" w:color="FF0000"/>
    ///     <w:bottom w:val="single" w:sz="12" w:space="0" w:color="0000FF"/>
    ///     <w:start w:val="none" w:sz="0" w:space="0" w:color="auto"/>
    ///     <w:end w:val="none" w:sz="0" w:space="0" w:color="auto"/>
    ///   </w:tcBorders>
    /// </w:tcPr>
    ///
    /// GOTCHA: When two adjacent cells define conflicting borders, the conflict
    /// resolution follows the ECMA-376 spec: wider borders win; if same width,
    /// the cell on the "end" side wins.
    /// </summary>
    public static void SetPerCellBorders(TableCell cell)
    {
        var tcPr = cell.GetFirstChild<TableCellProperties>()
                   ?? cell.PrependChild(new TableCellProperties());

        tcPr.TableCellBorders = new TableCellBorders(
            new TopBorder { Val = BorderValues.Double, Size = 4, Space = 0, Color = "FF0000" },
            new BottomBorder { Val = BorderValues.Single, Size = 12, Space = 0, Color = "0000FF" },
            new LeftBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" },
            new RightBorder { Val = BorderValues.None, Size = 0, Space = 0, Color = "auto" }
        );
    }

    // ──────────────────────────────────────────────────────────────
    // 15. CreateHorizontalMerge — GridSpan (column span)
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a row with horizontal cell merging using GridSpan.
    ///
    /// To merge 3 columns into one cell, set GridSpan.Val = 3 on that cell.
    /// The row still references the same grid columns, but one cell spans multiple.
    ///
    /// XML for a row in a 4-column table where first cell spans columns 1-3:
    /// <w:tr>
    ///   <w:tc>
    ///     <w:tcPr>
    ///       <w:gridSpan w:val="3"/>   <!-- this cell spans 3 grid columns -->
    ///     </w:tcPr>
    ///     <w:p><w:r><w:t>Merged across 3 columns</w:t></w:r></w:p>
    ///   </w:tc>
    ///   <w:tc>
    ///     <w:p><w:r><w:t>Normal cell</w:t></w:r></w:p>
    ///   </w:tc>
    /// </w:tr>
    ///
    /// GOTCHA: The total GridSpan values across all cells in a row must equal
    /// the number of GridColumn elements in TblGrid.
    /// </summary>
    public static TableRow CreateHorizontalMerge(TableRow row)
    {
        // Assume a 4-column grid: first cell spans 3 columns, second cell is normal

        // Cell spanning 3 columns
        var mergedCell = new TableCell(
            new TableCellProperties(
                new GridSpan { Val = 3 }),
            new Paragraph(
                new Run(new Text("This cell spans 3 columns"))));
        row.Append(mergedCell);

        // Normal cell (1 column, GridSpan defaults to 1 when omitted)
        var normalCell = new TableCell(
            new Paragraph(
                new Run(new Text("Normal cell"))));
        row.Append(normalCell);

        return row;
    }

    // ──────────────────────────────────────────────────────────────
    // 16. CreateVerticalMerge — VerticalMerge Restart + Continue
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates vertical cell merging using VerticalMerge with Restart/Continue pattern.
    ///
    /// Vertical merge pattern:
    ///   - First row: VerticalMerge.Val = MergedCellValues.Restart  (starts the merge)
    ///   - Subsequent rows: VerticalMerge.Val = MergedCellValues.Continue (continues)
    ///   - Last continuation can also use VerticalMerge with no Val attribute
    ///
    /// XML:
    /// Row 1: <w:tcPr><w:vMerge w:val="restart"/></w:tcPr>
    ///         <w:p><w:r><w:t>Visible content</w:t></w:r></w:p>
    /// Row 2: <w:tcPr><w:vMerge/></w:tcPr>
    ///         <w:p/>   <!-- MUST still have a paragraph, even though cell is merged -->
    /// Row 3: <w:tcPr><w:vMerge/></w:tcPr>
    ///         <w:p/>   <!-- MUST still have a paragraph -->
    ///
    /// GOTCHA: The "continue" cells MUST still contain at least one empty Paragraph.
    /// They also MUST have the same column position in the grid as the "restart" cell.
    /// </summary>
    public static Table CreateVerticalMerge(Table table)
    {
        var grid = new TableGrid(
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" },
            new GridColumn { Width = "3120" });
        // Only add grid if not already present
        if (table.GetFirstChild<TableGrid>() == null)
        {
            var tblPr = table.GetFirstChild<TableProperties>();
            if (tblPr != null)
                tblPr.InsertAfterSelf(grid);
            else
                table.PrependChild(grid);
        }

        // Row 1: first cell starts vertical merge
        var row1 = new TableRow(
            new TableCell(
                new TableCellProperties(
                    new VerticalMerge { Val = MergedCellValues.Restart }),  // Start merge
                new Paragraph(new Run(new Text("Spans 3 rows")))),
            new TableCell(
                new Paragraph(new Run(new Text("Row 1, Col 2")))),
            new TableCell(
                new Paragraph(new Run(new Text("Row 1, Col 3")))));
        table.Append(row1);

        // Row 2: first cell continues vertical merge
        var row2 = new TableRow(
            new TableCell(
                new TableCellProperties(
                    new VerticalMerge()),                                  // Continue (no Val)
                new Paragraph()),                                          // Empty paragraph required!
            new TableCell(
                new Paragraph(new Run(new Text("Row 2, Col 2")))),
            new TableCell(
                new Paragraph(new Run(new Text("Row 2, Col 3")))));
        table.Append(row2);

        // Row 3: first cell continues vertical merge
        var row3 = new TableRow(
            new TableCell(
                new TableCellProperties(
                    new VerticalMerge()),                                  // Continue
                new Paragraph()),                                          // Empty paragraph required!
            new TableCell(
                new Paragraph(new Run(new Text("Row 3, Col 2")))),
            new TableCell(
                new Paragraph(new Run(new Text("Row 3, Col 3")))));
        table.Append(row3);

        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 17. CreateNestedTable — table inside a table cell
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Inserts a table inside a table cell.
    ///
    /// GOTCHA: The nested table is a direct child of the TableCell, placed BEFORE
    /// the required trailing Paragraph. The cell structure is:
    ///
    /// <w:tc>
    ///   <w:tcPr>...</w:tcPr>
    ///   <w:tbl>              <!-- nested table -->
    ///     <w:tblPr>...</w:tblPr>
    ///     <w:tblGrid>...</w:tblGrid>
    ///     <w:tr>...</w:tr>
    ///   </w:tbl>
    ///   <w:p/>               <!-- REQUIRED trailing paragraph -->
    /// </w:tc>
    ///
    /// GOTCHA: The parent cell still MUST end with a Paragraph after the nested table.
    /// </summary>
    public static Table CreateNestedTable(TableCell parentCell)
    {
        var nestedTable = new Table();

        var tblPr = new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" },
                new LeftBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" },
                new RightBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" },
                new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "999999" }
            ));
        nestedTable.Append(tblPr);

        var grid = new TableGrid(
            new GridColumn { Width = "2000" },
            new GridColumn { Width = "2000" });
        nestedTable.Append(grid);

        // 2x2 nested table
        for (int r = 0; r < 2; r++)
        {
            var row = new TableRow();
            for (int c = 0; c < 2; c++)
            {
                var cell = new TableCell(
                    new Paragraph(
                        new Run(new Text($"Nested R{r + 1}C{c + 1}"))));
                row.Append(cell);
            }
            nestedTable.Append(row);
        }

        // Insert the nested table in the parent cell.
        // The parent cell must still end with a paragraph.
        parentCell.Append(nestedTable);
        parentCell.Append(new Paragraph());  // REQUIRED trailing paragraph

        return nestedTable;
    }

    // ──────────────────────────────────────────────────────────────
    // 18. CreateFloatingTable — absolute positioning
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Creates a floating (absolutely positioned) table using TablePositionProperties.
    ///
    /// XML:
    /// <w:tblPr>
    ///   <w:tblpPr
    ///     w:leftFromText="180"
    ///     w:rightFromText="180"
    ///     w:topFromText="180"
    ///     w:bottomFromText="180"
    ///     w:vertAnchor="page"
    ///     w:horzAnchor="page"
    ///     w:tblpX="2880"
    ///     w:tblpY="4320"/>
    /// </w:tblPr>
    ///
    /// Anchor values:
    ///   VerticalAnchorValues.Page / Margin / Text
    ///   HorizontalAnchorValues.Page / Margin / Text
    ///
    /// Position values (tblpX, tblpY) are in DXA from the anchor.
    /// FromText values are spacing between table and surrounding text, in DXA.
    ///
    /// GOTCHA: Floating tables allow text to wrap around them, similar to
    /// text-wrapped images. This can produce unexpected layouts.
    /// </summary>
    public static Table CreateFloatingTable(Body body)
    {
        var table = new Table();

        var tblPr = new TableProperties();

        // Floating position: 2 inches from left of page, 3 inches from top of page
        tblPr.TablePositionProperties = new TablePositionProperties
        {
            LeftFromText = 180,           // 0.125" spacing from text
            RightFromText = 180,
            TopFromText = 180,
            BottomFromText = 180,
            VerticalAnchor = VerticalAnchorValues.Page,
            HorizontalAnchor = HorizontalAnchorValues.Page,
            TablePositionX = 2880,        // 2 inches from left edge of page
            TablePositionY = 4320         // 3 inches from top of page
        };

        tblPr.Append(new TableWidth { Width = "3600", Type = TableWidthUnitValues.Dxa });
        tblPr.Append(new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new LeftBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new RightBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" },
            new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Space = 0, Color = "000000" }
        ));
        table.Append(tblPr);

        var grid = new TableGrid(
            new GridColumn { Width = "1800" },
            new GridColumn { Width = "1800" });
        table.Append(grid);

        // Simple 2x2 floating table
        for (int r = 0; r < 2; r++)
        {
            var row = new TableRow();
            for (int c = 0; c < 2; c++)
            {
                var cell = new TableCell(
                    new Paragraph(
                        new Run(new Text($"Float R{r + 1}C{c + 1}"))));
                row.Append(cell);
            }
            table.Append(row);
        }

        body.Append(table);
        return table;
    }

    // ──────────────────────────────────────────────────────────────
    // 19. ApplyTableLook — conditional formatting flags
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// Sets the TableLook element which controls which parts of a table style are applied.
    ///
    /// XML:
    /// <w:tblPr>
    ///   <w:tblLook w:val="04A0"
    ///     w:firstRow="1"
    ///     w:lastRow="0"
    ///     w:firstColumn="1"
    ///     w:lastColumn="0"
    ///     w:noHBand="0"
    ///     w:noVBand="1"/>
    /// </w:tblPr>
    ///
    /// These flags control conditional formatting from the applied table style:
    ///   FirstRow    = apply special header row formatting
    ///   LastRow     = apply special last row formatting
    ///   FirstColumn = apply special first column formatting
    ///   LastColumn  = apply special last column formatting
    ///   NoHorizontalBand = disable banded row shading
    ///   NoVerticalBand   = disable banded column shading
    ///
    /// The Val attribute is a bitmask but the individual boolean attributes are preferred.
    /// </summary>
    public static void ApplyTableLook(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        tblPr.TableLook = new TableLook
        {
            Val = "04A0",
            FirstRow = true,
            LastRow = false,
            FirstColumn = true,
            LastColumn = false,
            NoHorizontalBand = false,  // false = DO apply banded row shading
            NoVerticalBand = true      // true = do NOT apply banded column shading
        };
    }

    // ──────────────────────────────────────────────────────────────
    // 20. ApplyTableStyle — reference a named style
    // ──────────────────────────────────────────────────────────────
    /// <summary>
    /// References a named table style defined in the styles part.
    ///
    /// XML:
    /// <w:tblPr>
    ///   <w:tblStyle w:val="TableGrid"/>
    /// </w:tblPr>
    ///
    /// Common built-in style IDs:
    ///   "TableGrid"         — basic grid with all borders
    ///   "TableNormal"       — no borders or shading
    ///   "LightShading"      — light shading style
    ///   "MediumShading1"    — medium shading
    ///   "GridTable4-Accent1" — colorful banded table (Office 2013+)
    ///
    /// GOTCHA: The style ID must exist in the StyleDefinitionsPart. If you reference
    /// a style that doesn't exist, Word will silently ignore it and use defaults.
    /// Built-in styles are only available if they have been added to the styles part
    /// (Word adds them lazily on first use).
    ///
    /// GOTCHA: Combine with TableLook to control which conditional parts of the
    /// style are applied (header row, banded rows, etc.).
    /// </summary>
    public static void ApplyTableStyle(Table table)
    {
        var tblPr = table.GetFirstChild<TableProperties>()
                    ?? table.PrependChild(new TableProperties());

        // Reference the "TableGrid" built-in style
        tblPr.TableStyle = new TableStyle { Val = "TableGrid" };

        // Combine with TableLook for conditional formatting
        tblPr.TableLook = new TableLook
        {
            Val = "04A0",
            FirstRow = true,
            LastRow = false,
            FirstColumn = true,
            LastColumn = false,
            NoHorizontalBand = false,
            NoVerticalBand = true
        };
    }
}
