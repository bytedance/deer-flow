from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .config import StrictModel
from .io import load_json

OFFICIAL_SCENARIOS = {
    "confirmation_help",
    "access_help",
    "confidence_control",
    "noisy_signal_control",
}


class SelectionConfig(StrictModel):
    eligible_question_types: list[Literal["knowledge-update", "temporal-reasoning"]]
    excluded_pilot_ids: list[str]
    exclude_abstention_suffix: str
    answer_min_chars: int = Field(ge=0)
    answer_max_chars: int = Field(ge=1)
    answer_excluded_substrings: list[str]
    evidence_min_chars: int = Field(ge=0)
    evidence_max_chars: int = Field(ge=1)
    take_per_question_type: int = Field(ge=1)
    cases_per_type_per_scenario: int = Field(ge=1)


class OfficialManifest(StrictModel):
    schema_version: Literal[1]
    protocol_id: str
    selection: SelectionConfig
    scenario_order: list[str]
    loss_ranks: list[int]
    scenarios: dict[str, list[str]]

    @field_validator("loss_ranks")
    @classmethod
    def validate_loss_ranks(cls, value: list[int]) -> list[int]:
        if len(value) != 10 or any(rank < 1 or rank > 10 for rank in value):
            raise ValueError("official loss_ranks must contain ten values between 1 and 10")
        return value

    @model_validator(mode="after")
    def validate_scenarios(self) -> OfficialManifest:
        if set(self.scenarios) != OFFICIAL_SCENARIOS:
            raise ValueError("official manifest must define the four registered scenarios")
        if len(self.scenario_order) != len(set(self.scenario_order)) or set(self.scenario_order) != OFFICIAL_SCENARIOS:
            raise ValueError("official scenario_order must list each registered scenario exactly once")
        all_ids: list[str] = []
        for scenario, question_ids in self.scenarios.items():
            if len(question_ids) != 10:
                raise ValueError(f"scenario {scenario!r} must contain ten question IDs")
            all_ids.extend(question_ids)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("official question IDs must be unique")
        return self


class SyntheticCase(StrictModel):
    case_id: str
    support_fact: str
    question: str
    answer: str
    loss_rank: int = Field(ge=1, le=10)


class SyntheticManifest(StrictModel):
    schema_version: Literal[1]
    protocol_id: str
    scenario: Literal["correction_reserve"]
    cases: list[SyntheticCase]

    @field_validator("cases")
    @classmethod
    def validate_cases(cls, value: list[SyntheticCase]) -> list[SyntheticCase]:
        if len(value) != 5:
            raise ValueError("synthetic correction manifest must contain five cases")
        case_ids = [case.case_id for case in value]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("synthetic case IDs must be unique")
        return value


def load_official_manifest(path: Path) -> OfficialManifest:
    return OfficialManifest.model_validate(load_json(path))


def load_synthetic_manifest(path: Path) -> SyntheticManifest:
    return SyntheticManifest.model_validate(load_json(path))
