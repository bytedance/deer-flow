#!/usr/bin/env python3
"""
Validation utilities for checking AnnData compatibility with scvi-tools.

Usage:
    python validate_adata.py data.h5ad

    # Or import as module
    from validate_adata import validate_for_scvi, ValidationResult
    result = validate_for_scvi(adata)
    print(result.summary())
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import warnings


@dataclass
class ValidationResult:
    """Results from AnnData validation."""

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)

    def add_error(self, msg: str):
        """Add an error (makes validation fail)."""
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str):
        """Add a warning (doesn't fail validation)."""
        self.warnings.append(msg)

    def add_recommendation(self, msg: str):
        """Add a recommendation for improvement."""
        self.recommendations.append(msg)

    def summary(self) -> str:
        """Generate summary report."""
        lines = []
        lines.append("=" * 60)
        lines.append("scvi-tools AnnData Validation Report")
        lines.append("=" * 60)

        # Status
        status = "PASSED" if self.is_valid else "FAILED"
        lines.append(f"\nStatus: {status}")

        # Info
        if self.info:
            lines.append("\n--- Data Summary ---")
            for key, value in self.info.items():
                lines.append(f"  {key}: {value}")

        # Errors
        if self.errors:
            lines.append(f"\n--- Errors ({len(self.errors)}) ---")
            for i, err in enumerate(self.errors, 1):
                lines.append(f"  {i}. {err}")

        # Warnings
        if self.warnings:
            lines.append(f"\n--- Warnings ({len(self.warnings)}) ---")
            for i, warn in enumerate(self.warnings, 1):
                lines.append(f"  {i}. {warn}")

        # Recommendations
        if self.recommendations:
            lines.append(f"\n--- Recommendations ({len(self.recommendations)}) ---")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"  {i}. {rec}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


def validate_for_scvi(
    adata,
    layer: Optional[str] = None,
    batch_key: Optional[str] = None,
    labels_key: Optional[str] = None,
    check_hvg: bool = True
) -> ValidationResult:
    """
    Validate AnnData for scvi-tools compatibility.

    Parameters
    ----------
    adata : AnnData
        Data to validate
    layer : str, optional
        Layer containing counts (if None, checks X)
    batch_key : str, optional
        Expected batch column in obs
    labels_key : str, optional
        Expected labels column in obs
    check_hvg : bool
        Check for highly variable genes

    Returns
    -------
    ValidationResult with errors, warnings, and recommendations
    """
    import numpy as np
    from scipy.sparse import issparse

    result = ValidationResult()

    # Basic info
    result.info["shape"] = f"{adata.n_obs} cells x {adata.n_vars} genes"
    result.info["layers"] = list(adata.layers.keys()) if adata.layers else "None"

    # Get data matrix to check
    if layer is not None:
        if layer not in adata.layers:
            result.add_error(f"Layer '{layer}' not found. Available: {list(adata.layers.keys())}")
            return result
        X = adata.layers[layer]
        result.info["checking"] = f"layer '{layer}'"
    else:
        X = adata.X
        result.info["checking"] = "adata.X"

    # Check for None or empty
    if X is None:
        result.add_error("Data matrix is None")
        return result

    if X.shape[0] == 0 or X.shape[1] == 0:
        result.add_error(f"Data matrix is empty: shape {X.shape}")
        return result

    # Convert to array for checking
    if issparse(X):
        result.info["sparse"] = True
        X_check = X.data  # Just check non-zero values
    else:
        result.info["sparse"] = False
        X_check = X.flatten()

    # Check for raw counts (integers)
    if len(X_check) > 0:
        is_integer = np.allclose(X_check, X_check.astype(int))
        result.info["contains_integers"] = is_integer

        if not is_integer:
            result.add_error(
                "Data does not contain integers (raw counts required). "
                "Found float values - data may be normalized."
            )
            result.add_recommendation(
                "Use adata.raw.to_adata() to recover raw counts, "
                "or specify a layer with raw counts"
            )

    # Check for negative values
    min_val = X.min()
    if min_val < 0:
        result.add_error(f"Data contains negative values (min={min_val})")

    # Check for NaN/Inf
    if issparse(X):
        has_nan = np.isnan(X.data).any()
        has_inf = np.isinf(X.data).any()
    else:
        has_nan = np.isnan(X).any()
        has_inf = np.isinf(X).any()

    if has_nan:
        result.add_error("Data contains NaN values")
    if has_inf:
        result.add_error("Data contains Inf values")

    # Check data range
    max_val = X.max()
    result.info["value_range"] = f"[{min_val}, {max_val}]"

    if max_val < 10:
        result.add_warning(
            f"Maximum value is {max_val}, which is very low. "
            "Data may be log-transformed or normalized."
        )

    # Check sparsity
    if issparse(X):
        sparsity = 1 - (X.nnz / (X.shape[0] * X.shape[1]))
        result.info["sparsity"] = f"{sparsity:.1%}"

        if sparsity < 0.5:
            result.add_warning(
                f"Data is only {sparsity:.1%} sparse. "
                "Consider if this is expected for your data type."
            )

    # Check batch key
    if batch_key is not None:
        if batch_key not in adata.obs.columns:
            result.add_error(
                f"batch_key '{batch_key}' not found in obs. "
                f"Available columns: {list(adata.obs.columns)}"
            )
        else:
            n_batches = adata.obs[batch_key].nunique()
            result.info["n_batches"] = n_batches

            if n_batches == 1:
                result.add_warning(
                    "Only 1 batch found. Batch correction may not be needed."
                )

            # Check for small batches
            batch_counts = adata.obs[batch_key].value_counts()
            small_batches = batch_counts[batch_counts < 50]
            if len(small_batches) > 0:
                result.add_warning(
                    f"{len(small_batches)} batches have fewer than 50 cells. "
                    "Consider merging small batches."
                )

    # Check labels key
    if labels_key is not None:
        if labels_key not in adata.obs.columns:
            result.add_error(
                f"labels_key '{labels_key}' not found in obs. "
                f"Available columns: {list(adata.obs.columns)}"
            )
        else:
            n_labels = adata.obs[labels_key].nunique()
            result.info["n_labels"] = n_labels

            # Check for rare labels
            label_counts = adata.obs[labels_key].value_counts()
            rare_labels = label_counts[label_counts < 30]
            if len(rare_labels) > 0:
                result.add_warning(
                    f"{len(rare_labels)} cell types have fewer than 30 cells. "
                    "Rare types may not be well learned."
                )

    # Check HVG
    if check_hvg:
        if 'highly_variable' not in adata.var.columns:
            result.add_recommendation(
                "No highly variable genes found. Run sc.pp.highly_variable_genes() "
                "and subset to HVGs for better performance."
            )
        else:
            n_hvg = adata.var['highly_variable'].sum()
            result.info["n_hvg"] = n_hvg

            if n_hvg < 1000:
                result.add_warning(
                    f"Only {n_hvg} HVGs selected. Consider using 2000-4000 for best results."
                )
            elif n_hvg > 5000:
                result.add_warning(
                    f"{n_hvg} HVGs selected. Consider reducing to 2000-4000 "
                    "for efficiency."
                )

    # Check gene count
    if adata.n_vars > 30000:
        result.add_recommendation(
            f"Dataset has {adata.n_vars} genes. Subset to HVGs (2000-4000) "
            "for faster training and better results."
        )

    # Check cell count
    if adata.n_obs < 1000:
        result.add_warning(
            f"Dataset has only {adata.n_obs} cells. "
            "Deep learning models work best with >5000 cells."
        )

    # Check for counts layer
    if layer is None and 'counts' not in adata.layers:
        result.add_recommendation(
            "Store raw counts in adata.layers['counts'] before any normalization. "
            "This preserves the original data for scvi-tools."
        )

    # Check for raw attribute
    if adata.raw is not None:
        result.info["has_raw"] = True
        result.add_recommendation(
            "adata.raw exists. If X is normalized, use adata.raw.to_adata() "
            "to recover raw counts."
        )
    else:
        result.info["has_raw"] = False

    return result


def suggest_model(adata, result: ValidationResult) -> str:
    """
    Suggest appropriate scvi-tools model based on data.

    Parameters
    ----------
    adata : AnnData
        Data to analyze
    result : ValidationResult
        Validation result with info

    Returns
    -------
    String with model suggestion
    """
    suggestions = []

    # Check for multi-modal data
    if 'protein_expression' in adata.obsm:
        suggestions.append("totalVI: CITE-seq data detected (protein + RNA)")

    if 'spliced' in adata.layers and 'unspliced' in adata.layers:
        suggestions.append("veloVI: RNA velocity data detected (spliced + unspliced)")

    # Check for labels
    has_labels = result.info.get('n_labels', 0) > 0
    has_batches = result.info.get('n_batches', 0) > 1

    if has_batches:
        if has_labels:
            suggestions.append(
                "scANVI: Integration with cell type labels (recommended for label transfer)"
            )
        else:
            suggestions.append(
                "scVI: Unsupervised batch integration"
            )
    else:
        suggestions.append(
            "scVI: Dimensionality reduction and differential expression"
        )

    if not suggestions:
        suggestions.append("scVI: General-purpose single-cell analysis")

    return "\n".join([f"  - {s}" for s in suggestions])


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Validate AnnData for scvi-tools compatibility"
    )
    parser.add_argument("file", help="Path to h5ad file")
    parser.add_argument("--layer", help="Layer to check (default: X)")
    parser.add_argument("--batch-key", help="Batch column to check")
    parser.add_argument("--labels-key", help="Labels column to check")
    parser.add_argument("--suggest", action="store_true", help="Suggest model type")

    args = parser.parse_args()

    try:
        import scanpy as sc
    except ImportError:
        print("Error: scanpy is required. Install with: pip install scanpy")
        sys.exit(1)

    # Load data
    print(f"Loading {args.file}...")
    try:
        adata = sc.read_h5ad(args.file)
    except Exception as e:
        print(f"Error loading file: {e}")
        sys.exit(1)

    # Validate
    result = validate_for_scvi(
        adata,
        layer=args.layer,
        batch_key=args.batch_key,
        labels_key=args.labels_key
    )

    # Print report
    print(result.summary())

    # Suggest model
    if args.suggest:
        print("\nSuggested models:")
        print(suggest_model(adata, result))

    # Exit code
    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
