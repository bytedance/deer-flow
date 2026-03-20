#!/usr/bin/env python3
"""
Quality Control Analysis for Single-Cell RNA-seq Data
Following scverse best practices from:
https://www.sc-best-practices.org/preprocessing_visualization/quality_control.html

This is a convenience script that runs a complete QC workflow using the
modular functions from qc_core.py and qc_plotting.py.
"""

import anndata as ad
import scanpy as sc
import sys
import os
import argparse

# Import our modular utilities
from qc_core import (
    calculate_qc_metrics,
    detect_outliers_mad,
    apply_hard_threshold,
    filter_cells,
    filter_genes,
    print_qc_summary
)
from qc_plotting import (
    plot_qc_distributions,
    plot_filtering_thresholds,
    plot_qc_after_filtering
)

print("=" * 80)
print("Single-Cell RNA-seq Quality Control Analysis")
print("=" * 80)

# Default parameters (single source of truth)
DEFAULT_MAD_COUNTS = 5
DEFAULT_MAD_GENES = 5
DEFAULT_MAD_MT = 3
DEFAULT_MT_THRESHOLD = 8
DEFAULT_MIN_CELLS = 20
DEFAULT_MT_PATTERN = 'mt-,MT-'
DEFAULT_RIBO_PATTERN = 'Rpl,Rps,RPL,RPS'
DEFAULT_HB_PATTERN = '^Hb[^(p)]|^HB[^(P)]'

