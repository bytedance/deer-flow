#!/usr/bin/env bash
# make.sh — minimax-pdf unified CLI
# Usage: bash make.sh <command> [options]
#
# Commands:
#   check                          Verify all dependencies
#   fix                            Auto-install missing dependencies
#   run   --title T --type TYPE    Full pipeline → output.pdf
#         --out FILE               Output path (default: output.pdf)
#         --author A --date D
#         --subtitle S
#         --abstract A             Optional abstract text for cover
#         --cover-image URL        Optional cover image URL/path
#         --content FILE           Path to content.json (optional)
#   demo                           Build a full-featured demo to demo.pdf
#
# Document types:
#   report proposal resume portfolio academic general
#   minimal stripe diagonal frame editorial
#   magazine darkroom terminal poster
#
# Content block types:
#   h1 h2 h3 body bullet numbered callout table
#   image figure code math chart flowchart bibliography
#   divider caption pagebreak spacer
#
# Exit codes: 0 success, 1 usage error, 2 dep missing, 3 runtime error

set -euo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="python3"
NODE="node"

# ── Colour helpers ─────────────────────────────────────────────────────────────
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

# ── check ──────────────────────────────────────────────────────────────────────
cmd_check() {
  local ok=true
  bold "Checking dependencies..."

  # Python
  if command -v python3 &>/dev/null; then
    green "  ✓ python3 $(python3 --version 2>&1 | awk '{print $2}')"
  else
    red   "  ✗ python3 not found"
    ok=false
  fi

  # reportlab
  if python3 -c "import reportlab" 2>/dev/null; then
    green "  ✓ reportlab"
  else
    yellow "  ⚠ reportlab not installed  (run: make.sh fix)"
    ok=false
  fi

  # pypdf
  if python3 -c "import pypdf" 2>/dev/null; then
    green "  ✓ pypdf"
  else
    yellow "  ⚠ pypdf not installed  (run: make.sh fix)"
    ok=false
  fi

  # Node.js
  if command -v node &>/dev/null; then
    green "  ✓ node $(node --version)"
  else
    red   "  ✗ node not found — cover rendering unavailable"
    ok=false
  fi

  # Playwright
  if node -e "require('playwright')" 2>/dev/null || \
     node -e "require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright')" 2>/dev/null; then
    green "  ✓ playwright"
  else
    yellow "  ⚠ playwright not found  (run: make.sh fix)"
    ok=false
  fi

  # matplotlib (optional — required for math/chart/flowchart; degrades gracefully)
  if python3 -c "import matplotlib" 2>/dev/null; then
    green "  ✓ matplotlib (math, chart, flowchart blocks enabled)"
  else
    yellow "  ⚠ matplotlib not installed — math/chart/flowchart blocks degrade to text  (run: make.sh fix)"
  fi

  if $ok; then
    green "\nAll dependencies satisfied."
    exit 0
  else
    yellow "\nSome dependencies missing. Run: bash make.sh fix"
    exit 2
  fi
}

# ── fix ────────────────────────────────────────────────────────────────────────
cmd_fix() {
  bold "Installing missing dependencies..."
  local rc=0

  # Python packages
  if command -v python3 &>/dev/null; then
    python3 -m pip install --break-system-packages -q reportlab pypdf matplotlib 2>/dev/null \
      || python3 -m pip install -q reportlab pypdf matplotlib 2>/dev/null \
      || { yellow "  pip install failed — try: pip install reportlab pypdf matplotlib"; rc=3; }
    green "  ✓ Python packages installed (reportlab, pypdf, matplotlib)"
  fi

  # Playwright
  if command -v npm &>/dev/null; then
    npm install -g playwright --silent 2>/dev/null && \
    npx playwright install chromium --silent 2>/dev/null && \
    green "  ✓ Playwright + Chromium installed" || \
    { yellow "  playwright install failed — try manually"; rc=3; }
  else
    yellow "  npm not found — cannot install Playwright automatically"
    rc=2
  fi

  if [[ $rc -eq 0 ]]; then
    green "\nAll dependencies installed. Run: bash make.sh check"
  fi
  exit $rc
}

