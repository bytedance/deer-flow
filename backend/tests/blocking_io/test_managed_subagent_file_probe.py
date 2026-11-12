"""The startup volume probe runs once, off the Gateway event loop."""

from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI

from app.gateway import deps
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths


class _ReachedNextStartupCheck(Exception):
    pass


@pytest.fixture
def volume_paths(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    return paths


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", [None, "file", "db"], ids=["default-file", "explicit-file", "database"])
async def test_lifespan_probes_only_file_storage_off_loop(volume_paths, monkeypatch, backend):
    for name in ("GATEWAY_WORKERS", "WEB_CONCURRENCY", "DEER_FLOW_MULTI_INSTANCE"):
        monkeypatch.delenv(name, raising=False)
    paths = volume_paths
    config = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, database={"backend": "sqlite"})
    if backend is not None:
        config.agent_storage.backend = backend
    loop_thread = threading.get_ident()
    probe_threads = []
    original_link = deps.os.link

    def observed_link(source, destination):
        probe_threads.append(threading.get_ident())
        original_link(source, destination)

    def reached_next_check(_config):
        raise _ReachedNextStartupCheck

    monkeypatch.setattr(deps.os, "link", observed_link)
    # Stop after the real startup probe, before opening any runtime resources.
    monkeypatch.setattr(deps, "_validate_login_throttle_storage", reached_next_check)
    with pytest.raises(_ReachedNextStartupCheck):
        async with deps.langgraph_runtime(FastAPI(), config):
            pytest.fail("the following startup check must abort this focused test")

    if backend == "db":
        assert probe_threads == []
        assert not paths.managed_subagents_dir.exists()
    else:
        assert len(probe_threads) == 1
        assert probe_threads[0] != loop_thread
        assert list(paths.managed_subagents_dir.iterdir()) == []
