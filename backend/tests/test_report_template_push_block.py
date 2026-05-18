"""Unit tests for report_templates.push_block — SSE push helper."""

from __future__ import annotations

from typing import Any

import pytest

from deerflow.report_templates.push_block import PushBlockError, push_block_to_sse


@pytest.fixture
def captured_writes() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def patched_runtime(monkeypatch: pytest.MonkeyPatch, captured_writes: list[dict[str, Any]]):
    """Patch langgraph.config + genui_persistence so the helper runs offline."""
    from deerflow.report_templates import push_block as push_block_mod

    def fake_get_config() -> dict:
        return {"configurable": {"thread_id": "thr_test"}}

    def fake_writer(payload: dict[str, Any]) -> None:
        captured_writes.append(payload)

    def fake_get_stream_writer():
        return fake_writer

    monkeypatch.setattr(push_block_mod, "get_config", fake_get_config)
    monkeypatch.setattr(push_block_mod, "get_stream_writer", fake_get_stream_writer)

    # genui_persistence helpers are imported inline; patch the module surface.
    # Use raising=False so we tolerate the case where another test has replaced
    # the genui_persistence module with a sys.modules mock (conftest.py-style
    # injection) before this fixture runs.
    import deerflow.agents.genui_persistence as gp

    persisted: list[tuple[str, dict]] = []

    def fake_persist_block(thread_id: str, block: dict) -> None:
        persisted.append((thread_id, block))

    def fake_get_persisted_blocks(thread_id: str) -> list[dict]:
        return [b for t, b in persisted if t == thread_id]

    monkeypatch.setattr(gp, "persist_block", fake_persist_block, raising=False)
    monkeypatch.setattr(gp, "get_persisted_blocks", fake_get_persisted_blocks, raising=False)
    return persisted


class TestPushBlock:
    def test_pushes_block_and_folded_event(self, patched_runtime, captured_writes):
        result = push_block_to_sse(
            "markdown",
            {"content": "hello"},
            block_id="b1",
            sequence=1,
        )
        # Returned dict matches what was sent on the first writer call.
        assert result["block_id"] == "b1"
        assert result["component"] == "markdown"
        assert result["interactive"] is False
        assert result["sequence"] == 1
        # Two events: ui_block + ui_blocks_folded.
        assert len(captured_writes) == 2
        assert captured_writes[0]["type"] == "ui_block"
        assert captured_writes[0]["block_id"] == "b1"
        assert captured_writes[1]["type"] == "ui_blocks_folded"
        assert captured_writes[1]["blocks"][0]["block_id"] == "b1"

    def test_auto_generates_block_id(self, patched_runtime, captured_writes):
        result = push_block_to_sse("markdown", {"content": "x"})
        assert isinstance(result["block_id"], str)
        assert len(result["block_id"]) > 0

    def test_table_component_accepted(self, patched_runtime, captured_writes):
        result = push_block_to_sse("table", {"columns": ["a"], "data": [["1"]]})
        assert result["component"] == "table"

    def test_rejects_interactive_components(self, patched_runtime):
        with pytest.raises(PushBlockError, match="not pushable"):
            push_block_to_sse("form", {})
        with pytest.raises(PushBlockError, match="not pushable"):
            push_block_to_sse("confirm", {})

    def test_rejects_unknown_component(self, patched_runtime):
        with pytest.raises(PushBlockError, match="not pushable"):
            push_block_to_sse("totally_made_up_component", {})

    def test_requires_thread_id(self, monkeypatch: pytest.MonkeyPatch):
        from deerflow.report_templates import push_block as push_block_mod

        monkeypatch.setattr(push_block_mod, "get_config", lambda: {"configurable": {}})
        monkeypatch.setattr(
            push_block_mod, "get_stream_writer", lambda: (lambda *_a, **_kw: None)
        )
        with pytest.raises(PushBlockError, match="thread_id"):
            push_block_to_sse("markdown", {"content": "x"})

    def test_no_stream_writer_raises(self, monkeypatch: pytest.MonkeyPatch):
        from deerflow.report_templates import push_block as push_block_mod

        monkeypatch.setattr(
            push_block_mod, "get_config", lambda: {"configurable": {"thread_id": "t"}}
        )

        def boom():
            raise RuntimeError("no active stream")

        monkeypatch.setattr(push_block_mod, "get_stream_writer", boom)
        with pytest.raises(PushBlockError, match="no active stream"):
            push_block_to_sse("markdown", {"content": "x"})
