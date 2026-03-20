# scATAC-seq Analysis with PeakVI

This reference covers single-cell ATAC-seq analysis using PeakVI for dimensionality reduction, batch correction, and differential accessibility.

## Overview

PeakVI is a deep generative model for scATAC-seq data that:
- Models binary accessibility (peak open/closed)
- Handles batch effects
- Provides latent representation for clustering
- Enables differential accessibility analysis

## Prerequisites

```python
import scvi
import scanpy as sc
import numpy as np
import anndata as ad

print(f"scvi-tools version: {scvi.__version__}")
```

## Step 1: Load and Prepare ATAC Data

### From 10x Genomics (Cell Ranger ATAC)

```python
# Peak-cell matrix from fragments
# Usually in filtered_peak_bc_matrix format

adata = sc.read_10x_h5("filtered_peak_bc_matrix.h5")

# Or from mtx format
adata = sc.read_10x_mtx("filtered_peak_bc_matrix/")

# Check structure
print(f"Cells: {adata.n_obs}, Peaks: {adata.n_vars}")
print(f"Sparsity: {1 - adata.X.nnz / (adata.n_obs * adata.n_vars):.2%}")
```

### From ArchR/Signac

```python
# Export from ArchR (in R)
# saveArchRProject(proj, outputDirectory="atac_export", load=FALSE)
# Then read the exported files in Python

# From Signac:
# Export peak matrix and metadata
```

## Step 2: Quality Control

```python
# Calculate QC metrics
sc.pp.calculate_qc_metrics(adata, inplace=True)

# Key metrics for ATAC:
# - n_genes_by_counts: peaks per cell (should rename)
# - total_counts: fragments per cell
adata.obs['n_peaks'] = adata.obs['n_genes_by_counts']
adata.obs['total_fragments'] = adata.obs['total_counts']

# Filter cells
adata = adata[adata.obs['n_peaks'] > 500].copy()
adata = adata[adata.obs['n_peaks'] < 50000].copy()  # Remove potential doublets

# Filter peaks (accessible in at least n cells)
sc.pp.filter_genes(adata, min_cells=10)

print(f"After QC: {adata.shape}")
```

### Binarize Data

```python
# PeakVI works with binary accessibility
# Binarize if not already binary
adata.X = (adata.X > 0).astype(np.float32)

# Verify
print(f"Unique values: {np.unique(adata.X.data)}")
```

## Step 3: Feature Selection

Unlike RNA-seq, peak selection for ATAC is less established. Options:

### Option A: Most Accessible Peaks

```python
# Select top peaks by accessibility frequency
peak_accessibility = np.array(adata.X.sum(axis=0)).flatten()
top_peaks = np.argsort(peak_accessibility)[-50000:]  # Top 50k peaks

adata = adata[:, top_peaks].copy()
```

### Option B: Variable Peaks

```python
# Select peaks with high variance
# (Most informative for clustering)
from sklearn.feature_selection import VarianceThreshold

selector = VarianceThreshold(threshold=0.05)
selector.fit(adata.X)
adata = adata[:, selector.get_support()].copy()
```

### Option C: Peaks Near Genes

```python
# Keep peaks within promoter regions or gene bodies
# Requires peak annotation
# gene_peaks = peaks with gene annotation
# adata = adata[:, adata.var['near_gene']].copy()
```

## Step 4: Add Batch Information

```python
# Add batch annotation if multiple samples
adata.obs['batch'] = adata.obs['sample_id']  # Or appropriate column

print(adata.obs['batch'].value_counts())
```

## Step 5: Setup and Train PeakVI

```python
# Setup AnnData
scvi.model.PEAKVI.setup_anndata(
    adata,
    batch_key="batch"  # Optional, omit for single batch
)

# Create model
model = scvi.model.PEAKVI(
    adata,
    n_latent=20,      # Latent dimensions
    n_layers_encoder=2,
    n_layers_decoder=2
)

# Train
model.train(
    max_epochs=200,
    early_stopping=True,
    batch_size=128
)

# Check training
model.history['elbo_train'].plot()
```

## Step 6: Get Latent Representation

```python
# Latent space for downstream analysis
adata.obsm["X_PeakVI"] = model.get_latent_representation()

# Clustering and visualization
sc.pp.neighbors(adata, use_rep="X_PeakVI", n_neighbors=15)
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=0.5)

# Visualize
sc.pl.umap(adata, color=['leiden', 'batch'], ncols=2)
```

## Step 7: Differential Accessibility

```python
# Differential accessibility between clusters
da_results = model.differential_accessibility(
    groupby='leiden',
    group1='0',
    group2='1'
)

# Filter significant peaks
da_sig = da_results[
    (da_results['is_da_fdr_0.05']) &
    (abs(da_results['lfc_mean']) > 1)
]

print(f"Significant DA peaks: {len(da_sig)}")
print(da_sig.head())
```

### DA Between Conditions

```python
# Compare conditions within cell type
adata_subset = adata[adata.obs['cell_type'] == 'CD4 T cells'].copy()

da_condition = model.differential_accessibility(
    groupby='condition',
    group1='treated',
    group2='control'
)
```

## Step 8: Peak Annotation

