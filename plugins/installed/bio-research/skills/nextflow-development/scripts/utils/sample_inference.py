"""
Sample name and metadata inference from filenames.

This module extracts sample information, detects tumor/normal status,
and matches R1/R2 read pairs from sequencing file names.
"""

import os
import re
from typing import Dict, List, Optional, Tuple


# R1/R2 patterns with priority scores (higher = more confident)
R1_PATTERNS = [
    (r'_R1_\d{3}', 10),      # _R1_001 (Illumina standard)
    (r'_R1[_.]', 8),         # _R1. or _R1_
    (r'\.R1[_.]', 8),        # .R1. or .R1_
    (r'_1[_.]', 5),          # _1. or _1_
    (r'_R1\.f', 6),          # _R1.fastq
    (r'_1\.f', 4),           # _1.fastq
]

R2_PATTERNS = [
    (r'_R2_\d{3}', 10),      # _R2_001 (Illumina standard)
    (r'_R2[_.]', 8),         # _R2. or _R2_
    (r'\.R2[_.]', 8),        # .R2. or .R2_
    (r'_2[_.]', 5),          # _2. or _2_
    (r'_R2\.f', 6),          # _R2.fastq
    (r'_2\.f', 4),           # _2.fastq
]

# Tumor/normal keywords
TUMOR_KEYWORDS = [
    r'\btumou?r\b',
    r'\bmetastasis\b',
    r'\bmet\b',
    r'\bprimary\b',
    r'\bcancer\b',
    r'\bmalignant\b',
    r'[-_]T[-_]',
    r'[-_]T\d*$',
    r'^T\d*[-_]',
]

NORMAL_KEYWORDS = [
    r'\bnormal\b',
    r'\bgermline\b',
    r'\bblood\b',
    r'\bpbmc\b',
    r'\bcontrol\b',
    r'\bhealthy\b',
    r'\bmatched\b',
    r'[-_]N[-_]',
    r'[-_]N\d*$',
    r'^N\d*[-_]',
]

# Lane pattern
LANE_PATTERN = r'[_.]L(\d{3})[_.]'

# Patient/sample extraction patterns
PATIENT_PATTERNS = [
    r'^(P\d+)[-_]',           # P001_sample
    r'^(patient\d+)[-_]',     # patient1_sample
    r'^(TCGA-\w+-\w+)',       # TCGA format
    r'^([A-Z]{2,3}\d{3,})[-_]',  # AB123_sample
]

# Replicate patterns
REPLICATE_PATTERNS = [
    r'[_.]rep(\d+)',          # _rep1, .rep2
    r'[_.]replicate(\d+)',    # _replicate1
    r'[_.]R(\d+)[_.]',        # _R1_ (but not R1/R2 for reads!)
    r'[-_](\d+)$',            # sample_1 (last resort)
]


def extract_sample_info(filepath: str) -> Dict[str, str]:
    """
    Extract sample metadata from filepath.

    Args:
        filepath: Path to sequencing file

    Returns:
        Dict with: sample, patient, lane (if detectable)
    """
    filename = os.path.basename(filepath)

    # Remove extensions
    stem = filename
    for ext in ['.fastq.gz', '.fq.gz', '.fastq', '.fq', '.bam', '.cram', '.bai', '.crai']:
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break

    info = {}

    # Extract lane
    lane_match = re.search(LANE_PATTERN, stem)
    info['lane'] = f"L{lane_match.group(1)}" if lane_match else "L001"

    # Remove lane from stem
    clean_stem = re.sub(LANE_PATTERN, '_', stem)

    # Remove R1/R2 indicators and everything after
    for pattern, _ in R1_PATTERNS + R2_PATTERNS:
        clean_stem = re.sub(pattern + r'.*', '', clean_stem, flags=re.IGNORECASE)

    # Clean up trailing/multiple underscores and dots
    clean_stem = re.sub(r'[_.-]+$', '', clean_stem)
    clean_stem = re.sub(r'[_.-]{2,}', '_', clean_stem)

    # Try to extract patient ID
    for pattern in PATIENT_PATTERNS:
        match = re.match(pattern, clean_stem, re.IGNORECASE)
        if match:
            info['patient'] = match.group(1)
            break

    # Sample is the cleaned stem
    info['sample'] = clean_stem if clean_stem else filename.split('.')[0]

    # Default patient to sample if not extracted
    if 'patient' not in info:
        info['patient'] = info['sample']

    return info


