#!/usr/bin/env python3
"""
Core utility functions for single-cell RNA-seq quality control.

This module provides building blocks for metrics calculation and filtering
while following scverse best practices from:
https://www.sc-best-practices.org/preprocessing_visualization/quality_control.html
"""

import anndata as ad
import scanpy as sc
import numpy as np
from scipy.stats import median_abs_deviation


def calculate_qc_metrics(adata, mt_pattern='mt-,MT-', ribo_pattern='Rpl,Rps,RPL,RPS',
                        hb_pattern='^Hb[^(p)]|^HB[^(P)]', inplace=True):
    """
    Calculate QC metrics for single-cell RNA-seq data.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix
    mt_pattern : str
        Comma-separated mitochondrial gene prefixes (default: 'mt-,MT-')
    ribo_pattern : str
        Comma-separated ribosomal gene prefixes (default: 'Rpl,Rps,RPL,RPS')
    hb_pattern : str
        Regex pattern for hemoglobin genes (default: '^Hb[^(p)]|^HB[^(P)]')
    inplace : bool
        Modify adata in place (default: True)

    Returns
    -------
    AnnData or None
        If inplace=False, returns modified AnnData. Otherwise modifies in place.
    """
    if not inplace:
        adata = adata.copy()

    # Identify gene categories
    mt_prefixes = tuple(mt_pattern.split(','))
    adata.var['mt'] = adata.var_names.str.startswith(mt_prefixes)

    ribo_prefixes = tuple(ribo_pattern.split(','))
    adata.var['ribo'] = adata.var_names.str.startswith(ribo_prefixes)

    adata.var['hb'] = adata.var_names.str.match(hb_pattern)

    # Calculate QC metrics
    sc.pp.calculate_qc_metrics(
        adata,
        qc_vars=['mt', 'ribo', 'hb'],
        percent_top=None,
        log1p=False,
        inplace=True
    )

    if not inplace:
        return adata


def detect_outliers_mad(adata, metric, n_mads, verbose=True):
    """
    Detect outliers using Median Absolute Deviation (MAD).

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix with QC metrics
    metric : str
        Column name in adata.obs to use for outlier detection
    n_mads : float
        Number of MADs to use as threshold
    verbose : bool
        Print outlier statistics (default: True)

    Returns
    -------
    np.ndarray
        Boolean mask where True indicates outliers
    """
    metric_values = adata.obs[metric]
    median = np.median(metric_values)
    mad = median_abs_deviation(metric_values)

    # Calculate bounds
    lower = median - n_mads * mad
    upper = median + n_mads * mad

    # Identify outliers
    outlier_mask = (metric_values < lower) | (metric_values > upper)

    if verbose:
        print(f"  {metric}:")
        print(f"    Median: {median:.2f}, MAD: {mad:.2f}")
        print(f"    Bounds: [{lower:.2f}, {upper:.2f}] ({n_mads} MADs)")
        print(f"    Outliers: {outlier_mask.sum()} cells ({outlier_mask.sum()/len(metric_values)*100:.2f}%)")

    return outlier_mask


def apply_hard_threshold(adata, metric, threshold, operator='>', verbose=True):
    """
    Apply a hard threshold filter.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix
    metric : str
        Column name in adata.obs to filter on
    threshold : float
        Threshold value
    operator : str
        Comparison operator: '>', '<', '>=', '<=' (default: '>')
    verbose : bool
        Print filtering statistics (default: True)

    Returns
    -------
    np.ndarray
        Boolean mask where True indicates cells to filter out
    """
    metric_values = adata.obs[metric]

    if operator == '>':
        mask = metric_values > threshold
    elif operator == '<':
        mask = metric_values < threshold
    elif operator == '>=':
        mask = metric_values >= threshold
    elif operator == '<=':
        mask = metric_values <= threshold
    else:
        raise ValueError(f"Invalid operator: {operator}. Use '>', '<', '>=', or '<='")

    if verbose:
        print(f"  {metric} {operator} {threshold}:")
        print(f"    Cells filtered: {mask.sum()} ({mask.sum()/len(metric_values)*100:.2f}%)")

    return mask


def filter_cells(adata, mask, inplace=False):
    """
    Filter cells based on a boolean mask.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix
    mask : np.ndarray or pd.Series
        Boolean mask where True indicates cells to KEEP
    inplace : bool
        Modify adata in place (default: False)

    Returns
    -------
    AnnData
        Filtered AnnData object
    """
    if inplace:
        # This is actually a bit tricky - AnnData doesn't support true inplace filtering
        # Return filtered copy which caller should reassign
        return adata[mask].copy()
    else:
        return adata[mask].copy()


def filter_genes(adata, min_cells=20, min_counts=None, inplace=True):
    """
    Filter genes based on detection thresholds.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix
    min_cells : int
        Minimum number of cells a gene must be detected in (default: 20)
    min_counts : int, optional
        Minimum total counts across all cells
    inplace : bool
        Modify adata in place (default: True)

    Returns
    -------
    AnnData or None
        If inplace=False, returns filtered AnnData
    """
    if not inplace:
        adata = adata.copy()

    if min_cells is not None:
        sc.pp.filter_genes(adata, min_cells=min_cells)

    if min_counts is not None:
        sc.pp.filter_genes(adata, min_counts=min_counts)

    if not inplace:
        return adata


def print_qc_summary(adata, label=''):
    """
    Print summary statistics for QC metrics.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix with QC metrics
    label : str
        Label to prepend to output (e.g., 'Before filtering', 'After filtering')
    """
    if label:
        print(f"\n{label}:")
    print(f"  Cells: {adata.n_obs}")
    print(f"  Genes: {adata.n_vars}")

    if 'total_counts' in adata.obs:
        print(f"  Mean counts per cell: {adata.obs['total_counts'].mean():.0f}")
        print(f"  Median counts per cell: {adata.obs['total_counts'].median():.0f}")

    if 'n_genes_by_counts' in adata.obs:
        print(f"  Mean genes per cell: {adata.obs['n_genes_by_counts'].mean():.0f}")
        print(f"  Median genes per cell: {adata.obs['n_genes_by_counts'].median():.0f}")

    if 'pct_counts_mt' in adata.obs:
        print(f"  Mean mitochondrial %: {adata.obs['pct_counts_mt'].mean():.2f}%")

    if 'pct_counts_ribo' in adata.obs:
        print(f"  Mean ribosomal %: {adata.obs['pct_counts_ribo'].mean():.2f}%")
