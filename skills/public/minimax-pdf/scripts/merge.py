#!/usr/bin/env python3
"""
merge.py — Merge cover.pdf + body.pdf → final.pdf and print a QA report.

Usage:
    python3 merge.py --cover cover.pdf --body body.pdf --out final.pdf
    python3 merge.py --cover cover.pdf --body body.pdf --out final.pdf --title "My Report"

Exit codes: 0 success, 1 bad args/missing file, 2 missing dep, 3 merge error
"""

import argparse
import importlib.util
import json
import os
import sys

def ensure_deps():
    if importlib.util.find_spec("pypdf") is None:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "pypdf"]
        )


ensure_deps()

from pypdf import PdfWriter, PdfReader


def merge(cover_path: str, body_path: str, out_path: str, title: str = "") -> dict:
    writer = PdfWriter()

    for fpath, label in [(cover_path, "cover"), (body_path, "body")]:
        if not os.path.exists(fpath):
            return {"status": "error", "error": f"{label} file not found: {fpath}"}
        reader = PdfReader(fpath)
        for page in reader.pages:
            writer.add_page(page)

    # Set PDF metadata
    if title:
        writer.add_metadata({"/Title": title})

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    size_kb = os.path.getsize(out_path) // 1024
    total_pages = len(writer.pages)

    # ── QA checks ─────────────────────────────────────────────────────────────
    warnings = []

    # Page count sanity
    cover_pages = len(PdfReader(cover_path).pages)
    body_pages  = len(PdfReader(body_path).pages)
    if cover_pages != 1:
        warnings.append(f"Cover PDF has {cover_pages} pages (expected 1)")

    # File size sanity
    if size_kb < 20:
        warnings.append(f"Output is very small ({size_kb} KB) — may have blank pages")
    if size_kb > 50_000:
        warnings.append(f"Output is very large ({size_kb} KB) — consider compressing images")

    report = {
        "status":       "ok",
        "out":          out_path,
        "total_pages":  total_pages,
        "cover_pages":  cover_pages,
        "body_pages":   body_pages,
        "size_kb":      size_kb,
    }
    if warnings:
        report["warnings"] = warnings

    return report


def main():
    parser = argparse.ArgumentParser(description="Merge cover + body PDFs")
    parser.add_argument("--cover", required=True)
    parser.add_argument("--body",  required=True)
    parser.add_argument("--out",   required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    result = merge(args.cover, args.body, args.out, args.title)

    if result["status"] == "error":
        print(json.dumps(result), file=sys.stderr)
        sys.exit(3)

    print(json.dumps(result))

    # Human-readable QA summary
    print(f"\n── Build complete ──────────────────────────────────────")
    print(f"  Output  : {result['out']}")
    print(f"  Pages   : {result['total_pages']} total (1 cover + {result['body_pages']} body)")
    print(f"  Size    : {result['size_kb']} KB")
    if result.get("warnings"):
        print(f"  ⚠  Warnings:")
        for w in result["warnings"]:
            print(f"     • {w}")
    else:
        print(f"  ✓  No issues detected")
    print(f"────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
