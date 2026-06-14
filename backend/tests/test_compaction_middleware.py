"""Unit tests for HeadroomCompactionMiddleware.

These never import the heavy ``headroom-ai`` package: the middleware exposes a
``compress_fn`` injection seam, and the Headroom loader is monkeypatched where
the no-dependency path is under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.compaction_middleware import HeadroomCompactionMiddleware
from deerflow.config.compaction_config import CompactionConfig

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    messages: list[dict[str, Any]]
    tokens_saved: int = 0
    compression_ratio: float = 0.0
    transforms_applied: list[str] = field(default_factory=list)


class _FakeConfig:
    """Stand-in for headroom.CompressConfig that just records kwargs."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def _shrinking_compress(threshold: int = 50):
    """Return a fake ``compress`` that truncates long string content in place."""

    def _compress(payload, *, model, model_limit, config=None):
        out = []
        saved = 0
        for msg in payload:
            content = msg.get("content")
            if isinstance(content, str) and len(content) > threshold:
                saved += len(content) - len("COMPRESSED")
                out.append({**msg, "content": "COMPRESSED"})
            else:
                out.append(dict(msg))
        return _FakeResult(messages=out, tokens_saved=saved // 4, compression_ratio=0.5)

    return _compress


def _request(messages, model=None):
    return ModelRequest(model=model, messages=messages, tools=[], state={})


def _mw(config: CompactionConfig, compress_fn=None):
    return HeadroomCompactionMiddleware(
        config=config,
        compress_fn=compress_fn,
        compress_config_cls=_FakeConfig,
    )


def _capture_handler(box):
    def handler(req):
        box["request"] = req
        return []

    return handler


_BIG = "x" * 4000  # > min_tokens_to_compress and pushes history over the gate


# ---------------------------------------------------------------------------
# Disabled / gating
# ---------------------------------------------------------------------------


class TestGating:
    def test_disabled_passes_through(self):
        mw = _mw(CompactionConfig(enabled=False), compress_fn=_shrinking_compress())
        box: dict = {}
        mw.wrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t")]), _capture_handler(box))
        assert box["request"].messages[0].content == _BIG  # untouched

    def test_below_min_total_tokens_passes_through(self):
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=10_000), compress_fn=_shrinking_compress())
        box: dict = {}
        req = _request([ToolMessage(content=_BIG, tool_call_id="t")])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req

    def test_empty_messages_passes_through(self):
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress())
        box: dict = {}
        req = _request([])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req


# ---------------------------------------------------------------------------
# Compaction behaviour
# ---------------------------------------------------------------------------


