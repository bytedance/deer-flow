#!/usr/bin/env python3
"""
Enhanced nf-core samplesheet generator.

Features:
- FASTQ, BAM, and CRAM support
- Tumor/normal status inference for sarek
- Robust R1/R2 matching with scoring
- Pre-write validation with clear error messages
- Pipeline config-driven column generation

Usage:
    python generate_samplesheet.py /path/to/data rnaseq -o samplesheet.csv
    python generate_samplesheet.py /path/to/bams sarek --input-type bam
    python generate_samplesheet.py --validate samplesheet.csv rnaseq
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Add parent directory to path for utils import
sys.path.insert(0, str(Path(__file__).parent))

from utils.file_discovery import discover_files, detect_input_type, find_index_file
from utils.sample_inference import (
    extract_sample_info,
    infer_tumor_normal_status,
    match_read_pairs,
    extract_replicate_number
)
from utils.validators import validate_samplesheet, ValidationResult


def load_pipeline_config(pipeline: str) -> Dict:
    """Load pipeline configuration from YAML."""
    config_dir = Path(__file__).parent / "config" / "pipelines"
    config_file = config_dir / f"{pipeline}.yaml"

    if not config_file.exists():
        available = [f.stem for f in config_dir.glob("*.yaml") if not f.stem.startswith("_")]
        raise ValueError(f"Unknown pipeline '{pipeline}'. Available: {', '.join(available)}")

    with open(config_file) as f:
        return yaml.safe_load(f)


def generate_samplesheet(
    input_dir: str,
    pipeline: str,
    output_file: Optional[str] = None,
    input_type: str = "auto",
    single_end: bool = False,
    interactive: bool = True
) -> Tuple[Optional[str], ValidationResult]:
    """
    Generate samplesheet for specified pipeline.

    Args:
        input_dir: Directory containing sequencing files
        pipeline: Pipeline name (rnaseq, sarek, atacseq)
        output_file: Output CSV path (default: samplesheet_{pipeline}.csv)
        input_type: File type (auto, fastq, bam, cram)
        single_end: Suppress pairing warnings for single-end data
        interactive: Prompt for missing info

    Returns:
        Tuple of (output_path, validation_result)
    """
    config = load_pipeline_config(pipeline)
    samplesheet_config = config.get("samplesheet", {})
    supported_types = samplesheet_config.get("input_types", ["fastq"])

    # Determine input type
    if input_type == "auto":
        input_type = detect_input_type(input_dir)
        print(f"Auto-detected input type: {input_type.upper()}")

    if input_type not in supported_types:
        return None, ValidationResult(
            valid=False,
            errors=[f"Pipeline '{pipeline}' does not support {input_type.upper()} input. "
                    f"Supported: {supported_types}"]
        )

    # Discover files
    try:
        files = discover_files(input_dir, input_type)
    except ValueError as e:
        return None, ValidationResult(valid=False, errors=[str(e)])

    if not files:
        return None, ValidationResult(
            valid=False,
            errors=[f"No {input_type.upper()} files found in {input_dir}"],
            suggestions=[
                "Check directory path is correct",
                "Verify file extensions (.fastq.gz, .fq.gz, .bam, .cram)",
                f"Run: ls {input_dir}"
            ]
        )

    print(f"Found {len(files)} {input_type.upper()} files")

    # Process based on input type
    if input_type == "fastq":
        rows = _process_fastq_files(files, config, single_end)
    else:
        rows = _process_alignment_files(files, config, input_type)

    if not rows:
        return None, ValidationResult(
            valid=False,
            errors=["Could not generate any samplesheet rows from files"]
        )

    print(f"Generated {len(rows)} samplesheet rows")

    # Pipeline-specific processing
    if pipeline == "sarek":
        rows = _process_sarek_samples(rows, interactive)
    elif pipeline == "atacseq":
        rows = _process_atacseq_samples(rows)

    # Validate before writing
    validation = validate_samplesheet(rows, pipeline, config)

    if not validation.valid:
        print("\nValidation errors:")
        for error in validation.errors:
            print(f"  - {error}")

        if interactive:
            response = input("\nProceed anyway? [y/N]: ").strip().lower()
            if response != 'y':
                return None, validation
    elif validation.warnings:
        print("\nWarnings:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    # Determine output path
    output_path = output_file or f"samplesheet_{pipeline}.csv"

    # Write samplesheet
    _write_samplesheet(rows, config, output_path)

    print(f"\nGenerated: {output_path}")
    print(f"  Pipeline: {pipeline} v{config.get('version', 'unknown')}")
    print(f"  Samples: {len(set(r.get('sample', r.get('patient', '')) for r in rows))}")
    print(f"  Rows: {len(rows)}")

    # Preview
    _print_preview(rows, config)

    return output_path, validation


def _process_fastq_files(files, config: Dict, single_end: bool) -> List[Dict]:
    """Process FASTQ files into samplesheet rows."""
    pairs = match_read_pairs(files)

    if not pairs:
        return []

    # Check for unpaired files
    unpaired = [k for k, v in pairs.items() if v.get('r1') and not v.get('r2')]
    if unpaired and not single_end:
        print(f"\nNote: {len(unpaired)} samples appear to be single-end (no R2)")

    rows = []
    columns = config.get("samplesheet", {}).get("columns", [])

    for sample_key, pair_info in sorted(pairs.items()):
        if not pair_info.get('r1'):
            continue  # Skip entries with only R2

        info = pair_info.get('info', {})

        row = {
            'sample': info.get('sample', sample_key),
            'fastq_1': str(Path(pair_info['r1']).absolute()),
            'fastq_2': str(Path(pair_info['r2']).absolute()) if pair_info.get('r2') else '',
        }

        # Add additional info from filename
        if 'patient' in [c['name'] for c in columns]:
            row['patient'] = info.get('patient', info.get('sample', sample_key))

        if 'lane' in [c['name'] for c in columns]:
            row['lane'] = info.get('lane', 'L001')

        # Apply defaults from config
        for col in columns:
            if col['name'] not in row and 'default' in col:
                row[col['name']] = col['default']

        rows.append(row)

    return rows


def _process_alignment_files(files, config: Dict, input_type: str) -> List[Dict]:
    """Process BAM/CRAM files into samplesheet rows."""
    rows = []
    columns = config.get("samplesheet", {}).get("columns", [])

    for file_info in files:
        # Find index file
        index_path = find_index_file(file_info.path)

        info = extract_sample_info(file_info.path)

        row = {
            'sample': info.get('sample', file_info.stem),
            'bam': str(Path(file_info.path).absolute()),
            'bai': str(Path(index_path).absolute()) if index_path else '',
        }

        # Add patient for sarek
        if 'patient' in [c['name'] for c in columns]:
            row['patient'] = info.get('patient', info.get('sample', file_info.stem))

        # Apply defaults
        for col in columns:
            if col['name'] not in row and 'default' in col:
                row[col['name']] = col['default']

        # Warn if no index found
        if not index_path:
            print(f"  Warning: No index found for {file_info.name}")

        rows.append(row)

    return rows


def _process_sarek_samples(rows: List[Dict], interactive: bool) -> List[Dict]:
    """Process sarek samples: infer and confirm tumor/normal status."""
    # Auto-infer status from sample names
    for row in rows:
        sample_name = row.get('sample', '')
        inferred = infer_tumor_normal_status(sample_name)
        if inferred is not None:
            row['status'] = inferred

    # Report inference results
    inferred_tumor = [r for r in rows if r.get('status') == 1]
    inferred_normal = [r for r in rows if r.get('status') == 0]
    unknown = [r for r in rows if 'status' not in r]

    if inferred_tumor or inferred_normal:
        print(f"\nTumor/normal inference:")
        print(f"  Tumor samples: {len(inferred_tumor)}")
        print(f"  Normal samples: {len(inferred_normal)}")

    # Handle unknown samples
    if unknown and interactive:
        print(f"\n{len(unknown)} sample(s) with unknown status:")
        for r in unknown:
            print(f"  - {r.get('sample')}")

        print("\nSpecify status for each (0=normal, 1=tumor, Enter=skip):")
        for r in unknown:
            response = input(f"  {r.get('sample')} [0/1/Enter]: ").strip()
            if response in ['0', '1']:
                r['status'] = int(response)
            else:
                r['status'] = 0  # Default to normal
                print(f"    Defaulting to normal (0)")
    elif unknown:
        # Non-interactive: default to normal
        for r in unknown:
            r['status'] = 0

    return rows


def _process_atacseq_samples(rows: List[Dict]) -> List[Dict]:
    """Process ATAC-seq samples: ensure replicate numbers."""
    # Group by sample name
    sample_counts = {}
    for row in rows:
        sample = row.get('sample', '')
        if sample not in sample_counts:
            sample_counts[sample] = 0
        sample_counts[sample] += 1

    # Assign replicate numbers if not present
    sample_rep = {}
    for row in rows:
        sample = row.get('sample', '')

        if 'replicate' not in row or not row['replicate']:
            # Try to extract from filename
            extracted = extract_replicate_number(row.get('fastq_1', ''))
            if extracted:
                row['replicate'] = extracted
            else:
                # Auto-assign sequential
                if sample not in sample_rep:
                    sample_rep[sample] = 0
                sample_rep[sample] += 1
                row['replicate'] = sample_rep[sample]

    return rows


def _write_samplesheet(rows: List[Dict], config: Dict, output_path: str):
    """Write samplesheet to CSV file."""
    columns = config.get("samplesheet", {}).get("columns", [])
    column_names = [c['name'] for c in columns]

    # Filter to columns that have data
    active_columns = [c for c in column_names if any(c in row and row[c] for row in rows)]

    # Ensure fastq_1/fastq_2 or bam/bai are included
    for required in ['fastq_1', 'bam']:
        if required in column_names and required not in active_columns:
            if any(required in row for row in rows):
                active_columns.append(required)

    # Maintain original column order
    active_columns = [c for c in column_names if c in active_columns]

    with open(output_path, 'w') as f:
        f.write(','.join(active_columns) + '\n')
        for row in rows:
            values = [str(row.get(col, '')) for col in active_columns]
            f.write(','.join(values) + '\n')


def _print_preview(rows: List[Dict], config: Dict):
    """Print preview of generated samplesheet."""
    columns = config.get("samplesheet", {}).get("columns", [])
    column_names = [c['name'] for c in columns]
    active_columns = [c for c in column_names if any(c in row for row in rows)]

    print(f"\nPreview (first 3 rows):")
    print(','.join(active_columns))
    for row in rows[:3]:
        values = [str(row.get(col, ''))[:40] for col in active_columns]  # Truncate long paths
        print(','.join(values))
    if len(rows) > 3:
        print(f"... ({len(rows) - 3} more rows)")


def validate_existing_samplesheet(csv_path: str, pipeline: str) -> ValidationResult:
    """Validate an existing samplesheet file."""
    import csv

    if not os.path.exists(csv_path):
        return ValidationResult(valid=False, errors=[f"File not found: {csv_path}"])

    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return ValidationResult(valid=False, errors=[f"Failed to read CSV: {e}"])

    if not rows:
        return ValidationResult(valid=False, errors=["Samplesheet is empty"])

    config = load_pipeline_config(pipeline)
    return validate_samplesheet(rows, pipeline, config)


def main():
    parser = argparse.ArgumentParser(
        description='Generate nf-core samplesheet from data directory',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate samplesheet for RNA-seq
    %(prog)s ./fastqs rnaseq -o samples.csv

    # Generate samplesheet for sarek from BAM files
    %(prog)s ./bams sarek --input-type bam

    # Validate existing samplesheet
    %(prog)s --validate samplesheet.csv rnaseq

Supported pipelines: rnaseq, sarek, atacseq
        """
    )

    parser.add_argument('input', help='Directory with data files, or CSV path for --validate')
    parser.add_argument('pipeline', help='Pipeline name (rnaseq, sarek, atacseq)')
    parser.add_argument('-o', '--output', help='Output CSV filename')
    parser.add_argument('--input-type', choices=['auto', 'fastq', 'bam', 'cram'],
                        default='auto', help='Input file type (default: auto-detect)')
    parser.add_argument('--single-end', action='store_true',
                        help='Treat as single-end data (suppress pairing warnings)')
    parser.add_argument('--validate', action='store_true',
                        help='Validate existing samplesheet instead of generating')
    parser.add_argument('--no-interactive', action='store_true',
                        help='Non-interactive mode (use defaults)')

    args = parser.parse_args()

    try:
        if args.validate:
            # Validate existing samplesheet
            result = validate_existing_samplesheet(args.input, args.pipeline)
            if result.valid:
                print(f"✓ Samplesheet is valid for {args.pipeline}")
                if result.warnings:
                    print("\nWarnings:")
                    for w in result.warnings:
                        print(f"  - {w}")
                sys.exit(0)
            else:
                print(f"✗ Samplesheet validation failed")
                print(result.summary())
                sys.exit(1)
        else:
            # Generate new samplesheet
            if not os.path.isdir(args.input):
                print(f"Error: Not a directory: {args.input}")
                sys.exit(1)

            output_path, result = generate_samplesheet(
                args.input,
                args.pipeline,
                args.output,
                args.input_type,
                args.single_end,
                interactive=not args.no_interactive
            )

            if output_path is None:
                print("\nFailed to generate samplesheet.")
                if result.suggestions:
                    print("\nSuggestions:")
                    for s in result.suggestions:
                        print(f"  - {s}")
                sys.exit(1)

            sys.exit(0)

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == '__main__':
    main()
