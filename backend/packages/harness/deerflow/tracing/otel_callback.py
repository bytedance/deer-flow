"""Private OpenInference spans from LangChain callbacks, without global patches."""

from __future__ import annotations

import json
import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Status, StatusCode


def _json(value: Any) -> str:
    def default(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude={"additional_kwargs", "response_metadata"})
        return str(item)

    return json.dumps(value, default=default, ensure_ascii=False)[:16384]


class OpenInferenceCallback(BaseCallbackHandler):
    """One callback tree on one explicitly supplied tracer provider."""

    deerflow_scoped_tracing = True
    run_inline = True
    raise_error = False

    def __init__(self, tracer, snapshot, *, langfuse: bool = False, spans=None, lock=None, parent_context=None) -> None:
        self._tracer = tracer
        self._snapshot = snapshot
        self._langfuse = langfuse
        self._spans: dict[Any, Any] = spans if spans is not None else {}
        self._lock = lock if lock is not None else threading.RLock()
        self._parent_context = Context()
        if parent_context:
            try:
                context = trace.SpanContext(trace_id=int(parent_context["trace_id"], 16), span_id=int(parent_context["span_id"], 16), is_remote=True, trace_flags=trace.TraceFlags(parent_context["trace_flags"]))
                if not context.is_valid:
                    raise ValueError()
                self._parent_context = trace.set_span_in_context(trace.NonRecordingSpan(context), Context())
            except (KeyError, ValueError, TypeError):
                raise ValueError("Invalid parent tracing context") from None

    def _start(self, run_id, parent_run_id, name, kind, inputs, metadata=None):
        from deerflow.trace_context import get_current_trace_id

        metadata = metadata or {}
        with self._lock:
            key = (self._snapshot.snapshot_id, run_id)
            if key in self._spans:
                return
            parent = self._spans.get((self._snapshot.snapshot_id, parent_run_id))
            # Never adopt a global auto-instrumentor's active span. Callback
            # parent IDs are the authority for this private export tree.
            parent_context = trace.set_span_in_context(parent, Context()) if parent else self._parent_context
            attrs = {
                "openinference.span.kind": kind,
                "input.value": _json(inputs),
                "input.mime_type": "application/json",
                "deerflow.agent.name": self._snapshot.agent_name,
                "deerflow.user.id": self._snapshot.owner_user_id,
                "user.id": self._snapshot.owner_user_id,
                "deerflow.tracing.revision": self._snapshot.revision,
                "deerflow.tracing.snapshot_id": self._snapshot.snapshot_id,
            }
            for source, target in (("thread_id", "session.id"), ("run_id", "deerflow.run.id"), ("deerflow_run_id", "deerflow.run.id"), ("deerflow_trace_id", "deerflow_trace_id"), ("model_name", "llm.model_name")):
                if isinstance(metadata.get(source), (str, int)):
                    attrs[target] = metadata[source]
            if "deerflow_trace_id" not in attrs and get_current_trace_id():
                attrs["deerflow_trace_id"] = get_current_trace_id()
            if self._langfuse:
                attrs.update({"langfuse.observation.type": "generation" if kind == "LLM" else "span", "langfuse.user.id": self._snapshot.owner_user_id})
                if "session.id" in attrs:
                    attrs["langfuse.session.id"] = attrs["session.id"]
                if parent is None:
                    attrs["langfuse.trace.name"] = name
            self._spans[key] = self._tracer.start_span(name, context=parent_context, attributes=attrs)

    def _end(self, run_id, output=None, error=None):
        with self._lock:
            key = (self._snapshot.snapshot_id, run_id)
            span = self._spans.get(key)
            if span is not None and span.is_recording():
                self._spans[key] = trace.NonRecordingSpan(span.get_span_context())
            else:
                span = None
        if span is None:
            return
        if error is not None:
            # Arbitrary exceptions can contain provider headers or credentials.
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.set_attribute("error.type", type(error).__name__)
        else:
            span.set_attribute("output.value", _json(output))
            span.set_attribute("output.mime_type", "application/json")
            span.set_status(Status(StatusCode.OK))
        span.end()

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name") or "agent"
        self._start(run_id, parent_run_id, name, "AGENT" if parent_run_id is None else "CHAIN", inputs, metadata)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id, outputs)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=error)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self._start(run_id, parent_run_id, kwargs.get("name") or (serialized or {}).get("name") or "llm", "LLM", messages, metadata)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self._start(run_id, parent_run_id, kwargs.get("name") or (serialized or {}).get("name") or "llm", "LLM", prompts, metadata)

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            span = self._spans.get((self._snapshot.snapshot_id, run_id))
        if span is not None:
            usage = (getattr(response, "llm_output", None) or {}).get("token_usage", {})
            generations = getattr(response, "generations", [])
            if generations and generations[0]:
                message = getattr(generations[0][0], "message", None)
                usage = getattr(message, "usage_metadata", None) or usage
            for names, target in ((("total_tokens",), "total"), (("input_tokens", "prompt_tokens"), "prompt"), (("output_tokens", "completion_tokens"), "completion")):
                value = next((usage[name] for name in names if name in usage), None)
                if isinstance(value, int) and not isinstance(value, bool):
                    span.set_attribute(f"llm.token_count.{target}", value)
        self._end(run_id, getattr(response, "generations", response))

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=error)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self._start(run_id, parent_run_id, (serialized or {}).get("name") or "tool", "TOOL", input_str, metadata)

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id, output)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=error)

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self._start(run_id, parent_run_id, (serialized or {}).get("name") or "retriever", "RETRIEVER", query, metadata)

    def on_retriever_end(self, documents, *, run_id, **kwargs):
        self._end(run_id, documents)

    def on_retriever_error(self, error, *, run_id, **kwargs):
        self._end(run_id, error=error)
