using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Samples;

/// <summary>
/// Reference implementations for revision tracking (Track Changes).
///
/// ╔══════════════════════════════════════════════════════════════════╗
/// ║  CRITICAL: w:del uses w:delText, NEVER w:t                     ║
/// ║            w:ins uses w:t,       NEVER w:delText               ║
/// ║  Getting this wrong silently corrupts the document.            ║
/// ║  Word will open without error but display garbled text or      ║
/// ║  lose content when accepting/rejecting changes.                ║
/// ╚══════════════════════════════════════════════════════════════════╝
///
/// KEY CONCEPTS:
/// - Every revision element (ins, del, rPrChange, pPrChange) needs:
///     w:id   — unique revision ID (string, must be unique across all revisions)
///     w:author — who made the change
///     w:date — ISO 8601 timestamp
/// - InsertedRun (w:ins) wraps normal Run elements with w:t text
/// - DeletedRun (w:del) wraps Run elements that use DeletedText (w:delText) instead of Text (w:t)
/// - MoveFrom/MoveTo track text that was moved (not just deleted+inserted)
/// </summary>
public static class TrackChangesSamples
{
    /// <summary>
    /// Thread-safe counter for generating unique revision IDs.
    /// In production, scan the document for the max existing ID first.
    /// </summary>
    private static int s_revisionCounter;

    // ──────────────────────────────────────────────
    // 1. EnableTrackChanges
    // ──────────────────────────────────────────────

    /// <summary>
    /// Enables revision tracking in the document settings.
    /// This makes Word record all subsequent edits as tracked changes.
    ///
    /// Maps to: &lt;w:trackChanges/&gt; in settings.xml
    ///
    /// Note: This only controls whether NEW edits are tracked.
    /// Existing revision marks are always preserved regardless of this setting.
    /// </summary>
    public static void EnableTrackChanges(DocumentSettingsPart settingsPart)
    {
        settingsPart.Settings ??= new Settings();

        var existing = settingsPart.Settings.GetFirstChild<TrackRevisions>();
        if (existing == null)
        {
            settingsPart.Settings.Append(new TrackRevisions());
        }

        settingsPart.Settings.Save();
    }

    // ──────────────────────────────────────────────
    // 2. InsertTrackedInsertion — w:ins with w:t
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts text as a tracked insertion (w:ins).
    ///
    /// ╔══════════════════════════════════════════════════════╗
    /// ║  w:ins uses w:t (Text), NOT w:delText.              ║
    /// ║  The text appears with green underline in Word.     ║
    /// ╚══════════════════════════════════════════════════════╝
    ///
    /// XML structure:
    ///   &lt;w:ins w:id="1" w:author="John" w:date="2026-03-22T00:00:00Z"&gt;
    ///     &lt;w:r&gt;
    ///       &lt;w:t&gt;inserted text&lt;/w:t&gt;          &lt;!-- w:t, NOT w:delText --&gt;
    ///     &lt;/w:r&gt;
    ///   &lt;/w:ins&gt;
    /// </summary>
    public static InsertedRun InsertTrackedInsertion(Paragraph para, string text, string author)
    {
        var ins = new InsertedRun
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // CORRECT: w:ins contains w:r with w:t (normal Text element)
        ins.Append(new Run(
            new Text(text) { Space = SpaceProcessingModeValues.Preserve }));

        para.Append(ins);
        return ins;
    }

    // ──────────────────────────────────────────────
    // 3. InsertTrackedDeletion — w:del with w:delText
    // ──────────────────────────────────────────────

    /// <summary>
    /// Inserts text as a tracked deletion (w:del).
    ///
    /// ╔══════════════════════════════════════════════════════╗
    /// ║  w:del uses w:delText (DeletedText), NOT w:t.       ║
    /// ║  Using w:t inside w:del SILENTLY CORRUPTS the file. ║
    /// ║  The text appears with red strikethrough in Word.   ║
    /// ╚══════════════════════════════════════════════════════╝
    ///
    /// XML structure:
    ///   &lt;w:del w:id="2" w:author="John" w:date="2026-03-22T00:00:00Z"&gt;
    ///     &lt;w:r&gt;
    ///       &lt;w:delText xml:space="preserve"&gt;deleted text&lt;/w:delText&gt;   &lt;!-- w:delText, NOT w:t --&gt;
    ///     &lt;/w:r&gt;
    ///   &lt;/w:del&gt;
    /// </summary>
    public static DeletedRun InsertTrackedDeletion(Paragraph para, string deletedText, string author)
    {
        var del = new DeletedRun
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // CORRECT: w:del contains w:r with w:delText (DeletedText element)
        // WRONG would be: new Text(deletedText) — this creates w:t which corrupts the document
        del.Append(new Run(
            new DeletedText(deletedText) { Space = SpaceProcessingModeValues.Preserve }));

        para.Append(del);
        return del;
    }

