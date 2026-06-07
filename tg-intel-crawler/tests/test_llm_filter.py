import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tg_intel_crawler.filter.llm_filter import LLMFilter, AnalysisResult


@pytest.fixture
def llm_config():
    return {
        "api_key": "test-key",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "ep-test",
        "batch_size": 5,
    }


@pytest.fixture
def sample_llm_response():
    """Simulated LLM JSON response for a batch of messages."""
    return json.dumps([
        {
            "index": 0,
            "is_relevant": True,
            "risk_type": "账号交易",
            "risk_level": "high",
            "entities": {
                "accounts": ["dy_xxx"],
                "contacts": ["wx: seller123"],
                "links": [],
                "tools": [],
                "prices": ["50元/个"],
            },
            "summary": "出售抖音实名账号50元一个",
        },
        {
            "index": 1,
            "is_relevant": False,
            "risk_type": "",
            "risk_level": "",
            "entities": {},
            "summary": "",
        },
    ])


def test_parse_llm_response(sample_llm_response):
    """Should correctly parse LLM JSON response into AnalysisResult objects."""
    results = LLMFilter._parse_response(sample_llm_response)
    assert len(results) == 2
    assert results[0].is_relevant is True
    assert results[0].risk_type == "账号交易"
    assert results[0].risk_level == "high"
    assert results[0].entities["accounts"] == ["dy_xxx"]
    assert results[1].is_relevant is False


def test_parse_malformed_response():
    """Should return empty results for malformed JSON."""
    results = LLMFilter._parse_response("not valid json")
    assert results == []


def test_build_prompt():
    """Should build a proper analysis prompt with message list."""
    messages = ["抖音账号出售50一个", "今天天气真好"]
    prompt = LLMFilter._build_prompt(messages)
    assert "抖音账号出售50一个" in prompt
    assert "今天天气真好" in prompt
    assert "[0]" in prompt
    assert "[1]" in prompt


@pytest.mark.asyncio
async def test_analyze_batch_calls_llm(llm_config, sample_llm_response):
    """Should call LLM API and return parsed results."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = sample_llm_response

    with patch("tg_intel_crawler.filter.llm_filter.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        llm_filter = LLMFilter(llm_config)
        messages = ["抖音买号找我50一个", "今天天气不错"]
        results = await llm_filter.analyze_batch(messages)

        assert len(results) == 2
        assert results[0].is_relevant is True
        mock_client.chat.completions.create.assert_called_once()
