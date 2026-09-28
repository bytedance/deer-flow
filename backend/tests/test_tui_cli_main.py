"""Integration tests for ``main`` dispatch (headless paths), with a fake session."""

import json
from types import SimpleNamespace

import pytest

from deerflow.agents.middlewares.human_in_the_loop import DISABLE_TOOL_APPROVAL_KEY
from deerflow.client import StreamEvent
from deerflow.tui import cli

# Every headless run carries the tool-approval downgrade: the TUI has no approval
# surface yet, so it must not let a gated tool park a run nobody can resume. The
# assertions below are about the recursion-limit kwarg and spell out both rather
# than filtering, so the kwargs a headless run sends stay fully pinned. Drop this
# entry in the change that gives the TUI an approval prompt. See
# ``tests/test_tool_approval_client_downgrade.py``.
_DOWNGRADE = {DISABLE_TOOL_APPROVAL_KEY: True}


class _FakeClient:
    def __init__(self):
        self.chat_kwargs = None
        self.stream_kwargs = None

    def chat(self, message, *, thread_id=None, **kwargs):
        self.chat_kwargs = kwargs
        return f"answer:{message}"

    def stream(self, message, *, thread_id=None, **kwargs):
        self.stream_kwargs = kwargs
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "hi", "id": "m1"})
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 1}})


class _FakeSession:
    latest = None

    def __init__(self):
        self.client = _FakeClient()
        type(self).latest = self

    def resolve_thread(self, plan):
        return None


def test_main_print_outputs_chat_answer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--print", "hello"])
    assert rc == 0
    assert "answer:hello" in capsys.readouterr().out


def test_main_print_passes_explicit_recursion_limit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--recursion-limit", "250", "--print", "hello"])
    assert rc == 0
    assert _FakeSession.latest.client.chat_kwargs == {**_DOWNGRADE, "recursion_limit": 250}


def test_main_print_omits_default_recursion_limit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--print", "hello"])
    assert rc == 0
    assert _FakeSession.latest.client.chat_kwargs == _DOWNGRADE


def test_main_json_emits_ndjson_stream_events(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--json", "hello"])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    payloads = [json.loads(ln) for ln in lines]
    assert payloads[0]["type"] == "messages-tuple"
    assert payloads[-1]["type"] == "end"


def test_main_json_passes_explicit_recursion_limit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    rc = cli.main(["--recursion-limit", "250", "--json", "hello"])
    assert rc == 0
    assert _FakeSession.latest.client.stream_kwargs == {**_DOWNGRADE, "recursion_limit": 250}


def test_invalid_recursion_limit_fails_before_session_creation(monkeypatch):
    def fail_if_called():
        raise AssertionError("session should not be created for invalid CLI input")

    monkeypatch.setattr(cli, "_make_session", fail_if_called)
    with pytest.raises(SystemExit):
        cli.main(["--recursion-limit", "0", "--print", "hello"])


def test_main_headless_help_returns_2_and_prints_usage(monkeypatch, capsys):
    # On a TTY with no message and no piped stdin, --cli has nothing to run.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    rc = cli.main(["--cli"])
    assert rc == 2
    assert "deerflow" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Headless error boundary: client/setup failures must not escape main() as
# tracebacks. --print reports on stderr; --json appends one terminal error
# record while keeping every stdout line valid NDJSON. KeyboardInterrupt and
# SystemExit are not part of the boundary.
# --------------------------------------------------------------------------- #


def _raising_session(exc, *, stream_events_before_failure=0):
    def fail(*args, **kwargs):
        raise exc

    def stream(message, *, thread_id=None, **kwargs):
        for _ in range(stream_events_before_failure):
            yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "hi", "id": "m1"})
        raise exc

    return SimpleNamespace(resolve_thread=lambda plan: "thread-1", client=SimpleNamespace(chat=fail, stream=stream))


def test_main_print_client_failure_reports_error_without_traceback(monkeypatch, capsys):
    session = _raising_session(RuntimeError("Thread requires delta mode"))
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    rc = cli.main(["--print", "hello"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Thread requires delta mode" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_main_json_failure_before_first_event_emits_single_error_record(monkeypatch, capsys):
    session = _raising_session(RuntimeError("Thread requires delta mode"))
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    rc = cli.main(["--json", "hello"])
    captured = capsys.readouterr()
    assert rc == 1
    payloads = [json.loads(ln) for ln in captured.out.splitlines() if ln.strip()]
    assert payloads == [{"type": "error", "data": {"message": "Thread requires delta mode"}}]
    assert "Thread requires delta mode" in captured.err


def test_main_json_failure_after_event_keeps_every_line_valid_json(monkeypatch, capsys):
    session = _raising_session(RuntimeError("checkpoint mode mismatch"), stream_events_before_failure=1)
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    rc = cli.main(["--json", "hello"])
    captured = capsys.readouterr()
    assert rc == 1
    payloads = [json.loads(ln) for ln in captured.out.splitlines() if ln.strip()]
    assert payloads[0]["type"] == "messages-tuple"
    assert payloads[-1] == {"type": "error", "data": {"message": "checkpoint mode mismatch"}}


def test_main_session_creation_failure_reports_error_without_traceback(monkeypatch, capsys):
    def fail():
        raise RuntimeError("no checkpointer configured")

    monkeypatch.setattr(cli, "_make_session", fail)
    rc = cli.main(["--print", "hello"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no checkpointer configured" in captured.err
    assert "Traceback" not in captured.err


def test_main_thread_resolution_failure_emits_json_error_record(monkeypatch, capsys):
    def fail():
        raise RuntimeError("thread lookup failed")

    session = SimpleNamespace(resolve_thread=lambda plan: fail(), client=SimpleNamespace())
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    rc = cli.main(["--json", "hello"])
    captured = capsys.readouterr()
    assert rc == 1
    payloads = [json.loads(ln) for ln in captured.out.splitlines() if ln.strip()]
    assert payloads[-1]["type"] == "error"


def test_main_headless_boundary_preserves_keyboard_interrupt(monkeypatch):
    session = _raising_session(KeyboardInterrupt())
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["--print", "hello"])


class _BrokenStdout:
    """A stdout whose consumer closed the pipe early (e.g. ``| head``)."""

    def isatty(self):
        return False

    def write(self, *_args, **_kwargs):
        raise BrokenPipeError

    def flush(self):
        pass

    def fileno(self):
        raise OSError  # forces the devnull dup2 to take its best-effort path


def test_main_print_broken_pipe_exits_without_traceback(monkeypatch):
    monkeypatch.setattr(cli, "_make_session", _FakeSession)
    monkeypatch.setattr(cli.sys, "stdout", _BrokenStdout())
    rc = cli.main(["--print", "hello"])
    assert rc == 1


def test_main_json_broken_pipe_error_record_fails_silently(monkeypatch):
    session = _raising_session(RuntimeError("boom"))
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    monkeypatch.setattr(cli.sys, "stdout", _BrokenStdout())
    rc = cli.main(["--json", "hello"])
    assert rc == 1
