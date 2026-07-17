import json
from unittest.mock import patch, MagicMock
from governance_kb_mcp.config import KBConfig
from governance_kb_mcp.embedding import EmbeddingClient


def _make_config():
    return KBConfig(
        volcengine_api_key="test-key",
        embedding_model="doubao-embedding-text-240715",
        embedding_api_base="https://ark.cn-beijing.volces.com/api/v3",
        chroma_path="/tmp/test_chroma",
        host="0.0.0.0",
        port=8101,
        embedding_timeout=10.0,
    )


@patch("governance_kb_mcp.embedding.httpx.Client")
def test_embed_success(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}],
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_client

    config = _make_config()
    client = EmbeddingClient(config)
    result = client.embed("hello")
    assert result == [0.1, 0.2, 0.3]


@patch("governance_kb_mcp.embedding.httpx.Client")
def test_embed_timeout_returns_empty(mock_client_cls):
    import httpx
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.TimeoutException("timed out")
    mock_client_cls.return_value.__enter__.return_value = mock_client

    config = _make_config()
    client = EmbeddingClient(config)
    result = client.embed("hello")
    assert result == []


@patch("governance_kb_mcp.embedding.httpx.Client")
def test_embed_batch_success(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ],
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_client

    config = _make_config()
    client = EmbeddingClient(config)
    result = client.embed_batch(["hello", "world"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]


@patch("governance_kb_mcp.embedding.httpx.Client")
def test_embed_no_api_key_returns_empty(mock_client_cls):
    config = _make_config()
    config.volcengine_api_key = ""
    client = EmbeddingClient(config)
    result = client.embed("hello")
    assert result == []
    mock_client_cls.assert_not_called()
