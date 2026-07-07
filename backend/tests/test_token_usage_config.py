from deerflow.config.token_usage_config import TokenUsageConfig


def test_token_usage_enabled_by_default():
    assert TokenUsageConfig().enabled is True


def test_counting_defaults_to_approximate():
    cfg = TokenUsageConfig()
    assert cfg.counting == "approximate"
    assert cfg.is_exact_counting() is False


def test_is_exact_counting_is_case_insensitive_and_trims():
    assert TokenUsageConfig(counting=" exact ").is_exact_counting() is True
    assert TokenUsageConfig(counting="EXACT").is_exact_counting() is True
    assert TokenUsageConfig(counting="approximate").is_exact_counting() is False
    assert TokenUsageConfig(counting="").is_exact_counting() is False
