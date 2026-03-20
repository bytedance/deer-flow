#!/usr/bin/env python3
"""
Cluster and embed data using scvi-tools latent representation.

Computes neighbors, UMAP, and Leiden clustering on the latent space.
Input should have latent representation from train_model.py.

Usage:
    python cluster_embed.py input.h5ad output_dir/
    python cluster_embed.py input.h5ad output_dir/ --resolution 0.5 --use-rep X_scVI
"""

import argparse
import os
import sys


def cluster_and_embed(
    adata,
    use_rep=None,
    n_neighbors=15,
    resolution=1.0,
    min_dist=0.3
):
    """
    Cluster and compute UMAP embedding.

    Parameters
    ----------
    adata : AnnData
        Data with latent representation in obsm
    use_rep : str, optional
        Key in obsm to use (auto-detects if None)
    n_neighbors : int
        Number of neighbors for graph
    resolution : float
        Leiden clustering resolution
    min_dist : float
        UMAP min_dist parameter

    Returns
    -------
    AnnData with neighbors, UMAP, and leiden clustering
    """
    import scanpy as sc

    # Auto-detect representation
    if use_rep is None:
        candidates = ["X_scANVI", "X_scVI", "X_totalVI", "X_PeakVI", "X_MultiVI"]
        for key in candidates:
            if key in adata.obsm:
                use_rep = key
                break

        if use_rep is None:
            # Fall back to PCA
            if "X_pca" not in adata.obsm:
                print("No scvi-tools embedding found, computing PCA...")
                sc.pp.pca(adata)
            use_rep = "X_pca"

    print(f"Using representation: {use_rep}")
    print(f"Embedding shape: {adata.obsm[use_rep].shape}")

    # Compute neighbors
    print(f"Computing neighbors (n={n_neighbors})...")
    sc.pp.neighbors(adata, use_rep=use_rep, n_neighbors=n_neighbors)

    # UMAP
    print(f"Computing UMAP (min_dist={min_dist})...")
    sc.tl.umap(adata, min_dist=min_dist)

    # Leiden clustering
    print(f"Computing Leiden clustering (resolution={resolution})...")
    sc.tl.leiden(adata, resolution=resolution)

    n_clusters = adata.obs['leiden'].nunique()
    print(f"Found {n_clusters} clusters")

    return adata


def plot_results(adata, output_dir, batch_key=None, labels_key=None):
    """Generate and save visualization plots."""
    import scanpy as sc
    import matplotlib.pyplot as plt

    plots = []

    # Always plot clusters
    plots.append(("leiden", "Clusters"))

    # Plot batch if available
    if batch_key is not None and batch_key in adata.obs.columns:
        plots.append((batch_key, f"Batch ({batch_key})"))

    # Plot labels if available
    if labels_key is not None and labels_key in adata.obs.columns:
        plots.append((labels_key, f"Labels ({labels_key})"))

    # Check for common columns
    for col in adata.obs.columns:
        if col not in [p[0] for p in plots]:
            if 'cell' in col.lower() and 'type' in col.lower():
                plots.append((col, col))
            elif 'predict' in col.lower():
                plots.append((col, col))

    # Limit to 6 plots
    plots = plots[:6]

    # Create figure
    n_plots = len(plots)
    n_cols = min(3, n_plots)
    n_rows = (n_plots + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
    if n_plots == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    for i, (color, title) in enumerate(plots):
        try:
            sc.pl.umap(adata, color=color, ax=axes[i], show=False, title=title)
        except Exception as e:
            axes[i].set_title(f"Could not plot {color}: {e}")

    # Hide unused axes
    for i in range(len(plots), len(axes)):
        axes[i].set_visible(False)

    plt.tight_layout()

    plot_path = os.path.join(output_dir, "umap_clusters.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"UMAP plot saved to {plot_path}")

    # Save cluster counts
    cluster_counts = adata.obs['leiden'].value_counts().sort_index()
    counts_path = os.path.join(output_dir, "cluster_counts.csv")
    cluster_counts.to_csv(counts_path)
    print(f"Cluster counts saved to {counts_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Cluster and embed using scvi-tools latent space",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic clustering
    python cluster_embed.py adata_trained.h5ad results/

    # Custom resolution
    python cluster_embed.py adata_trained.h5ad results/ --resolution 0.5

    # Specify representation
    python cluster_embed.py adata_trained.h5ad results/ --use-rep X_scANVI

    # Include batch and label columns in plots
    python cluster_embed.py adata_trained.h5ad results/ --batch-key batch --labels-key cell_type
        """
    )
    parser.add_argument("input", help="Input h5ad file with latent representation")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument("--use-rep", help="Representation key in obsm (auto-detects)")
    parser.add_argument("--n-neighbors", type=int, default=15, help="Neighbors for graph (default: 15)")
    parser.add_argument("--resolution", type=float, default=1.0, help="Leiden resolution (default: 1.0)")
    parser.add_argument("--min-dist", type=float, default=0.3, help="UMAP min_dist (default: 0.3)")
    parser.add_argument("--batch-key", help="Batch column for plotting")
    parser.add_argument("--labels-key", help="Labels column for plotting")

    args = parser.parse_args()

    try:
        import scanpy as sc
    except ImportError:
        print("Error: scanpy required. Install with: pip install scanpy")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Load data
    print(f"Loading {args.input}...")
    adata = sc.read_h5ad(args.input)
    print(f"Data: {adata.shape}")

    # Cluster and embed
    adata = cluster_and_embed(
        adata,
        use_rep=args.use_rep,
        n_neighbors=args.n_neighbors,
        resolution=args.resolution,
        min_dist=args.min_dist
    )

    # Save results
    adata_path = os.path.join(args.output_dir, "adata_clustered.h5ad")
    adata.write_h5ad(adata_path)
    print(f"AnnData saved to {adata_path}")

    # Plot
    plot_results(adata, args.output_dir, args.batch_key, args.labels_key)

    print("\nDone!")


if __name__ == "__main__":
    main()
