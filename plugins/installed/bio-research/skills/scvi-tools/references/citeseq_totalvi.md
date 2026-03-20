# CITE-seq Analysis with totalVI

This reference covers multi-modal analysis of CITE-seq data (RNA + surface proteins) using totalVI.

## Overview

CITE-seq combines:
- scRNA-seq (transcriptome)
- Protein surface markers (antibody-derived tags, ADT)

totalVI jointly models both modalities to:
- Integrate across batches
- Denoise protein signal
- Learn joint latent representation
- Enable cross-modal imputation

## Prerequisites

```python
import scvi
import scanpy as sc
import mudata as md
import numpy as np
import pandas as pd

print(f"scvi-tools version: {scvi.__version__}")
```

## Step 1: Load CITE-seq Data

### From 10x Genomics (Cell Ranger)

```python
# 10x outputs separate gene expression and feature barcoding
adata_rna = sc.read_10x_h5("filtered_feature_bc_matrix.h5", gex_only=False)

# Separate RNA and protein
adata_protein = adata_rna[:, adata_rna.var['feature_types'] == 'Antibody Capture'].copy()
adata_rna = adata_rna[:, adata_rna.var['feature_types'] == 'Gene Expression'].copy()

print(f"RNA: {adata_rna.shape}")
print(f"Protein: {adata_protein.shape}")
```

### From MuData

```python
# If data is in MuData format
mdata = md.read_h5mu("cite_seq.h5mu")

adata_rna = mdata['rna'].copy()
adata_protein = mdata['protein'].copy()
```

### Combine into Single AnnData

```python
# totalVI expects protein data in obsm
adata = adata_rna.copy()

# Add protein expression to obsm
adata.obsm["protein_expression"] = adata_protein.X.toarray() if hasattr(adata_protein.X, 'toarray') else adata_protein.X

# Store protein names
adata.uns["protein_names"] = list(adata_protein.var_names)
```

## Step 2: Quality Control

### RNA QC

```python
# Standard RNA QC
# Handle both human (MT-) and mouse (mt-, Mt-) mitochondrial genes
    adata.var['mt'] = (
        adata.var_names.str.startswith('MT-') |
        adata.var_names.str.startswith('mt-') |
        adata.var_names.str.startswith('Mt-')
    )
sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)

# Filter cells
adata = adata[adata.obs['n_genes_by_counts'] > 200].copy()
adata = adata[adata.obs['pct_counts_mt'] < 20].copy()

# Filter genes
sc.pp.filter_genes(adata, min_cells=3)
```

### Protein QC

```python
# Protein QC
protein_counts = adata.obsm["protein_expression"]
print(f"Protein counts per cell: min={protein_counts.sum(1).min():.0f}, max={protein_counts.sum(1).max():.0f}")

# Check for isotype controls
# Isotype controls should have low counts
protein_names = adata.uns["protein_names"]
for i, name in enumerate(protein_names):
    if 'isotype' in name.lower() or 'control' in name.lower():
        print(f"{name}: mean={protein_counts[:, i].mean():.1f}")
```

## Step 3: Data Preparation

### Store Raw Counts

```python
# Store RNA counts
adata.layers["counts"] = adata.X.copy()

# Protein must be raw ADT counts (NOT CLR-normalized)
# WARNING: If importing from Seurat, ensure you use raw counts, not CLR-normalized data
# Seurat's NormalizeData(normalization.method = "CLR") transforms counts - use the original assay
```

### HVG Selection for RNA

```python
# Select HVGs for RNA
# Note: totalVI uses all proteins regardless of HVG

sc.pp.highly_variable_genes(
    adata,
    n_top_genes=4000,  # Use more for CITE-seq
    flavor="seurat_v3",
    batch_key="batch" if "batch" in adata.obs else None,
    layer="counts"
)

# Subset to HVGs
adata = adata[:, adata.var["highly_variable"]].copy()
```

## Step 4: Setup and Train totalVI

```python
# Setup AnnData for totalVI
scvi.model.TOTALVI.setup_anndata(
    adata,
    layer="counts",
    protein_expression_obsm_key="protein_expression",
    batch_key="batch"  # Optional
)

# Create model
model = scvi.model.TOTALVI(
    adata,
    n_latent=20,
    latent_distribution="normal"  # or "ln" for log-normal
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

## Step 5: Get Latent Representation

```python
# Joint latent space
adata.obsm["X_totalVI"] = model.get_latent_representation()

# Clustering and visualization
sc.pp.neighbors(adata, use_rep="X_totalVI")
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=1.0)

sc.pl.umap(adata, color=['leiden', 'batch'])
```

## Step 6: Denoised Protein Expression

```python
# Get denoised protein values
# This removes background noise from protein measurements

_, protein_denoised = model.get_normalized_expression(
    return_mean=True,
    transform_batch="batch1"  # Optional: normalize to specific batch
)

# Add to adata
adata.obsm["protein_denoised"] = protein_denoised

# Visualize denoised proteins
protein_names = adata.uns["protein_names"]
for i, protein in enumerate(protein_names[:5]):
    adata.obs[f"denoised_{protein}"] = protein_denoised[:, i]

sc.pl.umap(adata, color=[f"denoised_{p}" for p in protein_names[:5]])
```

## Step 7: Normalized RNA Expression

```python
# Get normalized RNA expression
rna_normalized, _ = model.get_normalized_expression(
    return_mean=True
)

# Store
adata.layers["totalVI_normalized"] = rna_normalized
```

## Step 8: Differential Expression

### RNA Differential Expression

```python
# DE between clusters
de_rna = model.differential_expression(
    groupby="leiden",
    group1="0",
    group2="1"
)

