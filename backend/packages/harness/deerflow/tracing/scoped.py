"""Frozen run configuration and reference-counted, destination-local exporters."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import threading
from collections.abc import Mapping
from contextlib import ExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult

from deerflow.tracing.otlp_exporter import TracingGrpcDependencyError
from deerflow.utils.file_io import await_drained

if TYPE_CHECKING:
    from deerflow.tracing.profiles import ProviderConfig, RunTracingSnapshot

logger = logging.getLogger(__name__)
_snapshot: ContextVar[RunTracingSnapshot | None] = ContextVar("deerflow_tracing_snapshot", default=None)
_session: ContextVar[TracingSession | None] = ContextVar("deerflow_tracing_session", default=None)
_pool_lock = threading.RLock()
_pool: dict[str, list] = {}


def get_current_snapshot() -> RunTracingSnapshot | None:
    return _snapshot.get()


class ScopedRoutingSampler(Sampler):
    """Global auto-instrumentors observe only deployment-inherited runs."""

    def __init__(self, delegate: Sampler) -> None:
        self.delegate = delegate

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None):
        snapshot = get_current_snapshot()
        if snapshot is not None and (snapshot.mode != "inherit" or not snapshot.monocle_enabled):
            return SamplingResult(Decision.DROP)
        return self.delegate.should_sample(parent_context, trace_id, name, kind, attributes, links, trace_state)

    def get_description(self) -> str:
        return f"DeerFlowScoped({self.delegate.get_description()})"


def install_global_tracing_guard() -> bool:
    """Install once, before global instrumentation; never replace a live provider."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import _get_from_env_or_default
    from opentelemetry.trace import ProxyTracerProvider

    with _pool_lock:
        provider = trace.get_tracer_provider()
        if isinstance(getattr(provider, "sampler", None), ScopedRoutingSampler):
            return True
        if not isinstance(provider, ProxyTracerProvider):
            return False
        trace.set_tracer_provider(TracerProvider(sampler=ScopedRoutingSampler(_get_from_env_or_default())))
        return isinstance(getattr(trace.get_tracer_provider(), "sampler", None), ScopedRoutingSampler)


def is_global_tracing_guard_installed() -> bool:
    from opentelemetry import trace

    return isinstance(getattr(trace.get_tracer_provider(), "sampler", None), ScopedRoutingSampler)


def _secret(value) -> str:
    return value.get_secret_value() if value is not None else ""


def _key(config: ProviderConfig) -> str:
    values = [config.provider, config.endpoint, config.project, config.space_id, config.public_key, getattr(config, "workspace_id", ""), config.transport, _secret(config.api_key), _secret(config.secret_key)]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class OtelResource:
    def __init__(self, config: ProviderConfig, *, exporter=None, batch: bool = True) -> None:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON

        self.config = config
        self.spans = {}
        self.span_lock = threading.RLock()
        self.provider = TracerProvider(
            sampler=ALWAYS_ON, resource=Resource.create({"service.name": "deer-flow", "openinference.project.name": config.project or "deer-flow", "model_id": config.project or "deer-flow"}), shutdown_on_exit=False
        )
        if exporter is None:
            headers = {"space_id": config.space_id, "api_key": _secret(config.api_key)}
            endpoint = config.endpoint
            if config.provider == "langfuse":
                token = base64.b64encode(f"{config.public_key}:{_secret(config.secret_key)}".encode()).decode()
                headers = {"Authorization": f"Basic {token}"}
                endpoint = endpoint.rstrip("/") + "/api/public/otel/v1/traces"
            from deerflow.tracing.otlp_exporter import IsolatedOtlpExporter

            exporter = IsolatedOtlpExporter(endpoint=endpoint, headers=headers, transport=config.transport)

        class BoundedBatchSpanProcessor(BatchSpanProcessor):
            def shutdown(self):
                # SDK force_flush currently ignores its timeout. Shutdown's
                # bounded queue drain is the lifecycle boundary instead.
                self._batch_processor.shutdown(timeout_millis=2000)

        self.processor = BoundedBatchSpanProcessor(exporter, max_queue_size=512, max_export_batch_size=64, schedule_delay_millis=500, export_timeout_millis=2000) if batch else SimpleSpanProcessor(exporter)
        self.provider.add_span_processor(self.processor)

    def callback(self, snapshot, *, parent_context=None):
        from deerflow.tracing.otel_callback import OpenInferenceCallback

        return OpenInferenceCallback(self.provider.get_tracer("deerflow.langchain"), snapshot, langfuse=self.config.provider == "langfuse", spans=self.spans, lock=self.span_lock, parent_context=parent_context)

    def close(self):
        self.provider.shutdown()


