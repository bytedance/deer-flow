"""Exercise the triage script through HTTP responses, reports and gh boundaries."""

from __future__ import annotations

import html
import http.client
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "score_issues.py"


@pytest.fixture
def script_path(tmp_path):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / ".github").mkdir()
    shutil.copy(REPO_ROOT / ".github" / "labels.yml", root / ".github" / "labels.yml")
    script = root / "scripts" / "score_issues.py"
    shutil.copy(SCRIPT_PATH, script)
    return script


@pytest.fixture
def scorer(script_path):
    spec = importlib.util.spec_from_file_location("score_issues", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def issue():
    return {"number": 42, "title": "工具调用失败", "body": "切换模型后，已有任务无法继续。", "url": "https://github.com/bytedance/deer-flow/issues/42", "labels": []}


@pytest.fixture
def facts():
    return {
        "trigger_quote": ["切换模型后"],
        "impact_quote": ["已有任务无法继续"],
        "kind": "bug",
        "area": "backend",
        "extension_hook": "",
        "priority": "P2",
        "route": "fix",
        "reason_zh": "切换模型后已有任务无法继续，属于实际工作流故障。",
    }


def response(facts, *, status="completed"):
    return {"status": status, "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(facts, ensure_ascii=False)}]}], "usage": {"input_tokens": 1100, "output_tokens": 1300, "total_tokens": 2400}}


@pytest.fixture
def transport(scorer, monkeypatch):
    calls = []

    def install(raw):
        def urlopen(request, **kwargs):
            calls.append((request, json.loads(request.data)))
            return io.BytesIO(json.dumps(raw).encode("utf-8"))

        monkeypatch.setattr(scorer.urllib.request, "urlopen", urlopen)
        return calls

    return install


def test_medium_uses_one_structured_call_full_body_and_no_author_or_labels(scorer, transport, issue, facts):
    issue.update(body="x" * 9000 + "\n切换模型后，已有任务无法继续。", author={"login": "not-model-input"}, labels=[{"name": "P0"}])
    calls = transport(response(facts))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert len(calls) == 1
    request, payload = calls[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert payload["model"] == "gpt-6.1-terra"
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 6500
    assert payload["text"]["format"]["strict"] is True
    assert len(payload["text"]["format"]["schema"]["required"]) == 8
    assert json.loads(payload["input"][1]["content"]) == {"title": issue["title"], "body": issue["body"]}
    assert result["llm"] == facts
    assert result["usage"]["total_tokens"] == 2400
    assert result["scoring"]["priority"] == "P2"
    assert result["scoring"]["needs_review"] is False
    assert result["scoring"]["suggested_labels"] == ["bug", "area:backend", "P2"]


@pytest.mark.parametrize("route", ["assign", "design", "extension", "governance"])
def test_priority_is_independent_of_routing(scorer, transport, issue, facts, route):
    facts.update(kind="governance" if route == "governance" else "feature", priority="P1", route=route, extension_hook="MCP" if route == "extension" else "")
    transport(response(facts))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert result["scoring"]["priority"] == "P1"
    assert result["scoring"]["route"] == route
    assert not result["scoring"]["needs_review"]
    assert "total_score" not in result["scoring"]


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"trigger_quote": ["a paraphrase"]}, "连续原文子串"),
        ({"impact_quote": []}, "缺少实际后果"),
        ({"impact_quote": ["x" * 161]}, "1–160"),
        ({"impact_quote": ["工具调用失败"] * 3}, "最多两段"),
        ({"trigger_quote": "切换模型后"}, "最多两段"),
        ({"trigger_quote": [None]}, "字符串"),
        ({"priority": []}, "无效枚举"),
        ({"route": "extension"}, "extension_hook"),
        ({"route": "extension", "extension_hook": "imaginary_hook"}, "无效枚举"),
        ({"extension_hook": "MCP"}, "extension_hook"),
        ({"priority": "Not-Applicable"}, "pr_review"),
        ({"route": "pr_review"}, "Not-Applicable"),
        ({"kind": "unknown"}, "无法识别诉求"),
        ({"reason_zh": []}, "缺少判断理由"),
        ({"extra": "field"}, "额外字段"),
    ],
)
def test_invalid_results_remain_visible_without_labels_or_repair_calls(scorer, transport, issue, facts, updates, error):
    facts.update(updates)
    calls = transport(response(facts))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert len(calls) == 1
    assert result["llm"] == facts
    assert result["scoring"]["needs_review"]
    assert result["scoring"]["suggested_labels"] == []
    report = scorer.render_markdown_report([result])
    assert "需人工复核" in report
    assert error in html.unescape(report)
    assert "工具调用失败" in report


