"""An externalized tool output must get one deterministic name per tool call."""

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    _build_externalized_filename,
)


def test_the_same_tool_call_gets_the_same_filename():
    """The host-disk and sandbox paths share this helper to agree on one name.

    A random suffix cannot do that: the same call would be written under two
    names, and externalizing one output twice would leave two files behind.
    """
    first = _build_externalized_filename(tool_name="bash", tool_call_id="call_abc123")
    second = _build_externalized_filename(tool_name="bash", tool_call_id="call_abc123")

    assert first == second
    assert first == "bash-call_abc123.log"


def test_different_tool_calls_get_different_filenames():
    first = _build_externalized_filename(tool_name="bash", tool_call_id="call_a")
    second = _build_externalized_filename(tool_name="bash", tool_call_id="call_b")

    assert first != second


def test_a_tool_call_id_cannot_escape_the_output_directory():
    name = _build_externalized_filename(tool_name="bash", tool_call_id="../../etc/passwd")

    assert "/" not in name
    assert ".." not in name
    assert name.startswith("bash-")
