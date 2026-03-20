#!/usr/bin/env python3
"""
ASM Output Validation Script

Validates ASM JSON output against common issues:
- Wrong technique selection
- Hyphenated field names (should be space-separated)
- Missing statistics documents
- Incorrect units
- Missing required fields
- Missing calculated data traceability
- Improperly flattened nested documents (sample document, device control, etc.)

Validation Rules:
    Based on: Allotrope ASM specification (December 2024)
    Last Updated: 2026-01-07
    Source: https://gitlab.com/allotrope-public/asm/-/tree/main/json-schemas/adm

Note: Unknown techniques/units generate WARNINGS (not errors) to allow for new
additions to the Allotrope specification. This prevents blocking valid data
when the Allotrope foundation adds new techniques or units.

Usage:
    python validate_asm.py output.json
    python validate_asm.py output.json --reference reference.json
    python validate_asm.py output.json --strict
"""

import json
import re
import sys
import argparse
from typing import Dict, List, Tuple, Any, Optional

# Validation metadata
ASM_SPEC_VERSION = "2024-12"
VALIDATION_RULES_DATE = "2026-01-07"
SCHEMA_SOURCE = "https://gitlab.com/allotrope-public/asm"


# All valid ASM techniques from https://gitlab.com/allotrope-public/asm/-/tree/main/json-schemas/adm
VALID_TECHNIQUES = [
    "absorbance",
    "automated-reactors",
    "balance",
    "bga",
    "binding-affinity",
    "bulk-density",
    "cell-counting",
    "cell-culture-analyzer",
    "chromatography",
    "code-reader",
    "conductance",
    "conductivity",
    "disintegration",
    "dsc",
    "dvs",
    "electronic-lab-notebook",
    "electronic-spectrometry",
    "electrophoresis",
    "flow-cytometry",
    "fluorescence",
    "foam-height",
    "foam-qualification",
    "fplc",
    "ftir",
    "gas-chromatography",
    "gc-ms",
    "gloss",
    "hot-tack",
    "impedance",
    "lc-ms",
    "light-obscuration",
    "liquid-chromatography",
    "liquid-handler",  # Added for liquid handler support
    "loss-on-drying",
    "luminescence",
    "mass-spectrometry",
    "metabolite-analyzer",
    "multi-analyte-profiling",
    "nephelometry",
    "nmr",
    "optical-imaging",
    "optical-microscopy",
    "osmolality",
    "oven-kf",
    "pcr",
    "ph",
    "plate-reader",
    "pressure-monitoring",
    "psd",
    "pumping",
    "raman",
    "rheometry",
    "sem",
    "solution-analyzer",
    "specific-rotation",
    "spectrophotometry",
    "stirring",
    "surface-area-analysis",
    "tablet-hardness",
    "temperature-monitoring",
    "tensile-test",
    "thermogravimetric-analysis",
    "titration",
    "ultraviolet-absorbance",
    "x-ray-powder-diffraction",
]

# Instrument keywords that indicate specific techniques
TECHNIQUE_INDICATORS = {
    "multi-analyte-profiling": [
        "bead",
        "luminex",
        "bio-plex",
        "bioplex",
        "multiplex",
        "plex",
        "msd",
        "region",
    ],
    "electrophoresis": [
        "tapestation",
        "bioanalyzer",
        "labchip",
        "fragment",
        "din",
        "rin",
        "gel",
        "capillary",
    ],
    "spectrophotometry": ["nanodrop", "lunatic", "a260", "a280", "wavelength"],
    "cell-counting": [
        "viability",
        "viable cell",
        "cell count",
        "vi-cell",
        "vicell",
        "nucleocounter",
        "cell density",
    ],
    "pcr": [
        "ct",
        "quantstudio",
        "cfx",
        "amplification",
        "melt curve",
        "qpcr",
        "cycle threshold",
    ],
    "plate-reader": [
        "microplate",
        "96-well",
        "384-well",
        "plate reader",
        "envision",
        "spectramax",
    ],
    "liquid-chromatography": [
        "hplc",
        "uplc",
        "retention time",
        "chromatogram",
        "empower",
        "chromeleon",
    ],
    "flow-cytometry": ["facs", "flow cytometry", "scatter", "gating", "cytometer"],
    "mass-spectrometry": ["m/z", "mass spec", "ms/ms", "lcms", "maldi"],
    "fluorescence": ["fluorescence", "excitation", "emission", "fluorimeter"],
    "luminescence": ["luminescence", "bioluminescence", "chemiluminescence"],
    "absorbance": ["absorbance", "optical density", "od600"],
    "ph": ["ph meter", "ph measurement"],
    "osmolality": ["osmolality", "osmometer"],
    "conductivity": ["conductivity", "conductance"],
    "balance": ["balance", "weight", "mass measurement"],
    "nmr": ["nmr", "nuclear magnetic resonance"],
    "ftir": ["ftir", "infrared", "ir spectrum"],
    "raman": ["raman", "raman spectroscopy"],
    "liquid-handler": [
        "biomek",
        "liquid handler",
        "aspirate",
        "dispense",
        "transfer volume",
        "liquid handling",
    ],
}

