"""Image search must keep config file reads off the agent event loop."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.community.image_search import tools

pytestmark = pytest.mark.asyncio


async def test_image_search_config_lookup_does_not_block_loop(monkeypatch) -> None:
    def load_config():
        # Keep a real file read in the lookup so the strict blocking-I/O gate
        # fails if the tool resolves config on the event loop.
        Path(__file__).read_text(encoding="utf-8")
        return SimpleNamespace(get_tool_config=lambda _name: None)

    monkeypatch.setattr(tools, "get_app_config", load_config)
    monkeypatch.setattr(tools, "_search_images", lambda **_kwargs: [])

    result = await tools.image_search_tool.ainvoke({"query": "a cat"})

    assert '"error": "No images found"' in result
