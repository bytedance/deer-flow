#!/usr/bin/env python3
"""
NCBI Utilities for GEO/SRA Data Access
======================================
Shared utilities for fetching metadata and downloading data from NCBI services.
"""

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# NCBI rate limiting - track last request time
_last_ncbi_request_time = 0.0
_NCBI_MIN_DELAY = 0.34  # 3 requests per second max without API key


def _rate_limit_ncbi():
    """Enforce NCBI rate limit of 3 requests/second."""
    global _last_ncbi_request_time
    current_time = time.time()
    elapsed = current_time - _last_ncbi_request_time
    if elapsed < _NCBI_MIN_DELAY:
        time.sleep(_NCBI_MIN_DELAY - elapsed)
    _last_ncbi_request_time = time.time()


# Try to import requests for better HTTP handling
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.debug("requests not installed - using urllib fallback")


def check_network_access() -> Tuple[bool, str]:
    """
    Check if NCBI/ENA servers are accessible.

    Returns:
        Tuple of (success, message)
    """
    test_urls = [
        ("NCBI Entrez", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi"),
        ("NCBI FTP", "https://ftp.ncbi.nlm.nih.gov/"),
        ("ENA API", "https://www.ebi.ac.uk/ena/portal/api/"),
    ]

    results = []
    for name, url in test_urls:
        try:
            if HAS_REQUESTS:
                # Use GET instead of HEAD - NCBI Entrez returns 405 for HEAD
                response = requests.get(url, timeout=10)
                success = response.status_code < 400
            else:
                req = Request(url, headers={'User-Agent': 'geo-sra-skill/1.0'})
                with urlopen(req, timeout=10) as response:
                    success = True
            results.append((name, success, None))
        except Exception as e:
            results.append((name, False, str(e)))

    all_success = all(r[1] for r in results)

    msg_parts = []
    for name, success, error in results:
        status = "✓" if success else "✗"
        msg_parts.append(f"  {status} {name}: {'OK' if success else error or 'Failed'}")

    return all_success, "\n".join(msg_parts)


def fetch_geo_metadata(geo_id: str) -> Optional[Dict]:
    """
    Fetch GEO study metadata using NCBI Entrez E-utilities.

    Args:
        geo_id: GEO accession (e.g., 'GSE110004')

    Returns:
        Dict with study metadata or None if failed
    """
    try:
        # Use esearch to get GEO UID
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term={geo_id}[Accession]&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(search_url, timeout=30)
            data = response.json()
        else:
            with urlopen(search_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        id_list = data.get('esearchresult', {}).get('idlist', [])
        if not id_list:
            logger.warning(f"No GEO entry found for {geo_id}")
            return None

        # Use esummary to get metadata
        uid = id_list[0]
        summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gds&id={uid}&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(summary_url, timeout=30)
            data = response.json()
        else:
            with urlopen(summary_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        result = data.get('result', {}).get(uid, {})

        return {
            'geo_id': geo_id,
            'title': result.get('title', 'N/A'),
            'summary': result.get('summary', 'N/A'),
            'organism': result.get('taxon', 'N/A'),
            'n_samples': result.get('n_samples', 0),
            'gpl': result.get('gpl', 'N/A'),
            'entrytype': result.get('entrytype', 'N/A'),
            'pubmed_ids': result.get('pubmedids', []),
        }

    except Exception as e:
        logger.error(f"Error fetching GEO metadata for {geo_id}: {e}")
        return None


def fetch_sra_study_accession(geo_id: str) -> Optional[str]:
    """
    Get the SRA study accession (SRPxxxxxx) for a GEO accession.

    Args:
        geo_id: GEO accession (e.g., 'GSE110004')

    Returns:
        SRA study accession (e.g., 'SRP126328') or None
    """
    try:
        # Search for SRA study linked to GEO
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={geo_id}[GEO]&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(search_url, timeout=30)
            data = response.json()
        else:
            with urlopen(search_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        id_list = data.get('esearchresult', {}).get('idlist', [])
        if not id_list:
            return None

        # Get summary to extract SRP accession
        uid = id_list[0]
        summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=sra&id={uid}&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(summary_url, timeout=30)
            data = response.json()
        else:
            with urlopen(summary_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        result = data.get('result', {}).get(uid, {})
        exp_xml = result.get('expxml', '')

        # Extract SRP from the XML
        srp_match = re.search(r'<Study acc="(SRP\d+)"', exp_xml)
        if srp_match:
            return srp_match.group(1)

        return None

    except Exception as e:
        logger.debug(f"Error fetching SRA study for {geo_id}: {e}")
        return None


def fetch_sra_run_info(geo_id: str, bioproject: Optional[str] = None) -> List[Dict]:
    """
    Fetch SRA run information for all samples in a GEO study.

    Args:
        geo_id: GEO accession (e.g., 'GSE110004')
        bioproject: Optional BioProject accession for fallback search

    Returns:
        List of dicts with run info (srr, gsm, layout, library_strategy, etc.)
    """
    runs = []

    try:
        # First get the BioProject accession
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={geo_id}[GEO]&retmax=1000&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(search_url, timeout=30)
            data = response.json()
        else:
            with urlopen(search_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        id_list = data.get('esearchresult', {}).get('idlist', [])

        # If no results, try BioProject fallback
        if not id_list:
            if not bioproject:
                bioproject = fetch_bioproject_from_geo(geo_id)

            if bioproject:
                logger.info(f"Using BioProject {bioproject} for {geo_id}")
                search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={bioproject}&retmax=1000&retmode=json"

                _rate_limit_ncbi()
                if HAS_REQUESTS:
                    response = requests.get(search_url, timeout=30)
                    data = response.json()
                else:
                    with urlopen(search_url, timeout=30) as response:
                        data = json.loads(response.read().decode())

                id_list = data.get('esearchresult', {}).get('idlist', [])

        if not id_list:
            logger.warning(f"No SRA entries found for {geo_id}")
            return runs

        # Batch fetch summaries
        ids_str = ','.join(id_list)
        summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=sra&id={ids_str}&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(summary_url, timeout=60)
            data = response.json()
        else:
            with urlopen(summary_url, timeout=60) as response:
                data = json.loads(response.read().decode())

        result = data.get('result', {})

        for uid in id_list:
            entry = result.get(uid, {})
            if not entry:
                continue

            exp_xml = entry.get('expxml', '')
            runs_xml = entry.get('runs', '')

            # Extract metadata from XML
            layout_match = re.search(r'<LIBRARY_LAYOUT>\s*<(\w+)', exp_xml)
            strategy_match = re.search(r'<LIBRARY_STRATEGY>(\w+)', exp_xml)
            source_match = re.search(r'<LIBRARY_SOURCE>(\w+)', exp_xml)
            gsm_match = re.search(r'<Sample acc="(GSM\d+)"', exp_xml)
            srx_match = re.search(r'<Experiment acc="(SRX\d+)"', exp_xml)

            # Extract run accessions
            srr_matches = re.findall(r'<Run acc="(SRR\d+)"[^>]*total_spots="(\d+)"[^>]*total_bases="(\d+)"', runs_xml)

            for srr, spots, bases in srr_matches:
                runs.append({
                    'srr': srr,
                    'srx': srx_match.group(1) if srx_match else '',
                    'gsm': gsm_match.group(1) if gsm_match else '',
                    'layout': layout_match.group(1).upper() if layout_match else 'UNKNOWN',
                    'library_strategy': strategy_match.group(1) if strategy_match else 'UNKNOWN',
                    'library_source': source_match.group(1) if source_match else 'UNKNOWN',
                    'spots': int(spots),
                    'bases': int(bases),
                })

        return runs

    except Exception as e:
        logger.error(f"Error fetching SRA run info for {geo_id}: {e}")
        return runs


def fetch_ena_fastq_urls(study_accession: str) -> Dict[str, List[str]]:
    """
    Get FASTQ download URLs from ENA for an SRA study.

    ENA provides faster downloads than SRA with pre-split paired files.

    Args:
        study_accession: SRA study accession (e.g., 'SRP126328')

    Returns:
        Dict mapping SRR accession to list of FASTQ URLs
    """
    fastq_urls = {}

    try:
        # Query ENA API
        ena_url = f"https://www.ebi.ac.uk/ena/portal/api/filereport?accession={study_accession}&result=read_run&fields=run_accession,sample_alias,fastq_ftp&format=tsv"

        if HAS_REQUESTS:
            response = requests.get(ena_url, timeout=60)
            content = response.text
        else:
            with urlopen(ena_url, timeout=60) as response:
                content = response.read().decode()

        lines = content.strip().split('\n')
        if len(lines) < 2:
            logger.warning(f"No FASTQ URLs found in ENA for {study_accession}")
            return fastq_urls

        # Parse TSV
        header = lines[0].split('\t')
        run_idx = header.index('run_accession') if 'run_accession' in header else 0
        ftp_idx = header.index('fastq_ftp') if 'fastq_ftp' in header else 2

        for line in lines[1:]:
            if not line.strip():
                continue
            fields = line.split('\t')
            if len(fields) > max(run_idx, ftp_idx):
                srr = fields[run_idx]
                ftp_urls = fields[ftp_idx]
                if ftp_urls:
                    # URLs are semicolon-separated, convert to HTTP URLs
                    # ENA supports both FTP and HTTP, HTTP is easier with requests
                    urls = [f"http://{url}" for url in ftp_urls.split(';') if url]
                    fastq_urls[srr] = urls

        return fastq_urls

    except Exception as e:
        logger.error(f"Error fetching ENA URLs for {study_accession}: {e}")
        return fastq_urls


def download_file(url: str, output_path: Path, timeout: int = 300, show_progress: bool = True) -> bool:
    """
    Download a file with progress indication.

    Args:
        url: URL to download
        output_path: Path to save file
        timeout: Download timeout in seconds
        show_progress: Show progress bar

    Returns:
        True if successful, False otherwise
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if HAS_REQUESTS:
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            with open(output_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"\r  Progress: {pct:.1f}%", end='', flush=True)
                if show_progress:
                    print()  # New line after progress
            return True
        else:
            # Fallback to urllib
            req = Request(url, headers={'User-Agent': 'geo-sra-skill/1.0'})
            with urlopen(req, timeout=timeout) as response:
                with open(output_path, 'wb') as f:
                    shutil.copyfileobj(response, f)
            return True

    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
        return False


def fetch_pubmed_metadata(pmid: str, max_retries: int = 3) -> Optional[Dict]:
    """
    Fetch paper metadata from PubMed.

    Args:
        pmid: PubMed ID
        max_retries: Number of retries on failure

    Returns:
        Dict with 'authors', 'year', 'journal', 'doi' or None
    """
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"

    for attempt in range(max_retries):
        try:
            _rate_limit_ncbi()
            if HAS_REQUESTS:
                response = requests.get(url, timeout=30)
                data = response.json()
            else:
                with urlopen(url, timeout=30) as response:
                    data = json.loads(response.read().decode())

            result = data.get('result', {}).get(pmid, {})

            if not result or 'error' in result:
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue
                return None

            # Extract authors
            authors_list = result.get('authors', [])
            if not authors_list:
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                    continue
                return None

            author_names = [f"{a.get('name', '')}" for a in authors_list[:3]]
            authors = ', '.join(author_names)
            if len(authors_list) > 3:
                authors += ', et al.'

            # Extract year
            pubdate = result.get('pubdate', '')
            year_match = re.search(r'\b(20\d{2})\b', pubdate)
            year = year_match.group(1) if year_match else "Unknown"

            # Extract journal
            journal = result.get('source', 'Unknown')

            # Extract DOI
            doi = ""
            for aid in result.get('articleids', []):
                if aid.get('idtype') == 'doi':
                    doi = aid.get('value', '')
                    break

            return {
                'authors': authors,
                'year': year,
                'journal': journal,
                'doi': doi,
                'title': result.get('title', '')
            }

        except Exception as e:
            logger.debug(f"PubMed fetch error for PMID {pmid} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
            continue

    return None


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def estimate_download_size(runs: List[Dict]) -> int:
    """
    Estimate total download size from SRA run info.

    Args:
        runs: List of run info dicts with 'bases' field

    Returns:
        Estimated size in bytes (rough estimate based on bases)
    """
    total_bases = sum(r.get('bases', 0) for r in runs)
    # FASTQ is roughly 1 byte per base when compressed
    return total_bases // 4  # Rough compression ratio


def fetch_bioproject_from_geo(geo_id: str) -> Optional[str]:
    """
    Fetch BioProject accession linked to a GEO study.

    Args:
        geo_id: GEO accession (e.g., 'GSE110004')

    Returns:
        BioProject accession (e.g., 'PRJNA432544') or None
    """
    try:
        # First get GDS UID
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term={geo_id}[Accession]&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(search_url, timeout=30)
            data = response.json()
        else:
            with urlopen(search_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        gds_ids = data.get('esearchresult', {}).get('idlist', [])
        if not gds_ids:
            return None

        # Get linked BioProject
        elink_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=gds&db=bioproject&id={gds_ids[0]}&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(elink_url, timeout=30)
            data = response.json()
        else:
            with urlopen(elink_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        linksets = data.get('linksets', [])
        if linksets and linksets[0].get('linksetdbs'):
            for linksetdb in linksets[0]['linksetdbs']:
                if linksetdb.get('dbto') == 'bioproject':
                    bp_ids = linksetdb.get('links', [])
                    if bp_ids:
                        # Get BioProject accession
                        summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=bioproject&id={bp_ids[0]}&retmode=json"
                        _rate_limit_ncbi()
                        if HAS_REQUESTS:
                            response = requests.get(summary_url, timeout=30)
                            data = response.json()
                        else:
                            with urlopen(summary_url, timeout=30) as response:
                                data = json.loads(response.read().decode())

                        result = data.get('result', {}).get(str(bp_ids[0]), {})
                        return result.get('project_acc')

        return None

    except Exception as e:
        logger.debug(f"Error fetching BioProject for {geo_id}: {e}")
        return None


def fetch_sra_run_info_detailed(geo_id: str, bioproject: Optional[str] = None) -> List[Dict]:
    """
    Fetch detailed SRA run information using efetch CSV format.

    This provides richer metadata than esummary, including sample names.

    Args:
        geo_id: GEO accession (e.g., 'GSE110004')
        bioproject: Optional BioProject accession for fallback search

    Returns:
        List of dicts with detailed run info
    """
    runs = []

    try:
        # First get SRA UIDs using GEO search
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={geo_id}[GEO]&retmax=1000&retmode=json"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(search_url, timeout=30)
            data = response.json()
        else:
            with urlopen(search_url, timeout=30) as response:
                data = json.loads(response.read().decode())

        id_list = data.get('esearchresult', {}).get('idlist', [])

        # If no results with GEO search, try BioProject
        if not id_list:
            # Try to find BioProject if not provided
            if not bioproject:
                logger.info(f"No direct SRA link for {geo_id}, searching for BioProject...")
                bioproject = fetch_bioproject_from_geo(geo_id)

            if bioproject:
                logger.info(f"Found BioProject: {bioproject}")
                search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={bioproject}&retmax=1000&retmode=json"

                _rate_limit_ncbi()
                if HAS_REQUESTS:
                    response = requests.get(search_url, timeout=30)
                    data = response.json()
                else:
                    with urlopen(search_url, timeout=30) as response:
                        data = json.loads(response.read().decode())

                id_list = data.get('esearchresult', {}).get('idlist', [])

        if not id_list:
            logger.warning(f"No SRA entries found for {geo_id}")
            return runs

        # Fetch run info in CSV format using efetch
        ids_str = ','.join(id_list)
        efetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id={ids_str}&rettype=runinfo&retmode=csv"

        _rate_limit_ncbi()
        if HAS_REQUESTS:
            response = requests.get(efetch_url, timeout=60)
            content = response.text
        else:
            with urlopen(efetch_url, timeout=60) as response:
                content = response.read().decode()

        lines = content.strip().split('\n')
        if len(lines) < 1:
            return runs

        # NCBI efetch runinfo CSV doesn't include headers
        # Define the fixed column order for SRA runinfo format
        header = [
            'Run', 'ReleaseDate', 'LoadDate', 'spots', 'bases', 'spots_with_mates',
            'avgLength', 'size_MB', 'AssemblyName', 'download_path', 'Experiment',
            'LibraryName', 'LibraryStrategy', 'LibrarySelection', 'LibrarySource',
            'LibraryLayout', 'InsertSize', 'InsertDev', 'Platform', 'Model',
            'SRAStudy', 'BioProject', 'Study_Pubmed_id', 'ProjectID', 'Sample',
            'BioSample', 'SampleType', 'TaxID', 'ScientificName', 'SampleName',
            'g1k_pop_code', 'source', 'g1k_analysis_group', 'Subject_ID', 'Sex',
            'Disease', 'Tumor', 'Affection_Status', 'Analyte_Type', 'Histological_Type',
            'Body_Site', 'CenterName', 'Submission', 'dbgap_study_accession', 'Consent',
            'RunHash', 'ReadHash'
        ]

        # Map column names to indices
        col_map = {col: idx for idx, col in enumerate(header)}

        for line in lines:
            if not line.strip():
                continue

            # Handle CSV fields (some may contain commas in quotes)
            fields = _parse_csv_line(line)
            if len(fields) < len(header):
                continue

            def get_field(name, default=''):
                idx = col_map.get(name, -1)
                return fields[idx] if idx >= 0 and idx < len(fields) else default

            run = {
                'srr': get_field('Run'),
                'srx': get_field('Experiment'),
                'gsm': get_field('SampleName'),  # Often GSM ID
                'sample_name': get_field('SampleName'),
                'library_name': get_field('LibraryName'),
                'layout': get_field('LibraryLayout', 'UNKNOWN').upper(),
                'library_strategy': get_field('LibraryStrategy', 'UNKNOWN'),
                'library_source': get_field('LibrarySource', 'UNKNOWN'),
                'library_selection': get_field('LibrarySelection', ''),
                'platform': get_field('Platform'),
                'model': get_field('Model'),
                'organism': get_field('ScientificName', ''),
                'spots': int(get_field('spots', 0) or 0),
                'bases': int(get_field('bases', 0) or 0),
                'size_mb': float(get_field('size_MB', 0) or 0),
                'bioproject': get_field('BioProject'),
                'biosample': get_field('BioSample'),
                'sra_study': get_field('SRAStudy'),
            }

            # Only add if we have a valid SRR
            if run['srr'].startswith('SRR'):
                runs.append(run)

        return runs

    except Exception as e:
        logger.error(f"Error fetching detailed SRA run info for {geo_id}: {e}")
        return runs


def _parse_csv_line(line: str) -> List[str]:
    """Parse a CSV line handling quoted fields."""
    import csv
    import io
    reader = csv.reader(io.StringIO(line))
    for row in reader:
        return row
    return []


def group_samples_by_type(runs: List[Dict]) -> Dict[str, Dict]:
    """
    Group SRA runs by library type and layout.

    Returns dict with group names as keys and info dicts as values:
    {
        'RNA-Seq:PAIRED': {
            'runs': [...],
            'count': 18,
            'gsm_range': 'GSM2879618-GSM2879635',
            'size_estimate': 50000000000,
            'description': 'RNA-Seq paired-end'
        },
        ...
    }
    """
    groups = {}

    for run in runs:
        strategy = run.get('library_strategy', 'UNKNOWN')
        layout = run.get('layout', 'UNKNOWN')
        key = f"{strategy}:{layout}"

        if key not in groups:
            groups[key] = {
                'runs': [],
                'gsm_ids': set(),
                'total_bases': 0,
                'strategy': strategy,
                'layout': layout,
            }

        groups[key]['runs'].append(run)
        gsm = run.get('gsm', '')
        if gsm.startswith('GSM'):
            groups[key]['gsm_ids'].add(gsm)
        groups[key]['total_bases'] += run.get('bases', 0)

    # Post-process groups
    result = {}
    for key, info in groups.items():
        gsm_list = sorted(info['gsm_ids'])
        gsm_range = _format_gsm_range(gsm_list) if gsm_list else 'N/A'

        result[key] = {
            'runs': info['runs'],
            'count': len(info['runs']),
            'gsm_range': gsm_range,
            'gsm_ids': gsm_list,
            'size_estimate': info['total_bases'] // 4,  # Rough compressed size
            'strategy': info['strategy'],
            'layout': info['layout'],
            'description': f"{info['strategy']} {info['layout'].lower()}",
        }

    return result


def _format_gsm_range(gsm_list: List[str]) -> str:
    """Format list of GSM IDs as a range if consecutive."""
    if not gsm_list:
        return 'N/A'

    if len(gsm_list) == 1:
        return gsm_list[0]

    # Extract numbers and check if consecutive
    try:
        numbers = [int(gsm.replace('GSM', '')) for gsm in gsm_list]
        numbers.sort()

        if numbers[-1] - numbers[0] == len(numbers) - 1:
            # Consecutive
            return f"GSM{numbers[0]}-GSM{numbers[-1]}"
        else:
            # Not consecutive, show count
            return f"{gsm_list[0]}...({len(gsm_list)} samples)"
    except ValueError:
        return f"{len(gsm_list)} samples"


def format_sample_groups_table(groups: Dict[str, Dict]) -> str:
    """Format sample groups as a readable table."""
    lines = []
    lines.append("")
    lines.append(f"{'Sample Group':<20} {'Count':>6} {'Layout':<10} {'GSM Range':<25} {'Est. Size':>12}")
    lines.append("-" * 80)

    for key, info in sorted(groups.items(), key=lambda x: -x[1]['count']):
        size_str = format_file_size(info['size_estimate'])
        lines.append(
            f"{info['strategy']:<20} {info['count']:>6} {info['layout']:<10} "
            f"{info['gsm_range']:<25} {size_str:>12}"
        )

    lines.append("-" * 80)
    total_runs = sum(g['count'] for g in groups.values())
    total_size = sum(g['size_estimate'] for g in groups.values())
    lines.append(f"{'TOTAL':<20} {total_runs:>6} {'':<10} {'':<25} {format_file_size(total_size):>12}")

    return '\n'.join(lines)
