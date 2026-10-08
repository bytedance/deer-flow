"""Tests for the multi-worker Postgres startup gate.

Pins the contract documented in ``docs/multi_worker.md`` work item 1
(issue #3948): when ``GATEWAY_WORKERS > 1`` and the configured
database backend is not Postgres, the Gateway must refuse to start.
The gate runs inside :func:`langgraph_runtime` *before* any
persistence engine is initialised so operators see a clear error
instead of intermittent SQLite ``database is locked`` failures in
production.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.gateway.deps import _enforce_postgres_for_multi_worker, _validate_agent_storage, _validate_login_throttle_storage, langgraph_runtime
from app.gateway.routers.browser import _browser_tools_enabled
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.deployment_config import MULTI_INSTANCE_ENV_VAR, DeploymentConfig, multi_instance_declaration
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig


def _config_with_backend(
    backend: str,
    *,
    heartbeat_enabled: bool | None = None,
    browser_enabled: bool = False,
    run_events_backend: str = "db",
    scheduler_enabled: bool = False,
    scheduler_multi_instance: bool = False,
    deployment_multi_instance: bool = False,
    stream_bridge_type: str | None = None,
    ownership_type: str | None = None,
) -> SimpleNamespace:
    run_ownership = RunOwnershipConfig(heartbeat_enabled=heartbeat_enabled) if heartbeat_enabled is not None else None
    tools = [SimpleNamespace(name="browser_navigate")] if browser_enabled else []
    stream_bridge = StreamBridgeConfig(type=stream_bridge_type) if stream_bridge_type is not None else None
    ownership = SimpleNamespace(type=ownership_type) if ownership_type is not None else None
    return SimpleNamespace(
        database=DatabaseConfig(backend=backend),
        run_ownership=run_ownership,
        run_events=SimpleNamespace(backend=run_events_backend),
        scheduler=SimpleNamespace(enabled=scheduler_enabled, multi_instance=scheduler_multi_instance),
        tools=tools,
        deployment=DeploymentConfig(multi_instance=deployment_multi_instance),
        stream_bridge=stream_bridge,
        sandbox=SimpleNamespace(ownership=ownership),
    )


def _cluster_ready(**overrides):
    """A Postgres deployment with every multi-instance prerequisite satisfied."""
    kwargs = dict(heartbeat_enabled=True, stream_bridge_type="redis")
    kwargs.update(overrides)
    return _config_with_backend("postgres", **kwargs)


@pytest.fixture(autouse=True)
def isolated_worker_env(monkeypatch):
    """Keep the suite independent of the invoking shell's worker count.

    Several tests here assert that the gate stays inert, which only holds when
    no worker count is set at all. ``WEB_CONCURRENCY`` is the count uvicorn takes
    on the launches that pass no ``--workers``, so an exported value in the
    invoking shell would otherwise turn these inert-gate expectations into
    refusals.
    """
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv(MULTI_INSTANCE_ENV_VAR, raising=False)
    monkeypatch.delenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", raising=False)


# ---------------------------------------------------------------------------
# Unit tests of the gate function itself
# ---------------------------------------------------------------------------


def test_gate_noop_when_gateway_workers_unset(monkeypatch):
    """With GATEWAY_WORKERS unset, every backend must be accepted."""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


def test_gate_noop_for_single_worker(monkeypatch):
    """GATEWAY_WORKERS=1 preserves the historical single-worker behavior."""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    for backend in ("sqlite", "memory", "postgres"):
        _enforce_postgres_for_multi_worker(_config_with_backend(backend))


# ---------------------------------------------------------------------------
# Uvicorn's WEB_CONCURRENCY fallback also starts several worker processes
# ---------------------------------------------------------------------------


def test_gate_rejects_multi_worker_from_uvicorn_worker_fallback(monkeypatch):
    """WEB_CONCURRENCY=N starts N workers even with GATEWAY_WORKERS unset.

    ``backend/Dockerfile`` and ``scripts/serve.sh`` launch uvicorn with no
    ``--workers``, so uvicorn takes the count from ``WEB_CONCURRENCY``.
    """
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "requires database.backend='postgres'" in str(exc_info.value)


def test_gate_rejects_scheduler_duplication_from_uvicorn_worker_fallback(monkeypatch):
    """Each of those workers starts its own scheduler, which the gate exists to refuse."""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", scheduler_enabled=True))
    assert "each worker starts its own scheduler" in str(exc_info.value)


def test_gate_rejects_process_local_browser_from_uvicorn_worker_fallback(monkeypatch):
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(SystemExit, match="process-local"):
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True, browser_enabled=True))


def test_gate_reads_uvicorn_worker_fallback_when_gateway_workers_is_blank(monkeypatch):
    """A blank GATEWAY_WORKERS means unset, exactly as the compose default treats it."""
    monkeypatch.setenv("GATEWAY_WORKERS", "")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_unparsable_gateway_workers_does_not_mask_uvicorn_worker_fallback(monkeypatch):
    """A non-numeric documented knob must not report one worker while uvicorn starts four.

    The launchers that pass no ``--workers`` (``backend/Dockerfile``, ``scripts/serve.sh``,
    ``backend/Makefile gateway``) take the count from ``WEB_CONCURRENCY`` alone, so there
    ``GATEWAY_WORKERS=abc`` never reaches uvicorn at all.
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "abc")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "WEB_CONCURRENCY=4" in str(exc_info.value), "must name the variable that actually set the count"


