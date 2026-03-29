#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
xlsx_insert_row.py — Insert a new data row into a worksheet in an unpacked xlsx.

Usage examples:
    # Insert "Utilities" row at position 6, copying styles from row 5
    python3 xlsx_insert_row.py /tmp/work/ --at 6 \\
        --sheet "Budget FY2025" \\
        --text A=Utilities \\
        --values B=3000 C=3000 D=3500 E=3500 \\
        --formula 'F=SUM(B{row}:E{row})' \\
        --copy-style-from 5

What it does:
  1. Shifts all rows >= at down by 1 (calls xlsx_shift_rows.py)
  2. Adds text values to sharedStrings.xml
  3. Inserts new row with specified cells (text, numbers, formulas)
  4. Copies cell styles from a reference row
  5. Updates dimension ref

The shift operation automatically expands SUM formulas that span the
insertion point, so total-row formulas are updated without extra work.

IMPORTANT: Run on an UNPACKED directory (from xlsx_unpack.py).
After running, repack with xlsx_pack.py.
"""

import argparse
import os
import re
import subprocess
import sys
import xml.dom.minidom
import xml.etree.ElementTree as ET

NS_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace('', NS_SS)
ET.register_namespace('r', NS_REL)
ET.register_namespace('xdr', 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing')
ET.register_namespace('x14', 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main')
ET.register_namespace('xr2', 'http://schemas.microsoft.com/office/spreadsheetml/2015/revision2')
ET.register_namespace('mc', 'http://schemas.openxmlformats.org/markup-compatibility/2006')


def _tag(local: str) -> str:
    return f"{{{NS_SS}}}{local}"


def _write_tree(tree: ET.ElementTree, path: str) -> None:
    tree.write(path, encoding="unicode", xml_declaration=False)
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        dom = xml.dom.minidom.parseString(raw.encode("utf-8"))
        pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [line for line in pretty.splitlines() if line.strip()]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


def col_number(s: str) -> int:
    n = 0
    for c in s.upper():
        n = n * 26 + (ord(c) - 64)
    return n


def find_ws_path(work_dir: str, sheet_name: str | None) -> str:
    wb_tree = ET.parse(os.path.join(work_dir, "xl", "workbook.xml"))
    rid = None
    for sheet in wb_tree.getroot().iter(_tag("sheet")):
        if sheet_name is None or sheet.get("name") == sheet_name:
            rid = sheet.get(f"{{{NS_REL}}}id")
            break

    if rid is None:
        print(f"ERROR: Sheet not found: {sheet_name}")
        sys.exit(1)

    rels_tree = ET.parse(os.path.join(work_dir, "xl", "_rels", "workbook.xml.rels"))
    for rel in rels_tree.getroot():
        if rel.get("Id") == rid:
            return os.path.join(work_dir, "xl", rel.get("Target"))

    print(f"ERROR: Relationship not found: {rid}")
    sys.exit(1)


def add_shared_string(work_dir: str, text: str) -> int:
    ss_path = os.path.join(work_dir, "xl", "sharedStrings.xml")
    tree = ET.parse(ss_path)
    root = tree.getroot()

    idx = 0
    for si in root.findall(_tag("si")):
        t_el = si.find(_tag("t"))
        if t_el is not None and t_el.text == text:
            return idx
        idx += 1

    si = ET.SubElement(root, _tag("si"))
    t = ET.SubElement(si, _tag("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text

    root.set("count", str(int(root.get("count", "0")) + 1))
    root.set("uniqueCount", str(int(root.get("uniqueCount", "0")) + 1))

    _write_tree(tree, ss_path)
    return idx


def get_row_styles(ws_tree: ET.ElementTree, row_num: int) -> dict[str, int]:
    """Get {col_letter: style_index} for all cells in a row."""
    styles = {}
    for row_el in ws_tree.getroot().iter(_tag("row")):
        if row_el.get("r") == str(row_num):
            for c in row_el:
                ref = c.get("r", "")
                col_str = re.match(r"([A-Z]+)", ref)
                if col_str:
                    styles[col_str.group(1)] = int(c.get("s", "0"))
            break
    return styles


def parse_kv(specs: list[str] | None) -> dict[str, str]:
    if not specs:
        return {}
    result = {}
    for spec in specs:
        col, _, val = spec.partition("=")
        result[col.upper()] = val
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Insert a new row into a worksheet in an unpacked xlsx")
    parser.add_argument("work_dir", help="Unpacked xlsx working directory")
    parser.add_argument("--at", type=int, required=True,
                        help="Row number to insert at (existing rows shift down)")
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first)")
    parser.add_argument("--text", nargs="+", default=None,
                        help="Text cells: COL=VALUE (e.g., A=Utilities)")
    parser.add_argument("--values", nargs="+", default=None,
                        help="Numeric cells: COL=VALUE (e.g., B=3000 C=3000)")
    parser.add_argument("--formula", nargs="+", default=None,
                        help="Formula cells: COL=FORMULA with {row} (e.g., F=SUM(B{row}:E{row}))")
    parser.add_argument("--copy-style-from", type=int, default=None,
                        help="Copy cell styles from this row number")
    args = parser.parse_args()

    at = args.at
    text_cells = parse_kv(args.text)
    num_cells = parse_kv(args.values)
    formula_cells = parse_kv(args.formula)

    # Step 1: Shift rows down using xlsx_shift_rows.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    shift_script = os.path.join(script_dir, "xlsx_shift_rows.py")

    print(f"Step 1: Shifting rows >= {at} down by 1...")
    result = subprocess.run(
        [sys.executable, shift_script, args.work_dir, "insert", str(at), "1"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: shift_rows failed:\n{result.stderr}")
        sys.exit(1)
    print(result.stdout)

    # Step 2: Resolve worksheet path and get reference styles
    ws_path = find_ws_path(args.work_dir, args.sheet)
    ws_tree = ET.parse(ws_path)

    ref_styles = {}
    if args.copy_style_from is not None:
        ref_styles = get_row_styles(ws_tree, args.copy_style_from)
        print(f"Step 2: Copied styles from row {args.copy_style_from}: {ref_styles}")

    # Step 3: Add text values to sharedStrings
    text_indices = {}
    for col, text in text_cells.items():
        text_indices[col] = add_shared_string(args.work_dir, text)
        print(f"  Added shared string: \"{text}\" → index {text_indices[col]}")

    # Step 4: Re-parse worksheet and build new row
    ws_tree = ET.parse(ws_path)
    root = ws_tree.getroot()
    sheet_data = root.find(_tag("sheetData"))

    new_row = ET.Element(_tag("row"))
    new_row.set("r", str(at))

    all_cols = sorted(
        set(list(text_cells) + list(num_cells) + list(formula_cells)),
        key=col_number,
    )

    for col in all_cols:
        cell = ET.SubElement(new_row, _tag("c"))
        cell.set("r", f"{col}{at}")

        if col in ref_styles:
            cell.set("s", str(ref_styles[col]))

        if col in text_cells:
            cell.set("t", "s")
            v = ET.SubElement(cell, _tag("v"))
            v.text = str(text_indices[col])
        elif col in num_cells:
            # Omit t attribute for numbers — "n" is the default per OOXML spec
            v = ET.SubElement(cell, _tag("v"))
            v.text = str(num_cells[col])
        elif col in formula_cells:
            formula_text = formula_cells[col].replace("{row}", str(at)).lstrip("=")
            f_el = ET.SubElement(cell, _tag("f"))
            f_el.text = formula_text
            # Use formula style from reference if available; it may differ
            # from the data style (e.g., black font vs blue font).
            # Look for the formula column's style specifically.
            if col in ref_styles:
                cell.set("s", str(ref_styles[col]))

    # Insert new row at the correct position in sheetData (sorted by row number)
    insert_idx = 0
    for i, row_el in enumerate(list(sheet_data)):
        r = row_el.get("r")
        if r and int(r) > at:
            insert_idx = i
            break
        insert_idx = i + 1

    sheet_data.insert(insert_idx, new_row)

    print(f"\nStep 3: Inserted row {at} with {len(all_cols)} cells:")
    for col in all_cols:
        if col in text_cells:
            print(f"  {col}{at} = \"{text_cells[col]}\" (text)")
        elif col in num_cells:
            print(f"  {col}{at} = {num_cells[col]} (number)")
        elif col in formula_cells:
            ftext = formula_cells[col].replace("{row}", str(at))
            print(f"  {col}{at} = {ftext} (formula)")

    # Step 5: Update dimension
    for dim in root.iter(_tag("dimension")):
        old_ref = dim.get("ref", "")
        if ":" in old_ref:
            start_ref, end_ref = old_ref.split(":")
            end_row = int(re.search(r"(\d+)", end_ref).group(1))
            end_col = re.match(r"([A-Z]+)", end_ref).group(1)
            # Dimension was already shifted by shift_rows, just verify
            max_col = max(col_number(end_col), max(col_number(c) for c in all_cols))
            max_col_letter = end_col if col_number(end_col) >= max_col else col
            new_ref = f"{start_ref}:{max_col_letter}{end_row}"
            if new_ref != old_ref:
                dim.set("ref", new_ref)
                print(f"\n  Dimension: {old_ref} → {new_ref}")

    _write_tree(ws_tree, ws_path)

    print(f"\nDone. Row {at} inserted successfully.")
    print(f"\nNext: python3 xlsx_pack.py {args.work_dir} output.xlsx")


if __name__ == "__main__":
    main()
