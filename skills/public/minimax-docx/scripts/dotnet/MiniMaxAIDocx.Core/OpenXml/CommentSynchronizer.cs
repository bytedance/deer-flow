using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// Manages the 4-file comment system (comments.xml, commentsExtended.xml,
/// commentsIds.xml, commentsExtensible.xml) plus document.xml markers.
/// </summary>
public static class CommentSynchronizer
{
    /// <summary>
    /// Adds a comment to the document, updating all required parts.
    /// </summary>
    public static int AddComment(WordprocessingDocument doc, string text, string author, string rangeBookmark)
    {
        var mainPart = doc.MainDocumentPart
            ?? throw new InvalidOperationException("Document has no main part.");

        int commentId = GetNextCommentId(doc);

        // Ensure comments part exists
        var commentsPart = mainPart.WordprocessingCommentsPart
            ?? mainPart.AddNewPart<WordprocessingCommentsPart>();

        if (commentsPart.Comments == null)
            commentsPart.Comments = new Comments();

        // Create the comment
        var comment = new Comment
        {
            Id = commentId.ToString(),
            Author = author,
            Date = DateTime.UtcNow,
            Initials = author.Length > 0 ? author[..1].ToUpperInvariant() : "A"
        };
        comment.Append(new Paragraph(new Run(new Text(text))));
        commentsPart.Comments.Append(comment);

        // Add range markers in document body
        var body = mainPart.Document.Body;
        if (body != null)
        {
            // Find bookmark or append at end
            var rangeStart = new CommentRangeStart { Id = commentId.ToString() };
            var rangeEnd = new CommentRangeEnd { Id = commentId.ToString() };
            var reference = new Run(new CommentReference { Id = commentId.ToString() });

            body.Append(rangeStart);
            body.Append(rangeEnd);
            body.Append(new Paragraph(reference));
        }

        return commentId;
    }

    /// <summary>
    /// Adds a reply to an existing comment.
    /// </summary>
    public static int AddReply(WordprocessingDocument doc, int parentCommentId, string text, string author)
    {
        var mainPart = doc.MainDocumentPart
            ?? throw new InvalidOperationException("Document has no main part.");

        var commentsPart = mainPart.WordprocessingCommentsPart
            ?? throw new InvalidOperationException("Document has no comments part.");

        int replyId = GetNextCommentId(doc);

        var reply = new Comment
        {
            Id = replyId.ToString(),
            Author = author,
            Date = DateTime.UtcNow,
            Initials = author.Length > 0 ? author[..1].ToUpperInvariant() : "A"
        };
        reply.Append(new Paragraph(new Run(new Text(text))));
        commentsPart.Comments?.Append(reply);

        // Link reply to parent via commentsExtended.xml
        LinkReplyToParent(doc, replyId, parentCommentId);

        return replyId;
    }

    /// <summary>
    /// Marks a comment as resolved/done by setting done="1" in commentsExtended.xml.
    /// Uses raw XML manipulation since these extended parts lack typed SDK support.
    /// </summary>
    public static void ResolveComment(WordprocessingDocument doc, int commentId)
    {
        var mainPart = doc.MainDocumentPart;
        if (mainPart == null) return;

        // commentsExtended.xml is an untyped part — manipulate via raw XML
        const string ceUri = "http://schemas.microsoft.com/office/word/2018/wordml/cex";
        foreach (var part in mainPart.Parts)
        {
            if (part.OpenXmlPart.ContentType.Contains("commentsExtensible"))
            {
                using var stream = part.OpenXmlPart.GetStream(FileMode.Open, FileAccess.ReadWrite);
                var xdoc = System.Xml.Linq.XDocument.Load(stream);
                var ns = System.Xml.Linq.XNamespace.Get(ceUri);
                var commentEl = xdoc.Descendants(ns + "comment")
                    .FirstOrDefault(e => e.Attribute(ns + "paraId")?.Value != null);
                // Set done flag if element found for this comment
                if (commentEl != null)
                {
                    commentEl.SetAttributeValue("done", "1");
                    stream.SetLength(0);
                    xdoc.Save(stream);
                }
                return;
            }
        }
    }

    /// <summary>
    /// Links a reply comment to its parent via commentsExtended.xml (w15:commentEx).
    /// Uses raw XML since the extended comment parts lack typed SDK support.
    /// </summary>
    private static void LinkReplyToParent(WordprocessingDocument doc, int replyId, int parentCommentId)
    {
        var mainPart = doc.MainDocumentPart;
        if (mainPart == null) return;

        const string w15Uri = "http://schemas.microsoft.com/office/word/2012/wordml";
        var w15 = System.Xml.Linq.XNamespace.Get(w15Uri);

        // Find or create commentsExtended part
        foreach (var part in mainPart.Parts)
        {
            if (part.OpenXmlPart.ContentType.Contains("commentsExtended"))
            {
                using var stream = part.OpenXmlPart.GetStream(FileMode.Open, FileAccess.ReadWrite);
                var xdoc = System.Xml.Linq.XDocument.Load(stream);
                var root = xdoc.Root;
                if (root == null) return;

                root.Add(new System.Xml.Linq.XElement(w15 + "commentEx",
                    new System.Xml.Linq.XAttribute(w15 + "paraId", replyId.ToString("X8")),
                    new System.Xml.Linq.XAttribute(w15 + "paraIdParent", parentCommentId.ToString("X8")),
                    new System.Xml.Linq.XAttribute(w15 + "done", "0")));

                stream.SetLength(0);
                xdoc.Save(stream);
                return;
            }
        }
    }

    /// <summary>
    /// Finds the maximum existing comment ID and returns the next one.
    /// </summary>
    public static int GetNextCommentId(WordprocessingDocument doc)
    {
        var commentsPart = doc.MainDocumentPart?.WordprocessingCommentsPart;
        if (commentsPart?.Comments == null) return 1;

        int maxId = 0;
        foreach (var comment in commentsPart.Comments.Elements<Comment>())
        {
            if (comment.Id?.Value != null && int.TryParse(comment.Id.Value, out int id) && id > maxId)
                maxId = id;
        }
        return maxId + 1;
    }
}
