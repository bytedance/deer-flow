# Spatial Transcriptomics Analysis

This reference covers spatial transcriptomics analysis using scvi-tools methods: DestVI for deconvolution and resolVI for building spatial models.

## Overview

Spatial transcriptomics technologies like Visium capture gene expression at defined spatial locations, but many platforms have multi-cellular resolution. scvi-tools provides two main approaches:

- **DestVI**: Deconvolution - estimates cell type proportions at each spot using a single-cell reference
- **resolVI**: Builds a spatial model that learns gene expression patterns accounting for spatial context

## Available Methods in scvi-tools

| Method | Description | Use Case |
|--------|-------------|----------|
| **DestVI** | Variational inference for deconvolution | Estimate cell type proportions per spot |
| **resolVI** | Spatial gene expression model | Learn spatially-aware representations |
| **CondSCVI** | Reference model for DestVI | Required for DestVI workflow |

## Prerequisites

```python
import scvi
import scanpy as sc
import squidpy as sq
import numpy as np

print(f"scvi-tools version: {scvi.__version__}")
```

---

## Part 1: DestVI Deconvolution

### Step 1: Load Spatial Data

```python
# Load Visium data
adata_spatial = sc.read_visium("spaceranger_output/")

# Check structure
print(f"Spots: {adata_spatial.n_obs}")
print(f"Genes: {adata_spatial.n_vars}")
print(f"Spatial coordinates: {adata_spatial.obsm['spatial'].shape}")

# Basic QC
sc.pp.calculate_qc_metrics(adata_spatial, inplace=True)
adata_spatial = adata_spatial[adata_spatial.obs['n_genes_by_counts'] > 200].copy()

# Store counts
adata_spatial.layers["counts"] = adata_spatial.X.copy()
```

### Step 2: Load Single-Cell Reference

```python
# Load reference single-cell data
adata_sc = sc.read_h5ad("reference_scrna.h5ad")

# Requirements:
# - Raw counts
# - Cell type annotations
print(f"Reference cells: {adata_sc.n_obs}")
print(f"Cell types: {adata_sc.obs['cell_type'].nunique()}")
print(adata_sc.obs['cell_type'].value_counts())

# Store counts
adata_sc.layers["counts"] = adata_sc.X.copy()
```

### Step 3: Prepare Data

```python
# DestVI requires gene overlap between reference and spatial
common_genes = adata_sc.var_names.intersection(adata_spatial.var_names)
print(f"Common genes: {len(common_genes)}")

adata_sc = adata_sc[:, common_genes].copy()
adata_spatial = adata_spatial[:, common_genes].copy()
```

### Step 4: Train Reference Model (CondSCVI)

```python
# Train conditional scVI on reference data
scvi.model.CondSCVI.setup_anndata(
    adata_sc,
    layer="counts",
    labels_key="cell_type"
)

sc_model = scvi.model.CondSCVI(
    adata_sc,
    n_latent=20
)

sc_model.train(max_epochs=200)
sc_model.history['elbo_train'].plot()
```

### Step 5: Train DestVI

```python
# Setup spatial data
scvi.model.DestVI.setup_anndata(
    adata_spatial,
    layer="counts"
)

# Train DestVI using reference model
spatial_model = scvi.model.DestVI.from_rna_model(
    adata_spatial,
    sc_model
)

spatial_model.train(max_epochs=500)
```

### Step 6: Get Cell Type Proportions

```python
# Infer cell type proportions at each spot
proportions = spatial_model.get_proportions()

# Add to adata
for ct in adata_sc.obs['cell_type'].unique():
    adata_spatial.obs[f'prop_{ct}'] = proportions[ct]

# Visualize
sq.pl.spatial_scatter(
    adata_spatial,
    color=[f'prop_{ct}' for ct in adata_sc.obs['cell_type'].unique()[:6]],
    ncols=3
)
```

---

## Part 2: resolVI Spatial Model

resolVI is a semi-supervised method that learns cell type assignments and spatially-aware representations directly from spatial data, optionally using initial cell type predictions.

**Note**: resolVI is in `scvi.external` (not `scvi.model`).

### Step 1: Prepare Spatial Data