# Filter significant genes
de_sig = de_rna[
    (de_rna['is_de_fdr_0.05']) &
    (abs(de_rna['lfc_mean']) > 1)
]

print(f"Significant DE genes: {len(de_sig)}")
```

### Protein Differential Expression

```python
# Protein DE
de_protein = model.differential_expression(
    groupby="leiden",
    group1="0",
    group2="1",
    mode="protein"
)

print(de_protein.head(20))
```

## Step 9: Visualization

### Protein Expression on UMAP

```python
# Denoised protein on UMAP
import matplotlib.pyplot as plt

proteins_to_plot = ["CD3", "CD4", "CD8", "CD19", "CD14"]

fig, axes = plt.subplots(1, len(proteins_to_plot), figsize=(4*len(proteins_to_plot), 4))
for ax, protein in zip(axes, proteins_to_plot):
    idx = adata.uns["protein_names"].index(protein)
    sc.pl.umap(
        adata,
        color=adata.obsm["protein_denoised"][:, idx],
        ax=ax,
        title=protein,
        show=False
    )
plt.tight_layout()
```

### Joint Heatmap

```python
# Heatmap of top genes and proteins per cluster
sc.pl.dotplot(
    adata,
    var_names=de_sig.index[:20].tolist(),
    groupby="leiden",
    layer="totalVI_normalized"
)
```

## Step 10: Cell Type Annotation

```python
# Use both RNA and protein markers for annotation

# RNA markers
rna_markers = {
    'T cells': ['CD3D', 'CD3E'],
    'CD4 T': ['CD4'],
    'CD8 T': ['CD8A', 'CD8B'],
    'B cells': ['CD19', 'MS4A1'],
    'Monocytes': ['CD14', 'LYZ']
}

# Check denoised protein expression
for i, protein in enumerate(adata.uns["protein_names"]):
    if any(m in protein for m in ['CD3', 'CD4', 'CD8', 'CD19', 'CD14']):
        print(f"{protein}: cluster means")
        for cluster in adata.obs['leiden'].unique():
            mask = adata.obs['leiden'] == cluster
            mean_expr = adata.obsm["protein_denoised"][mask, i].mean()
            print(f"  Cluster {cluster}: {mean_expr:.2f}")
```

## Complete Pipeline

```python
def analyze_citeseq(
    adata_rna,
    adata_protein,
    batch_key=None,
    n_top_genes=4000,
    n_latent=20
):
    """
    Complete CITE-seq analysis with totalVI.
    
    Parameters
    ----------
    adata_rna : AnnData
        RNA expression (raw counts)
    adata_protein : AnnData
        Protein expression (raw counts)
    batch_key : str, optional
        Batch column in obs
    n_top_genes : int
        Number of HVGs
    n_latent : int
        Latent dimensions
        
    Returns
    -------
    Tuple of (processed AnnData, trained model)
    """
    import scvi
    import scanpy as sc
    
    # Ensure same cells
    common_cells = adata_rna.obs_names.intersection(adata_protein.obs_names)
    adata = adata_rna[common_cells].copy()
    adata_protein = adata_protein[common_cells].copy()
    
    # Add protein to obsm
    adata.obsm["protein_expression"] = adata_protein.X.toarray() if hasattr(adata_protein.X, 'toarray') else adata_protein.X
    adata.uns["protein_names"] = list(adata_protein.var_names)
    
    # RNA QC
    # Handle both human (MT-) and mouse (mt-, Mt-) mitochondrial genes
    adata.var['mt'] = (
        adata.var_names.str.startswith('MT-') |
        adata.var_names.str.startswith('mt-') |
        adata.var_names.str.startswith('Mt-')
    )
    sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)
    adata = adata[adata.obs['pct_counts_mt'] < 20].copy()
    sc.pp.filter_genes(adata, min_cells=3)
    
    # Store counts
    adata.layers["counts"] = adata.X.copy()
    
    # HVG selection
    sc.pp.highly_variable_genes(
        adata,
        n_top_genes=n_top_genes,
        flavor="seurat_v3",
        batch_key=batch_key,
        layer="counts"
    )
    adata = adata[:, adata.var["highly_variable"]].copy()
    
    # Setup totalVI
    scvi.model.TOTALVI.setup_anndata(
        adata,
        layer="counts",
        protein_expression_obsm_key="protein_expression",
        batch_key=batch_key
    )
    
    # Train
    model = scvi.model.TOTALVI(adata, n_latent=n_latent)
    model.train(max_epochs=200, early_stopping=True)
    
    # Get representations
    adata.obsm["X_totalVI"] = model.get_latent_representation()
    rna_norm, protein_denoised = model.get_normalized_expression(return_mean=True)
    adata.layers["totalVI_normalized"] = rna_norm
    adata.obsm["protein_denoised"] = protein_denoised
    
    # Clustering
    sc.pp.neighbors(adata, use_rep="X_totalVI")
    sc.tl.umap(adata)
    sc.tl.leiden(adata)
    
    return adata, model

# Usage
adata, model = analyze_citeseq(
    adata_rna,
    adata_protein,
    batch_key="batch"
)

# Visualize
sc.pl.umap(adata, color=['leiden', 'batch'])
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Protein signal noisy | Background not removed | Use get_normalized_expression with denoising |
| Batch effects persist | Need batch_key | Ensure batch_key is specified |
| Memory error | Too many genes | Reduce n_top_genes |
| Poor protein clustering | Few proteins | Normal - totalVI uses RNA for structure |

## Key References

- Gayoso et al. (2021) "Joint probabilistic modeling of single-cell multi-omic data with totalVI"
