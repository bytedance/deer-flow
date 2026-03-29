#!/usr/bin/env python3
"""
reformat_parse.py — Convert an existing document into content.json,
then hand off to the CREATE pipeline (render_body.py).

Supported input formats:
  .md / .txt    — Markdown / plain text
  .pdf          — Extract text from existing PDF (layout preserved as best-effort)
  .json         — Pass-through if already content.json format

Usage:
    python3 reformat_parse.py --input doc.md   --out content.json
    python3 reformat_parse.py --input old.pdf  --out content.json
    python3 reformat_parse.py --input data.json --out content.json

Then pipe into the CREATE pipeline:
    python3 render_body.py --tokens tokens.json --content content.json --out body.pdf

Or use make.sh reformat which does both steps:
    bash make.sh reformat --input doc.md --type report --title "My Report" --out output.pdf

Exit codes: 0 success, 1 bad args / unsupported format, 2 dep missing, 3 parse error
"""

import argparse
import json
import os
import re
import sys
import importlib.util
from pathlib import Path




def ensure_deps():
    missing = []
    if importlib.util.find_spec("pypdf") is None:
        missing.append("pypdf")
    if missing:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q"] + missing
        )


ensure_deps()


# ── Markdown / plain text parser ───────────────────────────────────────────────
def parse_markdown(text: str) -> list:
    """
    Convert Markdown to content.json blocks.
    Supports: # headings, **bold**, bullet lists, > blockquotes (→ callout),
    | tables |, plain paragraphs.
    """
    blocks = []
    lines  = text.splitlines()
    i = 0

    def flush_para(buf: list):
        t = " ".join(buf).strip()
        if t:
            blocks.append({"type": "body", "text": _md_inline(t)})

    para_buf = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Blank line — flush paragraph buffer
        if not stripped:
            flush_para(para_buf)
            para_buf = []
            i += 1
            continue

        # ATX Headings: # ## ###
        m = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if m:
            flush_para(para_buf)
            para_buf = []
            level = len(m.group(1))
            htype = {1: "h1", 2: "h2", 3: "h3"}.get(level, "h3")
            blocks.append({"type": htype, "text": _md_inline(m.group(2))})
            i += 1
            continue

        # Display math block: $$expr$$ on one line, or opening $$ ... closing $$
        if stripped.startswith("$$"):
            flush_para(para_buf)
            para_buf = []
            inline_expr = stripped[2:].rstrip("$").strip()
            if inline_expr:
                # Single-line: $$E = mc^2$$
                blocks.append({"type": "math", "text": inline_expr})
                i += 1
            else:
                # Multi-line: opening $$ alone, then expression lines, then closing $$
                math_lines = []
                i += 1
                while i < len(lines) and lines[i].strip() != "$$":
                    math_lines.append(lines[i])
                    i += 1
                if i < len(lines):
                    i += 1  # skip closing $$
                blocks.append({"type": "math", "text": "\n".join(math_lines).strip()})
            continue

        # Fenced code block: ``` or ~~~
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_para(para_buf)
            para_buf = []
            fence = stripped[:3]
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # skip closing fence
            blocks.append({"type": "code", "text": "\n".join(code_lines)})
            continue

        # Blockquote → callout
        if stripped.startswith(">"):
            flush_para(para_buf)
            para_buf = []
            qt = re.sub(r'^>\s*', '', stripped)
            blocks.append({"type": "callout", "text": _md_inline(qt)})
            i += 1
            continue

        # Unordered bullet: -, *, +
        if re.match(r'^[-*+]\s+', stripped):
            flush_para(para_buf)
            para_buf = []
            text_part = re.sub(r'^[-*+]\s+', '', stripped)
            blocks.append({"type": "bullet", "text": _md_inline(text_part)})
            i += 1
            continue

        # Ordered list: 1. 2. etc. → numbered (preserves counter in render_body)
        if re.match(r'^\d+\.\s+', stripped):
            flush_para(para_buf)
            para_buf = []
            text_part = re.sub(r'^\d+\.\s+', '', stripped)
            blocks.append({"type": "numbered", "text": _md_inline(text_part)})
            i += 1
            continue

        # Table: | col | col |
        if stripped.startswith("|"):
            flush_para(para_buf)
            para_buf = []
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Remove separator rows (|---|---|)
            data_rows = [r for r in table_lines if not re.match(r'^\|[-:| ]+\|$', r)]
            parsed = []
            for row in data_rows:
                cells = [c.strip() for c in row.strip("|").split("|")]
                parsed.append(cells)
            if len(parsed) >= 2:
                blocks.append({
                    "type":    "table",
                    "headers": parsed[0],
                    "rows":    parsed[1:],
                })
            elif len(parsed) == 1:
                # Single row — treat as paragraph
                blocks.append({"type": "body", "text": " | ".join(parsed[0])})
            continue

        # Horizontal rule → spacer
        if re.match(r'^[-*_]{3,}$', stripped):
            flush_para(para_buf)
            para_buf = []
            blocks.append({"type": "spacer", "pt": 16})
            i += 1
            continue

        # Plain text → accumulate into paragraph
        para_buf.append(stripped)
        i += 1

    flush_para(para_buf)
    return blocks


