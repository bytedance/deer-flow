"""
File discovery utilities for FASTQ, BAM, and CRAM files.

This module provides functions to recursively discover sequencing data files
in a directory structure.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FileInfo:
    """Information about a discovered file."""
    path: str
    name: str
    stem: str
    extension: str
    size: int
    file_type: str  # fastq, bam, cram

    def __repr__(self):
        return f"FileInfo({self.name}, type={self.file_type})"


# Supported file extensions by type
EXTENSIONS = {
    "fastq": [".fastq.gz", ".fq.gz", ".fastq", ".fq"],
    "bam": [".bam"],
    "cram": [".cram"],
}

# Index file extensions
INDEX_EXTENSIONS = {
    "bam": [".bam.bai", ".bai"],
    "cram": [".cram.crai", ".crai"],
}


def discover_files(
    directory: str,
    file_type: str = "fastq",
    follow_symlinks: bool = True
) -> List[FileInfo]:
    """
    Recursively discover files of specified type.

    Args:
        directory: Root directory to search
        file_type: One of 'fastq', 'bam', 'cram'
        follow_symlinks: Whether to follow symbolic links

    Returns:
        List of FileInfo objects sorted by path
    """
    if file_type not in EXTENSIONS:
        raise ValueError(f"Unknown file type: {file_type}. Supported: {list(EXTENSIONS.keys())}")

    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        raise ValueError(f"Not a directory: {directory}")

    extensions = EXTENSIONS[file_type]
    files = []
    seen_paths = set()  # Avoid duplicates from symlinks

    for root, _, filenames in os.walk(directory, followlinks=follow_symlinks):
        for filename in filenames:
            # Check each extension
            for ext in extensions:
                if filename.lower().endswith(ext.lower()):
                    full_path = os.path.join(root, filename)

                    # Resolve to handle symlinks
                    try:
                        real_path = os.path.realpath(full_path)
                    except OSError:
                        real_path = full_path

                    if real_path in seen_paths:
                        continue
                    seen_paths.add(real_path)

                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0

                    # Extract stem (remove extension)
                    stem = filename
                    for e in extensions:
                        if stem.lower().endswith(e.lower()):
                            stem = stem[:-len(e)]
                            break

                    files.append(FileInfo(
                        path=full_path,
                        name=filename,
                        stem=stem,
                        extension=ext,
                        size=size,
                        file_type=file_type
                    ))
                    break  # Found matching extension, no need to check others

    return sorted(files, key=lambda f: f.path)


def count_files_by_type(directory: str) -> Dict[str, int]:
    """
    Count files by type in directory.

    Args:
        directory: Directory to scan

    Returns:
        Dict mapping file_type to count
    """
    counts = {}
    for file_type in EXTENSIONS:
        try:
            files = discover_files(directory, file_type)
            counts[file_type] = len(files)
        except (ValueError, PermissionError):
            counts[file_type] = 0
    return counts


def find_index_file(alignment_file: str) -> Optional[str]:
    """
    Find index file for a BAM or CRAM file.

    Args:
        alignment_file: Path to BAM or CRAM file

    Returns:
        Path to index file if found, None otherwise
    """
    path = Path(alignment_file)

    # Determine file type
    if path.suffix.lower() == ".bam":
        index_exts = INDEX_EXTENSIONS["bam"]
    elif path.suffix.lower() == ".cram":
        index_exts = INDEX_EXTENSIONS["cram"]
    else:
        return None

    # Try common index file patterns
    for ext in index_exts:
        # Pattern: file.bam.bai or file.bai
        if ext.startswith(".bam") or ext.startswith(".cram"):
            candidate = Path(str(path) + ext.split(".")[-1])
        else:
            candidate = path.with_suffix(ext)

        if candidate.exists():
            return str(candidate)

        # Also try: file.bam -> file.bam.bai
        candidate = Path(str(path) + "." + ext.lstrip("."))
        if candidate.exists():
            return str(candidate)

    return None


def detect_input_type(directory: str) -> str:
    """
    Auto-detect predominant input file type in directory.

    Prioritizes: FASTQ > BAM > CRAM

    Args:
        directory: Directory to scan

    Returns:
        Detected file type ('fastq', 'bam', or 'cram')
    """
    counts = count_files_by_type(directory)

    # Prioritize by preference
    for file_type in ["fastq", "bam", "cram"]:
        if counts.get(file_type, 0) > 0:
            return file_type

    return "fastq"  # Default
