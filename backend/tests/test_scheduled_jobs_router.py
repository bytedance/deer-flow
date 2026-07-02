from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.gateway.routers import scheduled_jobs as router_mod


class _RepoWithJob:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.job


def _request(user_id: str = "u1") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=user_id)))


@pytest.mark.anyio
async def test_run_job_now_due_parses_offset_datetimes(monkeypatch: pytest.MonkeyPatch) -> None:
    offset_tz = timezone(timedelta(hours=14))
    due_instant = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(offset_tz)
    repo = _RepoWithJob({"id": "job-1", "next_run_at": due_instant.isoformat()})

    monkeypatch.setattr(router_mod, "_get_repos", lambda: (repo, None))

    response = await router_mod.run_job_now(
        _request(),
        "job-1",
        router_mod.RunNowRequest(mode="due"),
    )

    assert response.status == "queued"
    assert response.message == "job already due"
