#!/usr/bin/env python3
"""
Differential expression analysis using scvi-tools models.

Uses the trained model's differential_expression method which accounts
for batch effects and uses the generative model for inference.

Usage:
    python differential_expression.py model_dir/ adata.h5ad output.csv --groupby leiden
    python differential_expression.py model_dir/ adata.h5ad output.csv --groupby cell_type --group1 "T cells" --group2 "B cells"
"""

import argparse
import os
import sys


def run_de_analysis(
    model,
    adata,
    groupby,
    group1=None,
    group2=None,
    n_genes=None
):
    """
    Run differential expression analysis.

    Parameters
    ----------
    model : scvi model
        Trained model with differential_expression method
    adata : AnnData
        Data used for training
    groupby : str
        Column in obs to group by
    group1 : str, optional
        First group (if None, computes for all groups)
    group2 : str, optional
        Second group (rest if None)
    n_genes : int, optional
        Limit to top N genes per group

    Returns
    -------
    DataFrame with DE results
    """
    import pandas as pd

    if group1 is not None:
        # Specific comparison
        print(f"Comparing {group1} vs {group2 or 'rest'}...")
        de_results = model.differential_expression(
            groupby=groupby,
            group1=group1,
            group2=group2
        )

        # Add comparison info
        de_results["comparison"] = f"{group1}_vs_{group2 or 'rest'}"

    else:
        # All pairwise or one-vs-rest
        groups = adata.obs[groupby].unique()
        print(f"Computing DE for {len(groups)} groups...")

        all_results = []
        for group in groups:
            print(f"  Processing {group}...")
            try:
                de = model.differential_expression(
                    groupby=groupby,
                    group1=group
                )
                de["group"] = group
                all_results.append(de)
            except Exception as e:
                print(f"  Warning: Failed for {group}: {e}")

        de_results = pd.concat(all_results, ignore_index=False)

    # Filter to significant
    if "is_de_fdr_0.05" in de_results.columns:
        n_sig = de_results["is_de_fdr_0.05"].sum()
        print(f"Found {n_sig} significant DE genes (FDR < 0.05)")

    # Limit to top genes if requested
    if n_genes is not None and "lfc_mean" in de_results.columns:
        if "group" in de_results.columns:
            # Top N per group
            de_results = de_results.groupby("group").apply(
                lambda x: x.nlargest(n_genes, "lfc_mean")
            ).reset_index(drop=True)
        else:
            de_results = de_results.nlargest(n_genes, "lfc_mean")

    return de_results


def plot_volcano(de_results, output_path, group_name=None):
    """Create volcano plot of DE results."""
    import matplotlib.pyplot as plt
    import numpy as np

    if "lfc_mean" not in de_results.columns:
        print("Cannot create volcano plot: missing lfc_mean column")
        return

    fig, ax = plt.subplots(figsize=(8, 6))

    # Get values
    lfc = de_results["lfc_mean"].values
    if "bayes_factor" in de_results.columns:
        y_val = de_results["bayes_factor"].values
        y_label = "Bayes Factor"
    elif "proba_de" in de_results.columns:
        y_val = -np.log10(1 - de_results["proba_de"].values + 1e-10)
        y_label = "-log10(1 - P(DE))"
    else:
        y_val = np.ones(len(lfc))
        y_label = ""

    # Color by significance
    if "is_de_fdr_0.05" in de_results.columns:
        sig = de_results["is_de_fdr_0.05"].values
        colors = ["red" if s else "gray" for s in sig]
    else:
        colors = "gray"

    ax.scatter(lfc, y_val, c=colors, alpha=0.5, s=10)
    ax.axvline(0, color="black", linestyle="--", alpha=0.5)
    ax.set_xlabel("Log Fold Change")
    ax.set_ylabel(y_label)

    title = "Differential Expression"
    if group_name:
        title += f": {group_name}"
    ax.set_title(title)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Volcano plot saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Differential expression with scvi-tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # DE for all clusters (one-vs-rest)
    python differential_expression.py model/ adata.h5ad de_results.csv --groupby leiden

    # Specific comparison
    python differential_expression.py model/ adata.h5ad de_results.csv \\
        --groupby cell_type --group1 "T cells" --group2 "B cells"

    # Top 50 genes per cluster
    python differential_expression.py model/ adata.h5ad de_results.csv \\
        --groupby leiden --n-genes 50
        """
    )
    parser.add_argument("model_dir", help="Directory containing saved model")
    parser.add_argument("input", help="Input h5ad file (same as training)")
    parser.add_argument("output", help="Output CSV file for DE results")
    parser.add_argument("--groupby", required=True, help="Column to group by")
    parser.add_argument("--group1", help="First group for comparison")
    parser.add_argument("--group2", help="Second group (default: rest)")
    parser.add_argument("--n-genes", type=int, help="Limit to top N genes per group")
    parser.add_argument("--model-type", choices=["scvi", "scanvi", "totalvi"],
                        default="scvi", help="Model type (default: scvi)")
    parser.add_argument("--plot", action="store_true", help="Generate volcano plot")

    args = parser.parse_args()

    try:
        import scvi
        import scanpy as sc
    except ImportError:
        print("Error: scvi-tools and scanpy required")
        sys.exit(1)

    # Load data
    print(f"Loading {args.input}...")
    adata = sc.read_h5ad(args.input)

    # Load model
    print(f"Loading model from {args.model_dir}...")
    if args.model_type == "scvi":
        model = scvi.model.SCVI.load(args.model_dir, adata=adata)
    elif args.model_type == "scanvi":
        model = scvi.model.SCANVI.load(args.model_dir, adata=adata)
    elif args.model_type == "totalvi":
        model = scvi.model.TOTALVI.load(args.model_dir, adata=adata)

    # Run DE
    de_results = run_de_analysis(
        model,
        adata,
        groupby=args.groupby,
        group1=args.group1,
        group2=args.group2,
        n_genes=args.n_genes
    )

    # Save results
    de_results.to_csv(args.output)
    print(f"DE results saved to {args.output}")

    # Plot
    if args.plot:
        plot_path = args.output.replace(".csv", "_volcano.png")
        plot_volcano(de_results, plot_path, args.group1)

    print("\nDone!")


if __name__ == "__main__":
    main()
