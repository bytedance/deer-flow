import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_gateway_catalog_never_takes_managed_guard_on_event_loop(monkeypatch):
    from app.gateway.routers import skills

    loop_thread = threading.get_ident()

    def load_skills(**kwargs):
        assert threading.get_ident() != loop_thread
        return []

    monkeypatch.setattr(skills, "_get_user_skill_storage", lambda _: SimpleNamespace(load_skills=load_skills))
    monkeypatch.setattr(skills, "_filter_visible_skills", AsyncMock(return_value=[]))
    assert (await skills.list_skills(SimpleNamespace(), SimpleNamespace())).skills == []