def test_unparsable_gateway_workers_does_not_mask_the_browser_gate(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "auto")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    config = _config_with_backend("postgres", heartbeat_enabled=True, browser_enabled=True)
    with pytest.raises(SystemExit, match="process-local"):
        _enforce_postgres_for_multi_worker(config)


def test_agent_storage_warning_names_the_fallback_when_the_knob_is_unparsable(monkeypatch, caplog):
    monkeypatch.setenv("GATEWAY_WORKERS", "auto")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with caplog.at_level("WARNING"):
        _validate_agent_storage(_config_with_backend("postgres", heartbeat_enabled=True))
    messages = [r.message for r in caplog.records if "not visible across workers" in r.message]
    assert messages and "WEB_CONCURRENCY=2" in messages[0]


def test_gate_accepts_single_worker_from_uvicorn_worker_fallback(monkeypatch):
    """WEB_CONCURRENCY=1 is a single worker, so the gate stays inert."""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    for value in ("1", "0", ""):
        monkeypatch.setenv("WEB_CONCURRENCY", value)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", scheduler_enabled=True))


def test_gate_prefers_gateway_workers_over_uvicorn_worker_fallback(monkeypatch):
    """An explicit GATEWAY_WORKERS wins: uvicorn ignores WEB_CONCURRENCY when --workers is passed.

    ``docker/docker-compose.yaml`` always passes ``--workers ${GATEWAY_WORKERS:-1}``.
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", scheduler_enabled=True))


def test_agent_storage_warning_names_the_variable_that_set_the_count(monkeypatch, caplog):
    """The divergence warning must be actionable for a WEB_CONCURRENCY deployment."""
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with caplog.at_level("WARNING"):
        _validate_agent_storage(_config_with_backend("postgres", heartbeat_enabled=True))
    messages = [r.message for r in caplog.records if "not visible across workers" in r.message]
    assert messages and "WEB_CONCURRENCY=2" in messages[0]


def test_gate_allows_multi_worker_with_postgres_and_heartbeat(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True, stream_bridge_type="redis"))


def test_gate_rejects_multi_worker_with_scheduler_enabled(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "postgres",
                heartbeat_enabled=True,
                scheduler_enabled=True,
            )
        )
    msg = str(exc_info.value)
    assert "scheduler.multi_instance=true" in msg
    assert "GATEWAY_WORKERS=1" in msg
    assert "scheduler.enabled=false" in msg


def test_gate_allows_single_worker_with_scheduler_enabled(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(
        _config_with_backend("sqlite", scheduler_enabled=True),
    )


def test_gate_allows_multi_instance_scheduler_with_single_worker(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(
        _config_with_backend(
            "postgres",
            heartbeat_enabled=True,
            scheduler_enabled=True,
            scheduler_multi_instance=True,
        )
    )


def test_gate_allows_multi_instance_scheduler_with_multiple_workers(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    _enforce_postgres_for_multi_worker(
        _config_with_backend(
            "postgres",
            heartbeat_enabled=True,
            scheduler_enabled=True,
            scheduler_multi_instance=True,
            stream_bridge_type="redis",
        )
    )


def test_gate_rejects_multi_instance_scheduler_without_postgres(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit, match="database.backend='postgres'"):
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "sqlite",
                heartbeat_enabled=True,
                scheduler_enabled=True,
                scheduler_multi_instance=True,
            )
        )


def test_gate_rejects_unsafe_multi_instance_config_even_when_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit, match="database.backend='postgres'"):
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "sqlite",
                heartbeat_enabled=True,
                scheduler_enabled=False,
                scheduler_multi_instance=True,
            )
        )


def test_gate_rejects_multi_instance_scheduler_without_heartbeat(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit, match="heartbeat_enabled=true"):
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "postgres",
                heartbeat_enabled=False,
                scheduler_enabled=True,
                scheduler_multi_instance=True,
            )
        )


def test_gate_rejects_multi_instance_scheduler_with_process_local_events(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit, match="run_events.backend='db'"):
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "postgres",
                heartbeat_enabled=True,
                run_events_backend="memory",
                scheduler_enabled=True,
                scheduler_multi_instance=True,
            )
        )


@pytest.mark.parametrize("run_events_backend", ["memory", "jsonl"])
def test_gate_rejects_process_local_run_events_with_multi_worker(monkeypatch, run_events_backend):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "postgres",
                heartbeat_enabled=True,
                run_events_backend=run_events_backend,
            )
        )
    msg = str(exc_info.value)
    assert "run_events.backend='db'" in msg
    assert run_events_backend in msg
    assert "GATEWAY_WORKERS=1" in msg


def test_gate_allows_process_local_run_events_for_single_worker(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    for run_events_backend in ("memory", "jsonl"):
        _enforce_postgres_for_multi_worker(
            _config_with_backend(
                "sqlite",
                run_events_backend=run_events_backend,
            )
        )


def test_gate_rejects_process_local_browser_with_multi_worker(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(
            _config_with_backend("postgres", heartbeat_enabled=True, browser_enabled=True),
        )
    msg = str(exc_info.value)
    assert "process-local" in msg
    assert "GATEWAY_WORKERS=1" in msg


def test_runtime_browser_surface_stays_disabled_after_incompatible_hot_reload(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    live_config = SimpleNamespace(tools=[SimpleNamespace(name="browser_navigate", model_extra={})])

    with patch("deerflow.config.get_app_config", return_value=live_config):
        assert _browser_tools_enabled() is False


def test_gate_rejects_multi_worker_with_sqlite(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=2" in msg
    assert "postgres" in msg.lower()
    assert "sqlite" in msg.lower()


def test_gate_rejects_multi_worker_with_memory(monkeypatch):
    """The gate is not sqlite-specific: memory is also unsafe across processes."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(_config_with_backend("memory"))


