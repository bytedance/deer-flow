# OpenXML Namespaces, Relationship Types, and Content Types

## Core Namespaces

| Prefix | URI | Used In |
|--------|-----|---------|
| `w` | `http://schemas.openxmlformats.org/wordprocessingml/2006/main` | document.xml, styles.xml, numbering.xml, headers, footers |
| `r` | `http://schemas.openxmlformats.org/officeDocument/2006/relationships` | Relationship references (r:id) |
| `wp` | `http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing` | Image/drawing placement in document |
| `a` | `http://schemas.openxmlformats.org/drawingml/2006/main` | DrawingML core (shapes, images, themes) |
| `pic` | `http://schemas.openxmlformats.org/drawingml/2006/picture` | Picture element in DrawingML |
| `v` | `urn:schemas-microsoft-com:vml` | VML (legacy shapes, watermarks) |
| `o` | `urn:schemas-microsoft-com:office:office` | Office VML extensions |
| `m` | `http://schemas.openxmlformats.org/officeDocument/2006/math` | Math equations (OMML) |
| `mc` | `http://schemas.openxmlformats.org/markup-compatibility/2006` | Markup compatibility (Ignorable, AlternateContent) |

## Extended Namespaces

| Prefix | URI | Purpose |
|--------|-----|---------|
| `w14` | `http://schemas.microsoft.com/office/word/2010/wordml` | Word 2010 extensions (contentPart, etc.) |
| `w15` | `http://schemas.microsoft.com/office/word/2012/wordml` | Word 2013 extensions (commentEx, etc.) |
| `w16cid` | `http://schemas.microsoft.com/office/word/2016/wordml/cid` | Comment IDs (durable IDs) |
| `w16cex` | `http://schemas.microsoft.com/office/word/2018/wordml/cex` | Comment extensible |
| `w16se` | `http://schemas.microsoft.com/office/word/2015/wordml/symex` | Symbol extensions |
| `wps` | `http://schemas.microsoft.com/office/word/2010/wordprocessingShape` | WordprocessingML shapes |
| `wpc` | `http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas` | Drawing canvas |

## Relationship Types

| Relationship | Type URI |
|-------------|----------|
| Document | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument` |
| Styles | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles` |
| Numbering | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering` |
| Font Table | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable` |
| Settings | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings` |
| Theme | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme` |
| Image | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/image` |
| Hyperlink | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink` |
| Header | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/header` |
| Footer | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer` |
| Comments | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments` |
| CommentsExtended | `http://schemas.microsoft.com/office/2011/relationships/commentsExtended` |
| CommentsIds | `http://schemas.microsoft.com/office/2016/09/relationships/commentsIds` |
| CommentsExtensible | `http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible` |
| Footnotes | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes` |
| Endnotes | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes` |
| Glossary | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/glossaryDocument` |
| Web Settings | `http://schemas.openxmlformats.org/officeDocument/2006/relationships/webSettings` |

## Content Types (`[Content_Types].xml`)

### Default Extensions

```xml
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
<Default Extension="xml" ContentType="application/xml" />
<Default Extension="png" ContentType="image/png" />
<Default Extension="jpeg" ContentType="image/jpeg" />
<Default Extension="gif" ContentType="image/gif" />
<Default Extension="emf" ContentType="image/x-emf" />
```

### Part Overrides

| Part | Content Type |
|------|-------------|
| `/word/document.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml` |
| `/word/styles.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml` |
| `/word/numbering.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml` |
| `/word/settings.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml` |
| `/word/fontTable.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml` |
| `/word/theme/theme1.xml` | `application/vnd.openxmlformats-officedocument.theme+xml` |
| `/word/header1.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml` |
| `/word/footer1.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml` |
| `/word/comments.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml` |
| `/word/commentsExtended.xml` | `application/vnd.ms-word.commentsExtended+xml` |
| `/word/commentsIds.xml` | `application/vnd.ms-word.commentsIds+xml` |
| `/word/commentsExtensible.xml` | `application/vnd.ms-word.commentsExtensible+xml` |
| `/word/footnotes.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml` |
| `/word/endnotes.xml` | `application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml` |
