# Troubleshooting Guide for scvi-tools

This reference provides a consolidated guide for diagnosing and resolving common issues across all scvi-tools models.

## Quick Diagnosis

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| "X should contain integers" | Normalized data in X | Use `layer="counts"` in setup |
| CUDA out of memory | GPU memory exhausted | Reduce `batch_size`, use smaller model |
| Training loss is NaN | Bad data or learning rate | Check for all-zero cells/genes |
| Batches not mixing | Too few shared features | Increase HVGs, check gene overlap |
| Over-correction | Too aggressive integration | Use scANVI with labels |
| Import error | Missing dependencies | `pip install scvi-tools[all]` |

## Data Format Issues

### Issue: CITE-seq protein data from Seurat is CLR-normalized

**Cause**: Seurat's `NormalizeData(normalization.method = "CLR")` transforms raw ADT counts. totalVI requires raw integer counts for protein data.

**Symptoms**:
- Protein values are not integers
- Protein values contain negative numbers
- Model training produces poor results

**Solution**:
```python
# Check if protein data is normalized
protein = adata.obsm["protein_expression"]
print(f"Min value: {protein.min()}")  # Should be 0 if raw counts
print(f"Contains integers: {np.allclose(protein, protein.astype(int))}")

# If importing from Seurat, use the raw counts assay, not the normalized one
# In R/Seurat, export the RNA assay's counts slot, not the data slot
# GetAssayData(seurat_obj, assay = "ADT", slot = "counts")
```

### Issue: "layer not found" or "X should contain integers"

**Cause**: scvi-tools requires raw integer counts, not normalized data.

**Solution**:
```python
# Check if X contains integers
import numpy as np
print(f"X max: {adata.X.max()}")
print(f"Contains integers: {np.allclose(adata.X.data, adata.X.data.astype(int))}")

# If normalized, recover from raw
if hasattr(adata, 'raw') and adata.raw is not None:
    adata = adata.raw.to_adata()

# Or use existing counts layer
adata.layers["counts"] = adata.X.copy()
scvi.model.SCVI.setup_anndata(adata, layer="counts")
```

### Issue: Sparse matrix errors

**Cause**: Incompatible sparse format or dense array expected.

**Solution**:
```python
from scipy.sparse import csr_matrix

# Convert to CSR format (most compatible)
if hasattr(adata.X, 'toarray'):
    adata.X = csr_matrix(adata.X)

# Or convert to dense if small enough
if adata.n_obs * adata.n_vars < 1e8:
    adata.X = adata.X.toarray()
```

### Issue: NaN or Inf values in data

**Cause**: Missing values or corrupted data.

**Solution**:
```python
import numpy as np

# Check for issues
X = adata.X.toarray() if hasattr(adata.X, 'toarray') else adata.X
print(f"NaN count: {np.isnan(X).sum()}")
print(f"Inf count: {np.isinf(X).sum()}")
print(f"Negative count: {(X < 0).sum()}")

# Replace NaN/Inf with 0
X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)
X = np.clip(X, 0, None)  # Ensure non-negative
adata.X = csr_matrix(X)
```

### Issue: batch_key or labels_key not found

**Cause**: Column name mismatch in adata.obs.

**Solution**:
```python
# List available columns
print(adata.obs.columns.tolist())

# Check for similar names
for col in adata.obs.columns:
    if 'batch' in col.lower() or 'sample' in col.lower():
        print(f"Potential batch column: {col}")
```

## GPU and Memory Issues

### Issue: CUDA out of memory

**Cause**: Model or batch doesn't fit in GPU memory.

**Solutions** (try in order):

```python
# 1. Reduce batch size
model.train(batch_size=64)  # Default is 128

# 2. Use smaller model architecture
model = scvi.model.SCVI(
    adata,
    n_latent=10,   # Default is 10-30
    n_layers=1     # Default is 1-2
)

# 3. Subset to fewer genes
sc.pp.highly_variable_genes(adata, n_top_genes=1500)
adata = adata[:, adata.var['highly_variable']].copy()

# 4. Clear GPU cache between models
import torch
torch.cuda.empty_cache()

# 5. Use CPU if GPU is too small
model.train(accelerator="cpu")
```

