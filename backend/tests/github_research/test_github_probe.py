import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from examples.github_research import github_probe


@pytest.mark.parametrize(
    "status,headers,expected",
    [
        (404, {}, "仓库不存在"),
        (401, {}, "GitHub Token 无效或已过期"),
        (
            403,
            {"x-ratelimit-remaining": "0"},
            "GitHub API 请求额度已用完",
        ),
        (
            429,
            {"retry-after": "30"},
            "请至少等待 30 秒",
        ),
        (
            403,
            {},
            "可能是权限限制或触发了额外限流",
        ),
        (500, {}, "GitHub 服务暂时异常"),
    ],
)
def test_http_error_messages(
    monkeypatch,
    capsys,
    status,
    headers,
    expected,
):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://github.com/fastapi/fastapi",
    )

    request = httpx.Request(
        "GET",
        "https://api.github.com/repos/fastapi/fastapi",
    )
    response = httpx.Response(
        status,
        headers=headers,
        request=request,
    )
    error = httpx.HTTPStatusError(
        "模拟 GitHub 错误",
        request=request,
        response=response,
    )

    fake_fetch = AsyncMock(side_effect=error)
    monkeypatch.setattr(
        github_probe,
        "fetch_repository",
        fake_fetch,
    )

    asyncio.run(github_probe.main())

    output = capsys.readouterr().out
    assert expected in output
    fake_fetch.assert_awaited_once_with("fastapi", "fastapi")


def test_timeout_message(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://github.com/fastapi/fastapi",
    )

    fake_fetch = AsyncMock(
        side_effect=httpx.ReadTimeout("模拟请求超时")
    )
    monkeypatch.setattr(
        github_probe,
        "fetch_repository",
        fake_fetch,
    )

    asyncio.run(github_probe.main())

    output = capsys.readouterr().out
    assert "请求 GitHub 超时，请稍后再试" in output
    fake_fetch.assert_awaited_once_with("fastapi", "fastapi")


def test_invalid_url_does_not_fetch(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://github.com.example.com/a/b",
    )

    fake_fetch = AsyncMock()
    monkeypatch.setattr(
        github_probe,
        "fetch_repository",
        fake_fetch,
    )

    asyncio.run(github_probe.main())

    output = capsys.readouterr().out
    assert "请输入 https://github.com/ 开头的仓库地址" in output
    fake_fetch.assert_not_called()