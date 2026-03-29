using System.IO.Compression;
using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.Validation;

public class GateCheckResult
{
    public bool Passed => Violations.Count == 0;
    public List<string> Violations { get; set; } = new();
}

public class GateCheckValidator
{
    private static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    public GateCheckResult Validate(string outputDocxPath, string templateDocxPath)
    {
        var result = new GateCheckResult();

        var templateStyles = ExtractStyles(templateDocxPath);
        var outputStyles = ExtractStyles(outputDocxPath);
        var templateSectPr = ExtractSectionProperties(templateDocxPath);
        var outputSectPr = ExtractSectionProperties(outputDocxPath);

        // All template styles must exist in output
        foreach (var style in templateStyles)
        {
            if (!outputStyles.Contains(style))
                result.Violations.Add($"Missing style: '{style}' defined in template but absent from output");
        }

        // Page margins must match
        if (templateSectPr.Margins != null && outputSectPr.Margins != null)
        {
            var tm = templateSectPr.Margins;
            var om = outputSectPr.Margins;
            if (tm.Top != om.Top || tm.Bottom != om.Bottom || tm.Left != om.Left || tm.Right != om.Right)
                result.Violations.Add($"Page margins mismatch: template=({tm.Top},{tm.Bottom},{tm.Left},{tm.Right}) output=({om.Top},{om.Bottom},{om.Left},{om.Right})");
        }

        // Page size must match
        if (templateSectPr.PageWidth != outputSectPr.PageWidth || templateSectPr.PageHeight != outputSectPr.PageHeight)
            result.Violations.Add($"Page size mismatch: template=({templateSectPr.PageWidth}x{templateSectPr.PageHeight}) output=({outputSectPr.PageWidth}x{outputSectPr.PageHeight})");

        // Default font must match
        var templateFont = ExtractDefaultFont(templateDocxPath);
        var outputFont = ExtractDefaultFont(outputDocxPath);
        if (templateFont != null && outputFont != null && templateFont != outputFont)
            result.Violations.Add($"Default font mismatch: template='{templateFont}' output='{outputFont}'");

        // Heading font hierarchy consistency
        ValidateHeadingFontHierarchy(outputDocxPath, result);

        return result;
    }

    private HashSet<string> ExtractStyles(string docxPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/styles.xml");
        if (entry == null) return new();

        using var stream = entry.Open();
        var doc = XDocument.Load(stream);
        return doc.Descendants(W + "style")
            .Select(s => (string?)s.Attribute(W + "styleId"))
            .Where(id => id != null)
            .ToHashSet()!;
    }

    private record SectionProps(int PageWidth, int PageHeight, MarginInfo? Margins);
    private record MarginInfo(int Top, int Bottom, int Left, int Right);

    private SectionProps ExtractSectionProperties(string docxPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/document.xml")!;
        using var stream = entry.Open();
        var doc = XDocument.Load(stream);

        var sectPr = doc.Descendants(W + "sectPr").LastOrDefault();
        if (sectPr == null) return new(0, 0, null);

        int.TryParse((string?)sectPr.Element(W + "pgSz")?.Attribute(W + "w"), out var pw);
        int.TryParse((string?)sectPr.Element(W + "pgSz")?.Attribute(W + "h"), out var ph);

        var pgMar = sectPr.Element(W + "pgMar");
        MarginInfo? margins = null;
        if (pgMar != null)
        {
            int.TryParse((string?)pgMar.Attribute(W + "top"), out var t);
            int.TryParse((string?)pgMar.Attribute(W + "bottom"), out var b);
            int.TryParse((string?)pgMar.Attribute(W + "left"), out var l);
            int.TryParse((string?)pgMar.Attribute(W + "right"), out var r);
            margins = new(t, b, l, r);
        }

        return new(pw, ph, margins);
    }

    private string? ExtractDefaultFont(string docxPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/styles.xml");
        if (entry == null) return null;

        using var stream = entry.Open();
        var doc = XDocument.Load(stream);

        var defaultStyle = doc.Descendants(W + "style")
            .FirstOrDefault(s => (string?)s.Attribute(W + "type") == "paragraph"
                && (string?)s.Attribute(W + "default") == "1");

        return (string?)defaultStyle?.Descendants(W + "rFonts").FirstOrDefault()?.Attribute(W + "ascii");
    }

    private void ValidateHeadingFontHierarchy(string docxPath, GateCheckResult result)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/styles.xml");
        if (entry == null) return;

        using var stream = entry.Open();
        var doc = XDocument.Load(stream);

        var headingSizes = new SortedDictionary<int, int>();
        foreach (var style in doc.Descendants(W + "style"))
        {
            var id = (string?)style.Attribute(W + "styleId");
            if (id == null || !id.StartsWith("Heading", StringComparison.OrdinalIgnoreCase)) continue;

            var numPart = id.AsSpan(7);
            if (!int.TryParse(numPart, out var level)) continue;

            var sz = (string?)style.Descendants(W + "sz").FirstOrDefault()?.Attribute(W + "val");
            if (sz != null && int.TryParse(sz, out var hps))
                headingSizes[level] = hps;
        }

        int prevSize = int.MaxValue;
        foreach (var (level, size) in headingSizes)
        {
            if (size > prevSize)
                result.Violations.Add($"Heading{level} ({size / 2}pt) is larger than a higher-level heading ({prevSize / 2}pt)");
            prevSize = size;
        }
    }
}
