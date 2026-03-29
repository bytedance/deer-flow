using System.CommandLine;
using System.IO.Compression;
using System.Text.Json;
using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.Commands;

public static class DiffCommand
{
    private static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    public static Command Create()
    {
        var beforeOption = new Option<string>("--before") { Description = "Original DOCX", Required = true };
        var afterOption = new Option<string>("--after") { Description = "Modified DOCX", Required = true };
        var jsonOption = new Option<bool>("--json") { Description = "Output as JSON" };

        var cmd = new Command("diff", "Compare two DOCX files")
        {
            beforeOption, afterOption, jsonOption
        };

        cmd.SetAction((parseResult) =>
        {
            var before = parseResult.GetValue(beforeOption)!;
            var after = parseResult.GetValue(afterOption)!;
            var asJson = parseResult.GetValue(jsonOption);

            if (!File.Exists(before)) { Console.Error.WriteLine($"File not found: {before}"); return; }
            if (!File.Exists(after)) { Console.Error.WriteLine($"File not found: {after}"); return; }

            var beforeParas = ExtractParagraphs(before);
            var afterParas = ExtractParagraphs(after);
            var beforeStyles = ExtractStyleIds(before);
            var afterStyles = ExtractStyleIds(after);
            var beforeStructure = ExtractStructure(before);
            var afterStructure = ExtractStructure(after);

            // Text diff
            var textChanges = new List<object>();
            int maxLen = Math.Max(beforeParas.Count, afterParas.Count);
            int changedParas = 0;
            for (int i = 0; i < maxLen; i++)
            {
                var bText = i < beforeParas.Count ? beforeParas[i] : null;
                var aText = i < afterParas.Count ? afterParas[i] : null;

                if (bText != aText)
                {
                    changedParas++;
                    textChanges.Add(new
                    {
                        paragraph = i + 1,
                        before = bText ?? "(absent)",
                        after = aText ?? "(absent)"
                    });
                }
            }

            // Style diff
            var addedStyles = afterStyles.Except(beforeStyles).ToList();
            var removedStyles = beforeStyles.Except(afterStyles).ToList();

            // Structure diff
            var structureChanges = new List<string>();
            if (beforeStructure.Sections != afterStructure.Sections)
                structureChanges.Add($"Sections: {beforeStructure.Sections} -> {afterStructure.Sections}");
            if (beforeStructure.Tables != afterStructure.Tables)
                structureChanges.Add($"Tables: {beforeStructure.Tables} -> {afterStructure.Tables}");
            if (beforeStructure.Images != afterStructure.Images)
                structureChanges.Add($"Images: {beforeStructure.Images} -> {afterStructure.Images}");

            var result = new
            {
                textChanges,
                styleChanges = new { added = addedStyles, removed = removedStyles },
                structureChanges,
                summary = $"{changedParas} paragraphs changed, {addedStyles.Count + removedStyles.Count} styles modified, {structureChanges.Count} structural changes"
            };

            if (asJson)
            {
                Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
            }
            else
            {
                Console.WriteLine(result.summary);
                Console.WriteLine();

                if (textChanges.Count > 0)
                {
                    Console.WriteLine($"Text changes ({textChanges.Count}):");
                    foreach (var tc in textChanges.Take(20))
                        Console.WriteLine($"  {tc}");
                    if (textChanges.Count > 20)
                        Console.WriteLine($"  ... and {textChanges.Count - 20} more");
                }

                if (addedStyles.Count > 0)
                    Console.WriteLine($"Added styles: {string.Join(", ", addedStyles)}");
                if (removedStyles.Count > 0)
                    Console.WriteLine($"Removed styles: {string.Join(", ", removedStyles)}");

                foreach (var sc in structureChanges)
                    Console.WriteLine($"Structure: {sc}");
            }
        });

        return cmd;
    }

    private static List<string> ExtractParagraphs(string docxPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/document.xml");
        if (entry == null) return new();

        using var stream = entry.Open();
        var doc = XDocument.Load(stream);
        return doc.Descendants(W + "p")
            .Select(p => string.Concat(p.Descendants(W + "t").Select(t => t.Value)))
            .ToList();
    }

    private static HashSet<string> ExtractStyleIds(string docxPath)
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

    private record StructureInfo(int Sections, int Tables, int Images);

    private static StructureInfo ExtractStructure(string docxPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/document.xml");
        if (entry == null) return new(0, 0, 0);

        using var stream = entry.Open();
        var doc = XDocument.Load(stream);
        return new(
            doc.Descendants(W + "sectPr").Count(),
            doc.Descendants(W + "tbl").Count(),
            doc.Descendants(W + "drawing").Count()
        );
    }
}