```python
# Annotate peaks with nearest genes
# Using pybedtools or similar

# Example peak name format: chr1:1000-2000
# Parse into bed format for annotation

import pandas as pd

def parse_peak_names(peak_names):
    """Parse peak names into bed format."""
    records = []
    for peak in peak_names:
        chrom, coords = peak.split(':')
        start, end = coords.split('-')
        records.append({
            'chrom': chrom,
            'start': int(start),
            'end': int(end),
            'peak': peak
        })
    return pd.DataFrame(records)

peak_bed = parse_peak_names(adata.var_names)
```

## Step 9: Motif Analysis

```python
# Export significant peaks for motif analysis
# Use HOMER, MEME, or chromVAR

# Export peak sequences
sig_peaks = da_sig.index.tolist()
peak_bed_sig = peak_bed[peak_bed['peak'].isin(sig_peaks)]
peak_bed_sig.to_csv("significant_peaks.bed", sep='\t', index=False, header=False)

# Then run HOMER:
# findMotifsGenome.pl significant_peaks.bed hg38 motif_output/ -size 200
```

## Step 10: Gene Activity Scores

```python
# Compute gene activity from peak accessibility
# (Requires peak-gene annotations)

def compute_gene_activity(adata, peak_gene_map):
    """
    Compute gene activity scores from peak accessibility.
    
    Parameters
    ----------
    adata : AnnData
        ATAC data with peaks
    peak_gene_map : dict
        Mapping of peaks to genes
        
    Returns
    -------
    AnnData with gene activity scores
    """
    from scipy.sparse import csr_matrix
    
    genes = list(set(peak_gene_map.values()))
    gene_matrix = np.zeros((adata.n_obs, len(genes)))
    
    for i, gene in enumerate(genes):
        gene_peaks = [p for p, g in peak_gene_map.items() if g == gene]
        if gene_peaks:
            peak_idx = [list(adata.var_names).index(p) for p in gene_peaks if p in adata.var_names]
            if peak_idx:
                gene_matrix[:, i] = np.array(adata.X[:, peak_idx].sum(axis=1)).flatten()
    
    adata_gene = ad.AnnData(
        X=csr_matrix(gene_matrix),
        obs=adata.obs.copy(),
        var=pd.DataFrame(index=genes)
    )
    
    return adata_gene
```

## Complete Pipeline

```python
def analyze_scatac(
    adata,
    batch_key=None,
    n_top_peaks=50000,
    n_latent=20,
    resolution=0.5
):
    """
    Complete scATAC-seq analysis with PeakVI.
    
    Parameters
    ----------
    adata : AnnData
        Raw peak-cell matrix
    batch_key : str, optional
        Batch annotation column
    n_top_peaks : int
        Number of top peaks to use
    n_latent : int
        Latent dimensions
    resolution : float
        Leiden clustering resolution
        
    Returns
    -------
    Tuple of (processed AnnData, trained model)
    """
    import scvi
    import scanpy as sc
    import numpy as np
    
    adata = adata.copy()
    
    # QC
    sc.pp.calculate_qc_metrics(adata, inplace=True)
    adata = adata[adata.obs['n_genes_by_counts'] > 500].copy()
    sc.pp.filter_genes(adata, min_cells=10)
    
    # Binarize
    adata.X = (adata.X > 0).astype(np.float32)
    
    # Select top peaks
    if adata.n_vars > n_top_peaks:
        peak_accessibility = np.array(adata.X.sum(axis=0)).flatten()
        top_peaks = np.argsort(peak_accessibility)[-n_top_peaks:]
        adata = adata[:, top_peaks].copy()
    
    # Setup PeakVI
    scvi.model.PEAKVI.setup_anndata(adata, batch_key=batch_key)
    
    # Train
    model = scvi.model.PEAKVI(adata, n_latent=n_latent)
    model.train(max_epochs=200, early_stopping=True)
    
    # Latent representation
    adata.obsm["X_PeakVI"] = model.get_latent_representation()
    
    # Clustering
    sc.pp.neighbors(adata, use_rep="X_PeakVI")
    sc.tl.umap(adata)
    sc.tl.leiden(adata, resolution=resolution)
    
    return adata, model

# Usage
adata, model = analyze_scatac(
    adata,
    batch_key="sample",
    n_top_peaks=50000
)

# Visualize
sc.pl.umap(adata, color=['leiden', 'sample'])

# Differential accessibility
da_results = model.differential_accessibility(
    groupby='leiden',
    group1='0',
    group2='1'
)
```

## Integration with scRNA-seq

For multiome data or separate RNA/ATAC from same cells:

```python
# See MultiVI for joint RNA+ATAC analysis
# Or use WNN (weighted nearest neighbors) approach

# Transfer labels from RNA to ATAC using shared latent space
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Training slow | Too many peaks | Subset to top 50k peaks |
| Poor clustering | Too few informative peaks | Use variable peaks |
| Batch dominates | Strong technical effects | Ensure batch_key is set |
| Memory error | Large peak matrix | Use sparse format, reduce peaks |

## Key References

- Ashuach et al. (2022) "PeakVI: A deep generative model for single-cell chromatin accessibility analysis"
