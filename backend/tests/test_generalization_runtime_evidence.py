"""Runtime decisions require structured evidence, not prose matches."""

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware, _extract_in_band_status
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


class ProviderError(Exception):
    def __init__(self, text, status=None, code=None, body=None):
        super().__init__(text)
        self.status_code = status
        self.code = code
        self.body = body


@pytest.mark.parametrize("text", ["No billing or permission issue; unknown failure", "server busy is only a quoted example", "HTTP 503 is not the actual response", "余额不足只是示例"])
def test_provider_prose_does_not_establish_error_category(text):
    middleware = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    assert middleware._classify_error(ProviderError(text)) == (False, "generic")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderError("quota billing permission", status=503), (True, "transient")),
        (ProviderError("server busy", status=401), (False, "auth")),
        (ProviderError("server busy", status=400), (False, "generic")),
        (ProviderError("anything", status=429, code="insufficient_quota"), (False, "quota")),
        (ProviderError("anything", status=429, code="limit_burst_rate"), (True, "burst_rate")),
        (IndexError("list index out of range"), (False, "generic")),
        (httpx.ReadError("peer closed"), (True, "transient")),
        (ProviderError("not an HTTP status", status=True), (False, "generic")),
    ],
)
def test_provider_classification_uses_status_codes_and_real_types(error, expected):
    middleware = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    assert middleware._classify_error(error) == expected


def test_in_band_status_does_not_parse_numbers_from_prose():
    assert _extract_in_band_status(ProviderError("Example [504], not an actual status")) is None
    assert _extract_in_band_status(ProviderError("anything", body={"error": {"status": 504}})) == 504


@pytest.mark.parametrize("text", ["orders", "do not query orders", "订单只是引用", "What does orders mean?", "unrelated preorders text"])
def test_mcp_routing_keywords_never_promote_schemas(text):
    middleware = McpRoutingMiddleware({"postgres_query": {"priority": 100, "keywords": ["orders", "订单"]}}, "hash", 3)
    state = {"messages": [HumanMessage(content=text)]}
    assert middleware.before_model(state, None) is None
