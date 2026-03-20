#!/usr/bin/env python3
"""
Utility functions for scvi-tools model training and evaluation.

Usage:
    from model_utils import prepare_adata, train_scvi, evaluate_integration
"""

import numpy as np
import scanpy as sc
from typing import Optional, List, Dict, Tuple
import warnings


def get_mito_genes(adata) -> np.ndarray:
    """
    Identify mitochondrial genes for both human and mouse data.

    Handles common prefixes:
    - Human: MT- (e.g., MT-CO1, MT-ND1)
    - Mouse: mt- or Mt- (e.g., mt-Co1, Mt-Nd1)

    Returns
    -------
    Boolean array indicating mitochondrial genes
    """
    return (
        adata.var_names.str.startswith('MT-') |
        adata.var_names.str.startswith('mt-') |
        adata.var_names.str.startswith('Mt-')
    )


def prepare_adata(
    adata,
    batch_key: Optional[str] = None,
    n_top_genes: int = 2000,
    min_genes: int = 200,
    max_genes: int = 5000,
    max_mito_pct: float = 20.0,
    min_cells: int = 3,
    copy: bool = True
):
    """
    Prepare AnnData for scvi-tools models.
    
    Parameters
    ----------
    adata : AnnData
        Raw count data
    batch_key : str, optional
        Column for batch information
    n_top_genes : int
        Number of highly variable genes
    min_genes : int
        Minimum genes per cell
    max_genes : int
        Maximum genes per cell
    max_mito_pct : float
        Maximum mitochondrial percentage
    min_cells : int
        Minimum cells per gene
    copy : bool
        Return copy of data
        
    Returns
    -------
    AnnData prepared for scvi-tools
    """
    if copy:
        adata = adata.copy()
    
    # Calculate QC metrics
    adata.var['mt'] = get_mito_genes(adata)
    sc.pp.calculate_qc_metrics(adata, qc_vars=['mt'], inplace=True)
    
    # Filter cells
    adata = adata[adata.obs['n_genes_by_counts'] >= min_genes].copy()
    adata = adata[adata.obs['n_genes_by_counts'] <= max_genes].copy()
    adata = adata[adata.obs['pct_counts_mt'] < max_mito_pct].copy()
    
    # Filter genes
    sc.pp.filter_genes(adata, min_cells=min_cells)
    
    # Store raw counts
    adata.layers["counts"] = adata.X.copy()
    
    # HVG selection
    if batch_key and batch_key in adata.obs.columns:
        sc.pp.highly_variable_genes(
            adata,
            n_top_genes=n_top_genes,
            flavor="seurat_v3",
            batch_key=batch_key,
            layer="counts"
        )
    else:
        # Need to normalize for non-seurat_v3 flavor
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        sc.pp.highly_variable_genes(adata, n_top_genes=n_top_genes)
        # Restore counts to X
        adata.X = adata.layers["counts"].copy()
    
    # Subset to HVGs
    adata = adata[:, adata.var['highly_variable']].copy()
    
    print(f"Prepared AnnData: {adata.shape}")
    if batch_key:
        print(f"Batches: {adata.obs[batch_key].nunique()}")
    
    return adata