@pytest.mark.parametrize("bad", [None, [], "text", {"priority": "P1"}])
def test_malformed_assessment_is_reported_not_dropped(scorer, transport, issue, bad):
    calls = transport(response(bad))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert len(calls) == 1
    assert result["scoring"]["needs_review"]
    assert result["scoring"]["suggested_labels"] == []
    assert "工具调用失败" in scorer.render_markdown_report([result])


@pytest.mark.parametrize(("priority", "route", "kind"), [("Needs-Info", "needs_info", "unknown"), ("Not-Applicable", "pr_review", "bug")])
def test_nonordinal_priorities_remain_distinct_and_unlabeled(scorer, transport, issue, facts, priority, route, kind):
    facts.update(priority=priority, route=route, kind=kind, trigger_quote=[], impact_quote=[])
    transport(response(facts))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert result["scoring"]["priority"] == priority
    assert result["scoring"]["suggested_labels"] == []
    assert not result["scoring"]["needs_review"]
    assert priority in scorer.render_markdown_report([result])


@pytest.mark.parametrize(
    "raw", [response({}, status="incomplete"), {"status": "completed", "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]}, {"status": "completed", "output": [{"content": [{"type": "output_text", "text": "not json"}]}]}, []]
)
def test_incomplete_refused_or_invalid_response_never_becomes_a_priority(scorer, transport, issue, raw):
    calls = transport(raw)
    result = scorer.evaluate_issue(issue, api_key="test-key")
    assert len(calls) == 1
    assert result["scoring"]["priority"] == "Needs-Info"
    assert result["scoring"]["needs_review"]
    assert not result["scoring"]["suggested_labels"]


@pytest.mark.parametrize("model", ["gpt-6.1-terra", "gpt-4o-mini"])
def test_chat_completions_compatibility(scorer, transport, issue, facts, model):
    calls = transport({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(facts)}}], "usage": {"total_tokens": 123}})
    result = scorer.evaluate_issue(issue, api_key="test-key", base_url="https://proxy.example/v1/chat/completions", api_format="chat-completions", model=model, reasoning_effort="high")
    request, payload = calls[0]
    assert request.full_url == "https://proxy.example/v1/chat/completions"
    assert payload["response_format"]["json_schema"]["strict"]
    if model == "gpt-6.1-terra":
        assert payload["reasoning_effort"] == "high"
        assert payload["max_completion_tokens"] == 6500
        assert "max_tokens" not in payload
    else:
        assert "reasoning_effort" not in payload
        assert payload["max_tokens"] == 6500
    assert not result["scoring"]["needs_review"]


@pytest.mark.parametrize(("status", "expected_calls"), [(401, 1), (429, 3), (503, 3)])
def test_transport_retries_are_bounded_and_errors_redact_credentials(scorer, monkeypatch, issue, status, expected_calls):
    calls = []

    def fail(request, **kwargs):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, "test-secret-key", {}, io.BytesIO(b"test-secret-key"))

    monkeypatch.setattr(scorer.urllib.request, "urlopen", fail)
    monkeypatch.setattr(scorer.time, "sleep", lambda _: None)
    result = scorer.evaluate_issue(issue, api_key="test-secret-key")
    assert len(calls) == expected_calls
    assert str(status) in result["scoring"]["validation_errors"][0]
    assert "test-secret-key" not in json.dumps(result)
    assert result["scoring"]["needs_review"]


