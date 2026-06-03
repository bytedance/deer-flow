from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProbeRef(BaseModel):
    point_id: str
    point_name: str
    point_type: str
    owner_device_id: str | None = None
    owner_device_name: str | None = None
    bearing_id: str | None = None
    bearing_name: str | None = None
    bearing_direction: str | None = None
    bearing_types: list[str] = Field(default_factory=list)
    shaft_id: str | None = None
    h_alarm: float | None = None
    hh_alarm: float | None = None
    unit_type: int | None = None
    type_num: int | None = None


class BearingRef(BaseModel):
    bearing_id: str
    bearing_name: str
    owner_device_id: str | None = None
    owner_device_name: str | None = None
    direction: str | None = None
    bearing_types: list[str] = Field(default_factory=list)
    shaft_id: str | None = None
    probes: list[ProbeRef] = Field(default_factory=list)


class DeviceContext(BaseModel):
    device_id: str
    device_name: str | None = None
    device_type: str
    process_type: str | None = None
    device_structure: str | None = None
    child_device_summary: list[str] = Field(default_factory=list)
    child_device_tree: list[dict[str, Any]] = Field(default_factory=list)
    probes: list[ProbeRef] = Field(default_factory=list)
    bearings: list[BearingRef] = Field(default_factory=list)
    process_points: list[ProbeRef] = Field(default_factory=list)

    probe_index: dict[str, ProbeRef] = Field(default_factory=dict)
    bearing_index: dict[str, BearingRef] = Field(default_factory=dict)
    shaft_probe_map: dict[str, list[str]] = Field(default_factory=dict)
    bearing_probe_map: dict[str, list[str]] = Field(default_factory=dict)
    process_point_map: dict[str, list[str]] = Field(default_factory=dict)
    rotor_device_ids: list[str] = Field(default_factory=list)
    rotor_device_type_map: dict[str, str] = Field(default_factory=dict)  # device_id -> LLM-inferred type


class TrendEvidenceItem(BaseModel):
    component_id: str
    feature: str
    current: float | None = None
    mean: float | None = None
    std: float | None = None
    alarm_status: str | None = None
    trend_class: str | None = None
    change_rate_grade: str | None = None
    dominant_pattern: str | None = None
    overall_direction: str | None = None
    changepoint_count: int = 0
    changepoint_types: list[str] = Field(default_factory=list)
    changepoint_severity: str | None = None
    spike_detected: bool = False
    over_threshold_ratio: float | None = None
    segment_count: int = 0
    narrative_summary: str | None = None
    raw_feature_stats: dict[str, Any] = Field(default_factory=dict)


class TrendEvidence(BaseModel):
    start_time: str
    end_time: str
    items: list[TrendEvidenceItem] = Field(default_factory=list)
    raw_result: dict[str, Any] = Field(default_factory=dict)


class WaveformEvidenceItem(BaseModel):
    component_id: str
    time_ms: str
    dominant_frequency_hz: float | None = None
    amp_1x_ratio: float | None = None
    harmonic_count: int = 0
    clipping_detected: bool = False
    shock_detected: bool = False
    impact_count: int = 0
    spectral_findings: list[str] = Field(default_factory=list)
    waveform_findings: list[str] = Field(default_factory=list)
    suspected_faults: list[str] = Field(default_factory=list)
    raw_feature_details: dict[str, Any] = Field(default_factory=dict)


class WaveformEvidence(BaseModel):
    items: list[WaveformEvidenceItem] = Field(default_factory=list)
    raw_results: list[dict[str, Any]] = Field(default_factory=list)


class OrbitEvidenceItem(BaseModel):
    bearing_id: str
    time_ms: str
    one_x_dominant: bool = False
    two_x_significant: bool = False
    one_x_precession_direction: str | None = None
    one_x_axis_ratio: float | None = None
    repetition_score: float | None = None
    flattening_score: float | None = None
    self_intersection_count: int = 0
    shape_tags: list[str] = Field(default_factory=list)
    one_x_tags: list[str] = Field(default_factory=list)
    two_x_tags: list[str] = Field(default_factory=list)
    raw_feature_details: dict[str, Any] = Field(default_factory=dict)


class OrbitEvidence(BaseModel):
    items: list[OrbitEvidenceItem] = Field(default_factory=list)
    raw_results: list[dict[str, Any]] = Field(default_factory=list)


class CandidateFault(BaseModel):
    rule_id: str = ""
    fault_type: str
    fault_subtype: str
    score: float
    matched_conditions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class FinalFault(BaseModel):
    fault_type: str
    fault_subtype: str
    confidence: Literal["high", "medium", "low"]
    score: float


class DiagnosisResult(BaseModel):
    device_id: str
    sub_device_id: str
    time_ms: str
    stage: Literal["running"] = "running"
    fault_type: str
    fault_subtype: str
    confidence: Literal["high", "medium", "low"]
    score: float
    final_faults: list[FinalFault] = Field(default_factory=list)
    evidence_summary: list[str] = Field(default_factory=list)
    running_actions: list[str] = Field(default_factory=list)
    maintenance_actions: list[str] = Field(default_factory=list)
    alternative_faults: list[CandidateFault] = Field(default_factory=list)
    primary_rule_detail: CandidateFault | None = None
    process_signal_summary: dict[str, Any] = Field(default_factory=dict)
    rule_optimization_conclusion: list[str] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)
