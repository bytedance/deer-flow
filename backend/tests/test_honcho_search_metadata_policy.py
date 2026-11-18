"""Malformed remote search metadata must honor the configured read policy."""

import json
import logging

import httpx
import pytest

from deerflow.agents.memory.backends.honcho.client import HonchoClient
from deerflow.agents.memory.backends.honcho.honcho_manager import HonchoMemoryManager
from deerflow.agents.memory.manager import MemoryReadError


@pytest.mark.asyncio
@pytest.mark.parametrize("async_read", [False, True])
@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("metadata", ["private-invalid-metadata", ["private-invalid-metadata"], 7, True])
async def test_search_metadata_failure_honors_read_policy(metadata, policy, async_read, caplog):
    manager = HonchoMemoryManager.from_config({"base_url": "http://honcho.test", "failure_policy": {"read": policy}})
    manager._client.close()
    requests = []

    def respond(request):
        requests.append(request)
        assert json.loads(request.content) == {"query": "synthetic query", "limit": 5}
        return httpx.Response(200, json=[{"content": "private-valid-content", "metadata": {"category": "preference"}}, {"content": "private-invalid-content", "metadata": metadata}])

    manager._client = HonchoClient(manager._config, transport=httpx.MockTransport(respond))

    async def search():
        if async_read:
            return await manager.asearch("synthetic query", user_id="synthetic-user")
        return manager.search("synthetic query", user_id="synthetic-user")

    try:
        with caplog.at_level(logging.WARNING):
            if policy == "fail_closed":
                with pytest.raises(MemoryReadError) as error:
                    await search()
                diagnostics = str(error.value)
            else:
                assert await search() == []
                diagnostics = caplog.text
        assert "metadata" in diagnostics
        for secret in ("private-invalid-metadata", "private-valid-content", "private-invalid-content"):
            assert secret not in diagnostics
        assert len(requests) == 1
    finally:
        manager.close()


@pytest.mark.parametrize("metadata", [None, {}, {"category": "preference"}])
def test_search_preserves_valid_metadata(metadata):
    manager = HonchoMemoryManager.from_config({"base_url": "http://honcho.test"})
    manager._client.close()
    manager._client = HonchoClient(manager._config, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"content": "Synthetic content", "metadata": metadata}])))
    try:
        result = manager.search("synthetic query", user_id="synthetic-user")
        assert result[0]["content"] == "Synthetic content"
        assert result[0]["category"] == ("preference" if metadata else "memory")
    finally:
        manager.close()