# Fields that should typically be in calculated-data-document, not measurement-document
SHOULD_BE_CALCULATED = [
    "dna integrity number",
    "rna integrity number",
    "din",
    "rin",
    "viability",
    "260/280",
    "a260/a280",
    "concentration",  # When derived from standard curve
    "percent of total",
    "average size",
    "molarity",  # When calculated from concentration
    "relative quantity",
    "fold change",
    "coefficient of variation",
]

# =============================================================================
# NESTED DOCUMENT STRUCTURE DEFINITIONS
# =============================================================================

# Fields that MUST be inside 'sample document' (space or hyphen separated)
SAMPLE_DOCUMENT_FIELDS = {
    # Core sample identification
    "sample identifier",
    "sample-identifier",
    "written name",
    "written-name",
    "batch identifier",
    "batch-identifier",
    "sample role type",
    "sample-role-type",
    "description",
    # Location fields (should be in sample document for most techniques)
    "location identifier",
    "location-identifier",
    "well location identifier",
    "well-location-identifier",
    "well plate identifier",
    "well-plate-identifier",
    # Liquid handler specific - source/destination pairs
    "source location identifier",
    "source-location-identifier",
    "destination location identifier",
    "destination-location-identifier",
    "source well plate identifier",
    "source-well-plate-identifier",
    "destination well plate identifier",
    "destination-well-plate-identifier",
    "source well location identifier",
    "source-well-location-identifier",
    "destination well location identifier",
    "destination-well-location-identifier",
}

# Fields that MUST be inside 'device control aggregate document' -> 'device control document'
DEVICE_CONTROL_FIELDS = {
    # General device control
    "device type",
    "device-type",
    "detector wavelength setting",
    "detector-wavelength-setting",
    "compartment temperature",
    "compartment-temperature",
    "sample volume setting",
    "sample-volume-setting",
    "flow rate",
    "flow-rate",
    "exposure duration setting",
    "exposure-duration-setting",
    "detector gain setting",
    "detector-gain-setting",
    "illumination setting",
    "illumination-setting",
    # Liquid handler specific
    "liquid handling technique",
    "liquid-handling-technique",
    "source liquid handling technique",
    "source-liquid-handling-technique",
    "destination liquid handling technique",
    "destination-liquid-handling-technique",
}

# Fields that should be in 'custom information document' (vendor-specific)
CUSTOM_INFO_FIELDS = {
    # Liquid handler specific
    "probe",
    "pod",
    "source labware name",
    "source-labware-name",
    "destination labware name",
    "destination-labware-name",
    "deck position",
    "deck-position",
}

# Fields that commonly get incorrectly flattened (superset for general checking)
COMMONLY_FLATTENED_FIELDS = {
    # Sample-related (often incorrectly put directly on measurement)
    "sample identifier",
    "sample-identifier",
    "sample barcode",
    "sample-barcode",
    "well index",
    "well-index",
    "location identifier",
    "location-identifier",
    # Device control related (often incorrectly put directly on measurement)
    "probe identifier",
    "probe-identifier",
    "device identifier",  # When it should be in device control doc, not measurement
    "device-identifier",
    "technique",  # Should be "liquid handling technique" in device control
    "transfer type",  # Should be structured differently
    "transfer-type",
}

