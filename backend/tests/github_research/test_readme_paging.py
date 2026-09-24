import asyncio
import base64
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.github_research import client as github_client
from deerflow.community.github_research.cache import ReadmeCache


@pytest.mark.parametrize(
    "offset,limit,expected,next_offset,has_more,truncated",
    [
        (0, 3, "甲乙丙", 3, True, True),
        (3, 3, "丁戊", None, False, True),
        (0, 8, "甲乙丙丁戊", None, False, False),
        (5, 3, "", None, False, True),
    ],
)
def test_readme_pages(
    monkeypatch,
    offset,
    limit,
    expected,
    next_offset,
    has_more,
    truncated,
):

    # 每个测试用独立缓存，防止不同测试相互影响。
    monkeypatch.setattr(
        github_client,
        "_readme_cache",
        ReadmeCache(),
    )

    text = "甲乙丙丁戊"
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET", "https://api.github.com/repos/example/demo/readme"
        ),
        json={
            "encoding": "base64",
            "content": base64.b64encode(
                text.encode("utf-8")
            ).decode("ascii"),
            "path": "README.md",
            "html_url": "https://github.com/example/demo/blob/main/README.md",
        },
    )

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.get.return_value = response

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    monkeypatch.setattr(
        github_client.httpx,
        "AsyncClient",
        lambda **kwargs: fake_client,
    )

    result = asyncio.run(
        github_client.fetch_readme(
            "https://github.com/example/demo",
            offset=offset,
            limit=limit,
        )
    )

    assert result["content"] == expected
    assert result["total_chars"] == 5
    assert result["returned_chars"] == len(expected)
    assert result["next_offset"] == next_offset
    assert result["has_more"] is has_more
    assert result["truncated"] is truncated
    fake_client.get.assert_awaited_once()

    assert result["cache_hit"] is False

    # 继续读取下一段，应该使用同一份缓存。
    second_offset = offset + len(expected)
    second = asyncio.run(
        github_client.fetch_readme(
            "https://github.com/example/demo",
            offset=second_offset,
            limit=limit,
        )
    )

    assert second["cache_hit"] is True
    assert second["content"] == text[second_offset:second_offset + limit]

    # 两次读取，总共只请求一次 GitHub。
    fake_client.get.assert_awaited_once()

    # 换一个 Token 后，不应该复用之前的缓存。
    monkeypatch.setenv("GITHUB_TOKEN", "another-fake-token")
    third = asyncio.run(
        github_client.fetch_readme(
            "https://github.com/example/demo",
            offset=0,
            limit=limit,
        )
    )

    assert third["cache_hit"] is False
    assert fake_client.get.await_count == 2


def make_readme_response(text: str) -> httpx.Response:
    """构造 GitHub 的模拟成功响应。"""
    return httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/readme",
        ),
        json={
            "encoding": "base64",
            "content": base64.b64encode(
                text.encode("utf-8")
            ).decode("ascii"),
            "path": "README.md",
            "html_url": (
                "https://github.com/example/demo/blob/main/README.md"
            ),
        },
    )


@pytest.fixture
def readme_environment(monkeypatch):
    """为每个测试提供独立缓存、模拟时钟和模拟客户端。"""
    now = [0.0]
    cache = ReadmeCache(
        ttl_seconds=300,
        clock=lambda: now[0],
    )
    monkeypatch.setattr(github_client, "_readme_cache", cache)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    monkeypatch.setattr(
        github_client.httpx,
        "AsyncClient",
        lambda **kwargs: fake_client,
    )

    return now, fake_client


def test_expired_cache_fetches_new_content(readme_environment):
    now, fake_client = readme_environment
    fake_client.get.side_effect = [
        make_readme_response("旧版安装说明"),
        make_readme_response("新版安装说明"),
    ]

    async def scenario():
        first = await github_client.fetch_readme(
            "https://github.com/example/demo"
        )

        now[0] = 299.0
        second = await github_client.fetch_readme(
            "https://github.com/example/demo"
        )
        assert fake_client.get.await_count == 1

        now[0] = 300.0
        third = await github_client.fetch_readme(
            "https://github.com/example/demo"
        )
        return first, second, third

    first, second, third = asyncio.run(scenario())

    assert first["content"] == "旧版安装说明"
    assert first["cache_hit"] is False
    assert second["content"] == "旧版安装说明"
    assert second["cache_hit"] is True
    assert third["content"] == "新版安装说明"
    assert third["cache_hit"] is False
    assert fake_client.get.await_count == 2


def test_failed_request_is_not_cached(readme_environment):
    _, fake_client = readme_environment
    failed_response = httpx.Response(
        503,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/readme",
        ),
    )
    fake_client.get.side_effect = [
        failed_response,
        make_readme_response("恢复后的正文"),
    ]

    async def scenario():
        # 第一次调用失败，应正常抛出异常。
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await github_client.fetch_readme(
                "https://github.com/example/demo"
            )
        assert exc.value.response.status_code == 503
        assert fake_client.get.await_count == 1

        # 模拟稍后重新发起调用，不是函数内部自动重试。
        recovered = await github_client.fetch_readme(
            "https://github.com/example/demo"
        )
        cached = await github_client.fetch_readme(
            "https://github.com/example/demo"
        )
        return recovered, cached

    recovered, cached = asyncio.run(scenario())

    assert recovered["content"] == "恢复后的正文"
    assert recovered["cache_hit"] is False
    assert cached["content"] == "恢复后的正文"
    assert cached["cache_hit"] is True
    assert fake_client.get.await_count == 2