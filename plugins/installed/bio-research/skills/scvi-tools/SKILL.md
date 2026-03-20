---
name: scvi-tools
description: Deep learning for single-cell analysis using scvi-tools. This skill should be used when users need (1) data integration and batch correction with scVI/scANVI, (2) ATAC-seq analysis with PeakVI, (3) CITE-seq multi-modal analysis with totalVI, (4) multiome RNA+ATAC analysis with MultiVI, (5) spatial transcriptomics deconvolution with DestVI, (6) label transfer and reference mapping with scANVI/scArches, (7) RNA velocity with veloVI, or (8) any deep learning-based single-cell method. Triggers include mentions of scVI, scANVI, totalVI, PeakVI, MultiVI, DestVI, veloVI, sysVI, scArches, variational autoencoder, VAE, batch correction, data integration, multi-modal, CITE-seq, multiome, reference mapping, latent space.
---

# scvi-tools Deep Learning Skill

This skill provides guidance for deep learning-based single-cell analysis using scvi-tools, the leading framework for probabilistic models in single-cell genomics.

## How to Use This Skill

1. Identify the appropriate workflow from the model/workflow tables below
2. Read the corresponding reference file for detailed steps and code
3. Use scripts in `scripts/` to avoid rewriting common code
4. For installation or GPU issues, consult `references/environment_setup.md`
5. For debugging, consult `references/troubleshooting.md`

## When to Use This Skill

- When scvi-tools, scVI, scANVI, or related models are mentioned
- When deep learning-based batch correction or integration is needed
- When working with multi-modal data (CITE-seq, multiome)
- When reference mapping or label transfer is required
- When analyzing ATAC-seq or spatial transcriptomics data
- When learning latent representations of single-cell data

## Model Selection Guide

| Data Type | Model | Primary Use Case |
|-----------|-------|------------------|
| scRNA-seq | **scVI** | Unsupervised integration, DE, imputation |
| scRNA-seq + labels | **scANVI** | Label transfer, semi-supervised integration |
| CITE-seq (RNA+protein) | **totalVI** | Multi-modal integration, protein denoising |
| scATAC-seq | **PeakVI** | Chromatin accessibility analysis |
| Multiome (RNA+ATAC) | **MultiVI** | Joint modality analysis |
| Spatial + scRNA reference | **DestVI** | Cell type deconvolution |
| RNA velocity | **veloVI** | Transcriptional dynamics |
| Cross-technology | **sysVI** | System-level batch correction |

## Workflow Reference Files

| Workflow | Reference File | Description |
|----------|---------------|-------------|
| Environment Setup | `references/environment_setup.md` | Installation, GPU, version info |
| Data Preparation | `references/data_preparation.md` | Formatting data for any model |
| scRNA Integration | `references/scrna_integration.md` | scVI/scANVI batch correction |
| ATAC-seq Analysis | `references/atac_peakvi.md` | PeakVI for accessibility |
| CITE-seq Analysis | `references/citeseq_totalvi.md` | totalVI for protein+RNA |
| Multiome Analysis | `references/multiome_multivi.md` | MultiVI for RNA+ATAC |
| Spatial Deconvolution | `references/spatial_deconvolution.md` | DestVI spatial analysis |
| Label Transfer | `references/label_transfer.md` | scANVI reference mapping |
| scArches Mapping | `references/scarches_mapping.md` | Query-to-reference mapping |
| Batch Correction | `references/batch_correction_sysvi.md` | Advanced batch methods |
| RNA Velocity | `references/rna_velocity_velovi.md` | veloVI dynamics |
| Troubleshooting | `references/troubleshooting.md` | Common issues and solutions |

## CLI Scripts

Modular scripts for common workflows. Chain together or modify as needed.

