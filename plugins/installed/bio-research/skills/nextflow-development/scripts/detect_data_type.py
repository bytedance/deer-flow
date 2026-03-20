#!/usr/bin/env python3
"""
Auto-detect appropriate nf-core pipeline from data directory.

Analyzes filenames, directory structure, and file content hints to suggest
the most appropriate pipeline for the data.

Usage:
    python detect_data_type.py /path/to/data
    python detect_data_type.py /path/to/data --json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import yaml


def load_all_pipeline_configs() -> Dict[str, Dict]:
    """Load all pipeline configurations."""
    config_dir = Path(__file__).parent / "config" / "pipelines"
    configs = {}

    for config_file in config_dir.glob("*.yaml"):
        if config_file.stem.startswith("_"):
            continue
        with open(config_file) as f:
            configs[config_file.stem] = yaml.safe_load(f)

    return configs


def scan_directory(directory: str) -> Dict:
    """Scan directory and collect file information."""
    info = {
        'fastq_count': 0,
        'bam_count': 0,
        'cram_count': 0,
        'filenames': [],
        'directories': [],
        'total_size_gb': 0,
    }

    directory = os.path.abspath(directory)

    for root, dirs, files in os.walk(directory):
        # Collect directory names
        rel_root = os.path.relpath(root, directory)
        if rel_root != '.':
            info['directories'].append(rel_root.lower())

        for filename in files:
            filename_lower = filename.lower()

            # Count file types
            if any(filename_lower.endswith(ext) for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq']):
                info['fastq_count'] += 1
            elif filename_lower.endswith('.bam'):
                info['bam_count'] += 1
            elif filename_lower.endswith('.cram'):
                info['cram_count'] += 1

            # Collect filenames for pattern matching
            info['filenames'].append(filename_lower)

            # Sum file sizes
            try:
                size = os.path.getsize(os.path.join(root, filename))
                info['total_size_gb'] += size / (1024**3)
            except:
                pass

    return info


def calculate_pipeline_scores(scan_info: Dict, configs: Dict) -> Dict[str, Dict]:
    """Calculate confidence scores for each pipeline."""
    scores = {}

    for pipeline_name, config in configs.items():
        score = 0
        matches = []

        # Check detection hints
        hints = config.get('detection_hints', {})

        # Filename hints
        filename_hints = hints.get('filename', [])
        for hint in filename_hints:
            hint_lower = hint.lower()
            for filename in scan_info['filenames']:
                if hint_lower in filename:
                    score += 10
                    matches.append(f"Filename contains '{hint}'")
                    break

        # Directory hints
        directory_hints = hints.get('directory', [])
        for hint in directory_hints:
            hint_lower = hint.lower()
            for dirname in scan_info['directories']:
                if hint_lower in dirname:
                    score += 15
                    matches.append(f"Directory contains '{hint}'")
                    break

        # Check data type compatibility
        data_types = config.get('data_types', [])
        input_types = config.get('samplesheet', {}).get('input_types', ['fastq'])

        # Prefer pipelines that support the available file types
        if 'fastq' in input_types and scan_info['fastq_count'] > 0:
            score += 5
        if 'bam' in input_types and scan_info['bam_count'] > 0:
            score += 5
        if 'cram' in input_types and scan_info['cram_count'] > 0:
            score += 5

        # Pipeline-specific boosts
        if pipeline_name == 'sarek':
            # Check for tumor/normal indicators
            tumor_indicators = ['tumor', 'tumour', 'cancer', 'met', 'primary']
            normal_indicators = ['normal', 'germline', 'blood', 'control']

            has_tumor = any(ind in ' '.join(scan_info['filenames']) for ind in tumor_indicators)
            has_normal = any(ind in ' '.join(scan_info['filenames']) for ind in normal_indicators)

            if has_tumor or has_normal:
                score += 20
                if has_tumor:
                    matches.append("Found tumor sample indicators")
                if has_normal:
                    matches.append("Found normal sample indicators")

            # DNA-related hints
            dna_hints = ['wgs', 'wes', 'exome', 'dna', 'variant', 'snp', 'indel']
            for hint in dna_hints:
                if hint in ' '.join(scan_info['filenames'] + scan_info['directories']):
                    score += 10
                    matches.append(f"Found DNA/variant indicator: '{hint}'")
                    break

        elif pipeline_name == 'rnaseq':
            # RNA-related hints
            rna_hints = ['rna', 'rnaseq', 'mrna', 'expression', 'transcript', 'counts']
            for hint in rna_hints:
                if hint in ' '.join(scan_info['filenames'] + scan_info['directories']):
                    score += 15
                    matches.append(f"Found RNA indicator: '{hint}'")
                    break

        elif pipeline_name == 'atacseq':
            # ATAC-related hints
            atac_hints = ['atac', 'atacseq', 'chromatin', 'accessibility', 'peak', 'macs']
            for hint in atac_hints:
                if hint in ' '.join(scan_info['filenames'] + scan_info['directories']):
                    score += 20
                    matches.append(f"Found ATAC-seq indicator: '{hint}'")
                    break

        scores[pipeline_name] = {
            'score': score,
            'matches': matches,
            'description': config.get('description', ''),
            'version': config.get('version', 'unknown'),
        }

    return scores


def detect_pipeline(directory: str) -> Tuple[str, Dict]:
    """
    Detect the most appropriate pipeline for the data.

    Args:
        directory: Path to data directory

    Returns:
        Tuple of (recommended_pipeline, all_scores)
    """
    if not os.path.isdir(directory):
        raise ValueError(f"Not a directory: {directory}")

    configs = load_all_pipeline_configs()
    scan_info = scan_directory(directory)

    # Check if any sequencing files found
    total_files = scan_info['fastq_count'] + scan_info['bam_count'] + scan_info['cram_count']
    if total_files == 0:
        raise ValueError(f"No sequencing files (FASTQ/BAM/CRAM) found in {directory}")

    scores = calculate_pipeline_scores(scan_info, configs)

    # Find highest scoring pipeline
    best_pipeline = max(scores.keys(), key=lambda k: scores[k]['score'])

    return best_pipeline, scores


def print_results(
    directory: str,
    recommended: str,
    scores: Dict,
    scan_info: Dict,
    output_json: bool = False
):
    """Print detection results."""
    if output_json:
        result = {
            'recommended': recommended,
            'scores': scores,
            'scan_info': {
                'fastq_count': scan_info['fastq_count'],
                'bam_count': scan_info['bam_count'],
                'cram_count': scan_info['cram_count'],
                'total_size_gb': round(scan_info['total_size_gb'], 2),
            }
        }
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 50)
    print("  nf-core Pipeline Detection")
    print("=" * 50)
    print(f"\nDirectory: {directory}")
    print(f"Files found: {scan_info['fastq_count']} FASTQ, "
          f"{scan_info['bam_count']} BAM, {scan_info['cram_count']} CRAM")
    print(f"Total size: {scan_info['total_size_gb']:.1f} GB")

    print("\n--- Pipeline Scores ---")
    sorted_pipelines = sorted(scores.keys(), key=lambda k: scores[k]['score'], reverse=True)

    for pipeline in sorted_pipelines:
        info = scores[pipeline]
        indicator = "→" if pipeline == recommended else " "
        print(f"\n{indicator} {pipeline} (score: {info['score']})")
        print(f"  {info['description']}")
        if info['matches']:
            print(f"  Matches: {', '.join(info['matches'][:3])}")

    print(f"\n{'=' * 50}")
    print(f"\n\033[92mRecommended: {recommended}\033[0m")
    print(f"Version: {scores[recommended]['version']}")

    # Print suggested next steps
    print(f"\n--- Next Steps ---")
    print(f"1. Run environment check:")
    print(f"   python scripts/check_environment.py")
    print(f"\n2. Run test profile:")
    config = load_all_pipeline_configs().get(recommended, {})
    test_cmd = config.get('test_profile', {}).get('command', '')
    if test_cmd:
        print(f"   {test_cmd}")
    print(f"\n3. Generate samplesheet:")
    print(f"   python scripts/generate_samplesheet.py {directory} {recommended}")


def main():
    parser = argparse.ArgumentParser(
        description='Detect appropriate nf-core pipeline for data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s ./data
    %(prog)s ./fastqs --json
        """
    )

    parser.add_argument('directory', help='Directory containing sequencing data')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    try:
        scan_info = scan_directory(args.directory)
        recommended, scores = detect_pipeline(args.directory)
        print_results(args.directory, recommended, scores, scan_info, args.json)
        sys.exit(0)

    except ValueError as e:
        if args.json:
            print(json.dumps({'error': str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)

    except Exception as e:
        if args.json:
            print(json.dumps({'error': str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
