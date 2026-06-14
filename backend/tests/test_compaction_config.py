"""Unit tests for CompactionConfig and its AppConfig registration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.compaction_config import CompactionConfig


class TestCompactionConfigDefaults:
    def test_disabled_by_default(self):
        cfg = CompactionConfig()
        assert cfg.enabled is False
        assert cfg.fail_open is True
        assert cfg.protect_recent == 4
        assert cfg.model is None
        assert cfg.min_total_tokens == 4_000

    def test_round_trips_through_dict(self):
        cfg = CompactionConfig(enabled=True, target_ratio=0.5, protect_recent=2, savings_profile="agent-90")
        restored = CompactionConfig(**cfg.model_dump())
        assert restored == cfg


class TestCompactionConfigValidation:
    def test_target_ratio_bounds(self):
        with pytest.raises(ValidationError):
            CompactionConfig(target_ratio=1.5)
        with pytest.raises(ValidationError):
            CompactionConfig(target_ratio=-0.1)
        # In-range values are accepted.
        assert CompactionConfig(target_ratio=0.0).target_ratio == 0.0
        assert CompactionConfig(target_ratio=1.0).target_ratio == 1.0

    def test_model_limit_must_be_positive(self):
        with pytest.raises(ValidationError):
            CompactionConfig(model_limit=0)

    def test_negative_floors_rejected(self):
        with pytest.raises(ValidationError):
            CompactionConfig(protect_recent=-1)
        with pytest.raises(ValidationError):
            CompactionConfig(min_total_tokens=-1)


class TestAppConfigRegistration:
    def test_app_config_has_compaction_default(self):
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        cfg = AppConfig(sandbox=SandboxConfig(use="test"))
        assert isinstance(cfg.compaction, CompactionConfig)
        assert cfg.compaction.enabled is False

    def test_app_config_parses_compaction_section(self):
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        cfg = AppConfig.model_validate(
            {
                "sandbox": SandboxConfig(use="test").model_dump(),
                "compaction": {"enabled": True, "target_ratio": 0.6, "min_total_tokens": 1000},
            }
        )
        assert cfg.compaction.enabled is True
        assert cfg.compaction.target_ratio == 0.6
        assert cfg.compaction.min_total_tokens == 1000
