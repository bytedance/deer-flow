#!/usr/bin/env python3
"""
fill_write.py — Write values into PDF form fields.

Usage:
    # From a JSON data file
    python3 fill_write.py --input form.pdf --data values.json --out filled.pdf

    # Inline JSON
    python3 fill_write.py --input form.pdf --out filled.pdf \
        --values '{"FirstName": "Jane", "Agree": "true"}'

values format:
    {
      "FieldName":  "text value",          # text field
      "CheckBox1":  "true",                # checkbox  (true / false)
      "Dropdown1":  "OptionValue",         # dropdown  (must match an existing choice value)
      "Radio1":     "/Choice2"             # radio     (must match a radio value)
    }

Exit codes: 0 success, 1 bad args, 2 dep missing, 3 read/write error, 4 validation error
"""

import argparse
import json
import os
import sys
import importlib.util




def ensure_deps():
    if importlib.util.find_spec("pypdf") is None:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "pypdf"]
        )


ensure_deps()
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject, BooleanObject


# ── Field helpers ─────────────────────────────────────────────────────────────
def _field_type(field) -> str:
    ft = str(field.get("/FT", ""))
    if ft == "/Tx":  return "text"
    if ft == "/Btn":
        ff = int(field.get("/Ff", 0))
        return "radio" if ff & (1 << 15) else "checkbox"
    if ft == "/Ch":
        ff = int(field.get("/Ff", 0))
        return "dropdown" if ff & (1 << 17) else "listbox"
    return "unknown"


def _get_checkbox_on_value(field) -> str:
    """Return the /AP /N key that means 'checked' (anything except /Off)."""
    ap = field.get("/AP")
    if ap and "/N" in ap:
        for k in ap["/N"]:
            if str(k) != "/Off":
                return str(k)
    return "/Yes"


def _get_dropdown_values(field) -> list[str]:
    opt = field.get("/Opt")
    if not opt:
        return []
    values = []
    for item in opt:
        try:
            from pypdf.generic import ArrayObject
            if isinstance(item, (list, ArrayObject)) and len(item) >= 1:
                values.append(str(item[0]))
            else:
                values.append(str(item))
        except Exception:
            values.append(str(item))
    return values


# ── Walk + fill ───────────────────────────────────────────────────────────────
def _walk_and_fill(fields, data: dict, filled: list, errors: list, parent: str = ""):
    for field in fields:
        name = str(field.get("/T", ""))
        full = f"{parent}.{name}" if parent else name

        # Recurse into named groups
        kids = field.get("/Kids")
        if kids:
            named = [k for k in kids if "/T" in k]
            if named:
                _walk_and_fill(named, data, filled, errors, full)
                continue

        if full not in data:
            continue

        value   = data[full]
        ftype   = _field_type(field)

        if ftype == "text":
            field.update({
                NameObject("/V"):  TextStringObject(str(value)),
                NameObject("/DV"): TextStringObject(str(value)),
            })
            filled.append(full)

        elif ftype == "checkbox":
            truthy = str(value).lower() in ("true", "1", "yes", "on")
            on_val = _get_checkbox_on_value(field)
            pdf_val = on_val if truthy else "/Off"
            field.update({
                NameObject("/V"):  NameObject(pdf_val),
                NameObject("/AS"): NameObject(pdf_val),
            })
            filled.append(full)

        elif ftype in ("dropdown", "listbox"):
            allowed = _get_dropdown_values(field)
            if allowed and str(value) not in allowed:
                errors.append({
                    "field": full,
                    "error": f"Value '{value}' not in allowed choices: {allowed}"
                })
                continue
            field.update({NameObject("/V"): TextStringObject(str(value))})
            filled.append(full)

        elif ftype == "radio":
            # Radio value must start with /
            pdf_val = str(value) if str(value).startswith("/") else f"/{value}"
            field.update({
                NameObject("/V"):  NameObject(pdf_val),
                NameObject("/AS"): NameObject(pdf_val),
            })
            filled.append(full)

        else:
            errors.append({"field": full, "error": f"Unsupported field type: {ftype}"})


def fill(pdf_path: str, out_path: str, data: dict) -> dict:
    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    acroform = writer._root_object.get("/AcroForm")  # type: ignore[attr-defined]
    if acroform is None or "/Fields" not in acroform:
        return {
            "status": "error",
            "error":  "This PDF has no fillable form fields.",
            "hint":   "Run fill_inspect.py first to confirm the PDF has fields.",
        }

    # Enable appearance regeneration so viewers show the new values
    acroform.update({NameObject("/NeedAppearances"): BooleanObject(True)})

    filled: list[str] = []
    errors: list[dict] = []
    _walk_and_fill(list(acroform["/Fields"]), data, filled, errors)

    # Warn about requested fields that were never found
    not_found = [k for k in data if k not in filled and not any(e["field"] == k for e in errors)]

    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        return {"status": "error", "error": f"Write failed: {e}"}

    result = {
        "status":        "ok",
        "out":           out_path,
        "filled_count":  len(filled),
        "filled_fields": filled,
        "size_kb":       os.path.getsize(out_path) // 1024,
    }
    if errors:
        result["validation_errors"] = errors
    if not_found:
        result["not_found"] = not_found
        result["hint"] = "Run fill_inspect.py to see all available field names."
    return result


def main():
    parser = argparse.ArgumentParser(description="Fill PDF form fields")
    parser.add_argument("--input",  required=True, help="Input PDF with form fields")
    parser.add_argument("--out",    required=True, help="Output PDF path")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--data",   help="Path to JSON file with field values")
    group.add_argument("--values", help="Inline JSON string with field values")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(json.dumps({"status": "error", "error": f"File not found: {args.input}"}),
              file=sys.stderr)
        sys.exit(1)

    # Load data
    try:
        if args.data:
            with open(args.data) as f:
                data = json.load(f)
        else:
            data = json.loads(args.values)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"JSON parse error: {e}"}),
              file=sys.stderr)
        sys.exit(1)

    result = fill(args.input, args.out, data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "ok":
        print(f"\n── Fill complete ───────────────────────────────────────",
              file=sys.stderr)
        print(f"  Output : {result['out']}", file=sys.stderr)
        print(f"  Filled : {result['filled_count']} field(s)", file=sys.stderr)
        if result.get("validation_errors"):
            print(f"  Errors :", file=sys.stderr)
            for e in result["validation_errors"]:
                print(f"    • {e['field']}: {e['error']}", file=sys.stderr)
        if result.get("not_found"):
            print(f"  Not found: {result['not_found']}", file=sys.stderr)
        print("", file=sys.stderr)
    else:
        sys.exit(3)


if __name__ == "__main__":
    main()
