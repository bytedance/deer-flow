#!/usr/bin/env python3
"""
Visualization functions for single-cell RNA-seq quality control.

This module provides plotting utilities for QC metrics and filtering thresholds.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import median_abs_deviation


def plot_qc_distributions(adata, output_path, title='Quality Control Metrics'):
    """
    Create comprehensive QC distribution plots.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix with QC metrics
    output_path : str
        Path to save the figure
    title : str
        Figure title (default: 'Quality Control Metrics')
    """
    fig, axes = plt.subplots(3, 3, figsize=(15, 12))
    fig.suptitle(title, fontsize=16, y=0.995)

    # Row 1: Histograms
    axes[0, 0].hist(adata.obs['total_counts'], bins=100, color='steelblue', edgecolor='black')
    axes[0, 0].set_xlabel('Total counts per cell')
    axes[0, 0].set_ylabel('Number of cells')
    axes[0, 0].set_title('Distribution of Total Counts')
    axes[0, 0].axvline(adata.obs['total_counts'].median(), color='red', linestyle='--', label='Median')
    axes[0, 0].legend()

    axes[0, 1].hist(adata.obs['n_genes_by_counts'], bins=100, color='forestgreen', edgecolor='black')
    axes[0, 1].set_xlabel('Genes per cell')
    axes[0, 1].set_ylabel('Number of cells')
    axes[0, 1].set_title('Distribution of Detected Genes')
    axes[0, 1].axvline(adata.obs['n_genes_by_counts'].median(), color='red', linestyle='--', label='Median')
    axes[0, 1].legend()

    axes[0, 2].hist(adata.obs['pct_counts_mt'], bins=100, color='coral', edgecolor='black')
    axes[0, 2].set_xlabel('Mitochondrial %')
    axes[0, 2].set_ylabel('Number of cells')
    axes[0, 2].set_title('Distribution of Mitochondrial Content')
    axes[0, 2].axvline(adata.obs['pct_counts_mt'].median(), color='red', linestyle='--', label='Median')
    axes[0, 2].legend()

    # Row 2: Violin plots
    axes[1, 0].violinplot([adata.obs['total_counts']], positions=[0], showmeans=True, showmedians=True)
    axes[1, 0].set_ylabel('Total counts')
    axes[1, 0].set_title('Total Counts per Cell')
    axes[1, 0].set_xticks([])

    axes[1, 1].violinplot([adata.obs['n_genes_by_counts']], positions=[0], showmeans=True, showmedians=True)
    axes[1, 1].set_ylabel('Genes detected')
    axes[1, 1].set_title('Genes per Cell')
    axes[1, 1].set_xticks([])

    axes[1, 2].violinplot([adata.obs['pct_counts_mt']], positions=[0], showmeans=True, showmedians=True)
    axes[1, 2].set_ylabel('Mitochondrial %')
    axes[1, 2].set_title('Mitochondrial Content')
    axes[1, 2].set_xticks([])

    # Row 3: Scatter plots
    scatter1 = axes[2, 0].scatter(
        adata.obs['total_counts'],
        adata.obs['n_genes_by_counts'],
        c=adata.obs['pct_counts_mt'],
        cmap='viridis',
        alpha=0.5,
        s=10
    )
    axes[2, 0].set_xlabel('Total counts')
    axes[2, 0].set_ylabel('Genes detected')
    axes[2, 0].set_title('Counts vs Genes (colored by MT%)')
    plt.colorbar(scatter1, ax=axes[2, 0], label='MT %')

    axes[2, 1].scatter(
        adata.obs['total_counts'],
        adata.obs['pct_counts_mt'],
        alpha=0.5,
        s=10,
        color='coral'
    )
    axes[2, 1].set_xlabel('Total counts')
    axes[2, 1].set_ylabel('Mitochondrial %')
    axes[2, 1].set_title('Total Counts vs Mitochondrial %')

    axes[2, 2].scatter(
        adata.obs['n_genes_by_counts'],
        adata.obs['pct_counts_mt'],
        alpha=0.5,
        s=10,
        color='forestgreen'
    )
    axes[2, 2].set_xlabel('Genes detected')
    axes[2, 2].set_ylabel('Mitochondrial %')
    axes[2, 2].set_title('Genes vs Mitochondrial %')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_filtering_thresholds(adata, outlier_masks, thresholds, output_path):
    """
    Visualize filtering thresholds overlaid on distributions.

    Parameters
    ----------
    adata : AnnData
        Annotated data matrix with QC metrics
    outlier_masks : dict
        Dictionary mapping metric names to boolean outlier masks
        Example: {'total_counts': mask1, 'n_genes_by_counts': mask2, 'pct_counts_mt': mask3}
    thresholds : dict
        Dictionary with threshold information for each metric
        Example: {'total_counts': {'n_mads': 5}, 'pct_counts_mt': {'n_mads': 3, 'hard': 8}}
    output_path : str
        Path to save the figure
    """
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    fig.suptitle('MAD-Based Filtering Thresholds', fontsize=16)

    # Helper function to plot with thresholds
    def plot_with_threshold(ax, metric, outlier_mask, n_mads, hard_threshold=None):
        data = adata.obs[metric]
        median = np.median(data)
        mad = median_abs_deviation(data)
        lower = median - n_mads * mad
        upper = median + n_mads * mad

        ax.hist(data[~outlier_mask], bins=100, alpha=0.7, label='Pass QC', color='steelblue')
        ax.hist(data[outlier_mask], bins=100, alpha=0.7, label='Fail QC', color='coral')
        ax.axvline(lower, color='red', linestyle='--', linewidth=2, label=f'Thresholds ({n_mads} MADs)')
        ax.axvline(upper, color='red', linestyle='--', linewidth=2)

        if hard_threshold is not None:
            ax.axvline(hard_threshold, color='darkred', linestyle=':', linewidth=2,
                      label=f'Hard threshold ({hard_threshold})')

        ax.set_xlabel(metric.replace('_', ' ').title())
        ax.set_ylabel('Number of cells')
        ax.legend()

    # Plot each metric
    metrics = [
        ('total_counts', 'Total Counts'),
        ('n_genes_by_counts', 'Genes Detected'),
        ('pct_counts_mt', 'Mitochondrial %')
    ]

    for idx, (metric, label) in enumerate(metrics):
        if metric in outlier_masks and metric in thresholds:
            hard = thresholds[metric].get('hard', None)
            plot_with_threshold(axes[idx], metric, outlier_masks[metric],
                              thresholds[metric]['n_mads'], hard)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_qc_after_filtering(adata, output_path):
    """
    Create QC plots for filtered data (simplified version without outlier overlay).

    Parameters
    ----------
    adata : AnnData
        Filtered annotated data matrix with QC metrics
    output_path : str
        Path to save the figure
    """
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    fig.suptitle('Quality Control Metrics - After Filtering', fontsize=16, y=0.995)

    # Row 1: Histograms
    axes[0, 0].hist(adata.obs['total_counts'], bins=100, color='steelblue', edgecolor='black')
    axes[0, 0].set_xlabel('Total counts per cell')
    axes[0, 0].set_ylabel('Number of cells')
    axes[0, 0].set_title('Distribution of Total Counts')

    axes[0, 1].hist(adata.obs['n_genes_by_counts'], bins=100, color='forestgreen', edgecolor='black')
    axes[0, 1].set_xlabel('Genes per cell')
    axes[0, 1].set_ylabel('Number of cells')
    axes[0, 1].set_title('Distribution of Detected Genes')

    axes[0, 2].hist(adata.obs['pct_counts_mt'], bins=100, color='coral', edgecolor='black')
    axes[0, 2].set_xlabel('Mitochondrial %')
    axes[0, 2].set_ylabel('Number of cells')
    axes[0, 2].set_title('Distribution of Mitochondrial Content')

    # Row 2: Scatter plots
    scatter1 = axes[1, 0].scatter(
        adata.obs['total_counts'],
        adata.obs['n_genes_by_counts'],
        c=adata.obs['pct_counts_mt'],
        cmap='viridis',
        alpha=0.5,
        s=10
    )
    axes[1, 0].set_xlabel('Total counts')
    axes[1, 0].set_ylabel('Genes detected')
    axes[1, 0].set_title('Counts vs Genes (colored by MT%)')
    plt.colorbar(scatter1, ax=axes[1, 0], label='MT %')

    axes[1, 1].scatter(
        adata.obs['total_counts'],
        adata.obs['pct_counts_mt'],
        alpha=0.5,
        s=10,
        color='coral'
    )
    axes[1, 1].set_xlabel('Total counts')
    axes[1, 1].set_ylabel('Mitochondrial %')
    axes[1, 1].set_title('Total Counts vs Mitochondrial %')

    axes[1, 2].scatter(
        adata.obs['n_genes_by_counts'],
        adata.obs['pct_counts_mt'],
        alpha=0.5,
        s=10,
        color='forestgreen'
    )
    axes[1, 2].set_xlabel('Genes detected')
    axes[1, 2].set_ylabel('Mitochondrial %')
    axes[1, 2].set_title('Genes vs Mitochondrial %')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