### Issue: No GPU detected

**Cause**: CUDA not installed or version mismatch.

**Diagnosis**:
```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA version: {torch.version.cuda}")
```

**Solution**:
```bash
# Check system CUDA
nvidia-smi
nvcc --version

# Reinstall PyTorch with matching CUDA
pip install torch --index-url https://download.pytorch.org/whl/cu118  # For CUDA 11.8
# Or
pip install torch --index-url https://download.pytorch.org/whl/cu121  # For CUDA 12.1
```

### Issue: Memory error with large datasets

**Cause**: Dataset too large for system RAM.

**Solutions**:
```python
# 1. Process in chunks (for very large data)
# Subsample for initial exploration
adata_sample = adata[np.random.choice(adata.n_obs, 50000, replace=False)].copy()

# 2. Use backed mode for AnnData
adata = sc.read_h5ad("large_data.h5ad", backed='r')

# 3. Reduce gene count aggressively
adata = adata[:, adata.var['highly_variable']].copy()
```

## Training Issues

### Issue: Training loss is NaN

**Cause**: Numerical instability, bad data, or learning rate issues.

**Solutions**:
```python
# 1. Check for problematic cells/genes
sc.pp.filter_cells(adata, min_genes=200)
sc.pp.filter_genes(adata, min_cells=3)

# 2. Remove cells with zero counts
adata = adata[adata.X.sum(axis=1) > 0].copy()

# 3. Use gradient clipping (built into scvi-tools)
model.train(max_epochs=200, early_stopping=True)
```

### Issue: Training doesn't converge

**Cause**: Insufficient epochs, poor hyperparameters, or data issues.

**Solutions**:
```python
# 1. Train longer
model.train(max_epochs=400)

# 2. Check training curves
import matplotlib.pyplot as plt
plt.plot(model.history['elbo_train'])
plt.plot(model.history['elbo_validation'])
plt.xlabel('Epoch')
plt.ylabel('ELBO')
plt.legend(['Train', 'Validation'])

# 3. Adjust model size for data size
# Small data (<10k cells): smaller model
model = scvi.model.SCVI(adata, n_latent=10, n_layers=1, dropout_rate=0.2)

# Large data (>100k cells): can use larger model
model = scvi.model.SCVI(adata, n_latent=30, n_layers=2)
```

### Issue: Overfitting (validation loss increases)

**Cause**: Model too complex or trained too long.

**Solutions**:
```python
# 1. Enable early stopping
model.train(early_stopping=True, early_stopping_patience=10)

# 2. Add regularization
model = scvi.model.SCVI(adata, dropout_rate=0.2)

# 3. Reduce model complexity
model = scvi.model.SCVI(adata, n_layers=1)
```

## Integration Issues

### Issue: Batches don't mix

**Cause**: Too few shared features, strong biological differences, or technical issues.

**Solutions**:
```python
# 1. Check gene overlap between batches
for batch in adata.obs['batch'].unique():
    batch_genes = adata[adata.obs['batch'] == batch].var_names
    print(f"{batch}: {len(batch_genes)} genes")

# 2. Use more HVGs
sc.pp.highly_variable_genes(adata, n_top_genes=4000, batch_key="batch")

# 3. Train longer
model.train(max_epochs=400)

# 4. Increase latent dimensions
model = scvi.model.SCVI(adata, n_latent=50)
```

### Issue: Over-correction (biological signal lost)

**Cause**: Model removes too much variation.

**Solutions**:
```python
# 1. Use scANVI with cell type labels
scvi.model.SCANVI.from_scvi_model(scvi_model, labels_key="cell_type")

# 2. Reduce model capacity
model = scvi.model.SCVI(adata, n_latent=10)

# 3. Use categorical covariates instead of batch_key
scvi.model.SCVI.setup_anndata(
    adata,
    layer="counts",
    categorical_covariate_keys=["batch"]  # Less aggressive than batch_key
)
```

