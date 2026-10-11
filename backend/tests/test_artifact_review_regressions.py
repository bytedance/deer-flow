"""Regression cases from PR #4929's occurrence, PII and URL reviews."""

from types import SimpleNamespace

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.thread_state import ThreadState, get_thread_state_schema, merge_tool_artifacts
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.tool_artifact_config import ToolArtifactConfig
from deerflow.tools.artifact_registry import extract_artifacts_from_result


def result(message_id, ref, call_id="reused"):
    return ToolMessage(id=message_id, content="done", tool_call_id=call_id, name="mcp_tool", artifact={"structured_content": {"file": ref}})


def runtime():
    return SimpleNamespace(context={"thread_id": "review-thread"})


def apply(state, update):
    if update:
        state["tool_artifacts"] = merge_tool_artifacts(state.get("tool_artifacts"), update.get("tool_artifacts"))
        state["tool_artifact_processed"] = list(dict.fromkeys([*state.get("tool_artifact_processed", []), *update.get("tool_artifact_processed", [])]))


def test_reused_provider_id_creates_distinct_artifacts_across_turns():
    middleware = ArtifactCaptureMiddleware()
    state = {"messages": [result("result-first", "/x/first.pdf")]}
    apply(state, middleware.before_model(state, runtime()))
    first = state["tool_artifacts"][0]
    state["messages"].append(result("result-second", "/x/second.pdf"))
    apply(state, middleware.before_model(state, runtime()))
    assert [e["real_ref"] for e in state["tool_artifacts"]] == ["/x/first.pdf", "/x/second.pdf"]
    assert len({e["handle"] for e in state["tool_artifacts"]}) == 2
    # Removing the earlier turn cannot change the surviving occurrence's handle.
    second = state["tool_artifacts"][1]
    fresh = ArtifactCaptureMiddleware().before_model({"messages": [state["messages"][-1]]}, runtime())
    assert fresh["tool_artifacts"][0]["handle"] == second["handle"] != first["handle"]


def test_reused_consuming_call_id_does_not_settle_a_later_occurrence():
    middleware = ArtifactCaptureMiddleware()
    state = {"messages": [result("result-first", "/x/first.pdf")]}
    apply(state, middleware.before_model(state, runtime()))
    state["messages"].append(AIMessage(id="quiet-turn", content="", tool_calls=[{"name": "read_file", "args": {"path": "/x/unrelated"}, "id": "read", "type": "tool_call"}]))
    apply(state, middleware.before_model(state, runtime()))
    handle = state["tool_artifacts"][0]["handle"]
    state["messages"].append(AIMessage(id="consuming-turn", content="", tool_calls=[{"name": "read_file", "args": {"path": handle}, "id": "read", "type": "tool_call"}]))
    apply(state, middleware.before_model(state, runtime()))
    assert state["tool_artifacts"][0]["consumed_by"] == ["read"]


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_eviction_remains_final_after_checkpoint_and_middleware_recreation(mode):
    saver = InMemorySaver()
    model = FakeToolCallingModel(responses=[AIMessage(content="done")])

    def agent():
        return create_agent(model=model, tools=[], middleware=[ArtifactCaptureMiddleware(ToolArtifactConfig(max_entries=10))], state_schema=get_thread_state_schema(mode), checkpointer=saver)

    config = {"configurable": {"thread_id": "review-thread"}}
    messages = [result(f"result-{i}", f"/x/{i}.pdf", f"call-{i}") for i in range(15)]
    graph = agent()
    first = graph.invoke({"messages": [HumanMessage(content="start"), *messages]}, config, context={"thread_id": "review-thread"})
    assert len(first["tool_artifacts"]) == 10
    retained = first["tool_artifacts"]
    # Mark a retained entry as consumed, then reload through a different graph instance.
    graph.update_state(config, {"tool_artifacts": [{**retained[-1], "consumed_by": ["read"]}]})
    for _ in range(3):
        restored = agent().invoke({"messages": [HumanMessage(content="continue")]}, config, context={"thread_id": "review-thread"})
        assert [e["handle"] for e in restored["tool_artifacts"]] == [e["handle"] for e in retained]
        assert restored["tool_artifacts"][-1]["consumed_by"] == ["read"]


@pytest.mark.parametrize("suffix", ["?sig=abc&expires=123", "#page=2", "?sig=abc#page=2"])
@pytest.mark.parametrize("wrapper", ["`{}`", '"{}"', "[{}]", "({})"])
def test_detected_file_url_preserves_suffix(suffix, wrapper):
    ref = "https://host/report.pdf" + suffix
    entries = extract_artifacts_from_result(ToolMessage(content="Saved " + wrapper.format(ref), tool_call_id="url"), thread_id="t")
    assert [e["real_ref"] for e in entries] == [ref]


