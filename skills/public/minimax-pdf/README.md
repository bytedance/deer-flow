# minimax-pdf

A Claude skill for creating and editing visually polished PDFs.  
Three routes. One design system. Tokens flow from content analysis through every renderer.

## Quick start

```bash
bash scripts/make.sh check   # verify deps
bash scripts/make.sh fix     # auto-install missing deps
bash scripts/make.sh demo    # → demo.pdf
```

---

## Route A: CREATE — generate a new PDF

```bash
bash scripts/make.sh run \
  --title   "Q3 Strategy Review" \
  --type    "proposal" \
  --author  "Strategy Team" \
  --date    "October 2025" \
  --content content.json \
  --out     report.pdf
```

**`--type` options:**

| Type | Palette | Cover pattern | Google Fonts (cover) |
|---|---|---|---|
| `report` | Deep ink, teal accent | `fullbleed` | Playfair Display / IBM Plex Sans |
| `proposal` | Near-black, amber accent | `split` | Syne / Nunito Sans |
| `resume` | White, navy accent | `typographic` | DM Serif Display / DM Sans |
| `portfolio` | Deep violet, coral accent | `atmospheric` | Fraunces / Inter |
| `academic` | Warm white, navy accent | `typographic` | EB Garamond / Source Sans 3 |
| `general` | Dark slate, blue accent | `fullbleed` | Outfit / Outfit |
| `minimal` | Near-white, red accent | `minimal` | Cormorant Garamond / Jost |
| `stripe` | Dark navy, amber accent | `stripe` | Barlow Condensed / Barlow |
| `diagonal` | Dark blue, teal accent | `diagonal` | Montserrat / Montserrat |
| `frame` | Warm cream, brown accent | `frame` | Cormorant / Crimson Pro |
| `editorial` | White, red accent | `editorial` | Bebas Neue / Libre Franklin |
| `magazine` | Warm linen, deep navy accent | `magazine` | Playfair Display / EB Garamond |
| `darkroom` | Deep navy, steel blue accent | `darkroom` | Playfair Display / EB Garamond |
| `terminal` | Near-black, neon green accent | `terminal` | Space Mono |
| `poster` | White, near-black accent | `poster` | Barlow Condensed / Courier Prime |

**content.json block types:**

```json
[
  {"type": "h1",      "text": "Section Title"},
  {"type": "h2",      "text": "Subsection"},
  {"type": "h3",      "text": "Sub-subsection"},
  {"type": "body",    "text": "Paragraph. Supports <b>bold</b> and <i>italic</i>."},
  {"type": "bullet",  "text": "Unordered list item"},
  {"type": "numbered","text": "Ordered list item — counter auto-resets between lists"},
  {"type": "callout", "text": "Key insight or highlighted finding"},
  {"type": "table",
    "headers": ["Col A", "Col B"],
    "rows":    [["a", "b"], ["c", "d"]]
  },
  {"type": "image",   "path": "chart.png", "caption": "Figure 1: optional caption"},
  {"type": "code",    "text": "def hello():\n    print('world')"},
  {"type": "math",    "text": "\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}", "label": "(1)"},
  {"type": "divider"},
  {"type": "caption", "text": "Table 1: standalone caption label"},
  {"type": "pagebreak"},
  {"type": "spacer",  "pt": 16}
]
```

---

## Route B: FILL — fill form fields in an existing PDF

```bash
# See what fields the PDF has
bash scripts/make.sh fill --input form.pdf --inspect

# Fill fields
bash scripts/make.sh fill \
  --input  form.pdf \
  --out    filled.pdf \
  --values '{"FirstName": "Jane", "Agree": "true", "Country": "US"}'

# Or from a JSON file
bash scripts/make.sh fill --input form.pdf --out filled.pdf --data values.json
```

Field value rules:
- `text` → any string
- `checkbox` → `"true"` or `"false"`
- `dropdown` → must match a choice value shown by `--inspect`
- `radio` → must match a radio value shown by `--inspect`

---

## Route C: REFORMAT — apply design to an existing document

```bash
bash scripts/make.sh reformat \
  --input  source.md \
  --title  "Annual Report" \
  --type   "report" \
  --author "Research Team" \
  --out    output.pdf
```

Supported input: `.md` `.txt` `.pdf` `.json`

---

## Architecture

