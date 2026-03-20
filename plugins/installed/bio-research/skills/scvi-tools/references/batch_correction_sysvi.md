# Advanced Batch Correction with sysVI

This reference covers system-level batch correction using sysVI, designed for integrating data across major technological or study differences.

## Overview

sysVI (System Variational Inference) extends scVI for scenarios where:
- Batch effects are very strong (different technologies)
- Standard scVI over-corrects biological signal
- You need to separate "system" effects from biological variation

## When to Use sysVI vs scVI

| Scenario | Recommended Model |
|----------|-------------------|
| Same technology, different samples | scVI |
| 10x v2 vs 10x v3 | scVI (usually) |
| 10x vs Smart-seq2 | sysVI |
| Different sequencing depths | scVI with covariates |
| Cross-study integration | sysVI |
| Atlas-scale integration | sysVI |

## Prerequisites

```python
import scvi
import scanpy as sc
import numpy as np

print(f"scvi-tools version: {scvi.__version__}")
```

## Understanding sysVI Architecture

sysVI separates variation into:
1. **Biological variation**: Cell type, state, trajectory
2. **System variation**: Technology, study, lab effects

```
                    ┌─────────────────┐
Input counts ──────►│    Encoder      │
                    │                 │
System info ───────►│  (conditioned)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Latent z      │
                    │  (biological)   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
System info ───────►│    Decoder      │
                    │  (conditioned)  │
                    └────────┬────────┘
                             │
                    Reconstructed counts
```

## Basic sysVI Workflow

### Step 1: Prepare Data

```python
# Load datasets from different systems
adata1 = sc.read_h5ad("10x_data.h5ad")
adata2 = sc.read_h5ad("smartseq_data.h5ad")

# Add system labels
adata1.obs["system"] = "10x"
adata2.obs["system"] = "Smart-seq2"

# Add batch labels (within system)
# e.g., different samples within each technology

# Concatenate
adata = sc.concat([adata1, adata2])

# Store raw counts
adata.layers["counts"] = adata.X.copy()
```

### Step 2: HVG Selection

```python
# Select HVGs considering both batch and system
sc.pp.highly_variable_genes(
    adata,
    n_top_genes=4000,  # More genes for cross-system
    flavor="seurat_v3",
    batch_key="system",  # Consider system for HVG
    layer="counts"
)

# Optionally: ensure overlap between systems
# Check HVGs are expressed in both systems
adata = adata[:, adata.var["highly_variable"]].copy()
```

### Step 3: Setup and Train sysVI

```python
# Setup AnnData
# Note: sysVI may be accessed differently depending on version
# Check scvi-tools documentation for current API

scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="sample",           # Within-system batches
    categorical_covariate_keys=["system"]  # System-level covariate
)

# For true sysVI (if available in your version)
# scvi.model.SysVI.setup_anndata(...)

# Create model with system awareness
model = scvi.model.SCVI(
    adata,
    n_latent=30,
    n_layers=2,
    gene_likelihood="nb"
)

# Train
model.train(max_epochs=300)
```

### Step 4: Extract Representations

```python
# Get latent representation
adata.obsm["X_integrated"] = model.get_latent_representation()

# Clustering and visualization
sc.pp.neighbors(adata, use_rep="X_integrated")
sc.tl.umap(adata)
sc.tl.leiden(adata)

# Check integration
sc.pl.umap(adata, color=["system", "leiden", "cell_type"])
```

## Alternative: Harmony + scVI

For cross-system integration, combining methods can work well:

```python
import scanpy.external as sce

# First run PCA
sc.pp.pca(adata)

# Apply Harmony for initial alignment
sce.pp.harmony_integrate(adata, key="system")

# Then train scVI on Harmony-corrected embedding
# Or use Harmony representation directly
```

## Alternative: Using Covariates in scVI

For moderate system effects:

```python
# Include system as categorical covariate
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="sample",
    categorical_covariate_keys=["system", "technology_version"]
)

model = scvi.model.SCVI(adata, n_latent=30)
model.train()
```

## Alternative: Separate Models + Integration

For very different systems:

```python
# Train separate models
scvi.model.SCVI.setup_anndata(adata1, layer="counts", batch_key="sample")
model1 = scvi.model.SCVI(adata1)
model1.train()

scvi.model.SCVI.setup_anndata(adata2, layer="counts", batch_key="sample")
model2 = scvi.model.SCVI(adata2)
model2.train()

# Get latent spaces
adata1.obsm["X_scVI"] = model1.get_latent_representation()
adata2.obsm["X_scVI"] = model2.get_latent_representation()

# Align with CCA or Harmony
# ... additional alignment step
```

## Evaluating Cross-System Integration

### Visual Assessment

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(15, 4))

# Color by system
sc.pl.umap(adata, color="system", ax=axes[0], show=False, title="By System")

# Color by cell type
sc.pl.umap(adata, color="cell_type", ax=axes[1], show=False, title="By Cell Type")

# Color by expression of marker
sc.pl.umap(adata, color="CD3D", ax=axes[2], show=False, title="CD3D Expression")

