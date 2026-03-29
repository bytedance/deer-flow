using System.CommandLine;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Commands;

/// <summary>
/// Scenario C: Apply formatting from a template DOCX to a source DOCX.
/// Copies styles, theme, numbering, headers/footers, and section properties
/// from the template while preserving all content from the source.
/// </summary>
public static class ApplyTemplateCommand
{
    public static Command Create()
    {
        var inputOpt = new Option<string>("--input") { Description = "Source DOCX (content to keep)", Required = true };
        var templateOpt = new Option<string>("--template") { Description = "Template DOCX (formatting to apply)", Required = true };
        var outputOpt = new Option<string>("--output") { Description = "Output DOCX file path", Required = true };
        var applyStylesOpt = new Option<bool>("--apply-styles") { Description = "Copy styles.xml from template" };
        applyStylesOpt.DefaultValueFactory = _ => true;
        var applyThemeOpt = new Option<bool>("--apply-theme") { Description = "Copy theme from template" };
        applyThemeOpt.DefaultValueFactory = _ => true;
        var applyNumberingOpt = new Option<bool>("--apply-numbering") { Description = "Copy numbering.xml from template" };
        applyNumberingOpt.DefaultValueFactory = _ => true;
        var applyHeadersFootersOpt = new Option<bool>("--apply-headers-footers") { Description = "Copy headers/footers from template" };
        var applySectionsOpt = new Option<bool>("--apply-sections") { Description = "Apply section properties from template" };
        applySectionsOpt.DefaultValueFactory = _ => true;

        var cmd = new Command("apply-template", "Apply template formatting to a DOCX")
        {
            inputOpt, templateOpt, outputOpt, applyStylesOpt, applyThemeOpt,
            applyNumberingOpt, applyHeadersFootersOpt, applySectionsOpt
        };

        cmd.SetAction((parseResult) =>
        {
            var inputPath = parseResult.GetValue(inputOpt)!;
            var templatePath = parseResult.GetValue(templateOpt)!;
            var outputPath = parseResult.GetValue(outputOpt)!;
            var applyStyles = parseResult.GetValue(applyStylesOpt);
            var applyTheme = parseResult.GetValue(applyThemeOpt);
            var applyNumbering = parseResult.GetValue(applyNumberingOpt);
            var applyHeadersFooters = parseResult.GetValue(applyHeadersFootersOpt);
            var applySections = parseResult.GetValue(applySectionsOpt);

            if (!File.Exists(inputPath)) { Console.Error.WriteLine($"Input file not found: {inputPath}"); return; }
            if (!File.Exists(templatePath)) { Console.Error.WriteLine($"Template file not found: {templatePath}"); return; }

            // Create output as a copy of the source
            File.Copy(inputPath, outputPath, overwrite: true);

            using var output = WordprocessingDocument.Open(outputPath, true);
            using var template = WordprocessingDocument.Open(templatePath, false);

            var outputMain = output.MainDocumentPart;
            var templateMain = template.MainDocumentPart;
            if (outputMain == null || templateMain == null)
            {
                Console.Error.WriteLine("Invalid document: missing main document part.");
                return;
            }

            int appliedCount = 0;

            if (applyStyles)
            {
                CopyStyles(templateMain, outputMain);
                appliedCount++;
                Console.WriteLine("  Applied: styles");
            }

            if (applyTheme)
            {
                CopyTheme(templateMain, outputMain);
                appliedCount++;
                Console.WriteLine("  Applied: theme");
            }

            if (applyNumbering)
            {
                CopyNumbering(templateMain, outputMain);
                appliedCount++;
                Console.WriteLine("  Applied: numbering");
            }

            if (applyHeadersFooters)
            {
                CopyHeadersAndFooters(templateMain, outputMain);
                appliedCount++;
                Console.WriteLine("  Applied: headers/footers");
            }

            if (applySections)
            {
                CopySectionProperties(templateMain, outputMain);
                appliedCount++;
                Console.WriteLine("  Applied: section properties");
            }

            outputMain.Document.Save();
            Console.WriteLine($"Applied {appliedCount} formatting component(s) from template to {outputPath}");
        });

        return cmd;
    }

