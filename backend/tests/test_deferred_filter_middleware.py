"""Tests for DeferredToolFilterMiddleware (closure deferred-set + state promotion)."""

from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware


@as_tool
def mcp_a(x: str) -> str:
    "a"
    return x


@as_tool
def mcp_b(x: str) -> str:
    "b"
    return x


@as_tool
def active_c(x: str) -> str:
    "c"
    return x


class _Req:
    def __init__(self, tools, state):
        self.tools = tools
        self.state = state
        self.overridden = None

    def override(self, tools):
        self.overridden = tools
        return self


def _mw():
    return DeferredToolFilterMiddleware(frozenset({"mcp_a", "mcp_b"}), "h1")


def test_hides_all_deferred_when_no_promotion():
    req = _Req([mcp_a, mcp_b, active_c], {})
    out = _mw()._filter_tools(req)
    assert [t.name for t in out.overridden] == ["active_c"]


def test_promoted_under_matching_hash_passes_through():
    req = _Req([mcp_a, mcp_b, active_c], {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})
    out = _mw()._filter_tools(req)
    assert {t.name for t in out.overridden} == {"mcp_a", "active_c"}


def test_promotion_ignored_when_hash_mismatch():
    req = _Req([mcp_a, mcp_b, active_c], {"promoted": {"catalog_hash": "STALE", "names": ["mcp_a"]}})
    out = _mw()._filter_tools(req)
    assert [t.name for t in out.overridden] == ["active_c"]


def test_no_deferred_names_is_noop():
    req = _Req([active_c], {})
    out = DeferredToolFilterMiddleware(frozenset(), "h1")._filter_tools(req)
    assert out.overridden is None  # returned unchanged


def test_blocked_message_for_unpromoted_deferred_call():
    class _TCReq:
        tool_call = {"name": "mcp_a", "id": "tc1"}
        state = {}

    msg = _mw()._blocked_tool_message(_TCReq())
    assert msg is not None and msg.status == "error" and "tool_search" in msg.content


def test_no_block_for_promoted_call():
    class _TCReq:
        tool_call = {"name": "mcp_a", "id": "tc1"}
        state = {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}}

    assert _mw()._blocked_tool_message(_TCReq()) is None


def test_no_block_for_non_deferred_call():
    class _TCReq:
        tool_call = {"name": "active_c", "id": "tc1"}
        state = {}

    assert _mw()._blocked_tool_message(_TCReq()) is None
