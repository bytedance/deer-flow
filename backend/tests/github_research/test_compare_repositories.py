import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from deerflow.community.github_research import tools as github_tools


def invoke_compare(first_url, second_url):
    raw = asyncio.run(
        github_tools.compare_repositories_tool.ainvoke(
            {
                "first_url": first_url,
                "second_url": second_url,
            }
        )
    )
    return json.loads(raw)


@pytest.fixture(autouse=True)
def mock_recent_commits_tool(monkeypatch):
    commits_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {
                    "sample_size": 1,
                    "scope": "default_branch",
                    "recent_commits": [
                        {
                            "sha": "1234567890ab",
                            "committed_at": "2026-09-20T12:00:00Z",
                            "source_url": ("https://github.com/example/demo/commit/1234567890abcdef"),
                        }
                    ],
                },
            }
        )
    )

    monkeypatch.setattr(
        github_tools,
        "github_recent_commits_tool",
        SimpleNamespace(ainvoke=commits_mock),
    )

    return commits_mock


@pytest.fixture(autouse=True)
def mock_latest_release_tool(monkeypatch):
    release_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {
                    "full_name": "example/demo",
                    "available": True,
                    "latest_release": {
                        "tag_name": "v2.1.0",
                        "created_at": "2026-09-01T10:00:00Z",
                        "published_at": "2026-09-02T12:00:00Z",
                        "author_login": "alice",
                        "source_url": ("https://github.com/example/demo/releases/tag/v2.1.0"),
                    },
                },
            }
        )
    )

    monkeypatch.setattr(
        github_tools,
        "github_latest_release_tool",
        SimpleNamespace(ainvoke=release_mock),
    )

    return release_mock


def test_one_repository_fails_other_succeeds(monkeypatch):
    first_url = "https://github.com/example/missing"
    second_url = "https://github.com/example/working"

    repository_data = {
        "full_name": "example/working",
        "stars": 123,
        "source_url": second_url,
    }
    readme_data = {
        "content": "这是第二个项目的说明。",
        "source_url": second_url + "/blob/main/README.md",
        "truncated": False,
    }

    # 第一个仓库失败，第二个仓库成功。
    repository_mock = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "ok": False,
                    "status_code": 404,
                    "error": "仓库不存在或无权访问。",
                }
            ),
            json.dumps(
                {
                    "ok": True,
                    "data": repository_data,
                }
            ),
        ]
    )
    readme_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": readme_data,
            }
        )
    )

    monkeypatch.setattr(
        github_tools,
        "github_repository_tool",
        SimpleNamespace(ainvoke=repository_mock),
    )
    monkeypatch.setattr(
        github_tools,
        "github_readme_tool",
        SimpleNamespace(ainvoke=readme_mock),
    )

    result = invoke_compare(first_url, second_url)

    assert result["status"] == "partial"
    assert len(result["repositories"]) == 2
    failed, succeeded = result["repositories"]

    # 失败仓库保留错误，并跳过它的 README。
    assert failed["repository_url"] == first_url
    assert failed["repository"]["ok"] is False
    assert failed["repository"]["status_code"] == 404
    assert "data" not in failed["repository"]
    assert failed["readme"]["skipped"] is True

    # 第二个仓库的成功数据完整保留。
    assert succeeded["repository_url"] == second_url
    assert succeeded["repository"]["data"] == repository_data
    assert succeeded["readme"]["data"] == readme_data
    assert succeeded["repository"]["source_type"] == "github_repository_api"
    assert succeeded["readme"]["source_type"] == "repository_readme"

    # 两个仓库各查一次，没有重试。
    assert repository_mock.await_args_list == [
        call({"repository_url": first_url}),
        call({"repository_url": second_url}),
    ]

    # 仅查询第二个仓库的 README，长度限制保持 4000。
    readme_mock.assert_awaited_once_with(
        {
            "repository_url": second_url,
            "offset": 0,
            "limit": 4000,
        }
    )


def test_duplicate_repository_does_not_query(monkeypatch):
    repository_mock = AsyncMock()
    readme_mock = AsyncMock()

    monkeypatch.setattr(
        github_tools,
        "github_repository_tool",
        SimpleNamespace(ainvoke=repository_mock),
    )
    monkeypatch.setattr(
        github_tools,
        "github_readme_tool",
        SimpleNamespace(ainvoke=readme_mock),
    )

    result = invoke_compare(
        "https://github.com/fastapi/fastapi",
        "https://github.com/FASTAPI/fastapi.git",
    )

    assert result["status"] == "failed"
    assert "两个不同的仓库" in result["error"]
    repository_mock.assert_not_called()
    readme_mock.assert_not_called()


def test_repository_queries_run_concurrently(monkeypatch):
    async def scenario():
        both_started = asyncio.Event()
        started_urls = []
        first_url = "https://github.com/example/first"
        second_url = "https://github.com/example/second"

        async def fake_repository(args):
            url = args["repository_url"]
            started_urls.append(url)

            if len(started_urls) == 2:
                both_started.set()

            # 两个查询都启动后，才允许任意一个返回。
            await both_started.wait()

            return json.dumps(
                {
                    "ok": True,
                    "data": {"source_url": url},
                }
            )

        repository_mock = AsyncMock(side_effect=fake_repository)
        readme_mock = AsyncMock(
            return_value=json.dumps(
                {
                    "ok": True,
                    "data": {"content": "模拟 README"},
                }
            )
        )

        monkeypatch.setattr(
            github_tools,
            "github_repository_tool",
            SimpleNamespace(ainvoke=repository_mock),
        )
        monkeypatch.setattr(
            github_tools,
            "github_readme_tool",
            SimpleNamespace(ainvoke=readme_mock),
        )

        raw = await asyncio.wait_for(
            github_tools.compare_repositories_tool.ainvoke(
                {
                    "first_url": first_url,
                    "second_url": second_url,
                }
            ),
            timeout=5,
        )
        result = json.loads(raw)

        assert result["status"] == "complete"
        assert [item["repository_url"] for item in result["repositories"]] == [first_url, second_url]
        assert repository_mock.await_count == 2
        assert readme_mock.await_count == 2

    asyncio.run(scenario())


