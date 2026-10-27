from deerflow.config.token_usage_config import TokenUsageConfig


def test_token_usage_enabled_by_default():
    assert TokenUsageConfig().enabled is True
