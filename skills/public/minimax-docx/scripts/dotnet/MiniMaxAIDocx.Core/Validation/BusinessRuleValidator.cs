using System.IO.Compression;
using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.Validation;

public class BusinessRuleValidator
{
    private static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    private static readonly XNamespace R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    private static readonly XNamespace WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
    private static readonly XNamespace A = "http://schemas.openxmlformats.org/drawingml/2006/main";

    private const int MinMarginDxa = 360;   // 0.25 inch
    private const int MaxMarginDxa = 4320;  // 3 inches
    private const int MinBodyFontHps = 16;  // 8pt
    private const int MaxBodyFontHps = 144; // 72pt
    private const int MinHeadingFontHps = 20; // 10pt
    private const int MaxHeadingFontHps = 192; // 96pt

    public ValidationResult Validate(string docxPath)
    {
        var result = new ValidationResult();

        using var zip = ZipFile.OpenRead(docxPath);
        var docEntry = zip.GetEntry("word/document.xml")
            ?? throw new InvalidOperationException("Missing word/document.xml");

        var doc = LoadXml(docEntry);
        var body = doc.Root?.Element(W + "body");
        if (body == null)
        {
            result.Errors.Add(Error("Document has no body element"));
            return result;
        }

        ValidateMargins(body, result);
        ValidateFontSizes(body, result);
        ValidateHeadingHierarchy(body, result);
        ValidateTableColumnWidths(body, result);
        ValidateRelationships(zip, doc, result);
        ValidateComments(zip, result);

        return result;
    }

    private void ValidateMargins(XElement body, ValidationResult result)
    {
        foreach (var sectPr in body.Descendants(W + "sectPr"))
        {
            var pgMar = sectPr.Element(W + "pgMar");
            if (pgMar == null) continue;

            foreach (var attr in new[] { "top", "bottom", "left", "right" })
            {
                var val = (string?)pgMar.Attribute(W + attr);
                if (val != null && int.TryParse(val, out var dxa))
                {
                    var absDxa = Math.Abs(dxa);
                    if (absDxa < MinMarginDxa)
                        result.Errors.Add(Error($"Margin '{attr}' is {absDxa} DXA ({absDxa / 1440.0:F2}\"), below minimum {MinMarginDxa} DXA"));
                    if (absDxa > MaxMarginDxa)
                        result.Warnings.Add(Warning($"Margin '{attr}' is {absDxa} DXA ({absDxa / 1440.0:F2}\"), above maximum {MaxMarginDxa} DXA"));
                }
            }
        }
    }

    private void ValidateFontSizes(XElement body, ValidationResult result)
    {
        foreach (var p in body.Descendants(W + "p"))
        {
            var pStyle = p.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val")?.Value;
            bool isHeading = pStyle?.StartsWith("Heading", StringComparison.OrdinalIgnoreCase) == true;

            foreach (var rPr in p.Descendants(W + "rPr"))
            {
                var szEl = rPr.Element(W + "sz");
                var val = (string?)szEl?.Attribute(W + "val");
                if (val != null && int.TryParse(val, out var hps))
                {
                    int min = isHeading ? MinHeadingFontHps : MinBodyFontHps;
                    int max = isHeading ? MaxHeadingFontHps : MaxBodyFontHps;
                    if (hps < min || hps > max)
                        result.Warnings.Add(Warning($"Font size {hps / 2.0}pt is outside {(isHeading ? "heading" : "body")} range ({min / 2}-{max / 2}pt)"));
                }
            }
        }
    }

    private void ValidateHeadingHierarchy(XElement body, ValidationResult result)
    {
        int lastLevel = 0;
        foreach (var p in body.Descendants(W + "p"))
        {
            var pStyle = p.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val")?.Value;
            if (pStyle == null) continue;

            int level = 0;
            if (pStyle.StartsWith("Heading", StringComparison.OrdinalIgnoreCase))
            {
                var numPart = pStyle.AsSpan(7);
                if (int.TryParse(numPart, out var parsed)) level = parsed;
            }

            if (level > 0)
            {
                if (lastLevel > 0 && level > lastLevel + 1)
                    result.Warnings.Add(Warning($"Heading level skips from {lastLevel} to {level} (missing Heading{lastLevel + 1})"));
                lastLevel = level;
            }
        }
    }

