# RNA Velocity with veloVI

This reference covers RNA velocity analysis using veloVI, a deep learning approach that improves upon traditional velocity methods.

## Overview

RNA velocity estimates the future state of cells by modeling:
- **Unspliced RNA**: Newly transcribed, contains introns
- **Spliced RNA**: Mature mRNA, introns removed

The ratio of unspliced to spliced indicates whether a gene is being upregulated or downregulated.

## Why veloVI?

Traditional methods (velocyto, scVelo) have limitations:
- Assume steady-state or dynamical model
- Sensitive to noise
- Don't handle batch effects

veloVI addresses these with:
- Probabilistic modeling
- Better uncertainty quantification
- Integration with scVI framework

## Prerequisites

```python
import scvi
import scvelo as scv
import scanpy as sc
import numpy as np

print(f"scvi-tools version: {scvi.__version__}")
print(f"scvelo version: {scv.__version__}")
```

## Step 1: Generate Spliced/Unspliced Counts

### From BAM Files (velocyto)

```bash
# Run velocyto on Cell Ranger output
velocyto run10x /path/to/cellranger_output /path/to/genes.gtf

# Output: velocyto.loom file with spliced/unspliced layers
```

### From kb-python (kallisto|bustools)

```bash
# Faster alternative using kallisto
kb count \
    --workflow lamanno \
    -i index.idx \
    -g t2g.txt \
    -c1 spliced_t2c.txt \
    -c2 unspliced_t2c.txt \
    -x 10xv3 \
    -o output \
    R1.fastq.gz R2.fastq.gz
```

## Step 2: Load Velocity Data

```python
# Load loom file from velocyto
adata = scv.read("velocyto_output.loom")

# Or load from kb-python
adata = sc.read_h5ad("adata.h5ad")
# Spliced in adata.layers["spliced"]
# Unspliced in adata.layers["unspliced"]

# Check layers
print("Available layers:", list(adata.layers.keys()))
print(f"Spliced shape: {adata.layers['spliced'].shape}")
print(f"Unspliced shape: {adata.layers['unspliced'].shape}")
```

### Merge with Existing AnnData

```python
# If you have separate loom and h5ad
ldata = scv.read("velocyto.loom")
adata = sc.read_h5ad("processed.h5ad")

# Merge velocity data into processed adata
adata = scv.utils.merge(adata, ldata)
```

## Step 3: Preprocessing for Velocity

```python
# Filter and normalize
scv.pp.filter_and_normalize(
    adata,
    min_shared_counts=20,
    n_top_genes=2000
)

# Compute moments (for scVelo comparison)
scv.pp.moments(adata, n_pcs=30, n_neighbors=30)
```

## Step 4: Run veloVI

### Setup AnnData

```python
# Setup for veloVI
scvi.model.VELOVI.setup_anndata(
    adata,
    spliced_layer="spliced",
    unspliced_layer="unspliced"
)
```

### Train Model

```python
# Create and train veloVI model
vae = scvi.model.VELOVI(adata)

vae.train(
    max_epochs=500,
    early_stopping=True,
    batch_size=256
)

# Check training
vae.history["elbo_train"].plot()
```

### Get Velocity Estimates

```python
# Get latent time
latent_time = vae.get_latent_time(n_samples=25)
adata.obs["veloVI_latent_time"] = latent_time

# Get velocity
velocities = vae.get_velocity(n_samples=25)
adata.layers["veloVI_velocity"] = velocities

# Get expression states
adata.layers["veloVI_expression"] = vae.get_expression_fit(n_samples=25)
```

## Step 5: Visualize Velocity

### Velocity Streamlines

```python
# Compute velocity graph
scv.tl.velocity_graph(adata, vkey="veloVI_velocity")

# Plot streamlines on UMAP
scv.pl.velocity_embedding_stream(
    adata,
    basis="umap",
    vkey="veloVI_velocity",
    color="cell_type"
)
```

### Velocity Arrows

```python
# Individual cell arrows
scv.pl.velocity_embedding(
    adata,
    basis="umap",
    vkey="veloVI_velocity",
    arrow_length=3,
    arrow_size=2,
    color="cell_type"
)
```

### Latent Time

```python
# Plot latent time (pseudotime from velocity)
sc.pl.umap(adata, color="veloVI_latent_time", cmap="viridis")
```

## Step 6: Compare with scVelo

```python
# Run standard scVelo for comparison
scv.tl.velocity(adata, mode="dynamical")
scv.tl.velocity_graph(adata)

# Compare velocity fields
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

scv.pl.velocity_embedding_stream(
    adata, basis="umap", ax=axes[0], 
    title="scVelo", show=False
)

scv.pl.velocity_embedding_stream(
    adata, basis="umap", vkey="veloVI_velocity",
    ax=axes[1], title="veloVI", show=False
)

plt.tight_layout()
```

## Step 7: Gene-Level Analysis

