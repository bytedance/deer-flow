"""Configuration for failure-mode red-team gating thresholds."""

from pydantic import BaseModel, Field


class FailureModeGateConfig(BaseModel):
    """Runtime configuration for academic failure-mode gates."""

    citation_fidelity_max: float = Field(default=0.75, ge=0.0, le=1.0)
    overclaim_claim_grounding_max: float = Field(default=0.65, ge=0.0, le=1.0)
    numeric_drift_abstract_body_max: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence_chain_claim_grounding_max: float = Field(default=0.55, ge=0.0, le=1.0)
    style_mismatch_venue_fit_max: float = Field(default=0.7, ge=0.0, le=1.0)
    superficial_rebuttal_completeness_max: float = Field(default=0.7, ge=0.0, le=1.0)
    min_target_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    max_control_false_positive_rate: float = Field(default=0.2, ge=0.0, le=1.0)


_failure_mode_gate_config: FailureModeGateConfig = FailureModeGateConfig()


def get_failure_mode_gate_config() -> FailureModeGateConfig:
    """Get the current failure-mode gate configuration."""
    return _failure_mode_gate_config


def set_failure_mode_gate_config(config: FailureModeGateConfig) -> None:
    """Set the failure-mode gate configuration."""
    global _failure_mode_gate_config
    _failure_mode_gate_config = config


def load_failure_mode_gate_config_from_dict(config_dict: dict) -> None:
    """Load failure-mode gate configuration from dictionary."""
    global _failure_mode_gate_config
    _failure_mode_gate_config = FailureModeGateConfig(**(config_dict or {}))