# Standard ASM units
VALID_UNITS = {
    "fluorescence": ["RFU", "MFI", "(unitless)"],
    "counts": ["#"],
    "volume": ["μL", "mL", "L", "µL"],
    "concentration": [
        "ng/μL",
        "ng/mL",
        "pg/mL",
        "mg/mL",
        "μg/mL",
        "M",
        "mM",
        "μM",
        "nM",
    ],
    "temperature": ["degC"],
    "unitless": ["(unitless)", "%"],
    "molecular_weight": ["bp", "Da", "kDa"],
    "time": ["s", "min", "h"],
}

# Standard sample role types
VALID_SAMPLE_ROLES = [
    "standard sample role",
    "blank role",
    "control sample role",
    "unknown sample role",
    "reference sample role",
    "calibration sample role",
]

# Standard statistic datum roles
VALID_STATISTIC_ROLES = [
    "median role",
    "arithmetic mean role",
    "coefficient of variation role",
    "standard deviation role",
    "standard error role",
    "trimmed arithmetic mean role",
    "trimmed standard deviation role",
    "minimum value role",
    "maximum value role",
]


class ValidationResult:
    """Container for validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        self.metrics: Dict[str, Any] = {}

    def add_error(self, msg: str):
        self.errors.append(f"ERROR: {msg}")

    def add_warning(self, msg: str):
        self.warnings.append(f"WARNING: {msg}")

    def add_info(self, msg: str):
        self.info.append(f"INFO: {msg}")

    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def print_report(self):
        print("\n" + "=" * 60)
        print("ASM VALIDATION REPORT")
        print("=" * 60)

        # Print metrics
        if self.metrics:
            print("\nMetrics:")
            for key, value in self.metrics.items():
                print(f"   {key}: {value}")

        # Print info
        if self.info:
            print("\n" + "\n".join(self.info))

        # Print warnings
        if self.warnings:
            print("\n" + "\n".join(self.warnings))

        # Print errors
        if self.errors:
            print("\n" + "\n".join(self.errors))

        # Summary
        print("\n" + "-" * 60)
        if self.is_valid():
            if self.warnings:
                print(f"PASSED with {len(self.warnings)} warning(s)")
            else:
                print("PASSED - No issues found")
        else:
            print(
                f"FAILED - {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
            )
        print("=" * 60 + "\n")


def validate_manifest(asm: Dict, result: ValidationResult):
    """Check for valid manifest."""
    if "$asm.manifest" not in asm:
        result.add_error("Missing $asm.manifest")
        return

    manifest = asm["$asm.manifest"]
    if isinstance(manifest, str):
        if "allotrope.org" in manifest:
            result.add_info(f"Manifest: {manifest}")
        else:
            result.add_warning(f"Non-standard manifest URL: {manifest}")
    elif isinstance(manifest, dict):
        if "vocabulary" in manifest or "contexts" in manifest:
            result.add_info("Manifest: Object format with vocabulary/contexts")
        else:
            result.add_warning("Manifest object missing vocabulary or contexts")


def detect_technique(asm: Dict) -> Tuple[str, float]:
    """Detect technique from ASM structure."""
    # Check for technique in top-level keys
    for key in asm.keys():
        if key == "$asm.manifest":
            continue
        # Extract technique name from aggregate document key
        # Handle both "liquid handler aggregate document" and "liquid-handler-aggregate-document"
        key_normalized = key.lower().replace("-", " ")
        if "aggregate document" in key_normalized:
            technique = key_normalized.replace(" aggregate document", "").strip()
            return technique, 100.0

    return "unknown", 0.0


def validate_technique(asm: Dict, result: ValidationResult, content_str: str):
    """Validate technique selection."""
    technique, confidence = detect_technique(asm)
    result.metrics["technique"] = technique
    result.metrics["technique_confidence"] = confidence

    if technique == "unknown":
        result.add_warning("Could not detect technique from ASM structure")
        return

    result.add_info(f"Detected technique: {technique}")

    # Check if technique is in known list (soft validation)
    technique_normalized = technique.replace(" ", "-")
    if technique_normalized not in VALID_TECHNIQUES:
        result.add_warning(
            f"Unknown technique '{technique}' not in known list (as of {VALIDATION_RULES_DATE}). "
            f"This may be a new Allotrope addition. Verify at: {SCHEMA_SOURCE}"
        )

    # Check if technique seems appropriate for content
    content_lower = content_str.lower()
    suggested_technique = None

    for tech, keywords in TECHNIQUE_INDICATORS.items():
        matches = sum(1 for kw in keywords if kw in content_lower)
        if matches >= 2:  # Multiple keyword matches
            if tech != technique.replace(" ", "-"):
                suggested_technique = tech
                break

    if suggested_technique:
        result.add_warning(
            f"Content suggests '{suggested_technique}' but ASM uses '{technique}' - "
            "verify correct technique selection"
        )


def validate_naming_conventions(content_str: str, result: ValidationResult):
    """Check for proper space-separated naming (not hyphens)."""
    # Find all keys that look like ASM field names
    # Hyphenated keys in ASM are typically wrong (should be space-separated)
    hyphenated_keys = re.findall(r'"([a-z]+-[a-z]+-?[a-z]*-?[a-z]*)":', content_str)

    # Filter to likely ASM fields (not URLs, not manifest)
    asm_hyphenated = []
    for key in hyphenated_keys:
        if "http" in key or "manifest" in key:
            continue
        # Known hyphenated keys that are OK
        if key in ["data-source-identifier", "data-source-feature"]:
            continue
        asm_hyphenated.append(key)

    if asm_hyphenated:
        unique = list(set(asm_hyphenated))[:10]
        result.add_warning(
            f"Found hyphenated field names (ASM uses spaces): {unique}"
            + (" ... and more" if len(set(asm_hyphenated)) > 10 else "")
        )
        result.add_info("Tip: Use 'sample identifier' not 'sample-identifier'")


def count_measurements(content_str: str) -> int:
    """Count measurement documents in ASM."""
    # Count occurrences of measurement document patterns
    count = len(re.findall(r'"measurement identifier":', content_str))
    if count == 0:
        count = len(re.findall(r'"measurement-identifier":', content_str))
    return count


def validate_measurements(content_str: str, result: ValidationResult):
    """Validate measurement documents."""
    count = count_measurements(content_str)
    result.metrics["measurement_count"] = count

    if count == 0:
        result.add_warning("No measurement documents found")
    else:
        result.add_info(f"Measurement count: {count}")


def validate_sample_roles(content_str: str, result: ValidationResult):
    """Check for valid sample roles."""
    roles = re.findall(r'"sample.role.type":\s*"([^"]+)"', content_str)
    if not roles:
        roles = re.findall(r'"sample role type":\s*"([^"]+)"', content_str)

    if roles:
        unknown_roles = [r for r in set(roles) if r not in VALID_SAMPLE_ROLES]
        if unknown_roles:
            result.add_warning(
                f"Unknown sample roles not in known list (as of {VALIDATION_RULES_DATE}): {unknown_roles}. "
                f"These may be valid Allotrope roles added after spec version {ASM_SPEC_VERSION}. "
                f"Verify at: {SCHEMA_SOURCE}"
            )


def validate_statistics(asm: Dict, content_str: str, result: ValidationResult):
    """Check for statistics documents where expected."""
    technique, _ = detect_technique(asm)

    has_stats = (
        "statistics aggregate document" in content_str.lower()
        or "statistics-aggregate-document" in content_str
    )

    result.metrics["has_statistics"] = has_stats

    # Statistics are required for multi-analyte profiling
    if "multi analyte" in technique or "multiplex" in content_str.lower():
        if not has_stats:
            result.add_warning(
                "No statistics aggregate document found - bead-based assays should include "
                "median, mean, CV, std dev per analyte"
            )
        else:
            result.add_info("Statistics document: Present")


def validate_units(content_str: str, result: ValidationResult):
    """Check for valid units."""
    # Find all unit values
    units = re.findall(r'"unit":\s*"([^"]+)"', content_str)

    # Check for common case-sensitivity issues
    case_issues = []
    for unit in set(units):
        if unit.lower() in ["rfu", "mfi"] and unit not in ["RFU", "MFI"]:
            case_issues.append(f"{unit} (should be uppercase)")
        elif unit in ["ul", "uL", "µl"] and unit != "μL":
            case_issues.append(f"{unit} (should be μL)")

    if case_issues:
        result.add_warning(f"Non-standard unit capitalization: {case_issues}")

    # Soft validation: check against known units list
    all_known_units = set()
    for unit_list in VALID_UNITS.values():
        all_known_units.update(unit_list)

    unknown_units = []
    for unit in set(units):
        # Skip units that have case issues (already reported above)
        if unit not in all_known_units and unit not in [u.lower() for u in case_issues]:
            unknown_units.append(unit)

    if unknown_units:
        result.add_warning(
            f"Unknown units not in known list (as of {VALIDATION_RULES_DATE}): {unknown_units}. "
            f"These may be valid Allotrope units added after spec version {ASM_SPEC_VERSION}. "
            f"Verify at: {SCHEMA_SOURCE}"
        )


def validate_metadata(content_str: str, result: ValidationResult):
    """Check for required metadata fields."""
    required_fields = [
        ("device system document", "equipment serial number"),
        ("data system document", "software name"),
        ("data system document", "software version"),
    ]

    missing = []
    for _, field in required_fields:
        if (
            field not in content_str.lower()
            and field.replace(" ", "-") not in content_str
        ):
            missing.append(field)

    if missing:
        result.add_warning(f"Missing recommended metadata: {missing}")


def validate_calculated_data(content_str: str, result: ValidationResult):
    """Check calculated data has proper traceability."""
    content_lower = content_str.lower()

    has_calculated = (
        "calculated data document" in content_lower
        or "calculated-data-document" in content_str
    )
    has_data_source = (
        "data source aggregate document" in content_lower
        or "data-source-aggregate-document" in content_str
    )

    result.metrics["has_calculated_data"] = has_calculated
    result.metrics["has_data_source_traceability"] = has_data_source

    if has_calculated:
        result.add_info("Calculated data document: Present")
        if not has_data_source:
            result.add_error(
                "Calculated data found without data-source-aggregate-document - "
                "traceability is required for audit/regulatory compliance"
            )
        else:
            result.add_info("Data source traceability: Present")

    # Check for calculated fields that might be incorrectly placed in measurement-document
    misplaced = []
    for field in SHOULD_BE_CALCULATED:
        # Check if field appears in measurement document context but not in calculated data
        field_pattern = field.replace("/", ".")
        if field_pattern in content_lower:
            # If we have the field but no calculated-data-document, it's misplaced
            if not has_calculated:
                misplaced.append(field)

    if misplaced:
        result.add_warning(
            f"Fields that should likely be in calculated-data-document: {misplaced[:5]}"
            + (f" ... and {len(misplaced)-5} more" if len(misplaced) > 5 else "")
        )


def validate_unique_identifiers(content_str: str, result: ValidationResult):
    """Validate that entities have unique identifiers for traceability."""
    # Count different identifier types
    measurement_ids = len(
        re.findall(r'"measurement identifier":\s*"[^"]+"', content_str)
    )
    if measurement_ids == 0:
        measurement_ids = len(
            re.findall(r'"measurement-identifier":\s*"[^"]+"', content_str)
        )

    calculated_ids = len(
        re.findall(r'"calculated data identifier":\s*"[^"]+"', content_str)
    )
    if calculated_ids == 0:
        calculated_ids = len(
            re.findall(r'"calculated-data-identifier":\s*"[^"]+"', content_str)
        )

    data_source_ids = len(
        re.findall(r'"data source identifier":\s*"[^"]+"', content_str)
    )
    if data_source_ids == 0:
        data_source_ids = len(
            re.findall(r'"data-source-identifier":\s*"[^"]+"', content_str)
        )

    result.metrics["measurement_identifiers"] = measurement_ids
    result.metrics["calculated_data_identifiers"] = calculated_ids
    result.metrics["data_source_identifiers"] = data_source_ids

    if measurement_ids == 0:
        result.add_warning(
            "No measurement identifiers found - required for traceability"
        )

    # If we have calculated data but no data source identifiers, that's a problem
    if calculated_ids > 0 and data_source_ids == 0:
        result.add_error(
            f"Found {calculated_ids} calculated data entries but no data source identifiers - "
            "each calculated value should reference its source"
        )


# =============================================================================
# NEW: NESTED DOCUMENT STRUCTURE VALIDATION
# =============================================================================


def validate_nested_document_structure(
    asm: Dict, content_str: str, result: ValidationResult
):
    """
    Validate that fields are properly nested in their correct documents.

    This checks for common mistakes like:
    - Sample fields flattened directly onto measurement instead of in 'sample document'
    - Device control fields flattened instead of in 'device control aggregate document'
    - Custom/vendor fields not wrapped in 'custom information document'
    """
    content_lower = content_str.lower()

    # Check if proper nested documents exist
    has_sample_doc = (
        '"sample document"' in content_lower or '"sample-document"' in content_str
    )
    has_device_control_doc = (
        '"device control aggregate document"' in content_lower
        or '"device-control-aggregate-document"' in content_str
    )
    has_custom_info_doc = (
        '"custom information document"' in content_lower
        or '"custom-information-document"' in content_str
    )

    result.metrics["has_sample_document"] = has_sample_doc
    result.metrics["has_device_control_document"] = has_device_control_doc
    result.metrics["has_custom_information_document"] = has_custom_info_doc

    # Parse ASM to check field locations
    def find_flattened_fields_in_measurements(obj, path=""):
        """Recursively find fields that appear directly on measurement documents."""
        issues = {"sample": [], "device_control": [], "custom": []}

        if isinstance(obj, dict):
            # Check if we're inside a measurement document
            in_measurement = (
                "measurement document" in path.lower() or "measurement-document" in path
            )
            in_sample_doc = (
                "sample document" in path.lower() or "sample-document" in path
            )
            in_device_control = (
                "device control" in path.lower() or "device-control" in path
            )
            in_custom_info = (
                "custom information" in path.lower() or "custom-information" in path
            )

            for key, value in obj.items():
                key_normalized = key.lower().replace("-", " ")
                new_path = f"{path}.{key}"

                # Check if this key should be nested but isn't
                if in_measurement and not in_sample_doc:
                    if key_normalized in [
                        f.lower().replace("-", " ") for f in SAMPLE_DOCUMENT_FIELDS
                    ]:
                        issues["sample"].append(key)

                if in_measurement and not in_device_control:
                    if key_normalized in [
                        f.lower().replace("-", " ") for f in DEVICE_CONTROL_FIELDS
                    ]:
                        issues["device_control"].append(key)

                if in_measurement and not in_custom_info:
                    if key_normalized in [
                        f.lower().replace("-", " ") for f in CUSTOM_INFO_FIELDS
                    ]:
                        issues["custom"].append(key)

                # Recurse
                child_issues = find_flattened_fields_in_measurements(value, new_path)
                for k in issues:
                    issues[k].extend(child_issues[k])

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                child_issues = find_flattened_fields_in_measurements(
                    item, f"{path}[{i}]"
                )
                for k in issues:
                    issues[k].extend(child_issues[k])

        return issues

    issues = find_flattened_fields_in_measurements(asm)
    flattened_sample_fields = list(set(issues["sample"]))
    flattened_device_control_fields = list(set(issues["device_control"]))
    flattened_custom_fields = list(set(issues["custom"]))

    # Report issues
    if flattened_sample_fields:
        result.add_error(
            f"Fields that should be nested in 'sample document' are flattened on measurement: "
            f"{flattened_sample_fields[:5]}"
            + (
                f" ... and {len(flattened_sample_fields)-5} more"
                if len(flattened_sample_fields) > 5
                else ""
            )
        )
        result.add_info(
            "Tip: Wrap sample fields in a 'sample document' object inside each measurement"
        )

    if flattened_device_control_fields:
        result.add_error(
            f"Fields that should be nested in 'device control aggregate document' are flattened: "
            f"{flattened_device_control_fields[:5]}"
            + (
                f" ... and {len(flattened_device_control_fields)-5} more"
                if len(flattened_device_control_fields) > 5
                else ""
            )
        )
        result.add_info(
            "Tip: Wrap device control fields in 'device control aggregate document' → 'device control document'"
        )

    if flattened_custom_fields:
        result.add_warning(
            f"Vendor-specific fields that should be in 'custom information document': "
            f"{flattened_custom_fields[:5]}"
            + (
                f" ... and {len(flattened_custom_fields)-5} more"
                if len(flattened_custom_fields) > 5
                else ""
            )
        )


def validate_liquid_handler_structure(
    asm: Dict, content_str: str, result: ValidationResult
):
    """
    Specific validation for liquid handler ASM documents.

    Checks for:
    - Proper transfer pairing (aspirate + dispense = 1 measurement)
    - Source/destination field pairs
    - Aspiration volume + transfer volume instead of single volume
    """
    technique, _ = detect_technique(asm)

    # Only run for liquid handler techniques
    if "liquid" not in technique.lower() and "handler" not in technique.lower():
        # Also check content for liquid handler indicators
        content_lower = content_str.lower()
        if not any(
            kw in content_lower
            for kw in ["aspirate", "dispense", "liquid handler", "biomek"]
        ):
            return

    result.add_info("Liquid handler specific validation...")

    content_lower = content_str.lower()

    # Check for proper volume field structure
    has_aspiration_volume = (
        "aspiration volume" in content_lower or "aspiration-volume" in content_str
    )
    has_transfer_volume = (
        "transfer volume" in content_lower or "transfer-volume" in content_str
    )
    has_single_volume = (
        '"volume"' in content_str
        and not has_aspiration_volume
        and not has_transfer_volume
    )

    if has_single_volume and not has_aspiration_volume:
        result.add_warning(
            "Liquid handler ASM uses single 'volume' field - "
            "consider using 'aspiration volume' and 'transfer volume' for full transfer semantics"
        )

    if has_aspiration_volume and has_transfer_volume:
        result.add_info("Volume fields: Proper aspiration/transfer volume structure")

    # Check for source/destination pairing
    has_source_dest = (
        "source location" in content_lower or "source-location" in content_str
    ) and (
        "destination location" in content_lower or "destination-location" in content_str
    )

    has_separate_transfer_type = (
        "transfer type" in content_lower or "transfer-type" in content_str
    )

    if has_separate_transfer_type and not has_source_dest:
        result.add_warning(
            "Found 'transfer type' field (Aspirate/Dispense as separate records) - "
            "proper ASM pairs source→destination in single measurement with 'source location identifier' "
            "and 'destination location identifier'"
        )
        result.add_info(
            "Tip: Pair aspirate+dispense operations by probe number into single transfer measurements"
        )

    if has_source_dest:
        result.add_info("Source/destination: Proper paired transfer structure")

    # Check for labware name fields in custom information document
    has_labware_names = (
        "source labware name" in content_lower
        or "destination labware name" in content_lower
    )

    if has_labware_names:
        result.add_info(
            "Labware names: Present (should be in custom information document)"
        )


def compare_to_reference(
    asm: Dict,
    reference: Dict,
    content_str: str,
    ref_content: str,
    result: ValidationResult,
):
    """Compare generated ASM to reference ASM."""
    result.add_info("Comparing to reference ASM...")

    # Compare techniques
    gen_tech, _ = detect_technique(asm)
    ref_tech, _ = detect_technique(reference)

    if gen_tech.replace("-", " ") != ref_tech.replace("-", " "):
        result.add_error(
            f"Technique mismatch: generated '{gen_tech}' vs reference '{ref_tech}'"
        )

    # Compare measurement counts
    gen_count = count_measurements(content_str)
    ref_count = count_measurements(ref_content)

    result.metrics["reference_measurement_count"] = ref_count

    if gen_count != ref_count:
        diff = ref_count - gen_count
        if diff > 0:
            result.add_error(
                f"Missing {diff} measurements: generated {gen_count} vs reference {ref_count}"
            )
        else:
            result.add_warning(
                f"Extra {-diff} measurements: generated {gen_count} vs reference {ref_count}"
            )

    # Compare sample roles
    gen_roles = set(re.findall(r'"sample.role.type":\s*"([^"]+)"', content_str))
    ref_roles = set(re.findall(r'"sample role type":\s*"([^"]+)"', ref_content))

    missing_roles = ref_roles - gen_roles
    if missing_roles:
        result.add_warning(f"Missing sample roles from reference: {missing_roles}")

    # Compare nested document presence
    ref_has_sample_doc = '"sample document"' in ref_content.lower()
    gen_has_sample_doc = (
        '"sample document"' in content_str.lower() or '"sample-document"' in content_str
    )

    if ref_has_sample_doc and not gen_has_sample_doc:
        result.add_error(
            "Reference has 'sample document' but generated ASM does not - fields may be incorrectly flattened"
        )

    ref_has_device_control = (
        '"device control aggregate document"' in ref_content.lower()
    )
    gen_has_device_control = (
        '"device control aggregate document"' in content_str.lower()
        or '"device-control-aggregate-document"' in content_str
    )

    if ref_has_device_control and not gen_has_device_control:
        result.add_error(
            "Reference has 'device control aggregate document' but generated ASM does not"
        )

    ref_has_custom_info = '"custom information document"' in ref_content.lower()
    gen_has_custom_info = (
        '"custom information document"' in content_str.lower()
        or '"custom-information-document"' in content_str
    )

    if ref_has_custom_info and not gen_has_custom_info:
        result.add_warning(
            "Reference has 'custom information document' for vendor fields but generated ASM does not"
        )


def validate_asm(
    filepath: str, reference_path: Optional[str] = None, strict: bool = False
) -> ValidationResult:
    """
    Validate ASM JSON file.

    Args:
        filepath: Path to ASM JSON file
        reference_path: Optional path to reference ASM for comparison
        strict: If True, treat warnings as errors

    Returns:
        ValidationResult with errors, warnings, and metrics
    """
    result = ValidationResult()

    # Load ASM file
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content_str = f.read()
            asm = json.loads(content_str)
    except json.JSONDecodeError as e:
        result.add_error(f"Invalid JSON: {e}")
        return result
    except FileNotFoundError:
        result.add_error(f"File not found: {filepath}")
        return result

    result.add_info(f"Validating: {filepath}")

    # Run validations
    validate_manifest(asm, result)
    validate_technique(asm, result, content_str)
    validate_naming_conventions(content_str, result)
    validate_measurements(content_str, result)
    validate_sample_roles(content_str, result)
    validate_statistics(asm, content_str, result)
    validate_units(content_str, result)
    validate_metadata(content_str, result)
    validate_calculated_data(content_str, result)
    validate_unique_identifiers(content_str, result)

    # NEW: Nested document structure validation
    validate_nested_document_structure(asm, content_str, result)
    validate_liquid_handler_structure(asm, content_str, result)

    # Compare to reference if provided
    if reference_path:
        try:
            with open(reference_path, "r", encoding="utf-8") as f:
                ref_content = f.read()
                reference = json.loads(ref_content)
            compare_to_reference(asm, reference, content_str, ref_content, result)
        except Exception as e:
            result.add_warning(f"Could not load reference file: {e}")

    # In strict mode, convert warnings to errors
    if strict:
        result.errors.extend([w.replace("WARNING", "ERROR") for w in result.warnings])
        result.warnings = []

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate ASM JSON output")
    parser.add_argument("input", help="ASM JSON file to validate")
    parser.add_argument("--reference", "-r", help="Reference ASM file for comparison")
    parser.add_argument(
        "--strict", "-s", action="store_true", help="Treat warnings as errors"
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show errors")

    args = parser.parse_args()

    result = validate_asm(args.input, args.reference, args.strict)

    if args.quiet:
        if result.errors:
            for error in result.errors:
                print(error)
            sys.exit(1)
        sys.exit(0)

    result.print_report()
    sys.exit(0 if result.is_valid() else 1)


if __name__ == "__main__":
    main()