# ── run ────────────────────────────────────────────────────────────────────────
cmd_run() {
  local title="Untitled Document"
  local type="general"
  local author=""
  local date=""
  local subtitle=""
  local abstract=""
  local cover_image=""
  local accent=""
  local cover_bg=""
  local content_file=""
  local out="output.pdf"
  local workdir
  workdir="$(mktemp -d)"

  # Parse options
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --title)        title="$2";        shift 2 ;;
      --type)         type="$2";         shift 2 ;;
      --author)       author="$2";       shift 2 ;;
      --date)         date="$2";         shift 2 ;;
      --subtitle)     subtitle="$2";     shift 2 ;;
      --abstract)     abstract="$2";     shift 2 ;;
      --cover-image)  cover_image="$2";  shift 2 ;;
      --accent)       accent="$2";       shift 2 ;;
      --cover-bg)     cover_bg="$2";     shift 2 ;;
      --content)      content_file="$2"; shift 2 ;;
      --out)          out="$2";          shift 2 ;;
      *) echo "Unknown option: $1"; exit 1 ;;
    esac
  done

  bold "Building: $title"
  echo "  Type    : $type"
  echo "  Output  : $out"

  # Step 1: tokens
  echo ""
  bold "Step 1/4  Generating design tokens..."
  local accent_args=()
  [[ -n "$accent"   ]] && accent_args+=(--accent   "$accent")
  [[ -n "$cover_bg" ]] && accent_args+=(--cover-bg "$cover_bg")
  $PY "$SCRIPTS/palette.py" \
    --title "$title" --type "$type" \
    --author "$author" --date "$date" \
    --out "$workdir/tokens.json" \
    "${accent_args[@]+"${accent_args[@]}"}"

  # Inject optional cover fields into tokens.json
  if [[ -n "$abstract" || -n "$cover_image" ]]; then
    PDF_ABSTRACT="$abstract" PDF_COVER_IMAGE="$cover_image" PDF_TOKENS="$workdir/tokens.json" \
    $PY - <<'PYEOF'
import json, os
with open(os.environ["PDF_TOKENS"]) as f:
    t = json.load(f)
abstract = os.environ.get("PDF_ABSTRACT", "")
cover_image = os.environ.get("PDF_COVER_IMAGE", "")
if abstract:
    t["abstract"] = abstract
if cover_image:
    t["cover_image"] = cover_image
with open(os.environ["PDF_TOKENS"], "w") as f:
    json.dump(t, f, indent=2)
PYEOF
  fi

  cat "$workdir/tokens.json" | $PY -c "
import json,sys
t=json.load(sys.stdin)
print(f'  Mood    : {t[\"mood\"]}')
print(f'  Pattern : {t[\"cover_pattern\"]}')
print(f'  Fonts   : {t[\"font_display\"]} / {t[\"font_body\"]}')"

  # Step 2: cover HTML + render
  echo ""
  bold "Step 2/4  Rendering cover..."
  local subtitle_args=()
  [[ -n "$subtitle" ]] && subtitle_args=(--subtitle "$subtitle")
  $PY "$SCRIPTS/cover.py" \
    --tokens "$workdir/tokens.json" \
    --out "$workdir/cover.html" \
    "${subtitle_args[@]+"${subtitle_args[@]}"}"

  $NODE "$SCRIPTS/render_cover.js" \
    --input "$workdir/cover.html" \
    --out   "$workdir/cover.pdf"
  green "  ✓ Cover rendered"

  # Step 3: body
  echo ""
  bold "Step 3/4  Rendering body pages..."
  if [[ -z "$content_file" ]]; then
    # Generate a minimal placeholder body
    cat > "$workdir/content.json" <<'JSON'