plt.tight_layout()
```

### Quantitative Metrics

```python
# Using scib-metrics
from scib_metrics.benchmark import Benchmarker

bm = Benchmarker(
    adata,
    batch_key="system",
    label_key="cell_type",
    embedding_obsm_keys=["X_integrated"]
)

bm.benchmark()

# Key metrics:
# - Batch mixing (ASW_batch, Graph connectivity)
# - Bio conservation (NMI, ARI, ASW_label)
```

### LISI Scores

```python
# Local Inverse Simpson's Index
from scib_metrics import lisi

# Batch LISI (higher = better mixing)
batch_lisi = lisi.ilisi_graph(
    adata,
    batch_key="system",
    use_rep="X_integrated"
)

# Cell type LISI (lower = better preservation)
ct_lisi = lisi.clisi_graph(
    adata,
    label_key="cell_type", 
    use_rep="X_integrated"
)

print(f"Batch LISI: {batch_lisi.mean():.3f}")
print(f"Cell type LISI: {ct_lisi.mean():.3f}")
```

## Handling Specific Challenges

### Different Gene Sets

```python
# Find common genes
common_genes = adata1.var_names.intersection(adata2.var_names)
print(f"Common genes: {len(common_genes)}")

# If too few, use gene mapping
# Or impute missing genes
```

### Different Sequencing Depths

```python
# Add depth as continuous covariate
adata.obs["log_counts"] = np.log1p(adata.obs["total_counts"])

scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="sample",
    continuous_covariate_keys=["log_counts"]
)
```

### Unbalanced Cell Types

```python
# Check cell type distribution per system
import pandas as pd

ct_dist = pd.crosstab(adata.obs["system"], adata.obs["cell_type"], normalize="index")
print(ct_dist)

# If very unbalanced, consider:
# 1. Subsample to balance
# 2. Use scANVI with labels to preserve rare types
```

## Complete Pipeline

```python
def integrate_cross_system(
    adatas: dict,
    system_key: str = "system",
    batch_key: str = "batch",
    cell_type_key: str = "cell_type",
    n_top_genes: int = 4000,
    n_latent: int = 30
):
    """
    Integrate datasets from different technological systems.
    
    Parameters
    ----------
    adatas : dict
        Dictionary of {system_name: AnnData}
    system_key : str
        Key for system annotation
    batch_key : str
        Key for within-system batch
    cell_type_key : str
        Key for cell type labels (optional)
    n_top_genes : int
        Number of HVGs
    n_latent : int
        Latent dimensions
        
    Returns
    -------
    Integrated AnnData with model
    """
    import scvi
    import scanpy as sc
    
    # Add system labels and concatenate
    for system_name, adata in adatas.items():
        adata.obs[system_key] = system_name
    
    adata = sc.concat(list(adatas.values()))
    
    # Find common genes
    for name, ad in adatas.items():
        if name == list(adatas.keys())[0]:
            common_genes = set(ad.var_names)
        else:
            common_genes = common_genes.intersection(ad.var_names)
    
    adata = adata[:, list(common_genes)].copy()
    print(f"Common genes: {len(common_genes)}")
    
    # Store counts
    adata.layers["counts"] = adata.X.copy()
    
    # HVG selection
    sc.pp.highly_variable_genes(
        adata,
        n_top_genes=n_top_genes,
        flavor="seurat_v3",
        batch_key=system_key,
        layer="counts"
    )
    adata = adata[:, adata.var["highly_variable"]].copy()
    
    # Setup with system as covariate
    scvi.model.SCVI.setup_anndata(
        adata,
        layer="counts",
        batch_key=batch_key if batch_key in adata.obs else None,
        categorical_covariate_keys=[system_key]
    )
    
    # Train
    model = scvi.model.SCVI(adata, n_latent=n_latent, n_layers=2)
    model.train(max_epochs=300, early_stopping=True)
    
    # Get representation
    adata.obsm["X_integrated"] = model.get_latent_representation()
    
    # Clustering
    sc.pp.neighbors(adata, use_rep="X_integrated")
    sc.tl.umap(adata)
    sc.tl.leiden(adata)
    
    return adata, model

# Usage
adatas = {
    "10x_v3": sc.read_h5ad("10x_v3_data.h5ad"),
    "Smart-seq2": sc.read_h5ad("smartseq_data.h5ad"),
    "Drop-seq": sc.read_h5ad("dropseq_data.h5ad")
}

adata_integrated, model = integrate_cross_system(adatas)

# Visualize
sc.pl.umap(adata_integrated, color=["system", "leiden"])
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Systems don't mix | Effects too strong | Use more genes, increase n_latent |
| Over-correction | Model too aggressive | Reduce n_layers, use scANVI |
| Few common genes | Different platforms | Use gene name mapping |
| One system dominates | Unbalanced sizes | Subsample larger dataset |

## Key References

- Lopez et al. (2018) "Deep generative modeling for single-cell transcriptomics"
- Luecken et al. (2022) "Benchmarking atlas-level data integration in single-cell genomics"