def train_scvi(
    adata,
    batch_key: Optional[str] = None,
    labels_key: Optional[str] = None,
    n_latent: int = 30,
    n_layers: int = 2,
    max_epochs: int = 200,
    early_stopping: bool = True,
    use_gpu: bool = True
):
    """
    Train scVI or scANVI model.
    
    Parameters
    ----------
    adata : AnnData
        Prepared data with counts layer
    batch_key : str, optional
        Batch column
    labels_key : str, optional
        Cell type labels (uses scANVI if provided)
    n_latent : int
        Latent dimensions
    n_layers : int
        Encoder/decoder layers
    max_epochs : int
        Maximum training epochs
    early_stopping : bool
        Use early stopping
    use_gpu : bool
        Use GPU if available
        
    Returns
    -------
    Trained model
    """
    import scvi
    
    # Setup AnnData
    scvi.model.SCVI.setup_anndata(
        adata,
        layer="counts",
        batch_key=batch_key
    )
    
    if labels_key and labels_key in adata.obs.columns:
        # Train scVI first
        scvi_model = scvi.model.SCVI(
            adata,
            n_latent=n_latent,
            n_layers=n_layers
        )
        scvi_model.train(
            max_epochs=max_epochs,
            early_stopping=early_stopping
        )
        
        # Initialize scANVI
        model = scvi.model.SCANVI.from_scvi_model(
            scvi_model,
            labels_key=labels_key,
            unlabeled_category="Unknown"
        )
        model.train(max_epochs=max_epochs // 4)
        
        # Store representation
        adata.obsm["X_scANVI"] = model.get_latent_representation()
    else:
        # Train scVI only
        model = scvi.model.SCVI(
            adata,
            n_latent=n_latent,
            n_layers=n_layers
        )
        model.train(
            max_epochs=max_epochs,
            early_stopping=early_stopping
        )
        
        # Store representation
        adata.obsm["X_scVI"] = model.get_latent_representation()
    
    return model


def evaluate_integration(
    adata,
    batch_key: str,
    label_key: str,
    embedding_key: str = "X_scVI"
) -> Dict[str, float]:
    """
    Evaluate integration quality using basic metrics.
    
    Parameters
    ----------
    adata : AnnData
        Integrated data
    batch_key : str
        Batch column
    label_key : str
        Cell type column
    embedding_key : str
        Key in obsm for embedding
        
    Returns
    -------
    Dictionary of metrics
    """
    from sklearn.metrics import silhouette_score
    from sklearn.neighbors import NearestNeighbors
    
    X = adata.obsm[embedding_key]
    batch = adata.obs[batch_key].values
    labels = adata.obs[label_key].values
    
    metrics = {}
    
    # Silhouette scores
    try:
        # Cell type silhouette (higher = better separation)
        metrics["silhouette_label"] = silhouette_score(X, labels)
        
        # Batch silhouette (lower = better mixing)
        metrics["silhouette_batch"] = silhouette_score(X, batch)
    except Exception as e:
        warnings.warn(f"Silhouette calculation failed: {e}")
    
    # Batch mixing in neighbors
    try:
        nn = NearestNeighbors(n_neighbors=50)
        nn.fit(X)
        distances, indices = nn.kneighbors(X)
        
        batch_mixing = []
        for i in range(len(X)):
            neighbor_batches = batch[indices[i]]
            unique_batches = len(np.unique(neighbor_batches))
            batch_mixing.append(unique_batches / len(np.unique(batch)))
        
        metrics["batch_mixing"] = np.mean(batch_mixing)
    except Exception as e:
        warnings.warn(f"Batch mixing calculation failed: {e}")
    
    return metrics


def get_marker_genes(
    model,
    adata,
    groupby: str,
    n_genes: int = 10
) -> Dict[str, List[str]]:
    """
    Get marker genes using scVI differential expression.
    
    Parameters
    ----------
    model : scvi model
        Trained scVI/scANVI model
    adata : AnnData
        Data used for training
    groupby : str
        Column to group cells by
    n_genes : int
        Number of top markers per group
        
    Returns
    -------
    Dictionary of {group: [marker_genes]}
    """
    markers = {}
    groups = adata.obs[groupby].unique()
    
    for group in groups:
        # Get DE results for this group vs rest
        de_results = model.differential_expression(
            groupby=groupby,
            group1=group
        )
        
        # Filter and sort
        de_sig = de_results[
            (de_results["is_de_fdr_0.05"] == True) &
            (de_results["lfc_mean"] > 0.5)
        ].sort_values("lfc_mean", ascending=False)
        
        markers[group] = de_sig.index[:n_genes].tolist()
    
    return markers


def plot_training_history(model, save_path: Optional[str] = None):
    """
    Plot model training history.
    
    Parameters
    ----------
    model : scvi model
        Trained model
    save_path : str, optional
        Path to save figure
    """
    import matplotlib.pyplot as plt
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    
    # ELBO
    if "elbo_train" in model.history:
        axes[0].plot(model.history["elbo_train"], label="Train")
    if "elbo_validation" in model.history:
        axes[0].plot(model.history["elbo_validation"], label="Validation")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("ELBO")
    axes[0].legend()
    axes[0].set_title("Training Loss")
    
    # Reconstruction
    if "reconstruction_loss_train" in model.history:
        axes[1].plot(model.history["reconstruction_loss_train"], label="Train")
    if "reconstruction_loss_validation" in model.history:
        axes[1].plot(model.history["reconstruction_loss_validation"], label="Validation")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Reconstruction Loss")
    axes[1].legend()
    axes[1].set_title("Reconstruction Loss")
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    
    return fig


def save_results(
    model,
    adata,
    output_dir: str,
    save_model: bool = True,
    save_adata: bool = True,
    plot_umap: bool = True
):
    """
    Save model, processed data, and visualization.

    Parameters
    ----------
    model : scvi model
        Trained model
    adata : AnnData
        Processed data with latent representation
    output_dir : str
        Output directory path
    save_model : bool
        Save the trained model
    save_adata : bool
        Save the processed AnnData
    plot_umap : bool
        Generate and save UMAP plot
    """
    import os
    import scanpy as sc
    import matplotlib.pyplot as plt

    os.makedirs(output_dir, exist_ok=True)

    # Save model
    if save_model:
        model_path = os.path.join(output_dir, "model")
        model.save(model_path)
        print(f"Model saved to {model_path}")

    # Save AnnData
    if save_adata:
        adata_path = os.path.join(output_dir, "adata_processed.h5ad")
        adata.write(adata_path)
        print(f"AnnData saved to {adata_path}")

    # Generate UMAP if needed
    if plot_umap:
        # Determine which embedding to use
        if "X_scANVI" in adata.obsm:
            rep_key = "X_scANVI"
        elif "X_scVI" in adata.obsm:
            rep_key = "X_scVI"
        else:
            rep_key = None

        if rep_key is not None:
            # Compute neighbors and UMAP if not present
            if "X_umap" not in adata.obsm:
                sc.pp.neighbors(adata, use_rep=rep_key)
                sc.tl.umap(adata)

            # Plot
            fig, axes = plt.subplots(1, 2, figsize=(12, 5))

            # Plot by batch if available
            batch_cols = [c for c in adata.obs.columns if 'batch' in c.lower()]
            if batch_cols:
                sc.pl.umap(adata, color=batch_cols[0], ax=axes[0], show=False, title="By Batch")

            # Plot by cluster
            if "leiden" not in adata.obs:
                sc.tl.leiden(adata)
            sc.pl.umap(adata, color="leiden", ax=axes[1], show=False, title="Clusters")

            plt.tight_layout()
            plot_path = os.path.join(output_dir, "umap.png")
            plt.savefig(plot_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"UMAP plot saved to {plot_path}")


def auto_select_model(adata) -> str:
    """
    Suggest the best scvi-tools model based on available data.

    Parameters
    ----------
    adata : AnnData
        Data to analyze

    Returns
    -------
    String with model recommendation and reasoning
    """
    suggestions = []

    # Check for multi-modal data
    if 'protein_expression' in adata.obsm:
        suggestions.append({
            'model': 'totalVI',
            'reason': 'CITE-seq data detected (protein + RNA)',
            'priority': 1
        })

    if 'spliced' in adata.layers and 'unspliced' in adata.layers:
        suggestions.append({
            'model': 'veloVI',
            'reason': 'RNA velocity data detected (spliced + unspliced)',
            'priority': 1
        })

    # Check for ATAC data indicators
    if adata.n_vars > 100000:  # Many peaks suggest ATAC
        suggestions.append({
            'model': 'PeakVI',
            'reason': f'Large number of features ({adata.n_vars}) suggests ATAC-seq peaks',
            'priority': 2
        })

    # Check for labels
    label_cols = [c for c in adata.obs.columns if 'cell' in c.lower() or 'type' in c.lower() or 'label' in c.lower()]
    has_labels = len(label_cols) > 0

    # Check for batch info
    batch_cols = [c for c in adata.obs.columns if 'batch' in c.lower() or 'sample' in c.lower()]
    has_batch = len(batch_cols) > 0

    if has_batch:
        if has_labels:
            suggestions.append({
                'model': 'scANVI',
                'reason': f'Batch info ({batch_cols[0]}) + labels ({label_cols[0]}) available',
                'priority': 1
            })
        else:
            suggestions.append({
                'model': 'scVI',
                'reason': f'Batch info ({batch_cols[0]}) available, no labels',
                'priority': 1
            })
    else:
        suggestions.append({
            'model': 'scVI',
            'reason': 'Standard scRNA-seq analysis',
            'priority': 2
        })

    # Sort by priority
    suggestions.sort(key=lambda x: x['priority'])

    # Format output
    lines = ["Recommended models (in order of priority):"]
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s['model']}: {s['reason']}")

    return "\n".join(lines)


