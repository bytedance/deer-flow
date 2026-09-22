"""Tests for scripts/eval_typesafe_risk_gate.py.

The script is the pre-enablement evidence for the TypeSafe gate, so its reporting
has to stay honest when the evaluation itself goes badly: a cache-pass call must
be classified from the response it got rather than from the expectation that
warming worked, and the optional connection diagnostic must never take the
completed evaluation down with it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import socket
import ssl
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason
from deerflow.guardrails.typesafe import TypeSafeGuardrailError

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_typesafe_risk_gate.py"

spec = importlib.util.spec_from_file_location("deerflow_eval_typesafe_risk_gate", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
eval_script = importlib.util.module_from_spec(spec)
# dataclasses resolve ``cls.__module__`` through sys.modules, so register first.
sys.modules[spec.name] = eval_script
spec.loader.exec_module(eval_script)

_SAFE_CASE = {"id": "read-file", "label": "safe", "tool": "read_file", "arguments": {"path": "README.md"}}


def _decision(*, allow: bool, cached: bool) -> GuardrailDecision:
    code = "typesafe.allowed" if allow else "typesafe.tool_call_risky"
    return GuardrailDecision(allow=allow, reasons=[GuardrailReason(code=code, message=f"{code}: p=0.5")], metadata={"cached": cached})


class _ScriptedProvider:
    """Replays a fixed sequence of decisions and errors."""

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self.calls = 0

    async def aevaluate(self, request) -> GuardrailDecision:
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _args(**overrides) -> argparse.Namespace:
    base = {
        "api_key_env": "TYPESAFE_API_KEY",
        "base_url": "https://api.typesafe.test",
        "model": "jev-test",
        "threshold": 0.5,
        "tools": "",
        "allowed_tools": "",
        "max_state_chars": 4000,
        "timeout": 5.0,
        "deadline_seconds": 10.0,
        "max_attempts": 2,
        "retry_backoff": 0.0,
        "skip_cache_pass": False,
    }
    return argparse.Namespace(**{**base, **overrides})


def _scripted_providers(monkeypatch, *, main_script: list[object], cache_script: list[object]) -> dict[bool, _ScriptedProvider]:
    providers = {False: _ScriptedProvider(main_script), True: _ScriptedProvider(cache_script)}
    monkeypatch.setattr(eval_script, "_provider", lambda args, *, cache_enabled: providers[cache_enabled])
    return providers


def _collect(monkeypatch, *, main_script: list[object], cache_script: list[object]):
    _scripted_providers(monkeypatch, main_script=main_script, cache_script=cache_script)
    return asyncio.run(eval_script._collect(_args(), [_SAFE_CASE]))


def _loopback_available() -> bool:
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        probe.close()
        return True
    except OSError:
        return False


# The two tests below need a real loopback peer; a sandbox that forbids binding
# cannot exercise them, and that is an environment limit rather than a defect.
_LOOPBACK = pytest.mark.skipif(not _loopback_available(), reason="loopback sockets are unavailable in this environment")


@contextlib.contextmanager
def _loopback_peer() -> Iterator[int]:
    """A loopback peer that accepts one connection and closes it immediately."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept_and_drop() -> None:
        connection, _ = listener.accept()
        connection.close()

    thread = threading.Thread(target=accept_and_drop, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(timeout=5)


def test_allowed_tools_refusals_get_their_own_population_and_stay_out_of_the_score(monkeypatch):
    """A permission refusal is neither a network sample nor a local state failure."""
    refusal = GuardrailDecision(
        allow=False,
        reasons=[GuardrailReason(code="typesafe.tool_not_allowed", message="typesafe.tool_not_allowed: tool='read_file' not in configured allowed_tools")],
        metadata={"tool_not_allowed": True},
    )
    collection = _collect(monkeypatch, main_script=[refusal], cache_script=[])

    outcome = collection.outcomes[0]
    assert (outcome.population, outcome.verdict) == (eval_script.NOT_ALLOWED, "deny")
    # The population name is a report/JSON field: pin the literal so a rename
    # cannot ship a mangled value unnoticed.
    assert eval_script.NOT_ALLOWED == "not_allowed"
    assert eval_script._score(collection.outcomes, fail_open=False)["safe_cases"] == 0


def test_tool_and_allowed_tools_lists_ignore_surrounding_whitespace(monkeypatch):
    """``--tools "bash, write_file"`` must probe both tools, not silently treat
    ``" write_file"`` as an unknown name."""
    monkeypatch.setenv("TYPESAFE_TEST_KEY", "key")
    provider = eval_script._provider(_args(api_key_env="TYPESAFE_TEST_KEY", tools="bash, write_file", allowed_tools=" bash , read_file "), cache_enabled=False)

    declared = provider.release_policy_parameters()
    assert declared["tools"] == ["bash", "write_file"]
    assert declared["allowed_tools"] == ["bash", "read_file"]


def test_failed_warming_leaves_the_next_call_a_network_evaluation(monkeypatch):
    providers = _scripted_providers(
        monkeypatch,
        main_script=[_decision(allow=True, cached=False)],
        cache_script=[TypeSafeGuardrailError("TypeSafe returned HTTP 503", cause="http_status"), _decision(allow=True, cached=False)],
    )

    collection = asyncio.run(eval_script._collect(_args(), [_SAFE_CASE]))

    assert [(outcome.population, outcome.verdict) for outcome in collection.outcomes] == [(eval_script.NETWORK, "allow"), (eval_script.NETWORK, "allow")]
    assert providers[True].calls == 2  # warming was attempted, and the second call really did reach the network
    # The warming failure is retained instead of being swallowed.
    assert [(outcome.pass_name, outcome.verdict, outcome.detail.split(":")[0]) for outcome in collection.warming] == [("warming", "error", "http_status")]
    assert eval_script._summarize(collection.outcomes)[eval_script.NETWORK]["n"] == 2
    assert eval_script._summarize(collection.outcomes)[eval_script.CACHE_HIT]["n"] == 0


def test_cache_hit_is_classified_from_the_response(monkeypatch):
    collection = _collect(
        monkeypatch,
        main_script=[_decision(allow=True, cached=False)],
        cache_script=[_decision(allow=True, cached=False), _decision(allow=True, cached=True)],
    )

    assert [outcome.population for outcome in collection.outcomes] == [eval_script.NETWORK, eval_script.CACHE_HIT]
    assert collection.outcomes[1].cached is True
    assert [outcome.verdict for outcome in collection.warming] == ["allow"]


def test_cache_pass_samples_are_not_counted_twice_in_the_scores(monkeypatch):
    collection = _collect(
        monkeypatch,
        main_script=[_decision(allow=False, cached=False)],
        cache_script=[_decision(allow=False, cached=False), _decision(allow=False, cached=True)],
    )

    score = eval_script._score(collection.outcomes, fail_open=False)

    assert len(collection.outcomes) == 2
    assert score["safe_cases"] == 1, "the cache pass re-evaluates the same case; it must not be weighted twice"
    assert score["safe_blocked"] == 1


@_LOOPBACK
def test_connection_probe_reports_unmeasurable_tls_without_raising():
    """A peer that accepts TCP and then drops the handshake must not abort the report."""
    with _loopback_peer() as port:
        result = eval_script._connection_cost(f"https://127.0.0.1:{port}", attempts=1)

    assert result["measured"] is True
    assert len(result["dns_seconds"]) == 1 and len(result["tcp_seconds"]) == 1
    assert result["tls_seconds"] is None
    assert result["tls_note"].startswith("not measured:")


@_LOOPBACK
def test_plain_http_endpoint_reports_tls_as_not_applicable():
    with _loopback_peer() as port:
        result = eval_script._connection_cost(f"http://127.0.0.1:{port}", attempts=1)

    assert result["measured"] is True
    assert result["tls_seconds"] is None
    assert result["tls_note"] == "not measured (plain http endpoint)"


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), ConnectionResetError("peer reset"), ssl.SSLError("EOF occurred in violation of protocol")])
def test_any_handshake_oserror_leaves_the_report_intact(monkeypatch, failure):
    """The reviewed failure modes: a handshake timeout or a peer reset are OSError, not SSLError.

    DNS and TCP are stubbed so the only failing stage is the handshake; the probe
    must report that stage as unmeasured and still return a reportable dict.
    """
    raw = socket.socket()  # a real socket object, never connected; only closed by the probe
    monkeypatch.setattr(eval_script.socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    monkeypatch.setattr(eval_script.socket, "create_connection", lambda address, timeout: raw)

    def explode(self, sock, server_hostname=None, **kwargs):
        raise failure

    monkeypatch.setattr(eval_script.ssl.SSLContext, "wrap_socket", explode)

    result = eval_script._safe_connection_cost("https://api.typesafe.test", attempts=1)

    assert result["measured"] is True
    assert result["tls_seconds"] is None
    assert result["tls_note"].startswith(f"not measured: {type(failure).__name__}")
    raw.close()


def test_connection_probe_failure_is_reported_instead_of_aborting(monkeypatch):
    def explode(base_url: str, attempts: int) -> dict:
        raise TimeoutError("handshake timed out")

    monkeypatch.setattr(eval_script, "_connection_cost", explode)

    result = eval_script._safe_connection_cost("https://api.typesafe.test", attempts=1)

    assert result["measured"] is False
    assert "TimeoutError" in result["reason"]
