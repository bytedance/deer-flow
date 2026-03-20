#!/usr/bin/env python3
"""
Instrument Data to ASM Converter

Converts laboratory instrument output files to Allotrope Simple Model (ASM) JSON format.
Supports auto-detection of instrument types and fallback parsing for unsupported formats.

Usage:
    python convert_to_asm.py <input_file> [--vendor VENDOR] [--output OUTPUT]
"""

import json
import sys
import re
import hashlib
import importlib.metadata
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from datetime import datetime


# Lazy imports to avoid errors if not installed
def get_allotropy():
    try:
        from allotropy.parser_factory import Vendor
        from allotropy.to_allotrope import allotrope_from_file, allotrope_from_io

        return Vendor, allotrope_from_file, allotrope_from_io
    except ImportError:
        return None, None, None


def get_pandas():
    try:
        import pandas as pd

        return pd
    except ImportError:
        return None


# Detection patterns for instrument identification
DETECTION_PATTERNS = {
    "BECKMAN_VI_CELL_BLU": {
        "columns": [
            "Sample ID",
            "Viable cells",
            "Viability",
            "Total cells",
            "Average diameter",
        ],
        "keywords": ["Vi-CELL BLU", "Beckman Coulter"],
        "file_patterns": [r".*\.csv$"],
        "confidence_boost": 20,
    },
    "BECKMAN_VI_CELL_XR": {
        "columns": ["Sample", "Total cells/ml", "Viable cells/ml", "Viability (%)"],
        "keywords": ["Vi-CELL XR", "Cell Viability Analyzer"],
        "file_patterns": [r".*\.(txt|xls|xlsx)$"],
        "confidence_boost": 20,
    },
    "THERMO_FISHER_NANODROP_EIGHT": {
        "columns": ["Sample Name", "Nucleic Acid Conc.", "A260", "A280", "260/280"],
        "keywords": ["NanoDrop Eight", "NanoDrop 8"],
        "file_patterns": [r".*\.(tsv|txt)$"],
        "confidence_boost": 15,
    },
    "THERMO_FISHER_NANODROP_ONE": {
        "columns": ["Sample Name", "Nucleic Acid(ng/uL)", "A260", "A280"],
        "keywords": ["NanoDrop One", "NanoDrop"],
        "file_patterns": [r".*\.(csv|xlsx)$"],
        "confidence_boost": 15,
    },
    "MOLDEV_SOFTMAX_PRO": {
        "columns": ["Well", "Sample", "Values", "Mean", "SD"],
        "keywords": ["SoftMax Pro", "SpectraMax", "Molecular Devices"],
        "file_patterns": [r".*\.txt$"],
        "confidence_boost": 15,
    },
    "BMG_MARS": {
        "columns": ["Well", "Content", "Conc.", "Mean", "SD", "CV"],
        "keywords": ["BMG LABTECH", "MARS", "CLARIOstar", "PHERAstar"],
        "file_patterns": [r".*\.(csv|txt)$"],
        "confidence_boost": 15,
    },
    "AGILENT_GEN5": {
        "columns": ["Well", "Read", "Time", "Temperature"],
        "keywords": ["Gen5", "BioTek", "Synergy"],
        "file_patterns": [r".*\.xlsx$"],
        "confidence_boost": 15,
    },
    "APPBIO_QUANTSTUDIO": {
        "columns": ["Well", "Sample Name", "Target Name", "CT", "Ct Mean"],
        "keywords": ["QuantStudio", "Applied Biosystems", "qPCR"],
        "file_patterns": [r".*\.xlsx$"],
        "confidence_boost": 15,
    },
}


def detect_instrument_type(
    filepath: str, file_content: Optional[str] = None
) -> Tuple[str, float]:
    """
    Auto-detect instrument type from file contents.

    Returns:
        Tuple of (vendor_name, confidence_score)
        confidence_score is 0-100
    """
    path = Path(filepath)
    filename = path.name.lower()
    extension = path.suffix.lower()

    # Read file content if not provided
    if file_content is None:
        try:
            if extension in [".xlsx", ".xls"]:
                pd = get_pandas()
                if pd:
                    df = pd.read_excel(filepath, nrows=50)
                    file_content = df.to_string() + "\n" + "\n".join(df.columns)
                else:
                    file_content = ""
            else:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read(10000)  # First 10KB
        except Exception as e:
            print(f"Warning: Could not read file for detection: {e}")
            file_content = ""

    content_lower = file_content.lower()
    scores = {}

    for vendor, patterns in DETECTION_PATTERNS.items():
        score = 0

        # Check file extension patterns
        for pattern in patterns.get("file_patterns", []):
            if re.match(pattern, filename, re.IGNORECASE):
                score += 10
                break

        # Check column headers
        columns_found = 0
        for col in patterns.get("columns", []):
            if col.lower() in content_lower:
                columns_found += 1
        if columns_found > 0:
            score += min(50, columns_found * 15)

        # Check keywords
        for keyword in patterns.get("keywords", []):
            if keyword.lower() in content_lower:
                score += patterns.get("confidence_boost", 10)

        scores[vendor] = min(100, score)

    # Return best match
    if scores:
        best = max(scores.items(), key=lambda x: x[1])
        return best[0], best[1]

    return "UNKNOWN", 0