class LangSmithResource:
    def __init__(self, config: ProviderConfig) -> None:
        from langsmith import Client

        self.config = config
        self.client = Client(api_url=config.endpoint, api_key=_secret(config.api_key), workspace_id=getattr(config, "workspace_id", ""), timeout_ms=2000, tracing_mode="langsmith", tracing_sampling_rate=1.0)

    def callback(self, snapshot, *, parent_context=None):
        from langchain_core.tracers.langchain import LangChainTracer
        from langsmith import tracing_context
        from langsmith.run_trees import RunTree

        snapshot_id = getattr(snapshot, "snapshot_id", None)
        destination_key = _key(self.config)
        parent = None
        if parent_context is not None:
            try:
                if not isinstance(parent_context, Mapping) or parent_context.get("snapshot_id") != snapshot_id or parent_context.get("destination_key") != destination_key:
                    raise ValueError()
                if any(not isinstance(parent_context.get(key), str) or not parent_context[key] for key in ("parent_run_id", "trace_id", "dotted_order")):
                    raise ValueError()
                parent = RunTree.from_dotted_order(parent_context["dotted_order"], client=self.client, project_name=self.config.project or "deer-flow", replicas=[])
                if str(parent.id) != parent_context["parent_run_id"] or str(parent.trace_id) != parent_context["trace_id"]:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ValueError("Invalid LangSmith parent tracing context") from None

        class PrivateLangChainTracer(LangChainTracer):
            deerflow_scoped_tracing = True
            _deerflow_snapshot_id = snapshot_id
            _deerflow_destination_key = destination_key

            def _start_trace(self, run):
                if parent is not None and run.parent_run_id is None:
                    run.parent_run_id = parent.id
                run.replicas = []
                with tracing_context(enabled=True, client=self.client, parent=False, replicas=[]):
                    super()._start_trace(run)

        order_map = {parent.id: (parent.trace_id, parent.dotted_order)} if parent is not None else None
        return PrivateLangChainTracer(project_name=self.config.project or "deer-flow", client=self.client, order_map=order_map)

    def close(self):
        self.client.flush(timeout=2)
        self.client.close(timeout=2)


def _create_resource(config: ProviderConfig):
    return LangSmithResource(config) if config.provider == "langsmith" else OtelResource(config)


def _release(key: str, snapshot_id: str) -> None:
    resource = None
    with _pool_lock:
        entry = _pool.get(key)
        if entry is None:
            return
        entry[1] -= 1
        entry[2][snapshot_id] -= 1
        if entry[2][snapshot_id] == 0:
            del entry[2][snapshot_id]
            if isinstance(entry[0], OtelResource):
                with entry[0].span_lock:
                    for span_key in [item for item in entry[0].spans if item[0] == snapshot_id]:
                        del entry[0].spans[span_key]
        if entry[1] == 0:
            resource = _pool.pop(key)[0]
    if resource is not None:
        try:
            resource.close()
        except Exception as exc:
            logger.warning("Tracing exporter drain failed (%s)", type(exc).__name__)


class TracingSession:
    """Hold exporter leases while ContextVars are activated per execution step."""

    def __init__(self, snapshot: RunTracingSnapshot | None, *, parent_contexts: dict | None = None) -> None:
        self.snapshot = snapshot
        self.parent_contexts = parent_contexts or {}
        self.resources = []
        self._keys: list[str] = []
        self._closed = False
        if snapshot is not None:
            from deerflow.tracing.profiles import validate_snapshot_environment

            validate_snapshot_environment(snapshot)
        if snapshot is None or snapshot.mode == "disabled":
            return
        try:
            with _pool_lock:
                for config in snapshot.providers:
                    key = _key(config)
                    if key not in _pool:
                        _pool[key] = [_create_resource(config), 0, {}]
                    _pool[key][1] += 1
                    leases = _pool[key][2]
                    leases[snapshot.snapshot_id] = leases.get(snapshot.snapshot_id, 0) + 1
                    self._keys.append(key)
                    self.resources.append(_pool[key][0])
        except TracingGrpcDependencyError:
            self.close()
            raise
        except Exception:
            self.close()
            raise RuntimeError("Tracing exporter initialization failed") from None

    @contextmanager
    def activate(self):
        if self._closed:
            raise RuntimeError("Tracing session is closed")
        snapshot_token = _snapshot.set(self.snapshot)
        session_token = _session.set(self)
        try:
            with ExitStack() as stack:
                if self.snapshot is not None:
                    from langchain_core.runnables.config import var_child_runnable_config
                    from langchain_core.tracers.context import tracing_v2_callback_var
                    from langsmith import tracing_context

                    inherited = var_child_runnable_config.get()
                    if inherited:
                        sanitized = dict(inherited)
                        callbacks = sanitized.get("callbacks")
                        if isinstance(callbacks, list):
                            sanitized["callbacks"] = [handler for handler in callbacks if not _is_provider_callback(handler)]
                        elif hasattr(callbacks, "handlers"):
                            callbacks = callbacks.copy()
                            callbacks.handlers = [handler for handler in callbacks.handlers if not _is_provider_callback(handler)]
                            callbacks.inheritable_handlers = [handler for handler in callbacks.inheritable_handlers if not _is_provider_callback(handler)]
                            sanitized["callbacks"] = callbacks
                        elif callbacks is not None and _is_provider_callback(callbacks):
                            sanitized["callbacks"] = []
                        config_token = var_child_runnable_config.set(sanitized)
                        stack.callback(var_child_runnable_config.reset, config_token)
                    tracer_token = tracing_v2_callback_var.set(None)
                    stack.callback(tracing_v2_callback_var.reset, tracer_token)
                    stack.enter_context(tracing_context(enabled=False, parent=False, replicas=[]))
                yield self
        finally:
            _session.reset(session_token)
            _snapshot.reset(snapshot_token)

    def callbacks(self) -> list:
        return [resource.callback(self.snapshot, parent_context=self.parent_contexts.get(resource.config.provider)) for resource in self.resources]

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for key in self._keys:
                _release(key, self.snapshot.snapshot_id)
            self._keys.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