@pytest.mark.parametrize("enabled", [True, False])
def test_structured_artifact_labels_follow_configured_pii_redaction(enabled):
    email = "alice@example.com"
    key = "sk-" + "a" * 24
    ref = f"https://host/report-{email}.pdf?token={key}"
    model = FakeToolCallingModel(responses=[AIMessage(content="done")])
    captured = []
    original = model._generate

    # Record the actual model request, after capture and durable projection.
    def record(messages, **kwargs):
        captured.extend(messages)
        return original(messages, **kwargs)

    object.__setattr__(model, "_generate", record)
    config = PiiRedactionConfig(enabled=enabled, token_secret="synthetic-test-secret")
    graph = create_agent(model=model, tools=[], middleware=[ArtifactCaptureMiddleware(), DurableContextMiddleware(pii_redaction_config=config)], state_schema=ThreadState)
    out = graph.invoke({"messages": [HumanMessage(content="continue"), result("private-result", ref)]}, context={"thread_id": "review-thread"})
    blocks = [m.content for m in captured if m.additional_kwargs.get("durable_context_data")]
    assert blocks
    rendered = "\n".join(blocks)
    assert (email in rendered) is not enabled
    assert (key in rendered) is not enabled
    assert out["tool_artifacts"][0]["real_ref"] == ref
    assert out["tool_artifacts"][0]["handle"] in rendered


def test_reused_provider_ids_in_real_checkpointed_agent_resolve_both_occurrences():
    from langchain_core.tools import tool
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware

    @tool
    def make_file(name: str) -> str:
        """Make a file and return its path."""
        return f"Saved /mnt/user-data/outputs/{name}"

    saver = InMemorySaver()
    model = FakeToolCallingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "make_file", "args": {"name": "first.pdf"}, "id": "reused", "type": "tool_call"}]),
            AIMessage(content="done"),
            AIMessage(content="", tool_calls=[{"name": "make_file", "args": {"name": "second.pdf"}, "id": "reused", "type": "tool_call"}]),
            AIMessage(content="done"),
        ]
    )
    graph = create_agent(model=model, tools=[make_file], middleware=[ArtifactCaptureMiddleware()], state_schema=ThreadState, checkpointer=saver)
    config = {"configurable": {"thread_id": "review-thread"}}
    graph.invoke({"messages": [HumanMessage(content="first")]}, config, context={"thread_id": "review-thread"})
    state = graph.invoke({"messages": [HumanMessage(content="second")]}, config, context={"thread_id": "review-thread"})
    entries = state["tool_artifacts"]
    assert [e["real_ref"] for e in entries] == ["/mnt/user-data/outputs/first.pdf", "/mnt/user-data/outputs/second.pdf"]
    assert entries[0]["handle"] != entries[1]["handle"]
    resolver = ArtifactResolutionMiddleware()
    for entry in entries:
        request = ToolCallRequest(tool_call={"name": "make_file", "args": {"name": entry["handle"]}, "id": "read", "type": "tool_call"}, tool=make_file, state=state, runtime=runtime())
        resolved = resolver.wrap_tool_call(request, lambda r: ToolMessage(content=r.tool_call["args"]["name"], tool_call_id="read"))
        assert resolved.content == entry["real_ref"]


@pytest.mark.parametrize("field", ["display_name", "artifact_type", "tool_name", "mime_type"])
def test_all_model_visible_artifact_labels_are_redacted_without_mutating_state(field):
    from langchain.agents.middleware.types import ModelRequest

    secret = "alice@example.com sk-" + "a" * 24
    entry = {
        "handle": "art_1234abcd",
        "tool_name": "mcp_tool",
        "tool_call_id": "make",
        "call_index": 0,
        "artifact_type": "file",
        "display_name": "report.pdf",
        "real_ref": "https://host/private.pdf",
        "created_at": "now",
        field: secret,
    }
    state = {"tool_artifacts": [entry], "messages": []}
    model = FakeToolCallingModel(responses=[AIMessage(content="done")])
    request = ModelRequest(model=model, messages=[], state=state, runtime=runtime(), tools=[])
    middleware = DurableContextMiddleware(pii_redaction_config=PiiRedactionConfig(enabled=True, token_secret="synthetic-test-secret"))
    projected = middleware._inject(request)
    data = next(m.content for m in projected.messages if m.additional_kwargs.get("durable_context_data"))
    assert "alice@example.com" not in data and "sk-" + "a" * 24 not in data
    assert entry[field] == secret and entry["real_ref"] == "https://host/private.pdf"
    assert entry["handle"] in data
