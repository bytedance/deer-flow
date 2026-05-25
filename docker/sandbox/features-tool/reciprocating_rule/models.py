"""Reciprocating machine diagnosis – data models.

Equivalent to Java ChannelFact, KeyFact, MacFact, and diagnosis result VOs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import (
    HL_A,
    HL_NAMES,
    POSITION_SEG_NUM,
    SS_NAMES,
    SS_NORMAL,
    SS_UNKNOWN,
)


@dataclass
class Channel:
    """Single measurement-point channel (≈ Java ChannelFact)."""

    # ── Configuration (from config API) ──
    name: str
    gpid: str
    position_type: str
    seg_num: int
    seg_feature: str
    main_feature: str
    alarm_model: str
    is_alarm: bool
    is_def_alarm: bool
    thresholds: dict[str, float] = field(default_factory=dict)
    seg_thresholds: dict[str, list[float]] = field(default_factory=dict)
    hysteresis: float = 0.0
    key_id: str = ""  # keyId from devicePoint.configInfo (for JSZD per-key lookup)

    # ── Runtime data (injected from data API) ──
    main_value: float = 0.0
    seg_values: list[float] = field(default_factory=list)
    signal_state: int = 0  # 0 = ok, -1 = error

    # ── Diagnosis output (written by rule engine) ──
    health_all: int = HL_A
    health_segs: dict[str, int] = field(default_factory=dict)
    alarm_level: int = 30  # AL_NORMAL

    @property
    def seg_alarm_enable(self) -> list[str]:
        """Return the list of enabled segment alarm names for this position type."""
        from .config import SEG_ALARM_ENABLE
        return SEG_ALARM_ENABLE.get(self.position_type, [])

    def health_name(self) -> str:
        return HL_NAMES.get(self.health_all, "?")


@dataclass
class Key:
    """Keyphasor / cylinder (≈ Java KeyFact)."""

    id: int
    name: str
    start_phase: int = 0
    real_rev: float = 1.0
    component_id: str = ""

    # ── Runtime data ──
    speed: float = 0.0
    ss_state: int = SS_UNKNOWN

    # ── Sub-objects ──
    channels: list[Channel] = field(default_factory=list)

    # ── Diagnosis output ──
    diag_states: dict[str, int] = field(default_factory=dict)
    diag_details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ss_name(self) -> str:
        return SS_NAMES.get(self.ss_state, "UNKNOWN")

    def channels_by_type(self, position_type: str) -> list[Channel]:
        return [ch for ch in self.channels if ch.position_type == position_type]

    def channel_by_type(self, position_type: str) -> Channel | None:
        for ch in self.channels:
            if ch.position_type == position_type:
                return ch
        return None


@dataclass
class Machine:
    """Machine / unit (≈ Java MacFact)."""

    id: str
    name: str
    low_run_speed: float = 100.0
    hysteresis_speed: float = 10.0
    jitter: float = 10.0

    # ── Sub-objects ──
    keys: list[Key] = field(default_factory=list)
    jszd_channels: list[Channel] = field(default_factory=list)

    # ── Diagnosis output ──
    diag_states: dict[str, int] = field(default_factory=dict)
    diag_details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChannelResult:
    """Diagnosis output for a single channel."""

    name: str
    position_type: str
    health: str
    health_value: int
    main_feature: str
    main_value: float
    seg_health: dict[str, str]  # only abnormal segments
    thresholds: dict[str, float] = field(default_factory=dict)  # hh, h, ll, l
    seg_thresholds: dict[str, list[float]] = field(default_factory=dict)  # per-seg hh/h/ll/l

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position_type": self.position_type,
            "health": self.health,
            "health_value": self.health_value,
            "main_feature": self.main_feature,
            "main_value": self.main_value,
            "seg_health": self.seg_health,
            "thresholds": self.thresholds,
            "seg_thresholds": self.seg_thresholds,
        }


@dataclass
class DiagnosisItem:
    """A single fault diagnosis result."""

    code: str
    level: str
    level_value: int
    name: str
    desc: str
    recommend: str
    component: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "level_value": self.level_value,
            "name": self.name,
            "desc": self.desc,
            "recommend": self.recommend,
            "component": self.component,
        }


@dataclass
class DiagnosisResult:
    """Complete diagnosis result for a single timestamp."""

    timestamp: int
    machine_id: str
    machine_name: str
    speed: float
    ss_state: str

    channels: list[ChannelResult] = field(default_factory=list)
    cylinder_diagnosis: list[DiagnosisItem] = field(default_factory=list)
    machine_diagnosis: list[DiagnosisItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "machine_id": self.machine_id,
            "machine_name": self.machine_name,
            "speed": self.speed,
            "ss_state": self.ss_state,
            "channels": [ch.to_dict() for ch in self.channels],
            "cylinder_diagnosis": [d.to_dict() for d in self.cylinder_diagnosis],
            "machine_diagnosis": [d.to_dict() for d in self.machine_diagnosis],
            "warnings": self.warnings,
        }