### Issue: One batch dominates clusters

**Cause**: Unbalanced batch sizes or incomplete integration.

**Solutions**:
```python
# 1. Check batch distribution
print(adata.obs['batch'].value_counts())

# 2. Subsample to balance
from sklearn.utils import resample
balanced = []
min_size = adata.obs['batch'].value_counts().min()
for batch in adata.obs['batch'].unique():
    batch_data = adata[adata.obs['batch'] == batch]
    balanced.append(batch_data[np.random.choice(len(batch_data), min_size, replace=False)])
adata_balanced = sc.concat(balanced)
```

## Model-Specific Issues

### scANVI: Poor label transfer

**Solutions**:
```python
# 1. Check label distribution
print(adata.obs['cell_type'].value_counts())

# 2. Use Unknown for low-confidence cells
adata.obs.loc[adata.obs['prediction_score'] < 0.5, 'cell_type'] = 'Unknown'

# 3. Train scVI longer before scANVI
scvi_model.train(max_epochs=300)
scanvi_model = scvi.model.SCANVI.from_scvi_model(scvi_model, labels_key="cell_type")
scanvi_model.train(max_epochs=100)
```

### totalVI: Noisy protein signal

**Solutions**:
```python
# 1. Use denoised protein values
_, protein_denoised = model.get_normalized_expression(return_mean=True)

# 2. Check isotype controls
# Isotype controls should have low expression
for i, name in enumerate(adata.uns["protein_names"]):
    if 'isotype' in name.lower():
        print(f"{name}: mean={adata.obsm['protein_expression'][:, i].mean():.1f}")
```

### PeakVI: Poor clustering

**Solutions**:
```python
# 1. Use more variable peaks
from sklearn.feature_selection import VarianceThreshold
selector = VarianceThreshold(threshold=0.05)
adata = adata[:, selector.fit(adata.X).get_support()].copy()

# 2. Binarize data
adata.X = (adata.X > 0).astype(np.float32)
```

### MultiVI: Different cell counts between modalities

**Solutions**:
```python
# Ensure same cells in same order
common_cells = adata_rna.obs_names.intersection(adata_atac.obs_names)
adata_rna = adata_rna[common_cells].copy()
adata_atac = adata_atac[common_cells].copy()
```

### DestVI: Poor deconvolution

**Solutions**:
```python
# 1. Check gene overlap
common_genes = adata_ref.var_names.intersection(adata_spatial.var_names)
print(f"Common genes: {len(common_genes)}")  # Should be >1000

# 2. Use tissue-matched reference
# Reference should contain all cell types expected in spatial data

# 3. Check reference quality
print(adata_ref.obs['cell_type'].value_counts())
```

## Version Compatibility

### scvi-tools 1.x vs 0.x API changes

Key differences:
```python
# 0.x API
scvi.data.setup_anndata(adata, ...)

# 1.x API (current)
scvi.model.SCVI.setup_anndata(adata, ...)
```

### Check versions
```python
import scvi
import scanpy as sc
import anndata
import torch

print(f"scvi-tools: {scvi.__version__}")
print(f"scanpy: {sc.__version__}")
print(f"anndata: {anndata.__version__}")
print(f"torch: {torch.__version__}")
```

### Recommended versions (as of late 2024)
```
scvi-tools>=1.0.0
scanpy>=1.9.0
anndata>=0.9.0
torch>=2.0.0
```

## Getting Help

1. **Check documentation**: https://docs.scvi-tools.org/
2. **GitHub issues**: https://github.com/scverse/scvi-tools/issues
3. **Discourse forum**: https://discourse.scverse.org/
4. **Tutorials**: https://docs.scvi-tools.org/en/stable/tutorials/index.html

When reporting issues, include:
- scvi-tools version (`scvi.__version__`)
- Python version
- Full error traceback
- Minimal reproducible example
