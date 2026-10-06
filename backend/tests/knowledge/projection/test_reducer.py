"""Tests for the vector-space projection reducers (spec §4 P1).

PCA is the built-in, zero-new-dependency default: the same fitted model must
reproduce the fitted coordinates and project unseen query vectors (the
retrieval-overlay path). UMAP stays an optional extra and must fail loudly
when the extra is absent.
"""

from __future__ import annotations

import numpy as np
import pytest

from deerflow.knowledge.projection.reducer import (
    UmapUnavailableError,
    l2_normalize,
    pca_reduce,
    umap_reduce,
)


def _cloud(n: int = 200, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian cloud stretched along a known principal direction in 3-D."""
    rng = np.random.default_rng(seed)
    direction = np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0)
    t = rng.normal(0.0, 10.0, size=(n, 1))
    noise = rng.normal(0.0, 0.1, size=(n, 3))
    return t * direction + noise, direction


def test_l2_normalize_unit_rows_and_zero_guard() -> None:
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.testing.assert_allclose(out[0], [0.6, 0.8])
    np.testing.assert_allclose(out[1], [0.0, 0.0])


def test_first_component_recovers_known_direction() -> None:
    x, direction = _cloud()
    coords, model = pca_reduce(x, 2)
    cosine = abs(float(model.components_[0] @ direction))
    assert cosine > 0.99
    assert coords.shape == (len(x), 2)
    assert model.model_version == "pca-v1"


def test_variance_ratio_sorted_and_dominant() -> None:
    x, _ = _cloud()
    _, model = pca_reduce(x, 2)
    ratios = model.variance_ratio_
    assert len(ratios) == 2
    assert ratios[0] >= ratios[1]
    assert ratios[0] > 0.95
    assert sum(ratios) <= 1.0 + 1e-9


def test_transform_matches_manual_projection() -> None:
    x, _ = _cloud()
    coords, model = pca_reduce(x, 2)
    manual = (l2_normalize(x) - model.mean_) @ model.components_.T
    np.testing.assert_allclose(coords, manual, atol=1e-10)
    # Single training point and a batch both land on their fitted coords.
    np.testing.assert_allclose(model.transform(x[0]), coords[0], atol=1e-10)
    np.testing.assert_allclose(model.transform(x[:5]), coords[:5], atol=1e-10)


def test_fit_is_scale_invariant_via_internal_normalization() -> None:
    x, direction = _cloud()
    _, model = pca_reduce(x * 7.5, 2)
    cosine = abs(float(model.components_[0] @ direction))
    assert cosine > 0.99


def test_unseen_query_vector_projects_into_fitted_space() -> None:
    x, direction = _cloud()
    _, model = pca_reduce(x, 2)
    # A query lying exactly on the principal axis must project near the x-axis.
    projected = model.transform(direction * 5.0)
    assert projected.shape == (2,)
    assert abs(float(projected[1])) < 0.1


def test_rejects_invalid_dims() -> None:
    x, _ = _cloud()
    with pytest.raises(ValueError, match="dims"):
        pca_reduce(x, 4)


def test_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        pca_reduce(np.empty((0, 3)), 2)


def test_pads_when_fewer_points_than_dims() -> None:
    coords, model = pca_reduce(np.array([[1.0, 0.0, 0.0]]), 3)
    assert coords.shape == (1, 3)
    assert model.components_.shape == (3, 3)
    assert np.isfinite(coords).all()


def test_zero_vector_rows_do_not_explode() -> None:
    x = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    coords, _ = pca_reduce(x, 2)
    assert np.isfinite(coords).all()


def test_umap_reduce_raises_without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境无关：monkeypatch 拦截 umap 的 import——本地真装了 extra（如开发机
    `uv sync --extra umap`）时本用例也必须绿。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "umap" or name.startswith("umap."):
            raise ImportError("No module named 'umap'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    x, _ = _cloud()
    with pytest.raises(UmapUnavailableError, match="umap"):
        umap_reduce(x, 2)


def test_umap_reduce_with_extra_produces_finite_coords() -> None:
    """装了 extra 的开发机/环境上的真实冒烟：UMAP 出正确形状的有限坐标。
    未装环境（CI 默认）自动 skip。"""
    pytest.importorskip("umap", reason="umap-learn extra not installed")
    x, _ = _cloud(30)  # 小样本——UMAP 拟合较慢
    coords, _model = umap_reduce(x, 2)
    assert coords.shape == (30, 2)
    assert np.isfinite(coords).all()
