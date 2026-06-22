"""Tests for DynamicContextMiddleware.

Verifies that memory and current date are injected as a <system-reminder> into
the first HumanMessage exactly once per session (frozen-snapshot pattern).
"""

from types import SimpleNamespace
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    DynamicContextMiddleware,
)

_SYSTEM_REMINDER_TAG = "<system-reminder>"


def _make_middleware(**kwargs) -> DynamicContextMiddleware:
    return DynamicContextMiddleware(**kwargs)


def _fake_runtime():
    return SimpleNamespace(context={})


def _reminder_msg(content: str, msg_id: str) -> HumanMessage:
    """Build a pre-PR HumanMessage reminder — simulates historical checkpoints.

    Uses HumanMessage (DEPRECATED format) to exercise the backward-compat
    path in ``is_dynamic_context_reminder``.  New reminders are SystemMessage.
    """
    return HumanMessage(
        content=content,
        id=msg_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )


def _date_reminder_msg(date_str: str, msg_id: str) -> SystemMessage:
    """Build a persisted date reminder in the current production shape.

    A date SystemMessage whose ``reminder_date`` additional_kwargs carries the
    authoritative date — what ``DynamicContextMiddleware`` now writes to state.
    """
    content = f"<system-reminder>\n<current_date>{date_str}</current_date>\n</system-reminder>"
    return SystemMessage(
        content=content,
        id=msg_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True, "reminder_date": date_str},
    )


# ---------------------------------------------------------------------------
# Basic injection
# ---------------------------------------------------------------------------


def test_injects_system_reminder_into_first_human_message():
    mw = _make_middleware()
    state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    updated_msgs = result["messages"]
    assert len(updated_msgs) == 2

    reminder_msg = updated_msgs[0]
    assert isinstance(reminder_msg, SystemMessage)
    assert reminder_msg.id == "msg-1"  # takes the original ID (position swap)
    assert reminder_msg.additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert _SYSTEM_REMINDER_TAG in reminder_msg.content
    assert "<current_date>2026-05-08, Friday</current_date>" in reminder_msg.content
    assert "Hello" not in reminder_msg.content  # reminder only — no user text

    user_msg = updated_msgs[1]
    assert isinstance(user_msg, HumanMessage)
    assert user_msg.id == "msg-1__user"  # derived ID
    assert user_msg.content == "Hello"


