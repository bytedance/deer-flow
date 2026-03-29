using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// Defines canonical child element ordering for key OpenXML parent elements
/// and provides reordering utilities.
/// </summary>
public static class ElementOrder
{
    private static readonly Dictionary<string, string[]> OrderMap = new()
    {
        ["w:body"] = ["w:p", "w:tbl", "w:sdt", "w:sectPr"],
        ["w:p"] = ["w:pPr", "w:hyperlink", "w:r", "w:ins", "w:del", "w:bookmarkStart", "w:bookmarkEnd", "w:commentRangeStart", "w:commentRangeEnd", "w:fldSimple"],
        ["w:pPr"] = ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:widowControl", "w:numPr", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:spacing", "w:ind", "w:jc", "w:rPr", "w:sectPr", "w:pPrChange"],
        ["w:r"] = ["w:rPr", "w:t", "w:br", "w:tab", "w:cr", "w:sym", "w:drawing", "w:delText", "w:fldChar", "w:instrText", "w:lastRenderedPageBreak", "w:noBreakHyphen", "w:softHyphen"],
        ["w:rPr"] = ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike", "w:dstrike", "w:vanish", "w:color", "w:sz", "w:szCs", "w:u", "w:shd", "w:highlight", "w:lang", "w:rPrChange"],
        ["w:tbl"] = ["w:tblPr", "w:tblGrid", "w:tr"],
        ["w:tblPr"] = ["w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblPrChange"],
        ["w:tr"] = ["w:trPr", "w:tc"],
        ["w:trPr"] = ["w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter", "w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange"],
        ["w:tc"] = ["w:tcPr", "w:p", "w:tbl"],
        ["w:tcPr"] = ["w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark", "w:headers", "w:cellIns", "w:cellDel", "w:cellMerge", "w:tcPrChange"],
        ["w:sectPr"] = ["w:headerReference", "w:footerReference", "w:type", "w:pgSz", "w:pgMar", "w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid"],
        ["w:hdr"] = ["w:p", "w:tbl", "w:sdt"],
        ["w:ftr"] = ["w:p", "w:tbl", "w:sdt"],
    };

    /// <summary>
    /// Returns the canonical child ordering for a given parent element name (e.g. "w:p").
    /// Returns null if no ordering is defined.
    /// </summary>
    public static string[]? GetChildOrder(string parentElement)
    {
        return OrderMap.TryGetValue(parentElement, out var order) ? order : null;
    }

    /// <summary>
    /// Reorders children of the given XElement according to the canonical ordering rules.
    /// Children not listed in the ordering are placed at the end in their original order.
    /// </summary>
    public static void ReorderChildren(XElement parent)
    {
        var qualifiedName = GetQualifiedName(parent);
        var order = GetChildOrder(qualifiedName);
        if (order == null) return;

        var children = parent.Elements().ToList();
        if (children.Count <= 1) return;

        var orderIndex = new Dictionary<string, int>();
        for (int i = 0; i < order.Length; i++)
            orderIndex[order[i]] = i;

        int unknownBase = order.Length;
        int unknownCounter = 0;

        var sorted = children
            .Select(c => (Element: c, QName: GetQualifiedName(c)))
            .OrderBy(x => orderIndex.TryGetValue(x.QName, out var idx) ? idx : unknownBase + unknownCounter++)
            .Select(x => x.Element)
            .ToList();

        parent.RemoveNodes();
        foreach (var child in sorted)
            parent.Add(child);
    }

    private static string GetQualifiedName(XElement element)
    {
        var ns = element.Name.Namespace;
        var local = element.Name.LocalName;

        if (ns == Ns.W) return $"w:{local}";
        if (ns == Ns.R) return $"r:{local}";
        if (ns == Ns.MC) return $"mc:{local}";

        return local;
    }
}