def compare_integrations(
    adata,
    batch_key: str,
    label_key: str,
    embedding_keys: List[str] = None
) -> Dict[str, Dict[str, float]]:
    """
    Compare multiple integration methods using standard metrics.

    Parameters
    ----------
    adata : AnnData
        Data with integration embeddings in obsm
    batch_key : str
        Batch column in obs
    label_key : str
        Cell type column in obs
    embedding_keys : list, optional
        Keys in obsm to compare (default: auto-detect)

    Returns
    -------
    Dictionary of {embedding: {metric: value}}
    """
    from sklearn.metrics import silhouette_score

    # Auto-detect embeddings
    if embedding_keys is None:
        embedding_keys = [k for k in adata.obsm.keys()
                         if k.startswith('X_') and 'umap' not in k.lower()]

    results = {}

    for key in embedding_keys:
        if key not in adata.obsm:
            continue

        X = adata.obsm[key]
        batch = adata.obs[batch_key].values
        labels = adata.obs[label_key].values

        metrics = {}

        try:
            # Silhouette scores
            metrics["silhouette_label"] = silhouette_score(X, labels)
            metrics["silhouette_batch"] = silhouette_score(X, batch)

            # Combined score (higher label preservation, lower batch separation = better)
            metrics["integration_score"] = metrics["silhouette_label"] - metrics["silhouette_batch"]

        except Exception as e:
            metrics["error"] = str(e)

        results[key] = metrics

    return results