def infer_tumor_normal_status(sample_name: str) -> Optional[int]:
    """
    Infer tumor (1) or normal (0) status from sample name.

    Args:
        sample_name: Sample identifier

    Returns:
        1 for tumor, 0 for normal, None if cannot determine
    """
    name_lower = sample_name.lower()

    # Check tumor indicators
    for pattern in TUMOR_KEYWORDS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return 1

    # Check normal indicators
    for pattern in NORMAL_KEYWORDS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return 0

    return None


def extract_replicate_number(sample_name: str) -> Optional[int]:
    """
    Extract replicate number from sample name.

    Args:
        sample_name: Sample identifier

    Returns:
        Replicate number if found, None otherwise
    """
    for pattern in REPLICATE_PATTERNS:
        match = re.search(pattern, sample_name, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _get_pattern_score(filename: str, patterns: List[Tuple[str, int]]) -> int:
    """Get highest matching pattern score."""
    max_score = 0
    for pattern, score in patterns:
        if re.search(pattern, filename, re.IGNORECASE):
            max_score = max(max_score, score)
    return max_score


def _get_sample_key(filepath: str) -> str:
    """Generate a key for grouping related files."""
    info = extract_sample_info(filepath)
    sample = info['sample']
    lane = info.get('lane', 'L001')

    # Include lane in key for multi-lane samples
    if lane != "L001":
        return f"{sample}_{lane}"
    return sample


def match_read_pairs(files) -> Dict[str, Dict]:
    """
    Match R1/R2 read pairs using scored pattern matching.

    Args:
        files: List of FileInfo objects (from file_discovery)

    Returns:
        Dict mapping sample_key to {'r1': path, 'r2': path, 'info': dict}
    """
    # Classify files
    r1_files = []
    r2_files = []

    for file in files:
        filename = file.name if hasattr(file, 'name') else os.path.basename(str(file))
        filepath = file.path if hasattr(file, 'path') else str(file)

        r1_score = _get_pattern_score(filename, R1_PATTERNS)
        r2_score = _get_pattern_score(filename, R2_PATTERNS)

        if r2_score > r1_score and r2_score > 0:
            r2_files.append((filepath, r2_score))
        elif r1_score > 0:
            r1_files.append((filepath, r1_score))
        else:
            # No clear indicator - assume R1 (single-end or non-standard naming)
            r1_files.append((filepath, 0))

    # Build pairs by matching sample keys
    pairs = {}

    # Process R1 files first
    for r1_path, score in r1_files:
        key = _get_sample_key(r1_path)
        info = extract_sample_info(r1_path)

        if key not in pairs:
            pairs[key] = {
                'r1': r1_path,
                'r2': None,
                'info': info,
                'score': score
            }
        else:
            # Multiple R1 files for same sample (should not happen)
            pairs[key]['r1'] = r1_path

    # Match R2 files
    for r2_path, score in r2_files:
        key = _get_sample_key(r2_path)
        info = extract_sample_info(r2_path)

        if key in pairs:
            pairs[key]['r2'] = r2_path
        else:
            # R2 without matching R1
            pairs[key] = {
                'r1': None,
                'r2': r2_path,
                'info': info,
                'score': score
            }

    return pairs


def infer_patient_groupings(sample_names: List[str]) -> Dict[str, str]:
    """
    Infer patient groupings from sample names.

    Groups samples that share a common prefix pattern.

    Args:
        sample_names: List of sample identifiers

    Returns:
        Dict mapping sample_name to patient_id
    """
    patient_map = {}

    for sample in sample_names:
        # Try to find a patient pattern
        for pattern in PATIENT_PATTERNS:
            match = re.match(pattern, sample, re.IGNORECASE)
            if match:
                patient_map[sample] = match.group(1)
                break

        if sample not in patient_map:
            # Default: each sample is its own patient
            patient_map[sample] = sample

    return patient_map
