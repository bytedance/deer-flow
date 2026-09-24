import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.github_research import tools as github_tools


def invoke_tool(url: str) -> dict:
    """调用工具，并把 JSON 字符串转换成字典。"""
    raw = asyncio.run(
        github_tools.github_repository_tool.ainvoke(
            {"repository_url": url}
        )
    )
    return json.loads(raw)


def test_success_keeps_evidence_boundary(monkeypatch):
    """未归档、Star 多，也不能自动认定维护活跃。"""
    repository = {
        "full_name": "example/demo",
        "description": "A demo project",
        "stars": 100000,
        "language": "Python",
        "license": "MIT",
        "archived": False,
        "pushed_at": "2026-09-01T00:00:00Z",
        "source_url": "https://github.com/example/demo",
    }
    fake_fetch = AsyncMock(return_value=repository)
    monkeypatch.setattr(
        github_tools, "fetch_repository", fake_fetch
    )

    result = invoke_tool("https://github.com/example/demo")

    assert result["ok"] is True
    assert result["data"] == repository
    assert result["assessment"]["maintenance_status"] == "unknown"
    assert result["assessment"]["reason"]
    assert "未归档不等于" in result["field_notes"]["archived"]
    fake_fetch.assert_awaited_once_with("example", "demo")


def test_invalid_url_does_not_fetch(monkeypatch):
    """非法域名应在发起请求前被拒绝。"""
    fake_fetch = AsyncMock()
    monkeypatch.setattr(
        github_tools, "fetch_repository", fake_fetch
    )

    result = invoke_tool("https://github.com.example.com/a/b")

    assert result["ok"] is False
    assert "error" in result
    assert "data" not in result
    fake_fetch.assert_not_called()


def test_timeout_returns_error(monkeypatch):
    """超时应返回错误信息，不应伪造数据或自动重试。"""
    fake_fetch = AsyncMock(
        side_effect=httpx.ReadTimeout("模拟超时")
    )
    monkeypatch.setattr(
        github_tools, "fetch_repository", fake_fetch
    )

    result = invoke_tool("https://github.com/example/demo")

    assert result["ok"] is False
    assert "超时" in result["error"]
    assert "data" not in result
    fake_fetch.assert_awaited_once_with("example", "demo")


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "Token"),
        (403, "暂停请求"),
        (404, "仓库不存在"),
        (429, "暂停请求"),
        (500, "500"),
    ],
)
def test_http_errors(monkeypatch, status, expected):
    """不同 HTTP 错误应转换成工具能返回的失败结果。"""
    request = httpx.Request(
        "GET", "https://api.github.com/repos/example/demo"
    )
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError(
        "模拟 GitHub 错误",
        request=request,
        response=response,
    )
    fake_fetch = AsyncMock(side_effect=error)
    monkeypatch.setattr(
        github_tools, "fetch_repository", fake_fetch
    )

    result = invoke_tool("https://github.com/example/demo")

    assert result["ok"] is False
    assert result["status_code"] == status
    assert expected in result["error"]
    assert "data" not in result
    fake_fetch.assert_awaited_once_with("example", "demo")