def test_report_keeps_quotes_but_escapes_issue_markup(scorer, transport, issue, facts):
    quote = "<script> | [link](https://example.com)\n下一行"
    issue["body"] += quote
    facts["impact_quote"] = [quote]
    transport(response(facts))
    result = scorer.evaluate_issue(issue, api_key="test-key")
    report = scorer.render_markdown_report([result])
    assert result["llm"]["impact_quote"] == [quote]
    assert "<script>" not in report
    assert "&lt;script&gt; &#124; &#91;link&#93;" in report
    assert "<br>下一行" in report
    assert report.splitlines()[-1].count("|") == 12


def test_report_links_only_validated_issue_numbers_and_escapes_free_text(scorer, transport, issue, facts):
    issue["number"] = "42]|![badge](https://example.com/badge)"
    facts["reason_zh"] = "说明 | ![badge](https://example.com/badge)"
    transport(response(facts))
    report = scorer.render_markdown_report([scorer.evaluate_issue(issue, api_key="test-key")])
    assert "| ![badge]" not in report
    assert "![badge]" not in report
    assert "https://github.com/bytedance/deer-flow/issues/42" not in report
    assert report.splitlines()[-1].count("|") == 12


def test_cli_offline_preview_under_ascii_stdout_never_labels(script_path, tmp_path, issue):
    input_file = tmp_path / "issues.json"
    output_file = tmp_path / "results.json"
    input_file.write_text(json.dumps([issue], ensure_ascii=False), encoding="utf-8-sig")
    result = subprocess.run(
        [sys.executable, str(script_path), "--input-json", str(input_file), "--output-json", str(output_file), "--repo", "bytedance/deer-flow", "--offline", "--dry-run"],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "需人工复核" in result.stdout.decode("utf-8")
    assert b"gh issue edit" not in result.stdout
    assert "跳过标签写入" in result.stderr.decode("utf-8")
    parsed = json.loads(output_file.read_text(encoding="utf-8"))
    assert parsed[0]["scoring"]["priority"] == "Needs-Info"
    assert parsed[0]["scoring"]["needs_review"]


@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("live_labels", [["P0"], ["p1"], []])
def test_cli_apply_preserves_live_priority_and_skips_invalid_evidence(scorer, transport, monkeypatch, tmp_path, issue, facts, live_labels, valid):
    if not valid:
        facts["trigger_quote"] = ["invented evidence"]
    calls = transport(response(facts))
    input_file = tmp_path / "issues.json"
    output_file = tmp_path / "results.json"
    input_file.write_text(json.dumps(issue), encoding="utf-8")
    gh_calls = []

    def gh(cmd, **kwargs):
        gh_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"labels": [{"name": label} for label in live_labels]}), "")

    monkeypatch.setattr(scorer.subprocess, "run", gh)
    assert scorer.main(["--repo", "bytedance/deer-flow", "--input-json", str(input_file), "--api-key", "test-key", "--output-json", str(output_file), "--apply-labels"]) == 0
    assert len(calls) == 1
    if valid:
        assert gh_calls == [["gh", "issue", "view", issue["url"], "--json", "labels"], ["gh", "issue", "edit", issue["url"], "--add-label", "bug,area:backend" + ("" if live_labels else ",P2")]]
    else:
        assert gh_calls == []
    assert json.loads(output_file.read_text())[0]["scoring"]["needs_review"] is not valid


def test_empty_label_catalog_never_invents_labels(scorer, transport, issue, facts):
    transport(response(facts))
    assert scorer.evaluate_issue(issue, api_key="test-key", declared_labels=set())["scoring"]["suggested_labels"] == []


