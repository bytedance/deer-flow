import asyncio
import json
from unittest.mock import AsyncMock

from deerflow.community.github_research import tools as github_tools


def test_no_release_is_successful_query(monkeypatch):
    fake_fetch = AsyncMock(
        return_value={
            "full_name": "example/demo",
            "available": False,
            "latest_release": None,
            "evidence_note": "接口没有返回可用的正式 Release。",
        }
    )
    monkeypatch.setattr(
        github_tools,
        "fetch_latest_release",
        fake_fetch,
    )

    raw = asyncio.run(
        github_tools.github_latest_release_tool.ainvoke({
            "repository_url": "https://github.com/example/demo"
        })
    )
    result = json.loads(raw)

    assert result["ok"] is True
    assert result["data"]["available"] is False
    assert result["data"]["latest_release"] is None

    fake_fetch.assert_awaited_once_with(
        "https://github.com/example/demo"
    )