```
SKILL.md                      ← Claude entry point, route table
design/design.md              ← Aesthetic system (read before CREATE/REFORMAT)
scripts/
  make.sh                     ← Unified CLI
  palette.py                  ← metadata → tokens.json       [CREATE, REFORMAT]
  cover.py                    ← tokens.json → cover.html     [CREATE, REFORMAT]
  render_cover.js             ← cover.html → cover.pdf       [CREATE, REFORMAT]
  render_body.py              ← tokens + content → body.pdf  [CREATE, REFORMAT]
  merge.py                    ← cover + body → final.pdf     [CREATE, REFORMAT]
  fill_inspect.py             ← PDF → field list             [FILL]
  fill_write.py               ← PDF + values → filled PDF    [FILL]
  reformat_parse.py           ← doc → content.json           [REFORMAT]
```

Design tokens (`tokens.json`) flow from `palette.py` to every renderer — cover and body are always visually consistent.

## Dependencies

| Tool | Used by | Install |
|---|---|---|
| Python 3.9+ | all `.py` scripts | system |
| `reportlab` | `render_body.py` | `pip install reportlab` |
| `pypdf` | fill, merge, reformat | `pip install pypdf` |
| Node.js 18+ | `render_cover.js` | system |
| `playwright` + Chromium | `render_cover.js` | `npm install -g playwright && npx playwright install chromium` |

## License

MIT

## Document types

| `--type` | Mood | Cover pattern | Cover fonts |
|---|---|---|---|
| `report` | Authoritative | `fullbleed` | Playfair Display / IBM Plex Sans |
| `proposal` | Confident | `split` | Syne / Nunito Sans |
| `resume` | Clean | `typographic` | DM Serif Display / DM Sans |
| `portfolio` | Expressive | `atmospheric` | Fraunces / Inter |
| `academic` | Scholarly | `typographic` | EB Garamond / Source Sans 3 |
| `general` | Neutral | `fullbleed` | Outfit |
| `minimal` | Restrained | `minimal` | Cormorant Garamond / Jost |
| `stripe` | Bold | `stripe` | Barlow Condensed / Barlow |
| `diagonal` | Dynamic | `diagonal` | Montserrat |
| `frame` | Classical | `frame` | Cormorant / Crimson Pro |
| `editorial` | Editorial | `editorial` | Bebas Neue / Libre Franklin |

Cover fonts load via Google Fonts `@import` at render time — no local caching.
Body pages always use system fonts (Times / Helvetica) via ReportLab.

## content.json schema

```json
[
  {"type": "h1",      "text": "Section Title"},
  {"type": "h2",      "text": "Subsection"},
  {"type": "h3",      "text": "Sub-subsection"},
  {"type": "body",    "text": "Paragraph text. Supports <b>bold</b> and <i>italic</i>."},
  {"type": "bullet",  "text": "Unordered list item"},
  {"type": "numbered","text": "Ordered list item — auto-numbered, counter resets between lists"},
  {"type": "callout", "text": "Highlighted insight or key finding"},
  {"type": "table",
    "headers": ["Column A", "Column B", "Column C"],
    "rows":    [["row1a", "row1b", "row1c"], ["row2a", "row2b", "row2c"]]
  },
  {"type": "image",   "path": "chart.png", "caption": "Figure 1: Sales by quarter"},
  {"type": "code",    "text": "SELECT * FROM users\nWHERE active = 1;"},
  {"type": "math",    "text": "\\sigma = \\sqrt{\\frac{1}{N}\\sum_{i=1}^N (x_i - \\mu)^2}", "label": "(2)"},
  {"type": "divider"},
  {"type": "caption", "text": "Table 2: standalone label"},
  {"type": "pagebreak"},
  {"type": "spacer",  "pt": 16}
]
```

## Architecture

```
SKILL.md                  ← Claude entry point, routing only
design/design.md          ← Aesthetic system (read before any script)
scripts/
  make.sh                 ← Unified CLI: check / fix / run / demo
  palette.py              ← content metadata → tokens.json
  cover.py                ← tokens.json → cover.html
  render_cover.js         ← cover.html → cover.pdf  (Playwright)
  render_body.py          ← tokens.json + content.json → body.pdf  (ReportLab)
  merge.py                ← cover.pdf + body.pdf → final.pdf + QA report
```

Design tokens (color, typography, spacing) are written once by `palette.py` and consumed by every downstream script. This guarantees visual consistency between cover and body without any manual coordination.

## Dependencies

| Tool | Purpose | Install |
|---|---|---|
| Python 3.9+ | palette, cover, render_body, merge | system |
| `reportlab` | Body page rendering | `pip install reportlab` |
| `pypdf` | Merging PDFs | `pip install pypdf` |
| Node.js 18+ | Cover rendering | system |
| `playwright` | Headless Chromium for cover | `npm install -g playwright && npx playwright install chromium` |

Run `bash scripts/make.sh check` to verify everything at once.  
Run `bash scripts/make.sh fix` to auto-install what is missing.

## License

MIT
