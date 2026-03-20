#!/usr/bin/env python3
"""
Train scvi-tools models.

Supports scVI, scANVI, totalVI, PeakVI, and other models.
Input should be prepared with prepare_data.py or equivalent.

Usage:
    python train_model.py input.h5ad output_dir/ --model scvi --batch-key batch
    python train_model.py input.h5ad output_dir/ --model scanvi --batch-key batch --labels-key cell_type
"""

import argparse
import os
import sys


def train_scvi(adata, batch_key=None, n_latent=30, n_layers=2, max_epochs=200):
    """Train scVI model."""
    import scvi

    scvi.model.SCVI.setup_anndata(
        adata,
        layer="counts",
        batch_key=batch_key
    )

    model = scvi.model.SCVI(
        adata,
        n_latent=n_latent,
        n_layers=n_layers
    )

    model.train(
        max_epochs=max_epochs,
        early_stopping=True,
        early_stopping_patience=10
    )

    adata.obsm["X_scVI"] = model.get_latent_representation()
    return model, "X_scVI"


def train_scanvi(adata, batch_key=None, labels_key=None, n_latent=30, n_layers=2, max_epochs=200):
    """Train scANVI model (scVI + labels)."""
    import scvi

    # First train scVI
    scvi.model.SCVI.setup_anndata(
        adata,
        layer="counts",
        batch_key=batch_key
    )

    scvi_model = scvi.model.SCVI(
        adata,
        n_latent=n_latent,
        n_layers=n_layers
    )
    scvi_model.train(max_epochs=max_epochs, early_stopping=True)

    # Initialize scANVI from scVI
    model = scvi.model.SCANVI.from_scvi_model(
        scvi_model,
        labels_key=labels_key,
        unlabeled_category="Unknown"
    )

    # Fine-tune scANVI
    model.train(max_epochs=max_epochs // 4)

    adata.obsm["X_scANVI"] = model.get_latent_representation()
    return model, "X_scANVI"


def train_totalvi(adata, batch_key=None, protein_key="protein_expression", n_latent=20, max_epochs=200):
    """Train totalVI model for CITE-seq."""
    import scvi
    import numpy as np

    scvi.model.TOTALVI.setup_anndata(
        adata,
        layer="counts",
        batch_key=batch_key,
        protein_expression_obsm_key=protein_key
    )

    model = scvi.model.TOTALVI(
        adata,
        n_latent=n_latent
    )

    model.train(max_epochs=max_epochs, early_stopping=True)

    adata.obsm["X_totalVI"] = model.get_latent_representation()

    # Also get denoised protein - convert to numpy array for h5ad compatibility
    _, protein_denoised = model.get_normalized_expression(return_mean=True)
    if hasattr(protein_denoised, 'values'):
        adata.obsm["protein_denoised"] = protein_denoised.values
    else:
        adata.obsm["protein_denoised"] = np.array(protein_denoised)

    return model, "X_totalVI"


def train_peakvi(adata, batch_key=None, n_latent=20, max_epochs=200):
    """Train PeakVI model for scATAC-seq."""
    import scvi
    import numpy as np

    # Binarize if not already
    if adata.X.max() > 1:
        print("Binarizing ATAC data...")
        adata.X = (adata.X > 0).astype(np.float32)

    scvi.model.PEAKVI.setup_anndata(
        adata,
        batch_key=batch_key
    )

    model = scvi.model.PEAKVI(
        adata,
        n_latent=n_latent
    )

    model.train(max_epochs=max_epochs, early_stopping=True)

    adata.obsm["X_PeakVI"] = model.get_latent_representation()
    return model, "X_PeakVI"


def train_velovi(adata, max_epochs=500):
    """Train veloVI model for RNA velocity.

    Note: Requires scvelo preprocessing. If Ms/Mu layers don't exist,
    will run preprocessing automatically.
    """
    import scvi
    import scvelo as scv

    # Check if data needs preprocessing
    if "Ms" not in adata.layers or "Mu" not in adata.layers:
        print("Preprocessing data for veloVI (scvelo moments)...")

        # Filter and normalize
        scv.pp.filter_and_normalize(adata, min_shared_counts=30, n_top_genes=2000)

        # Calculate moments (creates Ms, Mu layers)
        scv.pp.moments(adata, n_pcs=30, n_neighbors=30)

        print(f"After preprocessing: {adata.shape}")

    # VELOVI is in scvi.external, not scvi.model
    scvi.external.VELOVI.setup_anndata(
        adata,
        spliced_layer="Ms",
        unspliced_layer="Mu"
    )

    model = scvi.external.VELOVI(adata)
    model.train(max_epochs=max_epochs, early_stopping=True)

    # Get latent representation (cells x latent_dim)
    adata.obsm["X_veloVI"] = model.get_latent_representation()

    # Get velocity (cells x genes)
    adata.layers["velocity"] = model.get_velocity()

    # Get latent time per gene (cells x genes) - store mean across genes as summary
    latent_time_df = model.get_latent_time()
    adata.obs["latent_time_mean"] = latent_time_df.mean(axis=1).values

    return model, "X_veloVI"


def train_multivi(adata, batch_key=None, n_latent=20, max_epochs=300):
    """Train MultiVI model for multiome (RNA + ATAC).

    Note: Expects MuData or AnnData with both RNA and ATAC data.
    For AnnData, ATAC peaks should be concatenated with genes,
    or use MuData format.
    """
    import scvi
    import numpy as np

    # Check if this is MuData
    try:
        import mudata as md
        if isinstance(adata, md.MuData):
            # Setup for MuData
            scvi.model.MULTIVI.setup_mudata(
                adata,
                rna_layer="counts",
                atac_layer="counts",
                batch_key=batch_key,
                modalities={
                    "rna_layer": "rna",
                    "batch_key": "rna",
                    "atac_layer": "atac"
                }
            )
        else:
            raise ValueError("MultiVI requires MuData format with 'rna' and 'atac' modalities")
    except ImportError:
        raise ImportError("MultiVI requires mudata. Install with: pip install mudata")

    model = scvi.model.MULTIVI(
        adata,
        n_latent=n_latent
    )

    model.train(max_epochs=max_epochs, early_stopping=True)

    # Get latent representation
    latent = model.get_latent_representation()
    adata.obsm["X_MultiVI"] = latent

    return model, "X_MultiVI"


MODELS = {
    "scvi": train_scvi,
    "scanvi": train_scanvi,
    "totalvi": train_totalvi,
    "peakvi": train_peakvi,
    "velovi": train_velovi,
    "multivi": train_multivi,
}


def main():
    parser = argparse.ArgumentParser(
        description="Train scvi-tools models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Train scVI for batch correction
    python train_model.py prepared.h5ad results/ --model scvi --batch-key batch

    # Train scANVI with cell type labels
    python train_model.py prepared.h5ad results/ --model scanvi --batch-key batch --labels-key cell_type

    # Train totalVI for CITE-seq
    python train_model.py citeseq.h5ad results/ --model totalvi --batch-key batch

    # Train PeakVI for ATAC-seq
    python train_model.py atac.h5ad results/ --model peakvi

    # Train veloVI for RNA velocity
    python train_model.py velocity.h5ad results/ --model velovi

    # Train MultiVI for multiome (RNA + ATAC) - requires MuData format
    python train_model.py multiome.h5mu results/ --model multivi --batch-key batch
        """
    )
    parser.add_argument("input", help="Input h5ad file (prepared)")
    parser.add_argument("output_dir", help="Output directory for model and results")
    parser.add_argument("--model", choices=list(MODELS.keys()), default="scvi",
                        help="Model type (default: scvi)")
    parser.add_argument("--batch-key", help="Batch column in obs")
    parser.add_argument("--labels-key", help="Labels column (required for scanvi)")
    parser.add_argument("--protein-key", default="protein_expression",
                        help="Protein obsm key for totalvi")
    parser.add_argument("--n-latent", type=int, default=30, help="Latent dimensions (default: 30)")
    parser.add_argument("--n-layers", type=int, default=2, help="Encoder/decoder layers (default: 2)")
    parser.add_argument("--max-epochs", type=int, default=200, help="Max training epochs (default: 200)")

    args = parser.parse_args()

    # Validate
    if args.model == "scanvi" and args.labels_key is None:
        print("Error: --labels-key required for scanvi model")
        sys.exit(1)

    try:
        import scvi
        import scanpy as sc
    except ImportError:
        print("Error: scvi-tools and scanpy required")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Load data
    print(f"Loading {args.input}...")
    if args.input.endswith('.h5mu') or args.model == "multivi":
        try:
            import mudata as md
            adata = md.read(args.input)
            print(f"MuData: {adata.n_obs} cells")
            for mod_name, mod in adata.mod.items():
                print(f"  {mod_name}: {mod.shape}")
        except ImportError:
            print("Error: mudata required for .h5mu files. Install with: pip install mudata")
            sys.exit(1)
    else:
        adata = sc.read_h5ad(args.input)
        print(f"Data: {adata.shape}")

    # Check for counts layer
    if "counts" not in adata.layers:
        print("Warning: 'counts' layer not found, using X")
        adata.layers["counts"] = adata.X.copy()

    # Train model
    print(f"\nTraining {args.model.upper()}...")

    if args.model == "scvi":
        model, rep_key = train_scvi(
            adata, args.batch_key, args.n_latent, args.n_layers, args.max_epochs
        )
    elif args.model == "scanvi":
        model, rep_key = train_scanvi(
            adata, args.batch_key, args.labels_key, args.n_latent, args.n_layers, args.max_epochs
        )
    elif args.model == "totalvi":
        model, rep_key = train_totalvi(
            adata, args.batch_key, args.protein_key, args.n_latent, args.max_epochs
        )
    elif args.model == "peakvi":
        model, rep_key = train_peakvi(
            adata, args.batch_key, args.n_latent, args.max_epochs
        )
    elif args.model == "velovi":
        model, rep_key = train_velovi(adata, args.max_epochs)
    elif args.model == "multivi":
        model, rep_key = train_multivi(adata, args.batch_key, args.n_latent, args.max_epochs)

    print("Training complete!")

    # Save model
    model_path = os.path.join(args.output_dir, "model")
    model.save(model_path)
    print(f"Model saved to {model_path}")

    # Save adata with latent representation
    adata_path = os.path.join(args.output_dir, "adata_trained.h5ad")
    adata.write_h5ad(adata_path)
    print(f"AnnData saved to {adata_path}")

    # Save training history plot
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        if "elbo_train" in model.history:
            ax.plot(model.history["elbo_train"], label="Train")
        if "elbo_validation" in model.history:
            ax.plot(model.history["elbo_validation"], label="Validation")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("ELBO")
        ax.legend()
        ax.set_title(f"{args.model.upper()} Training History")

        plot_path = os.path.join(args.output_dir, "training_history.png")
        plt.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Training plot saved to {plot_path}")
    except Exception as e:
        print(f"Could not save training plot: {e}")

    print("\nDone! Next steps:")
    print(f"  - Run clustering: python cluster_embed.py {adata_path} {args.output_dir}")
    print(f"  - Load model: scvi.model.{args.model.upper()}.load('{model_path}')")


if __name__ == "__main__":
    main()
