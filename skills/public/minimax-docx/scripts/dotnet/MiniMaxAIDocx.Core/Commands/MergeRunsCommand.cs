using System.CommandLine;
using System.IO.Compression;
using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.Commands;

public static class MergeRunsCommand
{
    private static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    public static Command Create()
    {
        var inputOption = new Option<string>("--input") { Description = "DOCX file to optimize", Required = true };
        var outputOption = new Option<string>("--output") { Description = "Output path (default: overwrite input)" };
        var dryRunOption = new Option<bool>("--dry-run") { Description = "Report without modifying" };

        var cmd = new Command("merge-runs", "Merge adjacent runs with identical formatting")
        {
            inputOption, outputOption, dryRunOption
        };

        cmd.SetAction((parseResult) =>
        {
            var input = parseResult.GetValue(inputOption)!;
            var output = parseResult.GetValue(outputOption) ?? input;
            var dryRun = parseResult.GetValue(dryRunOption);

            if (!File.Exists(input))
            {
                Console.Error.WriteLine($"File not found: {input}");
                return;
            }

            var tempPath = Path.GetTempFileName();
            File.Copy(input, tempPath, true);

            using var zip = ZipFile.Open(tempPath, ZipArchiveMode.Update);
            var entry = zip.GetEntry("word/document.xml");
            if (entry == null)
            {
                Console.Error.WriteLine("Not a valid DOCX: missing word/document.xml");
                return;
            }

            XDocument doc;
            using (var stream = entry.Open())
                doc = XDocument.Load(stream);

            int originalCount = 0;
            int mergedCount = 0;

            foreach (var p in doc.Descendants(W + "p"))
            {
                var runs = p.Elements(W + "r").ToList();
                originalCount += runs.Count;

                for (int i = runs.Count - 1; i > 0; i--)
                {
                    var current = runs[i];
                    var previous = runs[i - 1];

                    var curProps = current.Element(W + "rPr")?.ToString() ?? "";
                    var prevProps = previous.Element(W + "rPr")?.ToString() ?? "";

                    if (curProps == prevProps)
                    {
                        // Only merge if both contain only text elements
                        var curChildren = current.Elements().Where(e => e.Name != W + "rPr").ToList();
                        var prevChildren = previous.Elements().Where(e => e.Name != W + "rPr").ToList();

                        if (curChildren.All(e => e.Name == W + "t") && prevChildren.All(e => e.Name == W + "t"))
                        {
                            var prevText = previous.Elements(W + "t").LastOrDefault();
                            var curText = current.Elements(W + "t").FirstOrDefault();

                            if (prevText != null && curText != null)
                            {
                                prevText.Value += curText.Value;
                                prevText.SetAttributeValue(XNamespace.Xml + "space", "preserve");

                                foreach (var extra in current.Elements(W + "t").Skip(1))
                                {
                                    previous.Add(new XElement(extra));
                                }

                                current.Remove();
                                runs.RemoveAt(i);
                            }
                        }
                    }
                }

                mergedCount += runs.Count;
            }

            if (dryRun)
            {
                Console.WriteLine($"Original runs: {originalCount}");
                Console.WriteLine($"After merge:   {mergedCount}");
                Console.WriteLine($"Reduction:     {(originalCount > 0 ? (originalCount - mergedCount) * 100.0 / originalCount : 0):F1}%");
                File.Delete(tempPath);
                return;
            }

            entry.Delete();
            var newEntry = zip.CreateEntry("word/document.xml", CompressionLevel.Optimal);
            using (var stream = newEntry.Open())
                doc.Save(stream);

            zip.Dispose();
            File.Copy(tempPath, output, true);
            File.Delete(tempPath);

            Console.WriteLine($"Original runs: {originalCount}");
            Console.WriteLine($"After merge:   {mergedCount}");
            Console.WriteLine($"Reduction:     {(originalCount > 0 ? (originalCount - mergedCount) * 100.0 / originalCount : 0):F1}%");
            Console.WriteLine($"Written to:    {output}");
        });

        return cmd;
    }
}