[
  {"type":"h1",   "text":"Document Body"},
  {"type":"body", "text":"Replace this with your content.json file using --content path/to/content.json"},
  {"type":"body", "text":"See the content.json schema in the skill README for the full list of supported block types: h1, h2, h3, body, bullet, callout, table, pagebreak, spacer."}
]
JSON
    content_file="$workdir/content.json"
    yellow "  No content file provided — using placeholder body."
  fi

  $PY "$SCRIPTS/render_body.py" \
    --tokens  "$workdir/tokens.json" \
    --content "$content_file" \
    --out     "$workdir/body.pdf"
  green "  ✓ Body rendered"

  # Step 4: merge
  echo ""
  bold "Step 4/4  Merging and QA..."
  $PY "$SCRIPTS/merge.py" \
    --cover "$workdir/cover.pdf" \
    --body  "$workdir/body.pdf" \
    --out   "$out" \
    --title "$title"

  # Cleanup
  rm -rf "$workdir"
}

# ── fill ──────────────────────────────────────────────────────────────────────
cmd_fill() {
  local input="" out="" values="" data_file="" inspect_only=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --input)   input="$2";     shift 2 ;;
      --out)     out="$2";       shift 2 ;;
      --values)  values="$2";    shift 2 ;;
      --data)    data_file="$2"; shift 2 ;;
      --inspect) inspect_only=true; shift ;;
      *) echo "Unknown option: $1"; exit 1 ;;
    esac
  done

  if [[ -z "$input" ]]; then
    echo "Usage: make.sh fill --input form.pdf [--out filled.pdf] [--values '{...}'] [--data values.json] [--inspect]"
    exit 1
  fi

  if $inspect_only || [[ -z "$out" && -z "$values" && -z "$data_file" ]]; then
    bold "Inspecting form fields in: $input"
    $PY "$SCRIPTS/fill_inspect.py" --input "$input"
    return
  fi

  bold "Filling form: $input → $out"

  local val_args=""
  if [[ -n "$values" ]];    then val_args="--values $values"; fi
  if [[ -n "$data_file" ]]; then val_args="--data $data_file"; fi

  $PY "$SCRIPTS/fill_write.py" --input "$input" --out "$out" $val_args
}

# ── reformat ───────────────────────────────────────────────────────────────────
cmd_reformat() {
  local input="" title="Reformatted Document" type="general"
  local author="" date="" out="output.pdf" subtitle=""
  local tmpdir
  tmpdir="$(mktemp -d)"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --input)    input="$2";    shift 2 ;;
      --title)    title="$2";    shift 2 ;;
      --type)     type="$2";     shift 2 ;;
      --author)   author="$2";   shift 2 ;;
      --date)     date="$2";     shift 2 ;;
      --subtitle) subtitle="$2"; shift 2 ;;
      --out)      out="$2";      shift 2 ;;
      *) echo "Unknown option: $1"; exit 1 ;;
    esac
  done

  if [[ -z "$input" ]]; then
    echo "Usage: make.sh reformat --input source.md --title T --type TYPE --out output.pdf"
    exit 1
  fi

  bold "Parsing: $input"
  $PY "$SCRIPTS/reformat_parse.py" --input "$input" --out "$tmpdir/content.json"
  green "  ✓ Parsed to content.json"

  bold "Applying design and building PDF..."
  local sub_args=()
  [[ -n "$subtitle" ]] && sub_args=(--subtitle "$subtitle")

  cmd_run \
    --title "$title" --type "$type" \
    --author "$author" --date "$date" \
    --content "$tmpdir/content.json" \
    --out "$out" \
    "${sub_args[@]+"${sub_args[@]}"}"

  rm -rf "$tmpdir"
}

