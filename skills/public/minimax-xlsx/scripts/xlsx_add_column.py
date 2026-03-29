#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
xlsx_add_column.py — Add a new column to a worksheet in an unpacked xlsx.

Usage examples:
    # Add a percentage column with formulas and number format
    python3 xlsx_add_column.py /tmp/work/ --col G \\
        --sheet "Budget FY2025" \\
        --header "% of Total" \\
        --formula '=F{row}/$F$10' --formula-rows 2:9 \\
        --total-row 10 --total-formula '=SUM(G2:G9)' \\
        --numfmt '0.0%'

What it does:
  1. Adds header cell (copies style from previous column's header)
  2. Adds formula cells for the specified row range
  3. Adds a total formula cell if specified
  4. Creates a new cell style with the given numfmt if needed
  5. Updates sharedStrings.xml for header text
  6. Updates dimension ref and column definitions

IMPORTANT: Run on an UNPACKED directory (from xlsx_unpack.py).
After running, repack with xlsx_pack.py.
"""

import argparse
import copy
import os
import re
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


def col_letter(n: int) -> str:
    r = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        r = chr(65 + rem) + r
    return r


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


def get_cell_style(ws_tree: ET.ElementTree, col: str, row: int) -> int:
    ref = f"{col}{row}"
    for row_el in ws_tree.getroot().iter(_tag("row")):
        if row_el.get("r") == str(row):
            for c in row_el:
                if c.get("r") == ref:
                    return int(c.get("s", "0"))
    return 0


def ensure_numfmt_style(work_dir: str, ref_style_idx: int, numfmt_code: str) -> int:
    """Clone a cellXfs entry with the given numfmt. Returns new style index."""
    styles_path = os.path.join(work_dir, "xl", "styles.xml")
    tree = ET.parse(styles_path)
    root = tree.getroot()

    # Find or add numFmt
    numfmts = root.find(_tag("numFmts"))
    numfmt_id = None
    if numfmts is not None:
        for nf in numfmts:
            if nf.get("formatCode") == numfmt_code:
                numfmt_id = int(nf.get("numFmtId"))
                break

    if numfmt_id is None:
        max_id = 163
        if numfmts is not None:
            for nf in numfmts:
                max_id = max(max_id, int(nf.get("numFmtId", "0")))
        else:
            numfmts = ET.SubElement(root, _tag("numFmts"))
            numfmts.set("count", "0")
            root.remove(numfmts)
            root.insert(0, numfmts)

        numfmt_id = max_id + 1
        nf = ET.SubElement(numfmts, _tag("numFmt"))
        nf.set("numFmtId", str(numfmt_id))
        nf.set("formatCode", numfmt_code)
        numfmts.set("count", str(len(list(numfmts))))

    # Find or create cellXfs entry
    cellxfs = root.find(_tag("cellXfs"))
    xf_list = list(cellxfs)
    ref_xf = xf_list[min(ref_style_idx, len(xf_list) - 1)]

    for i, xf in enumerate(xf_list):
        if (xf.get("numFmtId") == str(numfmt_id) and
                xf.get("fontId") == ref_xf.get("fontId") and
                xf.get("fillId") == ref_xf.get("fillId") and
                xf.get("borderId") == ref_xf.get("borderId")):
            return i

    new_xf = copy.deepcopy(ref_xf)
    new_xf.set("numFmtId", str(numfmt_id))
    new_xf.set("applyNumberFormat", "true")
    cellxfs.append(new_xf)
    cellxfs.set("count", str(len(list(cellxfs))))

    _write_tree(tree, styles_path)
    return len(list(cellxfs)) - 1


def _apply_border_to_row(work_dir: str, ws_path: str, ws_tree: ET.ElementTree,
                         ws_root: ET.Element, row_map: dict, border_row: int,
                         border_style: str, new_col: str) -> None:
    """Apply a top border to ALL cells in the specified row (A through new_col)."""
    styles_path = os.path.join(work_dir, "xl", "styles.xml")
    st_tree = ET.parse(styles_path)
    st_root = st_tree.getroot()

    # 1. Create a new border entry with the specified top style
    borders = st_root.find(_tag("borders"))
    new_border = ET.SubElement(borders, _tag("border"))
    for side in ("left", "right"):
        ET.SubElement(new_border, _tag(side))
    top_el = ET.SubElement(new_border, _tag("top"))
    top_el.set("style", border_style)
    ET.SubElement(new_border, _tag("bottom"))
    ET.SubElement(new_border, _tag("diagonal"))
    borders.set("count", str(len(list(borders))))
    new_border_id = len(list(borders)) - 1

    # 2. For each existing style used in the row, create a clone with the new borderId
    cellxfs = st_root.find(_tag("cellXfs"))
    style_remap = {}  # old_style_idx -> new_style_idx

    if border_row not in row_map:
        return

    row_el = row_map[border_row]
    # Collect all cells in this row and their styles
    for c in row_el:
        old_s = int(c.get("s", "0"))
        if old_s not in style_remap:
            xf_list = list(cellxfs)
            ref_xf = xf_list[min(old_s, len(xf_list) - 1)]
            new_xf = copy.deepcopy(ref_xf)
            new_xf.set("borderId", str(new_border_id))
            new_xf.set("applyBorder", "true")
            cellxfs.append(new_xf)
            cellxfs.set("count", str(len(list(cellxfs))))
            style_remap[old_s] = len(list(cellxfs)) - 1

    # 3. Apply remapped styles to all cells in the row
    for c in row_el:
        old_s = int(c.get("s", "0"))
        if old_s in style_remap:
            c.set("s", str(style_remap[old_s]))

    _write_tree(st_tree, styles_path)
    last_col_num = col_number(new_col)
    print(f"  Applied {border_style} top border to all cells in row {border_row} "
          f"(A-{new_col}, {len(style_remap)} style(s) cloned)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a column to a worksheet in an unpacked xlsx")
    parser.add_argument("work_dir", help="Unpacked xlsx working directory")
    parser.add_argument("--col", required=True, help="Column letter (e.g., G)")
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first)")
    parser.add_argument("--header", default=None, help="Header text for row 1")
    parser.add_argument("--formula", default=None,
                        help="Formula template with {row} placeholder")
    parser.add_argument("--formula-rows", default=None,
                        help="Row range for formulas (e.g., 2:9)")
    parser.add_argument("--total-row", type=int, default=None,
                        help="Row number for total formula")
    parser.add_argument("--total-formula", default=None,
                        help="Formula for total row")
    parser.add_argument("--numfmt", default=None,
                        help="Number format for data/total cells (e.g., 0.0%%)")
    parser.add_argument("--border-row", type=int, default=None,
                        help="Row to apply a top border to ALL cells (e.g., 10)")
    parser.add_argument("--border-style", default="medium",
                        help="Border style: thin, medium, thick (default: medium)")
    args = parser.parse_args()

    col = args.col.upper()
    prev_col = col_letter(col_number(col) - 1) if col_number(col) > 1 else "A"

    ws_path = find_ws_path(args.work_dir, args.sheet)
    ws_tree = ET.parse(ws_path)
    changes = 0

    print(f"Adding column {col} to {os.path.basename(ws_path)}")

    # Resolve styles from previous column
    header_style = get_cell_style(ws_tree, prev_col, 1) if args.header else 0

    data_style = None
    if args.formula_rows:
        start_row = int(args.formula_rows.split(":")[0])
        ref = get_cell_style(ws_tree, prev_col, start_row)
        data_style = (ensure_numfmt_style(args.work_dir, ref, args.numfmt)
                      if args.numfmt else ref)

    total_style = None
    if args.total_row:
        ref = get_cell_style(ws_tree, prev_col, args.total_row)
        total_style = (ensure_numfmt_style(args.work_dir, ref, args.numfmt)
                       if args.numfmt else ref)

    # Add header to sharedStrings
    header_idx = add_shared_string(args.work_dir, args.header) if args.header else None

    # Re-parse worksheet (sharedStrings write may have changed state)
    ws_tree = ET.parse(ws_path)
    root = ws_tree.getroot()
    sheet_data = root.find(_tag("sheetData"))

    row_map = {}
    for row_el in sheet_data:
        r = row_el.get("r")
        if r:
            row_map[int(r)] = row_el

    # Add header cell
    if args.header and 1 in row_map:
        cell = ET.SubElement(row_map[1], _tag("c"))
        cell.set("r", f"{col}1")
        cell.set("s", str(header_style))
        cell.set("t", "s")
        v = ET.SubElement(cell, _tag("v"))
        v.text = str(header_idx)
        changes += 1
        print(f"  {col}1 = \"{args.header}\" (header, style={header_style})")

    # Add formula cells
    if args.formula and args.formula_rows:
        start, end = map(int, args.formula_rows.split(":"))
        for row_num in range(start, end + 1):
            if row_num not in row_map:
                row_el = ET.SubElement(sheet_data, _tag("row"))
                row_el.set("r", str(row_num))
                row_map[row_num] = row_el

            formula_text = args.formula.replace("{row}", str(row_num))
            formula_text = formula_text.lstrip("=")
            cell = ET.SubElement(row_map[row_num], _tag("c"))
            cell.set("r", f"{col}{row_num}")
            if data_style is not None:
                cell.set("s", str(data_style))
            f_el = ET.SubElement(cell, _tag("f"))
            f_el.text = formula_text
            changes += 1

        print(f"  {col}{start}:{col}{end} = formulas (style={data_style})")

    # Add total formula
    if args.total_row and args.total_formula:
        if args.total_row not in row_map:
            row_el = ET.SubElement(sheet_data, _tag("row"))
            row_el.set("r", str(args.total_row))
            row_map[args.total_row] = row_el

        total_f = args.total_formula.lstrip("=")
        cell = ET.SubElement(row_map[args.total_row], _tag("c"))
        cell.set("r", f"{col}{args.total_row}")
        if total_style is not None:
            cell.set("s", str(total_style))
        f_el = ET.SubElement(cell, _tag("f"))
        f_el.text = total_f
        changes += 1
        print(f"  {col}{args.total_row} = ={total_f} (style={total_style})")

    # Update dimension
    for dim in root.iter(_tag("dimension")):
        old_ref = dim.get("ref", "")
        if ":" in old_ref:
            start_ref, end_ref = old_ref.split(":")
            end_col_str = re.match(r"([A-Z]+)", end_ref).group(1)
            end_row_str = re.search(r"(\d+)", end_ref).group(1)
            if col_number(col) > col_number(end_col_str):
                new_ref = f"{start_ref}:{col}{end_row_str}"
                dim.set("ref", new_ref)
                print(f"  Dimension: {old_ref} → {new_ref}")

    # Extend <cols> to cover new column
    cols_el = root.find(_tag("cols"))
    if cols_el is not None:
        new_col_num = col_number(col)
        covered = any(
            int(c.get("min", "0")) <= new_col_num <= int(c.get("max", "0"))
            for c in cols_el
        )
        if not covered:
            prev_num = col_number(prev_col)
            for c in cols_el:
                if int(c.get("min", "0")) <= prev_num <= int(c.get("max", "0")):
                    new_col_def = copy.deepcopy(c)
                    new_col_def.set("min", str(new_col_num))
                    new_col_def.set("max", str(new_col_num))
                    cols_el.append(new_col_def)
                    print(f"  Added <col> definition for column {col}")
                    break

    # Apply border to entire row if requested
    if args.border_row:
        _apply_border_to_row(args.work_dir, ws_path, ws_tree, root,
                             row_map, args.border_row, args.border_style,
                             col)

    _write_tree(ws_tree, ws_path)
    print(f"\nDone. {changes} cells added.")
    print(f"\nNext: python3 xlsx_pack.py {args.work_dir} output.xlsx")


if __name__ == "__main__":
    main()
