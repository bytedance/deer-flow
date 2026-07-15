from __future__ import annotations

import io
import json
from pathlib import Path

from deerflow.evaluation.cli import main


class _Response:
    def __init__(self, payload=None, text: str | None = None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _Client:
    requests: list[tuple[str, str, dict]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, path: str, **kwargs):
        self.requests.append(("POST", path, kwargs))
        return _Response({"eval_run_id": "eval-run-1", "status": "queued", "suite_name": "suite", "suite_digest": "abc", "total_items": 1})

    def get(self, path: str, **kwargs):
        self.requests.append(("GET", path, kwargs))
        if path.endswith("/report"):
            if kwargs.get("params", {}).get("format") == "markdown":
                return _Response(text="# Report\n")
            return _Response({"schema_version": "deerflow.evaluation.report.v1"})
        return _Response({"id": "eval-run-1", "status": "completed"})


def _suite_file(tmp_path: Path) -> Path:
    path = tmp_path / "suite.yaml"
    path.write_text(
        """
name: suite
items:
  - id: case-1
    type: task
    input:
      prompt: hello
""".strip(),
        encoding="utf-8",
    )
    return path


def test_eval_cli_run_posts_normalized_suite_and_idempotency_header(tmp_path):
    _Client.requests = []
    stdout = io.StringIO()
    suite = _suite_file(tmp_path)

    code = main(
        ["--gateway-url", "http://gateway", "run", str(suite), "--idempotency-key", "idem-1", "--start"],
        client_factory=_Client,
        stdout=stdout,
    )

    assert code == 0
    assert "LangSmith sync: disabled" in stdout.getvalue()
    method, path, kwargs = _Client.requests[0]
    assert (method, path) == ("POST", "/api/evals")
    assert kwargs["headers"] == {"Idempotency-Key": "idem-1"}
    assert kwargs["json"]["suite"]["name"] == "suite"
    assert kwargs["json"]["config"]["suite_path"] == str(suite.resolve())
    assert kwargs["json"]["start_immediately"] is True


def test_eval_cli_status_fetches_eval_run():
    _Client.requests = []
    stdout = io.StringIO()

    code = main(["status", "eval-run-1"], client_factory=_Client, stdout=stdout)

    assert code == 0
    assert _Client.requests[0] == ("GET", "/api/evals/eval-run-1", {})
    assert '"status": "completed"' in stdout.getvalue()


def test_eval_cli_report_supports_markdown():
    _Client.requests = []
    stdout = io.StringIO()

    code = main(["report", "eval-run-1", "--format", "markdown"], client_factory=_Client, stdout=stdout)

    assert code == 0
    assert _Client.requests[0] == ("GET", "/api/evals/eval-run-1/report", {"params": {"format": "markdown"}})
    assert stdout.getvalue() == "# Report\n"
