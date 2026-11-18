"""Verify structured preview budgets and access to the complete raw output."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares import tool_output_synopsis as synopsis_module
from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware, _build_preview, _patch_model_messages
from deerflow.agents.middlewares.tool_output_synopsis import ToolOutputSynopsis, build_tool_output_synopsis
from deerflow.config.tool_output_config import ToolOutputConfig


@pytest.mark.parametrize("key", ["x" * 20000, "字段🙂" * 5000, '"\\\n' * 5000], ids=["ascii", "unicode", "escaped"])
@pytest.mark.parametrize("nested", [False, True])
def test_long_json_labels_and_paths_are_bounded(key, nested):
    value = {key: {key: {key: 1}}} if nested else {key: 1}
    content = json.dumps(value, ensure_ascii=False)
    synopsis = build_tool_output_synopsis(content)
    assert synopsis.kind == "json"
    for item in synopsis.summary + synopsis.structure + synopsis.notable_items:
        assert len(item) <= 1500
    preview = _build_preview(content, tool_name="bash", virtual_path="/mnt/result.json", head_chars=1000, tail_chars=500)
    assert len(preview) < 4000
    assert "..." in preview
    assert preview.endswith("Use read_file on /mnt/result.json with start_line and end_line to inspect the raw output.")
    preview.encode("utf-8")


@pytest.mark.parametrize("head,tail", [(0, 0), (1, 0), (0, 1), (1000, 500), (2000, 1000)])
@pytest.mark.parametrize("kind", ["json", "xml", "csv", "yaml", "text", "unknown"])
def test_renderer_bounds_aggregate_synopsis_and_keeps_samples(monkeypatch, head, tail, kind):
    # Check every format at the shared renderer so no parser bypasses the budget.
    monkeypatch.setattr(synopsis_module, "build_tool_output_synopsis", lambda *args, **kwargs: ToolOutputSynopsis(kind, "title", ["s" * 10000], ["p" * 10000] * 24, ["v" * 10000] * 6))
    content = "H" * 5000 + "T" * 5000
    preview = _build_preview(content, tool_name="bash", virtual_path="/mnt/result.txt", head_chars=head, tail_chars=tail)
    # Use two existing short excerpts as the synopsis floor; retain raw samples separately.
    assert len(preview) <= max(840, head + tail) + head + tail + 600
    if kind != "text" or head + tail == 0:
        assert "Synopsis truncated" in preview
    assert preview.endswith("Use read_file on /mnt/result.txt with start_line and end_line to inspect the raw output.")
    if head:
        assert "H" * head in preview
    if tail:
        assert "T" * tail in preview


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_synopsis_exact_budget_boundary(monkeypatch, offset):
    prefix = "title:\n- "
    summary = "中" * (840 - len(prefix) + offset)
    monkeypatch.setattr(synopsis_module, "build_tool_output_synopsis", lambda *args, **kwargs: ToolOutputSynopsis("json", "title", [summary], [], []))
    preview = _build_preview("{}", tool_name="bash", virtual_path="/mnt/result.txt", head_chars=0, tail_chars=0)
    body = preview.split("\n\n", 1)[1].rsplit("\n\nAccess:", 1)[0]
    assert len(body) <= 840
    assert ("Synopsis truncated" in body) == (offset > 0)
    if offset <= 0:
        assert body == prefix + summary


@pytest.mark.parametrize("mode", ["sync", "async", "command"])
@pytest.mark.asyncio
async def test_model_visible_preview_preserves_externalized_json(tmp_path, mode):
    content = json.dumps({"字段🙂" * 5000: {"child": 1}}, ensure_ascii=False)
    config = ToolOutputConfig()
    middleware = ToolOutputBudgetMiddleware(config=config)
    request = SimpleNamespace(tool_call={"name": "bash", "id": "call-json"}, runtime=SimpleNamespace(state={"thread_data": {"outputs_path": str(tmp_path)}}))
    message = ToolMessage(content=content, name="bash", tool_call_id="call-json")
    result = Command(update={"messages": [message]}) if mode == "command" else message
    if mode == "async":

        async def handler(_):
            return result

        visible = await middleware.awrap_tool_call(request, handler)
    else:
        visible = middleware.wrap_tool_call(request, lambda _: result)
    if mode == "command":
        visible = visible.update["messages"][0]
    assert len(visible.content) < 7000
    assert "Preview kind: json" in visible.content
    assert "read_file" in visible.content
    files = list((tmp_path / ".tool-results").iterdir())
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == content
    virtual_path = f"/mnt/user-data/outputs/.tool-results/{files[0].name}"
    assert visible.content.count(virtual_path) == 2
    assert _patch_model_messages([visible], config) is None
    assert message.content == content


def test_short_json_keeps_complete_paths_and_values():
    content = '{"meta":{"source":"unit"},"items":[{"id":1}]}'
    preview = _build_preview(content, tool_name="bash", virtual_path="/mnt/result.json", head_chars=0, tail_chars=0)
    assert "Top-level keys: meta, items" in preview
    assert '$.meta.source: "unit"' in preview
    assert "$.items[0].id: 1" in preview
    assert "Synopsis truncated" not in preview


@pytest.mark.parametrize(
    "kind,content",
    [
        ("json", json.dumps({str(i): {"field" * 100: list(range(20))} for i in range(12)})),
        ("xml", "<" + "x" * 10000 + "/>"),
        ("yaml", "---\n" + "key" * 300 + ": 1\n"),
        ("csv", ("column" * 1000 + ",id\n") + "value,1\n" * 6),
        ("text", '{"invalid":' + "x" * 20000),
        ("unknown", "\x00" + "x" * 20000),
        ("unknown", "x" * 5000001),
    ],
    ids=["json", "xml", "yaml", "csv", "invalid-json", "binary", "oversized"],
)
def test_actual_format_and_parse_fallback_stay_bounded(kind, content):
    preview = _build_preview(content, tool_name="bash", virtual_path="/mnt/result.txt", head_chars=1000, tail_chars=500)
    assert f"Preview kind: {kind}" in preview
    assert len(preview) <= 3600
    assert preview.endswith("Use read_file on /mnt/result.txt with start_line and end_line to inspect the raw output.")


@pytest.mark.parametrize("size", [79, 80, 81])
def test_json_label_boundary(size):
    key = "k" * size
    result = build_tool_output_synopsis(json.dumps({key: 1}))
    keys = result.summary[1].removeprefix("Top-level keys: ")
    assert len(keys) <= 80
    assert (keys.endswith("...")) == (size > 80)
    if size <= 80:
        assert f"$.{key}: 1" in result.notable_items


def test_storage_failure_keeps_existing_fallback_budget():
    content = json.dumps({"x" * 40000: 1})
    config = ToolOutputConfig(fallback_max_chars=1000)
    middleware = ToolOutputBudgetMiddleware(config=config)
    request = SimpleNamespace(tool_call={"name": "bash", "id": "call-fallback"}, runtime=SimpleNamespace(state={}))
    result = middleware.wrap_tool_call(request, lambda _: ToolMessage(content=content, name="bash", tool_call_id="call-fallback"))
    assert len(result.content) <= 1000
    assert "Persistent storage unavailable" in result.content
    assert "output saved to" not in result.content


def test_long_reference_is_preserved_outside_synopsis_budget():
    path = "/mnt/" + "目录/" * 200 + "result.json"
    content = json.dumps({"x" * 20000: 1})
    preview = _build_preview(content, tool_name="tool" * 10000, virtual_path=path, head_chars=0, tail_chars=0)
    assert preview.count(path) == 2
    assert len(preview) <= 840 + 2 * len(path) + 600
    assert preview.endswith(f"Use read_file on {path} with start_line and end_line to inspect the raw output.")