### Velocity Phase Portraits

```python
# Plot phase portrait for specific genes
genes = ["SOX2", "PAX6", "DCX", "NEUROD1"]

scv.pl.velocity(
    adata,
    var_names=genes,
    vkey="veloVI_velocity",
    colorbar=True
)
```

### Gene Dynamics

```python
# Plot expression over latent time
for gene in genes:
    fig, ax = plt.subplots(figsize=(6, 4))
    
    sc.pl.scatter(
        adata,
        x="veloVI_latent_time",
        y=gene,
        color="cell_type",
        ax=ax,
        show=False
    )
    ax.set_xlabel("Latent Time")
    ax.set_ylabel(f"{gene} Expression")
```

### Driver Genes

```python
# Find genes driving velocity
scv.tl.rank_velocity_genes(
    adata,
    vkey="veloVI_velocity",
    groupby="cell_type"
)

# Get top genes per cluster
df = scv.get_df(adata, "rank_velocity_genes/names")
print(df.head(10))
```

## Step 8: Uncertainty Quantification

veloVI provides uncertainty estimates:

```python
# Get velocity with uncertainty
velocity_mean, velocity_std = vae.get_velocity(
    n_samples=100,
    return_mean=True,
    return_numpy=True
)

# Store uncertainty
adata.layers["velocity_uncertainty"] = velocity_std

# Visualize uncertainty
adata.obs["mean_velocity_uncertainty"] = velocity_std.mean(axis=1)
sc.pl.umap(adata, color="mean_velocity_uncertainty")
```

## Complete Pipeline

```python
def run_velocity_analysis(
    adata,
    spliced_layer="spliced",
    unspliced_layer="unspliced",
    n_top_genes=2000,
    max_epochs=500
):
    """
    Complete RNA velocity analysis with veloVI.
    
    Parameters
    ----------
    adata : AnnData
        Data with spliced/unspliced layers
    spliced_layer : str
        Layer name for spliced counts
    unspliced_layer : str
        Layer name for unspliced counts
    n_top_genes : int
        Number of velocity genes
    max_epochs : int
        Training epochs
        
    Returns
    -------
    AnnData with velocity and model
    """
    import scvi
    import scvelo as scv
    import scanpy as sc
    
    adata = adata.copy()
    
    # Preprocessing
    scv.pp.filter_and_normalize(
        adata,
        min_shared_counts=20,
        n_top_genes=n_top_genes
    )
    
    # Compute moments (needed for some visualizations)
    scv.pp.moments(adata, n_pcs=30, n_neighbors=30)
    
    # Setup veloVI
    scvi.model.VELOVI.setup_anndata(
        adata,
        spliced_layer=spliced_layer,
        unspliced_layer=unspliced_layer
    )
    
    # Train
    model = scvi.model.VELOVI(adata)
    model.train(max_epochs=max_epochs, early_stopping=True)
    
    # Get results
    adata.obs["latent_time"] = model.get_latent_time(n_samples=25)
    adata.layers["velocity"] = model.get_velocity(n_samples=25)
    
    # Compute velocity graph for visualization
    scv.tl.velocity_graph(adata, vkey="velocity")
    
    # Compute UMAP if not present
    if "X_umap" not in adata.obsm:
        sc.pp.neighbors(adata)
        sc.tl.umap(adata)
    
    return adata, model

# Usage
adata_velocity, model = run_velocity_analysis(adata)

# Visualize
scv.pl.velocity_embedding_stream(
    adata_velocity,
    basis="umap",
    vkey="velocity",
    color="cell_type"
)

sc.pl.umap(adata_velocity, color="latent_time")
```

## Advanced: Batch-Aware Velocity

```python
# For multi-batch data, include batch in model
scvi.model.VELOVI.setup_anndata(
    adata,
    spliced_layer="spliced",
    unspliced_layer="unspliced",
    batch_key="batch"
)

model = scvi.model.VELOVI(adata)
model.train()
```

## Interpreting Results

### Good Velocity Signal

- Streamlines follow expected differentiation
- Latent time correlates with known biology
- Phase portraits show clear dynamics

### Poor Velocity Signal

- Random/chaotic streamlines
- No correlation with known markers
- May indicate:
  - Insufficient unspliced reads
  - Cells at steady state
  - Technical issues

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| No velocity signal | Low unspliced counts | Check sequencing depth, use kb-python |
| Reversed direction | Wrong root assignment | Manually set root cells |
| Noisy streamlines | Too many genes | Reduce n_top_genes |
| Memory error | Large dataset | Reduce batch_size |

## Key References

- Gayoso et al. (2023) "Deep generative modeling of transcriptional dynamics for RNA velocity analysis in single cells"
- La Manno et al. (2018) "RNA velocity of single cells"
- Bergen et al. (2020) "Generalizing RNA velocity to transient cell states through dynamical modeling"
