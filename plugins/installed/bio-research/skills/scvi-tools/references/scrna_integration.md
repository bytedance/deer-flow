# scRNA-seq Integration with scVI and scANVI

This reference covers batch correction and dataset integration using scVI (unsupervised) and scANVI (semi-supervised with cell type labels).

## Overview

Single-cell datasets often have batch effects from:
- Different donors/patients
- Different experimental batches
- Different technologies (10x v2 vs v3)
- Different studies

scVI and scANVI learn a shared latent space where batch effects are removed while biological variation is preserved.

## When to Use Which Model

| Model | Use When | Labels Needed |
|-------|----------|---------------|
| **scVI** | No labels available, exploratory analysis | No |
| **scANVI** | Have partial/full labels, want better preservation | Yes (partial OK) |

## scVI Integration Workflow

### Step 1: Prepare Data

```python
import scvi
import scanpy as sc

# Load datasets
adata1 = sc.read_h5ad("dataset1.h5ad")
adata2 = sc.read_h5ad("dataset2.h5ad")

# Add batch annotation
adata1.obs["batch"] = "batch1"
adata2.obs["batch"] = "batch2"

# Concatenate
adata = sc.concat([adata1, adata2], label="batch")

# Ensure we have raw counts
# If data is normalized, recover from .raw
if hasattr(adata, 'raw') and adata.raw is not None:
    adata = adata.raw.to_adata()

# Store counts
adata.layers["counts"] = adata.X.copy()
```

### Step 2: HVG Selection Across Batches

```python
# Select HVGs considering batch
sc.pp.highly_variable_genes(
    adata,
    n_top_genes=2000,
    flavor="seurat_v3",
    batch_key="batch",
    layer="counts"
)

# Subset to HVGs
adata = adata[:, adata.var["highly_variable"]].copy()
```

### Step 3: Setup and Train scVI

```python
# Register data with scVI
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch"
)

# Create model
model = scvi.model.SCVI(
    adata,
    n_latent=30,          # Latent dimensions
    n_layers=2,           # Encoder/decoder depth
    gene_likelihood="nb"  # negative binomial (or "zinb")
)

# Train
model.train(
    max_epochs=200,
    early_stopping=True,
    early_stopping_patience=10,
    batch_size=128
)

# Plot training history
model.history["elbo_train"].plot()
```

### Step 4: Get Integrated Representation

```python
# Get latent representation
adata.obsm["X_scVI"] = model.get_latent_representation()

# Use for clustering and visualization
sc.pp.neighbors(adata, use_rep="X_scVI", n_neighbors=15)
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=1.0)

# Visualize integration
sc.pl.umap(adata, color=["batch", "leiden"], ncols=2)
```

### Step 5: Save Model

```python
# Save model for later use
model.save("scvi_model/")

# Load model
model = scvi.model.SCVI.load("scvi_model/", adata=adata)
```

## scANVI Integration Workflow

scANVI extends scVI with cell type labels for better biological preservation.

### Step 1: Prepare Data with Labels

```python
# Labels should be in adata.obs
# Use "Unknown" for unlabeled cells
print(adata.obs["cell_type"].value_counts())

# For partially labeled data
# Mark unlabeled cells
adata.obs["cell_type_scanvi"] = adata.obs["cell_type"].copy()
# adata.obs.loc[unlabeled_mask, "cell_type_scanvi"] = "Unknown"
```

### Step 2: Option A - Train scANVI from Scratch

```python
# Setup for scANVI
scvi.model.SCANVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    labels_key="cell_type"
)

# Create model
scanvi_model = scvi.model.SCANVI(
    adata,
    n_latent=30,
    n_layers=2
)

# Train
scanvi_model.train(max_epochs=200)
```

### Step 2: Option B - Initialize scANVI from scVI (Recommended)

```python
# First train scVI
scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
scvi_model = scvi.model.SCVI(adata, n_latent=30)
scvi_model.train(max_epochs=200)

# Initialize scANVI from scVI
scanvi_model = scvi.model.SCANVI.from_scvi_model(
    scvi_model,
    labels_key="cell_type",
    unlabeled_category="Unknown"  # For partially labeled data
)

# Fine-tune scANVI (fewer epochs needed)
scanvi_model.train(max_epochs=50)
```

### Step 3: Get Results

```python
# Latent representation
adata.obsm["X_scANVI"] = scanvi_model.get_latent_representation()

# Predicted labels for unlabeled cells
predictions = scanvi_model.predict()
adata.obs["predicted_cell_type"] = predictions

# Prediction probabilities
soft_predictions = scanvi_model.predict(soft=True)

# Visualization
sc.pp.neighbors(adata, use_rep="X_scANVI")
sc.tl.umap(adata)
sc.pl.umap(adata, color=["batch", "cell_type", "predicted_cell_type"])
```

## Comparing Integration Quality

### Visual Assessment

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(15, 4))

# Before integration (on PCA)
sc.pp.pca(adata)
sc.pl.pca(adata, color="batch", ax=axes[0], title="Before (PCA)", show=False)

