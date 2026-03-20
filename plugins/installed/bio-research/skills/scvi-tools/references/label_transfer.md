# Label Transfer and Reference Mapping with scANVI

This reference covers using scANVI for transferring cell type annotations from a reference atlas to query data.

## Overview

Reference mapping (also called "label transfer") uses a pre-trained model on annotated reference data to predict cell types in new, unannotated query data. This is faster than re-clustering and more consistent across studies.

scANVI excels at this because it:
- Jointly embeds reference and query in shared space
- Transfers labels probabilistically
- Handles batch effects between reference and query

## When to Use Reference Mapping

- Annotating new dataset using existing atlas
- Consistent annotation across multiple studies
- Speed: no need to re-cluster and manually annotate
- Quality: leverage expert-curated reference annotations

## Workflow Options

1. **Train new model**: Train scANVI on reference, then map query
2. **Use pre-trained model**: Load existing model (e.g., from Model Hub)
3. **scArches**: Extend existing model with query data (preserves reference)

## Option 1: Train scANVI on Reference

### Step 1: Prepare Reference Data

```python
import scvi
import scanpy as sc

# Load reference atlas
adata_ref = sc.read_h5ad("reference_atlas.h5ad")

# Check annotations
print(f"Reference cells: {adata_ref.n_obs}")
print(f"Cell types: {adata_ref.obs['cell_type'].nunique()}")
print(adata_ref.obs['cell_type'].value_counts())

# Ensure raw counts
adata_ref.layers["counts"] = adata_ref.raw.X.copy() if adata_ref.raw else adata_ref.X.copy()

# HVG selection
sc.pp.highly_variable_genes(
    adata_ref,
    n_top_genes=3000,
    flavor="seurat_v3",
    batch_key="batch" if "batch" in adata_ref.obs else None,
    layer="counts"
)
adata_ref = adata_ref[:, adata_ref.var["highly_variable"]].copy()
```

### Step 2: Train scANVI on Reference

```python
# First train scVI (unlabeled)
scvi.model.SCVI.setup_anndata(
    adata_ref,
    layer="counts",
    batch_key="batch"
)

scvi_ref = scvi.model.SCVI(adata_ref, n_latent=30)
scvi_ref.train(max_epochs=200)

# Initialize scANVI from scVI
scanvi_ref = scvi.model.SCANVI.from_scvi_model(
    scvi_ref,
    labels_key="cell_type",
    unlabeled_category="Unknown"
)

# Train scANVI
scanvi_ref.train(max_epochs=50)

# Save for later use
scanvi_ref.save("scanvi_reference_model/")
```

### Step 3: Prepare Query Data

```python
# Load query data
adata_query = sc.read_h5ad("query_data.h5ad")

# CRITICAL: Use same genes as reference
common_genes = adata_ref.var_names.intersection(adata_query.var_names)
print(f"Common genes: {len(common_genes)}")

# Subset query to reference genes
adata_query = adata_query[:, adata_ref.var_names].copy()

# Handle missing genes (set to 0)
missing_genes = set(adata_ref.var_names) - set(adata_query.var_names)
if missing_genes:
    # Add missing genes with zero expression
    import numpy as np
    from scipy.sparse import csr_matrix
    
    zero_matrix = csr_matrix((adata_query.n_obs, len(missing_genes)))
    # ... concat and reorder to match reference
    
# Store counts
adata_query.layers["counts"] = adata_query.X.copy()
```

### Step 4: Map Query to Reference

```python
# Prepare query data for mapping
scvi.model.SCANVI.prepare_query_anndata(adata_query, scanvi_ref)

# Create query model from reference
scanvi_query = scvi.model.SCANVI.load_query_data(
    adata_query,
    scanvi_ref
)

# Fine-tune on query (optional but recommended)
scanvi_query.train(
    max_epochs=100,
    plan_kwargs={"weight_decay": 0.0}
)

# Get predictions
adata_query.obs["predicted_cell_type"] = scanvi_query.predict()

# Get prediction probabilities
soft_predictions = scanvi_query.predict(soft=True)
adata_query.obs["prediction_score"] = soft_predictions.max(axis=1)
```

### Step 5: Evaluate Predictions

```python
# Confidence scores
print(f"Mean prediction confidence: {adata_query.obs['prediction_score'].mean():.3f}")

# Low confidence predictions
low_conf = adata_query.obs['prediction_score'] < 0.5
print(f"Low confidence cells: {low_conf.sum()} ({low_conf.mean()*100:.1f}%)")

# Visualize
sc.pp.neighbors(adata_query, use_rep="X_scANVI")
sc.tl.umap(adata_query)
sc.pl.umap(adata_query, color=['predicted_cell_type', 'prediction_score'])
```

## Option 2: Use Pre-Trained Models

### From Model Hub

```python
# scvi-tools maintains models on HuggingFace
# Check: https://huggingface.co/scvi-tools

# Example: Load pre-trained model
from huggingface_hub import hf_hub_download

model_path = hf_hub_download(
    repo_id="scvi-tools/example-model",
    filename="model.pt"
)

# Load model
model = scvi.model.SCANVI.load(model_path, adata=adata_query)
```

### From Published Atlas

```python
# Many atlases provide pre-trained models
# Example workflow with CellTypist-style model

# Download reference model
# model = scvi.model.SCANVI.load("atlas_model/", adata=adata_query)
```

## Option 3: scArches for Incremental Updates

scArches extends a reference model without retraining from scratch:

