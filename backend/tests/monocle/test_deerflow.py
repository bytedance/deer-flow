"""Trace-based behavioural tests for DeerFlow, using Monocle Test Tools.

Two layers:

* One **offline example** (``test_assertion_api_example``) loads a recorded
  trace from file and shows the full fluent vocabulary in one place. It needs no
  keys and no network, but because it asserts against frozen JSON it guards the
  trace format and the asserter wiring, not DeerFlow's behaviour. Treat it as the
  worked example for writing your own assertions.
* Two **live tests** drive the agent end-to-end through ``run_agent`` and assert
  on the trace the real run emits. These are the behavioural guards: a change
  that alters routing, tool selection, or token cost is caught here. They are
  **explicit opt-in** via ``MONOCLE_LIVE_TESTS=1`` (default off, so a plain run
  never spends tokens or hits the network) and need the DeerFlow app plus the
  configured model's credentials.

The whole module is skipped when ``monocle_test_tools`` is not installed (see the
``importorskip`` below), so a plain backend venv collects it without error.

    pytest backend/tests/monocle/                                  # offline only
    MONOCLE_LIVE_TESTS=1 pytest backend/tests/monocle/             # + live tests

See ``README.md`` for how to add your own.
"""

from pathlib import Path

import pytest

# monocle_test_tools hard-depends on the ML eval stack (torch, transformers,
# sentence-transformers), so it is a standalone requirements.txt install rather
# than a backend dependency. Skip the whole module when it is not present (e.g.
# a plain backend CI venv) instead of erroring at collection.
pytest.importorskip("monocle_test_tools", reason="pip install -r tests/monocle/requirements.txt")

from _helpers import live_tests_enabled  # noqa: E402
from monocle_test_tools import TraceAssertion  # noqa: E402

TRACES = Path(__file__).resolve().parent / "traces"
EXAMPLE_TRACE = str(TRACES / "web_research_ev_battery.json")


def test_live_gate_defaults_off(monkeypatch):
    """The live tests must be opt-in: gate closed by default, open only on the flag.

    This is what keeps the plain ``pytest backend/tests/monocle/`` run incapable
    of model calls, web requests, or sandbox writes, even on a checkout where
    credentials and ``config.yaml`` are present.
    """
    monkeypatch.delenv("MONOCLE_LIVE_TESTS", raising=False)
    assert live_tests_enabled() is False
    monkeypatch.setenv("MONOCLE_LIVE_TESTS", "1")
    assert live_tests_enabled() is True
    monkeypatch.setenv("MONOCLE_LIVE_TESTS", "0")
    assert live_tests_enabled() is False


# --- Offline example: the full assertion vocabulary against a recorded trace ---


def test_assertion_api_example(monocle_trace_asserter: TraceAssertion):
    """Worked example: every fluent assertion this suite uses, in one place.

    Loads a recorded web-research run (solid-state EV battery briefing) and
    asserts which agent ran, what it was asked and produced, which tools it
    called (and did not), and its token/duration budget. Copy this shape when
    writing a behavioural test — then point it at a live run (see the live tests
    below) so it actually guards behaviour.
    """
    monocle_trace_asserter.with_trace_source("file", trace_path=EXAMPLE_TRACE)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("solid-state EV batteries")
    monocle_trace_asserter.contains_any_output("solid-state", "battery", "batteries", "EV")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    # The recorded run made 5 web_fetch calls, but the intent is "researched by
    # fetching at least a couple of sources". Fetch counts genuinely vary run to
    # run, so keep this a floor rather than tightening it to the exact count.
    monocle_trace_asserter.called_tool("web_fetch", "LangGraph", min_count=2)
    monocle_trace_asserter.does_not_call_tool("image_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(100_000)
    monocle_trace_asserter.under_duration(60, span_type="workflow")


# --- Live: drive the agent and assert on the trace the real run emits ----------
# Output text varies run to run, so these assert structure + a lenient token
# budget only. Duration is omitted: a live run doing LLM calls and network I/O
# is inherently variable and would flake a wall-clock bound.


def test_web_research_live(monocle_trace_asserter: TraceAssertion, run_agent):
    """Live web-research path: the agent researches and uses ``web_search``."""
    monocle_trace_asserter.validator.test_workflow(
        run_agent,
        {"test_input": ("Research the current state of solid-state EV batteries in 2025 and write a 1-page markdown briefing with sources.",)},
    )

    monocle_trace_asserter.called_agent("LangGraph").contains_input("solid-state EV batteries")
    monocle_trace_asserter.contains_any_output("solid-state", "battery", "batteries", "EV")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(200_000)


def test_sandbox_write_file_live(monocle_trace_asserter: TraceAssertion, run_agent):
    """Live sandbox path: the agent authors a file with ``write_file`` and stays off the web."""
    monocle_trace_asserter.validator.test_workflow(
        run_agent,
        {"test_input": ("Write a Python script that prints the first 10 Fibonacci numbers and save it to a file named fib.py in the sandbox.",)},
    )

    monocle_trace_asserter.called_agent("LangGraph").contains_input("Fibonacci")
    monocle_trace_asserter.called_tool("write_file")
    monocle_trace_asserter.does_not_call_tool("web_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(100_000)
