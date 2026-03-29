# CJK Typography & Mixed-Script Guide

Rules for Chinese, Japanese, and Korean text in DOCX documents.

## Table of Contents

1. [Font Selection](#font-selection)
2. [Font Size Names (CJK)](#font-size-names)
3. [RunFonts Mapping](#runfonts-mapping)
4. [Punctuation & Line Breaking](#punctuation--line-breaking)
5. [Paragraph Indentation](#paragraph-indentation)
6. [Line Spacing for CJK](#line-spacing)
7. [Chinese Government Standard (GB/T 9704)](#gbt-9704)
8. [Mixed CJK + Latin Best Practices](#mixed-script)
9. [OpenXML Quick Reference](#openxml-quick-reference)

---

## Font Selection

### Recommended CJK Fonts

| Language | Serif (正文) | Sans (标题) | Notes |
|----------|-------------|-------------|-------|
| **Simplified Chinese** | 宋体 (SimSun) | 微软雅黑 (Microsoft YaHei) | YaHei for screen, SimSun for print |
| **Simplified Chinese** | 仿宋 (FangSong) | 黑体 (SimHei) | Government documents |
| **Traditional Chinese** | 新細明體 (PMingLiU) | 微軟正黑體 (Microsoft JhengHei) | Taiwan standard |
| **Japanese** | MS 明朝 (MS Mincho) | MS ゴシック (MS Gothic) | Classic pairing |
| **Japanese** | 游明朝 (Yu Mincho) | 游ゴシック (Yu Gothic) | Modern, Windows 10+ |
| **Korean** | 바탕 (Batang) | 맑은 고딕 (Malgun Gothic) | Standard pairing |

### Government Document Fonts (公文)

| Element | Font | Size |
|---------|------|------|
| 标题 (title) | 小标宋 (FZXiaoBiaoSong-B05S) | 二号 (22pt) |
| 一级标题 | 黑体 (SimHei) | 三号 (16pt) |
| 二级标题 | 楷体_GB2312 (KaiTi_GB2312) | 三号 (16pt) |
| 三级标题 | 仿宋_GB2312 加粗 | 三号 (16pt) |
| 正文 (body) | 仿宋_GB2312 (FangSong_GB2312) | 三号 (16pt) |
| 附注/页码 | 宋体 (SimSun) | 四号 (14pt) |

---

## Font Size Names

CJK uses named sizes. Map to points and `w:sz` half-point values:

| 字号 | Points | `w:sz` | Common Use |
|------|--------|--------|------------|
| 初号 | 42pt | 84 | Display title |
| 小初 | 36pt | 72 | Large title |
| 一号 | 26pt | 52 | Chapter heading |
| 小一 | 24pt | 48 | Major heading |
| 二号 | 22pt | 44 | Document title (公文) |
| 小二 | 18pt | 36 | Western H1 equivalent |
| 三号 | 16pt | 32 | CJK heading / 公文 body |
| 小三 | 15pt | 30 | Sub-heading |
| 四号 | 14pt | 28 | CJK subheading |
| 小四 | 12pt | 24 | Standard body (CJK) |
| 五号 | 10.5pt | 21 | Compact CJK body |
| 小五 | 9pt | 18 | Footnotes |
| 六号 | 7.5pt | 15 | Fine print |

---

## RunFonts Mapping

OpenXML uses four font slots to handle multilingual text:

```xml
<w:rFonts
  w:ascii="Calibri"        <!-- Latin characters (U+0000–U+007F) -->
  w:hAnsi="Calibri"        <!-- Latin extended, Greek, Cyrillic -->
  w:eastAsia="SimSun"      <!-- CJK Unified Ideographs, Kana, Hangul -->
  w:cs="Arial"             <!-- Arabic, Hebrew, Thai, Devanagari -->
/>
```

**Word's character classification logic:**

1. Character is in CJK range → uses `w:eastAsia` font
2. Character is in complex script range → uses `w:cs` font
3. Character is basic Latin (ASCII) → uses `w:ascii` font
4. Everything else → uses `w:hAnsi` font

**Key**: `w:eastAsia` is the **only** way to set CJK fonts. Setting just `w:ascii` will NOT affect CJK characters. Mixed text within a single run auto-switches fonts at the character level — no need for separate runs.

### Document Defaults

```xml
<w:docDefaults>
  <w:rPrDefault>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="SimSun" w:cs="Arial" />
      <w:sz w:val="22" />
      <w:szCs w:val="22" />
      <w:lang w:val="en-US" w:eastAsia="zh-CN" />
    </w:rPr>
  </w:rPrDefault>
</w:docDefaults>
```

`w:lang w:eastAsia` helps Word resolve ambiguous characters (e.g., punctuation shared between CJK and Latin).

---

## Punctuation & Line Breaking

### Full-Width vs Half-Width

CJK text uses full-width punctuation:

| Type | CJK | Latin |
|------|-----|-------|
| Period | 。(U+3002) | . |
| Comma | ，(U+FF0C) 、(U+3001) | , |
| Colon | ：(U+FF1A) | : |
| Semicolon | ；(U+FF1B) | ; |
| Quotes | 「」『』 or ""'' | "" '' |
| Parentheses | （）(U+FF08/09) | () |

In mixed text, use the punctuation style of the **surrounding language context**.

### OpenXML Controls

```xml
<w:pPr>
  <w:adjustRightInd w:val="true" />   <!-- Adjust right indent for CJK punctuation -->
  <w:snapToGrid w:val="true" />        <!-- Align to document grid -->
  <w:kinsoku w:val="true" />           <!-- Enable CJK line breaking rules -->
  <w:overflowPunct w:val="true" />     <!-- Allow punctuation to overflow margins -->
</w:pPr>
```

### Kinsoku Rules (禁則処理)

Prevents certain characters from appearing at the start or end of a line:
- **Cannot start a line**: `）」』】〉》。、，！？；：` and closing brackets
- **Cannot end a line**: `（「『【〈《` and opening brackets

Word applies these automatically when `w:kinsoku` is enabled.

### Line Breaking

- CJK characters can break between **any two characters** (no word boundaries needed)
- Latin words within CJK text still follow word-boundary breaking
- `w:wordWrap w:val="false"` enables CJK-style breaking (break anywhere)

---

## Paragraph Indentation

### Chinese Standard: 2-Character Indent

Chinese body text conventionally uses a 2-character first-line indent:

```xml
<w:ind w:firstLineChars="200" />  <!-- 200 = 2 characters × 100 -->
```

Preferred over `w:firstLine` with fixed DXA because `firstLineChars` scales with font size.

| Indent | Value |
|--------|-------|
| 1 character | `w:firstLineChars="100"` |
| 2 characters | `w:firstLineChars="200"` |
| 3 characters | `w:firstLineChars="300"` |

---

## Line Spacing

- CJK characters are taller than Latin characters at the same point size
- Default `1.0` line spacing may feel cramped with CJK text
- Recommended: `1.15–1.5` for mixed CJK+Latin, `1.0` with fixed 28pt for 公文

### Auto Spacing

```xml
<w:pPr>
  <w:autoSpaceDE w:val="true"/>  <!-- auto space between CJK and Latin -->
  <w:autoSpaceDN w:val="true"/>  <!-- auto space between CJK and numbers -->
</w:pPr>
```

Adds ~¼ em spacing between CJK and non-CJK characters automatically. **Recommended: always enable.**

---

## GB/T 9704

Chinese government document standard (党政机关公文格式). These are **strict requirements**, not suggestions.

### Page Setup

| Parameter | Value | OpenXML |
|-----------|-------|---------|
| Page size | A4 (210×297mm) | Width=11906, Height=16838 |
| Top margin | 37mm | 2098 DXA |
| Bottom margin | 35mm | 1984 DXA |
| Left margin | 28mm | 1588 DXA |
| Right margin | 26mm | 1474 DXA |
| Characters/line | 28 | |
| Lines/page | 22 | |
| Line spacing | Fixed 28pt | `line="560"` lineRule="exact" |

### Document Structure

```
┌─────────────────────────────────┐
│     发文机关标志 (红头)           │  ← 小标宋 or 红色大字
│     ══════════════════ (红线)    │  ← Red #FF0000, 2pt
├─────────────────────────────────┤
│  发文字号: X机发〔2025〕X号      │  ← 仿宋 三号, centered
│                                 │
│  标题 (Title)                   │  ← 小标宋 二号, centered
│                                 │     可分多行，回行居中
│  主送机关:                      │  ← 仿宋 三号
│                                 │
│  正文 (Body)...                 │  ← 仿宋_GB2312 三号
│  一、一级标题                    │  ← 黑体 三号
│  （一）二级标题                  │  ← 楷体 三号
│  1. 三级标题                    │  ← 仿宋 三号 加粗
│  (1) 四级标题                   │  ← 仿宋 三号
│                                 │
│  附件: 1. xxx                   │  ← 仿宋 三号
│                                 │
│  发文机关署名                    │  ← 仿宋 三号
│  成文日期                       │  ← 仿宋 三号, 小写中文数字
├─────────────────────────────────┤
│  ══════════════════ (版记线)     │
│  抄送: xxx                      │  ← 仿宋 四号
│  印发机关及日期                   │  ← 仿宋 四号
└─────────────────────────────────┘
```

### Numbering System

```
一、        ← 黑体 (SimHei), no indentation
（一）      ← 楷体 (KaiTi), indented 2 chars
1.          ← 仿宋加粗 (FangSong Bold), indented 2 chars
(1)         ← 仿宋 (FangSong), indented 2 chars
```

### Colors

| Element | Color | Requirement |
|---------|-------|-------------|
| All body text | Black #000000 | Mandatory |
| 红头 (agency name) | Red #FF0000 | Mandatory |
| 红线 (separator) | Red #FF0000 | Mandatory |
| 公章 (official seal) | Red | Mandatory |

### Page Numbers

- Position: bottom center
- Format: `-X-` (dash-number-dash)
- Font: 宋体 四号 (SimSun 14pt, `sz="28"`)
- No page number on cover page if present

---

## Mixed Script

### Font Size Harmony

CJK characters appear larger than Latin characters at the same point size. Compensation:

- If body is Calibri 11pt, pair with CJK at 11pt (same size — CJK looks slightly larger but acceptable)
- If precise visual match needed, CJK can be set 0.5–1pt smaller
- In practice, same point size is standard — don't over-optimize

### Bold and Italic

- **Chinese/Japanese have no true italic.** Word synthesizes a slant which looks poor
- Use **bold** for emphasis in CJK text
- Use 着重号 (emphasis dots) for traditional emphasis: `<w:em w:val="dot"/>` on RunProperties

---

## OpenXML Quick Reference

### Set EastAsia Font (C#)

```csharp
new Run(
    new RunProperties(
        new RunFonts { EastAsia = "SimSun", Ascii = "Calibri", HighAnsi = "Calibri" },
        new FontSize { Val = "32" }  // 三号 = 16pt = sz 32
    ),
    new Text("这是正文内容")
);
```

### Document Defaults (C#)

```csharp
new DocDefaults(new RunPropertiesDefault(new RunPropertiesBaseStyle(
    new RunFonts {
        Ascii = "Calibri", HighAnsi = "Calibri",
        EastAsia = "Microsoft YaHei"
    },
    new Languages { Val = "en-US", EastAsia = "zh-CN" }
)));
```

### 公文 Style Definitions (C#)

```csharp
// Title style — 小标宋 二号 centered
new Style(
    new StyleName { Val = "GongWen Title" },
    new BasedOn { Val = "Normal" },
    new StyleRunProperties(
        new RunFonts { EastAsia = "FZXiaoBiaoSong-B05S" },
        new FontSize { Val = "44" },  // 二号 = 22pt
        new Bold()
    ),
    new StyleParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Line = "560", LineRule = LineSpacingRuleValues.Exact }
    )
) { Type = StyleValues.Paragraph, StyleId = "GongWenTitle" };

// Body style — 仿宋_GB2312 三号
new Style(
    new StyleName { Val = "GongWen Body" },
    new StyleRunProperties(
        new RunFonts { EastAsia = "FangSong_GB2312", Ascii = "FangSong_GB2312" },
        new FontSize { Val = "32" }  // 三号 = 16pt
    ),
    new StyleParagraphProperties(
        new SpacingBetweenLines { Line = "560", LineRule = LineSpacingRuleValues.Exact }
    )
) { Type = StyleValues.Paragraph, StyleId = "GongWenBody" };
```

### Emphasis Dots (着重号)

```csharp
new RunProperties(new Emphasis { Val = EmphasisMarkValues.Dot });
```

### East Asian Text Layout

```xml
<!-- Snap to grid (align CJK chars to character grid) -->
<w:snapToGrid w:val="true"/>

<!-- Two-lines-in-one (双行合一) -->
<w:eastAsianLayout w:id="1" w:combine="true"/>

<!-- Vertical text in a cell -->
<w:textDirection w:val="tbRl"/>
```
