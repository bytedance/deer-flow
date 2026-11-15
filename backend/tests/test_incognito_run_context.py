"""The incognito marker is server-owned and survives admission to the runtime context."""

from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY
from deerflow.runtime.runs.worker import _build_runtime_context, _pin_admission_server_context


def test_caller_cannot_opt_a_run_out_of_durable_writes():
    runtime = _build_runtime_context("thread", "run", {INCOGNITO_CONTEXT_KEY: True})

    assert INCOGNITO_CONTEXT_KEY not in runtime


def test_admission_pinned_incognito_is_hoisted_into_the_runtime_context():
    runtime: dict = {}

    _pin_admission_server_context({"context": {INCOGNITO_CONTEXT_KEY: True}}, runtime)

    assert runtime[INCOGNITO_CONTEXT_KEY] is True


def test_non_incognito_context_is_not_hoisted():
    runtime: dict = {}

    _pin_admission_server_context({"context": {}}, runtime)

    assert INCOGNITO_CONTEXT_KEY not in runtime
