"""gRPC is selected explicitly; HTTP tracing does not depend on its runtime."""

import builtins
import os
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement
from pydantic import SecretStr


def _snapshot(transport="grpc"):
    provider = SimpleNamespace(provider="arize", endpoint="http://127.0.0.1:4317", project="test", space_id="space", public_key="", api_key=SecretStr("offline-test-key"), secret_key=None, transport=transport)
    return SimpleNamespace(snapshot_id="grpc-dependency-test", mode="configured", providers=(provider,), monocle_enabled=False)


@pytest.fixture
def missing_grpc(monkeypatch):
    original = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "grpc" or name.startswith("grpc."):
            raise ModuleNotFoundError("unavailable dependency: private-test-detail", name="grpc")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_grpc_exporter_missing_runtime_explains_the_optional_install(missing_grpc):
    from deerflow.tracing.otlp_exporter import IsolatedOtlpExporter

    with pytest.raises(RuntimeError, match=r"deerflow-harness\[tracing-grpc\]") as failure:
        IsolatedOtlpExporter(endpoint="http://127.0.0.1:4317", headers={}, transport="grpc")
    assert "uv sync --extra tracing-grpc" in str(failure.value)
    assert "private-test-detail" not in str(failure.value)


def test_session_preserves_the_missing_grpc_install_hint(missing_grpc):
    from deerflow.tracing.scoped import TracingSession

    with pytest.raises(RuntimeError, match=r"deerflow-harness\[tracing-grpc\]") as failure:
        TracingSession(_snapshot())
    assert "private-test-detail" not in str(failure.value)


def test_session_still_redacts_unrelated_initialization_errors(monkeypatch):
    from deerflow.tracing import scoped

    def fail(_config):
        raise RuntimeError("private-test-detail")

    monkeypatch.setattr(scoped, "_create_resource", fail)
    with pytest.raises(RuntimeError, match="Tracing exporter initialization failed") as failure:
        scoped.TracingSession(_snapshot("http"))
    assert "private-test-detail" not in str(failure.value)


def test_grpc_dependency_floor_applies_only_to_the_tracing_extra():
    project_file = Path(__file__).parents[1] / "packages/harness/pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    assert not any(Requirement(value).name == "grpcio" for value in project["dependencies"])
    grpc = [Requirement(value) for value in project["optional-dependencies"].get("tracing-grpc", ()) if Requirement(value).name == "grpcio"]
    assert len(grpc) == 1
    assert grpc[0].specifier.contains("1.80.0")
    assert not grpc[0].specifier.contains("1.79.0")


def test_gateway_tracing_extra_enables_the_harness_transport():
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    requirements = [Requirement(value) for value in project["optional-dependencies"].get("tracing-grpc", ())]
    assert len(requirements) == 1
    assert requirements[0].name == "deerflow-harness"
    assert "tracing-grpc" in requirements[0].extras


def test_http_export_works_when_every_grpc_import_is_unavailable(tmp_path):
    harness_dir = Path(__file__).parents[1] / "packages/harness"
    script = """
import builtins
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

original = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "grpc" or name.startswith("grpc."):
        raise AssertionError("HTTP tracing attempted to import grpc")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded_import

from deerflow.tracing.otlp_exporter import IsolatedOtlpExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

received = []
class Collector(BaseHTTPRequestHandler):
    def do_POST(self):
        received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
    def log_message(self, *_args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()
provider = TracerProvider(shutdown_on_exit=False)
exporter = IsolatedOtlpExporter(endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces", headers={}, transport="http")
provider.add_span_processor(SimpleSpanProcessor(exporter))
try:
    with provider.get_tracer("offline-test").start_as_current_span("http-without-grpc"):
        pass
    assert len(received) == 1 and received[0][0] == "/v1/traces" and received[0][1]
finally:
    provider.shutdown()
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)
"""
    env = {"PYTHONPATH": str(harness_dir)}
    if os.name == "nt" and "SystemRoot" in os.environ:
        env["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_grpc_export_reaches_a_real_local_collector():
    grpc = pytest.importorskip("grpc")
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from deerflow.tracing.otlp_exporter import IsolatedOtlpExporter

    received = []

    class Collector(trace_service_pb2_grpc.TraceServiceServicer):
        def Export(self, request, context):
            received.append((request, dict(context.invocation_metadata())))
            return trace_service_pb2.ExportTraceServiceResponse()

    with ThreadPoolExecutor(max_workers=1) as worker:
        server = grpc.server(worker)
        trace_service_pb2_grpc.add_TraceServiceServicer_to_server(Collector(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        provider = TracerProvider(shutdown_on_exit=False)
        exporter = IsolatedOtlpExporter(endpoint=f"http://127.0.0.1:{port}", headers={"space_id": "test-space", "api_key": "offline-test-key"}, transport="grpc")
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        try:
            with provider.get_tracer("offline-test").start_as_current_span("grpc-local-check"):
                pass
            assert len(received) == 1
            request, metadata = received[0]
            assert request.resource_spans[0].scope_spans[0].spans[0].name == "grpc-local-check"
            assert metadata["space_id"] == "test-space"
            assert metadata["api_key"] == "offline-test-key"
        finally:
            provider.shutdown()
            server.stop(0).wait(timeout=2)
