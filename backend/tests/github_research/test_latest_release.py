import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.github_research import client as github_client


def install_fake_client(monkeypatch, response):
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.get.return_value = response

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    monkeypatch.setattr(
        github_client.httpx,
        "AsyncClient",
        lambda **kwargs: fake_client,
    )

    return fake_client


def test_fetch_latest_release(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/releases/latest",
        ),
        json={
            "tag_name": "v2.1.0",
            "name": "Version 2.1.0",
            "created_at": "2026-09-01T10:00:00Z",
            "published_at": "2026-09-02T12:00:00Z",
            "html_url": (
                "https://github.com/example/demo/releases/tag/v2.1.0"
            ),
            "author": {"login": "alice"},
            "body": "这段很长的发布说明不应该进入返回结果。",
        },
    )
    fake_client = install_fake_client(monkeypatch, response)

    result = asyncio.run(
        github_client.fetch_latest_release(
            "https://github.com/example/demo"
        )
    )

    assert result["available"] is True

    release = result["latest_release"]
    assert release["tag_name"] == "v2.1.0"
    assert release["published_at"] == "2026-09-02T12:00:00Z"
    assert release["author_login"] == "alice"
    assert release["source_url"].endswith("/releases/tag/v2.1.0")

    # 发布正文没有进入结果，控制上下文长度。
    assert "body" not in release
    fake_client.get.assert_awaited_once()


def test_release_not_found_is_structured_result(monkeypatch):
    response = httpx.Response(
        404,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/releases/latest",
        ),
    )
    install_fake_client(monkeypatch, response)

    result = asyncio.run(
        github_client.fetch_latest_release(
            "https://github.com/example/demo"
        )
    )

    assert result["available"] is False
    assert result["latest_release"] is None
    assert "不能据此断言" in result["evidence_note"]


def test_non_404_error_is_raised(monkeypatch):
    response = httpx.Response(
        403,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/releases/latest",
        ),
    )
    install_fake_client(monkeypatch, response)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(
            github_client.fetch_latest_release(
                "https://github.com/example/demo"
            )
        )

    assert exc.value.response.status_code == 403