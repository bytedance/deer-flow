using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.OpenXml;

public record StyleInfo(string Id, string? Name, string Type, string? BasedOn, bool IsDefault);

public record StyleReport(
    List<StyleInfo> AllStyles,
    Dictionary<string, List<string>> InheritanceTree,
    string? DefaultParagraphStyle,
    string? DefaultCharacterStyle,
    int DirectFormattingCount);

/// <summary>
/// Analyzes the style hierarchy of a DOCX document.
/// </summary>
public static class StyleAnalyzer
{
    /// <summary>
    /// Analyzes styles.xml content and document.xml for direct formatting usage.
    /// </summary>
    public static StyleReport Analyze(XDocument stylesXml, XDocument documentXml)
    {
        var styles = ExtractStyles(stylesXml);
        var tree = BuildInheritanceTree(styles);
        var defaultPara = styles.FirstOrDefault(s => s.Type == "paragraph" && s.IsDefault)?.Id;
        var defaultChar = styles.FirstOrDefault(s => s.Type == "character" && s.IsDefault)?.Id;
        var directCount = CountDirectFormatting(documentXml);

        return new(styles, tree, defaultPara, defaultChar, directCount);
    }

    private static List<StyleInfo> ExtractStyles(XDocument stylesXml)
    {
        var result = new List<StyleInfo>();
        var root = stylesXml.Root;
        if (root == null) return result;

        foreach (var style in root.Elements(Ns.W + "style"))
        {
            var id = style.Attribute(Ns.W + "styleId")?.Value ?? "";
            var name = style.Element(Ns.W + "name")?.Attribute(Ns.W + "val")?.Value;
            var type = style.Attribute(Ns.W + "type")?.Value ?? "unknown";
            var basedOn = style.Element(Ns.W + "basedOn")?.Attribute(Ns.W + "val")?.Value;
            var isDefault = style.Attribute(Ns.W + "default")?.Value == "1";
            result.Add(new(id, name, type, basedOn, isDefault));
        }

        return result;
    }

    private static Dictionary<string, List<string>> BuildInheritanceTree(List<StyleInfo> styles)
    {
        var tree = new Dictionary<string, List<string>>();
        foreach (var style in styles)
        {
            var parent = style.BasedOn ?? "(root)";
            if (!tree.ContainsKey(parent))
                tree[parent] = [];
            tree[parent].Add(style.Id);
        }
        return tree;
    }

    private static int CountDirectFormatting(XDocument documentXml)
    {
        var body = documentXml.Root?.Element(Ns.W + "body");
        if (body == null) return 0;

        int count = 0;
        // Count inline rPr on runs (direct character formatting)
        count += body.Descendants(Ns.W + "r")
            .Count(r => r.Element(Ns.W + "rPr") != null);
        // Count inline pPr that contain more than just pStyle (direct paragraph formatting)
        count += body.Descendants(Ns.W + "p")
            .Select(p => p.Element(Ns.W + "pPr"))
            .Count(pPr => pPr != null && pPr.Elements().Any(e => e.Name != Ns.W + "pStyle"));

        return count;
    }
}
