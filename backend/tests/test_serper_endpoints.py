"""Offline endpoint configuration contracts for both Serper tools."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deerflow.community.serper import tools


@pytest.fixture
def serper(monkeypatch):
    configs = {"web_search": {"api_key": "web-key"}, "image_search": {"api_key": "image-key"}}
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra=configs[name])))
    monkeypatch.delenv("SERPER_BASE_URL", raising=False)
    response = MagicMock()
    response.json.return_value = {
        "organic": [{"title": "Web result", "link": "https://example.com/page", "snippet": "Snippet"}],
        "images": [{"title": "Image result", "imageUrl": "https://example.com/image.jpg", "thumbnailUrl": "https://example.com/thumb.jpg"}],
    }
    client = MagicMock()
    post = client.return_value.__enter__.return_value.post
    post.return_value = response
    monkeypatch.setattr(tools.httpx, "Client", client)
    return SimpleNamespace(configs=configs, post=post)


def assert_search(serper, tool_name, endpoint):
    search_tool = tools.web_search_tool if tool_name == "web_search" else tools.image_search_tool
    arguments = {"query": " test ", "max_results": 3}
    payload = {"q": "test", "num": 3}
    if tool_name == "web_search":
        arguments["time_range"] = "week"
        payload["tbs"] = "qdr:w"
    result = json.loads(search_tool.invoke(arguments))
    assert result["query"] == "test"
    assert result["total_results"] == 1
    serper.post.assert_called_once_with(endpoint, headers={"X-API-KEY": serper.configs[tool_name]["api_key"], "Content-Type": "application/json"}, json=payload)


def test_tool_config_precedes_environment_and_keeps_tool_credentials_paired(serper, monkeypatch):
    monkeypatch.setenv("SERPER_BASE_URL", "https://env.example")
    serper.configs["web_search"]["base_url"] = " https://web.example/api/ "
    serper.configs["image_search"]["base_url"] = "\thttps://images.example/v1///\n"
    assert_search(serper, "web_search", "https://web.example/api/search")
    serper.post.reset_mock()
    assert_search(serper, "image_search", "https://images.example/v1/images")


@pytest.mark.parametrize("tool_name,route", [("web_search", "search"), ("image_search", "images")])
@pytest.mark.parametrize("base_url", [None, "", " \t", 42, False, {}])
def test_unusable_tool_config_falls_back_to_environment(serper, monkeypatch, tool_name, route, base_url):
    monkeypatch.setenv("SERPER_BASE_URL", " https://env.example/ ")
    serper.configs[tool_name]["base_url"] = base_url
    assert_search(serper, tool_name, f"https://env.example/{route}")


def test_web_endpoint_does_not_leak_to_image_tool(serper):
    serper.configs["web_search"]["base_url"] = "https://web.example"
    assert_search(serper, "image_search", "https://google.serper.dev/images")


@pytest.mark.parametrize("tool_name,route", [("web_search", "search"), ("image_search", "images")])
def test_environment_endpoint_without_tool_config(serper, monkeypatch, tool_name, route):
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    monkeypatch.setenv("SERPER_API_KEY", serper.configs[tool_name]["api_key"])
    monkeypatch.setenv("SERPER_BASE_URL", " https://env.example/ ")
    assert_search(serper, tool_name, f"https://env.example/{route}")


def test_endpoint_is_operator_configuration_only():
    assert set(tools.web_search_tool.args_schema.model_json_schema()["properties"]) == {"query", "max_results", "time_range"}
    assert set(tools.image_search_tool.args_schema.model_json_schema()["properties"]) == {"query", "max_results"}