```python
# Load existing reference model
scanvi_ref = scvi.model.SCANVI.load("reference_model/")

# Surgery: prepare for query integration
scanvi_ref.freeze_layers()

# Map query data
scvi.model.SCANVI.prepare_query_anndata(adata_query, scanvi_ref)
scanvi_query = scvi.model.SCANVI.load_query_data(adata_query, scanvi_ref)

# Train only query-specific parameters
scanvi_query.train(
    max_epochs=200,
    plan_kwargs={"weight_decay": 0.0}
)
```

## Visualize Reference and Query Together

```python
# Concatenate for joint visualization
adata_ref.obs["dataset"] = "reference"
adata_query.obs["dataset"] = "query"

# Get latent representations
adata_ref.obsm["X_scANVI"] = scanvi_ref.get_latent_representation()
adata_query.obsm["X_scANVI"] = scanvi_query.get_latent_representation()

# Combine
adata_combined = sc.concat([adata_ref, adata_query])

# Compute combined UMAP
sc.pp.neighbors(adata_combined, use_rep="X_scANVI")
sc.tl.umap(adata_combined)

# Plot
sc.pl.umap(
    adata_combined,
    color=["dataset", "cell_type", "predicted_cell_type"],
    ncols=2
)
```

## Quality Control for Predictions

### Confidence Filtering

```python
# Filter predictions by confidence
confidence_threshold = 0.7

high_conf = adata_query[adata_query.obs['prediction_score'] >= confidence_threshold].copy()
low_conf = adata_query[adata_query.obs['prediction_score'] < confidence_threshold].copy()

print(f"High confidence: {len(high_conf)} ({len(high_conf)/len(adata_query)*100:.1f}%)")
print(f"Low confidence: {len(low_conf)} ({len(low_conf)/len(adata_query)*100:.1f}%)")
```

### Marker Validation

```python
# Validate predictions with known markers
markers = {
    'T cells': ['CD3D', 'CD3E'],
    'B cells': ['CD19', 'MS4A1'],
    'Monocytes': ['CD14', 'LYZ']
}

for ct, genes in markers.items():
    ct_cells = adata_query[adata_query.obs['predicted_cell_type'] == ct]
    if len(ct_cells) > 0:
        for gene in genes:
            if gene in adata_query.var_names:
                expr = ct_cells[:, gene].X.mean()
                print(f"{ct} - {gene}: {expr:.3f}")
```

## Complete Pipeline

```python
def transfer_labels(
    adata_ref,
    adata_query,
    cell_type_key="cell_type",
    batch_key=None,
    n_top_genes=3000,
    confidence_threshold=0.5
):
    """
    Transfer cell type labels from reference to query.
    
    Parameters
    ----------
    adata_ref : AnnData
        Annotated reference data
    adata_query : AnnData
        Unannotated query data
    cell_type_key : str
        Column with cell type annotations in reference
    batch_key : str, optional
        Batch column
    n_top_genes : int
        Number of HVGs
    confidence_threshold : float
        Minimum confidence for predictions
        
    Returns
    -------
    AnnData with predictions
    """
    import scvi
    import scanpy as sc
    
    # Prepare reference
    adata_ref = adata_ref.copy()
    adata_ref.layers["counts"] = adata_ref.X.copy()
    
    sc.pp.highly_variable_genes(
        adata_ref,
        n_top_genes=n_top_genes,
        flavor="seurat_v3",
        batch_key=batch_key,
        layer="counts"
    )
    adata_ref = adata_ref[:, adata_ref.var["highly_variable"]].copy()
    
    # Train reference model
    scvi.model.SCVI.setup_anndata(adata_ref, layer="counts", batch_key=batch_key)
    scvi_ref = scvi.model.SCVI(adata_ref, n_latent=30)
    scvi_ref.train(max_epochs=200)
    
    scanvi_ref = scvi.model.SCANVI.from_scvi_model(
        scvi_ref,
        labels_key=cell_type_key,
        unlabeled_category="Unknown"
    )
    scanvi_ref.train(max_epochs=50)
    
    # Prepare query
    adata_query = adata_query[:, adata_ref.var_names].copy()
    adata_query.layers["counts"] = adata_query.X.copy()
    
    # Map query
    scvi.model.SCANVI.prepare_query_anndata(adata_query, scanvi_ref)
    scanvi_query = scvi.model.SCANVI.load_query_data(adata_query, scanvi_ref)
    scanvi_query.train(max_epochs=100, plan_kwargs={"weight_decay": 0.0})
    
    # Get predictions
    adata_query.obs["predicted_cell_type"] = scanvi_query.predict()
    soft = scanvi_query.predict(soft=True)
    adata_query.obs["prediction_score"] = soft.max(axis=1)
    
    # Mark low confidence
    adata_query.obs["confident_prediction"] = adata_query.obs["prediction_score"] >= confidence_threshold
    
    # Add latent representation
    adata_query.obsm["X_scANVI"] = scanvi_query.get_latent_representation()
    
    return adata_query, scanvi_ref, scanvi_query

# Usage
adata_annotated, ref_model, query_model = transfer_labels(
    adata_ref,
    adata_query,
    cell_type_key="cell_type"
)

# Visualize
sc.pp.neighbors(adata_annotated, use_rep="X_scANVI")
sc.tl.umap(adata_annotated)
sc.pl.umap(adata_annotated, color=['predicted_cell_type', 'prediction_score'])
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Many low-confidence predictions | Query has novel cell types | Manually annotate low-confidence cells |
| Wrong predictions | Reference doesn't match tissue | Use tissue-appropriate reference |
| Gene mismatch | Different gene naming | Convert gene IDs |
| All same prediction | Query too different | Check data quality, try different reference |

## Key References

- Xu et al. (2021) "Probabilistic harmonization and annotation of single-cell transcriptomics data with deep generative models"
- Lotfollahi et al. (2022) "Mapping single-cell data to reference atlases by transfer learning"
