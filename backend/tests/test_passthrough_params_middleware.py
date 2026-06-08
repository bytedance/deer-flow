"""Unit tests for PassthroughParamsMiddleware.

Covers:
- Passthrough params injected into content as <deep_link_params> block
- SystemMessage injected at position 0 for stronger LLM compliance
- Internal keys (files, hide_from_ui, element) excluded from block
- No-op when no passthrough params present or params are all internal
- Only first HumanMessage is processed (multi-turn safety)
- additional_kwargs preserved unchanged on updated message
- Empty messages and non-human first message edge cases
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.passthrough_params_middleware import (
    PassthroughParamsMiddleware,
)


def _middleware() -> PassthroughParamsMiddleware:
    return PassthroughParamsMiddleware()


def _human(content, **extra_kwargs):
    return HumanMessage(content=content, additional_kwargs=dict(extra_kwargs) if extra_kwargs else None)


def _state(*messages):
    return {"messages": list(messages)}


# ---------------------------------------------------------------------------
# Passthrough injection
# ---------------------------------------------------------------------------


def test_injects_passthrough_params_into_string_content():
    mw = _middleware()
    msg = _human("diagnose this", device_id="P-203A", component_id="Bearing-1")
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    # SystemMessage at position 0, updated HumanMessage at position 1
    assert isinstance(result["messages"][0], SystemMessage)
    updated_msg = result["messages"][1]
    assert isinstance(updated_msg, HumanMessage)
    assert isinstance(updated_msg.content, str)
    assert "<deep_link_params>" in updated_msg.content
    assert "device_id: P-203A" in updated_msg.content
    assert "component_id: Bearing-1" in updated_msg.content
    assert "diagnose this" in updated_msg.content


def test_injects_passthrough_params_into_list_content():
    mw = _middleware()
    msg = _human(
        [{"type": "text", "text": "analyse this"}],
        analysis_type="trend",
        device_id="V-401",
    )
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    assert isinstance(result["messages"][0], SystemMessage)
    updated_msg = result["messages"][1]
    assert isinstance(updated_msg, HumanMessage)
    assert isinstance(updated_msg.content, list)
    combined = "".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in updated_msg.content
    )
    assert "<deep_link_params>" in combined
    assert "device_id: V-401" in combined
    assert "analysis_type: trend" in combined
    assert "analyse this" in combined


def test_system_message_contains_deep_link_instruction():
    mw = _middleware()
    msg = _human("generate report", template_id="daily-equipment", report_date="2026-05-31")
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    system_msg = result["messages"][0]
    assert isinstance(system_msg, SystemMessage)
    assert "deep_link_params" in system_msg.content
    assert "跳过" in system_msg.content or "直达" in system_msg.content


# ---------------------------------------------------------------------------
# Internal key exclusion
# ---------------------------------------------------------------------------


def test_excludes_files_key():
    mw = _middleware()
    msg = _human("hi", device_id="X-1", files=[{"filename": "f.txt"}])
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    updated_msg = result["messages"][1]
    assert "device_id: X-1" in updated_msg.content
    assert "files" not in str(updated_msg.content).split("<deep_link_params>")[1].split("</deep_link_params>")[0]


def test_excludes_hide_from_ui_key():
    mw = _middleware()
    msg = _human("hi", device_id="X-1", hide_from_ui=True)
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    updated_msg = result["messages"][1]
    params_block = updated_msg.content.split("<deep_link_params>")[1].split("</deep_link_params>")[0]
    assert "device_id" in params_block
    assert "hide_from_ui" not in params_block


def test_excludes_element_key():
    mw = _middleware()
    msg = _human("hi", device_id="X-1", element="task")
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    updated_msg = result["messages"][1]
    params_block = updated_msg.content.split("<deep_link_params>")[1].split("</deep_link_params>")[0]
    assert "device_id" in params_block
    assert "element" not in params_block


def test_excludes_none_values():
    mw = _middleware()
    msg = _human("hi", device_id=None, source="grafana")
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    updated_msg = result["messages"][1]
    params_block = updated_msg.content.split("<deep_link_params>")[1].split("</deep_link_params>")[0]
    assert "device_id" not in params_block
    assert "source: grafana" in params_block


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------


def test_noop_when_messages_empty():
    mw = _middleware()
    assert mw.before_agent({"messages": []}, None) is None


def test_noop_when_no_passthrough_params():
    mw = _middleware()
    msg = HumanMessage(content="plain message")
    state = _state(msg)
    assert mw.before_agent(state, None) is None


def test_noop_when_only_internal_keys():
    mw = _middleware()
    msg = _human("hi", files=[{"filename": "f.txt"}], hide_from_ui=True, element="task")
    state = _state(msg)
    assert mw.before_agent(state, None) is None


def test_noop_when_first_message_is_not_human():
    mw = _middleware()
    state = _state(AIMessage(content="hello"), HumanMessage(content="world", additional_kwargs={"device_id": "X-1"}))
    assert mw.before_agent(state, None) is None


# ---------------------------------------------------------------------------
# Multi-turn safety
# ---------------------------------------------------------------------------


def test_only_processes_first_message():
    mw = _middleware()
    msgs = [
        HumanMessage(content="first"),
        AIMessage(content="response"),
        HumanMessage(content="second", additional_kwargs={"device_id": "Y-2"}),
    ]
    state = _state(*msgs)
    result = mw.before_agent(state, None)

    assert result is None  # first message has no passthrough params, so no-op


def test_processes_first_message_with_params_and_ignores_later():
    mw = _middleware()
    msgs = [
        _human("first", device_id="Z-1"),
        AIMessage(content="response"),
        _human("second", source="other"),
    ]
    state = _state(*msgs)
    result = mw.before_agent(state, None)

    assert result is not None
    # SystemMessage at 0, updated first HumanMessage at 1, original AIMessage at 2, second HumanMessage at 3
    updated_msg = result["messages"][1]
    assert "device_id: Z-1" in updated_msg.content
    # Second human message should be unmodified
    assert "<deep_link_params>" not in result["messages"][3].content


# ---------------------------------------------------------------------------
# additional_kwargs preservation
# ---------------------------------------------------------------------------


def test_preserves_additional_kwargs_on_updated_message():
    mw = _middleware()
    kwargs = {"device_id": "P-203A", "component_id": "Bearing-1", "source": "grafana"}
    msg = _human("diagnose", **kwargs)
    state = _state(msg)
    result = mw.before_agent(state, None)

    assert result is not None
    updated_kwargs = result["messages"][1].additional_kwargs
    assert updated_kwargs == kwargs