### Pipeline Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `prepare_data.py` | QC, filter, HVG selection | `python scripts/prepare_data.py raw.h5ad prepared.h5ad --batch-key batch` |
| `train_model.py` | Train any scvi-tools model | `python scripts/train_model.py prepared.h5ad results/ --model scvi` |
| `cluster_embed.py` | Neighbors, UMAP, Leiden | `python scripts/cluster_embed.py adata.h5ad results/` |
| `differential_expression.py` | DE analysis | `python scripts/differential_expression.py model/ adata.h5ad de.csv --groupby leiden` |
| `transfer_labels.py` | Label transfer with scANVI | `python scripts/transfer_labels.py ref_model/ query.h5ad results/` |
| `integrate_datasets.py` | Multi-dataset integration | `python scripts/integrate_datasets.py results/ data1.h5ad data2.h5ad` |
| `validate_adata.py` | Check data compatibility | `python scripts/validate_adata.py data.h5ad --batch-key batch` |

### Example Workflow

```bash
# 1. Validate input data
python scripts/validate_adata.py raw.h5ad --batch-key batch --suggest

# 2. Prepare data (QC, HVG selection)
python scripts/prepare_data.py raw.h5ad prepared.h5ad --batch-key batch --n-hvgs 2000

# 3. Train model
python scripts/train_model.py prepared.h5ad results/ --model scvi --batch-key batch

# 4. Cluster and visualize
python scripts/cluster_embed.py results/adata_trained.h5ad results/ --resolution 0.8

# 5. Differential expression
python scripts/differential_expression.py results/model results/adata_clustered.h5ad results/de.csv --groupby leiden
```

### Python Utilities

The `scripts/model_utils.py` provides importable functions for custom workflows:

| Function | Purpose |
|----------|---------|
| `prepare_adata()` | Data preparation (QC, HVG, layer setup) |
| `train_scvi()` | Train scVI or scANVI |
| `evaluate_integration()` | Compute integration metrics |
| `get_marker_genes()` | Extract DE markers |
| `save_results()` | Save model, data, plots |
| `auto_select_model()` | Suggest best model |
| `quick_clustering()` | Neighbors + UMAP + Leiden |

## Critical Requirements

1. **Raw counts required**: scvi-tools models require integer count data
   ```python
   adata.layers["counts"] = adata.X.copy()  # Before normalization
   scvi.model.SCVI.setup_anndata(adata, layer="counts")
   ```

2. **HVG selection**: Use 2000-4000 highly variable genes
   ```python
   sc.pp.highly_variable_genes(adata, n_top_genes=2000, batch_key="batch", layer="counts", flavor="seurat_v3")
   adata = adata[:, adata.var['highly_variable']].copy()
   ```

3. **Batch information**: Specify batch_key for integration
   ```python
   scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
   ```

## Quick Decision Tree

```
Need to integrate scRNA-seq data?
├── Have cell type labels? → scANVI (references/label_transfer.md)
└── No labels? → scVI (references/scrna_integration.md)

Have multi-modal data?
├── CITE-seq (RNA + protein)? → totalVI (references/citeseq_totalvi.md)
├── Multiome (RNA + ATAC)? → MultiVI (references/multiome_multivi.md)
└── scATAC-seq only? → PeakVI (references/atac_peakvi.md)

Have spatial data?
└── Need cell type deconvolution? → DestVI (references/spatial_deconvolution.md)

Have pre-trained reference model?
└── Map query to reference? → scArches (references/scarches_mapping.md)

Need RNA velocity?
└── veloVI (references/rna_velocity_velovi.md)

Strong cross-technology batch effects?
└── sysVI (references/batch_correction_sysvi.md)
```

## Key Resources

- [scvi-tools Documentation](https://docs.scvi-tools.org/)
- [scvi-tools Tutorials](https://docs.scvi-tools.org/en/stable/tutorials/index.html)
- [Model Hub](https://huggingface.co/scvi-tools)
- [GitHub Issues](https://github.com/scverse/scvi-tools/issues)
