"""Dimensionality reducers for the vector-space projection (spec §4 P1).

PCA is implemented directly on numpy (centering + SVD) so the harness keeps a
zero-new-dependency posture. The fitted :class:`PCAModel` is tiny (dims×D + D
floats) and is kept alongside the cached projection so unseen query vectors
can be transformed into the same coordinate system without re-fitting — that
linear transform is what powers the retrieval overlay (spec §9).

UMAP produces prettier clusters but stays an optional extra
(``deerflow-harness[umap]``): it drags in numba/llvmlite (~100MB) and its
``transform`` for new points is unstable, so query overlay is PCA-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

MODEL_VERSION_PCA = "pca-v1"


class UmapUnavailableError(RuntimeError):
    """Raised when ``algo=umap`` is requested without the optional extra."""


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalization with a zero-norm guard (cosine sphereize)."""
    x = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return x / norms


@dataclass(frozen=True)
class PCAModel:
    """Fitted PCA parameters (principal axes + centering vector)."""

    components_: np.ndarray  # (dims, D) principal axes as rows
    mean_: np.ndarray  # (D,) mean of the normalized training data
    variance_ratio_: tuple[float, ...] = field(default_factory=tuple)
    model_version: str = MODEL_VERSION_PCA

    def transform(self, vector: np.ndarray) -> np.ndarray:
        """Project one ``(D,)`` or a batch ``(n, D)`` of raw vectors.

        The same L2 normalization applied at fit time is re-applied here so
        fit and transform never drift apart (query vectors arrive raw).
        """
        raw = np.asarray(vector, dtype=np.float64)
        single = raw.ndim == 1
        v = l2_normalize(np.atleast_2d(raw))
        out = (v - self.mean_) @ self.components_.T
        return out[0] if single else out


def pca_reduce(vectors: np.ndarray, dims: int) -> tuple[np.ndarray, PCAModel]:
    """Project ``vectors`` ``(n, D)`` to exactly ``dims`` columns via SVD.

    Inputs are L2-normalized first (cosine-space sphereize, matching the
    Embedding Projector practice). When the data has fewer points or features
    than ``dims``, the missing axes are zero-padded so callers always receive
    ``(n, dims)`` coordinates and a ``(dims, D)`` model.
    """
    if dims not in (2, 3):
        raise ValueError(f"dims must be 2 or 3, got {dims}")
    x = np.asarray(vectors, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] == 0:
        raise ValueError("vectors must be a non-empty 2-D array")
    x = l2_normalize(x)
    mean = x.mean(axis=0)
    centered = x - mean
    _, s, vt = np.linalg.svd(centered, full_matrices=False)
    n_axes = min(dims, vt.shape[0])
    components = vt[:n_axes]
    total = float((s**2).sum())
    ratios = tuple(float(v) for v in (s[:n_axes] ** 2 / total)) if total > 0 else (0.0,) * n_axes
    coords = centered @ components.T
    if n_axes < dims:
        pad = dims - n_axes
        coords = np.pad(coords, ((0, 0), (0, pad)))
        components = np.pad(components, ((0, pad), (0, 0)))
        ratios = ratios + (0.0,) * pad
    model = PCAModel(components_=components, mean_=mean, variance_ratio_=ratios)
    return coords, model


def umap_reduce(
    vectors: np.ndarray,
    dims: int,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
) -> tuple[np.ndarray, Any]:
    """UMAP projection via the optional ``deerflow-harness[umap]`` extra.

    Raises :class:`UmapUnavailableError` when the extra is absent; the API
    layer maps that to a 400 carrying the install hint (spec §7).
    """
    try:
        import umap
    except ImportError as exc:
        raise UmapUnavailableError("umap-learn is not installed; install it via the optional extra (`deerflow-harness[umap]`) or use algo=pca") from exc
    if dims not in (2, 3):
        raise ValueError(f"dims must be 2 or 3, got {dims}")
    x = l2_normalize(np.asarray(vectors, dtype=np.float64))
    if x.shape[0] == 0:
        raise ValueError("vectors must be a non-empty 2-D array")
    reducer = umap.UMAP(
        n_components=dims,
        n_neighbors=min(n_neighbors, max(2, x.shape[0] - 1)),
        min_dist=min_dist,
        metric="cosine",
    )
    return reducer.fit_transform(x), reducer


def prewarm_umap() -> bool:
    """Best-effort UMAP warm-up: lazy ``import umap`` plus a tiny fit.

    A cold-started Gateway process otherwise bills the *first* UMAP switch
    ~20s of fixed overhead before the real fit even starts (measured
    2026-08-17): the numba/llvmlite/pynndescent import chain (~10s) plus the
    per-process JIT-artifact load (~10s, disk cache warm). Running this once
    in a startup background thread moves that cost off the user-visible path.

    Designed for fire-and-forget scheduling from ``app.gateway.app.lifespan``;
    every failure mode returns ``False`` instead of raising so a failed
    warm-up merely leaves the lazy status-quo behaviour in place.
    """

    try:
        import umap

        # n_epochs is cut to the minimum: the goal is compiling/loading the
        # jitted code paths, which happens on the first fit regardless of the
        # epoch count — layout iterations on 64×32 points are pure overhead.
        umap.UMAP(n_components=2, n_neighbors=15, metric="cosine", n_epochs=5).fit_transform(np.random.rand(64, 32))
    except ImportError:
        return False  # optional extra absent; the API layer keeps its 400 install hint
    except Exception:  # noqa: BLE001 - warm-up must never break startup or the request path
        return False
    return True