# After scVI
sc.pp.neighbors(adata, use_rep="X_scVI")
sc.tl.umap(adata)
sc.pl.umap(adata, color="batch", ax=axes[1], title="After scVI", show=False)

# After scANVI
sc.pp.neighbors(adata, use_rep="X_scANVI")
sc.tl.umap(adata)
sc.pl.umap(adata, color="batch", ax=axes[2], title="After scANVI", show=False)

plt.tight_layout()
```

### Quantitative Metrics (scib)

```python
# pip install scib-metrics

from scib_metrics.benchmark import Benchmarker

bm = Benchmarker(
    adata,
    batch_key="batch",
    label_key="cell_type",
    embedding_obsm_keys=["X_pca", "X_scVI", "X_scANVI"]
)

bm.benchmark()
bm.plot_results_table()
```

## Differential Expression

scVI provides differential expression that accounts for batch effects:

```python
# DE between groups
de_results = model.differential_expression(
    groupby="cell_type",
    group1="T cells",
    group2="B cells"
)

# Filter significant
de_sig = de_results[
    (de_results["is_de_fdr_0.05"] == True) &
    (abs(de_results["lfc_mean"]) > 1)
]

print(de_sig.head(20))
```

## Advanced: Multiple Categorical Covariates

```python
# Include additional covariates beyond batch
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    batch_key="batch",
    categorical_covariate_keys=["donor", "technology"]
)

model = scvi.model.SCVI(adata, n_latent=30)
model.train()
```

## Training Tips

### For Large Datasets (>100k cells)

```python
model.train(
    max_epochs=100,      # Fewer epochs needed
    batch_size=256,      # Larger batches
    train_size=0.9,      # Less validation
    early_stopping=True
)
```

### For Small Datasets (<10k cells)

```python
model = scvi.model.SCVI(
    adata,
    n_latent=10,         # Smaller latent space
    n_layers=1,          # Simpler model
    dropout_rate=0.2     # More regularization
)

model.train(
    max_epochs=400,
    batch_size=64
)
```

### Monitoring Training

```python
# Check training curves
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.plot(model.history["elbo_train"], label="Train")
ax.plot(model.history["elbo_validation"], label="Validation")
ax.set_xlabel("Epoch")
ax.set_ylabel("ELBO")
ax.legend()

# Should see convergence without overfitting
```

## Complete Pipeline

```python
def integrate_datasets(
    adatas,
    batch_key="batch",
    labels_key=None,
    n_top_genes=2000,
    n_latent=30
):
    """
    Integrate multiple scRNA-seq datasets.
    
    Parameters
    ----------
    adatas : dict
        Dictionary of {batch_name: AnnData}
    batch_key : str
        Key for batch annotation
    labels_key : str, optional
        Key for cell type labels (uses scANVI if provided)
    n_top_genes : int
        Number of HVGs
    n_latent : int
        Latent dimensions
        
    Returns
    -------
    AnnData with integrated representation
    """
    import scvi
    import scanpy as sc
    
    # Add batch labels and concatenate
    for batch_name, adata in adatas.items():
        adata.obs[batch_key] = batch_name
    
    adata = sc.concat(list(adatas.values()), label=batch_key)
    
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
    
    # Train model
    if labels_key and labels_key in adata.obs.columns:
        # Use scANVI
        scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key=batch_key)
        scvi_model = scvi.model.SCVI(adata, n_latent=n_latent)
        scvi_model.train(max_epochs=200)
        
        model = scvi.model.SCANVI.from_scvi_model(
            scvi_model,
            labels_key=labels_key,
            unlabeled_category="Unknown"
        )
        model.train(max_epochs=50)
        rep_key = "X_scANVI"
    else:
        # Use scVI
        scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key=batch_key)
        model = scvi.model.SCVI(adata, n_latent=n_latent)
        model.train(max_epochs=200)
        rep_key = "X_scVI"
    
    # Add representation
    adata.obsm[rep_key] = model.get_latent_representation()
    
    # Compute neighbors and UMAP
    sc.pp.neighbors(adata, use_rep=rep_key)
    sc.tl.umap(adata)
    sc.tl.leiden(adata)
    
    return adata, model

# Usage
adatas = {
    "study1": sc.read_h5ad("study1.h5ad"),
    "study2": sc.read_h5ad("study2.h5ad"),
    "study3": sc.read_h5ad("study3.h5ad")
}

adata_integrated, model = integrate_datasets(
    adatas,
    labels_key="cell_type"
)

sc.pl.umap(adata_integrated, color=["batch", "leiden", "cell_type"])
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Batches not mixing | Too few shared genes | Use more HVGs, check gene overlap |
| Over-correction | Biological variation removed | Use scANVI with labels |
| Training diverges | Learning rate too high | Reduce lr, increase batch_size |
| NaN loss | Bad data | Check for all-zero cells/genes |
| Memory error | Too many cells | Reduce batch_size, use GPU |