# ── demo ──────────────────────────────────────────────────────────────────────
cmd_demo() {
  local tmpdir
  tmpdir="$(mktemp -d)"

  cat > "$tmpdir/content.json" <<'JSON'
[
  {"type":"h1",      "text":"Executive Summary"},
  {"type":"body",    "text":"This document was generated by minimax-pdf — a skill for creating visually polished PDFs. Every design decision is rooted in the document type and content, not a generic template."},
  {"type":"callout", "text":"Key insight: design tokens flow from palette.py through every renderer, keeping cover and body visually consistent."},

  {"type":"h1",      "text":"How It Works"},
  {"type":"h2",      "text":"The Token Pipeline"},
  {"type":"body",    "text":"The palette.py script infers a color palette and typography pair from the document type. These tokens are written to tokens.json and consumed by every downstream script."},
  {"type":"numbered","text":"palette.py generates color tokens, font selection, and the cover pattern"},
  {"type":"numbered","text":"cover.py renders the cover HTML using the selected pattern"},
  {"type":"numbered","text":"render_cover.js uses Playwright to convert the HTML cover to PDF"},
  {"type":"numbered","text":"render_body.py builds inner pages from content.json using ReportLab"},
  {"type":"numbered","text":"merge.py combines cover + body and runs final QA checks"},

  {"type":"h2",      "text":"Cover Patterns"},
  {"type":"table",
    "headers": ["Pattern",      "Document type",    "Visual character"],
    "rows": [
      ["fullbleed",   "report, general",   "Deep background · dot-grid texture"],
      ["split",       "proposal",          "Left dark panel · right dot-grid"],
      ["typographic", "resume, academic",  "Oversized display type · first-word accent"],
      ["atmospheric", "portfolio",         "Dark bg · radial glow · dot-grid"],
      ["magazine",    "magazine",          "Cream bg · centered · hero image"],
      ["darkroom",    "darkroom",          "Navy bg · centered · grayscale image"],
      ["terminal",    "terminal",          "Near-black · grid lines · monospace"],
      ["poster",      "poster",            "White · thick sidebar · oversized title"]
    ]
  },

  {"type":"h1",      "text":"Data Visualisation"},
  {"type":"h2",      "text":"Performance Metrics (Chart)"},
  {"type":"body",    "text":"Charts are rendered natively using matplotlib with a color palette derived from the document accent. No external chart services or image files required."},
  {"type":"chart",
    "chart_type": "bar",
    "title":      "Quarterly Performance",
    "labels":     ["Q1", "Q2", "Q3", "Q4"],
    "datasets": [
      {"label": "Revenue",  "values": [120, 145, 132, 178]},
      {"label": "Expenses", "values": [95,  108, 99,  122]}
    ],
    "y_label": "USD (thousands)",
    "caption": "Quarterly revenue vs. expenses"
  },

  {"type":"h2",      "text":"Market Share (Pie Chart)"},
  {"type":"chart",
    "chart_type": "pie",
    "labels":     ["Product A", "Product B", "Product C", "Other"],
    "datasets":   [{"values": [42, 28, 18, 12]}],
    "caption":    "Annual market share by product line"
  },

  {"type":"pagebreak"},

  {"type":"h1",      "text":"Mathematics"},
  {"type":"body",    "text":"Display math is rendered via matplotlib mathtext — no LaTeX binary installation required. Inline references use standard [N] notation in body text."},
  {"type":"math",    "text":"E = mc^2",                              "label":"(1)"},
  {"type":"math",    "text":"\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}", "label":"(2)"},
  {"type":"math",    "text":"\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}", "caption":"Basel problem (Euler, 1734)"},

  {"type":"h1",      "text":"Process Flow"},
  {"type":"body",    "text":"Flowcharts are drawn directly using matplotlib patches — no Graphviz or external tools needed. Supported node shapes: rect, diamond, oval, parallelogram."},
  {"type":"flowchart",
    "nodes": [
      {"id":"start",  "label":"Start",             "shape":"oval"},
      {"id":"input",  "label":"Receive Input",      "shape":"parallelogram"},
      {"id":"valid",  "label":"Valid?",             "shape":"diamond"},
      {"id":"proc",   "label":"Process Data",       "shape":"rect"},
      {"id":"err",    "label":"Return Error",        "shape":"rect"},
      {"id":"out",    "label":"Return Result",       "shape":"parallelogram"},
      {"id":"end",    "label":"End",                "shape":"oval"}
    ],
    "edges": [
      {"from":"start", "to":"input"},
      {"from":"input", "to":"valid"},
      {"from":"valid", "to":"proc",  "label":"Yes"},
      {"from":"valid", "to":"err",   "label":"No"},
      {"from":"proc",  "to":"out"},
      {"from":"err",   "to":"end"},
      {"from":"out",   "to":"end"}
    ],
    "caption": "Data validation and processing flow"
  },

  {"type":"h1",      "text":"Code Example"},
  {"type":"code",    "language":"python",
    "text":"# Design token pipeline\ntokens = palette.build_tokens(\n    title=\"Annual Report\",\n    doc_type=\"report\",\n    author=\"J. Smith\",\n    date=\"March 2026\",\n)\nhtml = cover.render(tokens)\npdf  = render_cover(html)"},

  {"type":"h1",      "text":"Design Principles"},
  {"type":"body",    "text":"The aesthetic system is documented in design/design.md. The core rule: every design decision must be rooted in the document content and purpose. A color chosen because it fits the content will always outperform a color chosen because it seems safe."},
  {"type":"h2",      "text":"Restraint over decoration"},
  {"type":"body",    "text":"The page is done when there is nothing left to remove. Accent color appears on section rules only — not on headings, not on bullets. No card components, no drop shadows."},
  {"type":"callout", "text":"A PDF passes the quality bar when a designer would not be embarrassed to hand it to a client."},

  {"type":"pagebreak"},
  {"type":"bibliography",
    "title": "References",
    "items": [
      {"id":"1","text":"Bringhurst, R. (2004). The Elements of Typographic Style (3rd ed.). Hartley & Marks."},
      {"id":"2","text":"Cairo, A. (2016). The Truthful Art: Data, Charts, and Maps for Communication. New Riders."},
      {"id":"3","text":"Hochuli, J. & Kinross, R. (1996). Designing Books: Practice and Theory. Hyphen Press."}
    ]
  }
]
JSON

  cmd_run \
    --title   "minimax-pdf demo" \
    --type    "report" \
    --author  "minimax-pdf skill" \
    --date    "$(date '+%B %Y')" \
    --subtitle "A demonstration of the token-based design pipeline" \
    --content "$tmpdir/content.json" \
    --out     "demo.pdf"

  rm -rf "$tmpdir"
}

# ── dispatch ───────────────────────────────────────────────────────────────────
main() {
  if [[ $# -lt 1 ]]; then
    bold "minimax-pdf — make.sh"
    echo ""
    echo "Usage: bash make.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  check                             Verify all dependencies"
    echo "  fix                               Auto-install missing deps"
    echo "  run    --title T --type TYPE      CREATE: full pipeline → PDF"
    echo "         [--author A] [--date D] [--subtitle S]"
    echo "         [--abstract A] [--cover-image URL]"
    echo "         [--accent #HEX] [--cover-bg #HEX]"
    echo "         [--content content.json] [--out output.pdf]"
    echo "  fill   --input f.pdf              FILL: inspect or fill form fields"
    echo "  reformat --input doc.md           REFORMAT: parse doc → apply design → PDF"
    echo "  demo                              Build a full-featured demo PDF"
    exit 0
  fi

  case "$1" in
    check)    cmd_check ;;
    fix)      cmd_fix   ;;
    run)      shift; cmd_run      "$@" ;;
    fill)     shift; cmd_fill     "$@" ;;
    reformat) shift; cmd_reformat "$@" ;;
    demo)     cmd_demo  ;;
    *)        echo "Unknown command: $1"; exit 1 ;;
  esac
}

main "$@"