    // ──────────────────────────────────────────────
    // 4. InsertFormattingChange — RunPropertiesChange
    // ──────────────────────────────────────────────

    /// <summary>
    /// Records a formatting change on a run (e.g., text was made bold).
    ///
    /// RunPropertiesChange (w:rPrChange) stores the PREVIOUS formatting.
    /// The current RunProperties on the run reflects the NEW formatting.
    ///
    /// Example: text changed from normal to bold:
    ///   &lt;w:rPr&gt;
    ///     &lt;w:b/&gt;                                      &lt;!-- current: bold --&gt;
    ///     &lt;w:rPrChange w:id="3" w:author="John" w:date="..."&gt;
    ///       &lt;w:rPr/&gt;                                  &lt;!-- previous: no bold --&gt;
    ///     &lt;/w:rPrChange&gt;
    ///   &lt;/w:rPr&gt;
    /// </summary>
    public static void InsertFormattingChange(Run run, string author)
    {
        // Ensure RunProperties exists
        run.RunProperties ??= new RunProperties();

        // Store the previous (empty/normal) formatting as the "before" state
        var rPrChange = new RunPropertiesChange
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // The child RunProperties inside rPrChange is the OLD formatting (before the change).
        // An empty RunProperties means "was default/normal formatting."
        rPrChange.Append(new PreviousRunProperties());

        run.RunProperties.Append(rPrChange);
    }

    // ──────────────────────────────────────────────
    // 5. InsertParagraphFormatChange — ParagraphPropertiesChange
    // ──────────────────────────────────────────────

    /// <summary>
    /// Records a paragraph formatting change (e.g., alignment changed).
    ///
    /// ParagraphPropertiesChange (w:pPrChange) stores the PREVIOUS paragraph properties.
    /// The current ParagraphProperties reflects the NEW formatting.
    ///
    /// Example: paragraph changed from left-aligned to centered:
    ///   &lt;w:pPr&gt;
    ///     &lt;w:jc w:val="center"/&gt;                     &lt;!-- current: centered --&gt;
    ///     &lt;w:pPrChange w:id="4" w:author="John" w:date="..."&gt;
    ///       &lt;w:pPr&gt;
    ///         &lt;w:jc w:val="left"/&gt;                   &lt;!-- previous: left --&gt;
    ///       &lt;/w:pPr&gt;
    ///     &lt;/w:pPrChange&gt;
    ///   &lt;/w:pPr&gt;
    /// </summary>
    public static void InsertParagraphFormatChange(Paragraph para, string author)
    {
        para.ParagraphProperties ??= new ParagraphProperties();

        var pPrChange = new ParagraphPropertiesChange
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // Store previous paragraph properties (before the change)
        // Example: was left-aligned before changing to whatever the current alignment is
        var previousPPr = new ParagraphPropertiesExtended();
        previousPPr.Append(new Justification { Val = JustificationValues.Left });
        pPrChange.Append(previousPPr);

        para.ParagraphProperties.Append(pPrChange);
    }

    // ──────────────────────────────────────────────
    // 6. InsertTableRowInsertion — table revision marks
    // ──────────────────────────────────────────────