class TestCompaction:
    def test_compresses_string_content(self):
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress())
        box: dict = {}
        req = _request([ToolMessage(content=_BIG, tool_call_id="t1")])
        mw.wrap_model_call(req, _capture_handler(box))

        forwarded = box["request"]
        assert forwarded is not req  # a new request was forwarded
        assert forwarded.messages[0].content == "COMPRESSED"

    def test_original_messages_not_mutated(self):
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress())
        original = ToolMessage(content=_BIG, tool_call_id="t1")
        req = _request([original])
        mw.wrap_model_call(req, _capture_handler({}))
        # Non-destructive: the original message object keeps its full content.
        assert original.content == _BIG

    def test_preserves_tool_calls_and_ids(self):
        ai = AIMessage(
            content=_BIG,
            id="ai-1",
            tool_calls=[{"name": "bash", "args": {"cmd": "ls"}, "id": "call-1", "type": "tool_call"}],
        )
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress())
        box: dict = {}
        mw.wrap_model_call(_request([ai]), _capture_handler(box))

        out = box["request"].messages[0]
        assert out.content == "COMPRESSED"
        assert out.id == "ai-1"
        assert out.tool_calls == ai.tool_calls

    def test_no_change_passes_original_request(self):
        # All content short → fake compress returns identical strings → no override.
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress(threshold=10_000))
        box: dict = {}
        req = _request([ToolMessage(content=_BIG, tool_call_id="t1")])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req

    def test_count_mismatch_passes_through(self):
        def dropping_compress(payload, *, model, model_limit, config=None):
            return _FakeResult(messages=payload[1:])  # drops one → shape mismatch

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=dropping_compress)
        box: dict = {}
        req = _request([HumanMessage(content=_BIG), ToolMessage(content=_BIG, tool_call_id="t1")])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req

    def test_list_content_preserved(self):
        # Multimodal/list content is never mapped back even if compress touches it.
        def mangle(payload, *, model, model_limit, config=None):
            out = [dict(m) for m in payload]
            out[0]["content"] = "SHOULD_NOT_APPLY"
            return _FakeResult(messages=out, tokens_saved=1)

        multimodal = HumanMessage(content=[{"type": "text", "text": _BIG}])
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=mangle)
        box: dict = {}
        mw.wrap_model_call(_request([multimodal]), _capture_handler(box))
        # No string change applied → original request forwarded unchanged.
        assert box["request"].messages[0].content == multimodal.content


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_fail_open_swallows_errors(self):
        def boom(payload, **kwargs):
            raise RuntimeError("kompress exploded")

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0, fail_open=True), compress_fn=boom)
        box: dict = {}
        req = _request([ToolMessage(content=_BIG, tool_call_id="t1")])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req

    def test_fail_closed_raises(self):
        def boom(payload, **kwargs):
            raise RuntimeError("kompress exploded")

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0, fail_open=False), compress_fn=boom)
        with pytest.raises(RuntimeError):
            mw.wrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t1")]), _capture_handler({}))


# ---------------------------------------------------------------------------
# Optional dependency fallback
# ---------------------------------------------------------------------------


class TestOptionalDependency:
    def test_noop_when_headroom_unavailable(self, monkeypatch):
        import deerflow.agents.middlewares.compaction_middleware as mod

        monkeypatch.setattr(mod, "_load_headroom", lambda: (None, None))
        # No compress_fn injected → middleware must resolve via _load_headroom.
        mw = HeadroomCompactionMiddleware(CompactionConfig(enabled=True, min_total_tokens=0))
        box: dict = {}
        req = _request([ToolMessage(content=_BIG, tool_call_id="t1")])
        mw.wrap_model_call(req, _capture_handler(box))
        assert box["request"] is req


# ---------------------------------------------------------------------------
# Model name resolution
# ---------------------------------------------------------------------------


class TestModelNameResolution:
    def test_explicit_config_model_wins(self):
        captured: dict = {}

        def spy(payload, *, model, model_limit, config=None):
            captured["model"] = model
            return _FakeResult(messages=[dict(m) for m in payload])

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0, model="claude-x"), compress_fn=spy)
        mw.wrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t")]), _capture_handler({}))
        assert captured["model"] == "claude-x"

    def test_resolves_from_request_model_attr(self):
        captured: dict = {}

        def spy(payload, *, model, model_limit, config=None):
            captured["model"] = model
            return _FakeResult(messages=[dict(m) for m in payload])

        class _Model:
            model_name = "gpt-from-binding"

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=spy)
        mw.wrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t")], model=_Model()), _capture_handler({}))
        assert captured["model"] == "gpt-from-binding"

    def test_falls_back_to_default(self):
        captured: dict = {}

        def spy(payload, *, model, model_limit, config=None):
            captured["model"] = model
            return _FakeResult(messages=[dict(m) for m in payload])

        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=spy)
        mw.wrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t")]), _capture_handler({}))
        assert captured["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Async path
# ---------------------------------------------------------------------------


class TestAsyncPath:
    @pytest.mark.anyio
    async def test_awrap_model_call_compresses(self):
        mw = _mw(CompactionConfig(enabled=True, min_total_tokens=0), compress_fn=_shrinking_compress())
        box: dict = {}

        async def handler(req):
            box["request"] = req
            return []

        await mw.awrap_model_call(_request([ToolMessage(content=_BIG, tool_call_id="t1")]), handler)
        assert box["request"].messages[0].content == "COMPRESSED"
