#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
style_audit.py — Financial formatting compliance checker for xlsx files.

Audits an xlsx file (or an unpacked xlsx directory) and reports:
1. Style system integrity: count attributes match actual element counts
2. Color-role violations: formula cells with blue font, input cells with black font
3. Year-format violations: cells containing 4-digit years using comma-format
4. Percentage value violations: percentage-formatted cells with values > 1 (likely meant 0.08 not 8)
5. Style index out-of-range: s attribute exceeds cellXfs count
6. fills[0]/fills[1] presence check (OOXML spec requirement)

Usage:
    python3 style_audit.py input.xlsx                  # audit a packed xlsx
    python3 style_audit.py /tmp/xlsx_work/             # audit an unpacked directory
    python3 style_audit.py input.xlsx --json           # machine-readable output
    python3 style_audit.py input.xlsx --summary        # counts only, no detail

Exit code:
    0 — no violations found
    1 — violations detected (or file cannot be opened)
"""

import sys
import os
import zipfile
import xml.etree.ElementTree as ET
import json
import re
import tempfile
import shutil

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NSP = f"{{{NS}}}"

# Predefined style index semantics from minimal_xlsx template.
# Maps cellXfs index -> (role, font_color_expectation, numFmt_type)
# role: "input" = blue expected, "formula" = black/green expected, "header" = any, "any" = skip
TEMPLATE_SLOT_ROLES = {
    0:  ("any",     None,    None),
    1:  ("input",   "blue",  "general"),
    2:  ("formula", "black", "general"),
    3:  ("formula", "green", "general"),
    4:  ("any",     None,    "general"),   # header
    5:  ("input",   "blue",  "currency"),
    6:  ("formula", "black", "currency"),
    7:  ("input",   "blue",  "percent"),
    8:  ("formula", "black", "percent"),
    9:  ("input",   "blue",  "integer"),
    10: ("formula", "black", "integer"),
    11: ("input",   "blue",  "year"),
    12: ("input",   "blue",  "general"),   # highlight
}

# AARRGGBB values for each role color
BLUE_RGB  = "000000ff"
BLACK_RGB = "00000000"
GREEN_RGB = "00008000"
RED_RGB   = "00ff0000"

# numFmtIds that represent percentage formats (built-in + common custom)
PERCENT_FMT_IDS = {9, 10, 165, 170}

# numFmtIds that use comma separator (would corrupt year display)
COMMA_FMT_IDS = {3, 4, 167, 168}  # #,##0 style — 4-digit years would show as 2,024


def _parse_styles(styles_xml: bytes) -> dict:
    """Parse styles.xml and return structured data."""
    root = ET.fromstring(styles_xml)

    def find(tag):
        return root.find(f"{NSP}{tag}")

    # numFmts
    num_fmts = {}  # id -> formatCode
    nf_elem = find("numFmts")
    if nf_elem is not None:
        declared_count = int(nf_elem.get("count", "0"))
        actual_count = len(nf_elem)
        for nf in nf_elem:
            fid = int(nf.get("numFmtId", "0"))
            num_fmts[fid] = nf.get("formatCode", "")
    else:
        declared_count = 0
        actual_count = 0

    # fonts — extract color and bold flag
    fonts = []
    fonts_elem = find("fonts")
    fonts_declared = 0
    if fonts_elem is not None:
        fonts_declared = int(fonts_elem.get("count", "0"))
        for font in fonts_elem:
            color_elem = font.find(f"{NSP}color")
            bold_elem = font.find(f"{NSP}b")
            if color_elem is not None:
                rgb = color_elem.get("rgb", "").lower()
                theme = color_elem.get("theme")
            else:
                rgb = ""
                theme = None
            fonts.append({
                "rgb": rgb,
                "theme": theme,
                "bold": bold_elem is not None,
            })

    # fills
    fills = []
    fills_elem = find("fills")
    fills_declared = 0
    if fills_elem is not None:
        fills_declared = int(fills_elem.get("count", "0"))
        for fill in fills_elem:
            pf = fill.find(f"{NSP}patternFill")
            pattern_type = pf.get("patternType", "") if pf is not None else ""
            fills.append({"patternType": pattern_type})

    # cellXfs
    xfs = []
    xfs_elem = find("cellXfs")
    xfs_declared = 0
    if xfs_elem is not None:
        xfs_declared = int(xfs_elem.get("count", "0"))
        for xf in xfs_elem:
            xfs.append({
                "numFmtId": int(xf.get("numFmtId", "0")),
                "fontId":   int(xf.get("fontId", "0")),
                "fillId":   int(xf.get("fillId", "0")),
                "borderId": int(xf.get("borderId", "0")),
            })

    return {
        "num_fmts": num_fmts,
        "num_fmts_declared": declared_count,
        "num_fmts_actual": actual_count,
        "fonts": fonts,
        "fonts_declared": fonts_declared,
        "fonts_actual": len(fonts),
        "fills": fills,
        "fills_declared": fills_declared,
        "fills_actual": len(fills),
        "xfs": xfs,
        "xfs_declared": xfs_declared,
        "xfs_actual": len(xfs),
    }


def _is_blue_font(font: dict) -> bool:
    return font["rgb"] == BLUE_RGB


def _is_black_font(font: dict) -> bool:
    return font["rgb"] == BLACK_RGB or (font["rgb"] == "" and font["theme"] is not None)


def _is_green_font(font: dict) -> bool:
    return font["rgb"] == GREEN_RGB


def _fmt_is_percent(num_fmt_id: int, num_fmts: dict) -> bool:
    if num_fmt_id in PERCENT_FMT_IDS:
        return True
    fmt_code = num_fmts.get(num_fmt_id, "")
    return "%" in fmt_code


def _fmt_is_comma(num_fmt_id: int, num_fmts: dict) -> bool:
    if num_fmt_id in COMMA_FMT_IDS:
        return True
    fmt_code = num_fmts.get(num_fmt_id, "")
    # formatCode has comma separator if it contains #,##0 but not a trailing , (scale)
    return "#,##" in fmt_code and not fmt_code.endswith(",") and not fmt_code.endswith(",\"M\"") and not fmt_code.endswith(",\"K\"")


def _looks_like_year(value_text: str) -> bool:
    """True if value is a 4-digit year between 1900 and 2100."""
    try:
        v = int(float(value_text))
        return 1900 <= v <= 2100
    except (ValueError, TypeError):
        return False


def _audit(styles_xml: bytes, sheet_xmls: list[tuple[str, bytes]]) -> dict:
    """
    Run all formatting compliance checks.

    Args:
        styles_xml: content of xl/styles.xml
        sheet_xmls: list of (sheet_name, xml_bytes) for each worksheet

    Returns:
        dict with violations and summary
    """
    results = {
        "violations": [],
        "warnings": [],
        "summary": {},
    }
    v = results["violations"]
    w = results["warnings"]

    styles = _parse_styles(styles_xml)
    fonts  = styles["fonts"]
    xfs    = styles["xfs"]
    num_fmts = styles["num_fmts"]

    # ── Check A: count attribute integrity ──────────────────────────────────
    if styles["fonts_declared"] != styles["fonts_actual"]:
        v.append({
            "type": "count_mismatch",
            "element": "fonts",
            "declared": styles["fonts_declared"],
            "actual": styles["fonts_actual"],
            "fix": f"Update <fonts count=\"{styles['fonts_actual']}\">",
        })
    if styles["fills_declared"] != styles["fills_actual"]:
        v.append({
            "type": "count_mismatch",
            "element": "fills",
            "declared": styles["fills_declared"],
            "actual": styles["fills_actual"],
            "fix": f"Update <fills count=\"{styles['fills_actual']}\">",
        })
    if styles["xfs_declared"] != styles["xfs_actual"]:
        v.append({
            "type": "count_mismatch",
            "element": "cellXfs",
            "declared": styles["xfs_declared"],
            "actual": styles["xfs_actual"],
            "fix": f"Update <cellXfs count=\"{styles['xfs_actual']}\">",
        })

    # ── Check B: fills[0] and fills[1] presence ──────────────────────────────
    fills = styles["fills"]
    if len(fills) < 2:
        v.append({
            "type": "missing_required_fills",
            "detail": "fills[0] (none) and fills[1] (gray125) are required by OOXML spec",
            "fix": "Prepend <fill><patternFill patternType='none'/></fill> and <fill><patternFill patternType='gray125'/></fill>",
        })
    else:
        if fills[0].get("patternType") != "none":
            v.append({
                "type": "fills_0_corrupted",
                "detail": f"fills[0] patternType='{fills[0].get('patternType')}', must be 'none'",
                "fix": "Set fills[0] patternFill patternType to 'none'",
            })
        if fills[1].get("patternType") != "gray125":
            v.append({
                "type": "fills_1_corrupted",
                "detail": f"fills[1] patternType='{fills[1].get('patternType')}', must be 'gray125'",
                "fix": "Set fills[1] patternFill patternType to 'gray125'",
            })

    # ── Check C: per-cell style violations ───────────────────────────────────
    total_cells = 0
    formula_cells = 0
    input_cells = 0

    for sheet_name, sheet_xml in sheet_xmls:
        ws = ET.fromstring(sheet_xml)

        for cell in ws.findall(f".//{NSP}c"):
            cell_ref = cell.get("r", "?")
            s_attr = cell.get("s")
            has_formula = cell.find(f"{NSP}f") is not None
            v_elem = cell.find(f"{NSP}v")
            value_text = v_elem.text if v_elem is not None else None
            total_cells += 1

            # Skip cells with no style
            if s_attr is None:
                continue

            try:
                s_idx = int(s_attr)
            except ValueError:
                continue

            # Check C1: s index out of range
            if s_idx >= len(xfs):
                v.append({
                    "type": "style_index_out_of_range",
                    "sheet": sheet_name,
                    "cell": cell_ref,
                    "s": s_idx,
                    "cellXfs_count": len(xfs),
                    "fix": f"s={s_idx} exceeds cellXfs count={len(xfs)}; add missing <xf> entries or lower s value",
                })
                continue

            xf = xfs[s_idx]
            font_id = xf["fontId"]
            num_fmt_id = xf["numFmtId"]

            if font_id >= len(fonts):
                v.append({
                    "type": "font_index_out_of_range",
                    "sheet": sheet_name,
                    "cell": cell_ref,
                    "fontId": font_id,
                    "fonts_count": len(fonts),
                    "fix": f"fontId={font_id} exceeds fonts count={len(fonts)}; add missing <font> entries",
                })
                continue

            font = fonts[font_id]

            # Check C2: color-role violation — formula cell with blue font
            if has_formula and _is_blue_font(font):
                formula_cells += 1
                f_elem = cell.find(f"{NSP}f")
                formula_text = f_elem.text if f_elem is not None else ""
                v.append({
                    "type": "formula_cell_blue_font",
                    "sheet": sheet_name,
                    "cell": cell_ref,
                    "s": s_idx,
                    "formula": formula_text,
                    "fix": "Formula cells must use black font (formula) or green font (cross-sheet ref). "
                           "Use style index 2/6/8/10 (black) or 3/13 (green) instead.",
                })

            # Check C3: color-role violation — non-formula cell with explicit black
            # (only flag if it looks like it should be an input — has a numeric value)
            if (not has_formula and _is_black_font(font)
                    and value_text is not None
                    and not font.get("bold")
                    and num_fmt_id not in (0,)   # skip general-format black (could be label)
            ):
                try:
                    float(value_text)
                    # It's a numeric value with black font — possible missing blue input marker
                    w.append({
                        "type": "numeric_input_may_lack_blue",
                        "sheet": sheet_name,
                        "cell": cell_ref,
                        "s": s_idx,
                        "value": value_text,
                        "note": "Hardcoded numeric value has black font — if this is a user-editable "
                                "assumption, change to blue-font input style (e.g. s=1/5/7/9/11/12).",
                    })
                except (ValueError, TypeError):
                    pass

            # Check C4: year value with comma-formatted numFmt
            if value_text and _looks_like_year(value_text) and _fmt_is_comma(num_fmt_id, num_fmts):
                v.append({
                    "type": "year_with_comma_format",
                    "sheet": sheet_name,
                    "cell": cell_ref,
                    "s": s_idx,
                    "value": value_text,
                    "numFmtId": num_fmt_id,
                    "fix": "Year values must use numFmtId=1 (format '0') to display as 2024 not 2,024. "
                           "Use style index 11 or a custom xf with numFmtId=1.",
                })

            # Check C5: percentage format with value > 1 (likely 8 instead of 0.08)
            if value_text and _fmt_is_percent(num_fmt_id, num_fmts):
                try:
                    pct_val = float(value_text)
                    if pct_val > 1.0:
                        w.append({
                            "type": "percent_value_gt_1",
                            "sheet": sheet_name,
                            "cell": cell_ref,
                            "s": s_idx,
                            "value": value_text,
                            "displayed_as": f"{pct_val * 100:.0f}%",
                            "note": f"Value {value_text} with percentage format displays as {pct_val*100:.0f}%. "
                                    "If intended rate is ~{:.0f}%, store as {:.4f} instead.".format(
                                        pct_val, pct_val / 100
                                    ),
                        })
                except (ValueError, TypeError):
                    pass

            if has_formula:
                formula_cells += 1
            elif value_text is not None:
                input_cells += 1

    results["summary"] = {
        "total_cells_inspected": total_cells,
        "formula_cells": formula_cells,
        "input_cells": input_cells,
        "violations": len(v),
        "warnings": len(w),
    }

    return results


def _load_from_xlsx(xlsx_path: str) -> tuple[bytes, list[tuple[str, bytes]]]:
    """Load styles.xml and all sheet XMLs from a packed xlsx file."""
    with zipfile.ZipFile(xlsx_path, "r") as z:
        styles_xml = z.read("xl/styles.xml")

        # Get sheet name mapping
        wb_xml = z.read("xl/workbook.xml")
        wb = ET.fromstring(wb_xml)
        rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        rels_xml = z.read("xl/_rels/workbook.xml.rels")
        rels = ET.fromstring(rels_xml)

        rid_to_name = {}
        for sheet in wb.findall(f".//{{{NS}}}sheet"):
            rid = sheet.get(f"{{{rel_ns}}}id", "")
            name = sheet.get("name", "")
            rid_to_name[rid] = name

        rid_to_path = {}
        for rel in rels:
            rid = rel.get("Id", "")
            target = rel.get("Target", "")
            if "worksheets" in target:
                if not target.startswith("xl/"):
                    target = "xl/" + target
                rid_to_path[rid] = target

        sheet_xmls = []
        for rid, name in rid_to_name.items():
            path = rid_to_path.get(rid)
            if path and path in z.namelist():
                sheet_xmls.append((name, z.read(path)))

    return styles_xml, sheet_xmls


def _load_from_dir(unpacked_dir: str) -> tuple[bytes, list[tuple[str, bytes]]]:
    """Load styles.xml and all sheet XMLs from an unpacked directory."""
    styles_path = os.path.join(unpacked_dir, "xl", "styles.xml")
    with open(styles_path, "rb") as f:
        styles_xml = f.read()

    # Get sheet names from workbook.xml
    wb_path = os.path.join(unpacked_dir, "xl", "workbook.xml")
    wb = ET.fromstring(open(wb_path, "rb").read())
    rels_path = os.path.join(unpacked_dir, "xl", "_rels", "workbook.xml.rels")
    rels = ET.fromstring(open(rels_path, "rb").read())

    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rid_to_name = {}
    for sheet in wb.findall(f".//{{{NS}}}sheet"):
        rid = sheet.get(f"{{{rel_ns}}}id", "")
        name = sheet.get("name", "")
        rid_to_name[rid] = name

    rid_to_path = {}
    for rel in rels:
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        if "worksheets" in target:
            rid_to_path[rid] = target

    sheet_xmls = []
    ws_dir = os.path.join(unpacked_dir, "xl", "worksheets")
    for rid, name in rid_to_name.items():
        rel_path = rid_to_path.get(rid, "")
        # rel_path may be "worksheets/sheet1.xml" or absolute path
        if rel_path.startswith("worksheets/"):
            full = os.path.join(unpacked_dir, "xl", rel_path)
        else:
            full = os.path.join(unpacked_dir, "xl", "worksheets", os.path.basename(rel_path))
        if os.path.exists(full):
            with open(full, "rb") as f:
                sheet_xmls.append((name, f.read()))

    return styles_xml, sheet_xmls


def main() -> None:
    use_json = "--json" in sys.argv
    summary_only = "--summary" in sys.argv

    args_clean = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args_clean:
        print("Usage: style_audit.py <input.xlsx | unpacked_dir/> [--json] [--summary]")
        sys.exit(1)

    target = args_clean[0]

    try:
        if os.path.isdir(target):
            styles_xml, sheet_xmls = _load_from_dir(target)
        elif target.endswith(".xlsx") or target.endswith(".xlsm"):
            styles_xml, sheet_xmls = _load_from_xlsx(target)
        else:
            print(f"ERROR: unrecognized target '{target}' — must be .xlsx file or unpacked directory")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR loading file: {e}")
        sys.exit(1)

    results = _audit(styles_xml, sheet_xmls)

    if use_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        sys.exit(1 if results["summary"]["violations"] > 0 else 0)

    # Human-readable output
    s = results["summary"]
    print(f"Target  : {target}")
    print(f"Cells   : {s['total_cells_inspected']} inspected  "
          f"({s['formula_cells']} formula, {s['input_cells']} input)")
    print(f"Violations : {s['violations']}")
    print(f"Warnings   : {s['warnings']}")

    if not summary_only:
        if results["violations"]:
            print("\n── Violations (must fix) ──")
            for item in results["violations"]:
                t = item["type"]
                if t == "count_mismatch":
                    print(f"  [FAIL] {item['element']} count mismatch: declared={item['declared']}, "
                          f"actual={item['actual']}")
                    print(f"         Fix: {item['fix']}")
                elif t == "missing_required_fills":
                    print(f"  [FAIL] {item['detail']}")
                    print(f"         Fix: {item['fix']}")
                elif t in ("fills_0_corrupted", "fills_1_corrupted"):
                    print(f"  [FAIL] {item['detail']}")
                    print(f"         Fix: {item['fix']}")
                elif t == "formula_cell_blue_font":
                    print(f"  [FAIL] [{item['sheet']}!{item['cell']}] formula cell has blue font "
                          f"(role=input, but cell contains formula: {item.get('formula', '')})")
                    print(f"         Fix: {item['fix']}")
                elif t == "style_index_out_of_range":
                    print(f"  [FAIL] [{item['sheet']}!{item['cell']}] s={item['s']} but "
                          f"cellXfs count={item['cellXfs_count']}")
                    print(f"         Fix: {item['fix']}")
                elif t == "font_index_out_of_range":
                    print(f"  [FAIL] [{item['sheet']}!{item['cell']}] fontId={item['fontId']} but "
                          f"fonts count={item['fonts_count']}")
                    print(f"         Fix: {item['fix']}")
                elif t == "year_with_comma_format":
                    print(f"  [FAIL] [{item['sheet']}!{item['cell']}] year value {item['value']} "
                          f"uses comma-format (numFmtId={item['numFmtId']}) — will display as "
                          f"{int(float(item['value'])):,}")
                    print(f"         Fix: {item['fix']}")
                else:
                    print(f"  [FAIL] {item}")

        if results["warnings"] and not summary_only:
            print("\n── Warnings (review recommended) ──")
            for item in results["warnings"]:
                t = item["type"]
                if t == "numeric_input_may_lack_blue":
                    print(f"  [WARN] [{item['sheet']}!{item['cell']}] numeric value={item['value']} "
                          f"has black font — if user-editable assumption, use blue-font input style")
                elif t == "percent_value_gt_1":
                    print(f"  [WARN] [{item['sheet']}!{item['cell']}] percent-format cell has "
                          f"value={item['value']} (displays as {item['displayed_as']}) — "
                          f"likely should be stored as decimal (e.g. 0.08 for 8%)")
                else:
                    print(f"  [WARN] {item}")

    print()
    if s["violations"] == 0:
        if s["warnings"] == 0:
            print("PASS — Financial formatting is compliant")
        else:
            print(f"PASS with WARN — {s['warnings']} warning(s) need review")
    else:
        print(f"FAIL — {s['violations']} violation(s) must be fixed before delivery")
        sys.exit(1)


if __name__ == "__main__":
    main()