def test_timeout_keeps_completed_repository(monkeypatch):
    async def fake_collect(owner, repo):
        if repo == "slow":
            # 永远等待，由整体超时负责取消。
            await asyncio.Event().wait()

        repository_url = f"https://github.com/{owner}/{repo}"

        return {
            "repository_url": repository_url,
            "repository": {
                "source_type": "github_repository_api",
                "ok": True,
                "data": {
                    "full_name": f"{owner}/{repo}",
                },
            },
            "readme": {
                "source_type": "repository_readme",
                "ok": True,
                "data": {
                    "content": "已完成的 README",
                },
            },
            "recent_commits": {
                "source_type": "default_branch_commits",
                "ok": True,
                "data": {
                    "sample_size": 1,
                    "scope": "default_branch",
                    "recent_commits": [
                        {
                            "sha": "1234567890ab",
                            "committed_at": "2026-09-20T12:00:00Z",
                        }
                    ],
                },
            },
            "latest_release": {
                "source_type": "github_latest_full_release",
                "ok": True,
                "data": {
                    "available": True,
                    "latest_release": {
                        "tag_name": "v2.1.0",
                        "published_at": "2026-09-02T12:00:00Z",
                    },
                },
            },
        }

    monkeypatch.setattr(
        github_tools,
        "_collect_repository",
        fake_collect,
    )

    # 测试中缩短整体等待时间，不需要真的等待 20 秒。
    monkeypatch.setattr(
        github_tools,
        "COMPARE_TIMEOUT_SECONDS",
        0.01,
    )

    result = invoke_compare(
        "https://github.com/example/fast",
        "https://github.com/example/slow",
    )

    assert result["status"] == "partial"

    completed, timed_out = result["repositories"]

    # 第一个仓库已经完成，因此四类数据都应保留。
    assert completed["repository_url"].endswith("/fast")
    assert completed["repository"]["ok"] is True
    assert completed["readme"]["ok"] is True
    assert completed["recent_commits"]["ok"] is True
    assert completed["latest_release"]["ok"] is True

    # 第二个仓库超时，因此后续资料均被标记为跳过。
    assert timed_out["repository_url"].endswith("/slow")
    assert timed_out["repository"]["ok"] is False
    assert "超过整体等待时间" in timed_out["repository"]["error"]
    assert timed_out["readme"]["skipped"] is True
    assert timed_out["recent_commits"]["skipped"] is True
    assert timed_out["latest_release"]["skipped"] is True


def test_commit_failure_keeps_other_sections(
    monkeypatch,
    mock_recent_commits_tool,
):
    repository_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {"full_name": "example/demo"},
            }
        )
    )
    readme_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {"content": "项目说明"},
            }
        )
    )
    mock_recent_commits_tool.return_value = json.dumps(
        {
            "ok": False,
            "status_code": 403,
            "error": "GitHub 拒绝访问提交记录。",
        }
    )

    monkeypatch.setattr(
        github_tools,
        "github_repository_tool",
        SimpleNamespace(ainvoke=repository_mock),
    )
    monkeypatch.setattr(
        github_tools,
        "github_readme_tool",
        SimpleNamespace(ainvoke=readme_mock),
    )

    result = invoke_compare(
        "https://github.com/example/first",
        "https://github.com/example/second",
    )

    assert result["status"] == "partial"
    assert len(result["repositories"]) == 2

    for item in result["repositories"]:
        assert item["repository"]["ok"] is True
        assert item["readme"]["ok"] is True
        assert item["recent_commits"]["ok"] is False
        assert item["recent_commits"]["status_code"] == 403
        assert item["recent_commits"]["source_type"] == "default_branch_commits"

    assert repository_mock.await_count == 2
    assert readme_mock.await_count == 2
    assert mock_recent_commits_tool.await_count == 2


def test_no_release_is_still_complete_query(
    monkeypatch,
    mock_latest_release_tool,
):
    repository_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {"full_name": "example/demo"},
            }
        )
    )
    readme_mock = AsyncMock(
        return_value=json.dumps(
            {
                "ok": True,
                "data": {"content": "项目说明"},
            }
        )
    )

    mock_latest_release_tool.return_value = json.dumps(
        {
            "ok": True,
            "data": {
                "full_name": "example/demo",
                "available": False,
                "latest_release": None,
                "evidence_note": "接口没有返回可用的正式 Release。",
            },
        }
    )

    monkeypatch.setattr(
        github_tools,
        "github_repository_tool",
        SimpleNamespace(ainvoke=repository_mock),
    )
    monkeypatch.setattr(
        github_tools,
        "github_readme_tool",
        SimpleNamespace(ainvoke=readme_mock),
    )

    result = invoke_compare(
        "https://github.com/example/first",
        "https://github.com/example/second",
    )

    assert result["status"] == "complete"

    for item in result["repositories"]:
        release = item["latest_release"]
        assert release["ok"] is True
        assert release["data"]["available"] is False
        assert release["data"]["latest_release"] is None
        assert release["source_type"] == "github_latest_full_release"

    assert mock_latest_release_tool.await_count == 2
