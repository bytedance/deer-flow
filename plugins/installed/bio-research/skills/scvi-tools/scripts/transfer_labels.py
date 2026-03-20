#!/usr/bin/env python3
"""
Transfer cell type labels from reference to query using scANVI.

Maps query cells to a pre-trained reference model and predicts cell types.

Usage:
    python transfer_labels.py reference_model/ query.h5ad output_dir/
    python transfer_labels.py reference_model/ query.h5ad output_dir/ --confidence 0.7
"""

import argparse
import os
import sys


def transfer_labels(
    reference_model,
    adata_query,
    max_epochs=100,
    confidence_threshold=0.5
):
    """
    Transfer labels from reference to query.

    Parameters
    ----------
    reference_model : SCANVI model
        Pre-trained scANVI model
    adata_query : AnnData
        Query data to annotate
    max_epochs : int
        Fine-tuning epochs
    confidence_threshold : float
        Minimum confidence for predictions

    Returns
    -------
    AnnData with predictions
    """
    import scvi
    import numpy as np

    # Get reference genes
    ref_genes = reference_model.adata.var_names
    print(f"Reference genes: {len(ref_genes)}")

    # Check gene overlap
    query_genes = adata_query.var_names
    common = ref_genes.intersection(query_genes)
    print(f"Query genes: {len(query_genes)}")
    print(f"Common genes: {len(common)} ({len(common)/len(ref_genes)*100:.1f}%)")

    if len(common) < len(ref_genes) * 0.5:
        print("Warning: Less than 50% gene overlap. Results may be unreliable.")

    # Subset query to reference genes
    # Missing genes will be filled with zeros
    adata_query = adata_query[:, adata_query.var_names.isin(ref_genes)].copy()

    # Ensure counts layer
    if "counts" not in adata_query.layers:
        adata_query.layers["counts"] = adata_query.X.copy()

    # Prepare query for mapping
    print("Preparing query data...")
    scvi.model.SCANVI.prepare_query_anndata(adata_query, reference_model)

    # Create query model
    print("Creating query model...")
    query_model = scvi.model.SCANVI.load_query_data(
        adata_query,
        reference_model
    )

    # Fine-tune
    print(f"Fine-tuning ({max_epochs} epochs)...")
    query_model.train(
        max_epochs=max_epochs,
        plan_kwargs={"weight_decay": 0.0}
    )

    # Get predictions
    print("Getting predictions...")
    predictions = query_model.predict()
    soft_predictions = query_model.predict(soft=True)

    adata_query.obs["predicted_cell_type"] = predictions
    adata_query.obs["prediction_confidence"] = soft_predictions.max(axis=1)
    adata_query.obs["confident_prediction"] = adata_query.obs["prediction_confidence"] >= confidence_threshold

    # Get latent representation
    adata_query.obsm["X_scANVI"] = query_model.get_latent_representation()

    # Stats
    n_confident = adata_query.obs["confident_prediction"].sum()
    print(f"\nPrediction summary:")
    print(f"  Total cells: {adata_query.n_obs}")
    print(f"  Confident (>= {confidence_threshold}): {n_confident} ({n_confident/adata_query.n_obs*100:.1f}%)")
    print(f"  Mean confidence: {adata_query.obs['prediction_confidence'].mean():.3f}")

    print("\nPredicted cell types:")
    print(adata_query.obs["predicted_cell_type"].value_counts())

    return adata_query, query_model


def plot_predictions(adata, output_dir):
    """Plot prediction results."""
    import scanpy as sc
    import matplotlib.pyplot as plt

    # Compute UMAP if needed
    if "X_umap" not in adata.obsm:
        sc.pp.neighbors(adata, use_rep="X_scANVI")
        sc.tl.umap(adata)

    # Plot
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))

    sc.pl.umap(adata, color="predicted_cell_type", ax=axes[0], show=False,
               title="Predicted Cell Type")
    sc.pl.umap(adata, color="prediction_confidence", ax=axes[1], show=False,
               title="Prediction Confidence", cmap="viridis")
    sc.pl.umap(adata, color="confident_prediction", ax=axes[2], show=False,
               title="Confident Predictions")

    plt.tight_layout()
    plot_path = os.path.join(output_dir, "predictions.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Prediction plot saved to {plot_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Transfer cell type labels using scANVI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic label transfer
    python transfer_labels.py reference_model/ query.h5ad results/

    # With confidence threshold
    python transfer_labels.py reference_model/ query.h5ad results/ --confidence 0.7

    # More fine-tuning
    python transfer_labels.py reference_model/ query.h5ad results/ --max-epochs 200
        """
    )
    parser.add_argument("model_dir", help="Directory containing reference scANVI model")
    parser.add_argument("query", help="Query h5ad file to annotate")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument("--reference-adata", help="Reference adata used for training (if not saved with model)")
    parser.add_argument("--max-epochs", type=int, default=100,
                        help="Fine-tuning epochs (default: 100)")
    parser.add_argument("--confidence", type=float, default=0.5,
                        help="Confidence threshold (default: 0.5)")

    args = parser.parse_args()

    try:
        import scvi
        import scanpy as sc
    except ImportError:
        print("Error: scvi-tools and scanpy required")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Load query data
    print(f"Loading query data: {args.query}")
    adata_query = sc.read_h5ad(args.query)
    print(f"Query: {adata_query.shape}")

    # Load reference model
    print(f"Loading reference model: {args.model_dir}")
    if args.reference_adata:
        ref_adata = sc.read_h5ad(args.reference_adata)
        reference_model = scvi.model.SCANVI.load(args.model_dir, adata=ref_adata)
    else:
        # Try loading without adata (works if model was saved with adata)
        try:
            reference_model = scvi.model.SCANVI.load(args.model_dir)
        except ValueError as e:
            if "no saved anndata" in str(e).lower():
                print("Error: Model was saved without adata. Please provide --reference-adata")
                sys.exit(1)
            raise
    print(f"Reference: {reference_model.adata.shape}")

    # Transfer labels
    adata_annotated, query_model = transfer_labels(
        reference_model,
        adata_query,
        max_epochs=args.max_epochs,
        confidence_threshold=args.confidence
    )

    # Save results
    adata_path = os.path.join(args.output_dir, "query_annotated.h5ad")
    adata_annotated.write_h5ad(adata_path)
    print(f"\nAnnotated data saved to {adata_path}")

    # Save query model
    model_path = os.path.join(args.output_dir, "query_model")
    query_model.save(model_path)
    print(f"Query model saved to {model_path}")

    # Save predictions CSV
    pred_df = adata_annotated.obs[["predicted_cell_type", "prediction_confidence", "confident_prediction"]]
    pred_path = os.path.join(args.output_dir, "predictions.csv")
    pred_df.to_csv(pred_path)
    print(f"Predictions saved to {pred_path}")

    # Plot
    plot_predictions(adata_annotated, args.output_dir)

    print("\nDone!")


if __name__ == "__main__":
    main()
