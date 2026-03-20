# Environment Setup for scvi-tools

This reference covers installation and environment configuration for scvi-tools.

## Installation Options

### Option 1: Conda Environment (Recommended)

```bash
# Create environment with GPU support
conda create -n scvi-env python=3.10
conda activate scvi-env

# Install scvi-tools
pip install scvi-tools

# For GPU acceleration (recommended for large datasets)
pip install torch --index-url https://download.pytorch.org/whl/cu118

# Common dependencies
pip install scanpy leidenalg
```

### Option 2: Pip Only

```bash
# Create virtual environment
python -m venv scvi-env
source scvi-env/bin/activate  # Linux/Mac
# scvi-env\Scripts\activate   # Windows

# Install
pip install scvi-tools scanpy
```

### Option 3: With Spatial Analysis Support

```bash
conda create -n scvi-spatial python=3.10
conda activate scvi-spatial

pip install scvi-tools scanpy squidpy
```

### Option 4: With MuData Support (Multiome)

```bash
pip install scvi-tools mudata muon
```

## Verify Installation

```python
import scvi
import torch
import scanpy as sc

print(f"scvi-tools version: {scvi.__version__}")
print(f"scanpy version: {sc.__version__}")
print(f"PyTorch version: {torch.__version__}")
print(f"GPU available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"GPU device: {torch.cuda.get_device_name(0)}")
    print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
```

## GPU Configuration

### Check CUDA Version

```bash
nvidia-smi
nvcc --version
```

### PyTorch CUDA Versions

| CUDA Version | PyTorch Install Command |
|--------------|------------------------|
| CUDA 11.8 | `pip install torch --index-url https://download.pytorch.org/whl/cu118` |
| CUDA 12.1 | `pip install torch --index-url https://download.pytorch.org/whl/cu121` |
| CPU only | `pip install torch --index-url https://download.pytorch.org/whl/cpu` |

### Memory Management

```python
import torch

# Clear GPU cache between models
torch.cuda.empty_cache()

# Monitor memory usage
print(f"Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
print(f"Cached: {torch.cuda.memory_reserved() / 1e9:.2f} GB")
```

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `CUDA out of memory` | GPU memory exhausted | Reduce batch_size, use smaller model |
| `No GPU detected` | CUDA not installed | Install CUDA toolkit matching PyTorch |
| `Version mismatch` | PyTorch/CUDA incompatibility | Reinstall PyTorch with correct CUDA version |
| `Import error scvi` | Missing dependencies | `pip install scvi-tools[all]` |

## Jupyter Setup

```bash
# Install Jupyter kernel
pip install ipykernel
python -m ipykernel install --user --name scvi-env --display-name "scvi-tools"

# For interactive plots
pip install matplotlib seaborn
```

## Recommended Package Versions

For reproducibility, pin versions:

```bash
pip install \
    scvi-tools>=1.0.0 \
    scanpy>=1.9.0 \
    anndata>=0.9.0 \
    torch>=2.0.0
```

## Version Compatibility Guide

### scvi-tools 1.x vs 0.x API Changes

The 1.x release introduced breaking changes. Key differences:

| Operation | 0.x API (deprecated) | 1.x API (current) |
|-----------|---------------------|-------------------|
| Setup data | `scvi.data.setup_anndata(adata, ...)` | `scvi.model.SCVI.setup_anndata(adata, ...)` |
| Register data | `scvi.data.register_tensor_from_anndata(...)` | Built into `setup_anndata` |
| View setup | `scvi.data.view_anndata_setup(adata)` | `scvi.model.SCVI.view_anndata_setup(adata)` |

### Migration from 0.x to 1.x

```python
# OLD (0.x) - DEPRECATED
import scvi
scvi.data.setup_anndata(adata, layer="counts", batch_key="batch")
model = scvi.model.SCVI(adata)

# NEW (1.x) - CURRENT
import scvi
scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
model = scvi.model.SCVI(adata)
```

### Model-Specific Setup (1.x)

Each model has its own setup method:

```python
# scVI
scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")

# scANVI
scvi.model.SCANVI.setup_anndata(adata, layer="counts", batch_key="batch", labels_key="cell_type")

# totalVI
scvi.model.TOTALVI.setup_anndata(adata, layer="counts", protein_expression_obsm_key="protein")

# MultiVI (uses MuData)
scvi.model.MULTIVI.setup_mudata(mdata, rna_layer="counts", atac_layer="counts")

# PeakVI
scvi.model.PEAKVI.setup_anndata(adata, batch_key="batch")

# veloVI
scvi.external.VELOVI.setup_anndata(adata, spliced_layer="spliced", unspliced_layer="unspliced")
```

### Minimum Version Requirements

| Package | Minimum Version | Notes |
|---------|-----------------|-------|
| scvi-tools | 1.0.0 | Required for current API |
| scanpy | 1.9.0 | HVG selection improvements |
| anndata | 0.9.0 | Improved MuData support |
| torch | 2.0.0 | Performance improvements |
| mudata | 0.2.0 | Required for MultiVI |
| scvelo | 0.2.5 | Required for veloVI |

### Check Your Versions

```python
import scvi
import scanpy as sc
import anndata
import torch

print(f"scvi-tools: {scvi.__version__}")
print(f"scanpy: {sc.__version__}")
print(f"anndata: {anndata.__version__}")
print(f"torch: {torch.__version__}")

# Check if using 1.x API
if hasattr(scvi.model.SCVI, 'setup_anndata'):
    print("Using scvi-tools 1.x API")
else:
    print("WARNING: Using deprecated 0.x API - please upgrade")
```

### Known Compatibility Issues

| Issue | Affected Versions | Solution |
|-------|-------------------|----------|
| `setup_anndata` not found | scvi-tools < 1.0 | Upgrade to 1.0+ |
| MuData errors | mudata < 0.2 | `pip install mudata>=0.2.0` |
| CUDA version mismatch | Any | Reinstall PyTorch for your CUDA |
| numpy 2.0 issues | Early 2024 builds | `pip install numpy<2.0` |

### Upgrading scvi-tools

```bash
# Upgrade to latest
pip install --upgrade scvi-tools

# Upgrade all dependencies
pip install --upgrade scvi-tools scanpy anndata torch

# If you have issues, clean install
pip uninstall scvi-tools
pip cache purge
pip install scvi-tools
```

## Testing Installation

```python
# Quick test with sample data
import scvi
import scanpy as sc

# Load test dataset
adata = scvi.data.heart_cell_atlas_subsampled()
print(f"Loaded test data: {adata.shape}")

# Setup and create model (quick test)
scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="cell_source")
model = scvi.model.SCVI(adata, n_latent=10)
print("Model created successfully")

# Quick training test (1 epoch)
model.train(max_epochs=1)
print("Training works!")
```
