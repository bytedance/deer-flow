"""
Samplesheet validation utilities.

Validates samplesheet rows against pipeline configuration before writing,
catching errors early with helpful messages.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml


@dataclass
class ValidationResult:
    """Result of samplesheet validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def __bool__(self):
        return self.valid

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = []
        if self.errors:
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"  - {e}")
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        if self.suggestions:
            lines.append("Suggestions:")
            for s in self.suggestions:
                lines.append(f"  - {s}")
        return "\n".join(lines)


def load_pipeline_config(pipeline: str) -> Optional[Dict]:
    """Load pipeline configuration from YAML file."""
    # Find config directory relative to this file
    script_dir = Path(__file__).parent.parent.parent
    config_path = script_dir / "config" / "pipelines" / f"{pipeline}.yaml"

    if not config_path.exists():
        return None

    with open(config_path) as f:
        return yaml.safe_load(f)


def validate_samplesheet(
    rows: List[Dict],
    pipeline: str,
    config: Optional[Dict] = None
) -> ValidationResult:
    """
    Validate samplesheet rows against pipeline requirements.

    Args:
        rows: List of row dictionaries
        pipeline: Pipeline name (e.g., 'rnaseq', 'sarek')
        config: Optional pre-loaded config dict

    Returns:
        ValidationResult with errors, warnings, and suggestions
    """
    errors = []
    warnings = []
    suggestions = []

    # Load config if not provided
    if config is None:
        config = load_pipeline_config(pipeline)

    if config is None:
        errors.append(f"Unknown pipeline: {pipeline}")
        return ValidationResult(valid=False, errors=errors)

    columns = config.get("samplesheet", {}).get("columns", [])
    required_cols = [c["name"] for c in columns if c.get("required", False)]

    if not rows:
        errors.append("Samplesheet is empty - no samples found")
        return ValidationResult(valid=False, errors=errors)

    # Validate each row
    for i, row in enumerate(rows):
        row_num = i + 2  # Account for header row

        # Check required columns
        for col_name in required_cols:
            col_config = next((c for c in columns if c["name"] == col_name), None)

            # Skip columns with conditions that don't apply
            if col_config and "condition" in col_config:
                # Simple condition check - skip for now
                # Full implementation would evaluate conditions
                pass

            if col_name not in row or row[col_name] is None or row[col_name] == "":
                # Check if there's a default
                if col_config and "default" in col_config:
                    continue
                errors.append(f"Row {row_num}: Missing required column '{col_name}'")

        # Validate path columns exist
        for col_name in ["fastq_1", "fastq_2", "bam", "bai"]:
            if col_name in row and row[col_name]:
                path = row[col_name]
                if not os.path.exists(path):
                    errors.append(f"Row {row_num}: File not found: {path}")
                elif not os.path.isfile(path):
                    errors.append(f"Row {row_num}: Not a file: {path}")

        # Validate enum values
        for col_config in columns:
            col_name = col_config["name"]
            if col_name in row and row[col_name] and "allowed" in col_config:
                value = row[col_name]
                allowed = col_config["allowed"]
                if value not in allowed:
                    errors.append(
                        f"Row {row_num}: Invalid value '{value}' for '{col_name}'. "
                        f"Allowed: {allowed}"
                    )

        # Check R1/R2 pairing consistency
        r1 = row.get("fastq_1", "")
        r2 = row.get("fastq_2", "")
        if r1 and not r2:
            warnings.append(f"Row {row_num}: Single-end data (no R2 file)")
        elif r2 and not r1:
            errors.append(f"Row {row_num}: R2 present but R1 missing")

    # Check for duplicate samples
    sample_col = "sample" if "sample" in rows[0] else "patient"
    if sample_col in rows[0]:
        samples = [r.get(sample_col, "") for r in rows]
        duplicates = [s for s in set(samples) if samples.count(s) > 1]
        if duplicates:
            warnings.append(f"Duplicate sample names: {duplicates}")
            suggestions.append(
                "Duplicates may be intentional (multi-lane sequencing). "
                "Verify sample grouping is correct."
            )

    # Pipeline-specific validation
    if pipeline == "sarek":
        _validate_sarek_specific(rows, errors, warnings, suggestions)
    elif pipeline == "atacseq":
        _validate_atacseq_specific(rows, errors, warnings, suggestions)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions
    )


def _validate_sarek_specific(
    rows: List[Dict],
    errors: List[str],
    warnings: List[str],
    suggestions: List[str]
):
    """Sarek-specific validation for tumor/normal pairing."""
    # Group by patient
    patients = {}
    for row in rows:
        patient = row.get("patient", "")
        status = row.get("status")

        if patient not in patients:
            patients[patient] = {"tumor": 0, "normal": 0, "unknown": 0}

        if status == 1:
            patients[patient]["tumor"] += 1
        elif status == 0:
            patients[patient]["normal"] += 1
        else:
            patients[patient]["unknown"] += 1

    # Check pairing
    for patient, counts in patients.items():
        if counts["tumor"] > 0 and counts["normal"] == 0:
            warnings.append(
                f"Patient '{patient}': Tumor sample(s) without matched normal. "
                "Somatic calling works best with paired tumor-normal."
            )
            suggestions.append(
                f"For patient '{patient}': Add a normal sample or use tumor-only mode."
            )

        if counts["unknown"] > 0:
            warnings.append(
                f"Patient '{patient}': {counts['unknown']} sample(s) with unknown status. "
                "Set status column to 0 (normal) or 1 (tumor)."
            )


def _validate_atacseq_specific(
    rows: List[Dict],
    errors: List[str],
    warnings: List[str],
    suggestions: List[str]
):
    """ATAC-seq specific validation for replicates."""
    # Group by sample (condition)
    samples = {}
    for row in rows:
        sample = row.get("sample", "")
        replicate = row.get("replicate", 1)

        if sample not in samples:
            samples[sample] = []

        samples[sample].append(replicate)

    # Check replicates
    for sample, reps in samples.items():
        if len(reps) < 2:
            warnings.append(
                f"Sample '{sample}': Only {len(reps)} replicate(s). "
                "Consensus peaks require 2+ replicates."
            )

        # Check for duplicate replicate numbers
        if len(reps) != len(set(reps)):
            errors.append(
                f"Sample '{sample}': Duplicate replicate numbers detected. "
                "Each replicate must have a unique number."
            )

    # Check all samples have R2 (ATAC-seq requires paired-end)
    for i, row in enumerate(rows):
        if not row.get("fastq_2"):
            errors.append(
                f"Row {i+2}: ATAC-seq requires paired-end data. R2 file missing."
            )


def validate_file_exists(path: str) -> bool:
    """Check if file exists and is accessible."""
    return os.path.isfile(path) and os.access(path, os.R_OK)


def validate_absolute_path(path: str) -> bool:
    """Check if path is absolute."""
    return os.path.isabs(path)
