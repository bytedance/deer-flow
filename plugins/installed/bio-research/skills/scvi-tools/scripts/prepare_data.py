#!/usr/bin/env python3
"""
Prepare AnnData for scvi-tools models.

This script handles QC filtering, HVG selection, and layer setup.
Output is ready for any scvi-tools model.

Usage:
    python prepare_data.py input.h5ad output.h5ad --batch-key batch --n-hvgs 2000
    python prepare_data.py input.h5ad output.h5ad --no-filter  # Skip QC filtering
"""

import argparse
import sys


def prepare_data(
    adata,
    batch_key=None,
    n_top_genes=2000,
    min_genes=200,
    max_genes=5000,
    max_mito_pct=20.0,
    min_cells=3,
    skip_filter=False
):
    """
    Prepare AnnData for scvi-tools.

    Parameters
    ----------
    adata : AnnData
        Raw count data
    batch_key : str, optional
        Batch column for batch-aware HVG selection
    n_top_genes : int
        Number of highly variable genes
    min_genes : int
        Minimum genes per cell
    max_genes : int
        Maximum genes per cell
    max_mito_pct : float
        Maximum mitochondrial percentage
    min_cells : int
        Minimum cells per gene
    skip_filter : bool
        Skip QC filtering (use if already filtered)

    Returns
    -------
    AnnData prepared for scvi-tools
    """
    import scanpy as sc
    import numpy as np
    from model_utils import get_mito_genes

    adata = adata.copy()
    print(f"Input: {adata.shape[0]} cells, {adata.shape[1]} genes")

    if not skip_filter:
        # Calculate QC metrics
        adata.var['mt'] = get_mito_genes(adata)
        sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)

        # Filter cells
        n_before = adata.n_obs
        adata = adata[adata.obs['n_genes_by_counts'] >= min_genes].copy()
        adata = adata[adata.obs['n_genes_by_counts'] <= max_genes].copy()
        adata = adata[adata.obs['pct_counts_mt'] < max_mito_pct].copy()
        print(f"Filtered cells: {n_before} → {adata.n_obs}")

        # Filter genes
        n_genes_before = adata.n_vars
        sc.pp.filter_genes(adata, min_cells=min_cells)
        print(f"Filtered genes: {n_genes_before} → {adata.n_vars}")

    # Store raw counts in layer
    adata.layers["counts"] = adata.X.copy()

    # HVG selection
    if batch_key is not None and batch_key in adata.obs.columns:
        print(f"Selecting {n_top_genes} HVGs (batch-aware: {batch_key})")
        sc.pp.highly_variable_genes(
            adata,
            n_top_genes=n_top_genes,
            flavor="seurat_v3",
            batch_key=batch_key,
            layer="counts"
        )
    else:
        print(f"Selecting {n_top_genes} HVGs")
        # Need to normalize for non-seurat_v3
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        sc.pp.highly_variable_genes(adata, n_top_genes=n_top_genes)
        # Restore counts to X
        adata.X = adata.layers["counts"].copy()

    # Subset to HVGs
    n_hvg = adata.var['highly_variable'].sum()
    adata = adata[:, adata.var['highly_variable']].copy()
    print(f"Selected {n_hvg} highly variable genes")

    print(f"Output: {adata.shape[0]} cells, {adata.shape[1]} genes")

    return adata


def main():
    parser = argparse.ArgumentParser(
        description="Prepare AnnData for scvi-tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic preparation
    python prepare_data.py raw.h5ad prepared.h5ad

    # With batch-aware HVG selection
    python prepare_data.py raw.h5ad prepared.h5ad --batch-key sample

    # Custom parameters
    python prepare_data.py raw.h5ad prepared.h5ad --n-hvgs 3000 --max-mito 15

    # Skip filtering (data already QC'd)
    python prepare_data.py filtered.h5ad prepared.h5ad --no-filter
        """
    )
    parser.add_argument("input", help="Input h5ad file")
    parser.add_argument("output", help="Output h5ad file")
    parser.add_argument("--batch-key", help="Batch column for HVG selection")
    parser.add_argument("--n-hvgs", type=int, default=2000, help="Number of HVGs (default: 2000)")
    parser.add_argument("--min-genes", type=int, default=200, help="Min genes per cell (default: 200)")
    parser.add_argument("--max-genes", type=int, default=5000, help="Max genes per cell (default: 5000)")
    parser.add_argument("--max-mito", type=float, default=20.0, help="Max mito %% (default: 20)")
    parser.add_argument("--min-cells", type=int, default=3, help="Min cells per gene (default: 3)")
    parser.add_argument("--no-filter", action="store_true", help="Skip QC filtering")

    args = parser.parse_args()

    try:
        import scanpy as sc
    except ImportError:
        print("Error: scanpy required. Install with: pip install scanpy")
        sys.exit(1)

    # Load data
    print(f"Loading {args.input}...")
    adata = sc.read_h5ad(args.input)

    # Prepare
    adata = prepare_data(
        adata,
        batch_key=args.batch_key,
        n_top_genes=args.n_hvgs,
        min_genes=args.min_genes,
        max_genes=args.max_genes,
        max_mito_pct=args.max_mito,
        min_cells=args.min_cells,
        skip_filter=args.no_filter
    )

    # Save
    print(f"Saving to {args.output}...")
    adata.write_h5ad(args.output)
    print("Done!")


if __name__ == "__main__":
    main()
