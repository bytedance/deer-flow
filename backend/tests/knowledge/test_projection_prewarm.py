"""Unit tests for the UMAP startup pre-warm hook (spec §4, 2026-08-17).

``prewarm_umap`` runs fire-and-forget from the Gateway lifespan, so its
contract is strict: **never raise** — a missing optional extra or any
warm-up failure returns ``False`` and leaves the lazy status-quo behaviour
(first UMAP request pays the JIT cost) in place.
"""

from __future__ import annotations

import builtins
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from deerflow.knowledge.projection.reducer import prewarm_umap


def _install_fake_umap(monkeypatch, umap_cls) -> None:
    """Plant a fake ``umap`` module so the lazy ``import umap`` binds to it."""
    fake = types.ModuleType("umap")
    fake.UMAP = umap_cls
    monkeypatch.setitem(sys.modules, "umap", fake)


def test_prewarm_returns_false_when_umap_missing(monkeypatch):
    """ImportError (optional extra absent) → False, never raises."""
    monkeypatch.delitem(sys.modules, "umap", raising=False)
    real_import = builtins.__import__

    def _raise_for_umap(name, *args, **kwargs):
        if name == "umap":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raise_for_umap)
    assert prewarm_umap() is False


def test_prewarm_swallows_fit_failure(monkeypatch):
    """Any exception inside the tiny fit → False (warm-up must never break startup)."""

    class _BrokenUMAP:
        def __init__(self, **_kwargs): ...

        def fit_transform(self, _x):
            raise RuntimeError("boom")

    _install_fake_umap(monkeypatch, _BrokenUMAP)
    assert prewarm_umap() is False


def test_prewarm_success_returns_true(monkeypatch):
    """A successful import+fit → True (lifespan logs the skip-Jit message)."""
    seen_kwargs: dict = {}

    class _FakeUMAP:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

        def fit_transform(self, x):
            assert isinstance(x, np.ndarray)
            return np.zeros((len(x), 2))

    _install_fake_umap(monkeypatch, _FakeUMAP)
    assert prewarm_umap() is True
    # The warm-up fit must mirror the real reducer's shape (cosine, 2D) so it
    # compiles the same jitted code paths the first real request will hit.
    assert seen_kwargs["metric"] == "cosine"
    assert seen_kwargs["n_components"] == 2


def test_lifespan_schedules_umap_prewarm_fire_and_forget():
    """The lifespan wiring must schedule the warm-up without awaiting it.

    Pins the startup contract behind the fast-first-UMAP-switch fix: the
    ``asyncio.to_thread`` wrapper is created (never blocked on) and the task
    reference lands on ``app.state`` so it cannot be GC'd mid-flight.
    """
    import asyncio
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from app.gateway.app import lifespan

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        yield

    startup_config = MagicMock()
    startup_config.log_level = "INFO"
    startup_config.memory.enabled = False
    fake_service = MagicMock()
    fake_service.get_status = MagicMock(return_value={})

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    app = FastAPI()

    async def drive() -> None:
        async with lifespan(app):
            # Inside the serving window the task must already exist and must
            # NOT have blocked startup (fire-and-forget, not awaited inline).
            assert hasattr(app.state, "umap_prewarm_task")

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.setup_monocle_tracing_if_enabled", MagicMock(return_value=False)),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.knowledge.projection.reducer.prewarm_umap", return_value=True),
    ):
        asyncio.run(drive())