```python
# Load and preprocess
adata = sc.read_visium("spaceranger_output/")

# QC
sc.pp.calculate_qc_metrics(adata, inplace=True)
adata = adata[adata.obs['n_genes_by_counts'] > 200].copy()

# Store counts
adata.layers["counts"] = adata.X.copy()

# HVG selection
sc.pp.highly_variable_genes(
    adata,
    n_top_genes=4000,
    flavor="seurat_v3",
    layer="counts"
)
adata = adata[:, adata.var['highly_variable']].copy()

# Optional: Get initial cell type predictions (e.g., from a reference)
# adata.obs["predicted_celltype"] = ...
```

### Step 2: Setup and Train resolVI

```python
# Setup for resolVI (note: scvi.external, not scvi.model)
scvi.external.RESOLVI.setup_anndata(
    adata,
    labels_key="predicted_celltype",  # Initial cell type predictions
    layer="counts"
)

# Create model (semisupervised=True uses the labels)
model = scvi.external.RESOLVI(adata, semisupervised=True)

# Train
model.train(max_epochs=50)
```

### Step 3: Get Cell Type Predictions

```python
# Get refined cell type predictions
# soft=True returns probabilities, soft=False returns labels
cell_type_probs = model.predict(adata, num_samples=3, soft=True)
cell_type_labels = model.predict(adata, num_samples=3, soft=False)

adata.obs["resolvi_celltype"] = cell_type_labels

# Visualize
sq.pl.spatial_scatter(adata, color="resolvi_celltype")
```

### Step 4: Get Latent Representation

```python
# Get latent representation
adata.obsm["X_resolVI"] = model.get_latent_representation(adata)

# Cluster based on spatial representation
sc.pp.neighbors(adata, use_rep="X_resolVI")
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=0.5)

# Visualize clusters spatially
sq.pl.spatial_scatter(adata, color="leiden")
```

### Step 5: Differential Expression

```python
# DE between cell types using resolVI
de_results = model.differential_expression(
    adata,
    groupby="resolvi_celltype",
    group1="T_cell",
    group2="Tumor"
)

print(de_results.head(20))
```

### Step 6: Niche Abundance Analysis

```python
# Analyze how cell type neighborhoods differ between conditions
# Requires spatial neighbor graph
sq.gr.spatial_neighbors(adata, coord_type="generic")

niche_results = model.differential_niche_abundance(
    groupby="resolvi_celltype",
    group1="T_cell",
    group2="Tumor",
    neighbor_key="spatial_neighbors"
)
```

### Step 7: Query Mapping (Transfer to New Data)

```python
# Map new spatial data to trained model
query_adata = sc.read_visium("new_sample/")
query_adata.layers["counts"] = query_adata.X.copy()

# Prepare and load query
model.prepare_query_anndata(query_adata, reference_model=model)
query_model = model.load_query_data(query_adata, reference_model=model)

# Fine-tune on query
query_model.train(max_epochs=20)

# Get predictions for query
query_labels = query_model.predict(query_adata, num_samples=3, soft=False)
```

---

## Visualization

### Spatial Proportions

```python
import matplotlib.pyplot as plt

# Plot multiple cell type proportions
cell_types = ['T_cell', 'Tumor', 'Fibroblast', 'Macrophage']
fig, axes = plt.subplots(2, 2, figsize=(12, 12))

for ax, ct in zip(axes.flat, cell_types):
    sq.pl.spatial_scatter(
        adata_spatial,
        color=f'prop_{ct}',
        ax=ax,
        title=ct,
        show=False
    )

plt.tight_layout()
```

### Enrichment by Region

```python
# Cluster spatial data
sc.pp.neighbors(adata_spatial)
sc.tl.leiden(adata_spatial, resolution=0.5)

# Compare proportions across regions
import pandas as pd

cell_types = adata_sc.obs['cell_type'].unique()
prop_cols = [f'prop_{ct}' for ct in cell_types]
region_props = adata_spatial.obs.groupby('leiden')[prop_cols].mean()
print(region_props)

# Heatmap
import seaborn as sns
plt.figure(figsize=(10, 6))
sns.heatmap(region_props.T, annot=True, cmap='viridis')
plt.title('Cell Type Proportions by Region')
```

