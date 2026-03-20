#!/usr/bin/env python3
"""
Genome reference management for nf-core pipelines.

Manages downloading, caching, and accessing genome references from iGenomes.
Supports auto-download when references aren't available locally.

Usage:
    python manage_genomes.py list
    python manage_genomes.py check GRCh38
    python manage_genomes.py download GRCh38
    python manage_genomes.py params GRCh38
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


# iGenomes reference configuration
IGENOMES = {
    # Human
    'GRCh38': {
        'display_name': 'Human GRCh38/hg38',
        'species': 'Homo sapiens',
        'aliases': ['hg38', 'GRCh38.p14'],
        's3_base': 's3://ngi-igenomes/igenomes/Homo_sapiens/NCBI/GRCh38',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    'GRCh37': {
        'display_name': 'Human GRCh37/hg19',
        'species': 'Homo sapiens',
        'aliases': ['hg19', 'GRCh37.p13'],
        's3_base': 's3://ngi-igenomes/igenomes/Homo_sapiens/NCBI/GRCh37',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Mouse
    'GRCm39': {
        'display_name': 'Mouse GRCm39/mm39',
        'species': 'Mus musculus',
        'aliases': ['mm39', 'GRCm39'],
        's3_base': 's3://ngi-igenomes/igenomes/Mus_musculus/Ensembl/GRCm39',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    'GRCm38': {
        'display_name': 'Mouse GRCm38/mm10',
        'species': 'Mus musculus',
        'aliases': ['mm10', 'GRCm38'],
        's3_base': 's3://ngi-igenomes/igenomes/Mus_musculus/NCBI/GRCm38',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Yeast
    'R64-1-1': {
        'display_name': 'Yeast R64-1-1/sacCer3',
        'species': 'Saccharomyces cerevisiae',
        'aliases': ['sacCer3', 'S288C', 'yeast'],
        's3_base': 's3://ngi-igenomes/igenomes/Saccharomyces_cerevisiae/Ensembl/R64-1-1',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Fruit fly
    'BDGP6': {
        'display_name': 'Drosophila BDGP6/dm6',
        'species': 'Drosophila melanogaster',
        'aliases': ['dm6', 'BDGP6', 'fly'],
        's3_base': 's3://ngi-igenomes/igenomes/Drosophila_melanogaster/Ensembl/BDGP6',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
        }
    },
    # C. elegans
    'WBcel235': {
        'display_name': 'C. elegans WBcel235/ce11',
        'species': 'Caenorhabditis elegans',
        'aliases': ['ce11', 'worm'],
        's3_base': 's3://ngi-igenomes/igenomes/Caenorhabditis_elegans/Ensembl/WBcel235',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Zebrafish
    'GRCz11': {
        'display_name': 'Zebrafish GRCz11/danRer11',
        'species': 'Danio rerio',
        'aliases': ['danRer11', 'zebrafish'],
        's3_base': 's3://ngi-igenomes/igenomes/Danio_rerio/Ensembl/GRCz11',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    'GRCz10': {
        'display_name': 'Zebrafish GRCz10/danRer10',
        'species': 'Danio rerio',
        'aliases': ['danRer10'],
        's3_base': 's3://ngi-igenomes/igenomes/Danio_rerio/Ensembl/GRCz10',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
        }
    },
    # Rat
    'Rnor_6.0': {
        'display_name': 'Rat Rnor_6.0/rn6',
        'species': 'Rattus norvegicus',
        'aliases': ['rn6', 'Rnor6', 'rat'],
        's3_base': 's3://ngi-igenomes/igenomes/Rattus_norvegicus/Ensembl/Rnor_6.0',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Arabidopsis
    'TAIR10': {
        'display_name': 'Arabidopsis TAIR10',
        'species': 'Arabidopsis thaliana',
        'aliases': ['arabidopsis'],
        's3_base': 's3://ngi-igenomes/igenomes/Arabidopsis_thaliana/Ensembl/TAIR10',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
            'bwa_index': 'Sequence/BWAIndex/',
            'star_index': 'Sequence/STARIndex/',
        }
    },
    # Chicken
    'GRCg6a': {
        'display_name': 'Chicken GRCg6a/galGal6',
        'species': 'Gallus gallus',
        'aliases': ['galGal6', 'chicken'],
        's3_base': 's3://ngi-igenomes/igenomes/Gallus_gallus/Ensembl/GRCg6a',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
        }
    },
    # Dog
    'CanFam3.1': {
        'display_name': 'Dog CanFam3.1/canFam3',
        'species': 'Canis lupus familiaris',
        'aliases': ['canFam3', 'dog'],
        's3_base': 's3://ngi-igenomes/igenomes/Canis_familiaris/Ensembl/CanFam3.1',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
        }
    },
    # Pig
    'Sscrofa11.1': {
        'display_name': 'Pig Sscrofa11.1/susScr11',
        'species': 'Sus scrofa',
        'aliases': ['susScr11', 'pig'],
        's3_base': 's3://ngi-igenomes/igenomes/Sus_scrofa/Ensembl/Sscrofa11.1',
        'files': {
            'fasta': 'Sequence/WholeGenomeFasta/genome.fa',
            'gtf': 'Annotation/Genes/genes.gtf',
        }
    },
}


def get_cache_dir() -> Path:
    """Get genome cache directory."""
    cache_dir = os.environ.get(
        'NF_CORE_GENOME_CACHE',
        os.path.expanduser('~/.nf-core/genomes')
    )
    return Path(cache_dir)


def resolve_genome_id(genome: str) -> Optional[str]:
    """Resolve genome ID from name or alias."""
    # Direct match
    if genome in IGENOMES:
        return genome

    # Check aliases
    genome_lower = genome.lower()
    for gid, info in IGENOMES.items():
        if genome_lower in [a.lower() for a in info.get('aliases', [])]:
            return gid

    return None


def is_genome_installed(genome_id: str) -> bool:
    """Check if genome is installed locally."""
    cache_dir = get_cache_dir()
    genome_dir = cache_dir / genome_id

    # Check for fasta as minimum requirement
    fasta_path = genome_dir / 'genome.fa'
    return fasta_path.exists()


def get_genome_path(genome_id: str) -> Optional[Path]:
    """Get local path to genome if installed."""
    if not is_genome_installed(genome_id):
        return None
    return get_cache_dir() / genome_id


def list_genomes(installed_only: bool = False) -> List[Dict]:
    """List available genomes."""
    result = []

    for genome_id, info in IGENOMES.items():
        installed = is_genome_installed(genome_id)

        if installed_only and not installed:
            continue

        genome_path = get_genome_path(genome_id) if installed else None

        result.append({
            'id': genome_id,
            'display_name': info['display_name'],
            'species': info['species'],
            'aliases': info.get('aliases', []),
            'installed': installed,
            'path': str(genome_path) if genome_path else None,
        })

    return result


def download_genome(
    genome_id: str,
    components: Optional[List[str]] = None,
    force: bool = False
) -> bool:
    """
    Download genome reference files from iGenomes.

    Args:
        genome_id: Genome identifier (e.g., GRCh38)
        components: Specific components to download (fasta, gtf, etc.)
        force: Overwrite existing files

    Returns:
        True if successful
    """
    # Resolve genome ID
    resolved = resolve_genome_id(genome_id)
    if not resolved:
        print(f"Unknown genome: {genome_id}")
        print(f"Available: {', '.join(IGENOMES.keys())}")
        return False

    genome_id = resolved
    info = IGENOMES[genome_id]

    # Check for AWS CLI
    aws_available = subprocess.run(
        ['which', 'aws'],
        capture_output=True
    ).returncode == 0

    if not aws_available:
        print("AWS CLI not found. Required for iGenomes download.")
        print("Install with: pip install awscli")
        print("\nAlternative: Use --genome flag with nf-core pipelines")
        print("which will auto-download references (slower, per-run).")
        return False

    # Create cache directory
    cache_dir = get_cache_dir()
    genome_dir = cache_dir / genome_id
    genome_dir.mkdir(parents=True, exist_ok=True)

    # Determine components to download
    if components is None:
        components = ['fasta', 'gtf']  # Minimum required

    print(f"Downloading {info['display_name']} to {genome_dir}")
    print(f"Components: {', '.join(components)}")

    success = True
    for component in components:
        if component not in info.get('files', {}):
            print(f"  Skipping {component}: not available for {genome_id}")
            continue

        remote_path = info['files'][component]
        s3_path = f"{info['s3_base']}/{remote_path}"

        # Determine local path
        if remote_path.endswith('/'):
            # Directory (e.g., index)
            local_path = genome_dir / component
        else:
            # File
            filename = Path(remote_path).name
            local_path = genome_dir / filename

        if local_path.exists() and not force:
            print(f"  {component}: Already exists (use --force to overwrite)")
            continue

        print(f"  Downloading {component}...")

        # Build AWS command
        cmd = ['aws', 's3', 'cp', '--no-sign-request']

        if remote_path.endswith('/'):
            cmd.extend(['--recursive', s3_path, str(local_path)])
        else:
            cmd.extend([s3_path, str(local_path)])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  ERROR downloading {component}:")
            print(f"    {result.stderr[:200]}")
            success = False
        else:
            print(f"  {component}: Downloaded successfully")

    if success:
        print(f"\nGenome {genome_id} ready at: {genome_dir}")
    else:
        print(f"\nSome components failed to download.")

    return success


def get_nextflow_params(genome_id: str) -> Dict[str, str]:
    """
    Get Nextflow parameters for a genome.

    Returns dict with --fasta, --gtf if local,
    or just --genome if using iGenomes key.
    """
    resolved = resolve_genome_id(genome_id)
    if not resolved:
        return {'error': f'Unknown genome: {genome_id}'}

    genome_id = resolved

    # Check if installed locally
    genome_path = get_genome_path(genome_id)

    if genome_path:
        params = {}

        # Check for local files
        fasta = genome_path / 'genome.fa'
        if fasta.exists():
            params['fasta'] = str(fasta)

        gtf = genome_path / 'genes.gtf'
        if gtf.exists():
            params['gtf'] = str(gtf)

        if params:
            return params

    # Fall back to iGenomes key
    return {'genome': genome_id}


def print_genome_list(genomes: List[Dict], output_json: bool = False):
    """Print genome list."""
    if output_json:
        print(json.dumps(genomes, indent=2))
        return

    print("\n" + "=" * 50)
    print("  Available Genomes")
    print("=" * 50 + "\n")

    for g in genomes:
        status = "\033[92m[installed]\033[0m" if g['installed'] else ""
        print(f"  {g['id']}: {g['display_name']} {status}")
        print(f"      Species: {g['species']}")
        print(f"      Aliases: {', '.join(g['aliases'])}")
        if g['path']:
            print(f"      Path: {g['path']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='Manage genome references for nf-core pipelines',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
    list              List available genomes
    check <genome>    Check if genome is installed
    download <genome> Download genome from iGenomes
    params <genome>   Get Nextflow parameters for genome

Examples:
    %(prog)s list
    %(prog)s list --installed
    %(prog)s check GRCh38
    %(prog)s download GRCh38
    %(prog)s download GRCh38 --components fasta gtf star_index
    %(prog)s params GRCh38
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # List command
    list_parser = subparsers.add_parser('list', help='List available genomes')
    list_parser.add_argument('--installed', action='store_true',
                             help='Show only installed genomes')
    list_parser.add_argument('--json', action='store_true',
                             help='Output as JSON')

    # Check command
    check_parser = subparsers.add_parser('check', help='Check if genome is installed')
    check_parser.add_argument('genome', help='Genome ID (e.g., GRCh38)')
    check_parser.add_argument('--json', action='store_true',
                              help='Output as JSON')

    # Download command
    dl_parser = subparsers.add_parser('download', help='Download genome from iGenomes')
    dl_parser.add_argument('genome', help='Genome ID (e.g., GRCh38)')
    dl_parser.add_argument('--components', nargs='+',
                           help='Specific components (fasta, gtf, bwa_index, star_index)')
    dl_parser.add_argument('--force', action='store_true',
                           help='Overwrite existing files')

    # Params command
    params_parser = subparsers.add_parser('params', help='Get Nextflow params for genome')
    params_parser.add_argument('genome', help='Genome ID')
    params_parser.add_argument('--json', action='store_true',
                               help='Output as JSON')

    args = parser.parse_args()

    if args.command == 'list':
        genomes = list_genomes(installed_only=args.installed)
        print_genome_list(genomes, args.json)

    elif args.command == 'check':
        resolved = resolve_genome_id(args.genome)
        if not resolved:
            print(f"Unknown genome: {args.genome}")
            sys.exit(1)

        installed = is_genome_installed(resolved)
        path = get_genome_path(resolved) if installed else None

        if args.json:
            print(json.dumps({
                'genome': resolved,
                'installed': installed,
                'path': str(path) if path else None
            }))
        else:
            if installed:
                print(f"✓ Genome {resolved} is installed at: {path}")
            else:
                print(f"✗ Genome {resolved} is not installed locally")
                print(f"  Download with: python {sys.argv[0]} download {resolved}")

        sys.exit(0 if installed else 1)

    elif args.command == 'download':
        success = download_genome(args.genome, args.components, args.force)
        sys.exit(0 if success else 1)

    elif args.command == 'params':
        params = get_nextflow_params(args.genome)

        if args.json:
            print(json.dumps(params))
        else:
            if 'error' in params:
                print(f"Error: {params['error']}")
                sys.exit(1)

            for key, value in params.items():
                print(f"--{key} {value}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