def test_missing_key_requires_explicit_offline_preview(scorer, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TRIAGE_LLM_API_KEY", raising=False)
    assert scorer.main([]) == 1
    assert "Missing API key" in capsys.readouterr().err


@pytest.mark.parametrize("failure_first", [True, False])
@pytest.mark.parametrize("error_type", [http.client.IncompleteRead, ConnectionResetError])
def test_batch_retains_successes_and_failed_issue_on_unexpected_read_error(scorer, monkeypatch, tmp_path, issue, facts, capsys, failure_first, error_type):
    failed = {**issue, "number": 43, "url": "https://github.com/bytedance/deer-flow/issues/43", "title": "读取中断"}
    items = [failed, issue] if failure_first else [issue, failed]
    source = tmp_path / "issues.json"
    output = tmp_path / "results.json"
    report = tmp_path / "report.md"
    source.write_text(json.dumps(items), encoding="utf-8")
    calls = []

    class BrokenResponse(io.BytesIO):
        def read(self, *args, **kwargs):
            raise error_type(b"secret-from-response")

    def urlopen(request, **kwargs):
        title = json.loads(json.loads(request.data)["input"][1]["content"])["title"]
        calls.append(title)
        return BrokenResponse() if title == failed["title"] else io.BytesIO(json.dumps(response(facts)).encode())

    monkeypatch.setattr(scorer.urllib.request, "urlopen", urlopen)
    status = scorer.main(["--input-json", str(source), "--output-json", str(output), "--output-md", str(report), "--api-key", "test-key", "--repo", "bytedance/deer-flow", "--dry-run", "--workers", "1"])
    assert status == 1
    assert calls == [item["title"] for item in items]
    assert output.is_file() and report.is_file()
    results = {item["number"]: item for item in json.loads(output.read_text(encoding="utf-8"))}
    assert results[42]["llm"] == facts
    assert not results[42]["scoring"]["needs_review"]
    assert results[43]["scoring"]["needs_review"]
    assert results[43]["scoring"]["priority"] == "Needs-Info"
    assert results[43]["scoring"]["suggested_labels"] == []
    text = report.read_text(encoding="utf-8")
    assert "读取中断" in text and "工具调用失败" in text
    assert error_type.__name__ in text
    captured = capsys.readouterr()
    assert "#43" in captured.err
    commands = [line for line in captured.out.splitlines() if line.startswith("[dry-run]")]
    assert len(commands) == 1 and "/issues/42 " in commands[0]
    assert "secret-from-response" not in text + captured.out + captured.err


@pytest.mark.parametrize("issue_number", [None, 42])
def test_live_fetch_uses_supported_fields(scorer, monkeypatch, issue_number):
    record = {"number": 42, "url": "https://github.com/bytedance/deer-flow/issues/42"}
    calls = []

    def fake_gh(cmd, **kwargs):
        calls.append(cmd)
        fields = cmd[cmd.index("--json") + 1].split(",")
        if "authorAssociation" in fields:
            return subprocess.CompletedProcess(cmd, 1, "", "Unknown JSON field: authorAssociation")
        result = record if issue_number else [record]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(result), "")

    monkeypatch.setattr(scorer.subprocess, "run", fake_gh)
    assert scorer.fetch_issues_via_gh("bytedance/deer-flow", issue_number, 20, "bug") == [record]
    assert len(calls) == 1
    assert calls[0][:3] == ["gh", "issue", "view" if issue_number else "list"]
    assert calls[0][-2:] == (["--repo", "bytedance/deer-flow"] if issue_number else ["--label", "bug"])


@pytest.mark.parametrize(
    ("repo", "url"),
    [
        (None, "https://github.com/bytedance/deer-flow/issues/42"),
        ("bytedance/deer-flow", "https://github.com/example-fork/deer-flow/issues/42"),
        ("bytedance/deer-flow", "https://github.com/bytedance/deer-flow/issues/43"),
        ("bytedance/deer-flow", "https://example.com/bytedance/deer-flow/issues/42"),
        ("bytedance/deer-flow", ""),
    ],
)
def test_label_apply_rejects_entire_invalid_export_before_any_gh_call(scorer, monkeypatch, tmp_path, repo, url):
    input_file = tmp_path / "issues.json"
    input_file.write_text(
        json.dumps(
            [
                {"number": 41, "url": "https://github.com/bytedance/deer-flow/issues/41", "title": "[bug] Startup failure"},
                {"number": 42, "url": url, "title": "[bug] Startup failure"},
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_gh(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(scorer.subprocess, "run", fake_gh)
    args = ["--input-json", str(input_file), "--offline", "--apply-labels"]
    if repo:
        args += ["--repo", repo]
    assert scorer.main(args) == 1
    assert calls == []
