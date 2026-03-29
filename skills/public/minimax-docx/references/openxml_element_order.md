# OpenXML Child Element Ordering Rules

Element ordering in OpenXML is defined by the XSD schema. Incorrect ordering produces invalid documents that Word may refuse to open or silently repair (potentially losing data).

> **Key rule**: Properties elements (`*Pr`) must always be the **first child** of their parent.

---

## w:document

```
Children in order:
1. w:background       [0..1]  — page background color/fill
2. w:body              [0..1]  — document content container
```

---

## w:body

```
Children in order (repeating group):
1. w:p                 [0..*]  — paragraph
2. w:tbl               [0..*]  — table
3. w:sdt               [0..*]  — structured document tag (content control)
4. w:sectPr            [0..1]  — LAST child: final section properties
```

Note: `w:p`, `w:tbl`, and `w:sdt` are interleaved in document order. The only strict rule is that `w:sectPr` must be the **last child** of `w:body`.

---

## w:p (Paragraph)

```
Children in order:
1. w:pPr               [0..1]  — paragraph properties (MUST be first)

Then any mix of (interleaved in document order):
- w:r                  [0..*]  — run
- w:hyperlink          [0..*]  — hyperlink wrapper
- w:ins                [0..*]  — tracked insertion
- w:del                [0..*]  — tracked deletion
- w:bookmarkStart      [0..*]  — bookmark anchor start
- w:bookmarkEnd        [0..*]  — bookmark anchor end
- w:commentRangeStart  [0..*]  — comment range start
- w:commentRangeEnd    [0..*]  — comment range end
- w:proofErr           [0..*]  — proofing error marker
- w:fldSimple          [0..*]  — simple field
- w:sdt                [0..*]  — inline content control
- w:smartTag           [0..*]  — smart tag
```

**Practical note**: After `w:pPr`, the remaining children appear in document reading order. Runs, hyperlinks, bookmarks, and comment ranges intermix freely based on their position in the text.

---

## w:pPr (Paragraph Properties)

```
Children in order:
1.  w:pStyle            [0..1]  — paragraph style reference
2.  w:keepNext          [0..1]  — keep with next paragraph
3.  w:keepLines         [0..1]  — keep lines together
4.  w:pageBreakBefore   [0..1]  — page break before paragraph
5.  w:framePr           [0..1]  — text frame properties
6.  w:widowControl      [0..1]  — widow/orphan control
7.  w:numPr             [0..1]  — numbering properties
8.  w:suppressLineNumbers [0..1]
9.  w:pBdr              [0..1]  — paragraph borders
10. w:shd               [0..1]  — shading
11. w:tabs              [0..1]  — tab stops
12. w:suppressAutoHyphens [0..1]
13. w:kinsoku           [0..1]  — CJK kinsoku settings
14. w:wordWrap           [0..1]
15. w:overflowPunct     [0..1]
16. w:topLinePunct      [0..1]
17. w:autoSpaceDE       [0..1]
18. w:autoSpaceDN       [0..1]
19. w:bidi              [0..1]  — right-to-left paragraph
20. w:adjustRightInd    [0..1]
21. w:snapToGrid        [0..1]
22. w:spacing            [0..1]  — line and paragraph spacing
23. w:ind               [0..1]  — indentation
24. w:contextualSpacing [0..1]
25. w:mirrorIndents     [0..1]
26. w:suppressOverlap   [0..1]
27. w:jc                [0..1]  — justification (left/center/right/both)
28. w:textDirection     [0..1]
29. w:textAlignment     [0..1]
30. w:outlineLvl        [0..1]  — outline level
31. w:divId             [0..1]
32. w:rPr               [0..1]  — run properties for paragraph mark
33. w:sectPr            [0..1]  — section break (section ends at this paragraph)
34. w:pPrChange         [0..1]  — tracked paragraph property change
```

---

## w:r (Run)

```
Children in order:
1. w:rPr               [0..1]  — run properties (MUST be first)

Then any of (one per run, typically):
- w:t                  [0..*]  — text content
- w:br                 [0..*]  — break (line, page, column)
- w:tab                [0..*]  — tab character
- w:cr                 [0..*]  — carriage return
- w:sym               [0..*]  — symbol character
- w:drawing            [0..*]  — DrawingML object (images)
- w:pict               [0..*]  — VML picture (legacy)
- w:fldChar            [0..*]  — complex field character
- w:instrText          [0..*]  — field instruction text
- w:delText            [0..*]  — deleted text (inside w:del)
- w:footnoteReference  [0..*]
- w:endnoteReference   [0..*]
- w:commentReference   [0..*]
- w:lastRenderedPageBreak [0..*]
```

---

## w:rPr (Run Properties)

```
Children in order:
1.  w:rStyle            [0..1]  — character style reference
2.  w:rFonts            [0..1]  — font specification
3.  w:b                 [0..1]  — bold
4.  w:bCs               [0..1]  — complex script bold
5.  w:i                 [0..1]  — italic
6.  w:iCs               [0..1]  — complex script italic
7.  w:caps              [0..1]  — all capitals
8.  w:smallCaps         [0..1]  — small capitals
9.  w:strike            [0..1]  — strikethrough
10. w:dstrike           [0..1]  — double strikethrough
11. w:outline           [0..1]
12. w:shadow            [0..1]
13. w:emboss            [0..1]
14. w:imprint           [0..1]
15. w:noProof           [0..1]  — suppress proofing
16. w:snapToGrid        [0..1]
17. w:vanish            [0..1]  — hidden text
18. w:color             [0..1]  — text color
19. w:spacing            [0..1]  — character spacing
20. w:w                 [0..1]  — character width scaling
21. w:kern              [0..1]  — font kerning
22. w:position          [0..1]  — vertical position (raise/lower)
23. w:sz                [0..1]  — font size (half-points)
24. w:szCs              [0..1]  — complex script font size
25. w:highlight         [0..1]  — text highlight color
26. w:u                 [0..1]  — underline
27. w:effect            [0..1]  — text effect (animated)
28. w:bdr               [0..1]  — run border
29. w:shd               [0..1]  — run shading
30. w:vertAlign         [0..1]  — superscript/subscript
31. w:rtl               [0..1]  — right-to-left
32. w:cs                [0..1]  — complex script
33. w:lang              [0..1]  — language
34. w:rPrChange         [0..1]  — tracked run property change
```

