# Comments System Guide (4-File Architecture)

## Overview

Word comments require coordination across **four XML files** plus references in `document.xml`, `[Content_Types].xml`, and `document.xml.rels`.

---

## The Four Comment Files

### 1. `word/comments.xml` — Main Comment Content

Contains the actual comment text:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:comment w:id="1" w:author="Alice" w:date="2026-03-21T09:00:00Z" w:initials="A">
    <w:p>
      <w:pPr><w:pStyle w:val="CommentText" /></w:pPr>
      <w:r>
        <w:rPr><w:rStyle w:val="CommentReference" /></w:rPr>
        <w:annotationRef />
      </w:r>
      <w:r>
        <w:t>This needs clarification.</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>
```

Key attributes: `w:id` (unique integer), `w:author`, `w:date` (ISO 8601), `w:initials`.

### 2. `word/commentsExtended.xml` — W15 Extensions

Links comments to paragraphs and tracks resolved status:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">
  <w15:commentEx w15:paraId="1A2B3C4D" w15:done="0" />
</w15:commentsEx>
```

- `w15:paraId` — matches the `w14:paraId` of the comment's paragraph in `comments.xml`
- `w15:done` — `"0"` = open, `"1"` = resolved

### 3. `word/commentsIds.xml` — Persistent ID Mapping

Provides durable IDs that survive copy/paste across documents:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cid:commentsIds xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid">
  <w16cid:commentId w16cid:paraId="1A2B3C4D" w16cid:durableId="12345678" />
</w16cid:commentsIds>
```

- `w16cid:paraId` — same as `w15:paraId`
- `w16cid:durableId` — globally unique identifier (8-digit hex)

### 4. `word/commentsExtensible.xml` — W16 Extensions

Modern comment extensions (used in newer Word versions):

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cex:commentsExtensible xmlns:w16cex="http://schemas.microsoft.com/office/word/2018/wordml/cex">
  <w16cex:commentExtensible w16cex:durableId="12345678" w16cex:dateUtc="2026-03-21T09:00:00Z" />
</w16cex:commentsExtensible>
```

---

## Document.xml References

Comments are anchored in document content using three elements:

```xml
<w:p>
  <w:commentRangeStart w:id="1" />
  <w:r><w:t>This text has a comment.</w:t></w:r>
  <w:commentRangeEnd w:id="1" />
  <w:r>
    <w:rPr><w:rStyle w:val="CommentReference" /></w:rPr>
    <w:commentReference w:id="1" />
  </w:r>
</w:p>
```

- `w:commentRangeStart` — marks where the commented text begins
- `w:commentRangeEnd` — marks where the commented text ends
- `w:commentReference` — the visible comment marker (superscript number), placed in a run after the range end

The `w:id` on all three must match the `w:id` in `comments.xml`.

---

## Content Types Registration

Add to `[Content_Types].xml`:

```xml
<Override PartName="/word/comments.xml"
          ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml" />
<Override PartName="/word/commentsExtended.xml"
          ContentType="application/vnd.ms-word.commentsExtended+xml" />
<Override PartName="/word/commentsIds.xml"
          ContentType="application/vnd.ms-word.commentsIds+xml" />
<Override PartName="/word/commentsExtensible.xml"
          ContentType="application/vnd.ms-word.commentsExtensible+xml" />
```

---

## Relationship Registration

Add to `word/_rels/document.xml.rels`:

```xml
<Relationship Id="rId20" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
              Target="comments.xml" />
<Relationship Id="rId21" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
              Target="commentsExtended.xml" />
<Relationship Id="rId22" Type="http://schemas.microsoft.com/office/2016/09/relationships/commentsIds"
              Target="commentsIds.xml" />
<Relationship Id="rId23" Type="http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible"
              Target="commentsExtensible.xml" />
```

---

## Step-by-Step: Adding a New Comment

1. **Choose a unique comment ID** (scan existing `w:id` values, use max + 1)
2. **Generate a paraId** (8-character hex, e.g., `"1A2B3C4D"`) and durableId (8-digit hex)
3. **Add to `comments.xml`**: Create `w:comment` element with content
4. **Add to `commentsExtended.xml`**: Create `w15:commentEx` with `paraId`, `done="0"`
5. **Add to `commentsIds.xml`**: Create `w16cid:commentId` with `paraId` and `durableId`
6. **Add to `commentsExtensible.xml`**: Create `w16cex:commentExtensible` with `durableId` and `dateUtc`
7. **Add to `document.xml`**: Insert `w:commentRangeStart`, `w:commentRangeEnd`, and `w:commentReference` around target text
8. **Verify `[Content_Types].xml`** and `document.xml.rels` have entries for all 4 files

---

## Step-by-Step: Adding a Reply

Replies are comments whose paragraph's `w14:paraId` links to a parent comment:

1. Create a new `w:comment` in `comments.xml` with a new `w:id`
2. In `commentsExtended.xml`, add `w15:commentEx` with:
   - `w15:paraId` = new paragraph ID
   - `w15:paraIdParent` = the `paraId` of the comment being replied to
   - `w15:done="0"`
3. Add entries in `commentsIds.xml` and `commentsExtensible.xml`
4. In `document.xml`, the reply does NOT need its own range markers — it shares the parent's range

```xml
<!-- In commentsExtended.xml -->
<w15:commentEx w15:paraId="5E6F7A8B" w15:paraIdParent="1A2B3C4D" w15:done="0" />
```

---

## Step-by-Step: Resolving a Comment

Set `w15:done="1"` on the comment's `w15:commentEx` entry:

```xml
<!-- Before -->
<w15:commentEx w15:paraId="1A2B3C4D" w15:done="0" />

<!-- After -->
<w15:commentEx w15:paraId="1A2B3C4D" w15:done="1" />
```

This marks the comment (and all its replies) as resolved. The comment remains visible but appears grayed out in Word.

---

## Minimum Viable Comment

At minimum, a working comment requires:
1. `comments.xml` with the `w:comment` element
2. `document.xml` with range markers and reference
3. Relationship in `document.xml.rels`
4. Content type in `[Content_Types].xml`

The extended files (`commentsExtended`, `commentsIds`, `commentsExtensible`) are optional but recommended for full compatibility with modern Word.
