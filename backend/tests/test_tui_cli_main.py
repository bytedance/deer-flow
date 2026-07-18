"""Integration tests for ``main`` dispatch (headless paths), with a fake session."""

import json

from deerflow.client import StreamEvent
from deerflow.tui import cli


class _FakeClient:
    def chat(self, message, *, thread_id=None, **kwargs):
        return f"answer:{message}"

    def stream(self, message, *, thread_id=None, **kwargs):
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "hi", "id": "m1"})
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 1}})


class _FakeSession:
    def __init__(self):
        self.client = _FakeClient()

    def resolve_thread(self, plan):
        return None


def test_main_print_outputs_chat_answer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--print", "hello"])
    assert rc == 0
    assert "answer:hello" in capsys.readouterr().out


def test_main_json_emits_ndjson_stream_events(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--json", "hello"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    payloads = [json.loads(ln) for ln in lines]
    assert payloads[0]["type"] == "messages-tuple"
    assert payloads[-1]["type"] == "end"


def test_main_headless_help_returns_2_and_prints_usage(monkeypatch, capsys):
    # On a TTY with no message and no piped stdin, --cli has nothing to run.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    rc = cli.main(["--cli"])
    assert rc == 2
    assert "deerflow" in capsys.readouterr().err