def test_gate_rejects_high_worker_counts(monkeypatch):
    """The threshold is >1, not ==2; prod-scale counts must also be gated."""
    monkeypatch.setenv("GATEWAY_WORKERS", "4")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "GATEWAY_WORKERS=4" in str(exc_info.value)


def test_gate_treats_invalid_env_as_single_worker(monkeypatch):
    """Non-integer GATEWAY_WORKERS values must not crash startup.

    Uvicorn itself rejects these later; the gate should not preempt
    that with its own crash. The count is then taken from the remaining
    spellings, and with no other variable set the gate stays inert.
    """
    for invalid in ("", "auto", "1.5", "abc", "0x4"):
        monkeypatch.setenv("GATEWAY_WORKERS", invalid)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_treats_zero_and_negatives_as_single_worker(monkeypatch):
    """GATEWAY_WORKERS <= 1 (including 0 and negatives) skips the gate."""
    for value in ("0", "-1", "-999"):
        monkeypatch.setenv("GATEWAY_WORKERS", value)
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))


def test_gate_error_message_lists_both_remediations(monkeypatch):
    """Operators must see both fix options without reading docs."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert "GATEWAY_WORKERS=1" in msg, "must mention the rollback knob"
    assert "Postgres" in msg, "must mention the alternative backend"


# ---------------------------------------------------------------------------
# Heartbeat enforcement: multi-worker requires heartbeat_enabled=true
# ---------------------------------------------------------------------------


def test_gate_rejects_multi_worker_without_heartbeat(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_rejects_multi_worker_without_run_ownership_config(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=None))
    msg = str(exc_info.value)
    assert "heartbeat_enabled=true" in msg


def test_gate_heartbeat_check_not_triggered_for_single_worker(monkeypatch):
    """GATEWAY_WORKERS=1 skips the heartbeat check entirely."""
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=False))


def test_gate_heartbeat_check_not_triggered_for_sqlite(monkeypatch):
    """The gate exits on Postgres check before reaching heartbeat check."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", heartbeat_enabled=True))
    msg = str(exc_info.value)
    assert "postgres" in msg.lower()


