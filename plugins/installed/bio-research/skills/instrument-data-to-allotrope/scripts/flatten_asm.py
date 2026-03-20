#!/usr/bin/env python3
"""
Flatten ASM JSON to 2D CSV

Converts hierarchical Allotrope Simple Model (ASM) JSON to flat tabular format
suitable for LIMS import, spreadsheet analysis, or database loading.

Usage:
    python flatten_asm.py <input_asm.json> [--output OUTPUT.csv]
"""

import json
import sys
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def detect_technique(asm: Dict[str, Any]) -> str:
    """Detect the ASM technique type from document structure."""
    for key in asm.keys():
        if key.endswith("-aggregate-document"):
            return key.replace("-aggregate-document", "")
    return "generic"


def flatten_value(value: Any, prefix: str = "") -> Dict[str, Any]:
    """
    Flatten a single ASM value, handling value datum patterns.

    Returns dict of {column_name: value}
    """
    result = {}

    if isinstance(value, dict):
        if "value" in value:
            # Value datum pattern
            result[prefix] = value["value"]
            if "unit" in value:
                result[f"{prefix}_unit"] = value["unit"]
        else:
            # Nested dict - recurse
            for k, v in value.items():
                clean_key = k.replace("-", "_")
                nested_prefix = f"{prefix}_{clean_key}" if prefix else clean_key
                result.update(flatten_value(v, nested_prefix))
    elif isinstance(value, list):
        # Array - could be data cube or list of items
        if len(value) > 0 and isinstance(value[0], dict):
            # List of objects - this shouldn't happen at leaf level
            result[prefix] = json.dumps(value)
        else:
            # Simple array - store as JSON string
            result[prefix] = json.dumps(value)
    else:
        # Scalar value
        result[prefix] = value

    return result


def extract_device_info(asm: Dict[str, Any], technique: str) -> Dict[str, Any]:
    """Extract device/instrument information from ASM."""
    agg_key = f"{technique}-aggregate-document"
    agg_doc = asm.get(agg_key, {})

    device = agg_doc.get("device-system-document", {})

    return {
        "instrument_serial_number": device.get("device-identifier"),
        "instrument_model": device.get("model-number"),
        "instrument_manufacturer": device.get("product-manufacturer"),
        "software_name": device.get("software-name"),
        "software_version": device.get("software-version"),
    }


def flatten_asm(asm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten ASM JSON to list of row dictionaries.

    Each measurement becomes one row with metadata repeated.
    """
    technique = detect_technique(asm)
    rows = []

    # Extract device info (shared across all rows)
    device_info = extract_device_info(asm, technique)
    device_info = {k: v for k, v in device_info.items() if v is not None}

    # Navigate to measurements
    agg_key = f"{technique}-aggregate-document"
    agg_doc = asm.get(agg_key, {})

    doc_key = f"{technique}-document"
    technique_docs = agg_doc.get(doc_key, [])

    for doc in technique_docs:
        # Get measurement aggregate
        meas_agg = doc.get("measurement-aggregate-document", {})

        # Extract common measurement metadata
        common_meta = {}
        for key, value in meas_agg.items():
            if key == "measurement-document":
                continue
            clean_key = key.replace("-", "_")
            if isinstance(value, (str, int, float, bool)):
                common_meta[clean_key] = value
            elif isinstance(value, dict) and "value" in value:
                common_meta[clean_key] = value["value"]
                if "unit" in value:
                    common_meta[f"{clean_key}_unit"] = value["unit"]

        # Extract each measurement as a row
        measurements = meas_agg.get("measurement-document", [])
        for meas in measurements:
            row = {**device_info, **common_meta}

            for key, value in meas.items():
                clean_key = key.replace("-", "_")
                flattened = flatten_value(value, clean_key)
                row.update(flattened)

            rows.append(row)

    return rows


def flatten_asm_to_csv(asm: Dict[str, Any], output_path: str) -> None:
    """
    Flatten ASM and write to CSV file.

    Args:
        asm: Parsed ASM JSON dictionary
        output_path: Path for output CSV
    """
    if not PANDAS_AVAILABLE:
        raise ImportError(
            "pandas is required for CSV output. Install with: pip install pandas"
        )

    rows = flatten_asm(asm)

    if not rows:
        print("Warning: No measurements found to flatten")
        # Create empty CSV with header
        with open(output_path, "w") as f:
            f.write("# No measurements found in ASM\n")
        return

    df = pd.DataFrame(rows)

    # Reorder columns for readability
    priority_cols = [
        "sample_identifier",
        "sample_id",
        "well_location",
        "well_position",
        "measurement_time",
        "measurement_datetime",
        "analyst",
    ]

    ordered_cols = []
    for col in priority_cols:
        if col in df.columns:
            ordered_cols.append(col)

    remaining = [c for c in df.columns if c not in ordered_cols]
    df = df[ordered_cols + remaining]

    df.to_csv(output_path, index=False)


def flatten_asm_to_dict(asm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten ASM and return as dictionary with rows and columns.

    Useful for non-CSV outputs or further processing.
    """
    rows = flatten_asm(asm)

    if not rows:
        return {"columns": [], "rows": []}

    columns = list(rows[0].keys())
    return {
        "columns": columns,
        "rows": [[row.get(col) for col in columns] for row in rows],
    }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Flatten ASM JSON to CSV")
    parser.add_argument("input", help="Input ASM JSON file")
    parser.add_argument(
        "--output", "-o", help="Output CSV path (default: input_flat.csv)"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    # Load ASM
    with open(input_path) as f:
        asm = json.load(f)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        suffix = ".flat.csv" if args.format == "csv" else ".flat.json"
        output_path = str(input_path.with_suffix("")) + suffix

    # Flatten and write
    if args.format == "csv":
        flatten_asm_to_csv(asm, output_path)
    else:
        result = flatten_asm_to_dict(asm)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

    print(f"Flattened output written to: {output_path}")

    # Report stats
    rows = flatten_asm(asm)
    print(f"  Rows: {len(rows)}")
    if rows:
        print(f"  Columns: {len(rows[0])}")


if __name__ == "__main__":
    main()
