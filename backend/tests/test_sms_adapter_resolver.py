"""Tests for loading the shared SMS adapter configuration."""

from __future__ import annotations

from textwrap import dedent


def test_load_sms_config_expands_base_url_env(monkeypatch, tmp_path):
    from deerflow.integrations import sms_adapter_resolver

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        dedent(
            """
            integrations:
              systems:
                sms:
                  system_type: sms
                  display_name: SMS
                  transport_type: http
                  base_url: "$SMS_BASE_URL"
                  auth_type: bearer
                  auth_mode: user_token
                  enabled: true
                  capabilities:
                    - abnormal.list
            """
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SMS_BASE_URL", "https://sms.example.test")

    cfg = sms_adapter_resolver._load_sms_config()

    assert cfg is not None
    assert cfg.base_url == "https://sms.example.test"