@contextmanager
def tracing_scope(snapshot: RunTracingSnapshot | None, *, parent_contexts: dict | None = None):
    with TracingSession(snapshot, parent_contexts=parent_contexts) as session, session.activate():
        yield session


@asynccontextmanager
async def async_tracing_scope(snapshot: RunTracingSnapshot | None, *, parent_contexts: dict | None = None):
    """Offload fingerprint/exporter I/O while binding ContextVars on the caller task."""
    session = None

    def construct():
        nonlocal session
        # Preserve ownership if cancellation drains construction but discards
        # its return value before the caller can enter the scope.
        session = TracingSession(snapshot, parent_contexts=parent_contexts)

    try:
        await await_drained(asyncio.to_thread(construct))
        with session.activate():
            yield session
    finally:
        if session is not None:
            await await_drained(asyncio.to_thread(session.close))


def _is_provider_callback(handler) -> bool:
    from langchain_core.tracers.langchain import LangChainTracer

    return bool(getattr(handler, "deerflow_scoped_tracing", False)) or isinstance(handler, LangChainTracer) or type(handler).__module__.startswith("langfuse.")


def capture_tracing_parent_context() -> dict[str, dict]:
    """Non-secret transport contexts for delayed or cross-process children."""
    from langchain_core.runnables.config import var_child_runnable_config

    session = _session.get()
    if session is None or session.snapshot is None:
        return {}
    inherited = var_child_runnable_config.get() or {}
    callbacks = inherited.get("callbacks")
    parent_run_id = getattr(callbacks, "parent_run_id", None)
    handlers = getattr(callbacks, "handlers", callbacks if isinstance(callbacks, (list, tuple)) else ())
    result = {}
    for resource in session.resources:
        if isinstance(resource, OtelResource):
            with resource.span_lock:
                parent = resource.spans.get((session.snapshot.snapshot_id, parent_run_id)) if parent_run_id else None
                if parent_run_id is None:
                    candidates = [span for key, span in resource.spans.items() if key[0] == session.snapshot.snapshot_id]
                    parent = candidates[0] if len(candidates) == 1 else None
                if parent is not None:
                    context = parent.get_span_context()
                    result[resource.config.provider] = {"trace_id": format(context.trace_id, "032x"), "span_id": format(context.span_id, "016x"), "trace_flags": int(context.trace_flags)}
        elif isinstance(resource, LangSmithResource):
            destination_key = _key(resource.config)
            for handler in handlers:
                if getattr(handler, "_deerflow_snapshot_id", None) != session.snapshot.snapshot_id or getattr(handler, "_deerflow_destination_key", None) != destination_key:
                    continue
                parent_id = parent_run_id
                if parent_id is None:
                    active = tuple(handler.run_map.values())
                    parent_id = active[0].id if len(active) == 1 else None
                order = handler.order_map.get(parent_id)
                if order is not None:
                    result["langsmith"] = {
                        "snapshot_id": session.snapshot.snapshot_id,
                        "destination_key": destination_key,
                        "parent_run_id": str(parent_id),
                        "trace_id": str(order[0]),
                        "dotted_order": order[1],
                    }
                    break
    return result


def build_scoped_callbacks() -> list | None:
    session = _session.get()
    return session.callbacks() if session is not None and session.snapshot is not None else None


def shutdown_tracing_exporters() -> None:
    """Drain unused resources; live run leases retain ownership until close."""
    with _pool_lock:
        resources = [_pool.pop(key)[0] for key, entry in list(_pool.items()) if entry[1] <= 0]
    for resource in resources:
        resource.close()