# ---------------------------------------------------------------------------
# Integration: the gate is wired into langgraph_runtime before init_engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_langgraph_runtime_invokes_gate_before_persistence_setup(monkeypatch):
    """When the gate trips, no persistence / stream-bridge setup may run.

    Guards against regressions that reorder the gate behind
    ``init_engine_from_config`` (or any other expensive startup step).
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "2")

    init_engine_from_config = AsyncMock(name="init_engine_from_config")

    @asynccontextmanager
    async def _noop_stream_bridge(_config):
        yield MagicMock()

    with (
        patch(
            "deerflow.persistence.engine.init_engine_from_config",
            init_engine_from_config,
        ),
        patch("deerflow.runtime.make_stream_bridge", side_effect=_noop_stream_bridge) as make_stream_bridge,
        patch("deerflow.runtime.make_store", side_effect=_noop_stream_bridge) as make_store,
    ):
        app = FastAPI()
        startup_config = _config_with_backend("sqlite")
        with pytest.raises(SystemExit):
            async with langgraph_runtime(app, startup_config):
                pass

    init_engine_from_config.assert_not_called()
    make_stream_bridge.assert_not_called()
    make_store.assert_not_called()


# ---------------------------------------------------------------------------
# Cross-process stream bridge: multi-worker now needs it too
# ---------------------------------------------------------------------------


def test_multi_worker_requires_a_cross_process_stream_bridge(monkeypatch):
    """GATEWAY_WORKERS > 1 with the memory bridge used to start and then 409 every SSE join on a peer."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    for bridge in (None, "memory"):
        with pytest.raises(SystemExit, match="stream_bridge.type='redis'"):
            _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True, stream_bridge_type=bridge))


def test_multi_worker_accepts_the_env_redis_stream_bridge(monkeypatch):
    """docker-compose and the Helm chart inject DEER_FLOW_STREAM_BRIDGE_REDIS_URL instead of a config section."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://redis:6379/0")
    _enforce_postgres_for_multi_worker(_config_with_backend("postgres", heartbeat_enabled=True))


def test_multi_worker_rejects_explicit_memory_sandbox_ownership(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit, match="sandbox.ownership.type='memory'"):
        _enforce_postgres_for_multi_worker(_cluster_ready(ownership_type="memory"))


# ---------------------------------------------------------------------------
# Explicit multi-instance declaration: Kubernetes replicas run one worker per Pod
# ---------------------------------------------------------------------------


def test_declared_multi_instance_is_gated_with_a_single_worker(monkeypatch):
    """replicas > 1 with GATEWAY_WORKERS=1 per Pod must not bypass the gate.

    Without the declaration every Pod reports one worker, passes every check,
    and its startup orphan reconciliation writes the peers' lease-less runs off
    as crashed on every rolling update.
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", deployment_multi_instance=True))
    msg = str(exc_info.value)
    assert "deployment.multi_instance=true" in msg
    assert "requires database.backend='postgres'" in msg
    assert "deployment.multi_instance=false" in msg, "must name the rollback knob"


def test_declared_multi_instance_accepts_a_fully_shared_deployment(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True))


def test_declared_multi_instance_requires_heartbeat():
    with pytest.raises(SystemExit, match="heartbeat_enabled=true"):
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, heartbeat_enabled=False))


@pytest.mark.parametrize("run_events_backend", ["memory", "jsonl"])
def test_declared_multi_instance_requires_db_run_events(run_events_backend):
    with pytest.raises(SystemExit, match="run_events.backend='db'"):
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, run_events_backend=run_events_backend))


def test_declared_multi_instance_requires_a_redis_stream_bridge():
    """The memory bridge is process-local, so a peer never sees the owner's SSE events."""
    for bridge in (None, "memory"):
        with pytest.raises(SystemExit, match="stream_bridge.type='redis'"):
            _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, stream_bridge_type=bridge))


def test_declared_multi_instance_accepts_the_env_redis_stream_bridge(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://redis:6379/0")
    _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, stream_bridge_type=None))


