using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// Result of a run merge operation.
/// </summary>
public record RunMergeResult(int OriginalRunCount, int MergedRunCount, int SizeReductionBytes);

/// <summary>
/// Merges adjacent w:r elements with identical w:rPr formatting to reduce document size.
/// </summary>
public static class RunMerger
{
    /// <summary>
    /// Merges adjacent runs with identical formatting in all paragraphs of the document body.
    /// </summary>
    public static RunMergeResult MergeRuns(XDocument document)
    {
        var body = document.Root?.Element(Ns.W + "body");
        if (body == null) return new(0, 0, 0);

        int originalCount = 0;
        int removedCount = 0;

        foreach (var paragraph in body.Descendants(Ns.W + "p"))
        {
            var runs = paragraph.Elements(Ns.W + "r").ToList();
            originalCount += runs.Count;

            for (int i = runs.Count - 1; i > 0; i--)
            {
                var current = runs[i];
                var previous = runs[i - 1];

                if (!AreRunPropertiesEqual(previous, current)) continue;

                // Merge text content from current into previous
                var prevText = GetOrCreateTextElement(previous);
                var currText = current.Element(Ns.W + "t");
                if (currText != null && prevText != null)
                {
                    prevText.Value += currText.Value;
                    // Preserve xml:space="preserve" if either has it
                    if (currText.Attribute(XNamespace.Xml + "space")?.Value == "preserve" ||
                        prevText.Value.StartsWith(' ') || prevText.Value.EndsWith(' '))
                    {
                        prevText.SetAttributeValue(XNamespace.Xml + "space", "preserve");
                    }
                }

                current.Remove();
                removedCount++;
            }
        }

        return new(originalCount, originalCount - removedCount, 0);
    }

    private static bool AreRunPropertiesEqual(XElement run1, XElement run2)
    {
        var rPr1 = run1.Element(Ns.W + "rPr");
        var rPr2 = run2.Element(Ns.W + "rPr");

        if (rPr1 == null && rPr2 == null) return true;
        if (rPr1 == null || rPr2 == null) return false;

        return XNode.DeepEquals(rPr1, rPr2);
    }

    private static XElement? GetOrCreateTextElement(XElement run)
    {
        var t = run.Element(Ns.W + "t");
        if (t == null)
        {
            t = new XElement(Ns.W + "t");
            run.Add(t);
        }
        return t;
    }
}