def _md_inline(text: str) -> str:
    """Convert inline Markdown to ReportLab XML markup."""
    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__',     r'<b>\1</b>', text)
    # Italic: *text* or _text_
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.+?)_',   r'<i>\1</i>', text)
    # Inline code: `code`
    text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
    # Strip markdown links, keep text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text


# ── PDF text extractor ─────────────────────────────────────────────────────────
def parse_pdf(pdf_path: str) -> list:
    """
    Extract text from an existing PDF and convert to content.json blocks.
    Best-effort: detects headings by font size heuristics if available,
    otherwise falls back to paragraph splitting.
    """
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    all_text = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            all_text.append(text.strip())

    full_text = "\n\n".join(all_text)

    # Treat extracted PDF text as plain text / light markdown
    # (most PDFs lose formatting — we do our best)
    return parse_plain(full_text)


def parse_plain(text: str) -> list:
    """
    Heuristic plain-text parser.
    Short ALL-CAPS or title-case lines → headings.
    Everything else → paragraphs.
    """
    blocks = []
    paragraphs = re.split(r'\n{2,}', text.strip())

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        lines = para.splitlines()

        # Single short line that looks like a heading
        if len(lines) == 1 and len(para) < 80:
            if para.isupper() or re.match(r'^[A-Z][^.!?]*$', para):
                blocks.append({"type": "h1", "text": para.title()})
                continue

        # Bullet lists
        if lines[0].startswith(("- ", "• ", "* ")):
            for line in lines:
                text_part = re.sub(r'^[-•*]\s+', '', line.strip())
                if text_part:
                    blocks.append({"type": "bullet", "text": text_part})
            continue

        # Regular paragraph
        blocks.append({"type": "body", "text": " ".join(lines)})

    return blocks


# ── Pass-through validator ─────────────────────────────────────────────────────
VALID_TYPES = {"h1","h2","h3","body","bullet","numbered","callout","table",
               "image","code","math","divider","caption","pagebreak","spacer"}

def validate_content_json(data: list) -> tuple[list, list]:
    """Return (valid_blocks, warnings)."""
    valid, warnings = [], []
    for i, block in enumerate(data):
        if not isinstance(block, dict):
            warnings.append(f"Block {i}: not a dict, skipped")
            continue
        btype = block.get("type")
        if btype not in VALID_TYPES:
            warnings.append(f"Block {i}: unknown type '{btype}', kept as-is")
        valid.append(block)
    return valid, warnings


# ── Dispatcher ─────────────────────────────────────────────────────────────────
def parse_file(input_path: str) -> tuple[list, list]:
    """Return (blocks, warnings)."""
    ext = Path(input_path).suffix.lower()

    if ext in (".md", ".txt", ".markdown"):
        with open(input_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        blocks = parse_markdown(text)
        return blocks, []

    if ext == ".pdf":
        blocks = parse_pdf(input_path)
        return blocks, ["PDF text extraction is best-effort — review content.json before rendering"]

    if ext == ".json":
        with open(input_path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return validate_content_json(data)
        # Maybe it's a meta-wrapper {"content": [...]}
        if isinstance(data, dict) and "content" in data:
            return validate_content_json(data["content"])
        return [], [f"JSON file does not contain a list of content blocks"]

    return [], [f"Unsupported file type: {ext}. Supported: .md .txt .pdf .json"]


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Parse a document into content.json")
    parser.add_argument("--input", required=True, help="Input file (.md, .txt, .pdf, .json)")
    parser.add_argument("--out",   default="content.json", help="Output content.json path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"status": "error", "error": f"File not found: {args.input}"}),
              file=sys.stderr)
        sys.exit(1)

    try:
        blocks, warnings = parse_file(args.input)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "error": str(e),
                          "trace": traceback.format_exc()}), file=sys.stderr)
        sys.exit(3)

    if not blocks:
        print(json.dumps({
            "status":   "error",
            "error":    "No content blocks extracted",
            "warnings": warnings,
        }), file=sys.stderr)
        sys.exit(3)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2, ensure_ascii=False)

    result = {
        "status":      "ok",
        "out":         args.out,
        "block_count": len(blocks),
        "warnings":    warnings,
    }
    print(json.dumps(result, indent=2))

    print(f"\n── Parsed {args.input} ─────────────────────────────────────",
          file=sys.stderr)
    print(f"  Blocks : {len(blocks)}", file=sys.stderr)

    type_counts: dict = {}
    for b in blocks:
        type_counts[b.get("type","?")] = type_counts.get(b.get("type","?"), 0) + 1
    for t, n in sorted(type_counts.items()):
        print(f"    {t:12} × {n}", file=sys.stderr)

    if warnings:
        print(f"  Warnings:", file=sys.stderr)
        for w in warnings:
            print(f"    ⚠  {w}", file=sys.stderr)
    print(f"\n  Next: bash make.sh run --content {args.out} --title '...' --type ...",
          file=sys.stderr)
    print("", file=sys.stderr)


if __name__ == "__main__":
    main()