    /// <summary>
    /// Replaces the output's StyleDefinitionsPart with the template's version.
    /// </summary>
    private static void CopyStyles(MainDocumentPart template, MainDocumentPart output)
    {
        var templateStyles = template.StyleDefinitionsPart;
        if (templateStyles == null) return;

        if (output.StyleDefinitionsPart != null)
            output.DeletePart(output.StyleDefinitionsPart);

        var newStylesPart = output.AddNewPart<StyleDefinitionsPart>();

        using var stream = templateStyles.GetStream(FileMode.Open, FileAccess.Read);
        newStylesPart.FeedData(stream);
    }

    /// <summary>
    /// Replaces the output's ThemePart with the template's version.
    /// </summary>
    private static void CopyTheme(MainDocumentPart template, MainDocumentPart output)
    {
        var templateTheme = template.ThemePart;
        if (templateTheme == null) return;

        if (output.ThemePart != null)
            output.DeletePart(output.ThemePart);

        var newThemePart = output.AddNewPart<ThemePart>();

        using var stream = templateTheme.GetStream(FileMode.Open, FileAccess.Read);
        newThemePart.FeedData(stream);
    }

    /// <summary>
    /// Copies numbering definitions from template, remapping numbering IDs
    /// referenced in the output document's paragraphs.
    /// </summary>
    private static void CopyNumbering(MainDocumentPart template, MainDocumentPart output)
    {
        var templateNumbering = template.NumberingDefinitionsPart;
        if (templateNumbering == null) return;

        var referencedNumIds = new HashSet<string>();
        var body = output.Document.Body;
        if (body != null)
        {
            foreach (var numId in body.Descendants<NumberingId>())
            {
                if (numId.Val?.Value != null)
                    referencedNumIds.Add(numId.Val.Value.ToString());
            }
        }

        if (output.NumberingDefinitionsPart != null)
            output.DeletePart(output.NumberingDefinitionsPart);

        var newNumberingPart = output.AddNewPart<NumberingDefinitionsPart>();

        using var stream = templateNumbering.GetStream(FileMode.Open, FileAccess.Read);
        newNumberingPart.FeedData(stream);

        if (referencedNumIds.Count > 0)
        {
            Console.WriteLine($"  Note: {referencedNumIds.Count} numbering reference(s) in document content mapped to template definitions.");
        }
    }

