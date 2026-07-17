import os
from governance_kb_mcp.config import KBConfig


def test_config_from_env():
    os.environ["VOLCENGINE_API_KEY"] = "test-key-123"
    config = KBConfig.from_env()
    assert config.volcengine_api_key == "test-key-123"
    assert config.embedding_model == "doubao-embedding-text-240715"
    assert config.embedding_api_base == "https://ark.cn-beijing.volces.com/api/v3"
    assert config.port == 8101
    assert config.host == "0.0.0.0"
    assert config.embedding_timeout == 10.0
    assert "chroma_db" in str(config.chroma_path)


def test_config_defaults_without_key():
    os.environ.pop("VOLCENGINE_API_KEY", None)
    config = KBConfig.from_env()
    assert config.volcengine_api_key == ""