---

## w:tbl (Table)

```
Children in order:
1. w:tblPr              [1..1]  — table properties (REQUIRED, must be first)
2. w:tblGrid            [1..1]  — column width definitions (REQUIRED)
3. w:tr                 [1..*]  — table row(s)
```

---

## w:tblPr (Table Properties)

```
Children in order:
1.  w:tblStyle           [0..1]  — table style reference
2.  w:tblpPr             [0..1]  — table positioning
3.  w:tblOverlap         [0..1]
4.  w:bidiVisual         [0..1]  — right-to-left table
5.  w:tblStyleRowBandSize [0..1]
6.  w:tblStyleColBandSize [0..1]
7.  w:tblW               [0..1]  — preferred table width
8.  w:jc                 [0..1]  — table alignment
9.  w:tblCellSpacing     [0..1]
10. w:tblInd             [0..1]  — table indent from margin
11. w:tblBorders         [0..1]  — table borders
12. w:shd                [0..1]  — table shading
13. w:tblLayout          [0..1]  — fixed or autofit
14. w:tblCellMar         [0..1]  — default cell margins
15. w:tblLook            [0..1]  — conditional formatting flags
16. w:tblCaption         [0..1]  — accessibility caption
17. w:tblDescription     [0..1]  — accessibility description
18. w:tblPrChange        [0..1]  — tracked table property change
```

---

## w:tr (Table Row)

```
Children in order:
1. w:trPr               [0..1]  — row properties (must be first)
2. w:tc                  [1..*]  — table cell(s)
```

---

## w:trPr (Table Row Properties)

```
Children in order:
1.  w:cnfStyle           [0..1]  — conditional formatting
2.  w:divId              [0..1]
3.  w:gridBefore         [0..1]  — grid columns before first cell
4.  w:gridAfter          [0..1]  — grid columns after last cell
5.  w:wBefore            [0..1]
6.  w:wAfter             [0..1]
7.  w:cantSplit          [0..1]  — don't split row across pages
8.  w:trHeight           [0..1]  — row height
9.  w:tblHeader          [0..1]  — repeat as header row
10. w:tblCellSpacing     [0..1]
11. w:jc                 [0..1]  — row alignment
12. w:hidden             [0..1]
13. w:ins                [0..1]  — tracked row insertion
14. w:del                [0..1]  — tracked row deletion
15. w:trPrChange         [0..1]  — tracked row property change
```

---

## w:tc (Table Cell)

```
Children in order:
1. w:tcPr               [0..1]  — cell properties (must be first)
2. w:p                   [1..*]  — paragraph(s) — at least one required
3. w:tbl                 [0..*]  — nested table(s)
```

---

## w:tcPr (Table Cell Properties)

```
Children in order:
1.  w:cnfStyle           [0..1]
2.  w:tcW                [0..1]  — cell width
3.  w:gridSpan           [0..1]  — horizontal merge (column span)
4.  w:hMerge             [0..1]  — legacy horizontal merge
5.  w:vMerge             [0..1]  — vertical merge
6.  w:tcBorders          [0..1]  — cell borders
7.  w:shd                [0..1]  — cell shading
8.  w:noWrap             [0..1]
9.  w:tcMar              [0..1]  — cell margins
10. w:textDirection      [0..1]
11. w:tcFitText          [0..1]
12. w:vAlign             [0..1]  — vertical alignment
13. w:hideMark           [0..1]
14. w:tcPrChange         [0..1]  — tracked cell property change
```

---

## w:sectPr (Section Properties)

```
Children in order:
1.  w:headerReference    [0..*]  — header references (type: default/first/even)
2.  w:footerReference    [0..*]  — footer references
3.  w:endnotePr          [0..1]
4.  w:footnotePr         [0..1]
5.  w:type               [0..1]  — section break type (nextPage/continuous/evenPage/oddPage)
6.  w:pgSz               [0..1]  — page size
7.  w:pgMar              [0..1]  — page margins
8.  w:paperSrc           [0..1]
9.  w:pgBorders          [0..1]  — page borders
10. w:lnNumType          [0..1]  — line numbering
11. w:pgNumType          [0..1]  — page numbering
12. w:cols               [0..1]  — column definitions
13. w:formProt           [0..1]
14. w:vAlign             [0..1]  — vertical alignment of page
15. w:noEndnote          [0..1]
16. w:titlePg            [0..1]  — different first page header/footer
17. w:textDirection      [0..1]
18. w:bidi               [0..1]
19. w:rtlGutter          [0..1]
20. w:docGrid            [0..1]  — document grid
21. w:sectPrChange       [0..1]  — tracked section property change
```

---

## w:hdr (Header) / w:ftr (Footer)

```
Children (same structure as w:body content):
1. w:p                   [0..*]  — paragraph(s)
2. w:tbl                 [0..*]  — table(s)
3. w:sdt                 [0..*]  — content controls
```

Headers and footers are essentially mini-documents. They follow the same content model as `w:body` but without a final `w:sectPr`.
