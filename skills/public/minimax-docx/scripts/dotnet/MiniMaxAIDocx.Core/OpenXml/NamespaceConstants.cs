using System.Xml.Linq;

namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// All OpenXML namespace URIs and common content/relationship type constants.
/// </summary>
public static class Ns
{
    public static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    public static readonly XNamespace R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    public static readonly XNamespace WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
    public static readonly XNamespace A = "http://schemas.openxmlformats.org/drawingml/2006/main";
    public static readonly XNamespace MC = "http://schemas.openxmlformats.org/markup-compatibility/2006";
    public static readonly XNamespace PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture";
    public static readonly XNamespace W14 = "http://schemas.microsoft.com/office/word/2010/wordml";
    public static readonly XNamespace W15 = "http://schemas.microsoft.com/office/word/2012/wordml";
    public static readonly XNamespace W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid";
    public static readonly XNamespace W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex";
    public static readonly XNamespace WPC = "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas";
    public static readonly XNamespace WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape";

    // Content types
    public const string MainDocumentContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml";
    public const string StylesContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml";
    public const string HeaderContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml";
    public const string FooterContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml";
    public const string CommentsContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml";

    // Relationship types
    public const string DocumentRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument";
    public const string StylesRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles";
    public const string HeaderRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header";
    public const string FooterRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer";
    public const string CommentsRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments";
    public const string ImageRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image";
    public const string HyperlinkRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink";
    public const string NumberingRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering";
    public const string FontTableRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable";
    public const string ThemeRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme";
    public const string SettingsRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings";
}
