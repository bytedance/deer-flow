from governance_lingxing_mcp.config import LXConfig


def test_config_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGXING_APP_ID", "ak_test")
    monkeypatch.setenv("LINGXING_APP_SECRET", "secret_test")
    monkeypatch.setenv("LINGXING_PORT", "8200")
    config = LXConfig.from_env()
    assert config.app_id == "ak_test"
    assert config.app_secret == "secret_test"
    assert config.port == 8200
    assert config.api_base == "https://openapi.lingxing.com"
    assert config.ttl_business_seconds == 21600
    assert config.ttl_ad_seconds == 1800
