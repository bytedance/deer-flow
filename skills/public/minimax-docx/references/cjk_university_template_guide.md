# Chinese University Thesis Template Guide (中国高校论文模板指南)

## Why This Guide Exists

Chinese university thesis templates (.docx) have structural patterns that differ significantly
from Western templates. Agents that assume Western conventions (Heading1/Heading2/Normal) will
fail repeatedly. This guide documents the ACTUAL patterns found in Chinese templates.

## Common StyleId Patterns

### Pattern A: Numeric IDs (most common in Chinese Word templates)

| Style Purpose | styleId | w:name | w:basedOn |
|--------------|---------|--------|-----------|
| Normal body | `a` | "Normal" | — |
| Default paragraph font | `a0` | "Default Paragraph Font" | — |
| Heading 1 (章标题) | `1` | "heading 1" | `a` |
| Heading 2 (节标题) | `2` | "heading 2" | `a` |
| Heading 3 (小节标题) | `3` | "heading 3" | `a` |
| TOC 1 | `11` | "toc 1" | `a` |
| TOC 2 | `21` | "toc 2" | `a` |
| TOC 3 | `31` | "toc 3" | `a` |
| Header | `a3` | "header" | `a` |
| Footer | `a4` | "footer" | `a` |
| Table of Contents heading | `10` | "TOC Heading" | `1` |

### Pattern B: English IDs (less common, usually from international templates)
Standard Heading1/Heading2/Heading3/Normal — these follow the Western pattern.

### Pattern C: Mixed (some Chinese, some English)
Some templates define custom styles with Chinese names:
| Style Purpose | styleId | w:name |
|--------------|---------|--------|
| 论文标题 | `lunwenbiaoti` | "论文标题" |
| 章标题 | `zhangbiaoti` | "章标题" |
| 正文 | `zhengwen` | "正文" |

### How to Identify Which Pattern

```bash
# Extract all styleIds from the template
$CLI analyze --input template.docx --styles-only

# Or manually:
# unzip template.docx word/styles.xml
# Search for w:styleId= in the extracted file
```

Look at the first few styleIds. If you see `1`, `2`, `3`, `a`, `a0` → Pattern A.
If you see `Heading1`, `Normal` → Pattern B.

## Standard Thesis Structure

Chinese university theses follow a highly standardized structure:

```
┌─────────────────────────────────────┐
│ 封面 (Cover Page)                    │  ← Usually 1-2 pages
│   - 校名、校徽                       │
│   - 论文题目 (title)                  │
│   - 作者、导师、院系、日期             │
├─────────────────────────────────────┤
│ 学术诚信承诺书 / 独创性声明            │  ← 1 page
│   (Academic Integrity Declaration)   │
├─────────────────────────────────────┤
│ 中文摘要 (Chinese Abstract)          │  ← 1-2 pages
│   - "摘 要" heading                  │
│   - Abstract body                    │
│   - "关键词：" line                  │
├─────────────────────────────────────┤
│ 英文摘要 (English Abstract)          │  ← 1-2 pages
│   - "ABSTRACT" heading              │
│   - Abstract body                    │
│   - "Keywords:" line                 │
├─────────────────────────────────────┤
│ 目录 (Table of Contents)             │  ← 1-3 pages
│   - Often inside SDT block           │
│   - Static example entries           │
│   - TOC field code                   │
├─────────────────────────────────────┤
│ 正文 (Body)                          │  ← Main content
│   第1章 绪论                          │
│   1.1 研究背景                        │
│   1.2 研究目的和意义                   │
│   第2章 文献综述                       │
│   ...                                │
│   第N章 结论与展望                     │
├─────────────────────────────────────┤
│ 参考文献 (References)                │  ← Styled differently
├─────────────────────────────────────┤
│ 致谢 (Acknowledgments)              │  ← Optional
├─────────────────────────────────────┤
│ 附录 (Appendices)                    │  ← Optional
└─────────────────────────────────────┘
```

## Identifying Zone Boundaries in Templates

Templates contain EXAMPLE content that must be replaced. Here's how to find the zones:

### Zone A (Front matter) — KEEP from template
- Starts at: paragraph 0
- Ends at: the paragraph BEFORE the first chapter heading
- Contains: cover, declaration, abstracts, TOC
- How to detect end: search for first paragraph with style `1` (or Heading1) containing "第1章" or "绪论"

### Zone B (Body content) — REPLACE with user content
- Starts at: first chapter heading ("第1章...")
- Ends at: "参考文献" heading (inclusive) or last body paragraph before acknowledgments
- How to detect:
  ```python
  for i, el in enumerate(body_elements):
      text = get_text(el)
      style = get_style(el)
      if style in ('1', 'Heading1') and ('第1章' in text or '绪论' in text):
          zone_b_start = i
      if '参考文献' in text:
          zone_b_end = i
  ```

### Zone C (Back matter) — KEEP from template (or remove)
- Starts after: 参考文献
- Contains: 致谢, 附录, final sectPr

## Font Expectations in Chinese Thesis Templates

| Element | Font | Size (字号) | Size (pt) | w:sz |
|---------|------|------------|-----------|------|
| 论文标题 | 华文中宋 or 黑体 | 二号 or 小二 | 22pt or 18pt | 44 or 36 |
| 章标题 (H1) | 黑体 | 三号 | 16pt | 32 |
| 节标题 (H2) | 黑体 | 四号 | 14pt | 28 |
| 小节标题 (H3) | 黑体 | 小四 | 12pt | 24 |
| 正文 | 宋体 | 小四 | 12pt | 24 |
| 页眉 | 宋体 | 五号 | 10.5pt | 21 |
| 页脚/页码 | 宋体 | 五号 | 10.5pt | 21 |
| 表格内容 | 宋体 | 五号 | 10.5pt | 21 |
| 参考文献条目 | 宋体 | 五号 | 10.5pt | 21 |

## RunFonts for CJK Body Text

```xml
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"
          w:eastAsia="宋体" w:cs="Times New Roman"/>
```

For headings:
```xml
<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"
          w:eastAsia="黑体" w:cs="Times New Roman"/>
```

IMPORTANT: When cleaning direct formatting, ALWAYS preserve w:eastAsia.
Removing it causes Chinese text to fall back to the wrong font.

## Common Mistakes with Chinese Templates

1. **Searching for `Heading1`** — Chinese templates use `1`, not `Heading1`
2. **Clearing all rFonts** — Must keep eastAsia font declarations
3. **Assuming "第1章" is the first paragraph** — It's typically paragraph 100+ after cover/abstract/TOC
4. **Ignoring SDT blocks in TOC** — The TOC is wrapped in an SDT, not just field codes
5. **Wrong line spacing** — Chinese theses typically use fixed 20pt (line="400") or 22pt (line="440"), not the 28pt used in government documents
6. **Missing section breaks** — Each zone (abstract, TOC, body) usually has its own sectPr for different headers/footers

## Style Mapping Quick Reference

When source document uses Western IDs and template uses Chinese numeric IDs:

```json
{
  "Heading1": "1",
  "Heading2": "2",
  "Heading3": "3",
  "Heading4": "3",
  "Normal": "a",
  "BodyText": "a",
  "ListParagraph": "a",
  "Caption": "a",
  "TOC1": "11",
  "TOC2": "21",
  "TOC3": "31"
}
```

When source uses Chinese numeric IDs and template uses Western IDs — reverse the mapping.
