# XSD Validation Guide

## Running Validation

```bash
# Validate against the WML subset schema
dotnet run --project minimax-docx validate input.docx --xsd assets/xsd/wml-subset.xsd

# Validate against business rules (REQUIRED for Scenario C gate-check)
dotnet run --project minimax-docx validate input.docx --xsd assets/xsd/business-rules.xsd

# Validate against both
dotnet run --project minimax-docx validate input.docx --xsd assets/xsd/wml-subset.xsd --xsd assets/xsd/business-rules.xsd
```

---

## What wml-subset.xsd Covers

The subset schema validates the most common WordprocessingML elements:

| Area | Elements Validated |
|------|--------------------|
| Document structure | `w:document`, `w:body`, `w:sectPr` |
| Paragraphs | `w:p`, `w:pPr`, `w:r`, `w:rPr`, `w:t` |
| Tables | `w:tbl`, `w:tblPr`, `w:tblGrid`, `w:tr`, `w:tc` |
| Styles | `w:styles`, `w:style`, `w:docDefaults` |
| Lists | `w:numbering`, `w:abstractNum`, `w:num` |
| Headers/Footers | `w:hdr`, `w:ftr` |
| Track Changes | `w:ins`, `w:del`, `w:rPrChange`, `w:pPrChange` |
| Comments | `w:comment`, `w:commentRangeStart`, `w:commentRangeEnd` |

### What It Does NOT Cover

- DrawingML elements (`a:`, `pic:`, `wp:`) — image/shape internals
- VML elements (`v:`, `o:`) — legacy shapes
- Math elements (`m:`) — equations
- Extended namespaces (`w14`, `w15`, `w16*`) — vendor extensions
- Custom XML data parts
- Relationship and content type validation (structural, not schema-based)

---

## Interpreting Errors

### Element Ordering Error

```
ERROR: Element 'w:jc' is not expected at this position.
Expected: w:spacing, w:ind, w:contextualSpacing, ...
Location: /word/document.xml, line 45
```

**Cause**: Child elements are in wrong order. See `references/openxml_element_order.md`.
**Fix**: Reorder children to match schema sequence.

### Missing Required Element

```
ERROR: Element 'w:tbl' missing required child 'w:tblPr'.
Location: /word/document.xml, line 102
```

**Cause**: A required child element is absent.
**Fix**: Add the missing element. Tables require both `w:tblPr` and `w:tblGrid`.

### Invalid Attribute Value

```
ERROR: Attribute 'w:val' has invalid value 'middle'.
Expected: 'left', 'center', 'right', 'both', 'distribute'
Location: /word/document.xml, line 78
```

**Cause**: An attribute value is not in the allowed enumeration.
**Fix**: Use one of the valid values listed in the error.

### Unexpected Element

```
ERROR: Element 'w:customTag' is not expected.
Location: /word/document.xml, line 200
```

**Cause**: An element not defined in the subset schema. May be a vendor extension.
**Fix**: Check if it's a known extension (w14/w15/w16). If so, it's likely safe. If unknown, investigate or remove.

---

## Business Rules XSD

The `business-rules.xsd` schema enforces project-specific constraints beyond standard OpenXML validity:

| Rule | What It Checks |
|------|---------------|
| Required styles | `Normal`, `Heading1`-`Heading3`, `TableGrid` must exist in `styles.xml` |
| Font consistency | `w:docDefaults` fonts match expected values |
| Margin ranges | Page margins within acceptable range (720-2160 DXA) |
| Page size | Must be A4 or Letter |
| Heading hierarchy | No gaps (e.g., H1 → H3 without H2) |
| Style chain | `w:basedOn` references must resolve to existing styles |

### Extending Business Rules

To add project-specific rules, add `xs:assert` or `xs:restriction` elements:

```xml
<!-- Require minimum 1-inch margins -->
<xs:element name="pgMar">
  <xs:complexType>
    <xs:attribute name="top" type="xs:integer">
      <xs:restriction>
        <xs:minInclusive value="1440" />
      </xs:restriction>
    </xs:attribute>
  </xs:complexType>
</xs:element>
```

---

## Gate-Check: Scenario C Hard Gate

In Scenario C (Apply Template), the output document **MUST** pass `business-rules.xsd` validation before delivery:

```
1. Apply template  →  output.docx
2. Validate        →  dotnet run ... validate output.docx --xsd business-rules.xsd
3. PASS?           →  Deliver to user
4. FAIL?           →  Fix issues, re-validate, repeat until PASS
```

**This is a hard gate.** A document that fails business-rules validation is NOT deliverable, even if it opens correctly in Word.

---

## False Positives

### Vendor Extensions

Elements from extended namespaces (`w14`, `w15`, `w16*`) are not in the subset schema and may trigger warnings:

```
WARNING: Element '{http://schemas.microsoft.com/office/word/2010/wordml}shadow' is not expected.
```

These are generally safe to ignore — they are Microsoft extensions for newer features (e.g., advanced text effects, comment extensions).

### Markup Compatibility

Documents may contain `mc:AlternateContent` blocks with fallback content. The subset schema may not recognize the `mc:` namespace processing. These are safe if the document opens correctly in Word.

### Recommended Approach

1. Run validation
2. Treat **errors** as must-fix
3. Review **warnings** — ignore known vendor extensions, investigate unknown elements
4. After fixing errors, re-validate to confirm
