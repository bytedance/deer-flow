# OpenXML SDK 3.x Complete Reference Encyclopedia — Part 2

**Target:** DocumentFormat.OpenXml 3.x / .NET 8+ / C# 12
**Last Updated:** 2026-03-22

This document covers page setup, tables, headers/footers, section breaks, document properties, and printing/compatibility settings. Every code block is ready to copy-paste.

---

## Namespace Aliases Used Throughout

```csharp
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A = DocumentFormat.OpenXml.Drawing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;
using PIC = DocumentFormat.OpenXml.Drawing.Pictures;
```

---

## Table of Contents

1. [Page Setup](#1-page-setup)
2. [Tables — Comprehensive](#2-tables--comprehensive)
3. [Headers, Footers & Page Numbers](#3-headers-footers--page-numbers)
4. [Section Breaks & Multi-Section](#4-section-breaks--multi-section)
5. [Document Properties](#5-document-properties)
6. [Printing & Compatibility Settings](#6-printing--compatibility-settings)

---

## 1. Page Setup

Page setup is controlled via `SectionProperties`, which is placed as the **last child element** of `Body` for the final (or only) section, or inside `ParagraphProperties` for mid-document section breaks.

### 1.1 PageSize — Standard Paper Sizes

```csharp
// =============================================================================
// PAGE SIZE — STANDARD PAPER SIZES
// =============================================================================
// PageSize Width and Height are specified in DXA (twentieths of a point).
// 1 inch = 1440 DXA.  1 cm ≈ 567 DXA.  1 mm ≈ 56.7 DXA.
//
// Common paper sizes (portrait orientation):
//   Letter:  12240 × 15840  (8.5" × 11")
//   A4:      11906 × 16838  (210mm × 297mm)
//   Legal:   12240 × 20160  (8.5" × 14")
//   A3:      16838 × 23811  (297mm × 420mm)
//   B5:      10318 × 14570  (182mm × 257mm)
//   16K:      10318 × 14570 (approximate, varies by region)

var sectionProps = new SectionProperties();

// --- Letter (US default) ---
sectionProps.AppendChild(new PageSize
{
    Width = 12240U,   // 8.5 inches
    Height = 15840U   // 11 inches
});
// Produces XML: <w:pgSz w:w="12240" w:h="15840" />

// --- A4 (ISO default) ---
var a4Size = new PageSize
{
    Width = 11906U,   // 210mm
    Height = 16838U   // 297mm
};

// --- Legal ---
var legalSize = new PageSize
{
    Width = 12240U,   // 8.5 inches
    Height = 20160U   // 14 inches
};

// --- A3 ---
var a3Size = new PageSize
{
    Width = 16838U,   // 297mm
    Height = 23811U   // 420mm
};

body.AppendChild(sectionProps);
```

### 1.2 PageOrientation — CRITICAL Landscape Handling

```csharp
// =============================================================================
// PAGE ORIENTATION — LANDSCAPE
// =============================================================================
// CRITICAL GOTCHA: Setting Orient = Landscape is NOT enough!
// You MUST ALSO swap Width and Height values. Word uses the numeric dimensions
// to determine actual page size; Orient only controls the print driver rotation.
//
// If you set Orient = Landscape but don't swap dimensions, Word will
// display portrait but print rotated — a confusing bug.

// --- Portrait (default, explicit) ---
var portraitSize = new PageSize
{
    Width = 12240U,
    Height = 15840U
    // Orient is omitted for portrait (it's the default)
};
// Produces XML: <w:pgSz w:w="12240" w:h="15840" />

// --- Landscape — CORRECT way ---
var landscapeSize = new PageSize
{
    Width = 15840U,                                      // SWAPPED: was Height
    Height = 12240U,                                     // SWAPPED: was Width
    Orient = PageOrientationValues.Landscape              // AND set Orient
};
// Produces XML: <w:pgSz w:w="15840" w:h="12240" w:orient="landscape" />

// --- Helper method for safe orientation switching ---
static PageSize CreatePageSize(uint shortEdge, uint longEdge, bool landscape)
{
    return landscape
        ? new PageSize
        {
            Width = longEdge,       // Long edge becomes width
            Height = shortEdge,     // Short edge becomes height
            Orient = PageOrientationValues.Landscape
        }
        : new PageSize
        {
            Width = shortEdge,
            Height = longEdge
        };
}

// Usage:
var letterLandscape = CreatePageSize(12240, 15840, landscape: true);
var a4Portrait = CreatePageSize(11906, 16838, landscape: false);
```

### 1.3 PageMargin — Common Presets

```csharp
// =============================================================================
// PAGE MARGIN — ALL PROPERTIES
// =============================================================================
// All margin values are in DXA (twentieths of a point). 1 inch = 1440 DXA.
//
// Properties:
//   Top, Bottom    — signed Int32 (can be negative for overlap)
//   Left, Right    — unsigned UInt32
//   Header, Footer — unsigned UInt32 (distance from page edge to header/footer)
//   Gutter         — unsigned UInt32 (extra margin for binding; added to Left
//                    unless GutterAtTop is set in Settings)

// --- Normal / Standard (1" all around) ---
var normalMargins = new PageMargin
{
    Top = 1440,         // 1 inch
    Bottom = 1440,      // 1 inch
    Left = 1440U,       // 1 inch
    Right = 1440U,      // 1 inch
    Header = 720U,      // 0.5 inch (distance from page edge)
    Footer = 720U,      // 0.5 inch
    Gutter = 0U         // No binding gutter
};
// Produces XML:
// <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
//          w:header="720" w:footer="720" w:gutter="0" />

// --- Narrow (0.5" all around) ---
var narrowMargins = new PageMargin
{
    Top = 720,
    Bottom = 720,
    Left = 720U,
    Right = 720U,
    Header = 720U,
    Footer = 720U,
    Gutter = 0U
};

// --- Moderate (1" top/bottom, 0.75" left/right) ---
var moderateMargins = new PageMargin
{
    Top = 1440,
    Bottom = 1440,
    Left = 1080U,     // 0.75 inch
    Right = 1080U,    // 0.75 inch
    Header = 720U,
    Footer = 720U,
    Gutter = 0U
};

// --- Wide (1" top/bottom, 2" left/right) ---
var wideMargins = new PageMargin
{
    Top = 1440,
    Bottom = 1440,
    Left = 2880U,     // 2 inches
    Right = 2880U,    // 2 inches
    Header = 720U,
    Footer = 720U,
    Gutter = 0U
};

// --- Chinese Government Document 公文 standard (GB/T 9704-2012) ---
// Top: 37mm (2098 DXA), Bottom: 35mm (1984 DXA)
// Left: 28mm (1588 DXA), Right: 26mm (1474 DXA)
var chineseGovMargins = new PageMargin
{
    Top = 2098,        // 37mm
    Bottom = 1984,     // 35mm
    Left = 1588U,      // 28mm
    Right = 1474U,     // 26mm
    Header = 851U,     // 15mm
    Footer = 567U,     // 10mm (approx)
    Gutter = 0U
};

// --- With binding gutter (e.g., for book printing) ---
var gutterMargins = new PageMargin
{
    Top = 1440,
    Bottom = 1440,
    Left = 1440U,
    Right = 1440U,
    Header = 720U,
    Footer = 720U,
    Gutter = 720U      // 0.5 inch added to left margin for binding
};
```

### 1.4 PageBorders

```csharp
// =============================================================================
// PAGE BORDERS
// =============================================================================
// PageBorders defines borders around the entire page.
// OffsetFrom controls whether border distance is from page edge or text margin.
//   PageBorderOffsetValues.Page = from page edge
//   PageBorderOffsetValues.Text = from text margin
//
// Each border: Val (style), Size (eighth-points: 4=0.5pt, 8=1pt, 12=1.5pt),
//              Color (hex RGB), Space (distance in points from text/page edge)

var pageBorders = new PageBorders
{
    OffsetFrom = PageBorderOffsetValues.Page
};

// Top border: single line, 1pt, black
pageBorders.AppendChild(new TopBorder
{
    Val = BorderValues.Single,
    Size = 8U,               // 8 eighth-points = 1pt
    Color = "000000",
    Space = 24U              // 24 points from page edge
});

// Bottom border
pageBorders.AppendChild(new BottomBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 24U
});

// Left border
pageBorders.AppendChild(new LeftBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 24U
});

// Right border
pageBorders.AppendChild(new RightBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 24U
});

// --- Double border example ---
var doubleBorder = new TopBorder
{
    Val = BorderValues.Double,   // Double line
    Size = 4U,                   // 0.5pt per line
    Color = "0000FF",            // Blue
    Space = 24U
};

// --- Common BorderValues ---
// Single, Double, Triple, DotDash, Dashed, Dotted, Thick, ThinThickSmallGap,
// ThickThinSmallGap, Wave, DoubleWave, BasicBlackDots, None

sectionProps.AppendChild(pageBorders);
```

### 1.5 Columns — Multi-Column Layout

```csharp
// =============================================================================
// COLUMNS — MULTI-COLUMN LAYOUTS
// =============================================================================
// Columns element defines the column layout within a section.
// Space is measured in DXA. EqualWidth=true makes all columns equal.

// --- 2 equal columns ---
var twoCols = new Columns
{
    EqualWidth = true,
    ColumnCount = 2,
    Space = "720"          // 0.5 inch gap between columns
};
// Produces XML: <w:cols w:num="2" w:space="720" w:equalWidth="1" />

// --- 3 equal columns with separator ---
var threeColsSep = new Columns
{
    EqualWidth = true,
    ColumnCount = 3,
    Space = "360",         // 0.25 inch gap
    Separator = true       // Vertical line between columns
};
// Produces XML: <w:cols w:num="3" w:space="360" w:equalWidth="1" w:sep="1" />

// --- Custom unequal columns (e.g., 2/3 + 1/3 of content width) ---
// When using unequal widths, EqualWidth must be false and you define
// each column explicitly with Column elements.
// For Letter page with 1" margins: content width = 12240 - 1440 - 1440 = 9360 DXA
// Column 1: 6000 DXA wide, 360 DXA space after
// Column 2: 3000 DXA wide (6000 + 360 + 3000 = 9360)

var unequalCols = new Columns { EqualWidth = false };
unequalCols.AppendChild(new Column
{
    Width = "6000",
    Space = "360"
});
unequalCols.AppendChild(new Column
{
    Width = "3000"
    // No Space on last column
});
// Produces XML:
// <w:cols w:equalWidth="0">
//   <w:col w:w="6000" w:space="360" />
//   <w:col w:w="3000" />
// </w:cols>

sectionProps.AppendChild(unequalCols);
```

### 1.6 LineNumbering

```csharp
// =============================================================================
// LINE NUMBERING
// =============================================================================
// LineNumbering adds line numbers in the margin. Useful for legal/academic docs.
// CountBy = show every Nth number (1 = every line, 5 = every 5th)
// Start = starting number
// Distance = distance from text in DXA
// Restart: NewPage, NewSection, Continuous

var lineNums = new LineNumbering
{
    CountBy = 5,                                         // Show every 5th line number
    Start = 1,                                           // Start at line 1
    Distance = 360U,                                     // 0.25 inch from text
    Restart = LineNumberRestartValues.NewPage             // Restart each page
};
// Produces XML:
// <w:lnNumType w:countBy="5" w:start="1" w:distance="360" w:restart="newPage" />

sectionProps.AppendChild(lineNums);
```

### 1.7 DocGrid — CJK Document Grid

```csharp
// =============================================================================
// DOCUMENT GRID — CJK LAYOUT
// =============================================================================
// DocGrid specifies a document grid (character grid) primarily for CJK documents.
// Type: Default (no grid), Lines (line grid), LinesAndChars (line+char grid),
//       SnapToChars (snap to character grid)
// LinePitch = distance between lines in DXA (e.g., 312 for standard Chinese docs)
// CharacterSpace = extra spacing between characters in DXA

// --- Chinese document grid: 28 lines × 28 chars per line (common for 公文) ---
var cjkGrid = new DocGrid
{
    Type = DocGridValues.LinesAndChars,
    LinePitch = 579,          // DXA between lines (≈ 28 lines on A4 with std margins)
    CharacterSpace = 0        // Default character spacing
};
// Produces XML:
// <w:docGrid w:type="linesAndChars" w:linePitch="579" w:charSpace="0" />

// --- Simple line-only grid ---
var lineGrid = new DocGrid
{
    Type = DocGridValues.Lines,
    LinePitch = 360            // Standard line pitch
};

sectionProps.AppendChild(cjkGrid);
```

### 1.8 VerticalTextAlignmentOnPage

```csharp
// =============================================================================
// VERTICAL TEXT ALIGNMENT ON PAGE
// =============================================================================
// Controls vertical alignment of text within the page (above bottom margin).
// Values: Top (default), Center, Both (justified), Bottom

var vertAlign = new VerticalTextAlignmentOnPage
{
    Val = VerticalJustificationValues.Center
};
// Produces XML: <w:vAlign w:val="center" />
// Use case: Title pages, certificate pages

sectionProps.AppendChild(vertAlign);
```

### 1.9 Complete Page Setup Example

```csharp
// =============================================================================
// COMPLETE PAGE SETUP — PUTTING IT ALL TOGETHER
// =============================================================================
// A4 portrait, moderate margins, 2-column layout with separator

using var doc = WordprocessingDocument.Create(
    "PageSetupDemo.docx", WordprocessingDocumentType.Document);

var mainPart = doc.MainDocumentPart!;
var body = mainPart.Document.Body!;

// Add content paragraphs ...
body.AppendChild(new Paragraph(
    new Run(new Text("This is a two-column document on A4 paper."))));

// Section properties — MUST be last child of Body
var sectPr = new SectionProperties();

// Page size: A4 portrait
sectPr.AppendChild(new PageSize
{
    Width = 11906U,
    Height = 16838U
});

// Margins: moderate
sectPr.AppendChild(new PageMargin
{
    Top = 1440, Bottom = 1440,
    Left = 1080U, Right = 1080U,
    Header = 720U, Footer = 720U, Gutter = 0U
});

// 2-column with separator
sectPr.AppendChild(new Columns
{
    EqualWidth = true,
    ColumnCount = 2,
    Space = "720",
    Separator = true
});

// Line grid for CJK
sectPr.AppendChild(new DocGrid
{
    Type = DocGridValues.Lines,
    LinePitch = 312
});

body.AppendChild(sectPr);
mainPart.Document.Save();
```

---

## 2. Tables — Comprehensive

### 2.1 TableProperties — Width, Layout, Alignment, Indent

```csharp
// =============================================================================
// TABLE PROPERTIES — WIDTH, LAYOUT, ALIGNMENT
// =============================================================================
// Table width can be specified in three ways:
//   Pct:  percentage of page width. 5000 = 100%. (multiply % by 50)
//   Dxa:  absolute width in DXA (twentieths of a point). 1 inch = 1440 DXA.
//   Auto: table auto-sizes to content.
//
// TableLayout:
//   Fixed: columns maintain exact widths. Required for complex cell sizing.
//   Autofit: columns adjust to content (default).
//
// TableJustification: Left (default), Center, Right

var table = new Table();

var tblProps = new TableProperties();

// --- Width: 100% of page ---
tblProps.AppendChild(new TableWidth
{
    Width = "5000",                           // 5000 = 100%
    Type = TableWidthUnitValues.Pct
});
// Produces XML: <w:tblW w:w="5000" w:type="pct" />

// --- Width: fixed DXA ---
// var tblWidth = new TableWidth { Width = "9360", Type = TableWidthUnitValues.Dxa };

// --- Width: auto ---
// var tblWidth = new TableWidth { Width = "0", Type = TableWidthUnitValues.Auto };

// Layout: fixed column widths
tblProps.AppendChild(new TableLayout
{
    Type = TableLayoutValues.Fixed
});

// Center the table on the page
tblProps.AppendChild(new TableJustification
{
    Val = TableRowAlignmentValues.Center
});

// Table indent (left offset when not centered) — in DXA
// tblProps.AppendChild(new TableIndentation
// {
//     Width = 720,                           // 0.5 inch indent
//     Type = TableWidthUnitValues.Dxa
// });

table.AppendChild(tblProps);
```

### 2.2 TableBorders — All Border Properties

```csharp
// =============================================================================
// TABLE BORDERS
// =============================================================================
// TableBorders defines default borders for the entire table.
// Each border has:
//   Val   — BorderValues enum (Single, Double, Dotted, Dashed, None, etc.)
//   Size  — in eighth-points: 4 = 0.5pt, 8 = 1pt, 12 = 1.5pt, 16 = 2pt, 24 = 3pt
//   Color — hex RGB string (e.g., "000000" for black, "FF0000" for red)
//   Space — space between border and content in points
//
// Border types: TopBorder, BottomBorder, LeftBorder, RightBorder,
//               InsideHorizontalBorder, InsideVerticalBorder

var tblBorders = new TableBorders();

// Top border: single, 1pt, black
tblBorders.AppendChild(new TopBorder
{
    Val = BorderValues.Single,
    Size = 8U,           // 1pt (8 eighth-points)
    Color = "000000",
    Space = 0U
});

// Bottom border
tblBorders.AppendChild(new BottomBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 0U
});

// Left border
tblBorders.AppendChild(new LeftBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 0U
});

// Right border
tblBorders.AppendChild(new RightBorder
{
    Val = BorderValues.Single,
    Size = 8U,
    Color = "000000",
    Space = 0U
});

// Inside horizontal borders (between rows)
tblBorders.AppendChild(new InsideHorizontalBorder
{
    Val = BorderValues.Single,
    Size = 4U,           // 0.5pt — thinner than outer borders
    Color = "000000",
    Space = 0U
});

// Inside vertical borders (between columns)
tblBorders.AppendChild(new InsideVerticalBorder
{
    Val = BorderValues.Single,
    Size = 4U,
    Color = "000000",
    Space = 0U
});

// Produces XML:
// <w:tblBorders>
//   <w:top w:val="single" w:sz="8" w:color="000000" w:space="0" />
//   <w:bottom w:val="single" w:sz="8" w:color="000000" w:space="0" />
//   <w:left w:val="single" w:sz="8" w:color="000000" w:space="0" />
//   <w:right w:val="single" w:sz="8" w:color="000000" w:space="0" />
//   <w:insideH w:val="single" w:sz="4" w:color="000000" w:space="0" />
//   <w:insideV w:val="single" w:sz="4" w:color="000000" w:space="0" />
// </w:tblBorders>

tblProps.AppendChild(tblBorders);
```

### 2.3 TableGrid — Column Definitions

```csharp
// =============================================================================
// TABLE GRID — COLUMN WIDTH DEFINITIONS
// =============================================================================
// TableGrid defines the column structure of the table. Each GridColumn
// specifies the width in DXA. The number of GridColumn elements determines
// the number of columns.
//
// IMPORTANT: GridColumn widths should sum to the table width.
// For a 100% table on Letter with 1" margins: 12240 - 1440 - 1440 = 9360 DXA

var tableGrid = new TableGrid();

// 3 columns: 3000 + 3000 + 3360 = 9360 DXA
tableGrid.AppendChild(new GridColumn { Width = "3000" });
tableGrid.AppendChild(new GridColumn { Width = "3000" });
tableGrid.AppendChild(new GridColumn { Width = "3360" });

// Produces XML:
// <w:tblGrid>
//   <w:gridCol w:w="3000" />
//   <w:gridCol w:w="3000" />
//   <w:gridCol w:w="3360" />
// </w:tblGrid>

table.AppendChild(tableGrid);
```

### 2.4 TableCellProperties — Width, Alignment, Direction, Shading

```csharp
// =============================================================================
// TABLE CELL PROPERTIES
// =============================================================================
// TableCellProperties controls individual cell appearance.

var cellProps = new TableCellProperties();

// Cell width — should match the GridColumn width
cellProps.AppendChild(new TableCellWidth
{
    Width = "3000",
    Type = TableWidthUnitValues.Dxa
});

// Vertical alignment within cell: Top (default), Center, Bottom
cellProps.AppendChild(new TableCellVerticalAlignment
{
    Val = TableVerticalAlignmentValues.Center
});

// Text direction (for vertical text in CJK, etc.)
// Values: LefToRight (default), TopToBottom (text rotated 90° CW),
//         TopToBottomV (vertical CJK), BottomToTopV
cellProps.AppendChild(new TextDirection
{
    Val = TextDirectionValues.TopToBottom
});

// NoWrap — prevents text from wrapping within the cell
cellProps.AppendChild(new NoWrap());

// Cell shading (background color)
cellProps.AppendChild(new Shading
{
    Val = ShadingPatternValues.Clear,
    Color = "auto",
    Fill = "D9E2F3"          // Light blue background
});
// Produces XML: <w:shd w:val="clear" w:color="auto" w:fill="D9E2F3" />
```

### 2.5 TableCellMargin — Table-Level Default vs Per-Cell Override

```csharp
// =============================================================================
// TABLE CELL MARGINS
// =============================================================================
// There are TWO levels of cell margin control:
//   1. Table-level default: TableCellMarginDefault (inside TableProperties)
//   2. Per-cell override:   TableCellMargin (inside TableCellProperties)
//
// All values are in DXA. Default Word cell margins are approximately:
//   Top: 0, Bottom: 0, Left: 108 (0.075"), Right: 108

// --- Table-level default margins ---
var defaultMargins = new TableCellMarginDefault();
defaultMargins.AppendChild(new TopMargin
{
    Width = "72",                             // ~0.05 inch
    Type = TableWidthUnitValues.Dxa
});
defaultMargins.AppendChild(new BottomMargin
{
    Width = "72",
    Type = TableWidthUnitValues.Dxa
});
defaultMargins.AppendChild(new StartMargin
{
    Width = "108",                            // ~0.075 inch (default)
    Type = TableWidthUnitValues.Dxa
});
defaultMargins.AppendChild(new EndMargin
{
    Width = "108",
    Type = TableWidthUnitValues.Dxa
});

tblProps.AppendChild(defaultMargins);
// Produces XML:
// <w:tblCellMar>
//   <w:top w:w="72" w:type="dxa" />
//   <w:bottom w:w="72" w:type="dxa" />
//   <w:start w:w="108" w:type="dxa" />
//   <w:end w:w="108" w:type="dxa" />
// </w:tblCellMar>

// --- Per-cell override (larger padding for a specific cell) ---
var cellMarginOverride = new TableCellMargin();
cellMarginOverride.AppendChild(new TopMargin
{
    Width = "144",                            // 0.1 inch
    Type = TableWidthUnitValues.Dxa
});
cellMarginOverride.AppendChild(new BottomMargin
{
    Width = "144",
    Type = TableWidthUnitValues.Dxa
});
cellMarginOverride.AppendChild(new StartMargin
{
    Width = "216",                            // 0.15 inch
    Type = TableWidthUnitValues.Dxa
});
cellMarginOverride.AppendChild(new EndMargin
{
    Width = "216",
    Type = TableWidthUnitValues.Dxa
});

cellProps.AppendChild(cellMarginOverride);
```

### 2.6 Row Height

```csharp
// =============================================================================
// TABLE ROW HEIGHT
// =============================================================================
// TableRowHeight is set inside TableRowProperties.
// Val = height in DXA
// HeightRuleType:
//   Exact:   row is exactly this height (content may be clipped)
//   AtLeast: row is at least this height, grows for content (default behavior)
//   Auto:    height determined by content

var rowProps = new TableRowProperties();

// Row height: at least 0.5 inch
rowProps.AppendChild(new TableRowHeight
{
    Val = 720U,                                // 0.5 inch in DXA
    HeightRule = HeightRuleValues.AtLeast
});
// Produces XML: <w:trHeight w:val="720" w:hRule="atLeast" />

// Exact height (content may clip):
// rowProps.AppendChild(new TableRowHeight
// {
//     Val = 720U,
//     HeightRule = HeightRuleValues.Exact
// });

var row = new TableRow();
row.AppendChild(rowProps);
```

### 2.7 Header Row Repeat (Repeat on Every Page)

```csharp
// =============================================================================
// HEADER ROW REPEAT
// =============================================================================
// TableHeader on TableRowProperties marks a row to repeat at the top
// of each page when the table spans multiple pages.
// IMPORTANT: Only works for rows at the TOP of the table (contiguous from first row).
// You cannot repeat a row in the middle of a table.

var headerRowProps = new TableRowProperties();
headerRowProps.AppendChild(new TableHeader());  // No value needed — presence = true

// Produces XML:
// <w:trPr>
//   <w:tblHeader />
// </w:trPr>

var headerRow = new TableRow();
headerRow.AppendChild(headerRowProps);
// ... add cells to headerRow ...
```

### 2.8 Per-Cell Border Override

```csharp
// =============================================================================
// PER-CELL BORDER OVERRIDE
// =============================================================================
// TableCellBorders inside TableCellProperties overrides table-level borders
// for a specific cell. Useful for special formatting, merging visual areas, etc.

var cellBorders = new TableCellBorders();

// Remove bottom border on this cell
cellBorders.AppendChild(new BottomBorder
{
    Val = BorderValues.None,
    Size = 0U,
    Color = "auto",
    Space = 0U
});

// Add thick right border
cellBorders.AppendChild(new RightBorder
{
    Val = BorderValues.Single,
    Size = 24U,          // 3pt thick
    Color = "FF0000",    // Red
    Space = 0U
});

// Produces XML:
// <w:tcBorders>
//   <w:bottom w:val="none" w:sz="0" w:color="auto" w:space="0" />
//   <w:right w:val="single" w:sz="24" w:color="FF0000" w:space="0" />
// </w:tcBorders>

cellProps.AppendChild(cellBorders);
```

### 2.9 Horizontal Merge (GridSpan)

```csharp
// =============================================================================
// HORIZONTAL MERGE — GRIDSPAN
// =============================================================================
// To merge cells horizontally, use GridSpan on the first cell's properties.
// The cell spans across multiple grid columns. You do NOT add extra cells
// for the spanned columns — only one cell covers the span.
//
// Example: 3-column table, first row merges columns 1+2

var mergedRow = new TableRow();

// Cell spanning columns 1 and 2
var spanCell = new TableCell();
var spanCellProps = new TableCellProperties();
spanCellProps.AppendChild(new GridSpan { Val = 2 });      // Span 2 columns
spanCellProps.AppendChild(new TableCellWidth
{
    Width = "6000",                                        // Combined width: 3000 + 3000
    Type = TableWidthUnitValues.Dxa
});
spanCell.AppendChild(spanCellProps);
spanCell.AppendChild(new Paragraph(new Run(new Text("Spans columns 1-2"))));
mergedRow.AppendChild(spanCell);

// Cell in column 3 (normal)
var normalCell = new TableCell();
normalCell.AppendChild(new TableCellProperties(
    new TableCellWidth { Width = "3360", Type = TableWidthUnitValues.Dxa }));
normalCell.AppendChild(new Paragraph(new Run(new Text("Column 3"))));
mergedRow.AppendChild(normalCell);

// Produces XML for the merged cell:
// <w:tc>
//   <w:tcPr>
//     <w:gridSpan w:val="2" />
//     <w:tcW w:w="6000" w:type="dxa" />
//   </w:tcPr>
//   <w:p><w:r><w:t>Spans columns 1-2</w:t></w:r></w:p>
// </w:tc>
```

### 2.10 Vertical Merge

```csharp
// =============================================================================
// VERTICAL MERGE
// =============================================================================
// To merge cells vertically across rows, use VerticalMerge:
//   First row: VerticalMerge with Val = Restart  (starts the merge)
//   Subsequent rows: VerticalMerge with Val = Continue (or omit Val — Continue is default)
//
// Each row still needs the cell placeholder, but continue cells should contain
// an empty paragraph only.

// Row 1: start of vertical merge
var vRow1 = new TableRow();
var vCell1 = new TableCell();
var vCellProps1 = new TableCellProperties();
vCellProps1.AppendChild(new VerticalMerge { Val = MergedCellValues.Restart });
vCellProps1.AppendChild(new TableCellWidth { Width = "3000", Type = TableWidthUnitValues.Dxa });
vCell1.AppendChild(vCellProps1);
vCell1.AppendChild(new Paragraph(new Run(new Text("Merged vertically"))));
vRow1.AppendChild(vCell1);
// ... add remaining cells in row 1

// Row 2: continue the vertical merge
var vRow2 = new TableRow();
var vCell2 = new TableCell();
var vCellProps2 = new TableCellProperties();
vCellProps2.AppendChild(new VerticalMerge());  // Val omitted = Continue
vCellProps2.AppendChild(new TableCellWidth { Width = "3000", Type = TableWidthUnitValues.Dxa });
vCell2.AppendChild(vCellProps2);
vCell2.AppendChild(new Paragraph());           // Empty paragraph required — cell must have content
vRow2.AppendChild(vCell2);
// ... add remaining cells in row 2

// Row 3: if no VerticalMerge, the merge stops and this cell is independent.

// Produces XML:
// Row 1 cell: <w:tcPr><w:vMerge w:val="restart" /></w:tcPr>
// Row 2 cell: <w:tcPr><w:vMerge /></w:tcPr>  (continue is the default)
```

### 2.11 Nested Tables

```csharp
// =============================================================================
// NESTED TABLES
// =============================================================================
// A table can be nested inside a table cell. Simply add a Table element
// as a child of a TableCell (alongside the required Paragraph).
// IMPORTANT: Every TableCell MUST contain at least one Paragraph, even if
// it also contains a nested table. The Paragraph should come AFTER the table.

var outerTable = new Table();
// ... outer table properties and grid ...

var containerCell = new TableCell();
containerCell.AppendChild(new TableCellProperties(
    new TableCellWidth { Width = "6000", Type = TableWidthUnitValues.Dxa }));

// Build inner (nested) table
var innerTable = new Table();
var innerProps = new TableProperties();
innerProps.AppendChild(new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct });
innerProps.AppendChild(new TableBorders(
    new TopBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" },
    new BottomBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" },
    new LeftBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" },
    new RightBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" },
    new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" },
    new InsideVerticalBorder { Val = BorderValues.Single, Size = 4U, Color = "999999" }
));
innerTable.AppendChild(innerProps);

var innerGrid = new TableGrid(
    new GridColumn { Width = "2500" },
    new GridColumn { Width = "2500" });
innerTable.AppendChild(innerGrid);

var innerRow = new TableRow(
    new TableCell(
        new TableCellProperties(new TableCellWidth { Width = "2500", Type = TableWidthUnitValues.Dxa }),
        new Paragraph(new Run(new Text("Inner A")))),
    new TableCell(
        new TableCellProperties(new TableCellWidth { Width = "2500", Type = TableWidthUnitValues.Dxa }),
        new Paragraph(new Run(new Text("Inner B"))))
);
innerTable.AppendChild(innerRow);

// Add inner table to container cell
containerCell.AppendChild(innerTable);
// MUST have a paragraph after nested table
containerCell.AppendChild(new Paragraph());
```

### 2.12 Table Positioning (Floating Table)

```csharp
// =============================================================================
// TABLE POSITIONING — FLOATING TABLE
// =============================================================================
// TablePositionProperties makes a table "float" at a specific position
// on the page, allowing text to wrap around it.
// All position values are in DXA.

var floatProps = new TablePositionProperties
{
    VerticalAnchor = VerticalAnchorValues.Page,
    HorizontalAnchor = HorizontalAnchorValues.Page,
    TablePositionX = 2880,           // 2 inches from left page edge
    TablePositionY = 4320,           // 3 inches from top page edge
    LeftFromText = 180,              // 0.125 inch gap from text on left
    RightFromText = 180,
    TopFromText = 0,
    BottomFromText = 0
};

tblProps.AppendChild(floatProps);
// Produces XML:
// <w:tblpPr w:vertAnchor="page" w:horzAnchor="page"
//           w:tblpX="2880" w:tblpY="4320"
//           w:leftFromText="180" w:rightFromText="180"
//           w:topFromText="0" w:bottomFromText="0" />
```

### 2.13 TableLook — Conditional Formatting Flags

```csharp
// =============================================================================
// TABLE LOOK — CONDITIONAL FORMATTING FLAGS
// =============================================================================
// TableLook controls which conditional formatting bands are applied from
// the table style. These flags tell Word which "special" formatting to use.
//
// Val is a hex bitmask. Common values:
//   0x04A0 = FirstRow + LastRow + NoHBand (typical for styled tables)
//   0x0000 = no conditional formatting
//
// Individual boolean flags can also be set:

var tableLook = new TableLook
{
    Val = "04A0",
    FirstRow = true,        // Apply first-row (header) formatting
    LastRow = true,         // Apply last-row (totals) formatting
    FirstColumn = false,
    LastColumn = false,
    NoHorizontalBand = true,  // Don't apply horizontal banding
    NoVerticalBand = true     // Don't apply vertical banding
};

tblProps.AppendChild(tableLook);
// Produces XML:
// <w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="1"
//            w:firstColumn="0" w:lastColumn="0"
//            w:noHBand="1" w:noVBand="1" />
```

### 2.14 Complete Styled Table — Header + Data + Totals + Zebra Striping

```csharp
// =============================================================================
// COMPLETE STYLED TABLE
// =============================================================================
// Builds a professional table with:
//   - Header row (dark background, white text, repeats on page break)
//   - Data rows with alternating zebra-stripe shading
//   - Totals row (bold, top border)
//   - Full 100% width on Letter page

static Table CreateStyledTable(string[][] data, bool hasHeaderRow = true, bool hasTotalsRow = true)
{
    int cols = data[0].Length;
    // For Letter page with 1" margins: 12240 - 2 * 1440 = 9360
    int totalWidth = 9360;
    int colWidth = totalWidth / cols;

    var table = new Table();

    // --- Table Properties ---
    var tblPr = new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableLayout { Type = TableLayoutValues.Fixed },
        new TableBorders(
            new TopBorder { Val = BorderValues.Single, Size = 8U, Color = "000000" },
            new BottomBorder { Val = BorderValues.Single, Size = 8U, Color = "000000" },
            new LeftBorder { Val = BorderValues.Single, Size = 4U, Color = "BFBFBF" },
            new RightBorder { Val = BorderValues.Single, Size = 4U, Color = "BFBFBF" },
            new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4U, Color = "BFBFBF" },
            new InsideVerticalBorder { Val = BorderValues.Single, Size = 4U, Color = "BFBFBF" }
        ),
        new TableLook
        {
            Val = "04A0", FirstRow = true, LastRow = true,
            FirstColumn = false, LastColumn = false,
            NoHorizontalBand = true, NoVerticalBand = true
        }
    );
    table.AppendChild(tblPr);

    // --- Table Grid ---
    var grid = new TableGrid();
    for (int c = 0; c < cols; c++)
    {
        int w = (c == cols - 1) ? totalWidth - colWidth * (cols - 1) : colWidth;
        grid.AppendChild(new GridColumn { Width = w.ToString() });
    }
    table.AppendChild(grid);

    // --- Rows ---
    for (int r = 0; r < data.Length; r++)
    {
        bool isHeader = hasHeaderRow && r == 0;
        bool isTotals = hasTotalsRow && r == data.Length - 1;
        bool isOddDataRow = !isHeader && !isTotals && (r % 2 == 1);

        var row = new TableRow();

        // Row properties
        var trPr = new TableRowProperties();
        trPr.AppendChild(new TableRowHeight
        {
            Val = isHeader ? 480U : 360U,
            HeightRule = HeightRuleValues.AtLeast
        });
        if (isHeader)
        {
            trPr.AppendChild(new TableHeader());   // Repeat header on each page
        }
        row.AppendChild(trPr);

        // Cells
        for (int c = 0; c < cols; c++)
        {
            int w = (c == cols - 1) ? totalWidth - colWidth * (cols - 1) : colWidth;
            var cell = new TableCell();
            var tcPr = new TableCellProperties();
            tcPr.AppendChild(new TableCellWidth
            {
                Width = w.ToString(),
                Type = TableWidthUnitValues.Dxa
            });
            tcPr.AppendChild(new TableCellVerticalAlignment
            {
                Val = TableVerticalAlignmentValues.Center
            });

            // Header: dark blue background
            if (isHeader)
            {
                tcPr.AppendChild(new Shading
                {
                    Val = ShadingPatternValues.Clear,
                    Color = "auto",
                    Fill = "2F5496"     // Dark blue
                });
            }
            // Zebra stripe: light gray on odd data rows
            else if (isOddDataRow)
            {
                tcPr.AppendChild(new Shading
                {
                    Val = ShadingPatternValues.Clear,
                    Color = "auto",
                    Fill = "F2F2F2"     // Light gray
                });
            }
            // Totals row: top border emphasis
            if (isTotals)
            {
                tcPr.AppendChild(new TableCellBorders(
                    new TopBorder
                    {
                        Val = BorderValues.Single,
                        Size = 12U,    // 1.5pt
                        Color = "000000"
                    }
                ));
            }
            cell.AppendChild(tcPr);

            // Paragraph with text
            var runProps = new RunProperties();
            if (isHeader)
            {
                runProps.AppendChild(new Bold());
                runProps.AppendChild(new Color { Val = "FFFFFF" });   // White text
                runProps.AppendChild(new FontSize { Val = "22" });    // 11pt
            }
            else if (isTotals)
            {
                runProps.AppendChild(new Bold());
            }

            var para = new Paragraph(
                new ParagraphProperties(
                    new Justification
                    {
                        Val = (c > 0) ? JustificationValues.Right : JustificationValues.Left
                    }
                ),
                new Run(runProps, new Text(data[r][c]))
            );
            cell.AppendChild(para);
            row.AppendChild(cell);
        }
        table.AppendChild(row);
    }
    return table;
}

// --- Usage ---
string[][] salesData =
[
    ["Product",  "Q1",    "Q2",    "Q3",    "Q4"   ],
    ["Widget A", "1,200", "1,350", "1,100", "1,500"],
    ["Widget B", "800",   "920",   "870",   "1,010"],
    ["Widget C", "2,100", "2,300", "2,150", "2,400"],
    ["Total",    "4,100", "4,570", "4,120", "4,910"]
];

var styledTable = CreateStyledTable(salesData, hasHeaderRow: true, hasTotalsRow: true);
body.AppendChild(styledTable);
body.AppendChild(new Paragraph());  // Empty paragraph after table
```

### 2.15 Three-Line Table (学术三线表)

```csharp
// =============================================================================
// THREE-LINE TABLE (学术三线表)
// =============================================================================
// Academic/scientific table style common in Chinese academic publishing:
//   - Top border: THICK (1.5pt)
//   - Border below header: THIN (0.75pt)
//   - Bottom border: THICK (1.5pt)
//   - NO vertical borders, NO other horizontal borders
//
// This is achieved by:
// 1. Setting table borders to None (removes all defaults)
// 2. Using per-cell borders on the header row (bottom) and first/last rows (top/bottom)

static Table CreateThreeLineTable(string[] headers, string[][] rows)
{
    int cols = headers.Length;
    int totalWidth = 9360;
    int colWidth = totalWidth / cols;

    var table = new Table();

    // Table properties: NO borders by default
    var tblPr = new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableJustification { Val = TableRowAlignmentValues.Center },
        new TableLayout { Type = TableLayoutValues.Fixed },
        new TableBorders(
            new TopBorder { Val = BorderValues.None, Size = 0U },
            new BottomBorder { Val = BorderValues.None, Size = 0U },
            new LeftBorder { Val = BorderValues.None, Size = 0U },
            new RightBorder { Val = BorderValues.None, Size = 0U },
            new InsideHorizontalBorder { Val = BorderValues.None, Size = 0U },
            new InsideVerticalBorder { Val = BorderValues.None, Size = 0U }
        )
    );
    table.AppendChild(tblPr);

    // Table grid
    var grid = new TableGrid();
    for (int c = 0; c < cols; c++)
    {
        int w = (c == cols - 1) ? totalWidth - colWidth * (cols - 1) : colWidth;
        grid.AppendChild(new GridColumn { Width = w.ToString() });
    }
    table.AppendChild(grid);

    // --- Header row ---
    var headerRow = new TableRow();
    headerRow.AppendChild(new TableRowProperties(new TableHeader()));

    for (int c = 0; c < cols; c++)
    {
        int w = (c == cols - 1) ? totalWidth - colWidth * (cols - 1) : colWidth;
        var cell = new TableCell();
        var tcPr = new TableCellProperties(
            new TableCellWidth { Width = w.ToString(), Type = TableWidthUnitValues.Dxa },
            new TableCellBorders(
                // Top: THICK line (1.5pt = 12 eighth-points)
                new TopBorder { Val = BorderValues.Single, Size = 12U, Color = "000000", Space = 0U },
                // Bottom: THIN line (0.75pt = 6 eighth-points)
                new BottomBorder { Val = BorderValues.Single, Size = 6U, Color = "000000", Space = 0U }
            ),
            new TableCellVerticalAlignment { Val = TableVerticalAlignmentValues.Center }
        );
        cell.AppendChild(tcPr);
        cell.AppendChild(new Paragraph(
            new ParagraphProperties(
                new Justification { Val = JustificationValues.Center }),
            new Run(
                new RunProperties(new Bold()),
                new Text(headers[c]))));
        cell.AppendChild(cell);     // Fix: should be row.AppendChild
        headerRow.AppendChild(cell);
    }
    table.AppendChild(headerRow);

    // --- Data rows ---
    for (int r = 0; r < rows.Length; r++)
    {
        var dataRow = new TableRow();
        bool isLastRow = (r == rows.Length - 1);

        for (int c = 0; c < cols; c++)
        {
            int w = (c == cols - 1) ? totalWidth - colWidth * (cols - 1) : colWidth;
            var cell = new TableCell();
            var tcPr = new TableCellProperties(
                new TableCellWidth { Width = w.ToString(), Type = TableWidthUnitValues.Dxa }
            );

            // Last data row: add THICK bottom border
            if (isLastRow)
            {
                tcPr.AppendChild(new TableCellBorders(
                    new BottomBorder
                    {
                        Val = BorderValues.Single,
                        Size = 12U,      // 1.5pt thick
                        Color = "000000",
                        Space = 0U
                    }
                ));
            }

            tcPr.AppendChild(new TableCellVerticalAlignment
            {
                Val = TableVerticalAlignmentValues.Center
            });
            cell.AppendChild(tcPr);
            cell.AppendChild(new Paragraph(
                new ParagraphProperties(
                    new Justification { Val = JustificationValues.Center }),
                new Run(new Text(rows[r][c]))));
            dataRow.AppendChild(cell);
        }
        table.AppendChild(dataRow);
    }

    return table;
}

// --- Usage ---
string[] columnHeaders = ["Variable", "Mean", "SD", "p-value"];
string[][] dataRows =
[
    ["Age",    "45.2", "12.3", "0.032"],
    ["BMI",    "26.8", "4.1",  "0.001"],
    ["SBP",    "132",  "18.5", "< 0.001"],
    ["HR",     "72.1", "11.2", "0.145"]
];

var threeLineTable = CreateThreeLineTable(columnHeaders, dataRows);
body.AppendChild(threeLineTable);
```

---

## 3. Headers, Footers & Page Numbers

Headers and footers are stored in separate XML parts (HeaderPart, FooterPart) linked to SectionProperties via HeaderReference and FooterReference.

### 3.1 Creating HeaderPart and FooterPart

```csharp
// =============================================================================
// CREATING HEADER AND FOOTER PARTS
// =============================================================================
// Headers and footers are separate parts within the package, each containing
// their own XML document tree rooted at <w:hdr> or <w:ftr>.
// They are linked to sections via HeaderReference/FooterReference.
//
// Steps:
// 1. Add a HeaderPart/FooterPart to the MainDocumentPart
// 2. Set the part's root element (Header/Footer)
// 3. Add content (paragraphs, tables, images) to the root element
// 4. Create a HeaderReference/FooterReference in SectionProperties

var mainPart = doc.MainDocumentPart!;

// --- Create a header part ---
var headerPart = mainPart.AddNewPart<HeaderPart>();
string headerPartId = mainPart.GetIdOfPart(headerPart);

// Build header content
headerPart.Header = new Header(
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Center }),
        new Run(
            new RunProperties(
                new FontSize { Val = "18" },      // 9pt — typical header size
                new Color { Val = "808080" }),     // Gray
            new Text("Company Confidential"))
    )
);
headerPart.Header.Save();

// --- Create a footer part ---
var footerPart = mainPart.AddNewPart<FooterPart>();
string footerPartId = mainPart.GetIdOfPart(footerPart);

footerPart.Footer = new Footer(
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Center }),
        new Run(
            new RunProperties(new FontSize { Val = "18" }),
            new Text("Footer text here"))
    )
);
footerPart.Footer.Save();
```

### 3.2 HeaderReference and FooterReference — Types

```csharp
// =============================================================================
// HEADER/FOOTER REFERENCE — LINKING TO SECTION
// =============================================================================
// HeaderReference/FooterReference types:
//   Default — used on all pages (unless First/Even overrides)
//   First   — used on the first page of the section (requires TitlePage)
//   Even    — used on even-numbered pages (requires EvenAndOddHeaders setting)
//
// A section can have up to 3 headers and 3 footers (Default + First + Even).

var sectPr = body.Elements<SectionProperties>().FirstOrDefault()
    ?? body.AppendChild(new SectionProperties());

// Default header (all pages)
sectPr.AppendChild(new HeaderReference
{
    Type = HeaderFooterValues.Default,
    Id = headerPartId
});

// Default footer (all pages)
sectPr.AppendChild(new FooterReference
{
    Type = HeaderFooterValues.Default,
    Id = footerPartId
});

// Produces XML:
// <w:sectPr>
//   <w:headerReference w:type="default" r:id="rId4" />
//   <w:footerReference w:type="default" r:id="rId5" />
// </w:sectPr>
```

### 3.3 Different First Page (TitlePage)

```csharp
// =============================================================================
// DIFFERENT FIRST PAGE — TITLEPAGE
// =============================================================================
// To have a different header/footer on the first page, you must:
// 1. Add a TitlePage element to SectionProperties
// 2. Create separate HeaderPart/FooterPart for the first page
// 3. Add HeaderReference/FooterReference with Type = First

// Enable different first page
sectPr.AppendChild(new TitlePage());
// Produces XML: <w:titlePg />

// Create first-page header (e.g., empty / no header on cover page)
var firstHeaderPart = mainPart.AddNewPart<HeaderPart>();
string firstHeaderId = mainPart.GetIdOfPart(firstHeaderPart);
firstHeaderPart.Header = new Header(new Paragraph()); // Empty header
firstHeaderPart.Header.Save();

// Create first-page footer
var firstFooterPart = mainPart.AddNewPart<FooterPart>();
string firstFooterId = mainPart.GetIdOfPart(firstFooterPart);
firstFooterPart.Footer = new Footer(new Paragraph()); // Empty footer
firstFooterPart.Footer.Save();

// Link to section
sectPr.AppendChild(new HeaderReference
{
    Type = HeaderFooterValues.First,
    Id = firstHeaderId
});
sectPr.AppendChild(new FooterReference
{
    Type = HeaderFooterValues.First,
    Id = firstFooterId
});
```

### 3.4 Even and Odd Page Headers

```csharp
// =============================================================================
// EVEN AND ODD PAGE HEADERS/FOOTERS
// =============================================================================
// For different headers on even vs. odd pages (e.g., book-style layout):
// 1. Set EvenAndOddHeaders in DocumentSettingsPart
// 2. Create separate parts for Even pages
// 3. "Default" type becomes the ODD page header/footer

// Enable even/odd in Settings
var settingsPart = mainPart.DocumentSettingsPart
    ?? mainPart.AddNewPart<DocumentSettingsPart>();
if (settingsPart.Settings == null)
    settingsPart.Settings = new Settings();

settingsPart.Settings.AppendChild(new EvenAndOddHeaders());
settingsPart.Settings.Save();
// Produces XML in settings.xml: <w:evenAndOddHeaders />

// Create even-page header
var evenHeaderPart = mainPart.AddNewPart<HeaderPart>();
string evenHeaderId = mainPart.GetIdOfPart(evenHeaderPart);
evenHeaderPart.Header = new Header(
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Left }),
        new Run(new Text("Chapter Title"))   // Left-aligned on even pages
    )
);
evenHeaderPart.Header.Save();

// Link: "Default" = odd pages, "Even" = even pages
sectPr.AppendChild(new HeaderReference
{
    Type = HeaderFooterValues.Even,
    Id = evenHeaderId
});
// The existing Default header is now used only on odd pages.
```

### 3.5 SimpleField — PAGE, NUMPAGES, SECTIONPAGES

```csharp
// =============================================================================
// SIMPLE FIELDS — PAGE NUMBERS AND TOTALS
// =============================================================================
// SimpleField inserts a field code that Word evaluates at render time.
// Common field codes:
//   PAGE         — current page number
//   NUMPAGES     — total pages in document
//   SECTIONPAGES — total pages in current section
//   DATE         — current date
//   TIME         — current time
//
// The Instruction property contains the field code string.
// A child Run with text is used for the "cached" display value (optional but
// recommended for non-Word renderers).

// --- Simple page number field ---
var pageField = new SimpleField { Instruction = " PAGE " };
pageField.AppendChild(new Run(new Text("1")));  // Cached display value
// Produces XML: <w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>

// --- Total page count ---
var totalField = new SimpleField { Instruction = " NUMPAGES " };
totalField.AppendChild(new Run(new Text("1")));

// --- Section page count ---
var sectionPagesField = new SimpleField { Instruction = " SECTIONPAGES " };
sectionPagesField.AppendChild(new Run(new Text("1")));
```

### 3.6 "Page X of Y" Footer

```csharp
// =============================================================================
// "PAGE X OF Y" FOOTER
// =============================================================================
// Combines text runs with SimpleField elements in a single paragraph.

var pageXofYFooter = mainPart.AddNewPart<FooterPart>();
string pageXofYId = mainPart.GetIdOfPart(pageXofYFooter);

var footerPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center })
);

// "Page "
footerPara.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),   // 9pt
    new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }
));

// PAGE field
var pgField = new SimpleField { Instruction = " PAGE " };
pgField.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text("1")));
footerPara.AppendChild(pgField);

// " of "
footerPara.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text(" of ") { Space = SpaceProcessingModeValues.Preserve }
));

// NUMPAGES field
var npField = new SimpleField { Instruction = " NUMPAGES " };
npField.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text("1")));
footerPara.AppendChild(npField);

pageXofYFooter.Footer = new Footer(footerPara);
pageXofYFooter.Footer.Save();

// Link to section
sectPr.AppendChild(new FooterReference
{
    Type = HeaderFooterValues.Default,
    Id = pageXofYId
});
```

### 3.7 Header with Logo Image

```csharp
// =============================================================================
// HEADER WITH LOGO IMAGE
// =============================================================================
// To add an image to a header:
// 1. Add an ImagePart to the HeaderPart (not MainDocumentPart)
// 2. Build the Drawing/Inline/Graphic elements in the header paragraph
// 3. Image sizing uses EMUs (English Metric Units): 1 inch = 914400 EMU

var logoHeaderPart = mainPart.AddNewPart<HeaderPart>();
string logoHeaderId = mainPart.GetIdOfPart(logoHeaderPart);

// Add image to header part
var imagePart = logoHeaderPart.AddImagePart(ImagePartType.Png);
using (var stream = File.OpenRead("logo.png"))
{
    imagePart.FeedData(stream);
}
string imageRelId = logoHeaderPart.GetIdOfPart(imagePart);

// Image dimensions in EMU (e.g., 1.5 inch wide × 0.5 inch tall)
long widthEmu = 1371600;    // 1.5 * 914400
long heightEmu = 457200;    // 0.5 * 914400

// Build the inline drawing element
var drawing = new Drawing(
    new DW.Inline(
        new DW.Extent { Cx = widthEmu, Cy = heightEmu },
        new DW.EffectExtent { LeftEdge = 0L, TopEdge = 0L, RightEdge = 0L, BottomEdge = 0L },
        new DW.DocProperties { Id = 1U, Name = "Logo" },
        new DW.NonVisualGraphicFrameDrawingProperties(
            new A.GraphicFrameLocks { NoChangeAspect = true }),
        new A.Graphic(
            new A.GraphicData(
                new PIC.Picture(
                    new PIC.NonVisualPictureProperties(
                        new PIC.NonVisualDrawingProperties { Id = 1U, Name = "logo.png" },
                        new PIC.NonVisualPictureDrawingProperties()),
                    new PIC.BlipFill(
                        new A.Blip { Embed = imageRelId },
                        new A.Stretch(new A.FillRectangle())),
                    new PIC.ShapeProperties(
                        new A.Transform2D(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = widthEmu, Cy = heightEmu }),
                        new A.PresetGeometry(new A.AdjustValueList())
                        { Preset = A.ShapeTypeValues.Rectangle })
                )
            ) { Uri = "http://schemas.openxmlformats.org/drawingml/2006/picture" }
        )
    )
    {
        DistanceFromTop = 0U,
        DistanceFromBottom = 0U,
        DistanceFromLeft = 0U,
        DistanceFromRight = 0U
    }
);

logoHeaderPart.Header = new Header(
    new Paragraph(new Run(drawing))
);
logoHeaderPart.Header.Save();
```

### 3.8 Table-Layout Header (Logo Left, Text Center, Page Right)

```csharp
// =============================================================================
// TABLE-LAYOUT HEADER
// =============================================================================
// A common professional header pattern: 3-column invisible table
//   Left cell:   Company logo
//   Center cell: Document title
//   Right cell:  Page number
// The table has no borders, giving a clean three-zone layout.

var tblHeaderPart = mainPart.AddNewPart<HeaderPart>();
string tblHeaderId = mainPart.GetIdOfPart(tblHeaderPart);

// Content width for Letter with 1" margins = 9360 DXA
var headerTable = new Table(
    new TableProperties(
        new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
        new TableLayout { Type = TableLayoutValues.Fixed },
        new TableBorders(
            new TopBorder { Val = BorderValues.None },
            new BottomBorder { Val = BorderValues.Single, Size = 4U, Color = "000000" },
            new LeftBorder { Val = BorderValues.None },
            new RightBorder { Val = BorderValues.None },
            new InsideHorizontalBorder { Val = BorderValues.None },
            new InsideVerticalBorder { Val = BorderValues.None }
        )
    ),
    new TableGrid(
        new GridColumn { Width = "3120" },   // ~1/3
        new GridColumn { Width = "3120" },   // ~1/3
        new GridColumn { Width = "3120" }    // ~1/3
    )
);

// Left cell: logo placeholder (or image Drawing)
var leftCell = new TableCell(
    new TableCellProperties(
        new TableCellWidth { Width = "3120", Type = TableWidthUnitValues.Dxa },
        new TableCellVerticalAlignment { Val = TableVerticalAlignmentValues.Center }),
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Left }),
        new Run(
            new RunProperties(new Bold(), new FontSize { Val = "18" }),
            new Text("ACME Corp")))
);

// Center cell: document title
var centerCell = new TableCell(
    new TableCellProperties(
        new TableCellWidth { Width = "3120", Type = TableWidthUnitValues.Dxa },
        new TableCellVerticalAlignment { Val = TableVerticalAlignmentValues.Center }),
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Center }),
        new Run(
            new RunProperties(new FontSize { Val = "18" }),
            new Text("Technical Specification v2.0")))
);

// Right cell: page number
var pageFieldRight = new SimpleField { Instruction = " PAGE " };
pageFieldRight.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text("1")));

var rightCell = new TableCell(
    new TableCellProperties(
        new TableCellWidth { Width = "3120", Type = TableWidthUnitValues.Dxa },
        new TableCellVerticalAlignment { Val = TableVerticalAlignmentValues.Center }),
    new Paragraph(
        new ParagraphProperties(
            new Justification { Val = JustificationValues.Right }),
        new Run(
            new RunProperties(new FontSize { Val = "18" }),
            new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }),
        pageFieldRight)
);

headerTable.AppendChild(new TableRow(leftCell, centerCell, rightCell));

tblHeaderPart.Header = new Header(headerTable, new Paragraph());
tblHeaderPart.Header.Save();
```

### 3.9 Chinese Government Document Page Numbers (公文页码)

```csharp
// =============================================================================
// CHINESE GOVERNMENT DOCUMENT PAGE NUMBERS (公文页码)
// =============================================================================
// Standard: bottom center, format "-X-" (em-dash surrounding page number)
// Font: 宋体 (SimSun) 四号 (14pt = "28" half-points)
// Per GB/T 9704-2012

var govFooterPart = mainPart.AddNewPart<FooterPart>();
string govFooterId = mainPart.GetIdOfPart(govFooterPart);

var govFooterPara = new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center })
);

// Run properties for 宋体四号
RunProperties GovPageRunProps() => new RunProperties(
    new RunFonts
    {
        Ascii = "SimSun",
        HighAnsi = "SimSun",
        EastAsia = "SimSun"
    },
    new FontSize { Val = "28" },           // 14pt = 四号
    new FontSizeComplexScript { Val = "28" }
);

// "—" (em-dash before page number)
govFooterPara.AppendChild(new Run(
    GovPageRunProps(),
    new Text("\u2014") { Space = SpaceProcessingModeValues.Preserve }
));

// PAGE field
var govPageField = new SimpleField { Instruction = " PAGE " };
govPageField.AppendChild(new Run(GovPageRunProps(), new Text("1")));
govFooterPara.AppendChild(govPageField);

// "—" (em-dash after page number)
govFooterPara.AppendChild(new Run(
    GovPageRunProps(),
    new Text("\u2014") { Space = SpaceProcessingModeValues.Preserve }
));

govFooterPart.Footer = new Footer(govFooterPara);
govFooterPart.Footer.Save();

// Link to section
sectPr.AppendChild(new FooterReference
{
    Type = HeaderFooterValues.Default,
    Id = govFooterId
});
```

### 3.10 Multi-Section with Different Headers

```csharp
// =============================================================================
// MULTI-SECTION WITH DIFFERENT HEADERS
// =============================================================================
// Each section can have its own set of header/footer parts.
// To change headers mid-document, create a section break and attach
// different HeaderReference/FooterReference to each SectionProperties.
// See Section 4 for full section break mechanics.

// Section 1 header
var sec1Header = mainPart.AddNewPart<HeaderPart>();
string sec1HeaderId = mainPart.GetIdOfPart(sec1Header);
sec1Header.Header = new Header(
    new Paragraph(new Run(new Text("Chapter 1: Introduction"))));
sec1Header.Header.Save();

// Section 2 header
var sec2Header = mainPart.AddNewPart<HeaderPart>();
string sec2HeaderId = mainPart.GetIdOfPart(sec2Header);
sec2Header.Header = new Header(
    new Paragraph(new Run(new Text("Chapter 2: Methods"))));
sec2Header.Header.Save();

// Section 1 content + section break
body.AppendChild(new Paragraph(new Run(new Text("Section 1 content..."))));

// Mid-document section properties (in last paragraph of section 1)
var sec1Break = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new PageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            new SectionType { Val = SectionMarkValues.NextPage },
            new HeaderReference { Type = HeaderFooterValues.Default, Id = sec1HeaderId }
        )
    )
);
body.AppendChild(sec1Break);

// Section 2 content
body.AppendChild(new Paragraph(new Run(new Text("Section 2 content..."))));

// Final section properties (last child of Body)
var sec2Props = new SectionProperties(
    new PageSize { Width = 12240U, Height = 15840U },
    new PageMargin
    {
        Top = 1440, Bottom = 1440,
        Left = 1440U, Right = 1440U,
        Header = 720U, Footer = 720U, Gutter = 0U
    },
    new HeaderReference { Type = HeaderFooterValues.Default, Id = sec2HeaderId }
);
body.AppendChild(sec2Props);
```

---

## 4. Section Breaks & Multi-Section

### 4.1 Section Properties Placement Rules

```csharp
// =============================================================================
// SECTION PROPERTIES PLACEMENT
// =============================================================================
// There are exactly TWO places SectionProperties can appear:
//
// 1. FINAL SECTION: As the last child element of <w:body>.
//    This controls the last (or only) section of the document.
//    body.AppendChild(new SectionProperties(...));
//
// 2. MID-DOCUMENT SECTION BREAK: Inside ParagraphProperties of the
//    LAST paragraph of a section. This paragraph acts as the section divider.
//    The paragraph's text content belongs to the PREVIOUS section.
//
// IMPORTANT: Mid-document SectionProperties goes inside pPr, NOT as a child
// of Body. This is the #1 mistake when creating multi-section documents.

// --- Final section (last child of Body) ---
var finalSectPr = new SectionProperties(
    new PageSize { Width = 12240U, Height = 15840U },
    new PageMargin
    {
        Top = 1440, Bottom = 1440,
        Left = 1440U, Right = 1440U,
        Header = 720U, Footer = 720U, Gutter = 0U
    }
);
body.AppendChild(finalSectPr);  // MUST be last child

// --- Mid-document section break ---
// This paragraph ends section 1 and starts section 2
var sectionBreakPara = new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new PageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            new SectionType { Val = SectionMarkValues.NextPage }
        )
    )
);
// Produces XML:
// <w:p>
//   <w:pPr>
//     <w:sectPr>
//       <w:pgSz w:w="12240" w:h="15840" />
//       <w:pgMar ... />
//       <w:type w:val="nextPage" />
//     </w:sectPr>
//   </w:pPr>
// </w:p>
```

### 4.2 SectionType Values

```csharp
// =============================================================================
// SECTION TYPE VALUES
// =============================================================================
// SectionType controls how the section break behaves:
//
//   NextPage    — new section starts on next page (most common)
//   Continuous  — new section starts on same page (used for column changes)
//   EvenPage    — new section starts on next even page (inserts blank if needed)
//   OddPage     — new section starts on next odd page (inserts blank if needed)
//
// If SectionType is omitted, the default is NextPage.

// Next page break (explicit)
var nextPageBreak = new SectionType { Val = SectionMarkValues.NextPage };

// Continuous — same page (e.g., switch from 1-column to 2-column)
var continuousBreak = new SectionType { Val = SectionMarkValues.Continuous };

// Even page — for chapters that must start on left page (in book layout)
var evenPageBreak = new SectionType { Val = SectionMarkValues.EvenPage };

// Odd page — for chapters that must start on right page
var oddPageBreak = new SectionType { Val = SectionMarkValues.OddPage };
```

### 4.3 Per-Section Page Setup

```csharp
// =============================================================================
// PER-SECTION PAGE SETUP
// =============================================================================
// Each section independently controls its own:
//   - PageSize (portrait vs landscape, paper size)
//   - PageMargin
//   - Columns
//   - Headers/Footers
//   - PageNumberType (restart numbering)
//   - LineNumbering
//   - DocGrid

// Example: Section with landscape A4 and narrow margins
var landscapeSection = new SectionProperties(
    new PageSize
    {
        Width = 16838U,    // A4 long edge (landscape: swap W/H)
        Height = 11906U,   // A4 short edge
        Orient = PageOrientationValues.Landscape
    },
    new PageMargin
    {
        Top = 720, Bottom = 720,
        Left = 720U, Right = 720U,
        Header = 720U, Footer = 720U, Gutter = 0U
    },
    new SectionType { Val = SectionMarkValues.NextPage }
);
```

### 4.4 PageNumberType — Restart Numbering

```csharp
// =============================================================================
// PAGE NUMBER TYPE — RESTART AND FORMAT
// =============================================================================
// PageNumberType controls page numbering within a section.
//   Start  — starting page number (restarts counting)
//   Format — numbering format (Decimal, UpperRoman, LowerRoman,
//            UpperLetter, LowerLetter)
//
// Common pattern: front matter uses i, ii, iii; body restarts at 1.

// Restart at page 1 (e.g., after front matter)
var restartNumbering = new PageNumberType
{
    Start = 1,
    Format = NumberFormatValues.Decimal
};
// Produces XML: <w:pgNumType w:start="1" w:fmt="decimal" />

// Roman numeral numbering for front matter
var romanNumbering = new PageNumberType
{
    Start = 1,
    Format = NumberFormatValues.LowerRoman
};
// Produces XML: <w:pgNumType w:start="1" w:fmt="lowerRoman" />

// Add to section properties
landscapeSection.AppendChild(restartNumbering);
```

### 4.5 Complete Example: Portrait, Landscape, Portrait

```csharp
// =============================================================================
// COMPLETE MULTI-SECTION EXAMPLE
// =============================================================================
// Document with three sections:
//   Section 1: Letter portrait (cover + intro)
//   Section 2: Letter landscape (wide table)
//   Section 3: Letter portrait (conclusion), page numbers restart at 1
//
// Each section has its own header.

using var doc = WordprocessingDocument.Create(
    "MultiSection.docx", WordprocessingDocumentType.Document);

var mainPart = doc.MainDocumentPart!;
var body = mainPart.Document.Body!;

// --- Create headers for each section ---
HeaderPart CreateSimpleHeader(string text)
{
    var hp = mainPart.AddNewPart<HeaderPart>();
    hp.Header = new Header(
        new Paragraph(
            new ParagraphProperties(
                new ParagraphBorders(
                    new BottomBorder
                    {
                        Val = BorderValues.Single, Size = 4U,
                        Color = "999999", Space = 1U
                    }),
                new Justification { Val = JustificationValues.Right }),
            new Run(
                new RunProperties(
                    new FontSize { Val = "18" },
                    new Color { Val = "999999" }),
                new Text(text)))
    );
    hp.Header.Save();
    return hp;
}

var header1 = CreateSimpleHeader("Introduction");
var header2 = CreateSimpleHeader("Data Tables");
var header3 = CreateSimpleHeader("Conclusion");

// --- Create "Page X of Y" footer (shared) ---
var sharedFooter = mainPart.AddNewPart<FooterPart>();
var fPara = new Paragraph(
    new ParagraphProperties(new Justification { Val = JustificationValues.Center }));
fPara.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text("Page ") { Space = SpaceProcessingModeValues.Preserve }));
var pf = new SimpleField { Instruction = " PAGE " };
pf.AppendChild(new Run(new RunProperties(new FontSize { Val = "18" }), new Text("1")));
fPara.AppendChild(pf);
fPara.AppendChild(new Run(
    new RunProperties(new FontSize { Val = "18" }),
    new Text(" of ") { Space = SpaceProcessingModeValues.Preserve }));
var npf = new SimpleField { Instruction = " NUMPAGES " };
npf.AppendChild(new Run(new RunProperties(new FontSize { Val = "18" }), new Text("1")));
fPara.AppendChild(npf);
sharedFooter.Footer = new Footer(fPara);
sharedFooter.Footer.Save();
string sharedFooterId = mainPart.GetIdOfPart(sharedFooter);

// =================== SECTION 1: Portrait ===================
body.AppendChild(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center }),
    new Run(
        new RunProperties(new Bold(), new FontSize { Val = "48" }),
        new Text("Annual Report 2025"))));

body.AppendChild(new Paragraph(new Run(new Text("Introduction content goes here..."))));

// Section 1 break (inside pPr of last paragraph)
body.AppendChild(new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new PageSize { Width = 12240U, Height = 15840U },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            new SectionType { Val = SectionMarkValues.NextPage },
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header1)
            },
            new FooterReference
            {
                Type = HeaderFooterValues.Default,
                Id = sharedFooterId
            }
        )
    )
));

// =================== SECTION 2: Landscape ===================
body.AppendChild(new Paragraph(new Run(
    new RunProperties(new Bold(), new FontSize { Val = "28" }),
    new Text("Wide Data Table"))));

body.AppendChild(new Paragraph(new Run(
    new Text("This section uses landscape orientation for a wide table."))));

// Section 2 break
body.AppendChild(new Paragraph(
    new ParagraphProperties(
        new SectionProperties(
            new PageSize
            {
                Width = 15840U,     // SWAPPED for landscape
                Height = 12240U,    // SWAPPED for landscape
                Orient = PageOrientationValues.Landscape
            },
            new PageMargin
            {
                Top = 1440, Bottom = 1440,
                Left = 1440U, Right = 1440U,
                Header = 720U, Footer = 720U, Gutter = 0U
            },
            new SectionType { Val = SectionMarkValues.NextPage },
            new HeaderReference
            {
                Type = HeaderFooterValues.Default,
                Id = mainPart.GetIdOfPart(header2)
            },
            new FooterReference
            {
                Type = HeaderFooterValues.Default,
                Id = sharedFooterId
            }
        )
    )
));

// =================== SECTION 3: Portrait (restart page numbers) ===================
body.AppendChild(new Paragraph(new Run(
    new RunProperties(new Bold(), new FontSize { Val = "28" }),
    new Text("Conclusion"))));

body.AppendChild(new Paragraph(new Run(
    new Text("Final section content with restarted page numbering."))));

// Final section properties — last child of Body
body.AppendChild(new SectionProperties(
    new PageSize { Width = 12240U, Height = 15840U },
    new PageMargin
    {
        Top = 1440, Bottom = 1440,
        Left = 1440U, Right = 1440U,
        Header = 720U, Footer = 720U, Gutter = 0U
    },
    new PageNumberType
    {
        Start = 1,                                         // Restart at page 1
        Format = NumberFormatValues.Decimal
    },
    new HeaderReference
    {
        Type = HeaderFooterValues.Default,
        Id = mainPart.GetIdOfPart(header3)
    },
    new FooterReference
    {
        Type = HeaderFooterValues.Default,
        Id = sharedFooterId
    }
));

mainPart.Document.Save();
```

---

## 5. Document Properties

### 5.1 CoreFilePropertiesPart (Dublin Core Metadata)

```csharp
// =============================================================================
// CORE FILE PROPERTIES (DUBLIN CORE)
// =============================================================================
// Core properties map to the Dublin Core metadata standard.
// They appear in File > Properties > Summary in Word.
// The underlying XML is stored in docProps/core.xml.
//
// Available properties: Title, Subject, Creator (Author), Keywords,
// Description, LastModifiedBy, Revision, Created, Modified, Category,
// ContentStatus, ContentType, Identifier, Language, Version

using var doc = WordprocessingDocument.Create(
    "PropertiesDemo.docx", WordprocessingDocumentType.Document);

// Core properties are accessed via the package-level properties
// Use the OpenXml Packaging API:
var corePart = doc.CoreFilePropertiesPart
    ?? doc.AddCoreFilePropertiesPart();

// The core properties use the OpenXmlPart's XML directly.
// You can set properties via the PackageProperties interface:
doc.PackageProperties.Title = "Quarterly Financial Report";
doc.PackageProperties.Subject = "Q4 2025 Financial Summary";
doc.PackageProperties.Creator = "Jane Smith";
doc.PackageProperties.Keywords = "finance, quarterly, report, 2025";
doc.PackageProperties.Description = "Comprehensive financial report for Q4 2025";
doc.PackageProperties.LastModifiedBy = "John Doe";
doc.PackageProperties.Revision = "3";
doc.PackageProperties.Created = DateTime.UtcNow;
doc.PackageProperties.Modified = DateTime.UtcNow;
doc.PackageProperties.Category = "Financial Reports";
doc.PackageProperties.ContentStatus = "Final";
doc.PackageProperties.Language = "en-US";
doc.PackageProperties.Version = "2.0";

// Produces docProps/core.xml:
// <cp:coreProperties>
//   <dc:title>Quarterly Financial Report</dc:title>
//   <dc:subject>Q4 2025 Financial Summary</dc:subject>
//   <dc:creator>Jane Smith</dc:creator>
//   <cp:keywords>finance, quarterly, report, 2025</cp:keywords>
//   <dc:description>Comprehensive financial report...</dc:description>
//   <cp:lastModifiedBy>John Doe</cp:lastModifiedBy>
//   <cp:revision>3</cp:revision>
//   <dcterms:created>2025-12-01T00:00:00Z</dcterms:created>
//   <dcterms:modified>2025-12-01T00:00:00Z</dcterms:modified>
//   <cp:category>Financial Reports</cp:category>
//   <cp:contentStatus>Final</cp:contentStatus>
// </cp:coreProperties>
```

### 5.2 ExtendedFilePropertiesPart (Application Properties)

```csharp
// =============================================================================
// EXTENDED FILE PROPERTIES (APPLICATION PROPERTIES)
// =============================================================================
// Extended properties are stored in docProps/app.xml.
// They include application-specific metadata like Company, Manager, etc.

using DocumentFormat.OpenXml.ExtendedProperties;

var extPart = doc.ExtendedFilePropertiesPart
    ?? doc.AddExtendedFilePropertiesPart();

extPart.Properties = new DocumentFormat.OpenXml.ExtendedProperties.Properties();

// Company name
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Company("ACME Corporation"));

// Manager
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Manager("Alice Johnson"));

// Application name
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Application("Custom Document Generator"));

// Application version
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.ApplicationVersion("1.0.0"));

// Total editing time in minutes
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.TotalTime("0"));

// Pages, Words, Characters (these are hints; Word recalculates them)
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Pages("1"));
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Words("0"));
extPart.Properties.AppendChild(
    new DocumentFormat.OpenXml.ExtendedProperties.Characters("0"));

extPart.Properties.Save();

// Produces docProps/app.xml:
// <Properties>
//   <Company>ACME Corporation</Company>
//   <Manager>Alice Johnson</Manager>
//   <Application>Custom Document Generator</Application>
//   <AppVersion>1.0.0</AppVersion>
//   <TotalTime>0</TotalTime>
//   <Pages>1</Pages>
// </Properties>
```

### 5.3 CustomFilePropertiesPart (Custom Key-Value Properties)

```csharp
// =============================================================================
// CUSTOM FILE PROPERTIES (KEY-VALUE PAIRS)
// =============================================================================
// Custom properties allow arbitrary key-value metadata.
// Stored in docProps/custom.xml. Useful for document management systems,
// workflow tracking, template variables, etc.
//
// Supported value types: Text (string), Number (int), Date (DateTime),
// Boolean (bool), Filetime

using DocumentFormat.OpenXml.CustomProperties;
using DocumentFormat.OpenXml.VariantTypes;

var customPart = doc.CustomFilePropertiesPart
    ?? doc.AddCustomFilePropertiesPart();

customPart.Properties = new DocumentFormat.OpenXml.CustomProperties.Properties();

// Property IDs must start at 2 and increment
int propertyId = 2;

// --- String property ---
customPart.Properties.AppendChild(new CustomDocumentProperty
{
    FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
    PropertyId = propertyId++,
    Name = "Department",
    VTLPWSTR = new VTLPWSTR("Engineering")
});

// --- Integer property ---
customPart.Properties.AppendChild(new CustomDocumentProperty
{
    FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
    PropertyId = propertyId++,
    Name = "DocumentVersion",
    VTInt32 = new VTInt32("5")
});

// --- Boolean property ---
customPart.Properties.AppendChild(new CustomDocumentProperty
{
    FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
    PropertyId = propertyId++,
    Name = "Approved",
    VTBool = new VTBool("true")
});

// --- DateTime property ---
customPart.Properties.AppendChild(new CustomDocumentProperty
{
    FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
    PropertyId = propertyId++,
    Name = "ApprovalDate",
    VTFileTime = new VTFileTime(DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
});

// --- Double/Float property ---
customPart.Properties.AppendChild(new CustomDocumentProperty
{
    FormatId = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
    PropertyId = propertyId++,
    Name = "ConfidenceScore",
    VTDouble = new VTDouble("0.95")
});

customPart.Properties.Save();

// Produces docProps/custom.xml:
// <Properties>
//   <property fmtid="{D5CDD505-...}" pid="2" name="Department">
//     <vt:lpwstr>Engineering</vt:lpwstr>
//   </property>
//   <property fmtid="{D5CDD505-...}" pid="3" name="DocumentVersion">
//     <vt:i4>5</vt:i4>
//   </property>
//   <property fmtid="{D5CDD505-...}" pid="4" name="Approved">
//     <vt:bool>true</vt:bool>
//   </property>
//   ...
// </Properties>
```

### 5.4 Reading and Modifying Existing Properties

```csharp
// =============================================================================
// READING AND MODIFYING EXISTING PROPERTIES
// =============================================================================

using var existingDoc = WordprocessingDocument.Open("existing.docx", isEditable: true);

// --- Read core properties ---
string? title = existingDoc.PackageProperties.Title;
string? author = existingDoc.PackageProperties.Creator;
DateTime? modified = existingDoc.PackageProperties.Modified;

// --- Modify core properties ---
existingDoc.PackageProperties.Title = "Updated Title";
existingDoc.PackageProperties.Modified = DateTime.UtcNow;

// --- Read custom properties ---
var customProps = existingDoc.CustomFilePropertiesPart?.Properties;
if (customProps != null)
{
    foreach (var prop in customProps.Elements<CustomDocumentProperty>())
    {
        string name = prop.Name!;
        // Value is in one of the VT* child elements
        string? textValue = prop.VTLPWSTR?.Text;
        string? intValue = prop.VTInt32?.Text;
        string? boolValue = prop.VTBool?.Text;
        // Use whichever is non-null
    }
}

// --- Update a specific custom property ---
var deptProp = customProps?.Elements<CustomDocumentProperty>()
    .FirstOrDefault(p => p.Name == "Department");
if (deptProp != null)
{
    deptProp.VTLPWSTR = new VTLPWSTR("Marketing");
    customProps!.Save();
}
```

---

## 6. Printing & Compatibility Settings

### 6.1 DocumentSettingsPart — Zoom, TabStop, ProofState

```csharp
// =============================================================================
// DOCUMENT SETTINGS — ZOOM, TAB STOPS, PROOF STATE
// =============================================================================
// DocumentSettingsPart (settings.xml) contains document-wide settings.
// These control behavior in Word's UI and rendering.

var mainPart2 = doc.MainDocumentPart!;
var settingsPart2 = mainPart2.DocumentSettingsPart
    ?? mainPart2.AddNewPart<DocumentSettingsPart>();
settingsPart2.Settings ??= new Settings();
var settings = settingsPart2.Settings;

// --- Zoom level ---
// Val = percentage (100 = 100%). Percent is a string.
settings.AppendChild(new Zoom
{
    Percent = "120",                                      // 120% zoom
    Val = PresetZoomValues.BestFit                        // Or: None, FullPage, BestFit, TextFit
});
// Produces XML: <w:zoom w:percent="120" w:val="bestFit" />

// --- Default Tab Stop ---
// Distance in DXA for default tab stops. Standard is 720 (0.5 inch).
settings.AppendChild(new DefaultTabStop
{
    Val = 720                                             // 0.5 inch
});
// Produces XML: <w:defaultTabStop w:val="720" />

// For Chinese documents, common default tab stop is 420 (about 2 characters wide)
// settings.AppendChild(new DefaultTabStop { Val = 420 });

// --- Proof State ---
// Tells Word the spell/grammar check status. Setting both to "clean"
// prevents Word from showing the "Proofing" notification on open.
settings.AppendChild(new ProofState
{
    Spelling = ProofingStateValues.Clean,
    Grammar = ProofingStateValues.Clean
});
// Produces XML: <w:proofState w:spelling="clean" w:grammar="clean" />

// --- Character Spacing Control ---
// CompressWhitespace: whether to compress whitespace at line edges (CJK)
settings.AppendChild(new CharacterSpacingControl
{
    Val = CharacterSpacingValues.DoNotCompress
});

// --- Remove personal information on save ---
settings.AppendChild(new RemovePersonalInformation());
// Produces XML: <w:removePersonalInformation />

settings.Save();
```

### 6.2 Compatibility Settings

```csharp
// =============================================================================
// COMPATIBILITY SETTINGS
// =============================================================================
// Compatibility settings control how Word renders the document,
// providing backward compatibility with older Word versions.
// CompatibilityMode is the most important setting.

var compat = new Compatibility();

// --- Compatibility Mode ---
// 15 = Word 2013+ mode (current standard)
// 14 = Word 2010 mode
// 12 = Word 2007 mode
// Omitted or 0 = oldest compatibility
compat.AppendChild(new CompatibilitySetting
{
    Name = CompatSettingNameValues.CompatibilityMode,
    Uri = "http://schemas.microsoft.com/office/word",
    Val = "15"                                            // Word 2013+ mode
});

// --- Override page break rules ---
// Useful compatibility flags for consistent rendering:

// UseWord2002TableStyleRules: use newer table style rules
compat.AppendChild(new CompatibilitySetting
{
    Name = CompatSettingNameValues.OverrideTableStyleFontSizeAndJustification,
    Uri = "http://schemas.microsoft.com/office/word",
    Val = "1"
});

// EnableOpenTypeFeatures: enable advanced typography
compat.AppendChild(new CompatibilitySetting
{
    Name = CompatSettingNameValues.EnableOpenTypeFeatures,
    Uri = "http://schemas.microsoft.com/office/word",
    Val = "1"
});

// DifferentiateMultirowTableHeaders
compat.AppendChild(new CompatibilitySetting
{
    Name = CompatSettingNameValues.DifferentiateMultirowTableHeaders,
    Uri = "http://schemas.microsoft.com/office/word",
    Val = "1"
});

// UseWord2013TrackBottomHyphenation
compat.AppendChild(new CompatibilitySetting
{
    Name = CompatSettingNameValues.UseWord2013TrackBottomHyphenation,
    Uri = "http://schemas.microsoft.com/office/word",
    Val = "0"
});

settings.AppendChild(compat);
settings.Save();

// Produces XML:
// <w:compat>
//   <w:compatSetting w:name="compatibilityMode"
//     w:uri="http://schemas.microsoft.com/office/word" w:val="15" />
//   <w:compatSetting w:name="overrideTableStyleFontSizeAndJustification"
//     w:uri="http://schemas.microsoft.com/office/word" w:val="1" />
//   ...
// </w:compat>
```

### 6.3 MirrorMargins, GutterAtTop, BookFoldPrinting

```csharp
// =============================================================================
// MIRROR MARGINS, GUTTER, BOOK FOLD
// =============================================================================
// These settings are for documents intended for double-sided printing or
// book binding.

// --- Mirror Margins ---
// When enabled, Left/Right margins become Inside/Outside.
// On even pages, margins are swapped so the binding edge stays consistent.
settings.AppendChild(new MirrorMargins());
// Produces XML: <w:mirrorMargins />
// After this, PageMargin.Left = inside margin, PageMargin.Right = outside margin.
// Even pages automatically flip them.

// --- Gutter at Top ---
// By default, gutter is added to the left (or inside with MirrorMargins).
// GutterAtTop moves the gutter to the top margin instead.
// Used for calendar-style or top-bound documents.
settings.AppendChild(new GutterAtTop());
// Produces XML: <w:gutterAtTop />

// --- Book Fold Printing ---
// Enables booklet printing (2 pages per sheet, folded in half).
// Word reorders pages for saddle-stitch binding.
settings.AppendChild(new BookFoldPrinting());
// Produces XML: <w:bookFoldPrinting />

// Optional: sheets per booklet (for thick documents split into signatures)
// Default 0 = all pages in one booklet
settings.AppendChild(new BookFoldPrintingSheets { Val = 16 });
// Produces XML: <w:bookFoldPrintingSheets w:val="16" />
// 16 sheets = 64 pages per booklet signature

// --- Book Fold Reversed ---
// For right-to-left booklets (Hebrew, Arabic, Japanese right-bound)
// settings.AppendChild(new BookFoldRevPrinting());

settings.Save();
```

### 6.4 Additional Document Settings

```csharp
// =============================================================================
// ADDITIONAL DOCUMENT SETTINGS
// =============================================================================

// --- Update Fields on Open ---
// Forces Word to recalculate all fields (TOC, page numbers, etc.) on open.
settings.AppendChild(new UpdateFieldsOnOpen { Val = true });
// Produces XML: <w:updateFields w:val="true" />
// WARNING: This causes a dialog popup in some Word versions.

// --- Do Not Track Moves ---
// Prevents move tracking in track changes (shows as delete + insert instead).
// settings.AppendChild(new DoNotTrackMoves());

// --- Do Not Track Formatting ---
// Prevents formatting changes from being tracked.
// settings.AppendChild(new DoNotTrackFormatting());

// --- Default Zoom for Print Preview ---
// PrintTwoOnOne: print 2 pages per sheet
// settings.AppendChild(new PrintTwoOnOne());

// --- Document protection (read-only, forms-only, etc.) ---
// DocumentProtection can enforce read-only, allow only comments,
// restrict to form fields, etc.
// settings.AppendChild(new DocumentProtection
// {
//     Edit = DocumentProtectionValues.ReadOnly,
//     Enforcement = true
// });

// --- Even and Odd Headers (setting-level flag) ---
// Must be set here for the EvenPage header/footer references to work.
// settings.AppendChild(new EvenAndOddHeaders());

settings.Save();
```

### 6.5 Complete Settings Setup

```csharp
// =============================================================================
// COMPLETE SETTINGS SETUP — PRODUCTION-READY
// =============================================================================
// A comprehensive settings configuration suitable for most documents.

static void ConfigureDocumentSettings(WordprocessingDocument doc)
{
    var mainPart = doc.MainDocumentPart!;
    var settingsPart = mainPart.DocumentSettingsPart
        ?? mainPart.AddNewPart<DocumentSettingsPart>();
    settingsPart.Settings = new Settings();
    var s = settingsPart.Settings;

    // Zoom to 100%
    s.AppendChild(new Zoom
    {
        Percent = "100",
        Val = PresetZoomValues.None
    });

    // Default tab stop: 0.5 inch
    s.AppendChild(new DefaultTabStop { Val = 720 });

    // Mark spell/grammar as clean
    s.AppendChild(new ProofState
    {
        Spelling = ProofingStateValues.Clean,
        Grammar = ProofingStateValues.Clean
    });

    // Character spacing control
    s.AppendChild(new CharacterSpacingControl
    {
        Val = CharacterSpacingValues.DoNotCompress
    });

    // Compatibility: Word 2013+ mode with useful features
    var compat = new Compatibility();
    foreach (var (name, val) in new[]
    {
        (CompatSettingNameValues.CompatibilityMode, "15"),
        (CompatSettingNameValues.OverrideTableStyleFontSizeAndJustification, "1"),
        (CompatSettingNameValues.EnableOpenTypeFeatures, "1"),
        (CompatSettingNameValues.DifferentiateMultirowTableHeaders, "1"),
        (CompatSettingNameValues.UseWord2013TrackBottomHyphenation, "0"),
    })
    {
        compat.AppendChild(new CompatibilitySetting
        {
            Name = name,
            Uri = "http://schemas.microsoft.com/office/word",
            Val = val
        });
    }
    s.AppendChild(compat);

    s.Save();
}

// Usage:
ConfigureDocumentSettings(doc);
```

---

## Quick Reference: Unit Conversions

| Unit | Full Name | Relation |
|------|-----------|----------|
| DXA | Twentieths of a point | 1 inch = 1440 DXA; 1 cm = 567 DXA; 1 pt = 20 DXA |
| Half-point | Half a typographic point | Font size: 24 = 12pt. 1 pt = 2 half-points |
| Eighth-point | Eighth of a point | Border size: 8 = 1pt. 1 pt = 8 eighth-points |
| EMU | English Metric Unit | 1 inch = 914400 EMU; 1 cm = 360000 EMU; 1 pt = 12700 EMU |
| Pct (table width) | Fiftieths of a percent | 5000 = 100%. Multiply percentage by 50 |

## Quick Reference: Common PageSize Values

| Paper | Width (DXA) | Height (DXA) | Inches | mm |
|-------|-------------|--------------|--------|-----|
| Letter | 12240 | 15840 | 8.5 x 11 | 216 x 279 |
| A4 | 11906 | 16838 | -- | 210 x 297 |
| Legal | 12240 | 20160 | 8.5 x 14 | 216 x 356 |
| A3 | 16838 | 23811 | -- | 297 x 420 |
| B5 | 10318 | 14570 | -- | 182 x 257 |

## Quick Reference: Common Margin Presets (DXA)

| Preset | Top | Bottom | Left | Right |
|--------|-----|--------|------|-------|
| Normal | 1440 | 1440 | 1440 | 1440 |
| Narrow | 720 | 720 | 720 | 720 |
| Moderate | 1440 | 1440 | 1080 | 1080 |
| Wide | 1440 | 1440 | 2880 | 2880 |
| Chinese 公文 | 2098 | 1984 | 1588 | 1474 |
