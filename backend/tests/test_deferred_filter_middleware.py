"""Tests for DeferredToolFilterMiddleware (closure deferred-set + state promotion)."""

from langchain_core.messages import AIMessage, HumanMessage
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
    req = _Req(
        [mcp_a, mcp_b, active_c],
        {
            "messages": [HumanMessage(content="current", id="user-1")],
            "promoted": {"catalog_hash": "h1", "names": ["mcp_a"], "turn_id": "user-1"},
        },
    )
    out = _mw()._filter_tools(req)
    assert {t.name for t in out.overridden} == {"mcp_a", "active_c"}


def test_promotion_ignored_when_hash_mismatch():
    req = _Req([mcp_a, mcp_b, active_c], {"promoted": {"catalog_hash": "STALE", "names": ["mcp_a"]}})
    out = _mw()._filter_tools(req)
    assert [t.name for t in out.overridden] == ["active_c"]


def test_promotion_ignored_when_user_turn_changes():
    state = {
        "messages": [HumanMessage(content="next", id="user-2")],
        "promoted": {"catalog_hash": "h1", "names": ["mcp_a"], "turn_id": "user-1"},
    }
    req = _Req([mcp_a, active_c], state)

    out = _mw()._filter_tools(req)

    assert [t.name for t in out.overridden] == ["active_c"]


def test_legacy_promotion_without_user_turn_fails_closed():
    req = _Req([mcp_a, active_c], {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})

    out = _mw()._filter_tools(req)

    assert [t.name for t in out.overridden] == ["active_c"]


def test_before_model_establishes_empty_current_turn_scope():
    state = {"messages": [HumanMessage(content="first", id="user-1")]}

    assert _mw().before_model(state, runtime=None) == {
        "promoted": {
            "catalog_hash": "h1",
            "names": [],
            "turn_id": "user-1",
        }
    }


def test_before_model_clears_prior_turn_promotions():
    state = {
        "messages": [HumanMessage(content="first", id="user-1"), AIMessage(content="done"), HumanMessage(content="second", id="user-2")],
        "promoted": {"catalog_hash": "h1", "names": ["mcp_a"], "turn_id": "user-1"},
    }

    assert _mw().before_model(state, runtime=None) == {
        "promoted": {
            "catalog_hash": "h1",
            "names": [],
            "turn_id": "user-2",
        }
    }


def test_before_model_migrates_in_flight_legacy_checkpoint():
    state = {
        "messages": [HumanMessage(content="first", id="user-1"), AIMessage(content="", tool_calls=[])],
        "promoted": {"catalog_hash": "h1", "names": ["mcp_a"]},
    }

    assert _mw().before_model(state, runtime=None) == {
        "promoted": {
            "catalog_hash": "h1",
            "names": ["mcp_a"],
            "turn_id": "user-1",
        }
    }


def test_before_model_expires_legacy_promotion_after_new_user_message():
    state = {
        "messages": [HumanMessage(content="first", id="user-1"), AIMessage(content="done"), HumanMessage(content="second", id="user-2")],
        "promoted": {"catalog_hash": "h1", "names": ["mcp_a"]},
    }

    assert _mw().before_model(state, runtime=None) == {
        "promoted": {
            "catalog_hash": "h1",
            "names": [],
            "turn_id": "user-2",
        }
    }


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
        state = {
            "messages": [HumanMessage(content="current", id="user-1")],
            "promoted": {"catalog_hash": "h1", "names": ["mcp_a"], "turn_id": "user-1"},
        }

    assert _mw()._blocked_tool_message(_TCReq()) is None


def test_blocks_tool_call_promoted_only_in_prior_user_turn():
    class _TCReq:
        tool_call = {"name": "mcp_a", "id": "tc1"}
        state = {
            "messages": [HumanMessage(content="next", id="user-2")],
            "promoted": {"catalog_hash": "h1", "names": ["mcp_a"], "turn_id": "user-1"},
        }

    msg = _mw()._blocked_tool_message(_TCReq())

    assert msg is not None and msg.status == "error"


def test_no_block_for_non_deferred_call():
    class _TCReq:
        tool_call = {"name": "active_c", "id": "tc1"}
        state = {}

    assert _mw()._blocked_tool_message(_TCReq()) is None