    private void ValidateTableColumnWidths(XElement body, ValidationResult result)
    {
        var sectPr = body.Element(W + "sectPr");
        if (sectPr == null) return;

        var pgSz = sectPr.Element(W + "pgSz");
        var pgMar = sectPr.Element(W + "pgMar");
        if (pgSz == null || pgMar == null) return;

        if (!int.TryParse((string?)pgSz.Attribute(W + "w"), out var pageWidth)) return;
        int.TryParse((string?)pgMar.Attribute(W + "left"), out var marginLeft);
        int.TryParse((string?)pgMar.Attribute(W + "right"), out var marginRight);
        var contentWidth = pageWidth - marginLeft - marginRight;

        int tableIndex = 0;
        foreach (var tbl in body.Descendants(W + "tbl"))
        {
            tableIndex++;
            var firstRow = tbl.Element(W + "tr");
            if (firstRow == null) continue;

            int totalWidth = 0;
            foreach (var tc in firstRow.Elements(W + "tc"))
            {
                var tcW = tc.Element(W + "tcPr")?.Element(W + "tcW");
                var w = (string?)tcW?.Attribute(W + "w");
                if (w != null && int.TryParse(w, out var cellWidth))
                    totalWidth += cellWidth;
            }

            if (totalWidth > 0)
            {
                var tolerance = contentWidth * 0.02;
                if (Math.Abs(totalWidth - contentWidth) > tolerance)
                    result.Warnings.Add(Warning($"Table {tableIndex}: column widths sum to {totalWidth} DXA but content width is {contentWidth} DXA"));
            }
        }
    }

    private void ValidateRelationships(ZipArchive zip, XDocument doc, ValidationResult result)
    {
        var relsEntry = zip.GetEntry("word/_rels/document.xml.rels");
        if (relsEntry == null) return;

        var relDoc = LoadXml(relsEntry);
        var ns = relDoc.Root?.Name.Namespace ?? XNamespace.None;
        var definedIds = new HashSet<string>();

        foreach (var rel in relDoc.Descendants(ns + "Relationship"))
        {
            var id = (string?)rel.Attribute("Id");
            if (id != null) definedIds.Add(id);
        }

        var referencedIds = new HashSet<string>();
        foreach (var el in doc.Descendants())
        {
            var rid = (string?)el.Attribute(R + "id") ?? (string?)el.Attribute(R + "embed");
            if (rid != null) referencedIds.Add(rid);
        }

        foreach (var id in referencedIds.Except(definedIds))
            result.Errors.Add(Error($"Reference r:id='{id}' has no matching relationship"));

        foreach (var id in definedIds.Except(referencedIds))
            result.Warnings.Add(Warning($"Orphaned relationship: Id='{id}' is defined but never referenced"));
    }

    private void ValidateComments(ZipArchive zip, ValidationResult result)
    {
        var commentFiles = new[] { "word/comments.xml", "word/commentsExtended.xml", "word/commentsIds.xml", "word/commentsExtensible.xml" };
        var existing = commentFiles.Where(f => zip.GetEntry(f) != null).ToList();

        if (existing.Count > 0 && existing.Count < 4)
        {
            var missing = commentFiles.Except(existing);
            result.Warnings.Add(Warning($"Comments partially present. Missing: {string.Join(", ", missing)}"));
        }

        if (zip.GetEntry("word/comments.xml") is { } commentsEntry)
        {
            var commentsDoc = LoadXml(commentsEntry);
            var commentIds = commentsDoc.Descendants(W + "comment")
                .Select(c => (string?)c.Attribute(W + "id"))
                .Where(id => id != null)
                .ToHashSet();

            if (zip.GetEntry("word/commentsExtended.xml") is { } extEntry)
            {
                var W15 = XNamespace.Get("http://schemas.microsoft.com/office/word/2012/wordml");
                var extDoc = LoadXml(extEntry);
                var extIds = extDoc.Descendants(W15 + "commentEx")
                    .Select(c => (string?)c.Attribute(W15 + "paraId"))
                    .Where(id => id != null)
                    .ToHashSet();

                if (commentIds.Count > 0 && extIds.Count == 0)
                    result.Warnings.Add(Warning("comments.xml has entries but commentsExtended.xml has none"));
            }
        }
    }

    private static XDocument LoadXml(ZipArchiveEntry entry)
    {
        using var stream = entry.Open();
        return XDocument.Load(stream);
    }

    private static ValidationError Error(string msg) => new() { Message = msg, Severity = "Error" };
    private static ValidationError Warning(string msg) => new() { Message = msg, Severity = "Warning" };
}
