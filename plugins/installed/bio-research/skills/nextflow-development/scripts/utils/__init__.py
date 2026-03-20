"""
Utility modules for nf-core pipeline deployment.

Modules:
    ncbi_utils: NCBI/GEO/SRA data fetching and download utilities
    file_discovery: Find FASTQ, BAM, and CRAM files
    sample_inference: Extract sample info, detect tumor/normal
    validators: Validate samplesheets before writing
"""

# NCBI utilities for GEO/SRA data acquisition
from .ncbi_utils import (
    check_network_access,
    fetch_geo_metadata,
    fetch_sra_study_accession,
    fetch_sra_run_info,
    fetch_sra_run_info_detailed,
    fetch_bioproject_from_geo,
    fetch_ena_fastq_urls,
    download_file,
    fetch_pubmed_metadata,
    format_file_size,
    estimate_download_size,
    group_samples_by_type,
    format_sample_groups_table,
)

# File discovery utilities
from .file_discovery import discover_files, FileInfo, count_files_by_type

# Sample inference utilities
from .sample_inference import (
    extract_sample_info,
    infer_tumor_normal_status,
    match_read_pairs,
    extract_replicate_number
)

# Validation utilities
from .validators import validate_samplesheet, ValidationResult

__all__ = [
    # ncbi_utils
    'check_network_access',
    'fetch_geo_metadata',
    'fetch_sra_study_accession',
    'fetch_sra_run_info',
    'fetch_sra_run_info_detailed',
    'fetch_bioproject_from_geo',
    'fetch_ena_fastq_urls',
    'download_file',
    'fetch_pubmed_metadata',
    'format_file_size',
    'estimate_download_size',
    'group_samples_by_type',
    'format_sample_groups_table',
    # file_discovery
    'discover_files',
    'FileInfo',
    'count_files_by_type',
    # sample_inference
    'extract_sample_info',
    'infer_tumor_normal_status',
    'match_read_pairs',
    'extract_replicate_number',
    # validators
    'validate_samplesheet',
    'ValidationResult',
]
