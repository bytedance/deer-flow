import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import HumanMessage

from app.gateway.routers import auth
from deerflow.agents.middlewares import dynamic_context_middleware as module
from deerflow.security.store import UserSecurityStore


@pytest.mark.asyncio
async def test_profile_reads_writes_and_model_projection_are_off_loop(tmp_path, monkeypatch):
    store = UserSecurityStore(tmp_path)
    monkeypatch.setattr(auth, "get_user_security_store", lambda: store)
    monkeypatch.setattr(module, "get_user_security_store", lambda: store)

    async def current_user(_):
        return SimpleNamespace(id="alice")

    monkeypatch.setattr(auth, "get_current_user_from_request", current_user)
    request = SimpleNamespace()
    assert (await auth.update_account_profile(request, auth.UserProfileUpdate(nickname="小林"))).nickname == "小林"
    assert (await auth.get_account_profile(request)).nickname == "小林"
    model_request = ModelRequest(model=SimpleNamespace(), messages=[HumanMessage(content="你好")], state={}, runtime=SimpleNamespace(context={"user_id": "alice"}))

    async def capture(projected):
        return projected

    result = await module.DynamicContextMiddleware().awrap_model_call(model_request, capture)
    assert "小林" in str(result.messages)
    assert await asyncio.to_thread(store.get_nickname, "bob") is None