def convert_with_allotropy(filepath: str, vendor_name: str) -> Optional[Dict[str, Any]]:
    """
    Convert file using allotropy library.

    Returns:
        ASM dictionary or None if conversion fails
    """
    Vendor, allotrope_from_file, _ = get_allotropy()

    if Vendor is None:
        print(
            "Warning: allotropy not installed. Run: pip install allotropy --break-system-packages"
        )
        return None

    try:
        vendor = getattr(Vendor, vendor_name, None)
        if vendor is None:
            print(f"Warning: Vendor {vendor_name} not found in allotropy")
            return None

        asm = allotrope_from_file(filepath, vendor)
        return asm
    except Exception as e:
        print(f"Allotropy conversion failed: {e}")
        return None


def get_deterministic_timestamp(filepath: str) -> str:
    """
    Get deterministic timestamp for file.
    Uses file modification time for reproducibility.

    Returns:
        ISO format timestamp string
    """
    try:
        path = Path(filepath)
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).isoformat()
    except Exception:
        return "TIMESTAMP_NOT_AVAILABLE"


def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA256 hash of file for provenance tracking."""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return "HASH_NOT_AVAILABLE"


def get_library_version(library: str) -> str:
    """Get version of installed library."""
    try:
        return importlib.metadata.version(library)
    except Exception:
        return "VERSION_NOT_AVAILABLE"


def add_provenance_metadata(
    asm: Dict[str, Any],
    filepath: str,
    vendor: str,
    confidence: float,
    used_fallback: bool,
    warnings: list = None,
) -> Dict[str, Any]:
    """
    Add provenance metadata to ASM for reproducibility and audit trail.

    This metadata enables:
    - Reproducing conversions months later
    - Determining which version generated data
    - Auditing data lineage for regulatory compliance
    """
    pd = get_pandas()

    asm["$conversion_metadata"] = {
        "skill_version": "1.0.0",
        "allotropy_version": get_library_version("allotropy"),
        "pandas_version": pd.__version__ if pd else "NOT_INSTALLED",
        "conversion_timestamp_utc": datetime.utcnow().isoformat(),
        "input_file_sha256": calculate_file_hash(filepath),
        "input_file_size_bytes": Path(filepath).stat().st_size,
        "input_file_name": Path(filepath).name,
        "parser_used": "fallback" if used_fallback else "allotropy",
        "detection_confidence": confidence,
        "vendor_detected": vendor,
        "warnings": warnings or [],
    }

    return asm


def flexible_parse(filepath: str, detected_type: str) -> Optional[Dict[str, Any]]:
    """
    Flexible fallback parser when allotropy fails.
    Creates ASM-like structure from parsed data.

    **WARNING:** This parser creates simplified ASM that:
    - Does NOT distinguish raw vs. calculated data
    - LACKS instrument control parameters (temperature, wavelengths, etc.)
    - MAY NOT be compatible with regulatory requirements (GxP)
    - Should be used for exploratory analysis only, not production LIMS import
    """
    pd = get_pandas()
    if pd is None:
        print("Warning: pandas not installed for flexible parsing")
        return None

    path = Path(filepath)
    extension = path.suffix.lower()

    try:
        # Read file based on extension
        if extension in [".xlsx", ".xls"]:
            df = pd.read_excel(filepath, engine="openpyxl")
        elif extension == ".tsv":
            df = pd.read_csv(filepath, sep="\t")
        elif extension == ".csv":
            df = pd.read_csv(filepath)
        else:
            df = pd.read_csv(filepath, sep=None, engine="python")

        # Build ASM-like structure
        asm = build_flexible_asm(df, detected_type, filepath)
        return asm

    except Exception as e:
        print(f"Flexible parsing failed: {e}")
        return None


def build_flexible_asm(df, detected_type: str, filepath: str) -> Dict[str, Any]:
    """
    Build ASM-like JSON structure from parsed DataFrame.
    """
    timestamp = get_deterministic_timestamp(filepath)

    # Determine technique from detected type
    technique = "generic"
    if "VI_CELL" in detected_type:
        technique = "cell-counting"
    elif "NANODROP" in detected_type:
        technique = "spectrophotometry"
    elif detected_type in ["MOLDEV_SOFTMAX_PRO", "BMG_MARS", "AGILENT_GEN5"]:
        technique = "plate-reader"
    elif "QUANTSTUDIO" in detected_type:
        technique = "pcr"

    # Build base structure
    asm = {
        "$asm.manifest": {
            "vocabulary": ["http://purl.allotrope.org/voc/afo/REC/2023/09/"],
            "contexts": [
                "http://purl.allotrope.org/json-ld/afo-context-REC-2023-09.jsonld"
            ],
        },
        f"{technique}-aggregate-document": {
            "device-system-document": {
                "device-identifier": "FLEXIBLE_PARSER",
                "product-manufacturer": (
                    detected_type.split("_")[0] if "_" in detected_type else "Unknown"
                ),
            },
            f"{technique}-document": [
                {
                    "measurement-aggregate-document": {
                        "measurement-time": timestamp,
                        "measurement-document": [],
                    }
                }
            ],
        },
    }

    # Add measurements from DataFrame
    measurements = asm[f"{technique}-aggregate-document"][f"{technique}-document"][0][
        "measurement-aggregate-document"
    ]["measurement-document"]

    for _, row in df.iterrows():
        meas = {}
        for col in df.columns:
            value = row[col]
            if pd.notna(value):
                # Clean column name
                clean_col = str(col).lower().replace(" ", "-").replace("_", "-")
                clean_col = re.sub(r"[^a-z0-9-]", "", clean_col)

                # Handle numeric values
                if isinstance(value, (int, float)):
                    meas[clean_col] = {"value": value, "unit": "(unitless)"}
                else:
                    meas[clean_col] = str(value)

        if meas:
            measurements.append(meas)

    return asm


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert instrument data to ASM format"
    )
    parser.add_argument("input", help="Input file path")
    parser.add_argument(
        "--vendor", help="Vendor enum name (auto-detected if not provided)"
    )
    parser.add_argument(
        "--output", "-o", help="Output file path (default: input_asm.json)"
    )
    parser.add_argument(
        "--flatten", action="store_true", help="Also generate flattened CSV"
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow fallback to simplified parser (reduced metadata)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip automatic validation (not recommended)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force conversion even with low confidence detection",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    warnings = []

    # Detect or use provided vendor
    if args.vendor:
        vendor = args.vendor.upper()
        confidence = 100
        print(f"Using specified vendor: {vendor}")
    else:
        vendor, confidence = detect_instrument_type(str(input_path))
        print(f"Detected instrument: {vendor} (confidence: {confidence}%)")

        # Enforce confidence thresholds
        if confidence < 30:
            print(
                f"ERROR: Detection confidence too low ({confidence}%). Cannot proceed."
            )
            print("Please specify --vendor explicitly.")
            sys.exit(1)
        elif confidence < 60:
            warning_msg = f"WARNING: Low confidence detection ({confidence}%)."
            print(warning_msg)
            warnings.append(warning_msg)
            if not args.force:
                print("Use --force to proceed anyway (not recommended).")
                sys.exit(1)

    # Try allotropy first
    asm = convert_with_allotropy(str(input_path), vendor)
    used_fallback = False

    # Fall back to flexible parser
    if asm is None:
        print("\n" + "=" * 60)
        print("ALLOTROPY PARSING FAILED - USING REDUCED METADATA PARSER")
        print("=" * 60)
        print("Output will lack:")
        print("  - Calculated data traceability")
        print("  - Device control settings")
        print("  - Data processing metadata")
        print("\nNot suitable for:")
        print("  - Regulatory submissions")
        print("  - LIMS import with validation")
        print("=" * 60 + "\n")

        if not args.allow_fallback:
            print(
                "ERROR: Allotropy parsing failed. Use --allow-fallback to continue with"
            )
            print("simplified parser, but note that output will lack required metadata")
            print("for GxP compliance.")
            sys.exit(1)

        asm = flexible_parse(str(input_path), vendor)
        used_fallback = True
        warnings.append("Used fallback parser - reduced metadata")

    if asm is None:
        print("Error: Could not convert file")
        sys.exit(1)

    # Add provenance metadata
    asm = add_provenance_metadata(
        asm, str(input_path), vendor, confidence, used_fallback, warnings
    )

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(".asm.json")

    # Write to temporary file first
    temp_path = output_path.with_suffix(".tmp")

    try:
        with open(temp_path, "w") as f:
            json.dump(asm, f, indent=2, default=str)

        # Validate unless skipped
        if not args.skip_validation:
            print("Running validation...")
            try:
                from validate_asm import validate_asm

                result = validate_asm(str(temp_path))

                if not result.is_valid():
                    print("\n" + "=" * 60)
                    print("VALIDATION FAILED")
                    print("=" * 60)
                    for error in result.errors:
                        print(f"ERROR: {error}")
                    for warning in result.warnings:
                        print(f"WARNING: {warning}")
                    print("=" * 60)

                    # Remove temp file
                    temp_path.unlink()
                    print("\nValidation failed. Output file not created.")
                    sys.exit(1)
                else:
                    if result.warnings:
                        print("\nValidation warnings:")
                        for warning in result.warnings:
                            print(f"  WARNING: {warning}")
                    print("Validation passed.")
            except ImportError:
                print(
                    "Warning: validate_asm.py not found. Skipping validation. "
                    "Consider adding validation script."
                )

        # Move temp file to final location
        temp_path.replace(output_path)
        print(f"ASM output written to: {output_path}")

    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        raise e

    # Optionally flatten
    if args.flatten:
        from flatten_asm import flatten_asm_to_csv

        flat_path = input_path.with_suffix(".flat.csv")
        flatten_asm_to_csv(asm, str(flat_path))
        print(f"Flattened CSV written to: {flat_path}")


if __name__ == "__main__":
    main()
