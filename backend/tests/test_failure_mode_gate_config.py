"""Tests for failure-mode gate configuration loading."""

from __future__ import annotations

from unittest.mock import patch

from src.config.app_config import AppConfig
from src.config.failure_mode_gate_config import (
    FailureModeGateConfig,
    get_failure_mode_gate_config,
    load_failure_mode_gate_config_from_dict,
    set_failure_mode_gate_config,
)


def test_load_failure_mode_gate_config_from_dict():
    previous = get_failure_mode_gate_config().model_copy(deep=True)
    try:
        load_failure_mode_gate_config_from_dict(
            {
                "citation_fidelity_max": 0.7,
                "overclaim_claim_grounding_max": 0.6,
                "numeric_drift_abstract_body_max": 0.75,
                "evidence_chain_claim_grounding_max": 0.5,
                "style_mismatch_venue_fit_max": 0.65,
                "superficial_rebuttal_completeness_max": 0.66,
                "min_target_recall": 0.97,
                "max_control_false_positive_rate": 0.1,
            }
        )
        cfg = get_failure_mode_gate_config()
        assert cfg.citation_fidelity_max == 0.7
        assert cfg.overclaim_claim_grounding_max == 0.6
        assert cfg.numeric_drift_abstract_body_max == 0.75
        assert cfg.evidence_chain_claim_grounding_max == 0.5
        assert cfg.style_mismatch_venue_fit_max == 0.65
        assert cfg.superficial_rebuttal_completeness_max == 0.66
        assert cfg.min_target_recall == 0.97
        assert cfg.max_control_false_positive_rate == 0.1
    finally:
        set_failure_mode_gate_config(previous)


def test_set_failure_mode_gate_config_roundtrip():
    previous = get_failure_mode_gate_config().model_copy(deep=True)
    try:
        target = FailureModeGateConfig(min_target_recall=0.99, max_control_false_positive_rate=0.05)
        set_failure_mode_gate_config(target)
        loaded = get_failure_mode_gate_config()
        assert loaded.min_target_recall == 0.99
        assert loaded.max_control_false_positive_rate == 0.05
    finally:
        set_failure_mode_gate_config(previous)


def test_app_config_from_file_loads_failure_mode_gate_section(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
models: []
sandbox:
  use: src.sandbox.local:LocalSandboxProvider
failure_mode_gate:
  citation_fidelity_max: 0.7
  min_target_recall: 0.98
""".strip(),
        encoding="utf-8",
    )
    with patch.object(AppConfig, "resolve_config_path", return_value=config_file), patch(
        "src.config.app_config.load_failure_mode_gate_config_from_dict"
    ) as gate_loader:
        try:
            AppConfig.from_file()
        except Exception:
            # Minimal config may fail full model validation in some environments;
            # this assertion only checks loader dispatch.
            pass
    gate_loader.assert_called_once()
    loaded = gate_loader.call_args.args[0]
    assert loaded["citation_fidelity_max"] == 0.7
    assert loaded["min_target_recall"] == 0.98