    /// <summary>
    /// Marks a table row as a tracked insertion.
    ///
    /// Table-level track changes use TableRowProperties with InsertedMathControl
    /// mapped from w:trPr/w:ins — indicating the entire row was inserted.
    ///
    /// Structure:
    ///   &lt;w:tr&gt;
    ///     &lt;w:trPr&gt;
    ///       &lt;w:ins w:id="5" w:author="John" w:date="..."/&gt;
    ///     &lt;/w:trPr&gt;
    ///     &lt;w:tc&gt;...&lt;/w:tc&gt;
    ///   &lt;/w:tr&gt;
    /// </summary>
    public static void InsertTableRowInsertion(TableRow row, string author)
    {
        row.TableRowProperties ??= new TableRowProperties();

        var inserted = new Inserted
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        row.TableRowProperties.Append(inserted);
    }

    // ──────────────────────────────────────────────
    // 7. AcceptAllRevisions — accept all tracked changes
    // ──────────────────────────────────────────────

    /// <summary>
    /// Programmatically accepts all tracked changes in the document body.
    ///
    /// For insertions (w:ins): unwrap the content (keep the runs, remove the w:ins wrapper)
    /// For deletions (w:del): remove the entire element (the deleted text disappears)
    /// For formatting changes: remove the rPrChange/pPrChange (keep new formatting)
    /// For table row insertions: remove the w:ins from trPr
    ///
    /// ╔══════════════════════════════════════════════════════════════╗
    /// ║  Process deletions before insertions to avoid invalidating  ║
    /// ║  element references. Always call .ToList() before          ║
    /// ║  iterating to avoid modifying the collection during        ║
    /// ║  enumeration.                                              ║
    /// ╚══════════════════════════════════════════════════════════════╝
    /// </summary>
    public static void AcceptAllRevisions(Body body)
    {
        // 1. Accept deletions — remove the w:del and all its content
        foreach (var del in body.Descendants<DeletedRun>().ToList())
        {
            del.Remove();
        }

        // 2. Accept insertions — unwrap w:ins, keeping child runs in place
        foreach (var ins in body.Descendants<InsertedRun>().ToList())
        {
            var parent = ins.Parent;
            if (parent == null) continue;

            // Move all child elements before the ins element, then remove ins
            var children = ins.ChildElements.ToList();
            foreach (var child in children)
            {
                child.Remove();
                ins.InsertBeforeSelf(child);
            }
            ins.Remove();
        }

        // 3. Accept formatting changes — remove rPrChange (keep new formatting)
        foreach (var rPrChange in body.Descendants<RunPropertiesChange>().ToList())
        {
            rPrChange.Remove();
        }

        // 4. Accept paragraph formatting changes
        foreach (var pPrChange in body.Descendants<ParagraphPropertiesChange>().ToList())
        {
            pPrChange.Remove();
        }

        // 5. Accept table row insertions — remove w:ins from trPr
        foreach (var inserted in body.Descendants<TableRowProperties>()
            .SelectMany(trPr => trPr.Elements<Inserted>()).ToList())
        {
            inserted.Remove();
        }

        // 6. Accept MoveFrom/MoveTo — keep MoveTo content, remove MoveFrom
        foreach (var moveFrom in body.Descendants<MoveFromRun>().ToList())
        {
            moveFrom.Remove();
        }
        foreach (var moveTo in body.Descendants<MoveToRun>().ToList())
        {
            var parent = moveTo.Parent;
            if (parent == null) continue;
            var children = moveTo.ChildElements.ToList();
            foreach (var child in children)
            {
                child.Remove();
                moveTo.InsertBeforeSelf(child);
            }
            moveTo.Remove();
        }

        // 7. Remove move range markers
        foreach (var marker in body.Descendants<MoveFromRangeStart>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveFromRangeEnd>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveToRangeStart>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveToRangeEnd>().ToList()) marker.Remove();
    }

    // ──────────────────────────────────────────────
    // 8. RejectAllRevisions — reject all tracked changes
    // ──────────────────────────────────────────────

