import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.github_research import client as github_client


def test_fetch_recent_commits(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://api.github.com/repos/example/demo/commits",
        ),
        json=[
            {
                "sha": "1234567890abcdef",
                "html_url": (
                    "https://github.com/example/demo/commit/1234567890abcdef"
                ),
                "author": {"login": "alice"},
                "commit": {
                    "committer": {
                        "date": "2026-09-20T12:00:00Z"
                    }
                },
            },
            {
                "sha": "abcdef1234567890",
                "html_url": (
                    "https://github.com/example/demo/commit/abcdef1234567890"
                ),
                # GitHub 用户可能已删除，因此 author 允许为空。
                "author": None,
                "commit": {
                    "committer": {
                        "date": "2026-09-19T10:00:00Z"
                    }
                },
            },
        ],
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
        github_client.fetch_recent_commits(
            "https://github.com/example/demo",
            limit=2,
        )
    )

    assert result["full_name"] == "example/demo"
    assert result["sample_size"] == 2
    assert result["scope"] == "default_branch"

    first, second = result["recent_commits"]

    assert first["sha"] == "1234567890ab"
    assert first["author_login"] == "alice"
    assert first["committed_at"] == "2026-09-20T12:00:00Z"

    assert second["sha"] == "abcdef123456"
    assert second["author_login"] is None
    assert second["committed_at"] == "2026-09-19T10:00:00Z"

    fake_client.get.assert_awaited_once()

    request_kwargs = fake_client.get.await_args.kwargs
    assert request_kwargs["params"] == {"per_page": 2}
    assert "Authorization" in request_kwargs["headers"]


@pytest.mark.parametrize("limit", [0, 11, -1, True, 2.5])
def test_invalid_limit_is_rejected_before_request(
    monkeypatch,
    limit,
):
    def fail_if_client_created(**kwargs):
        raise AssertionError("非法 limit 不应该创建网络客户端")

    monkeypatch.setattr(
        github_client.httpx,
        "AsyncClient",
        fail_if_client_created,
    )

    with pytest.raises(ValueError, match="1 到 10"):
        asyncio.run(
            github_client.fetch_recent_commits(
                "https://github.com/example/demo",
                limit=limit,
            )
        )