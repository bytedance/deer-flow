#!/usr/bin/env python3
"""
Integrate multiple datasets using scvi-tools.

Concatenates multiple h5ad files and runs batch correction with scVI or scANVI.

Usage:
    python integrate_datasets.py output_dir/ dataset1.h5ad dataset2.h5ad dataset3.h5ad
    python integrate_datasets.py output_dir/ *.h5ad --batch-names study1,study2,study3
"""

import argparse
import os
import sys


def integrate_datasets(
    adatas,
    batch_names=None,
    labels_key=None,
    n_top_genes=2000,
    n_latent=30,
    max_epochs=200
):
    """
    Integrate multiple datasets.

    Parameters
    ----------
    adatas : list of AnnData
        Datasets to integrate
    batch_names : list of str, optional
        Names for each dataset (default: dataset_0, dataset_1, ...)
    labels_key : str, optional
        Cell type column (uses scANVI if provided)
    n_top_genes : int
        Number of HVGs
    n_latent : int
        Latent dimensions
    max_epochs : int
        Training epochs

    Returns
    -------
    Integrated AnnData and trained model
    """
    import scvi
    import scanpy as sc
    import numpy as np

    # Assign batch names
    if batch_names is None:
        batch_names = [f"dataset_{i}" for i in range(len(adatas))]

    if len(batch_names) != len(adatas):
        raise ValueError(f"Number of batch names ({len(batch_names)}) must match datasets ({len(adatas)})")

    # Add batch labels
    for adata, name in zip(adatas, batch_names):
        adata.obs["batch"] = name
        print(f"{name}: {adata.shape}")

    # Find common genes
    common_genes = set(adatas[0].var_names)
    for adata in adatas[1:]:
        common_genes = common_genes.intersection(adata.var_names)
    common_genes = list(common_genes)
    print(f"\nCommon genes: {len(common_genes)}")

    # Subset to common genes
    adatas = [adata[:, common_genes].copy() for adata in adatas]

    # Concatenate
    print("Concatenating datasets...")
    adata = sc.concat(adatas, label="batch", keys=batch_names)
    print(f"Combined: {adata.shape}")

    # Store counts
    adata.layers["counts"] = adata.X.copy()

    # HVG selection
    print(f"Selecting {n_top_genes} HVGs...")
    sc.pp.highly_variable_genes(
        adata,
        n_top_genes=n_top_genes,
        flavor="seurat_v3",
        batch_key="batch",
        layer="counts"
    )
    adata = adata[:, adata.var["highly_variable"]].copy()

    # Train model
    if labels_key is not None and labels_key in adata.obs.columns:
        print(f"\nTraining scANVI with labels ({labels_key})...")

        # First train scVI
        scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
        scvi_model = scvi.model.SCVI(adata, n_latent=n_latent)
        scvi_model.train(max_epochs=max_epochs, early_stopping=True)

        # Then scANVI
        model = scvi.model.SCANVI.from_scvi_model(
            scvi_model,
            labels_key=labels_key,
            unlabeled_category="Unknown"
        )
        model.train(max_epochs=max_epochs // 4)

        adata.obsm["X_scANVI"] = model.get_latent_representation()
        rep_key = "X_scANVI"

    else:
        print("\nTraining scVI...")
        scvi.model.SCVI.setup_anndata(adata, layer="counts", batch_key="batch")
        model = scvi.model.SCVI(adata, n_latent=n_latent)
        model.train(max_epochs=max_epochs, early_stopping=True)

        adata.obsm["X_scVI"] = model.get_latent_representation()
        rep_key = "X_scVI"

    # Cluster
    print("\nClustering...")
    sc.pp.neighbors(adata, use_rep=rep_key)
    sc.tl.umap(adata)
    sc.tl.leiden(adata)

    print(f"Found {adata.obs['leiden'].nunique()} clusters")

    return adata, model


def plot_integration(adata, output_dir, labels_key=None):
    """Plot integration results."""
    import scanpy as sc
    import matplotlib.pyplot as plt

    plots = [
        ("batch", "By Batch"),
        ("leiden", "Clusters")
    ]

    if labels_key is not None and labels_key in adata.obs.columns:
        plots.append((labels_key, f"Cell Types ({labels_key})"))

    if "predicted_cell_type" in adata.obs.columns:
        plots.append(("predicted_cell_type", "Predicted Types"))

    n_plots = len(plots)
    fig, axes = plt.subplots(1, n_plots, figsize=(5 * n_plots, 4))
    if n_plots == 1:
        axes = [axes]

    for ax, (color, title) in zip(axes, plots):
        sc.pl.umap(adata, color=color, ax=ax, show=False, title=title)

    plt.tight_layout()
    plot_path = os.path.join(output_dir, "integration.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Integration plot saved to {plot_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Integrate multiple datasets with scvi-tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Integrate multiple files
    python integrate_datasets.py results/ data1.h5ad data2.h5ad data3.h5ad

    # With custom batch names
    python integrate_datasets.py results/ *.h5ad --batch-names ctrl,treat1,treat2

    # With cell type labels (uses scANVI)
    python integrate_datasets.py results/ *.h5ad --labels-key cell_type
        """
    )
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument("inputs", nargs="+", help="Input h5ad files")
    parser.add_argument("--batch-names", help="Comma-separated batch names")
    parser.add_argument("--labels-key", help="Cell type column (uses scANVI)")
    parser.add_argument("--n-hvgs", type=int, default=2000, help="Number of HVGs (default: 2000)")
    parser.add_argument("--n-latent", type=int, default=30, help="Latent dimensions (default: 30)")
    parser.add_argument("--max-epochs", type=int, default=200, help="Max epochs (default: 200)")

    args = parser.parse_args()

    try:
        import scvi
        import scanpy as sc
    except ImportError:
        print("Error: scvi-tools and scanpy required")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Parse batch names
    batch_names = None
    if args.batch_names:
        batch_names = args.batch_names.split(",")

    # Load datasets
    print("Loading datasets...")
    adatas = []
    for path in args.inputs:
        print(f"  Loading {path}...")
        adatas.append(sc.read_h5ad(path))

    # Integrate
    adata, model = integrate_datasets(
        adatas,
        batch_names=batch_names,
        labels_key=args.labels_key,
        n_top_genes=args.n_hvgs,
        n_latent=args.n_latent,
        max_epochs=args.max_epochs
    )

    # Save results
    adata_path = os.path.join(args.output_dir, "integrated.h5ad")
    adata.write_h5ad(adata_path)
    print(f"\nIntegrated data saved to {adata_path}")

    model_path = os.path.join(args.output_dir, "model")
    model.save(model_path)
    print(f"Model saved to {model_path}")

    # Plot
    plot_integration(adata, args.output_dir, args.labels_key)

    print("\nDone!")


if __name__ == "__main__":
    main()
