from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PumpPoint:
    point_id: str
    name: str
    point_kind: str
    endpoint_series: str | None = None
    thresholds: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PumpTargetContext:
    machine_id: str
    component_id: str
    target_name: str
    target_kind: str
    points: list[PumpPoint]
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "component_id": self.component_id,
            "target_name": self.target_name,
            "target_kind": self.target_kind,
            "points": [
                {
                    "point_id": point.point_id,
                    "name": point.name,
                    "point_kind": point.point_kind,
                    "endpoint_series": point.endpoint_series,
                    "thresholds": point.thresholds,
                    "config": point.config,
                }
                for point in self.points
            ],
            "warnings": list(self.warnings),
        }


@dataclass
class PumpDiagnosisResult:
    machine_id: str
    component_id: str
    diagnosis_time: str
    diagnosis_window: dict[str, str]
    target_info: dict[str, Any]
    base_freq: float | None
    health_findings: list[dict[str, Any]]
    malfunction_findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    sampled_waveforms: list[dict[str, Any]]
    warnings: list[str]

    def model_dump(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "component_id": self.component_id,
            "diagnosis_time": self.diagnosis_time,
            "diagnosis_window": self.diagnosis_window,
            "target_info": self.target_info,
            "base_freq": self.base_freq,
            "health_findings": self.health_findings,
            "malfunction_findings": self.malfunction_findings,
            "evidence": self.evidence,
            "sampled_waveforms": self.sampled_waveforms,
            "warnings": self.warnings,
        }
