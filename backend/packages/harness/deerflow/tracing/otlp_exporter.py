"""OTLP transport with explicit headers and no ambient exporter configuration."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


class TracingGrpcDependencyError(RuntimeError):
    """A fixed installation hint safe to expose through run initialization."""

    def __init__(self) -> None:
        super().__init__("gRPC tracing requires the tracing-grpc extra. In backend/, run `uv sync --extra tracing-grpc`, or install `pip install 'deerflow-harness[tracing-grpc]'`.")


class IsolatedOtlpExporter(SpanExporter):
    """Send one bounded batch only to the profile's endpoint and credentials."""

    def __init__(self, *, endpoint: str, headers: dict[str, str], transport: str) -> None:
        self.endpoint = endpoint
        self.headers = headers
        self.transport = transport
        self._session = None
        self._channel = None
        self._stub = None
        if transport == "grpc":
            try:
                import grpc
                from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import TraceServiceStub
            except (ImportError, RuntimeError):
                raise TracingGrpcDependencyError() from None

            parsed = urlsplit(endpoint)
            self._channel = grpc.secure_channel(parsed.netloc, grpc.ssl_channel_credentials()) if parsed.scheme == "https" else grpc.insecure_channel(parsed.netloc)
            self._stub = TraceServiceStub(self._channel)
        else:
            self._session = requests.Session()
            # Retain deployment proxy/TLS policy, but prevent .netrc auth from
            # replacing the explicitly selected profile's authentication.
            self._session.auth = lambda request: request

    def export(self, spans) -> SpanExportResult:
        try:
            payload = encode_spans(spans)
            if self._stub is not None:
                self._stub.Export(payload, metadata=tuple(self.headers.items()), timeout=2)
            else:
                response = self._session.post(self.endpoint, data=payload.SerializeToString(), headers={"Content-Type": "application/x-protobuf", **self.headers}, timeout=2, allow_redirects=False)
                try:
                    if not 200 <= response.status_code < 300:
                        logger.warning("Tracing batch export rejected (HTTP %s)", response.status_code)
                        return SpanExportResult.FAILURE
                finally:
                    response.close()
            return SpanExportResult.SUCCESS
        except Exception as exc:
            logger.warning("Tracing batch export failed (%s)", type(exc).__name__)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        if self._session is not None:
            self._session.close()
        if self._channel is not None:
            self._channel.close()