def test_declared_multi_instance_rejects_explicit_memory_sandbox_ownership():
    with pytest.raises(SystemExit, match="sandbox.ownership.type='memory'"):
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, ownership_type="memory"))


def test_declared_multi_instance_accepts_redis_or_inferred_sandbox_ownership():
    """An omitted ownership section is inferred from the redis stream bridge (ownership/factory.py)."""
    for ownership in (None, "redis"):
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, ownership_type=ownership))


def test_declared_multi_instance_rejects_single_instance_scheduler():
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, scheduler_enabled=True))
    msg = str(exc_info.value)
    assert "each worker starts its own scheduler" in msg
    assert "scheduler.multi_instance=true" in msg
    assert "deployment.multi_instance=false" in msg


def test_declared_multi_instance_accepts_multi_instance_scheduler():
    _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, scheduler_enabled=True, scheduler_multi_instance=True))


def test_declared_multi_instance_rejects_process_local_browser():
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_cluster_ready(deployment_multi_instance=True, browser_enabled=True))
    msg = str(exc_info.value)
    assert "process-local" in msg
    assert "deployment.multi_instance=false" in msg


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on", "replicas"])
def test_env_declaration_is_gated(monkeypatch, value):
    """DEER_FLOW_MULTI_INSTANCE is what deploy tooling sets from the replica count.

    Any spelling that is not an explicit "off" counts: a typo must fail closed
    (run the gate) rather than silently disable it.
    """
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, value)
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    msg = str(exc_info.value)
    assert f"{MULTI_INSTANCE_ENV_VAR}={value}" in msg
    assert f"Unset {MULTI_INSTANCE_ENV_VAR}" in msg, "must name the rollback knob"


@pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off", "  "])
def test_falsy_env_declaration_stays_inert(monkeypatch, value):
    """A templated DEER_FLOW_MULTI_INSTANCE=false (one replica) must not trip the gate."""
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, value)
    _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", scheduler_enabled=True))


def test_env_declaration_accepts_a_fully_shared_deployment(monkeypatch):
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    _enforce_postgres_for_multi_worker(_cluster_ready())


def test_worker_count_is_reported_over_the_declaration(monkeypatch):
    """When both apply, the refusal names the worker count: that is the knob uvicorn acts on."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite"))
    assert "GATEWAY_WORKERS=2" in str(exc_info.value)


@pytest.mark.parametrize(
    ("declared_by", "expected_rollback"),
    [
        ("env", f"Set GATEWAY_WORKERS=1 and unset {MULTI_INSTANCE_ENV_VAR}"),
        ("config", "Set GATEWAY_WORKERS=1 and set deployment.multi_instance=false"),
    ],
)
def test_worker_count_rollback_also_withdraws_the_declaration(monkeypatch, declared_by, expected_rollback):
    """With both knobs active, a rollback that only resets the worker count is not enough.

    Following ``Set GATEWAY_WORKERS=1`` alone leaves the declaration tripping the
    gate at the next start, so the operator would bounce through a second
    refusal before learning about the other knob. The message names both.
    """
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    if declared_by == "env":
        monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    config = _config_with_backend("sqlite", deployment_multi_instance=declared_by == "config")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(config)
    assert expected_rollback in str(exc_info.value)


def test_offered_env_rollback_clears_the_gate(monkeypatch):
    """The remediation a refusal offers must make the next start succeed."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    sqlite = _config_with_backend("sqlite")
    with pytest.raises(SystemExit):
        _enforce_postgres_for_multi_worker(sqlite)

    # Resetting only the worker count is the half-step the message must not suggest.
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(sqlite)
    assert f"{MULTI_INSTANCE_ENV_VAR}=1" in str(exc_info.value)

    # The full rollback the message offered clears the gate.
    monkeypatch.delenv(MULTI_INSTANCE_ENV_VAR)
    _enforce_postgres_for_multi_worker(sqlite)


def test_offered_config_rollback_clears_the_gate(monkeypatch):
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", deployment_multi_instance=True))
    assert "Set GATEWAY_WORKERS=1 and set deployment.multi_instance=false" in str(exc_info.value)

    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    _enforce_postgres_for_multi_worker(_config_with_backend("sqlite", deployment_multi_instance=False))


