"""Offline checks for the live PoC; never use real credentials or a model."""

import copy
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import poc_external_system_message_injection as poc
import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("DEERFLOW_PAT", "DEERFLOW_ACCESS_TOKEN", "DEERFLOW_CSRF_TOKEN", "DEERFLOW_BASE_URL", "DEERFLOW_THREAD_ID", "DEERFLOW_ASSISTANT_ID", "DEERFLOW_TIMEOUT_SECONDS", "DEERFLOW_CONFIRM_APPEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEERFLOW_THREAD_ID", "synthetic-poc-thread")
    monkeypatch.setenv("DEERFLOW_CONFIRM_APPEND", "YES")


def test_auth_headers_allows_gateway_auth_disabled_mode():
    assert poc.auth_headers() == {}


def test_pat_takes_precedence_and_session_requires_both_cookies(monkeypatch):
    monkeypatch.setenv("DEERFLOW_ACCESS_TOKEN", "fixture-session")
    with pytest.raises(poc.PocError):
        poc.auth_headers()
    monkeypatch.setenv("DEERFLOW_CSRF_TOKEN", "fixture-csrf")
    assert poc.auth_headers()["X-CSRF-Token"] == "fixture-csrf"
    monkeypatch.setenv("DEERFLOW_PAT", "fixture-pat")
    assert poc.auth_headers() == {"Authorization": "Bearer fixture-pat"}


