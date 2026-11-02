import asyncio
from types import SimpleNamespace

import pytest
from deerflow_extension_api import HostCapabilityError

from deerflow_extension_skill_evolution import recent_runs
from deerflow_extension_skill_evolution.recent_runs import recent_changed_runs


def test_recent_tail_reaches_end_including_empty_metadata_pages():
    pages = [
        SimpleNamespace(items=(1, 2), next_cursor="first", has_more=True),
        SimpleNamespace(items=(), next_cursor="second", has_more=True),
        SimpleNamespace(items=(3, 4, 5), next_cursor=None, has_more=False),
    ]
    calls = []

    class Reader:
        async def list_changed_runs(self, *, cursor, limit):
            calls.append(cursor)
            return pages[len(calls) - 1]

    assert asyncio.run(recent_changed_runs(Reader(), limit=2)) == [4, 5]
    assert calls == [None, "first", "second"]


@pytest.mark.parametrize("cursor", [None, "", "repeated"])
def test_incomplete_or_repeating_cursor_never_returns_old_metadata_as_recent(cursor):
    class Reader:
        async def list_changed_runs(self, **kwargs):
            return SimpleNamespace(items=("old",), next_cursor=cursor, has_more=True)

    with pytest.raises(HostCapabilityError) as error:
        asyncio.run(recent_changed_runs(Reader(), limit=2))
    assert error.value.code == "UNAVAILABLE"


def test_metadata_budget_fails_closed_on_an_unending_feed(monkeypatch):
    monkeypatch.setattr(recent_runs, "_MAX_METADATA_PAGES", 2)
    calls = []

    class Reader:
        async def list_changed_runs(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(items=(len(calls),), next_cursor=str(len(calls)), has_more=True)

    with pytest.raises(HostCapabilityError) as error:
        asyncio.run(recent_changed_runs(Reader(), limit=1))
    assert error.value.code == "QUOTA_EXCEEDED"
    assert len(calls) == 2