# Parse command-line arguments
parser = argparse.ArgumentParser(
    description='Quality Control Analysis for Single-Cell RNA-seq Data',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python3 qc_analysis.py data.h5ad
  python3 qc_analysis.py raw_feature_bc_matrix.h5
  python3 qc_analysis.py data.h5ad --mad-counts 4 --mad-genes 4 --mad-mt 2.5
  python3 qc_analysis.py data.h5ad --mt-threshold 10 --min-cells 10
  python3 qc_analysis.py data.h5ad --mt-pattern "^mt-" --ribo-pattern "^Rpl,^Rps"
    """
)

parser.add_argument('input_file', help='Input .h5ad or .h5 file (10X Genomics format)')
parser.add_argument('--output-dir', type=str, help='Output directory (default: <input_basename>_qc_results)')
parser.add_argument('--mad-counts', type=float, default=DEFAULT_MAD_COUNTS, help=f'MAD threshold for total counts (default: {DEFAULT_MAD_COUNTS})')
parser.add_argument('--mad-genes', type=float, default=DEFAULT_MAD_GENES, help=f'MAD threshold for gene counts (default: {DEFAULT_MAD_GENES})')
parser.add_argument('--mad-mt', type=float, default=DEFAULT_MAD_MT, help=f'MAD threshold for mitochondrial percentage (default: {DEFAULT_MAD_MT})')
parser.add_argument('--mt-threshold', type=float, default=DEFAULT_MT_THRESHOLD, help=f'Hard threshold for mitochondrial percentage (default: {DEFAULT_MT_THRESHOLD})')
parser.add_argument('--min-cells', type=int, default=DEFAULT_MIN_CELLS, help=f'Minimum cells for gene filtering (default: {DEFAULT_MIN_CELLS})')
parser.add_argument('--mt-pattern', type=str, default=DEFAULT_MT_PATTERN, help=f'Comma-separated mitochondrial gene prefixes (default: "{DEFAULT_MT_PATTERN}")')
parser.add_argument('--ribo-pattern', type=str, default=DEFAULT_RIBO_PATTERN, help=f'Comma-separated ribosomal gene prefixes (default: "{DEFAULT_RIBO_PATTERN}")')
parser.add_argument('--hb-pattern', type=str, default=DEFAULT_HB_PATTERN, help=f'Hemoglobin gene regex pattern (default: "{DEFAULT_HB_PATTERN}")')

args = parser.parse_args()

# Verify input file exists
if not os.path.exists(args.input_file):
    print(f"\nError: File '{args.input_file}' not found!")
    sys.exit(1)

input_file = args.input_file
base_name = os.path.splitext(os.path.basename(input_file))[0]

# Set up output directory
if args.output_dir:
    output_dir = args.output_dir
else:
    output_dir = f"{base_name}_qc_results"

os.makedirs(output_dir, exist_ok=True)
print(f"\nOutput directory: {output_dir}")

# Display parameters
print(f"\nParameters:")
print(f"  MAD thresholds: counts={args.mad_counts}, genes={args.mad_genes}, MT%={args.mad_mt}")
print(f"  MT hard threshold: {args.mt_threshold}%")
print(f"  Min cells for gene filtering: {args.min_cells}")
print(f"  Gene patterns: MT={args.mt_pattern}, Ribo={args.ribo_pattern}")

# Load the data
print("\n[1/5] Loading data...")
file_ext = os.path.splitext(input_file)[1].lower()

if file_ext == '.h5ad':
    adata = ad.read_h5ad(input_file)
    print(f"Loaded .h5ad file: {adata.n_obs} cells × {adata.n_vars} genes")
elif file_ext == '.h5':
    adata = sc.read_10x_h5(input_file)
    print(f"Loaded 10X .h5 file: {adata.n_obs} cells × {adata.n_vars} genes")
    # Make variable names unique (10X data sometimes has duplicate gene names)
    adata.var_names_make_unique()
else:
    print(f"\nError: Unsupported file format '{file_ext}'. Expected .h5ad or .h5")
    sys.exit(1)

# Store original counts for comparison
n_cells_original = adata.n_obs
n_genes_original = adata.n_vars

# Calculate QC metrics
print("\n[2/5] Calculating QC metrics...")
calculate_qc_metrics(adata, mt_pattern=args.mt_pattern,
                     ribo_pattern=args.ribo_pattern,
                     hb_pattern=args.hb_pattern,
                     inplace=True)

print(f"  Found {adata.var['mt'].sum()} mitochondrial genes (pattern: {args.mt_pattern})")
print(f"  Found {adata.var['ribo'].sum()} ribosomal genes (pattern: {args.ribo_pattern})")
print(f"  Found {adata.var['hb'].sum()} hemoglobin genes (pattern: {args.hb_pattern})")

print_qc_summary(adata, label='QC Metrics Summary (before filtering)')

# Create before-filtering visualizations
print("\n[3/5] Creating QC visualizations...")
before_plot = os.path.join(output_dir, 'qc_metrics_before_filtering.png')
plot_qc_distributions(adata, before_plot, title='Quality Control Metrics - Before Filtering')
print(f"  Saved: {before_plot}")

# Apply MAD-based filtering
print("\n[4/5] Applying MAD-based filtering thresholds...")

# Detect outliers for each metric
adata.obs['outlier_counts'] = detect_outliers_mad(adata, 'total_counts', args.mad_counts)
adata.obs['outlier_genes'] = detect_outliers_mad(adata, 'n_genes_by_counts', args.mad_genes)
adata.obs['outlier_mt'] = detect_outliers_mad(adata, 'pct_counts_mt', args.mad_mt)

# Apply hard threshold for mitochondrial content
print(f"\n  Applying hard threshold for mitochondrial content (>{args.mt_threshold}%):")
high_mt_mask = apply_hard_threshold(adata, 'pct_counts_mt', args.mt_threshold, operator='>')

# Combine MT filters (MAD + hard threshold)
adata.obs['outlier_mt'] = adata.obs['outlier_mt'] | high_mt_mask

# Overall filtering decision
adata.obs['pass_qc'] = ~(
    adata.obs['outlier_counts'] |
    adata.obs['outlier_genes'] |
    adata.obs['outlier_mt']
)

print(f"\n  Total cells failing QC: {(~adata.obs['pass_qc']).sum()} ({(~adata.obs['pass_qc']).sum()/adata.n_obs*100:.2f}%)")
print(f"  Cells passing QC: {adata.obs['pass_qc'].sum()} ({adata.obs['pass_qc'].sum()/adata.n_obs*100:.2f}%)")

# Visualize filtering thresholds
outlier_masks = {
    'total_counts': adata.obs['outlier_counts'].values,
    'n_genes_by_counts': adata.obs['outlier_genes'].values,
    'pct_counts_mt': adata.obs['outlier_mt'].values
}

thresholds = {
    'total_counts': {'n_mads': args.mad_counts},
    'n_genes_by_counts': {'n_mads': args.mad_genes},
    'pct_counts_mt': {'n_mads': args.mad_mt, 'hard': args.mt_threshold}
}

threshold_plot = os.path.join(output_dir, 'qc_filtering_thresholds.png')
plot_filtering_thresholds(adata, outlier_masks, thresholds, threshold_plot)
print(f"\n  Saved: {threshold_plot}")

# Apply filtering
print("\n[5/5] Applying filters...")
adata_filtered = filter_cells(adata, adata.obs['pass_qc'].values, inplace=False)
print(f"  Cells after filtering: {adata_filtered.n_obs} (removed {n_cells_original - adata_filtered.n_obs})")

# Filter genes
print(f"\n  Filtering genes detected in <{args.min_cells} cells...")
filter_genes(adata_filtered, min_cells=args.min_cells, inplace=True)
print(f"  Genes after filtering: {adata_filtered.n_vars} (removed {n_genes_original - adata_filtered.n_vars})")

# Generate summary statistics
print("\n" + "=" * 80)
print("QC Summary")
print("=" * 80)

print("\nBefore filtering:")
print(f"  Cells: {n_cells_original}")
print(f"  Genes: {n_genes_original}")

print("\nAfter filtering:")
print(f"  Cells: {adata_filtered.n_obs} ({adata_filtered.n_obs/n_cells_original*100:.1f}% retained)")
print(f"  Genes: {adata_filtered.n_vars} ({adata_filtered.n_vars/n_genes_original*100:.1f}% retained)")

print_qc_summary(adata_filtered, label='\nFiltered data QC metrics')

# Create after-filtering visualizations
after_plot = os.path.join(output_dir, 'qc_metrics_after_filtering.png')
plot_qc_after_filtering(adata_filtered, after_plot)
print(f"\n  Saved: {after_plot}")

# Save filtered data
print("\nSaving filtered data...")
output_filtered = os.path.join(output_dir, f'{base_name}_filtered.h5ad')
output_with_qc = os.path.join(output_dir, f'{base_name}_with_qc.h5ad')
adata_filtered.write(output_filtered)
print(f"  Saved: {output_filtered}")

# Also save the unfiltered data with QC annotations
adata.write(output_with_qc)
print(f"  Saved: {output_with_qc} (original data with QC annotations)")

print("\n" + "=" * 80)
print("Quality Control Analysis Complete!")
print("=" * 80)
print(f"\nAll results saved to: {output_dir}/")
print("\nGenerated files:")
print("  1. qc_metrics_before_filtering.png - Initial QC visualizations")
print("  2. qc_filtering_thresholds.png - MAD-based threshold visualization")
print("  3. qc_metrics_after_filtering.png - Post-filtering QC visualizations")
print(f"  4. {base_name}_filtered.h5ad - Filtered dataset")
print(f"  5. {base_name}_with_qc.h5ad - Original dataset with QC annotations")
print("\nNext steps:")
print("  - Consider ambient RNA correction (SoupX)")
print("  - Consider doublet detection (scDblFinder)")
print("  - Proceed with normalization and downstream analysis")
