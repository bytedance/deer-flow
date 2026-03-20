# Data Preparation for scvi-tools

This reference covers how to properly prepare AnnData objects for use with scvi-tools models.

## Overview

Proper data preparation is critical for scvi-tools. Key requirements:
1. **Raw counts** (not normalized)
2. **Highly variable gene selection**
3. **Proper setup_anndata() call**

## Step 1: Load and Inspect Data

```python
import scanpy as sc
import scvi
import numpy as np

# Load data
adata = sc.read_h5ad("data.h5ad")

# Check what's in adata.X
print(f"Shape: {adata.shape}")
print(f"X dtype: {adata.X.dtype}")
print(f"X contains integers: {np.allclose(adata.X.data, adata.X.data.astype(int))}")
print(f"X min: {adata.X.min()}, max: {adata.X.max()}")
```

### Verify Raw Counts

```python
# scvi-tools needs INTEGER counts
# If X appears normalized, check for raw counts

if hasattr(adata, 'raw') and adata.raw is not None:
    print("Found adata.raw")
    # Use raw counts
    adata = adata.raw.to_adata()
    
# Or check layers
if 'counts' in adata.layers:
    print("Found counts layer")
    # Will specify layer in setup_anndata
```

## Step 2: Basic Filtering

```python
# Filter cells (standard QC)
sc.pp.filter_cells(adata, min_genes=200)
sc.pp.filter_cells(adata, max_genes=5000)

# Calculate mito percent if not present
# Handle both human (MT-) and mouse (mt-, Mt-) mitochondrial genes
adata.var['mt'] = (
    adata.var_names.str.startswith('MT-') |
    adata.var_names.str.startswith('mt-') |
    adata.var_names.str.startswith('Mt-')
)
sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)
adata = adata[adata.obs['pct_counts_mt'] < 20].copy()

# Filter genes
sc.pp.filter_genes(adata, min_cells=3)

print(f"After filtering: {adata.shape}")
```

## Step 3: Store Raw Counts

**Critical**: Always preserve raw counts before any normalization.

```python
# Store raw counts in a layer
adata.layers["counts"] = adata.X.copy()

# Now you can normalize for other purposes (HVG selection)
# But scvi will use the counts layer
```

## Step 4: Highly Variable Gene Selection

scvi-tools works best with 1,500-5,000 HVGs.

### For Single-Batch Data

```python
# Normalize for HVG selection only
adata_hvg = adata.copy()
sc.pp.normalize_total(adata_hvg, target_sum=1e4)
sc.pp.log1p(adata_hvg)

# Select HVGs
sc.pp.highly_variable_genes(
    adata_hvg,
    n_top_genes=2000,
    flavor="seurat"  # or "cell_ranger"
)

# Transfer HVG annotation
adata.var['highly_variable'] = adata_hvg.var['highly_variable']
```

### For Multi-Batch Data (Recommended)

```python
# Use seurat_v3 flavor with batch_key
# This selects genes variable across batches
sc.pp.highly_variable_genes(
    adata,
    n_top_genes=2000,
    flavor="seurat_v3",
    batch_key="batch",  # Your batch column
    layer="counts"      # Use raw counts
)
```

### Subset to HVGs

```python
# Subset to highly variable genes
adata = adata[:, adata.var['highly_variable']].copy()
print(f"After HVG selection: {adata.shape}")
```

## Step 5: Setup AnnData

The `setup_anndata()` function registers data for the model.

### Basic Setup

```python
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts"  # Specify layer with raw counts
)
```

### With Batch Information

```python
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch"  # Column in adata.obs
)
```

### With Cell Type Labels (for scANVI)

```python
scvi.model.SCANVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    labels_key="cell_type"  # Column with cell type labels
)
```

### With Continuous Covariates

```python
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    continuous_covariate_keys=["percent_mito", "n_genes"]
)
```

### With Categorical Covariates

```python
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    categorical_covariate_keys=["donor", "technology"]
)
```

## Multi-Modal Data Setup

### CITE-seq (for totalVI)

```python
# Protein data in adata.obsm
# RNA in adata.X, protein in separate matrix

# Add protein data
adata.obsm["protein_expression"] = protein_counts  # numpy array

# Setup for totalVI
scvi.model.TOTALVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    protein_expression_obsm_key="protein_expression"
)
```

### Multiome RNA+ATAC (for MultiVI)

```python
# RNA and ATAC in separate AnnData objects or MuData

import mudata as md

# If using MuData
mdata = md.read("multiome.h5mu")

scvi.model.MULTIVI.setup_mudata(
    mdata,
    rna_layer="counts",
    protein_layer=None,
    batch_key="batch",
    modalities={"rna": "rna", "accessibility": "atac"}
)
```

## Complete Preparation Pipeline

For a complete preparation function, use `prepare_adata()` from `scripts/model_utils.py`:

```python
from model_utils import prepare_adata

# Prepare data with QC, HVG selection, and layer setup
adata = prepare_adata(
    adata,
    batch_key="batch",
    n_top_genes=2000,
    min_genes=200,
    max_mito_pct=20
)

# Then setup for your model
import scvi
scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
```

This function handles:
- Mitochondrial QC filtering
- Cell and gene filtering
- Storing counts in layer
- HVG selection (batch-aware if batch_key provided)
- Subsetting to HVGs

## Checking Setup

```python
# View registered data
print(adata.uns['_scvi_manager_uuid'])
print(adata.uns['_scvi_adata_minify_type'])

# For scVI
scvi.model.SCVI.view_anndata_setup(adata)
```

## Common Issues and Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| "X should contain integers" | Normalized data in X | Use layer="counts" |
| "batch_key not found" | Wrong column name | Check adata.obs.columns |
| Sparse matrix errors | Incompatible format | Convert: adata.X = adata.X.toarray() |
| Memory error | Too many genes | Subset to HVGs first |
| NaN in data | Missing values | Filter or impute |

## Data Format Reference

### Required

- `adata.X` or `adata.layers["counts"]`: Raw integer counts (sparse OK)
- `adata.obs`: Cell metadata DataFrame
- `adata.var`: Gene metadata DataFrame

### Recommended

- `adata.obs["batch"]`: Batch/sample identifiers
- `adata.var["highly_variable"]`: HVG boolean mask

### For scANVI

- `adata.obs["labels"]`: Cell type annotations
- Can include "Unknown" for unlabeled cells