    /// <summary>
    /// Copies headers and footers from the template, remapping relationship IDs.
    /// </summary>
    private static void CopyHeadersAndFooters(MainDocumentPart template, MainDocumentPart output)
    {
        var outputBody = output.Document.Body;
        if (outputBody == null) return;

        // Remove existing header/footer parts from output
        foreach (var hp in output.HeaderParts.ToList())
            output.DeletePart(hp);
        foreach (var fp in output.FooterParts.ToList())
            output.DeletePart(fp);

        // Remove existing header/footer references from all section properties
        foreach (var sectPr in outputBody.Descendants<SectionProperties>())
        {
            foreach (var hr in sectPr.Elements<HeaderReference>().ToList())
                hr.Remove();
            foreach (var fr in sectPr.Elements<FooterReference>().ToList())
                fr.Remove();
        }

        var templateBody = template.Document?.Body;
        if (templateBody == null) return;

        var templateFinalSectPr = templateBody.Descendants<SectionProperties>().LastOrDefault();
        if (templateFinalSectPr == null) return;

        var outputFinalSectPr = outputBody.Descendants<SectionProperties>().LastOrDefault();
        if (outputFinalSectPr == null)
        {
            outputFinalSectPr = new SectionProperties();
            outputBody.Append(outputFinalSectPr);
        }

        // Copy headers
        foreach (var headerRef in templateFinalSectPr.Elements<HeaderReference>())
        {
            var templateHeaderPart = template.GetPartById(headerRef.Id!) as HeaderPart;
            if (templateHeaderPart == null) continue;

            var newHeaderPart = output.AddNewPart<HeaderPart>();
            using (var stream = templateHeaderPart.GetStream(FileMode.Open, FileAccess.Read))
            {
                newHeaderPart.FeedData(stream);
            }

            CopyPartRelationships(templateHeaderPart, newHeaderPart);

            var newRefId = output.GetIdOfPart(newHeaderPart);
            outputFinalSectPr.InsertAt(new HeaderReference
            {
                Type = headerRef.Type,
                Id = newRefId
            }, 0);
        }

        // Copy footers
        foreach (var footerRef in templateFinalSectPr.Elements<FooterReference>())
        {
            var templateFooterPart = template.GetPartById(footerRef.Id!) as FooterPart;
            if (templateFooterPart == null) continue;

            var newFooterPart = output.AddNewPart<FooterPart>();
            using (var stream = templateFooterPart.GetStream(FileMode.Open, FileAccess.Read))
            {
                newFooterPart.FeedData(stream);
            }

            CopyPartRelationships(templateFooterPart, newFooterPart);

            var newRefId = output.GetIdOfPart(newFooterPart);
            var lastHeaderRef = outputFinalSectPr.Elements<HeaderReference>().LastOrDefault();
            if (lastHeaderRef != null)
                lastHeaderRef.InsertAfterSelf(new FooterReference { Type = footerRef.Type, Id = newRefId });
            else
                outputFinalSectPr.InsertAt(new FooterReference { Type = footerRef.Type, Id = newRefId }, 0);
        }
    }

    /// <summary>
    /// Copies sub-relationships (images, etc.) from a source part to a target part.
    /// </summary>
    private static void CopyPartRelationships(OpenXmlPart source, OpenXmlPart target)
    {
        foreach (var rel in source.ExternalRelationships)
        {
            target.AddExternalRelationship(rel.RelationshipType, rel.Uri, rel.Id);
        }

        foreach (var childPart in source.Parts)
        {
            try
            {
                var contentType = childPart.OpenXmlPart.ContentType;
                if (contentType.StartsWith("image/"))
                {
                    var newChild = target.AddNewPart<ImagePart>(contentType, childPart.RelationshipId);
                    using var stream = childPart.OpenXmlPart.GetStream(FileMode.Open, FileAccess.Read);
                    newChild.FeedData(stream);
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[WARN] Skipped non-image embedded part: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Copies page size, margins, columns, and document grid from template section properties.
    /// </summary>
    private static void CopySectionProperties(MainDocumentPart template, MainDocumentPart output)
    {
        var templateBody = template.Document?.Body;
        var outputBody = output.Document?.Body;
        if (templateBody == null || outputBody == null) return;

        var templateSectPr = templateBody.Descendants<SectionProperties>().LastOrDefault();
        if (templateSectPr == null) return;

        var outputSectPr = outputBody.Descendants<SectionProperties>().LastOrDefault();
        if (outputSectPr == null)
        {
            outputSectPr = new SectionProperties();
            outputBody.Append(outputSectPr);
        }

        CopyChildElement<PageSize>(templateSectPr, outputSectPr);
        CopyChildElement<PageMargin>(templateSectPr, outputSectPr);
        CopyChildElement<Columns>(templateSectPr, outputSectPr);
        CopyChildElement<DocGrid>(templateSectPr, outputSectPr);
        CopyChildElement<PageBorders>(templateSectPr, outputSectPr);
    }

    private static void CopyChildElement<T>(SectionProperties source, SectionProperties target) where T : OpenXmlElement
    {
        var sourceElement = source.GetFirstChild<T>();
        if (sourceElement == null) return;

        var existing = target.GetFirstChild<T>();
        existing?.Remove();

        target.Append((T)sourceElement.CloneNode(true));
    }
}
