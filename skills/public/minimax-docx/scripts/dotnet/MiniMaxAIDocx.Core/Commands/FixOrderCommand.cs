using System.CommandLine;
using System.IO.Compression;
using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.Commands;

public static class FixOrderCommand
{
    private static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    // Canonical element ordering within common parent elements per ISO 29500
    private static readonly Dictionary<string, List<string>> ElementOrder = new()
    {
        ["pPr"] = new() { "pStyle", "keepNext", "keepLines", "pageBreakBefore", "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "spacing", "ind", "jc", "outlineLvl", "rPr" },
        ["rPr"] = new() { "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "vanish", "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "vertAlign", "lang" },
        ["tblPr"] = new() { "tblStyle", "tblpPr", "tblOverlap", "tblW", "jc", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook" },
        ["tcPr"] = new() { "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign" },
        ["sectPr"] = new() { "headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz", "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "docGrid" },
    };

    public static Command Create()
    {
        var inputOption = new Option<string>("--input") { Description = "DOCX file to fix", Required = true };
        var outputOption = new Option<string>("--output") { Description = "Output path (default: overwrite input)" };
        var backupOption = new Option<bool>("--backup") { Description = "Create .bak before modifying", DefaultValueFactory = (_) => true };

        var cmd = new Command("fix-order", "Fix OpenXML element ordering per ISO 29500")
        {
            inputOption, outputOption, backupOption
        };

        cmd.SetAction((parseResult) =>
        {
            var input = parseResult.GetValue(inputOption)!;
            var output = parseResult.GetValue(outputOption) ?? input;
            var backup = parseResult.GetValue(backupOption);

            if (!File.Exists(input))
            {
                Console.Error.WriteLine($"File not found: {input}");
                return;
            }

            if (backup && output == input)
                File.Copy(input, input + ".bak", true);

            var tempPath = Path.GetTempFileName();
            File.Copy(input, tempPath, true);

            using var zip = ZipFile.Open(tempPath, ZipArchiveMode.Update);
            var entry = zip.GetEntry("word/document.xml");
            if (entry == null)
            {
                Console.Error.WriteLine("Not a valid DOCX");
                return;
            }

            XDocument doc;
            using (var stream = entry.Open())
                doc = XDocument.Load(stream);

            int reorderedCount = 0;

            foreach (var (parentName, order) in ElementOrder)
            {
                foreach (var parent in doc.Descendants(W + parentName))
                {
                    var children = parent.Elements().ToList();
                    var sorted = children.OrderBy(e =>
                    {
                        var idx = order.IndexOf(e.Name.LocalName);
                        return idx >= 0 ? idx : order.Count;
                    }).ToList();

                    bool changed = false;
                    for (int i = 0; i < children.Count; i++)
                    {
                        if (children[i] != sorted[i])
                        {
                            changed = true;
                            break;
                        }
                    }

                    if (changed)
                    {
                        parent.ReplaceNodes(sorted);
                        reorderedCount++;
                    }
                }
            }

            entry.Delete();
            var newEntry = zip.CreateEntry("word/document.xml", CompressionLevel.Optimal);
            using (var stream = newEntry.Open())
                doc.Save(stream);

            zip.Dispose();
            File.Copy(tempPath, output, true);
            File.Delete(tempPath);

            Console.WriteLine($"Reordered {reorderedCount} element group(s)");
            Console.WriteLine($"Written to: {output}");
        });

        return cmd;
    }
}
