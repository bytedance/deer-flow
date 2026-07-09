"""Trace-based behavioural tests for DeerFlow, using Monocle Test Tools.

Each test loads the Monocle trace a run emitted (recorded under
``monocle_apptrace 0.8.8``) via the file trace source, and asserts what the run
actually did: which agent ran, which tools it called, what it was asked and
produced, and its token/duration cost. Loading by file (no keys, no re-run)
keeps the suite fast and deterministic.

    pytest monocle-test/                 # offline file-loaded tests (no keys)
    pytest monocle-test/ -k live         # also run the live end-to-end path (needs OPENAI_API_KEY)

Traces live in ``traces/`` and are named ``monocle_trace_deer-flow_<id>_<ts>.json``.
"""
import os

import pytest
from monocle_test_tools import TraceAssertion

from conftest import TRACES, run_deerflow

# One recorded 0.8.8 trace per curated question (see monocle-test/README.md).
TRACE_Q0_EV_BATTERY = str(TRACES / "monocle_trace_deer-flow_11a4723410cab1883c4a20fd059512cc_2026-07-09_12.27.43.json")
TRACE_Q1_VECTOR_DB  = str(TRACES / "monocle_trace_deer-flow_60cc772a50e38e66da20bf38d6b718ee_2026-07-09_12.28.03.json")
TRACE_Q2_EV_BATTERY_DUP = str(TRACES / "monocle_trace_deer-flow_fb44094c05dd3323603bcaccf67cda87_2026-07-09_12.28.20.json")
TRACE_Q3_FIB_SANDBOX = str(TRACES / "monocle_trace_deer-flow_7b2f131865f54e2f0ed7147a2883567f_2026-07-09_12.27.21.json")


# --- Offline: one file-loaded trace per curated question ------------------

def test_q0_ev_battery_briefing(monocle_trace_asserter: TraceAssertion):
    """Q0 — research solid-state EV batteries and write a sourced briefing."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_Q0_EV_BATTERY)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("solid-state EV batteries")
    monocle_trace_asserter.contains_any_output("solid-state", "battery", "batteries", "EV")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    monocle_trace_asserter.called_tool("web_fetch", "LangGraph", min_count=2)
    monocle_trace_asserter.does_not_call_tool("image_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(100_000)
    monocle_trace_asserter.under_duration(60, span_type="workflow")


def test_q1_vector_db_comparison(monocle_trace_asserter: TraceAssertion):
    """Q1 — compare open-source vector databases (subagent path).

    NOTE: captured under stock 0.8.8, this run surfaces a single ``LangGraph``
    agent doing the research directly — there is no distinct ``task``/subagent
    span to assert on (that fidelity lives on an out-of-tree branch). We assert
    only what this trace contains.
    """
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_Q1_VECTOR_DB)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("vector databases")
    monocle_trace_asserter.contains_any_output("vector", "database", "Weaviate", "Faiss", "Qdrant")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(100_000)
    monocle_trace_asserter.under_duration(60, span_type="workflow")


def test_q2_ev_battery_briefing_repeat(monocle_trace_asserter: TraceAssertion):
    """Q2 — repeat of Q0; a second independent trace of the same question."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_Q2_EV_BATTERY_DUP)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("solid-state EV batteries")
    monocle_trace_asserter.contains_any_output("solid-state", "battery", "batteries", "EV")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    monocle_trace_asserter.called_tool("web_fetch", "LangGraph", min_count=2)
    monocle_trace_asserter.under_token_limit(100_000)
    monocle_trace_asserter.under_duration(60, span_type="workflow")


def test_q3_fibonacci_sandbox(monocle_trace_asserter: TraceAssertion):
    """Q3 — author a script to a file in the sandbox (write_file, no web tools)."""
    monocle_trace_asserter.with_trace_source("file", trace_path=TRACE_Q3_FIB_SANDBOX)

    monocle_trace_asserter.called_agent("LangGraph").contains_input("Fibonacci")
    monocle_trace_asserter.contains_any_output("fib", "Fibonacci", "script", "file")
    monocle_trace_asserter.called_tool("write_file")
    monocle_trace_asserter.does_not_call_tool("web_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(50_000)
    monocle_trace_asserter.under_duration(30, span_type="workflow")


# --- Live: run the agent end-to-end (needs OPENAI_API_KEY) ----------------
# Output text varies run to run, so this asserts structure + budget only, with
# contains_any_output kept phrasing-robust.

@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_web_research_live(monocle_trace_asserter: TraceAssertion):
    """Live web-research path: solid-state EV battery briefing (web_search).

    Requires the DeerFlow app on the path (run from the backend venv), so this
    skips automatically in the standalone test-tools venv.
    """
    pytest.importorskip("deerflow", reason="DeerFlow app not importable in this venv")

    monocle_trace_asserter.validator.test_workflow(
        run_deerflow,
        {"test_input": (
            "Research the current state of solid-state EV batteries in 2025 and "
            "write a 1-page markdown briefing with sources.",
        )},
    )

    monocle_trace_asserter.called_agent("LangGraph").contains_input("solid-state EV batteries")
    monocle_trace_asserter.contains_any_output("solid-state", "battery", "batteries", "EV")
    monocle_trace_asserter.called_tool("web_search", "LangGraph")
    monocle_trace_asserter.under_token_limit(200_000)
    monocle_trace_asserter.under_duration(180, span_type="workflow")