def quick_clustering(
    adata,
    use_rep: str = None,
    resolution: float = 1.0,
    n_neighbors: int = 15
):
    """
    Quick clustering pipeline on latent representation.

    Parameters
    ----------
    adata : AnnData
        Data with latent representation
    use_rep : str, optional
        Key in obsm (auto-detects scVI/scANVI if not specified)
    resolution : float
        Leiden clustering resolution
    n_neighbors : int
        Number of neighbors for graph

    Returns
    -------
    AnnData with neighbors, UMAP, and leiden clustering
    """
    import scanpy as sc

    # Auto-detect representation
    if use_rep is None:
        if "X_scANVI" in adata.obsm:
            use_rep = "X_scANVI"
        elif "X_scVI" in adata.obsm:
            use_rep = "X_scVI"
        elif "X_totalVI" in adata.obsm:
            use_rep = "X_totalVI"
        elif "X_PeakVI" in adata.obsm:
            use_rep = "X_PeakVI"
        elif "X_MultiVI" in adata.obsm:
            use_rep = "X_MultiVI"
        else:
            raise ValueError("No scvi-tools embedding found in obsm")

    print(f"Using representation: {use_rep}")

    # Compute neighbors
    sc.pp.neighbors(adata, use_rep=use_rep, n_neighbors=n_neighbors)

    # UMAP
    sc.tl.umap(adata)

    # Leiden clustering
    sc.tl.leiden(adata, resolution=resolution)

    print(f"Found {adata.obs['leiden'].nunique()} clusters")

    return adata


if __name__ == "__main__":
    print("scvi-tools model utilities")
    print("\nAvailable functions:")
    print("  - prepare_adata: Standard data preparation (QC, HVG, layer setup)")
    print("  - train_scvi: Train scVI or scANVI with sensible defaults")
    print("  - evaluate_integration: Compute batch mixing and silhouette metrics")
    print("  - get_marker_genes: Extract markers using scVI differential expression")
    print("  - plot_training_history: Visualize training convergence")
    print("  - save_results: Save model, data, and visualizations")
    print("  - auto_select_model: Suggest best model for your data")
    print("  - compare_integrations: Compare multiple integration embeddings")
    print("  - quick_clustering: Quick clustering on latent representation")