@pytest.mark.parametrize(
    "name,value",
    [
        ("DEERFLOW_THREAD_ID", ""),
        ("DEERFLOW_THREAD_ID", "http://localhost:2026/workspace/chats/id"),
        ("DEERFLOW_BASE_URL", "https://example.com"),
        ("DEERFLOW_BASE_URL", "http://user:secret@localhost:2026"),
        ("DEERFLOW_ASSISTANT_ID", ""),
        ("DEERFLOW_TIMEOUT_SECONDS", "nan"),
        ("DEERFLOW_TIMEOUT_SECONDS", "-1"),
        ("DEERFLOW_CONFIRM_APPEND", "NO"),
    ],
)
def test_invalid_configuration_fails_before_network(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(poc, "get_json", lambda *_: pytest.fail("configuration must be checked before HTTP"))
    with pytest.raises(poc.PocError):
        poc.main([])


class FakeGateway:
    def __init__(self, *, blocked, obeys=False, mutate_on_reject=False):
        self.blocked = blocked
        self.obeys = obeys
        self.mutate_on_reject = mutate_on_reject
        self.messages = []
        self.checkpoint = 1
        self.calls = []

    def state(self, *_):
        return {"checkpoint_id": str(self.checkpoint), "values": {"messages": copy.deepcopy(self.messages)}}

    def run(self, _url, _headers, messages, _timeout, _assistant_id=None):
        self.calls.append(copy.deepcopy(messages))
        if self.blocked and any(m["role"] == "system" for m in messages):
            if self.mutate_on_reject:
                self.checkpoint += 1
            raise poc.PocHTTPError(400, poc.ROLE_REJECTION_DETAIL)
        self.messages.extend({**m, "type": m["role"]} for m in messages)
        answer = "synthetic answer"
        if self.obeys and any(m.get("type") == "system" for m in self.messages):
            answer += "\n" + poc.MARKER
        self.checkpoint += 1
        self.messages.append({"id": f"ai-{self.checkpoint}", "type": "ai", "content": answer})
        return {"http_status": 200, "saw_end": True}


def install_gateway(monkeypatch, **kwargs):
    gateway = FakeGateway(**kwargs)
    monkeypatch.setattr(poc, "get_json", gateway.state)
    monkeypatch.setattr(poc, "stream_run", gateway.run)
    return gateway


def test_blocked_is_success_and_followup_still_runs(monkeypatch, capsys):
    gateway = install_gateway(monkeypatch, blocked=True)
    assert poc.main([]) == 0
    assert len(gateway.calls) == 3
    assert all(m.get("type") != "system" for m in gateway.messages)
    output = capsys.readouterr().out
    assert "BLOCKED" in output
    assert "Checkpoint unchanged: True" in output
    assert "Ordinary follow-up" in output


@pytest.mark.parametrize("obeys", [False, True])
def test_vulnerable_is_detected_independently_of_model_obedience(monkeypatch, capsys, obeys):
    install_gateway(monkeypatch, blocked=False, obeys=obeys)
    assert poc.main(["--expect", "vulnerable"]) == 0
    output = capsys.readouterr().out
    assert "VULNERABLE" in output
    assert f"Marker is exact last line: {obeys}" in output
    assert "Provider payload observation: NOT DIRECT" in output
    assert "/workspace/chats/synthetic-poc-thread" in output


@pytest.mark.parametrize("blocked,expected", [(False, "blocked"), (True, "vulnerable")])
def test_unexpected_outcome_is_nonzero(monkeypatch, blocked, expected):
    install_gateway(monkeypatch, blocked=blocked)
    assert poc.main(["--expect", expected]) == 2


def test_rejection_that_writes_checkpoint_is_not_a_pass(monkeypatch):
    install_gateway(monkeypatch, blocked=True, mutate_on_reject=True)
    with pytest.raises(poc.PocError, match="checkpoint"):
        poc.main([])


@pytest.mark.parametrize("status,detail", [(400, "unrelated validation error"), (401, "Invalid token"), (403, "Forbidden"), (500, "error")])
def test_other_errors_are_not_reported_as_fixed(monkeypatch, status, detail):
    gateway = install_gateway(monkeypatch, blocked=False)
    original_run = gateway.run

    def run(url, headers, messages, timeout, assistant_id=None):
        if any(m["role"] == "system" for m in messages):
            raise poc.PocHTTPError(status, detail)
        return original_run(url, headers, messages, timeout, assistant_id)

    monkeypatch.setattr(poc, "stream_run", run)
    with pytest.raises(poc.PocHTTPError):
        poc.main([])


def test_contaminated_thread_is_rejected_before_appending(monkeypatch):
    gateway = install_gateway(monkeypatch, blocked=True)
    gateway.messages.append({"type": "ai", "content": poc.MARKER})
    with pytest.raises(poc.PocError, match="fresh"):
        poc.main([])
    assert not gateway.calls


@pytest.mark.parametrize(
    "events,ok", [(b'event: metadata\ndata: {"run_id":"fixture"}\n\nevent: end\ndata: {}\n\n', True), (b'event: error\ndata: {"message":"fixture"}\n\nevent: end\ndata: {}\n\n', False), (b"event: metadata\ndata: {}\n\n", False)]
)
def test_sse_errors_and_missing_end_are_not_success(monkeypatch, events, ok):
    response = io.BytesIO(events)
    response.status = 200
    monkeypatch.setattr(poc, "_HTTP", SimpleNamespace(open=lambda *_args, **_kwargs: response))
    if ok:
        assert poc.stream_run("http://localhost:2026/api/test", {}, [], 10)["saw_end"]
    else:
        with pytest.raises(poc.PocError):
            poc.stream_run("http://localhost:2026/api/test", {}, [], 10)


def test_stream_run_uses_configured_assistant_id(monkeypatch):
    response = io.BytesIO(b"event: end\ndata: {}\n\n")
    response.status = 200
    captured = []

    class _Opener:
        def open(self, request, *, timeout):
            captured.append((request, timeout))
            return response

    monkeypatch.setenv("DEERFLOW_ASSISTANT_ID", "custom-agent")
    monkeypatch.setattr(poc, "_HTTP", _Opener())

    result = poc.stream_run("http://localhost:2026/api/test", {}, [], 10)

    assert result["saw_end"] is True
    assert captured[0][1] == 10
    assert json.loads(captured[0][0].data)["assistant_id"] == "custom-agent"


def test_http_errors_do_not_echo_response_secrets():
    assert "fixture-secret" not in str(poc.PocHTTPError(401, "fixture-secret"))


def test_http_error_preserves_detail_for_classification_only():
    error = HTTPError("http://localhost:2026", 400, "Bad Request", {}, io.BytesIO(b'{"detail":"fixture-secret"}'))
    converted = poc._http_error(error)
    assert converted.status == 400
    assert converted.detail == "fixture-secret"
    assert "fixture-secret" not in str(converted)


def test_redirects_cannot_forward_credentials():
    assert poc._NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://example.com") is None