    /// <summary>
    /// Programmatically rejects all tracked changes in the document body.
    ///
    /// For insertions (w:ins): remove the entire element (the inserted text disappears)
    /// For deletions (w:del): unwrap the content and convert w:delText back to w:t
    ///                        (the "deleted" text is restored)
    /// For formatting changes: restore old formatting from rPrChange/pPrChange
    ///
    /// ╔══════════════════════════════════════════════════════════════╗
    /// ║  When rejecting deletions, you MUST convert w:delText back  ║
    /// ║  to w:t. Leaving w:delText in a non-deleted run causes     ║
    /// ║  the text to be invisible in Word.                         ║
    /// ╚══════════════════════════════════════════════════════════════╝
    /// </summary>
    public static void RejectAllRevisions(Body body)
    {
        // 1. Reject insertions — remove the entire w:ins and its content
        foreach (var ins in body.Descendants<InsertedRun>().ToList())
        {
            ins.Remove();
        }

        // 2. Reject deletions — restore deleted text by unwrapping w:del
        //    and converting w:delText back to w:t
        foreach (var del in body.Descendants<DeletedRun>().ToList())
        {
            var parent = del.Parent;
            if (parent == null) continue;

            // Convert DeletedText -> Text in each run inside the deletion
            foreach (var run in del.Elements<Run>().ToList())
            {
                foreach (var delText in run.Elements<DeletedText>().ToList())
                {
                    // IMPORTANT: convert w:delText back to w:t
                    var text = new Text(delText.Text ?? "") { Space = SpaceProcessingModeValues.Preserve };
                    delText.InsertAfterSelf(text);
                    delText.Remove();
                }
            }

            // Unwrap — move children before the del element
            var children = del.ChildElements.ToList();
            foreach (var child in children)
            {
                child.Remove();
                del.InsertBeforeSelf(child);
            }
            del.Remove();
        }

        // 3. Reject formatting changes — restore old RunProperties
        foreach (var rPrChange in body.Descendants<RunPropertiesChange>().ToList())
        {
            var runProperties = rPrChange.Parent as RunProperties;
            if (runProperties == null) continue;

            // Get the previous (old) formatting
            var previousRPr = rPrChange.GetFirstChild<PreviousRunProperties>();
            if (previousRPr != null)
            {
                // Remove current formatting (except the rPrChange itself)
                var currentProps = runProperties.ChildElements
                    .Where(c => c is not RunPropertiesChange).ToList();
                foreach (var prop in currentProps)
                {
                    prop.Remove();
                }

                // Restore old formatting from PreviousRunProperties
                foreach (var oldProp in previousRPr.ChildElements.ToList())
                {
                    oldProp.Remove();
                    runProperties.Append(oldProp);
                }
            }
            rPrChange.Remove();
        }

        // 4. Reject paragraph formatting changes — restore old ParagraphProperties
        foreach (var pPrChange in body.Descendants<ParagraphPropertiesChange>().ToList())
        {
            var paragraphProperties = pPrChange.Parent as ParagraphProperties;
            if (paragraphProperties == null) continue;

            var previousPPr = pPrChange.GetFirstChild<ParagraphPropertiesExtended>();
            if (previousPPr != null)
            {
                var currentProps = paragraphProperties.ChildElements
                    .Where(c => c is not ParagraphPropertiesChange).ToList();
                foreach (var prop in currentProps)
                {
                    prop.Remove();
                }
                foreach (var oldProp in previousPPr.ChildElements.ToList())
                {
                    oldProp.Remove();
                    paragraphProperties.Append(oldProp);
                }
            }
            pPrChange.Remove();
        }

        // 5. Reject table row insertions — remove the entire row
        foreach (var row in body.Descendants<TableRow>().ToList())
        {
            var trPr = row.TableRowProperties;
            if (trPr?.GetFirstChild<Inserted>() != null)
            {
                row.Remove();
            }
        }

        // 6. Reject MoveFrom/MoveTo — keep MoveFrom content (original position), remove MoveTo
        foreach (var moveTo in body.Descendants<MoveToRun>().ToList())
        {
            moveTo.Remove();
        }
        foreach (var moveFrom in body.Descendants<MoveFromRun>().ToList())
        {
            var parent = moveFrom.Parent;
            if (parent == null) continue;

            // Convert any DeletedText back to Text in MoveFrom runs
            foreach (var run in moveFrom.Elements<Run>().ToList())
            {
                foreach (var delText in run.Elements<DeletedText>().ToList())
                {
                    var text = new Text(delText.Text ?? "") { Space = SpaceProcessingModeValues.Preserve };
                    delText.InsertAfterSelf(text);
                    delText.Remove();
                }
            }

            var children = moveFrom.ChildElements.ToList();
            foreach (var child in children)
            {
                child.Remove();
                moveFrom.InsertBeforeSelf(child);
            }
            moveFrom.Remove();
        }

        // 7. Remove move range markers
        foreach (var marker in body.Descendants<MoveFromRangeStart>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveFromRangeEnd>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveToRangeStart>().ToList()) marker.Remove();
        foreach (var marker in body.Descendants<MoveToRangeEnd>().ToList()) marker.Remove();
    }