### Spatial Cell Type Interactions

```python
# Neighborhood enrichment using cell type assignments
sq.gr.spatial_neighbors(adata_spatial)

# Create "dominant cell type" annotation
prop_cols = [f'prop_{ct}' for ct in cell_types]
adata_spatial.obs['dominant_type'] = adata_spatial.obs[prop_cols].idxmax(axis=1)
adata_spatial.obs['dominant_type'] = adata_spatial.obs['dominant_type'].str.replace('prop_', '')

# Co-occurrence analysis
sq.gr.co_occurrence(adata_spatial, cluster_key='dominant_type')
sq.pl.co_occurrence(adata_spatial, cluster_key='dominant_type')
```

---

## Complete DestVI Pipeline

```python
def deconvolve_spatial(
    adata_spatial,
    adata_ref,
    cell_type_key="cell_type",
    n_latent=20,
    max_epochs_ref=200,
    max_epochs_spatial=500
):
    """
    Perform spatial deconvolution using DestVI.

    Parameters
    ----------
    adata_spatial : AnnData
        Spatial transcriptomics data
    adata_ref : AnnData
        Single-cell reference with cell type annotations
    cell_type_key : str
        Column in adata_ref.obs with cell type labels
    n_latent : int
        Latent dimensions
    max_epochs_ref : int
        Training epochs for reference model
    max_epochs_spatial : int
        Training epochs for spatial model

    Returns
    -------
    AnnData with cell type proportions in obs
    """
    import scvi

    # Get common genes
    common_genes = adata_ref.var_names.intersection(adata_spatial.var_names)
    adata_ref = adata_ref[:, common_genes].copy()
    adata_spatial = adata_spatial[:, common_genes].copy()

    # Ensure counts are stored
    if "counts" not in adata_ref.layers:
        adata_ref.layers["counts"] = adata_ref.X.copy()
    if "counts" not in adata_spatial.layers:
        adata_spatial.layers["counts"] = adata_spatial.X.copy()

    # Train reference model
    scvi.model.CondSCVI.setup_anndata(
        adata_ref,
        layer="counts",
        labels_key=cell_type_key
    )

    ref_model = scvi.model.CondSCVI(adata_ref, n_latent=n_latent)
    ref_model.train(max_epochs=max_epochs_ref)

    # Train spatial model
    scvi.model.DestVI.setup_anndata(adata_spatial, layer="counts")

    spatial_model = scvi.model.DestVI.from_rna_model(
        adata_spatial,
        ref_model
    )
    spatial_model.train(max_epochs=max_epochs_spatial)

    # Get proportions
    proportions = spatial_model.get_proportions()

    cell_types = adata_ref.obs[cell_type_key].unique()
    for ct in cell_types:
        adata_spatial.obs[f'prop_{ct}'] = proportions[ct]

    # Add dominant type
    prop_cols = [f'prop_{ct}' for ct in cell_types]
    adata_spatial.obs['dominant_type'] = adata_spatial.obs[prop_cols].idxmax(axis=1)
    adata_spatial.obs['dominant_type'] = adata_spatial.obs['dominant_type'].str.replace('prop_', '')

    return adata_spatial, ref_model, spatial_model

# Usage
adata_spatial, ref_model, spatial_model = deconvolve_spatial(
    adata_spatial,
    adata_sc,
    cell_type_key="cell_type"
)

# Visualize
sq.pl.spatial_scatter(
    adata_spatial,
    color=['dominant_type', 'prop_T_cell', 'prop_Tumor'],
    ncols=3
)
```

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Few common genes | Different gene naming | Convert gene names (Ensembl ↔ Symbol) |
| Poor deconvolution | Reference doesn't match | Use tissue-matched reference |
| All spots same type | Over-smoothing | Adjust model parameters, check reference diversity |
| NaN proportions | Missing cell types | Ensure all expected types in reference |
| Training slow | Large spatial dataset | Reduce max_epochs, increase batch_size |

## Key References

- Lopez et al. (2022) "DestVI identifies continuums of cell types in spatial transcriptomics data"
- [scvi-tools spatial tutorials](https://docs.scvi-tools.org/en/stable/tutorials/index.html)