def test_memory_included_when_present():
    mw = _make_middleware()
    state = {"messages": [HumanMessage(content="Hi", id="msg-1")]}

    with (
        mock.patch(
            "deerflow.agents.lead_agent.prompt._get_memory_context",
            return_value="<memory>\nUser prefers Python.\n</memory>",
        ),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    # Memory is a separate HumanMessage — not merged into SystemMessage (OWASP LLM01)
    msgs = result["messages"]
    assert len(msgs) == 3  # date SystemMessage + memory HumanMessage + user HumanMessage

    assert isinstance(msgs[0], SystemMessage)
    assert "<current_date>2026-05-08, Friday</current_date>" in msgs[0].content
    assert "User prefers Python." not in msgs[0].content  # memory NOT in system role

    assert isinstance(msgs[1], HumanMessage)
    assert "User prefers Python." in msgs[1].content

    assert msgs[2].content == "Hi"


# ---------------------------------------------------------------------------
# Frozen-snapshot: no re-injection within a session
# ---------------------------------------------------------------------------


def test_skips_injection_if_already_present():
    """Second turn: separate reminder message already present → no update."""
    mw = _make_middleware()
    state = {
        "messages": [
            _date_reminder_msg("2026-05-08, Friday", "msg-1"),
            HumanMessage(content="Hello", id="msg-1__user"),
            AIMessage(content="Hi there"),
            HumanMessage(content="Follow-up", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is None  # no update needed


def test_second_turn_with_memory_does_not_reinject():
    """Regression: a dateless memory reminder must not shadow the date reminder.

    Reproduces the scrambled-messages / wrong-answer bug (thread
    9be75d63): production persists the injected context as TWO flagged
    messages — a date SystemMessage and a separate dateless <memory>
    HumanMessage. On a later turn ``_last_injected_date`` scans in reverse
    and hits the memory message first; because it has no <current_date> it
    must keep scanning to find the real date. If it stops and returns None,
    the middleware falsely treats this as the first turn, re-injects, picks
    the previous turn's ``__user`` message as the target, and the model
    re-answers the stale turn instead of the new one.
    """
    mw = _make_middleware()
    date_reminder = "<system-reminder>\n<current_date>2026-05-08, Friday</current_date>\n</system-reminder>"
    state = {
        "messages": [
            SystemMessage(
                content=date_reminder,
                id="msg-1",
                additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
            ),
            _reminder_msg("<memory>\nUser prefers Python.\n</memory>", "msg-1__memory"),
            HumanMessage(content="test", id="msg-1__user", name="user-input"),
            AIMessage(content="Test received"),
            HumanMessage(content="tell me the weather", id="msg-2", name="user-input"),
        ]
    }

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value="<memory>\nUser prefers Python.\n</memory>"), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is None  # same day already injected → must NOT re-inject


def test_poisoned_memory_does_not_spoof_injected_date():
    """A <current_date> embedded in user-influenceable memory must not spoof detection.

    Memory is LLM-extracted from user input and injected unescaped (it's
    hide_from_ui, so InputSanitizationMiddleware skips it). If a memory fact
    contains a literal <current_date>…</current_date>, content-regex detection
    would return that fake date (it sits after the authoritative date message but
    is hit first in the reverse scan) and trigger a false midnight crossing /
    re-injection. The authoritative date lives in additional_kwargs, so detection
    must ignore the memory content entirely.
    """
    mw = _make_middleware()
    today = "2026-05-08, Friday"
    date_reminder = f"<system-reminder>\n<current_date>{today}</current_date>\n</system-reminder>"
    state = {
        "messages": [
            SystemMessage(
                content=date_reminder,
                id="msg-1",
                additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True, "reminder_date": today},
            ),
            _reminder_msg("<memory>\nUser asked about <current_date>2024-01-01</current_date> last year.\n</memory>", "msg-1__memory"),
            HumanMessage(content="test", id="msg-1__user", name="user-input"),
            AIMessage(content="Test received"),
            HumanMessage(content="follow up", id="msg-2", name="user-input"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = today
        result = mw.before_agent(state, _fake_runtime())

    # Detection uses the authoritative metadata date (today) → same day → no re-injection.
    # If the fake 2024 date from memory content leaked in, this would be a midnight crossing.
    assert result is None


def test_date_reminder_carries_structured_date():
    """First-turn injection records the authoritative date in additional_kwargs.

    The date SystemMessage carries ``reminder_date``; the memory HumanMessage
    deliberately does not (it is dateless and must never spoof detection).
    """
    mw = _make_middleware()
    state = {"messages": [HumanMessage(content="Hi", id="msg-1")]}

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value="<memory>\nUser prefers Python.\n</memory>"),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    msgs = result["messages"]
    assert isinstance(msgs[0], SystemMessage)
    assert msgs[0].additional_kwargs.get("reminder_date") == "2026-05-08, Friday"
    # Memory HumanMessage must not carry the authoritative date
    assert isinstance(msgs[1], HumanMessage)
    assert "reminder_date" not in msgs[1].additional_kwargs


def test_legacy_systemmessage_reminder_without_key_detected():
    """Backward-compat: pre-reminder_date checkpoints kept the date in content only.

    A date SystemMessage with the date in content but no ``reminder_date`` key
    must still be detected (via the SystemMessage-scoped content fallback) so
    in-flight conversations from before the upgrade do not re-inject.
    """
    mw = _make_middleware()
    state = {
        "messages": [
            SystemMessage(
                content="<system-reminder>\n<current_date>2026-05-08, Friday</current_date>\n</system-reminder>",
                id="msg-1",
                additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},  # no reminder_date
            ),
            HumanMessage(content="Hello", id="msg-1__user"),
            AIMessage(content="Hi there"),
            HumanMessage(content="Follow-up", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is None  # same day detected from content → no re-injection


def test_injects_only_into_first_human_message_not_later_ones():
    """Reminder targets the first HumanMessage; subsequent messages are not touched."""
    mw = _make_middleware()
    state = {
        "messages": [
            HumanMessage(content="First", id="msg-1"),
            AIMessage(content="Reply"),
            HumanMessage(content="Second", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    msgs = result["messages"]
    # Only the two injected messages are returned (reminder + original first query)
    assert len(msgs) == 2
    assert msgs[0].id == "msg-1"  # reminder takes first message's ID
    assert msgs[0].additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert _SYSTEM_REMINDER_TAG in msgs[0].content
    assert msgs[1].id == "msg-1__user"  # original content with derived ID
    assert msgs[1].content == "First"
    # "Second" (msg-2) is not in the returned update — it is left unchanged
    assert all(m.id != "msg-2" for m in msgs)


def test_summary_human_message_is_not_used_as_injection_target():
    """After summarization, the synthetic summary HumanMessage is not a user turn."""
    mw = _make_middleware()
    state = {
        "messages": [
            HumanMessage(content="Here is a summary of the conversation to date:\n\n...", id="summary-1", name="summary"),
            AIMessage(content="Earlier reply"),
            HumanMessage(content="Follow-up", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    msgs = result["messages"]
    assert len(msgs) == 2
    assert msgs[0].id == "msg-2"
    assert msgs[0].additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert msgs[1].id == "msg-2__user"
    assert msgs[1].content == "Follow-up"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_no_messages_returns_none():
    mw = _make_middleware()
    result = mw.before_agent({"messages": []}, _fake_runtime())
    assert result is None


def test_no_human_message_returns_none():
    mw = _make_middleware()
    state = {"messages": [AIMessage(content="assistant only")]}
    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""):
        result = mw.before_agent(state, _fake_runtime())
    assert result is None


def test_list_content_message_handled_as_separate_reminder():
    """List-content (e.g. multi-modal) messages remain intact; reminder is a separate message."""
    mw = _make_middleware()
    original_content = [{"type": "text", "text": "Hello"}]
    state = {"messages": [HumanMessage(content=original_content, id="msg-1")]}

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    msgs = result["messages"]
    assert len(msgs) == 2
    # Reminder is a plain string message with the flag set
    assert isinstance(msgs[0].content, str)
    assert msgs[0].additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert _SYSTEM_REMINDER_TAG in msgs[0].content
    # Original list-content message is untouched
    assert msgs[1].content == original_content


def test_reminder_uses_original_id_user_message_uses_derived_id():
    """Reminder takes original ID (position swap); user message gets {id}__user."""
    mw = _make_middleware()
    original_id = "original-id-abc"
    state = {"messages": [HumanMessage(content="Hello", id=original_id)]}

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result["messages"][0].id == original_id
    assert result["messages"][1].id == f"{original_id}__user"


def test_message_without_id_gets_stable_uuid():
    """If the original HumanMessage has no ID, a UUID is generated and used consistently."""
    mw = _make_middleware()
    state = {"messages": [HumanMessage(content="Hello", id=None)]}

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    reminder_id = result["messages"][0].id
    user_id = result["messages"][1].id
    assert reminder_id is not None
    assert reminder_id != "None"
    assert user_id == f"{reminder_id}__user"


def test_user_message_containing_system_reminder_tag_does_not_prevent_injection():
    """A user message containing '<system-reminder>' must not be mistaken for a reminder."""
    mw = _make_middleware()
    state = {
        "messages": [
            HumanMessage(content="What is <system-reminder>?", id="msg-1"),
        ]
    }

    with mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""), mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    # Injection must happen — the user message does NOT carry the reminder flag
    assert result is not None
    assert result["messages"][0].additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True


# ---------------------------------------------------------------------------
# Midnight crossing
# ---------------------------------------------------------------------------


def test_midnight_crossing_injects_date_update_as_separate_message():
    """When the date has changed, a separate date-update reminder is injected before
    the current turn's HumanMessage using the ID-swap technique."""
    mw = _make_middleware()
    state = {
        "messages": [
            _date_reminder_msg("2026-05-08, Friday", "msg-1"),
            HumanMessage(content="Hello", id="msg-1__user"),
            AIMessage(content="Response"),
            HumanMessage(content="Good morning", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-09, Saturday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is not None
    msgs = result["messages"]
    assert len(msgs) == 2

    # Midnight-cross reminder is also a SystemMessage — both paths are covered
    assert isinstance(msgs[0], SystemMessage)

    # Date-update reminder takes the current message's ID
    assert msgs[0].id == "msg-2"
    assert msgs[0].additional_kwargs.get(_DYNAMIC_CONTEXT_REMINDER_KEY) is True
    assert _SYSTEM_REMINDER_TAG in msgs[0].content
    assert "<current_date>2026-05-09, Saturday</current_date>" in msgs[0].content
    assert "Good morning" not in msgs[0].content  # reminder only

    # Original user text appended with derived ID
    assert msgs[1].id == "msg-2__user"
    assert msgs[1].content == "Good morning"


def test_midnight_crossing_id_swap():
    """Date-update reminder uses original ID; user message uses {id}__user."""
    mw = _make_middleware()
    state = {
        "messages": [
            _date_reminder_msg("2026-05-08, Friday", "msg-1"),
            HumanMessage(content="Next day message", id="msg-2"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-09, Saturday"
        result = mw.before_agent(state, _fake_runtime())

    assert result["messages"][0].id == "msg-2"
    assert result["messages"][1].id == "msg-2__user"


def test_memory_message_carries_reminder_key_for_title_eligibility():
    """Regression: memory HumanMessage must carry _DYNAMIC_CONTEXT_REMINDER_KEY.

    Without it, title_middleware._is_user_message_for_title counts the memory
    block as a second user message and skips title generation entirely.
    Similarly, summarization_middleware._preserve_dynamic_context_reminders
    would not rescue the memory block from summary compression.
    """
    from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder

    mw = _make_middleware()
    state = {"messages": [HumanMessage(content="Hi", id="msg-1")]}

    with (
        mock.patch(
            "deerflow.agents.lead_agent.prompt._get_memory_context",
            return_value="<memory>\nUser prefers Python.\n</memory>",
        ),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        result = mw.before_agent(state, _fake_runtime())

    msgs = result["messages"]
    # Memory message must be recognized as a dynamic-context reminder
    memory_msg = msgs[1]
    assert isinstance(memory_msg, HumanMessage)
    assert memory_msg.id == "msg-1__memory"
    assert is_dynamic_context_reminder(memory_msg) is True

    # Only the actual user message is title-eligible
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    title_eligible = [m for m in msgs if TitleMiddleware._is_user_message_for_title(m)]
    assert len(title_eligible) == 1
    assert title_eligible[0].content == "Hi"


def test_no_second_midnight_injection_once_date_updated():
    """After a midnight update is persisted, the same-day path skips re-injection."""
    mw = _make_middleware()
    state = {
        "messages": [
            _date_reminder_msg("2026-05-08, Friday", "msg-1"),
            HumanMessage(content="Hello", id="msg-1__user"),
            AIMessage(content="Response"),
            _date_reminder_msg("2026-05-09, Saturday", "msg-2"),
            HumanMessage(content="Good morning", id="msg-2__user"),
            AIMessage(content="Good morning!"),
            HumanMessage(content="Third turn", id="msg-3"),
        ]
    }

    with mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "2026-05-09, Saturday"
        result = mw.before_agent(state, _fake_runtime())

    assert result is None  # same day as last injected date → no update