    // ──────────────────────────────────────────────
    // 9. InsertMoveFromTo — MoveFrom + MoveTo blocks
    // ──────────────────────────────────────────────

    /// <summary>
    /// Creates a tracked move operation (text moved from one location to another).
    ///
    /// A move consists of:
    ///   - MoveFromRangeStart/End markers around the original location
    ///   - MoveFrom (w:moveFrom) containing the original text with w:delText
    ///   - MoveToRangeStart/End markers around the new location
    ///   - MoveTo (w:moveTo) containing the moved text with w:t
    ///   - Both share the same name attribute to link them
    ///
    /// ╔══════════════════════════════════════════════════════════════╗
    /// ║  MoveFrom uses w:delText (like w:del — text is "leaving")  ║
    /// ║  MoveTo uses w:t (like w:ins — text is "arriving")         ║
    /// ╚══════════════════════════════════════════════════════════════╝
    /// </summary>
    public static void InsertMoveFromTo(Body body, string movedText, string author)
    {
        string moveId = GenerateRevisionId();
        string moveId2 = GenerateRevisionId();
        string moveName = "move" + moveId;

        // ── MoveFrom paragraph (original location — text shown with strikethrough) ──
        var moveFromPara = new Paragraph();

        moveFromPara.Append(new MoveFromRangeStart
        {
            Id = moveId,
            Author = author,
            Date = DateTime.UtcNow,
            Name = moveName
        });

        var moveFrom = new MoveFromRun
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // MoveFrom uses DeletedText (w:delText), NOT Text (w:t)
        // The text is visually struck through in Word
        moveFrom.Append(new Run(
            new DeletedText(movedText) { Space = SpaceProcessingModeValues.Preserve }));

        moveFromPara.Append(moveFrom);
        moveFromPara.Append(new MoveFromRangeEnd { Id = moveId });

        body.Append(moveFromPara);

        // ── MoveTo paragraph (destination — text shown with double underline) ──
        var moveToPara = new Paragraph();

        moveToPara.Append(new MoveToRangeStart
        {
            Id = moveId2,
            Author = author,
            Date = DateTime.UtcNow,
            Name = moveName
        });

        var moveTo = new MoveToRun
        {
            Id = GenerateRevisionId(),
            Author = author,
            Date = DateTime.UtcNow
        };

        // MoveTo uses Text (w:t), NOT DeletedText (w:delText)
        // The text is visually double-underlined in green in Word
        moveTo.Append(new Run(
            new Text(movedText) { Space = SpaceProcessingModeValues.Preserve }));

        moveToPara.Append(moveTo);
        moveToPara.Append(new MoveToRangeEnd { Id = moveId2 });

        body.Append(moveToPara);
    }

    // ──────────────────────────────────────────────
    // 10. GenerateRevisionId — unique ID pattern
    // ──────────────────────────────────────────────

    /// <summary>
    /// Generates a unique revision ID string.
    ///
    /// Revision IDs (w:id) must be unique across ALL revision elements in the document:
    /// ins, del, rPrChange, pPrChange, moveFrom, moveTo, table row ins/del, etc.
    ///
    /// Word uses simple incrementing integers starting from 0.
    /// When programmatically adding revisions to an existing document,
    /// first scan for the maximum existing ID and start from there.
    ///
    /// For new documents, a simple counter suffices.
    /// For existing documents, use:
    ///   int maxId = body.Descendants()
    ///       .SelectMany(e => e.GetAttributes())
    ///       .Where(a => a.LocalName == "id")
    ///       .Select(a => int.TryParse(a.Value, out int v) ? v : 0)
    ///       .DefaultIfEmpty(0)
    ///       .Max();
    /// </summary>
    public static string GenerateRevisionId()
    {
        return Interlocked.Increment(ref s_revisionCounter).ToString();
    }
}
