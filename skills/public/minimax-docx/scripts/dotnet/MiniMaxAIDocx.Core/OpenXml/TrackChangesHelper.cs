using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// Helpers for Track Changes (revision marks) operations.
/// </summary>
public static class TrackChangesHelper
{
    /// <summary>
    /// Wraps a run in a w:ins element to propose an insertion.
    /// </summary>
    public static InsertedRun ProposeInsertion(Run run, string author, DateTime date)
    {
        var ins = new InsertedRun
        {
            Author = author,
            Date = date,
            Id = run.Parent is Body body ? GetNextRevisionId(body).ToString() : "1"
        };
        run.Remove();
        ins.Append(run);
        return ins;
    }

    /// <summary>
    /// Wraps a run in a w:del element, converting w:t to w:delText.
    /// </summary>
    public static DeletedRun ProposeDeletion(Run run, string author, DateTime date)
    {
        // Convert w:t elements to w:delText
        foreach (var text in run.Elements<Text>().ToList())
        {
            var delText = new DeletedText { Text = text.Text, Space = SpaceProcessingModeValues.Preserve };
            text.InsertAfterSelf(delText);
            text.Remove();
        }

        var del = new DeletedRun
        {
            Author = author,
            Date = date,
            Id = run.Parent is Body body ? GetNextRevisionId(body).ToString() : "1"
        };
        run.Remove();
        del.Append(run);
        return del;
    }

    /// <summary>
    /// Accepts an insertion by removing the w:ins wrapper and keeping content.
    /// </summary>
    public static void AcceptInsertion(OpenXmlElement insElement)
    {
        if (insElement is not InsertedRun) return;
        var parent = insElement.Parent;
        if (parent == null) return;

        var children = insElement.ChildElements.ToList();
        foreach (var child in children)
        {
            child.Remove();
            insElement.InsertBeforeSelf(child);
        }
        insElement.Remove();
    }

    /// <summary>
    /// Accepts a deletion by removing the entire w:del element and its content.
    /// </summary>
    public static void AcceptDeletion(OpenXmlElement delElement)
    {
        delElement.Remove();
    }

    /// <summary>
    /// Finds the maximum existing revision ID in the document and returns the next one.
    /// </summary>
    public static int GetNextRevisionId(WordprocessingDocument doc)
    {
        var body = doc.MainDocumentPart?.Document?.Body;
        if (body == null) return 1;
        return GetNextRevisionId(body);
    }

    private static int GetNextRevisionId(OpenXmlElement root)
    {
        int maxId = 0;
        foreach (var element in root.Descendants())
        {
            var idAttr = element.GetAttributes().FirstOrDefault(a => a.LocalName == "id");
            if (idAttr.Value != null && int.TryParse(idAttr.Value, out int id) && id > maxId)
                maxId = id;
        }
        return maxId + 1;
    }
}
