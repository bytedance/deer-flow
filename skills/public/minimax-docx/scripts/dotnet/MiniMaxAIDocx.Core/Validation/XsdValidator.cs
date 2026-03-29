using System.IO.Compression;
using System.Xml;
using System.Xml.Schema;

namespace MiniMaxAIDocx.Core.Validation;

public class XsdValidator
{
    public ValidationResult Validate(string docxPath, string xsdPath)
    {
        using var zip = ZipFile.OpenRead(docxPath);
        var entry = zip.GetEntry("word/document.xml")
            ?? throw new InvalidOperationException("DOCX does not contain word/document.xml");

        using var stream = entry.Open();
        using var reader = new StreamReader(stream);
        var xmlContent = reader.ReadToEnd();

        return ValidateXml(xmlContent, xsdPath);
    }

    public ValidationResult ValidateXml(string xmlContent, string xsdPath)
    {
        var result = new ValidationResult();
        var settings = new XmlReaderSettings();

        var schemaSet = new XmlSchemaSet();
        schemaSet.Add(null, xsdPath);
        settings.Schemas = schemaSet;
        settings.ValidationType = ValidationType.Schema;
        settings.ValidationFlags |= XmlSchemaValidationFlags.ReportValidationWarnings;

        settings.ValidationEventHandler += (sender, e) =>
        {
            var error = new ValidationError
            {
                LineNumber = e.Exception?.LineNumber ?? 0,
                LinePosition = e.Exception?.LinePosition ?? 0,
                Message = e.Message,
                Severity = e.Severity == XmlSeverityType.Warning ? "Warning" : "Error"
            };

            if (e.Severity == XmlSeverityType.Warning)
                result.Warnings.Add(error);
            else
                result.Errors.Add(error);
        };

        using var stringReader = new StringReader(xmlContent);
        using var xmlReader = XmlReader.Create(stringReader, settings);

        try
        {
            while (xmlReader.Read()) { }
        }
        catch (XmlException ex)
        {
            result.Errors.Add(new ValidationError
            {
                LineNumber = ex.LineNumber,
                LinePosition = ex.LinePosition,
                Message = $"XML parse error: {ex.Message}",
                Severity = "Error"
            });
        }

        return result;
    }
}
