#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
xlsx_unpack.py — Unpack an xlsx file into a working directory for XML editing.

Usage:
    python3 xlsx_unpack.py <input.xlsx> <output_dir>

What it does:
1. Unzips the xlsx (which is a ZIP archive)
2. Pretty-prints all XML and .rels files for readability
3. Prints a summary of key files to edit
"""

import sys
import zipfile
import os
import shutil
import xml.dom.minidom


def pretty_print_xml(content: bytes) -> str:
    """Pretty-print XML bytes. Returns original content on parse failure."""
    try:
        dom = xml.dom.minidom.parseString(content)
        pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        # Remove the extra blank lines toprettyxml adds
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"
    except Exception:
        return content.decode("utf-8", errors="replace")


def unpack(xlsx_path: str, output_dir: str) -> None:
    if not os.path.isfile(xlsx_path):
        print(f"ERROR: File not found: {xlsx_path}", file=sys.stderr)
        sys.exit(1)

    if not xlsx_path.lower().endswith((".xlsx", ".xlsm")):
        print(f"WARNING: '{xlsx_path}' does not have an .xlsx/.xlsm extension", file=sys.stderr)

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    try:
        with zipfile.ZipFile(xlsx_path, "r") as z:
            # Validate member paths to prevent zip-slip (path traversal) attacks
            for member in z.namelist():
                member_path = os.path.realpath(os.path.join(output_dir, member))
                if not member_path.startswith(os.path.realpath(output_dir) + os.sep) and member_path != os.path.realpath(output_dir):
                    print(f"ERROR: Zip entry '{member}' would escape target directory (path traversal blocked)", file=sys.stderr)
                    shutil.rmtree(output_dir, ignore_errors=True)
                    sys.exit(1)
            z.extractall(output_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(output_dir, ignore_errors=True)
        print(f"ERROR: '{xlsx_path}' is not a valid ZIP/xlsx file", file=sys.stderr)
        sys.exit(1)

    # Pretty-print XML and .rels files
    xml_count = 0
    for dirpath, _, filenames in os.walk(output_dir):
        for fname in filenames:
            if fname.endswith(".xml") or fname.endswith(".rels"):
                fpath = os.path.join(dirpath, fname)
                with open(fpath, "rb") as f:
                    raw = f.read()
                pretty = pretty_print_xml(raw)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(pretty)
                xml_count += 1

    print(f"Unpacked '{xlsx_path}' → '{output_dir}'")
    print(f"Pretty-printed {xml_count} XML/rels files\n")

    # Print key files grouped by category
    categories = {
        "Package root": ["[Content_Types].xml", "_rels/.rels"],
        "Workbook": ["xl/workbook.xml", "xl/_rels/workbook.xml.rels"],
        "Styles & Strings": ["xl/styles.xml", "xl/sharedStrings.xml"],
        "Worksheets": [],
    }

    all_files = []
    for dirpath, _, filenames in os.walk(output_dir):
        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), output_dir)
            all_files.append(rel)

    # Collect worksheets
    for rel in sorted(all_files):
        if rel.startswith("xl/worksheets/") and rel.endswith(".xml"):
            categories["Worksheets"].append(rel)

    print("Key files to inspect/edit:")
    for category, files in categories.items():
        if not files:
            continue
        print(f"\n  [{category}]")
        for f in files:
            full = os.path.join(output_dir, f)
            if os.path.isfile(full):
                size = os.path.getsize(full)
                print(f"    {f}  ({size:,} bytes)")
            else:
                print(f"    {f}  (not found)")

    # Warn about high-risk files present
    risky = {
        "xl/vbaProject.bin": "VBA macros — DO NOT modify",
        "xl/pivotTables": "Pivot tables — update source ranges carefully if shifting rows",
        "xl/charts": "Charts — update data ranges if shifting rows",
    }
    print("\n  [High-risk content detected:]")
    found_any = False
    for path, warning in risky.items():
        full = os.path.join(output_dir, path)
        if os.path.exists(full):
            print(f"    ⚠️  {path} — {warning}")
            found_any = True
    if not found_any:
        print("    ✓ None (safe to edit)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: xlsx_unpack.py <input.xlsx> <output_dir>")
        sys.exit(1)
    unpack(sys.argv[1], sys.argv[2])