def test_browser_refusal_names_the_declaration_when_both_knobs_are_active(monkeypatch):
    """The browser refusal must not send the operator through the same double bounce."""
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    with pytest.raises(SystemExit) as exc_info:
        _enforce_postgres_for_multi_worker(_cluster_ready(browser_enabled=True))
    msg = str(exc_info.value)
    assert "browser" in msg
    assert f"Set GATEWAY_WORKERS=1 and unset {MULTI_INSTANCE_ENV_VAR}" in msg


def test_agent_storage_warning_fires_for_a_declared_multi_instance_deployment(caplog):
    with caplog.at_level("WARNING"):
        _validate_agent_storage(_cluster_ready(deployment_multi_instance=True))
    messages = [r.message for r in caplog.records if "not visible across workers" in r.message]
    assert messages and "deployment.multi_instance=true" in messages[0]


def test_deployment_declaration_helpers(monkeypatch):
    assert DeploymentConfig().multi_instance is False
    assert multi_instance_declaration(None) is None

    by_config = multi_instance_declaration(SimpleNamespace(deployment=DeploymentConfig(multi_instance=True)))
    assert by_config is not None
    assert (by_config.source, by_config.knob, by_config.rollback) == ("config", "deployment.multi_instance=true", "set deployment.multi_instance=false")
    assert str(by_config) == by_config.knob

    # The environment wins over config.yaml and keeps the operator's spelling.
    monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "replicas")
    by_env = multi_instance_declaration(SimpleNamespace(deployment=DeploymentConfig(multi_instance=True)))
    assert by_env is not None
    assert (by_env.source, by_env.knob, by_env.rollback) == ("env", f"{MULTI_INSTANCE_ENV_VAR}=replicas", f"unset {MULTI_INSTANCE_ENV_VAR}")


# ---------------------------------------------------------------------------
# Login throttle storage warning (auth.local.throttle_storage)
# ---------------------------------------------------------------------------


def _with_throttle_storage(config, selector):
    config.auth = SimpleNamespace(local=SimpleNamespace(throttle_storage=selector))
    return config


def _throttle_warnings(caplog):
    return [r.message for r in caplog.records if "auth.local.throttle_storage" in r.message]


def test_login_throttle_warning_fires_for_a_declared_multi_instance_deployment_on_memory(caplog):
    """Explicit memory counters under N replicas hand an attacker N x max_login_attempts guesses."""
    from deerflow.config.auth_config import LoginThrottleStorage

    with caplog.at_level("WARNING"):
        _validate_login_throttle_storage(_with_throttle_storage(_cluster_ready(deployment_multi_instance=True), LoginThrottleStorage.MEMORY))
    messages = _throttle_warnings(caplog)
    assert messages and "deployment.multi_instance=true" in messages[0]
    assert "max_login_attempts" in messages[0]
    # The selector is a StrEnum; the warning must render its value, not "LoginThrottleStorage.MEMORY".
    assert "auth.local.throttle_storage=memory:" in messages[0]
    assert "LoginThrottleStorage" not in messages[0]


def test_login_throttle_warning_names_the_worker_variable(monkeypatch, caplog):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with caplog.at_level("WARNING"):
        _validate_login_throttle_storage(_with_throttle_storage(_cluster_ready(), "memory"))
    messages = _throttle_warnings(caplog)
    assert messages and "WEB_CONCURRENCY=2" in messages[0]


def test_login_throttle_auto_resolves_to_the_database_under_multi_instance_without_warning(caplog):
    with caplog.at_level("WARNING"):
        _validate_login_throttle_storage(_with_throttle_storage(_cluster_ready(deployment_multi_instance=True), "auto"))
        _validate_login_throttle_storage(_with_throttle_storage(_cluster_ready(deployment_multi_instance=True), "db"))
    assert _throttle_warnings(caplog) == []


def test_login_throttle_memory_is_silent_for_a_single_instance(caplog):
    with caplog.at_level("WARNING"):
        _validate_login_throttle_storage(_with_throttle_storage(_config_with_backend("sqlite"), "memory"))
    assert _throttle_warnings(caplog) == []


def test_login_throttle_gate_tolerates_a_config_without_an_auth_section(caplog):
    with caplog.at_level("WARNING"):
        _validate_login_throttle_storage(_cluster_ready(deployment_multi_instance=True))
    assert _throttle_warnings(caplog) == []
